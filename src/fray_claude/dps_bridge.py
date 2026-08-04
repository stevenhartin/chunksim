"""Pricing a kill with the DPS calculator instead of a money-making guide.

`heuristics.py` gets its kills-per-hour from the OSRS wiki's money-making
guides, which cover **243 of the export's 2,710 training methods** - most ways
of killing a thing do not make money and so have no guide. Everything else
falls back to a flat `DEFAULT_KPH`. This module computes the number instead,
from the gear `bis.py` says the map can actually reach, using the `osrs-dps`
library.

**The dependency is optional and must stay optional.** `osrs-dps` is GPL-3.0
where this project is MIT, so it is something a user installs deliberately
(`pip install -e ../osrs-dps`), not something vendored in. Every entry point
here checks `DPS_AVAILABLE` and the estimator falls back to the scraped rates
without it. Import this module freely - importing is safe when the library is
absent; only calling is not.

**Time-to-kill is not a kill cycle.** The library returns seconds of
*fighting*; a kills-per-hour figure also carries travel, banking and respawn,
which is exactly what the wiki's guides bake in and the calculator cannot
know. `kills_per_hour` therefore takes an explicit `overhead` and the whole
conversion is `3600 / (ttk + overhead)`. See `measure_overhead` for what the
real map says that number is, and read its docstring before trusting a
calibration: the naive fit is contaminated by the gear gap.

**Item stats come from this project's own export, not the library's.** The
library takes resolved stat blocks precisely so a caller with its own
equipment data does not need a second copy joined by name. That keeps the
numbers consistent with the gear `bis.py` picked - it would be incoherent to
choose a whip using one stat table and price the kill with another. The cost
is that where the export disagrees with the wiki, this follows the export:
measured examples are the Occult necklace's magic attack (10 here, 12
upstream) and its prayer bonus (3 here, 2 upstream). Neither moves a kill time
much; both are the export's to fix.

**Two conversions the export needs on the way in**, and the first is the one
that bites:

1. `magic_damage` is a **display percentage** here and **tenths of a percent**
   in the library, matching upstream's `magic_str`. Occult necklace is `5`
   in the export and `50` upstream; Master wand `10` and `100`. Copying the
   field straight through under-reports every magic hit tenfold, and it is the
   one field where the otherwise field-for-field copy breaks.
2. `slot: "2h"` is the export's way of saying two-handed; the library carries
   it as a separate `two_handed` flag beside an ordinary weapon slot.

**What is deliberately not supplied**, each of which makes the estimate
*conservative* rather than wrong - a missing bonus lengthens the kill:

- **Prayers.** Piety and Rigour are worth a lot, but the map records no prayer
  level (`estimate.infer_levels` reads a floor out of completed challenges,
  which says nothing about what is active in a fight).
- **Weapon category.** The export has no `category` field, so the effects
  keyed off one - `Polearm` reaching flying monsters, `Pickaxe` against
  Guardians, `Salamander` bypassing some melee immunities - never fire.
- **`in_wilderness`.** The wilderness weapons only get their bonus inside it,
  and a drop table does not say where its monster stands. The map's BiS holds
  a `Webweaver bow (u)`, so this one is live and costs real damage.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from fray_claude.chunkinfo import ChunkInfo
from fray_claude.heuristics import Rate
from fray_claude.summary import _mapping

try:  # pragma: no cover - exercised by whether the extra is installed
    from osrs_dps import (
        CombatStyle,
        Levels,
        Loadout,
        StatBlock,
        Target,
        Unsupported,
        dps,
    )
    from osrs_dps.data import MonsterIndex, load_monsters

    DPS_AVAILABLE = True
except ImportError:  # pragma: no cover - ditto
    DPS_AVAILABLE = False


#: Seconds of not-fighting per kill: travel, banking, respawn, finding the
#: next one. A single flat number is crude - a boss with a 90-second respawn
#: and a slayer monster in a packed cave are nothing alike - which is why it
#: is a parameter everywhere and this is only the fallback. Calibrated against
#: the wiki's own rates by `measure_overhead`.
DEFAULT_OVERHEAD_SECONDS = 30.0

#: The export stores magic damage as a display percentage; the library wants
#: upstream's `magic_str`, in tenths of a percent. See the module docstring.
MAGIC_DAMAGE_SCALE = 10

#: The BiS styles worth pricing a kill with. `bis.py` also emits Tank, Flinch,
#: Prayer and Weight Reducing winners, which are not ways of dealing damage.
OFFENSIVE_STYLES = ("Melee", "Ranged", "Magic")

#: The damage-maximising stance for each style, which is what someone killing
#: for a drop would use. Stance buys invisible level boosts that differ
#: between accuracy and max hit, so it cannot be inferred from the style.
_STANCES = {"Melee": "Aggressive", "Ranged": "Rapid", "Magic": "Accurate"}

#: Which melee damage type each export attack bonus corresponds to. Ordered,
#: because a weapon with equal bonuses resolves to the first.
#: Version suffixes that mark a **stage of one fight** rather than an
#: alternative monster. The distinction matters because `best_kill` resolves
#: an ambiguous name by taking the fastest version, which is right for
#: substitutable monsters - kill whichever `Cave bug` is easier - and wrong
#: for these, where you fight every one of them in sequence and pricing the
#: softest phase under-reports the whole kill.
#:
#: Nothing in the data marks the difference: the library's `Target.phase` is
#: unpopulated for all 2,844 entries and the four `Abyssal Sire` phases carry
#: identical hitpoints and defence, so the version *string* is the only
#: signal there is. On the real export this catches 13 of 284 ambiguous names
#: - a small share, but every one of them is a boss, which is where an
#: estimate spends its hours.
_SEQUENTIAL_VERSIONS = ("phase", "stage", "wave", "delve", "enraged", "transition")

_MELEE_ATTACK_BONUSES: tuple[tuple[str, "CombatStyle"], ...] = (
    ("attack_stab", CombatStyle.STAB),
    ("attack_slash", CombatStyle.SLASH),
    ("attack_crush", CombatStyle.CRUSH),
)


class DpsUnavailableError(RuntimeError):
    """Raised when this module is used without `osrs-dps` installed."""


def _require() -> None:
    if not DPS_AVAILABLE:
        raise DpsUnavailableError(
            "osrs-dps is not installed; install the optional extra with "
            "`pip install -e ../osrs-dps` (or `pip install '.[dps]'`)"
        )


@dataclass(frozen=True)
class KillEstimate:
    """One monster, priced: how long a kill takes and what did the killing.

    `monster` is the library's own key, which may carry a `#version` suffix
    the caller's name did not - see `match`. `style` names the BiS style that
    won, since the fastest of the three is what someone would actually use.
    """

    monster: str
    style: str
    ttk: float
    dps: float
    max_hit: int
    accuracy: float
    #: How `monster` was reached from the requested name: `exact` when the
    #: library indexed that name itself, `variant` when the name was ambiguous
    #: and the easiest version was chosen. Mirrors `heuristics.py`'s habit of
    #: recording how a join was made rather than only its result.
    match: str = "exact"

    def kills_per_hour(self, overhead: float = DEFAULT_OVERHEAD_SECONDS) -> float:
        """Kills per hour, this kill's fighting time plus `overhead`."""
        cycle = self.ttk + overhead
        return 3600.0 / cycle if cycle > 0 else 0.0


