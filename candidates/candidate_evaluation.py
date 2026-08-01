from __future__ import annotations

from dataclasses import dataclass, field
from difflib import ndiff
import logging
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Callable


def _changes_only_within_spans(original: str, candidate: str, spans: tuple[tuple[int, int], ...] | None) -> bool:
    if spans is None:
        return True
    original_lines = original.splitlines()
    candidate_lines = candidate.splitlines()
    if len(original_lines) != len(candidate_lines):
        return False
    allowed = {line for start, end in spans for line in range(start, end)}
    return all(before == after or index in allowed for index, (before, after) in enumerate(zip(original_lines, candidate_lines)))

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
        )


def evaluate_candidates(
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
    editable_spans: tuple[tuple[int, int], ...] | None = None,
) -> EvaluationResult:
    original_source = file_name.read_text(encoding="UTF-8")
    candidates = [candidate for candidate in candidates if _changes_only_within_spans(original_source, candidate, editable_spans)]
    original_score = _score_source(original_source, str(file_name))
    benchmark_targets = benchmark_targets or []
    original_benchmark_seconds = _benchmark_total(run_project_benchmarks(target_dir, benchmark_targets))

    if not candidates:
        logger.info("Optimizer did not find a better candidate for %s: no generated candidates", file_name)
        return EvaluationResult(
            final_source=original_source,
            final_record=None,
            original_score=original_score,
            original_benchmark_seconds=original_benchmark_seconds,
            completed_with_evidence=original_benchmark_seconds is not None,
            confidence_label="safe but unproven",
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
            CandidateSeed(
                source=candidate_source,
                origin="generated",
                lineage=(f"generated-{candidate_index}",),
            )
            for candidate_index, candidate_source in enumerate(candidates)
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
                        source=combined_source,
                        origin="combined",
                        lineage=(
                            f"combined-{round_index}-{combined_index}",
                            "baseline",
                            *(candidate.lineage[0] for candidate in survivors[: max(1, survivor_count)]),
                        ),
                    )
                    for combined_index, combined_source in enumerate(combined_sources)
                ]
            )
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
