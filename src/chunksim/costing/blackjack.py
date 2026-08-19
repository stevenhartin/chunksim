"""Blackjacking, where one knockout buys two pickpockets and no stun at all.

**An ordinary pickpocket is a roll against a stun; a blackjacked one is not a
roll at all.** You knock the target unconscious and take their pocket *twice*
while they are down, so the success chart that matters is the **knockout**
chart and the pickpockets are free. `costing/pickpocket.py` prices the awake
method - the wiki's own `np/(10-8p)` over a pickpocket chance - and for these
three NPCs nobody does that: the Menaphite Thug read 104,422/hr awake against
a published **265,000** blackjacked, and the two Pollnivneach bandits were
refused outright as uncharted, which they are only for a method nobody uses.

### The loop, and the one number that fixes it

`Thieving training` states it: "knock out the bandit and pickpocket them twice
while they are unconscious. **The timing is right when the player receives
experience drops every two ticks**". So a cycle is one knockout attempt and
two pickpockets at two ticks each, and a failed knockout costs another attempt
- the page says to "keep trying to knock them out again", which is what stops
it becoming a stun.

That is the whole model, and it lands on the page's own ceiling exactly. Two
thug pickpockets at 137.5 over six ticks is **275,000 an hour**, against
"at maximum efficiency, it is possible to gain up to 270,000-275,000
experience per hour at level 99".

### Three NPCs, and the level is which one you use

    45-55   Bearded Pollnivnian bandit    65 xp     knockout pays 10
    55-65   Pollnivnian bandit, no beard  84.3 xp   knockout pays 10
    65+     Menaphite Thug                137.5 xp  knockout pays nothing stated

The bandits' page states the knockout experience outright - "knocking out
either bandit rewards 10 Thieving experience" - and the thug's does not, so
the thug's cycle pays only its two pickpockets. That is the reading the
ceiling confirms: with a knockout bonus the thug would be 285,000 at perfect
play, above the page's own maximum.

### What it comes out at, and the residual

Against `Thieving training`'s brews column the model runs **1.02x to 1.16x**,
tightest at the top:

    level 45    114,331   published  99,000    1.16x
    level 55    152,436   published 136,000    1.12x
    level 65    243,794   published 230,000    1.06x
    level 99    269,388   published 265,000    1.02x

**Nothing is fitted to close that**, and the reason is that nothing could: a
constant multiplier cannot produce a residual that shrinks from 16% to 2%, and
neither can a constant overhead - solving the published column for extra ticks
per cycle gives 1.14 at level 45 down to 0.10 at 99. The page says what the
shape is in its own hidden comment: the rates "assume having good practice and
include resupply time ... Lower levels scale down more to factor in that you
fail more often and likely make more mistakes". Practice is not a term this
model has, so the published column is carried as the **oracle** and the
mechanic is what is spent - `costing/barracuda.py`'s relationship, and
`tests/test_costing_blackjack.py` pins both ends of the band.

### Two assumptions, both named

**The no-beard bandit shares the bearded one's knockout chart**, because the
page draws one `Knock-Out chance` chart for both and anchors it at 45. A level
56 NPC is probably harder to knock down than a level 41 one, so this is
optimistic by however much that is - and it is very likely part of why the
residual is widest in that bracket.

**A blackjack and partial completion of `The Feud` are not checked here.**
Upstream gates the thug on the quest and gates each NPC on its own level; the
blackjack itself is a shop item in Pollnivneach, which is where the NPCs are,
so a map that can reach them can buy one.

Pure: nothing but the valid set comes in.
"""

from __future__ import annotations

from typing import Mapping, NamedTuple

from chunksim.costing.gathering import CONFIRMED, CURVE_STEPS, success_chance
from chunksim.costing.heuristics import ComputedMethod

SKILL = "Thieving"

#: What a band calls the activity.
ACTIVITY = "blackjacking"

#: Ticks in an hour.
TICKS_PER_HOUR = 6000.0

