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

SKILL = "Farming"

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

#: Herbs one seed returns, on average. **The wiki's own empirical figure** -
#: `Herb patch` states "an average of 8.8 herbs per seed in a standard
#: (non-protected) herb patch" and computes its profit tables from it. The
#: standard patch rather than the boosted one, which is the conservative end
#: taken everywhere else here: ultracompost, magic secateurs and the Farming
#: cape all raise it and a chunk map may hold none of them.
HERBS_PER_SEED = 8.8

#: The export's own marker for a herb grown in an ordinary patch. Both are
#: required: `Category` alone also catches the allotments and trees, and
#: `Objects` alone would catch anything else standing at a herb patch. The
#: three Chambers of Xeric herbs (`buchu`, `golpar`, `noxifer`) carry neither
#: and are correctly left out - they are not farmed, they are found.
HERB_CATEGORY = "Normal Farming"
HERB_PATCH = "Herb patch"


def harvest_yields(
    challenges: Mapping[str, Any], valid: Mapping[str, Any]
) -> dict[str, float]:
    """`{task: herbs per action}` for every herb a map can grow.

    **What stops the item walk charging a whole seed against one herb.** A
    ranarr seed prices at 163s and a patch returns 8.8 herbs for it, so the
    per-herb cost is 19s rather than 169s - and a grimy ranarr weed was the
    single most expensive thing in Herblore's inputs. See
    `Heuristics.harvest_yield`, which this fills, and `estimate._route_hours`,
    which spends it.

    Joined on upstream's own `Category`/`Objects` rather than on the task's
    words, for the reason every join in this project prefers a field: the
    export says which challenges are ordinary farming and which are not.
    """
    found: dict[str, float] = {}
    for task in valid or {}:
        challenge = challenges.get(task)
        if not isinstance(challenge, dict) or challenge.get("Primary") is not True:
            continue
        categories = challenge.get("Category")
        objects = challenge.get("Objects")
        if not isinstance(categories, list) or HERB_CATEGORY not in categories:
            continue
        if not isinstance(objects, list) or HERB_PATCH not in objects:
            continue
        found[task] = HERBS_PER_SEED
    return found


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


#: Export span -> the crop name `Module:Skill calc/Farming` uses, for the
#: eleven that differ. **A vocabulary difference and nothing more**: every one
#: of these lands in the same bucket its neighbours do once it joins, so what
#: the table buys is the *sentence* a reader sees rather than a rate.
#:
#: Three shapes, all of which turn up elsewhere in this project: a plural the
#: calculator writes and upstream does not (`Marigolds`), a `(Farming)`
#: disambiguator the calculator carries (`Oak (Farming)`), and the calculator
#: naming the *product* where upstream names the plant (`Calquat fruit`,
#: `Cactus spine`, and the three anima seeds).
CROP_ALIASES: dict[str, str] = {
    "attas plant": "Attas",
    "cactus (farming)": "Cactus spine",
    "calquat tree": "Calquat fruit",
    "huasca": "Huasca",
    "iasor plant": "Iasor",
    "kronos plant": "Kronos",
    "marigold": "Marigolds",
    "nasturtium": "Nasturtiums",
    "oak tree": "Oak (Farming)",
    "willow tree": "Willow Tree (Farming)",
    "zamorak's grapes": "Grapes",
}

#: The prefix upstream gives an uncleaned herb, which the calculator does not.
_GRIMY = "grimy "

#: Upstream's own patch name -> the schedule line it is, for the patches that
#: are one. **The second half of the join, and the better half**: a crop
#: challenge states `Objects: ["Hops Patch"]` whether or not the calculator's
#: table has heard of the crop, so where `CROP_ALIASES` is a rename this is
#: upstream telling us what kind of thing a crop is.
#:
#: `flax`, `hemp` and `cotton` are why it exists: all three are planted in a
#: hops patch exactly as barley and the four hops are, and none of them has a
#: row in `Module:Skill calc/Farming`. Upstream says `Hops Patch` on all
#: eight, so they classify together without the calculator having to catch up.
#:
#: **`Hops` and `Flower` are deliberately absent from
#: `DEFAULT_HARVESTS_PER_DAY`** and are listed here anyway, because the point
#: is to reach the "not in the schedule" sentence rather than to fall off the
#: end of the join. A patch not named here, and a challenge that states no
#: patch at all, keep `unpriced`.
PATCH_KEYS: dict[str, str] = {
    "allotment patch": "Allotment",
    "bush patch": "Bush",
    "cactus patch": "Cactus",
    "flower patch": "Flower",
    "fruit tree patch": "Fruit tree",
    "hardwood tree patch": "Hardwood",
    "herb patch": "Herb",
    "hops patch": "Hops",
    "redwood tree patch": "Redwood",
    "tree patch": "Tree",
}


