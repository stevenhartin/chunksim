"""A sequence of fights and puzzles, priced as one run.

**The thing raids are and single monsters are not.** Everything else in
`costing/` that touches combat prices one kill and multiplies: a rate is a
monster's time-to-kill plus an overhead, and the answer scales linearly. A raid
is a *run* - an ordered set of rooms, some of which are fights and some of
which are not, ending in one reward roll - so the unit that has a duration is
the whole sequence and the unit that has a chance is the sequence's end. This
module is that unit, and it knows nothing about any particular raid.

### What a stage is

A `Stage` is a name, a duration and optionally some points. Three things build
one and they are deliberately not subclasses:

- **`FightPlan`** names a target `costing/dps_bridge.py` can price and how many
  of them a room holds. Its duration is the fight, adjusted by whatever
  `costing/mechanics.py` says about that target - see `Mechanic` for why a
  time-to-kill is not a room's duration.
- **`PuzzlePlan`** names a duration outright, for a room where nothing is
  killed: a solved puzzle, a supply run, a walk between chambers. Most raid
  puzzles are solved to a constant by their own guides, which is why this is a
  number and not a model.
- **`Encounter`** is the built sequence, and answers `seconds` and `points`.

**A plan is not a stage until something prices it**, which is the whole reason
for the split: `build` takes a `kill_seconds` callable, so the pure layer never
imports the optional DPS extra and a caller without it gets `None` rather than
a wrong number.

### What it deliberately does not decide

**How a run's stages are chosen.** Theatre of Blood runs the same six rooms
every time; Chambers of Xeric draws a random subset; Tombs of Amascut fixes the
bosses and varies their difficulty. That is a *selector*, and it belongs to the
raid rather than here - this module prices whatever list it is handed.

**What the run yields.** A chest is a chance and a table, and the three raids'
chests differ in every particular. `Objective` is here because it is the
question a caller asks, but answering it is the raid's job.

Pure: every input is an argument, including the clock.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping, Sequence

#: `target -> seconds of fighting`, or `None` where nothing can price it.
#: `costing/dps_bridge.py` supplies one; tests supply a dict's `get`.
KillSeconds = Callable[[str], float | None]

#: What a caller is trying to make fast. **Defaulting to the whole collection
#: log** because that is the goal a chunk map actually has: a unique is a means
#: to it, and experience is a by-product.
GREEN_LOG = "green-log"
EXPERIENCE = "experience"
UNIQUE = "unique"


@dataclass(frozen=True)
class Objective:
    """What a raid should be optimised for.

    **One object rather than three flags**, so a raid module takes the
    question rather than a set of booleans it has to interpret - and so a
    fourth objective is an entry here rather than a new parameter everywhere.
    """

    kind: str = GREEN_LOG
    #: The item wanted, for `UNIQUE`. Empty otherwise.
    item: str = ""

    @classmethod
    def for_unique(cls, item: str) -> "Objective":
        """Minimise the expected time to one named drop."""
        return cls(kind=UNIQUE, item=item)

    def __post_init__(self) -> None:
        if self.kind == UNIQUE and not self.item:
            raise ValueError("a unique objective must name an item")


#: The default, and what a caller gets by asking for nothing.
FULL_LOG = Objective()


@dataclass(frozen=True)
class Mechanic:
    """What a fight costs beyond its time-to-kill.

    **Two numbers, because a fight is not a damage race.** `uptime` is the
    share of the fight actually spent attacking - phases where the boss is
    immune, a walk to the next platform, a shield that has to be broken by
    somebody else - and divides the time-to-kill. `idle_seconds` is a fixed
    cost the room carries however fast the kill is.

    Both are inert by default, so a target nothing is known about prices as a
    plain damage race rather than as an error.

    **Not raid-bound on purpose.** The Nightmare's totems and Vardorvis's
    head-dodging are the same shape as Olm's transitions, and a standalone
    boss should be able to say so without pretending to be a raid.
    """

    #: Share of the fight spent dealing damage, `0 < uptime <= 1`.
    uptime: float = 1.0
    #: Seconds the room costs whatever the kill takes.
    idle_seconds: float = 0.0
    #: Why, in the module's own words - carried so a reader can weigh it.
    note: str = ""

    def seconds(self, time_to_kill: float) -> float:
        """`time_to_kill` as the room's real duration."""
        if self.uptime <= 0:
            return 0.0
        return time_to_kill / self.uptime + self.idle_seconds