def _stat_block(entry: Mapping[str, Any]) -> StatBlock:
    """One equipment entry as a library stat block.

    Field-for-field bar `magic_damage`; see `MAGIC_DAMAGE_SCALE`.
    """

    def num(key: str) -> int:
        value = entry.get(key, 0)
        return int(value) if isinstance(value, (int, float)) else 0

    return StatBlock(
        attack_stab=num("attack_stab"),
        attack_slash=num("attack_slash"),
        attack_crush=num("attack_crush"),
        attack_magic=num("attack_magic"),
        attack_ranged=num("attack_ranged"),
        defence_stab=num("defence_stab"),
        defence_slash=num("defence_slash"),
        defence_crush=num("defence_crush"),
        defence_magic=num("defence_magic"),
        defence_ranged=num("defence_ranged"),
        melee_strength=num("melee_strength"),
        ranged_strength=num("ranged_strength"),
        magic_damage=num("magic_damage") * MAGIC_DAMAGE_SCALE,
        prayer=num("prayer"),
    )


def _melee_style(weapon: Mapping[str, Any]) -> CombatStyle:
    """The damage type a melee weapon rolls, by its own best attack bonus.

    `bis.py`'s `Melee` winner is a weapon, not a style - an abyssal whip is
    slash and a dragon dagger stab, and the export says which by where the
    bonus sits. Ties fall to stab, matching the field order.
    """

    def bonus(key: str) -> float:
        value = weapon.get(key, 0)
        return float(value) if isinstance(value, (int, float)) else 0.0

    _, style = max(_MELEE_ATTACK_BONUSES, key=lambda pair: bonus(pair[0]))
    return style


