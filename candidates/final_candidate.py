from __future__ import annotations

from pathlib import Path
import shutil


def final_candidate(
    final_file_source: str,
    file_path: Path,
    target_dir: Path,
    optimized_project_dir: Path,
) -> Path:
    if not optimized_project_dir.exists():
        shutil.copytree(
            target_dir,
            optimized_project_dir,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("optimized", "state", "_local", "__pycache__"),
        )

    relative_path = file_path.relative_to(target_dir)
    optimized_file_path = optimized_project_dir / relative_path
    optimized_file_path.parent.mkdir(parents=True, exist_ok=True)
    optimized_file_path.write_text(final_file_source, encoding="UTF-8")
    return optimized_project_dir
