"""Which training methods this project can price, and what priced them.

**The estimator's own answer to "how much of this is modelled".** Every other
module here computes a *rate*; this one computes what the rates are made of, so
`chunksim training` and the GUI's methods overlay can show it and a reader can
tell a method that is slow from one nothing has reached.

### The statuses, and why three of them are separated rather than lumped

    modelled     this project computed it - a curve, a recipe, a counted mechanic
    pinned       a hand correction in `overrides.json`, which outranks all of it
    published    somebody's figure, joined by name
    guess        a number chosen so there is one (`costing/rumours.py`, `stated`)
    unpriced     nothing reached it; the 1,000/hr floor is what estimate uses
    unreachable  no map can even *do* it, so no layer was ever asked

`guess` is separated from `modelled` because it is the one that should shrink
and the one a reader most needs warning about: it looks exactly like a rate
and is an admission. `pinned` is separated from `published` for the opposite
reason - `overrides.json` is the top of the layering by design, so a pin is
not a gap.

**`unreachable` is separated from both, and it is the one that was wrong.**
Every computed layer walks the derivation's `valid` set, so a challenge
outside it is never offered to any of them and keeps whatever the raw scrape
left in `Heuristics.training`. Reported as `published` that reads "somebody's
guide decides this method", when the truth is "upstream's own gates put it out
of reach and nothing here was ever asked". Measured against the ceiling -
every rollable chunk, a real map's rules - **all 47 of the export's remaining
`published` rows were this**, and not one reachable method anywhere was on a
published figure. The distinction matters because the two are different work:
a published row is a modelling gap, an unreachable one is a fact about the
game (`Ancient brew` wants nihil dust, `Guthix rest` wants a quest the ceiling
cannot finish).

**`match` decides the status and `pinned` overrides it**, which is the same
reading `training._modelled_tasks` takes: an override lands in `training`
looking exactly like the guide row it replaced, so the *only* way to tell is
`Heuristics.pinned`.

### What "unpriced" means depends on which question was asked

Over one map it means "this map cannot price it" - the materials may be
unreachable, or the model's own gate may not be held. Over the whole export
(`chunksim training` with no map) it means "no map could", which is the useful
form for deciding what to model next.

Pure: takes a derivation and a priced `Heuristics` and returns rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from chunksim.costing.heuristics import Heuristics, activity_name
from chunksim.costing.training import TrainingOption, training_options
from chunksim.derive.active_tasks import DISPLAY_SKILLS
from chunksim.derive.pipeline import Derived
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.model.summary import _mapping

#: The export's challenge categories that are skills somebody trains.
#: `derive/active_tasks.py` owns the list; `Quest`, `Diary`, `Extra`,
#: `Nonskill` and `Combat` are categories rather than skills and a training
#: report listing them would be listing five things nobody levels.
SKILLS: tuple[str, ...] = tuple(sorted(DISPLAY_SKILLS))

#: `Rate.match` values this project produced itself.
MODELLED_MATCHES = frozenset({"modelled", "computed", "confirmed"})

#: The one that is an admission rather than a measurement.
GUESS_MATCHES = frozenset({"guess"})

#: The statuses, least actionable first - so a table printing them reversed
#: reads best-to-worst and ends on the two that are not the model's fault.
STATUSES: tuple[str, ...] = (
    "unreachable",
    "unpriced",
    "guess",
    "published",
    "pinned",
    "modelled",
)


def status_of(match: str, *, pinned: bool = False, reachable: bool = True) -> str:
    """Which of `STATUSES` a rate belongs to.

    **`reachable` is checked first and overrules everything**, including a
    pin: no layer was asked about a challenge outside the derivation's `valid`
    set, so whatever sits in `Heuristics.training` for it is a leftover rather
    than a decision. See the module docstring for what reporting those as
    `published` was saying.
    """
    if not reachable:
        return "unreachable"
    if pinned:
        return "pinned"
    if not match or match == "default":
        return "unpriced"
    if match in MODELLED_MATCHES:
        return "modelled"
    if match in GUESS_MATCHES:
        return "guess"
    return "published"


@dataclass(frozen=True)
class MethodStatus:
    """One primary training method and what priced it."""

    task: str
    skill: str
    #: The level it opens at, per the export. `None` where the export says
    #: nothing, which is rare and is not the same as level 1.
    level: int | None
    #: The headline rate, before what the method consumes is charged.
    xp_per_hour: float
    #: What it is actually worth once gathering its materials is charged and
    #: any same-skill experience that gathering pays is credited. This is what
    #: `training_bands` ranks on, so it is what "best" means.
    effective_xp_per_hour: float
    match: str
    source: str
    status: str
    #: The `overrides.json` path that would move it, or `""`.
    knob: str

    @property
    def method(self) -> str:
        """The activity's display name, markup stripped."""
        return activity_name(self.task)

    def as_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "method": self.method,
            "skill": self.skill,
            "level": self.level,
            "xp_per_hour": round(self.xp_per_hour, 1),
            "effective_xp_per_hour": round(self.effective_xp_per_hour, 1),
            "match": self.match,
            "source": self.source,
            "status": self.status,
            "knob": self.knob,
        }


