from __future__ import annotations

from collections.abc import Callable

from .region import RegionProposal
from .runner_base import OptimizationState, RegionRunner


def optimize_regions(
    state: OptimizationState,
    runners: list[RegionRunner],
    optimize_region: Callable[[RegionProposal], bool],
    save_round: Callable[[dict[str, object]], None],
    max_expansions: int,
    swap_after_stalled_rounds: int,
    resume: dict[str, object] | None = None,
) -> list[RegionProposal]:
    """Optimize one proposal at a time, expanding stalled proposals before swapping."""
    resume = resume or {}
    state.attempted_regions.update(resume.get("attempted_regions", []))
    runner_index = int(resume.get("runner_index", 0))
    accepted: list[RegionProposal] = []
    stalled = 0
    while runner_index < len(runners):
        runner = runners[runner_index]
        region = runner.propose(state)
        if region is None:
            runner_index += 1
            stalled = 0
            continue
        expansions = 0
        while region is not None:
            state.attempted_regions.add(region.key)
            changed = optimize_region(region)
            save_round({"runner_index": runner_index, "runner": runner.name, "region": region.key, "attempted_regions": sorted(state.attempted_regions), "changed": changed})
            if changed:
                accepted.append(region)
                stalled = 0
                break
            stalled += 1
            if expansions >= max_expansions or stalled >= swap_after_stalled_rounds:
                break
            region = runner.expand(state, region, "no evidence-backed candidate")
            expansions += 1
        runner_index += 1
        stalled = 0
    return accepted
