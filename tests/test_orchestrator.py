from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from analyze.interfunction_calls import build_function_graph
from candidates.candidate_evaluation import _changes_only_within_spans
from orchestrator.loop import optimize_regions
from orchestrator.region import Criterion, RegionProposal
from orchestrator.runner_base import OptimizationState
from orchestrator.runners.static_slice import StaticComplexitySliceRunner
from orchestrator.runners.dynamic_slice import DynamicSliceRunner


def _write(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source).strip() + "\n", encoding="UTF-8")


class RegionRunnerTests(unittest.TestCase):
    def test_static_runner_selects_and_expands_a_function(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_path = root / "app.py"
            _write(file_path, """
                def helper():
                    return 1
                def target(flag):
                    if flag:
                        return helper()
                    return 0
            """)
            state = OptimizationState(root, [file_path], {}, build_function_graph(root, [file_path]), [])
            runner = StaticComplexitySliceRunner()
            region = runner.propose(state)
            self.assertIsNotNone(region)
            assert region is not None
            self.assertEqual(region.criterion.symbol, "target")
            expanded = runner.expand(state, region, "stalled")
            self.assertIsNotNone(expanded)
            assert expanded is not None
            self.assertEqual(len(expanded.editable_spans), 2)

    def test_loop_expands_stalled_region_before_swapping(self) -> None:
        root = Path("/tmp/project")
        initial = RegionProposal(Criterion(root / "app.py", "target", 1, 3), ((1, 3),), runner_name="test")
        expanded = RegionProposal(initial.criterion, ((1, 3), (5, 7)), runner_name="test")

        class Runner:
            name = "test"
            def propose(self, state): return initial
            def expand(self, state, region, reason): return expanded

        state = OptimizationState(root, [], {}, {}, [])
        saved: list[dict[str, object]] = []
        accepted = optimize_regions(state, [Runner()], lambda region: region == expanded, saved.append, 1, 2)
        self.assertEqual(accepted, [expanded])
        self.assertEqual(len(saved), 2)

    def test_loop_exhausts_regions_from_one_runner_before_swapping(self) -> None:
        root = Path("/tmp/project")
        regions = [
            RegionProposal(
                Criterion(root / "app.py", f"target_{index}", index, index + 1),
                ((index, index + 1),),
            )
            for index in range(5)
        ]

        class Runner:
            name = "first"

            def propose(self, state):
                return next((region for region in regions if region.key not in state.attempted_regions), None)

            def expand(self, state, region, reason):
                return None

        class EmptyRunner:
            name = "second"

            def propose(self, state):
                return None

            def expand(self, state, region, reason):
                return None

        state = OptimizationState(root, [], {}, {}, [])
        saved: list[dict[str, object]] = []
        accepted = optimize_regions(state, [Runner(), EmptyRunner()], lambda region: True, saved.append, 1, 2)

        self.assertEqual(accepted, regions)
        self.assertEqual([round_state["runner_index"] for round_state in saved], [0] * 5)

    def test_loop_switches_after_runner_exhaustion(self) -> None:
        root = Path("/tmp/project")
        region = RegionProposal(Criterion(root / "app.py", "target", 1, 3), ((1, 3),))

        class EmptyRunner:
            name = "empty"

            def __init__(self) -> None:
                self.calls = 0

            def propose(self, state):
                self.calls += 1
                return None

            def expand(self, state, region, reason):
                return None

        class AcceptingRunner:
            name = "accepting"

            def __init__(self) -> None:
                self.calls = 0

            def propose(self, state):
                self.calls += 1
                return None if region.key in state.attempted_regions else region

            def expand(self, state, region, reason):
                return None

        empty = EmptyRunner()
        accepting = AcceptingRunner()
        accepted = optimize_regions(
            OptimizationState(root, [], {}, {}, []),
            [empty, accepting],
            lambda proposal: True,
            lambda _round: None,
            1,
            2,
        )

        self.assertEqual(accepted, [region])
        self.assertEqual(empty.calls, 1)
        self.assertEqual(accepting.calls, 2)

    def test_span_guard_rejects_out_of_region_change(self) -> None:
        original = "first = 1\nsecond = 2\n"
        self.assertTrue(_changes_only_within_spans(original, "first = 1\nsecond = 3\n", ((1, 2),)))
        self.assertFalse(_changes_only_within_spans(original, "first = 9\nsecond = 2\n", ((1, 2),)))

    def test_dynamic_runner_uses_executed_test_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app = root / "app.py"
            _write(app, """
                def used():
                    return 1
                def unused():
                    if True:
                        return 2
            """)
            _write(root / "tests" / "test_app.py", """
                import unittest
                from app import used
                class AppTests(unittest.TestCase):
                    def test_used(self):
                        self.assertEqual(used(), 1)
            """)
            _write(root / "tests" / "__init__.py", "")
            state = OptimizationState(root, [app], {}, build_function_graph(root, [app]), [])
            region = DynamicSliceRunner().propose(state)
            self.assertIsNotNone(region)
            assert region is not None
            self.assertEqual(region.criterion.symbol, "used")

    def test_dynamic_runner_skips_attempted_top_region(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app = root / "app.py"
            _write(app, """
                def most_used():
                    if True:
                        return 1

                def next_used():
                    return 2
            """)
            state = OptimizationState(root, [app], {}, {}, [])
            runner = DynamicSliceRunner()

            def executed_lines(_state):
                return {str(app.resolve()): {1, 2, 3, 5}}

            runner._executed_lines = executed_lines  # type: ignore[method-assign]
            first = runner.propose(state)
            self.assertIsNotNone(first)
            assert first is not None
            state.attempted_regions.add(first.key)

            second = runner.propose(state)

            self.assertIsNotNone(second)
            assert second is not None
            self.assertEqual(second.criterion.symbol, "next_used")


if __name__ == "__main__":
    unittest.main()
