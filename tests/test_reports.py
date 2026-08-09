from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import config
from main import _write_final_reports


class ReportTests(unittest.TestCase):
    def test_final_report_includes_benchmark_results(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "target"
            optimized = root / "optimized"
            target.mkdir()
            optimized.mkdir()
            runtime_config = config.build_runtime_config(target, workspace_root=root)
            benchmark = {
                "command": ["python", "benchmark.py"],
                "returncode": 0,
                "stdout": "",
                "stderr": "",
                "duration_seconds": 0.125,
            }

            _write_final_reports(runtime_config, optimized, [], [benchmark])

            report = json.loads((optimized / "optimization_report.json").read_text(encoding="UTF-8"))
            self.assertEqual(report["benchmarks"], [benchmark])


if __name__ == "__main__":
    unittest.main()
