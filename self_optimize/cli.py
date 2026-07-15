"""Console entry points for the project."""

from __future__ import annotations

import argparse

import config
from main import main as run_main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="self-optimize",
        description="Run the project optimizer against a target Python project.",
    )
    parser.add_argument(
        "--target",
        required=True,
        help="Path to the Python project that should be analyzed.",
    )
    parser.add_argument(
        "--recovery",
        help="Optional recovery stage or token to resume from.",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    runtime_config = config.build_runtime_config(
        target=args.target,
        recovery_token=args.recovery,
    )
    config.init_config(runtime_config)
    return run_main(runtime_config)
