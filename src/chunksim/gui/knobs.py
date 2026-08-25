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
from collections.abc import Mapping, Sequence
from typing import Any

from chunksim.costing import instanced
from chunksim.costing.estimate import DEFAULT_ACTION_SECONDS
from chunksim.costing.heuristics import CONFIG_BRANCHES, Heuristics

#: Which field of a branch's leaf carries the number worth editing, or `None`
#: where the leaf is the number. Branches absent from here are readable and
#: not editable - `monster_stats` and `spell_costs` are scraped structure
#: rather than a figure someone would argue with, and `training` and `quests`
#: belong to the skilling and quest buckets, which do not record knobs yet.
NUMERIC_FIELD: Mapping[str, str | None] = {
    "actions": None,
    "currencies": None,
    "rarities": None,
    "runs": None,
    "wait": None,
    "monsters": "value",
    "quests": "hours",
    "shops": "price",
    "slayer": "kills_per_hour",
    "superiors": "spawn_rate",
    "training": "value",
}

#: A branch whose editable figure needs a sentence of explanation to be
#: trusted rather than second-guessed. **One sentence of what the number
#: means, one of where it comes from** - the same two things `knobLayers`
#: draws underneath, in words rather than a stack of layer rows. A branch
#: whose leaf is self-explanatory once you can see its path
#: (`superiors/Colossal Hydra`, `quests/Dragon Slayer II`) has no entry:
#: adding one for every branch would bury the ones that actually correct a
#: wrong assumption under ones that only restate the label.
BRANCH_NOTES: Mapping[str, str] = {
    "actions": (
        "Seconds for one performance of this action - one imbue, one dose, "
        "one recipe step. Read off a guide's own actions-per-hour or a "
        "recipe's tick cost; an action nothing publishes falls back to a "
        "flat default. Overriding it moves every route that performs it."
    ),
    "currencies": (
        "How much of this currency can be earned an hour - Slayer points, "
        "shop tokens, anything that is not coins. Divides a shop price into "
        "hours, so a currency with no rate here prices nothing it buys "
        "either - those read as unpriced, not free."
    ),
    # **The one branch a simulated fight can outrank.** `monsters` and
    # `slayer` are the two places a number can be spent that this dialog's
    # own three config layers never held - see `app.js`'s `knobLayers`
    # `computed` line, which is what actually shows it. The note here only
    # has to say that this can happen, not repeat the number: the layer
    # stack above already does that.
    "monsters": (
        "Kills per hour for this monster. Simulated from this map's own "
        "BiS gear and levels wherever the fight can be priced that way, "
        "ahead of the scrape below - which only applies where the "
        "simulation can't run (gear out of reach, or a fight nothing here "
        "models). Set a number here to pin it against both."
    ),
    "quests": (
        "Hours to complete this quest once, start to finish. Read off the "
        "wiki's own stated length where it gives one; a quest that states "
        "none falls back to a flat default."
    ),
    "runs": (
        "Seconds for one completion of this raid or instance. The wiki "
        "publishes no duration for these at all, so every figure here is "
        "this project's own estimate rather than a scrape - correcting one "
        "is not disagreeing with a source, there isn't one."
    ),
    "shops": (
        "What this shop charges for this item, in whatever it sells in - "
        "paired with that currency's own rate (see `currencies`) to turn a "
        "price into hours."
    ),
    "slayer": (
        "One master's whole assignment table: how many of each task it "
        "hands out, and how fast each is killed. Sizes are per master; kill "
        "rates are shared across every master that can assign the same "
        "monster, and simulated the same way `monsters` are. The hours "
        "spent *waiting* for a gated task to come back around is a "
        "separate number - see `wait` - not this table."
    ),
    "superiors": (
        "How often this superior spawns from its ordinary counterpart's "
        "death while on a slayer task - roughly 1/200 unmodified. Raising "
        "it is what the Bigger and Badder unlock buys, per monster."
    ),
    "training": (
        "Experience an hour for this method, at the level it's read at. A "
        "number here is a hand pin and beats everything else, including "
        "this project's own modelled curve - which is what the estimate "
        "actually spends when nothing is pinned, so an empty box does not "
        "mean the method goes unpriced."
    ),
    # **`wait/<master>/<task>` is what a task-gated item's own knob list
    # names now** - it used to be `slayer/<master>/<task>`, whose
    # `kills_per_hour` looked like the wait but was never read by one
    # (`MasterRate.hours_to_be_assigned` excludes the gate task from its own
    # wait; that number feeds Slayer XP and other tasks' waits instead - a
    # real thing, just not this one). Rather than show a real-but-unrelated
    # figure next to a misleading label, this branch exists so the number
    # shown *is* the one thing the price actually depends on.
    "wait": (
        "Hours until this task is next assigned. Computed by default from "
        "the master's whole task list - weighted by how long each other "
        "task takes, preferring this map's own combat simulations where "
        "reachable - so there is no single wiki figure behind it. Set a "
        "number here to override that computation directly for this map."
    ),
}

