from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher, ndiff
import ast
import importlib.util
import logging
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Callable, Iterable

from orchestrator.region import Criterion, RegionProposal


@dataclass(frozen=True, slots=True)
class ExternalDependency:
    name: str
    kind: str
    reason: str


@dataclass(frozen=True, slots=True)
class GuardResult:
    accepted: bool
    outcome: str
    reasons: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()


def _within_span(start: int, end: int, spans: tuple[tuple[int, int], ...], insertion: bool = False) -> bool:
    return any(span_start <= start and end <= span_end if not insertion else span_start <= start <= span_end for span_start, span_end in spans)


def _module_declarations(source: str) -> dict[str, tuple[str, int, int]]:
    tree = ast.parse(source)
    declarations: dict[str, tuple[str, int, int]] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            declarations[node.name] = ("helper", node.lineno - 1, node.end_lineno or node.lineno)
        elif isinstance(node, ast.ClassDef):
            declarations[node.name] = ("class_member", node.lineno - 1, node.end_lineno or node.lineno)
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    declarations[f"{node.name}.{child.name}"] = ("class_member", child.lineno - 1, child.end_lineno or child.lineno)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    declarations[target.id] = ("global", node.lineno - 1, node.end_lineno or node.lineno)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                name = alias.asname or (alias.name if isinstance(node, ast.Import) else alias.name.split(".")[-1])
                declarations[name] = ("import", node.lineno - 1, node.end_lineno or node.lineno)
    return declarations


def _import_modules(source: str) -> dict[str, str]:
    modules: dict[str, str] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                modules[alias.asname or alias.name] = node.module
    return modules


def _target_references(source: str, symbol: str) -> set[str]:
    tree = ast.parse(source)
    target: ast.AST | None = None
    class_name, _, method_name = symbol.partition(".")
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == symbol:
            target = node
        elif isinstance(node, ast.ClassDef) and method_name and node.name == class_name:
            target = next((child for child in node.body if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == method_name), None)
    if target is None:
        return set()
    references = {node.id for node in ast.walk(target) if isinstance(node, ast.Name)}
    if method_name:
        references.update(f"{class_name}.{node.attr}" for node in ast.walk(target) if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in {"self", "cls"})
    return references


def _is_stdlib_import(name: str) -> bool:
    root = name.split(".", 1)[0]
    return root in sys.stdlib_module_names or importlib.util.find_spec(root) is not None and not (importlib.util.find_spec(root).origin or "").startswith(str(Path.cwd()))


