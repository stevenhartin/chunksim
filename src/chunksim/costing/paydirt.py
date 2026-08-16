"""What a Motherlode Mine ore really costs, which is not one pay-dirt.

**A challenge that names an `Output` it does not reliably hand over.** The
export carries `Obtain ~|runite ore|~ from pay-dirt` with `Output: Runite ore`
and no stated pace, so `estimate._route_hours` priced it at
`DEFAULT_ACTION_SECONDS` - the item walk believed pay-dirt produced runite ore
every 3.5 seconds. That made a runite bar cheaper than an adamantite one
(14.0s against 65.0s), which is the inversion that gave it away, and it fed
every mithril, adamantite and runite recipe in the project.

The guard for exactly this is already in `_route_hours` - "only where the pace
is stated rather than defaulted" - but it fires on `Output != item`, and here
the output *is* the item.

**Both halves of the real answer are published**, and the second is a chart
this project already knows how to read:

- how fast a pay-dirt is mined, from `Pay-dirt`'s own success chart, which the
  gathering model already prices as `Mine ~|pay-dirt|~`'s seconds per resource;
- which ore a pay-dirt turns out to be, from a **second** chart on the same
  page - six series with `cascade=yes`, one per ore.

### The cascade

`cascade=yes` is the mechanic Mod Ash describes: "pay-dirt rolls for each ore
in descending order, starting from the top tier you're eligible to get". So an
ore's chance is its own roll times the chance every higher-priority roll
failed, and coal's series is `226/325` - always true - which makes it the
remainder rather than a seventh outcome.

It reproduces the wiki's published percentages at level 99 on five of six:

    golden nugget    3.12%   published 3.13%
    runite ore       2.27%   published 2.27%
    adamantite ore  18.85%   published 18.18%
    mithril ore     26.93%   published 26.93%
    gold ore        24.22%   published 24.22%
    coal            24.60%   published 24.6%

and they sum to exactly 100%. **The sixth is the page disagreeing with
itself**: 18.85 is what its own chart gives, and 18.18 appears only in a
sentence of prose beside it. The chart is followed.

### Why this is a `Mining` fact and not a Smithing one

Nothing here is about the Foundry. What it fixes is the price of three *ores*,
which is why it sits beside the gathering model and feeds `action_seconds` -
the same seam `gathering.priced_methods` uses to tell the item walk what a log
costs. Measured at 99 Mining, a runite ore goes from 3.5 seconds to roughly
880, which is the difference between a rune bar being cheaper than an adamant
one and being what it is.

Pure: the level and the pay-dirt's own cost come in as arguments.
"""

from __future__ import annotations

from typing import Mapping

from chunksim.costing.gathering import success_chance

#: The export's challenge for mining pay-dirt, whose seconds-per-resource the
#: gathering model already computes.
PAYDIRT_TASK = "Mine ~|pay-dirt|~"

#: Ore -> the export's `Obtain ... from pay-dirt` challenge. Only three, which
#: is upstream's choice: coal, gold and the nugget have no such challenge.
OBTAIN: dict[str, str] = {
    "Mithril ore": "Obtain ~|mithril ore|~ from pay-dirt",
    "Adamantite ore": "Obtain ~|adamantite ore|~ from pay-dirt",
    "Runite ore": "Obtain ~|runite ore|~ from pay-dirt",
}

#: `(ore, low, high, Mining level)` in **cascade order**, off the second chart
#: on `Pay-dirt`. The order is the mechanic, not presentation: each is rolled
#: only if everything above it failed.
CASCADE: tuple[tuple[str, float, float, int], ...] = (
    ("Golden nugget", 7.0, 7.0, 30),
    ("Runite ore", -20.0, 5.0, 85),
    ("Adamantite ore", -90.0, 50.0, 70),
    ("Mithril ore", -19.0, 90.0, 55),
    ("Gold ore", -40.0, 126.0, 40),
    # `226/325` clamps to certainty at every level, which is what makes coal
    # the remainder rather than a seventh outcome.
    ("Coal", 226.0, 325.0, 30),
)


def ore_chances(level: int) -> dict[str, float]:
    """Every outcome's share of one pay-dirt at `level`, summing to one.

    A series below its own Mining requirement is not rolled at all, which is
    why a level-70 player gets no runite and a level-50 one no adamantite.
    """
    found: dict[str, float] = {}
    survives = 1.0
    for ore, low, high, needs in CASCADE:
        if level < needs:
            continue
        chance = success_chance(level, low, high)
        found[ore] = survives * chance
        survives *= 1.0 - chance
    return found


def ore_chance(ore: str, level: int) -> float:
    """One outcome's share of a pay-dirt, or `0.0` where it cannot happen."""
    return ore_chances(level).get(ore, 0.0)


def action_seconds(
    paydirt_seconds: float, level: int
) -> dict[str, float]:
    """`{challenge: seconds}` for each `Obtain ... from pay-dirt`.

    One ore costs however long a pay-dirt takes, divided by the chance that
    pay-dirt turns out to be this ore. An ore the level cannot reach is
    omitted rather than priced at infinity - the item walk reads a missing
    entry as "no stated pace", which is the honest answer and the one that
    keeps it off the default.
    """
    if paydirt_seconds <= 0:
        return {}
    chances = ore_chances(level)
    return {
        task: paydirt_seconds / chances[ore]
        for ore, task in OBTAIN.items()
        if chances.get(ore, 0.0) > 0.0
    }


def timed(
    gathering_seconds: Mapping[str, float], level: int
) -> dict[str, float]:
    """The entries to merge into `Heuristics.action_seconds`, or `{}`.

    Takes the gathering model's own `Mine ~|pay-dirt|~` figure rather than
    recomputing it, so the two cannot drift: one model owns how fast a
    pay-dirt is mined and this owns what comes out of it.
    """
    paydirt = gathering_seconds.get(PAYDIRT_TASK)
    if paydirt is None:
        return {}
    return action_seconds(paydirt, level)
