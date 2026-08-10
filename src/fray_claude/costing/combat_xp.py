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
from fray_claude.model.chunkinfo import ChunkInfo
from fray_claude.model.summary import _mapping
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

#: Seconds before a killed monster comes back. **An assumption, and the only
#: one here** - the export has no respawn timer and neither does
#: `infobox_monster`, so this is the ordinary NPC figure rather than a
#: measurement. It exists to stop a kill rate assuming an endless queue: a
#: chunk holding two of something cannot be farmed at 900 an hour whatever
#: the gear says. Where a map holds plenty of spawns the cap does not bind
#: and the number is unchanged.
RESPAWN_SECONDS = 30.0

#: Named areas whose monsters cannot be *farmed*, and so are not training
#: targets however reachable they are. A raid room is fought once per raid and
#: a wave minigame gives you each monster a fixed number of times per run, so
#: pricing either as "kill it, kill it again" describes nothing anyone can do.
#:
#: **Only combat training is affected.** These monsters stay in
#: `reachable_providers` and keep their drops priced, because you really can
#: get a twisted bow by doing the raid - what you cannot do is train Strength
#: on Muttadile. Excluding them globally would change item pricing, which is a
#: different and correct answer.
#:
#: Names are the export's own, checked against it: 21 monsters sit in
#: `Chambers of Xeric` on the benchmark map, 9 in `Inferno` and 7 in
#: `Fight Caves`. `dps_bridge.GROUP_BOSSES` already refuses a handful of these
#: by name for a related reason - a solo kill time for team content is not a
#: number worth having - and this is the same argument applied by *place*,
#: which catches the twenty-one rank-and-file monsters that list misses.
INSTANCED_AREAS: frozenset[str] = frozenset(
    {
        "Chambers of Xeric",
        "Theatre of Blood",
        "Tombs of Amascut",
        "Tombs of Amascut Lobby",
        "Inferno",
        "Fight Caves",
        "Gauntlet Lobby",
    }
)

#: Which BiS style trains which skill. Melee trains three, and which of the
#: three is a matter of the stance rather than the weapon.
STYLE_FOR_SKILL: dict[str, str] = {
    "Attack": "Melee",
    "Strength": "Melee",
    "Defence": "Melee",
    "Ranged": "Ranged",
    "Magic": "Magic",
}


def farmable_providers(derived: Derived) -> frozenset[str]:
    """Reachable monsters you could actually grind, for experience.

    A monster is dropped when **every** chunk it is reachable in is an
    instance - see `INSTANCED_AREAS`. "Every" rather than "any" on purpose:
    a lizardman shaman is in the Chambers of Xeric *and* in the Lizardman
    Temple, and the temple is a place you can stand.
    """
    farmable: set[str] = set()
    for monster in reachable_providers(derived):
        where = derived.source_index.monsters.get(monster)
        if where and all(chunk in INSTANCED_AREAS for chunk in where):
            continue
        farmable.add(monster)
    return frozenset(farmable)


def spawn_caps(
    chunk_info: ChunkInfo, derived: Derived, respawn: float = RESPAWN_SECONDS
) -> dict[str, float]:
    """`{monster: most kills an hour its spawns can supply}`.

    The export counts spawns per chunk (`chunks[id]["Monster"]`) and
    `SourceIndex.monsters` says which chunks are reachable, so the two give a
    ceiling without anything being invented except the respawn time. A monster
    with no counted spawn is absent rather than capped at zero - `skillItems`
    activities and superiors are reachable providers with no square of their
    own, and capping those at nothing would delete them.
    """
    caps: dict[str, float] = {}
    chunks = _mapping(chunk_info.data, "chunks")
    for monster, where in derived.source_index.monsters.items():
        spawns = 0.0
        for chunk in where:
            count = _mapping(chunks.get(chunk, {}), "Monster").get(monster)
            if isinstance(count, (int, float)) and not isinstance(count, bool):
                spawns += float(count)
        if spawns > 0 and respawn > 0:
            caps[monster] = spawns * 3600.0 / respawn
    return caps


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
    derived: Derived,
    heuristics: Heuristics,
    stats: Mapping[str, MonsterStats],
    caps: Mapping[str, float] | None = None,
) -> CombatTarget | None:
    """The reachable monster paying the most damage per hour, or `None`.

    Reachability is `reachable_providers`, the same gate every other bucket is
    held to, and a monster whose kill rate is only a default is passed over -
    see the module docstring on why a guessed rate must not be multiplied by
    real hitpoints.
    """
    best: CombatTarget | None = None
    for monster in sorted(farmable_providers(derived)):
        entry = stats.get(monster)
        if entry is None or entry.hitpoints <= 0:
            continue
        found = heuristics.kills_per_hour(monster)
        if found.value <= 0 or found.source.startswith("default"):
            continue
        cap = None if caps is None else caps.get(monster)
        rate = min(found.value, cap) if cap is not None and cap > 0 else found.value
        damage = rate * entry.hitpoints * entry.xp_multiplier
        if best is None or damage > best.damage_per_hour:
            best = CombatTarget(
                monster=monster,
                damage_per_hour=damage,
                kills_per_hour=rate,
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
    *,
    by_style: Mapping[str, Any] | None = None,
    caps: Mapping[str, float] | None = None,
) -> tuple[dict[str, Rate], dict[str, float]]:
    """An XP rate for each combat skill, or an empty dict if nothing is priced.

    **`by_style` is the good answer and the fallback is the rough one.** With
    the `dps` extra installed the caller passes `dps_bridge.price_combat`,
    which pairs the simulated kill rate with the health of the *version it
    simulated* and reports one target per style - so Ranged is priced on the
    map's bow rather than on its whip. Without it, one damage figure from the
    scraped kill rates serves all five skills, which flatters whichever style
    the map is worst at.

    `levels` decides only which spell Magic may cast; damage does not care
    what level you are.

    Returns the rates **and** the damage per hour behind each, which
    `hitpoints_credit` needs and cannot recover from a rate: Magic's rate is
    mostly casting experience, so dividing it back by 2 would overstate the
    damage by a factor of three.
    """
    fallback = best_target(derived, heuristics, stats, caps)
    styled = dict(by_style or {})
    if not styled and fallback is None:
        return {}, {}

    rated: dict[str, Rate] = {}
    damages: dict[str, float] = {}
    for skill, per_damage in COMBAT_SKILLS.items():
        found = styled.get(STYLE_FOR_SKILL.get(skill, ""))
        if found is not None:
            damage, monster = found.damage_per_hour, found.monster
        elif skill == "Hitpoints" and styled:
            # **Hitpoints comes off whatever you actually train**, so it takes
            # the best style rather than a style of its own.
            best = max(styled.values(), key=lambda rate: rate.damage_per_hour)
            damage, monster = best.damage_per_hour, best.monster
        elif fallback is not None:
            damage, monster = fallback.damage_per_hour, fallback.monster
        else:
            continue

        value = damage * per_damage
        source = f"combat:{monster}"
        if skill == "Magic":
            spell = best_spell(spells, levels.get("Magic", 1))
            if spell is not None:
                value += spell.experience * 3600.0 / CAST_SECONDS
                source = f"combat:{monster} casting {spell.name}"
        if value > 0:
            rated[skill] = Rate(value=value, source=source, match="computed")
            damages[skill] = damage
    return rated, damages


