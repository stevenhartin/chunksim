"""How fast a made thing is made, from the wiki's own per-action numbers.

**The rate this replaces was a guess by association.** `heuristics.py` joins a
training method to a money-making guide by *name*, which reaches 225 of 2,657
methods and, when it reaches, is still only evidence that someone wrote a guide
with a similar title. `remote/recipes.py` brings back the two numbers that
actually decide a rate - experience per action and the action's tick cost - for
3,889 recipes across thirteen skills, and this module turns them into an hourly
figure:

    xp_per_hour = experience * 3600 / (0.6 * ticks + input_seconds)

Three parts, each of which has to be right for the answer to mean anything:

**The join is exact, on `Output`.** A challenge carries the item it produces
(`Mix a ~|combat potion|~` -> `Combat potion(4)`) and a recipe carries the item
it produces, so the two meet on a full string with no fuzz anywhere. Measured
against the real export: 93% of Cooking's primary methods, 94% of Herblore's,
95% of Fletching's and Runecraft's, 91% of Crafting's. Contrast
`heuristics.py`, whose joins really do span two vocabularies and need a
`contained` tier - here there is nothing to be fuzzy about, and a name that
does not match exactly is a method this module declines to price.

**Gathering skills are absent, and that is the honest answer.** Fishing,
Woodcutting, Firemaking and Farming join at ~0% because a fishing spot is not a
recipe: the wiki records no `{{Recipe}}` for it, so there are no ticks and no
materials to read. They keep whatever the scrape gave them and wait for a model
of their own. Reporting a 0% join as coverage of the skill would read as this
module having failed at something it never attempted.

**An input you cannot obtain drops the method.** `input_seconds` is the caller's
`_item_hours` walk, which prices the cheapest route to a material and returns
`None` when there is not one. Treating that `None` as zero - pricing the action
at its tick cost alone - makes a method whose ingredients are unreachable the
*fastest* thing on the map, and it would open a band at whatever level it sits
at. So a method with an unpriceable input is not a slow method here; it is not a
method at all.

Two judgement calls worth knowing before reading a number:

- **A variant is assumed available.** `Bronze bar` has a normal-furnace recipe
  at 5 ticks and a Blast Furnace one at 2, and nothing in the export says
  whether this map reaches a blast furnace. The faster of the two wins, which
  matches how the item walk already picks the cheapest route, and is optimistic
  in exactly the way that picks up a facility a chunk map may not hold.
- **Input time is *serial* with the action.** A tick spent making is not a tick
  spent gathering, so the two add. That is right for the materials you buy or
  make and pessimistic for the ones that come off a monster you were killing
  anyway - the alternative, ignoring input time entirely, is the error this
  module exists to remove.

Pure: the caller supplies both the recipes and the pricing callable, so nothing
here reads disk or network and no `_Walk` has to cross a module boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Callable, Mapping, Sequence

from fray_claude.costing.heuristics import DEFAULT_XP_PER_HOUR, Rate
from fray_claude.derive.task_names import strip_task_markup
from fray_claude.model.chunkinfo import ChunkInfo
from fray_claude.model.summary import _mapping
from fray_claude.remote.recipes import Recipe

#: One game tick, in seconds. The whole engine runs on it.
TICK_SECONDS = 0.6

#: How this module labels a rate it computed, in `Rate.match`. It beats only
#: `default` - see `apply`, and the measurement behind that in the docstring.
COMPUTED_MATCH = "computed"

#: The verbs a challenge name starts with, stripped to leave the thing made.
#: **Construction needs this and almost nothing else does.** Its challenges
#: carry `Output Object` - the furniture - where every other skill carries
#: `Output`, so the `Output` join reached 28 of its 602 methods. The recipe's
#: own output *is* the furniture name, and `Build a ~|mahogany table|~` says
#: so in the task name. Measured across all thirteen skills, adding this route
#: gains **500 Construction methods** and six elsewhere: it is a Construction
#: fix that happens to be expressible generally, not a new fuzzy tier.
_VERBS = re.compile(
    r"^(?:build|craft|cook|mix|smith|smelt|fletch|make|cut|clean|enchant|cast"
    r"|bake|brew|spin|weave|string|carve|repair)\s+(?:an?\s+|the\s+)?",
    re.IGNORECASE,
)


def join_keys(challenge: Mapping[str, Any], task: str) -> tuple[str, ...]:
    """Every name a challenge offers a recipe, most specific first.

    `Output` is upstream's own statement of what the method produces and is
    tried first. `Output Object` is the same thing for a built object. The
    task's own words are last and are still an **exact** match - the verb is
    removed mechanically and the remainder compared whole - so this stays a
    join on a full string rather than becoming a containment tier.
    """
    keys: list[str] = []
    for field in ("Output", "Output Object"):
        value = challenge.get(field)
        if isinstance(value, str) and value.strip():
            keys.append(value.strip())
    keys.append(_VERBS.sub("", strip_task_markup(task)).strip())
    return tuple(key for key in dict.fromkeys(keys) if key)


#: Seconds an action costs beyond its own animation: the withdraw, the click,
#: the walk back. **Fitted, not chosen** - `recipe_overhead.py` re-runs the
#: fit and is the authority on this number. Over the 24 methods where a recipe
#: and an *exactly* joined guide both exist and the materials price free,
#: tick-math alone is a median 1.38x fast; 0.4s an action brings that to
#: 1.14x. It is also the right order for the thing it stands in for - 28 items
#: a bank trip at ~20s a trip is 0.7s an item - which is the only reason to
#: trust a one-parameter fit over 24 points at all.
ACTION_OVERHEAD_SECONDS = 0.4

@dataclass(frozen=True)
class ActionRate:
    """One training method, priced from the action it actually performs."""

    task: str
    skill: str
    xp_per_hour: float
    experience: float
    ticks: int
    #: Seconds of gathering per action, across every material.
    input_seconds: float
    output: str
    materials: tuple[str, ...] = ()

    @property
    def performing_seconds(self) -> float:
        """The action alone: its animation and the overhead, no materials.

        **What `estimate._route_hours` needs and `action_seconds` is not.**
        The walk charges a conversion's inputs itself, so handing it the whole
        cycle would bill the materials twice.
        """
        return TICK_SECONDS * self.ticks + ACTION_OVERHEAD_SECONDS

    @property
    def action_seconds(self) -> float:
        """The whole cycle: the animation, the materials, and the overhead.

        All three, because leaving the overhead out here and adding it in
        `action_seconds()` is how the fit harness came to subtract it twice.
        """
        return TICK_SECONDS * self.ticks + self.input_seconds + ACTION_OVERHEAD_SECONDS

    def as_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "skill": self.skill,
            "xp_per_hour": round(self.xp_per_hour, 1),
            "experience": self.experience,
            "ticks": self.ticks,
            "input_seconds": round(self.input_seconds, 2),
            "output": self.output,
            "materials": list(self.materials),
        }


@dataclass(frozen=True)
class RecipeCoverage:
    """What the join reached, per skill, so a total can be read honestly."""

    #: Skill -> (methods priced, primary methods offered).
    skills: dict[str, tuple[int, int]] = field(default_factory=dict)
    #: Methods that joined a recipe but lost an input to `None`.
    dropped: tuple[str, ...] = ()

    @property
    def priced(self) -> int:
        return sum(priced for priced, _ in self.skills.values())

    @property
    def offered(self) -> int:
        return sum(offered for _, offered in self.skills.values())

    def as_dict(self) -> dict[str, Any]:
        return {
            "priced": self.priced,
            "offered": self.offered,
            "skills": {
                skill: {"priced": priced, "offered": offered}
                for skill, (priced, offered) in sorted(self.skills.items())
            },
            "dropped": list(self.dropped),
        }


def index_recipes(recipes: Sequence[Recipe]) -> dict[str, tuple[Recipe, ...]]:
    """`recipes` grouped by the item they produce, order preserved.

    Several recipes can make one item - `Bronze bar` has three - so this is a
    tuple per output rather than a single winner. Which of them a map can
    actually use is not knowable from the export; `rate_for` takes the fastest
    that prices.
    """
    grouped: dict[str, list[Recipe]] = {}
    for recipe in recipes:
        grouped.setdefault(recipe.output, []).append(recipe)
    return {output: tuple(found) for output, found in grouped.items()}


def material_seconds(
    recipe: Recipe, input_seconds: Callable[[str, float], float | None]
) -> float | None:
    """Seconds of gathering for one action's materials, or `None` if any has
    no route.

    `None` propagates deliberately: see the module docstring on why an
    unpriceable input drops the method rather than falling back to ticks.
    """
    total = 0.0
    for material in recipe.materials:
        seconds = input_seconds(material.name, material.quantity)
        if seconds is None:
            return None
        total += seconds
    return total


def action_seconds(
    recipe: Recipe, input_seconds: Callable[[str, float], float | None]
) -> float | None:
    """Seconds for one whole action of `recipe`, or `None`."""
    materials = material_seconds(recipe, input_seconds)
    if recipe.ticks is None or materials is None:
        return None
    return TICK_SECONDS * recipe.ticks + ACTION_OVERHEAD_SECONDS + materials


def rate_for(
    recipes: Sequence[Recipe], input_seconds: Callable[[str, float], float | None]
) -> tuple[Recipe, float, float] | None:
    """The fastest of `recipes` that prices end to end.

    `(recipe, rate, material seconds)` - the last **summed, never recovered by
    subtracting the ticks back off the total**. That subtraction left 4.4e-16
    where a shop-bought material should have been exactly zero, and every
    caller asking "did the materials cost anything" got the wrong answer for
    seventeen of twenty-one methods.

    **`None` drops the method, and drops its material cost with it - which
    biases the wrong way.** Refusing the *rate* is right: tick-math over inputs
    nothing can price is a made-up number. But `computed_rates` is also the
    only source of `material_seconds_per_xp`, so a method that keeps a scraped
    rate then ranks as though its inputs were free - and the inputs in question
    are precisely the ones too hard to price. Measured on both cached maps (60
    such methods on `fray`, 76 on `verf`) **not one wins a band**, so this is
    recorded rather than fixed; it would start to matter on a map whose Cooking
    or Crafting climb has nothing better to offer.
    """
    best: tuple[Recipe, float, float] | None = None
    for recipe in recipes:
        materials = material_seconds(recipe, input_seconds)
        if recipe.ticks is None or materials is None:
            continue
        seconds = TICK_SECONDS * recipe.ticks + ACTION_OVERHEAD_SECONDS + materials
        if seconds <= 0:
            continue
        rate = recipe.experience * 3600.0 / seconds
        if best is None or rate > best[1]:
            best = (recipe, rate, materials)
    return best


def computed_rates(
    chunk_info: ChunkInfo,
    valid: Mapping[str, Mapping[str, Any]],
    recipes: Mapping[str, Sequence[Recipe]],
    input_seconds: Callable[[str, float], float | None],
) -> tuple[dict[str, ActionRate], RecipeCoverage]:
    """Every reachable primary method `recipes` can price, keyed by task name.

    The key is the raw challenge name, because that is what
    `Heuristics.training` is keyed by everywhere else - markup and all.

    Only methods in `valid` are considered, so this inherits the derivation's
    reachability gate rather than inventing a second one.
    """
    priced: dict[str, ActionRate] = {}
    coverage: dict[str, tuple[int, int]] = {}
    dropped: list[str] = []

    for skill, rows in sorted(recipes.items()):
        by_output = index_recipes(list(rows))
        # Matched case-insensitively: upstream writes `Build a ~|mahogany
        # table|~` where the wiki page is `Mahogany table`, and the case is
        # the only thing between them.
        by_output = {**{name.lower(): found for name, found in by_output.items()}}
        challenges = _mapping(chunk_info.challenges, skill)
        offered = found = 0
        for task in sorted(valid.get(skill) or {}):
            challenge = challenges.get(task)
            if not isinstance(challenge, dict) or challenge.get("Primary") is not True:
                continue
            offered += 1
            keys = join_keys(challenge, task)
            output = next((key for key in keys if key.lower() in by_output), None)
            if output is None:
                continue
            candidates = by_output[output.lower()]
            chosen = rate_for(candidates, input_seconds)
            if chosen is None:
                dropped.append(task)
                continue
            recipe, rate, materials = chosen
            found += 1
            priced[task] = ActionRate(
                task=task,
                skill=skill,
                xp_per_hour=rate,
                experience=recipe.experience,
                ticks=recipe.ticks or 0,
                input_seconds=materials,
                output=output,
                materials=tuple(material.name for material in recipe.materials),
            )
        if offered:
            coverage[skill] = (found, offered)

    return priced, RecipeCoverage(skills=coverage, dropped=tuple(sorted(dropped)))


def apply(
    training: Mapping[str, Mapping[str, Rate]],
    computed: Mapping[str, ActionRate],
    pinned: frozenset[str] = frozenset(),
) -> dict[str, dict[str, Rate]]:
    """`training` with a computed rate wherever there was no real one.

    **`defaults < computed < scraped < overrides`, and the ordering is the
    measured part of this module.** It is not the layering `dps_bridge` uses,
    which puts its computed kill rates *above* the scrape - and the difference
    is not taste. A simulated fight and a money-making guide answer the same
    question, so the better-informed one should win. A recipe and a guide do
    not:

    - **Where the materials are cheap, tick-math is roughly the guide.** It ran
      a median 1.38x above when materials were free; now that they cost
      something the six comparable methods straddle it, x0.68 to x2.73. That
      is agreement, not evidence either way.
    - **Where the materials are expensive, it is a floor by a mile.** The other
      26 span x0.0043 to x2.73, most of them at the bottom, because this
      charges you six minutes for the silver bar where the guide assumes you
      bought it. That is the right model for a chunk account and the wrong
      number to compare against a guide.

    So a guide, when there is one, keeps the method. What this replaces is the
    **1,000/hr floor**, which is not evidence of anything, and there are far
    more of those: 852 methods priced on the benchmark map against 58 that had a guide.

    `pinned` is the set of task names `heuristics/overrides.json` speaks about;
    a hand pin outranks everything, as it does everywhere else.

    Nothing is removed. A method this could not price keeps what it had, so the
    result is never worse-informed than the input.
    """
    merged = {task: dict(skills) for task, skills in training.items()}
    for task, rate in computed.items():
        if task in pinned:
            continue
        existing = merged.get(task, {}).get(rate.skill)
        if existing is not None and existing.match != "default":
            continue
        # **A computed rate slower than the floor is not evidence.** The floor
        # is a deliberate stand-in for ignorance, set low so a gap reads as
        # slow rather than free; a computed number *below* it says this model
        # is missing something about the method - a bulk action, a faster
        # variant, materials someone already has - far more often than it says
        # the method is genuinely glacial.
        #
        # It is not hypothetical. Supercompost is the one Farming method the
        # recipe data reaches on the benchmark map, and 15 watermelons an
        # action price it at 173 xp/hr, which the band walk then applied to
        # the whole climb: **Farming 1 -> 99 at 75,353 hours**. 130 of 852
        # computed rates sit below the floor, across nine skills.
        if rate.xp_per_hour < DEFAULT_XP_PER_HOUR:
            continue
        merged.setdefault(task, {})[rate.skill] = Rate(
            value=rate.xp_per_hour, source="recipe", match=COMPUTED_MATCH
        )
    return merged
