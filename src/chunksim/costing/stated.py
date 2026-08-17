"""Methods whose rate is stated rather than derived, and says so.

Two activities live here and they have one thing in common: **nothing about
them can be computed from the tables**, so the number is somebody's statement
and the only honest thing to do is carry it with a provenance that says which
part was measured and which was chosen.

- **Moss lizard.** The experience is a formula - nine tenths of your Hunter
  level, floored, and capped at ninety - so it climbs exactly and needs no
  fitting. The *pace* is not published: catching three takes about half a
  minute, so ten seconds each, and that is a guess. Every band is marked
  `GUESS` for it.
- **Trouble Brewing.** A whole minigame with eight skills' worth of challenges
  and nothing tabulated anywhere. Fifteen thousand an hour is a stated
  estimate, applied to each skill the export lists a challenge for, and it is
  a guess twice over: in the figure, and in giving every skill the same one.

  **Cooking has left this module**, which is the second entry to do so and
  for the reason given below about Tempoross: the way to retire a `GUESS` is
  to go and read the pages. Seven of the eight challenges are `Participate in
  ~|Trouble Brewing|~ **for <skill> xp**`; Cooking's is the bare one, because
  brewing the rum *is* the minigame and the rest are side-effects of running
  about doing it - and the rum's chain turns out to be countable end to end.
  See `costing/troublebrewing.py`. The other seven keep the 15,000, which is
  now explicitly a statement about the *secondary* skills, and the warning
  below that they "are the more likely to be overstated" is the reason not to
  lift them on the strength of the one that was measured.

- **The lantern harpoon.** Two squid come off one spot and which you get is
  decided by level: the page has the split at 69 Fishing (69% swordtip, 31%
  jumbo) and again at 91 (62%/38%), so the share is read at both ends and
  straight-lined between them. The *catch rate* is not on any page - 250 an
  hour at 52 rising to 400 at 99 comes from a video - so this is `GUESS` too,
  and it is a bad enough method that being within a few percent is beside the
  point: 13,750/hr at 52 and 25,244 at 99, below almost everything else
  Fishing offers.

- **Tempoross has left this module**, and it is worth saying where it went and
  why, because it is the shape of thing that should. It was three invented
  figures - 100,000 an hour for a crystal or infernal harpoon, 85,000 for a
  dragon one, 80,000 for a plain one - flat across the whole climb. The wiki
  publishes a rate for four harpoons at five levels each, and against those the
  guess was wrong twice: a plain harpoon at level 35 is 30,000 rather than
  80,000, and crystal and infernal are 95,000 and 76,000 rather than one number
  for both. See `costing/tempoross.py`. **A `GUESS` here is a placeholder for a
  page nobody has read yet**, and the way to retire one is to go and read it.

- **Guardians of the Rift.** The only entry here that is an *arithmetic
  ceiling* rather than somebody's estimate, and the distinction is worth
  keeping: a game caps you at 250 guardian fragments however hard you mine, six
  games fit in an hour, and a fragment pays 5 experience - so 7,500 an hour is
  what the cap allows, not what a player averages. It is still `GUESS`, because
  "six games an hour" and "mining constantly" are both readings rather than
  published figures, and because a ceiling quoted as a rate overstates every
  player who ever stops to do the rest of the minigame.

- **The Fishing Trawler.** A minigame with nothing tabulated; ten thousand an
  hour is the stated figure and there is no more to it.
- **Temple Trekking's tomes.** Seven skills have one and every one of them is a
  viable way to train that skill, at 2,500 an hour - and **the rate doubles if
  the player has finished Darkness of Hallowvale**, because Burgh de Rott
  Ramble is the same trek run in reverse and twice as quickly. That is the one
  place in this module where a *quest* decides a rate, and the export records
  it: `completed_challenges["Quest"]` holds the completion.

**Why they are not in `gathering.PROFILES`.** Neither has a node, a chance or
an interval, and a moss lizard's experience is a function rather than a table
entry - shaping either like the things that do have those would invite a
comparison that does not hold.

Pure: the level and the reachable set come in as arguments.
"""

from __future__ import annotations

import math
from typing import Mapping

from chunksim.costing.gathering import CURVE_STEPS, GUESS, Tables
from chunksim.costing.heuristics import ComputedMethod
from chunksim.derive.other_tasks import CATEGORIES as OTHER_CATEGORIES

#: The export's own name for the moss lizard trap.
MOSS_LIZARD_TASK = "Trap a ~|moss lizard|~"

#: Share of the Hunter level a moss lizard pays, and the cap on it.
MOSS_LIZARD_SHARE = 0.9
MOSS_LIZARD_CAP = 90.0

#: Moss lizards caught in an hour. **A guess**: three in about thirty seconds
#: is ten seconds each, which is where this comes from and why every rate it
#: produces is marked as invented.
MOSS_LIZARD_PER_HOUR = 360.0

