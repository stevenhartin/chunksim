"""How fast a skill goes, and why.

**The climb is walked in bands, not priced at one rate.** `estimate.py` used to
take the fastest method open at the player's *current* level and apply it to the
whole climb to 99; when nothing open at that level had a scraped rate the climb
was priced at `DEFAULT_XP_PER_HOUR`, which is how Herblore 1-99 came out at
13,034 hours on a map that knew eighteen real Herblore rates. A player does not
train at one rate: they level into better methods, and the same climb walked
band by band is 100 hours.

Split out of `estimate.py` because "how fast does this skill go" is a
self-contained question that two other modules already wanted independently -
and because `estimate.py` was the largest module in `costing/`.

Pure, and a pure function of `(Derived, ChunkInfo, Heuristics, skill, levels)`:
no disk, no network, no module-level mutable state. The one ordering subtlety is
in `training_hours` - see the tie-break there, which exists so `--jobs` cannot
change the *labels* either.
"""

from __future__ import annotations

from typing import Any
from chunksim.costing.heuristics import DEFAULT_XP_PER_HOUR
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.model.experience import MAX_LEVEL, level_for_xp, xp_for_level
from chunksim.derive.pipeline import Derived
from chunksim.costing.heuristics import (
    GOTR_SOURCE,
    TITHE_SOURCE,
    ComputedMethod,
    Heuristics,
    Rate,
)
from chunksim.costing.recipe_rates import RECIPE_SOURCE
from chunksim.costing.spells import SPELL_SOURCE
from chunksim.model.summary import _mapping
from chunksim.costing.heuristics import activity_name
import re
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class TrainingOption:
    """One way of training a skill, and what it would cost per hour."""

    method: str
    level: int | None
    xp_per_hour: float
    #: Where the rate came from - `exact`, `contained`, or `default` for the
    #: floor. A `default` option is not evidence of anything; it is the absence
    #: of evidence, priced conservatively.
    match: str
    #: Seconds of gathering per XP, for the materials this method consumes
    #: that the published rate assumes to hand. `0.0` means either that it
    #: consumes nothing or that no recipe describes it - see
    #: `effective_xp_per_hour`.
    material_seconds_per_xp: float = 0.0
    #: Experience in **this same skill** earned while gathering what the
    #: method consumes, per experience the method itself pays. Zero is the
    #: common case - a log chopped for a bow pays Woodcutting, which does
    #: nothing for a Fletching climb. See `effective_xp_per_hour`.
    material_xp_per_xp: float = 0.0
    #: Which rate source won this option, as `Rate.source` spells it. Carried
    #: so a caller can prefer a *particular* method over a faster one -
    #: `estimate.py` does exactly that for Tithe Farm, which loses on hours
    #: and wins on calendar. Not serialised: it is a routing detail, where
    #: `match` is the thing a reader is being asked to judge.
    source: str = ""
    #: The override path behind `xp_per_hour`, or `""` where the file
    #: describes nothing that would move it. **Set here rather than worked
    #: out later**: `method` is `activity_name(name)`, a display string, where
    #: the config key is the challenge's own name - so the one thing a reader
    #: needs cannot be recovered from what is carried alongside it.
    knob: str = ""

    @property
    def effective_xp_per_hour(self) -> float:
        """The rate including the time to obtain what the method consumes,
        **and the experience obtaining it pays**.

        **What the climb is ranked and priced on**, where `xp_per_hour` is what
        a guide publishes. The two differ because a published rate is quoted
        with the materials to hand - "299,000 an hour at anglerfish" describes
        the range, not the trip before it - and on a chunk map the trip is
        often the whole cost. Ranking on the published figure picked xerician
        robes for Crafting at 167,200/hr on a map where one fabric takes 95
        seconds to obtain and a robe needs four: 831/hr once the fabric is
        counted, and a method no player would touch.

        Added as seconds per XP rather than as a ratio so the two halves
        compose exactly: `3600 / (processing + gathering)`.

        **Gathering can pay the same skill, and charging its time without
        crediting its experience is the same error in reverse.** Sorting a
        salvage pays 95 Sailing and costs 34 seconds of *salvaging*, which
        itself pays 200 Sailing - so the pair is 295 experience for 36
        seconds, not 95. `material_xp_per_xp` is that credit, per experience
        the method itself pays, and it is only ever the *same* skill: chopping
        a log for a bow pays Woodcutting, which does nothing for a Fletching
        climb and is not counted here.
        """
        if self.xp_per_hour <= 0:
            return 0.0
        earned = 1.0 + max(0.0, self.material_xp_per_xp)
        if self.material_seconds_per_xp <= 0:
            # Returned unchanged rather than round-tripped through the
            # arithmetic, which is the common case and would otherwise turn
            # 50,000 into 50,000.00000000001.
            return self.xp_per_hour * earned
        return 3600.0 * earned / (3600.0 / self.xp_per_hour + self.material_seconds_per_xp)

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "level": self.level,
            "xp_per_hour": round(self.xp_per_hour, 1),
            "effective_xp_per_hour": round(self.effective_xp_per_hour, 1),
            "material_seconds_per_xp": round(self.material_seconds_per_xp, 4),
            "material_xp_per_xp": round(self.material_xp_per_xp, 4),
            "match": self.match,
            # **Added for the methods overlay and the `training` subcommand.**
            # A rate without its provenance is the thing this whole layering
            # exists to stop being shown: `source` says which layer answered
            # and `knob` is the path that would move it, which is what makes a
            # row clickable in the GUI rather than a line of text.
            "source": self.source,
            "knob": self.knob,
        }


