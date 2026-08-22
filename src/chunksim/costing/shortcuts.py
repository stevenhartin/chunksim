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

  **Two have now turned up, and between them they bracket the eight.** They
  are the only published hourly figures for a single shortcut anywhere, and
  they disagree in opposite directions:

  - The `Agility` page says of the Wintertodt prison gap that "the player can
    expect experience rates of up to 21,000 Agility experience per hour" at 18
    experience a jump - 1,167 jumps an hour, or **5.1 ticks**.
  - `Monkey bars (Edgeville Dungeon)` says "players can gain up to 13,000
    experience per hour" at 20 experience a swing, which cannot fail - 650
    swings an hour, or **9.2 ticks**.

  So the stated eight sits between them, and the pair says more than either
  did alone: a single observation looked like evidence that the constant was
  conservative, where two say it is an average with real spread on both sides.
  Neither is re-fitted. A gap jumped on the spot while waiting for a boss is
  the fastest shape a shortcut has and monkey bars traversed as an idle method
  are among the slowest, so the honest reading is that the shapes differ by
  nearly a factor of two, and one number standing for all sixty-four is what
  this model is.
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

**And a drop is a decision, so `refused` says so.** Those two challenges join
a real wiki page, are read, and are declined - which printed as `unpriced`,
the word that means "nothing reached this". `coverage.REFUSED` is for exactly
that gap between what a model decided and what the report said.

**Named by hand, because the deciding code runs at a different time.**
`_add_shortcuts` is `chunksim heuristics`' - it turns the scrape into
`wiki_rates.json` - and by the time an estimate runs, a zero-experience
shortcut is indistinguishable from one whose name never joined: both are
simply absent from `training`. Carrying the distinction in the blob would
mean a re-scrape to fill it, so the two are written down here instead, with
the measurement above as their provenance. `tests/test_costing_shortcuts.py`
pins that both are still `Primary: true` Agility shortcuts upstream, since a
name that matches nothing would be silently inert.

**The other misses are *not* this, and calling them refusals would be
wrong.** 33 of the 80 shortcut challenges state no `Objects` at all, so there
is no structural key to join a wiki page on and the fallback is the
challenge's own prose. That is a name lookup somebody can do - it is how
`skill_tables.SHORTCUT_ALIASES`' 22 entries were made - so those stay
`unpriced`, which is precisely "somebody should go and close this". The
rejected word-overlap scorer refused to *guess* the link, not to have one.
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


#: `{task: why}` for a shortcut this project reads and then declines.
#:
#: **A hand table for the reason `remote/gathering.CHART_LABELS` is one**: the
#: fact behind each is measured (see the module docstring) but is decided in
#: `chunksim heuristics`, whose output cannot tell a zero-experience refusal
#: from a name that never joined. Two rows, both `Primary: true` upstream and
#: both awarding nothing on their own wiki page.
REFUSED: dict[str, str] = {
    "Access the Burg de Rot fence ~|shortcut|~": (
        "Fence (Burgh de Rott) awards no experience"
    ),
    "Access the Fremennik Slayer Dungeon chasm jump ~|shortcut|~": (
        "Crevice (Fremennik Slayer Dungeon) awards no experience"
    ),
    # A third, found the moment `EXTRA_SHORTCUT_PAGES` made its page
    # reachable: the boulder is `level = 10` and `xp = 0`, and its `{{Agility
    # info}}` calls it an `Obstacle` rather than a `Shortcut`. It also wants a
    # rope, which is beside the point once the experience is nought.
    "Access the Mountain Camp boulder ~|shortcut|~": (
        "Boulder (Mountain Camp) awards no experience"
    ),
}


def refused() -> dict[str, str]:
    """`{task: why}` for the shortcuts read and declined - see `REFUSED`.

    A function rather than the bare mapping so callers match `foundry.refused`
    and `courses.refused`, and so a future version can take the valid set if
    one of these ever becomes conditional.
    """
    return dict(REFUSED)
