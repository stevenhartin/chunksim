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

- **A variant is assumed available, but only among the ones the task did not
  rule out.** `Bronze bar` has three recipes - a 5-tick furnace, an 11-tick
  Blast Furnace, and a 3-tick `Superheat` - and nothing in the export says
  whether this map reaches a blast furnace, so the fastest wins. It is
  optimistic in exactly the way that picks up a facility a chunk map may not
  hold. **What it may not do is cross a method the task named**: upstream
  offers `Smelt a ~|bronze bar|~` and the same `with superheat item`, and
  taking the fastest across all three priced the furnace task as a spell and
  made the pair look ambiguous when it never was. `variant_candidates` gives
  each task the variants it names, or the ones no sibling named.
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
from typing import Any, Callable, Container, Iterable, Mapping, Sequence

from chunksim.costing import fishcutting, lectern
from chunksim.costing.heuristics import Rate
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


def join_keys(challenge: Mapping[str, Any], task: str, skill: str = "") -> tuple[str, ...]:
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
    # **The markup already says what the thing is**, which is the whole reason
    # upstream writes it: `~|...|~` wraps the item or monster a task names. It
    # is the answer where the task carries no `Output` *and* says where the
    # work happens - `Craft a ~|toy cat|~ on a crafting table 4` verb-strips to
    # `toy cat on a crafting table 4`, which is a facility rather than a thing,
    # and eight Crafting challenges share that shape.
    #
    # **Last of the exact keys, so it can only fill a gap.** Anything carrying
    # an `Output` has already matched on it, which is what keeps `Craft a
    # ~|nature rune|~ with guardian essence` on the minigame rather than
    # collapsing onto the plain altar rune this would otherwise name.
    marked = task.partition("~|")[2].rpartition("|~")[0].strip()
    if marked:
        keys.append(marked)
    # **Doses last, and only as a fallback.** A potion's dose is a vocabulary
    # difference as often as a real one: upstream calls the challenge's output
    # `Super combat potion(3)` where the only recipe makes a `(4)`, and
    # `Extreme potion(3)` where the wiki says `Extreme energy potion(3)`. The
    # exact keys are tried first, so a challenge whose own dose *is* made
    # never reaches these - `Mix an ~|attack potion|~` keeps the 3-dose recipe
    # rather than borrowing the 4-dose one beside it.
    keys.extend(_dose_variants(keys))
    # **An anchored span is a wiki page and a section of it, and the section is
    # the variant label.** Upstream writes `Build a ~|wooden hull#Raft|~`, and
    # `Wooden hull` is one recipe page carrying three `{{Recipe}}`s labelled
    # `Raft`, `Skiff` and `Sloop` - so the page is what the thing answers to
    # and the anchor is what tells the three apart. Nothing else has to be
    # done about the anchor: it stays in the task's own words, so
    # `variant_candidates` reads `Raft` out of them exactly as it reads
    # `Superheat` out of `with superheat item`.
    #
    # **Last, because an anchor is usually a place rather than a variant.**
    # 1,872 marked spans in the export carry a `#` and most are objects -
    # `coal rock#Miscellania`, `soil#Fossil Island` - which is why this offers
    # only the page and lets the corpus decide: measured, 169 of them name a
    # page that is a recipe output *and* an anchor that is one of its
    # variants.
    #
    # **The four trawling nets are the one place the anchor means something
    # else, and they are right anyway.** `#Skiff` and `#Sloop` there name the
    # boat the net is *fitted to* rather than a way of building it - upstream's
    # own `Items` differ by exactly that one entry and agree on every material
    # - and the wiki publishes a single recipe it says works "on any boat". So
    # both tasks taking it is correct for the materials and the ticks, and the
    # only thing left unexplained is upstream giving the Skiff form Level 53
    # against the recipe's 61.
    page = marked.partition("#")[0].strip() if "#" in marked else ""
    if page:
        keys.append(page)
    # **The wiki disambiguates by skill where the plain name collides with
    # something else's**, and upstream's own markup already carries the plain
    # name - `thistle (Construction)` is the wiki's title for the sapling
    # `~|thistle|~` builds, next to a Farming `Thistle` that is a different
    # thing entirely. Tried last and only with a `skill` in hand, so a caller
    # that has not threaded one through loses nothing.
    if skill and marked:
        keys.append(f"{marked} ({skill})")
    # **A trailing count is the task's own vocabulary, not the recipe's.**
    # `~|rune case 1|~`, `~|rune case 2|~` and `~|rune case 3|~` are three
    # tasks for a wiki page with no numbered variants at all - `Rune case`
    # carries `Elemental`/`Low catalytic`/`High catalytic`, distinguished by
    # which runes the task stocks rather than by a digit anywhere in the
    # recipe. Offering the bare page lets `material_candidates` do what it
    # already does for every other unlabelled variant; measured across the
    # whole export, three tasks carry a trailing digit whose bare form is a
    # recipe output, and all three are this one page.
    if marked and marked[-1].isdigit():
        bare = marked.rstrip("0123456789").strip()
        if bare:
            keys.append(bare)
    # **The wiki titles a container by the state it is made in, and upstream
    # by what it is.** A blowpipe is fletched empty and filled later, so the
    # recipe page is `Toxic blowpipe (empty)` where the export's `Output` is
    # `Toxic blowpipe` - four blowpipes and a bullseye lantern.
    #
    # **A rule rather than five hand entries, because the corpus bounds it
    # exactly**: six recipe outputs end in `(empty)`, five of them are the
    # `(empty)` form of an upstream `Output`, and the sixth (`Crab trap
    # (empty)`) has no upstream twin to reach. So this can add those five
    # joins and cannot reach anything else - and it is offered last, so a page
    # that really is titled plainly still wins.
    keys.extend(f"{key} (empty)" for key in list(keys))
    return tuple(key for key in dict.fromkeys(keys) if key)


def _dose_variants(keys: Sequence[str]) -> list[str]:
    """Every other dose of each key, plus a bare name given each dose.

    The second half is what reaches `Extreme energy potion(3)` from a task
    whose words are `extreme energy potion` - `join_keys`' third key strips the
    verb and leaves no dose at all.
    """
    found: list[str] = []
    for key in keys:
        match = _DOSED.match(key)
        if match:
            name, dose = match.group("name"), match.group("dose")
            found.extend(f"{name}({other})" for other in "4321" if other != dose)
        else:
            found.extend(f"{key}({other})" for other in "4321")
    return found


