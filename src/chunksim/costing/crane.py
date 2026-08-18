"""Repairing a Port Piscarilius fishing crane, which pays two skills at once.

**Every term is published and one is spent twice.** `Fishing Crane` carries a
`{{Skilling success chart}}` and states the rest in prose, so nothing here is
fitted:

| Term | Where | Value |
|---|---|---|
| attempt cadence | "made on the first tick, and then every ten ticks thereafter" | 10 ticks |
| success curve | `{{Skilling success chart}}` | `low1=41`, `high1=76`, `req1=30` |
| what the curve reads | "whichever is higher" of Crafting and Construction | `max` of the two |
| experience | "four times their Crafting level and four times their Construction level" | `4 x level`, *each* |
| nails | "you lose nine nails and three planks" | 9 a repair |
| bent nails | "Each failed attempt will lead to one nail being bent" | 1 a failure |
| planks | as above | 3 a repair |

**The curve check is real rather than an identity.** The chart's parameters and
the page's prose are two separate statements, and `gathering.success_chance`
turns the first into the second: 20.31% at level 30 and 30.08% at 99, against
the page's "approximately 20%" and "30%". Nothing here was tuned to make that
happen - the same function reads every other skilling chart in the project.

### One success is one repair, which is not obvious

"At least nine nails are required" reads as nine placements, and it is not:
"If they succeed in repairing it, the crane is fixed on the same tick they made
the attempt, immediately rewarding experience", and "once you do receive the
experience for a successful crane repair, you lose nine nails and three planks".
So a repair is **one** roll of the curve, and the nine nails are its price
rather than its length. A failure costs one bent nail and ten more ticks.

### Why the loop is continuous

A repaired crane takes 30 to 60 seconds to break again, and there is a seven
tick floor between attempts on different cranes. Neither binds: **the regime is
world-hopped**, the same answer `costing/wintertodt.py` gives for the same
question - hop to a world whose crane is already broken rather than stand
waiting for this one. The seven ticks are shorter than the ten an attempt takes
anyway, so switching never costs more than staying.

That makes the figure below a *ceiling* in the one way this cannot check: it
assumes a broken crane is always a hop away, and prices no hop. The hop itself
is why `costing/wintertodt.py` carries `GAMES_PER_HOUR` rather than a pure tick
count; here the crane's own 30-60 second timer is long against the ~20 seconds
a repair takes, so a player really is hopping most cycles.

### The materials are charged, and that is most of the answer

Nine nails and three planks a repair is not free - `Plank[+]` resolves to the
cheapest plank the map can make, which is a log chopped and a sawmill fee, and
that dominates. Charged **inside the rate** rather than through
`Heuristics.material_seconds_per_xp`, for a reason particular to this method:
that table is keyed by task alone, and upstream files *one* task name under
both skills, so a single entry would have to serve two different
experience-per-repair figures (`4 x Crafting` against `4 x Construction`) and
would be wrong for whichever skill it was not computed against. Folding the
cost into each skill's own rate keeps the two honest and independent.

Pure: the levels and the item walk come in as arguments.
"""

from __future__ import annotations

from typing import Callable, Mapping

from chunksim.costing.gathering import CONFIRMED, CURVE_STEPS, success_chance
from chunksim.costing.heuristics import ComputedMethod

#: Ticks between attempts - "made on the first tick, and then every ten ticks
#: thereafter". A failure buys ten more of them and nothing else.
ATTEMPT_TICKS = 10.0

TICK_SECONDS = 0.6

#: `{{Skilling success chart}}`'s `low1`/`high1`, and the `req1` the chart and
#: upstream's own `Level` agree on.
CURVE: tuple[float, float] = (41.0, 76.0)
OPENS_AT = 30

#: Experience a success pays, per level, **in each skill separately**.
XP_PER_LEVEL = 4.0

#: What a *successful* repair consumes, whatever it took to get there.
NAILS_PER_REPAIR = 9.0
PLANKS_PER_REPAIR = 3.0

