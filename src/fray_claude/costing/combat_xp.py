"""Combat experience, which is damage and almost nothing else.

**The skills that had no training method at all.** `Attack`, `Strength`,
`Defence`, `Hitpoints` and `Ranged` have zero `Primary: true` challenges
anywhere in the export - there is no "Train Attack" task to join a rate to -
so `fray estimate` had nothing to price them with. They were reported as
`unpriced_skills`, which is honest but unhelpful: on the benchmark map Strength
60 -> 75 was the single largest line left, at the 1,000/hr floor.

They do not need a training method, because combat experience is a published
constant times a number this project already computes. From the wiki's Combat
article:

- **4 experience per point of damage** in melee and Ranged combat styles.
- **2 experience per point of damage** in Magic - *not* 4, which is the easy
  mistake and a factor of two on the whole climb.
- **1.33 experience per point of damage** to Hitpoints, alongside whichever of
  the above you were training.
- A cast pays the **spell's base experience as well**, whether or not it hits.
  That is not a rounding term: Fire Surge is 50.5 xp a cast against roughly 24
  xp of damage, so two thirds of a Magic rate is the casting.
- Some monsters multiply all of it. `remote/combat.py` reads the percentage;
  361 monsters have a non-zero one and the rest are 1x.

And damage per hour is `kills_per_hour * hitpoints`, both already here:
`Heuristics.kills_per_hour` is the layered rate every other bucket spends, and
the hitpoints come from `infobox_monster`. **So this improves automatically
with the `dps` extra** - `dps_bridge.enrich` replaces the kill rates with ones
simulated from the map's own BiS gear, and these rates follow without knowing
the extra exists.

Three things worth knowing before quoting a number:

- **One damage figure serves all five skills.** `kills_per_hour` does not say
  which style did the killing, so the Magic rate assumes you kill as fast with
  a spell as with a whip. That flatters Magic on a map with good melee gear.
  Correcting it needs a per-style DPS, which `dps_bridge` could give and this
  deliberately does not ask for yet.
- **A monster with only a *default* kill rate is refused.** `kills_per_hour`
  falls back to a per-kind constant, and multiplying a guessed rate by real
  hitpoints produces a confident-looking fabrication. The same rule
  `training_options` already applies to `default` scraped rates.
- **Hitpoints is double counted against whatever else you train**, because in
  the game it is free. Pricing the climbs separately overstates the total by
  however much they overlap; taking it off would need the same treatment quest
  XP got, and is a scheduling question rather than a rate one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from fray_claude.costing.heuristics import Heuristics, Rate
from fray_claude.costing.levels import reachable_providers
from fray_claude.derive.pipeline import Derived
from fray_claude.remote.combat import AttackSpell, MonsterStats

#: Experience per point of damage, by the skill the style trains.
XP_PER_DAMAGE = 4.0
MAGIC_XP_PER_DAMAGE = 2.0
HITPOINTS_XP_PER_DAMAGE = 4.0 / 3.0

#: The skills this prices, and the multiplier each takes.
COMBAT_SKILLS: dict[str, float] = {
    "Attack": XP_PER_DAMAGE,
    "Strength": XP_PER_DAMAGE,
    "Defence": XP_PER_DAMAGE,
    "Ranged": XP_PER_DAMAGE,
    "Magic": MAGIC_XP_PER_DAMAGE,
    "Hitpoints": HITPOINTS_XP_PER_DAMAGE,
}

#: Ticks between autocasts, which is the standard spell speed. Only Magic
#: needs it, and only for the base-xp half of the rate.
CAST_TICKS = 5
CAST_SECONDS = CAST_TICKS * 0.6


@dataclass(frozen=True)
class CombatTarget:
    """The monster a combat skill would be trained on, and how fast."""

    monster: str
    damage_per_hour: float
    kills_per_hour: float
    hitpoints: float
    xp_multiplier: float = 1.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "monster": self.monster,
            "damage_per_hour": round(self.damage_per_hour, 1),
            "kills_per_hour": round(self.kills_per_hour, 2),
            "hitpoints": self.hitpoints,
            "xp_multiplier": self.xp_multiplier,
        }


def best_target(
    derived: Derived, heuristics: Heuristics, stats: Mapping[str, MonsterStats]
) -> CombatTarget | None:
    """The reachable monster paying the most damage per hour, or `None`.

    Reachability is `reachable_providers`, the same gate every other bucket is
    held to, and a monster whose kill rate is only a default is passed over -
    see the module docstring on why a guessed rate must not be multiplied by
    real hitpoints.
    """
    best: CombatTarget | None = None
    for monster in sorted(reachable_providers(derived)):
        entry = stats.get(monster)
        if entry is None or entry.hitpoints <= 0:
            continue
        rate = heuristics.kills_per_hour(monster)
        if rate.value <= 0 or rate.source.startswith("default"):
            continue
        damage = rate.value * entry.hitpoints * entry.xp_multiplier
        if best is None or damage > best.damage_per_hour:
            best = CombatTarget(
                monster=monster,
                damage_per_hour=damage,
                kills_per_hour=rate.value,
                hitpoints=entry.hitpoints,
                xp_multiplier=entry.xp_multiplier,
            )
    return best


def best_spell(spells: Sequence[AttackSpell], magic_level: int) -> AttackSpell | None:
    """The highest-paying spell castable at `magic_level`.

    By experience rather than by level: the two mostly agree, but Fire Surge
    (95, 50.5) pays less than Ice Barrage (94, 52) and picking "the highest
    level I can cast" would quietly take the worse one.
    """
    castable = [spell for spell in spells if spell.level <= magic_level]
    if not castable:
        return None
    return max(castable, key=lambda spell: (spell.experience, -spell.level, spell.name))


def combat_rates(
    derived: Derived,
    heuristics: Heuristics,
    stats: Mapping[str, MonsterStats],
    spells: Sequence[AttackSpell],
    levels: Mapping[str, int],
) -> dict[str, Rate]:
    """An XP rate for each combat skill, or an empty dict if nothing is priced.

    `levels` decides only which spell Magic may cast; every other skill's rate
    is level-independent, because damage is.
    """
    target = best_target(derived, heuristics, stats)
    if target is None:
        return {}

    rated: dict[str, Rate] = {}
    for skill, per_damage in COMBAT_SKILLS.items():
        value = target.damage_per_hour * per_damage
        source = f"combat:{target.monster}"
        if skill == "Magic":
            spell = best_spell(spells, levels.get("Magic", 1))
            if spell is not None:
                value += spell.experience * 3600.0 / CAST_SECONDS
                source = f"combat:{target.monster} casting {spell.name}"
        if value > 0:
            rated[skill] = Rate(value=value, source=source, match="computed")
    return rated