#: Ticks one action costs, whether it is a knockout attempt or a pickpocket.
#: **Stated**: "the timing is right when the player receives experience drops
#: every two ticks".
ACTION_TICKS = 2.0

#: Pickpockets taken per successful knockout, stated in the same sentence.
POCKETS_PER_KNOCKOUT = 2.0


class Target(NamedTuple):
    """One blackjackable NPC, as the wiki states it."""

    #: The export's own challenge.
    task: str
    #: Thieving level it opens at, per upstream and the infobox alike.
    opens: int
    #: Experience for one pickpocket while it is down.
    experience: float
    #: Experience for the knockout itself, where the wiki states one.
    knockout: float
    #: Its `Knock-Out chance` chart's plain series.
    curve: tuple[float, float]


#: The three, in the order `Thieving training` introduces them.
TARGETS: tuple[Target, ...] = (
    Target(
        task="Pickpocket a ~|bandit (Pollnivneach)#Bearded|~",
        opens=45,
        experience=65.0,
        knockout=10.0,
        curve=(80.0, 240.0),
    ),
    # **The same chart, which is the assumption this module is least sure of**
    # - see the module docstring. The page draws one `Knock-Out chance` for
    # both bandits and anchors it at 45.
    Target(
        task="Pickpocket a ~|bandit (Pollnivneach)#No beard|~",
        opens=55,
        experience=84.3,
        knockout=10.0,
        curve=(80.0, 240.0),
    ),
    Target(
        task="Pickpocket a ~|Menaphite Thug|~",
        opens=65,
        experience=137.5,
        # **Nothing states one**, where the bandits' page states 10 outright.
        # The ceiling confirms the silence: with a bonus the thug would be
        # 285,000 at perfect play, above the page's own 270,000-275,000.
        knockout=0.0,
        curve=(78.0, 240.0),
    ),
)


def knockout_chance(target: Target, level: int) -> float:
    """The chance one blackjack swing puts the target down."""
    return success_chance(level, *target.curve)


def cycle_ticks(target: Target, level: int) -> float:
    """Ticks one knockout-and-two-pockets cycle costs on average.

    A failed swing costs another swing and nothing else: the page's own advice
    is to "keep trying to knock them out again", which is what avoids the stun
    an awake pickpocket would take.
    """
    chance = knockout_chance(target, level)
    if chance <= 0:
        return 0.0
    return ACTION_TICKS / chance + ACTION_TICKS * POCKETS_PER_KNOCKOUT


def cycle_experience(target: Target) -> float:
    """What one cycle pays: the knockout, where it pays, and two pockets."""
    return target.knockout + POCKETS_PER_KNOCKOUT * target.experience


def xp_per_hour(target: Target, level: int) -> float:
    """Thieving experience an hour blackjacking `target` at `level`."""
    ticks = cycle_ticks(target, level)
    if ticks <= 0:
        return 0.0
    return cycle_experience(target) * TICKS_PER_HOUR / ticks


def ceiling(target: Target) -> float:
    """What the target pays with a knockout that never misses.

    The thug's is 275,000, which is the page's own stated maximum - the check
    that the cycle is the right shape before any chance is applied to it.
    """
    return cycle_experience(target) * TICKS_PER_HOUR / (
        ACTION_TICKS * (1.0 + POCKETS_PER_KNOCKOUT)
    )


def methods(
    valid: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Thieving": bands}` for whichever of the three a map can reach.

    Bands rather than one rate, because the knockout chance climbs: the thug
    is 243,794/hr where it opens and 269,388 at 99.
    """
    reachable = valid.get(SKILL) or {}
    found: list[ComputedMethod] = []
    for target in TARGETS:
        if target.task not in reachable:
            continue
        steps = (target.opens, *(step for step in CURVE_STEPS if step > target.opens))
        found.extend(
            ComputedMethod(
                method=ACTIVITY,
                xp_per_hour=xp_per_hour(target, step),
                level=step,
                match=CONFIRMED,
                knob=f"training/{target.task}/{SKILL}",
            )
            for step in steps
        )
    return {SKILL: tuple(found)} if found else {}
