from __future__ import annotations

import json
import logging
from pathlib import Path
import shlex
import shutil
import subprocess
import time
from difflib import unified_diff

from project_loader import entrypoint_detect, file_discover, import_graph_builder
from analyze import ast_parser, hotspot_detector
from analyze.interfunction_calls import build_function_graph
from context_builder import prompt_packager
from candidates.candidate_evaluation import evaluate_candidates, run_project_tests
from candidates.final_candidate import final_candidate
from config import RuntimeConfig, get_config, init_config
from llm.llmagent import generate_candidates, generate_combined_candidates
import recovery
import state_storage as storage
from orchestrator.loop import optimize_regions
from orchestrator.region import RegionProposal
from orchestrator.runner_base import OptimizationState
# from orchestrator.runners import DynamicSliceRunner, StaticComplexitySliceRunner

logger = logging.getLogger(__name__)


def _ensure_runtime_dirs(runtime_config: RuntimeConfig) -> None:
    runtime_config.local_dir.mkdir(parents=True, exist_ok=True)
    runtime_config.optimized_dir.mkdir(parents=True, exist_ok=True)


def _prepare_working_project(runtime_config: RuntimeConfig) -> Path:
    if not runtime_config.optimized_run_dir.exists():
        shutil.copytree(
            runtime_config.target_dir,
            runtime_config.optimized_run_dir,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("optimized", "state", "_local", "__pycache__"),
        )
    return runtime_config.optimized_run_dir


def _build_import_graph(file_paths: list[Path]) -> dict[str, list[dict]]:
    all_imports: dict[str, list[dict]] = {}

    for file_path in file_paths:
        file_key = str(file_path.resolve())
        if file_key in all_imports:
            raise ValueError(f"Duplicate import-graph key detected for {file_key}")
        all_imports[file_key] = import_graph_builder.build_import_graph(file_path)

    return all_imports


def _discover_files(
    runtime_config: RuntimeConfig,
    state_store: storage.StateStore,
    recovered_data: dict[str, object],
) -> list[Path]:
    recovered_files = recovered_data.get(storage.FILE_LIST_STAGE)
    if recovered_files is not None:
        return [Path(file_path) for file_path in recovered_files]

    file_paths = file_discover.walk_through(runtime_config.target_dir)
    storage.save_file_list(state_store, [str(path) for path in file_paths])
    return file_paths


def _discover_imports(
    state_store: storage.StateStore,
    file_paths: list[Path],
    recovered_data: dict[str, object],
) -> dict[str, list[dict]]:
    recovered_imports = recovered_data.get(storage.IMPORT_GRAPH_STAGE)
    if recovered_imports is not None:
        return recovered_imports  # type: ignore[return-value]

    import_graph = _build_import_graph(file_paths)
    storage.save_import_graph(state_store, import_graph)
    return import_graph


def _discover_entry_points(
    runtime_config: RuntimeConfig,
    state_store: storage.StateStore,
    import_graph: dict[str, list[dict]],
    file_paths: list[Path],
    recovered_data: dict[str, object],
) -> list[Path]:
    recovered_roots = recovered_data.get(storage.ENTRY_POINTS_STAGE)
    if recovered_roots is not None:
        return [Path(root_path) for root_path in recovered_roots]

    roots = entrypoint_detect.find_entry_points(
        runtime_config.target_dir,
        import_graph,
        file_paths,
    )
    storage.save_entry_points(state_store, [str(path) for path in roots])
    return roots


def _discover_asts(
    state_store: storage.StateStore,
    file_paths: list[Path],
    recovered_data: dict[str, object],
) -> dict[str, object]:
    recovered_asts = recovered_data.get(storage.AST_STAGE)
    if recovered_asts is not None:
        return recovered_asts

    all_asts = {}
    for file_path in file_paths:
        all_asts[str(file_path)] = ast_parser.block_generator(file_path)

    storage.save_ast_graphs(state_store, all_asts)
    return all_asts


