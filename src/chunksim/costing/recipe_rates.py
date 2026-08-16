"""How fast a made thing is made, from the wiki's own per-action numbers.

**The rate this replaces was a guess by association.** `heuristics.py` joins a
training method to a money-making guide by *name*, which reaches 225 of 2,657
methods and, when it reaches, is still only evidence that someone wrote a guide
with a similar title. `remote/recipes.py` brings back the two numbers that
actually decide a rate - experience per action and the action's tick cost - for
3,889 recipes across thirteen skills, and this module turns them into an hourly
figure:

    xp_per_hour = experience * 3600 / (0.6 * ticks + input_seconds + trip_share)

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
materials to read. Reporting a 0% join as coverage of the skill would read as
this module having failed at something it never attempted. **`costing/gathering.py`
is the model of their own they were waiting for**, and it is where a log's or an
ore's cost now comes from - including the cost of the ones this module's recipes
consume, which is the join between the two halves.

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

from chunksim.costing.heuristics import DEFAULT_XP_PER_HOUR, Rate
from chunksim.derive.task_names import strip_task_markup
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.model.summary import _mapping
from chunksim.remote.recipes import Recipe

#: One game tick, in seconds. The whole engine runs on it.
TICK_SECONDS = 0.6

#: How this module labels a rate it computed, in `Rate.match`. It beats the
#: scrape's two tiers as well as `default` - see `apply`, and `REPLACEABLE`
#: for why that is a whitelist rather than a check against `modelled`.
COMPUTED_MATCH = "computed"

#: The `Rate.match` tiers a computed recipe rate may replace: the floor, and
#: the scrape's `exact` and `contained` joins. **A whitelist, so it fails
#: closed** - `gathering.py`'s `modelled` and any layer added later keep their
#: rate without having to be named here, which is the direction a mistake
#: should go in. `apply` never sees an override, because those arrive as
#: `pinned`.
REPLACEABLE = frozenset({"default", "exact", "contained"})

#: `Rate.source` for a rate this project computed from a recipe. **Its figure
#: already includes the materials**, so `training._material_cost` must not add
#: them a second time - see that function.
RECIPE_SOURCE = "recipe"

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


#: Seconds one bank trip costs: the walk, the withdraw, the walk back.
#:
#: **Calibrated rather than fitted afresh, and the distinction matters.**
#: `ACTION_OVERHEAD_SECONDS` was fitted at 0.4s an action over 24 methods, and
#: `recipe_overhead.py` records that the fit has since gone *flat* - now that
#: shops, spawns and actions all cost something, only six pairs are comparable
#: and 0.0s scores exactly what 0.4s does. So there is no evidence left to
#: re-fit against, and this number is chosen to reproduce the one there was:
#: `TRIP_SECONDS / CARRY_SLOTS` is 0.4s, which is what a single-input action
#: still costs.
TRIP_SECONDS = 10.8

#: Slots a trip brings back, an inventory being 28 and one holding the tool.
CARRY_SLOTS = 27.0

#: What a single-input action pays for its trip. Kept as a name because it is
#: the number the fit produced and the one `recipe_overhead.py` reports on.
ACTION_OVERHEAD_SECONDS = TRIP_SECONDS / CARRY_SLOTS


def trip_seconds(recipe: Recipe) -> float:
    """The share of a bank trip one action of `recipe` costs.

    **What a flat constant could not see.** An action is not charged for a trip;
    it is charged for its *share* of one, and the share is decided by how many
    actions an inventory covers. A Giants' Foundry preform eats 28 bars, so a
    trip buys exactly one action and it pays for the whole run; a bowstring on
    a longbow eats one, so a trip buys 27 and each pays a twenty-seventh. Priced
    flat, those two came out the same.

    **Consuming nothing means no trip at all.** That is the "some can do
    infinite" case - an action with no materials has nothing to carry, so there
    is nothing to walk back for, and charging it a trip share would invent
    downtime. Cutting a gem from a gem you are already holding is not the
    shape; a fire lit from logs you just chopped is.

    The quantities are the recipe's own, so this needs no new data.
    """
    consumed = sum(material.quantity for material in recipe.materials)
    if consumed <= 0:
        return 0.0
    return TRIP_SECONDS * consumed / CARRY_SLOTS

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
    #: The trip share this action was priced with - see `trip_seconds`. Carried
    #: rather than recomputed because an `ActionRate` no longer holds the
    #: recipe it came from, and the two must not be able to disagree.
    trip_seconds: float = ACTION_OVERHEAD_SECONDS

    @property
    def performing_seconds(self) -> float:
        """The action alone: its animation and the overhead, no materials.

        **What `estimate._route_hours` needs and `action_seconds` is not.**
        The walk charges a conversion's inputs itself, so handing it the whole
        cycle would bill the materials twice.
        """
        return TICK_SECONDS * self.ticks + self.trip_seconds

    @property
    def action_seconds(self) -> float:
        """The whole cycle: the animation, the materials, and the overhead.

        All three, because leaving the overhead out here and adding it in
        `action_seconds()` is how the fit harness came to subtract it twice.
        """
        return TICK_SECONDS * self.ticks + self.input_seconds + self.trip_seconds

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
    return TICK_SECONDS * recipe.ticks + trip_seconds(recipe) + materials


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
    such methods on the reference map, 76 on the second) **not one wins a
    band**, so this is
    recorded rather than fixed; it would start to matter on a map whose Cooking
    or Crafting climb has nothing better to offer.
    """
    best: tuple[Recipe, float, float] | None = None
    for recipe in recipes:
        materials = material_seconds(recipe, input_seconds)
        if recipe.ticks is None or materials is None:
            continue
        seconds = TICK_SECONDS * recipe.ticks + trip_seconds(recipe) + materials
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
                trip_seconds=trip_seconds(recipe),
            )
        if offered:
            coverage[skill] = (found, offered)

    return priced, RecipeCoverage(skills=coverage, dropped=tuple(sorted(dropped)))


