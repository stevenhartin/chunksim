"""Burning a log, which is two methods with two mechanics and one rate today.

**The export already knows they are two and the pricing did not.** Upstream
carries `Burn ~|magic logs|~` and `Burn ~|magic logs|~ at a fire` as separate
challenges, and their `Items` say why: the first needs a `Tinderbox` and makes
a `Player fire`, the second needs a `ForesterFire[+]` object and no tinderbox
at all. They were priced identically - 15 logs, 30 challenges, 15 duplicated
numbers - because `heuristics.burning_rate` turns an experience figure into a
rate and the log is all either challenge names.

### Lighting a log is a roll, and below level 43 it is a bad one

Firemaking has a `{{Skilling success chart}}` like any gathering skill:
`low=64`, `high=512`, so **65/256 at level 1** rising to certainty at 43. A
failed attempt costs the cycle and you try again. Nothing in this project was
spending that, so the bottom of the skill was quoted at its level-43 rate -
normal logs at 51,979/hr where the roll makes them **14,661**.

**The wiki has done the same arithmetic and published it, which is the check.**
`Pay-to-play Firemaking training` assumes 1,485 logs an hour and multiplies out
exactly for every band from 42 up (arctic pine `125 x 1485` = 185,625, magic
`303.8 x 1485` = 451,143). The two bands *below* 43 carry a footnote - "includes
some time lost to failed attempts" - and are quoted lower than that product:
willow at 107,000 against 133,650 and teak at 138,000 against 155,925. Those
ratios are 0.8006 and 0.8850, against **0.7975 and 0.8759** from this model at
each band's opening level. Under 1% on both, from a curve fitted to nothing.

### A campfire is a different action and does not roll at all

Adding a log to a forester's campfire takes **9 ticks** and always succeeds -
you are feeding a fire rather than lighting one. Both figures are the wiki's:
the change of 29 May 2025 states the tick count outright ("now takes 9 ticks,
up from 4"), and the training page's campfire table quotes a flat 665 logs an
hour at *every* level including 1-15, where the line-burning table's own rows
are docked for failures. 665 is `3600 / (9 x 0.6)` to three figures, so the
published rate is the cadence and nothing else.

**So the two methods cross over, and that is the finding.** A campfire is half
the speed of a perfect line above 43 and nearly twice as fast below 12, because
one of them rolls and the other does not. Priced as one number they were wrong
in both directions at once.

### What is stated here rather than published

`LINE_TICKS` is the wiki's own assumption rather than a measurement - it says
"it is possible to keep lighting the logs tick-perfectly every 4 ticks" and
builds its table on 1,485 logs an hour, which is that cadence with a little
slop. `BANK_SECONDS` is this project's, and it is why every figure here reads
below the published one: the wiki's tables charge nothing for banking and this
charges ten seconds an inventory, so magic logs come out at 394,778 against
451,143. The conservative end, as everywhere else.

**The inventory differs by one and the export says why.** A line needs the
tinderbox in a slot and a campfire does not (`Items` lists it on one challenge
and not the other), so 27 logs a trip against 28.

**The manual campfire rate is not taken.** The page offers 975 logs an hour
"while holding down spacebar" beside the automatic 665; a published range gets
its conservative end here, as Tempoross' harpoon tiers and the Gwenith Glide's
crystal extractor both do.

Pure: the experience column arrives as an argument (`Heuristics.burning`) and
the level does too.
"""

from __future__ import annotations

from typing import Any, Mapping

from chunksim.costing.gathering import CURVE_STEPS, success_chance
from chunksim.costing.heuristics import ComputedMethod

#: What a band calls each method.
LINE_ACTIVITY = "burning logs in a line"
CAMPFIRE_ACTIVITY = "a forester's campfire"

#: What this labels its rates.
FIREMAKING_MATCH = "modelled"

#: The skill, and the only one either method pays.
SKILL = "Firemaking"

#: The `{{Skilling success chart}}` parameters off the skill's own page:
#: 65/256 at level 1, certainty from 43, 513/256 at 99. The chance applies to
#: *lighting* a log and to nothing else - a campfire is fed, not lit.
SUCCESS_LOW = 64.0
SUCCESS_HIGH = 512.0

#: The level the roll saturates at. Above it the two methods are flat, so the
#: bands stop here rather than carrying nine more identical points.
CERTAIN_AT = 43

#: Ticks per attempt at lighting a log on the ground. **The wiki's own
#: assumption** - "it is possible to keep lighting the logs tick-perfectly
#: every 4 ticks" - which its 1,485 logs an hour is built on.
LINE_TICKS = 4

#: Ticks to add one log to a forester's campfire. **Published**, in the change
#: of 29 May 2025 that set it: "now takes 9 ticks (up from 4 ticks)". The
#: training page's flat 665 logs an hour is `3600 / (9 x 0.6)`.
CAMPFIRE_TICKS = 9

#: Logs an inventory carries. **The difference is the tinderbox**, which the
#: export itself records: `Burn ~|X logs|~` lists one in its `Items` and `Burn
#: ~|X logs|~ at a fire` does not.
LINE_LOGS_PER_TRIP = 27
CAMPFIRE_LOGS_PER_TRIP = 28

