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
    parser.add_argument(
        "--agents",
        type=int,
        default=1,
        help="Number of concurrent Codex candidate workers to run.",
    )
    parser.add_argument(
        "--codex-model",
        help="Optional Codex model override for candidate generation.",
    )
    parser.add_argument(
        "--test-command",
        action="append",
        default=[],
        help="Test command to run for each candidate; repeat to run multiple commands.",
    )
    parser.add_argument(
        "--benchmark-command",
        action="append",
        default=[],
        help="Benchmark command to time for each candidate; repeat to run multiple commands.",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    runtime_config = config.build_runtime_config(
        target=args.target,
        recovery_token=args.recovery,
        agent_count=args.agents,
        codex_model=args.codex_model,
        test_targets=args.test_command,
        benchmark_targets=args.benchmark_command,
    )
    config.init_config(runtime_config)
    return run_main(runtime_config)


if __name__ == "__main__":
    raise SystemExit(main())
