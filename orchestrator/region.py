from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Criterion:
    file_path: Path
    symbol: str
    start_line: int
    end_line: int


@dataclass(frozen=True, slots=True)
class RegionProposal:
    criterion: Criterion
    editable_spans: tuple[tuple[int, int], ...]
    dependencies: tuple[str, ...] = ()
    runner_name: str = ""
    evidence: dict[str, object] = field(default_factory=dict)

    @property
    def key(self) -> str:
        spans = ",".join(f"{start}:{end}" for start, end in self.editable_spans)
        return f"{self.criterion.file_path.resolve()}:{self.criterion.symbol}:{spans}"
