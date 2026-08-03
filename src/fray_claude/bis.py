"""Best-in-slot equipment synthesis per combat style and slot.

Port of `calcBIS` (worker.js:5232-8381, ~3,150 lines) - upstream's runtime
synthesis of `BiS` challenges, which have no static definition anywhere in
`chunkinfo.json` (see `challenges.py`'s module docstring for why
`calc_challenges` never populates `valid['BiS']`).

Per this project's semantics (agreed with the user, since BiS is inherently
non-monotonic - a later chunk can make a *better* item available for a slot
someone already filled): this module recomputes the best achievable item per
(style, slot) fresh from a given state, rather than accumulating task
history. `unlock.py`/`simulate.py` diff two `compute_bis` calls to report
which slots improved, kept separate from their monotonic `new_tasks` set.

For each (style, slot) this maximizes a style-specific stat (the scoring
functions collected in `StyleSpec`) over items that are both reachable
(present in the passed-in item index) and wearable - the "candidate gates"
section below: `_requirements_ok` for skill requirements, `_task_unlocks_ok`,
`_consumable_ok`, and `_source_reachable`, the same "don't require training a
skill just to wield its output" gate `challenges.py` applies to combat
`Items` requirements. Ties are first-seen-wins; it then resolves
2H-vs-(1H+shield) and emits an "Obtain a/an X" task name/label per winner.

Deliberately not ported (documented, not silently wrong):
- The set-effect DPS override chain (worker.js:6444-8182, ~1,738 lines: Void,
  Obsidian, Inquisitor, Verac's, Crystal, Karil's set bonuses) - a
  self-contained sub-algorithm, out of scope for this increment.
- Ties-as-alternates (`bestEquipmentAlts`) and the greedy set-cover dedup
  pass (worker.js:8321-8379) that lets one item cover several styles - this
  module picks a single first-seen winner per (style, slot) instead. The
  *ordering* half of that is modelled though: already-obtained equipment is
  iterated first (`_order_completed_first`), so a tie resolves to gear you
  already have rather than proposing an identical item you don't.
- The `Show Best in Slot 1H and 2H` rule's dual weapon/2h emission: a 2H
  winner always *replaces* the weapon+shield slots here (upstream's rule-off
  behaviour); the rule-on case, which additionally keeps the 1H alternative
  under a second `ammo (2h)` pseudo-slot, is not modelled.
- Full `checkPrimaryMethod`/`slayerLocked` (see `sources.py`'s
  `_slayer_skill_items_for` docstring). Skill-requirement gating here is
  `_has_any_valid` - "the skill has *a* valid challenge". Note this is
  **weaker than `challenges.py`'s own gate**, which stopped sharing it once
  `_check_primary_method` was ported: a skill that is untrainable but still
  holds valid `Level 1` challenges passes here and fails there, so an
  equipment candidate can be admitted whose `Items` requirement the same
  skill would refuse.
- `ProcessingSource` (zero uses in the real export this was built against)
  and `Multi Step Processing`. Upstream keeps a separate ammo variant of the
  source-quality gate differing only in the `ProcessingSource` clause; since
  that flag is unused in practice, one shared `_source_reachable` suffices.
- The `Wield Crafted Items Override` re-entry fixpoint (worker.js:355), where
  a fresh `calcBIS` result feeds back into re-running `calcChallenges`.

One upstream bug is reproduced rather than "fixed", since fixing it would be
an undocumented behaviour change: the ammo tie-break upstream uses compares
`ability_damage`, a field present on 0 of 2,247 real `equipment` entries, so
it is always `undefined === undefined`. This module doesn't score ammo ties
at all (first-seen-wins via `>`, not `>=`, on `ranged_strength`), which
produces the same winner upstream's always-true tie-break would, without
needing to replicate the bug's alt-registration side effect (which this
module doesn't track anyway - see "ties-as-alternates" above).

Three details that each cost a wrong answer before they were right:

- **Candidates come from `ChallengeResult.available_items`, not
  `SourceIndex.items`.** The narrow index omits anything obtainable only by
  *making* it - `Granite ring (i)` exists solely as an imbue challenge's
  `Output`. Feeding challenge outputs in moved 19 of 43 picks and took the
  oracle from 4/6 to 5/6. (`boosts.py` hit the identical trap.)
- **2H-vs-(1H+shield) scores both sides with the *weapon* formula**, the
  shield's offensive stats summed into the 1H side and the weapon's own
  `attack_speed` retained; ties go to 1H+shield. Scoring the shield with the
  *armour* formula instead compares a DPS-scale number against one scaled by
  100000, so 1H+shield won unconditionally and every 2H pick was wrongly
  deleted - which is what made this module miss `Webweaver bow (u)` and
  invent an `Odium ward` pick for a slot a 2H bow should have removed.
- **The `ammo` slot is set from whatever pairs with the *winning launcher***,
  not picked independently, and is deleted when that weapon takes no ammo -
  otherwise a Melee build is told to go and obtain javelins.

Multiple styles picking the same item join their labels with upstream's
literal `_STYLE_SEPARATOR` (a slash plus U+200B).

**The oracle is real and load-bearing.** The cached map's
`chunkinfo.activeTasks.BiS` records upstream's own last-computed picks, and
`tests/test_bis.py`'s opt-in oracle test asserts **all six** of them
(including the Melee weapon `Abyssal whip`, reached via the
`skillItems.Slayer` route in `sources.py`). Every one of the six started out
mismatched, and each mismatch turned out to be a distinct real bug - unported
area unlocks, challenge `Output` items not reaching BiS, unported
`skillItems`-via-`Output`, and unhonoured `backloggedSources`. Treat a
mismatch there as a defect, not as oracle staleness; an earlier stage of this
project wrongly explained five of them away that way.

`BisResult` splits `tasks` into `completed` (already obtained, cross-
referenced against `completedChallenges.BiS` merged with
`checkedChallenges.BiS`, whose task-name keys match `bis_task_name`'s own
output format) and `active` (not yet obtained), plus `outdated`: a completed
pick whose slot has since been beaten by something better, resolved back to
an item via `_formatted_name_index` (`formatted_name -> (item, slot)`, built
from `equipment`). For *display* it also carries `slots` (task name -> slot,
covering `tasks` and `outdated` alike, since `picks`' packed
`"{style}-{slot}"` keys can't be reached from a task name) and
`current_chunk` - the subset of `completed`/`outdated` still sitting in
`checkedChallenges`, i.e. banked during the chunk in play rather than an
earlier one. `bis_display_name` renders the pair as `[<slot>] Obtain a
granite ring (i)`, suffixed `CURRENT_CHUNK_SUFFIX` for the current chunk, and
`display_sorted` floats those to the top. `current_chunk` is intersected with
what the result actually shows, so a checked entry naming neither a current
pick nor a resolvable outdated one is left out rather than sitting unmatched.

`_formatted_name_index` lowercases both sides on purpose: the same item can
be stored under two spellings over time (`Craw's bow (u)` interned vs. a
literal `craw's bow (u)`), so real data can carry an apparent duplicate for
one item. Two bugs here were found only by checking against live data rather
than fixtures - a completed 2H-slot item was never flagged outdated
(`_finalize_slots` folds a 2H winner into the `weapon` key in `picks`, and
the lookup wasn't normalised the same way), and `completed` came back empty
entirely because `BiS` was wrongly skipping `t_N` resolution.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from fray_claude.challenges import (
    CURRENT_CHUNK_SUFFIX,
    _PROCESSING_SKILLS,
    _has_any_valid,
    strip_task_markup,
)
from fray_claude.chunkinfo import ChunkInfo
from fray_claude.summary import _mapping

_VOWELS = frozenset("aeiou")
_UNARMED_SOURCES: dict[str, str] = {"Built-in": "secondary-Nonskill"}
_DEFENCE_STATS = ("defence_crush", "defence_magic", "defence_ranged", "defence_slash", "defence_stab")
#: Upstream's multi-style label join (worker.js:8210): a slash followed by a
#: ZERO WIDTH SPACE (U+200B), not a plain "/" - invisible but load-bearing,
#: since upstream's own renderer splits on this exact sequence.
_STYLE_SEPARATOR = "/​"


def _stat(equip: Mapping[str, Any], key: str) -> float:
    value = equip.get(key)
    return float(value) if isinstance(value, (int, float)) else 0.0


def _total_defence(equip: Mapping[str, Any]) -> float:
    return sum(_stat(equip, key) for key in _DEFENCE_STATS)


def _is_weapon(equip: Mapping[str, Any]) -> bool:
    """`attack_speed > 0` is upstream's own discriminator - it's `0` on
    every armour entry in the real export, never a real speed there."""
    return _stat(equip, "attack_speed") > 0


# --- style scoring functions (worker.js:5290-6219's 19 near-identical
# blocks, collapsed to one function pair per style) -------------------------


def _melee_weapon(e: Mapping[str, Any], ammo: float) -> float:
    best = max(_stat(e, "attack_crush"), _stat(e, "attack_slash"), _stat(e, "attack_stab"))
    return (best + _stat(e, "melee_strength") + 64) / _stat(e, "attack_speed")


def _melee_armour(e: Mapping[str, Any], ammo: float) -> float:
    total = _stat(e, "attack_crush") + _stat(e, "attack_slash") + _stat(e, "attack_stab")
    return 100000 * _stat(e, "melee_strength") + 1000 * total + _total_defence(e)


def _melee_style_weapon(stat_key: str) -> Callable[[Mapping[str, Any], float], float]:
    def score(e: Mapping[str, Any], ammo: float) -> float:
        return (_stat(e, stat_key) + _stat(e, "melee_strength") + 64) / _stat(e, "attack_speed")

    return score


def _melee_style_armour(stat_key: str) -> Callable[[Mapping[str, Any], float], float]:
    def score(e: Mapping[str, Any], ammo: float) -> float:
        return 100000 * _stat(e, "melee_strength") + 1000 * _stat(e, stat_key) + _total_defence(e)

    return score


def _ranged_weapon(e: Mapping[str, Any], ammo: float) -> float:
    return (_stat(e, "attack_ranged") + _stat(e, "ranged_strength") + ammo + 64) / (
        _stat(e, "attack_speed") - 1
    )


def _ranged_armour(e: Mapping[str, Any], ammo: float) -> float:
    return 100000 * _stat(e, "ranged_strength") + 1000 * _stat(e, "attack_ranged") + _total_defence(e)


def _magic_weapon(e: Mapping[str, Any], ammo: float) -> float:
    return 1000 * _stat(e, "magic_damage") + _stat(e, "attack_magic")


def _magic_armour(e: Mapping[str, Any], ammo: float) -> float:
    return 100000 * _stat(e, "magic_damage") + 1000 * _stat(e, "attack_magic") + _total_defence(e)


def _prayer_score(e: Mapping[str, Any], ammo: float) -> float:
    return _stat(e, "prayer")


def _melee_tank_score(e: Mapping[str, Any], ammo: float) -> float:
    return _total_defence(e)


def _tank_score(stat_key: str) -> Callable[[Mapping[str, Any], float], float]:
    def score(e: Mapping[str, Any], ammo: float) -> float:
        return _stat(e, stat_key)

    return score


def _flinch_weapon(e: Mapping[str, Any], ammo: float) -> float:
    best = max(_stat(e, "attack_crush"), _stat(e, "attack_slash"), _stat(e, "attack_stab"))
    return best + _stat(e, "melee_strength")


def _flinch_armour(e: Mapping[str, Any], ammo: float) -> float:
    total = _stat(e, "attack_crush") + _stat(e, "attack_slash") + _stat(e, "attack_stab")
    return 1000 * _stat(e, "melee_strength") + total


def _melee_style_flinch_weapon(stat_key: str) -> Callable[[Mapping[str, Any], float], float]:
    def score(e: Mapping[str, Any], ammo: float) -> float:
        return _stat(e, stat_key) + _stat(e, "melee_strength")

    return score


def _melee_style_flinch_armour(stat_key: str) -> Callable[[Mapping[str, Any], float], float]:
    def score(e: Mapping[str, Any], ammo: float) -> float:
        return 1000 * _stat(e, "melee_strength") + _stat(e, stat_key)

    return score


def _weight_score(e: Mapping[str, Any], ammo: float) -> float:
    return -_stat(e, "weight")


@dataclass(frozen=True)
class StyleSpec:
    """One combat style: a name (used in task labels/keys, spaces kept for
    the label but stripped to `_` for the `{style}-{slot}` pick key, matching
    upstream's `skill.replaceAll(' ', '_')`), a weapon and an armour scoring
    function, and whether/when it's enabled.
    """

    name: str
    weapon_score: Callable[[Mapping[str, Any], float], float]
    armour_score: Callable[[Mapping[str, Any], float], float]
    requires_weight: bool = False
    requires_positive_score: bool = False


_BASE_STYLES = (
    StyleSpec("Melee", _melee_weapon, _melee_armour),
    StyleSpec("Ranged", _ranged_weapon, _ranged_armour),
    StyleSpec("Magic", _magic_weapon, _magic_armour),
)
_MELEE_SUBSTYLES = (
    StyleSpec("Stab", _melee_style_weapon("attack_stab"), _melee_style_armour("attack_stab")),
    StyleSpec("Slash", _melee_style_weapon("attack_slash"), _melee_style_armour("attack_slash")),
    StyleSpec("Crush", _melee_style_weapon("attack_crush"), _melee_style_armour("attack_crush")),
)
_TANK_STYLES = (
    StyleSpec("Melee Tank", _melee_tank_score, _melee_tank_score),
    StyleSpec("Ranged Tank", _tank_score("defence_ranged"), _tank_score("defence_ranged")),
    StyleSpec("Magic Tank", _tank_score("defence_magic"), _tank_score("defence_magic")),
)
_MELEE_TANK_SUBSTYLES = (
    StyleSpec("Stab Tank", _tank_score("defence_stab"), _tank_score("defence_stab")),
    StyleSpec("Slash Tank", _tank_score("defence_slash"), _tank_score("defence_slash")),
    StyleSpec("Crush Tank", _tank_score("defence_crush"), _tank_score("defence_crush")),
)
_FLINCH_STYLES = (StyleSpec("Flinch", _flinch_weapon, _flinch_armour),)
_MELEE_FLINCH_SUBSTYLES = (
    StyleSpec(
        "Stab Flinch",
        _melee_style_flinch_weapon("attack_stab"),
        _melee_style_flinch_armour("attack_stab"),
    ),
    StyleSpec(
        "Slash Flinch",
        _melee_style_flinch_weapon("attack_slash"),
        _melee_style_flinch_armour("attack_slash"),
    ),
    StyleSpec(
        "Crush Flinch",
        _melee_style_flinch_weapon("attack_crush"),
        _melee_style_flinch_armour("attack_crush"),
    ),
)
_PRAYER_STYLE = StyleSpec("Prayer", _prayer_score, _prayer_score, requires_positive_score=True)
_WEIGHT_STYLE = StyleSpec("Weight Reducing", _weight_score, _weight_score, requires_weight=True)


def active_styles(rules: Mapping[str, Any]) -> list[StyleSpec]:
    """Port of `combatStyles` construction (worker.js:5233-5260): Melee/
    Ranged/Magic are always active; the rest are gated by `rules['Show Best
    in Slot ... Tasks']`, and the melee-family styles (base/Tank/Flinch)
    each split into Stab/Slash/Crush when `Show Best in Slot Melee Style
    Tasks` is on.
    """
    melee_split = rules.get("Show Best in Slot Melee Style Tasks") is True
    styles: list[StyleSpec] = list(_MELEE_SUBSTYLES if melee_split else _BASE_STYLES[:1])
    styles.append(_BASE_STYLES[1])
    styles.append(_BASE_STYLES[2])
    if rules.get("Show Best in Slot Prayer Tasks") is True:
        styles.append(_PRAYER_STYLE)
    if rules.get("Show Best in Slot Defensive Tasks") is True:
        styles.extend(_MELEE_TANK_SUBSTYLES if melee_split else _TANK_STYLES[:1])
        styles.append(_TANK_STYLES[1])
        styles.append(_TANK_STYLES[2])
    if rules.get("Show Best in Slot Flinching Tasks") is True:
        styles.extend(_MELEE_FLINCH_SUBSTYLES if melee_split else _FLINCH_STYLES)
    if rules.get("Show Best in Slot Weight Tasks") is True:
        styles.append(_WEIGHT_STYLE)
    return styles


# --- candidate gates (worker.js:5310-5312's `validWearable`, and the
# combat/`BIS Skilling` source-quality gate shared with `challenges.py`) ----


def _requirements_ok(
    equip: Mapping[str, Any],
    *,
    rules: Mapping[str, Any],
    max_skill: Mapping[str, int],
    passive_skill: Mapping[str, int],
    valid: Mapping[str, Mapping[str, Any]],
) -> bool:
    requirements = equip.get("requirements")
    if not isinstance(requirements, dict):
        return True
    for skill, level in requirements.items():
        if not isinstance(level, (int, float)) or level <= 1:
            continue
        if rules.get("Skiller") is True:
            return False
        if not _has_any_valid(skill, valid):
            passive_level = passive_skill.get(skill)
            if not (isinstance(passive_level, (int, float)) and passive_level >= level):
                return False
        cap = max_skill.get(skill)
        if isinstance(cap, (int, float)) and cap < level:
            return False
    return True


def _task_unlocks_ok(
    item_name: str, task_unlocks_items: Mapping[str, Any], valid: Mapping[str, Mapping[str, Any]]
) -> bool:
    """Port of the `taskUnlocks.Items` gate (worker.js:5311): every listed
    `{task_name: task_skill}` unlock must already be valid.
    """
    entries = task_unlocks_items.get(item_name)
    if not isinstance(entries, list):
        return True
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for task_name, task_skill in entry.items():
            if task_name not in valid.get(task_skill, {}):
                return False
    return True


def _consumable_ok(equip: Mapping[str, Any], sources: Mapping[str, str], rules: Mapping[str, Any]) -> bool:
    if rules.get("Consumable Primary BiS") is not True or equip.get("is_consumable") is not True:
        return True
    return any(not tag.startswith("secondary-") for tag in sources.values())


def _source_reachable(
    sources: Mapping[str, str], *, rules: Mapping[str, Any], challenges: Mapping[str, Mapping[str, Any]]
) -> bool:
    """Port of the combat source-quality gate (worker.js:4067-4082, the same
    mechanic `challenges.py`'s `_source_quality_ok` implements for `Items`
    requirements): an item is usable if at least one of its sources is *not*
    a plain skill-training output - don't require training a skill just to
    wield its product - unless `Wield Crafted Items` is on, the training
    skill is Slayer, or the source challenge is `NoXp`.
    """
    for source_name, tag in sources.items():
        skill = tag.partition("-")[2]
        if (
            "-" not in tag
            or skill not in _PROCESSING_SKILLS
            or rules.get("Wield Crafted Items") is True
            or skill == "Slayer"
        ):
            return True
        challenge = challenges.get(skill, {}).get(source_name)
        if isinstance(challenge, dict) and challenge.get("NoXp") is True:
            return True
    return False


CandidateCheck = Callable[[str, Mapping[str, Any], Mapping[str, str]], bool]


# --- ammo pairing (worker.js:5334-5367's weapon-ammo resolution) -----------


def build_ammo_index(ammo_tools: Mapping[str, Any]) -> dict[str, list[str]]:
    """Invert `codeItems.ammoTools` (`ammo -> {weapon: True}`) to
    `weapon -> [compatible ammo]`, once - upstream rescans the whole table
    per candidate weapon (202 entries), an easy order-of-magnitude to avoid.
    """
    index: dict[str, list[str]] = {}
    for ammo_name, weapons in ammo_tools.items():
        if ammo_name == "No ammo" or not isinstance(weapons, dict):
            continue
        for weapon_name in weapons:
            index.setdefault(weapon_name, []).append(ammo_name)
    return index


def _best_ammo(
    weapon_name: str,
    ammo_index: Mapping[str, list[str]],
    *,
    equipment: Mapping[str, Mapping[str, Any]],
    items: Mapping[str, Mapping[str, str]],
    candidate_ok: CandidateCheck,
) -> tuple[str | None, bool]:
    """Best reachable ammo for `weapon_name` by `ranged_strength`
    (first-seen-wins on ties), and whether the weapon needs ammo at all - a
    weapon with compatible ammo listed but none reachable is unusable for
    Ranged (worker.js:5365-5367).
    """
    candidates = ammo_index.get(weapon_name)
    if not candidates:
        return None, False
    best_name: str | None = None
    best_strength = float("-inf")
    for ammo_name in candidates:
        equip = equipment.get(ammo_name)
        sources = items.get(ammo_name)
        if not isinstance(equip, dict) or sources is None or not candidate_ok(ammo_name, equip, sources):
            continue
        strength = _stat(equip, "ranged_strength")
        if strength > best_strength:
            best_strength = strength
            best_name = ammo_name
    return best_name, True


# --- per-style, per-slot winner selection ----------------------------------

#: slot -> (item name, ammo name or None, score)
_SlotWinners = dict[str, tuple[str, "str | None", float]]


def _best_for_style(
    style: StyleSpec,
    *,
    equipment: Mapping[str, Mapping[str, Any]],
    items: Mapping[str, Mapping[str, str]],
    ammo_index: Mapping[str, list[str]],
    candidate_ok: CandidateCheck,
) -> _SlotWinners:
    """Best item per slot for one style - first-seen-wins on ties, since
    Python dicts preserve `equipment`'s JSON insertion order the same way
    `Object.keys` does upstream.
    """
    winners: _SlotWinners = {}
    for item_name, equip in equipment.items():
        if style.requires_weight and "weight" not in equip:
            continue
        sources = items.get(item_name)
        if sources is None or not candidate_ok(item_name, equip, sources):
            continue
        slot = equip.get("slot")
        if not isinstance(slot, str):
            continue

        ammo_name: str | None = None
        ammo_strength = 0.0
        if style.name == "Ranged" and _is_weapon(equip):
            ammo_name, needs_ammo = _best_ammo(
                item_name, ammo_index, equipment=equipment, items=items, candidate_ok=candidate_ok
            )
            if needs_ammo and ammo_name is None:
                continue
            if ammo_name is not None:
                ammo_strength = _stat(equipment[ammo_name], "ranged_strength")

        score_fn = style.weapon_score if _is_weapon(equip) else style.armour_score
        score = score_fn(equip, ammo_strength)
        if style.requires_positive_score and score <= 0:
            continue

        current = winners.get(slot)
        if current is None or score > current[2]:
            winners[slot] = (item_name, ammo_name, score)
    return winners


def _combined_weapon_shield(
    weapon: Mapping[str, Any], shield: Mapping[str, Any]
) -> dict[str, Any]:
    """Weapon stats with the shield's summed in, keeping the *weapon's*
    `attack_speed` - upstream divides the combined offence by the weapon's
    speed, not the shield's (worker.js:6228)."""
    combined: dict[str, Any] = dict(weapon)
    for key, value in shield.items():
        if key == "attack_speed" or not isinstance(value, (int, float)):
            continue
        base = combined.get(key)
        combined[key] = (base if isinstance(base, (int, float)) else 0) + value
    return combined


def _finalize_slots(
    winners: _SlotWinners, style: StyleSpec, equipment: Mapping[str, Mapping[str, Any]]
) -> dict[str, tuple[str, "str | None"]]:
    """Port of the 2H-vs-(1H+shield) shootout (worker.js:6220-6443): compare
    the 2H slot's score against weapon+shield combined; the winner replaces
    both. Ties go to 1H+shield (`>`, not `>=`). The `Show Best in Slot 1H
    and 2H` rule's dual-emission case (keeping both under `ammo (2h)`) isn't
    modelled - see the module docstring.

    The `ammo` slot is **not** an independent pick. Upstream overwrites it
    with `bestAmmoSaved[<winning launcher slot>]` - the ammo paired with
    whichever weapon actually won - and deletes it outright when that
    launcher takes none (worker.js:6430-6443). Treating ammo as its own
    argmax produced items no setup could use: a Melee build was told to
    obtain javelins, and a Ranged build the highest-`ranged_strength` ammo
    in the game rather than something its bow can fire.
    """
    two_h = winners.get("2h")
    weapon = winners.get("weapon")
    shield = winners.get("shield")
    result: dict[str, tuple[str, str | None]] = {
        slot: (item, ammo)
        for slot, (item, ammo, _score) in winners.items()
        if slot not in ("2h", "weapon", "shield", "ammo")
    }
    def ammo_strength(name: str | None) -> float:
        return _stat(equipment.get(name or "", {}), "ranged_strength")

    def power(equip: Mapping[str, Any], ammo: str | None) -> float:
        # Both sides are scored with the *weapon* formula. Summing the
        # shield's armour score onto the 1H side instead - as this used to -
        # compares a DPS-scale number against an armour score scaled by
        # 100000, so 1H+shield won almost unconditionally, wrongly deleting
        # every 2H pick (and with it the shield slot's real competitor).
        if not _is_weapon(equip):
            return 0.0
        return style.weapon_score(equip, ammo_strength(ammo))

    two_h_power = (
        power(equipment.get(two_h[0], {}), two_h[1]) if two_h is not None else float("-inf")
    )
    if weapon is None:
        weapon_shield_power = 0.0
    else:
        weapon_equip: Mapping[str, Any] = equipment.get(weapon[0], {})
        if shield is not None:
            weapon_equip = _combined_weapon_shield(weapon_equip, equipment.get(shield[0], {}))
        weapon_shield_power = power(weapon_equip, weapon[1])
    if two_h is not None and two_h_power > weapon_shield_power:
        result["weapon"] = (two_h[0], two_h[1])
        paired_ammo = two_h[1]
    else:
        paired_ammo = weapon[1] if weapon is not None else None
        if weapon is not None:
            result["weapon"] = (weapon[0], weapon[1])
        if shield is not None:
            result["shield"] = (shield[0], None)
    if paired_ammo is not None:
        result["ammo"] = (paired_ammo, None)
    return result


# --- task name/label generation (worker.js:5368-5369, 8208-8235) -----------


def format_equip(equip: Mapping[str, Any], item_name: str) -> str:
    """Port of `formatEquip`: an item's `formatted_name` override, or its
    lowercased name."""
    formatted = equip.get("formatted_name")
    return formatted if isinstance(formatted, str) else item_name.lower()


def article_for(name: str) -> str:
    """Port of the `a`/`an`/plural article logic (worker.js:5368-5369),
    verbatim including its quirks: computed from the *raw* name (not
    `format_equip`'d), first-letter-only (no `an hour`-style exceptions),
    and overridden to a bare `' '` when the name is plural (ends in `s`, or
    ends in `)` with the pre-`(` segment ending in `s`).
    """
    lower = name.lower()
    if lower.endswith("s"):
        return " "
    if lower.endswith(")"):
        pre_paren = lower.split("(", 1)[0].strip()
        if pre_paren.endswith("s"):
            return " "
    return " an " if lower[:1] in _VOWELS else " a "


def bis_task_name(item_name: str, equip: Mapping[str, Any]) -> str:
    return f"Obtain{article_for(item_name)}~|{format_equip(equip, item_name)}|~"


_TASK_ITEM_PATTERN = re.compile(r"~\|(.+?)\|~")

def bis_display_name(task_name: str, slot: str | None = None, *, current_chunk: bool = False) -> str:
    """Render a BiS task for a terminal: `Obtain a ~|granite ring (i)|~`
    becomes `[ring] Obtain a granite ring (i)`.

    `slot` comes from `BisResult.slots`; it's omitted only for a task whose
    item no longer resolves to an equipment entry. `current_chunk` appends
    `CURRENT_CHUNK_SUFFIX` to separate what was ticked off during the chunk
    in play from what earlier chunks already banked.
    """
    text = strip_task_markup(task_name)
    if slot:
        text = f"[{slot}] {text}"
    if current_chunk:
        text = f"{text} {CURRENT_CHUNK_SUFFIX}"
    return text


def _formatted_name_index(equipment: Mapping[str, Mapping[str, Any]]) -> dict[str, tuple[str, str]]:
    """`format_equip`'d, lowercased display name -> `(item_name, slot)` -
    lets an `Obtain a/an ~|X|~` task name, as found in
    `completedChallenges.BiS`, be resolved back to the equipment entry it
    names. Lowercased on both sides deliberately: the same item can appear
    under two spellings across time, since a name interned into
    `tasksMap.json` keeps the casing `formatEquip` produced then, while a
    not-yet-interned one is stored literally - real map data has both
    `Craw's bow (u)` and `craw's bow (u)` for the same item.
    """
    index: dict[str, tuple[str, str]] = {}
    for item_name, equip in equipment.items():
        slot = equip.get("slot")
        if isinstance(slot, str):
            index[format_equip(equip, item_name).lower()] = (item_name, slot)
    return index


def _outdated_notes(
    completed_bis: Mapping[str, Any],
    tasks: Mapping[str, str],
    picks: Mapping[str, str],
    equipment: Mapping[str, Mapping[str, Any]],
) -> dict[str, tuple[str, str]]:
    """A `completed_bis` entry whose item no longer matches the current pick
    for its slot in *any* style - i.e. a better item has since become
    reachable, so the player's gear there is outdated. Only checked for
    entries absent from the current `tasks` view entirely; a still-current
    completed item is simply in both `completed` and `tasks`, needing no note.

    Returns `task_name -> (note, slot)`; the slot is the *outdated* item's
    own (2h-normalised) slot, which `compute_bis` folds into
    `BisResult.slots` so these entries display like any other pick.
    """
    index = _formatted_name_index(equipment)
    notes: dict[str, tuple[str, str]] = {}
    for task_name in completed_bis:
        if task_name in tasks:
            continue
        match = _TASK_ITEM_PATTERN.search(task_name)
        if match is None:
            continue
        resolved = index.get(match.group(1).lower())
        if resolved is None:
            continue
        old_item, slot = resolved
        # `_finalize_slots` always folds a winning "2h" item into the
        # "weapon" key - "2h" itself never appears in `picks` - so an old
        # 2h item's slot must be normalised the same way to compare.
        slot = "weapon" if slot == "2h" else slot
        upgrades: dict[str, str] = {}
        for style_slot, item in picks.items():
            style, _, key_slot = style_slot.rpartition("-")
            if key_slot == slot and item != old_item:
                upgrades[style] = item
        if upgrades:
            note = ", ".join(f"{style}: {item}" for style, item in sorted(upgrades.items()))
            notes[task_name] = (f"superseded by {note}", slot)
    return notes


def _order_completed_first(
    equipment: Mapping[str, Mapping[str, Any]], completed_bis: Mapping[str, Any]
) -> dict[str, Mapping[str, Any]]:
    """Iterate already-obtained equipment first, so an exact scoring tie
    resolves to gear the player already has.

    Ties are decided first-seen-wins (see `_best_for_style`), and upstream
    builds its candidate pool as `{...completedEquipment, ...equipment}` -
    completed items ahead of the export's own order. Skipping this was a
    real mismatch: `Defence cape(t)` and `Hitpoints cape(t)` have byte-identical
    stats, as do `Amulet of glory` and `Amulet of avarice`, and in each pair
    the export happens to list the *unobtained* one first - so this module
    kept proposing an item you'd gain nothing by getting, while upstream
    correctly reported the slot as already filled.
    """
    index = _formatted_name_index(equipment)
    completed_names: list[str] = []
    for task_name in completed_bis:
        match = _TASK_ITEM_PATTERN.search(task_name)
        if match is None:
            continue
        resolved = index.get(match.group(1).lower())
        if resolved is not None and resolved[0] in equipment:
            completed_names.append(resolved[0])
    # `{**a, **b}` keeps a's key positions for duplicates, so the completed
    # names stay at the front while every entry still maps to its real data.
    return {**{name: equipment[name] for name in completed_names}, **equipment}


@dataclass(frozen=True)
class BisResult:
    """`picks["{style}-{slot}"] = item_name` (style spaces replaced by `_`,
    matching upstream's `highestOverallLocal` key shape) is the structural
    view `unlock.py`/`simulate.py` diff to report which slots improved.
    `tasks[task_name] = label` is the full current-picks display view (every
    style's winner, regardless of completion). `completed`/`active` split
    `tasks` against `completed_bis` (`completedChallenges.BiS`, passed into
    `compute_bis`): completed picks the player has already obtained versus
    ones still to get - upstream's own `calcBIS(completedOnly)` distinction.
    `outdated` flags a `completed_bis` entry whose slot has since been beaten
    by something better, per `_outdated_notes`. `label` joins every style
    that picked the same (slot, item) with upstream's `'/' + U+200B`
    separator (worker.js:8210) when more than one style shares a winner.

    `slots[task_name] = slot` is the display counterpart to `picks`' packed
    `"{style}-{slot}"` keys: the same slot, reachable from a task name alone,
    covering `tasks` and `outdated` alike so `bis_display_name` can prefix
    either. `current_chunk` holds the subset of `completed`/`outdated` names
    obtained during the chunk in play (`checkedChallenges`, not yet migrated
    into `completedChallenges` - see `pipeline.load_map_state`), which is
    what separates "banked this chunk" from "banked at some point earlier".
    """

    picks: dict[str, str]
    tasks: dict[str, str] = field(default_factory=dict)
    completed: dict[str, str] = field(default_factory=dict)
    active: dict[str, str] = field(default_factory=dict)
    outdated: dict[str, str] = field(default_factory=dict)
    slots: dict[str, str] = field(default_factory=dict)
    current_chunk: frozenset[str] = frozenset()

    def display_name(self, task_name: str) -> str:
        """`task_name` rendered for a terminal, with its slot prefix and, if
        it was obtained this chunk, the `(Active Task)` suffix."""
        return bis_display_name(
            task_name,
            self.slots.get(task_name),
            current_chunk=task_name in self.current_chunk,
        )

    def display_sorted(self, task_names: Iterable[str]) -> list[str]:
        """`task_names` as display strings, this chunk's acquisitions first
        and each group alphabetical within itself."""
        return [
            self.display_name(name)
            for name in sorted(task_names, key=lambda n: (n not in self.current_chunk, n))
        ]

    def as_dict(self) -> dict[str, Any]:
        return {
            "picks": self.picks,
            "tasks": self.tasks,
            "completed": self.completed,
            "active": self.active,
            "outdated": self.outdated,
            "slots": self.slots,
            "current_chunk": sorted(self.current_chunk),
        }


def compute_bis(
    chunk_info: ChunkInfo,
    items: Mapping[str, Mapping[str, str]],
    valid: Mapping[str, Mapping[str, Any]],
    *,
    rules: Mapping[str, Any],
    max_skill: Mapping[str, int] | None = None,
    passive_skill: Mapping[str, int] | None = None,
    completed_bis: Mapping[str, Any] | None = None,
    checked_bis: Mapping[str, Any] | None = None,
) -> BisResult:
    """Compute the best-achievable item per (style, slot) for the current
    state. `items` should be the same `SourceIndex.items` ordinary
    challenges use; `valid` is `ChallengeResult.valid`, consulted by the
    skill-requirement and task-unlock gates. `completed_bis` is
    `MapState.completed_challenges.get("BiS", {})` - already-obtained BiS
    items, splitting the result into `completed`/`active` (see `BisResult`).

    `checked_bis` is the un-merged `MapState.checked_challenges.get("BiS")`,
    i.e. the part of `completed_bis` banked during the chunk in play. It only
    ever labels output (`BisResult.current_chunk`); every completion gate
    here reads `completed_bis`, which already subsumes it.
    """
    max_skill = max_skill or {}
    passive_skill = passive_skill or {}
    completed_bis = completed_bis or {}
    checked_bis = checked_bis or {}
    equipment = _order_completed_first(_mapping(chunk_info.data, "equipment"), completed_bis)
    ammo_index = build_ammo_index(_mapping(chunk_info.code_items, "ammoTools"))
    task_unlocks_items = _mapping(_mapping(chunk_info.data, "taskUnlocks"), "Items")
    challenges = chunk_info.challenges
    if "Unarmed" not in items:
        items = {**items, "Unarmed": _UNARMED_SOURCES}

    def candidate_ok(item_name: str, equip: Mapping[str, Any], sources: Mapping[str, str]) -> bool:
        return (
            _requirements_ok(equip, rules=rules, max_skill=max_skill, passive_skill=passive_skill, valid=valid)
            and _task_unlocks_ok(item_name, task_unlocks_items, valid)
            and _consumable_ok(equip, sources, rules)
            and _source_reachable(sources, rules=rules, challenges=challenges)
        )

    picks: dict[str, str] = {}
    by_slot_item: dict[tuple[str, str], list[str]] = {}
    for style in active_styles(rules):
        winners = _best_for_style(
            style, equipment=equipment, items=items, ammo_index=ammo_index, candidate_ok=candidate_ok
        )
        for slot, (item_name, _ammo) in _finalize_slots(winners, style, equipment).items():
            picks[f"{style.name.replace(' ', '_')}-{slot}"] = item_name
            by_slot_item.setdefault((slot, item_name), []).append(style.name)

    tasks: dict[str, str] = {}
    slots: dict[str, str] = {}
    for (slot, item_name), styles in by_slot_item.items():
        equip = equipment.get(item_name, {})
        task_name = bis_task_name(item_name, equip)
        tasks[task_name] = _STYLE_SEPARATOR.join(styles) + " BiS " + slot
        slots[task_name] = slot

    completed = {name: label for name, label in tasks.items() if name in completed_bis}
    active = {name: label for name, label in tasks.items() if name not in completed_bis}
    outdated_notes = _outdated_notes(completed_bis, tasks, picks, equipment)
    outdated = {name: note for name, (note, _slot) in outdated_notes.items()}
    slots.update({name: slot for name, (_note, slot) in outdated_notes.items()})
    return BisResult(
        picks=picks,
        tasks=tasks,
        completed=completed,
        active=active,
        outdated=outdated,
        slots=slots,
        # Restricted to names this result actually shows: a `checkedChallenges`
        # entry for an item that is neither a current pick nor a resolvable
        # outdated one has nowhere to be labelled.
        current_chunk=frozenset(checked_bis) & (frozenset(completed) | frozenset(outdated)),
    )
