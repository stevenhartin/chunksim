"""Guardians of the Rift, which is one minigame rather than twelve methods.

**You do not choose the rune.** Only two portals are open at a time, one
elemental and one catalytic, and which they are is the game's decision - so
`Craft a ~|nature rune|~ with guardian essence` is not a method a player picks,
it is a thing that happens while playing Guardians of the Rift. The export
carries twelve of them and they were being priced **five different ways**:

    lvl  1  air     56,760/hr  mmg: "Crafting air runes (high level)"
    lvl  2  mind     5,824/hr  recipe: one imbue, one tick
    lvl 27  cosmic  21,440/hr  mmg: "Crafting cosmic runes"
    lvl 35  chaos   28,475/hr  mmg: "Crafting chaos runes through the Abyss"
    lvl 44  nature  25,000/hr  wiki:gotr

Three of those describe a *different activity* - the ordinary altar, or the
Abyss - joined through the rune's `Output` because the minigame shares it. The
recipe rate is the tick cost of a single imbue with no minigame around it. And
`_add_banded`'s first published band is level 40, so everything below it fell
through to whichever of those had joined.

**So this replaces all of it with one curve, and the curve is the rune mix.**
At Runecraft level `L` the accessible runes are those whose own level `L`
allows - imbuing needs the same level as crafting normally - and the two open
portals mean an essence is as likely to become the elemental rune as the
catalytic one. `xp_per_essence` is that average, and it is the whole of what
the player's level buys in *quality*.

**Throughput is calibrated, not modelled, and that is the honest split.** What
a level also buys is a bigger pouch, and nothing published states essence per
hour. So the published `Runecraft level -> XP/h` bands are divided by the
modelled mix to recover it - 3,704 essence an hour at 40 rising to 9,532 at 99,
which is the colossal pouch at 85 showing up exactly where it should. Same
shape as `skill_tables.parse_tithe`: ours decides the curve, the published
figure decides the scale.

**Below the first published band the throughput is held flat**, which is the
one assumption here and a narrow one: the medium pouch covers 25 to 49, so a
player at 27 and a player at 40 carry the same essence and differ only in
which runes they can imbue. That puts level 27 - the minigame's own entry
requirement - at 24,306/hr against 25,000 at 40.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from chunksim.costing.gathering import CURVE_STEPS
from chunksim.costing.heuristics import ComputedMethod

#: The minigame's own entry requirement. Nothing below this can play at all,
#: whatever rune a challenge names.
GOTR_LEVEL = 27

#: The elemental half of the rune list. **A fixed game concept and short
#: enough to read**, like `skill_tables.BARRACUDA_RANKS`: everything else the
#: minigame offers is catalytic. The split is what makes two portals two
#: different questions.
ELEMENTAL_RUNES: frozenset[str] = frozenset(
    {"Air rune", "Water rune", "Earth rune", "Fire rune"}
)

#: The suffix upstream gives every challenge that is this minigame.
GUARDIAN_SUFFIX = "with guardian essence"

#: What a band calls the activity, so a climb inside the minigame reads as
#: the minigame rather than as whichever rune sorted first.
ACTIVITY = "Guardians of the Rift"

#: What this labels its rates, in `Rate.match`.
GOTR_MATCH = "modelled"

#: `Rate.source` for a rate this model computed.
GOTR_SOURCE = "computed:gotr"


def rune_mix(runes: Mapping[str, tuple[int, float]], level: int) -> float:
    """Experience one guardian essence pays on average at `level`.

    `runes` is `{rune: (its own Runecraft level, xp per guardian essence)}`.
    Two portals are open, one of each alignment, so the two halves are weighted
    equally and each is a plain mean over the runes that level reaches - the
    game rotates them and the player takes what is up.

    `0.0` when either half is empty, which is every level below `GOTR_LEVEL`
    and is the honest answer: you cannot enter.
    """
    elemental = [xp for name, (need, xp) in runes.items()
                 if name in ELEMENTAL_RUNES and need <= level]
    catalytic = [xp for name, (need, xp) in runes.items()
                 if name not in ELEMENTAL_RUNES and need <= level]
    if not elemental or not catalytic:
        return 0.0
    return 0.5 * sum(elemental) / len(elemental) + 0.5 * sum(catalytic) / len(catalytic)


def essence_per_hour(
    bands: Mapping[int, float], runes: Mapping[str, tuple[int, float]], level: int
) -> float:
    """Guardian essence imbued an hour at `level`, from the published bands.

    Each band states an experience rate at a level; dividing by the mix at that
    level recovers the essence behind it. Read at the highest band the level
    reaches, and **held flat below the lowest** - see the module docstring on
    why the medium pouch makes that narrow rather than convenient.
    """
    recovered: list[tuple[int, float]] = []
    for need, published in bands.items():
        mix = rune_mix(runes, need)
        if mix > 0 and published:
            recovered.append((need, published / mix))
    if not recovered:
        return 0.0
    recovered.sort()
    below = [rate for need, rate in recovered if need <= level]
    return below[-1] if below else recovered[0][1]


def gotr_runes(
    challenges: Mapping[str, Any], experience: Mapping[str, float]
) -> dict[str, tuple[int, float]]:
    """`{rune: (level, xp per guardian essence)}` for the minigame's challenges.

    **Both halves are read rather than stated.** The level is the export's own
    `Level` on the `with guardian essence` challenge, which is the rune's
    requirement and so the level at which it joins the rotation; the experience
    is the `Guardian essence` recipe's. Only the elemental/catalytic split is
    stated, because nothing in either source carries it.
    """
    found: dict[str, tuple[int, float]] = {}
    for task, challenge in challenges.items():
        if not isinstance(challenge, dict) or GUARDIAN_SUFFIX not in task:
            continue
        output = challenge.get("Output")
        level = challenge.get("Level")
        if not isinstance(output, str) or not isinstance(level, int):
            continue
        paid = experience.get(output)
        if paid:
            found[output] = (level, paid)
    return found


def rates(
    runes: Mapping[str, tuple[int, float]],
    bands: Mapping[int, float],
    levels: Sequence[int] = CURVE_STEPS,
) -> list[tuple[int, float]]:
    """`(level, xp per hour)` for the minigame, at each of `levels`.

    Levels below `GOTR_LEVEL` are dropped rather than priced at zero: the
    minigame refuses them, which is not the same as being slow.
    """
    found: list[tuple[int, float]] = []
    for level in levels:
        if level < GOTR_LEVEL:
            continue
        mix = rune_mix(runes, level)
        essence = essence_per_hour(bands, runes, level)
        if mix > 0 and essence > 0:
            found.append((level, mix * essence))
    return found


def methods(
    challenges: Mapping[str, Any],
    valid: Mapping[str, Any],
    bands: Mapping[int, float],
    experience: Mapping[str, float],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{skill: bands}` for Guardians of the Rift, over all twelve challenges.

    **One curve, on all twelve, and the levels are the minigame's.** The export
    gives `Craft an ~|air rune|~ with guardian essence` a `Level` of 1 - the
    rune's own requirement - but nobody plays this below 27, so a rate written
    against the challenge's level would offer the minigame to a level-1 player.
    Bands carry their own level, which is what makes that expressible: every
    challenge gets the same points, each opening where the minigame does.

    **Built here rather than through `gathering.banded_methods`** for the one
    thing that function cannot do: name the activity. It labels a band
    `activity_name(task)`, so a climb spent entirely inside the minigame read
    as "Craft an air rune with guardian essence" from 30 to 99 - which is the
    per-rune confusion this module exists to remove. A knob per task is still
    emitted, because that is what `training._modelled_tasks` reads to retire
    the five different guides these were priced from.
    """
    runes = gotr_runes(challenges, experience)
    tasks = sorted(task for task in (valid or {}) if GUARDIAN_SUFFIX in task)
    if not runes or not bands or not tasks:
        return {}
    found = [
        ComputedMethod(
            method=ACTIVITY,
            xp_per_hour=rate,
            level=level,
            match=GOTR_MATCH,
            knob=f"training/{task}/Runecraft",
        )
        for level, rate in rates(runes, bands)
        for task in tasks
    ]
    return {"Runecraft": tuple(found)} if found else {}
