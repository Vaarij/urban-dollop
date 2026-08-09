from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from self_optimize import cli


class CliTests(unittest.TestCase):
    def test_parse_args_accepts_repeatable_commands(self) -> None:
        args = cli.parse_args(
            [
                "--target",
                "project",
                "--test-command",
                "python -m unittest",
                "--test-command",
                "python -m doctest README.md",
                "--benchmark-command",
                "python benchmark.py",
            ]
        )

        self.assertEqual(args.test_command, ["python -m unittest", "python -m doctest README.md"])
        self.assertEqual(args.benchmark_command, ["python benchmark.py"])

    def test_main_passes_commands_to_runtime_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            with patch("self_optimize.cli.run_main", return_value=0) as run_main:
                result = cli.main(
                    [
                        "--target",
                        str(target),
                        "--test-command",
                        "python -m unittest",
                        "--benchmark-command",
                        "python benchmark.py",
                    ]
                )

        self.assertEqual(result, 0)
        runtime_config = run_main.call_args.args[0]
        self.assertEqual(runtime_config.test_targets, ["python -m unittest"])
        self.assertEqual(runtime_config.benchmark_targets, ["python benchmark.py"])


if __name__ == "__main__":
    unittest.main()
