"""Werewolf Skullball, where the lap is published and the reset is not.

**A course whose reward is a stopwatch rather than a lap.** Ten goals, a
skull kicked through each, and "you will gain 750 Agility experience if you
complete the game in under 4 minutes. For every 3 seconds over 4 minutes,
you'll lose 8 experience" - so the payout is a step function of the completion
time and the timer does not start until the first goal is scored.

Everything about the run itself is published. `Werewolf Skullball` tabulates
three ways of playing it and what each takes:

    method                     time         experience
    Run recommended route      2:20 - 2:45         750
    Walk recommended route     2:45 - 3:15         750
    Unplanned scramble         3:00 - 3:49         750

All three pay the maximum because all three are inside four minutes, which is
the decay rule being the check on the table rather than a separate fact - and
the page's optimal route, "times as fast as 1:45 can be achieved", is what the
same 750 looks like at the top.

**What nothing states is the reset**, and it is the whole of what makes this a
`GUESS`. Between laps the player runs back to the Skullball Boss, talks to
him, waits for a skull to come out of "one of four chutes on the wall south of
the first goal", and taps it into position - all outside the timer, which is
why the page says there is "plenty of time to position the ball before
starting the activity" and why it offers an `Alternative 1` that "avoids lots
of manual tapping before starting the course".

**One component of the reset is published and the rest is not.** The wiki
ships the route as tile markers (`Module:Tile markers/Werewolf Skullball
recommended route.json`), so the run back is measurable: `End` sits at region
(43, 8) and goal 1 at (35, 13), which is **8 tiles** of Chebyshev distance and
4 ticks at a run - 2.4 seconds. The dialogue and the ball positioning are not
published anywhere, and `RESET_SECONDS` is this module's one invented number.

### What the invented number can and cannot do

It is bounded in a way most guesses here are not, because the lap dominates:
the same 750 over a 165-second lap reads 16,364/hr at no reset at all and
12,000/hr at a full minute. So the honest range is narrow, and 30 seconds is
the pessimistic end of what the geometry and the action count suggest - a
2.4-second run back, a dialogue, and four or five ball actions.

**Where it does decide something, said plainly.** At 30 seconds this reads
13,846/hr against the Edgeville monkey bars' 15,000, and the break-even is a
**15-second** reset: any faster and skullball would take `fray`'s 25-40 band
off them. That is the one place on any cached map where this module's guess
changes an answer, and it is why the conservative end was taken rather than
the middle.

### Two readings deliberately not taken

**The optimal route is not the method.** 1:45 with the same reset would read
20,000/hr, and the page frames it as "with more effort": mark each target tile, and "hit the ball
1 tile before it reaches each target tile to redirect it while it is still
moving". Tile markers are a client plugin and mid-flight redirection is not
what the page presents as the route, so it is carried as the ceiling rather
than spent - `costing/coxchest.py`'s split between a figure recovered under a
tooled regime and one an estimate here may assume.

**And the slow end of the band is what is priced**, which is
`costing/pyramid.py`'s rule for a hedged published range. 2:20 would read
16,364/hr before any reset at all.

*(The two pages disagree about the ball: `Werewolf Skullball` says a tap moves
it 1 square, a kick 4 and a shoot 9, where `Agility` says 1, 5 and 10. Checked
and not needed - the lap times are published directly, so nothing here counts
squares.)*

Pure: nothing but the valid set comes in.
"""

from __future__ import annotations

from typing import Mapping

from chunksim.costing.gathering import GUESS
from chunksim.costing.heuristics import ComputedMethod

SKILL = "Agility"

SECONDS_PER_HOUR = 3600.0

#: The maximum payout, and the window it needs.
MAX_EXPERIENCE = 750.0
FULL_MARKS_SECONDS = 240.0

#: "For every 3 seconds over 4 minutes, you'll lose 8 experience."
DECAY_SECONDS = 3.0
DECAY_EXPERIENCE = 8.0

#: The page's own table, as `(method, fastest, slowest)` in seconds. Carried
#: entire because which one is priced is a decision, not a lookup.
LAPS: tuple[tuple[str, float, float], ...] = (
    ("Run recommended route", 140.0, 165.0),
    ("Walk recommended route", 165.0, 195.0),
    ("Unplanned scramble", 180.0, 229.0),
)

#: "With more effort, times as fast as 1:45 can be achieved" - the ceiling,
#: recorded and not spent. See the module docstring.
OPTIMAL_SECONDS = 105.0

#: The row this prices, and the end of its band. The slow end of a hedged
#: published range, which is `costing/pyramid.py`'s rule.
PRICED_LAP = LAPS[0]
LAP_SECONDS = PRICED_LAP[2]

#: Tiles from `End` to goal 1, off the wiki's own tile markers - region
#: (43, 8) to (35, 13), so `max(8, 5)`.
RUN_BACK_TILES = 8

#: Ticks a tile costs at a run, and what a tick is worth.
TILES_PER_TICK = 2
TICK_SECONDS = 0.6
RUN_BACK_SECONDS = RUN_BACK_TILES / TILES_PER_TICK * TICK_SECONDS

#: **The one invented number in this module.** The run back above is
#: measurable and the dialogue and ball positioning are not; 30 seconds is
#: the pessimistic end of what they plausibly cost. One invented factor makes
#: the product invented, which is why every band here is `GUESS`.
RESET_SECONDS = 30.0

#: Upstream's own name for the activity.
TASK = "Play ~|Werewolf Skullball|~"

#: The level the export gates it at. The `Ring of Charos` and Creature of
#: Fenkenstrain are upstream's to enforce and it does - a challenge reaching
#: this module is one the derivation already called valid, which is
#: `costing/wintertodt.py`'s rule.
OPENS_AT = 25


def experience_for(seconds: float) -> float:
    """What a lap of `seconds` pays, per the page's own decay rule."""
    if seconds <= FULL_MARKS_SECONDS:
        return MAX_EXPERIENCE
    over = int((seconds - FULL_MARKS_SECONDS) // DECAY_SECONDS)
    return max(0.0, MAX_EXPERIENCE - DECAY_EXPERIENCE * over)


def rate_for(lap_seconds: float, *, reset_seconds: float = RESET_SECONDS) -> float:
    """Agility experience an hour at that lap time and that reset."""
    cycle = lap_seconds + reset_seconds
    if cycle <= 0:
        return 0.0
    return experience_for(lap_seconds) * SECONDS_PER_HOUR / cycle


def xp_per_hour() -> float:
    """The rate this module carries - the priced lap plus the invented reset."""
    return rate_for(LAP_SECONDS)


def methods(
    valid: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Agility": (...)}` where a map can reach the course."""
    if TASK not in (valid.get(SKILL) or {}):
        return {}
    return {
        SKILL: (
            ComputedMethod(
                method="Werewolf Skullball",
                xp_per_hour=xp_per_hour(),
                level=OPENS_AT,
                # **One invented factor makes the product invented** -
                # `costing/tempoross.py`'s rule. Everything else here is the
                # page's own table.
                match=GUESS,
                knob=f"training/{TASK}/{SKILL}",
            ),
        )
    }