def build_loadouts(
    chunk_info: ChunkInfo,
    picks: Mapping[str, str],
    levels: Mapping[str, int],
) -> dict[str, Loadout]:
    """A `Loadout` per offensive style, from `BisResult.picks`.

    `picks` is keyed `"{style}-{slot}"`, so each style's worn set is every
    pick whose key starts with it. Slots the map cannot fill are simply
    absent, which is a thinner set rather than an error - an early chunk with
    no magic weapon should price a magic kill badly, not refuse to price it.

    `levels` is `estimate.infer_levels`'s floor, so an unproven skill reads as
    level 1 and the kill comes out slow. That is the conservative direction.
    """
    _require()
    equipment = chunk_info.equipment
    loadouts: dict[str, Loadout] = {}

    for style in OFFENSIVE_STYLES:
        prefix = f"{style}-"
        worn = {
            key[len(prefix) :]: name for key, name in picks.items() if key.startswith(prefix)
        }
        if not worn:
            continue

        entries = {
            slot: _mapping(equipment, name) for slot, name in worn.items() if name
        }
        bonuses = StatBlock()
        for entry in entries.values():
            bonuses = bonuses + _stat_block(entry)

        # **The pick key's slot and the export entry's `slot` are different
        # things, and only the latter knows two-handedness.** `bis.py` emits
        # every weapon under a `weapon` pick key - a 2H winner replaces the
        # weapon *and* shield picks rather than appearing under a `2h` one -
        # so reading the key would call the map's `Webweaver bow (u)` one
        # handed. The entry says `slot: "2h"`, and that is what to believe.
        weapon_pick = "weapon" if "weapon" in entries else "2h" if "2h" in entries else ""
        weapon = entries.get(weapon_pick, {})
        speed = weapon.get("attack_speed", 4)
        attack_speed = int(speed) if isinstance(speed, (int, float)) and speed > 0 else 4
        two_handed = weapon.get("slot") == "2h"

        if style == "Melee":
            combat_style = _melee_style(weapon)
        elif style == "Ranged":
            combat_style = CombatStyle.RANGED
        else:
            combat_style = CombatStyle.MAGIC

        loadouts[style] = Loadout(
            levels=Levels(
                attack=levels.get("Attack", 1),
                strength=levels.get("Strength", 1),
                defence=levels.get("Defence", 1),
                ranged=levels.get("Ranged", 1),
                magic=levels.get("Magic", 1),
                hitpoints=levels.get("Hitpoints", 10),
                prayer=levels.get("Prayer", 1),
            ),
            bonuses=bonuses,
            attack_speed=attack_speed,
            style=combat_style,
            stance=_STANCES[style],
            worn=frozenset(worn.values()),
            weapon_name=worn.get(weapon_pick, ""),
            two_handed=two_handed,
        )
    return loadouts


