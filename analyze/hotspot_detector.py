from __future__ import annotations

from pathlib import Path


class NoHotspotCandidateError(ValueError):
    """Raised when no AST blocks are available to score."""


def _score_function(block: dict[str, object]) -> int:
    return int(block.get("max_conditionals", 0)) + int(block.get("max_nesting", 0))


def _score_file(blocks: object) -> int:
    if not isinstance(blocks, (list, tuple)) or len(blocks) != 2:
        return 0

    functions, classes = blocks
    function_score = sum(_score_function(function) for function in functions)
    class_score = sum(
        _score_function(method)
        for class_block in classes
        for method in class_block.get("class_methods", [])
    )
    return function_score + class_score


def find_max_hotspots(ast_graph: dict[str, object]) -> tuple[Path, int]:
    best_file: Path | None = None
    highest_score: int | None = None

    for file_path, blocks in ast_graph.items():
        file_score = _score_file(blocks)
        if highest_score is None or file_score > highest_score:
            highest_score = file_score
            best_file = Path(file_path)

    if best_file is None or highest_score is None:
        raise NoHotspotCandidateError("No AST hotspot candidates were available.")

    return best_file, highest_score