def training_options(
    derived: Derived, chunk_info: ChunkInfo, heuristics: Heuristics, skill: str
) -> tuple[TrainingOption, ...]:
    """Every reachable primary method for `skill` that has a *real* rate.

    **What `training_bands` builds the climb out of**, and what the tooltip
    falls back to when a climb has no bands worth showing: the methods a reader
    could correct.

    Sorted fastest first. Only methods with a real rate: a list of level-1
    options all sitting at the floor would say "here are your alternatives"
    and mean "there are none".

    Only methods with a real rate: a list of level-1 options all sitting at the
    floor would say "here are your alternatives" and mean "there are none".
    """
    # **Some skills have no `Primary` challenge to join a rate to** - there is
    # no "Train Strength" task anywhere in the export and no "bury a bone"
    # one either - so their rate does not come from a challenge at all. See
    # `costing/combat_xp.py` and `costing/prayer.py`, both of which reach here
    # through `Heuristics.computed`.
    #: **Added to the challenge-derived list, not substituted for it.** For
    #: combat that is the same thing - the export has no primary challenge to
    #: find - but Prayer has six of them, offering fish at a shrine and shards
    #: at a libation bowl, and a computed bury rate is an *alternative* to
    #: those rather than a replacement. The band walk picks per level.
    found: list[TrainingOption] = [
        TrainingOption(
            method=option.method,
            level=option.level,
            xp_per_hour=option.xp_per_hour,
            match=option.match,
            # **A computed method pays for what it consumes, same as a scraped
            # one.** Missing this was a real defect and a large one: moving the
            # Giants' Foundry out of the scrape and into a module dropped the
            # bars it eats and read Smithing 1-99 at 54.5 hours against 144.5.
            # Measured over the whole export, the six preforms are the only
            # computed methods whose task has a material cost at all - every
            # other activity here consumes nothing - so this charges what is
            # there and is silent everywhere else.
            #
            # A computed activity that *includes* its own gathering must be
            # kept out of `material_seconds_per_xp` rather than handled here;
            # Guardians of the Rift is the precedent, and `_material_cost`
            # carries the argument for why.
            material_seconds_per_xp=_computed_material_cost(heuristics, option),
            material_xp_per_xp=_computed_material_credit(heuristics, option),
            knob=option.knob,
        )
        for option in heuristics.computed.get(skill) or ()
        if option.xp_per_hour > 0
    ]
    # **A computed method about the *same task* replaces the scrape rather than
    # joining it**, which is the one place the layering in `costing/__init__.py`
    # was not being applied. See `_modelled_tasks`.
    modelled = _modelled_tasks(heuristics, skill)

    challenges = _mapping(chunk_info.challenges, skill)
    for name in derived.challenges.valid.get(skill) or {}:
        challenge = challenges.get(name)
        if not isinstance(challenge, dict) or challenge.get("Primary") is not True:
            continue
        rate = heuristics.xp_per_hour(name, skill)
        if rate.match == "default":
            continue
        if name in modelled:
            continue
        level = challenge.get("Level")
        found.append(
            TrainingOption(
                method=activity_name(name),
                level=int(level) if isinstance(level, (int, float)) else None,
                xp_per_hour=rate.value,
                match=rate.match,
                material_seconds_per_xp=_material_cost(heuristics, name, rate),
                material_xp_per_xp=heuristics.material_xp_per_xp.get(name, 0.0),
                source=rate.source,
                # `name`, not `activity_name(name)`: the file is keyed by the
                # challenge, and the display string is not a key anywhere.
                knob=f"training/{name}/{skill}",
            )
        )
    return tuple(sorted(found, key=lambda option: -option.effective_xp_per_hour))


