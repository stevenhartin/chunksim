"""Fixing a Dorgesh-Kaan lamp, which pays two skills and joined the wrong recipe.

**500 Crafting and 500 Firemaking a lamp**, at level 52 in both, stated twice
on `Light orb` - in prose and again in its `{{Firemaking info}}`, which names
the action "Fixing broken lamp" and carries both skills' figures. Upstream
agrees on the level and files one challenge under each skill, cross-gated on
the other.

**The rate it had was the wrong action's.** Nothing on the wiki marks the
replacement as a `{{Recipe}}`, so the join fell through to the only thing named
after a light orb - `Craft a ~|light orb|~`, the level 87 glassblowing that
*makes* one - and `Replace a ~|light orb|~ in Dorgesh-Kaan` came out with the
same 20,581/hr as the crafting step it consumes, at a level 35 below its own.
That is `costing/lectern.py`'s shape: a challenge whose real action the recipe
corpus does not describe, which has to be stated rather than joined.

### What is real and what is not

Real: the 500 in each skill, the level, and **the orb**, which the item walk
prices end to end at ~19 seconds - molten glass blown into an empty orb, then
cave goblin wire. That is most of the cycle and it is this project's own
number, not a guess.

Not real: how long a lamp takes. The replacement is one click on a broken lamp,
and the lamps are scattered across a city - the wiki publishes a map of every
location precisely because they are not in one place - so the walk between them
is unmodelled and unpublished. `ACTION_TICKS` charges the game's floor of one
tick, which makes this a **ceiling** in `costing/trawler.py`'s sense and the
same convention `recipe_rates.ZERO_TICK_TICKS` applies wherever the wiki states
no duration.

**The orb is folded into the rate rather than declared through
`Heuristics.material_seconds_per_xp`**, for `costing/crane.py`'s reason:
upstream files one task name under both skills it pays, and that map is keyed
by task alone. Its sibling `material_xp_per_xp` is too, and there the shared
key is not merely imprecise but wrong - making an orb is glassblowing, so the
experience it pays is **Crafting's**, and crediting it to a Firemaking climb
breaks the one rule that map has ("it is only ever the *same* skill"). Left in
place it read Firemaking at 169,656 against a true 90,950.

So both stale entries are dropped by name where they are merged, and
`SUPERSEDED_TASKS` is what names them. The wrong recipe's own numbers were
wrong twice over besides: 0.161 seconds an experience is the glassblowing
chain's cost, not the orb's 0.038.

**Dropping the credit undercharges Crafting, knowingly.** Blowing the orb does
pay Crafting, so a fair Crafting figure would credit it back and read higher
than the 90,950 here; the same credit on the Firemaking side is simply false.
With one key for two skills the choice is between a conservative number and a
wrong one, and this takes the conservative one - the direction
`costing/training.py` takes everywhere else it cannot tell the two halves
apart.

**And this ceiling decides bands, which is worth saying plainly.** On a map
that cannot reach Wintertodt the Firemaking climb sits at 44,326/hr from level
45, and this comes out near 91,000 - so it takes the climb from 52 up. Where
Wintertodt is reachable it decides nothing, losing to 211,200 at the same
level. A reader doubting the walking should read the band it owns as the best
case rather than the answer; the knob is `training/<task>/<skill>` in each
skill, as usual.

**Both skills, one action, and the same rate in each** - which is honest here
where it would not be for `costing/swimming.py`: that module prices the slower
of two exchanges because the hour buys different amounts of each, and this one
pays 500 and 500 for the same click.

Pure: the valid set and a material-cost closure, both handed in.
"""

from __future__ import annotations

from typing import Callable, Mapping

from chunksim.costing.gathering import GUESS
from chunksim.costing.heuristics import ComputedMethod

#: Upstream files the same challenge under both skills it pays.
SKILLS: tuple[str, ...] = ("Crafting", "Firemaking")

TASK = "Replace a ~|light orb|~ in Dorgesh-Kaan"

METHOD = "fixing a Dorgesh-Kaan lamp"

#: The item a fix consumes, spelled as the export spells it.
ORB = "Light orb"

#: **Published** for each skill, on `Light orb` and in its `{{Firemaking
#: info}}`.
XP_PER_LAMP = 500.0

#: And the level both state, which upstream matches.
LEVEL = 52

#: Ticks the click costs. **The game's floor**, so the walk between lamps is
#: uncharged and the figure is a ceiling - see the module docstring.
ACTION_TICKS = 1.0

SECONDS_PER_TICK = 0.6
SECONDS_PER_HOUR = 3600.0


#: The entries the wrong recipe join leaves behind, which `inputs` drops by
#: name. Both are keyed by task alone, so neither can be corrected per skill.
SUPERSEDED_TASKS: tuple[str, ...] = (TASK,)


def rate_with(orb_seconds: float) -> float:
    """Experience an hour in either skill, given what an orb costs to obtain."""
    seconds = ACTION_TICKS * SECONDS_PER_TICK + orb_seconds
    return XP_PER_LAMP * SECONDS_PER_HOUR / seconds if seconds > 0 else 0.0


def methods(
    valid: Mapping[str, Mapping[str, object]],
    material_seconds: Callable[[str, float], float | None],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{skill: (one band,)}` for whichever of the two the map can reach.

    **No route to an orb is no rate**, `costing/crane.py`'s refusal: 500
    experience over one tick is 3,000,000/hr on paper, and the orb is the
    method.
    """
    orb = material_seconds(ORB, 1.0)
    if orb is None or orb <= 0:
        return {}
    rate = rate_with(orb)
    found: dict[str, tuple[ComputedMethod, ...]] = {}
    for skill in SKILLS:
        if TASK not in (valid.get(skill) or {}):
            continue
        found[skill] = (
            ComputedMethod(
                method=METHOD,
                xp_per_hour=rate,
                level=LEVEL,
                match=GUESS,
                knob=f"training/{TASK}/{skill}",
            ),
        )
    return found
