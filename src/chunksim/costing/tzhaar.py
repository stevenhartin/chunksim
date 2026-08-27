"""The Fight Caves and the Inferno: one wave schedule, two rosters.

**A wave minigame is a run, not a monster**, and the export files it as a
monster. `TzKal-Zuk` carries the `Jal-nib-rek` drop at 1/100, so
`Heuristics.kills_per_hour` fell back to `DEFAULT_KPH` and the item walk read
**twenty Zuk kills an hour** - the pet at 5.0 hours, when each kill is a
forty-to-sixty minute Inferno from wave 1 and a hundred of them is closer to
eighty hours. That is `costing/raids.py`'s defect exactly, one activity over,
and it is fixed the same way: price the goal as the run it actually is.

### The two are the same schedule

The Inferno is "a successor to the TzHaar Fight Cave", and the wave tables say
so more precisely than the prose does. Count each minigame's rank-and-file
across every wave:

| tier | Fight Caves | n | Inferno | n |
|---|---|---|---|---|
| 1 | `Tz-Kih` (bat) | 48 | `Jal-MejRah` (bat) | 48 |
| 2 | `Tz-Kek` (blob) | 40 | `Jal-Ak` (blob) | 40 |
| 3 | `Tok-Xil` (ranger) | 36 | `Jal-ImKot` (meleer) | 36 |
| 4 | `Yt-MejKot` (meleer) | 34 | `Jal-Xil` (ranger) | 34 |
| 5 | `Ket-Zek` (mager) | 33 | `Jal-Zek` (mager) | 33 |

**Identical, and the roles do not match** - the third monster introduced is a
ranger in the caves and a meleer in the Inferno, the fourth the other way
round. So what the two share is the *escalation*, one more tier every so many
waves, not the creatures filling it. That is why this is one module with two
rosters rather than two modules that would have duplicated the schedule and
then drifted.

The Inferno spreads the same five tiers over 66 waves where the caves use 62,
and adds three of its own: wave 67 is one `JalTok-Jad`, 68 is three, 69 is
`TzKal-Zuk`. It also puts three `Jal-Nib` in almost every wave, which is 210
of them - a tenth of the run's fighting on this map's gear, and the single
biggest difference between the two rosters.

### A multiset, not an ordering

**The per-wave breakdown is deliberately not carried.** A run's duration is a
sum over everything it kills plus a per-wave cost, and a sum does not care
what order the terms arrive in - so the published tables are reduced to their
totals here and `tests/test_costing_tzhaar.py` pins those totals against the
counts read off the wiki.

What that costs is real and worth stating: **nothing per-wave can be
modelled** - not that early waves are faster than late ones, not a death on
wave 50 costing more than one on wave 5, not the pillars. A model wanting any
of those needs the ordering back, and the wave tables are on the wiki.

### What a run kills that the wave table does not list

Four spawn mechanics add monsters no wave announces, all published, all folded
into the roster counts here:

- Every `Tz-Kek` (level 45) splits into **two** level-22 ones when it dies:
  40 becomes 80 more.
- Every `Jal-Ak` splits into **three** smaller ones, one per attack style:
  40 becomes 120.
- `TzTok-Jad` summons four `Yt-HurKot` at half health. `JalTok-Jad` summons
  five, or **three** on waves 68 and 69 - so the Inferno's four Jads summon
  5 + 3 + 3 + 3 = 14 between them.
- `TzKal-Zuk` summons four `Jal-MejJak` below 240 hitpoints.

### The Zuk wave is a floor, and says so

Zuk's room spawns a `Jal-Xil` and a `Jal-Zek` on a repeating 3:30 timer, and a
`JalTok-Jad` once he is below 480. **How many sets appear depends on how long
the fight takes, which is what this model is computing** - a genuine
circularity, and the sort this project refuses rather than approximates. What
is counted instead is the one guaranteed Jad and a single set, which is the
*fastest* the wave can go. A slower map really does fight more of them, so the
Inferno's figure here is a **ceiling on the speed**, not an expectation.

### Where the numbers come from, and which one is invented

The schedule, the hitpoints, the split mechanics and the drop chances are all
published. The kill times are this project's own, from `costing/dps_bridge.py`
against the map's own gear - which is the whole point, and why a poorly
equipped map should read hours where a well equipped one reads minutes.

`PER_WAVE_SECONDS` is **invented**: the spawn delay, the walk to whatever
spawned and the repositioning between waves are not published anywhere this
project could find, and one constant across sixty-nine waves is a stand-in for
sixty-nine unknowns. Every figure this module produces from the sequencer is
therefore a `GUESS`, by the rule that one invented factor makes the product
invented.

`RUN_SECONDS` is worse than invented and is labelled so: it is a **maintainer's
own figure**, not a publication. The Inferno's 45-60 minutes at best-in-slot,
~30 for a world record and two hours on bad gear, and the caves' 30-45, come
from someone who has done them. `item_seconds` spends the band's midpoint
because the goal walk runs before any DPS-derived rate exists - the same
compromise `raids.item_seconds` documents, and the same honest fix: price
goals after the enrichment rather than fudge a multiplier here.

**`run`/`answer` are the sequencer - a real per-map figure - and until
`costing/inputs.py`'s `_tzhaar_run_seconds` they had no caller at all.**
`instanced.kill_seconds` reached only the *function* `run_seconds` below,
whose own name this paragraph used to conflate with the sequencer's: it is
the flat band plus a hand override, nothing gear-sensitive, and every map
read the identical 45-60 minutes regardless of what it could actually kill
with. `_tzhaar_run_seconds` closes that: it calls `run` with a real
`dps_bridge.tzhaar_kill_seconds`, floors the result at `RUN_SECONDS` (an
invented `UPTIME` makes the sequencer's own answer a ceiling, not a
promise), and writes it into `Heuristics.run_seconds` - the very dict
`overrides` below reads - so a real map's pace reaches `run_seconds`
without needing a hand-set correction to get there. `tests/test_dps_bridge.py`
and `tests/test_costing_inputs.py` cover the sequencer and the wiring
respectively; nothing in this file's own suite ever compared the two,
which is what let the claim above stand unchecked as long as it did.

Pure: a kill-time lookup handed in, like every other encounter module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from chunksim.costing import encounter
from chunksim.costing.encounter import (
    EXPERIENCE,
    FightPlan,
    KillSeconds,
    Mechanic,
    Objective,
    PuzzlePlan,
    UNIQUE,
)

FIGHT_CAVES, INFERNO = "Fight Caves", "Inferno"

#: Waves per run, as the wiki states them: 63 and 69.
WAVES: Mapping[str, int] = {FIGHT_CAVES: 63, INFERNO: 69}

#: What the **wave tables** give, as `osrs-dps` keys, with the two published
#: split mechanics folded in. Totals rather than a per-wave breakdown - see
#: the module docstring.
#:
#: **Kept apart from `ZUK_ROOM` on purpose.** Folding Zuk's own spawns in here
#: put a 35th `Jal-Xil` among the wave counts and broke the one claim this
#: module is built on - that the two schedules' five tiers are identical.
#: `tests/test_costing_tzhaar.py` caught it, and the split is what keeps the
#: published half checkable against the wiki.
WAVE_ROSTER: Mapping[str, Mapping[str, int]] = {
    FIGHT_CAVES: {
        "Tz-Kih": 48,
        "Tz-Kek#Level 45": 40,
        # Two per level-45 killed.
        "Tz-Kek#Level 22": 80,
        "Tok-Xil#Standard": 36,
        "Yt-MejKot#Standard": 34,
        "Ket-Zek#Standard": 33,
        "TzTok-Jad": 1,
        # Jad's four healers, at half health.
        "Yt-HurKot#Level 108": 4,
    },
    INFERNO: {
        "Jal-Nib": 210,
        "Jal-MejRah": 48,
        "Jal-Ak": 40,
        # Three per blob, one per attack style.
        "Jal-AkRek-Xil": 40,
        "Jal-AkRek-Mej": 40,
        "Jal-AkRek-Ket": 40,
        "Jal-ImKot": 36,
        "Jal-Xil": 34,
        "Jal-Zek": 33,
        # Wave 67 is one, wave 68 is three.
        "JalTok-Jad": 4,
        # 5 for wave 67's Jad, 3 each for wave 68's three.
        "Yt-HurKot#Level 141": 14,
    },
}

#: Wave 69's own spawns, over and above the wave table. **A floor, not an
#: expectation** - see the module docstring: the `Jal-Xil`/`Jal-Zek` set
#: repeats on a 3:30 timer, so a slower map fights more of them, and how many
#: depends on the answer being computed.
ZUK_ROOM: Mapping[str, int] = {
    "TzKal-Zuk#Normal": 1,
    # Four, below 240 hitpoints.
    "Jal-MejJak": 4,
    # One guaranteed below 480, and its three healers.
    "JalTok-Jad": 1,
    "Yt-HurKot#Level 141": 3,
    # A single set, which is the fastest the wave can go.
    "Jal-Xil": 1,
    "Jal-Zek": 1,
}


def roster(variant: str) -> dict[str, int]:
    """Everything one completed run kills - the wave table plus, for the
    Inferno, Zuk's room."""
    found = dict(WAVE_ROSTER.get(variant) or {})
    if variant == INFERNO:
        for target, count in ZUK_ROOM.items():
            found[target] = found.get(target, 0) + count
    return found


