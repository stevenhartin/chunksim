"""Pickpocketing, where the wiki publishes the whole mechanic as an equation.

**A flat 3.5-second cycle was standing in for a curve, and it is 2x to 3.6x
too fast.** `heuristics.PICKPOCKET_CYCLE_SECONDS` was calibrated against one
published figure - a Knight of Ardougne at level 55, 86,000 xp/hr - and its own
comment said what was wrong with that: "success rate climbs with level and one
constant cannot follow it". What it did not say is that the published figure
assumes gear. `Thieving training` states it outright: those rates "assume the
player has completed the **medium Ardougne Diary** and is **using dodgy
necklaces**", which are a +10% success rate and a 25% chance to shrug off the
stun. Neither is a thing a chunk map necessarily has.

### The equation is the wiki's own

The `Thieving` page writes it: "every pickpocket will take on average
`2 + 8(1-p)` ticks (based on the success chance, p), [so] the actual amount of
pickpockets in n ticks will be `np/(10-8p)`". Both figures behind it are
published too - `Stun (status)` states the failure lockout as **8 ticks
(4.8 seconds)**, and `Thieving training` gives the never-failing rate for a
knight as 252,900 xp/hr, which at 84.3 experience is 3,000 an hour and so
exactly a **2-tick** attempt.

### Three checks, and the model is not fitted to any of them

Reproducing the published Knight of Ardougne figures needs the *geared* curve
and the necklace, so it is a check on the whole mechanic rather than on the
part this actually spends:

    level 55, medium diary, dodgy necklace   84,630   published 86,000
    level 95, tick-perfect                  252,900   published 252,900
    the level failing stops, medium diary         95   published 95

The middle one is arithmetic and the outer two are not. The third is the
sharpest: `success_chance(94, 55, 264)` is 254/256 and `success_chance(95, ...)`
is the first to reach certainty, which is the level the page names.

### What this spends instead

`low1`/`high1` - the **plain** series, no gloves, no diary, no cape. A chunk map
may hold none of them and the estimate is about this map. Against the geared
published figure that is 30% lower at level 55 (60,141 against 86,000), which is
the usual shape here: a guide is evidence about the action and a model is
evidence about the action plus the map.

### Seven NPCs are refused rather than guessed

The wiki charts eighteen of its twenty-five pickpocketable rows. The other seven
- the digsite workman, the villager, the cave goblin, the Fremennik citizen, the
two Pollnivneach bandits and the pirate - have a `{{Thieving info}}` box and no
success chart anywhere, so nothing published says how often they fail.

**They keep no rate at all.** Borrowing a median from the eighteen was
considered and refused on the spread: at their own opening level those run from
**0.344** (an elf) to **0.707** (a man), a factor of two in chance and more than
that in rate, so a median is not evidence about any one of them. It is the same
call `costing/shortcuts.py` makes for the 37 shortcuts whose join nothing here
can verify, and the cost is stated rather than hidden: the reference map loses
its cave-goblin band and the every-rollable-chunk map its Fremennik-citizen one,
both of which were quoting a number this module now has positive evidence is
roughly twice the truth.

Pure: the curves arrive as an argument (`Heuristics.pickpockets`).
"""

from __future__ import annotations

from typing import Any, Mapping

from chunksim.costing.gathering import CURVE_STEPS, success_chance
from chunksim.costing.heuristics import ComputedMethod

#: What a band calls the activity.
ACTIVITY = "pickpocketing"

#: What this labels its rates.
PICKPOCKET_MATCH = "modelled"

#: The skill it pays.
SKILL = "Thieving"

#: Ticks one attempt takes when it succeeds. **Published**, by way of the
#: never-failing rate: `Thieving training` gives a Knight of Ardougne at 100%
#: as 252,900 xp/hr, which at 84.3 experience is 3,000 an hour.
ATTEMPT_TICKS = 2.0

#: Ticks a failure locks pickpocketing out for. **Published** on
#: `Stun (status)`: "prevented from further pickpocket attempts for 8 ticks
#: (4.8 seconds)". Movement is barred for nine, which does not matter here.
STUN_TICKS = 8.0

#: Ticks in an hour.
TICKS_PER_HOUR = 6000.0


def attempt_ticks(chance: float, stun_resist: float = 0.0) -> float:
    """Ticks one attempt costs on average at success chance `chance`.

    The `Thieving` page's own `2 + 8(1-p)`. `stun_resist` is the chance a
    failure is shrugged off - a dodgy necklace is 0.25 - and is **zero by
    default** because a necklace is an item this project does not assume. It
    exists so the published figures can be reproduced as a check.
    """
    return ATTEMPT_TICKS + STUN_TICKS * (1.0 - chance) * (1.0 - stun_resist)


def xp_per_hour(
    experience: float, level: int, low: float, high: float, stun_resist: float = 0.0
) -> float:
    """Thieving experience an hour pickpocketing one NPC at `level`.

    `np / (10 - 8p)` successes an hour, each worth `experience`, which is the
    page's own formula with the two ticks and the eight substituted back in.
    """
    chance = success_chance(level, low, high)
    ticks = attempt_ticks(chance, stun_resist)
    if ticks <= 0 or experience <= 0:
        return 0.0
    return TICKS_PER_HOUR * chance / ticks * experience


