"""Aerial fishing, which pays two skills and never misses.

**No success roll at all**, which is what makes this arithmetic rather than a
model: "Unlike Falconry, a catch is guaranteed each time the bird is sent."
What a level buys is not a better chance but a better *fish*, and the game
picks which one by a formula Mod Ash stated outright:

    X = (Fishing level x 2 + Hunter level) / 3
    roll = a random integer in [0, X)
    82+ -> greater siren, 67+ -> mottled eel, 52+ -> common tench, else bluegill

each subject to the catch's own two level requirements. So the method is one
activity whose payout is a *mix*, the same shape as Puro-Puro rather than as a
node - and like Puro-Puro it lives beside the gathering walk rather than in it.

**It pays Fishing and Hunter at once**, which nothing else here does, and the
per-catch figures for both come off the `Aerial fishing` creature table because
neither skill's calculator carries a row for these at all. That absence is why
the four catches were refused before this module: not for want of a chance -
there is none to want - but for want of an experience figure.

**Every input is published and the result checks at both ends.** The catch rate
is the wiki's own (`1,600 fish per hour`, stated in its rate chart's caption),
and the Hunter training guide independently says aerial fishing runs "between
25,000-80,000 Hunter experience per hour". This computes 26,400 at the bottom
and 82,311 at the top. Two figures from two pages agreeing to within 3% is the
strongest check any activity in `costing/` has.

**Levels are assumed to move together**, which is the wiki's own assumption for
the same arithmetic: its chart "assumes at each X the requirements for the
applicable fish are met, meaning Fishing and Hunter levels are close together".
A map whose two levels are far apart is priced as though the trailing one had
caught up, which is optimistic - and stated here rather than buried, because it
is the one place this module guesses at anything.

Pure: the table and the level come in as arguments.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Mapping, Sequence

from chunksim.costing.gathering import CONFIRMED, CURVE_STEPS, NodeRate, Tables

#: The object every aerial challenge names, under both skills.
AERIAL_NODE = "Fishing spot (aerial fishing)"

#: The skills a catch pays, and the export challenges that name it in each.
AERIAL_SKILLS = ("Fishing", "Hunter")

#: `roll` thresholds, best fish first. Mod Ash, 13 June 2019.
THRESHOLDS: tuple[tuple[int, str], ...] = (
    (82, "Greater siren"),
    (67, "Mottled eel"),
    (52, "Common tench"),
)

#: The fish every roll falls through to.
DEFAULT_FISH = "Bluegill"

#: Catches an hour. **The wiki's own figure**, from the caption of its aerial
#: fishing rate chart, and the number that makes this reproduce the training
#: guide's stated range at both ends.
CATCHES_PER_HOUR = 1600.0


def roll_ceiling(fishing: int, hunter: int) -> int:
    """`X` in Mod Ash's formula: the exclusive top of the roll."""
    return (fishing * 2 + hunter) // 3


def catch_mix(
    fish: Sequence[tuple[str, int, float, int, float]], fishing: int, hunter: int
) -> dict[str, float]:
    """What share of catches is each fish, at these two levels.

    Walked roll by roll rather than solved, because the thresholds interact
    with each fish's own requirements: a player who can roll 82 but cannot yet
    *catch* a siren falls through to the next one it qualifies for, and that is
    the "very small chance for newly unlocked fish" the page describes.
    """
    ceiling = roll_ceiling(fishing, hunter)
    if ceiling < 1:
        return {}
    allowed = {
        name: fishing >= fish_level and hunter >= hunt_level
        for name, fish_level, _fx, hunt_level, _hx in fish
    }
    if not allowed.get(DEFAULT_FISH):
        return {}
    counts: dict[str, int] = {}
    for roll in range(ceiling):
        chosen = DEFAULT_FISH
        for threshold, name in THRESHOLDS:
            if roll >= threshold and allowed.get(name):
                chosen = name
                break
        counts[chosen] = counts.get(chosen, 0) + 1
    return {name: count / ceiling for name, count in counts.items()}


def experience_per_catch(
    fish: Sequence[tuple[str, int, float, int, float]],
    mix: Mapping[str, float],
    skill: str,
) -> float:
    """The blended experience one catch pays in `skill`."""
    column = 2 if skill == "Fishing" else 4
    return sum(
        share * float(row[column]) for row in fish for name, share in mix.items()
        if row[0] == name
    )


def methods(
    tables: Tables, valid: Mapping[str, Mapping[str, object]]
) -> dict[str, tuple[NodeRate, ...]]:
    """`{task: rates}` for every aerial challenge a map can reach.

    **One rate per skill, applied to all four of that skill's challenges**, for
    the reason barbarian fishing's three share one: they are the same action,
    and which fish a task names does not change what an hour of it pays.
    """
    fish = tables.aerial_fish
    if not fish:
        return {}
    # **Keyed by task, and a task belongs to two skills here.** The export
    # carries `Catch a ~|bluegill|~` under Fishing *and* under Hunter, so both
    # skills' rates go under the one key and `banded_methods` groups them by
    # `NodeRate.skill` as it does everywhere else. Writing per skill overwrote
    # one with the other and lost Fishing entirely.
    priced: dict[str, list[NodeRate]] = {}
    for skill in AERIAL_SKILLS:
        tasks = [
            task
            for task in (valid.get(skill) or {})
            if any(task == f"Catch a ~|{row[0].lower()}|~" for row in fish)
            or any(task == f"Catch an ~|{row[0].lower()}|~" for row in fish)
        ]
        if not tasks:
            continue
        # **Both requirements, because both must be met.** Levels move
        # together here, so the activity opens at the higher of the pair the
        # cheapest catch asks for - 43 Fishing against 35 Hunter, so 43.
        opens = max(
            (max(int(row[1]), int(row[3])) for row in fish if row[0] == DEFAULT_FISH),
            default=1,
        )
        rates: list[NodeRate] = []
        for level in (opens, *(step for step in CURVE_STEPS if step > opens)):
            # Both levels together - see the module docstring on why.
            mix = catch_mix(fish, level, level)
            if not mix:
                continue
            paid = experience_per_catch(fish, mix, skill)
            if paid <= 0:
                continue
            rates.append(
                NodeRate(
                    task="",
                    skill=skill,
                    level=level,
                    xp_per_hour=paid * CATCHES_PER_HOUR,
                    experience=paid,
                    chance=1.0,
                    roll_seconds=3600.0 / CATCHES_PER_HOUR,
                    duty=1.0,
                    node=AERIAL_NODE,
                    tool="Cormorant",
                    provenance=CONFIRMED,
                )
            )
        for task in tasks:
            priced.setdefault(task, []).extend(
                replace(rate, task=task) for rate in rates
            )
    return {task: tuple(rates) for task, rates in priced.items()}