#: The five rank-and-file tiers, in the order each minigame introduces them.
#: **The counts match across the two and the roles do not** - see the module
#: docstring; `tests/test_costing_tzhaar.py` pins both halves of that, and
#: reads them off `WAVE_ROSTER` so Zuk's room cannot disturb the claim.
TIERS: Mapping[str, tuple[str, ...]] = {
    FIGHT_CAVES: (
        "Tz-Kih",
        "Tz-Kek#Level 45",
        "Tok-Xil#Standard",
        "Yt-MejKot#Standard",
        "Ket-Zek#Standard",
    ),
    INFERNO: ("Jal-MejRah", "Jal-Ak", "Jal-ImKot", "Jal-Xil", "Jal-Zek"),
}

#: Spawn delay, approach and repositioning, per wave. **Invented** - nothing
#: publishes it, and one number stands for sixty-nine unknowns. Its size is
#: chosen to be small beside the fighting rather than fitted to a total: a
#: wave spawns, the spawns walk to the player, the player moves.
PER_WAVE_SECONDS = 9.0

#: Share of a run spent attacking. **Invented**, one number across the whole
#: run, for `theatre.UPTIME`'s reason: nothing measures it, and five invented
#: numbers would only look more precise. Lower than a raid's because a wave
#: minigame spends real time waiting for spawns to become reachable.
UPTIME = 0.8