def _ambiguous(computed: Mapping[str, ActionRate]) -> frozenset[tuple[str, str]]:
    """The `(skill, output)` pairs more than one task joined - see `apply`.

    Computed from the rates themselves rather than passed in, because an
    `ActionRate` already records the `output` it joined on: a second source of
    truth for which recipe reached which task is the thing most likely to
    drift out of step with the join that produced them.
    """
    seen: dict[tuple[str, str], int] = {}
    for rate in computed.values():
        key = (rate.skill, rate.output.lower())
        seen[key] = seen.get(key, 0) + 1
    return frozenset(key for key, count in seen.items() if count > 1)


def apply(
    training: Mapping[str, Mapping[str, Rate]],
    computed: Mapping[str, ActionRate],
    pinned: frozenset[str] = frozenset(),
) -> dict[str, dict[str, Rate]]:
    """`training` with a computed rate wherever a recipe describes the method.

    **`defaults < scraped < computed < modelled < overrides`, and the middle
    step used to run the other way.** A recipe now outranks a money-making
    guide, which is the same layering `dps_bridge` and `gathering.py` already
    used: where this project can compute an answer for the method in front of
    it, that answer beats a figure someone published about their own account.

    The superseded argument is worth keeping, because it is the tempting one
    and it is half right. It ran: a recipe and a guide do not measure the same
    thing, since the guide assumes you bought the silver bar where this charges
    you six minutes for mining it - so where materials were free the two agreed
    (a median 1.38x, six comparable methods spanning x0.68 to x2.73) and where
    they were not this sat below by a mile (26 methods, x0.0043 to x2.73). All
    of that is still true. What it got wrong is which number a *chunk account*
    wants: the guide's shopping trip is the thing a chunk map most often cannot
    make, so being "below the guide" is the model being right about this map
    rather than the model being pessimistic. **A guide is evidence about the
    action; a recipe is evidence about the action plus the map**, and the
    second is what an estimate here is for.

    Four guards keep the flip from reaching further than that:

    - **`REPLACEABLE` is a whitelist**, so this overwrites the floor and the
      scrape's two join tiers and nothing else. `gathering.py`'s `modelled`
      rate still wins, because a success curve really does measure the same
      thing as a guide and is the better-informed of the two.
    - **A hand pin outranks everything**, as it does everywhere else - `pinned`
      is the set of task names `heuristics/overrides.json` speaks about.
    - **A computed rate below the floor is still skipped**, for the reason
      below, which is what stops a badly-joined material turning into a
      100,000-hour climb.
    - **An ambiguous join may fill the floor but may not replace the scrape**,
      which is `_ambiguous` and is the guard the flip actually needed.

    That last one is this module's own headline contract catching up with it.
    The join is exact *on `Output`* - and where upstream offers several ways to
    make one thing, one recipe reaches all of them: `Craft a ~|nature rune|~`
    and `Craft a ~|nature rune|~ with guardian essence` share an `Output` and
    are the altar loop and a minigame. Measured on the reference export that is
    **32 outputs covering 71 tasks**, almost all of them Runecraft's Guardians
    of the Rift variants and Smithing's `with superheat item` ones.

    While the scrape won this was invisible, which is why it survived: the
    altar's recipe was written over a Guardians of the Rift task and then
    discarded. Replacing the scrape made it load-bearing, and it cost Runecraft
    its whole measured climb - the uber map went **271.4h to 474.9h**, because
    a 16,728/hr altar recipe displaced `wiki:gotr`'s 25,000/40,000/50,000
    bands. So a recipe that cannot say *which* of several tasks it describes is
    not evidence against a rate that names one, and the scrape keeps the
    method. Filling a floor is still allowed, because there the alternative is
    nothing at all.

    Nothing is removed. A method this could not price keeps what it had, so the
    result is never worse-informed than the input.
    """
    merged = {task: dict(skills) for task, skills in training.items()}
    shared = _ambiguous(computed)
    for task, rate in computed.items():
        if task in pinned:
            continue
        existing = merged.get(task, {}).get(rate.skill)
        if existing is not None and existing.match not in REPLACEABLE:
            continue
        if (
            existing is not None
            and existing.match != "default"
            and (rate.skill, rate.output.lower()) in shared
        ):
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
            value=rate.xp_per_hour, source=RECIPE_SOURCE, match=COMPUTED_MATCH
        )
    return merged
