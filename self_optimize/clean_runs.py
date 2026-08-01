from __future__ import annotations

import argparse
from pathlib import Path
import shutil


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Remove optimizer output from previous runs.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the directories that would be removed without deleting them.",
    )
    return parser


def _remove_path(path: Path, dry_run: bool) -> None:
    if not path.exists():
        print(f"[clean-runs] skipping missing {path}")
        return
    if dry_run:
        print(f"[clean-runs] would remove {path}")
        return
    shutil.rmtree(path)
    print(f"[clean-runs] removed {path}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    workspace_root = Path(__file__).resolve().parent.parent
    _remove_path(workspace_root / "state", args.dry_run)
    _remove_path(workspace_root / "optimized", args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