def patch_key(challenge: Mapping[str, Any]) -> str | None:
    """The schedule line upstream's own `Objects` says this crop grows on."""
    for name in challenge.get("Objects") or ():
        if isinstance(name, str):
            found = PATCH_KEYS.get(name.strip().lower())
            if found is not None:
                return found
    return None


def crop_for(task: str, crops: Sequence[Crop]) -> Crop | None:
    """The crop a `Grow a ~|...|~` challenge is about, or `None`.

    Joined on upstream's own marked span, which is what `~|...|~` is for -
    the challenge states no `Output` for a crop and its verb-stripped words
    are a sentence. Doses of vocabulary are stripped in the order they matter:
    the `grimy ` prefix first, then `CROP_ALIASES`.
    """
    span = task.partition("~|")[2].rpartition("|~")[0].strip().lower()
    if not span:
        return None
    by_name = {crop.name.lower(): crop for crop in crops}
    for key in (span, span.removeprefix(_GRIMY)):
        found = by_name.get(key) or by_name.get(CROP_ALIASES.get(key, "").lower())
        if found is not None:
            return found
    return None


def refused(
    valid: Mapping[str, Any],
    crops: Sequence[Crop],
    challenges: Mapping[str, Any] = {},
    *,
    harvests_per_day: Mapping[str, float] | None = None,
    level: int = 99,
) -> dict[str, str]:
    """`{task: why}` for every crop the schedule already answers for.

    **The report was contradicting the estimate.** `plan_for` picks one crop
    per line of the schedule and the estimate's whole Farming answer *is*
    those picks - so `Grow a ~|grimy torstol|~` printed `unpriced`, the one
    word meaning "nothing reached this", about the very method the model
    spends. See `coverage.REFUSED`.

    Three sentences, because the rows are three different things:

    - **the schedule's own pick** - priced, on the calendar axis, and there is
      deliberately no hourly figure for it;
    - **outranked on its line** - a ranking rather than a gap; the schedule
      takes the best crop per line and this one lost;
    - **not in the schedule at all** - the decision this module's docstring
      already records for hops, flowers, belladonna, spirit trees and
      celastrus.

    **What it must not do is invent an hourly rate.** A herb harvest is a
    hundred experience for a few seconds of clicking, so a per-crop rate reads
    enormous and would win every band - the exact error `estimate.
    _farming_bands` exists to avoid, and the reason this module reports days.

    **Two ways in, and the second is upstream's rather than the wiki's.**
    `crop_for` matches the calculator's table; where that has no row,
    `patch_key` reads the patch off the challenge's own `Objects` - which is
    how `flax`, `hemp` and `cotton` classify with the hops they are planted
    beside despite the calculator carrying none of the three. A challenge that
    states neither keeps `unpriced`, which is honest and is what the two
    Chambers of Xeric herbs and the Sorceress's Garden get: they name no patch
    because they are not farmed.

    `level` is where the schedule is read, and only the *winner named in a
    sentence* depends on it: at 99 the herb line takes torstol, lower down it
    takes something else, and either way there is no hourly rate for any of
    them.
    """
    reachable = valid.get(SKILL) or {}
    if not reachable:
        return {}
    # **The crop table is optional and the patch fallback is not.** With no
    # table `plan_for` names no winner, so an in-schedule line reads
    # "another crop" - vague but true; what still works is the sentence that
    # matters most here, since a hops patch is excluded whatever is planted.
    rates = dict(
        DEFAULT_HARVESTS_PER_DAY if harvests_per_day is None else harvests_per_day
    )
    winners = {run.key: run.crop for run in plan_for(
        crops, level, harvests_per_day=rates
    ).runs}
    found: dict[str, str] = {}
    for task in reachable:
        crop = crop_for(task, crops)
        if crop is not None:
            key = schedule_key(crop)
            mine = crop.name
        else:
            body = challenges.get(task)
            key = patch_key(body) if isinstance(body, dict) else None
            mine = ""
            if key is None:
                continue
        if key is None or rates.get(key, 0.0) <= 0:
            found[task] = (
                "deliberately not in the growing schedule - see costing/farming.py"
            )
        elif mine and winners.get(key) == mine:
            found[task] = (
                f"the growing schedule's {key} crop - Farming is priced in days"
            )
        else:
            found[task] = f"outranked on the {key} line, where the schedule takes "
            found[task] += str(winners.get(key) or "another crop")
    return found


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