def validate_region_candidate(
    original: str,
    candidate: str,
    region: RegionProposal | None,
    dependencies: Iterable[ExternalDependency] = (),
) -> GuardResult:
    if region is None:
        return GuardResult(True, "unrestricted")
    try:
        original_declarations = _module_declarations(original)
        candidate_declarations = _module_declarations(candidate)
        references = _target_references(candidate, region.criterion.symbol)
        imports = _import_modules(candidate)
    except SyntaxError as exc:
        return GuardResult(False, "rejected", (f"invalid syntax: {exc.msg}",))
    declared = {dependency.name: dependency for dependency in dependencies}
    new_declarations = {name: value for name, value in candidate_declarations.items() if name not in original_declarations}
    reasons: list[str] = []
    accepted_dependencies: set[str] = set()
    opcodes = SequenceMatcher(None, original.splitlines(), candidate.splitlines()).get_opcodes()
    for tag, old_start, old_end, new_start, new_end in opcodes:
        if tag == "equal" or _within_span(old_start, old_end, region.editable_spans, tag == "insert"):
            continue
        matching = [
            (name, declaration)
            for name, declaration in new_declarations.items()
            if declaration[1] <= new_start and new_end <= declaration[2]
        ]
        if len(matching) != 1:
            reasons.append(f"out-of-region {tag} at original lines {old_start + 1}-{old_end}")
            continue
        name, (kind, _start, _end) = matching[0]
        dependency = declared.get(name)
        if dependency is None or dependency.kind != kind or not dependency.reason.strip():
            reasons.append(f"undeclared or unjustified {kind} dependency {name}")
        elif name not in references:
            reasons.append(f"dependency {name} is not referenced by {region.criterion.symbol}")
        elif kind == "import" and not _is_stdlib_import(imports.get(name, name)):
            reasons.append(f"dependency {name} is not a stdlib import")
        else:
            accepted_dependencies.add(name)
    for name, (kind, _start, _end) in new_declarations.items():
        dependency = declared.get(name)
        if dependency is None or dependency.kind != kind or not dependency.reason.strip():
            reasons.append(f"undeclared or unjustified {kind} dependency {name}")
        elif name not in references:
            reasons.append(f"dependency {name} is not referenced by {region.criterion.symbol}")
        elif kind == "import" and not _is_stdlib_import(imports.get(name, name)):
            reasons.append(f"dependency {name} is not a stdlib import")
        else:
            accepted_dependencies.add(name)
    for name, dependency in declared.items():
        if name not in accepted_dependencies:
            reasons.append(f"declared dependency {name} was not used by an allowed addition")
    if reasons:
        return GuardResult(False, "rejected", tuple(sorted(set(reasons))))
    outcome = "accepted_justified_dependency" if accepted_dependencies else "accepted_region_only"
    return GuardResult(True, outcome, dependencies=tuple(sorted(accepted_dependencies)))


def _changes_only_within_spans(original: str, candidate: str, spans: tuple[tuple[int, int], ...] | None) -> bool:
    if spans is None:
        return True
    region = RegionProposal(Criterion(Path("<legacy>"), "", 0, 0), spans)
    return validate_region_candidate(original, candidate, region).accepted

from analyze import ast_parser

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CommandResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float


@dataclass(slots=True)
class CandidateRecord:
    source: str
    score: int
    diff_size: int
    round_index: int
    origin: str
    lineage: tuple[str, ...]
    benchmark_seconds: float | None = None
    baseline_score: int = 0
    baseline_benchmark_seconds: float | None = None
    complexity_delta: int = 0
    benchmark_delta: float | None = None
    mutation_kind: str = "cleanup"
    outcome_label: str = "behavior-preserving cleanup"
    confidence_label: str = "safe but unproven"
    meets_minimum_evidence: bool = False
    external_dependencies: tuple[ExternalDependency, ...] = ()

    def sort_key(self) -> tuple[int, float, int]:
        benchmark_value = self.benchmark_delta if self.benchmark_delta is not None else float("inf")
        meaningful_rank = 0 if self.meets_minimum_evidence else 1
        cleanup_rank = 0 if self.mutation_kind == "complexity_reduction" else 1
        noop_rank = 1 if self.diff_size == 0 and not self.meets_minimum_evidence else 0
        return (
            meaningful_rank,
            cleanup_rank,
            self.score,
            benchmark_value,
            self.diff_size,
            noop_rank,
        )


@dataclass(slots=True)
class CandidateSeed:
    source: str
    origin: str
    lineage: tuple[str, ...]
    external_dependencies: tuple[ExternalDependency, ...] = ()


@dataclass(slots=True)
class RoundSummary:
    round_index: int
    passing_count: int
    survivor_count: int
    selected_origin: str | None


@dataclass(slots=True)
class EvaluationResult:
    final_source: str
    final_record: CandidateRecord | None
    round_summaries: list[RoundSummary] = field(default_factory=list)
    original_score: int = 0
    original_benchmark_seconds: float | None = None
    completed_with_evidence: bool = False
    confidence_label: str = "safe but unproven"
    guard_results: list[GuardResult] = field(default_factory=list)


