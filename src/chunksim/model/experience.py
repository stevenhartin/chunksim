"""The OSRS experience curve: cumulative XP at a level, and XP between two.

**Nothing here is a heuristic.** Everything in `heuristics.py` is a guess the
user may correct by hand; this is the game's own arithmetic and they must not.
Keeping the two apart is the whole reason this is its own module rather than
another section of the config - an override file that could redefine what
level 92 costs would make every estimate unfalsifiable.

The curve is closed-form, so it is computed rather than scraped or tabulated::

    xp(L) = floor( sum(i = 1 .. L-1) floor(i + 300 * 2**(i/7)) / 4 )

That reproduces the wiki's published table value for value - checked at
levels 2 (83), 10 (1,154), 26 (8,740), 51 (111,945), 76 (1,336,443),
92 (6,517,253) and 99 (13,034,431), which `tests/test_experience.py` pins.
The wiki does publish the table, in a hand-laid four-column wikitext layout,
but parsing that would be strictly more code and strictly less certain than
four lines of arithmetic.

Levels run to **126**, not 99: the curve is what converts a Combat level or a
virtual level into XP, and callers already hold levels above 99 (`max_skill`
carries whatever the player has). Level 1 is 0 XP, and a target at or below
the current level costs nothing rather than raising - a skill already past its
goal is a normal state, not an error.
"""

from __future__ import annotations

from bisect import bisect_right

#: The highest level the curve is defined for. 126 is the Combat-level
#: ceiling; 99 is only where the *skill* cap sits, and the difference matters
#: because `max_skill` can hold either.
MAX_LEVEL = 126

#: Where a *skill* stops. `MAX_LEVEL` is the Combat-level ceiling and the
#: curve runs that far because `max_skill` can hold either, but no skill goes
#: past 99 - so anything converting an experience total into a **skill** level
#: clamps here instead. `level_for_xp` deliberately does not: it is the
#: curve's inverse and the curve is defined to 126.
MAX_SKILL_LEVEL = 99


def xp_for_level(level: int) -> int:
    """Cumulative XP needed to reach `level`, from 1 (0 XP) to `MAX_LEVEL`."""
    if level < 1 or level > MAX_LEVEL:
        raise ValueError(f"level out of range: {level!r} (expected 1..{MAX_LEVEL})")
    total = 0
    for step in range(1, level):
        total += int(step + 300 * 2 ** (step / 7))
    return total // 4


def xp_between(current: int, target: int) -> int:
    """XP still to earn to get from `current` to `target`.

    Zero when the target is already reached or passed. `current` is clamped
    to the curve's range rather than rejected, because it comes from the map
    payload (`MapState.max_skill`) and a nonsense value there should not stop
    an estimate - it should cost nothing and be visible as a skill needing no
    work.
    """
    if target <= current:
        return 0
    return xp_for_level(target) - xp_for_level(max(1, min(current, MAX_LEVEL)))


#: Every level's threshold, in order, so `level_for_xp` is a binary search
#: rather than a loop over the curve.
#:
#: **A tuple built at import is a constant, not a cache.** The project's rule is
#: no module-level *mutable* state - no `lru_cache`, no memo dict - because the
#: pure layer runs in worker processes and a memo makes `--jobs` disagree. This
#: is 126 integers computed from a closed form, immutable, identical in every
#: process, in the same category as `challenges._UNARMED_SOURCES`. For the same
#: reason `xp_for_level` is deliberately *not* memoised: the band walk calls it
#: once per training method per skill, which is nothing.
_THRESHOLDS: tuple[int, ...] = tuple(xp_for_level(level) for level in range(1, MAX_LEVEL + 1))


def level_for_xp(xp: int) -> int:
    """The level `xp` total experience buys: the exact inverse of `xp_for_level`.

    `level_for_xp(xp_for_level(n)) == n` for every level, and one XP short of a
    threshold is the level below - which is the property that matters, since
    this exists to answer "where does a quest's experience reward leave me".

    Clamped rather than raising, at both ends: below zero is level 1 and past
    the curve is `MAX_LEVEL`. A caller handing this a total is describing a
    player, and a player cannot be off the curve.
    """
    return max(1, min(MAX_LEVEL, bisect_right(_THRESHOLDS, xp)))
