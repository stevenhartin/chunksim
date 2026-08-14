"""Farming, which is measured in days rather than hours.

**Every other skill in this project is a rate, and Farming is not.** A crop
grows for hours or days while you do something else, so what limits the skill
is how many harvests a day you get round to. Priced as a rate it came out at
**75,353 hours for 1 to 99** off the one method the recipe data reached
(supercompost, 8.5 xp for fifteen watermelons), which is the kind of number
that says the model is wrong rather than the skill is slow.

So this reports **two** answers and they measure different things:

- `active_hours` - time actually spent planting and harvesting. It is small,
  it is comparable with every other skill's hours, and it is what goes in the
  estimate's bucket.
- `days` - calendar time, from how many harvests a day the schedule allows.
  It is the thing that actually constrains Farming and is reported beside the
  hours rather than added to them, because a day of waiting is not a day of
  playing.

**The schedule is the model.** `DEFAULT_HARVESTS_PER_DAY` says how many
harvests of each kind a player gets through in a day, and every number in it is
a stated figure rather than a measurement - redwood at 0.14 is one a week
because that is how long it takes to grow, hardwood at 0.33 is one every three
days, and eight herb runs is a reasonably attentive day. Tunable under
`farming` in `heuristics/overrides.json`.

**What is deliberately not farmed**: hops and flowers (nobody trains on them),
belladonna, spirit trees and celastrus (gated, or with no reliable seed
source). They are absent from the schedule rather than set to zero, so adding
one back is a line in the overrides file rather than a code change.

The crop data is `remote/farming.py`'s. `xp` there is per *item* and `plantXp`
is once, so a harvest pays `plant + xp * yield` - and yield is one for a tree,
which is checked once, against several for a herb or an allotment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from chunksim.remote.farming import Crop

#: Harvests a day, by schedule key. See the module docstring: stated figures,
#: and the model rather than an input to it.
DEFAULT_HARVESTS_PER_DAY: dict[str, float] = {
    "Fruit tree": 1.0,
    "Tree": 3.0,
    "Cactus": 3.0,
    "Bush": 3.0,
    "Allotment": 8.0,
    "Herb": 8.0,
    "Hardwood": 1.0 / 3.0,
    "Redwood": 1.0 / 7.0,
}

#: `Special` covers everything the module could not classify, so the schedule
#: key for those comes from the crop's own name. Anything not listed here and
#: not in `DEFAULT_HARVESTS_PER_DAY` by patch type is not farmed.
_SPECIAL_KEYS: dict[str, str] = {
    "Cactus spine": "Cactus",
    "Potato cactus": "Cactus",
    "Teak tree": "Hardwood",
    "Mahogany tree": "Hardwood",
    "Camphor tree": "Hardwood",
    "Ironwood tree": "Hardwood",
    "Rosewood tree": "Hardwood",
    "Redwood tree": "Redwood",
}

#: Items a harvest yields, where the crop does not yield exactly one. The
#: first four are the calculator's own published assumptions; herbs and
#: allotments are **ours**, standing in for a `ChanceToSave` whose per-crop
#: `Chance1`/`Chance99` live in the calculator's JavaScript and in no page this
#: can read. Six is roughly three harvest lives plus supercompost.
#:
#: It matters less than it looks: a magic tree is 13,914 xp against a ranarr's
#: 30, so the trees carry the climb and the assumption moves the total by
#: very little.
_YIELDS: dict[str, float] = {"Herb": 6.0, "Allotment": 6.0, "Bush": 4.0}
_CROP_YIELDS: dict[str, float] = {
    "Cactus spine": 3.0,
    "Potato cactus": 6.0,
    "Grapes": 10.0,
    "Celastrus tree": 6.0,
}

#: Seconds of clicking one harvest costs - travel to the patch, pick it, and
#: replant. A stated figure, and the only one that decides `active_hours`.
HARVEST_SECONDS = 60.0


@dataclass(frozen=True)
class FarmingRun:
    """One kind of harvest, and what a day of them pays."""

    key: str
    crop: str
    level: int
    experience: float
    harvests_per_day: float

    @property
    def xp_per_day(self) -> float:
        return self.experience * self.harvests_per_day

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "crop": self.crop,
            "level": self.level,
            "experience": round(self.experience, 1),
            "harvests_per_day": round(self.harvests_per_day, 3),
            "xp_per_day": round(self.xp_per_day, 1),
        }


@dataclass(frozen=True)
class FarmingPlan:
    """A day of farming: what is planted, what it pays, what it costs."""

    runs: tuple[FarmingRun, ...] = ()

    @property
    def xp_per_day(self) -> float:
        return sum(run.xp_per_day for run in self.runs)

    @property
    def harvests_per_day(self) -> float:
        return sum(run.harvests_per_day for run in self.runs)

    @property
    def hours_per_day(self) -> float:
        return self.harvests_per_day * HARVEST_SECONDS / 3600.0

    def days_for(self, experience: float) -> float:
        """Calendar days to earn `experience` on this schedule."""
        return experience / self.xp_per_day if self.xp_per_day > 0 else 0.0

    def hours_for(self, experience: float) -> float:
        """Hours of *clicking* to earn `experience` - not calendar time."""
        return self.days_for(experience) * self.hours_per_day

    def as_dict(self) -> dict[str, Any]:
        return {
            "xp_per_day": round(self.xp_per_day, 1),
            "hours_per_day": round(self.hours_per_day, 2),
            "runs": [run.as_dict() for run in self.runs],
        }


def schedule_key(crop: Crop) -> str | None:
    """Which line of the schedule `crop` belongs to, or `None` if unfarmed."""
    if crop.patch in DEFAULT_HARVESTS_PER_DAY:
        return crop.patch
    return _SPECIAL_KEYS.get(crop.name)


def expected_yield(crop: Crop) -> float:
    """Items one harvest of `crop` gives."""
    named = _CROP_YIELDS.get(crop.name)
    if named is not None:
        return named
    return _YIELDS.get(crop.patch, 1.0)


def harvest_experience(crop: Crop) -> float:
    """Experience one harvest pays: planting once, then per item taken."""
    return crop.plant_experience + crop.experience * expected_yield(crop)


def plan_for(
    crops: Sequence[Crop],
    level: int,
    *,
    harvests_per_day: Mapping[str, float] | None = None,
    reachable_seeds: frozenset[str] | None = None,
) -> FarmingPlan:
    """The best crop for each line of the schedule at `level`.

    Best by experience per harvest rather than by level: the two usually agree,
    and where they do not the payout is what matters.

    `reachable_seeds`, when given, drops a crop whose seed this map cannot get
    - a farming schedule you have no seeds for is not a schedule.
    """
    # `or` would read an *empty* schedule as "use the defaults", which is the
    # opposite of what passing one means: someone who farms nothing farms
    # nothing.
    rates = dict(
        DEFAULT_HARVESTS_PER_DAY if harvests_per_day is None else harvests_per_day
    )
    best: dict[str, Crop] = {}
    for crop in crops:
        key = schedule_key(crop)
        if key is None or rates.get(key, 0.0) <= 0 or crop.level > level:
            continue
        if reachable_seeds is not None and crop.seed and crop.seed not in reachable_seeds:
            continue
        standing = best.get(key)
        if standing is None or harvest_experience(crop) > harvest_experience(standing):
            best[key] = crop
    return FarmingPlan(
        runs=tuple(
            FarmingRun(
                key=key,
                crop=crop.name,
                level=crop.level,
                experience=harvest_experience(crop),
                harvests_per_day=rates[key],
            )
            for key, crop in sorted(best.items())
        )
    )
