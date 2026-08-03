"""Temporary skill boosts: how much a challenge's `Level` can be discounted.

Port of the boost block upstream repeats verbatim at a dozen sites
(worker.js:1210/1630/1960/2004/4591/5086/8395/8436/8539/8578 and
index.js:6437). Given `rules['Boosting']`, a challenge is allowed to be
attempted below its stated `Level` if the player can reach a boost item for
that skill, so every level comparison upstream makes is against a *boosted*
level rather than the raw one.

The pieces, all from `chunkinfo.json`'s `codeItems`:

- `boostItems[skill]` maps a boost's name to its size. A plain number is a
  flat boost (`Wild pie` -> 5 Slayer). A **string** is either the `"N%+M"`
  proportional form (`"15%+5"`) or, for `Crystal saw`, a bare `"3"` that
  never reaches the string path because the key is special-cased first.
- A boost key may name a non-item: `"Abidor Crank~npcs"`, `"Oldak~npcs"`,
  `"Altar#Edgeville Monastery~objects"`. The part after `~` is the
  `SourceIndex` category to look in; with no `~` it's `items`.
- `boostTaskBans[skill][challenge]` lists boosts that specific challenge may
  not use (only `Thieving`'s Sorceress's Garden entries in real data - you
  can't drink the sq'irkjuice you need the boost to obtain).
- `Crystal saw` is Construction-only and applies **+3 only to challenges
  whose `Items` include `Saw[+]`**; it is tracked separately from
  `best_boost` because the two clamps below treat it differently.

Faithful to two upstream quirks, because reproducing the behaviour is the
point:

- **`"4%"`-style values contribute nothing.** `"4%".split('%+')` doesn't
  split, so JS coerces `"4%"` to `NaN` and `NaN > bestBoost` is false.
  `Strength`'s `Beer` is the only real case. `_percent_boost` returns `None`
  for exactly the inputs that produce `NaN` there.
- **The two clamps differ.** `real_level` (the candidate side,
  worker.js:8464) floors the result at 1. `completed_ceiling` (the
  completed-challenge side, worker.js:8422) instead rewrites `bestBoost` to
  `Level - 1` and recomputes, which yields `1 - crystal_saw` - i.e. **-2**
  when the saw applies. They agree everywhere except a Construction
  `Saw[+]` challenge whose boost would take it below level 1.

Not modelled: `skillQuestXp` (no quest-XP state exists in this codebase), and
the `Kill X` rule's own copy of this block (worker.js:4702), whose rule is
off on real maps and whose surrounding feature is unported.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any

from fray_claude.chunkinfo import ChunkInfo
from fray_claude.sources import SourceIndex
from fray_claude.summary import _mapping

#: Upstream reads availability out of `baseChunkData`, whose keys are these.
_CATEGORY_ATTRS = ("items", "objects", "monsters", "npcs", "shops")

_CRYSTAL_SAW = "Crystal saw"
_CRYSTAL_SAW_SKILL = "Construction"
_CRYSTAL_SAW_REQUIRES = "Saw[+]"
_CRYSTAL_SAW_AMOUNT = 3

_JS_PARSE_INT = re.compile(r"^\s*[+-]?\d+")


def _parse_int_js(text: str) -> int | None:
    """`parseInt` semantics: leading whitespace and sign, digits, then stop.
    `None` stands in for `NaN`."""
    match = _JS_PARSE_INT.match(text)
    return int(match.group()) if match else None


def _percent_boost(value: str, level: float) -> int | None:
    """The `"N%+M"` proportional boost, applied twice exactly as upstream
    does (worker.js:8404-8405) - the second pass recomputes against the
    already-discounted level. `None` where JS would produce `NaN`, which is
    never greater than the running best and so contributes nothing.
    """
    parts = value.split("%+")
    if len(parts) < 2:
        return None  # JS: `parseInt(undefined)` -> NaN
    try:
        percent = float(parts[0])  # JS: `"4%" * n` -> NaN
    except ValueError:
        return None
    flat = _parse_int_js(parts[1])
    if flat is None:
        return None
    possible = math.floor(level * percent / 100 + flat)
    return math.floor((level - possible) * percent / 100 + flat)


def _available(boost: str, items: Mapping[str, Any], source_index: SourceIndex) -> bool:
    """`baseChunkData[category].hasOwnProperty(name)`, where a `~` in the
    boost key names the category and its absence means `items`.

    `items` is passed separately from `source_index` on purpose: by the time
    upstream evaluates a boost, `baseChunkData['items']` is the *seeded*
    index, including items that exist only as a valid challenge's `Output`.
    Real data depends on it - `Wild pie`, the 5-point Slayer boost the map's
    own oracle records as `"92{5}"`, is baked, not dropped, so it appears in
    `ChallengeResult.available_items` and never in `SourceIndex.items`.
    Passing the narrow index here silently yields no boost at all. The other
    categories have no such second source and come off `source_index`.
    """
    name, _, category = boost.partition("~")
    if not category:
        return name in items
    if category not in _CATEGORY_ATTRS:
        return False
    contents: Mapping[str, Any] = getattr(source_index, category)
    return name in contents


def best_boost(
    skill: str,
    name: str,
    challenge: Mapping[str, Any],
    level: float,
    *,
    rules: Mapping[str, Any],
    chunk_info: ChunkInfo,
    items: Mapping[str, Any],
    source_index: SourceIndex,
) -> tuple[int, int]:
    """`(best_boost, crystal_saw)` for one challenge, both already 0 when
    boosting doesn't apply. They are returned apart because `real_level` and
    `completed_ceiling` clamp them differently (see the module docstring).

    Returns `(0, 0)` unless `rules['Boosting']` is on, the skill has a
    `boostItems` table, and the challenge is not flagged `NoBoost`.
    """
    if rules.get("Boosting") is not True:
        return 0, 0
    # `hasOwnProperty('NoBoost')` - presence, not truthiness.
    if "NoBoost" in challenge:
        return 0, 0
    code_items = chunk_info.code_items
    table = _mapping(_mapping(code_items, "boostItems"), skill)
    if not table:
        return 0, 0
    banned = _mapping(_mapping(code_items, "boostTaskBans"), skill).get(name)
    banned_list = banned if isinstance(banned, list) else []

    best = 0
    crystal_saw = 0
    for boost, amount in table.items():
        if not _available(boost, items, source_index):
            continue
        if boost in banned_list:
            continue
        if boost == _CRYSTAL_SAW:
            # Construction-only, and only for challenges that use a saw at
            # all. Upstream checks the raw `Items` list, `Saw[+]` included.
            if skill == _CRYSTAL_SAW_SKILL:
                challenge_items = challenge.get("Items")
                if isinstance(challenge_items, list) and _CRYSTAL_SAW_REQUIRES in challenge_items:
                    crystal_saw = _CRYSTAL_SAW_AMOUNT
            continue
        if isinstance(amount, str):
            possible = _percent_boost(amount, level)
            if possible is not None and possible > best:
                best = possible
        elif isinstance(amount, (int, float)) and amount > best:
            best = int(amount)
    return best, crystal_saw


def real_level(
    skill: str,
    name: str,
    challenge: Mapping[str, Any],
    level: float,
    *,
    rules: Mapping[str, Any],
    chunk_info: ChunkInfo,
    items: Mapping[str, Any],
    source_index: SourceIndex,
) -> float:
    """The level a *candidate* challenge effectively needs (worker.js:8462):
    `Level - (bestBoost + crystalSaw)`, floored at 1."""
    best, saw = best_boost(
        skill,
        name,
        challenge,
        level,
        rules=rules,
        chunk_info=chunk_info,
        items=items,
        source_index=source_index,
    )
    return max(level - (best + saw), 1)


def completed_ceiling(
    skill: str,
    name: str,
    challenge: Mapping[str, Any],
    level: float,
    *,
    rules: Mapping[str, Any],
    chunk_info: ChunkInfo,
    items: Mapping[str, Any],
    source_index: SourceIndex,
) -> float:
    """The level a *completed* challenge proves (worker.js:8420-8424).

    Deliberately not `real_level`: upstream's clamp here rewrites `bestBoost`
    to `Level - 1` and recomputes rather than flooring the result, so a
    Construction `Saw[+]` challenge that would fall below 1 yields `1 - 3`,
    i.e. `-2`. Reproduced rather than corrected - the two sides of the same
    comparison genuinely differ upstream.
    """
    best, saw = best_boost(
        skill,
        name,
        challenge,
        level,
        rules=rules,
        chunk_info=chunk_info,
        items=items,
        source_index=source_index,
    )
    if level - (best + saw) < 1:
        best = int(level) - 1
    return level - (best + saw)
