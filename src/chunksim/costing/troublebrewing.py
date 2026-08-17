"""Trouble Brewing's Cooking, which is a woodcutting loop wearing a hat.

**A minigame nothing tabulates, whose Cooking rate is nonetheless countable.**
`costing/stated.py` carried the whole activity as one invented figure - 15,000
an hour, applied to each of the eight skills the export lists a challenge for -
and its own docstring said what to do about that: "a `GUESS` here is a
placeholder for a page nobody has read yet, and the way to retire one is to go
and read it". The pages exist and the chain is short:

    chop a scrapey tree      -> 1 scrapey tree log,  25 Woodcutting xp
    fletch the log, knife    -> 1 scrapey bark,      50 Fletching xp
    deposit the bark         ->                     100 **Cooking** xp

so an hour of Cooking here is an hour of *chopping*, and the Cooking figure is
whatever bark you can produce times a hundred. Every link is one-to-one, which
is what makes the count possible at all.

### What is published, and what this refuses to invent

Two mechanics, both off the tree's own page: **log attempts occur every 4 game
ticks**, and the tree has **a 1/8 chance to deplete** whenever a chop yields a
log. The success chance is not invented either - the gathering tables already
carry a `Scrapey tree` chart with a confirmed series per axe tier, the same one
`gathering.rate_at` would spend, so the axe the map holds and the level it can
swing it at both bind here exactly as they do everywhere else.

**The fletch and the deposit are charged nothing, and that is a decision rather
than an oversight.** Neither is timed anywhere: the wiki's `{{Recipe}}` for
scrapey bark carries `ticks = ""`, and no page times walking to a hopper. So
rather than invent two numbers this prices the parts it can and lets the rest
be free - which makes the result an **arithmetic ceiling** rather than an
estimate, the same standing `stated.py` gives Guardians of the Rift's 7,500.
A real player is slower. Nothing here is quoted as though they were not.

### The ceiling, and a published figure that sits above it

A game is 20 minutes and the wiki puts the lobby at 3 more, so "approximately
2-3 games can be completed per hour". **Two** is taken, the conservative end,
which is 40 minutes of play in the hour. The fastest a scrapey tree can
possibly hand over a log is one per 4 ticks, so 40 minutes is at most 1,000
logs and at most **100,000 Cooking experience an hour** - before a single
second is spent fletching, hopping to the next tree, or walking to a hopper.

That matters because theoatrix's 1-99 Cooking guide puts Trouble Brewing at
"around 200k XP per hour" with no requirements, and 200,000 needs *two* logs
every four ticks. It is not a near miss to be split the difference with; it is
outside what the mechanic allows, so it is not carried. **A community figure is
still evidence and this is not a dismissal of it** - it is what happens when a
number can be checked against the actions underneath it, which is the whole
argument for modelling rather than scraping.

### Still a guess, for the reason the ceiling is one

The rate is `GUESS` despite every input being published, because a ceiling
quoted as a rate overstates every player who ever stops to do the rest of the
minigame - and Trouble Brewing has a rest: it is a team game with a score, and
a player chopping for the whole twenty minutes is playing it badly. The
provenance is about how well the *rate* is known, not how well the mechanics
are.

**The other seven skills stay in `stated.py`.** Their challenges say
`Participate in ~|Trouble Brewing|~ **for <skill> xp**` where Cooking's says
none of that, because brewing the rum is the minigame and the rest are
side-effects of running about doing it. Nothing here counts those.

Pure: the tables, the export and the reachable set come in as arguments.
"""

from __future__ import annotations

from typing import Any, Mapping

from chunksim.costing.gathering import (
    GUESS,
    PROFILES,
    Tables,
    best_tool,
    success_chance,
    tool_curve,
)
from chunksim.costing.heuristics import ComputedMethod
from chunksim.model.chunkinfo import ChunkInfo

#: The export's own name for the Cooking challenge, and the skill it pays.
#: **The bare one**: the other seven end `for <skill> xp`.
TASK = "Participate in ~|Trouble Brewing|~"
SKILL = "Cooking"

#: What a band calls it.
ACTIVITY = "Trouble Brewing"

#: The chart's key in `Tables.curves`, and the axe family the export defines.
CURVE = "scrapey tree"
AXE_FAMILY = "Axe[+]"

