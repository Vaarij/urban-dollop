from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

from orchestrator.region import Criterion, RegionProposal
from orchestrator.runner_base import OptimizationState
from .static_slice import StaticComplexitySliceRunner, _blocks


_TRACER = '''import atexit, json, os, sys
root = os.environ.get("SELF_OPTIMIZE_TRACE_ROOT")
output = os.environ.get("SELF_OPTIMIZE_TRACE_OUTPUT")
lines = {}
def trace(frame, event, arg):
    if event == "line":
        filename = frame.f_code.co_filename
        if filename.startswith("<"):
            return trace
        name = os.path.realpath(filename)
        if root and name.startswith(root + os.sep):
            lines.setdefault(name, set()).add(frame.f_lineno - 1)
    return trace
sys.settrace(trace)
@atexit.register
def save():
    if output:
        previous = {}
        if os.path.exists(output):
            with open(output, "r", encoding="utf-8") as file:
                previous = json.load(file)
        for name, values in previous.items():
            lines.setdefault(name, set()).update(values)
        with open(output, "w", encoding="utf-8") as file:
            json.dump({name: sorted(values) for name, values in lines.items()}, file)
'''


class DynamicSliceRunner:
    name = "dynamic"

    def _executed_lines(self, state: OptimizationState) -> dict[str, set[int]]:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            (temp_path / "sitecustomize.py").write_text(_TRACER, encoding="UTF-8")
            output = temp_path / "trace.json"
            env = dict(os.environ)
            env["SELF_OPTIMIZE_TRACE_ROOT"] = os.path.realpath(state.project_dir)
            env["SELF_OPTIMIZE_TRACE_OUTPUT"] = str(output)
            env["PYTHONPATH"] = os.pathsep.join([str(temp_path), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
            default_command = [sys.executable, "-m", "unittest", "discover"]
            if (state.project_dir / "tests").is_dir():
                default_command.extend(["-s", "tests"])
            commands = [shlex.split(target) for target in state.test_targets] or [default_command]
            for command in commands:
                subprocess.run(command, cwd=state.project_dir, env=env, capture_output=True, text=True, check=False)
            if not output.exists():
                return {}
            return {path: set(lines) for path, lines in json.loads(output.read_text(encoding="UTF-8")).items()}

    def propose(self, state: OptimizationState) -> RegionProposal | None:
        executed = self._executed_lines(state)
        candidates: list[tuple[int, Path, str, int, int, int]] = []
        for file_path in state.source_files:
            seen = executed.get(str(file_path.resolve()), set())
            for symbol, start, end, score in _blocks(file_path):
                count = sum(start <= line < end for line in seen)
                proposal = RegionProposal(Criterion(file_path, symbol, start, end), ((start, end),))
                if count and proposal.key not in state.attempted_regions:
                    candidates.append((count, file_path, symbol, start, end, score))
        if not candidates:
            return None
        count, file_path, symbol, start, end, score = max(candidates, key=lambda item: (item[0], item[5]))
        return RegionProposal(
            Criterion(file_path, symbol, start, end),
            ((start, end),),
            runner_name=self.name,
            evidence={"executed_lines": count, "complexity": score},
        )

    def expand(self, state: OptimizationState, region: RegionProposal, reason: str) -> RegionProposal | None:
        return StaticComplexitySliceRunner().expand(state, region, reason)
