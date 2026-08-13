"""Everything `fray estimate` and the Estimate tab must agree about.

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
what `fray estimate` printed for the same map, and the wrong number is a
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

from fray_claude.costing import combat_xp, dps_bridge, recipe_rates
from fray_claude.costing.estimate import material_seconds
from fray_claude.costing import prayer as prayer_costing
from fray_claude.costing.heuristics import ComputedMethod, MaterialCost
from fray_claude.store import cache
from fray_claude.model.chunkinfo import ChunkInfo
from fray_claude.store.derived_cache import (
    Digests,
    PricingDigests,
    cached_enrich,
    pricing_digests,
)
from fray_claude.costing.estimate import EstimateResult, estimate
from fray_claude.derive.search import WorldIndex
from fray_claude.remote.recipes import Material as RecipeMaterial, Recipe
from fray_claude.costing.levels import goal_levels, infer_levels, reachable_providers
from fray_claude.costing.heuristics import Heuristics, load, merge
from fray_claude.derive.pipeline import Derived, MapState
from fray_claude.derive.search import build_world_index
from fray_claude.model.summary import _mapping

__all__ = [
    "EstimateAnswer",
    "ReferenceBlobs",
    "load_reference",
    "estimate_answer",
    "level_overrides",
    "load_heuristics",
    "load_recipes",
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
    four times to answer a single `fray estimate` - by `load_heuristics`, by
    `level_overrides`, by `pinned_keys` and by `recipe_priced` - and the rate
    scrape three times to answer one `/api/roll`. None of them is expensive
    alone; what they were was a habit of asking disk for something the caller
    already had, which is also how the two apps came to answer differently.

    Nothing here needs the export, which is what lets a long-running
    `fray-gui` build it before it has parsed one. The half that does need the
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
    #: `cache/reference/wiki_recipes.json`, parsed back into `Recipe`s.
    recipes: Mapping[str, tuple[Recipe, ...]]
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
            cache.WIKI_RATES_BLOB_NAME, root, hint="run: fray heuristics"
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
        recipes=_recipes_from(_recipe_blob(root)),
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
    """The `fray recipes` blob, back as `Recipe`s, or empty if never fetched.

    Empty is a supported way to run, exactly as an absent rate scrape is: every
    method simply keeps whatever the guides and defaults gave it. The caller
    does not have to check - `recipe_rates.apply` over nothing is a no-op.
    """
    return _recipes_from(_recipe_blob(root))


def _recipe_blob(root: Path | None = None) -> Mapping[str, Any]:
    """The raw recipes blob, or `{}` when never fetched."""
    try:
        found: Mapping[str, Any] = cache.read_blob(cache.RECIPES_BLOB_NAME, root)["data"]
    except cache.CacheMissError:
        return {}
    return found


def _recipes_from(blob: Mapping[str, Any]) -> dict[str, tuple[Recipe, ...]]:
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
    seconds = material_seconds(state, derived, world, heuristics, level_overrides=levels)
    # **Prayer is priced here because this is where the item walk is.** Its
    # rate is a bone's experience over the time to collect one, so it needs
    # exactly the closure the recipes need and would otherwise build a second
    # `_Walk` to ask the same question.
    prayed = _prayer_methods(state, derived, heuristics, levels, seconds)
    overrides = blobs.overrides
    # **The hand materials do not depend on the recipes**, so they are read
    # before the early return: a clone with no `fray recipes` cache still
    # charges the foundry for its bars.
    by_hand = hand_material_costs(overrides, seconds)
    # **Spells sit under the recipes and over nothing**, which is the one
    # ordering question this layer has. Ten of the 190 also have a `{{Recipe}}`
    # - the enchants - and that row charges the jewellery or the bolts as well
    # as the runes, so it is both larger and righter. Where both describe the
    # same thing they agree: a charge-orb cast prices at 0.6162 s/xp either way.
    by_spell = spell_material_costs(heuristics, seconds)
    if not recipes:
        return (
            replace(
                heuristics,
                computed=prayed,
                material_seconds_per_xp={**by_spell, **by_hand},
            ),
            recipe_rates.RecipeCoverage(),
        )
    pinned = frozenset(_mapping(overrides, "training"))
    computed, coverage = recipe_rates.computed_rates(
        state.chunk_info,
        derived.challenges.valid,
        recipes,
        seconds,
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
        **by_spell,
        **{
            task: rate.input_seconds / rate.experience
            for task, rate in computed.items()
            if rate.experience > 0 and rate.input_seconds > 0
        },
    }
    per_xp.update(by_hand)
    return (
        replace(
            heuristics,
            training=recipe_rates.apply(heuristics.training, computed, pinned),
            action_seconds=timed,
            computed=prayed,
            material_seconds_per_xp=per_xp,
        ),
        coverage,
    )


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

    It matters because casting *wins climbs*. On `fray` `Cast ~|varrock
    teleport|~` held 25 -> 99 at a published 38,500/hr with its 3 air, 1 fire
    and 1 law charged at nothing; charged, it is 11,807 effective and loses the
    top band. **Magic 1 -> 99 goes 339.7h -> 1,018.5h on `fray` and 396.7h ->
    1,015.4h on `verf`.** Every rune prices on both maps.
    """
    return priced_materials(heuristics.spell_costs, collect)


def hand_material_costs(
    overrides: Mapping[str, Any], collect: Callable[[str, float], float | None]
) -> dict[str, float]:
    """`material_seconds_per_xp` for the methods a `{{Recipe}}` cannot describe.

    **The one way to charge a method for what it consumes when the export does
    not say how much.** `recipe_priced` derives that figure from
    `computed_rates`, which is the only place experience-per-action and
    quantity-per-action exist together - the export carries neither (0 of its
    2,710 primary challenges state a quantity anywhere in `Items`, and its one
    experience field is a quest's one-off lump). So a method with a scraped or
    hand-entered rate and no recipe row is ranked as though its inputs were
    free, which is the documented material bias.

    This is the hand-stated half of that pair, in the file hand-stated numbers
    already live in. An entry is `{"experience": <per action>, "items":
    {<name>: <quantity>}}`; the seconds come from the same item walk a recipe's
    do, so the two cannot disagree about what a bar costs on this map.

    **The Giants' Foundry is what it was written for and is the whole of it
    today.** Its six challenges declare `Items: ["AdamantMats[+]*", ...]` -
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
                str(item): int(quantity)
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
        # **Merged, not replaced**: `recipe_priced` has already put Prayer's
        # methods in `computed`, and combat's arrive later because they
        # multiply the kill rates.
        merged = {
            **priced.computed,
            **{
                skill: (
                    ComputedMethod(
                        method=rate.source.removeprefix("combat:"),
                        xp_per_hour=rate.value,
                        match=rate.match,
                    ),
                )
                for skill, rate in rates.items()
                if rate.value > 0
            },
        }
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
    it or neither should**: this function exists because `fray estimate` and
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
    result = estimate(state, derived, world, heuristics, level_overrides=levels)
    return EstimateAnswer(result=result, scraped_rates=scraped_rates, coverage=coverage)
