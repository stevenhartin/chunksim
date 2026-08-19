"""Vale Totems, a Fletching minigame that pays a little Construction too.

**Two published tables, and this module is the arithmetic between them.**
`Vale Totems/Strategies` states the per-totem experience by log type and the
Construction experience by level, and both close exactly:

| Log | Fletching | Build/carve | Decorate | Per totem | Published |
|---|---|---|---|---|---|
| Oak | 20 | 12.5 | 51.2 | 254.8 | 254.8 |
| Willow | 35 | 31.7 | 126.9 | 634.4 | 634.4 |
| Maple | 50 | 50.8 | 201 | 1,007.2 | 1,007.2 |
| Yew | 65 | 82.6 | 326.2 | 1,635.2 | 1,635.2 |
| Magic | 80 | 156.1 | 619.8 | 3,103.6 | 3,103.6 |
| Redwood | 90 | 221.3 | 725.5 | 3,787.2 | 3,787.2 |

The per-totem column is **`4 x (build/carve + decorate)`** and the page says
why: "the result of the building action, three carvings, and four
decorations" - four building/carving actions and four decorations, all six
rows to the tenth of an experience point.

**Construction is one experience point per level, per totem built.** "When
building a totem, the player receives one Construction experience point per
level, e.g., 70XP at level 70, unaffected by totem type." Its published
per-hour table is `104 x level` on all nine rows, 1 through 99 - which is
where `TOTEMS_PER_HOUR` comes from, and it agrees with the page's own "13
loops (104 totems) per hour as a standard for comparison".

**The Fletching per-hour table checks the same constant, and catches a typo.**
`104 x` the per-totem column reproduces five of its six rows exactly; redwood
is published as 393,686.8 where the arithmetic gives **393,868.8**, a digit
transposition on the wiki rather than a disagreement about the mechanic. The
other five agreeing to the decimal is what makes that readable as a typo.

### What this charges that the published figure does not

Every rate above assumes the logs and decorations were **bought**: the
calculator's own assumptions say "all logs and bow strings are purchased from
GE". A chunk map cannot, so `LOGS_PER_TOTEM` five - "one to build the totem
and four fletched items for decorations" - is charged through the item walk,
and at 104 totems an hour that is 520 logs an hour. It is usually the binding
constraint and always the larger term: chopping is slower than the minigame.

**What is excluded on both sides is fletching the decorations.** Doing that
during the loop costs time and pays its own ordinary Fletching experience, and
the page prices the pair together - "slightly lower for fletching, and possibly
around 10-15% lower rates if both fletching and stringing". Charging the raw
log without crediting the fletch is the conservative half of that, and the
honest description of this rate is *the minigame's own experience for the
minigame's own actions*.

### The two skills want different logs

Fletching's payout scales hard with the log - redwood is fifteen times oak -
so it wants the best tier its level allows. Construction's does not scale with
the log **at all**, so it wants the *cheapest*: oak, whatever the player's
Fletching level. That is why `rate_at` picks per skill rather than sharing one
answer, and it is the same shape as `costing/crane.py`'s two skills reading
different levels.

**The Construction gate is the Fletching one.** Upstream gives its Construction
challenge `Level: 1`, because what actually gates the minigame is Fletching 20
and the miniquest - so a rate written against that level would offer it to a
player who cannot enter, which is `costing/gotr.py`'s lesson and
`costing/wintertodt.py`'s. The Fletching challenge's own validity is the gate,
and the Construction one additionally needs a house, which upstream states as
a `Player-owned house` chunk and the derivation already enforces.

Pure: the levels and the item walk come in as arguments.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from chunksim.costing.gathering import CONFIRMED, CURVE_STEPS
from chunksim.costing.heuristics import ComputedMethod

#: Totems built an hour: "13 loops (104 totems) per hour as a standard for
#: comparison", and the constant the Construction table divides out exactly.
TOTEMS_PER_HOUR = 104.0

#: "Each complete totem requires five logs (one to build the totem and four
#: fletched items for decorations)."
LOGS_PER_TOTEM = 5.0

#: Construction experience a build pays, per level of Construction.
CONSTRUCTION_XP_PER_LEVEL = 1.0


@dataclass(frozen=True)
class Totem:
    """One log tier: what it needs, and what its actions pay Fletching."""

    log: str
    requirement: int
    #: Experience for *each* of the build and the three carvings.
    build_carve: float
    #: Experience for *each* of the four decorations.
    decorate: float
    #: Vale offerings one totem's ent visit leaves. **The per-totem column**,
    #: not the hourly one beside it - see `TOTEMS` for why they disagree.
    offerings: float

    @property
    def fletching_xp(self) -> float:
        """One totem end to end - four building/carving actions, four
        decorations. Reproduces the page's own total column exactly."""
        return 4.0 * (self.build_carve + self.decorate)


