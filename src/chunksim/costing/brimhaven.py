"""The Brimhaven Agility Arena, which is one activity upstream splits in three.

**Not a course and not a shortcut**, which is why nothing else here reached
it. There is no lap: 24 of the arena's 25 pillars carry a ticket dispenser,
one of them activates every 60 seconds, and the player crosses obstacles to
reach it before it moves. So an hour is a *tag* rate and a *downtime* rate
added together, and both are published.

### The tagging half derives exactly, and four published figures say so

Every term is stated on `Brimhaven Agility Arena`:

- **The tag pays `30 x (level // 10)`** - "tagging a dispenser awards 30
  Agility experience for every 10 Agility levels (**including** Agility boosts
  or drains), maxing out at 300 if boosting to level 100". The cap is
  unreachable without a boost, so a climb here tops out at 270.
- **A ticket is 345** experience redeemed with Pirate Jackie the Fruit.
- **Sixty tags an hour**, the page's own assumption for its passive figures:
  "these rates assume no pillars are missed (60 pillars tagged per hour)".

Multiplied out that is `60 x (30 x (level // 10) + 345)`, and it reproduces
every passive figure the page publishes within 0.5% - the page rounding its
own to the nearest thousand:

    level  gloves   derived   published
      40      no     27,900      28,000
      40     yes     29,970      30,000
      80      no     35,100      35,000
      80     yes     37,170      37,000

It also reproduces the elite Karamja Diary's stated bonus, which is the check
that the reading of "10% chance of two tickets" is right: 6 extra tickets an
hour at the **gloved** 379.5 is 2,277, and 2,277 is the page's own figure.
Neither gloves nor the diary are spent - a chunk map may hold neither, the
same split `costing/pickpocket.py` makes between what a published figure is
calibrated on and what an estimate here may assume.

### The downtime half needs one number nothing states

"The best experience per hour rates will be achieved by non-stop completing
Agility obstacles during the waiting time for the active Ticket Dispenser to
move." The obstacle table gives an experience and a tick count for all
fourteen obstacles, so what an hour of downtime pays is arithmetic. What
nothing anywhere states is **how much of each minute is spent travelling to
the dispenser** rather than crossing the same obstacle back and forth.

So that one number is recovered from a published figure rather than chosen:
`Pay-to-play Agility training` says of level 40, without gloves, "you can then
expect to gain around **45,000-50,000** experience per hour when tagging every
pillar and using the floor spikes trap during the downtime". Solving the
midpoint for the travel time gives **27.3 seconds a tag** - about 45 ticks,
which is the right size for crossing the arena.

**The check is at the other end of the climb and with different gear**, so it
is a prediction rather than an identity. The arena page states "at level 99
with the elite diary complete, expect to be able to achieve up to 68,000
Agility experience per hour when constantly jumping over floor spikes during
down time"; this model, given the gloves and the diary that figure assumes,
computes 62,807 - **0.92x**, on the low side of a figure the page hedges with
"up to". The residual has a reason: the 27.3 seconds is recovered at level 40,
where the floor spikes still fail ("players will no longer fail this obstacle
at level 50"), so it carries a level-40 player's mistakes into every band
above it. The model is calibrated at 40 and conservative from 50 up.

The other independent confirmation costs nothing: the same guide says the
floor spikes alone "can achieve approximately 36,000 experience per hour",
and 24 experience every 4 ticks is exactly 36,000. That is the downtime
arithmetic checked with the travel term removed.

### Nothing is offered below level 20, and that is where the evidence stops

`OPENS_AT` is 20 rather than upstream's 1, for three reasons that agree:

- **Level 20 is where the floor spikes open**, and every published figure
  about this arena assumes them - the guide's bracket, its 45,000-50,000, its
  36,000, and the arena page's 68,000.
- **The guide's own bracket is "Levels 20-47"**. It never offers the arena
  below 20, and the fastest route it does offer there is questing.
- **Below 20 the model would be optimistic in two unquantified ways at once.**
  The travel constant is recovered from a route that uses 4-tick spikes and
  pads; a level-1 route is 9 to 13 ticks an obstacle. And a failed rope swing
  drops the player off the platform to climb back up, where a failed spike
  merely hurts. Priced anyway the arena reads ~37,000/hr at level **1**, which
  would own the bottom of every Agility climb on the strength of those two
  silences.

All three challenges name this activity, so all three take these bands - the
arrangement `costing/pyramid.py` uses for the same reason, and what stops
upstream's level-1 `Access the low-level obstacles` claiming a rate for a
regime nothing describes.

### What level 40 actually buys, which is not a faster method

The obvious reading of upstream's three tiers is that each unlocks a better
obstacle. The published table says otherwise, per tick:

    obstacle          level    xp   ticks   xp/tick
    Rope swing            1    20       4      5.00   <- best below 20
    Pillar                1    18       9      2.00
    Floor spikes         20    24       4      6.00   <- best from 20 up
    Pressure pad         20    26       4      3.25   <- see below
    Hand holds           20    22      10      2.20
    Spinning blades      40    28       5      5.60
    Darts                40    30      10      3.00

**Level 40 unlocks nothing worth using.** Spinning blades and darts both pay
less per tick than the level-20 floor spikes even at perfect success, and
`Spinning blades (Brimhaven Agility Arena)` charts a 153/256 success rate at
40 on 157,676 logged attempts, so the real figure is worse still. What 40
buys is route options - it is the level at which every obstacle in the arena
can be crossed, so no detour is forced - and a detour is inside the recovered
travel constant rather than beside it. The jump a reader expects at 40 is
there, and it is the tag formula's 90 to 120 rather than the obstacles'.

**The pressure pad is the trap.** It is the highest-paying obstacle in the
arena per crossing and it is not the best method, because of the 17 July 2024
change: "an 8-tick delay (4.8s) has been applied to the pressure pads before
the player can continue to receive experience for navigating the obstacle
after two consecutive uses". Two paid crossings at 4 ticks then 8 dead ticks
is 52 experience per 16 ticks - 3.25, not 6.5 - which is why the page says
repeatedly using them "used to be a good tactic". `Obstacle.lockout_ticks`
carries it so the table cannot pick the pad by its headline number.

### What is deliberately not charged

The 200 coin entry fee is per *entry*, not per hour, and an entry lasts as
long as the player stays; food is genuinely consumed and no page states how
much. Both sit inside the recovered constant at level 40, which is the level
they matter at.

Pure: nothing but the valid set comes in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from chunksim.costing.gathering import INFERRED
from chunksim.costing.heuristics import ComputedMethod

SKILL = "Agility"

TICK_SECONDS = 0.6
SECONDS_PER_HOUR = 3600.0

#: Experience a tag pays for every ten Agility levels held.
TAG_XP_PER_TEN_LEVELS = 30.0

#: The stated ceiling, at level 100 - reachable only with a boost, which this
#: project does not model, so it is recorded rather than spent.
TAG_XP_CAP = 300.0

#: What Pirate Jackie the Fruit pays for one Agility arena ticket. Ungloved:
#: `Karamja gloves 2` and above add 10% and a chunk map may hold neither.
TICKET_XP = 345.0

#: Dispensers tagged an hour - one activates every 60 seconds and the page's
#: own passive figures assume none are missed.
TAGS_PER_HOUR = 60.0

#: The arena's own requirement is none at all, but see `OPENS_AT`.
OPENS_AT = 20

#: The level at which the floor spikes stop failing, stated on their page.
#: Recorded because it is why the recovered constant understates above it.
NO_FAIL_LEVEL = 50


@dataclass(frozen=True)
class Obstacle:
    """One row of the arena's published obstacle table."""

    name: str
    level: int
    #: Experience for one crossing, ungloved.
    experience: float
    #: Ticks one crossing takes.
    ticks: float
    #: Paid crossings before a lockout, where the obstacle has one.
    paid_uses: int = 0
    #: Ticks of no experience once `paid_uses` is spent.
    lockout_ticks: float = 0.0

    @property
    def xp_per_tick(self) -> float:
        """What crossing this back and forth pays, lockout included."""
        if not self.lockout_ticks or not self.paid_uses:
            return self.experience / self.ticks
        paid = self.paid_uses * self.experience
        return paid / (self.paid_uses * self.ticks + self.lockout_ticks)

    @property
    def xp_per_second(self) -> float:
        return self.xp_per_tick / TICK_SECONDS