def _modelled_tasks(heuristics: Heuristics, skill: str) -> frozenset[str]:
    """Tasks whose scraped rate a computed method supersedes.

    **A guide figure is one number and a model is a curve, and where both
    describe the same task the curve wins.** That is the argument
    `gathering.apply` already makes for the node walk - "a success curve and a
    training guide measure the same thing, and the curve is evaluated at *this*
    map's level with *this* map's best axe where the guide is somebody else's
    account" - and until this existed it stopped at the node walk. A
    `ComputedMethod` was *added* to the scraped list instead, so the flat figure
    stayed in and won wherever the curve happened to be below it, which is
    precisely the low-level stretch the curve exists to correct.

    Measured on the every-rollable-chunk map, five tasks were being priced by
    the guide over part of their range despite having a model:

        Underwater Thieving  84,560 flat against 1,005 at level 1 - eight of
                             eleven points, and 84x out at the bottom
        Tempoross            62,000 flat, which is the *level 70* figure, from
                             level 35 where the table says 30,000
        Mine iron ore        45,000 flat from level 20, off a guide row whose
                             own title says "below level 60"
        Track a herbiboar    137,000 flat against a curve the module was
                             written because the flat number is wrong
        Pyramid Plunder 7-8  benign, inside the model's own residual

    **A hand pin still beats both**, which is why this needs `Heuristics.pinned`
    rather than reading the source string: an override lands in `training`
    looking exactly like the guide row it replaced, and `overrides.json` is the
    top of the layering by design.

    Keyed on the `knob`, because that is already the task-and-skill a method
    would be corrected through and so is the only handle that cannot drift from
    the name the file uses.
    """
    prefix = "training/"
    suffix = f"/{skill}"
    return frozenset(
        option.knob[len(prefix) : -len(suffix)]
        for option in heuristics.computed.get(skill) or ()
        if option.xp_per_hour > 0
        and option.knob.startswith(prefix)
        and option.knob.endswith(suffix)
        and option.knob[len(prefix) : -len(suffix)] not in heuristics.pinned
    )


#: Rate sources whose figure already covers getting the materials, so the
#: walk must not charge for them a second time. See `_material_cost`.
#:
#: **A spell is the fourth and joined for the same reason a recipe did.**
#: `costing/spells.py` charges the challenge's own `Items` - the runes *and*
#: the big bone, the jewellery, the ore - so `spell_material_costs` adding the
#: runes again would bill half of it twice.
_ALL_INCLUSIVE_SOURCES = frozenset(
    {RECIPE_SOURCE, GOTR_SOURCE, TITHE_SOURCE, SPELL_SOURCE}
)


def _computed_material_cost(
    heuristics: Heuristics, option: ComputedMethod
) -> float:
    """What a computed method's own task consumes, per XP it pays.

    Keyed on the `knob`, which is the only handle a `ComputedMethod` carries
    to the challenge it is about - and the same one `_modelled_tasks` uses, so
    the two cannot disagree about which task a module is speaking for. A knob
    naming no task, as `combat_xp`'s `monster_stats/<monster>` does, costs
    nothing because there is nothing to look up.
    """
    prefix = "training/"
    if not option.knob.startswith(prefix):
        return 0.0
    task = option.knob[len(prefix) :].rsplit("/", 1)[0]
    return heuristics.material_seconds_per_xp.get(task, 0.0)


def _computed_material_credit(
    heuristics: Heuristics, option: ComputedMethod
) -> float:
    """Same-skill experience a computed method's gathering pays, per its own.

    The `_computed_material_cost` twin, keyed the same way and for the same
    reason: the two halves of one question must not be able to disagree about
    which task they are answering.
    """
    prefix = "training/"
    if not option.knob.startswith(prefix):
        return 0.0
    task = option.knob[len(prefix) :].rsplit("/", 1)[0]
    return heuristics.material_xp_per_xp.get(task, 0.0)