def _run_benchmark_commands(project_dir: Path, benchmark_targets: list[str]) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for target in benchmark_targets:
        command = shlex.split(target)
        started_at = time.perf_counter()
        completed = subprocess.run(
            command,
            cwd=project_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        results.append(
            {
                "command": command,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "duration_seconds": time.perf_counter() - started_at,
            }
        )
    return results


def _build_diff_report(target_dir: Path, optimized_project_dir: Path, changed_files: list[str]) -> str:
    patches: list[str] = []
    for relative_file in changed_files:
        original_path = target_dir / relative_file
        optimized_path = optimized_project_dir / relative_file
        original_text = original_path.read_text(encoding="UTF-8").splitlines(keepends=True)
        optimized_text = optimized_path.read_text(encoding="UTF-8").splitlines(keepends=True)
        patches.extend(
            unified_diff(
                original_text,
                optimized_text,
                fromfile=str(original_path),
                tofile=str(optimized_path),
            )
        )
    return "".join(patches)


def _write_final_reports(
    runtime_config: RuntimeConfig,
    optimized_project_dir: Path,
    file_results: list[dict[str, object]],
    benchmark_results: list[dict[str, object]],
) -> None:
    changed_files = [
        str(result["relative_path"])
        for result in file_results
        if result.get("changed")
    ]
    changed_file_results = [result for result in file_results if result.get("changed")]
    evidence_backed_changes = [result for result in changed_file_results if result.get("meets_minimum_evidence")]
    report_confidence = "safe but unproven"
    if evidence_backed_changes and benchmark_results:
        report_confidence = "measurably improved"
    elif evidence_backed_changes:
        report_confidence = "complexity-reducing cleanup"
    diff_text = _build_diff_report(runtime_config.target_dir, optimized_project_dir, changed_files)
    (optimized_project_dir / "optimization_diff.patch").write_text(diff_text, encoding="UTF-8")
    (optimized_project_dir / "optimization_report.json").write_text(
        json.dumps(
            {
                "optimized_project_dir": str(optimized_project_dir),
                "confidence_label": report_confidence,
                "completed_with_evidence": bool(evidence_backed_changes),
                "changed_files": changed_files,
                "summary": {
                    "changed_file_count": len(changed_file_results),
                    "evidence_backed_change_count": len(evidence_backed_changes),
                    "measurable_improvement_count": sum(
                        1 for result in changed_file_results if result.get("confidence_label") == "measurably improved"
                    ),
                    "cleanup_only_count": sum(
                        1 for result in changed_file_results if result.get("outcome_label") == "behavior-preserving cleanup"
                    ),
                },
                "files": file_results,
                "benchmarks": benchmark_results or [{"skipped": True}],
            },
            indent=2,
        ),
        encoding="UTF-8",
    )


def _optimize_files(
    runtime_config: RuntimeConfig,
    file_paths: list[Path],
    all_asts: dict[str, object],
    region: RegionProposal | None = None,
) -> tuple[Path, list[dict[str, object]]]:
    optimized_project_dir = _prepare_working_project(runtime_config)
    file_results: list[dict[str, object]] = []

    for file_path in file_paths:
        relative_path = file_path.relative_to(runtime_config.target_dir)
        working_file_path = optimized_project_dir / relative_path
        print(f"[self-optimize] generating candidates for {working_file_path}")
        current_ast = ast_parser.block_generator(working_file_path)
        context = prompt_packager.build_context_file(region) if region else prompt_packager.build_context_file(working_file_path, "file_candidate", "file", current_ast)
        candidate_samples = generate_candidates(
            context=context,
            file_path=working_file_path,
            sample_count=runtime_config.candidate_sample_count,
            working_dir=optimized_project_dir,
            agent_count=runtime_config.agent_count,
            model=runtime_config.codex_model,
        )

        def _combine_candidates(baseline_source: str, passing_candidates: list[object]) -> list[str]:
            formatted_candidates = [
                {
                    "score": candidate.score,
                    "origin": candidate.origin,
                    "lineage": list(candidate.lineage),
                    "benchmark_seconds": candidate.benchmark_seconds,
                    "file_source": candidate.source,
                }
                for candidate in passing_candidates
            ]
            return generate_combined_candidates(
                context=context,
                file_path=working_file_path,
                baseline_source=baseline_source,
                passing_candidates=formatted_candidates,
                sample_count=1,
                working_dir=optimized_project_dir,
                agent_count=runtime_config.agent_count,
                model=runtime_config.codex_model,
            )

        evaluation = evaluate_candidates(
            candidate_samples,
            working_file_path,
            optimized_project_dir,
            runtime_config.test_targets,
            iteration_count=runtime_config.evaluation_rounds,
            sample_count=runtime_config.candidate_sample_count,
            benchmark_targets=runtime_config.benchmark_targets,
            survivor_count=runtime_config.survivor_count,
            combination_enabled=runtime_config.combination_enabled,
            combination_generator=_combine_candidates if runtime_config.combination_enabled else None,
            region=region,
        )
        print(f"[self-optimize] selected passing candidate for {working_file_path}")
        optimized_project_dir = final_candidate(
            evaluation.final_source,
            working_file_path,
            optimized_project_dir,
            optimized_project_dir,
        )
        original_source = file_path.read_text(encoding="UTF-8")
        file_results.append(
            {
                "relative_path": relative_path.as_posix(),
                "changed": evaluation.final_source != original_source,
                "original_score": evaluation.original_score,
                "round_summaries": [
                    {
                        "round_index": summary.round_index,
                        "passing_count": summary.passing_count,
                        "survivor_count": summary.survivor_count,
                        "selected_origin": summary.selected_origin,
                    }
                    for summary in evaluation.round_summaries
                ],
                "completed_with_evidence": evaluation.completed_with_evidence,
                "confidence_label": evaluation.confidence_label,
                "final_score": evaluation.final_record.score if evaluation.final_record is not None else None,
                "final_origin": evaluation.final_record.origin if evaluation.final_record is not None else "baseline",
                "lineage": list(evaluation.final_record.lineage) if evaluation.final_record is not None else ["baseline"],
                "mutation_kind": evaluation.final_record.mutation_kind if evaluation.final_record is not None else "baseline",
                "outcome_label": evaluation.final_record.outcome_label if evaluation.final_record is not None else "safe but unproven",
                "score_delta": (
                    evaluation.original_score - evaluation.final_record.score
                    if evaluation.final_record is not None
                    else 0
                ),
                "benchmark_seconds": evaluation.final_record.benchmark_seconds if evaluation.final_record is not None else None,
                "benchmark_delta": evaluation.final_record.benchmark_delta if evaluation.final_record is not None else None,
                "diff_size": evaluation.final_record.diff_size if evaluation.final_record is not None else 0,
                "meets_minimum_evidence": (
                    evaluation.final_record.meets_minimum_evidence
                    if evaluation.final_record is not None
                    else False
                ),
                "guard": [
                    {"outcome": result.outcome, "reasons": list(result.reasons), "dependencies": list(result.dependencies)}
                    for result in evaluation.guard_results
                ],
            }
        )

    return optimized_project_dir, file_results


def _finalize_project(
    runtime_config: RuntimeConfig,
    optimized_project_dir: Path,
    file_results: list[dict[str, object]],
) -> None:
    print(f"[self-optimize] running final tests in {optimized_project_dir}")
    if not run_project_tests(optimized_project_dir, runtime_config.test_targets):
        raise RuntimeError(f"Final project tests failed for {optimized_project_dir}")
    benchmark_results = _run_benchmark_commands(optimized_project_dir, runtime_config.benchmark_targets)
    _write_final_reports(runtime_config, optimized_project_dir, file_results, benchmark_results)
    print("[self-optimize] final verification complete")


def main(runtime_config: RuntimeConfig | None = None) -> int:
    runtime_config = runtime_config or get_config()
    init_config(runtime_config)
    _ensure_runtime_dirs(runtime_config)
    state_store = storage.build_state_store(runtime_config.state_dir, runtime_config.target_dir)
    state_store.write_manifest()
    logging.basicConfig(
        handlers=[logging.FileHandler(runtime_config.local_dir / "app.log", mode="w")],
        level=logging.INFO,
        format="%(asctime)s.%(msecs)03d %(levelname)s %(module)s - %(funcName)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    runtime_config.write_json()

    run_succeeded = False

    try:
        logger.info("Started")
        print(f"[self-optimize] starting run for {runtime_config.target_dir}")
        recovered_data: dict[str, object] = {}
        if runtime_config.recovery_token is not None:
            logger.info("Loading recovery state for %s", runtime_config.recovery_token)
            print(f"[self-optimize] loading recovery state {runtime_config.recovery_token}")
            recovered_data = recovery.load_recovery_bundle(
                state_store,
                runtime_config.recovery_token,
            )

        file_smoke = _discover_files(runtime_config, state_store, recovered_data)
        test_files = file_discover.find_test_files(runtime_config.target_dir)
        source_files = [
            file_path
            for file_path in file_smoke
            if not file_discover.is_test_file(file_path, runtime_config.target_dir)
        ]
        print(
            f"[self-optimize] discovered {len(file_smoke)} python files "
            f"({len(source_files)} source, {len(test_files)} test)"
        )

        logger.info("Looping through imports")
        all_imports = _discover_imports(state_store, file_smoke, recovered_data)
        logger.info("Finished looping through import")

        logger.info("Starting Detection of Potential Entry Points")
        _discover_entry_points(
            runtime_config,
            state_store,
            all_imports,
            file_smoke,
            recovered_data,
        )
        logger.info("Ending Detection of Potential Entry Points")

        logger.info("Starting AST Parser")
        all_asts = _discover_asts(state_store, file_smoke, recovered_data)

        file_name, _score = hotspot_detector.find_max_hotspots(all_asts)
        logger.info("Prepared optimization context for %s", file_name)
        prompt_packager.build_context_file(
            file_name,
            "generate_complexity_metrics",
            "function",
            all_asts[str(file_name)],
        )

        function_graph = build_function_graph(runtime_config.target_dir, source_files)
        state = OptimizationState(runtime_config.target_dir, source_files, all_asts, function_graph, runtime_config.test_targets)
        # {"dynamic": DynamicSliceRunner(), "static": StaticComplexitySliceRunner()}
        runners = None
        selected_runners = [runners[name] for name in runtime_config.runner_plan if name in runners]
        file_results: list[dict[str, object]] = []
        optimized_project_dir = _prepare_working_project(runtime_config)

        def optimize_region(region: RegionProposal) -> bool:
            nonlocal optimized_project_dir
            optimized_project_dir, results = _optimize_files(runtime_config, [region.criterion.file_path], all_asts, region)
            file_results.extend(results)
            return bool(results and results[-1].get("meets_minimum_evidence"))

        recovery_round = recovered_data.get(storage.ORCHESTRATOR_ROUND_STAGE)
        optimize_regions(
            state,
            selected_runners,
            optimize_region,
            lambda round_state: storage.save_orchestrator_round(state_store, round_state),
            runtime_config.max_expansions,
            runtime_config.swap_after_stalled_rounds,
            recovery_round if isinstance(recovery_round, dict) else None,
        )
        _finalize_project(runtime_config, optimized_project_dir, file_results)
        print(f"[self-optimize] wrote optimized project to {optimized_project_dir}")

        logger.info("Ended")
        run_succeeded = True
        return 0
    except Exception:
        logger.exception("Optimizer run failed")
        raise
    finally:
        if run_succeeded:
            runtime_config.cleanup_json()


if __name__ == "__main__":
    raise SystemExit("Run `uv run self-optimize --target <path>`.")