#: A maintainer's own figures, not a publication - see the module docstring.
#: `(best, typical, poor)` seconds for one completed run.
RUN_BAND: Mapping[str, tuple[float, float, float]] = {
    # 30 minutes at a world-record pace, 45-60 at best-in-slot, two hours on
    # gear that can barely do it.
    INFERNO: (30 * 60.0, 52.5 * 60.0, 120 * 60.0),
    # 30-45, "could go a bit longer".
    FIGHT_CAVES: (30 * 60.0, 37.5 * 60.0, 75 * 60.0),
}

#: What `item_seconds` spends: the band's midpoint.
RUN_SECONDS: Mapping[str, float] = {
    variant: band[1] for variant, band in RUN_BAND.items()
}

#: The cape each run awards, and the pet each has a chance at.
CAPE: Mapping[str, str] = {FIGHT_CAVES: "Fire cape", INFERNO: "Infernal cape"}
PET: Mapping[str, str] = {FIGHT_CAVES: "Tzrek-jad", INFERNO: "Jal-nib-rek"}

#: The pet's chance on a completed run, off task. Published on both pages.
PET_CHANCE: Mapping[str, float] = {FIGHT_CAVES: 1 / 200.0, INFERNO: 1 / 100.0}

#: **The cape can be handed back for a second roll at the same chance** -
#: `TzHaar-Mej-Jal` takes a fire cape, `TzHaar-Ket-Keh` an infernal one. So a
#: completed run is two independent rolls, not one, and forgetting the second
#: would report the pet as taking twice as long as it does.
#:
#: One cape has to be *kept*, both being collection log entries in their own
#: right - immaterial at fifty-plus runs, and stated because the arithmetic
#: below quietly assumes it.
EXCHANGE_ROLL = True