#: A fight nothing is known about: a plain damage race with no downtime.
PLAIN = Mechanic()


@dataclass(frozen=True)
class FightPlan:
    """A room resolved by killing something."""

    name: str
    #: The key `kill_seconds` is asked about - `osrs-dps`' own spelling.
    target: str
    #: How many of it the room holds. Fractional where a room holds a varying
    #: number and the mean is what a run costs.
    count: float = 1.0
    points: float = 0.0


@dataclass(frozen=True)
class PuzzlePlan:
    """A room resolved without killing anything, timed outright."""

    name: str
    seconds: float
    points: float = 0.0


@dataclass(frozen=True)
class Stage:
    """One priced room."""

    name: str
    seconds: float
    points: float = 0.0
    #: The target this came from, or empty for a puzzle. Carried so a caller
    #: can say *which* fight it could not price.
    target: str = ""


@dataclass(frozen=True)
class Encounter:
    """One priced run."""

    name: str
    stages: tuple[Stage, ...] = ()

    @property
    def seconds(self) -> float:
        return sum(stage.seconds for stage in self.stages)

    @property
    def points(self) -> float:
        return sum(stage.points for stage in self.stages)

    @property
    def hours(self) -> float:
        return self.seconds / 3600.0

    def runs_per_hour(self) -> float:
        return 3600.0 / self.seconds if self.seconds > 0 else 0.0


def build(
    name: str,
    plans: Iterable[FightPlan | PuzzlePlan],
    kill_seconds: KillSeconds,
    mechanics: Mapping[str, Mechanic] = {},
    attackers: float = 1.0,
) -> Encounter | None:
    """One run's stages, or `None` if any fight cannot be priced.

    **All or nothing, and that is the point.** A raid missing one room's
    duration is not a raid that takes slightly less time; reporting the sum of
    what happened to price would be a number with a hole in it, and the hole
    would be invisible. `costing/crane.py`'s refusal, one layer up.

    **`attackers` divides the time-to-kill and nothing else**, which is what a
    party is: `kill_seconds` answers for one player, and three of them put a
    boss down in a third of the time. It does *not* divide a `Mechanic`'s
    `idle_seconds` or a puzzle - a maze is walked once however many are
    watching, and a phase the boss spends invulnerable is invulnerable to
    everybody. Getting that split wrong is the difference between a party
    helping and a party making the raid free.
    """
    if attackers <= 0:
        return None
    stages: list[Stage] = []
    for plan in plans:
        if isinstance(plan, PuzzlePlan):
            stages.append(Stage(plan.name, plan.seconds, plan.points))
            continue
        found = kill_seconds(plan.target)
        if found is None or found <= 0:
            return None
        mechanic = mechanics.get(plan.target, PLAIN)
        found = found / attackers
        stages.append(
            Stage(
                name=plan.name,
                seconds=mechanic.seconds(found) * plan.count,
                points=plan.points,
                target=plan.target,
            )
        )
    return Encounter(name=name, stages=tuple(stages))


def expected_runs(chance: float) -> float:
    """Runs to see something that happens with probability `chance` a run.

    The mean of a geometric distribution, which is the honest figure for
    something run for hours - `costing/gathering.py`'s reason throughout.
    """
    return 1.0 / chance if chance > 0 else float("inf")


def runs_for_all(chances: Sequence[float]) -> float:
    """Expected runs to see **every** one of `chances` at least once.

    **The coupon collector's problem with unequal probabilities**, which is
    what a green log is: the answer is not the slowest item's own expectation,
    because the others are still being collected while it is awaited, and it is
    not the sum either. It is
    `integral from 0 to inf of (1 - product(1 - exp(-p_i t))) dt`, and the
    inclusion-exclusion form of that integral is exact for the handful of items
    a raid chest holds:

        E = sum over non-empty subsets S of (-1)^(|S|+1) / sum(p_i for i in S)

    Exponential in the item count, which is why it is used here and not
    somewhere with hundreds: a raid chest holds seven.
    """
    positive = [p for p in chances if p > 0]
    if not positive or len(positive) != len(chances):
        # A drop that cannot happen is never collected, so the log never closes.
        return float("inf")
    total = 0.0
    for mask in range(1, 1 << len(positive)):
        subset = [p for index, p in enumerate(positive) if mask >> index & 1]
        sign = -1.0 if len(subset) % 2 == 0 else 1.0
        total += sign / sum(subset)
    return total
