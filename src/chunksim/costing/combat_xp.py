"""Combat experience, which is damage and almost nothing else.

**The skills that had no training method at all.** `Attack`, `Strength`,
`Defence`, `Hitpoints` and `Ranged` have zero `Primary: true` challenges
anywhere in the export - there is no "Train Attack" task to join a rate to -
so `chunksim estimate` had nothing to price them with. They were reported as
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

**One rate for the whole climb was the next thing wrong with it.** `combat_
rates` prices at `goals` - the levels the chunk *ends* at - so Attack on Angry
Bear read 95,361/hr flat from level 1 to 99, when the accuracy behind that
number is plainly a function of the Attack level being trained: real
combat gets faster as it goes, and the estimate said otherwise.
`combat_curves` is the fix, **for the skills whose own level actually moves
the number** (`CURVED_SKILLS` - Attack, Strength, Ranged, Magic): it re-asks
`dps_bridge.combat_curve` for the same already-chosen fight at every level
1-99 of the skill in question, holding everything else at `goals`, and hands
back a real band per level rather than one snapshot. Defence and Hitpoints
are deliberately left flat - neither skill's own level touches accuracy or
max hit, so a curve for either would be a slope invented rather than found.
Needs the `dps` extra the same as everything else here: without it
`combat_curves` is simply never called and every combat skill reads exactly
as flat as it always has.

**Every error this model has had was in what the constant was multiplied by,
never in the constant.** So the four things worth knowing are all about the
fight rather than the arithmetic:

- **The styles are priced separately**, because the experience depends on
  which one you use. With the `dps` extra the caller passes
  `dps_bridge.price_combat`, which reports one target per style - so Ranged is
  priced on the map's bow rather than on its whip - and pairs each kill rate
  with the health of the *version it simulated*. Without the extra, one damage
  figure serves all five skills, which flatters whichever style the map is
  worst at. See `combat_rates`.
- **Reachable is not farmable.** A raid room is fought once per raid, so a
  monster reachable only inside an instance cannot be ground for experience -
  see `farmable_providers` and `INSTANCED_AREAS`. The gate gets combat
  training *only*: excluding those monsters from item pricing would change a
  different and correct answer.
- **Nothing waits for the next monster unless something makes it.** A 2-health
  monster is one you would run out of, so `spawn_caps` reads the export's own
  per-chunk spawn counts and caps the rate at what they can supply. The
  respawn time is the one assumption in the file.
- **A monster with only a *default* kill rate is refused.** `kills_per_hour`
  falls back to a per-kind constant, and multiplying a guessed rate by real
  hitpoints produces a confident-looking fabrication. The same rule
  `training_options` already applies to `default` scraped rates.

**Hitpoints and Slayer are credits, not climbs priced beside the others.**
Every point of damage pays Hitpoints 1.33 whatever style dealt it, and a
Slayer climb's XP per hour *is* a damage rate - so charging for those hours
separately bills the same fighting twice. `slayer_credit` shares the damage
out (it runs first, so `hitpoints_credit` sees the hours actually left), and
both take the XP off the front of the climb the way `quest_xp_grants` does.
Nothing upstream records what a shared climb ought to cost, so
`tests/test_combat_xp.py` pins invariants rather than numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from chunksim.costing import instanced
from chunksim.costing.heuristics import ComputedMethod, Heuristics, Rate
from chunksim.costing.levels import reachable_providers
from chunksim.derive.pipeline import Derived
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.model.summary import _mapping
from chunksim.remote.combat import AttackSpell, MonsterStats

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

#: **Moved to `costing/instanced.py`**, which is now the one place that knows
#: which places are runs and what killing one's boss costs. It was a frozenset
#: of seven *names* here, and the export files the same place under a numbered
#: square too - fourteen of them - so a map holding `9551` rather than
#: `Fight Caves` trained on Tz-Kih. Re-exported under the old name because
#: `costing/prayer.py`'s docstring cites it and a reader following that
#: reference should land somewhere.
INSTANCED_AREAS = instanced.RUN_ONLY_PLACES

#: Which BiS style trains which skill. Melee trains three, and which of the
#: three is a matter of the stance rather than the weapon.
STYLE_FOR_SKILL: dict[str, str] = {
    "Attack": "Melee",
    "Strength": "Melee",
    "Defence": "Melee",
    "Ranged": "Ranged",
    "Magic": "Magic",
}


def farmable_providers(derived: Derived, chunk_info: ChunkInfo) -> frozenset[str]:
    """Reachable monsters you could actually grind, for experience.

    A monster is dropped when **every** chunk it is reachable in is part of a
    run - `costing/instanced.run_only`, which is now the one place that test
    lives. "Every" rather than "any" on purpose: a lizardman shaman is in the
    Chambers of Xeric *and* in the Lizardman Temple, and the temple is a place
    you can stand.

    **`chunk_info` is why this takes an argument it used to do without.** The
    membership test was against a frozenset of seven *names*, and the export
    files the same place under a numbered square too - fourteen of them - so a
    map holding `9551` rather than `Fight Caves` trained on Tz-Kih. See
    `instanced.place_ids`.
    """
    places = instanced.place_ids(chunk_info)
    farmable: set[str] = set()
    for monster in reachable_providers(derived):
        where = derived.source_index.monsters.get(monster)
        if where and instanced.run_only(where, places):
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
    chunk_info: ChunkInfo | None = None,
) -> CombatTarget | None:
    """The reachable monster paying the most damage per hour, or `None`.

    **`chunk_info` is optional and should not be**, which is the honest state
    of this seam: without it `farmable_providers` resolves no numbered squares
    and a map holding `9551` rather than `Fight Caves` reads Tz-Kih as
    farmable. Every production caller passes one - `costing/inputs.py` does -
    and the default exists so the hand-built fixtures in
    `tests/test_combat_xp.py` need not carry an export to ask about two
    monsters. See `instanced.place_ids`.

    Reachability is `reachable_providers`, the same gate every other bucket is
    held to, and a monster whose kill rate is only a default is passed over -
    see the module docstring on why a guessed rate must not be multiplied by
    real hitpoints.
    """
    best: CombatTarget | None = None
    for monster in sorted(farmable_providers(derived, chunk_info or ChunkInfo({}))):
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
    chunk_info: ChunkInfo | None = None,
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
    fallback = best_target(derived, heuristics, stats, caps, chunk_info)
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


#: Skills whose own level measurably changes outgoing damage. Defence and
#: Hitpoints affect only what a monster does to *you*, or how much health you
#: have - neither touches your accuracy or your max hit, so a curve for
#: either would be inventing a slope nothing in the combat formulas produces.
#: A flat rate for those two is the honest shape, not a gap this project has
#: not gotten to yet - see `combat_curves`, which builds one for everything
#: else.
CURVED_SKILLS = frozenset({"Attack", "Strength", "Ranged", "Magic"})


def combat_curves(
    styled: Mapping[str, Any],
    curve: Callable[[str, str, str], Mapping[int, float]],
    spells: Sequence[AttackSpell],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """A real climb for `CURVED_SKILLS`, off the target `styled` already
    chose - a flat `Attack` rate on Angry Bear was the whole reason this
    exists: accuracy genuinely improves as Attack rises, and the estimate
    said otherwise.

    **One already-chosen target scaling with level, not a search for a
    better one at each level.** `curve` is `dps_bridge.combat_curve` bound to
    the rest of its arguments by the caller - see that function's own
    docstring for what asking it means and what it does not attempt (a
    different monster taking over partway up the climb).

    `styled` is `dps_bridge.price_combat`'s own `{style: CombatRate}` -
    typed loosely, like `combat_rates`'s own `by_style`, so this module still
    does not import `dps_bridge` and stays exactly as usable without the
    `dps` extra as it always has: an empty `styled` (no extra installed)
    finds nothing for any skill and returns `{}`, and `combat_rates`'s flat
    figure is all `costing/inputs.py` has to merge in, unchanged.

    Every band spends the same mechanics `combat_rates` uses for its own flat
    figure - the same `per_damage` multiplier, the same Magic spell bonus -
    so a reader comparing the two never finds them disagreeing about what a
    skill's rate is made of, only about whether it is one number or several.
    A band's `method` carries the spell name for Magic, exactly as
    `combat_rates`'s own `source` already does - a climb through Fire Bolt,
    then Fire Wave, then Ice Barrage is genuinely three different actions,
    not one method sampled three times.
    """
    found: dict[str, tuple[ComputedMethod, ...]] = {}
    for skill in CURVED_SKILLS:
        rate = styled.get(STYLE_FOR_SKILL[skill])
        if rate is None:
            continue
        damage_by_level = curve(rate.monster, STYLE_FOR_SKILL[skill], skill)
        if not damage_by_level:
            continue
        per_damage = COMBAT_SKILLS[skill]
        bands: list[ComputedMethod] = []
        for level in sorted(damage_by_level):
            value = damage_by_level[level] * per_damage
            method = rate.monster
            if skill == "Magic":
                spell = best_spell(spells, level)
                if spell is not None:
                    value += spell.experience * 3600.0 / CAST_SECONDS
                    method = f"{rate.monster} casting {spell.name}"
            if value <= 0:
                continue
            bands.append(
                ComputedMethod(
                    method=method,
                    xp_per_hour=value,
                    level=level,
                    match="computed",
                    knob=f"monster_stats/{rate.monster}",
                )
            )
        if bands:
            found[skill] = tuple(bands)
    return found


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
