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


#: Seconds one raid takes, from each raid's own published rate. **Published
#: rather than modelled**, and the reason is ordering: `estimate.
#: material_seconds` runs before the DPS enrichment, so the walk has no
#: map-specific raid duration to divide by. `costing/tombs.py` explains the
#: same choice for the lily.
#:
#: - Chambers, normal: `Money making guide/Chambers of Xeric`, `kph = 3`.
#: - Chambers, Challenge Mode: **no rate is published**, so the solo time
#:   limit the kit and the dust are gated on stands in - 1 hour 10 minutes.
#:   It is a bound rather than a pace, which makes every Challenge Mode
#:   answer here conservative.
#: - Theatre: `Money making guide/Theatre of Blood` (trio), `kph = 3`.
#: - Tombs: `Money making guide/Tombs of Amascut (Expert)` at raid level 300,
#:   `kph = 1.75`.
PUBLISHED_RAID_SECONDS: dict[str, float] = {
    CHAMBERS: xeric.PUBLISHED_SECONDS,
    f"{CHAMBERS} (challenge)": xeric.CM_SOLO_TIME_LIMIT_SECONDS,
    THEATRE: theatre.PUBLISHED_SECONDS,
    TOMBS: 3600.0 / tombs.GUIDE_RAIDS_PER_HOUR,
}

#: Every raid's cape tiers and the completions each wants. All three run
#: 100/500/1,000/1,500/2,000, and the export carries every tier as its own
#: collection log entry - **which is why a cape cannot be priced as a drop**:
#: there is no rate to divide by, only a count to multiply.
CAPE_TIERS: dict[str, dict[str, int]] = {
    CHAMBERS: {
        "Xeric's guard": 100, "Xeric's warrior": 500, "Xeric's sentinel": 1_000,
        "Xeric's general": 1_500, "Xeric's champion": 2_000,
    },
    THEATRE: {
        "Sinhaza shroud tier 1": 100, "Sinhaza shroud tier 2": 500,
        "Sinhaza shroud tier 3": 1_000, "Sinhaza shroud tier 4": 1_500,
        "Sinhaza shroud tier 5": 2_000,
    },
    TOMBS: {
        "Icthlarin's shroud (tier 1)": 100, "Icthlarin's shroud (tier 2)": 500,
        "Icthlarin's shroud (tier 3)": 1_000, "Icthlarin's shroud (tier 4)": 1_500,
        "Icthlarin's shroud (tier 5)": 2_000,
    },
}


#: The pets, which are tertiary rolls rather than table entries and so need
#: their own rates. **All published**, and each raid does it differently:
#:
#: - `Olmlet` is `1/53` **conditional on the raid having given a unique** -
#:   `Ancient chest` says "pets changed from 1/65 to 1/53 for a player who got
#:   a unique", so it multiplies the unique chance rather than standing beside
#:   it.
#: - `Lil' Zik` is a flat `1/650` in normal mode and `1/500` in hard.
#: - `Tumeken's guardian` reuses the Tombs' own formula with different
#:   constants: 1% for every `350,000 - 700 * RL` points.
OLMLET_GIVEN_UNIQUE = 1 / 53
LIL_ZIK_CHANCE = 1 / 650
TOA_PET_POINTS_PER_PERCENT_BASE = 350_000.0
TOA_PET_POINTS_PER_PERCENT_SLOPE = 700.0


def toa_pet_chance(points: float, raid_level: int) -> float:
    """`Tumeken's guardian` per raid - the uniques' shape, other constants."""
    per = TOA_PET_POINTS_PER_PERCENT_BASE - TOA_PET_POINTS_PER_PERCENT_SLOPE * (
        tombs.scaled_raid_level(raid_level)
    )
    if per <= 0 or points <= 0:
        return 0.0
    return min(1.0, points / (per * 100.0))


