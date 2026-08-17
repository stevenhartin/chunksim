"""Agility shortcuts, priced from what one use pays and how often it works.

**The sibling of `courses.py`, and the same argument.** A course is an
obstacle count and a lap time; a shortcut is an experience and an attempt, and
in both cases the wiki publishes the parts rather than the rate. Nothing
anywhere states a shortcut's experience per hour, which is why this used to be
a constant chosen to make the answer look right - `heuristics.SHORTCUT_CYCLE_
SECONDS`, 18 seconds, whose own comment called it "a stated target, not a
measurement" and set it so the best shortcut in the table reached ~5,000/hr.

Three things replace it, all read rather than chosen:

- **`SHORTCUT_TICKS`, the attempt.** Shortcuts vary - a wall climb is quicker
  than a stepping-stone chain - and eight ticks is the average across them.
  The one number here that is stated rather than derived, and the one to
  correct if a measurement turns up.
- **`failxp`, from each shortcut's own `{{Agility info}}`.** A failed attempt
  still pays, usually less: the Cosmic altar narrow walkway pays 9.9 on a
  success and 6 on a failure, so a model that counted only successes would be
  wrong in the safe direction but wrong.
- **The success chance, from `{{Skilling success chart}}`** through
  `gathering.success_chance` - the game's exact function, already needed for
  fishing and woodcutting. **A shortcut with no chart cannot fail**, which is
  the wiki's own convention: it charts one precisely where there is a chance
  to miss. 14 of the 64 experience-paying shortcuts have a curve.

So one attempt pays `p * xp + (1 - p) * failxp`, and the rate is that over
eight ticks.

**Most shortcuts are not a training method and the numbers say so.** At their
opening level, 16 of 64 come out under 2,000/hr, 23 between 2,000 and 5,000,
17 between 5,000 and 10,000, and 8 at or above - the best being 20,625 for the
Vampyrium rock slides at 27.5 experience with no failure. The median is 3,750.
That is the honest outcome: they exist in the export as *access*, and a player
spamming one is not training Agility so much as passing the time.

**Upstream mostly excludes the ones that pay nothing, but not entirely.**
93 of 162 shortcuts award 0 experience, and on the challenges that join today
every `Primary: true` one pays something while 29 of the 30 non-primary ones
pay nothing - so the flag is a strong signal for "is this a training method".
It is not a rule: `Fence (Burgh de Rott)` and `Crevice (Fremennik Slayer
Dungeon)` are both `Primary: true` and both pay nothing. So `heuristics.
_add_shortcuts` drops a zero-experience shortcut on its own experience rather
than on the flag, and a wider join cannot quietly introduce a 0/hr method.
"""

from __future__ import annotations

from chunksim.costing.gathering import success_chance
from chunksim.remote.skill_tables import ShortcutInfo

#: Ticks one shortcut attempt takes, door to door. **Stated, not fitted**: the
#: individual shortcuts differ and nothing publishes a distribution, so this is
#: the average across them and is the assumption to revisit first.
SHORTCUT_TICKS = 8.0

#: One game tick, in seconds.
TICK_SECONDS = 0.6

#: Seconds one attempt takes.
ATTEMPT_SECONDS = SHORTCUT_TICKS * TICK_SECONDS


def expected_experience(info: ShortcutInfo, level: int) -> float:
    """What one attempt pays on average at `level`.

    Both outcomes, weighted by the published curve. A shortcut with no curve
    never fails, so this is its experience outright - see the module docstring
    for why absence means certainty here rather than ignorance.
    """
    if info.low is None or info.high is None:
        return info.experience
    chance = success_chance(level, info.low, info.high)
    return chance * info.experience + (1.0 - chance) * info.fail_experience


def xp_per_hour(info: ShortcutInfo, level: int) -> float:
    """`info`'s rate at `level`, in experience per hour."""
    return expected_experience(info, level) * 3600.0 / ATTEMPT_SECONDS