#: Entering the Inferno costs a fire cape, one time. So an Inferno goal is a
#: Fight Caves run plus the Inferno runs - published on the Inferno page:
#: "This is a one-time fee".
INFERNO_ENTRY_COST = FIGHT_CAVES


def run_seconds(variant: str, overrides: Mapping[str, float] = {}) -> float:
    """How long one completed `variant` takes, correction applied.

    **`RUN_SECONDS` is this project's own figure and nothing publishes a
    better one**, which is precisely why it is overridable: `overrides` is
    `Heuristics.run_seconds` - populated two ways now, not one.
    `costing/inputs.py`'s `_tzhaar_run_seconds` writes a real per-map figure
    from the sequencer (`run`) here first; the `runs` branch of
    `heuristics/overrides.json` or a map's own file, a hand correction,
    still wins over it (`priced_heuristics`' own merge order). A correction
    here - hand-set or computed - moves every answer that spends a run - the
    pet, the cape, the boss kill - at once, because they all come through
    here.
    """
    got = overrides.get(variant)
    if isinstance(got, (int, float)) and not isinstance(got, bool) and got > 0:
        return float(got)
    return RUN_SECONDS[variant]


def entry_seconds(variant: str, overrides: Mapping[str, float] = {}) -> float:
    """What has to be done *before* the first `variant` run.

    The Inferno costs a fire cape to enter, one time - so it carries a Fight
    Caves run and the caves carry nothing.
    """
    return run_seconds(FIGHT_CAVES, overrides) if variant == INFERNO else 0.0


def pet_chance(variant: str) -> float:
    """One completed run's chance at the pet, both rolls counted.

    `1 - (1 - p)^2` rather than `2p`: two independent rolls at the same
    chance, which is very nearly but not exactly twice as likely.
    """
    single = PET_CHANCE.get(variant, 0.0)
    if single <= 0.0:
        return 0.0
    return 1.0 - (1.0 - single) ** (2 if EXCHANGE_ROLL else 1)


def plans(variant: str) -> tuple[FightPlan | PuzzlePlan, ...]:
    """One run's fights, plus the per-wave cost as a single puzzle.

    **The waves are one `PuzzlePlan` rather than sixty-nine**, because
    `PER_WAVE_SECONDS` is one constant and splitting it would imply this
    module knows something per-wave that it does not.
    """
    found: list[FightPlan | PuzzlePlan] = [
        FightPlan(name=target, target=target, count=count)
        for target, count in roster(variant).items()
    ]
    found.append(
        PuzzlePlan(
            name="between waves",
            seconds=PER_WAVE_SECONDS * WAVES.get(variant, 0),
        )
    )
    return tuple(found)


def mechanics(variant: str) -> dict[str, Mechanic]:
    """`UPTIME` against every fight in `variant`."""
    note = "share of a wave minigame spent attacking"
    return {
        target: Mechanic(uptime=UPTIME, note=note)
        for target in roster(variant)
    }


def run(variant: str, kill_seconds: KillSeconds) -> encounter.Encounter | None:
    """One completed run, or `None` if a monster cannot be priced."""
    return encounter.build(
        variant, plans(variant), kill_seconds, mechanics(variant)
    )


@dataclass(frozen=True)
class Answer:
    """What one variant costs for one objective."""

    variant: str
    encounter_: encounter.Encounter
    #: Completions expected, or `inf` where the objective cannot be met.
    runs: float
    #: Seconds paid once before the first run - the Inferno's fire cape.
    entry_seconds: float = 0.0

    @property
    def seconds(self) -> float:
        return self.encounter_.seconds * self.runs + self.entry_seconds

    @property
    def hours(self) -> float:
        return self.seconds / 3600.0