#: Seconds to bank and come back for the next inventory. **This project's
#: figure, not the wiki's** - its tables charge nothing at all for banking,
#: which is the whole of why every rate here reads below the published one.
BANK_SECONDS = 10.0

#: One tick.
TICK_SECONDS = 0.6


def light_chance(level: int) -> float:
    """The chance one attempt at lighting a log succeeds at `level`."""
    return success_chance(level, SUCCESS_LOW, SUCCESS_HIGH)


def line_seconds(level: int) -> float:
    """Seconds one log takes to light, failed attempts included.

    A failure costs the whole cycle and you try again, so the expected time is
    the cycle over the chance - the same shape `costing/shortcuts.py` gives an
    Agility shortcut and `costing/gathering.py` a tree.
    """
    chance = light_chance(level)
    return LINE_TICKS * TICK_SECONDS / chance if chance > 0 else 0.0


def line_xp_per_hour(experience: float, level: int) -> float:
    """Experience an hour lighting logs worth `experience` on the ground."""
    seconds = line_seconds(level)
    if seconds <= 0 or experience <= 0:
        return 0.0
    trip = LINE_LOGS_PER_TRIP * seconds + BANK_SECONDS
    return LINE_LOGS_PER_TRIP * experience * 3600.0 / trip


def campfire_xp_per_hour(experience: float) -> float:
    """Experience an hour feeding logs worth `experience` to a campfire.

    **Flat in level**, because feeding a fire has no roll in it. That is what
    makes this the better method below 12 and the worse one above.
    """
    if experience <= 0:
        return 0.0
    trip = CAMPFIRE_LOGS_PER_TRIP * CAMPFIRE_TICKS * TICK_SECONDS + BANK_SECONDS
    return CAMPFIRE_LOGS_PER_TRIP * experience * 3600.0 / trip


def steps_for(level: int) -> tuple[int, ...]:
    """The levels a log opening at `level` changes rate at.

    Its own, then `gathering.CURVE_STEPS` above it, then `CERTAIN_AT` - above
    which the curve is flat and another point would say nothing. A log opening
    at 45 therefore has exactly one.
    """
    above = tuple(step for step in CURVE_STEPS if level < step < CERTAIN_AT)
    if level >= CERTAIN_AT:
        return (level,)
    return (level, *above, CERTAIN_AT)


#: The suffix upstream gives the campfire half of each pair.
CAMPFIRE_SUFFIX = " at a fire"


def methods(
    challenges: Mapping[str, Any],
    valid: Mapping[str, Any],
    burning: Mapping[str, float],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{skill: methods}` for every log a map can burn, either way.

    `burning` is `log -> experience`, carried on `Heuristics` straight off
    `skill_tables.parse_burning` - the wiki's experience column, which is real
    data, where the rate over it was this project's arithmetic all along.

    **Joined on the export's own `Items`**, which is where the log is named and
    is the same join the scrape this supersedes already made. Which of the two
    methods a challenge is comes off `Objects`: a campfire challenge needs a
    `ForesterFire[+]` and a line one needs a tinderbox in its `Items`.
    """
    by_log = {name.lower(): experience for name, experience in burning.items()}
    found: list[ComputedMethod] = []
    for task in sorted(valid or {}):
        challenge = challenges.get(task)
        if not isinstance(challenge, dict) or challenge.get("Primary") is not True:
            continue
        log = _log_of(challenge, by_log)
        if log is None:
            continue
        experience = by_log[log]
        level = challenge.get("Level")
        opens = int(level) if isinstance(level, (int, float)) else 1
        knob = f"training/{task}/{SKILL}"
        if _is_campfire(challenge):
            found.append(
                ComputedMethod(
                    method=CAMPFIRE_ACTIVITY,
                    xp_per_hour=campfire_xp_per_hour(experience),
                    level=opens,
                    match=FIREMAKING_MATCH,
                    knob=knob,
                )
            )
            continue
        found.extend(
            ComputedMethod(
                method=LINE_ACTIVITY,
                xp_per_hour=line_xp_per_hour(experience, step),
                level=step,
                match=FIREMAKING_MATCH,
                knob=knob,
            )
            for step in steps_for(opens)
        )
    return {SKILL: tuple(found)} if found else {}


def _is_campfire(challenge: Mapping[str, Any]) -> bool:
    """Whether a challenge feeds an existing fire rather than lighting one.

    **Upstream's own `Objects`, not the task's words.** `at a fire` is a
    suffix a rename could take away; the `ForesterFire[+]` requirement is the
    thing that makes the action what it is.
    """
    return any(
        isinstance(entry, str) and entry.startswith("ForesterFire")
        for entry in challenge.get("Objects") or ()
    )


def _log_of(challenge: Mapping[str, Any], by_log: Mapping[str, float]) -> str | None:
    """The log a burning challenge consumes, or `None` if it is not one.

    `Items` carries a trailing `*` where upstream means "or better", and the
    tinderbox alongside it on the line-burning half - so this takes the first
    entry the experience table has heard of rather than the first entry.
    """
    for required in challenge.get("Items") or ():
        if not isinstance(required, str):
            continue
        name = required.rstrip("*").strip().lower()
        if name in by_log:
            return name
    return None
