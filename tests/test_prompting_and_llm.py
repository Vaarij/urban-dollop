from __future__ import annotations

import hashlib
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

import config
from analyze import ast_parser
from candidates import candidate_evaluation
from candidates.candidate_evaluation import CandidateRecord, EvaluationResult
from context_builder import prompt_packager
from llm import llmagent
import main as optimize_main


def _write_file(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source).strip() + "\n", encoding="UTF-8")


class PromptPackagerTests(unittest.TestCase):
    def test_build_context_file_uses_runtime_config_and_generates_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            root_dir = Path(temp_dir_name).resolve()
            file_path = root_dir / "module.py"
            _write_file(
                file_path,
                """
                async def fetch(item_id: int, label="x", *, verbose: bool = False) -> str:
                    return str(item_id)

                class Runner:
                    @staticmethod
                    def build(size: int) -> int:
                        return size

                    @classmethod
                    def create(cls, name):
                        return cls()
                """,
            )
            runtime_config = config.build_runtime_config(root_dir, workspace_root=root_dir)
            runtime_config.prompt_task["task_id"] = "runtime-task"
            runtime_config.instructions["may_request_more_context"] = False
            config.init_config(runtime_config)

            context = prompt_packager.build_context_file(file_path, "file_candidate", "file", {"blocks": 1})

            self.assertEqual(context["task"]["task_id"], "runtime-task")
            self.assertFalse(context["instructions"]["may_request_more_context"])
            self.assertEqual(context["scope"]["source"], str(file_path.resolve()))
            self.assertEqual(
                context["target"]["source_hash"],
                hashlib.sha256(file_path.read_bytes()).hexdigest(),
            )
            self.assertEqual(context["target"]["ast_data"], {"blocks": 1})
            self.assertEqual(context["target"]["contracts"][0]["symbol"], "fetch")
            self.assertTrue(context["target"]["contracts"][0]["is_async"])
            self.assertEqual(
                context["target"]["contracts"][0]["parameters"],
                [
                    {
                        "name": "item_id",
                        "kind": "positional_or_keyword",
                        "annotation": "int",
                        "has_default": False,
                    },
                    {
                        "name": "label",
                        "kind": "positional_or_keyword",
                        "annotation": None,
                        "has_default": True,
                    },
                    {
                        "name": "verbose",
                        "kind": "keyword_only",
                        "annotation": "bool",
                        "has_default": True,
                    },
                ],
            )
            runner_contract = context["target"]["contracts"][1]
            self.assertEqual(runner_contract["symbol"], "Runner")
            self.assertEqual(runner_contract["methods"][0]["symbol"], "Runner.build")
            self.assertTrue(runner_contract["methods"][0]["is_staticmethod"])
            self.assertTrue(runner_contract["methods"][1]["is_classmethod"])

    def test_build_context_file_handles_missing_target_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            root_dir = Path(temp_dir_name).resolve()
            file_path = root_dir / "module.py"
            _write_file(file_path, "def present():\n    return 1\n")
            config.init_config(config.build_runtime_config(root_dir, workspace_root=root_dir))

            context = prompt_packager.build_context_file(file_path, "missing", "function", {"blocks": 1})

            self.assertEqual(context["target"]["contracts"], [])

    def test_build_context_file_hash_changes_with_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            root_dir = Path(temp_dir_name).resolve()
            file_path = root_dir / "module.py"
            _write_file(file_path, "def present():\n    return 1\n")
            config.init_config(config.build_runtime_config(root_dir, workspace_root=root_dir))

            first_hash = prompt_packager.build_context_file(file_path, "file_candidate", "file", {})["target"]["source_hash"]
            _write_file(file_path, "def present():\n    return 2\n")
            second_hash = prompt_packager.build_context_file(file_path, "file_candidate", "file", {})["target"]["source_hash"]

            self.assertNotEqual(first_hash, second_hash)