def answer(
    variant: str,
    kill_seconds: KillSeconds,
    objective: Objective = encounter.FULL_LOG,
) -> Answer | None:
    """`variant` priced for `objective`, or `None` if it cannot be priced."""
    built = run(variant, kill_seconds)
    if built is None:
        return None
    entry = 0.0
    if variant == INFERNO:
        # **A fire cape is the entry fee**, so the Inferno's own goals carry
        # one Fight Caves run. One-time, not per run.
        caves = run(FIGHT_CAVES, kill_seconds)
        if caves is None:
            return None
        entry = caves.seconds
    if objective.kind == UNIQUE:
        if objective.item == CAPE.get(variant):
            runs = 1.0
        elif objective.item == PET.get(variant):
            runs = encounter.expected_runs(pet_chance(variant))
        else:
            return None
    elif objective.kind == EXPERIENCE:
        # **Not answered here rather than answered badly**, exactly as
        # `costing/theatre.py` refuses: a run's combat experience is its
        # roster's hitpoints against the map's damage, which is
        # `costing/combat_xp.py`'s question.
        return None
    else:
        # The whole log is the cape and the pet, and the pet is the long pole
        # by two orders of magnitude.
        runs = encounter.expected_runs(pet_chance(variant))
    return Answer(variant=variant, encounter_=built, runs=runs, entry_seconds=entry)


#: The monster whose death **is** the run's completion. Nothing else in the
#: game drops either of them, so "kill it once" and "complete the run" are the
#: same sentence - which is exactly what the kill-goal path in
#: `costing/estimate.py` did not know.
FINAL_BOSS: Mapping[str, str] = {FIGHT_CAVES: "TzTok-Jad", INFERNO: "TzKal-Zuk"}


def variant_of_boss(monster: str) -> str | None:
    """Which run `monster` ends, or `None` if it does not end one."""
    for variant, boss in FINAL_BOSS.items():
        if monster == boss:
            return variant
    return None


def kill_seconds(
    monster: str, overrides: Mapping[str, float] = {}
) -> float | None:
    """Seconds for **one** kill of a run's final boss, or `None`.

    **A task wanting a kill is not cheaper than a task wanting the drop.**
    `costing/estimate.py` prices an ordinary kill goal at `1 / kills_per_hour`,
    which is right for something you can walk up to and wrong by three orders
    of magnitude for something guarded by sixty-eight waves: four Combat
    Achievements naming `TzKal-Zuk` came out at **0.05 hours** between them.

    The Inferno's figure carries a Fight Caves run, that being the published
    entry fee, so it is the honest cost of a first kill on a map holding
    neither cape.

    **Only the two final bosses are answered.** The rank-and-file are just as
    unreachable without a run, but the cheapest way to reach one is to fight
    up to its first wave - and the wave ordering is exactly what this module
    does not carry (see the module docstring). Refusing them is
    `None`; they keep whatever the kill-rate layer left, and a map that
    actually needs one should be the reason the ordering comes back.
    """
    variant = variant_of_boss(monster)
    if variant is None:
        return None
    return run_seconds(variant, overrides) + entry_seconds(variant, overrides)


def activity_for(item: str) -> str | None:
    """Which run earns `item`, or `None` if neither does.

    **Matched case-insensitively**, for `_Walk.raid_seconds`' reason: the
    wiki writes `Jal-Nib-Rek`, the export's drop table writes `Jal-nib-rek`,
    and an item name is not a place two different things differ only by
    capitalisation.
    """
    wanted = item.lower()
    for variant in (FIGHT_CAVES, INFERNO):
        if wanted in (CAPE[variant].lower(), PET[variant].lower()):
            return variant
    return None


def item_seconds(overrides: Mapping[str, float] = {}) -> dict[str, float]:
    """`{item: seconds}` for both capes and both pets, for the item walk.

    **This is the flat band, not the sequencer** - see the module docstring on
    why the two are kept apart, and `raids.item_seconds` for the same
    compromise and the same reason: the goal walk is built before any
    DPS-derived rate exists.

    The Inferno's two entries carry a Fight Caves run as well, that being the
    published entry fee.
    """
    caves_run = run_seconds(FIGHT_CAVES, overrides)
    inferno_run = run_seconds(INFERNO, overrides)
    entry = entry_seconds(INFERNO, overrides)
    return {
        CAPE[FIGHT_CAVES]: caves_run,
        PET[FIGHT_CAVES]: caves_run / pet_chance(FIGHT_CAVES),
        CAPE[INFERNO]: entry + inferno_run,
        PET[INFERNO]: entry + inferno_run / pet_chance(INFERNO),
    }
