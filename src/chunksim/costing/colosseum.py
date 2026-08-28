"""The Fortis Colosseum: eleven waves of a fixed roster, then Sol Heredit,
then a chest that pays out on however far the run got.

**The same shape `costing/tzhaar.py` is, with one real difference.** Both
are a wave schedule the export files as a monster with a drop table -
`Rewards Chest (Fortis Colosseum)` is absent from `drops` entirely, exactly
like `Chest (Barrows)` and `Lunar Chest` - but unlike the Fight Caves and
the Inferno, the Colosseum publishes a real money-making guide with a real
`kph`, so `RUN_SECONDS` here is a guide figure rather than
`costing/tzhaar.py`'s own maintainer's band.

### The roster is a floor, not the whole schedule

`Fortis Colosseum/Strategies`' own wave breakdown gives eleven waves' base
composition - the Fremennik Warband trio (`Fremennik warband berserker`/
`seer`/`archer`, one each, every wave but the twelfth), plus `Serpent
shaman` on waves 1-6, `Javelin Colossus` and `Manticore` escalating through
the run, `Shockwave Colossus` from wave 7. **What is not in `WAVE_ROSTER`
is the 40-second reinforcement timer**: "If the player does not complete a
wave within 40 seconds, additional enemy reinforcements will arrive" -
`Jaguar warrior` on waves 1-6, an extra `Serpent shaman` on waves 4-6 and
10-11, more of everything else. How many of those a run fights depends on
how long the run takes, which is what this model computes - the same
circularity `costing/tzhaar.py`'s `ZUK_ROOM` states for wave 69's repeating
spawns - so this counts only the guaranteed base roster and calls the
result a **ceiling on the speed**, not an expectation, for the same reason.

### Sol Heredit needs no script

`osrs_dps` carries `Sol Heredit` as one bare key at `hitpoints=1500`,
matching `Fortis Colosseum/Strategies`' own "Phase 1 (100% HP, 1500 HP)" -
no `#`-suffixed sub-phases the way the Hydra or Zulrah have. His published
mechanics (the grapple, the light beams, the enrage engulfing below 150 HP)
punish a slow kill rather than forcing a real zero-damage window the way
the Nightmare's totems or the Alchemical Hydra's vents do - nothing states a
duration a player is locked out of attacking for - so, exactly like Araxxor
and Cerberus (`costing/dps_bridge.SCRIPTS`'s own docstring), this is a
considered refusal to script him rather than an oversight: there is no
published downtime to spend a `Phase.reduced_seconds` on.

### The chest: progressive, but this model prices the full clear

A real run can bank loot and stop after any wave; this module only answers
for reaching wave 12; matching `costing/theatre.py`'s and
`costing/xeric.py`'s own convention of pricing the guide's own assumed
scenario rather than a strategy choice.

**`item_seconds` takes `overrides`, the same seam `raids.item_seconds` and
`tzhaar.item_seconds` use.** `run(kill_seconds)` above builds a real
DPS-modelled `Encounter` from this map's own gear and levels, but nothing
in this module ever spent it before this - `PUBLISHED_SECONDS` alone priced
every chest reward regardless of account, the exact "150/hour default"
shape `costing/brimstone.py`'s own docstring names, just with a guide
figure standing in for the missing model instead of `DEFAULT_KPH`.
`costing/inputs.py`'s `_colosseum_run_seconds` is `_tzhaar_run_seconds`'s
own twin: it feeds the sequencer's answer in as `overrides[FORTIS_COLOSSEUM]`
and floors it at `RUN_SECONDS` - a real published pace, not a looser
deadline the way Chambers Challenge's own guide entry is, so a computed run
should never be trusted over it, matching `_tzhaar_run_seconds`'s own
choice rather than `_raid_run_seconds`'s world-record exception.

`Money making guide/Completing the Fortis Colosseum (Wave 12)` states `kph = 2.5` - a 1,440-second run - and
its own `Output` fields already sum the wave-by-wave unique odds from
`[[Rewards Chest (Fortis Colosseum)]]` for a full clear, so
the chances below are transcribed from that arithmetic rather than
re-derived: `0.0416` (`1/24.06`) for any one specific piece of `Sunfire
fanatic armour` (matches the page's own "cumulative drop rate of any piece
... approximately 1/8.43" divided three ways, allowing for its own
duplicate-avoidance rounding), `0.0121` (`1/83.2`) for `Tonalztics of ralos
(uncharged)`, matching the page's stated `1/83.61`, and `0.0831` (`1/12.0`)
for at least one `Echo crystal`, matching its stated `1/12.44` - the small
gaps in all three are the guide's own rounding on the per-wave fractions
this project summed exactly, not a disagreement about the mechanic.

**`Dizana's quiver` is not a chance - "completing wave 12 will guarantee
[[Dizana's quiver]]"** - so it costs exactly one full clear, not an
expected-runs division by a rate.

**The pet is two rolls, not one, for `costing/tzhaar.py`'s exact reason.**
"A flat 1/200 chance for the pet Smol Heredit is rolled" on every completed
run, and the guaranteed quiver "can later be given to Minimus for... another
1/200 chance". A player keeps their first quiver to close that collection
log entry and trades every one after, so a completed run is two independent
1/200 rolls once the quiver itself is owned - `1 - (1 - 1/200)^2`, matching
`tzhaar.pet_chance`'s own formula and its own note that which one is kept is
immaterial at the scale this project prices over.

**`Sunfire splinters` is guaranteed, not a rate** - wave 1 alone drops 80
unconditionally - so it is priced as one run rather than `runs / chance`.

Pure: `FightPlan`/`PuzzlePlan` construction only, no `osrs_dps` import.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from chunksim.costing import encounter
from chunksim.costing.encounter import EXPERIENCE, FightPlan, KillSeconds, Objective, PuzzlePlan, UNIQUE

FORTIS_COLOSSEUM = "Fortis Colosseum"

#: Upstream's own challenge for the chest's loot.
LOOT_TASK = "Fortis Colosseum loot*"

#: Sol Heredit's own key - see the module docstring on why he needs no
#: script.
FINAL_BOSS = "Sol Heredit"

#: The eleven regular waves' *guaranteed* roster - see the module docstring
#: on why the 40-second reinforcement timer is excluded. Every count here is
#: `Fortis Colosseum/Strategies`' own wave-breakdown list, summed by monster.
WAVES = 11

WAVE_ROSTER: Mapping[str, int] = {
    "Fremennik warband berserker": 11,
    "Fremennik warband seer": 11,
    "Fremennik warband archer": 11,
    "Serpent shaman": 6,
    "Javelin Colossus": 13,
    "Manticore": 11,
    "Shockwave Colossus": 3,
}

#: Guessed - see `costing/tzhaar.py`'s `PER_WAVE_SECONDS` for the same
#: shape: nothing publishes how long the pre-wave modifier choice, the
#: arena reset and the walk to spawns cost, and one constant across eleven
#: waves stands in for eleven unknowns.
PER_WAVE_SECONDS = 8.0

#: Share of a run spent attacking. Guessed, one number across the whole run
#: for `costing/tzhaar.py`'s own reason.
UPTIME = 0.75

#: `Money making guide/Completing the Fortis Colosseum (Wave 12)`: `kph =
#: 2.5` - a full clear including Sol Heredit.
PUBLISHED_RUNS_PER_HOUR = 2.5
PUBLISHED_SECONDS = 3600.0 / PUBLISHED_RUNS_PER_HOUR
RUN_SECONDS = PUBLISHED_SECONDS

#: `Sunfire fanatic helm`/`cuirass`/`chausses`, `Tonalztics of ralos
#: (uncharged)`, `Echo crystal` (at least one) - the guide's own summed
#: wave-by-wave arithmetic for a full clear. See the module docstring for
#: the cross-check against `[[Rewards Chest (Fortis Colosseum)]]`'s own
#: cumulative figures.
ARMOUR_PIECE_CHANCE = 0.04155461736811242
TONALZTICS_CHANCE = 0.012013399663596939
ECHO_CRYSTAL_CHANCE = 0.08310923473622484

ARMOUR_PIECES: tuple[str, ...] = (
    "Sunfire fanatic helm", "Sunfire fanatic cuirass", "Sunfire fanatic chausses",
)

#: Published on `[[Rewards Chest (Fortis Colosseum)]]`: a flat roll per
#: completed run.
PET_CHANCE_PER_ROLL = 1.0 / 200.0

#: The quiver is exchangeable for a second pet roll - see the module
#: docstring, matching `costing/tzhaar.py`'s `EXCHANGE_ROLL`.
EXCHANGE_ROLL = True


def pet_chance() -> float:
    """One completed run's chance at `Smol Heredit`, both rolls counted -
    `costing/tzhaar.pet_chance`'s own formula."""
    if PET_CHANCE_PER_ROLL <= 0.0:
        return 0.0
    return 1.0 - (1.0 - PET_CHANCE_PER_ROLL) ** (2 if EXCHANGE_ROLL else 1)