#: A potion's dose as both vocabularies write it: `Attack potion(3)`.
_DOSED = re.compile(r"^(?P<name>.+?)\((?P<dose>[1-4])\)$")


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
    #: **A float, because not every action is tick-gated.** Cleaning a herb
    #: costs 18/28 of a tick - see `costing/herblore.py` - and truncating that
    #: to an `int` made it free, which in the item walk is the fastest method
    #: in the game.
    ticks: float
    #: Seconds of gathering per action, across every material.
    input_seconds: float
    output: str
    materials: tuple[str, ...] = ()
    #: The trip share this action was priced with - see `trip_seconds`. Carried
    #: rather than recomputed because an `ActionRate` no longer holds the
    #: recipe it came from, and the two must not be able to disagree.
    trip_seconds: float = ACTION_OVERHEAD_SECONDS
    #: The wiki's own label for *which* way of making `output` this is -
    #: `Superheat`, `Blast Furnace`, or empty for the ordinary one. Carried
    #: because `_ambiguous` asks whether two tasks landed on the same recipe,
    #: and `output` alone cannot answer that; see `variant_candidates`.
    variant: str = ""

    @property
    def key(self) -> tuple[str, str, str, tuple[str, ...]]:
        """What this rate describes: a skill, an item, *which* way of making
        it, and what it is made from.

        The variant is in here because it is the whole question `_ambiguous`
        asks. Keyed on the item alone, the two ways of smelting a bar are one
        answer given twice; keyed on the recipe, they are two answers.

        **The materials are in here for the same reason and were missing.**
        The wiki labels a variant only where the *method* differs (a furnace
        against a Blast Furnace); where the difference is what goes in, every
        recipe carries an empty label. Ten fish make `Fine fish offcuts`, so
        four cut-up tasks that had each correctly chosen their own fish still
        read as one recipe describing four methods - and `apply`'s guard then
        held a money-making guide about *cooking* a marlin over the recipe for
        the knife. Two recipes differing only in their input are two answers,
        exactly as two differing only in their variant are.
        """
        return (
            self.skill,
            self.output.lower(),
            self.variant.lower(),
            tuple(sorted(name.lower() for name in self.materials)),
        )

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
            "variant": self.variant,
        }


@dataclass(frozen=True)
class RecipeCoverage:
    """What the join reached, per skill, so a total can be read honestly."""

    #: Skill -> (methods priced, primary methods offered).
    skills: dict[str, tuple[int, int]] = field(default_factory=dict)
    #: Methods that joined a recipe but lost an input to `None`, each with
    #: the material that blocked it - `""` where the recipe was refused for
    #: want of a duration rather than an input. See `unroutable`.
    dropped: Mapping[str, str] = field(default_factory=dict)

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
            "dropped": dict(self.dropped),
        }


#: Anything that is not a letter or a digit, for comparing a recipe's variant
#: against a task's words.
_WORDS = re.compile(r"[^a-z0-9]+")


def _words(text: str) -> set[str]:
    return set(_WORDS.sub(" ", text.lower()).split())


def names_variant(variant: str, task: str) -> bool:
    """Whether `task` says it is the method `variant` labels.

    **Whole words, all of them, and an unlabelled variant names nothing.** The
    wiki writes `Superheat` where upstream writes `~|... |~ with superheat
    item`, so this is a subset test over words rather than a substring one -
    `Blast Furnace` must not match a task that merely says "furnace". A recipe
    whose `variant` is empty is the skill's ordinary way of making the thing
    and is claimed by nobody, which is what leaves Runecraft's altars alone.
    """
    tokens = _words(variant)
    return bool(tokens) and tokens <= _words(strip_task_markup(task))


def variant_candidates(
    task: str, recipes: Sequence[Recipe], siblings: Sequence[str]
) -> tuple[Recipe, ...]:
    """The recipes of `recipes` that `task` - rather than a sibling - describes.

    **The field that resolves the join was being thrown away.** `Bronze bar`
    has three recipes and upstream has two tasks, `Smelt a ~|bronze bar|~` and
    the same `with superheat item`; joined on `Output` alone both got the
    fastest recipe, which is the 3-tick Superheat one, so the furnace task was
    priced as a spell and the pair looked ambiguous. It never was: the wiki
    labels that recipe `Superheat` and the task says so.

    So a task takes the variants it names; a task naming none takes the ones no
    *sibling* names, leaving the qualified methods to the tasks that asked for
    them. **Siblings come from the whole export, not from what this map can
    reach** - otherwise a map holding only the furnace task would find nothing
    had claimed `Superheat` and price the furnace as a spell, which is the
    original defect back again on a smaller map.

    Falls back to the whole set when the partition would leave a task nothing,
    so a variant vocabulary this does not understand costs a method its
    precision rather than its rate. Resolves **13 of the 32** recipe-joined
    ambiguous groups on the reference export: all twelve bar pairs, plus
    Cooking's chompy on `Fire` against `Ogre spit-roast`. The other nineteen
    are Runecraft's `with guardian essence` and friends, where every variant is
    empty because the minigame has no `{{Recipe}}` at all - they stay ambiguous
    and `apply`'s guard still holds them.
    """
    mine = tuple(recipe for recipe in recipes if names_variant(recipe.variant, task))
    if mine:
        return mine
    spoken = {
        recipe.variant
        for recipe in recipes
        if any(names_variant(recipe.variant, other) for other in siblings)
    }
    rest = tuple(recipe for recipe in recipes if recipe.variant not in spoken)
    return rest or tuple(recipes)


def stocks(challenge: Mapping[str, Any]) -> frozenset[str]:
    """The items a challenge lists, without upstream's markers, lowercased.

    `Magic logs*` and `Fire rune[+]` are the same two markers `estimate`
    strips: `*` says the action consumes it and `[+]` says any member of a
    family will do.
    """
    found = {
        item.replace("*", "").replace("[+]", "").strip().lower()
        for item in challenge.get("Items") or ()
        if isinstance(item, str)
    }
    return frozenset(name for name in found if name)


def names_material(recipe: Recipe, challenge: Mapping[str, Any]) -> bool:
    """Whether `challenge` lists everything `recipe` is made from.

    **Upstream's own `Items`, not the task's words**, and the difference is not
    academic. Every `Fletch ~|X logs|~ into shafts` task contains the word
    `logs`, so a word-subset test over the name says the magic one is *also*
    describing the plain-log recipe - which is the failure `names_variant`
    warns about ("`Blast Furnace` must not match a task that merely says
    furnace") arriving through a different door. The `Items` list says `Magic
    logs` and stops there.

    A challenge listing no items names nothing, which is right: `Craft a
    ~|nature rune|~ with guardian essence` has no `Items` because the minigame
    hands the essence over.

    **The dose is a vocabulary difference here exactly as it is in
    `join_keys`.** Upstream writes the family a potion belongs to - `Ranging
    potion[+]` - where a `{{Recipe}}` writes the strength it consumes,
    `Ranging potion(3)`. Compared literally the two never meet, so every
    divine potion disowned its own recipe. Doses are only dropped when the
    literal comparison has already failed, so a challenge naming a *particular*
    strength still says so.
    """
    held = stocks(challenge)
    materials = {material.name.lower() for material in recipe.materials}
    if not materials:
        return False
    if materials <= held:
        return True
    return {_undosed(name) for name in materials} <= {_undosed(name) for name in held}


def _undosed(name: str) -> str:
    """`attack potion(3)` -> `attack potion`; anything else unchanged."""
    found = _DOSED.match(name)
    return found.group("name") if found else name


