"""Which training methods this project can price, and what priced them.

**The estimator's own answer to "how much of this is modelled".** Every other
module here computes a *rate*; this one computes what the rates are made of, so
`chunksim training` and the GUI's methods overlay can show it and a reader can
tell a method that is slow from one nothing has reached.

### The statuses, and why three of them are separated rather than lumped

    modelled       this project computed it - a curve, a recipe, a counted mechanic
    pinned         a hand correction in `overrides.json`, which outranks all of it
    published      somebody's figure, joined by name
    guess          a number chosen so there is one (`costing/rumours.py`, `stated`)
    unpriced       nothing reached it; the 1,000/hr floor is what estimate uses
    refused        nothing quoted it *on purpose*, and the row says whose call
    unreachable    *this map* cannot do it, which is ordinary
    uncompletable  *no* map can do it, which is a finding rather than a state

**`refused` is `unpriced` with a reason, and separating them is the point.**
Several models decline a method by name - Woodcutting's swaying tree is one
object worth one experience, an impling is a wandering spawn nothing publishes
a rate for, `costing/disclaimed.py` carries a page that disclaims itself. Each
of those refusals was made *so that* the method would not be quoted a number,
and every one of them then read as `unpriced` - the one word that means
"somebody should go and close this". The two are opposite claims and the
report now says which: **`unpriced` is a gap and `refused` is a decision**,
with the deciding module's own sentence printed beside the row
(`Heuristics.refused`).

**It renames only what would otherwise be `unpriced`**, which is what keeps it
honest and is the difference from `one-off`. A decoration has an arithmetic
rate and is exempt anyway, so `one_off` is checked ahead of every priced tier;
a refusal has no rate by construction, so it is checked last - and the day
somebody finds the missing mechanic, the model wins and the refusal goes quiet
without anything having to be edited. That is exactly what
`costing/disclaimed.py` promises about its own entry.

`guess` is separated from `modelled` because it is the one that should shrink
and the one a reader most needs warning about: it looks exactly like a rate
and is an admission. `pinned` is separated from `published` for the opposite
reason - `overrides.json` is the top of the layering by design, so a pin is
not a gap.

**`uncompletable` and `unreachable` are the same test asked of different
worlds, and only one of them is news.** A method a particular map cannot do is
the ordinary condition of a chunk map. A method the *ceiling* cannot do -
every rollable chunk unlocked - is a statement that no player could ever
perform it, which is either a fact about the game or a defect here, and the
report says which by naming the blocker (`MethodStatus.blocker`). See
`blocker_for`: measured against the ceiling the 307 split into 134 wanting an
item nothing provides (Leagues rewards, `Vorkath's stuffed head`), 108 behind
a quest the ceiling cannot finish, 18 wanting an object, 13 in a chunk or
section the roll set does not cover, and 34 with no stated requirement at all
- and it is that last group, plus anything unexpected in the others, that is
worth chasing.

**Separating them from the priced statuses is the correction that mattered.**
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

from chunksim.costing import oneoff
from chunksim.costing.heuristics import Heuristics, activity_name
from chunksim.costing.training import TrainingOption, training_options
from chunksim.derive.active_tasks import DISPLAY_SKILLS
from chunksim.derive.pipeline import Derived, MapState
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
#: reads best-to-worst and ends on the three that are not the model's fault.
#:
#: `one-off` sits beside the two absent statuses rather than near `unpriced`
#: for the same reason they do: it is a statement about the *challenge*, not
#: about how well this project priced it. See `costing/oneoff.py`.
STATUSES: tuple[str, ...] = (
    "uncompletable",
    "unreachable",
    "one-off",
    "refused",
    "unpriced",
    "guess",
    "published",
    "pinned",
    "modelled",
)

#: What a method some model declined to quote is called. Distinct from
#: `unpriced`, which is the same absence with nobody's name on it, and from
#: `ONE_OFF`, which exempts a method that *does* have a rate. See the module
#: docstring; the sentence comes from `Heuristics.refused`.
REFUSED = "refused"

#: What a decoration placed once is called - `costing/oneoff.py` names them.
ONE_OFF = "one-off"

#: `MethodStatus.blocker` for a *reachable* method whose recipe lost an
#: input. Deliberately not in `BLOCKERS`: that tuple is the breakdown of what
#: the world lacks, printed for `uncompletable` rows only, and this is a
#: statement about a method the world plainly has.
INPUT = "input"

#: What a method the reported world cannot do is called. The ceiling report
#: passes `UNCOMPLETABLE`, because there nothing else can be true; a per-map
#: report passes `UNREACHABLE`, where it is just this map.
UNREACHABLE = "unreachable"
UNCOMPLETABLE = "uncompletable"


def status_of(
    match: str,
    *,
    pinned: bool = False,
    reachable: bool = True,
    absent: str = UNREACHABLE,
    one_off: bool = False,
    refused: bool = False,
) -> str:
    """Which of `STATUSES` a rate belongs to.

    **`reachable` is checked first and overrules everything**, including a
    pin: no layer was asked about a challenge outside the derivation's `valid`
    set, so whatever sits in `Heuristics.training` for it is a leftover rather
    than a decision. See the module docstring for what reporting those as
    `published` was saying.

    **`one_off` is checked second**, ahead of every priced tier: a decoration
    a map cannot reach is still first of all unreachable, but one it *can*
    reach is exempt from being priced at all rather than priced badly. See
    `costing/oneoff.py`.

    **`refused` is checked last**, and only ever renames `unpriced`: a model
    that declined to quote a number has not thereby claimed a number somebody
    else computed is wrong. See the module docstring.
    """
    if not reachable:
        return absent
    if one_off:
        return ONE_OFF
    if pinned:
        return "pinned"
    if not match or match == "default":
        return REFUSED if refused else "unpriced"
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
    #: For an `unreachable`/`uncompletable` row, which requirement branch
    #: blocked it (`BLOCKERS`) and what it named. `("", "")` for every priced
    #: row, since there is nothing blocking one.
    blocker: str = ""
    blocked_by: str = ""

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
            "blocker": self.blocker,
            "blocked_by": self.blocked_by,
        }


@dataclass(frozen=True)
class Reachability:
    """What a derived world can provide, for explaining what it cannot do.

    Assembled once per report from a `Derived` - see `from_derived` - because
    `blocker_for` is asked about every primary challenge and each answer is a
    few set lookups.
    """

    items: frozenset[str]
    objects: frozenset[str]
    #: Every valid task name across every category, which is what a
    #: challenge's `Tasks` branch names.
    tasks: frozenset[str]
    #: NPCs and monsters the map can get to, which is what a challenge's
    #: `NPCs` branch names.
    npcs: frozenset[str]
    #: Chunk ids the map holds, unlocked or walked into.
    chunks: frozenset[str]
    #: Rules the *player* turned off. Upstream gates a challenge by naming a
    #: rule in its `Category`, so an off rule is a choice rather than a gap -
    #: which is exactly the distinction this whole report is for.
    rules_off: frozenset[str] = frozenset()

    @classmethod
    def from_derived(cls, derived: Derived, state: MapState | None = None) -> "Reachability":
        return cls(
            items=frozenset(derived.challenges.available_items),
            objects=frozenset(derived.challenges.available_objects),
            tasks=frozenset(
                task for per in derived.challenges.valid.values() for task in per
            ),
            npcs=frozenset(derived.source_index.npcs) | frozenset(derived.source_index.monsters),
            # Expanded as well as unlocked: a named area is walked into
            # rather than rolled, and calling that a location blocker would
            # report the derivation's own answer back as a defect.
            chunks=frozenset(derived.expanded_chunks) | frozenset(derived.reachable_sections),
            rules_off=frozenset(
                name
                for name, value in (state.rules if state is not None else {}).items()
                if value is False
            ),
        )


#: What `blocker_for` can say, and the order it tries them in - most specific
#: first, since a challenge behind a quest usually also lists the items that
#: quest would hand over.
BLOCKERS: tuple[str, ...] = (
    "rule",
    "superseded",
    "task",
    "item",
    "object",
    "npc",
    "location",
    "unstated",
)


def blocker_for(
    challenge: Mapping[str, Any], reach: Reachability
) -> tuple[str, str]:
    """`(kind, what)` for why a world cannot do `challenge`.

    **Upstream's own requirement branches, in order, most decisive first.** A
    rule the player turned off is checked before anything, because upstream
    gates a whole family by naming the rule in its `Category` and the family's
    items are then beside the point - `Make a ~|rune felling axe|~ (alt)` is
    behind `Secondary Primary`, not behind its anvil. A missing `Tasks` entry
    comes next for the same reason: a quest-gated challenge routinely lists
    the items that quest hands over, so reporting the item would name a
    symptom.

    `unstated` is the one worth chasing: the challenge asks for nothing this
    can see and is still invalid, so it is a `Category` upstream applies for
    reasons not in `rules`, an unported pass, or a defect here.
    """
    for name in challenge.get("Category") or ():
        if isinstance(name, str) and name in reach.rules_off:
            return "rule", name
    # **Upstream's own "this is the fallback form" marker.** A barehanded
    # butterfly catch names the netted one as its `BackupParent`, and where
    # the parent is valid upstream drops the backup - so it is not a gap of
    # any kind, it is the same catch counted once. Checked before the
    # requirement branches because the backup's own requirements are met.
    parent = challenge.get("BackupParent")
    if isinstance(parent, str) and parent in reach.tasks:
        return "superseded", parent
    for task in challenge.get("Tasks") or {}:
        if isinstance(task, str) and task not in reach.tasks:
            return "task", task
    for item in challenge.get("Items") or ():
        if isinstance(item, str):
            name = item.replace("*", "").replace("[+]", "").strip()
            if name and name not in reach.items:
                return "item", name
    for obj in challenge.get("Objects") or ():
        if isinstance(obj, str):
            name = obj.replace("[+]", "").strip()
            if name and name not in reach.objects:
                return "object", name
    for npc in challenge.get("NPCs") or ():
        if isinstance(npc, str) and npc not in reach.npcs:
            return "npc", npc
    for chunk in challenge.get("Chunks") or ():
        if isinstance(chunk, str) and chunk not in reach.chunks:
            return "location", chunk
    return "unstated", ""


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
    absent: str = UNREACHABLE,
    reach: Reachability | None = None,
) -> tuple[MethodStatus, ...]:
    """Every primary method of `skill`, with what priced it, worst first.

    `reachable` is the derivation's `valid` set for this skill and is always
    what decides the absent status. `only_reachable` decides whether those are
    *listed*: the per-map report wants only what the map can do, and the
    export-wide one wants the whole census. `absent` names them - `UNREACHABLE`
    for one map, `UNCOMPLETABLE` for the ceiling - and `reach` is what lets
    each say *why*.

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
        blocker, blocked_by = (
            ("", "")
            if task in reachable or reach is None
            else blocker_for(challenge, reach)
        )
        model = computed.get(knob)
        if model is not None:
            rate, match, source = model.xp_per_hour, model.match, model.source
        else:
            found_rate = heuristics.xp_per_hour(task, skill)
            rate, match, source = found_rate.value, found_rate.match, found_rate.source
        # **An unpriced method says which ingredient it wanted, where it
        # wanted one.** `blocker`/`blocked_by` were only ever filled for a
        # method the world cannot reach; a reachable one that joined a recipe
        # and lost an input is the other half of "why is there no number
        # here", and `recipe_rates.unroutable` is the answer. Blank stays
        # blank: no recipe joined at all, or one joined and was refused for
        # want of a stated duration, and neither is an ingredient to name.
        if not blocker and task in reachable:
            wanted = heuristics.unroutable.get(task, "")
            if wanted:
                blocker, blocked_by = INPUT, wanted
        # **A refusal replaces the source rather than the rate**, because
        # there is no rate: the column that would say `wiki:herblore` says
        # whose decision the blank is instead. See `REFUSED`.
        why = heuristics.refused.get(task, "") if task in reachable else ""
        if why:
            source = why
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
                    absent=absent,
                    one_off=bool(oneoff.reason(task)),
                    refused=bool(why),
                ),
                knob=knob,
                blocker=blocker,
                blocked_by=blocked_by,
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
