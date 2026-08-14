"""The challenges upstream *builds* at runtime rather than reading from the
export.

`chunkpicker-chunkinfo-export.json` is not the whole challenge list. Several
of upstream's rules construct challenges while `calcChallengesWork` runs and
write them straight into `chunkInfo['challenges']` and `valids` - past
`checkChallenge` entirely, so they are valid the moment they are made. Read
the export alone and those tasks simply do not exist, with no error to say so.

**The definition goes in; the validity does not.** Upstream seeds `valids`
with the name as it writes the definition, but the definition lands in
`chunkInfo['challenges']` *before* the scan at worker.js:3673, so the
challenge is then checked like any other - and both capes are gated on a
running total this project does not compute (`QuestPointsNeeded`,
`TotalLevelNeeded`, two of `challenges._LEVEL_GATES_NOT_SUPPORTED`).
Forcing them valid here made `Quest point cape (t)` a reachable item and
`Perform the Quest point cape emote` an active Lumbridge Elite task on a map
where upstream lists neither - the oracle caught it. So the definitions are
overlaid and nothing else: the ordinary evaluation refuses the gate, and the
name lands in `ChallengeResult.unsupported`, which is this project's way of
saying "upstream has a challenge here and this tool cannot judge it" rather
than guessing either way.

The definition is what downstream needs regardless, because `other_tasks`'
grouping, the panel's `Label` and `cli/listing` all look a name back up in
the export.

Upstream gets the definition there by mutating the parsed export in place.
This module cannot: that dict is shared across processes and read-only by
this project's own rule. `ChunkInfo.with_challenges` builds a shallow overlay
instead - one merged `challenges` branch over the same 10MB of data - and
`pipeline.derive` threads the overlaid `ChunkInfo` through the run, so every
consumer that already takes one sees the injected entries with no change.
`Derived.injected` carries the definitions out to the callers that hold only
a `MapState`, which re-apply the overlay themselves.

What is here so far:

- **`Buy the ~|Max cape|~`** (worker.js:3609), `Extra`, gated on
  `rules['Skillcape']` *and* holding chunk `11063` - Mac's hut on Falador's
  rooftop. Neither cached map holds it.
- **`Buy the quest point cape*`** (worker.js:3630), `Nonskill`, gated on
  chunk `12338` alone: **no rule guards it**, and both cached maps hold that
  chunk, so this one is a task both of them were missing. Its
  `QuestPointsNeeded` is computed rather than constant - the sum of every
  `QuestPoints` in the export's `Quest` branch, which moves whenever upstream
  adds a quest.

Chunk membership is tested the way upstream tests it, with
`hasOwnProperty`: a chunk id present in the payload counts whatever its
value, and this project's decoded `unlocked` maps an id to itself rather than
to `True` anyway.

`synthesised_challenges` is the other half, for the rules that build in
*bulk* from what the map can already reach - a task per shop line, per
droptable row, per monster. Those cannot be settled before the fixed point
the way the capes can, because their input **is** the fixed point's answer:
the seeded item index. `pipeline.derive` recomputes them at the end of each
pass, re-overlays, and refuses to converge until they stop moving. That
terminates because none of them carries an `Output` - they consume what is
already reachable and add nothing to it, so the item index cannot chase its
own tail through them.

Unlike the capes these *are* re-judged, and want to be: upstream writes them
after its own scan, so they are checked on the following pass like anything
else, and their `Items` requirement is satisfied by construction. Letting the
ordinary machinery do it is both simpler and the same answer.

All eight bulk rules are ported. What is *not* ported, and shows only in
`All Droptables`, is upstream's re-keying of `dropTablesGlobal` when an item
gains or loses its `*` secondary marker (worker.js:906-1022) and the pass
that prunes emptied branches (worker.js:1112-1138); nothing here writes an
entry those would move, but a future `skillItems` route might.

(`Skilling Pets` is the odd one out and lives in `challenges.py` instead: it
builds no challenge at all, it seeds seven pet *items*. It belongs to this
family only in that the same kind of rule switch turns it on.)
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import re

from chunksim.derive import sources
from chunksim.derive.challenges import _SKILL_NAMES
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.model.summary import _mapping

#: `(chunk id, category, name)` for the two capes. Upstream writes each as a
#: literal; the shared shape is worth naming once.
_MAX_CAPE_CHUNK = "11063"
_QUEST_CAPE_CHUNK = "12338"

#: Upstream's `valids[category][name] = 'Skillcapes'`, and the `Label` the
#: `Extra` panel groups the cape under.
_SKILLCAPES = "Skillcapes"


def _total_quest_points(chunk_info: ChunkInfo) -> int:
    """Every `QuestPoints` in the export's `Quest` branch, summed.

    Upstream recomputes this on each run rather than storing it, so the cape
    tracks a growing game: adding a quest raises the bar for everyone.
    """
    total = 0
    quests = chunk_info.challenges.get("Quest")
    if not isinstance(quests, dict):
        return total
    for challenge in quests.values():
        points = challenge.get("QuestPoints") if isinstance(challenge, dict) else None
        if isinstance(points, (int, float)) and not isinstance(points, bool):
            total += int(points)
    return total


def injected_challenges(
    chunk_info: ChunkInfo, unlocked: Mapping[str, Any], rules: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    """The definitions to overlay, keyed by category then name.

    Empty on a map holding neither chunk, which is the common case and costs
    nothing - `ChunkInfo.with_challenges` returns the same object.
    """
    definitions: dict[str, dict[str, Any]] = {}

    def add(category: str, name: str, definition: dict[str, Any]) -> None:
        definitions.setdefault(category, {})[name] = definition

    if rules.get("Skillcape") is True and _MAX_CAPE_CHUNK in unlocked:
        add(
            "Extra",
            "Buy the ~|Max cape|~",
            {
                "Category": ["Skillcape"],
                "Chunks": [f"{_MAX_CAPE_CHUNK}-3"],
                "ChunksDetails": [f"{_MAX_CAPE_CHUNK}-3"],
                "Label": _SKILLCAPES,
                "NPCs": ["Mac"],
                "Output": "Max cape",
                "TotalLevelNeeded": 2376,
                "Permanent": False,
            },
        )

    if _QUEST_CAPE_CHUNK in unlocked:
        add(
            "Nonskill",
            "Buy the quest point cape*",
            {
                "Chunks": [_QUEST_CAPE_CHUNK],
                "ChunksDetails": [_QUEST_CAPE_CHUNK],
                "NPCs": ["Wise Old Man"],
                "Output": "Quest point cape (t)",
                "QuestPointsNeeded": _total_quest_points(chunk_info),
                "Permanent": False,
                "Not F2P": True,
            },
        )

    return definitions


def _shop_source(source: str) -> str:
    """`~|Bob's Brilliant Axes|~` -> `Bob's Brilliant Axes`; anything else
    unchanged. Upstream unwraps the markup for the *name* only, and leaves
    the index key it came from alone."""
    if "~|" in source and "|~" in source:
        return source.split("~|")[1].split("|~")[0]
    return source


def _all_shops(items: Mapping[str, Mapping[str, str]]) -> dict[str, dict[str, Any]]:
    """A task per (shop, item) the map can reach - port of worker.js:5071.

    The tag has to be **exactly** `shop`: an item a shop sells is tagged
    `shop`, where one that merely passes through a shop as part of a longer
    route carries a compound tag, and upstream tests equality rather than
    membership. `^^` marks an index entry that is not a real item and is
    skipped whole; a `*` in the item name is a secondary marker, dropped from
    the task name but kept in `Items` where `_compile_items` reads it.

    One item sold in four shops is four tasks, which is the point of the
    rule - 572 of them on the second cached map.
    """
    built: dict[str, dict[str, Any]] = {}
    for item, sources in items.items():
        if "^^" in item:
            continue
        for source, tag in sources.items():
            if tag != "shop":
                continue
            name = f"{_shop_source(source)}: ~|{item.replace('*', '')}|~"
            built[name] = {
                "Category": ["All Shops"],
                "Items": [item],
                "ItemsDetails": [item],
                "Label": "All Shops",
                "Permanent": False,
            }
    return built


def _nest_loot(
    chunk_info: ChunkInfo, items: Mapping[str, Mapping[str, str]], rules: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    """A task per bird-nest drop - port of worker.js:5050.

    A reachable `Bird nest (…)` has a matching `<name> loot` entry in both
    `skillItems.Nonskill` and `challenges.Nonskill`, and every row of that
    loot table becomes its own task. The `Not F2P` check reads the *loot*
    challenge rather than anything built here, so an F2P map loses the whole
    nest rather than individual rows.

    The rate goes into the name exactly as the export stores it - no
    `find_fraction` pass, unlike `All Droptables` proper, because nothing is
    multiplied here to need re-expressing. An empty quantity key reads as
    `N/A`, upstream's `(quantity || 'N/A')`.

    **The `Category` is `All Droptables`, not `All Droptables Nest`.** So on
    a map with the nest rule on and the droptable rule off, upstream builds
    these and its own category gate takes them straight back out on the next
    pass. That is reproduced by building them and letting the gate run, which
    is the same settled answer.
    """
    built: dict[str, dict[str, Any]] = {}
    loot_tables = _mapping(chunk_info.skill_items, "Nonskill")
    nonskill = _mapping(chunk_info.challenges, "Nonskill")
    f2p = rules.get("F2P") is True
    for nest in items:
        if "Bird nest (" not in nest:
            continue
        loot_key = f"{nest} loot"
        table = loot_tables.get(loot_key)
        challenge = nonskill.get(loot_key)
        if not isinstance(table, dict) or not isinstance(challenge, dict):
            continue
        if f2p and "Not F2P" in challenge:
            continue
        for drop, quantities in table.items():
            if not isinstance(quantities, dict):
                continue
            for quantity, rate in quantities.items():
                name = (
                    f"{nest.replace('[+]', '')}: ~|{drop}|~ "
                    f"({quantity or 'N/A'}) ({rate})"
                )
                built[name] = {
                    "Category": ["All Droptables"],
                    "Items": [drop],
                    "ItemsDetails": [drop],
                    "Monsters": [f"{nest}-object"],
                    "Label": "All Droptables",
                    "Permanent": False,
                }
    return built


def _slayer_task_for(monster: str, slayer: Mapping[str, Any]) -> str | None:
    """The Slayer assignment a `Kill X` task should hang off, or `None`.

    Upstream asks twice and the two questions are not the same (worker.js:4751
    then :4753): whether *any* Slayer challenge outputs this monster or names
    it case-sensitively, and then which one to link, matching
    case-insensitively and skipping the `|~ alt` duplicates. A monster that
    answers the first and not the second reaches `[0]` of an empty list -
    `undefined` - and upstream writes a `Tasks` key spelled "undefined". That
    is a bug rather than an intention, so it is not reproduced; the link is
    simply left off, which is what the `Tasks` requirement then reads as
    "nothing to wait for".
    """
    def outputs(name: str) -> bool:
        entry = slayer.get(name)
        return isinstance(entry, dict) and entry.get("Output") == monster

    if not any(outputs(name) or f"~|{monster}|~" in name for name in slayer):
        return None
    lowered = f"~|{monster.lower()}|~"
    for name in slayer:
        if (outputs(name) or lowered in name.lower()) and "|~ alt" not in name:
            return name
    return None


def _kill_x(
    chunk_info: ChunkInfo,
    monsters: Mapping[str, Any],
    rules: Mapping[str, Any],
    *,
    slayer_trainable: bool,
    slayer_has_tasks: bool,
    slayer_cap: int | None,
    passive_slayer: int | None,
    best_boost: int,
    backlog: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """A task per killable monster - port of worker.js:4718.

    Every monster the chunks hold becomes `Kill X ~|<monster>|~`, where the X
    is `rules['Kill X Amount']` at display time, not here. Three gates decide
    which monsters count:

    - **Slayer reach.** A monster that needs a Slayer level is only killable
      if Slayer is trainable and any assignment lock allows it, or a
      `passiveSkill` floor already covers the requirement. Both comparisons
      take the best Slayer boost the chunks can supply, computed at level 1
      the way upstream computes it.
    - **`Kill X Boss`**, which is a second rule rather than an amount: off,
      the boss list is excluded outright.
    - **The backlog**, checked here rather than left to the ordinary
      machinery, because a forced-valid challenge never reaches it. Both
      spellings of a `#` sub-name are tried, as everywhere the backlog is
      read.

    A `Tasks` link back to the matching Slayer assignment is added when the
    map has any Slayer validity at all, so that killing the monster reads as
    part of a slayer task rather than a free-standing goal.
    """
    slayer_monsters = chunk_info.slayer_monsters
    bosses = _mapping(chunk_info.code_items, "bossMonsters")
    boss_ok = rules.get("Kill X Boss") is True
    slayer = _mapping(chunk_info.challenges, "Slayer")
    built: dict[str, dict[str, Any]] = {}
    for monster in sorted(monsters):
        required = slayer_monsters.get(monster)
        if isinstance(required, (int, float)) and not isinstance(required, bool):
            locked_ok = slayer_trainable and (
                slayer_cap is None or required <= slayer_cap + best_boost
            )
            passive_ok = passive_slayer is not None and passive_slayer + best_boost >= required
            if not locked_ok and not passive_ok:
                continue
        if not boss_ok and monster in bosses:
            continue
        name = f"Kill X ~|{monster}|~"
        if name in backlog or f"Kill X ~|{monster.replace('#', '/')}|~" in backlog:
            continue
        entry: dict[str, Any] = {
            "Category": ["Kill X"],
            "Monsters": [monster],
            "MonstersDetails": [monster],
            "Label": "Kill X",
            "Permanent": False,
        }
        if slayer_has_tasks:
            assignment = _slayer_task_for(monster, slayer)
            if assignment is not None:
                entry["Tasks"] = {assignment: "Slayer"}
        built[name] = entry
    return built


#: The four source tags `Every Drop` walks (worker.js:4768). A tag naming
#: any of them means the item came off something killable, pickpocketable or
#: caught, which is what the rule is a checklist of.
_DROP_TAGS = ("-drop", "-Slayer", "-Thieving", "-Hunter")

#: Upstream's `dropRatesGlobal` key for a pickpocket table - an invented
#: namespace, so a Thieving NPC's loot cannot collide with a monster of the
#: same name.
_THIEVING_KEY = "[Thieving] "

#: `skillNames` plus `Nonskill`: upstream refuses to emit `All Droptables`
#: rows from a `dropTablesGlobal` key suffixed with one of these, those being
#: the `skillItems` routes rather than a real entity.
_SKILL_ROUTE_SUFFIXES = frozenset({*_SKILL_NAMES, "Nonskill"})

#: Upstream's own `Every Drop` task-name shape, used to read the item back
#: out of a stored completion.
_EVERY_DROP_NAME = re.compile(r".*: ~\|.*\|~ \(.*\)")


def _completed_drop_items(completed_extra: Mapping[str, Any]) -> set[str]:
    r"""The items already ticked off as `Every Drop` tasks.

    Upstream re-reads its own task names out of `completedChallenges['Extra']`
    to find them (`/.*: ~\|.*\|~ \(.*\)/`, then the text between the first
    pair of pipes), because the completion is stored under the *task* name and
    the rule needs the *item*. A drop ticked off any one source is not offered
    from another.
    """
    done: set[str] = set()
    for line in completed_extra:
        if not isinstance(line, str) or not _EVERY_DROP_NAME.match(line):
            continue
        parts = line.split("|")
        if len(parts) > 1:
            done.add(parts[1])
    return done


def _every_drop_source(
    source: str, tag: str, chunk_info: ChunkInfo, rules: Mapping[str, Any]
) -> tuple[str, Mapping[str, Any] | None, str | None]:
    """`(rate key, loot table to measure, real name)` for one source tag.

    Four shapes, and the key is not the source name in three of them
    (worker.js:4769/4771/4810/4851). A `Slay ` source is really its monster;
    a Thieving source is its NPC under an invented namespace; an impling is
    its jar minus the word. Only the plain drop case keeps the name it came
    with. Where a table is returned the caller has to measure it - those two
    rate namespaces are ones `gather_chunks_info` never builds.
    """
    plain = source.replace("*", "")
    if "Slay " in source:
        challenge = _mapping(chunk_info.challenges, "Slayer").get(source)
        output = challenge.get("Output") if isinstance(challenge, dict) else None
        return (output if isinstance(output, str) else plain), None, None
    if "-Thieving" in tag:
        challenge = _mapping(chunk_info.challenges, "Thieving").get(source)
        npc = challenge.get("Output") if isinstance(challenge, dict) else None
        if isinstance(npc, str):
            table = _mapping(chunk_info.skill_items, "Thieving").get(npc)
            return f"{_THIEVING_KEY}{npc}", table if isinstance(table, dict) else None, npc
    if rules.get("Every Drop Implings") is True and "-Hunter" in tag and "impling" in source:
        challenge = _mapping(chunk_info.challenges, "Hunter").get(source)
        jar = challenge.get("Output") if isinstance(challenge, dict) else None
        if isinstance(jar, str):
            table = _mapping(chunk_info.skill_items, "Hunter").get(jar)
            return jar.replace(" jar", ""), table if isinstance(table, dict) else None, jar
    return plain, None, None


def _every_drop(
    chunk_info: ChunkInfo,
    given: "SynthesisInputs",
    rules: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """A task per item per source that yields it - port of worker.js:4758.

    Where `All Shops` is one task per shop line, this is one per *drop line*:
    an item off three monsters is three tasks, each carrying that monster's
    own rate in its title. The rate is `dropRatesGlobal`'s, which for an
    ordinary monster is `SourceIndex.drop_rates` already - and for a Thieving
    NPC or an impling is a namespace upstream fills as it goes, measured here
    through `sources.loot_table_rates` so the gates stay the tested ones.

    Three things are refused, and the last is the subtle one: an item already
    ticked off under any source, an item that is itself a drop *table* name
    rather than a thing (`RareDropTable+` is not loot), and an item carrying
    `^`, upstream's marker for an index entry that is not a real item.
    """
    done = _completed_drop_items(given.completed_extra)
    rates: dict[str, Mapping[str, str]] = dict(given.drop_rates)
    drop_tables = _mapping(chunk_info.code_items, "dropTables")
    built: dict[str, dict[str, Any]] = {}
    for item in sorted(given.items):
        bare = item.replace("*", "")
        if item in done or bare in done or bare in drop_tables or "^" in bare:
            continue
        for source, tag in given.items[item].items():
            if not any(marker in tag for marker in _DROP_TAGS):
                continue
            key, table, real = _every_drop_source(source, tag, chunk_info, rules)
            if table is not None and real is not None and key not in rates:
                rates[key] = sources.loot_table_rates(
                    table,
                    entity=real,
                    chunk_info=chunk_info,
                    rules=rules,
                    backlogged_sources=given.backlogged_sources,
                )
            rate = rates.get(key, {}).get(bare)
            if rate is None:
                continue
            name = f"{key.replace('[+]', '')}: ~|{bare}|~ ({rate})"
            built[name] = {
                "Category": ["Every Drop"],
                "Items": [bare],
                "ItemsDetails": [bare],
                "Label": "Every Drop",
                "Permanent": False,
            }
    return built


#: `dropTablesGlobal`'s entity suffixes, and the export field each one is
#: read off. Upstream picks the first that the *source challenge* has
#: (worker.js:4943), never the entity itself.
_ENTITY_SUFFIXES = (("Mix", "-mix"), ("NPCs", "-npc"), ("Objects", "-object"))

#: Upstream's own `All Droptables` task-name shape as its completion parser
#: expects it - `<entity>: <something> ~|<item>|~ (<qty>) (<rate>)`.
_ALL_DROPTABLES_NAME = re.compile(r".*: .+ ~\|.*\|~ \(.*\) \(.*\)")


def _entity_suffix(challenge: Mapping[str, Any]) -> str:
    for field_name, suffix in _ENTITY_SUFFIXES:
        if field_name in challenge:
            return suffix
    return ""


def _completed_droptable_rows(completed_extra: Mapping[str, Any]) -> set[tuple[str, str, str]]:
    r"""The `(entity, item, quantity)` rows already ticked off.

    **This matches nothing on the names the rule actually builds, and that is
    upstream's state rather than a mistake here.** The parser wants
    `<entity>: <something> ~|<item>|~ …` - note the `.+` between the colon
    and the markup - while every name the emit produces goes straight from
    `: ` to `~|`. So the regex cannot fire, and a completed droptable row is
    offered again. Ported as written: guessing at the shape it was meant for
    would invent a suppression upstream does not have, and a reader finding
    this list always empty deserves to know why.
    """
    rows: set[tuple[str, str, str]] = set()
    for line in completed_extra:
        if not isinstance(line, str) or not _ALL_DROPTABLES_NAME.match(line):
            continue
        entity = line.split(":")[0]
        parts = line.split("|")
        head = line.split(" ~")[0].split(": ")
        if len(parts) > 1 and len(head) > 1:
            rows.add((entity, parts[1], head[1]))
    return rows


def _all_droptables(
    chunk_info: ChunkInfo, given: "SynthesisInputs", rules: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    """A task per drop *row* - port of worker.js:4881.

    Where `Every Drop` is one task per (source, item), this is one per
    (source, item, **quantity**): a monster dropping 1 coin and 100 coins is
    two rows, and the title carries which. That is the whole reason it needs
    `SourceIndex.drop_quantities` - `dropTablesGlobal` - where the other
    rules make do with rates.

    Ordinary monster drops are in that table already. Three families are not,
    and each is keyed under a name of its own so it cannot collide: a Slayer
    assignment's monster, a Thieving NPC under `[Thieving] ` plus whichever
    of `-mix`/`-npc`/`-object` its *source challenge* implies, and an
    impling's jar minus the word plus `-npc`. The suffix survives into the
    definition, deciding whether the row names a monster, an NPC or an
    object; it is stripped from the title.

    Upstream's own filter on which entities to emit skips a key whose suffix
    after `-` is a skill name - those come from a `skillItems` route this
    project does not build - and it is kept so that adding that route later
    cannot silently start emitting from it.
    """
    quantities: dict[str, dict[str, dict[str, str]]] = {
        entity: {item: dict(rows) for item, rows in table.items()}
        for entity, table in given.drop_quantities.items()
    }
    slayer = _mapping(chunk_info.challenges, "Slayer")
    thieving = _mapping(chunk_info.challenges, "Thieving")
    hunter = _mapping(chunk_info.challenges, "Hunter")
    skill_items = chunk_info.skill_items

    def measure(key: str, entity: str, table: Any, *, multiply: bool) -> None:
        if key in quantities or not isinstance(table, dict):
            return
        _, built = sources.loot_table_tables(
            table,
            entity=entity,
            chunk_info=chunk_info,
            rules=rules,
            backlogged_sources=given.backlogged_sources,
            multiply_quantities=multiply,
        )
        if built:
            quantities[key] = built

    for item in sorted(given.items):
        if "^" in item:
            continue
        for source, tag in given.items[item].items():
            if "Slay " in source:
                challenge = slayer.get(source)
                monster = challenge.get("Output") if isinstance(challenge, dict) else None
                if isinstance(monster, str):
                    measure(
                        monster, monster, _mapping(skill_items, "Slayer").get(monster), multiply=True
                    )
            if "-Thieving" in tag and isinstance(thieving.get(source), dict):
                challenge = thieving[source]
                npc = challenge.get("Output")
                if isinstance(npc, str):
                    key = f"{_THIEVING_KEY}{npc}{_entity_suffix(challenge)}"
                    measure(key, npc, _mapping(skill_items, "Thieving").get(npc), multiply=False)
            if "-Hunter" in tag and "impling" in source and isinstance(hunter.get(source), dict):
                jar = hunter[source].get("Output")
                if isinstance(jar, str):
                    key = f"{jar.replace(' jar', '')}-npc"
                    measure(key, jar, _mapping(skill_items, "Hunter").get(jar), multiply=False)

    done = _completed_droptable_rows(given.completed_extra)
    built: dict[str, dict[str, Any]] = {}
    for entity, table in quantities.items():
        head, _, suffix = entity.partition("-")
        if suffix and suffix in _SKILL_ROUTE_SUFFIXES:
            continue
        bare = entity
        extra: dict[str, Any] = {"Monsters": [entity], "MonsterDetails": [entity]}
        for field_name, marker in _ENTITY_SUFFIXES:
            if marker in entity:
                bare = entity.replace(marker, "")
                if marker == "-mix":
                    extra = {
                        "Monsters": [bare],
                        "MonsterDetails": [bare],
                        "NPCs": [bare],
                        "NPCsDetails": [bare],
                    }
                else:
                    extra = {
                        "Monsters": [entity],
                        "MonsterDetails": [entity],
                        field_name: [bare],
                        f"{field_name}Details": [bare],
                    }
                break
        title_entity = bare.replace("[+]", "")
        for item, rows in table.items():
            if "^" in item:
                continue
            for quantity, rate in rows.items():
                if (entity, item, quantity) in done:
                    continue
                name = f"{title_entity}: ~|{item}|~ ({quantity or 'N/A'}) ({rate})"
                built[name] = {
                    "Category": ["All Droptables"],
                    "Items": [item],
                    "ItemsDetails": [item],
                    "Label": "All Droptables",
                    "Permanent": False,
                    **extra,
                }
    return built


def forced_valid_from(
    definitions: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> dict[str, dict[str, int | str | bool]]:
    """What `calc_challenges` writes into `valid` for each synthesised
    challenge: its `Label`, which is what upstream stores
    (`valids['Extra'][name] = 'All Shops'`) and what `other_tasks` groups an
    `Extra` entry by."""
    return {
        category: {name: str(entry.get("Label", "")) for name, entry in entries.items()}
        for category, entries in definitions.items()
    }


@dataclass(frozen=True)
class SynthesisInputs:
    """Everything the bulk rules read beyond the export and the rules.

    A record rather than eight parameters, because the set grows with each
    rule ported and every one of them is threaded from the same place in
    `pipeline.derive`. All of it is one pass's answer, not the map's: `items`
    and `monsters` are the seeded indexes, `slayer_trainable` this pass's
    `checkPrimaryMethod`.
    """

    items: Mapping[str, Mapping[str, str]]
    monsters: Mapping[str, Any] = field(default_factory=dict)
    backlog: Mapping[str, Any] = field(default_factory=dict)
    drop_rates: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    drop_quantities: Mapping[str, Mapping[str, Mapping[str, str]]] = field(default_factory=dict)
    completed_extra: Mapping[str, Any] = field(default_factory=dict)
    backlogged_sources: Mapping[str, Any] = field(default_factory=dict)
    slayer_trainable: bool = False
    slayer_has_tasks: bool = False
    #: The assignment lock's level cap, or `None` for "no lock".
    slayer_cap: int | None = None
    passive_slayer: int | None = None
    best_slayer_boost: int = 0


def synthesised_challenges(
    chunk_info: ChunkInfo, given: SynthesisInputs, rules: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    """The bulk-built challenges, from one pass's seeded indexes.

    Keyed by category then name, like `injected_challenges`, and empty when
    none of the rules that build them is on - which is the common case, and
    lets `pipeline.derive` skip rebuilding its overlay entirely.
    """
    extra: dict[str, Any] = {}
    if rules.get("All Shops") is True:
        extra.update(_all_shops(given.items))
    if rules.get("All Droptables Nest") is True:
        extra.update(_nest_loot(chunk_info, given.items, rules))
    if rules.get("All Droptables") is True:
        extra.update(_all_droptables(chunk_info, given, rules))
    if rules.get("Every Drop") is True:
        extra.update(_every_drop(chunk_info, given, rules))
    if rules.get("Kill X") is True:
        extra.update(
            _kill_x(
                chunk_info,
                given.monsters,
                rules,
                slayer_trainable=given.slayer_trainable,
                slayer_has_tasks=given.slayer_has_tasks,
                slayer_cap=given.slayer_cap,
                passive_slayer=given.passive_slayer,
                best_boost=given.best_slayer_boost,
                backlog=given.backlog,
            )
        )
    return {"Extra": extra} if extra else {}
