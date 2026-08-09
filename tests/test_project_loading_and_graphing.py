from __future__ import annotations

import ast
import tempfile
import textwrap
import unittest
from pathlib import Path

import config
from analyze import ast_parser, hotspot_detector
from analyze.interfunction_calls import analyze_interfunction_calls, build_function_graph
from project_loader import entrypoint_detect, file_discover, import_graph_builder, static_slice


def _write_file(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source).strip() + "\n", encoding="UTF-8")


class ProjectLoadingAndGraphingTests(unittest.TestCase):
    def test_static_slice_records_assignments_and_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            file_path = Path(temp_dir_name) / "module.py"
            _write_file(
                file_path,
                """
                total = 3
                doubled = total * 2
                left = right = doubled + offset
                annotated: int = right
                """,
            )

            tree = ast.parse(file_path.read_text(encoding="UTF-8"))
            variables = static_slice._variable_finder(tree)

            self.assertEqual(
                variables,
                [
                    static_slice.VariableDefinition("total", 1),
                    static_slice.VariableDefinition("doubled", 2),
                    static_slice.VariableDefinition("left", 3),
                    static_slice.VariableDefinition("right", 3),
                    static_slice.VariableDefinition("annotated", 4),
                ],
            )
            definitions = static_slice.backward_slice(tree, variables)

            self.assertEqual(
                definitions,
                [
                    static_slice.TargetDefinition("total", "3", True, []),
                    static_slice.TargetDefinition("doubled", "total * 2", False, ["total"]),
                    static_slice.TargetDefinition("left", "doubled + offset", False, ["doubled", "offset"]),
                    static_slice.TargetDefinition("right", "doubled + offset", False, ["doubled", "offset"]),
                    static_slice.TargetDefinition("annotated", "right", False, ["right"]),
                ],
            )
    def test_transfer_functions_list_conditional_outputs(self) -> None:
        definitions = [
            static_slice.TargetDefinition("a", "5", True, []),
            static_slice.TargetDefinition("c", "True", True, []),
            static_slice.TargetDefinition(
                "y", "a * 2 if c else a // 2", False, ["c", "a", "a"]
            )
        ]

        self.assertEqual(
            static_slice.transfer_function_gen(definitions),
            {
                "a": [({"a": 5}, 5)],
                "c": [({"c": True}, True), ({"c": False}, False)],
                "y": [({"c": True, "a": 5}, 10), ({"c": False, "a": 5}, 2)],
            },
        )

    def test_transfer_functions_limit_combinations(self) -> None:
        inputs = [
            static_slice.TargetDefinition(f"input_{index}", "True", True, [])
            for index in range(7)
        ]
        names = [definition.target for definition in inputs]
        definitions = inputs + [
            static_slice.TargetDefinition(
                "result", " + ".join(names), False, names
            )
        ]

        transfer_functions = static_slice.transfer_function_gen(definitions)

        self.assertEqual(
            len(transfer_functions["result"]),
            static_slice.MAX_DISCRETE_COMBINATIONS,
        )

    def test_file_discovery_uses_config_root_and_finds_tests(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            root_dir = Path(temp_dir_name).resolve()
            _write_file(root_dir / "app.py", "def run():\n    return 1")
            _write_file(root_dir / "pkg" / "worker.py", "def work():\n    return 2")
            _write_file(root_dir / "tests" / "test_app.py", "import unittest")
            _write_file(root_dir / "_local" / "ignored.py", "raise RuntimeError")

            runtime_config = config.build_runtime_config(root_dir, workspace_root=root_dir)
            config.init_config(runtime_config)

            all_files = file_discover.walk_through()
            test_files = file_discover.find_test_files()
            source_files = file_discover.find_source_files()

            self.assertEqual(
                [path.relative_to(root_dir).as_posix() for path in all_files],
                ["app.py", "pkg/worker.py", "tests/test_app.py"],
            )
            self.assertEqual(
                [path.relative_to(root_dir).as_posix() for path in test_files],
                ["tests/test_app.py"],
            )
            self.assertEqual(
                [path.relative_to(root_dir).as_posix() for path in source_files],
                ["app.py", "pkg/worker.py"],
            )

    def test_entrypoint_detection_resolves_relative_and_absolute_project_imports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            root_dir = Path(temp_dir_name).resolve()
            _write_file(root_dir / "main.py", "from pkg.service import run\n\nrun()\n")
            _write_file(root_dir / "pkg" / "__init__.py", "")
            _write_file(
                root_dir / "pkg" / "service.py",
                """
                from .helpers import helper

                def run():
                    return helper()
                """,
            )
            _write_file(root_dir / "pkg" / "helpers.py", "def helper():\n    return 1\n")

            file_list = file_discover.walk_through(root_dir)
            import_graph = {
                str(file_path): import_graph_builder.build_import_graph(file_path)
                for file_path in file_list
            }

            roots = entrypoint_detect.find_entry_points(root_dir, import_graph, file_list)

            self.assertEqual(
                [path.relative_to(root_dir).as_posix() for path in roots],
                ["main.py"],
            )

    def test_interfunction_calls_track_local_functions_and_methods(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            file_path = Path(temp_dir_name) / "module.py"
            _write_file(
                file_path,
                """
                def helper():
                    return 1

                def top():
                    return helper()

                class Runner:
                    def run(self):
                        helper()
                        return self.finish()

                    def finish(self):
                        return helper()
                """,
            )

            call_map = analyze_interfunction_calls(file_path)

            self.assertEqual(call_map["helper"], [])
            self.assertEqual(call_map["top"], ["helper"])
            self.assertEqual(call_map["Runner.run"], ["Runner.finish", "helper"])
            self.assertEqual(call_map["Runner.finish"], ["helper"])

    def test_function_graph_tracks_project_import_calls(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            root_dir = Path(temp_dir_name).resolve()
            _write_file(
                root_dir / "main.py",
                """
                from pkg.service import run
                import pkg.helpers

                def entry():
                    return run()
                """,
            )
            _write_file(
                root_dir / "pkg" / "service.py",
                """
                from .helpers import helper

                def run():
                    return helper()
                """,
            )
            _write_file(root_dir / "pkg" / "helpers.py", "def helper():\n    return 1\n")

            file_list = file_discover.walk_through(root_dir)
            graph = build_function_graph(root_dir, file_list)
            self.assertIn(f"{root_dir / 'pkg' / 'service.py'}:run", graph[f"{root_dir / 'main.py'}:entry"])
            self.assertIn(f"{root_dir / 'pkg' / 'helpers.py'}:helper", graph[f"{root_dir / 'pkg' / 'service.py'}:run"])

    def test_ast_parser_keeps_class_methods_out_of_top_level_functions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            file_path = Path(temp_dir_name) / "module.py"
            _write_file(
                file_path,
                """
                from dataclasses import dataclass

                def top():
                    return 1

                class Runner:
                    def run(self):
                        return top()

                @dataclass
                class Payload:
                    value: int
                """,
            )

            functions, classes = ast_parser.block_generator(file_path)

            self.assertEqual([block["function_name"] for block in functions], ["top"])
            self.assertEqual(classes[0]["class_name"], "Runner")
            self.assertEqual(
                [block["function_name"] for block in classes[0]["class_methods"]],
                ["run"],
            )
            self.assertTrue(classes[1]["data_class"])
            self.assertEqual(classes[1]["class_methods"], [])

    def test_ast_parser_handles_deeply_nested_control_flow_iteratively(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            file_path = Path(temp_dir_name) / "deep.py"
            nested_lines = ["def stress(flag):"]
            for depth in range(60):
                nested_lines.append(f"{'    ' * (depth + 1)}if flag:")
            nested_lines.append(f"{'    ' * 61}return True and flag and flag and flag")
            source = "\n".join(nested_lines)
            _write_file(file_path, source)

            functions, _classes = ast_parser.block_generator(file_path)

            self.assertEqual(functions[0]["function_name"], "stress")
            self.assertGreaterEqual(int(functions[0]["max_nesting"]), 60)
            self.assertGreaterEqual(int(functions[0]["max_conditionals"]), 4)

    def test_hotspot_detector_raises_when_no_candidates_exist(self) -> None:
        with self.assertRaises(hotspot_detector.NoHotspotCandidateError):
            hotspot_detector.find_max_hotspots({})

    def test_hotspot_detector_scores_class_methods(self) -> None:
        ast_graph = {
            "/tmp/a.py": (
                [],
                [
                    {
                        "class_name": "Runner",
                        "class_methods": [
                            {"function_name": "run", "max_conditionals": 2, "max_nesting": 3}
                        ],
                        "data_class": False,
                        "start_line": 0,
                        "end_line": 10,
                    }
                ],
            ),
            "/tmp/b.py": (
                [
                    {"function_name": "top", "max_conditionals": 1, "max_nesting": 1},
                ],
                [],
            ),
        }

        best_file, score = hotspot_detector.find_max_hotspots(ast_graph)

        self.assertEqual(best_file, Path("/tmp/a.py"))
        self.assertEqual(score, 5)


if __name__ == "__main__":
    unittest.main()
