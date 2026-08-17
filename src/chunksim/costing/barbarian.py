"""Barbarian fishing's Strength and Agility, off the Fishing model's own rolls.

**One action paying three skills, and two of them were unpriced.** The
gathering walk already prices `Catch a ~|leaping trout|~` and its two siblings
for Fishing, cascade and all - the best fish is rolled first and each failure
falls through to the next (`gathering.SkillProfile.cascades`). The same catch
also pays Strength and Agility, and the export carries all three challenges a
second and third time under those skills, at their own lower requirements
(15/30/45 against Fishing's 48/58/70). Nothing priced them, so a map could
train Strength at the Barbarian Outpost and this would not know.

**Nothing new is modelled here; the existing rolls are read a second time.**
`_expected` walks the same cascade `gathering._cascade` does, with the same
curves and the same five-tick roll, and swaps only which experience column it
sums. So the Fishing rate this reproduces is *identical* to the node walk's -
38,224/hr at level 70, 48,768 at 99 - and the ancillary rate cannot drift from
it, because a divergence would have to come from the one arithmetic they share.

**The check is the wiki's own table, and it is a ratio rather than a level.**
`Barbarian Fishing` publishes an AFK column of Fishing experience beside a
Strength/Agility column, and their ratio runs 0.090 to 0.092 from level 48 to
99. This computes **0.089 at every level**, which is the agreement worth
having: the absolute figures differ because this project's Fishing model is
more conservative than the guide's (38,224 against 48,000 at level 70), and
that disagreement is inherited deliberately rather than patched here. What
this module claims is only that the ancillary skills are a fixed fraction of
whatever Fishing earns, and both sources say the same fraction.

**The level axis is Fishing's, not the skill being trained.** A catch pays
Strength 5-7 depending on which fish it was, and which fish it was depends on
the *Fishing* level - so the rate rises with Fishing and is flat in Strength.
Reading it at the Strength level would price a level-15 player at the
composition a level-99 Fisher gets. The Strength and Agility requirements are
so far below Fishing's that they never bind: 45 Strength for a sturgeon
against 70 Fishing.

**All three challenges share one rate**, for the reason `aerial.py` gives for
its four: they are the same action, and which fish a task names does not change
what an hour of it pays.

Pure: the tables and the level come in as arguments.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from chunksim.costing.gathering import (
    CONFIRMED,
    CURVE_STEPS,
    NodeRate,
    Tables,
    success_chance,
)

#: The cascade, best fish first. Same order and same names as
#: `gathering.SkillProfile.cascades` uses, because it is the same roll.
CASCADE: tuple[str, ...] = ("Leaping sturgeon", "Leaping salmon", "Leaping trout")

#: Experience one catch pays in the two ancillary skills, per fish. **A fixed
#: game figure, read off `Barbarian Fishing`'s experience table** - trout 5,
#: salmon 6, sturgeon 7, the same in both skills - and short enough to read,
#: like `skill_tables.BARRACUDA_RANKS`. Neither skill's calculator carries a
#: row for these, which is why there is nothing to scrape.
ANCILLARY_EXPERIENCE: dict[str, float] = {
    "leaping trout": 5.0,
    "leaping salmon": 6.0,
    "leaping sturgeon": 7.0,
}

#: The skills a catch pays besides Fishing. Fishing is deliberately absent:
#: the node walk already prices it, and pricing it twice would put two rates
#: on one task.
ANCILLARY_SKILLS: tuple[str, ...] = ("Strength", "Agility")

#: Ticks between rolls at a fishing spot. The `Fishing` profile's own figure -
#: net, bait, harpoon and cage all share it - repeated rather than imported so
#: this module needs no `SkillProfile`.
ROLL_TICKS = 5.0

#: One game tick, in seconds.
TICK_SECONDS = 0.6

#: The spot every barbarian challenge names.
BARBARIAN_NODE = "Fishing spot (barbarian)"

#: Fishing level the cheapest fish opens at, so the activity does.
OPENS_AT = 48


def _expected(tables: Tables, level: int) -> float:
    """Ancillary experience one roll pays on average, at Fishing `level`.

    The cascade `gathering._cascade` walks, summing the Strength/Agility column
    instead of the Fishing one. `0.0` when any member is missing a curve - half
    a cascade is a different cascade, which is the rule the gathering model
    already applies.
    """
    survive, expected = 1.0, 0.0
    for name in CASCADE:
        curves = tables.curves.get(name.lower())
        paid = ANCILLARY_EXPERIENCE.get(name.lower())
        if not curves or paid is None:
            return 0.0
        chance = success_chance(level, curves[0][1], curves[0][2])
        expected += survive * chance * paid
        survive *= 1.0 - chance
    return expected


def methods(
    tables: Tables, valid: Mapping[str, Mapping[str, object]]
) -> dict[str, tuple[NodeRate, ...]]:
    """`{task: rates}` for barbarian fishing's Strength and Agility challenges.

    Empty when the map reaches none of them, or when the tables carry no curve
    for the cascade - the same refusal the node walk makes.
    """
    priced: dict[str, list[NodeRate]] = {}
    for skill in ANCILLARY_SKILLS:
        tasks = [
            task
            for task in (valid.get(skill) or {})
            if any(task == f"Catch a ~|{fish.lower()}|~" for fish in CASCADE)
        ]
        if not tasks:
            continue
        rates: list[NodeRate] = []
        for level in (OPENS_AT, *(step for step in CURVE_STEPS if step > OPENS_AT)):
            paid = _expected(tables, level)
            if paid <= 0:
                continue
            rates.append(
                NodeRate(
                    task="",
                    skill=skill,
                    # **The band opens at the *Fishing* level.** See the module
                    # docstring: the rate is flat in the skill being trained.
                    level=level,
                    xp_per_hour=paid * 3600.0 / (ROLL_TICKS * TICK_SECONDS),
                    experience=paid,
                    chance=1.0,
                    roll_seconds=ROLL_TICKS * TICK_SECONDS,
                    duty=1.0,
                    node=BARBARIAN_NODE,
                    tool="Barbarian rod",
                    provenance=CONFIRMED,
                )
            )
        for task in tasks:
            priced.setdefault(task, []).extend(
                [rate for rate in rates if rate.skill == skill]
            )
    return {task: tuple(rates) for task, rates in priced.items() if rates}