#: The whole published table, in the page's own order. Carried entire rather
#: than reduced to the winner, because which one wins is the finding.
OBSTACLES: tuple[Obstacle, ...] = (
    Obstacle("Blade", 1, 0.0, 5.0),
    Obstacle("Rope swing", 1, 20.0, 4.0),
    Obstacle("Low wall", 1, 8.0, 5.0),
    Obstacle("Plank", 1, 6.0, 9.0),
    Obstacle("Balancing rope", 1, 10.0, 9.0),
    Obstacle("Log balance", 1, 12.0, 9.0),
    Obstacle("Balancing ledge", 1, 16.0, 9.0),
    Obstacle("Monkey bars", 1, 14.0, 13.0),
    Obstacle("Pillar", 1, 18.0, 9.0),
    Obstacle("Pressure pad", 20, 26.0, 4.0, paid_uses=2, lockout_ticks=8.0),
    Obstacle("Floor spikes", 20, 24.0, 4.0),
    Obstacle("Hand holds", 20, 22.0, 10.0),
    Obstacle("Spinning blades", 40, 28.0, 5.0),
    Obstacle("Darts", 40, 30.0, 10.0),
)

#: The level and the ungloved band `Pay-to-play Agility training` publishes,
#: which is the only thing here that is not arithmetic over the table.
CALIBRATION_LEVEL = 40
CALIBRATION_BAND = (45_000.0, 50_000.0)