def load_monster_index() -> MonsterIndex:
    """The library's monster data. Build **one** per invocation and pass it on.

    Parsing is the expensive part, and the library keeps no module-level cache
    on purpose, so a caller that reloads per monster pays for it every time.
    """
    _require()
    return load_monsters()


def candidate_targets(index: MonsterIndex, name: str) -> tuple[tuple[str, Target], ...]:
    """Every monster `name` could mean, as `(key, target)` pairs.

    The library indexes exact names only and refuses to guess: `Abyssal demon`
    has three versions with different defences, so it is not a key at all
    while `Abyssal demon#Standard` is. Measured against the real export, 491
    of this project's 872 drop-table monsters hit exactly, 284 more are bare
    names with versions behind them, and 97 are absent altogether.

    This resolves the middle group by returning *all* the versions and letting
    `best_kill` choose, rather than picking one here on a rule like "lowest
    level" that has no combat meaning. An empty result means the name cannot
    be priced - either it is absent from the library's data, or its versions
    are the sequential phases of one fight rather than alternatives, for which
    see `_SEQUENTIAL_VERSIONS`. Either way the caller should report it rather
    than price it.
    """
    _require()
    exact = index.get(name)
    if exact is not None:
        return ((name, exact),)

    prefix = f"{name}#"
    versions = [key for key in index if key.startswith(prefix)]
    if any(
        marker in key[len(prefix) :].casefold()
        for key in versions
        for marker in _SEQUENTIAL_VERSIONS
    ):
        return ()

    return tuple(
        (key, target)
        for key in versions
        if (target := index.get(key)) is not None
    )


def best_kill(
    loadouts: Mapping[str, Loadout],
    name: str,
    candidates: Iterable[tuple[str, Target]],
    *,
    on_slayer_task: bool = False,
) -> KillEstimate | None:
    """The fastest way to kill `name` with the gear on offer, or `None`.

    Fastest across **both** axes: which BiS style to use, and - when the name
    was ambiguous - which version of the monster. Choosing the quickest
    version is the one policy here with a defensible meaning: someone farming
    a drop kills whichever one they can kill fastest.

    `None` means no combination produced a kill: an empty `candidates`, a
    loadout that cannot damage the target (`dps == 0`, which the library
    reports with `expected_ttk == 0`), or every pairing refused as
    `Unsupported`. All three are "do not price this", not "price it at zero".
    """
    _require()
    pairs = tuple(candidates)
    if not pairs or not loadouts:
        return None

    best: KillEstimate | None = None
    for key, target in pairs:
        fight = target
        if on_slayer_task and not target.is_slayer_monster:
            fight = _slayer_target(target)
        for style, loadout in loadouts.items():
            try:
                result = dps(_on_task(loadout) if on_slayer_task else loadout, fight)
            except Unsupported:
                continue
            # A zero rate is the library saying "never killed"; its companion
            # ttk of 0.0 is a convention, not a fast kill. Read the pair.
            if result.dps <= 0 or result.expected_ttk <= 0:
                continue
            if best is None or result.expected_ttk < best.ttk:
                best = KillEstimate(
                    monster=key,
                    style=style,
                    ttk=result.expected_ttk,
                    dps=result.dps,
                    max_hit=result.max_hit,
                    accuracy=result.accuracy,
                    match="exact" if key == name else "variant",
                )
    return best


def _on_task(loadout: Loadout) -> Loadout:
    """`loadout` with the slayer-task buff set, for black masks and helms."""
    return replace(loadout, buffs=replace(loadout.buffs, on_slayer_task=True))


def _slayer_target(target: Target) -> Target:
    """`target` marked as counting for a slayer assignment."""
    return replace(target, is_slayer_monster=True)


