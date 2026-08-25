"""Perilous Moons: three solo bosses, each weak to a melee style the other
two resist, feeding one shared chest.

**Why this needs `costing/dps_bridge.SCRIPTS`, not just `costing/encounter.py`.**
`[[Perilous Moons]]`: "each Moon is weak to different melee styles... they
all have low Defence level (60)... very high ranged and magic defence." The
library's own stat blocks say exactly how much: Blue Moon carries
`defence_crush=0` against `defence_stab=100`/`defence_slash=100`, Blood
Moon `defence_slash=0` against the other two at `100`, the Eclipse Moon
`defence_stab=0` the same way - and all three carry `defence_magic=500`/
`defence_ranged=500`, ruling those out entirely. That is Zulrah's magma-form
shape (one style takes nothing) repeated across a *melee substyle* axis
`dps_bridge.build_loadouts` never resolved before this module: an ordinary
`Melee` loadout is one weapon, ranked on the best of stab/slash/crush
combined, so it is right for exactly one of the three Moons and wrong for
the other two - a scythe (slash) would price the Blue Moon and the Eclipse
Moon as if fought with a weapon two of their three melee defences actively
resist.

**The fix is `dps_bridge.MELEE_SUBSTYLES`**, added alongside this module:
`Stab`/`Slash`/`Crush` loadouts, ranked on their own attack bonus rather
than the best of the three, built from BiS picks `derived.bis.picks` has
carried all along. Each Moon is registered here as its own one-phase
`FightScript` - `hp_share=1.0`, no reduction window, `styles={the one
substyle that actually damages it}` - so `dps_bridge.best_kill` resolves it
through `_scripted_kill`, which filters `loadouts` down to that one style
before the ordinary search ever runs. **One phase is still a script, not a
plain kill**, for the same reason `costing/nightmare.py`'s single phase is:
the style restriction has nowhere else to live.

Ranged and Magic are excluded from every Moon's `styles` outright rather
than left for the ordinary search to discover on its own - `defence_ranged`/
`defence_magic=500` would already make either style look catastrophically
slow, but "catastrophically slow" and "refused" are different answers, and
this project refuses rather than approximates a fight nothing here has
evidence anyone actually has.

### Why this is a chest, not three separate drop tables

**The export carries none of it.** `Blue Moon`/`Blood Moon`/`Eclipse Moon`
are absent from `drops` entirely - `chunksim chunkinfo`'s data has no table
for any of the three - and the twelve unique armour/weapon pieces are gated
behind `Lunar Chest`'s `Output`, itself equally absent. That is exactly the
shape `costing/raids.py`'s module docstring describes for Chambers, Theatre
and Tombs: a reward the export files under something with no table, priced
at whatever `Heuristics.kills_per_hour` falls back to unless a module says
otherwise.

### Where the numbers come from

**Twelve items, one uniform chance.** `Money making guide/Moons of Peril`'s
own `Output` fields are `1/224` for every one of the twelve pieces - four
per Moon (`Eclipse atlatl`/helm/chestplate/tassets, `Dual macuahuitl`/helm/
chestplate/tassets, `Blue moon spear`/helm/chestplate/tassets) - so
`UNIQUE_CHANCE` is quoted from the guide rather than derived, the same way
`costing/theatre.py`'s `TEAM_UNIQUE_CHANCE` is.

**`kph = 10` at "kills all 3 bosses"** is the guide's own completion unit: one
run is one full clear, matching `costing/theatre.py`'s "twenty minutes for a
raid" reading rather than a per-boss rate. No party division applies - this
is solo content, and the guide's own gear ("Bandos armour and a Zamorakian
hasta" for the baseline 10kph, "maxed... Scythe of Vitur" for 14) is a single
melee loadout throughout, unlike the Hydra's or Nightmare's ranged/magic
oracle comparisons.

### What stays unmodelled

Each Moon's special attacks (Blue Moon's weapon freeze, Blood Moon's jaguar
swarm, Eclipse Moon's mimics) are avoidable per the wiki's own strategy
sections and are not costed, matching every other boss module in this
project. The order the three are fought in does not matter to this model,
matching the wiki's own "the Moons can be fought in any order."

Pure: `FightScript`/`Phase` construction only, no `osrs_dps` import - the
Moons are registered into `dps_bridge.SCRIPTS` by that module, exactly as
`hydra.py`/`nightmare.py`/`zulrah.py`/`sire.py`/`grotesque_guardians.py` are.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from chunksim.costing import encounter
from chunksim.costing.encounter import EXPERIENCE, FightPlan, KillSeconds, Objective, UNIQUE
from chunksim.costing.fightscripts import FightScript, Phase

PERILOUS_MOONS = "Perilous Moons"

#: Upstream's own challenge for the raid's loot.
LOOT_TASK = "Perilous Moons loot*"

BLUE_MOON, BLOOD_MOON, ECLIPSE_MOON = "Blue Moon", "Blood Moon", "Eclipse Moon"

#: Each Moon's one weak melee substyle - published on its own wiki page and
#: matched exactly by the library's `0`-vs-`100` defence split. See the
#: module docstring.
WEAK_TO: Mapping[str, str] = {
    BLUE_MOON: "Crush",
    BLOOD_MOON: "Slash",
    ECLIPSE_MOON: "Stab",
}

#: The library's own key for each Moon's phase target. **The Eclipse Moon
#: has no bare key** - `osrs_dps` carries `Eclipse Moon#Regular` and
#: `Eclipse Moon#Clone` (the Mimic special attack's decoys, identical stats)
#: rather than one unversioned entry the way Blue Moon and Blood Moon do -
#: so its phase targets the real boss's own key explicitly, exactly the
#: reason `Phase.target` is documented as "never the bare boss name" in
#: `costing/fightscripts.py`.
_TARGET: Mapping[str, str] = {
    BLUE_MOON: BLUE_MOON,
    BLOOD_MOON: BLOOD_MOON,
    ECLIPSE_MOON: f"{ECLIPSE_MOON}#Regular",
}

#: One `FightScript` per Moon, each a single unsplit phase against its own
#: full health - `hp_share=1.0`, no reduction window, restricted to the one
#: substyle that actually damages it. `dps_bridge.py` composes these into
#: `SCRIPTS` alongside every other scripted boss.
SCRIPTS: Mapping[str, FightScript] = {
    name: FightScript(
        name=name,
        phases=(
            Phase(
                name=name,
                target=_TARGET[name],
                hp_share=1.0,
                styles=frozenset({style}),
                note=f"Weak to {style.lower()} - '{style}' is the only "
                "style offered; Ranged and Magic are refused outright "
                "rather than priced against defence_ranged=defence_magic="
                "500. See the module docstring on Phase.styles.",
            ),
        ),
    )
    for name, style in WEAK_TO.items()
}

#: Guide's own figure: `Money making guide/Moons of Peril`, `kph = 10` "at
#: kills all 3 bosses" - one completion is one full clear, not one boss.
PUBLISHED_RUNS_PER_HOUR = 10.0
PUBLISHED_SECONDS = 3600.0 / PUBLISHED_RUNS_PER_HOUR

#: The twelve uniques, split by which Moon awards them. Every one shares the
#: guide's own `1/224` - see the module docstring.
UNIQUE_CHANCE = 1.0 / 224.0

UNIQUE_TABLE: Mapping[str, tuple[str, ...]] = {
    BLUE_MOON: ("Blue moon spear", "Blue moon helm", "Blue moon chestplate", "Blue moon tassets"),
    BLOOD_MOON: (
        "Dual macuahuitl",
        "Blood moon helm",
        "Blood moon chestplate",
        "Blood moon tassets",
    ),
    ECLIPSE_MOON: (
        "Eclipse atlatl",
        "Eclipse moon helm",
        "Eclipse moon chestplate",
        "Eclipse moon tassets",
    ),
}


def item_chances() -> dict[str, float]:
    """`{item: chance one full clear gives it}` - flat across all twelve,
    plus `Atlatl dart`.

    **`Atlatl dart` is treated as guaranteed, and that is an approximation
    stated rather than hidden.** Unlike `costing/colosseum.py`'s quiver and
    splinters, the guide never says "guaranteed" for it outright - its
    `Output` field gives an *expected quantity* per run
    (`(55/56)^3 x mean quantity x drop share`, not a chance of at least one),
    and turning that into a true per-run "at least one" probability needs
    the underlying roll count this project does not have. The quantity
    formula's own factors put it close enough to certain - a common material
    drop at a several-in-thirty share, rolled whenever the rarer table is
    not hit - that `1.0` is the right order of magnitude; a future scrape
    finding the real roll count should replace this rather than refine it.
    """
    found = {
        item: UNIQUE_CHANCE
        for items in UNIQUE_TABLE.values()
        for item in items
    }
    found["Atlatl dart"] = 1.0
    return found


def plans() -> tuple[FightPlan, ...]:
    """One run's three bosses, "any order" per the wiki - the sum does not
    care which."""
    return tuple(FightPlan(name=name, target=name) for name in WEAK_TO)


def run(kill_seconds: KillSeconds) -> encounter.Encounter | None:
    """One completed run - three bosses, no puzzle rooms, no party."""
    return encounter.build(PERILOUS_MOONS, plans(), kill_seconds)


@dataclass(frozen=True)
class Answer:
    """What one run costs for one objective."""

    run: encounter.Encounter
    #: Completions expected, or `inf` where the objective cannot be met.
    runs: float

    @property
    def seconds(self) -> float:
        return self.run.seconds * self.runs

    @property
    def hours(self) -> float:
        return self.seconds / 3600.0


def answer(kill_seconds: KillSeconds, objective: Objective = encounter.FULL_LOG) -> Answer | None:
    """`objective` priced against a full clear, or `None` if a boss cannot be
    priced."""
    built = run(kill_seconds)
    if built is None:
        return None
    chances = item_chances()
    if objective.kind == UNIQUE:
        runs = encounter.expected_runs(chances.get(objective.item, 0.0))
    elif objective.kind == EXPERIENCE:
        # **Not answered here rather than answered badly** - a run's combat
        # experience is its three bosses' hitpoints against the map's
        # damage, which is `costing/combat_xp.py`'s question, matching every
        # other encounter module's refusal.
        return None
    else:
        runs = encounter.runs_for_all(list(chances.values()))
    return Answer(run=built, runs=runs)


def item_seconds() -> dict[str, float]:
    """`{item: seconds}` for the item walk, at `PUBLISHED_SECONDS` - see
    `costing/raids.item_seconds` for the shape and the reason it is
    published rather than modelled: the goal walk runs before any
    DPS-derived rate exists, so there is no map-driven run duration to
    divide by yet.
    """
    return {
        item: PUBLISHED_SECONDS / chance
        for item, chance in item_chances().items()
        if chance > 0
    }


def activity_for(item: str) -> str | None:
    """`PERILOUS_MOONS` if `item` is one of the chest's own rewards, else
    `None` - `costing/tzhaar.activity_for`'s exact shape, matched
    case-insensitively for the same reason that module's docstring gives.
    """
    wanted = item.lower()
    return PERILOUS_MOONS if wanted in {name.lower() for name in item_chances()} else None