class LlmAgentTests(unittest.TestCase):
    def test_extract_json_payload_handles_fenced_and_unfenced_json(self) -> None:
        fenced = textwrap.dedent(
            """\
            ```json
            {"candidate_id": "a", "file_source": "print(1)", "reason": "ok"}
            ```
            """
        )
        unfenced = '{"candidate_id": "b", "file_source": "print(2)", "reason": "ok"}'

        self.assertEqual(llmagent._extract_json_payload(fenced).candidate_id, "a")
        self.assertEqual(llmagent._extract_json_payload(unfenced).candidate_id, "b")

    def test_extract_tokens_used_handles_json_events(self) -> None:
        raw_output = textwrap.dedent(
            """\
            {"event":"started"}
            {"event":"completed","usage":{"input_tokens":120,"output_tokens":80,"total_tokens":200}}
            """
        )

        self.assertEqual(llmagent._extract_tokens_used(raw_output), 200)

    def test_extract_tokens_used_handles_text_fallback_formats(self) -> None:
        self.assertEqual(llmagent._extract_tokens_used("Tokens used: 123\n"), 123)
        self.assertEqual(llmagent._extract_tokens_used("total_tokens=1,234\n"), 1234)
        self.assertEqual(llmagent._extract_tokens_used("tokens used\n456\n"), 456)

    def test_generate_candidates_preserves_order_and_logs_projection(self) -> None:
        results = {
            2: llmagent.CandidateJobResult(
                candidate_index=2,
                status="completed",
                payload=llmagent.CandidatePayload("c", "third", "ok"),
                tokens_used=None,
                duration_seconds=0.03,
            ),
            0: llmagent.CandidateJobResult(
                candidate_index=0,
                status="completed",
                payload=llmagent.CandidatePayload("a", "first", "ok"),
                tokens_used=11,
                duration_seconds=0.01,
            ),
            1: llmagent.CandidateJobResult(
                candidate_index=1,
                status="completed",
                payload=llmagent.CandidatePayload("b", "second", "ok"),
                tokens_used=13,
                duration_seconds=0.02,
            ),
        }

        def fake_run(spec, file_path, working_dir, model=None, codex_command=llmagent.DEFAULT_CODEX_COMMAND):
            return results[spec.candidate_index]

        with tempfile.TemporaryDirectory() as temp_dir_name:
            root_dir = Path(temp_dir_name).resolve()
            file_path = root_dir / "module.py"
            _write_file(file_path, "def present():\n    return 1\n")
            with mock.patch("llm.llmagent._run_candidate_job", side_effect=fake_run):
                with self.assertLogs("llm.llmagent", level="INFO") as logs:
                    candidates = llmagent.generate_candidates({}, file_path, 3, root_dir, agent_count=2)

        self.assertEqual([candidate.file_source for candidate in candidates], ["first", "second", "third"])
        joined = "\n".join(logs.output)
        self.assertIn("Projected candidate prompt volume", joined)
        self.assertIn("1 unknown", joined)

    def test_generate_candidates_allows_partial_failures(self) -> None:
        results = {
            0: llmagent.CandidateJobResult(
                candidate_index=0,
                status="failed",
                payload=None,
                tokens_used=None,
                duration_seconds=0.01,
                error="boom",
            ),
            1: llmagent.CandidateJobResult(
                candidate_index=1,
                status="completed",
                payload=llmagent.CandidatePayload("b", "second", "ok"),
                tokens_used=5,
                duration_seconds=0.02,
            ),
        }

        def fake_run(spec, file_path, working_dir, model=None, codex_command=llmagent.DEFAULT_CODEX_COMMAND):
            return results[spec.candidate_index]

        with tempfile.TemporaryDirectory() as temp_dir_name:
            root_dir = Path(temp_dir_name).resolve()
            file_path = root_dir / "module.py"
            _write_file(file_path, "def present():\n    return 1\n")
            with mock.patch("llm.llmagent._run_candidate_job", side_effect=fake_run):
                candidates = llmagent.generate_candidates({}, file_path, 2, root_dir, agent_count=2)

        self.assertEqual([candidate.file_source for candidate in candidates], ["second"])

    def test_generate_candidates_raises_summary_error_when_all_jobs_fail(self) -> None:
        def fake_run(spec, file_path, working_dir, model=None, codex_command=llmagent.DEFAULT_CODEX_COMMAND):
            return llmagent.CandidateJobResult(
                candidate_index=spec.candidate_index,
                status="failed",
                payload=None,
                tokens_used=None,
                duration_seconds=0.01,
                error=f"failed-{spec.candidate_index}",
            )

        with tempfile.TemporaryDirectory() as temp_dir_name:
            root_dir = Path(temp_dir_name).resolve()
            file_path = root_dir / "module.py"
            _write_file(file_path, "def present():\n    return 1\n")
            with mock.patch("llm.llmagent._run_candidate_job", side_effect=fake_run):
                with self.assertLogs("llm.llmagent", level="WARNING") as logs:
                    with self.assertRaises(RuntimeError) as exc:
                        llmagent.generate_candidates({}, file_path, 2, root_dir, agent_count=2)

        self.assertIn("failed-0", str(exc.exception))
        self.assertIn("did not find a better candidate", "\n".join(logs.output))

    def test_generate_combined_candidates_builds_baseline_inclusive_prompt(self) -> None:
        captured_prompts: list[str] = []

        def fake_run(spec, file_path, working_dir, model=None, codex_command=llmagent.DEFAULT_CODEX_COMMAND):
            captured_prompts.append(spec.prompt)
            return llmagent.CandidateJobResult(
                candidate_index=spec.candidate_index,
                status="completed",
                payload=llmagent.CandidatePayload("combo", "combined", "ok"),
                tokens_used=7,
                duration_seconds=0.01,
            )

        with tempfile.TemporaryDirectory() as temp_dir_name:
            root_dir = Path(temp_dir_name).resolve()
            file_path = root_dir / "module.py"
            _write_file(file_path, "def present():\n    return 1\n")
            with mock.patch("llm.llmagent._run_candidate_job", side_effect=fake_run):
                result = llmagent.generate_combined_candidates(
                    {},
                    file_path,
                    "def present():\n    return 1\n",
                    [{"score": 3, "origin": "generated", "file_source": "def present():\n    return 2\n"}],
                    1,
                    root_dir,
                )

        self.assertEqual([candidate.file_source for candidate in result], ["combined"])
        self.assertIn("Current retained baseline", captured_prompts[0])
        self.assertIn('"score": 3', captured_prompts[0])
        self.assertIn("Avoid no-op combinations", captured_prompts[0])

    def test_run_candidate_job_requests_json_output(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["codex"],
            returncode=0,
            stdout='{"event":"completed","usage":{"total_tokens":42}}\n',
            stderr="",
        )

        with tempfile.TemporaryDirectory() as temp_dir_name:
            root_dir = Path(temp_dir_name).resolve()
            file_path = root_dir / "module.py"
            _write_file(file_path, "def present():\n    return 1\n")

            def fake_run(command, **kwargs):
                output_path = Path(kwargs["cwd"]) / "unused"
                return completed

            original_builder = llmagent._build_output_schema
            with mock.patch("llm.llmagent.subprocess.run", return_value=completed) as run_mock:
                with mock.patch("llm.llmagent._extract_json_payload", return_value=llmagent.CandidatePayload("a", "def present():\n    return 1\n", "ok")):
                    with mock.patch("pathlib.Path.exists", return_value=True):
                        with mock.patch("pathlib.Path.read_text", return_value='{"candidate_id":"a","file_source":"def present():\\n    return 1\\n","reason":"ok"}'):
                            result = llmagent._run_candidate_job(
                                llmagent.CandidateJobSpec(0, 1, "prompt"),
                                file_path,
                                root_dir,
                            )

        command = run_mock.call_args.args[0]
        self.assertIn("--json", command)
        self.assertEqual(result.tokens_used, 42)

    def test_build_candidate_prompt_discourages_trivial_refactors(self) -> None:
        prompt = llmagent._build_candidate_prompt(
            {},
            Path("/tmp/example.py"),
            "def present():\n    return 1\n",
            0,
            1,
        )

        self.assertIn("Lower AST complexity is the primary goal", prompt)
        self.assertIn("Avoid trivial local refactors", prompt)


