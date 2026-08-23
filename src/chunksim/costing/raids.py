"""All three raids at once, and the thing that actually decides the answer.

`costing/theatre.py`, `costing/xeric.py` and `costing/tombs.py` each answer
about their own chest. This asks the question a chunk map actually has: **how
long is the whole raid collection log**, given that all three must be closed.

### The three are added, not compared

Every other optimisation in this project picks a best. This one does not, and
the reason is the shape of the goal rather than a modelling choice: the export
carries the Chambers', the Theatre's and the Tombs' rewards as separate
collection log entries, so a player needs all three logs and the total is their
**sum**. `best_for` still exists for one item, where picking is the question.

### Two thousand, three times

Each raid's tier-five cape wants 2,000 completions - `Xeric's champion`,
`Sinhaza shroud tier 5`, `Icthlarin's shroud (tier 5)` - and the export carries
every tier of all three as collection log entries. Measured, that constraint
binds in all three raids and the drop tables barely matter: the answer is very
nearly "six thousand raids", and which of them are fast is what is left to
optimise.

That has a consequence worth stating because it inverts the usual advice.
**Where the cape binds, the best drop rate is the wrong thing to optimise**:
the Theatre's hard mode is better per raid and loses, because both modes need
the same 2,000 raids and hard's rooms are longer. A named unique still prefers
the better table, which is what `Objective` is for.

Pure: three callables in, one comparison out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from chunksim.costing import encounter, theatre, tombs, xeric
from chunksim.costing.encounter import KillSeconds, Objective

CHAMBERS, THEATRE, TOMBS = "Chambers of Xeric", "Theatre of Blood", "Tombs of Amascut"


@dataclass(frozen=True)
class RaidAnswer:
    """One raid's answer, in the shape all three share."""

    raid: str
    #: The mode or raid level that won, for a reader.
    setting: str
    run_seconds: float
    runs: float
    bound_by: str

    @property
    def hours(self) -> float:
        return self.run_seconds * self.runs / 3600.0


@dataclass(frozen=True)
class Comparison:
    """Every raid priced for one objective."""

    answers: tuple[RaidAnswer, ...]

    @property
    def hours(self) -> float:
        """**Summed, because all three logs must close.** See the module
        docstring on why this is not a minimum."""
        return sum(answer.hours for answer in self.answers)

    @property
    def complete(self) -> bool:
        """Whether every raid could be priced and reached."""
        return bool(self.answers) and all(
            answer.hours < float("inf") for answer in self.answers
        )

    def slowest(self) -> RaidAnswer | None:
        priced = [a for a in self.answers if a.hours < float("inf")]
        return max(priced, key=lambda a: a.hours) if priced else None


def compare(
    chambers: Callable[[str], KillSeconds],
    theatre_seconds: KillSeconds,
    tombs_stats: Callable[[int], tombs.StatsFor],
    objective: Objective = encounter.FULL_LOG,
    theatre_party: int = theatre.PARTY_SIZE,
    tombs_levels: Sequence[int] = tombs.SEARCH_LEVELS,
) -> Comparison:
    """Each raid at its own best setting for `objective`.

    The three callables differ in shape because the raids do - see each
    module: the Theatre's modes are separate monsters, the Chambers' mode is a
    scaling flag, and the Tombs' setting is a dial.
    """
    found: list[RaidAnswer] = []

    got_cox = xeric.best(chambers, objective)
    if got_cox is not None:
        found.append(
            RaidAnswer(CHAMBERS, got_cox.mode, got_cox.run.seconds, got_cox.runs,
                       got_cox.bound_by)
        )
    got_tob = theatre.best(theatre_seconds, objective, theatre_party)
    if got_tob is not None:
        found.append(
            RaidAnswer(THEATRE, got_tob.mode, got_tob.run.seconds, got_tob.runs,
                       got_tob.bound_by)
        )
    got_toa = tombs.best(tombs_stats, objective, levels=tombs_levels)
    if got_toa is not None:
        found.append(
            RaidAnswer(TOMBS, f"raid level {got_toa.raid_level}",
                       got_toa.run.seconds, got_toa.runs, got_toa.bound_by)
        )
    return Comparison(tuple(found))


def best_for(comparison: Comparison) -> RaidAnswer | None:
    """The single fastest raid, for an objective only one of them can meet.

    **Only meaningful for a named unique.** A green log needs all three, so
    taking a minimum of them would answer a question nobody asked.
    """
    priced = [a for a in comparison.answers if a.hours < float("inf")]
    return min(priced, key=lambda a: a.hours) if priced else None