def slayer_credit(damage: float, needs: Mapping[str, float]) -> dict[str, float]:
    """Combat XP earned during the Slayer climb, allocated across its goals.

    **A Slayer task is a fight, and the estimate was charging for it twice.**
    `hitpoints_credit` deliberately left this out - its docstring says so - on
    the grounds that an under-estimate is the safe error. On the benchmark map
    the under-estimate is 353 of 1,263 skilling hours: 394 hours of Slayer
    deals 8.6M damage, which pays 11.5M Hitpoints XP against a climb needing
    8.7M, and 34.6M to the attacking styles against a Defence climb needing
    12.8M. All three were being priced in full beside the Slayer hours that
    had already earned them.

    **Slayer XP is damage.** A task monster pays Slayer experience equal to its
    hitpoints, so a Slayer rate in XP per hour *is* a damage rate and needs no
    separate model - which is what makes this a credit rather than a guess.

    Two different sharing rules, because the game has two:

    - **Hitpoints is free alongside.** Every point of damage pays it 1.33
      whatever style dealt the damage, so it is never in competition with
      anything and is credited in full up to what the climb still needs.
    - **The attacking skills compete**, because a kill is dealt in one style.
      So it is the *damage* that is shared out, not the experience, and each
      skill converts its share at its own rate - which is how Magic's 2 per
      damage stays honest against melee's 4 rather than being averaged in.

    Allocated **smallest remaining need first**, which is deterministic (so
    `--jobs` cannot move it) and matches the plan's `w_s = 1 while below goal`:
    finishing the cheap goals first is what maximises the number of goals a
    fixed quantity of damage closes. Every allocation respecting the caps is
    realisable by a player switching styles as each goal lands, so this is a
    choice among correct answers rather than an approximation of one.

    `needs` is the XP each skill still wants *after* quest grants. Returns the
    XP to credit per skill, never more than the need and never more than the
    damage can pay.
    """
    credit: dict[str, float] = {}
    if damage <= 0:
        return credit

    hitpoints = needs.get("Hitpoints", 0.0)
    if hitpoints > 0:
        credit["Hitpoints"] = min(hitpoints, HITPOINTS_XP_PER_DAMAGE * damage)

    remaining = damage
    attacking = sorted(
        (
            (need, skill)
            for skill, need in needs.items()
            if skill != "Hitpoints" and need > 0
        )
    )
    for need, skill in attacking:
        if remaining <= 0:
            break
        per_damage = MAGIC_XP_PER_DAMAGE if skill == "Magic" else XP_PER_DAMAGE
        spent = min(remaining, need / per_damage)
        credit[skill] = spent * per_damage
        remaining -= spent
    return credit


def hitpoints_credit(hours: Mapping[str, float], damage: Mapping[str, float]) -> float:
    """Hitpoints XP earned for free while training the other combat skills.

    **Hitpoints is not a climb you make; it is one that happens to you.** Every
    point of damage that pays 4 XP to Strength pays 1.33 to Hitpoints at the
    same moment, so charging for both climbs bills the same hours twice. On the
    benchmark map that was 231 hours of Hitpoints sitting behind 100 hours of
    melee that had already earned most of it.

    `hours` is what each of the other five combat skills costs and `damage`
    is the damage per hour its style deals, so their product is the damage
    that will be dealt anyway. This does **not** subtract non-combat training:
    a Slayer climb also pays Hitpoints, and leaving that out keeps the credit
    an under-estimate rather than an over-one.

    Same shape as `quest_xp_grants`: XP that arrives from elsewhere, taken off
    the front of the climb rather than netted off the hours.
    """
    return sum(
        hours.get(skill, 0.0) * damage.get(skill, 0.0) * HITPOINTS_XP_PER_DAMAGE
        for skill in COMBAT_SKILLS
        if skill != "Hitpoints"
    )