def steps_for(level: int, low: float, high: float) -> tuple[int, ...]:
    """The levels an NPC available from `level` changes rate at.

    Its own, `gathering.CURVE_STEPS` above it, and the level the curve reaches
    certainty at if that is not already one of them - which is a real corner of
    the rate rather than a tenth level, and the one the wiki names for a
    knight.
    """
    above = tuple(step for step in CURVE_STEPS if step > level)
    certain = next(
        (point for point in range(level, 100) if success_chance(point, low, high) >= 1.0),
        None,
    )
    found = {level, *above}
    if certain is not None:
        found.add(certain)
    return tuple(sorted(found))


def methods(
    challenges: Mapping[str, Any],
    valid: Mapping[str, Any],
    curves: Mapping[str, tuple[int, float, float, float]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{skill: bands}` for every NPC a map can pickpocket *and* the wiki charts.

    Bands rather than one rate, because the whole point is that the chance
    climbs: a Knight of Ardougne is 60,141/hr at 55 and 252,900 at 95.
    """
    found: list[ComputedMethod] = []
    for task in sorted(valid or {}):
        challenge = challenges.get(task)
        if not isinstance(challenge, dict) or challenge.get("Primary") is not True:
            continue
        charted = _charted(challenge, curves)
        if charted is None:
            continue
        level, experience, low, high = charted
        found.extend(
            ComputedMethod(
                method=ACTIVITY,
                xp_per_hour=xp_per_hour(experience, step, low, high),
                level=step,
                match=PICKPOCKET_MATCH,
                knob=f"training/{task}/{SKILL}",
            )
            for step in steps_for(level, low, high)
        )
    return {SKILL: tuple(found)} if found else {}


def charted_tasks(
    challenges: Mapping[str, Any],
    valid: Mapping[str, Any],
    curves: Mapping[str, tuple[int, float, float, float]],
) -> frozenset[str]:
    """Pickpocket challenges the wiki publishes a success chart for."""
    return frozenset(
        task
        for task in valid or {}
        if isinstance(challenges.get(task), dict)
        and _charted(challenges[task], curves) is not None
    )


def refuse_uncharted(
    training: Mapping[str, dict[str, Any]],
    curves: Mapping[str, tuple[int, float, float, float]],
    challenges: Mapping[str, Any],
    valid: Mapping[str, Any],
    pinned: frozenset[str] = frozenset(),
    refused: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Strip the flat-cycle rate from a pickpocket nothing charts.

    **The flat rate is not a worse estimate, it is a known-wrong one.** On
    every one of the eighteen NPCs that can be checked it runs 2x to 3.6x fast,
    so leaving it on the seven that cannot is quoting a number this module has
    evidence against. What is left is no rate, which the 1,000/hr floor already
    says is "nothing priced this".

    A hand pin survives, as everywhere: `overrides.json` is the top of the
    layering and somebody who has measured a cave goblin outranks this.

    **`refused` collects what was taken away and why**, because the absence
    that is left is a decision rather than a gap and the report has to be able
    to tell them apart - see `coverage.REFUSED`. That is the correction to the
    sentence above: the 1,000/hr floor says "nothing priced this", which is
    the one reading this refusal exists to deny.
    """
    charted = charted_tasks(challenges, valid, curves)
    kept: dict[str, dict[str, Any]] = {}
    for task, per_skill in training.items():
        rate = per_skill.get(SKILL)
        drop = (
            rate is not None
            and getattr(rate, "source", "") == UNCHARTED_SOURCE
            and task not in charted
            and task not in pinned
        )
        if not drop:
            kept[task] = per_skill
            continue
        if refused is not None:
            refused[task] = REASON
        rest = {skill: value for skill, value in per_skill.items() if skill != SKILL}
        if rest:
            kept[task] = rest
    return kept


#: Why a stripped NPC keeps no rate, printed beside it by `chunksim training`.
#: One sentence for all seven: they share the reason exactly.
REASON = "no success chart, and the flat cycle runs 2x-3.6x fast where checked"


#: `Rate.source` the flat-cycle scrape writes, and the only source this will
#: take away. A money-making guide about one NPC is a different claim and is
#: left alone.
UNCHARTED_SOURCE = "wiki:pickpockets"


def _charted(
    challenge: Mapping[str, Any], curves: Mapping[str, tuple[int, float, float, float]]
) -> tuple[int, float, float, float] | None:
    """The curve for the NPC a challenge names, or `None`.

    Joined on the export's own `NPCs`, which is where the name lives and is a
    structural join rather than a read of the task's words.
    """
    for npc in challenge.get("NPCs") or ():
        if not isinstance(npc, str):
            continue
        found = curves.get(npc) or _folded(npc, curves)
        if found is not None:
            return found
    return None


def _folded(
    npc: str, curves: Mapping[str, tuple[int, float, float, float]]
) -> tuple[int, float, float, float] | None:
    """A case-insensitive lookup, since upstream writes `Fremennik citizen`
    where the wiki's table writes `Fremennik Citizen`."""
    wanted = npc.lower()
    return next((value for name, value in curves.items() if name.lower() == wanted), None)