#: How many keys deep a branch's leaves sit. **Not inferable from the path**,
#: which is why it is written down: real quest names contain the separator -
#: `Recipe for Disaster/Another Cook's Quest` is one key, not two - so
#: splitting on every `/` reads that as a two-level path into a branch that is
#: one level deep. It resolves to nothing, and a *write* would build a nested
#: object `load` then ignores, which is a correction that silently does not
#: apply.
#:
#: So the branch decides how many pieces there are, and the split takes the
#: last separator rather than the first: the leaf key of a two-level branch
#: (a skill, an item, an assignment) is the simple half, and the container (a
#: shop, a quest, a master) is where a slash would turn up.
BRANCH_DEPTH: Mapping[str, int] = {
    "shops": 2,
    "slayer": 2,
    "training": 2,
    "wait": 2,
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
#: at any of these three is one the estimator is answering from somewhere
#: else - **usually a model rather than a default**, which is the part this
#: note used to get wrong. `_EFFECTIVE` says which of those two it can speak
#: to; where it cannot, it says nothing rather than quoting a fallback the
#: estimate never spent. See `_pinned_xp`.
LAYERS: tuple[str, ...] = ("scraped", "site", "map")


#: How to ask a built `Heuristics` what a branch's entry *actually* resolves
#: to, defaults and all.
#:
#: **Because "default" is not a number and a reader wants the number.** There
#: is no config-shaped layer of defaults to lay under the other three (see
#: `LAYERS`) - a fallback is applied per field, by the accessor, and often
#: depends on something the config does not hold: `kills_per_hour` picks one
#: of three figures by whether the monster is a boss, a slayer target or
#: neither. So the effective value is asked of the object that knows, rather
#: than reconstructed from the file.
_EFFECTIVE: Mapping[str, Any] = {
    "monsters": lambda h, parts: h.kills_per_hour(parts[1]).value,
    "quests": lambda h, parts: h.quest_hours(parts[1]).hours,
    "currencies": lambda h, parts: h.currency_per_hour.get(parts[1]),
    "actions": lambda h, parts: h.action_seconds.get(parts[1], DEFAULT_ACTION_SECONDS),
    "rarities": lambda h, parts: h.rarities.get(parts[1].lower()),
    # **The model's own figure is the default here, not a constant.** A run
    # has no scraped duration - the wiki publishes none - so with nothing
    # written at any layer the panel should show what the estimator actually
    # spent, which is `instanced`'s table and not a fallback.
    "runs": lambda h, parts: instanced.run_seconds(parts[1], h.run_seconds),
    "superiors": lambda h, parts: _attr(h.superiors.get(parts[1]), "spawn_rate"),
    "monster_stats": lambda h, parts: _attr(h.monster_stats.get(parts[1]), "hitpoints"),
    # **`None`, not the default, and that is a correction.** This used to be
    # `h.xp_per_hour(task, skill).value`, which reads the `training` branch and
    # falls back to `DEFAULT_XP_PER_HOUR` - so a knob nobody had pinned showed
    # a flat **1,000/hr**. That is wrong for almost every training method: the
    # rate the estimate actually spends comes from `Heuristics.computed`, the
    # modelled band curve, and this `Heuristics` is built from the merged
    # *config* alone - `inputs.load_heuristics` - so `computed` is empty here.
    #
    # `Burn wood at ~|Wintertodt|~` is the worked case. `costing/wintertodt.py`
    # prices it 126,720/hr at level 30 rising to 418,176 at 99 and stamps this
    # very knob path on every band; the dialog showed 1,000. Of the 26
    # Firemaking methods on the benchmark map, 25 are modelled and none is
    # published, so the config-only answer is wrong far more often than right.
    #
    # **`routes_view.resolve_knob` now pays for the priced stack** where it has
    # a map, so `computed` is populated and `_training_rate` can report the
    # modelled band. Without a map it still falls through to "no opinion",
    # which `app.js` renders by omitting the "Default" line.
    "training": lambda h, parts: _training_rate(h, parts),
    "shops": lambda h, parts: _attr(h.shop_prices.get(parts[1], {}).get(parts[2]), "price"),
    "slayer": lambda h, parts: _attr(
        (h.slayer.get(parts[1]) or {}).get(parts[2]), "kills_per_hour"
    ),
    # **Only the override, never the computed fallback.** The fallback
    # (`MasterRate.hours_to_be_assigned`) needs the master's whole task
    # list, which a bare `Heuristics` cannot supply - `routes_view.
    # resolve_knob` fills it in itself, precisely when this returns `None`.
    "wait": lambda h, parts: (h.wait_hours.get(parts[1]) or {}).get(parts[2]),
}


def _training_rate(h: Heuristics, parts: Sequence[str]) -> float | None:
    """What a training knob actually resolves to, best layer first.

    **Never `DEFAULT_XP_PER_HOUR`, which is what this used to return.** That
    fallback is the `training` branch's, and the estimate almost never spends
    it: of the 26 Firemaking methods on the benchmark map, 25 are modelled and
    none is published, so a knob nobody had pinned showed a flat 1,000/hr for
    a curve running to six figures.

    Three answers, in the order the estimate resolves them:

    1. **A pin**, which outranks every model, so where the `training` branch
       holds a value that value is the answer.
    2. **The modelled band**, from `Heuristics.computed` - the layer
       `costing/wintertodt.py` and its neighbours write into, each stamping
       the knob path it belongs to. The **highest** band is reported, matching
       `training_bands`' running maximum: a curve's top is what the method is
       worth once its level is reached, and quoting the opening band would
       understate `Burn wood at ~|Wintertodt|~` by a factor of three.
    3. **Nothing**, where neither has an opinion. `app.js` omits the "Default"
       line rather than printing a number the estimate never spent.

    Reaching (2) is why `routes_view.resolve_knob` pays for a priced
    `Heuristics`; with a config-only one this falls through to (3).
    """
    pinned = h.training.get(parts[1], {}).get(parts[2])
    if pinned is not None:
        return float(pinned.value)
    wanted = f"training/{parts[1]}/{parts[2]}"
    banded = [
        method.xp_per_hour
        for methods in h.computed.values()
        for method in methods
        if method.knob == wanted and method.xp_per_hour > 0
    ]
    return max(banded) if banded else None


def _attr(holder: Any, name: str) -> float | None:
    value = getattr(holder, name, None)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def effective(path: str, heuristics: Heuristics) -> float | None:
    """What this knob resolves to right now, with every fallback applied.

    `None` where the branch is two levels deep and only one was given
    (`slayer/Duradel` is a table, not a figure), or where the accessor has
    nothing to answer with. A caller showing this must treat `None` as "no
    single number" rather than as zero.
    """
    parts = split(path)
    reader = _EFFECTIVE.get(parts[0])
    if reader is None or len(parts) != 1 + (BRANCH_DEPTH.get(parts[0], 1)):
        return None
    try:
        value = reader(heuristics, parts)
    except (AttributeError, KeyError, TypeError, ValueError):  # pragma: no cover - defensive
        return None
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


class KnobError(ValueError):
    """A path or value this module refuses. Carries what to tell the user."""


def split(path: str) -> tuple[str, ...]:
    """`monsters/Abyssal demon` -> `("monsters", "Abyssal demon")`.

    Raises `KnobError` for anything that is not a known branch followed by at
    least one key. **The branch check is the guard**: these paths address a
    file that is read back and parsed, so an unchecked one is a way to write
    arbitrary JSON into it - the discipline `settings.sanitise` applies to
    keys, applied to paths.

    **The branch decides how many keys follow, not the separator** - see
    `BRANCH_DEPTH`. A one-level branch keeps everything after it as a single
    key, slashes and all, which is what makes `quests/Recipe for
    Disaster/Freeing Evil Dave` address the quest it names rather than a
    nesting that does not exist.

    A two-level branch also accepts one key, which addresses the container
    rather than a leaf: `slayer/Duradel` is a real thing to ask about, since
    that is what the superior shared table is priced off.
    """
    branch, separator, rest = path.partition("/")
    if not separator or not rest:
        raise KnobError(f"{path!r} is not a knob: expected '<branch>/<key>'")
    if branch not in CONFIG_BRANCHES:
        raise KnobError(f"{branch!r} is not an override branch")
    if BRANCH_DEPTH.get(branch, 1) == 1 or "/" not in rest:
        return (branch, rest)
    container, _, leaf = rest.rpartition("/")
    if not container or not leaf:
        raise KnobError(f"{path!r} is not a knob: expected '<branch>/<key>/<key>'")
    return (branch, container, leaf)


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
    # A branch-shaped path (`slayer/Duradel`) is a group of leaves, and a leaf
    # whose branch has no single figure is structure. Neither has one number
    # to put in a box - and they are not the same reason, so they do not get
    # the same sentence. A dialog that said "read from the whole branch" over
    # a monster's hitpoints would be explaining the wrong thing.
    editable = number is not None or (winner is None and _editable_shape(parts))
    if editable:
        why = ""
    elif branch not in NUMERIC_FIELD:
        why = "several numbers, not one — read but not edited here"
    else:
        why = "read from the whole branch, not from one entry"
    return {
        "path": path,
        "branch": branch,
        # **The split, so the page does not have to know `BRANCH_DEPTH`.** A
        # second copy of that rule in JavaScript is a second thing to get
        # wrong about `Recipe for Disaster/Freeing Evil Dave`, and the page
        # only wants it to draw the path readably.
        "parts": list(parts),
        "layers": {
            name: {"value": held, "number": _number(held, branch)}
            for name, held in layers.items()
        },
        "layer": winner,
        "value": value,
        "number": number,
        "editable": editable,
        "why": why,
        "note": BRANCH_NOTES.get(branch, ""),
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
