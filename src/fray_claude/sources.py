"""Which items, objects, monsters, NPCs and shops the unlocked chunks make available.

Port of `gatherChunksInfo` (worker.js): for each unlocked chunk (and, within
it, each *reachable* section - see `sections.py`), record the objects/NPCs/
shops/monsters directly present, the items obtainable from monster drops
(subject to the `Rare Drop`/`RDT`/`Boss`/`Skiller`/F2P-adjacent rule gates
and the `Rare Drop Amount`/`Secondary Primary Amount` thresholds), and items
buyable from an accessible shop.

A monster with no `drops` entry falls back to its `skillItems.Slayer` entry
(e.g. `Abyssal demon` has no `drops` table - `Abyssal whip` only exists via
`skillItems.Slayer.'Abyssal demon'`), gated by a simplified Slayer-level
check rather than upstream's full `isSlayerValid` - see
`_slayer_skill_items_for`'s docstring for why the full version (which needs
challenge-validity state) can't be expressed in this one-directional
pipeline. Non-Slayer `skillItems` categories (Mining, Fishing, Thieving, ...)
are not ported: upstream resolves those the same lazy, per-queried-item way
inside `calcChallengesWork` rather than in `gatherChunksInfo` itself, and
only Slayer's is needed for `Items` requirements and `bis.py`'s equipment
candidates seen so far.

Two pieces of upstream `gatherChunksInfo` are deliberately not ported here,
each guarded so an affected map raises loudly instead of silently producing
an incomplete index:

- The `KeyItem Bosses` pass (worker.js:9269-9357): a secondary rate-boosting
  heuristic for bosses whose drop requires owning a set of "key" items first.
  A distinct, self-contained sub-algorithm from the rest of this module.
- `codeItems.dropTables`' quantity-keyed side table (`dropTablesGlobal`,
  upstream's `calcedQuantity`): only consumed by the dynamic "Every Drop"/
  "All Droptables" challenge synthesis, which is `challenges.py`'s job (that
  synthesis lives in `calcChallengesWork`, not `gatherChunksInfo`) - not
  needed for ordinary item/object/monster/npc/shop availability.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fray_claude.chunkinfo import ChunkInfo
from fray_claude.rates import (
    build_rare_drop_num,
    build_secondary_primary_num,
    find_fraction,
    looks_non_numeric,
    parse_ratio,
    secondary_primary_denominator,
)
from fray_claude.summary import _mapping

_RDT_FAMILY = frozenset({"RareDropTable+", "GemDropTable+", "GemDropTableLegends+"})
_MANUAL_SOURCE = "Manually Added*"


@dataclass(frozen=True)
class SourceIndex:
    """What the unlocked (and reachable) chunks make available.

    Each of `items`/`objects`/`monsters`/`npcs`/`shops` maps the thing's name
    to `{source: tag}`; for `objects`/`monsters`/`npcs`/`shops` the tag is
    always `True` (mere presence), while `items` tags carry how it's
    obtained (`'primary-drop'`, `'secondary-drop'`, `'shop'`,
    `'primary-spawn'`, `'secondary-spawn'`, `'primary-Nonskill'`,
    `'secondary-Nonskill'`) since some challenges care which.
    """

    items: dict[str, dict[str, str]]
    objects: dict[str, dict[str, bool]]
    monsters: dict[str, dict[str, bool]]
    npcs: dict[str, dict[str, bool]]
    shops: dict[str, dict[str, bool]]
    drop_rates: dict[str, dict[str, str]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "items": self.items,
            "objects": self.objects,
            "monsters": self.monsters,
            "npcs": self.npcs,
            "shops": self.shops,
            "drop_rates": self.drop_rates,
        }

    def category(self, name: str) -> dict[str, dict[str, Any]]:
        """One of `CATEGORIES` by name, for `fray sources <category>`."""
        if name not in CATEGORIES:
            raise ValueError(f"unknown source category: {name!r} (expected one of {CATEGORIES})")
        return dict(getattr(self, name))


#: The listable branches of a `SourceIndex`, in the order `fray sources` reports them.
CATEGORIES = ("items", "objects", "monsters", "npcs", "shops")


def _apply_drop_rate_overrides(
    drops: Mapping[str, Any],
    chunk_info: ChunkInfo,
    chunk_ids: Mapping[str, bool],
    reachable_sections: Mapping[str, Mapping[str, bool]],
) -> dict[str, Any]:
    """Port of the `droprateOverrides` pass (worker.js:8806-8817).

    A required chunk reference without a `-section` suffix can never be
    satisfied - `unlockedSections[chunk][undefined]` is always falsy in
    JS - so such an override always falls back to `OldRate`. Reproduced,
    not fixed.
    """
    overrides = _mapping(chunk_info.code_items, "droprateOverrides")
    result: dict[str, Any] = {
        monster: dict(monster_drops) if isinstance(monster_drops, dict) else monster_drops
        for monster, monster_drops in drops.items()
    }
    for monster, monster_overrides in overrides.items():
        if not isinstance(monster_overrides, dict):
            continue
        monster_drops = result.setdefault(monster, {})
        if not isinstance(monster_drops, dict):
            continue
        for drop, override_list in monster_overrides.items():
            if not isinstance(override_list, list):
                continue
            for override in override_list:
                if not isinstance(override, dict):
                    continue
                use_new_rate = True
                required_chunks = override.get("Chunks")
                if isinstance(required_chunks, list):
                    for chunk_ref in required_chunks:
                        if not isinstance(chunk_ref, str):
                            use_new_rate = False
                            continue
                        chunk_id, sep, section_id = chunk_ref.partition("-")
                        if not sep:
                            use_new_rate = False
                            continue
                        if chunk_id not in chunk_ids or not reachable_sections.get(
                            chunk_id, {}
                        ).get(section_id):
                            use_new_rate = False
                monster_drops[drop] = override.get("NewRate" if use_new_rate else "OldRate")
    return result


@dataclass(frozen=True)
class _Settings:
    """Rule-derived scalars threaded through the drop-resolution helpers."""

    rare_drop: bool
    rdt: bool
    boss: bool
    rare_drop_num: float
    secondary_primary_num: float
    secondary_primary_denominator: int


def _settings(rules: Mapping[str, Any]) -> _Settings:
    return _Settings(
        rare_drop=rules.get("Rare Drop") is True,
        rdt=rules.get("RDT") is True,
        boss=rules.get("Boss") is True,
        rare_drop_num=build_rare_drop_num(str(rules.get("Rare Drop Amount", "0"))),
        secondary_primary_num=build_secondary_primary_num(
            str(rules.get("Secondary Primary Amount", "1"))
        ),
        secondary_primary_denominator=secondary_primary_denominator(
            str(rules.get("Secondary Primary Amount", "1"))
        ),
    )


def _is_backlogged(backlogged: Mapping[str, Any], category: str, name: str) -> bool:
    bucket = backlogged.get(category)
    return isinstance(bucket, dict) and bucket.get(name) is True


def _passes_boss_gate(settings: _Settings, boss_monsters: Mapping[str, Any], monster: str) -> bool:
    return settings.boss or monster not in boss_monsters


def _classify_and_record(
    *, items: dict[str, dict[str, str]], item: str, monster: str, is_primary: bool
) -> None:
    """`items[item][monster] = 'primary-drop'` unless already set, else the
    existing tag is preserved if this call would only downgrade to
    'secondary-drop' - port of `else if (!items[item][monster])`.
    """
    bucket = items.setdefault(item, {})
    if is_primary:
        bucket[monster] = "primary-drop"
    elif monster not in bucket:
        bucket[monster] = "secondary-drop"


def _record_drop_rate(
    *, drop_rates: dict[str, dict[str, str]], monster: str, item: str, rate: float, drop_name: str
) -> None:
    drop_rates.setdefault(monster, {})[item] = find_fraction(
        rate, "GeneralSeedDropTable" in drop_name
    )


def _expand_drop_table(
    *,
    monster: str,
    drop: str,
    monster_rate_raw: str,
    table: Mapping[str, Any],
    items: dict[str, dict[str, str]],
    drop_rates: dict[str, dict[str, str]],
    settings: _Settings,
    boss_monsters: Mapping[str, Any],
    backlogged: Mapping[str, Any],
) -> None:
    """Port of the `Object.keys(dropTables[drop]).forEach((item) => ...)` block
    (e.g. worker.js:8817-8862): expand a drop TABLE into the items it can
    produce, each independently rate-checked against `monster_rate * item_rate`.
    """
    monster_rate = parse_ratio(monster_rate_raw)
    for item, table_entry_raw in table.items():
        if not isinstance(table_entry_raw, str):
            continue
        table_rate_raw = table_entry_raw.partition("@")[0]
        table_rate = parse_ratio(table_rate_raw)
        combined_rate = monster_rate * table_rate
        passes_threshold = (
            settings.rare_drop
            or math.isnan(monster_rate)
            or combined_rate > settings.rare_drop_num
        )
        if not (
            passes_threshold
            and _passes_boss_gate(settings, boss_monsters, monster)
            and not _is_backlogged(backlogged, "items", item)
        ):
            continue
        is_primary = (
            (monster_rate_raw == "Always" and table_rate_raw == "Always")
            or (
                settings.secondary_primary_denominator > 50
                and (looks_non_numeric(monster_rate_raw) or looks_non_numeric(table_rate_raw))
            )
            or (combined_rate >= settings.secondary_primary_num)
        )
        _classify_and_record(items=items, item=item, monster=monster, is_primary=is_primary)
        _record_drop_rate(
            drop_rates=drop_rates, monster=monster, item=item, rate=combined_rate, drop_name=drop
        )


def _add_single_drop_item(
    *,
    monster: str,
    drop: str,
    monster_rate_raw: str,
    items: dict[str, dict[str, str]],
    drop_rates: dict[str, dict[str, str]],
    settings: _Settings,
) -> None:
    """Port of the `else if (...)` single-item fallback (e.g. worker.js:8864-
    8880): `drop` itself (not a drop-table name) becomes the item."""
    monster_rate = parse_ratio(monster_rate_raw)
    is_primary = (
        monster_rate_raw == "Always"
        or (settings.secondary_primary_denominator > 50 and looks_non_numeric(monster_rate_raw))
        or ("/" not in monster_rate_raw.replace("~", "") and settings.secondary_primary_num < 1)
        or ("/" in monster_rate_raw.replace("~", "") and monster_rate >= settings.secondary_primary_num)
    )
    _classify_and_record(items=items, item=drop, monster=monster, is_primary=is_primary)
    _record_drop_rate(
        drop_rates=drop_rates, monster=monster, item=drop, rate=monster_rate, drop_name=drop
    )


def _resolve_monster_drop(
    *,
    monster: str,
    drop: str,
    monster_rate_raw: str,
    drop_tables: Mapping[str, Any],
    items: dict[str, dict[str, str]],
    drop_rates: dict[str, dict[str, str]],
    settings: _Settings,
    boss_monsters: Mapping[str, Any],
    backlogged: Mapping[str, Any],
) -> None:
    """Port of the repeated per-drop dispatch (e.g. worker.js:8815-8899):
    a drop is either a drop TABLE (expand it) or a literal item (the drop
    name itself), with the two RDT-gated branches upstream keeps as
    separate `if` statements - see the module docstring's note on
    `GemDropTableLegends+`, the one case where both branches can fire.
    """
    table = drop_tables.get(drop)
    has_table = isinstance(table, dict)
    is_rdt_family = drop in _RDT_FAMILY

    table_branch = has_table and (not is_rdt_family or settings.rdt) and drop != "GemDropTableLegends+"
    if table_branch:
        _expand_drop_table(
            monster=monster,
            drop=drop,
            monster_rate_raw=monster_rate_raw,
            table=table,  # type: ignore[arg-type]
            items=items,
            drop_rates=drop_rates,
            settings=settings,
            boss_monsters=boss_monsters,
            backlogged=backlogged,
        )
    else:
        monster_rate = parse_ratio(monster_rate_raw)
        passes_threshold = (
            settings.rare_drop or math.isnan(monster_rate) or monster_rate > settings.rare_drop_num
        )
        if (
            passes_threshold
            and _passes_boss_gate(settings, boss_monsters, monster)
            and not _is_backlogged(backlogged, "items", drop)
        ):
            _add_single_drop_item(
                monster=monster,
                drop=drop,
                monster_rate_raw=monster_rate_raw,
                items=items,
                drop_rates=drop_rates,
                settings=settings,
            )

    if has_table and is_rdt_family and settings.rdt:
        _expand_drop_table(
            monster=monster,
            drop=drop,
            monster_rate_raw=monster_rate_raw,
            table=table,  # type: ignore[arg-type]
            items=items,
            drop_rates=drop_rates,
            settings=settings,
            boss_monsters=boss_monsters,
            backlogged=backlogged,
        )


def _slayer_skill_items_for(
    monster: str,
    skill_items_slayer: Mapping[str, Any],
    slayer_monsters: Mapping[str, Any],
    max_skill: Mapping[str, int],
) -> Mapping[str, Any] | None:
    """Port of the `skillItems['Slayer']` fallback used when a monster has no
    `drops` entry (e.g. worker.js:986-999: `Abyssal demon` has no `drops`
    table, only `skillItems.Slayer.'Abyssal demon'`, which is where
    `Abyssal whip` comes from).

    Simplified vs. upstream's `isSlayerValid`: gated only on the monster's
    required Slayer level (`slayerMonsters`) against `max_skill['Slayer']`,
    when both are present. Upstream additionally requires `checkPrimaryMethod`
    ("is Slayer trainable at all") and, for a slayer-locked monster, a live
    slayer assignment (`slayerLocked`) plus that monster's own Slayer task
    already being valid - a genuine circularity (item availability depending
    on challenge validity) that this project's one-directional
    sources -> challenges pipeline can't express, so it isn't modelled here.
    """
    table = skill_items_slayer.get(monster)
    if not isinstance(table, dict):
        return None
    required_level = slayer_monsters.get(monster)
    if isinstance(required_level, (int, float)) and "Slayer" in max_skill:
        if required_level > max_skill["Slayer"]:
            return None
    return table


def _resolve_monster(
    *,
    monster: str,
    drops: Mapping[str, Any],
    drop_tables: Mapping[str, Any],
    items: dict[str, dict[str, str]],
    monsters: dict[str, dict[str, bool]],
    drop_rates: dict[str, dict[str, str]],
    source: str,
    settings: _Settings,
    rules: Mapping[str, Any],
    boss_monsters: Mapping[str, Any],
    backlogged: Mapping[str, Any],
    skill_items_slayer: Mapping[str, Any],
    slayer_monsters: Mapping[str, Any],
    max_skill: Mapping[str, int],
) -> None:
    """Record `monster` as present at `source`, and (unless `Skiller` is on,
    it's backlogged, or it has no known drops) resolve every drop it can
    yield into `items`. A monster absent from `drops` falls back to its
    `skillItems.Slayer` entry, if any - see `_slayer_skill_items_for`.
    """
    if not _is_backlogged(backlogged, "monsters", monster):
        monsters.setdefault(monster, {})[source] = True

    monster_drops = drops.get(monster)
    if not isinstance(monster_drops, dict):
        monster_drops = _slayer_skill_items_for(
            monster, skill_items_slayer, slayer_monsters, max_skill
        )
    if (
        rules.get("Skiller") is True
        or not isinstance(monster_drops, dict)
        or _is_backlogged(backlogged, "monsters", monster)
    ):
        return
    for drop, quantities in monster_drops.items():
        if not isinstance(quantities, dict):
            continue
        for rate_raw in quantities.values():
            if not isinstance(rate_raw, str):
                continue
            _resolve_monster_drop(
                monster=monster,
                drop=drop,
                monster_rate_raw=rate_raw,
                drop_tables=drop_tables,
                items=items,
                drop_rates=drop_rates,
                settings=settings,
                boss_monsters=boss_monsters,
                backlogged=backlogged,
            )


def _task_unlocked(
    task_unlocks: Mapping[str, Any],
    branch: str,
    name: str,
    source: str,
    valid_tasks: Mapping[str, Mapping[str, Any]],
) -> bool:
    """Port of the `taskUnlocks` gate (worker.js:2155+, upstream's
    `shouldDelete` pass): an entity present in a chunk can still be locked
    behind completing specific challenges *at that location*.

    `taskUnlocks[branch][name]` is keyed by location - a chunk id, a
    `chunk-section`, or a named area - each mapping to a list of
    `{task name: task skill}` that must all be valid. Real examples: the
    `Sir Tiffy Cashien (The Slug Menace)` shop needs that quest before it
    sells Proselyte armour, `White Knight Armoury` needs `Wanted!`, and
    `Crazy archaeologist`/`Lava dragon` are gated `F2P Only`. Ignoring this
    made every such source unconditionally available.

    Only the entity branches (`Monsters`/`NPCs`/`Objects`/`Shops`/`Spawns`)
    are checked here; `Items` has a different, flat shape and is applied by
    `bis.py`'s `_task_unlocks_ok` against equipment candidates.
    """
    locations = _mapping(task_unlocks, branch).get(name)
    if not isinstance(locations, dict):
        return True
    required = locations.get(source)
    if not isinstance(required, list):
        return True
    for entry in required:
        if not isinstance(entry, dict):
            continue
        for task_name, task_skill in entry.items():
            if not isinstance(task_skill, str):
                continue
            if task_name not in valid_tasks.get(task_skill, {}):
                return False
    return True


def _add_shop_items(
    *,
    shop: str,
    shop_items: Mapping[str, Any],
    items: dict[str, dict[str, str]],
    minigame_shops: Mapping[str, Any],
    rules: Mapping[str, Any],
    backlogged: Mapping[str, Any],
) -> None:
    items_for_shop = shop_items.get(shop)
    if not isinstance(items_for_shop, dict) or _is_backlogged(backlogged, "shops", shop):
        return
    minigame_only = shop in minigame_shops
    for item in items_for_shop:
        if (not minigame_only or rules.get("Minigame") is True) and not _is_backlogged(
            backlogged, "items", item
        ):
            items.setdefault(item, {})[shop] = "shop"


def gather_chunks_info(
    chunk_ids: Mapping[str, bool],
    reachable_sections: Mapping[str, Mapping[str, bool]],
    chunk_info: ChunkInfo,
    *,
    rules: Mapping[str, Any],
    backlogged_sources: Mapping[str, Any] | None = None,
    manual_monsters: Mapping[str, Any] | None = None,
    manual_equipment: Mapping[str, Any] | None = None,
    max_skill: Mapping[str, int] | None = None,
    valid_tasks: Mapping[str, Mapping[str, Any]] | None = None,
) -> SourceIndex:
    """Port of `gatherChunksInfo`: what the unlocked chunks make available.

    `chunk_ids` should already be expanded via `sections.expand_chunk_areas`;
    `reachable_sections` is `sections.unlocked_sections`'s output.
    """
    if rules.get("KeyItem Bosses") is True:
        raise NotImplementedError(
            "the 'KeyItem Bosses' rate-boosting pass is not ported; "
            "gather_chunks_info's results would be incomplete under this rule"
        )

    backlogged = backlogged_sources or {}
    manual_monsters = manual_monsters or {}
    max_skill = max_skill or {}
    settings = _settings(rules)
    boss_monsters = _mapping(chunk_info.code_items, "bossMonsters")
    minigame_shops = _mapping(chunk_info.code_items, "minigameShops")
    shop_items = chunk_info.shop_items
    drop_tables = _mapping(chunk_info.code_items, "dropTables")
    drops = _apply_drop_rate_overrides(chunk_info.drops, chunk_info, chunk_ids, reachable_sections)
    skill_items_slayer = _mapping(chunk_info.skill_items, "Slayer")
    slayer_monsters = chunk_info.slayer_monsters
    task_unlocks = _mapping(chunk_info.data, "taskUnlocks")
    valid_tasks = valid_tasks or {}

    items: dict[str, dict[str, str]] = {}
    objects: dict[str, dict[str, bool]] = {}
    monsters: dict[str, dict[str, bool]] = {}
    npcs: dict[str, dict[str, bool]] = {}
    shops: dict[str, dict[str, bool]] = {}
    drop_rates: dict[str, dict[str, str]] = {}

    for item in manual_equipment or {}:
        items.setdefault(item, {})["Manually Added Equipment"] = "secondary-drop"

    for chunk_id in chunk_ids:
        entry = chunk_info.chunk(chunk_id)
        if not entry or (chunk_id == "Puro-Puro" and rules.get("Puro-Puro") is not True):
            continue

        sections_field = entry.get("Sections")
        if isinstance(sections_field, dict):
            reachable_here = reachable_sections.get(chunk_id, {})
            for section_id, section_entry in sections_field.items():
                if not reachable_here.get(section_id) or not isinstance(section_entry, dict):
                    continue
                source = f"{chunk_id}-{section_id}"
                for monster in _mapping(section_entry, "Monster"):
                    if not _task_unlocked(task_unlocks, "Monsters", monster, source, valid_tasks):
                        continue
                    _resolve_monster(
                        monster=monster,
                        drops=drops,
                        drop_tables=drop_tables,
                        items=items,
                        monsters=monsters,
                        drop_rates=drop_rates,
                        source=source,
                        settings=settings,
                        rules=rules,
                        boss_monsters=boss_monsters,
                        backlogged=backlogged,
                        skill_items_slayer=skill_items_slayer,
                        slayer_monsters=slayer_monsters,
                        max_skill=max_skill,
                    )
                for shop in _mapping(section_entry, "Shop"):
                    if not _task_unlocked(task_unlocks, "Shops", shop, source, valid_tasks):
                        continue
                    _add_shop_items(
                        shop=shop,
                        shop_items=shop_items,
                        items=items,
                        minigame_shops=minigame_shops,
                        rules=rules,
                        backlogged=backlogged,
                    )
                    if not _is_backlogged(backlogged, "shops", shop):
                        shops.setdefault(shop, {})[source] = True
                for spawn in _mapping(section_entry, "Spawn"):
                    if not _is_backlogged(backlogged, "items", spawn) and _task_unlocked(
                        task_unlocks, "Spawns", spawn, source, valid_tasks
                    ):
                        tag = "primary-spawn" if rules.get("Primary Spawns") is True else "secondary-spawn"
                        items.setdefault(spawn, {})[source] = tag
                for obj in _mapping(section_entry, "Object"):
                    if not _is_backlogged(backlogged, "objects", obj) and _task_unlocked(
                        task_unlocks, "Objects", obj, source, valid_tasks
                    ):
                        objects.setdefault(obj, {})[source] = True
                for npc in _mapping(section_entry, "NPC"):
                    if not _is_backlogged(backlogged, "npcs", npc) and _task_unlocked(
                        task_unlocks, "NPCs", npc, source, valid_tasks
                    ):
                        npcs.setdefault(npc, {})[source] = True

        for monster in _mapping(entry, "Monster"):
            if not _task_unlocked(task_unlocks, "Monsters", monster, chunk_id, valid_tasks):
                continue
            _resolve_monster(
                monster=monster,
                drops=drops,
                drop_tables=drop_tables,
                items=items,
                monsters=monsters,
                drop_rates=drop_rates,
                source=chunk_id,
                settings=settings,
                rules=rules,
                boss_monsters=boss_monsters,
                backlogged=backlogged,
                skill_items_slayer=skill_items_slayer,
                slayer_monsters=slayer_monsters,
                max_skill=max_skill,
            )
        for shop in _mapping(entry, "Shop"):
            if not _task_unlocked(task_unlocks, "Shops", shop, chunk_id, valid_tasks):
                continue
            _add_shop_items(
                shop=shop,
                shop_items=shop_items,
                items=items,
                minigame_shops=minigame_shops,
                rules=rules,
                backlogged=backlogged,
            )
            if not _is_backlogged(backlogged, "shops", shop):
                shops.setdefault(shop, {})[chunk_id] = True
        for spawn in _mapping(entry, "Spawn"):
            if not _is_backlogged(backlogged, "items", spawn) and _task_unlocked(
                task_unlocks, "Spawns", spawn, chunk_id, valid_tasks
            ):
                tag = "primary-spawn" if rules.get("Primary Spawns") is True else "secondary-spawn"
                items.setdefault(spawn, {})[chunk_id] = tag
        for obj in _mapping(entry, "Object"):
            if not _is_backlogged(backlogged, "objects", obj) and _task_unlocked(
                task_unlocks, "Objects", obj, chunk_id, valid_tasks
            ):
                objects.setdefault(obj, {})[chunk_id] = True
        for npc in _mapping(entry, "NPC"):
            if not _is_backlogged(backlogged, "npcs", npc) and _task_unlocked(
                task_unlocks, "NPCs", npc, chunk_id, valid_tasks
            ):
                npcs.setdefault(npc, {})[chunk_id] = True

    manual_monster_items = manual_monsters.get("Items")
    if isinstance(manual_monster_items, dict):
        for item, is_primary in manual_monster_items.items():
            if not _is_backlogged(backlogged, "items", item):
                tag = "primary-Nonskill" if is_primary else "secondary-Nonskill"
                items.setdefault(item, {})[_MANUAL_SOURCE] = tag

    manual_monster_names = manual_monsters.get("Monsters")
    if isinstance(manual_monster_names, dict):
        for monster in manual_monster_names:
            _resolve_monster(
                monster=monster,
                drops=drops,
                drop_tables=drop_tables,
                items=items,
                monsters=monsters,
                drop_rates=drop_rates,
                source=_MANUAL_SOURCE,
                settings=settings,
                rules=rules,
                boss_monsters=boss_monsters,
                backlogged=backlogged,
                skill_items_slayer=skill_items_slayer,
                slayer_monsters=slayer_monsters,
                max_skill=max_skill,
            )

    manual_npcs = manual_monsters.get("NPCs")
    if isinstance(manual_npcs, dict):
        for npc in manual_npcs:
            if not _is_backlogged(backlogged, "npcs", npc):
                npcs.setdefault(npc, {})[_MANUAL_SOURCE] = True

    manual_objects = manual_monsters.get("Objects")
    if isinstance(manual_objects, dict):
        for obj in manual_objects:
            if not _is_backlogged(backlogged, "objects", obj):
                objects.setdefault(obj, {})[_MANUAL_SOURCE] = True

    manual_shops = manual_monsters.get("Shops")
    if isinstance(manual_shops, dict):
        for shop in manual_shops:
            if not _is_backlogged(backlogged, "shops", shop):
                shops.setdefault(shop, {})[_MANUAL_SOURCE] = True
                _add_shop_items(
                    shop=shop,
                    shop_items=shop_items,
                    items=items,
                    minigame_shops=minigame_shops,
                    rules=rules,
                    backlogged=backlogged,
                )

    return SourceIndex(
        items=items,
        objects=objects,
        monsters=monsters,
        npcs=npcs,
        shops=shops,
        drop_rates=drop_rates,
    )
