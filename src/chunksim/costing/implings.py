"""Puro-Puro, priced as one method rather than as twelve.

**An impling is not a node and the loop model is the wrong shape for it.**
Every other gathering method is "stand at this thing and roll": one creature,
one chance, one interval. Impling hunting is the opposite - you do not choose
what you catch, the spawn tables choose for you, and what your level buys is
*which* of them you are allowed to keep and how much each is worth. So the
export's own `Catch implings in ~|Puro-Puro|~ after reaching 17 Hunter` is the
method, and the twelve `Catch a ~|baby impling|~` challenges are tasks that
happen to be completed while training it.

**Overworld implings are deliberately not a training method.** They spawn a few
dozen at a time across the whole of Gielinor on a thirty-minute server cycle;
you meet one by accident. Upstream says the same thing in its own vocabulary -
the wandering variants are `Primary: false` with `ForcedSecondary` - and this
module answers only for Puro-Puro, which the export gates behind
`Chunks: ["Puro-Puro"]`. A map that cannot reach it never sees the challenge,
so the gate costs nothing here: `derived.challenges.valid` has already applied
it.

**Everything below is read, not fitted.** The `Impling` article publishes the
four spawn-tier tables and how many points of each kind Puro-Puro has; the
calculator publishes experience per impling *specifically for Puro-Puro*, which
differs from the overworld figure and is much lower for the good ones (a magpie
is 44 there against 216 in Gielinor); the catch chances are ordinary
`{{Skilling success chart}}` curves. The one number from outside is the
butterfly-net interval, which `costing/gathering.py` fits against ruby harvest
and sapphire glacialis.

**No published figure checks the total**, which is worth knowing before
trusting it to two significant figures. It is arithmetic over published inputs -
the standing of Thieving's stalls rather than of Woodcutting's twelve-row
agreement - and it lands near 28,000/hr at 99, which is the region Puro-Puro is
generally quoted at.

The supply model, and the one simplification in it:

- an **invisible** spawn point respawns the moment its impling is caught and
  spends two minutes invisible, so each point can be harvested about thirty
  times an hour. Puro-Puro has 21 low-tier, 12 mid-tier and 2 high-tier points.
- the **fixed** spawns - 51 of them, respawning in 4.2 seconds, or 30 for earth
  and essence - make low-tier implings effectively unlimited, so they are
  modelled as a floor you can always fall back on rather than as a supply to
  count. That is the simplification, and it only ever *fills* time the better
  implings did not.

What is left is a knapsack over an hour: take the most valuable impling you can
catch, as many as the spawns provide, then the next, and spend whatever time is
left on the ones that never run out.

Pure: the tables and the level come in as arguments.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from chunksim.costing.gathering import (
    CURVE_STEPS,
    PROFILES,
    TICK_SECONDS,
    NodeRate,
    Tables,
    success_chance,
)

#: The export's own name for the method, which is also the reachability gate:
#: it carries `Chunks: ["Puro-Puro"]`, so it is only ever valid on a map that
#: holds the realm.
PURO_PURO_TASK = "Catch implings in ~|Puro-Puro|~ after reaching 17 Hunter"

#: Invisible spawn points in Puro-Puro, by the tier table each one rolls.
#: **Published on `Impling`**: "Of these 35 spawn points, there are 21 low-tier
#: spawns, 12 mid-tier spawns, and 2 high-tier spawns."
SPAWN_POINTS: Mapping[str, int] = {
    "Low-tier": 21,
    "Mid-tier": 12,
    "High-tier (Puro-Puro)": 2,
}

#: Seconds an invisible spawn spends before it can be caught. It "respawns
#: immediately upon capture" and then "roams for two minutes before
#: manifesting", so this is the whole cycle of one point.
INVISIBLE_SECONDS = 120.0

#: The tier whose implings the 51 fixed spawns keep topped up, so its supply is
#: not counted - see the module docstring.
UNLIMITED_TIER = "Low-tier"

#: Hunter level each impling needs, from the calculator's own rows. Held here
#: rather than read back out of `Tables.experience`, which keys on name alone
#: and has no level in it.
LEVELS: Mapping[str, int] = {
    "Baby impling": 17,
    "Young impling": 22,
    "Gourmet impling": 28,
    "Earth impling": 36,
    "Essence impling": 42,
    "Eclectic impling": 50,
    "Nature impling": 58,
    "Magpie impling": 65,
    "Ninja impling": 74,
    "Dragon impling": 83,
    "Lucky impling": 89,
}


def supply_per_hour(tables: Tables) -> dict[str, float]:
    """How many of each impling Puro-Puro's invisible points offer in an hour.

    The unlimited tier is left out entirely rather than given a large number:
    `puro_puro_rate` treats absence as "always available", which is what 51
    spawns on a 4.2-second respawn amount to.
    """
    found: dict[str, float] = {}
    per_point = 3600.0 / INVISIBLE_SECONDS
    for tier, points in SPAWN_POINTS.items():
        if tier == UNLIMITED_TIER:
            continue
        for impling, share in tables.spawn_tiers.get(tier, ()):
            found[impling] = found.get(impling, 0.0) + points * per_point * share
    return found


def puro_puro_rate(
    tables: Tables, level: int, roll_seconds: float
) -> tuple[float, dict[str, float]] | None:
    """`(xp per hour, catches per hour)` at `level`, or `None` if unpriceable.

    **Most valuable first, until the hour or the spawns run out.** A player does
    not queue for a lucky impling; they catch the best thing in front of them,
    and over an hour that is the same as taking the spawns in order of what they
    pay. The low tier never runs out, so it absorbs whatever time is left.

    `None` where the spawn tables or the experience figures are missing, which
    is a clone that has never run `chunksim gather-tables`.
    """
    experience = tables.experience.get("Hunter") or {}
    if not tables.spawn_tiers or not experience:
        return None
    supply = supply_per_hour(tables)
    unlimited = {name for name, _ in tables.spawn_tiers.get(UNLIMITED_TIER, ())}

    priced: list[tuple[float, float, str]] = []
    for impling, opens in LEVELS.items():
        if level < opens:
            continue
        entry = experience.get(impling.lower())
        curves = tables.curves.get(impling.lower())
        if entry is None or not curves:
            continue
        paid = entry[0]
        chance = success_chance(level, curves[0][1], curves[0][2])
        if paid <= 0 or chance <= 0:
            continue
        priced.append((paid, roll_seconds / chance, impling))
    if not priced:
        return None

    seconds = 3600.0
    total = 0.0
    caught: dict[str, float] = {}
    for paid, cost, impling in sorted(priced, reverse=True):
        if seconds <= 0:
            break
        available = seconds / cost if impling in unlimited else supply.get(impling, 0.0)
        take = min(available, seconds / cost)
        if take <= 0:
            continue
        caught[impling] = take
        total += take * paid
        seconds -= take * cost
    if total <= 0:
        return None
    return total, caught


#: The loop whose interval this is caught at - an impling is netted like a
#: butterfly, which is the one thing the two really do share, and
#: `costing/gathering.py` fits that interval against two butterflies.
PURO_PURO_LOOP = "Butterfly net"

#: The level the export's own challenge names: "after reaching 17 Hunter". The
#: challenge itself carries `Level: 1`, because what gates it is the realm
#: rather than the level, so the opening figure has to come from the name.
PURO_PURO_OPENS = 17


def methods(
    tables: Tables, valid: Mapping[str, Mapping[str, object]]
) -> dict[str, tuple[NodeRate, ...]]:
    """`{task: rates}` for Puro-Puro, or `{}` where the map cannot reach it.

    **The reachability gate is upstream's and costs nothing here.** The export
    puts `Chunks: ["Puro-Puro"]` on the challenge, so it is only ever in
    `valid` on a map that holds the realm - which is also the whole of "not a
    training method until you unlock Puro-Puro".

    Merged by `costing/inputs.py` rather than produced inside
    `gathering.priced_methods`, because this module imports that one and the
    dependency has to run one way. It also keeps the generic node walk free of
    a method that is not a node.
    """
    if PURO_PURO_TASK not in (valid.get("Hunter") or {}):
        return {}
    interval = PROFILES["Hunter"].roll_ticks_by_kind.get(PURO_PURO_LOOP)
    if not interval:
        return {}
    levels = (
        PURO_PURO_OPENS,
        *(step for step in CURVE_STEPS if step > PURO_PURO_OPENS),
    )
    found = puro_puro_methods(tables, levels, interval * TICK_SECONDS)
    return {PURO_PURO_TASK: found} if found else {}


def puro_puro_methods(
    tables: Tables, levels: Sequence[int], roll_seconds: float
) -> tuple[NodeRate, ...]:
    """The method priced at each level worth re-reading, for the band walk.

    Shaped as `NodeRate`s so `gathering.apply` and `gathering.banded_methods`
    handle this exactly as they handle a tree: the opening level's figure
    becomes the training rate and the rest becomes the climb. `chance` and
    `experience` are the *blended* ones - what an average catch cost and paid -
    since there is no single creature to report.
    """
    found: list[NodeRate] = []
    for level in levels:
        priced = puro_puro_rate(tables, level, roll_seconds)
        if priced is None:
            continue
        total, caught = priced
        catches = sum(caught.values())
        if catches <= 0:
            continue
        found.append(
            NodeRate(
                task=PURO_PURO_TASK,
                skill="Hunter",
                level=level,
                xp_per_hour=total,
                experience=total / catches,
                chance=roll_seconds / (3600.0 / catches),
                roll_seconds=roll_seconds,
                duty=1.0,
                node="Puro-Puro",
                tool="Butterfly net",
            )
        )
    return tuple(found)