#: The Fishing Trawler, which is a minigame and nothing else.
TRAWLER_TASK = "Train fishing on the ~|Fishing Trawler|~"
TRAWLER_OPENS = 15
TRAWLER_PER_HOUR = 10_000.0

#: What every Temple Trekking tome challenge ends with. Seven skills carry one
#: - Agility, Firemaking, Fishing, Mining, Slayer, Thieving, Woodcutting - and
#: reading the tome trains that skill, so the method is the trek itself.
TOME_SUFFIX = "tome|~ from Temple Trekking"

#: The trek's rate, and the rate once the Ramble is unlocked. **Doubling is the
#: whole of the difference**: Burgh de Rott Ramble is the same journey run in
#: reverse and twice as fast, so an hour buys two treks' worth of tomes.
TOME_PER_HOUR = 2_500.0
TOME_RAMBLE_PER_HOUR = 5_000.0

#: The quest that unlocks the Ramble, as the export's `Quest` branch names it.
RAMBLE_QUEST = "~|Darkness of Hallowvale|~ Complete the quest"

#: The category upstream tags a minigame challenge with, and the minigame this
#: module has a figure for.
#: Guardians of the Rift, which caps what mining can pay however long you do it.
RIFT_TASK = "Mine for ~|guardian fragments|~ in Guardians of the Rift"
#: The per-game fragment cap, the games an hour, and what one fragment pays.
#: Their product is the ceiling; see the module docstring on why a ceiling is
#: not a rate.
RIFT_FRAGMENT_CAP = 250.0
RIFT_GAMES_PER_HOUR = 6.0
RIFT_FRAGMENT_EXPERIENCE = 5.0

MINIGAME_CATEGORY = "Minigame"
TROUBLE_BREWING = "Trouble Brewing"

#: The challenge branches that are not skills, so a minigame listed under one
#: does not become a training rate for it. `derive/other_tasks.CATEGORIES` owns
#: the first three; `Combat` and `Nonskill` are the export's other two
#: non-skill groupings, and `Combat` in particular carries challenges that
#: belong to six real skills at once.
NOT_SKILLS = frozenset({*OTHER_CATEGORIES, "Combat", "Nonskill"})

#: Experience an hour from Trouble Brewing, in each **secondary** skill it
#: pays. A guess in the figure and a guess again in applying one figure to
#: seven skills; these are the more likely to be overstated.
TROUBLE_BREWING_PER_HOUR = 15_000.0

#: The skills this module does **not** speak for, because something else does.
#: Only Cooking, and only because it is the minigame's own skill rather than a
#: side-effect of playing it - the export marks that itself, giving Cooking the
#: bare `Participate in ~|Trouble Brewing|~` where the other seven are `... for
#: <skill> xp`. See `costing/troublebrewing.py`, which counts it.
TROUBLE_BREWING_MODELLED = frozenset({"Cooking"})


#: The two squid a lantern harpoon spot yields, and the tasks that name them.
LANTERN_TASKS: tuple[tuple[str, str], ...] = (
    ("Catch a ~|raw swordtip squid|~", "raw swordtip squid"),
    ("Catch a ~|raw jumbo squid|~", "raw jumbo squid"),
)

#: The level the spot opens at, and the one the jumbo squid joins the mix at.
LANTERN_OPENS = 52
LANTERN_MIX_OPENS = 69

#: `(level, catches per hour)` at each end, straight-lined between. **From a
#: video rather than a page**, which is why every rate here is a guess.
LANTERN_PACE: tuple[tuple[int, float], ...] = ((52, 250.0), (99, 400.0))

#: `(level, swordtip share)` at each end. **These two are read**: the page
#: states the split at 69 and again at 91, and the line between them is the
#: only part this project supplies.
LANTERN_SPLIT: tuple[tuple[int, float], ...] = ((69, 0.69), (91, 0.62))


def _straight_line(points: tuple[tuple[int, float], ...], level: int) -> float:
    """The line through two published points, read at `level`."""
    (first_level, first), (last_level, last) = points
    if last_level == first_level:
        return first
    return first + (level - first_level) * (last - first) / (last_level - first_level)


def lantern_catches_per_hour(level: int) -> float:
    """Squid an hour at `level`, held inside the two ends it was quoted at."""
    held = max(LANTERN_PACE[0][0], min(level, LANTERN_PACE[1][0]))
    return _straight_line(LANTERN_PACE, held)


def lantern_swordtip_share(level: int) -> float:
    """What share of catches is the lesser squid.

    All of them below the level the jumbo joins at, and the published split
    thereafter - extended past 91 rather than held there, since the two points
    describe a drift rather than a ceiling.
    """
    if level < LANTERN_MIX_OPENS:
        return 1.0
    return max(0.0, min(1.0, _straight_line(LANTERN_SPLIT, level)))