def _build_test_commands(test_targets: list[str], project_dir: Path | None = None) -> list[list[str]]:
    if test_targets:
        return [shlex.split(target) for target in test_targets]
    command = [sys.executable, "-m", "unittest", "discover"]
    if project_dir is not None and (project_dir / "tests").is_dir():
        command.extend(["-s", "tests"])
    return [command]


def _run_project_commands(project_dir: Path, targets: list[str]) -> list[CommandResult]:
    commands = _build_test_commands(targets, project_dir)
    results: list[CommandResult] = []
    for command in commands:
        started_at = time.perf_counter()
        completed = subprocess.run(
            command,
            cwd=project_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        results.append(
            CommandResult(
                command=command,
                returncode=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                duration_seconds=time.perf_counter() - started_at,
            )
        )
    return results


def run_project_tests(project_dir: Path, test_targets: list[str]) -> bool:
    return all(result.returncode == 0 for result in _run_project_commands(project_dir, test_targets))


def run_project_benchmarks(project_dir: Path, benchmark_targets: list[str]) -> list[CommandResult]:
    if not benchmark_targets:
        return []
    return _run_project_commands(project_dir, benchmark_targets)


def _write_candidate_copy(
    source_project_dir: Path,
    file_name: Path,
    candidate_source: str,
    destination_dir: Path,
) -> Path:
    project_copy = destination_dir / source_project_dir.name
    shutil.copytree(
        source_project_dir,
        project_copy,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("optimized", "state", "_local", "__pycache__"),
    )
    relative_path = file_name.relative_to(source_project_dir)
    destination_file = project_copy / relative_path
    destination_file.write_text(candidate_source, encoding="UTF-8")
    return project_copy


def _score_blocks(blocks: tuple[list[dict[str, int | str]], list[dict[str, object]]]) -> int:
    functions, classes = blocks
    function_score = sum(
        int(function["max_conditionals"]) + int(function["max_nesting"])
        for function in functions
    )
    class_score = sum(
        int(method["max_conditionals"]) + int(method["max_nesting"])
        for class_block in classes
        for method in class_block["class_methods"]
    )
    return function_score + class_score


def _score_source(source: str, filename: str) -> int:
    return _score_blocks(ast_parser.block_generator_from_source(source, filename=filename))


def _diff_size(original_source: str, candidate_source: str) -> int:
    return sum(
        1
        for line in ndiff(original_source.splitlines(), candidate_source.splitlines())
        if line.startswith("+ ") or line.startswith("- ")
    )


def _benchmark_total(benchmark_results: list[CommandResult]) -> float | None:
    if not benchmark_results:
        return None
    if any(result.returncode != 0 for result in benchmark_results):
        return None
    return sum(result.duration_seconds for result in benchmark_results)


def _benchmark_delta(
    baseline_seconds: float | None,
    candidate_seconds: float | None,
) -> float | None:
    if baseline_seconds is None or candidate_seconds is None:
        return None
    return candidate_seconds - baseline_seconds


def _classify_mutation_kind(
    complexity_delta: int,
    diff_size: int,
    benchmark_delta: float | None,
) -> str:
    if diff_size == 0:
        return "no_op"
    if complexity_delta > 0 or (benchmark_delta is not None and benchmark_delta < 0):
        return "complexity_reduction"
    if diff_size <= 2:
        return "near_no_op"
    return "cleanup"


def _meets_minimum_evidence(
    complexity_delta: int,
    benchmark_delta: float | None,
) -> bool:
    return complexity_delta > 0 or (benchmark_delta is not None and benchmark_delta < 0)


def _label_outcome(
    mutation_kind: str,
    complexity_delta: int,
    benchmark_delta: float | None,
) -> str:
    if complexity_delta > 0:
        return "complexity-reducing cleanup"
    if benchmark_delta is not None and benchmark_delta < 0:
        return "measurably improved"
    if mutation_kind in {"cleanup", "near_no_op"}:
        return "behavior-preserving cleanup"
    return "safe but unproven"


def _label_confidence(
    meets_minimum_evidence: bool,
    benchmark_delta: float | None,
) -> str:
    if meets_minimum_evidence and benchmark_delta is not None:
        return "measurably improved"
    if meets_minimum_evidence:
        return "complexity-reducing cleanup"
    return "safe but unproven"


def _select_best_candidate(
    candidates: list[CandidateRecord],
) -> CandidateRecord:
    return min(candidates, key=lambda candidate: (*candidate.sort_key(), candidate.origin, candidate.lineage))


def _dedupe_sources(sources: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for source in sources:
        if source in seen:
            continue
        seen.add(source)
        ordered.append(source)
    return ordered


def _dedupe_seeds(seeds: list[CandidateSeed]) -> list[CandidateSeed]:
    unique_sources = _dedupe_sources([seed.source for seed in seeds])
    return [
        next(seed for seed in seeds if seed.source == source)
        for source in unique_sources
    ]


def _candidate_seed(candidate: object, index: int) -> CandidateSeed:
    if isinstance(candidate, str):
        return CandidateSeed(candidate, "generated", (f"generated-{index}",))
    source = getattr(candidate, "file_source", None)
    if not isinstance(source, str):
        raise TypeError("Candidate must be source text or expose file_source.")
    dependencies = tuple(
        ExternalDependency(str(item.get("name", "")), str(item.get("kind", "")), str(item.get("reason", "")))
        for item in getattr(candidate, "external_dependencies", [])
        if isinstance(item, dict)
    )
    return CandidateSeed(source, "generated", (f"generated-{index}",), dependencies)


def _evaluate_seed(
    seed: CandidateSeed,
    candidate_index: int,
    file_name: Path,
    target_dir: Path,
    test_targets: list[str],
    benchmark_targets: list[str],
    baseline_source: str,
    baseline_score: int,
    baseline_benchmark_seconds: float | None,
    round_index: int,
) -> CandidateRecord | None:
    with tempfile.TemporaryDirectory() as temp_dir_name:
        project_dir = _write_candidate_copy(
            target_dir,
            file_name,
            seed.source,
            Path(temp_dir_name),
        )
        if not run_project_tests(project_dir, test_targets):
            return None
        try:
            candidate_score = _score_source(seed.source, str(file_name))
        except SyntaxError as exc:
            logger.warning(
                "Skipping candidate %s for %s: failed to parse candidate source (%s)",
                candidate_index,
                file_name,
                exc,
            )
            return None
        benchmark_seconds = _benchmark_total(run_project_benchmarks(project_dir, benchmark_targets))
        complexity_delta = baseline_score - candidate_score
        benchmark_delta = _benchmark_delta(baseline_benchmark_seconds, benchmark_seconds)
        mutation_kind = _classify_mutation_kind(complexity_delta, _diff_size(baseline_source, seed.source), benchmark_delta)
        meets_minimum_evidence = _meets_minimum_evidence(complexity_delta, benchmark_delta)
        return CandidateRecord(
            source=seed.source,
            score=candidate_score,
            diff_size=_diff_size(baseline_source, seed.source),
            round_index=round_index,
            origin=seed.origin,
            lineage=seed.lineage,
            benchmark_seconds=benchmark_seconds,
            baseline_score=baseline_score,
            baseline_benchmark_seconds=baseline_benchmark_seconds,
            complexity_delta=complexity_delta,
            benchmark_delta=benchmark_delta,
            mutation_kind=mutation_kind,
            outcome_label=_label_outcome(mutation_kind, complexity_delta, benchmark_delta),
            confidence_label=_label_confidence(meets_minimum_evidence, benchmark_delta),
            meets_minimum_evidence=meets_minimum_evidence,
            external_dependencies=seed.external_dependencies,
        )


def evaluate_candidates(
    candidates: list[object],
    file_name: Path,
    target_dir: Path,
    test_targets: list[str],
    iteration_count: int = 1,
    sample_count: int = 10,
    benchmark_targets: list[str] | None = None,
    survivor_count: int = 3,
    combination_enabled: bool = False,
    combination_generator: Callable[[str, list[CandidateRecord]], list[object]] | None = None,
    region: RegionProposal | None = None,
    editable_spans: tuple[tuple[int, int], ...] | None = None,
) -> EvaluationResult:
    original_source = file_name.read_text(encoding="UTF-8")
    if region is None and editable_spans is not None:
        region = RegionProposal(Criterion(file_name, "", 0, 0), editable_spans)
    seeds = [_candidate_seed(candidate, index) for index, candidate in enumerate(candidates)]
    guard_results = [validate_region_candidate(original_source, seed.source, region, seed.external_dependencies) for seed in seeds]
    for result in guard_results:
        if not result.accepted:
            logger.info("Rejected candidate for %s: %s", file_name, "; ".join(result.reasons))
    seeds = [seed for seed, result in zip(seeds, guard_results) if result.accepted]
    original_score = _score_source(original_source, str(file_name))
    benchmark_targets = benchmark_targets or []
    original_benchmark_seconds = _benchmark_total(run_project_benchmarks(target_dir, benchmark_targets))

    if not seeds:
        logger.info("Optimizer did not find a better candidate for %s: no region-valid candidates", file_name)
        return EvaluationResult(
            final_source=original_source,
            final_record=None,
            original_score=original_score,
            original_benchmark_seconds=original_benchmark_seconds,
            completed_with_evidence=original_benchmark_seconds is not None,
            confidence_label="safe but unproven",
            guard_results=guard_results,
        )

    retained_record = CandidateRecord(
        source=original_source,
        score=original_score,
        diff_size=0,
        round_index=-1,
        origin="baseline",
        lineage=("baseline",),
        benchmark_seconds=original_benchmark_seconds,
        baseline_score=original_score,
        baseline_benchmark_seconds=original_benchmark_seconds,
        complexity_delta=0,
        benchmark_delta=0.0 if original_benchmark_seconds is not None else None,
        mutation_kind="baseline",
        outcome_label="safe but unproven",
        confidence_label="safe but unproven",
        meets_minimum_evidence=False,
    )
    current_candidates = _dedupe_seeds(
        [
            seed for seed in seeds
        ]
    )
    round_summaries: list[RoundSummary] = []

    for round_index in range(iteration_count):
        passing_candidates: list[CandidateRecord] = []
        baseline_source = retained_record.source
        logger.info(
            "Evaluating round %s for %s against retained score %s with %s input candidates",
            round_index + 1,
            file_name,
            retained_record.score,
            len(current_candidates[:sample_count]),
        )

        for candidate_index, candidate_seed in enumerate(current_candidates[:sample_count]):
            record = _evaluate_seed(
                candidate_seed,
                candidate_index,
                file_name,
                target_dir,
                test_targets,
                benchmark_targets,
                baseline_source,
                retained_record.score,
                retained_record.benchmark_seconds,
                round_index,
            )
            if record is not None:
                passing_candidates.append(record)

        if not passing_candidates:
            logger.info("Optimizer did not find a better candidate for %s: no passing candidates", file_name)
            round_summaries.append(RoundSummary(round_index, 0, 0, None))
            break

        survivors = sorted(
            passing_candidates,
            key=lambda candidate: (*candidate.sort_key(), candidate.origin, candidate.lineage),
        )[: max(1, survivor_count)]

        if combination_enabled and combination_generator is not None and round_index + 1 < iteration_count:
            try:
                combined_sources = combination_generator(baseline_source, survivors)
            except RuntimeError as exc:
                logger.warning("Candidate combination failed for %s in round %s: %s", file_name, round_index + 1, exc)
                combined_sources = []
            combined_seeds = _dedupe_seeds(
                [
                    CandidateSeed(
                        source=_candidate_seed(combined_source, combined_index).source,
                        origin="combined",
                        lineage=(
                            f"combined-{round_index}-{combined_index}",
                            "baseline",
                            *(candidate.lineage[0] for candidate in survivors[: max(1, survivor_count)]),
                        ),
                        external_dependencies=_candidate_seed(combined_source, combined_index).external_dependencies,
                    )
                    for combined_index, combined_source in enumerate(combined_sources)
                ]
            )
            combined_guard_results = [
                validate_region_candidate(original_source, seed.source, region, seed.external_dependencies)
                for seed in combined_seeds
            ]
            guard_results.extend(combined_guard_results)
            combined_seeds = [
                seed for seed, result in zip(combined_seeds, combined_guard_results) if result.accepted
            ]
            for combined_index, combined_seed in enumerate(combined_seeds):
                record = _evaluate_seed(
                    combined_seed,
                    combined_index,
                    file_name,
                    target_dir,
                    test_targets,
                    benchmark_targets,
                    baseline_source,
                    retained_record.score,
                    retained_record.benchmark_seconds,
                    round_index,
                )
                if record is not None:
                    survivors.append(record)
            survivors = sorted(
                survivors,
                key=lambda candidate: (*candidate.sort_key(), candidate.origin, candidate.lineage),
            )[: max(1, survivor_count)]

        winning_candidate = _select_best_candidate(survivors)
        if winning_candidate.score <= retained_record.score:
            retained_record = winning_candidate
            logger.info(
                "Selected candidate for %s in round %s with score %s, benchmark %s, diff size %s, origin %s",
                file_name,
                round_index + 1,
                winning_candidate.score,
                winning_candidate.benchmark_seconds,
                winning_candidate.diff_size,
                winning_candidate.origin,
            )
        else:
            logger.info(
                "Optimizer did not find a better candidate for %s in round %s: best score %s worse than retained score %s",
                file_name,
                round_index + 1,
                winning_candidate.score,
                retained_record.score,
            )

        round_summaries.append(
            RoundSummary(
                round_index=round_index,
                passing_count=len(passing_candidates),
                survivor_count=len(survivors),
                selected_origin=retained_record.origin,
            )
        )

        if not combination_enabled or combination_generator is None:
            break
        current_candidates = _dedupe_seeds(
            [
                CandidateSeed(
                    source=candidate.source,
                    origin=candidate.origin,
                    lineage=candidate.lineage,
                    external_dependencies=candidate.external_dependencies,
                )
                for candidate in survivors
            ]
        )

    if retained_record.source == original_source:
        logger.info("Optimizer did not find a better candidate for %s: falling back to original source", file_name)
        final_record = None
    else:
        final_record = retained_record

    return EvaluationResult(
        final_source=retained_record.source,
        final_record=final_record,
        round_summaries=round_summaries,
        original_score=original_score,
        original_benchmark_seconds=original_benchmark_seconds,
        completed_with_evidence=(
            final_record is not None and final_record.meets_minimum_evidence
        ),
        confidence_label=final_record.confidence_label if final_record is not None else "safe but unproven",
        guard_results=guard_results,
    )


def candidate_eval(
    candidates: list[str],
    file_name: Path,
    target_dir: Path,
    test_targets: list[str],
    iteration_count: int = 1,
    sample_count: int = 10,
    benchmark_targets: list[str] | None = None,
    survivor_count: int = 3,
    combination_enabled: bool = False,
    combination_generator: Callable[[str, list[CandidateRecord]], list[str]] | None = None,
) -> str:
    """Return the best passing file candidate for the requested file."""
    return evaluate_candidates(
        candidates,
        file_name,
        target_dir,
        test_targets,
        iteration_count=iteration_count,
        sample_count=sample_count,
        benchmark_targets=benchmark_targets,
        survivor_count=survivor_count,
        combination_enabled=combination_enabled,
        combination_generator=combination_generator,
    ).final_source