def material_candidates(
    challenge: Mapping[str, Any],
    recipes: Sequence[Recipe],
    siblings: Sequence[Mapping[str, Any]],
) -> tuple[Recipe, ...]:
    """`variant_candidates`' rule on the *material* axis.

    **The nineteen groups the variant field could not resolve.** Its docstring
    records them as staying ambiguous - "Runecraft's `with guardian essence`
    and friends, where every variant is empty because the minigame has no
    `{{Recipe}}` at all" - and that was half right. The minigame has no recipe,
    but the *essence* does: the wiki writes one `Nature rune` recipe per
    essence it accepts, `Pure`, `Rune`, `Daeyalt` and `Guardian`, and upstream
    writes `Items: ["Pure essence*"]` on the altar task and nothing at all on
    the minigame one. The distinguishing field was never missing; it was in the
    materials rather than in the label.

    What it cost: all twelve altar runes shared a key with their Guardians of
    the Rift twin, because `rate_for` maximises and pure essence is the fastest
    thing that prices - so the twin took the pure-essence recipe too. `apply`'s
    guard then held the six with a money-making guide (air, chaos, cosmic,
    death, law, nature) on that guide, while the five with only the floor
    (mind, water, earth, fire, body) took the computed rate. Six methods on a
    scrape because of a collision that was never real.

    Applied **after** the variant partition and only where that left more than
    one candidate, so a group the wiki's own label already resolved cannot be
    widened again. Falls back to the whole set the same way, for the same
    reason: a vocabulary this does not understand costs a method its precision
    rather than its rate.
    """
    if len(recipes) < 2:
        return tuple(recipes)
    mine = tuple(recipe for recipe in recipes if names_material(recipe, challenge))
    if mine:
        return mine
    spoken = {
        id(recipe)
        for recipe in recipes
        if any(names_material(recipe, other) for other in siblings)
    }
    rest = tuple(recipe for recipe in recipes if id(recipe) not in spoken)
    return rest or tuple(recipes)


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


#: `(output, material)` pairs this project prices at zero because
#: *destroying* the thing returns the material, so the loop this rate prices
#: never actually consumes it a second time. The wiki states it identically
#: for all three: "when the mounted sword object is destroyed, the sword is
#: returned." **Not a general property of `(mounted)` items** - checked and
#: rejected for the fish and head trophies beside them, whose own pages say
#: the opposite ("cannot be removed to retrieve the stuffed fish/head"), so
#: this is three hand-verified entries rather than a rule keyed on the name.
#:
#: **Safe because the rate is only ever asked for a challenge already valid**,
#: which for these three means the one-time quest is already done - `Complete
#: ~|Shadow of the Storm|~`/`~|Demon Slayer|~`/`~|Merlin's Crystal|~` gates
#: the task itself, upstream's own reachability check rather than anything
#: this table has to repeat. Zeroing the sword's cost does not claim it was
#: free to obtain, only that obtaining it again is not part of this loop.
#:
#: The wiki's own `{{Recipe}}` marks `mat2cost = 0` for the sword on all
#: three pages, which looks like the same fact stated in the template and is
#: not: that field is exposed nowhere in the Bucket `production_json` this
#: project reads (verified against the live table - only `output.cost`
#: survives, no per-material `cost`), and even where present it means "the
#: wiki's own cost calculator has no coin price for this," which is true of
#: the fish trophies' materials too and does not imply either is returned.
RETURNED_MATERIALS: frozenset[tuple[str, str]] = frozenset(
    {
        ("Darklight (mounted)", "Darklight"),
        ("Silverlight (mounted)", "Silverlight"),
        ("Excalibur (mounted)", "Excalibur"),
    }
)


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
        if (recipe.output, material.name) in RETURNED_MATERIALS:
            continue
        seconds = input_seconds(material.name, material.quantity)
        if seconds is None:
            return None
        total += seconds
    return total


def unroutable(
    recipes: Sequence[Recipe], input_seconds: Callable[[str, float], float | None]
) -> str:
    """The first material of `recipes` the walk cannot route, or `""`.

    **The diagnosis behind a dropped method**, so `unpriced` can say *which*
    input it wanted rather than only that it wanted one. `rate_for` returns a
    bare `None` because it is the hot path and the answer it needs is
    yes-or-no; this walks the same materials again and is called only once
    that has already failed, over the memoised `input_seconds` closure
    `estimate.material_seconds` builds - so the second walk is a lookup.

    **One name, from the first candidate.** A challenge can join several
    recipes (`Mounted bass` joins three, one per display tier) and they
    usually share the material that blocks them; where they do not, this
    names one of them rather than claiming to be the whole story.

    `""` where every material routes, which is not "nothing was wrong" - a
    recipe with no tick cost and no `stated_ticks` entry is refused by
    `rate_for` before its materials are ever asked about. Blank therefore
    means "not an input", and the caller must not render it as one.
    """
    for recipe in recipes:
        for material in recipe.materials:
            # Skipped for the reason `material_seconds` skips them: destroying
            # the object returns the material, so the loop never buys a second.
            if (recipe.output, material.name) in RETURNED_MATERIALS:
                continue
            if input_seconds(material.name, material.quantity) is None:
                return material.name
    return ""


#: What an action the wiki states as **instant** is charged, in ticks.
#:
#: **The game's own floor rather than a fitted number.** `ticks = 0` is a
#: claim - `Module:Recipe` renders it "0 (0s) per action" - and it means the
#: game imposes no delay, not that the action is free: a player still has to
#: click, and two distinct actions cannot resolve in one tick. So one tick is
#: the shortest cycle the game allows and this is a **ceiling** on the rate,
#: `costing/trawler.py`'s sense of the word.
#:
#: **Checked against the only two published families that price a zero-tick
#: action**, by dividing their rate back out: `wiki:darts` implies exactly
#: **1.00** tick across all eight dart recipes, and the twelve
#: `mmg:Money making guide/Cleaning grimy ...` guides imply exactly **1.20**.
#: So the floor is not merely a bound - it is within 20% of what the two
#: independent observations say a player sustains, and the difference is
#: 0.12 seconds against material costs that are usually seconds.
#:
#: **A module that states a duration still wins**, because `ticks_for` asks
#: `stated_ticks` first: `costing/chisel.py` says a dark essence block really
#: is free on a run already being paid for, and `costing/herblore.py` counts
#: the bank trip a clean herb sits inside at 18/28 of a tick. Both of those
#: are about a *cycle* where this is about an action, and both are better
#: answers where they apply.
ZERO_TICK_TICKS = 1.0


def ticks_for(recipe: Recipe, stated_ticks: Mapping[str, float] = {}) -> float | None:
    """Ticks one action of `recipe` costs, or `None` where nothing says.

    Three sources in order, and the order is the whole of it: a duration the
    wiki published, then one a module stated for an action the wiki left
    blank *or* called instant, then `ZERO_TICK_TICKS` for a stated instant
    nothing else spoke for. A blank with no stated figure stays `None`, which
    is what drops the method.
    """
    if recipe.timed:
        return recipe.ticks
    stated = stated_ticks.get(recipe.output)
    if stated is not None:
        return stated
    return ZERO_TICK_TICKS if recipe.ticks == 0.0 else None


def action_seconds(
    recipe: Recipe,
    input_seconds: Callable[[str, float], float | None],
    stated_ticks: Mapping[str, float] = {},
) -> float | None:
    """Seconds for one whole action of `recipe`, or `None`."""
    materials = material_seconds(recipe, input_seconds)
    ticks = ticks_for(recipe, stated_ticks)
    if ticks is None or materials is None:
        return None
    return TICK_SECONDS * ticks + trip_seconds(recipe) + materials


