"""The Blast Furnace's three side jobs: flat experience, and no curve on any.

**The simplest mechanics this project prices, and the only ones with no roll,
no material and no level curve at all.** One building carries all three - two
treadmills paid by the tick and a stove paid by the spadeful - and each page
states the whole of itself:

| Object | Skill | Stated | Published rate |
|---|---|---|---|
| `Pump (Blast Furnace)` | Strength | "2 Strength experience every tick" | 12,000/hr |
| `Pedals` | Agility | "1 xp" a tick | "up to 6,000 Agility experience ... per hour" |

Six thousand ticks an hour times the per-tick figure *is* the published rate in
both rows, so each page's own mechanic and its own headline are the same
arithmetic and there is nothing here to fit. `experience_per_tick` is the model
and `published_per_hour` is carried beside it as the check - the relationship
`costing/barracuda.py` describes, and `tests/test_costing_blastfurnace.py`
asserts it so a wiki rebalance fails a test rather than drifting quietly.

### The stove is the odd one, and the only one with a cadence

`Stove (Blast Furnace)` pays by the action rather than the tick: "every
spadeful grants 5 Firemaking experience", and its `{{Firemaking info}}` says
the same with `level = 30`, which upstream's own challenge agrees with. A
spadeful is two clicks - a spade on the coke heap, then the stove - and
**nothing anywhere times them**, so `SPADE_TICKS` is invented where the two
treadmills invent nothing.

**It is safe to invent because the whole plausible range loses.** Even at one
tick a click, two clicks a spadeful is 15,000/hr, and the slowest reading
anyone would defend is nearer 3,600 - against a Firemaking climb that is
39,627 on the poorest cached map at the level the stove opens, and 126,720
where Wintertodt is reachable. That is `costing/toymouse.py`'s argument, and
it is why this is a `GUESS` that closes a row rather than a refusal: unlike
`Burn kindling (Chambers of Xeric)`, which is refused a few lines away in the
same skill, a guess here cannot decide a band.

The coke is not charged. It is dug from the heap beside the stove, in the
building the challenge is already standing in, so it is part of the action
rather than a material - which is also why `Spadeful of coke` has no route in
the item graph and needs none.

**Neither treadmill has a cadence worth the name.** The pump "can be operated for up to
100 minutes before automatically stopping"; one reclick every hour and forty
minutes is a rounding error, which is what makes these among the few rates in
the game that do not move with level, gear or concentration. `{{Skill info}}`
puts both at level 30 and upstream agrees.

### Both are ceilings, and the two depend on different things

`costing/trawler.py`'s sense of the word: every term is published and the
assumption on top is not checkable from anything the wiki states.

- **The pump depends on other people.** "In order to receive experience, the
  Blast Furnace must be filled with Coke. In the event that the Blast Furnace
  is empty, experience gains will be halted until it is filled" - and the page
  draws its own conclusion, "achieving the maximum theoretical experience rate
  is unlikely". That is the same assumption `costing/wintertodt.py` makes about
  a world with people in it.
- **The pedals depend on an item, which is the stronger caveat.** Pedalling
  costs "0.5% energy per tick", so it runs 271-385 ticks unaided (303-532 in
  full graceful) and then stops; the 6,000 is quoted "up to" and only "with
  energy restoration items". A map may not hold those - the split
  `costing/pickpocket.py` makes between what a published figure is calibrated
  on and what an estimate here may assume - and unlike the pickpockets there is
  no unaided figure published to fall back to, which is `costing/coxchest.py`'s
  reason for spending a tooled one.

Both are `CONFIRMED` rather than `GUESS` because nothing in either is
invented. And neither can decide anything today: 6,000/hr is a twelfth of what
Agility's slowest cached climb already runs at, so the pedals are coverage.

**No Hitpoints experience**, which the pump's page names as the point of the
method and which this project has no way to represent - `costing/combat_xp.py`'s
rates carry a Hitpoints share and this one would carry none. Worth knowing
before comparing the two.

Pure: nothing but the valid set comes in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from chunksim.costing.gathering import CONFIRMED, GUESS
from chunksim.costing.heuristics import ComputedMethod

#: Ticks in an hour.
TICKS_PER_HOUR = 6000.0

SECONDS_PER_TICK = 0.6

#: Upstream's own challenge for the stove.
STOVE_TASK = "Operate the stove at the ~|Blast Furnace|~"

#: What a band calls it.
STOVE_METHOD = "Blast Furnace stove"

#: **Published** on `Stove (Blast Furnace)` and in its `{{Firemaking info}}`.
STOVE_XP = 5.0

#: And the level both that infobox and upstream state.
STOVE_LEVEL = 30

#: Ticks a spadeful costs: a click on the coke and a click on the stove, at
#: the game's floor of one tick an action. **Invented** - see the module
#: docstring for why that is safe here and is not for the kindling.
SPADE_TICKS = 2.0


@dataclass(frozen=True)
class Treadmill:
    """One flat-rate Blast Furnace object."""

    #: The export's own challenge.
    task: str
    #: What a band calls the activity.
    activity: str
    skill: str
    #: Per `{{Skill info}}` and upstream alike.
    level: int
    #: **Stated**, and the whole model.
    experience_per_tick: float
    #: The page's own headline figure. **A check, not a source** - see the
    #: module docstring: it is `experience_per_tick * TICKS_PER_HOUR` restated,
    #: so carrying both is what lets a test notice if they ever disagree.
    published_per_hour: float

    @property
    def xp_per_hour(self) -> float:
        """Flat, at every level."""
        return self.experience_per_tick * TICKS_PER_HOUR


TREADMILLS: tuple[Treadmill, ...] = (
    Treadmill(
        task="Operate the pump at the ~|Blast Furnace|~",
        activity="Blast Furnace pump",
        skill="Strength",
        level=30,
        experience_per_tick=2.0,
        published_per_hour=12_000.0,
    ),
    Treadmill(
        task="Operate the pedals at the ~|Blast Furnace|~",
        activity="Blast Furnace pedals",
        skill="Agility",
        level=30,
        experience_per_tick=1.0,
        published_per_hour=6_000.0,
    ),
)


def stove_xp_per_hour() -> float:
    """Five experience a spadeful at the game's floor of a tick a click."""
    return STOVE_XP * TICKS_PER_HOUR / SPADE_TICKS