def item_chances() -> dict[str, float]:
    """`{item: chance one full clear gives it}`. `Dizana's quiver` and
    `Sunfire splinters` are here too, at `1.0` - both are guaranteed rather
    than a rate ("completing wave 12 will guarantee Dizana's quiver", wave 1
    alone drops splinters unconditionally), and `1.0` is not a special case
    to either `encounter.expected_runs` or `encounter.runs_for_all`: one run
    is exactly what both already compute for a certainty.
    """
    found = {item: ARMOUR_PIECE_CHANCE for item in ARMOUR_PIECES}
    found["Tonalztics of ralos (uncharged)"] = TONALZTICS_CHANCE
    found["Echo crystal"] = ECHO_CRYSTAL_CHANCE
    found["Smol heredit"] = pet_chance()
    found["Dizana's quiver (uncharged)"] = 1.0
    found["Sunfire splinters"] = 1.0
    return found


def plans() -> tuple[FightPlan | PuzzlePlan, ...]:
    """One run: the eleven-wave roster, Sol Heredit, and the per-wave
    overhead as a single puzzle - matching `costing/tzhaar.py`'s own shape."""
    found: list[FightPlan | PuzzlePlan] = [
        FightPlan(name=target, target=target, count=count)
        for target, count in WAVE_ROSTER.items()
    ]
    found.append(FightPlan(name=FINAL_BOSS, target=FINAL_BOSS))
    found.append(
        PuzzlePlan(name="between waves", seconds=PER_WAVE_SECONDS * (WAVES + 1))
    )
    return tuple(found)


