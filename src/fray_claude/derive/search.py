"""World-wide fuzzy search across items, monsters, NPCs, objects, shops and tasks.

Unlike `sources.py`'s `SourceIndex` (which only knows chunks you've already
unlocked), this indexes the *entire* chunkinfo export - every route by which
an item can be obtained, and every chunk an entity appears in - so a query
can answer "where would I get this" as well as "do I have this yet".

Item acquisition is spread across five routes in the export, and this module
covers all of them (verified against the real export: monster drops alone
account for 1,640 of 5,962 distinct items; `skillItems` - Slayer, Fishing,
Thieving, ... - adds 882 more that appear nowhere else; challenge `Output`
adds a further 2,347 crafted/cooked/smithed items unobtainable any other
way):

- `drops[monster][drop][quantity]` - monster kills, expanded through
  `codeItems.dropTables` when `drop` names a table rather than a literal
  item (the same expansion `sources.py` does for the unlocked case).
- `skillItems[skill][activity][drop][quantity]` - non-combat-drop skilling
  sources, entirely separate from `drops`. `activity` is *not* reliably a
  monster - for Mining it's a rock/object ("Gem rocks"), for Fishing a
  fishing spot (an NPC, oddly - "Fish shoal"), for Slayer it usually is a
  monster ("Aquanite") - so resolving its location tries Monster/NPC/Object
  in turn rather than assuming one category.
- `shopItems[shop]` - shop stock (1,385 items).
- a chunk's (or chunk section's) `Spawn` block - fixed ground spawns (357
  items); the spawn's own chunk-section *is* its location, so this route
  needs no further lookup.
- a challenge's `Output` field - crafted/cooked/smithed/produced items,
  keyed by the producing challenge rather than a place at all; "available"
  for this route means the challenge is currently valid, not that some
  chunk is unlocked.

Because `sources.py` covers only 3 of those 5 routes, **this module's
availability marking is a strict superset of `fray sources`'s**: a query can
report an item available that `fray sources` would never list. "Abyssal whip"
is the concrete case - a `skillItems.Slayer` drop appearing nowhere in
`drops`.

Entity locations (`Monster`/`NPC`/`Object`/`Shop`/`Spawn` blocks) are read
directly off `chunkinfo.json`'s `chunks`, walking both the top-level block
and every `Sections[n]` block - 505 of 2,222 chunks nest their contents
there instead (see `sections.py`).

Fuzzy matching is a small stdlib ladder (exact, prefix, substring, then
`difflib.SequenceMatcher` for typos) - no new dependency, and it resolves
real cases cleanly: "abyssal whip" and bare "whip" both find "Abyssal whip";
"rune platebdy" (typo) still finds "Rune platebody". Names are normalised
first (`~|...|~` markup and `#`/`_` variant separators stripped), since
11,614 of 14,692 challenge names carry that markup and would otherwise never
match a plain-language query.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from fray_claude.model.chunkinfo import ChunkInfo
from fray_claude.derive.pipeline import Derived
from fray_claude.model.summary import _mapping

_MARKUP = re.compile(r"~\||\|~")
_SEPARATORS = re.compile(r"[#_]")
_WHITESPACE = re.compile(r"\s+")
_MIN_FUZZY_RATIO = 0.6
_EXACT_SCORE = 3.0

_ENTITY_CATEGORIES = ("Monster", "NPC", "Object", "Shop", "Spawn")
_ENTITY_TYPES = {"monster": "Monster", "npc": "NPC", "object": "Object", "shop": "Shop"}
TYPES = ("item", "monster", "npc", "object", "shop", "task")


def normalise(name: str) -> str:
    """Strip challenge-name markup/variant separators for matching."""
    text = _MARKUP.sub("", name)
    text = _SEPARATORS.sub(" ", text)
    return _WHITESPACE.sub(" ", text).strip().lower()


@dataclass(frozen=True)
class ItemSource:
    """One way to obtain an item.

    `route` is `'drop'`, a skill name (`skillItems`), `'shop'`, `'spawn'`,
    or `'task:<category>'` for a challenge `Output`; `name` is the
    monster/activity/shop/challenge that provides it (for `'spawn'`, `name`
    is already the chunk-section location itself).
    """

    route: str
    name: str


@dataclass(frozen=True)
class WorldIndex:
    """Reverse indexes over the whole chunkinfo export, independent of any
    particular map's unlocked state. Build once per process, like
    `ChunkInfo` itself - it's a full pass over the export, though a cheap
    one (~0.03s on the real ~10MB file, on top of parsing it).
    """

    item_sources: dict[str, list[ItemSource]]
    locations: dict[str, dict[str, set[str]]]  # category -> entity name -> chunk/chunk-section ids
    chunk_names: dict[str, str]
    boss_monsters: frozenset[str]
    challenges: dict[str, dict[str, Any]]

    def entity_names(self, category: str) -> list[str]:
        return list(self.locations.get(category, {}))

    def entity_locations(self, name: str) -> list[str]:
        """Where `name` is placed, trying Monster/NPC/Object/Shop in turn -
        used to resolve a `skillItems` activity, which isn't reliably one
        category (see the module docstring).
        """
        for category in ("Monster", "NPC", "Object", "Shop"):
            locations = self.locations.get(category, {}).get(name)
            if locations:
                return sorted(locations)
        return []


def _expand_drop(drop: str, drop_tables: Mapping[str, Any]) -> list[str]:
    table = drop_tables.get(drop)
    return list(table) if isinstance(table, dict) else [drop]


def build_world_index(chunk_info: ChunkInfo) -> WorldIndex:
    """Build a `WorldIndex` from the raw chunkinfo export."""
    data = chunk_info.data
    drop_tables = _mapping(chunk_info.code_items, "dropTables")
    item_sources: dict[str, list[ItemSource]] = {}

    def add_source(item: str, source: ItemSource) -> None:
        item_sources.setdefault(item, []).append(source)

    drops = _mapping(data, "drops")
    for monster, table in drops.items():
        if not isinstance(table, dict):
            continue
        for drop in table:
            for item in _expand_drop(drop, drop_tables):
                add_source(item, ItemSource("drop", monster))

    skill_items = _mapping(data, "skillItems")
    #: What each `skillItems` activity yields, kept because a *challenge* can
    #: name one as its `Output` - see the challenge loop below.
    table_contents: dict[str, set[str]] = {}
    for skill, activities in skill_items.items():
        if not isinstance(activities, dict):
            continue
        for activity, table in activities.items():
            if not isinstance(table, dict):
                continue
            for drop in table:
                for item in _expand_drop(drop, drop_tables):
                    add_source(item, ItemSource(skill, activity))
                    table_contents.setdefault(activity, set()).add(item)

    for shop, items in chunk_info.shop_items.items():
        if not isinstance(items, dict):
            continue
        for item in items:
            add_source(item, ItemSource("shop", shop))

    locations: dict[str, dict[str, set[str]]] = {category: {} for category in _ENTITY_CATEGORIES}
    chunk_names: dict[str, str] = {}
    for chunk_id, entry in chunk_info.chunks.items():
        if not isinstance(entry, dict):
            continue
        name = entry.get("Nickname")
        if not isinstance(name, str):
            name = entry.get("Name") if isinstance(entry.get("Name"), str) else None
        if isinstance(name, str):
            chunk_names[chunk_id] = name

        blocks: list[tuple[str, Mapping[str, Any]]] = []
        sections_field = entry.get("Sections")
        if isinstance(sections_field, dict):
            blocks.extend(
                (f"{chunk_id}-{section_id}", section_entry)
                for section_id, section_entry in sections_field.items()
                if isinstance(section_entry, dict)
            )
        blocks.append((chunk_id, entry))

        for location, block in blocks:
            for category in _ENTITY_CATEGORIES:
                names = block.get(category)
                if not isinstance(names, dict):
                    continue
                for entity_name in names:
                    locations[category].setdefault(entity_name, set()).add(location)
                    if category == "Spawn":
                        add_source(entity_name, ItemSource("spawn", location))

    for category, entries in chunk_info.challenges.items():
        if not isinstance(entries, dict):
            continue
        for name, challenge in entries.items():
            if not isinstance(challenge, dict):
                continue
            output = challenge.get("Output")
            if isinstance(output, str):
                add_source(output, ItemSource(f"task:{category}", name))
                # **A challenge's `Output` is often a table, not an item**, and
                # 223 of them are: `Catch a ~|raw swordfish|~` outputs
                # `Raw swordfish loot`, which is
                # `{"Raw swordfish": "Always", "Big swordfish": "1/2500"}`.
                # Without seeding the *contents* the fish itself had no task
                # route at all - only `ItemSource("Fishing", "Raw swordfish
                # loot")`, which `_kill_hours` refuses because a table is not a
                # monster it can stand in front of. The item was therefore
                # unpriceable on a map that plainly fishes it, and
                # `estimate._route_hours` divides by the row's own chance so a
                # 1/2500 member costs 2,500 performances rather than one.
                for made in table_contents.get(output, ()):  # noqa: B007
                    add_source(made, ItemSource(f"task:{category}", name))

    boss_monsters = frozenset(_mapping(chunk_info.code_items, "bossMonsters"))

    return WorldIndex(
        item_sources=item_sources,
        locations=locations,
        chunk_names=chunk_names,
        boss_monsters=boss_monsters,
        challenges=chunk_info.challenges,
    )


def _score(normalised_query: str, candidate: str) -> float:
    normalised_candidate = normalise(candidate)
    if normalised_candidate == normalised_query:
        return _EXACT_SCORE
    if normalised_candidate.startswith(normalised_query):
        return 2.0
    if normalised_query in normalised_candidate:
        return 1.0
    ratio = SequenceMatcher(None, normalised_query, normalised_candidate).ratio()
    return ratio if ratio >= _MIN_FUZZY_RATIO else 0.0


def rank(query: str, candidates: Iterable[str], limit: int) -> list[str]:
    """Score `candidates` against `query`: exact beats prefix beats
    substring beats a typo-tolerant `SequenceMatcher` ratio. Ties break
    alphabetically, for a stable, testable order.
    """
    normalised_query = normalise(query)
    if not normalised_query:
        return []
    scored = [(_score(normalised_query, c), c) for c in candidates]
    survivors = [(score, name) for score, name in scored if score > 0]
    survivors.sort(key=lambda pair: (-pair[0], pair[1]))
    return [name for _, name in survivors[:limit]]


@dataclass(frozen=True)
class LocationHit:
    chunk_id: str
    available: bool

    def as_dict(self) -> dict[str, Any]:
        return {"chunk_id": self.chunk_id, "available": self.available}


@dataclass(frozen=True)
class SourceHit:
    route: str
    name: str
    available: bool
    locations: list[LocationHit] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "name": self.name,
            "available": self.available,
            "locations": [loc.as_dict() for loc in self.locations],
        }


@dataclass(frozen=True)
class SearchHit:
    """One search result. `detail` is type-specific:

    - `item`: `{"sources": [SourceHit.as_dict(), ...]}`
    - `monster`/`npc`/`object`/`shop`: `{"locations": [...], "provides": [item, ...]}`
      (`monster` also carries `"boss": bool`)
    - `task`: `{"category": str}`
    """

    type: str
    name: str
    available: bool
    detail: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"type": self.type, "name": self.name, "available": self.available, **self.detail}


def _location_available(
    location: str, unlocked: Mapping[str, bool], derived: Derived | None
) -> bool:
    chunk_id, sep, section_id = location.partition("-")
    if chunk_id not in unlocked:
        return False
    if not sep or derived is None:
        return True
    return bool(derived.reachable_sections.get(chunk_id, {}).get(section_id))


def _location_hits(
    locations: Iterable[str], unlocked: Mapping[str, bool], derived: Derived | None
) -> list[LocationHit]:
    return [
        LocationHit(loc, _location_available(loc, unlocked, derived)) for loc in sorted(locations)
    ]


def _source_hit(
    source: ItemSource, world: WorldIndex, unlocked: Mapping[str, bool], derived: Derived | None
) -> SourceHit:
    if source.route.startswith("task:"):
        category = source.route.split(":", 1)[1]
        available = derived is not None and source.name in derived.challenges.valid.get(
            category, {}
        )
        return SourceHit(route=source.route, name=source.name, available=available)

    if source.route == "spawn":
        location_names = [source.name]
    elif source.route == "shop":
        location_names = sorted(world.locations.get("Shop", {}).get(source.name, set()))
    elif source.route == "drop":
        location_names = sorted(world.locations.get("Monster", {}).get(source.name, set()))
    else:
        location_names = world.entity_locations(source.name)

    locations = _location_hits(location_names, unlocked, derived)
    return SourceHit(
        route=source.route,
        name=source.name,
        available=any(loc.available for loc in locations),
        locations=locations,
    )


def _item_hit(
    world: WorldIndex, name: str, unlocked: Mapping[str, bool], derived: Derived | None
) -> SearchHit:
    sources = [_source_hit(s, world, unlocked, derived) for s in world.item_sources.get(name, [])]
    return SearchHit(
        type="item",
        name=name,
        available=any(source.available for source in sources),
        detail={"sources": [source.as_dict() for source in sources]},
    )


def _provides(world: WorldIndex, entity_name: str) -> list[str]:
    return sorted(
        item
        for item, sources in world.item_sources.items()
        if any(source.name == entity_name for source in sources)
    )


def _entity_hit(
    world: WorldIndex,
    type_name: str,
    category: str,
    name: str,
    unlocked: Mapping[str, bool],
    derived: Derived | None,
) -> SearchHit:
    locations = _location_hits(world.locations.get(category, {}).get(name, set()), unlocked, derived)
    detail: dict[str, Any] = {
        "locations": [loc.as_dict() for loc in locations],
        "provides": _provides(world, name),
    }
    if type_name == "monster":
        detail["boss"] = name in world.boss_monsters
    return SearchHit(
        type=type_name,
        name=name,
        available=any(loc.available for loc in locations),
        detail=detail,
    )


def _task_hit(category: str, name: str, derived: Derived | None) -> SearchHit:
    available = derived is not None and name in derived.challenges.valid.get(category, {})
    return SearchHit(type="task", name=name, available=available, detail={"category": category})


def search(
    world: WorldIndex,
    query: str,
    *,
    unlocked: Mapping[str, bool] | None = None,
    derived: Derived | None = None,
    types: Iterable[str] | None = None,
    limit: int = 10,
) -> list[SearchHit]:
    """Rank `query` across the requested `types` (default: all of `TYPES`)
    and attach availability/location detail.

    Pass `unlocked`/`derived` (the current map's decoded chunk-id set and
    `pipeline.derive` output) to mark results available/locked against that
    state; omit both for a purely static lookup, where every hit reports
    unavailable.

    If `query` is an exact name match (case-insensitive, markup-normalised)
    for something in any requested type, only exact matches are returned -
    e.g. querying "Abyssal whip" suppresses fuzzy neighbours like "Abyssal
    whip ornament kit" that would otherwise also survive.
    """
    wanted = frozenset(types) if types is not None else frozenset(TYPES)
    unlocked = unlocked or {}
    normalised_query = normalise(query)
    if not normalised_query:
        return []

    candidates: list[tuple[float, str, str]] = []  # (score, type, name)
    if "item" in wanted:
        candidates.extend(
            (_score(normalised_query, name), "item", name) for name in world.item_sources
        )
    for type_name, category in _ENTITY_TYPES.items():
        if type_name not in wanted:
            continue
        candidates.extend(
            (_score(normalised_query, name), type_name, name)
            for name in world.locations.get(category, {})
        )
    if "task" in wanted:
        candidates.extend(
            (_score(normalised_query, name), "task", f"{category}\0{name}")
            for category, entries in world.challenges.items()
            if isinstance(entries, dict)
            for name in entries
        )

    survivors = [(score, type_name, name) for score, type_name, name in candidates if score > 0]
    if any(score == _EXACT_SCORE for score, _, _ in survivors):
        survivors = [triple for triple in survivors if triple[0] == _EXACT_SCORE]
    survivors.sort(key=lambda triple: (-triple[0], triple[1], triple[2]))

    hits: list[SearchHit] = []
    for _, type_name, name in survivors[:limit]:
        if type_name == "item":
            hits.append(_item_hit(world, name, unlocked, derived))
        elif type_name == "task":
            category, _, task_name = name.partition("\0")
            hits.append(_task_hit(category, task_name, derived))
        else:
            hits.append(_entity_hit(world, type_name, _ENTITY_TYPES[type_name], name, unlocked, derived))
    return hits
