"""Bryophyta's and Obor's lair chests: what a key really costs.

Both chests are `skillItems.Nonskill` activities - `Chest (Bryophyta's
lair)`/`Chest (Obor's lair)` - that the item walk reaches directly whenever
something inside wants pricing (`Bryophyta's essence`, a rune, a bar): the
chest is read as an ordinary monster-shaped source and its "kills per hour"
is asked of `Heuristics.kills_per_hour`. Neither chest is ever scraped or
combat-simulated - it has no stat block, nothing fights it - so that call
falls to `DEFAULT_KPH["regular"]`, 150 an hour, and everything inside prices
as though the chest opens on demand.

It does not. Each opening consumes one key - `Mossy key` for Bryophyta's
lair, `Giant key` for Obor's - and a key is a rare drop off the boss itself
**or** off the ordinary giants sharing its name, whichever is faster on this
map. `CANDIDATE_CHANCE` is read straight off `cache/reference/chunkinfo.json`'s
own `drops` tables (checked 2026-08-24) rather than estimated: Bryophyta
drops a Mossy key at 1/16, a Moss giant at 1/150 (1/120 in the Iorwerth
Dungeon variant); Obor drops a Giant key at 1/16, and so do a Hill Giant's
four regional variants at 1/128, alongside two non-giant monsters that
happen to share the table (Black Knight Titan, the Ardougne Zoo Cyclops).

`OPEN_SECONDS` mirrors `costing.estimate.DEFAULT_ACTION_SECONDS` (four game
ticks) rather than importing it - the same four-tick stand-in the item
walk's own `make:` route would spend turning a key into an open chest, once
`estimate._route_hours`'s certainty gate stops refusing that route for a
`*`-marked (consumed) `Items` entry. The two fixes agree on this number
deliberately: one prices the chest as a *destination* (something already
pricing inside it), the other as a *goal* (something asking for the chest
by name), and they would read as two different chests if they disagreed.

This module owns none of the wiring - it is pure arithmetic over a rate
lookup the caller supplies. `dps_bridge._apply_gated_bosses` is the one
caller: it has the map's resolved `Heuristics.kills_per_hour` for every
candidate monster already in hand, and injects the result as a synthetic
`Rate` for each chest name before the item walk ever asks for one.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

BRYOPHYTAS_LAIR = "Chest (Bryophyta's lair)"
OBORS_LAIR = "Chest (Obor's lair)"

#: Chest name -> {candidate monster: chance of the key per kill}.
CANDIDATE_CHANCE: Mapping[str, Mapping[str, float]] = {
    BRYOPHYTAS_LAIR: {
        "Bryophyta": 1.0 / 16.0,
        "Moss giant": 1.0 / 150.0,
        "Moss giant (Iorwerth Dungeon)": 1.0 / 120.0,
    },
    OBORS_LAIR: {
        "Obor": 1.0 / 16.0,
        "Hill Giant": 1.0 / 128.0,
        "Hill Giant#Kourend": 1.0 / 128.0,
        "Hill Giant#Plateau": 1.0 / 128.0,
        "Hill Giant#Varlamore": 1.0 / 128.0,
        "Black Knight Titan": 1.0 / 128.0,
        "Cyclops (Ardougne Zoo)": 1.0 / 128.0,
    },
}

#: Four ticks - see the module docstring for why this mirrors, rather than
#: imports, `costing.estimate.DEFAULT_ACTION_SECONDS`.
OPEN_SECONDS = 4 * 0.6

#: A candidate monster's own kill time in seconds, or `None` if it cannot be
#: priced (unreachable, no rate). The caller's job - see `dps_bridge`.
KillSeconds = Callable[[str], float | None]


def key_seconds(chest: str, kill_seconds: KillSeconds) -> float | None:
    """The fastest way to one key, over every monster that drops it."""
    best: float | None = None
    for name, chance in CANDIDATE_CHANCE.get(chest, {}).items():
        if chance <= 0:
            continue
        found = kill_seconds(name)
        if found is None or found <= 0:
            continue
        per_key = found / chance
        if best is None or per_key < best:
            best = per_key
    return best


def effective_seconds(chest: str, kill_seconds: KillSeconds) -> float | None:
    """One key, plus opening the chest with it - `None` if no candidate
    monster can be priced at all, which the caller must leave unpriced
    rather than guess at."""
    found = key_seconds(chest, kill_seconds)
    return None if found is None else found + OPEN_SECONDS