def primary_tasks(chunk_info: ChunkInfo, skill: str) -> dict[str, Mapping[str, Any]]:
    """Every `Primary` challenge the export files under `skill`.

    **Not `derived.challenges.valid`**, which is the map's answer. This is the
    export's, and it is what `chunksim training` with no map reports over.
    """
    return {
        task: challenge
        for task, challenge in _mapping(chunk_info.challenges, skill).items()
        if isinstance(challenge, dict) and challenge.get("Primary") is True
    }


def statuses_for(
    chunk_info: ChunkInfo,
    heuristics: Heuristics,
    skill: str,
    reachable: Mapping[str, Any],
    *,
    only_reachable: bool = True,
) -> tuple[MethodStatus, ...]:
    """Every primary method of `skill`, with what priced it, worst first.

    `reachable` is the derivation's `valid` set for this skill and is always
    what decides the `unreachable` status. `only_reachable` decides whether
    the unreachable ones are *listed*: the per-map report wants only what the
    map can do, and the export-wide one wants the whole census.

    **Computed methods are folded in by knob, not appended.** A model that
    supersedes a challenge's rate (`training._modelled_tasks`) writes no entry
    in `Heuristics.training` at all, so reading that alone would report a
    modelled method as unpriced - which is exactly backwards.
    """
    offered = primary_tasks(chunk_info, skill)
    tasks = (
        {task: c for task, c in offered.items() if task in reachable}
        if only_reachable
        else offered
    )
    computed = _computed_by_knob(heuristics, skill)
    found: list[MethodStatus] = []
    for task, challenge in tasks.items():
        knob = f"training/{task}/{skill}"
        level = challenge.get("Level")
        model = computed.get(knob)
        if model is not None:
            rate, match, source = model.xp_per_hour, model.match, model.source
        else:
            found_rate = heuristics.xp_per_hour(task, skill)
            rate, match, source = found_rate.value, found_rate.match, found_rate.source
        found.append(
            MethodStatus(
                task=task,
                skill=skill,
                level=int(level) if isinstance(level, (int, float)) else None,
                xp_per_hour=rate,
                effective_xp_per_hour=rate,
                match=match,
                source=source,
                status=status_of(
                    match,
                    pinned=task in heuristics.pinned,
                    reachable=task in reachable,
                ),
                knob=knob,
            )
        )
    return tuple(sorted(found, key=lambda row: (STATUSES.index(row.status), -row.xp_per_hour)))


@dataclass(frozen=True)
class _Computed:
    xp_per_hour: float
    match: str
    source: str


def _computed_by_knob(heuristics: Heuristics, skill: str) -> dict[str, _Computed]:
    """The best computed rate per task, for the skill.

    A model contributes a *band per level*, so a task can appear many times;
    the highest is what the method reaches, which is what a coverage report is
    reporting the existence of rather than the value of.
    """
    best: dict[str, _Computed] = {}
    for option in heuristics.computed.get(skill) or ():
        if option.xp_per_hour <= 0 or not option.knob:
            continue
        seen = best.get(option.knob)
        if seen is None or option.xp_per_hour > seen.xp_per_hour:
            best[option.knob] = _Computed(
                option.xp_per_hour, option.match, f"computed:{option.method}"
            )
    return best


def best_methods(
    derived: Derived,
    chunk_info: ChunkInfo,
    heuristics: Heuristics,
    levels: Mapping[str, int],
    skills: Sequence[str],
) -> dict[str, TrainingOption | None]:
    """`{skill: the best method its level can use}`, or `None` where none is.

    **Ranked on `effective_xp_per_hour`, which is what `training_bands` ranks
    on** - so this names the method the estimate would actually spend rather
    than the one with the biggest headline. A guide's figure quoted with its
    materials free is exactly the row that wins the second ranking and loses
    the first.

    **Gated on the level the map is at**, because "best" for somebody at 40 is
    not the level-90 method. A method with no level at all is treated as open.
    """
    found: dict[str, TrainingOption | None] = {}
    for skill in skills:
        at = levels.get(skill, 1)
        options = [
            option
            for option in training_options(derived, chunk_info, heuristics, skill)
            if option.level is None or option.level <= at
        ]
        found[skill] = max(
            options, key=lambda option: option.effective_xp_per_hour, default=None
        )
    return found


def skill_methods(
    derived: Derived,
    chunk_info: ChunkInfo,
    heuristics: Heuristics,
    skill: str,
) -> tuple[TrainingOption, ...]:
    """Every reachable method of one skill, best first.

    `training_options` already sorts on `effective_xp_per_hour` and already
    drops the ones sitting at the floor, which is the same reading a reader of
    this list wants: a page of level-1 methods all quoting 1,000/hr would say
    "here are your alternatives" and mean "there are none".
    """
    return training_options(derived, chunk_info, heuristics, skill)
