from __future__ import annotations

import logging
from pathlib import Path

from config import get_config

logger = logging.getLogger(__name__)

SKIPPED_DIRS = {
    ".gitignore",
    "cache",
    ".git",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    "node_modules",
    "build",
    "dist",
    ".idea",
    ".vscode",
    "optimized",
    "state",
    "_local",
}
TEST_DIR_NAMES = {"test", "tests"}


def _resolve_root_dir(root_dir: Path | None = None) -> Path:
    if root_dir is not None:
        return root_dir.resolve()
    return get_config().target_dir.resolve()


def is_test_file(file_path: Path, root_dir: Path | None = None) -> bool:
    if file_path.suffix != ".py":
        return False

    if (
        file_path.name == "tests.py"
        or file_path.name.startswith("test_")
        or file_path.stem.endswith("_test")
    ):
        return True

    resolved_root = _resolve_root_dir(root_dir)
    relative_path = file_path.resolve().relative_to(resolved_root)
    return any(part in TEST_DIR_NAMES for part in relative_path.parts)


def walk_through(root_dir: Path | None = None) -> list[Path]:
    resolved_root = _resolve_root_dir(root_dir)
    files_in_project: list[Path] = []
    logger.info("Walking through %s", resolved_root.name)
    for root, dirs, files in resolved_root.walk():
        dirs[:] = [directory for directory in dirs if directory not in SKIPPED_DIRS]
        for filename in files:
            if filename.endswith(".py"):
                files_in_project.append(root / filename)
    return sorted(files_in_project)


def find_test_files(root_dir: Path | None = None) -> list[Path]:
    resolved_root = _resolve_root_dir(root_dir)
    return [
        file_path
        for file_path in walk_through(resolved_root)
        if is_test_file(file_path, resolved_root)
    ]


def find_source_files(root_dir: Path | None = None) -> list[Path]:
    resolved_root = _resolve_root_dir(root_dir)
    return [
        file_path
        for file_path in walk_through(resolved_root)
        if not is_test_file(file_path, resolved_root)
    ]