class CandidateEvaluationTests(unittest.TestCase):
    def test_block_generator_from_source_matches_file_parser(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            root_dir = Path(temp_dir_name).resolve()
            file_path = root_dir / "module.py"
            source = """
                def top(flag):
                    if flag and flag:
                        return 1
                    return 0

                class Runner:
                    def run(self, enabled):
                        if enabled:
                            return top(enabled)
                        return 0
            """
            _write_file(file_path, source)

            from_file = ast_parser.block_generator(file_path)
            from_source = ast_parser.block_generator_from_source(
                textwrap.dedent(source).strip() + "\n",
                filename=str(file_path),
            )

        self.assertEqual(from_file, from_source)

    def test_candidate_eval_logs_when_falling_back_to_original(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            root_dir = Path(temp_dir_name).resolve()
            file_path = root_dir / "module.py"
            _write_file(file_path, "def present():\n    return 1\n")
            original_source = file_path.read_text(encoding="UTF-8")

            with mock.patch("candidates.candidate_evaluation.run_project_tests", return_value=False):
                with self.assertLogs("candidates.candidate_evaluation", level="INFO") as logs:
                    result = candidate_evaluation.candidate_eval(
                        ["def present():\n    return 2\n"],
                        file_path,
                        root_dir,
                        [],
                    )

        self.assertEqual(result, original_source)
        self.assertIn("did not find a better candidate", "\n".join(logs.output))

    def test_candidate_eval_selects_lowest_total_complexity_score(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            root_dir = Path(temp_dir_name).resolve()
            file_path = root_dir / "module.py"
            _write_file(
                file_path,
                """
                def choose(a, b, c):
                    if a and b and c:
                        return 1
                    if a:
                        return 2
                    return 3
                """,
            )
            lower_score = "def choose(a, b, c):\n    if a:\n        return 1\n    return 3\n"
            higher_score = "def choose(a, b, c):\n    if a and b and c:\n        return 1\n    if a and b:\n        return 2\n    return 3\n"

            with mock.patch("candidates.candidate_evaluation.run_project_tests", return_value=True):
                result = candidate_evaluation.candidate_eval(
                    [higher_score, lower_score],
                    file_path,
                    root_dir,
                    [],
                )

        self.assertEqual(result, lower_score)

    def test_candidate_eval_breaks_equal_scores_by_smaller_diff(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            root_dir = Path(temp_dir_name).resolve()
            file_path = root_dir / "module.py"
            _write_file(
                file_path,
                """
                def choose(flag):
                    if flag:
                        return 1
                    return 0
                """,
            )
            smaller_diff = "def choose(flag):\n    if flag:\n        return 2\n    return 0\n"
            larger_diff = "def choose(flag):\n    result = 0\n    if flag:\n        result = 2\n    return result\n"

            with mock.patch("candidates.candidate_evaluation.run_project_tests", return_value=True):
                result = candidate_evaluation.candidate_eval(
                    [larger_diff, smaller_diff],
                    file_path,
                    root_dir,
                    [],
                )

        self.assertEqual(result, smaller_diff)

    def test_candidate_eval_can_select_equal_score_candidate_over_original(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            root_dir = Path(temp_dir_name).resolve()
            file_path = root_dir / "module.py"
            _write_file(
                file_path,
                """
                def choose(flag):
                    if flag:
                        return 1
                    return 0
                """,
            )
            equal_score = "def choose(flag):\n    if flag:\n        return 2\n    return 0\n"
            worse_score = "def choose(flag):\n    if flag and flag:\n        return 2\n    return 0\n"

            with mock.patch("candidates.candidate_evaluation.run_project_tests", return_value=True):
                result = candidate_evaluation.candidate_eval(
                    [worse_score, equal_score],
                    file_path,
                    root_dir,
                    [],
                )

        self.assertEqual(result, equal_score)

    def test_candidate_eval_skips_unparseable_passing_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            root_dir = Path(temp_dir_name).resolve()
            file_path = root_dir / "module.py"
            _write_file(
                file_path,
                """
                def choose(flag):
                    if flag:
                        return 1
                    return 0
                """,
            )
            bad_source = "def choose(flag)\n    return 1\n"
            good_source = "def choose(flag):\n    return 1\n"

            with mock.patch("candidates.candidate_evaluation.run_project_tests", return_value=True):
                result = candidate_evaluation.candidate_eval(
                    [bad_source, good_source],
                    file_path,
                    root_dir,
                    [],
                )

        self.assertEqual(result, good_source)

    def test_evaluate_candidates_can_select_combined_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            root_dir = Path(temp_dir_name).resolve()
            file_path = root_dir / "module.py"
            _write_file(
                file_path,
                """
                def choose(flag):
                    if flag and flag:
                        return 1
                    return 0
                """,
            )
            generated = "def choose(flag):\n    if flag:\n        return 1\n    return 0\n"
            combined = "def choose(flag):\n    return 1 if flag else 0\n"

            with mock.patch("candidates.candidate_evaluation.run_project_tests", return_value=True):
                result = candidate_evaluation.evaluate_candidates(
                    [generated],
                    file_path,
                    root_dir,
                    [],
                    iteration_count=2,
                    sample_count=1,
                    survivor_count=1,
                    combination_enabled=True,
                    combination_generator=lambda baseline, survivors: [combined],
                )

        self.assertEqual(result.final_source, combined)
        self.assertIsNotNone(result.final_record)
        self.assertEqual(result.final_record.origin, "combined")
        self.assertEqual(len(result.round_summaries), 2)

    def test_evaluate_candidates_prefers_evidence_backed_complexity_reduction(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            root_dir = Path(temp_dir_name).resolve()
            file_path = root_dir / "module.py"
            _write_file(
                file_path,
                """
                def choose(a, b):
                    if a and b:
                        return 1
                    return 0
                """,
            )
            cleanup = "def choose(a, b):\n    if a and b:\n        return 2\n    return 0\n"
            simplification = "def choose(a, b):\n    if a:\n        return 1\n    return 0\n"

            with mock.patch("candidates.candidate_evaluation.run_project_tests", return_value=True):
                result = candidate_evaluation.evaluate_candidates(
                    [cleanup, simplification],
                    file_path,
                    root_dir,
                    [],
                )

        self.assertEqual(result.final_source, simplification)
        self.assertIsNotNone(result.final_record)
        self.assertTrue(result.final_record.meets_minimum_evidence)
        self.assertEqual(result.final_record.mutation_kind, "complexity_reduction")
        self.assertEqual(result.confidence_label, "complexity-reducing cleanup")


class MainWorkflowTests(unittest.TestCase):
    def test_optimize_files_uses_cumulative_working_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            root_dir = Path(temp_dir_name).resolve()
            target_dir = root_dir / "target"
            _write_file(target_dir / "a.py", "def a():\n    return 1\n")
            _write_file(target_dir / "b.py", "def b():\n    return 2\n")
            runtime_config = config.build_runtime_config(target_dir, workspace_root=root_dir)
            config.init_config(runtime_config)

            def fake_generate_candidates(context, file_path, sample_count, working_dir, agent_count=1, model=None, codex_command=llmagent.DEFAULT_CODEX_COMMAND):
                return [file_path.read_text(encoding="UTF-8")]

            def fake_evaluate_candidates(candidates, file_name, target_dir, test_targets, **kwargs):
                if file_name.name == "a.py":
                    return EvaluationResult(
                        final_source="def a():\n    return 10\n",
                        final_record=CandidateRecord(
                            source="def a():\n    return 10\n",
                            score=1,
                            diff_size=1,
                            round_index=0,
                            origin="generated",
                            lineage=("generated-0",),
                        ),
                    )
                self.assertEqual((target_dir / "a.py").read_text(encoding="UTF-8"), "def a():\n    return 10\n")
                return EvaluationResult(final_source=file_name.read_text(encoding="UTF-8"), final_record=None)

            with mock.patch("main.generate_candidates", side_effect=fake_generate_candidates):
                with mock.patch("main.evaluate_candidates", side_effect=fake_evaluate_candidates):
                    optimized_dir, file_results = optimize_main._optimize_files(
                        runtime_config,
                        [target_dir / "a.py", target_dir / "b.py"],
                        {},
                    )
                    optimized_source = (optimized_dir / "a.py").read_text(encoding="UTF-8")

        self.assertEqual(optimized_source, "def a():\n    return 10\n")
        self.assertEqual(len(file_results), 2)

    def test_write_final_reports_writes_diff_and_skip_benchmark(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            root_dir = Path(temp_dir_name).resolve()
            target_dir = root_dir / "target"
            optimized_dir = root_dir / "optimized"
            _write_file(target_dir / "module.py", "def present():\n    return 1\n")
            _write_file(optimized_dir / "module.py", "def present():\n    return 2\n")
            runtime_config = config.build_runtime_config(target_dir, workspace_root=root_dir)
            optimize_main._write_final_reports(
                runtime_config,
                optimized_dir,
                [{"relative_path": "module.py", "changed": True}],
                [],
            )

            report = (optimized_dir / "optimization_report.json").read_text(encoding="UTF-8")
            diff_text = (optimized_dir / "optimization_diff.patch").read_text(encoding="UTF-8")

        self.assertIn('"skipped": true', report.lower())
        self.assertIn('"confidence_label": "safe but unproven"', report)
        self.assertIn('"completed_with_evidence": false', report.lower())
        self.assertIn("---", diff_text)


if __name__ == "__main__":
    unittest.main()
