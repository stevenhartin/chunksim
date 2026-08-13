"""What an override *path* means, as opposed to where it is stored.

`costing/estimate.py` records which entries a priced number was read off, as
paths into the override file (`monsters/Abyssal demon`). This module is what
turns one of those back into something a person can look at and change: which
layer each value came from, what the layers underneath say, and whether a
proposed replacement is allowed.

**Two files, and which one a write goes to is the caller's decision, not
this module's.** `heuristics/overrides.json` is checked in and applies to
every map; `cache/overrides/<map_id>.json` belongs to one. Both are ordinary
merged config (`heuristics.CONFIG_BRANCHES`), so the same path addresses the
same thing in either, and `resolve` reports all four layers at once - a value
you cannot see being overridden is a number that looks wrong for no reason.

**Refuse rather than coerce**, following `gui/settings.py`: a path that is not
a known branch, or a value that is not finite, is rejected outright rather
than clamped or dropped. The estimator's whole stance is that it would rather
say nothing than say something plausible, and a knob quietly rounded to
something else would be exactly that failure moved into the editor.

**A leaf is a number; a branch is a group.** The file's shapes are not
uniform - `currencies/Coins` is a bare float, `monsters/Goblin` is an object
with a `value`, `slayer/Duradel/Abyssal demons` is an object with five - so
`NUMERIC_FIELD` says, per branch, which field carries the number a person
would edit. `None` means the branch's leaves *are* numbers. A path naming a
branch rather than a leaf (`slayer/Duradel`, which is what the superior
shared table reads) resolves to everything under it, and is shown rather than
edited: the number came off the whole table, so there is no single entry to
change.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from fray_claude.costing.heuristics import CONFIG_BRANCHES

#: Which field of a branch's leaf carries the number worth editing, or `None`
#: where the leaf is the number. Branches absent from here are readable and
#: not editable - `monster_stats` and `spell_costs` are scraped structure
#: rather than a figure someone would argue with, and `training` and `quests`
#: belong to the skilling and quest buckets, which do not record knobs yet.
NUMERIC_FIELD: Mapping[str, str | None] = {
    "actions": None,
    "currencies": None,
    "rarities": None,
    "monsters": "value",
    "shops": "price",
    "slayer": "kills_per_hour",
    "superiors": "spawn_rate",
}

#: Where a write may go. `site` is `heuristics/overrides.json`, which is
#: checked in and moves every map; `map` is the open map's own file.
SCOPES: tuple[str, ...] = ("site", "map")

#: The layers a value can come from, weakest first. Named rather than
#: numbered so a payload says `"scraped"` rather than `1`, which is the same
#: reason `Rate.source` is a string.
#:
#: **There is no `default` layer, and that is a fact about the file rather
#: than an omission here.** A default is applied per field inside
#: `heuristics.load` and `Heuristics`' own accessors - `kills_per_hour` falls
#: back to `DEFAULT_KPH` by what kind of monster it is - so there is no
#: config-shaped dictionary of them to lay underneath. A knob with no value
#: at any of these three is one the estimator is answering from a default,
#: which is what an empty stack means and what the panel says.
LAYERS: tuple[str, ...] = ("scraped", "site", "map")


class KnobError(ValueError):
    """A path or value this module refuses. Carries what to tell the user."""


def split(path: str) -> tuple[str, ...]:
    """`monsters/Abyssal demon` -> `("monsters", "Abyssal demon")`.

    Raises `KnobError` for anything that is not a known branch followed by at
    least one key. **The branch check is the guard**: these paths address a
    file that is read back and parsed, so an unchecked one is a way to write
    arbitrary JSON into it - the discipline `settings.sanitise` applies to
    keys, applied to paths.
    """
    parts = tuple(part for part in path.split("/") if part)
    if len(parts) < 2:
        raise KnobError(f"{path!r} is not a knob: expected '<branch>/<key>'")
    if parts[0] not in CONFIG_BRANCHES:
        raise KnobError(f"{parts[0]!r} is not an override branch")
    if len(parts) > 3:
        raise KnobError(f"{path!r} is deeper than any override branch goes")
    return parts


def at(config: Mapping[str, Any], parts: tuple[str, ...]) -> Any:
    """What `parts` addresses in one layer, or `None` when it holds nothing."""
    found: Any = config
    for part in parts:
        if not isinstance(found, Mapping) or part not in found:
            return None
        found = found[part]
    return found


def _number(value: Any, branch: str) -> float | None:
    """The editable number inside a leaf, or `None` if there is not one."""
    field = NUMERIC_FIELD.get(branch)
    if field is not None:
        value = value.get(field) if isinstance(value, Mapping) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def resolve(
    path: str,
    *,
    scraped: Mapping[str, Any],
    site: Mapping[str, Any],
    map_overrides: Mapping[str, Any],
) -> dict[str, Any]:
    """One knob, at every layer, and which layer is in force.

    All three are reported rather than only the winner, because the question a
    person opens this to answer is usually "why is that number what it is" -
    and "because you set it three maps ago" is an answer only a full stack can
    give.

    `editable` is false for a branch-shaped path and for a leaf whose shape
    this module has no numeric field for. Saying so is the point: an editor
    that offered a box for something it could not write would be a lie with a
    cursor in it.
    """
    parts = split(path)
    branch = parts[0]
    layers = {
        "scraped": at(scraped, parts),
        "site": at(site, parts),
        "map": at(map_overrides, parts),
    }
    winner = next(
        (name for name in reversed(LAYERS) if layers[name] is not None), None
    )
    value = layers[winner] if winner is not None else None
    number = _number(value, branch)
    return {
        "path": path,
        "branch": branch,
        "layers": {
            name: {"value": held, "number": _number(held, branch)}
            for name, held in layers.items()
        },
        "layer": winner,
        "value": value,
        "number": number,
        # A branch-shaped path (`slayer/Duradel`) is a group of leaves, and a
        # leaf whose branch has no numeric field is structure. Neither has one
        # number to put in a box.
        "editable": number is not None or (winner is None and _editable_shape(parts)),
    }


def _editable_shape(parts: tuple[str, ...]) -> bool:
    """Whether a path that currently holds nothing could be written.

    A knob with no value anywhere is the normal case for a rate that has only
    ever been a default, and it must still be offerable - otherwise the only
    numbers you can correct are the ones somebody already corrected.
    """
    return parts[0] in NUMERIC_FIELD


def written(
    path: str, number: float | None, current: Mapping[str, Any]
) -> dict[str, Any]:
    """`current` with `path` set to `number`, or cleared when it is `None`.

    Returns a whole new config rather than mutating: this is what gets written
    to disk, and a half-applied edit is the one outcome worse than a refused
    one. Clearing prunes the branches it empties, so removing the last
    correction leaves `{}` and `cache.write_map_overrides` can delete the file
    - which keeps "no corrections" a single state rather than two.
    """
    parts = split(path)
    branch = parts[0]
    if branch not in NUMERIC_FIELD:
        raise KnobError(f"{branch!r} entries are not editable here")
    if number is not None and (
        isinstance(number, bool) or not math.isfinite(number) or number <= 0
    ):
        raise KnobError(f"{number!r} is not a positive, finite number")

    updated = _deepcopy(current)
    if number is None:
        _prune(updated, parts)
        return updated

    field = NUMERIC_FIELD[branch]
    holder: dict[str, Any] = updated
    for part in parts[:-1]:
        nested = holder.get(part)
        holder[part] = dict(nested) if isinstance(nested, Mapping) else {}
        holder = holder[part]
    leaf = parts[-1]
    if field is None:
        holder[leaf] = number
    else:
        existing = holder.get(leaf)
        entry = dict(existing) if isinstance(existing, Mapping) else {}
        entry[field] = number
        # **Say who set it.** Every other entry in the file carries a `source`
        # and `heuristics/README.md` is built on them being readable; an entry
        # that appeared with no provenance would be indistinguishable from a
        # scrape that went wrong.
        entry.setdefault("source", "hand: edited in the estimate panel")
        holder[leaf] = entry
    return updated


def _deepcopy(config: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: _deepcopy(value) if isinstance(value, Mapping) else value
        for key, value in config.items()
    }


def _prune(config: dict[str, Any], parts: tuple[str, ...]) -> None:
    """Remove `parts`, and any branch it leaves empty."""
    head, rest = parts[0], parts[1:]
    if head not in config:
        return
    if not rest:
        del config[head]
        return
    nested = config[head]
    if isinstance(nested, dict):
        _prune(nested, rest)
        if not nested:
            del config[head]


__all__ = ["KnobError", "LAYERS", "NUMERIC_FIELD", "SCOPES", "at", "resolve", "split", "written"]
