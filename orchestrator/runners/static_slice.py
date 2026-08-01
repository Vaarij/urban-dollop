from __future__ import annotations

from pathlib import Path

from analyze import ast_parser
from orchestrator.region import Criterion, RegionProposal
from orchestrator.runner_base import OptimizationState


def _blocks(file_path: Path) -> list[tuple[str, int, int, int]]:
    functions, classes = ast_parser.block_generator(file_path)
    blocks = [
        (str(item["function_name"]), int(item["start_line"]), int(item["end_line"]), int(item["max_nesting"]) + int(item["max_conditionals"]))
        for item in functions
    ]
    for class_block in classes:
        class_name = str(class_block["class_name"])
        blocks.extend(
            (f"{class_name}.{item['function_name']}", int(item["start_line"]), int(item["end_line"]), int(item["max_nesting"]) + int(item["max_conditionals"]))
            for item in class_block["class_methods"]
        )
    return blocks


class StaticComplexitySliceRunner:
    name = "static"

    def propose(self, state: OptimizationState) -> RegionProposal | None:
        candidates: list[tuple[int, Path, str, int, int]] = []
        for file_path in state.source_files:
            for symbol, start, end, score in _blocks(file_path):
                criterion = Criterion(file_path, symbol, start, end)
                if RegionProposal(criterion, ((start, end),)).key not in state.attempted_regions:
                    candidates.append((score, file_path, symbol, start, end))
        if not candidates:
            return None
        score, file_path, symbol, start, end = max(candidates, key=lambda item: item[0])
        return RegionProposal(Criterion(file_path, symbol, start, end), ((start, end),), runner_name=self.name, evidence={"complexity": score})

    def expand(self, state: OptimizationState, region: RegionProposal, reason: str) -> RegionProposal | None:
        matching = [key for key, values in state.function_graph.items() if key.endswith(f":{region.criterion.symbol}")]
        dependencies = sorted({dependency for key in matching for dependency in state.function_graph[key]})
        spans = list(region.editable_spans)
        for dependency in dependencies:
            path_text, symbol = dependency.rsplit(":", 1)
            path = Path(path_text)
            if path.resolve() != region.criterion.file_path.resolve():
                continue
            for known_symbol, start, end, _score in _blocks(path):
                if known_symbol == symbol:
                    spans.append((start, end))
        expanded = RegionProposal(region.criterion, tuple(sorted(set(spans))), tuple(dependencies), self.name, {**region.evidence, "expanded_for": reason})
        return None if expanded.key in state.attempted_regions or expanded.editable_spans == region.editable_spans else expanded
