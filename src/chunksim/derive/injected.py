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

Still outstanding: `All Droptables`, `All Droptables Nest`, `Every Drop`,
`Every Drop Implings`, `Kill X`, `Kill X Boss`, `Skilling Pets`. The last is
not a challenge at all - it seeds pet *items* - and belongs beside the
others only because the same rule switch turns it on.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

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


def synthesised_challenges(
    chunk_info: ChunkInfo, items: Mapping[str, Mapping[str, str]], rules: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    """The bulk-built challenges, from one pass's seeded item index.

    Keyed by category then name, like `injected_challenges`, and empty when
    none of the rules that build them is on - which is the common case, and
    lets `pipeline.derive` skip rebuilding its overlay entirely.
    """
    extra: dict[str, Any] = {}
    if rules.get("All Shops") is True:
        extra.update(_all_shops(items))
    if rules.get("All Droptables Nest") is True:
        extra.update(_nest_loot(chunk_info, items, rules))
    return {"Extra": extra} if extra else {}