#: Minutes one game lasts, and games an hour. The page gives a 20-minute game
#: with a 3-minute interval and "approximately 2-3 games ... per hour"; **two**
#: is the conservative end, and 2 x 20 is the 40 minutes of play an hour this
#: counts.
GAME_MINUTES = 20.0
GAMES_PER_HOUR = 2.0

#: Ticks between chop attempts - the tree's own "log attempts occur every 4
#: game ticks", which happens to be Woodcutting's usual roll.
CHOP_TICKS = 4.0

#: One game tick, in seconds.
TICK_SECONDS = 0.6

#: "a 1/8 chance to deplete whenever someone chopping the tree receives a log",
#: so eight logs share one move to the next tree.
DEPLETE_CHANCE = 1.0 / 8.0

#: Seconds spent getting to the next tree when one goes.
#: `gathering.PROFILES["Woodcutting"].node_seconds`, repeated rather than
#: imported for the reason `barbarian.ROLL_TICKS` is - and it is a *hop* rather
#: than the tree's 14.4-second respawn, because a player walks to the next one.
HOP_SECONDS = 2.4

#: Cooking experience one bark pays when deposited, and the one-to-one chain
#: that makes bark a synonym for logs.
BARK_EXPERIENCE = 100.0

#: The level upstream opens the challenge at. Nothing about Cooking gates this;
#: what gates it is holding an axe, which the curve already asks about.
OPENS_AT = 1


def logs_per_hour(chance: float) -> float:
    """Scrapey tree logs an hour of *play* at `chance` per chop attempt.

    The play, not the wall clock: `GAMES_PER_HOUR` games of `GAME_MINUTES`.
    Fletching and depositing are free here - see the module docstring for why
    that makes this a ceiling.
    """
    if chance <= 0:
        return 0.0
    seconds = CHOP_TICKS * TICK_SECONDS / chance + DEPLETE_CHANCE * HOP_SECONDS
    return GAMES_PER_HOUR * GAME_MINUTES * 60.0 / seconds


def chop_chance(
    tables: Tables, chunk_info: ChunkInfo, level: int, available: frozenset[str]
) -> float:
    """The chance one chop attempt yields a log, with the best axe held.

    `0.0` when the tables carry no chart or the map reaches no axe - the same
    refusal `gathering.rate_at` makes, and for the same reason: a chunk map
    holding no axe holds no woodcutting either.
    """
    curves = tables.curves.get(CURVE)
    axe = best_tool(chunk_info, AXE_FAMILY, level, available)
    if not curves or not axe:
        return 0.0
    # **The same series `gathering.rate_at` would spend**, which is why this
    # calls its chooser rather than matching the tier itself: two readings of
    # "which axe's chart is this" would drift, and the one that drifted would
    # go quiet rather than fail.
    series = tool_curve(curves, PROFILES["Woodcutting"], axe)
    return success_chance(level, series[1], series[2])


def xp_per_hour(
    tables: Tables, chunk_info: ChunkInfo, level: int, available: frozenset[str]
) -> float:
    """Cooking experience an hour, depositing every bark you can make."""
    return logs_per_hour(chop_chance(tables, chunk_info, level, available)) * BARK_EXPERIENCE


def methods(
    tables: Tables | None,
    chunk_info: ChunkInfo,
    valid: Mapping[str, Mapping[str, Any]],
    available: frozenset[str],
    woodcutting_level: int,
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Cooking": band}` where a map can reach Trouble Brewing and an axe.

    **One flat band, and the Woodcutting level is handed in.** Nothing about
    this moves with Cooking - the deposit pays 100 whoever does it - so there
    is no curve to band. What moves it is the chop chance, which is a fact
    about the player's *Woodcutting* and their axe at the moment they are
    asked, exactly as `sacredeel.py` takes a Fishing level for a Cooking rate.
    """
    if tables is None or TASK not in (valid.get(SKILL) or {}):
        return {}
    rate = xp_per_hour(tables, chunk_info, woodcutting_level, available)
    if rate <= 0:
        return {}
    return {
        SKILL: (
            ComputedMethod(
                method=ACTIVITY,
                xp_per_hour=rate,
                level=OPENS_AT,
                match=GUESS,
                knob=f"training/{TASK}/{SKILL}",
            ),
        )
    }