def _material_cost(heuristics: Heuristics, name: str, rate: Rate) -> float:
    """Gathering seconds per XP, **only where the rate does not already have
    them.**

    The two rate sources measure different things and adding the same seconds
    to both counts them twice. A money-making guide quotes a method with its
    materials to hand - "299,000 an hour at anglerfish" describes the range,
    not the trip before it - so the gathering has to be added. A
    `recipe_rates` figure is `experience * 3600 / (0.6*ticks + materials +
    overhead)`, which already *is* the whole cycle, so adding it again halves
    the method.

    Measured on a simulated run of the second map when this was found: 653
    options carried a
    computed rate and had their materials charged twice, against 58 with a
    guide rate that were correct. `Build a ~|4-poster|~` read 9,270/hr against
    a true 18,187.

    Keyed on the source rather than on a flag, because the layering is what
    decides it: `recipe_rates.apply` puts a computed rate *below* a scraped
    one, so whichever survives is what the option is priced on.

    **Guardians of the Rift is the second such source, and it is not a recipe
    at all.** Its essence is mined inside the minigame - that is most of what
    the twenty minutes is - and the wiki's figure is what comes out of the
    whole thing, so charging the rune's essence again would bill the same work
    twice. It is the one activity here where "gather" and "train" are not two
    steps that could be timed apart.
    """
    if rate.source in _ALL_INCLUSIVE_SOURCES:
        return 0.0
    return heuristics.material_seconds_per_xp.get(name, 0.0)


@dataclass(frozen=True)
class TrainingBand:
    """One stretch of a climb, trained by one method at one rate."""

    level_from: int
    level_to: int
    xp: int
    xp_per_hour: float
    method: str
    #: `exact`, `contained`, or `default` for the floor. Carried per band
    #: rather than per skill because a climb can be part measured and part
    #: guessed, and which part is which is the first thing a reader asks.
    match: str
    #: What a guide publishes for this method, where `xp_per_hour` is that
    #: figure *plus* the time to obtain what the method consumes. Equal when
    #: the method consumes nothing, or when no recipe describes it. Carried so
    #: a reader can see why a 290,000/hr shark reads as 148,000 - see
    #: `TrainingOption.effective_xp_per_hour`.
    published_xp_per_hour: float = 0.0
    #: The override path behind this band's rate - see `TrainingOption.knob`.
    knob: str = ""

    @property
    def material_hours(self) -> float:
        """The share of this band's hours spent gathering, not performing."""
        if self.published_xp_per_hour <= 0 or self.xp_per_hour <= 0:
            return 0.0
        return self.xp / self.xp_per_hour - self.xp / self.published_xp_per_hour

    @property
    def hours(self) -> float:
        return self.xp / self.xp_per_hour if self.xp_per_hour > 0 else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "level_from": self.level_from,
            "level_to": self.level_to,
            "xp": self.xp,
            "published_xp_per_hour": round(self.published_xp_per_hour, 1),
            "material_hours": round(self.material_hours, 2),
            "xp_per_hour": round(self.xp_per_hour, 1),
            "method": self.method,
            "match": self.match,
            "hours": round(self.hours, 2),
        }


def training_bands(
    options: Sequence[TrainingOption],
    start_xp: int,
    target_level: int,
    *,
    floor: float = DEFAULT_XP_PER_HOUR,
) -> tuple[TrainingBand, ...]:
    """The climb from `start_xp` to `target_level`, split where the rate changes.

    **Walked on the XP axis rather than the level axis**, which is what makes
    the arithmetic exact and the quest grant free: `start_xp` is a total, so a
    quest reward is added to it and the bands below it simply vanish - there is
    no separate level adjustment to keep in step.

    The method available at a level is a **running maximum**: a method open at
    54 is still open at 90, so the rate can only rise as the climb goes on, and
    a band boundary is a level where it does. That monotonicity is why **the
    floor can only ever be the first band** - which is the whole of "the floor
    stays visible". It is a named stretch carrying its own XP and hours, not a
    number averaged into the total where nobody can see it.

    Because `xp_for_level` is exact integers and the bands telescope,
    `sum(band.xp)` is exactly the XP between the two ends and
    `sum(band.hours)` is exactly `xp / blended_rate`.

    **The tie-break is load-bearing.** Two methods at the same level and the
    same rate must label their band identically in every worker process, or
    `--jobs` changes the text while leaving the number alone - which is worse
    than changing both, because nothing would catch it. Hence the sort on
    `(level, -rate, method)`.
    """
    target_xp = xp_for_level(min(int(target_level), MAX_LEVEL))
    if start_xp >= target_xp:
        return ()

    # **Ranked on `effective_xp_per_hour`, not the published one.** A method
    # whose materials cost more than the action is not a fast method, however
    # fast the guide says the action is; see `TrainingOption`.
    ranked = sorted(
        (
            (
                max(1, option.level or 1),
                option.effective_xp_per_hour,
                option.method,
                option.match,
                option.xp_per_hour,
                option.knob,
            )
            for option in options
        ),
        key=lambda entry: (entry[0], -entry[1], entry[2]),
    )
    steps: list[tuple[int, float, str, str, float, str]] = []
    best = 0.0
    for level, rate, method, match, published, knob in ranked:
        if rate <= best:
            continue
        best = rate
        steps.append((xp_for_level(level), rate, method, match, published, knob))

    edges = sorted(
        {start_xp, target_xp} | {xp for xp, *_ in steps if start_xp < xp < target_xp}
    )
    bands: list[TrainingBand] = []
    for lower, upper in zip(edges, edges[1:]):
        open_now = [step for step in steps if step[0] <= lower]
        rate, method, match, published, knob = (
            open_now[-1][1:] if open_now else (floor, "", "default", floor, "")
        )
        bands.append(
            TrainingBand(
                level_from=level_for_xp(lower),
                level_to=level_for_xp(upper),
                xp=upper - lower,
                xp_per_hour=rate,
                method=method,
                match=match,
                published_xp_per_hour=published,
                knob=knob,
            )
        )
    return tuple(bands)