def item_seconds() -> dict[str, float]:
    """`{item: seconds}` for every raid reward, to merge into the item walk.

    **This replaces a number that was wrong by two orders of magnitude.** The
    export models each raid as a monster carrying a drop table, so
    `Heuristics.kills_per_hour` fell back to `DEFAULT_KPH` and the walk priced
    a raid at 150 completions an hour - `Xeric's champion`, which wants two
    thousand raids, came out at **24 seconds**, and a twisted bow at 5.7
    hours against this project's own 307.

    Three shapes go in, and the second is the one no drop rate could express:

    - **Uniques**, priced as one raid over the chance a raid gives that item.
    - **Capes**, priced as the completions the tier wants times one raid.
      There is no rate here at all; a cape is a counter.
    - **Common chest items**, which `costing/tombs.py` answers for directly
      from its guide's own stated yield.

    Everything is one raid's published duration - see
    `PUBLISHED_RAID_SECONDS` - because the goal walk is built before any
    DPS-derived rate exists.

    **That direction is optimistic and the docstring should say so rather
    than claim otherwise.** A guide's raid is an established raider's, and a
    chunk map's party is slower: the Theatre's trio is twenty published
    minutes against the ninety-five `costing/theatre.py` computes for the
    every-rollable-chunk map's gear, so these figures are roughly five times
    too fast there. They are still two orders of magnitude better than the
    twenty-four seconds they replace, and the honest fix is to price goals
    after the enrichment rather than to fudge a multiplier here.
    """
    found: dict[str, float] = {}

    cox_run = PUBLISHED_RAID_SECONDS[CHAMBERS]
    cox_chances = xeric.item_chances(xeric.NORMAL)
    for item, chance in cox_chances.items():
        if chance > 0:
            found[item] = cox_run / chance
    # The two Challenge Mode exclusives, at the slower Challenge Mode raid.
    cm_run = PUBLISHED_RAID_SECONDS[f"{CHAMBERS} (challenge)"]
    for item, chance in xeric.CHALLENGE_ONLY.items():
        found[item] = cm_run / chance

    tob_run = PUBLISHED_RAID_SECONDS[THEATRE]
    for item, chance in theatre.item_chances(theatre.NORMAL).items():
        if chance > 0:
            found[item] = tob_run / chance

    toa_run = PUBLISHED_RAID_SECONDS[TOMBS]
    # **The guide's implied points, not this module's derived ones** - see
    # `tombs.guide_implied_points`, which measures the gap at 41%.
    toa_chance = tombs.unique_chance(
        tombs.guide_implied_points(), tombs.GUIDE_RAID_LEVEL
    )
    for item, weight in tombs.weights_at(tombs.GUIDE_RAID_LEVEL).items():
        if toa_chance * weight > 0:
            found[item] = toa_run / (toa_chance * weight)

    # **The pets, which are tertiary rolls and not table entries.** Without
    # them the walk read an olmlet at 0.4 hours and a Lil' Zik at 4.3, off the
    # same 150-raids-an-hour drop route everything else here replaces.
    cox_unique = sum(cox_chances.values())
    if cox_unique > 0:
        found["Olmlet"] = cox_run / (cox_unique * OLMLET_GIVEN_UNIQUE)
    found["Lil' Zik"] = tob_run / LIL_ZIK_CHANCE
    pet = toa_pet_chance(tombs.guide_implied_points(), tombs.GUIDE_RAID_LEVEL)
    if pet > 0:
        found["Tumeken's guardian"] = toa_run / pet

    for raid, tiers in CAPE_TIERS.items():
        run = PUBLISHED_RAID_SECONDS[
            f"{CHAMBERS} (challenge)" if raid == CHAMBERS else raid
        ]
        for cape, completions in tiers.items():
            found[cape] = run * completions

    found.update(tombs.item_seconds())
    return found


def best_for(comparison: Comparison) -> RaidAnswer | None:
    """The single fastest raid, for an objective only one of them can meet.

    **Only meaningful for a named unique.** A green log needs all three, so
    taking a minimum of them would answer a question nobody asked.
    """
    priced = [a for a in comparison.answers if a.hours < float("inf")]
    return min(priced, key=lambda a: a.hours) if priced else None