def methods(
    valid: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{skill: (one band,)}` per treadmill the map can reach.

    **Each is gated on its own challenge**, not on the building: upstream
    carries the pump under Strength and the pedals under Agility, so a map can
    have derived one valid without the other.
    """
    found: dict[str, tuple[ComputedMethod, ...]] = {}
    for mill in TREADMILLS:
        if mill.task not in (valid.get(mill.skill) or {}):
            continue
        found[mill.skill] = (
            *found.get(mill.skill, ()),
            ComputedMethod(
                method=mill.activity,
                xp_per_hour=mill.xp_per_hour,
                level=mill.level,
                match=CONFIRMED,
                knob=f"training/{mill.task}/{mill.skill}",
            ),
        )
    # **The stove, and `GUESS` rather than `CONFIRMED`**, because its cadence
    # is invented where the treadmills' is not. Gated on its own challenge
    # like they are: upstream files it under Firemaking and a map can reach
    # the building without it.
    if STOVE_TASK in (valid.get("Firemaking") or {}):
        found["Firemaking"] = (
            *found.get("Firemaking", ()),
            ComputedMethod(
                method=STOVE_METHOD,
                xp_per_hour=stove_xp_per_hour(),
                level=STOVE_LEVEL,
                match=GUESS,
                knob=f"training/{STOVE_TASK}/Firemaking",
            ),
        )
    return found
