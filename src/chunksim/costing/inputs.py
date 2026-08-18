"""Everything `chunksim estimate` and the Estimate tab must agree about.

**Two apps computed this twice and had already drifted.** `gui/server.py`'s
`_heuristics_for` said in its own docstring that it "mirrors
`cli._load_heuristics`", which is the shape of a bug rather than a design: the
CLI passed `pinned_slayer` to `dps_bridge.enrich` and the GUI did not, so the
same map priced differently depending on which app you asked.

**And the divergence would not have stayed on screen.** `enrichment_key` hashes
`PricingDigests{rates, overrides, library}`, where `overrides` is a digest of
the *file* `heuristics/overrides.json` - identical for both apps. Nothing in the
key records whether the pins inside that file were actually applied, so the two
apps computed the same key and stored different values under it in a shared
`cache/derived/`, last writer winning. Opening the Estimate tab could change
what `chunksim estimate` printed for the same map, and the wrong number is a
perfectly plausible one.

It was latent rather than live: `heuristics/overrides.json` ships with `slayer`
and `monsters` both empty, so the two agreed until someone used the file for
what it is checked in for. Fixing the drift by unifying the code is what stops
it recurring - a shared module cannot mirror itself out of step.

Composition, not logic: every function here is the two apps' existing bodies
moved verbatim. It touches disk through `cache.py` and reads the optional DPS
extra through `dps_bridge.py`, which is why it sits beside them rather than in
the pure layer - `cli.py` and `gui/server.py` are its only callers.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from collections.abc import Callable
from typing import Any, Mapping

from chunksim.costing import (
    aerial,
    coverage,
    barbarian,
    barracuda,
    blastmine,
    farming,
    firemaking,
    gotr,
    library,
    artefacts,
    chambers,
    combat_xp,
    courses,
    disclaimed,
    dps_bridge,
    driftnet,
    forestry,
    foundry,
    herbiboar,
    implings,
    paydirt,
    pickpocket,
    production,
    pyramid,
    recipe_rates,
    pyramid_plunder,
    rumours,
    salvage,
    sacredeel,
    sepulchre,
    sorceress,
    spells,
    stated,
    troublebrewing,
    swimming,
    tempoross,
    valuables,
    wintertodt,
    wiremachine,
)
from chunksim.costing import gathering as gathering_model
from chunksim.costing.estimate import material_seconds
from chunksim.costing import prayer as prayer_costing
from chunksim.costing.heuristics import ComputedMethod, MaterialCost
from chunksim.store import cache
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.store.derived_cache import (
    Digests,
    PricingDigests,
    cached_enrich,
    pricing_digests,
)
from chunksim.costing.estimate import EstimateResult, estimate
from chunksim.costing.training import TrainingOption
from chunksim.derive.search import WorldIndex
from chunksim.remote.recipes import Material as RecipeMaterial, Recipe
from chunksim.costing.levels import goal_levels, infer_levels, reachable_providers
from chunksim.costing.heuristics import Heuristics, load, merge
from chunksim.derive.pipeline import Derived, MapState
from chunksim.derive.search import build_world_index
from chunksim.model.summary import _mapping

__all__ = [
    "EstimateAnswer",
    "ReferenceBlobs",
    "load_reference",
    "estimate_answer",
    "level_overrides",
    "load_heuristics",
    "load_recipes",
    "load_aliases",
    "recipes_from",
    "hand_material_costs",
    "priced_materials",
    "spell_material_costs",
    "recipe_priced",
    "pinned_keys",
    "priced_heuristics",
]


@dataclass(frozen=True)
class ReferenceBlobs:
    """The reference files, read once and carried.

    **One invocation, one read of each.** `heuristics/overrides.json` was read
    four times to answer a single `chunksim estimate` - by `load_heuristics`, by
    `level_overrides`, by `pinned_keys` and by `recipe_priced` - and the rate
    scrape three times to answer one `/api/roll`. None of them is expensive
    alone; what they were was a habit of asking disk for something the caller
    already had, which is also how the two apps came to answer differently.

    Nothing here needs the export, which is what lets a long-running
    `chunksim-gui` build it before it has parsed one. The half that does need the
    export is `Heuristics`, which `load_heuristics` still assembles, because
    `bossMonsters` and `slayerMonsters` come off the `ChunkInfo`.

    Frozen and passed as an argument, never a module global - a stale copy of
    this is a wrong number rather than a slow one, so the GUI's memo of it is
    validated against the files' own mtimes (`gui/derivation.py`).

    **Which map is being priced is part of what this holds**, because one of
    the layers belongs to a map. `overrides` is the *effective* corrections -
    the checked-in file with that map's own laid over it - so everything
    downstream (`load_heuristics`, `levels`, `pinned`, `recipe_priced`) gets
    the fourth layer without being told about it, which is the only way four
    readers of one merge stay agreed. The cost is that a `ReferenceBlobs` is
    now about one map, and `map_id` says which.
    """

    #: `cache/reference/wiki_rates.json`, or `{}` when never fetched.
    scraped: dict[str, Any]
    #: Whether that scrape was there at all - see `load_heuristics`.
    scraped_found: bool
    #: `heuristics/overrides.json` with `cache/overrides/<map_id>.json` merged
    #: over it, deepest value winning. Site-wide corrections are the standing
    #: opinion; a map's are what someone learned about that map, so they win.
    overrides: dict[str, Any]
    #: `src/chunksim/heuristics/wiki_recipes.json`, parsed back into `Recipe`s.
    recipes: Mapping[str, tuple[Recipe, ...]]
    #: `src/chunksim/heuristics/wiki_aliases.json` merged with
    #: `recipe_rates.HAND_ALIASES`: upstream item names the wiki now files
    #: elsewhere, so a rename reads as a rename rather than as a method with
    #: no recipe. The fetched half is empty when never run, which prices
    #: exactly as it did before the blob existed; the hand half never is.
    aliases: Mapping[str, str]
    #: `src/chunksim/heuristics/gathering.json`, indexed for lookup. **Not a
    #: cache blob** - it ships with the package and only `chunksim
    #: gather-tables` writes it - but it is read here with the rest because it
    #: is the same kind of thing to every reader downstream: numbers the
    #: estimator spends, read once per invocation and threaded.
    gathering: gathering_model.Tables
    #: What this machine would price against, for the enrichment cache key.
    pricing: PricingDigests
    #: Which map `overrides` was assembled for, or `None` for the site-wide
    #: layer alone. Carried so a caller can tell whether it is holding the
    #: right blobs for the map it is about to price.
    map_id: str | None = None

    @property
    def levels(self) -> dict[str, int]:
        """The hand-set skill levels; see `level_overrides`."""
        return _levels_from(self.overrides)

    @property
    def pinned(self) -> tuple[frozenset[str], dict[str, frozenset[str]]]:
        """The hand-written rates the computed layer must not overwrite."""
        return _pinned_from(self.overrides)


def load_reference(root: Path | None = None, map_id: str | None = None) -> ReferenceBlobs:
    """Read every reference file once. See `ReferenceBlobs`.

    `map_id` adds that map's own corrections as a fourth layer. Omitting it is
    the site-wide answer and is what a caller pricing nothing in particular
    wants; passing a map that has no corrections produces the same blobs,
    which is correct rather than merely convenient - the two price the same.
    """
    try:
        scraped: dict[str, Any] = cache.read_blob(
            cache.WIKI_RATES_BLOB_NAME, root, hint="run: chunksim heuristics"
        )["data"]
        scraped_found = True
    except cache.CacheMissError:
        scraped, scraped_found = {}, False
    overrides = cache.read_overrides(root)
    if map_id is not None:
        # `merge` is `heuristics.py`'s own deep merge, the same one that lays
        # overrides over the scrape - so the fourth layer composes by exactly
        # the rule the other three already follow.
        overrides = merge(overrides, cache.read_map_overrides(map_id, root))
    return ReferenceBlobs(
        scraped=scraped,
        scraped_found=scraped_found,
        overrides=overrides,
        recipes=recipes_from(_recipe_blob(root)),
        aliases=load_aliases(root),
        gathering=gathering_model.load_tables(cache.read_gathering(root)),
        pricing=pricing_digests(root, map_id),
        map_id=map_id,
    )


@dataclass(frozen=True)
class EstimateAnswer:
    """One estimate, with the two things a caller must say out loud about it.

    `scraped_rates` and `coverage` are not decoration: an estimate with no
    scrape is thousands of hours light, and one priced with the DPS extra is a
    materially different number from one without (3,969h against 2,816h on the
    real map). Both apps render these; neither may drop them.
    """

    result: EstimateResult
    scraped_rates: bool
    coverage: dps_bridge.DpsCoverage | None

    def as_dict(self, map_id: str) -> dict[str, Any]:
        """The JSON both apps emit. One shape, so `--export-json` and
        `/api/estimate` cannot describe the same answer differently."""
        return {
            "map_id": map_id,
            "scraped_rates": self.scraped_rates,
            "dps": self.coverage.as_dict() if self.coverage is not None else None,
            **self.result.as_dict(),
        }


@dataclass(frozen=True)
class TrainingAnswer:
    """What every skill on one map can be trained with, and by what.

    **Assembled here for the reason everything else in this module is**: the
    CLI's `chunksim training` and the GUI's methods overlay ask the same
    question, and two assemblies of it would drift exactly as `chunksim
    estimate` and the Estimate tab already did once.
    """

    #: Skill -> the best method its current level can use, or `None`.
    best: dict[str, TrainingOption | None]
    #: Skill -> every reachable method, best first. Only filled for the skill
    #: a caller asked to drill into: the full set is ~2,400 rows and neither
    #: app draws them all at once.
    methods: dict[str, tuple[TrainingOption, ...]]
    #: The levels `best` was gated on, so a reader can see why a method was
    #: left out.
    levels: dict[str, int]

    def as_dict(self, map_id: str) -> dict[str, Any]:
        """The JSON both apps emit."""
        return {
            "map_id": map_id,
            "levels": dict(sorted(self.levels.items())),
            "best": {
                skill: (option.as_dict() if option is not None else None)
                for skill, option in sorted(self.best.items())
            },
            "methods": {
                skill: [option.as_dict() for option in options]
                for skill, options in sorted(self.methods.items())
            },
        }


def training_answer(
    state: MapState,
    unlocked: Mapping[str, bool],
    derived: Derived,
    digests: Digests,
    *,
    skill: str | None = None,
    root: Path | None = None,
    refresh: bool = False,
    reference: ReferenceBlobs | None = None,
    map_id: str | None = None,
) -> TrainingAnswer:
    """Every skill's best method on one map, and one skill's full list.

    The same layers `estimate_answer` prices with, in the same order, because
    the method a reader is shown here has to be the method the estimate spent
    - a list that ranked differently from the total beside it would be worse
    than no list.

    `skill` fills `methods` for that skill alone. The full set is ~2,400 rows
    on an every-chunk map and the point of the overlay is the best few.
    """
    blobs = load_reference(root, map_id) if reference is None else reference
    heuristics, _ = load_heuristics(state.chunk_info, root, blobs)
    world = build_world_index(state.chunk_info)
    heuristics, _ = priced_heuristics(
        state,
        unlocked,
        derived,
        heuristics,
        blobs.levels,
        digests,
        world=world,
        root=root,
        refresh=refresh,
        reference=blobs,
    )
    # **The levels the estimate itself is about**, which is the map's floor
    # raised by the hand overrides - the same `{**infer_levels, **levels}`
    # every other caller here builds. A method gated above them is not one
    # this map can train with today, which is what "best" has to mean.
    at = {**infer_levels(state), **blobs.levels}
    skills = coverage.SKILLS
    return TrainingAnswer(
        best=coverage.best_methods(derived, state.chunk_info, heuristics, at, skills),
        methods=(
            {skill: coverage.skill_methods(derived, state.chunk_info, heuristics, skill)}
            if skill
            else {}
        ),
        levels={name: at.get(name, 1) for name in skills},
    )


def training_statuses(
    state: MapState,
    unlocked: Mapping[str, bool],
    derived: Derived,
    digests: Digests,
    *,
    root: Path | None = None,
    reference: ReferenceBlobs | None = None,
    map_id: str | None = None,
    valid: bool = True,
) -> dict[str, tuple[coverage.MethodStatus, ...]]:
    """`{skill: every primary method and what priced it}`.

    `valid=False` *lists* the methods the state cannot reach as well, which is
    `chunksim training`'s no-map report: the whole census rather than what one
    map can do. Either way reachability decides the `unreachable` status -
    see `coverage.status_of`.
    """
    blobs = load_reference(root, map_id) if reference is None else reference
    heuristics, _ = load_heuristics(state.chunk_info, root, blobs)
    world = build_world_index(state.chunk_info)
    heuristics, _ = priced_heuristics(
        state, unlocked, derived, heuristics, blobs.levels, digests,
        world=world, root=root, reference=blobs,
    )
    # **The ceiling calls it `uncompletable` and says why.** A method one map
    # cannot do is ordinary; one the every-rollable-chunk world cannot do is a
    # finding, so the report names the requirement that blocked it rather than
    # leaving a count.
    reach = coverage.Reachability.from_derived(derived, state)
    return {
        skill: coverage.statuses_for(
            state.chunk_info,
            heuristics,
            skill,
            derived.challenges.valid.get(skill) or {},
            only_reachable=valid,
            absent=coverage.UNREACHABLE if valid else coverage.UNCOMPLETABLE,
            reach=reach,
        )
        for skill in coverage.SKILLS
    }


def load_heuristics(
    info: ChunkInfo,
    root: Path | None = None,
    reference: ReferenceBlobs | None = None,
) -> tuple[Heuristics, bool]:
    """The two layers merged, and whether the scraped one was there at all.

    Returns the flag rather than swallowing it: an estimate with no scrape
    still produces a plausible-looking total, and the difference is not small.
    Without it there are no superior mappings and no slayer assignment sizes,
    so every superior drop and every task-gated boss drop goes unpriced - on
    the real map, 19 unpriced items against 3, and a total ~3,000 hours light.
    Printing that quietly would be the worst of both.
    """
    blobs = load_reference(root) if reference is None else reference
    return (
        load(
            merge(blobs.scraped, blobs.overrides),
            boss_monsters=frozenset(_mapping(info.code_items, "bossMonsters")),
            slayer_monsters=frozenset(info.slayer_monsters),
        ),
        blobs.scraped_found,
    )


def load_recipes(root: Path | None = None) -> dict[str, tuple[Recipe, ...]]:
    """The `chunksim recipes` blob, back as `Recipe`s, or empty if never fetched.

    Empty is a supported way to run, exactly as an absent rate scrape is: every
    method simply keeps whatever the guides and defaults gave it. The caller
    does not have to check - `recipe_rates.apply` over nothing is a no-op.
    """
    return recipes_from(_recipe_blob(root))


def load_aliases(root: Path | None = None) -> dict[str, str]:
    """The `chunksim recipes` alias map, plus `recipe_rates.HAND_ALIASES`.

    Empty of the fetched half is a supported way to run, like an absent recipe
    blob: the join simply misses the names the wiki has since renamed, which
    is what it did before this existed. The hand-curated half is never empty
    and never depends on a fetch - see `HAND_ALIASES` for why a redirect
    cannot stand in for it. **Merged with the fetch winning a collision**,
    though none is expected: the fetch is what the wiki says today and the
    hand table exists only where the wiki has nothing to say at all.
    """
    try:
        found: Mapping[str, Any] = cache.read_blob(cache.ALIASES_BLOB_NAME, root)["data"]
        fetched = {str(alias): str(target) for alias, target in found.items()}
    except cache.CacheMissError:
        fetched = {}
    return {**recipe_rates.HAND_ALIASES, **fetched}


def _recipe_blob(root: Path | None = None) -> Mapping[str, Any]:
    """The raw recipes blob, or `{}` when never fetched."""
    try:
        found: Mapping[str, Any] = cache.read_blob(cache.RECIPES_BLOB_NAME, root)["data"]
    except cache.CacheMissError:
        return {}
    return found


def recipes_from(blob: Mapping[str, Any]) -> dict[str, tuple[Recipe, ...]]:
    """`load_recipes` over bytes already read."""
    return {
        skill: tuple(
            Recipe(
                page=str(row.get("page") or ""),
                output=str(row["output"]),
                output_quantity=float(row.get("output_quantity") or 1.0),
                skill=skill,
                level=int(row.get("level") or 1),
                experience=float(row["experience"]),
                ticks=None if row.get("ticks") is None else int(row["ticks"]),
                materials=tuple(
                    RecipeMaterial(str(m["name"]), float(m.get("quantity") or 1.0))
                    for m in row.get("materials") or []
                    if isinstance(m, dict) and m.get("name")
                ),
                variant=str(row.get("variant") or ""),
            )
            for row in rows
            if isinstance(row, dict) and row.get("output") and row.get("experience") is not None
        )
        for skill, rows in blob.items()
        if isinstance(rows, list)
    }


def recipe_priced(
    state: MapState,
    derived: Derived,
    world: WorldIndex,
    heuristics: Heuristics,
    levels: dict[str, int],
    *,
    root: Path | None = None,
    reference: ReferenceBlobs | None = None,
) -> tuple[Heuristics, recipe_rates.RecipeCoverage]:
    """`heuristics` with a rate computed for every method the recipes reach.

    **Runs whether or not the DPS extra is installed**, unlike
    `priced_heuristics` - a recipe is wiki data and the item walk is this
    project's own, so neither needs `osrs-dps`. It is folded into the same
    cached call because it costs ~0.6s on a real map: the walk prices every
    material of every reachable method, and that is the whole expense.
    """
    blobs = load_reference(root) if reference is None else reference
    recipes = dict(blobs.recipes)
    pinned = frozenset(_mapping(blobs.overrides, "training"))

    # **Gathering is priced first, and the order is load-bearing.** A recipe's
    # inputs are walked by `material_seconds`, and a log or an ore is now
    # something this project *models* rather than charges four ticks for - so
    # the walk has to be able to see the modelled figure before it prices a
    # single recipe. Run the other way round, every Fletching method would be
    # costed against logs at `estimate.DEFAULT_ACTION_SECONDS`, which assumes
    # a tree hands one over every four ticks with certainty.
    heuristics, gathered, gathering_coverage = _gathered(
        state, derived, heuristics, blobs, levels, pinned
    )

    # **Before the walk, because the walk spends it.** A herb patch yields ~8.8
    # herbs for one seed, and `_route_hours` charges the seed per *herb*
    # without this - see `farming.harvest_yields`.
    heuristics = replace(
        heuristics,
        harvest_yield={
            **heuristics.harvest_yield,
            **farming.harvest_yields(
                _mapping(state.chunk_info.challenges, "Farming"),
                derived.challenges.valid.get("Farming") or {},
            ),
        },
    )
    walked = material_seconds(
        state,
        derived,
        world,
        heuristics,
        level_overrides=levels,
        # **What a `make:` route earned, so the walk can credit it.** Built
        # from the same join `computed_rates` uses - see
        # `recipe_rates.challenge_experience`.
        made_experience=recipe_rates.challenge_experience(
            state.chunk_info,
            recipes,
            blobs.aliases,
            recipe_rates.stated_ticks(state.chunk_info, recipes),
            derived.challenges.valid,
        ),
        # **The last-resort route.** An intermediate the export has no
        # challenge for is otherwise unreachable however well the wiki
        # documents it - see `estimate._recipe_hours`.
        recipes=recipes,
    )
    seconds = walked.seconds
    # **Prayer is priced here because this is where the item walk is.** Its
    # rate is a bone's experience over the time to collect one, so it needs
    # exactly the closure the recipes need and would otherwise build a second
    # `_Walk` to ask the same question.
    prayed = _prayer_methods(state, derived, heuristics, levels, seconds)
    overrides = blobs.overrides
    # **The hand materials do not depend on the recipes**, so they are read
    # before the early return: a clone with no `chunksim recipes` cache still
    # charges the foundry for its bars.
    by_hand = hand_material_costs(overrides, seconds)
    # **Spells sit under the recipes and over nothing**, which is the one
    # ordering question this layer has. Ten of the 190 also have a `{{Recipe}}`
    # - the enchants - and that row charges the jewellery or the bolts as well
    # as the runes, so it is both larger and righter. Where both describe the
    # same thing they agree: a charge-orb cast prices at 0.6162 s/xp either way.
    by_spell = spell_material_costs(heuristics, seconds)
    # **The broadest of the three, so it goes in first and is overwritten by
    # both.** A calculator row states an average action for a whole skill; a
    # recipe knows the variant, a spell's infobox is measured against the
    # export's own casts, and a hand entry is a deliberate correction. What it
    # is for is the methods the other two never reach - Firemaking has no
    # `{{Recipe}}` at all, and burned its logs for free until this existed.
    by_calc = priced_materials(
        production.calculator_costs(state.chunk_info, derived.challenges.valid, blobs.gathering),
        seconds,
    )
    if not recipes:
        return (
            replace(
                heuristics,
                computed=_merge_computed(prayed, gathered),
                material_seconds_per_xp={**by_calc, **by_spell, **by_hand},
            ),
            recipe_rates.RecipeCoverage(),
        )
    computed, coverage = recipe_rates.computed_rates(
        state.chunk_info,
        derived.challenges.valid,
        recipes,
        seconds,
        blobs.aliases,
        # **The durations the wiki does not publish** - cleaning a herb is not
        # tick-gated and nothing times a chisel done on the run. See
        # `recipe_rates.stated_ticks` for the three contributors and why the
        # merge lives in one place.
        recipe_rates.stated_ticks(state.chunk_info, recipes),
    )
    # **A recipe's tick cost is also a statement of how long the action takes**,
    # and the item walk needs that separately from the rate: it charges a
    # conversion's inputs itself, so only the performing half belongs here.
    # Guides cover 248 methods; recipes cover an order of magnitude more.
    timed = {
        **{task: rate.performing_seconds for task, rate in computed.items()},
        **heuristics.action_seconds,
    }
    # **What a method consumes, per XP it pays.** The rate a guide publishes is
    # quoted with the materials to hand, so it describes the action and not the
    # trip before it; `costing/training.py` needs both halves to rank a method
    # on what it actually costs. Taken from the same `ActionRate`s the rates
    # above come from, so the two cannot disagree about a recipe.
    per_xp = {
        **by_calc,
        **by_spell,
        **{
            task: rate.input_seconds / rate.experience
            for task, rate in computed.items()
            if rate.experience > 0 and rate.input_seconds > 0
        },
    }
    per_xp.update(by_hand)
    # **Sorting salvage costs the salvage.** Sailing has no `{{Recipe}}` at
    # all, so nothing above fills these in - see `salvage.material_seconds_per_xp`
    # for why 171,000/hr on paper is not a training method.
    per_xp.update(
        salvage.material_seconds_per_xp(
            _mapping(state.chunk_info.challenges, "Sailing"),
            derived.challenges.valid.get("Sailing") or {},
            # **The same level `_gathered` timed the wreck at.** These are the
            # two halves of one question - how long a salvage takes and what
            # that costs per experience - and a crewmate makes both faster.
            {**infer_levels(state), **levels}.get("Sailing", 1),
        )
    )
    # **And the experience that gathering paid.** The salvage a sorting
    # challenge eats was found by salvaging, which pays Sailing too - charging
    # the time without crediting the experience prices the pair as though the
    # finding were somebody else's work.
    credited = salvage.material_xp_per_xp(
        _mapping(state.chunk_info.challenges, "Sailing"),
        derived.challenges.valid.get("Sailing") or {},
    )
    # **And the generic half: a recipe whose materials pay their own skill.**
    # Smelting a bar pays Smithing before you smith it and cleaning a herb
    # pays Herblore before you mix it, and the walk has just told us whether
    # it *made* each material or bought it. Only the same skill counts - a log
    # chopped for a bow pays Woodcutting, which does nothing for Fletching.
    for task, rate in computed.items():
        if rate.experience <= 0:
            continue
        paid = sum(
            walked.experience(material, 1.0, rate.skill) for material in rate.materials
        )
        if paid > 0:
            credited[task] = paid / rate.experience
    # **An activity that gathers what it consumes must carry no material cost
    # at all.** Guardians of the Rift mines its own essence - that is most of
    # what a game is - so the rate already covers it, and charging the rune's
    # essence again bills the same twenty minutes twice. The scraped path
    # dodged this through `training._ALL_INCLUSIVE_SOURCES`, which a
    # `ComputedMethod` has no source to be matched by; removing the entry
    # fixes both paths at once and is the truer statement anyway.
    # **And a sacred eel is the same shape**: the dissection is spammable, so
    # the whole hour is the catching that the model already prices. Charging
    # the eel again read 26,620/hr as 13,002. See `costing/sacredeel.py`.
    for task in list(per_xp):
        if gotr.GUARDIAN_SUFFIX in task or task == sacredeel.TASK:
            del per_xp[task]
    # **The rate layers, applied and then refused, in that order.** Written as
    # statements rather than as one nested expression: there are four refusals
    # now and a reader of the innermost had to count brackets to find out which
    # layer it was inside. The order is the whole of the layering and each step
    # says what it is for.
    #
    # **`recipe_rates.apply` cannot overwrite a modelled rate**, and needs no
    # telling: it only fills where the existing rate is `default`, and
    # `gathering.apply` has already written a `modelled` one. The two computed
    # layers therefore compose without either having to know the other exists.
    rated = recipe_rates.apply(heuristics.training, computed, pinned)
    # **Spells fill after the recipes and share their whitelist.** A recipe
    # knows which variant of an action it describes; a cast timed by the wiki
    # and charged by the export's own `Items` is the answer for the 100-odd
    # Magic methods no recipe reaches. See `costing/spells.py`.
    rated = spells.apply(
        rated,
        spells.computed_rates(
            state.chunk_info, derived.challenges.valid, heuristics.spell_costs, seconds
        ),
        pinned,
    )
    # **Refused after applied, so a computed rate is never removed.** A method
    # whose inputs have no route keeps no *scraped* rate - see
    # `recipe_rates.refuse_dropped` for the bias that fixes.
    rated = recipe_rates.refuse_dropped(rated, coverage.dropped, pinned)
    # **A teleport in `computed` is one whose tablet joined**, so this is the
    # lectern gate read back rather than applied twice.
    rated = spells.refuse_untabled(rated, heuristics.spell_costs, computed, pinned)
    # **A pickpocket nothing charts keeps no rate either.** The flat cycle it
    # would otherwise keep is not a worse estimate but a known-wrong one: on
    # all eighteen NPCs the wiki charts it runs 2x to 3.6x fast. See
    # `costing/pickpocket.py`.
    rated = pickpocket.refuse_uncharted(
        rated,
        heuristics.pickpockets,
        _mapping(state.chunk_info.challenges, "Thieving"),
        derived.challenges.valid.get("Thieving") or {},
        pinned,
    )
    # **And a method its own page says is not for training keeps no rate**,
    # which is a different claim from "slow" - see `costing/disclaimed.py`.
    rated = disclaimed.refuse(rated, pinned)
    return (
        replace(
            heuristics,
            training=rated,
            action_seconds=timed,
            computed=_merge_computed(prayed, gathered),
            material_seconds_per_xp=per_xp,
            material_xp_per_xp=credited,
        ),
        coverage,
    )


def _guardian_experience(recipes: Mapping[str, Any]) -> dict[str, float]:
    """`{rune: xp per guardian essence}`, from the recipe corpus.

    The minigame's own recipes, told apart by the material they consume -
    `Guardian essence` rather than pure or daeyalt - and the plain variants
    only, since a combination rune needs two altars and is a different action.
    """
    found: dict[str, float] = {}
    for recipe in recipes.get("Runecraft") or ():
        if recipe.variant:
            continue
        if any(material.name == "Guardian essence" for material in recipe.materials):
            found[recipe.output] = recipe.experience
    return found


def _gathered(
    state: MapState,
    derived: Derived,
    heuristics: Heuristics,
    blobs: ReferenceBlobs,
    levels: dict[str, int],
    pinned: frozenset[str],
) -> tuple[Heuristics, dict[str, tuple[ComputedMethod, ...]], gathering_model.GatheringCoverage]:
    """`heuristics` with `costing/gathering.py`'s answers laid on.

    Three things go on, and they land in three different places because they
    answer three different questions:

    - **The rate at the method's opening level** replaces whatever the scrape
      had, in `training`. See `gathering.apply` for why this layer wins where
      `recipe_rates`' loses.
    - **The rest of the curve** goes into `computed`, which carries a level per
      entry so `training_bands` can open each point where it belongs. A
      gathering rate is a function of level and one number cannot be it.
    - **The seconds one resource costs** goes into `action_seconds`, which is
      what `estimate._route_hours` charges for performing a challenge. That is
      the join between this model and the production half: a log costs what
      chopping one costs, rather than the four ticks
      `estimate.DEFAULT_ACTION_SECONDS` stands in with.

    **The walk is charged the un-banked figure.** `NodeRate.seconds_per_item`
    drops the bank share deliberately: `estimate._route_hours` already charges
    a trip for the production action that consumes the material, and
    `recipe_rates.trip_seconds` is where. Charging both bills one walk to the
    bank twice, which is the error `training._material_cost` exists to prevent
    in the other direction.
    """
    if blobs.gathering.empty:
        return heuristics, {}, gathering_model.GatheringCoverage()
    at_level = {**infer_levels(state), **levels}
    priced, coverage = gathering_model.priced_methods(
        state.chunk_info,
        derived.challenges.valid,
        blobs.gathering,
        frozenset(derived.challenges.available_items),
        at_level,
    )
    # **Puro-Puro is one method rather than twelve, and it is not a node**, so
    # it is produced beside the node walk instead of inside it - see
    # `costing/implings.py`. Merged here because that module reads
    # `gathering.py` and the dependency has to run one way. It contributes
    # nothing on a map that cannot reach the realm, which is upstream's gate
    # rather than one this project invents.
    nodeless = {
        **implings.methods(blobs.gathering, derived.challenges.valid),
        # Aerial fishing is one action paying two skills and never missing, so
        # it is a mix rather than a node - see `costing/aerial.py`.
        **aerial.methods(blobs.gathering, derived.challenges.valid),
        # **The same catch the node walk already priced, read a second time.**
        # Barbarian fishing pays Strength and Agility beside its Fishing, and
        # the export carries all three challenges under each - see
        # `costing/barbarian.py`. Fishing itself is not touched here.
        **barbarian.methods(blobs.gathering, derived.challenges.valid),
    }
    # The level a player is at now is what the item walk should pay, where the
    # band walk gets the whole curve; `min` is the method's opening point and
    # is the fallback for a skill no completion has established a level for.
    timed: dict[str, float] = {}
    for task, rates in priced.items():
        held = at_level.get(rates[0].skill, 1)
        chosen = min(
            (rate for rate in rates if rate.level <= held), key=lambda rate: -rate.level,
            default=min(rates, key=lambda rate: rate.level),
        )
        if chosen.seconds_per_item > 0:
            timed[task] = chosen.seconds_per_item
    # **A salvage costs what finding it costs.** The sorting challenge eats
    # one, and without a duration on the wreck the walk charged
    # `estimate.DEFAULT_ACTION_SECONDS` - which read sorting as the fastest
    # thing in Sailing by an order of magnitude. See `costing/salvage.py`.
    timed.update(
        salvage.action_seconds(
            _mapping(state.chunk_info.challenges, "Sailing"),
            derived.challenges.valid.get("Sailing") or {},
            at_level.get("Sailing", 1),
        )
    )
    # **What a pay-dirt turns out to be** - see `costing/paydirt.py`. It takes
    # the figure just computed for `Mine ~|pay-dirt|~` rather than its own, so
    # one model owns how fast a pay-dirt is mined and the other what comes out
    # of it. Without this the item walk read `Obtain ~|runite ore|~ from
    # pay-dirt` at the four-tick default and made a runite bar cheaper than an
    # adamantite one.
    timed.update(paydirt.timed(timed, at_level.get("Mining", 1)))
    # **And the same again for the Blast Mine** - see `costing/blastmine.py`,
    # which is where the runite ore came from on a map holding every chunk.
    timed.update(blastmine.action_seconds(at_level.get("Mining", 1)))
    # **Puro-Puro goes to the bands and not to `training`, and the difference
    # is a real one.** `apply` writes a method's opening rate into `training`,
    # where `training_options` reads the level off the *challenge* - and
    # upstream gives that challenge `Level: 1`, because what gates it is
    # holding the realm rather than a level. Routed that way the climb opened
    # at 1 with the level-17 figure and swallowed the floor band: 12.0h of
    # honest ignorance became 0.6h. Sent to `banded_methods` alone, every point
    # carries the level this model computed it at.
    banded = gathering_model.banded_methods(priced)
    for skill, methods in gathering_model.banded_methods(nodeless, keep_first=True).items():
        banded[skill] = (*banded.get(skill, ()), *methods)
    # **Herbiboar is a puzzle rather than a loop**, so it never enters the node
    # walk - see `costing/herbiboar.py`. It contributes bands and no training
    # rate, for the reason Puro-Puro does: the level shape is the point, and the
    # scraped guide figure it refines is one number across twenty levels.
    for skill, methods in herbiboar.methods(blobs.gathering, derived.challenges.valid).items():
        banded[skill] = (*banded.get(skill, ()), *methods)
    # **Guardians of the Rift is one minigame, not twelve rune methods.** The
    # rune you get is the game's decision, so all twelve challenges share one
    # curve - and the bands carry the *minigame's* level rather than the
    # rune's, which is what stops a level-1 player being offered it. See
    # `costing/gotr.py`.
    # **The Arceuus library pays a multiple of the level you already have**,
    # in either Magic or Runecraft - one activity, two challenges, and no rate
    # table would ever join a name like `Turn in books at the ~|Arceuus
    # Library|~ for Runecraft xp`. See `costing/library.py`.
    for skill, methods in library.methods(
        {name: _mapping(state.chunk_info.challenges, name) for name in library.EXPERIENCE_PER_LEVEL},
        derived.challenges.valid,
    ).items():
        banded[skill] = (*banded.get(skill, ()), *methods)
    # **Shipwreck salvaging, with one crewmate rather than the guides' two.**
    # Upstream splits finding from sorting where the guides bundle them, and a
    # crewmate is worth D^2/125 rather than a second player - see
    # `costing/salvage.py`.
    for skill, methods in salvage.methods(
        _mapping(state.chunk_info.challenges, "Sailing"),
        derived.challenges.valid.get("Sailing") or {},
    ).items():
        banded[skill] = (*banded.get(skill, ()), *methods)
    # **The Barracuda trials, counted rather than quoted.** `Sailing training`
    # states all nine rates as wiki expressions over components each trial's
    # own page publishes, so this reads the components and reproduces the
    # scrape exactly - deliberately, since that makes the scrape this model's
    # oracle. See `costing/barracuda.py`.
    for skill, methods in barracuda.methods(
        _mapping(state.chunk_info.challenges, "Sailing"),
        derived.challenges.valid.get("Sailing") or {},
    ).items():
        banded[skill] = (*banded.get(skill, ()), *methods)
    # **Burning a log is two methods and the export always said so.** A line
    # rolls against the skill's own success curve and a forester's campfire
    # does not, so the two cross over at level 12 - where the pricing had one
    # number for both. See `costing/firemaking.py`.
    for skill, methods in firemaking.methods(
        _mapping(state.chunk_info.challenges, "Firemaking"),
        derived.challenges.valid.get("Firemaking") or {},
        heuristics.burning,
    ).items():
        banded[skill] = (*banded.get(skill, ()), *methods)
    # **Pickpocketing is a roll and was priced as a constant.** The wiki
    # publishes the whole mechanic - a 2-tick attempt, an 8-tick stun and
    # `np/(10-8p)` - and a success curve per NPC. See `costing/pickpocket.py`.
    for skill, methods in pickpocket.methods(
        _mapping(state.chunk_info.challenges, "Thieving"),
        derived.challenges.valid.get("Thieving") or {},
        heuristics.pickpockets,
    ).items():
        banded[skill] = (*banded.get(skill, ()), *methods)
    # **A stall that can fail**, and its own page publishes the cycle, the
    # experience and the success chart - see `costing/wiremachine.py`. It is
    # the last money-making guide in Thieving.
    for skill, methods in wiremachine.methods(
        _mapping(state.chunk_info.challenges, "Thieving"),
        derived.challenges.valid.get("Thieving") or {},
    ).items():
        banded[skill] = (*banded.get(skill, ()), *methods)
    for skill, methods in gotr.methods(
        _mapping(state.chunk_info.challenges, "Runecraft"),
        derived.challenges.valid.get("Runecraft") or {},
        heuristics.gotr,
        _guardian_experience(blobs.recipes),
    ).items():
        banded[skill] = (*banded.get(skill, ()), *methods)
    # Rumours pay an exact formula at an invented pace - see
    # `costing/rumours.py`, whose every band is marked `guess` for it.
    for skill, methods in rumours.methods(derived.challenges.valid).items():
        banded[skill] = (*banded.get(skill, ()), *methods)
    # **The Chambers families gate on Cooking as well as their own skill**, so
    # this is the one place a second skill's level has to be handed in - see
    # `costing/chambers.py`.
    # **Nine events, none of them chosen** - see `costing/forestry.py`. It pays
    # six skills at once, which is why it is merged like this rather than being
    # priced under whichever event a challenge names.
    for skill, methods in forestry.methods(
        blobs.gathering, state.chunk_info, derived.challenges.valid
    ).items():
        banded[skill] = (*banded.get(skill, ()), *methods)
    # **One game, three skills, and no chance anywhere in it** - see
    # `costing/wintertodt.py`. Needs neither the tables nor the export: the
    # rate is the wiki's own multipliers times a count of games, so `valid` is
    # the whole of its input.
    for skill, methods in wintertodt.methods(derived.challenges.valid).items():
        banded[skill] = (*banded.get(skill, ()), *methods)
    # **The same boss played the slow way, which is the only way it pays
    # Construction** - see `costing/wintertodt.solo_methods`. Firemaking's
    # level is handed in for the reason Pyramid Plunder's Strength is: the
    # rate is a function of a skill other than the one being trained, and
    # upstream's Construction row says `Level: 1` because it states the boss's
    # requirement somewhere else entirely.
    for skill, methods in wintertodt.solo_methods(
        derived.challenges.valid, at_level.get("Firemaking", 1)
    ).items():
        banded[skill] = (*banded.get(skill, ()), *methods)
    # **One game, two skills that cannot both be maximised** - see
    # `costing/pyramid_plunder.py`. Strength needs its own level because the
    # sarcophagus chart is against that and not against Thieving, which is the
    # same second-skill hand-in `chambers` needs.
    for skill, methods in pyramid_plunder.methods(
        derived.challenges.valid, at_level.get("Strength", 1)
    ).items():
        banded[skill] = (*banded.get(skill, ()), *methods)
    # **One hour paying two skills at once, priced as the slower exchange** -
    # see `costing/swimming.py`. Each skill reads only its own level, so this
    # needs nothing handed in.
    for skill, methods in swimming.methods(derived.challenges.valid).items():
        banded[skill] = (*banded.get(skill, ()), *methods)
    # **Four gardens and the level picks which** - see `costing/sorceress.py`.
    # Flat rates, so nothing but the valid set is needed.
    for skill, methods in sorceress.methods(derived.challenges.valid).items():
        banded[skill] = (*banded.get(skill, ()), *methods)
    # **Five floors the scrape gave one rate** - see `costing/sepulchre.py`.
    for skill, methods in sepulchre.methods(derived.challenges.valid).items():
        banded[skill] = (*banded.get(skill, ()), *methods)
    # **A money-making rate that was winning from level 1** - see
    # `costing/pyramid.py`, whose bands open where the wiki's table does.
    for skill, methods in pyramid.methods(derived.challenges.valid).items():
        banded[skill] = (*banded.get(skill, ()), *methods)
    # **A lap and a lap time, which is what a course is** - see
    # `costing/courses.py`, and the eight it leaves to the guide.
    for skill, methods in courses.methods(derived.challenges.valid).items():
        banded[skill] = (*banded.get(skill, ()), *methods)
    # **Jagex's own two columns, multiplied** - see `costing/foundry.py`.
    for skill, methods in foundry.methods(derived.challenges.valid).items():
        banded[skill] = (*banded.get(skill, ()), *methods)
    # **A published curve rather than a derived one** - see
    # `costing/valuables.py`, which is a transcription and says so.
    for skill, methods in valuables.methods(derived.challenges.valid).items():
        banded[skill] = (*banded.get(skill, ()), *methods)
    # **The one activity that derives completely** - see
    # `costing/artefacts.py`, whose published table it reproduces exactly.
    for skill, methods in artefacts.methods(derived.challenges.valid).items():
        banded[skill] = (*banded.get(skill, ()), *methods)
    # **Which harpoon the map holds decides this one** - see
    # `costing/tempoross.py`, which needs the reachable set for that and
    # re-chooses at every band the way the node walk re-chooses an axe.
    for skill, methods in tempoross.methods(
        derived.challenges.valid, frozenset(derived.challenges.available_items)
    ).items():
        banded[skill] = (*banded.get(skill, ()), *methods)
    # **And the other regime, which is a Cooking method.** The same fight,
    # counted rather than tabulated: 55 fish loaded a game at 10 experience
    # each, five games an hour. The two challenges are two choices - a climb
    # takes the best of what it is offered - so Fishing keeps the not-cooking
    # table and Cooking gets this.
    for skill, methods in tempoross.cooking_methods(derived.challenges.valid).items():
        banded[skill] = (*banded.get(skill, ()), *methods)
    # **Trouble Brewing's Cooking is a woodcutting loop**, so the *Woodcutting*
    # level and the axe the map holds decide it - see
    # `costing/troublebrewing.py`, which retires the 15,000 `stated.py` was
    # guessing for this one of its eight skills.
    for skill, methods in troublebrewing.methods(
        blobs.gathering,
        state.chunk_info,
        derived.challenges.valid,
        frozenset(derived.challenges.available_items),
        at_level.get("Woodcutting", 1),
    ).items():
        banded[skill] = (*banded.get(skill, ()), *methods)
    # Two activities whose rate is stated rather than computed - see
    # `costing/stated.py`, whose every band is marked `guess`.
    # Two skills at once and a ceiling at 70 - see `costing/driftnet.py`.
    for skill, methods in driftnet.methods(
        blobs.gathering, derived.challenges.valid
    ).items():
        banded[skill] = (*banded.get(skill, ()), *methods)
    for skill, methods in stated.methods(
        state.chunk_info,
        derived.challenges.valid,
        blobs.gathering,
        frozenset(derived.challenges.available_items),
        state.completed_challenges.get("Quest") or {},
    ).items():
        banded[skill] = (*banded.get(skill, ()), *methods)
    for skill, methods in chambers.methods(
        blobs.gathering, derived.challenges.valid, at_level.get("Cooking", 1)
    ).items():
        banded[skill] = (*banded.get(skill, ()), *methods)
    # **A Cooking method with no Cooking time in it**, so the *Fishing* level
    # is the second one handed in here - the cut is not tick-gated and an hour
    # of dissecting is an hour of catching. See `costing/sacredeel.py` for why
    # the bands are Cooking's even so.
    for skill, methods in sacredeel.methods(
        blobs.gathering,
        _mapping(state.chunk_info.challenges, sacredeel.SKILL),
        derived.challenges.valid,
        at_level.get("Fishing", 1),
    ).items():
        banded[skill] = (*banded.get(skill, ()), *methods)
    return (
        replace(
            heuristics,
            training=gathering_model.apply(heuristics.training, priced, pinned),
            action_seconds={**heuristics.action_seconds, **timed},
            pinned=pinned,
        ),
        banded,
        coverage,
    )


def _merge_computed(
    *layers: Mapping[str, tuple[ComputedMethod, ...]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """Every computed layer's methods for a skill, **concatenated not replaced**.

    Prayer offers bones and gathering offers a curve; a skill can have both, and
    a `dict` update would silently drop whichever was written first. That is not
    hypothetical - Prayer and combat already had to be merged rather than
    assigned for exactly this reason.
    """
    merged: dict[str, tuple[ComputedMethod, ...]] = {}
    for layer in layers:
        for skill, methods in layer.items():
            merged[skill] = merged.get(skill, ()) + tuple(methods)
    return merged


def priced_materials(
    stated: Mapping[str, MaterialCost], collect: Callable[[str, float], float | None]
) -> dict[str, float]:
    """`{task: seconds of gathering per XP}`, for methods whose per-action
    consumption and per-action experience are both known.

    The arithmetic both stated sources share, so a hand entry and a spell's
    rune cost cannot come out differently: total seconds for one action over
    the XP that action pays. The granularity cancels - ten darts for ten times
    the XP is the same number as one for one - so only the ratio has to be
    right.

    **An item the walk cannot price leaves its method uncharged rather than
    dropping it.** That is the same direction `recipe_rates` is wrong in with
    an unpriceable material, and the better failure of the two: dropping would
    silently remove a method somebody deliberately rated.
    """
    costs: dict[str, float] = {}
    for task, cost in stated.items():
        if cost.experience <= 0:
            continue
        total = 0.0
        for item, quantity in cost.items.items():
            if quantity <= 0:
                continue
            priced = collect(item, float(quantity))
            if priced is None:
                total = -1.0
                break
            total += priced
        if total > 0:
            costs[task] = total / cost.experience
    return costs


def spell_material_costs(
    heuristics: Heuristics, collect: Callable[[str, float], float | None]
) -> dict[str, float]:
    """`material_seconds_per_xp` for every `Cast ...` task the wiki prices.

    **Casting is the one family where the general fix exists rather than
    needing a hand entry per method.** The bias `hand_material_costs` describes
    needs experience per action and quantity per action together, and the export
    states neither - but `infobox_spell` states both, for all 201 spells, so 190
    of the export's 214 `Cast` challenges get a real material cost off one Bucket
    query. See `remote/combat.parse_spell_costs` for what counts as consumed.

    It matters because casting *wins climbs*. On the reference map `Cast
    ~|varrock teleport|~` held 25 -> 99 at a published 38,500/hr with its 3 air,
    1 fire and 1 law charged at nothing; charged, it is 11,807 effective and
    loses the top band. **Magic 1 -> 99 goes 339.7h -> 1,018.5h on the reference
    map and 396.7h -> 1,015.4h on the second map.** Every rune prices on both.
    """
    return priced_materials(heuristics.spell_costs, collect)


def hand_material_costs(
    overrides: Mapping[str, Any], collect: Callable[[str, float], float | None]
) -> dict[str, float]:
    """`material_seconds_per_xp` for a method somebody rated by hand.

    **The last word on what a method consumes**, over the recipe that describes
    it and over `costing/production.py`'s calculator row. The export states
    neither half of the pair this needs - 0 of its 2,710 primary challenges
    carry a quantity anywhere in `Items`, and its one experience field is a
    quest's one-off lump - so every source of it is something joined on from
    outside, and this is the one a person writes deliberately.

    This is the hand-stated half, in the file hand-stated numbers already live
    in. An entry is `{"experience": <per action>, "items": {<name>:
    <quantity>}}`; the seconds come from the same item walk a recipe's do, so
    the two cannot disagree about what a bar costs on this map.

    **The Giants' Foundry is what it was written for**, and was the whole of it
    until `production.py` turned the general case into a layer. Its six
    challenges declare `Items: ["AdamantMats[+]*", ...]` -
    family placeholders, not items - with `Output: None`, so nothing joins them
    and the wiki's 276,000/hr was being spent with the bars free. The wiki
    states both missing numbers outright: the crucible "needs to be filled with
    28 bars worth of metal", and the alloy-tier table's average XP per sword is
    exactly the hourly figure divided by its swords per hour, so the quantity
    and the experience corroborate the rate already in `training`.

    **Bars rather than the family's smithed members**, which the crucible also
    takes: a smithed item contributes one bar *less* than it cost to make, so
    it is strictly worse per bar of value and no player would use one.

    An item the walk cannot price at all leaves its method uncharged rather
    than dropping it, which is what `recipe_rates` does with an unpriceable
    material and is wrong in the same direction. It cannot bite here - all six
    bars price on both cached maps - and a drop would silently remove a method
    a person deliberately rated.
    """
    stated: dict[str, MaterialCost] = {}
    for task, entry in _mapping(overrides, "materials").items():
        if not isinstance(entry, dict):
            continue
        experience = entry.get("experience")
        if not isinstance(experience, (int, float)) or experience <= 0:
            continue
        stated[task] = MaterialCost(
            experience=float(experience),
            items={
                str(item): float(quantity)
                for item, quantity in _mapping(entry, "items").items()
                if isinstance(quantity, (int, float)) and quantity > 0
            },
        )
    costs = priced_materials(stated, collect)
    return costs


def _prayer_methods(
    state: MapState,
    derived: Derived,
    heuristics: Heuristics,
    levels: dict[str, int],
    collect: Callable[[str, float], float | None],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """Prayer's computed methods, or `{}` when the scrape has no bone table.

    Empty rather than defaulted: without the wiki's burial values there is
    nothing to compute, and the six offering challenges the export *does* carry
    remain the answer. See `costing/prayer.py`.
    """
    if not heuristics.bones:
        return {}
    found = prayer_costing.prayer_methods(
        state.chunk_info,
        derived,
        heuristics.bones,
        heuristics.altars,
        {**infer_levels(state), **levels},
        collect,
    )
    if not found:
        return {}
    return {
        "Prayer": tuple(
            ComputedMethod(
                method=method.method, xp_per_hour=method.xp_per_hour, level=method.level
            )
            for method in found
        )
    }


def level_overrides(root: Path | None = None) -> dict[str, int]:
    """The hand-set skill levels from `heuristics/overrides.json`.

    `isinstance(level, bool)` is excluded deliberately - `True` is an `int` in
    Python, and a stray `"Attack": true` would otherwise become level 1.
    """
    return _levels_from(cache.read_overrides(root))


def _levels_from(raw: Mapping[str, Any]) -> dict[str, int]:
    """`level_overrides` over bytes already read."""
    return {
        skill: int(level)
        for skill, level in _mapping(raw, "levels").items()
        if isinstance(level, int) and not isinstance(level, bool)
    }


def pinned_keys(root: Path | None = None) -> tuple[frozenset[str], dict[str, frozenset[str]]]:
    """The hand-written rates the computed layer must not overwrite.

    Monsters and slayer tasks, from the one file. Returned together because
    they come from one read and are passed to one call - splitting them is how
    the GUI came to pass the first and forget the second.
    """
    return _pinned_from(cache.read_overrides(root))


def _pinned_from(raw: Mapping[str, Any]) -> tuple[frozenset[str], dict[str, frozenset[str]]]:
    """`pinned_keys` over bytes already read."""
    monsters = frozenset(_mapping(raw, "monsters"))
    slayer = {
        master: frozenset(tasks)
        for master, tasks in _mapping(raw, "slayer").items()
        if isinstance(tasks, dict)
    }
    return monsters, slayer


def priced_heuristics(
    state: MapState,
    unlocked: Mapping[str, bool],
    derived: Derived,
    heuristics: Heuristics,
    levels: dict[str, int],
    digests: Digests,
    *,
    world: WorldIndex | None = None,
    root: Path | None = None,
    refresh: bool = False,
    reference: ReferenceBlobs | None = None,
) -> tuple[Heuristics, dps_bridge.DpsCoverage | None]:
    """Every rate this machine can compute, layered on and cached as one.

    Two computations, deliberately behind one key. `recipe_priced` costs
    ~0.6s on a real map and `dps_bridge.enrich` ~0.7s, and both are pure functions of
    the same inputs, so splitting them into two cache entries would buy nothing
    and give the two a chance to disagree about which derivation they saw.

    **The recipe half runs with or without the DPS extra**, which is why this
    no longer returns early when the extra is absent. That path used to skip
    the cache entirely; now it stores, because without the extra there is still
    six seconds of item walking to avoid repeating. `None` for the coverage
    still means `osrs-dps` is not installed - a supported way to run and a
    different answer rather than a broken one; both apps say which they show.

    **Order matters: recipes first, then fights.** A recipe rate is priced
    through the item walk, which spends kill rates, so running `enrich` first
    would change what a material costs. It does not run first, and a comment
    here is cheaper than the afternoon spent finding out why two runs of the
    same map disagreed.

    The levels are `goal_levels`, the ones the chunk *ends* at, because that is
    what `slayer.py` already judges a master at and pricing the same fight at
    two different levels inside one command would be indefensible.
    """
    index = build_world_index(state.chunk_info) if world is None else world
    blobs = load_reference(root) if reference is None else reference
    pinned_monsters, pinned_slayer = blobs.pinned
    goals = goal_levels(state, derived, {**infer_levels(state), **levels})

    def compute() -> tuple[Heuristics, dps_bridge.DpsCoverage | None]:
        priced, _ = recipe_priced(
            state, derived, index, heuristics, levels, root=root, reference=blobs
        )
        coverage: dps_bridge.DpsCoverage | None = None
        if dps_bridge.DPS_AVAILABLE:
            priced, coverage = dps_bridge.enrich(
                priced,
                state.chunk_info,
                derived,
                goals,
                pinned_monsters=pinned_monsters,
                pinned_slayer=pinned_slayer,
            )
        # **Last, because it multiplies the kill rates.** Running this before
        # `enrich` would price combat off the scraped rates and then throw the
        # simulated ones away - the numbers would be quietly worse on exactly
        # the maps where the extra had most to say.
        caps = combat_xp.spawn_caps(state.chunk_info, derived)
        by_style: dict[str, dps_bridge.CombatRate] = {}
        if dps_bridge.DPS_AVAILABLE:
            # **The kit is not optional here.** Without it the Magic loadout
            # has no runes and never lands a hit, so `price_combat` returned
            # melee and ranged only - and Magic fell through to the rough
            # fallback, which is the inconsistent model this call exists to
            # replace.
            by_style = dps_bridge.price_combat(
                state.chunk_info,
                derived.bis.picks,
                goals,
                sorted(combat_xp.farmable_providers(derived)),
                kit=dps_bridge.assemble_kit(
                    state.chunk_info,
                    goals,
                    items=derived.challenges.available_items,
                    source_index=derived.source_index,
                ),
                slayer_monsters=frozenset(state.chunk_info.slayer_monsters),
                boss_monsters=frozenset(_mapping(state.chunk_info.code_items, "bossMonsters")),
                multipliers={
                    name: entry.xp_multiplier
                    for name, entry in priced.monster_stats.items()
                },
                caps=caps,
            )
        rates, damage = combat_xp.combat_rates(
            derived,
            priced,
            priced.monster_stats,
            priced.spells,
            goals,
            by_style=by_style,
            caps=caps,
        )
        # **Merged, not replaced - and this used to say so while replacing.**
        # `recipe_priced` has already put Prayer's methods in `computed`, and
        # combat's arrive later because they multiply the kill rates. A dict
        # comprehension keyed by skill overwrote the whole tuple, so anything
        # non-combat filed under a *combat* skill was destroyed: barbarian
        # fishing's Strength bands, all 21 of them, computed and then thrown
        # away before anything could read them.
        merged = dict(priced.computed)
        for skill, rate in rates.items():
            if rate.value <= 0:
                continue
            merged[skill] = (
                *merged.get(skill, ()),
                ComputedMethod(
                    method=rate.source.removeprefix("combat:"),
                    xp_per_hour=rate.value,
                    match=rate.match,
                    # Damage against hitpoints, so the entry a reader could
                    # look at is the monster's - not a training rate, which
                    # is a path nothing would read.
                    knob=f"monster_stats/{rate.source.removeprefix('combat:')}",
                ),
            )
        return (
            replace(priced, combat=rates, combat_damage=damage, computed=merged),
            coverage,
        )

    return cached_enrich(
        compute,
        state,
        unlocked,
        digests,
        blobs.pricing,
        root=root,
        refresh=refresh,
    )


def estimate_answer(
    state: MapState,
    unlocked: Mapping[str, bool],
    derived: Derived,
    digests: Digests,
    *,
    root: Path | None = None,
    refresh: bool = False,
    reference: ReferenceBlobs | None = None,
    map_id: str | None = None,
) -> EstimateAnswer:
    """The whole estimate, assembled once for whichever app asked.

    Everything above, in the one order both apps used: load the layers, read
    the level overrides, let the computed rates beat the scraped ones, then
    price. What is left at the call sites is rendering.

    `reference` is the reference files already read - pass one in a process
    that will ask more than once, which is the GUI. Omitted, this reads them,
    which is what a one-shot CLI invocation wants.

    `map_id` is which map's own corrections to lay on. **Both apps must pass
    it or neither should**: this function exists because `chunksim estimate` and
    the Estimate tab had already drifted once, and a fourth layer one of them
    applied would be that drift again, in the place hardest to notice. It is
    ignored when `reference` is given, since those blobs already carry
    whichever map they were assembled for - `ReferenceBlobs.map_id` says
    which.
    """
    blobs = load_reference(root, map_id) if reference is None else reference
    heuristics, scraped_rates = load_heuristics(state.chunk_info, root, blobs)
    levels = blobs.levels
    world = build_world_index(state.chunk_info)
    heuristics, coverage = priced_heuristics(
        state,
        unlocked,
        derived,
        heuristics,
        levels,
        digests,
        world=world,
        root=root,
        refresh=refresh,
        reference=blobs,
    )
    result = estimate(
        state, derived, world, heuristics, level_overrides=levels, recipes=blobs.recipes
    )
    return EstimateAnswer(result=result, scraped_rates=scraped_rates, coverage=coverage)