@dataclass(frozen=True)
class LampGrant:
    """Quest XP you may spend on one of several skills, left unspent.

    `skills` empty means "any skill". `count` is how many separate lamps of
    `xp` the quest pays - Dragon Slayer II hands out four of 25,000.

    **Deliberately not allocated.** Spending a lamp well is an optimisation
    (put it where it saves the most hours), and this module does not optimise;
    guessing would quietly reduce the estimate on the strength of a choice
    nobody made. They are reported instead, so the reader can see there is
    experience on the table.
    """

    quest: str
    skills: tuple[str, ...]
    xp: int
    count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "quest": self.quest,
            "skills": list(self.skills),
            "xp": self.xp,
            "count": self.count,
        }


#: `"Attack|Defence|Strengthx4"` - the trailing `xN` is how many lamps, and the
#: `|` list is what each may be spent on. 356 of the export's 378 reward keys
#: are a bare skill name; 17 carry a count and 5 are a choice of one.
_LAMP_COUNT = re.compile(r"^(?P<names>.+?)x(?P<count>\d+)$")


def _reward_key(key: str) -> tuple[tuple[str, ...], int]:
    """`"Anyx6"` -> `((), 6)`; `"Cooking"` -> `(("Cooking",), 1)`."""
    match = _LAMP_COUNT.fullmatch(key)
    names, count = (match["names"], int(match["count"])) if match else (key, 1)
    parts = tuple(part.strip() for part in names.split("|") if part.strip())
    return ((), count) if parts == ("Any",) else (parts, count)


def quest_xp_grants(
    derived: Derived, chunk_info: ChunkInfo
) -> tuple[dict[str, int], tuple[LampGrant, ...]]:
    """XP from quests this map can finish, by skill, plus the unspent lamps.

    **Exactly the quests the `quests` bucket is already charging you for**, and
    that is the invariant that makes double counting impossible. The set walked
    here is `other_tasks`' `active` groups - post-completions, post-superseded,
    post-backlog - which is the same set `estimate._quest_tasks` prices the
    hours of. A quest already done is not in it, so its reward cannot be granted
    twice; a quest that cannot be reached is not in it either.

    **Completability needs no graph walk.** `XpReward` sits on exactly the 209
    `… Complete the quest` terminals and nowhere else, and challenge validity is
    transitive through `Tasks` - so the terminal being active *is* "every step
    is reachable and it is not already done".

    The time and the experience live in different buckets on purpose: the
    quest's hours are the quests bucket's, its XP is the skilling bucket's. Note
    the deliberate asymmetry that follows - hours are prorated by how many steps
    are left, XP is not, because the game pays the reward on completion.
    """
    grants: dict[str, int] = {}
    lamps: list[LampGrant] = []
    quests = _mapping(chunk_info.challenges, "Quest")
    category = derived.other_tasks.categories.get("Quest")
    for group in category.groups if category else ():
        for name in group.active:
            entry = quests.get(name)
            reward = entry.get("XpReward") if isinstance(entry, dict) else None
            if not isinstance(reward, dict):
                continue
            for key, value in reward.items():
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    continue
                skills, count = _reward_key(str(key))
                if len(skills) == 1 and count == 1:
                    grants[skills[0]] = grants.get(skills[0], 0) + int(value)
                else:
                    lamps.append(
                        LampGrant(quest=group.name, skills=skills, xp=int(value), count=count)
                    )
    return grants, tuple(sorted(lamps, key=lambda lamp: (lamp.quest, -lamp.xp)))