#: The arena page's own top-end figure, and the gear it assumes. Spent as a
#: check on the recovered constant rather than as a source - see the module
#: docstring for the 0.92x it lands at.
TOP_END_LEVEL = 99
TOP_END_XP_PER_HOUR = 68_000.0
GLOVES_BONUS = 1.1
ELITE_TICKET_BONUS = 1.1


def tag_experience(level: int) -> float:
    """What one dispenser tag pays at `level`."""
    return min(TAG_XP_PER_TEN_LEVELS * (level // 10), TAG_XP_CAP)


def best_obstacle(level: int) -> Obstacle:
    """The obstacle worth crossing back and forth at `level`.

    Maximised on `xp_per_tick`, which is what makes the pressure pad lose to
    the floor spikes and the level-40 pair lose to both.
    """
    return max(
        (row for row in OBSTACLES if row.level <= level),
        key=lambda row: (row.xp_per_tick, -row.level, row.name),
    )


def tagging_xp_per_hour(level: int, *, gloves: bool = False, elite: bool = False) -> float:
    """The half that derives exactly - tags plus the tickets they hand over."""
    tickets = TICKET_XP * (GLOVES_BONUS if gloves else 1.0)
    tags = TAGS_PER_HOUR * (ELITE_TICKET_BONUS if elite else 1.0)
    return TAGS_PER_HOUR * tag_experience(level) + tags * tickets


def _travel_seconds_per_tag() -> float:
    """Seconds of each 60-second cycle spent reaching the dispenser.

    **Recovered, not chosen.** The one unpublished term, solved out of the
    guide's own ungloved band at level 40 - see the module docstring.
    """
    target = sum(CALIBRATION_BAND) / 2.0
    downtime_xp = target - tagging_xp_per_hour(CALIBRATION_LEVEL)
    downtime = downtime_xp / best_obstacle(CALIBRATION_LEVEL).xp_per_second
    return (SECONDS_PER_HOUR - downtime) / TAGS_PER_HOUR


TRAVEL_SECONDS_PER_TAG = _travel_seconds_per_tag()


def downtime_xp_per_hour(level: int, *, gloves: bool = False) -> float:
    """What the obstacle crossed during the wait pays over an hour."""
    downtime = SECONDS_PER_HOUR - TAGS_PER_HOUR * TRAVEL_SECONDS_PER_TAG
    paid = best_obstacle(level).xp_per_second
    return downtime * paid * (GLOVES_BONUS if gloves else 1.0)


def rate_at(level: int, *, gloves: bool = False, elite: bool = False) -> float:
    """Agility experience an hour at `level`, or `0.0` below `OPENS_AT`."""
    if level < OPENS_AT:
        return 0.0
    return tagging_xp_per_hour(level, gloves=gloves, elite=elite) + downtime_xp_per_hour(
        level, gloves=gloves
    )


def bands() -> tuple[tuple[int, float], ...]:
    """`(level, rate)` wherever the answer changes, from `OPENS_AT` to 99.

    Derived rather than listed, so a corrected obstacle row or a changed tag
    formula moves the band boundaries with it. Today they are the multiples of
    ten the tag formula steps at - level 40 adds no boundary of its own,
    because the obstacles it unlocks are slower than the ones already open.
    """
    found: list[tuple[int, float]] = []
    for level in range(OPENS_AT, 100):
        rate = rate_at(level)
        if not found or abs(rate - found[-1][1]) > 1e-9:
            found.append((level, rate))
    return tuple(found)


#: Every challenge upstream files under this activity. Three obstacle tiers,
#: one arena - same chunk, same `Output`, and no way to play one without the
#: others.
TASKS: tuple[str, ...] = (
    "Access the low-level obstacles at the ~|Brimhaven Agility Arena|~",
    "Access the medium-level obstacles at the ~|Brimhaven Agility Arena|~",
    "Access the high-level obstacles at the ~|Brimhaven Agility Arena|~",
)


def methods(
    valid: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Agility": (...)}` where a map can reach the arena."""
    reachable = valid.get(SKILL) or {}
    found = [
        ComputedMethod(
            method="Brimhaven Agility Arena",
            xp_per_hour=rate,
            level=level,
            # **`INFERRED`, never `CONFIRMED`.** The tagging half is the
            # wiki's own arithmetic and the obstacle table is transcribed,
            # but the split between travelling and crossing is this project's
            # arithmetic over somebody's figure rather than a line the wiki
            # drew - and a rate is only as good as its weakest input.
            match=INFERRED,
            knob=f"training/{task}/{SKILL}",
        )
        for task in TASKS
        if task in reachable
        for level, rate in bands()
    ]
    return {SKILL: tuple(found)} if found else {}
