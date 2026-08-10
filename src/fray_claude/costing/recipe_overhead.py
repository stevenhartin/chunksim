"""The harness that fitted `recipe_rates.ACTION_OVERHEAD_SECONDS`.

**No caller in `src/`, deliberately** - the same shape as `dps_overhead.py`,
and for the same reason. A constant that came out of a measurement should be
re-derivable by whoever doubts it, and a docstring claiming "0.4 seconds,
fitted" is worth nothing if the fit cannot be run again.

Run it against whatever maps are cached:

    .venv/bin/python -m fray_claude.costing.recipe_overhead fray verf

What it fits, and what it refuses to. The residuals are **bimodal**, and that
is the finding rather than a nuisance: methods whose materials price free are a
systematically *fast* ceiling (tick-math has no banking), and methods whose
materials cost something are systematically slow by three orders of magnitude
(this charges you for fishing the anglerfish where the guide assumes you bought
it). A single constant across both is meaningless, so only the free-input pairs
are fitted and the split is printed beside the answer.

Measured over `fray`, `verf` and `verf-sim/run-001`: 30 methods have both a
recipe and an *exactly* joined guide, 24 of them with free materials. Across
those 24 tick-math alone is a median 1.38x above the guide; 0.4s an action
brings the median error to 1.14x, and 0.4s is a fixed point of the fit - the
constant in use does change which recipe variant wins, so re-running with a
different one in place is part of checking it. The other 6 land at x0.0011 to
x0.024, which is the split this refuses to average over.

It is also the right order for what it stands in for: 28 items a bank trip at
~20s a trip is 0.7s an item.
"""

from __future__ import annotations

import math
import statistics
import sys

from fray_claude.costing import recipe_rates
from fray_claude.costing.estimate import material_seconds
from fray_claude.costing.inputs import load_heuristics, load_recipes
from fray_claude.derive.pipeline import derive, load_map_state
from fray_claude.derive.search import build_world_index
from fray_claude.model.chunkinfo import ChunkInfo
from fray_claude.model.firebase import reverse_tasks_map
from fray_claude.store import cache

#: `(experience, action seconds before overhead, the guide's rate)`.
Pair = tuple[float, float, float]


def pairs_for(map_ids: list[str]) -> tuple[list[Pair], list[Pair]]:
    """Every method with both a recipe and an exact guide, split by input cost."""
    info = ChunkInfo(cache.read_chunkinfo())
    tasks_map = reverse_tasks_map(cache.read_blob(cache.TASKS_MAP_BLOB_NAME)["data"])
    recipes = load_recipes()
    heuristics, _ = load_heuristics(info)
    world = build_world_index(info)

    free: list[Pair] = []
    paid: list[Pair] = []
    seen: set[str] = set()
    for map_id in map_ids:
        state, unlocked = load_map_state(cache.read_cache(map_id)["data"], info, tasks_map)
        derived = derive(state, unlocked)
        priced, _ = recipe_rates.computed_rates(
            info,
            derived.challenges.valid,
            recipes,
            material_seconds(state, derived, world, heuristics),
        )
        for task, action in priced.items():
            guide = heuristics.xp_per_hour(task, action.skill)
            if guide.match != "exact" or guide.value <= 0 or task in seen:
                continue
            seen.add(task)
            bare = action.action_seconds - recipe_rates.ACTION_OVERHEAD_SECONDS
            (free if action.input_seconds <= 0 else paid).append(
                (action.experience, bare, guide.value)
            )
    return free, paid


def error_at(pairs: list[Pair], overhead: float) -> float:
    """Median absolute log-ratio of computed against the guide."""
    return statistics.median(
        abs(math.log(xp * 3600.0 / (seconds + overhead) / guide))
        for xp, seconds, guide in pairs
    )


def fit(pairs: list[Pair]) -> float:
    """The overhead minimising `error_at`, to a tenth of a second."""
    return min(((error_at(pairs, c / 10), c / 10) for c in range(0, 1200)))[1]


def main(argv: list[str]) -> int:
    free, paid = pairs_for(argv or ["fray"])
    print(f"{len(free)} free-input pairs, {len(paid)} paid-input pairs")
    if paid:
        ratios = sorted(xp * 3600.0 / s / g for xp, s, g in paid)
        print(
            f"  paid inputs are not fitted: ratios x{ratios[0]:.4f}..x{ratios[-1]:.4f}"
            " - this charges for the supply chain the guide assumes you buy"
        )
    if not free:
        print("  nothing to fit")
        return 1
    best = fit(free)
    print(
        f"  best overhead {best:.1f}s"
        f"  median error x{math.exp(error_at(free, best)):.2f}"
        f"  (0s: x{math.exp(error_at(free, 0.0)):.2f})"
    )
    print(f"  in use: {recipe_rates.ACTION_OVERHEAD_SECONDS}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
