from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .region import RegionProposal


@dataclass(slots=True)
class OptimizationState:
    project_dir: Path
    source_files: list[Path]
    ast_graph: dict[str, object]
    function_graph: dict[str, set[str]]
    test_targets: list[str]
    attempted_regions: set[str] = field(default_factory=set)


class RegionRunner(Protocol):
    name: str

    def propose(self, state: OptimizationState) -> RegionProposal | None: ...

    def expand(self, state: OptimizationState, region: RegionProposal, reason: str) -> RegionProposal | None: ...