def mechanics() -> dict[str, encounter.Mechanic]:
    """`UPTIME` against every fight in the run, Sol Heredit included."""
    note = "share of a Colosseum run spent attacking"
    found = {target: encounter.Mechanic(uptime=UPTIME, note=note) for target in WAVE_ROSTER}
    found[FINAL_BOSS] = encounter.Mechanic(uptime=UPTIME, note=note)
    return found


def run(kill_seconds: KillSeconds) -> encounter.Encounter | None:
    """One completed run, or `None` if something in it cannot be priced."""
    return encounter.build(FORTIS_COLOSSEUM, plans(), kill_seconds, mechanics())


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
    """`objective` priced against a full wave-12 clear, or `None` if
    something in the run cannot be priced."""
    built = run(kill_seconds)
    if built is None:
        return None
    chances = item_chances()
    if objective.kind == UNIQUE:
        runs = encounter.expected_runs(chances.get(objective.item, 0.0))
    elif objective.kind == EXPERIENCE:
        # **Not answered here rather than answered badly**, matching every
        # other encounter module's refusal - see `costing/combat_xp.py`.
        return None
    else:
        # The quiver and the splinters bind every run; the log is closed by
        # whichever of the rate-limited drops is slowest.
        runs = encounter.runs_for_all(list(chances.values()))
    return Answer(run=built, runs=runs)


def run_seconds(overrides: Mapping[str, float] = {}) -> float:
    """How long one completed run takes, correction applied -
    `costing/tzhaar.run_seconds`'s own shape, minus its `variant` key since
    the Colosseum has only the one.

    `overrides` is `Heuristics.run_seconds`: empty (published pace only) for
    the goal walk, built before any DPS-derived rate exists;
    `costing/inputs.py`'s `_colosseum_run_seconds` once the post-enrichment
    walk asks. A hand correction in `runs` still wins over either, by the
    same merge order `tzhaar.run_seconds`'s own docstring describes.
    """
    got = overrides.get(FORTIS_COLOSSEUM)
    if isinstance(got, (int, float)) and not isinstance(got, bool) and got > 0:
        return float(got)
    return RUN_SECONDS


def item_seconds(overrides: Mapping[str, float] = {}) -> dict[str, float]:
    """`{item: seconds}` for the item walk, at `run_seconds(overrides)` - see
    `costing/raids.item_seconds` for the shape this mirrors."""
    run = run_seconds(overrides)
    return {
        item: run / chance
        for item, chance in item_chances().items()
        if chance > 0
    }


def activity_for(item: str) -> str | None:
    """`FORTIS_COLOSSEUM` if `item` is one of the chest's own rewards, else
    `None` - `costing/tzhaar.activity_for`'s exact shape, matched
    case-insensitively for the same reason that module's docstring gives.
    """
    wanted = item.lower()
    return FORTIS_COLOSSEUM if wanted in {name.lower() for name in item_chances()} else None