#: `Vale Totems/Strategies`' "Base Totem XP and Offerings", cheapest first.
#:
#: **The offerings column is per totem, and the page's hourly one beside it
#: disagrees with the page.** That table divides by **112** on every row -
#: 20 x 112 is 2,240, 105 x 112 is 11,760 - where the prose says "13 loops
#: (104 totems) per hour as a standard for comparison" and the Construction
#: table divides out to exactly 104 on all nine of its rows. So the per-totem
#: figure is the primitive and `TOTEMS_PER_HOUR` is this file's own constant
#: for both, which is also the conservative reading of the two.
TOTEMS: tuple[Totem, ...] = (
    Totem("Oak logs", 20, 12.5, 51.2, 20.0),
    Totem("Willow logs", 35, 31.7, 126.9, 30.0),
    Totem("Maple logs", 50, 50.8, 201.0, 40.0),
    Totem("Yew logs", 65, 82.6, 326.2, 65.0),
    Totem("Magic logs", 80, 156.1, 619.8, 90.0),
    Totem("Redwood logs", 90, 221.3, 725.5, 105.0),
)

#: The Fletching level the minigame itself opens at, and the lowest totem's.
OPENS_AT = 20

TASKS: dict[str, str] = {
    "Fletching": "Participate in ~|Vale Totems|~ for Fletching xp",
    "Construction": "Participate in ~|Vale Totems|~ for Construction xp",
}

#: What the band is called wherever a rate is shown.
METHOD = "Vale Totems"


def seconds_per_totem(
    totem: Totem, material_seconds: Callable[[str, float], float | None] | None
) -> float | None:
    """One totem's whole cycle, logs included, or `None` with no route to them."""
    playing = 3600.0 / TOTEMS_PER_HOUR
    if material_seconds is None:
        return playing
    logs = material_seconds(totem.log, LOGS_PER_TOTEM)
    return None if logs is None else playing + logs


def _affordable(
    level: int, material_seconds: Callable[[str, float], float | None] | None
) -> list[tuple[Totem, float]]:
    """`(totem, seconds)` for every tier `level` allows that has a log route."""
    found = []
    for totem in TOTEMS:
        if totem.requirement > level:
            continue
        seconds = seconds_per_totem(totem, material_seconds)
        if seconds is not None and seconds > 0:
            found.append((totem, seconds))
    return found


def affordable(
    level: int, material_seconds: Callable[[str, float], float | None] | None
) -> list[tuple[Totem, float]]:
    """`_affordable`, exported for `costing/valeoffering.py`.

    The offerings a totem leaves are decided by the totem, so pricing one
    needs exactly the same "which tiers can this map build, and what does each
    cost once its five logs are charged" answer this file already computes.
    """
    return _affordable(level, material_seconds)


def fletching_rate(
    level: int, material_seconds: Callable[[str, float], float | None] | None = None
) -> float:
    """Fletching an hour at `level`, on the best tier it allows.

    **Best after the logs are charged**, which is not always the highest tier:
    redwood pays fifteen times oak and costs far more chopping, so which wins
    is a property of the map rather than of the minigame.
    """
    return max(
        (
            totem.fletching_xp * 3600.0 / seconds
            for totem, seconds in _affordable(level, material_seconds)
        ),
        default=0.0,
    )


def construction_rate(
    construction_level: int,
    fletching_level: int,
    material_seconds: Callable[[str, float], float | None] | None = None,
) -> float:
    """Construction an hour, which the log tier does not scale.

    So the **cheapest** affordable tier wins, where `fletching_rate` takes the
    most valuable - the two skills genuinely want different logs.
    """
    cheapest = min(
        (seconds for _, seconds in _affordable(fletching_level, material_seconds)),
        default=0.0,
    )
    if cheapest <= 0:
        return 0.0
    return CONSTRUCTION_XP_PER_LEVEL * construction_level * 3600.0 / cheapest


def methods(
    valid: Mapping[str, Mapping[str, object]],
    levels: Mapping[str, int],
    material_seconds: Callable[[str, float], float | None] | None = None,
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{skill: bands}` for whichever of the two the map can reach.

    **Both gate on the Fletching challenge**, which is upstream's own "can this
    map play the minigame" - see the module docstring on why its Construction
    twin's `Level: 1` is not one.
    """
    if TASKS["Fletching"] not in (valid.get("Fletching") or {}):
        return {}
    found: dict[str, tuple[ComputedMethod, ...]] = {}

    fletching = tuple(
        ComputedMethod(
            method=METHOD,
            xp_per_hour=rate,
            level=totem.requirement,
            match=CONFIRMED,
            knob=f"training/{TASKS['Fletching']}/Fletching",
        )
        for totem in TOTEMS
        if (rate := fletching_rate(totem.requirement, material_seconds)) > 0
    )
    if fletching:
        found["Fletching"] = fletching

    if TASKS["Construction"] in (valid.get("Construction") or {}):
        held = max(levels.get("Fletching", 1), OPENS_AT)
        banded = tuple(
            ComputedMethod(
                method=METHOD,
                xp_per_hour=rate,
                level=step,
                match=CONFIRMED,
                knob=f"training/{TASKS['Construction']}/Construction",
            )
            for step in (1, *CURVE_STEPS)
            if (rate := construction_rate(step, held, material_seconds)) > 0
        )
        if banded:
            found["Construction"] = banded
    return found