def price_monsters(
    chunk_info: ChunkInfo,
    picks: Mapping[str, str],
    levels: Mapping[str, int],
    monsters: Iterable[str],
    *,
    index: MonsterIndex | None = None,
    overhead: float = DEFAULT_OVERHEAD_SECONDS,
    slayer_monsters: frozenset[str] = frozenset(),
) -> dict[str, Rate]:
    """Kills-per-hour for `monsters`, as `Rate`s ready to merge.

    Returns only what it could price. A monster missing from the result is one
    the caller should leave to the scraped rate or the default - this never
    substitutes a guess, because a wrong kill time is indistinguishable from a
    right one once it reaches a total.

    The `Rate.source` is `dps`, and `Rate.match` carries `KillEstimate.match`
    so an estimate can show which numbers rest on a variant choice.
    """
    _require()
    monster_index = load_monster_index() if index is None else index
    loadouts = build_loadouts(chunk_info, picks, levels)
    if not loadouts:
        return {}

    rates: dict[str, Rate] = {}
    for name in monsters:
        kill = best_kill(
            loadouts,
            name,
            candidate_targets(monster_index, name),
            on_slayer_task=name in slayer_monsters,
        )
        if kill is None:
            continue
        kph = kill.kills_per_hour(overhead)
        if kph <= 0:
            continue
        rates[name] = Rate(value=kph, source="dps", match=kill.match)
    return rates


@dataclass(frozen=True)
class OverheadSample:
    """One monster where both a wiki rate and a computed kill time exist."""

    monster: str
    wiki_kph: float
    ttk: float
    #: `3600 / wiki_kph - ttk`. Negative means the computed fight is already
    #: slower than the wiki's whole cycle - see `measure_overhead`.
    overhead: float


def measure_overhead(
    chunk_info: ChunkInfo,
    picks: Mapping[str, str],
    levels: Mapping[str, int],
    wiki_rates: Mapping[str, Rate],
    *,
    index: MonsterIndex | None = None,
) -> tuple[OverheadSample, ...]:
    """Per-monster overhead implied by the wiki's own rates.

    For any monster the guides cover, `3600 / kph` is a full kill cycle and
    this module can compute the fighting part, so the difference is everything
    else. That is the appealing calibration: fit it where both numbers exist,
    apply it where only one does.

    **Read the samples before believing the fit.** The wiki's rates assume
    near-max gear and this project's `ttk` comes from chunk-restricted BiS, so
    the two are not the same fight. Where the map's gear is worse - which is
    the normal case, that being the point of the game mode - the computed
    `ttk` is longer than the wiki's whole cycle and the implied overhead comes
    out **negative**. A mean over those is meaningless.

    Doing this honestly needs the fighting time at *max* gear, which means a
    BiS pass over the whole equipment table rather than the unlocked subset.
    This function deliberately returns the raw samples rather than a single
    number, so that gap stays visible instead of being averaged away.
    """
    _require()
    monster_index = load_monster_index() if index is None else index
    loadouts = build_loadouts(chunk_info, picks, levels)
    if not loadouts:
        return ()

    samples: list[OverheadSample] = []
    for monster, rate in sorted(wiki_rates.items()):
        if rate.value <= 0:
            continue
        kill = best_kill(loadouts, monster, candidate_targets(monster_index, monster))
        if kill is None:
            continue
        samples.append(
            OverheadSample(
                monster=monster,
                wiki_kph=rate.value,
                ttk=kill.ttk,
                overhead=3600.0 / rate.value - kill.ttk,
            )
        )
    return tuple(samples)


__all__ = [
    "DEFAULT_OVERHEAD_SECONDS",
    "DPS_AVAILABLE",
    "MAGIC_DAMAGE_SCALE",
    "OFFENSIVE_STYLES",
    "DpsUnavailableError",
    "KillEstimate",
    "OverheadSample",
    "best_kill",
    "build_loadouts",
    "candidate_targets",
    "load_monster_index",
    "measure_overhead",
    "price_monsters",
]
