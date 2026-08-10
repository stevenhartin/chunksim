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

#: The highest level the curve is defined for. 126 is the Combat-level
#: ceiling; 99 is only where the *skill* cap sits, and the difference matters
#: because `max_skill` can hold either.
MAX_LEVEL = 126


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