def rate_for(
    recipes: Sequence[Recipe],
    input_seconds: Callable[[str, float], float | None],
    stated_ticks: Mapping[str, float] = {},
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
        # **A stated duration only where the wiki publishes none.** `ticks` is
        # `0` for every clean herb - the wiki's way of saying the action is
        # not tick-gated - and reading that as no time at all is the fastest
        # method in the game, while refusing it outright cost Herblore
        # eighteen methods. `costing/herblore.py` states the bank cycle
        # instead; a recipe carrying a *positive* tick cost keeps it, so this
        # can never overwrite a published duration. See `ticks_for`.
        ticks = ticks_for(recipe, stated_ticks)
        if ticks is None or materials is None:
            continue
        seconds = TICK_SECONDS * ticks + trip_seconds(recipe) + materials
        if seconds <= 0:
            continue
        rate = recipe.experience * 3600.0 / seconds
        if best is None or rate > best[1]:
            best = (recipe, rate, materials)
    return best


def unjoined_outputs(
    chunk_info: ChunkInfo, recipes: Mapping[str, Sequence[Recipe]]
) -> tuple[str, ...]:
    """Every name a primary method offers that no recipe answers to.

    **What `chunksim recipes` hands the wiki to ask "did you rename this?"** -
    see `api.fetch_wiki_redirects`. Lives here rather than in the CLI because
    it has to miss in exactly the way `computed_rates` misses; two
    near-identical join loops would drift, and the one that drifted would go
    quiet rather than fail.

    **Over the whole export, not over a map's valid set**, because which name
    the wiki files an item under is a fact about the wiki. A per-map alias
    blob would be a cache that answered differently depending on which map
    happened to be open when it was written.

    **The two keys that are titles are asked about; the one that is a sentence
    is not.** `Output` is upstream's own name for the thing, and the marked
    span is the item the task names - that is what upstream writes `~|...|~`
    *for*. `join_keys`' verb-stripped key is neither: it is a sentence (`a
    broken ~|strut|~ in the Motherlode Mine`), and handing 2,000 of those to
    the wiki asks questions whose answer is always no.

    **Leaving the span out was costing whole families**, because a challenge
    with no `Output` was never asked about at all - which is most of
    Construction's furniture. It adds 465 names to 236, so 15 batched requests
    rather than 6, and the wiki answers with **36 more aliases**: the Sailing
    `javelin heads` -> `tips` rename across five metals that the bronze one
    had already exposed through its `Output`, five snelms whose `(pointed)`
    the wiki writes as a prefix, `Otherworldy` -> `Otherworldly` and `Chili` ->
    `Chilli` where upstream's spelling is simply wrong, and eight POH pieces
    the wiki files under another name (`Demon throne` -> `Demonic throne`,
    `Wooden telescope` -> `Oak telescope`, `Icon of Bob` -> `Bob icon`).

    An anchor is dropped first, for the reason `join_keys` offers the page
    half: `wooden hull#Raft` is a section of a page and the page is the title.
    """
    wanted: set[str] = set()
    for skill, rows in recipes.items():
        by_output = {name.lower() for name in index_recipes(list(rows))}
        challenges = _mapping(chunk_info.challenges, skill)
        if not isinstance(challenges, dict):
            continue
        for task, challenge in challenges.items():
            if not isinstance(challenge, dict) or challenge.get("Primary") is not True:
                continue
            keys = join_keys(challenge, task, skill)
            if any(key.lower() in by_output for key in keys):
                continue
            for field in ("Output", "Output Object"):
                value = challenge.get(field)
                if isinstance(value, str) and value.strip():
                    wanted.add(value.strip())
            span = task.partition("~|")[2].rpartition("|~")[0]
            span = span.partition("#")[0].strip()
            if span:
                # Titled as the wiki titles a page, since that is what is
                # being asked about - upstream lowercases the span inside its
                # own sentence.
                wanted.add(span[:1].upper() + span[1:])
    return tuple(sorted(wanted))


#: Vocabulary drift the wiki's own redirect machinery cannot see, because no
#: page exists under upstream's name for a redirect to point *from*. Each of
#: these was verified by hand: the target's Construction level and materials
#: match upstream's `Level`/`Items` for the source task exactly.
#:
#: **`wiki_aliases.json` cannot hold these**, unlike the 37 it does - that
#: file is `chunksim recipes`' own fetch, written wholesale each time it runs,
#: so a hand entry there would survive until the next refresh silently undid
#: it. This constant is what `remote/skill_tables.SHORTCUT_ALIASES` is for
#: shortcuts: a small table for drift a fetch structurally cannot find.
#:
#: Four are a plainer word than the wiki's title (`Wooden dining table` names
#: the furniture upstream's own task calls it; the page is `Wood dining
#: table`) or a shape neither an anchor nor a redirect reaches (`Teak mounted
#: fish display` names what the export calls it; the page is `Teak display
#: (fishing trophy)`). The other two are upstream reusing one family word,
#: `revitalisation`, for tiers the wiki names progressively -
#: `Restoration -> Revitalisation -> Rejuvenation -> Fancy -> Ornate` - so only
#: the base tier's name is actually the wiki's; `Fancy revitalisation pool`
#: and `Ornate revitalisation pool` are not pages and have no redirect to be.
HAND_ALIASES: dict[str, str] = {
    # **A charge the export drops and the wiki keeps.** Upstream states this
    # enchant's `Output` as the bare `Digsite pendant` where the wiki's recipe
    # makes a `Digsite pendant (5)` - and it is inconsistent about it, since
    # `Enchant a ~|sapphire necklace|~` right beside it says `Games
    # necklace(8)` charge and all. `join_keys`' dose fallback tries `(1)`
    # through `(4)`, which is a potion's range and not a jewellery charge, so
    # a five never comes up. Measured over the whole export, this is the only
    # unjoined key that a charge-suffixed recipe output would answer.
    "Digsite pendant": "Digsite pendant (5)",
    "Wooden dining table": "Wood dining table",
    "Teak mounted head display": "Teak display (head trophy)",
    "Teak mounted fish display": "Teak display (fishing trophy)",
    "Mahogany mounted fish display": "Mahogany display (fishing trophy)",
    "Fancy revitalisation pool": "Fancy rejuvenation pool",
    "Ornate revitalisation pool": "Ornate rejuvenation pool",
    # **A plural the wiki writes and upstream does not.** `Fletch a
    # ~|wolfbone arrowtip|~` makes four at a time and the wiki titles the
    # page `Wolfbone arrowtips`. **Measured, this is the only one**: across
    # the whole export exactly one `Output` that joins nothing has a recipe
    # output that is its plural, so a general `s` rule would buy this join and
    # nothing else while risking every singular that means something.
    "Wolfbone arrowtip": "Wolfbone arrowtips",
    # **A state the wiki's recipe makes and upstream's `Output` skips.**
    # Chiselling a `Serpentine visage` produces a *charged*-name-less helm;
    # the wiki titles its recipe output `Serpentine helm (uncharged)` because
    # scales are what charge it afterwards. Levels agree exactly (52) and so
    # does the material.
    "Serpentine helm": "Serpentine helm (uncharged)",
    # **Same shape one word over.** Glassblowing makes an `Empty fishbowl`;
    # upstream calls the challenge's output `Fishbowl`, which on the wiki is
    # the page holding three recipes and is what the *filled* one is called.
    # Crafting 42 and one molten glass on both sides.
    "Fishbowl": "Empty fishbowl",
    # **Two family names, where upstream states no `Output` at all and the
    # wiki has a page per variant.** Both are cases where the variants are
    # identical in everything a rate reads:
    #
    # - four toy horseys, all Crafting 10, 15 experience, 3 ticks, one
    #   `Plank` - so the colour is not a choice a rate can see, and upstream
    #   carries no per-colour challenge either;
    # - nine snelms, all Crafting 15, 32.5 experience, 2 ticks, differing
    #   only in which blamish shell goes in. Upstream *does* carry the nine
    #   individually and they price on their own; this is its extra family
    #   challenge, `Items: ["Snelm shell[+]*"]`, and the alias fixes which
    #   shell it walks to rather than what it pays.
    "toy horsey": "Grey toy horsey",
    "snelm": "Myre snelm",
    # **And a third of the same shape.** `Dye a ~|cape|~` states no `Output`
    # and `Items: ["Cape[+]*", "Dye[+]*"]`; the wiki has a page per colour and
    # every one is Crafting 1, 2.5 experience, a base cape and a dye.
    # **Measured, exactly one primary challenge in the export offers the key
    # `cape`**, and no recipe output is named that, so the alias cannot reach
    # anything else.
    "cape": "Blue cape",
    # **The largest family of the four, and the one where the metal is a
    # cost rather than a variant.** Upstream carries one challenge for the
    # whole of painted heraldic armour; the wiki has a page per metal *and*
    # per crest - **48 helms and 48 kiteshields**, three metals by sixteen
    # crests. Measured over the corpus every helm is Crafting 38, 37
    # experience, 6 ticks and every kiteshield Crafting 43, 40 and 6, which
    # are upstream's own `Level`s exactly. So the crest is invisible to a rate
    # and the metal is only what the base costs - and **steel is what the
    # alias names**, because the experience is identical and `rate_for`
    # maximises, so given all forty-eight it would choose the cheapest base
    # itself.
    #
    # **The lowercase `(construction)` is not the problem** - `by_output` is
    # matched case-insensitively, so upstream's spelling would have found a
    # page called `Heraldic helmet (Construction)` if one carried a recipe. It
    # does not: that page is prose, and the recipes live on the 96 variants.
    "heraldic helmet (construction)": "Steel heraldic helm (Arrav)",
    "heraldic kiteshield (construction)": "Steel kiteshield (Arrav)",
}

#: A recipe's own *material* named in the wiki's vocabulary, where upstream's
#: item graph (`derive/search.build_world_index`, keyed on every `Output` the
#: export states) knows the same thing under a plainer name. **The opposite
#: direction from `HAND_ALIASES`** - that table takes an export name to a wiki
#: title so a challenge can find its recipe; this takes a recipe's own
#: material to the export name so the item walk can find a *route* to it, and
#: the two tables are not interchangeable because the two lookups run against
#: different vocabularies (wiki recipe outputs against export `Output`
#: strings, respectively).
#:
#: **Found by asking why `Build an ~|ancient altar|~` refused to price despite
#: every input the export names being reachable.** The wiki's `{{Recipe}}` for
#: `Ancient altar` lists a material called `Pharaoh's sceptre (uncharged)` -
#: correctly, Pyramid Plunder really does hand the sceptre over with no
#: charges - but the only challenge that produces one anywhere in the export
#: states its `Output` as the bare `Pharaoh's sceptre`, so
#: `world.item_sources` never seeds the wiki's exact string.
#:
#: **One entry, deliberately, though the search that found it turned up
#: twenty more.** Of the recipe corpus's 524 distinct material names with no
#: literal source, 21 resolve by stripping a trailing parenthetical against
#: `world.item_sources` - but "strips clean" is not "means the same thing".
#: `Corrupted helm (attuned)`/`(basic)` are Trahaearn degradation tiers,
#: `Spider on shaft (raw)` is a cooking state, `Mith grapple (unf)` is the same
#: unfinished/finished split the alias fetch already handles for bars, and
#: `Super defence(4)` is a dose the recipe corpus's own dose fallback
#: (`_dose_variants`) was built for and does not reach here because this path
#: runs after the wiki recipe is already chosen. Each needs checking against
#: what the state actually costs to reach, the way the sceptre was - a
#: strip-and-retry rule applied uniformly would treat a degraded item as free
#: to obtain from a fresh one, which is the same mistake pricing a shop item
#: at its ground-spawn cousin's rate would be. This entry is the one checked;
#: the other twenty are recorded here for whoever checks the next one.
#: **Charge and spelling, the two shapes this keeps turning out to be.**
#: `Black mask` is the wiki's recipe name for a mask the export models only in
#: its dropped form, `Black mask (10)` - and upstream's own `Items` for all
#: four challenges that want one say `Black mask (10)` outright, so the
#: mapping is upstream's rather than a guess. `Araxyte venom sac` is the
#: vocabulary lag `wiki_aliases.json` handles for *outputs*, seen on the
#: material axis where that fetch cannot look: the item was renamed `sack` ->
#: `sac` on 30 June 2026, the wiki followed and the export has not.
#: **A fourth shape was here and has been retired**, which is worth recording
#: because it was the wrong fix rather than an obsolete one. `Raw batta`,
#: `Raw crunchies` and `Raw gnomebowl` were mapped to `Gianne dough` on the
#: strength of upstream's own `Items`, because the wiki appeared to state no
#: `{{Recipe}}` for pressing dough into a tin. It states one - the recipe
#: simply pays no skill, and `bucket('recipe').where('uses_skill', ...)` can
#: only see recipes that award experience. `remote/recipes.parse_unskilled`
#: sweeps those now, so all three route properly and charge the tin as well as
#: the dough. **The lesson is to check whether the wiki is silent before
#: writing down what it should have said**: 53 materials had no route for
#: exactly this reason and an alias each would have been 53 hand entries.
MATERIAL_ALIASES: dict[str, str] = {
    "Pharaoh's sceptre (uncharged)": "Pharaoh's sceptre",
    "Black mask": "Black mask (10)",
    "Araxyte venom sac": "Araxyte venom sack",
    # A MediaWiki redirect, which is what makes it the cleanest entry here:
    # `Crab meat` and `Giant crab meat` are one page and one item id. It is
    # the vocabulary lag `wiki_aliases.json` handles for *outputs*, on the
    # material axis where that fetch cannot look.
    "Giant crab meat": "Crab meat",
    # **Another redirect, and upstream is inconsistent with itself here.** The
    # wiki has one page, `Grimy buchu leaf`, which `Grimy buchu` redirects to.
    # Upstream writes the grimy form *without* the word - `Grow a ~|grimy
    # buchu|~` outputs `Grimy buchu` - and the clean form *with* it, `Output:
    # "Buchu leaf"`. So all four Chambers of Xeric buchu methods joined their
    # recipe and were dropped for an input the raid plainly grows, while
    # golpar and noxifer beside them priced.
    "Grimy buchu leaf": "Grimy buchu",
    # **The third rename, and the same shape as the venom sac.** `Lily of the
    # sands` became `Lily of the Sands` in the Summer Sweep Up of 19 August
    # 2026 - the item's own `{{Subject changes}}` says so - and the wiki
    # followed while the export did not, so `Menaphite remedy(3)`'s recipe
    # asks for a material upstream spells with a small `s`. Capitalisation
    # rather than a word this time, which is why it is an entry and not a
    # fold: `world.item_sources` is keyed by upstream's own `Output` strings
    # and matching them case-insensitively would be a general rule over a
    # vocabulary nobody has checked for collisions.
    "Lily of the Sands": "Lily of the sands",
}


def with_aliases(
    by_output: Mapping[str, tuple[Recipe, ...]], aliases: Mapping[str, str]
) -> dict[str, tuple[Recipe, ...]]:
    """`by_output` with each alias registered alongside the name it renames.

    **Additive, never overriding.** An alias that collides with a name the
    recipes already answer to is dropped: the wiki redirecting `X` to `Y` says
    nothing about a *recipe* whose own output is `X`, and letting the redirect
    win there would trade a real join for a guessed one.
    """
    merged = dict(by_output)
    for alias, target in aliases.items():
        key = alias.lower()
        found = by_output.get(target.lower())
        if found is not None and key not in merged:
            merged[key] = found
    return merged


def stated_ticks(
    chunk_info: ChunkInfo, recipes: Mapping[str, Sequence[Recipe]]
) -> dict[str, float]:
    """Every duration this project states where the wiki publishes none.

    **One answer, because three callers ask it.** `computed_rates`,
    `challenge_experience` and the item walk's own recipe corpus
    (`estimate._setup`) each need to know how long an untimed action takes,
    and three copies of the merge is three chances for the walk and the rate
    layer to disagree about the same recipe.

    Each contributor fills only where the wiki says nothing, so a published
    tick cost is never overwritten: `herblore` states the bank cycle a clean
    herb costs, `chisel` states the zero a dark essence block costs on a run
    already paid for, `fishcutting` states the three ticks a knife costs on
    a crab - the wiki's own figure for the same knife on a fish - and
    `yewtree` states the one cell a family of otherwise-identical garden
    trees leaves blank on this one page, and `greenman` the one cell its
    two-recipe family leaves blank - measured in game rather than borrowed,
    with the sibling's published 4 as the check; `gnomecooking` states the one
    tick three of the four gnome crunchies publish and the fourth does not.
    `potionsteps` fills two Herblore blanks in families that publish the rest -
    the one barbarian mix of twenty-nine the wiki left untimed, and the two
    middle combines of the sanfew serum, whose third step states the two ticks
    all three share. `feathering` is the largest of them by far: 145 of Fletching's 158 untimed recipes are a stack of
    feathers onto a stack of tips, and the four the wiki *does* time are all
    2 ticks.
    """
    # Deferred: `estimate` imports this module for the merge and `chisel`,
    # `herblore`, `fishcutting`, `yewtree` and `greenman` are leaves, but
    # keeping the imports local documents that nothing here depends on their
    # module state.
    from chunksim.costing import (
        chisel,
        feathering,
        fishcutting as cutting,
        fremennikicons,
        gnomecooking,
        greenman,
        measured,
        herblore,
        potionsteps,
        yewtree,
    )

    found = dict(herblore.stated_ticks(recipes))
    found.update(chisel.stated_ticks(recipes))
    found.update(yewtree.stated_ticks(recipes))
    found.update(greenman.stated_ticks(recipes))
    found.update(gnomecooking.stated_ticks(recipes))
    found.update(fremennikicons.stated_ticks(recipes))
    found.update(measured.stated_ticks(recipes))
    found.update(feathering.stated_ticks(recipes))
    found.update(potionsteps.stated_ticks(recipes))
    for skill, rows in recipes.items():
        challenges = _mapping(chunk_info.challenges, skill)
        found.update(cutting.stated_ticks(challenges, list(rows)))
    return found


def _joined(
    task: str,
    challenge: Mapping[str, Any],
    by_output: Mapping[str, Sequence[Recipe]],
    siblings: Mapping[str, tuple[str, ...]],
    cuts: Mapping[str, tuple[Recipe, ...]],
    challenges: Mapping[str, Any] = {},
    tablets: Mapping[str, tuple[Recipe, ...]] = {},
    skill: str = "",
) -> tuple[str, tuple[Recipe, ...]] | None:
    """`(output, recipes)` for one challenge, or `None` where nothing joins.

    **One answer to "which recipe is this challenge", shared.**
    `computed_rates` and `challenge_experience` both ask it, and the second's
    docstring already said a second answer is the thing most likely to drift -
    so there is one.

    Two families are checked before the `Output` join, both because their key
    is not an `Output` at all. Upstream names a knife action's output `Marlin
    loot`, a bundle the wiki has no page for, so that join runs on the fish
    going in (`costing/fishcutting.py`). And upstream names a teleport
    `Cast ~|camelot teleport|~` where the only repeatable form of that cast is
    `Camelot teleport (tablet)` at a lectern (`costing/lectern.py`) - a cast
    that moves you is not a method, so the tablet is not a fallback here but
    the answer.
    """
    tablet = tablets.get(task)
    if tablet is not None:
        return tablet[0].output, tablet
    cut = cuts.get(task)
    if cut is not None:
        # The recipe's own output stands in as the key, since upstream's is a
        # bundle name nothing else answers to.
        return cut[0].output, cut
    keys = join_keys(challenge, task, skill)
    joined = [key for key in keys if key.lower() in by_output]
    if not joined:
        return None
    # **`Output` is upstream's claim about what is made and `Items` its claim
    # about what it is made from; where the two disagree, take the pair that
    # agrees with a recipe.** Upstream files `Mix a ~|divine magic potion|~`
    # under `Divine ranging potion(3)` and `Mix a ~|divine battlemage
    # potion|~` under `Divine bastion potion(3)` - two plain data errors, each
    # of which put two tasks on one recipe and got both refused as ambiguous.
    # Their own `Items` say `Magic potion[+]` and `Battlemage potion[+]`, and
    # the key list already carries the right output further down.
    #
    # **A preference, not a filter**: where nothing the challenge owns joins,
    # the first key still wins, so a challenge that lists no items or lists a
    # family no recipe names prices exactly as it did before this existed.
    output = next(
        (
            key
            for key in joined
            if any(names_material(recipe, challenge) for recipe in by_output[key.lower()])
        ),
        joined[0],
    )
    kin = siblings.get(output.lower(), ())
    candidates = material_candidates(
        challenge,
        variant_candidates(task, by_output[output.lower()], kin),
        [challenges[other] for other in kin if isinstance(challenges.get(other), dict)],
    )
    if output in fishcutting.CUT_OUTPUTS:
        # The family task takes what no species-specific one named - see
        # `fishcutting.unclaimed`, which is `variant_candidates`' own rule
        # applied to the fish going in rather than the wiki's variant label.
        candidates = fishcutting.unclaimed(candidates, cuts)
    return output, candidates


def challenge_experience(
    chunk_info: ChunkInfo,
    recipes: Mapping[str, Sequence[Recipe]],
    aliases: Mapping[str, str] = {},
    stated_ticks: Mapping[str, float] = {},
    valid: Mapping[str, Mapping[str, Any]] = {},
) -> dict[str, tuple[str, float]]:
    """`{task: (skill, experience one performance pays)}`, for every challenge
    a recipe describes.

    **What the item walk needs to credit its own gathering.** Charging a
    method for the bar it consumes and discarding the Smithing the smelting
    paid prices that half as somebody else's work - but the credit is only
    honest for the route the walk *chose*, so the walk has to carry it and
    this is the lookup it carries. See `estimate._Priced.experience`.

    Joined exactly as `computed_rates` joins, through the same `_joined`,
    because a second answer to "which recipe is this challenge" is the thing
    most likely to drift.

    `valid` is this map's reachable set, and it is here for one reason: which
    lectern a map can build decides whether a teleport has a tablet route at
    all (`costing/lectern.py`). Omitted, no teleport joins - which is the
    conservative answer and the one a caller with no derivation to hand
    should get.
    """
    found: dict[str, tuple[str, float]] = {}
    for skill, rows in recipes.items():
        by_output = {name.lower(): got for name, got in index_recipes(list(rows)).items()}
        by_output = with_aliases(by_output, aliases)
        challenges = _mapping(chunk_info.challenges, skill)
        if not isinstance(challenges, dict):
            continue
        siblings = _siblings(challenges, by_output, skill)
        cuts = fishcutting.cut_recipes(challenges, list(rows))
        tablets = lectern.tablet_recipes(challenges, list(rows), valid)
        for task, challenge in challenges.items():
            if not isinstance(challenge, dict) or challenge.get("Primary") is not True:
                continue
            joined = _joined(task, challenge, by_output, siblings, cuts, challenges, tablets, skill)
            if joined is None:
                continue
            output, candidates = joined
            # **Per unit of output, and the lowest of them.** Superglass Make
            # pays 180 experience and returns 28.8 molten glass, so a bare
            # `max(experience)` credited nine times what a piece is worth and
            # made glassblowing the whole Crafting climb. The walk charges the
            # challenge once per item, so the credit has to be per item too -
            # and where the variants disagree the smallest is taken, because
            # this number makes a method look *faster* and the walk cannot say
            # which variant it used.
            paid = min(
                (
                    recipe.experience / max(recipe.output_quantity, 1.0)
                    for recipe in candidates
                    if recipe.timed or recipe.output in stated_ticks
                ),
                default=0.0,
            )
            if paid > 0:
                found[task] = (skill, paid)
    return found


def _siblings(
    challenges: Mapping[str, Any], by_output: Mapping[str, Sequence[Recipe]], skill: str = ""
) -> dict[str, tuple[str, ...]]:
    """Every primary task in one skill that joins each output, keyed by output.

    Read from the **whole** export rather than from a map's valid set, because
    `variant_candidates` asks which methods upstream offers for an item, and
    that is a property of the game rather than of who can reach it here.
    """
    joined: dict[str, list[str]] = {}
    for task, challenge in challenges.items():
        if not isinstance(challenge, dict) or challenge.get("Primary") is not True:
            continue
        for key in join_keys(challenge, task, skill):
            if key.lower() in by_output:
                joined.setdefault(key.lower(), []).append(task)
                break
    return {output: tuple(tasks) for output, tasks in joined.items()}


def _skill_join_tables(
    chunk_info: ChunkInfo,
    valid: Mapping[str, Mapping[str, Any]],
    rows: Sequence[Recipe],
    skill: str,
    aliases: Mapping[str, str],
) -> tuple[
    dict[str, tuple[Recipe, ...]],
    Mapping[str, tuple[str, ...]],
    Mapping[str, tuple[Recipe, ...]],
    Mapping[str, tuple[Recipe, ...]],
    Mapping[str, Any],
]:
    """`(by_output, siblings, cuts, tablets, challenges)` - the join tables
    `_joined` reads for every task in `skill` at once.

    Built once per skill by `computed_rates`'s own loop, and rebuilt here for
    `recipe_for_task`'s single task - one place this setup lives, so a second
    version of it is not a second thing to keep in step with `_joined` itself.
    """
    by_output = index_recipes(list(rows))
    # Matched case-insensitively: upstream writes `Build a ~|mahogany
    # table|~` where the wiki page is `Mahogany table`, and the case is
    # the only thing between them.
    by_output = {**{name.lower(): found for name, found in by_output.items()}}
    # **After the lowercasing, so an alias competes with the real names on
    # the same terms** - see `with_aliases` for why it never displaces one.
    by_output = with_aliases(by_output, aliases)
    challenges = _mapping(chunk_info.challenges, skill)
    siblings = _siblings(challenges, by_output, skill)
    cuts = fishcutting.cut_recipes(challenges, list(rows))
    # **A teleport is only castable twice at a lectern**, so its tablet is
    # what the challenge describes - see `costing/lectern.py`, which is
    # also where the two gates live.
    tablets = lectern.tablet_recipes(challenges, list(rows), valid)
    return by_output, siblings, cuts, tablets, challenges


def computed_rates(
    chunk_info: ChunkInfo,
    valid: Mapping[str, Mapping[str, Any]],
    recipes: Mapping[str, Sequence[Recipe]],
    input_seconds: Callable[[str, float], float | None],
    aliases: Mapping[str, str] = {},
    stated_ticks: Mapping[str, float] = {},
) -> tuple[dict[tuple[str, str], ActionRate], RecipeCoverage]:
    """Every reachable primary method `recipes` can price, by task and skill.

    The task half of the key is the raw challenge name, because that is what
    `Heuristics.training` is keyed by everywhere else - markup and all.

    Only methods in `valid` are considered, so this inherits the derivation's
    reachability gate rather than inventing a second one.

    `aliases` is the wiki's own redirect map for the names this join missed -
    empty unless `chunksim recipes` has been run against an export, and a
    supported way to run, exactly as an absent recipe blob is.

    **Keyed by `(task, skill)` rather than by task, because upstream files one
    challenge under both skills it pays** and this loop runs once per skill.
    Keyed by task alone the later skill silently overwrote the earlier one, in
    *alphabetical* order - so `Fletch a ~|wolfbone arrowtip|~` kept Fletching
    and read `unpriced` under Crafting, and `Replace a ~|light orb|~ in
    Dorgesh-Kaan` kept Crafting and lost Firemaking. Measured over the
    every-rollable-chunk map, 37 primary challenges are valid under more than
    one skill and 13 of them reach this; those two are the ones no other layer
    already answers for, the rest being the ten `with superheat item` smelts
    (`costing/spells.py` prices the Magic copies) and an avernic tread
    (`costing/oneoff.py`).
    """
    priced: dict[tuple[str, str], ActionRate] = {}
    coverage: dict[str, tuple[int, int]] = {}
    dropped: dict[str, str] = {}

    for skill, rows in sorted(recipes.items()):
        by_output, siblings, cuts, tablets, challenges = _skill_join_tables(
            chunk_info, valid, list(rows), skill, aliases
        )
        offered = found = 0
        for task in sorted(valid.get(skill) or {}):
            challenge = challenges.get(task)
            if not isinstance(challenge, dict) or challenge.get("Primary") is not True:
                continue
            offered += 1
            joined = _joined(task, challenge, by_output, siblings, cuts, challenges, tablets, skill)
            if joined is None:
                continue
            output, candidates = joined
            chosen = rate_for(candidates, input_seconds, stated_ticks)
            if chosen is None:
                # **Diagnosed only on failure**, so the succeeding path pays
                # nothing for it - see `unroutable`.
                dropped[task] = unroutable(candidates, input_seconds)
                continue
            recipe, rate, materials = chosen
            ticks = ticks_for(recipe, stated_ticks) or 0.0
            found += 1
            priced[task, skill] = ActionRate(
                task=task,
                skill=skill,
                xp_per_hour=rate,
                experience=recipe.experience,
                ticks=ticks,
                input_seconds=materials,
                output=output,
                materials=tuple(material.name for material in recipe.materials),
                trip_seconds=trip_seconds(recipe),
                variant=recipe.variant,
            )
        if offered:
            coverage[skill] = (found, offered)

    return priced, RecipeCoverage(skills=coverage, dropped=dict(sorted(dropped.items())))


def recipe_for_task(
    chunk_info: ChunkInfo,
    valid: Mapping[str, Mapping[str, Any]],
    recipes: Mapping[str, Sequence[Recipe]],
    task: str,
    skill: str,
    input_seconds: Callable[[str, float], float | None],
    aliases: Mapping[str, str] = {},
    stated_ticks: Mapping[str, float] = {},
) -> tuple[Recipe, float, float] | None:
    """The winning recipe behind one task's `ActionRate`, re-run rather than
    recovered.

    **`ActionRate` deliberately does not keep the `Recipe` it came from** (see
    its own docstring) - `training.trace_option` needs the real one back,
    materials and quantities included, to walk what a training method's own
    action actually consumes. This runs the same join (`_joined`, off the
    same `_skill_join_tables`) and the same selection (`rate_for`)
    `computed_rates` runs for every task in `skill` at once, for just the one
    a caller asked about - not a second implementation, the same two
    functions called with a narrower `task`.

    `None` where `task` is not a valid, primary, recipe-joinable method for
    `skill` - the same gate `computed_rates` applies before ever reaching
    `rate_for`.
    """
    if task not in (valid.get(skill) or {}):
        return None
    challenge = _mapping(chunk_info.challenges, skill).get(task)
    if not isinstance(challenge, dict) or challenge.get("Primary") is not True:
        return None
    by_output, siblings, cuts, tablets, challenges = _skill_join_tables(
        chunk_info, valid, recipes.get(skill, ()), skill, aliases
    )
    joined = _joined(task, challenge, by_output, siblings, cuts, challenges, tablets, skill)
    if joined is None:
        return None
    _output, candidates = joined
    return rate_for(candidates, input_seconds, stated_ticks)


#: The `Rate.match` tiers a dropped method loses - the scrape's two, and the
#: floor. A `modelled` or `confirmed` rate is a model's own answer about the
#: whole activity and says nothing about a recipe's inputs.
REFUSED_WHEN_DROPPED = frozenset({"default", "exact", "contained"})


def refuse_dropped(
    training: Mapping[str, Mapping[str, Rate]],
    dropped: Iterable[str],
    pinned: Container[str] = frozenset(),
) -> dict[str, dict[str, Rate]]:
    """`training` with the scraped rate removed from every dropped method.

    **A dropped method keeps its guide rate *and pays nothing for materials*,
    which biases the wrong way.** `rate_for` returns `None` when an input has
    no route - rightly, since tick-math over inputs nothing can price is a
    made-up number - but it is also the only source of
    `material_seconds_per_xp`, so the scrape then ranks as though the
    ingredients were free. And the ingredients in question are precisely the
    ones too hard to price.

    `rate_for`'s docstring recorded this rather than fixing it, on the measured
    grounds that **not one such method won a band**. That stopped being true:
    `Mix an ~|ancient mix|~` needs an `Ancient brew(2)` the map cannot route,
    so the recipe was dropped and `wiki:herblore`'s 522,500/hr stood
    unchallenged against recipe-priced neighbours at 30,546 - and it took the
    top four bands of the skill.

    So a method this project cannot cost is refused rather than quoted. A hand
    pin survives, as everywhere, and so does a *modelled* rate: a model
    answering for a whole activity is not a claim about a recipe's inputs.
    """
    refused = {task for task in dropped if task not in pinned}
    if not refused:
        return {task: dict(skills) for task, skills in training.items()}
    kept: dict[str, dict[str, Rate]] = {}
    for task, skills in training.items():
        if task not in refused:
            kept[task] = dict(skills)
            continue
        survivors = {
            skill: rate
            for skill, rate in skills.items()
            if rate.match not in REFUSED_WHEN_DROPPED
        }
        if survivors:
            kept[task] = survivors
    return kept


#: Upstream's marker for a second way into an action it already lists.
ALT_SUFFIX = " (alt)"


def base_task(task: str) -> str:
    """`task` without upstream's `(alt)` marker.

    **An `(alt)` twin is bookkeeping, not a second method.** Measured over the
    whole export there are 20 of them, **every one** has a non-alt twin, and
    every difference between a pair is a flag or a second route into the same
    action - `ManualNonProcessing` on the fish cut-ups, `ForestryXp` on the
    felling axes, a `Tasks` gate naming the other skill on the rations. Not
    one names a different thing made. So two rates that differ only by this
    suffix are one method seen twice, and `_ambiguous` must not read the pair
    as a recipe that cannot say which task it describes.
    """
    return task[: -len(ALT_SUFFIX)] if task.endswith(ALT_SUFFIX) else task


def _ambiguous(
    computed: Mapping[tuple[str, str], ActionRate],
) -> frozenset[tuple[str, str, str, tuple[str, ...]]]:
    """The `ActionRate.key`s more than one *method* landed on - see `apply`.

    Computed from the rates themselves rather than passed in, because an
    `ActionRate` already records the recipe it joined: a second source of
    truth for which recipe reached which task is the thing most likely to
    drift out of step with the join that produced them.

    **The key is the recipe, not the item it makes.** Keyed on the item, the
    twelve bar pairs read as ambiguous when `variant_candidates` has already
    told them apart - the guard would then hold a rate against a scrape on the
    strength of a collision that no longer exists.

    **And a method, not a task**: see `base_task`. `Cut up a ~|raw marlin|~`
    and its `(alt)` twin are one action listed twice, and counting them as two
    held a money-making guide about *cooking* the fish over the recipe that
    describes the knife.
    """
    seen: dict[tuple[str, str, str, tuple[str, ...]], set[str]] = {}
    for (task, _skill), rate in computed.items():
        seen.setdefault(rate.key, set()).add(base_task(task))
    return frozenset(key for key, tasks in seen.items() if len(tasks) > 1)


def apply(
    training: Mapping[str, Mapping[str, Rate]],
    computed: Mapping[tuple[str, str], ActionRate],
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

    Three guards keep the flip from reaching further than that:

    - **`REPLACEABLE` is a whitelist**, so this overwrites the floor and the
      scrape's two join tiers and nothing else. `gathering.py`'s `modelled`
      rate still wins, because a success curve really does measure the same
      thing as a guide and is the better-informed of the two.
    - **A hand pin outranks everything**, as it does everywhere else - `pinned`
      is the set of task names `heuristics/overrides.json` speaks about.
    - **An ambiguous join may fill the floor but may not replace the scrape**,
      which is `_ambiguous` and is the guard the flip actually needed.

    **A fourth guard used to sit here and is gone: a computed rate below
    `DEFAULT_XP_PER_HOUR` was skipped.** The argument was that a sub-floor
    number says the model is missing something far more often than it says the
    method is glacial, and it had a real case - Supercompost at 173 xp/hr, the
    one Farming method the recipes reached, pricing Farming 1 -> 99 at 75,353
    hours. What retired it is that the surrounding models caught up. The band
    walk takes a running *maximum*, so a slow method decides a climb only where
    it is the only one, and Tithe Farm now covers Farming from level 34 -
    bounding Supercompost to the stretch below it, 236.4h rather than 75,353h.
    Keeping the guard was costing the distinction it existed to protect:
    a method slower than the stand-in for "unpriced" was being filed *as*
    unpriced. Measured over both cached maps, removing it priced 218 more
    methods, moved 37 off a guide, and changed one climb by 5.5h.

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
    for (task, _skill), rate in computed.items():
        if task in pinned:
            continue
        existing = merged.get(task, {}).get(rate.skill)
        if existing is not None and existing.match not in REPLACEABLE:
            continue
        if (
            existing is not None
            and existing.match != "default"
            and rate.key in shared
        ):
            continue
        merged.setdefault(task, {})[rate.skill] = Rate(
            value=rate.xp_per_hour, source=RECIPE_SOURCE, match=COMPUTED_MATCH
        )
    return merged