#: The export's own names for them, `[+]` and all: the walk resolves a family
#: to its cheapest member, which is the right reading of "planks of the same
#: type" where the wiki offers oak, teak and mahogany.
NAIL_ITEM = "Nails[+]"
PLANK_ITEM = "Plank[+]"

#: Upstream files one task name under both skills, each requiring the other at
#: 30 - see the module docstring on why that forces materials into the rate.
TASK = "Repair a crane at ~|Port Piscarilius|~"
SKILLS: tuple[str, ...] = ("Construction", "Crafting")

#: What the band is called wherever a rate is shown.
METHOD = "Fishing Crane (world-hopped)"


def chance(gate_level: int) -> float:
    """The success rate at `gate_level`, which is the higher of the two skills."""
    return success_chance(max(gate_level, OPENS_AT), *CURVE)


def attempts_per_repair(gate_level: int) -> float:
    """Expected attempts to land one repair - a geometric mean, `1/p`."""
    found = chance(gate_level)
    return 1.0 / found if found > 0 else 0.0


def nails_per_repair(gate_level: int) -> float:
    """Nine, plus one bent for every attempt that was not the last."""
    return NAILS_PER_REPAIR + max(attempts_per_repair(gate_level) - 1.0, 0.0)


def repair_seconds(gate_level: int) -> float:
    """Seconds of *attempting* per repair, before materials."""
    return attempts_per_repair(gate_level) * ATTEMPT_TICKS * TICK_SECONDS


def rate_at(
    skill_level: int,
    gate_level: int,
    material_seconds: Callable[[str, float], float | None] | None = None,
) -> float:
    """Experience an hour this pays a skill at `skill_level`.

    `gate_level` is the higher of Crafting and Construction, which is what the
    curve reads; `skill_level` is the one being paid, which is what the
    experience scales on. They are the same number only when the player's two
    levels are.

    `material_seconds` prices the nails and planks into the cycle. Omitted, the
    figure is the attempting alone - a ceiling, and the one this module's own
    tests pin, since a walk is a property of a map rather than of the game.
    """
    seconds = repair_seconds(gate_level)
    if seconds <= 0:
        return 0.0
    if material_seconds is not None:
        nails = material_seconds(NAIL_ITEM, nails_per_repair(gate_level))
        planks = material_seconds(PLANK_ITEM, PLANKS_PER_REPAIR)
        if nails is None or planks is None:
            # **No route to a nail is no rate**, the same refusal
            # `recipe_rates.rate_for` makes: tick-math over inputs nothing can
            # price is a made-up number.
            return 0.0
        seconds += nails + planks
    return XP_PER_LEVEL * skill_level * 3600.0 / seconds


def methods(
    valid: Mapping[str, Mapping[str, object]],
    levels: Mapping[str, int],
    material_seconds: Callable[[str, float], float | None] | None = None,
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{skill: bands}` for whichever of the two skills the map can reach.

    **Banded on the skill's own level, with the gate read at each point.** The
    experience scales on the skill being trained and the chance on the higher
    of the two, so a Construction climb past its Crafting level starts moving
    the curve as well as the payout - which is why this is a band per step
    rather than one number.
    """
    found: dict[str, tuple[ComputedMethod, ...]] = {}
    for skill in SKILLS:
        if TASK not in (valid.get(skill) or {}):
            continue
        other = max(levels.get(name, 1) for name in SKILLS if name != skill)
        banded = tuple(
            ComputedMethod(
                method=METHOD,
                xp_per_hour=rate,
                level=step,
                match=CONFIRMED,
                knob=f"training/{TASK}/{skill}",
            )
            for step in (OPENS_AT, *(s for s in CURVE_STEPS if s > OPENS_AT))
            if (rate := rate_at(step, max(step, other), material_seconds)) > 0
        )
        if banded:
            found[skill] = banded
    return found