def lantern_rate(tables: Tables, level: int) -> float:
    """Fishing experience an hour from a lantern harpoon spot."""
    paid = tables.skill_info.get("Fishing") or {}
    values = [paid.get(page) for _task, page in LANTERN_TASKS]
    if any(value is None for value in values):
        return 0.0
    swordtip, jumbo = (value[1] for value in values if value is not None)
    share = lantern_swordtip_share(level)
    return lantern_catches_per_hour(level) * (share * swordtip + (1.0 - share) * jumbo)


def tome_rate(completed_quests: Mapping[str, object]) -> float:
    """Experience an hour from a Temple Trekking tome.

    Doubled where Darkness of Hallowvale is finished, which is what unlocks
    Burgh de Rott Ramble - the same trek in reverse, at twice the pace.
    """
    return TOME_RAMBLE_PER_HOUR if RAMBLE_QUEST in completed_quests else TOME_PER_HOUR


def rift_rate() -> float:
    """The most mining in Guardians of the Rift can pay in an hour."""
    return RIFT_FRAGMENT_CAP * RIFT_GAMES_PER_HOUR * RIFT_FRAGMENT_EXPERIENCE


def moss_lizard_experience(level: int) -> float:
    """`floor(0.9 x level)`, capped at ninety. Exact, not fitted."""
    return min(math.floor(MOSS_LIZARD_SHARE * level), MOSS_LIZARD_CAP)


def methods(
    chunk_info: object,
    valid: Mapping[str, Mapping[str, object]],
    tables: Tables | None = None,
    available: frozenset[str] | None = None,
    completed_quests: Mapping[str, object] | None = None,
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{skill: (...)}` for whichever of these a map can reach."""
    found: dict[str, list[ComputedMethod]] = {}
    quests = completed_quests or {}
    # **Seven skills, one activity.** Reading a tome trains the skill it names,
    # so each skill's challenge carries the trek's own rate.
    for skill, tasks in valid.items():
        if skill in NOT_SKILLS:
            continue
        for task in tasks:
            if not task.endswith(TOME_SUFFIX):
                continue
            found.setdefault(skill, []).append(
                ComputedMethod(
                    method="Temple Trekking",
                    xp_per_hour=tome_rate(quests),
                    level=1,
                    match=GUESS,
                    knob=f"training/{task}/{skill}",
                )
            )
            break
    if RIFT_TASK in (valid.get("Mining") or {}):
        found.setdefault("Mining", []).append(
            ComputedMethod(
                method="Guardians of the Rift",
                xp_per_hour=rift_rate(),
                level=1,
                match=GUESS,
                knob=f"training/{RIFT_TASK}/Mining",
            )
        )
    reachable = valid.get("Fishing") or {}
    if TRAWLER_TASK in reachable:
        found.setdefault("Fishing", []).append(
            ComputedMethod(
                method="Fishing Trawler",
                xp_per_hour=TRAWLER_PER_HOUR,
                level=TRAWLER_OPENS,
                match=GUESS,
                knob=f"training/{TRAWLER_TASK}/Fishing",
            )
        )
    if tables is not None and any(task in reachable for task, _page in LANTERN_TASKS):
        for level in (LANTERN_OPENS, *(step for step in CURVE_STEPS if step > LANTERN_OPENS)):
            paid = lantern_rate(tables, level)
            if paid <= 0:
                continue
            found.setdefault("Fishing", []).append(
                ComputedMethod(
                    method="lantern harpoon",
                    xp_per_hour=paid,
                    level=level,
                    match=GUESS,
                    knob=f"training/{LANTERN_TASKS[0][0]}/Fishing",
                )
            )
    if MOSS_LIZARD_TASK in (valid.get("Hunter") or {}):
        for level in (20, *(step for step in CURVE_STEPS if step > 20)):
            paid = moss_lizard_experience(level)
            if paid <= 0:
                continue
            found.setdefault("Hunter", []).append(
                ComputedMethod(
                    method="moss lizard",
                    xp_per_hour=paid * MOSS_LIZARD_PER_HOUR,
                    level=level,
                    match=GUESS,
                    knob=f"training/{MOSS_LIZARD_TASK}/Hunter",
                )
            )
    for skill, tasks in valid.items():
        if skill in NOT_SKILLS:
            continue
        for task in tasks:
            if TROUBLE_BREWING not in task or skill in TROUBLE_BREWING_MODELLED:
                continue
            found.setdefault(skill, []).append(
                ComputedMethod(
                    method="Trouble Brewing",
                    xp_per_hour=TROUBLE_BREWING_PER_HOUR,
                    level=1,
                    match=GUESS,
                    knob=f"training/{task}/{skill}",
                )
            )
            break
    return {skill: tuple(methods) for skill, methods in found.items()}
