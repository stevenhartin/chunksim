"""The Gauntlet and the Corrupted Gauntlet: a preparation phase that dwarfs
the boss fight, and a reward chest the export has no table for.

**Why the boss's own time-to-kill is not this activity's kill rate.** Both
variants are "the player is given a limited amount of time to explore a
randomly generated dungeon layout, gather various resources and supplies...
all in preparation to defeat the [[Crystalline Hunllef]]" - up to a
published cap (`[[The Gauntlet]]`: "The player has 10 minutes to prepare...
If the timer runs out, the player will automatically get teleported into
the boss room") before the fight this project's own damage model prices even
starts. A model that only asked `dps_bridge` "how long does Crystalline
Hunllef take" and multiplied would be answering the same question
`costing/tzhaar.py`'s own docstring names for the Fight Caves: right about
the fight, silent about everything that has to happen before it.

### `PREP_SECONDS` is this project's own figure, not the wiki's

The 10-minute (600s) and 7-minute-30 (450s) numbers on `[[The Gauntlet]]`
are the **caps** the timer enforces, not how long an efficient player
actually spends - most of that budget is slack for a player still gathering
what they need, and a model spending the whole cap every run would
overstate the common case badly. Nothing on the wiki states a typical
efficient prep duration for either variant, so `PREP_SECONDS` here is
stated as this project's own accepted estimate: **2-3 minutes for the
regular Gauntlet, 5-6 minutes for the Corrupted Gauntlet**, and the
midpoint of each band (150s, 330s) is what `plans()` spends. This is the
same shape `costing/tzhaar.py`'s `PER_WAVE_SECONDS` and `RUN_SECONDS` are -
an invented number standing in because nothing published one - and every
rate this module produces is therefore a `GUESS` by the same rule.

### The boss needs no `FightScript`

Both `Crystalline Hunllef` and `Corrupted Hunllef` carry **uniform defence
across every damage type** in `osrs_dps` - `20` against stab/slash/crush/
magic/ranged alike, for both - so unlike Perilous Moons there is no style a
generic loadout gets wrong: whichever of Melee/Ranged/Magic the map's own
BiS search prefers is exactly as good against either Hunllef as any other,
numerically. The shield that forces a player to alternate between two
attack styles mid-fight is real but is a *player-execution* mechanic, not a
static defence differential `osrs_dps`'s own stat block encodes or a
published downtime duration this project could cite - so, matching the
refusal already stated for Araxxor, Cerberus and Sol Heredit, this module
prices the fight as a plain damage race and states the omission rather than
inventing a switch-overhead constant nothing publishes.

### The chest, and why one module answers for both variants

`Reward chest The Gauntlet loot*`'s own `Output` is `Reward Chest (The
Gauntlet)`, absent from `drops` entirely - the same gap `costing/raids.py`,
`costing/barrows.py`, `costing/colosseum.py` and `costing/moons.py` each
close for their own chest. **There is only one `(The Gauntlet)`
collection-log category, not two** - the export gates `Crystal armour
seed`, `Crystal weapon seed`, `Enhanced crystal weapon seed` and `Youngllef`
under it regardless of which Hunllef gave them, matching `[[The
Gauntlet]]`'s own tables: both variants can drop all four, at different
rates. `item_seconds` therefore takes the **faster of the two variants per
item**, the same "offer the best available" choice `costing/raids.best_for`
makes for a named unique - `Gauntlet cape` is the one exception, guaranteed
on a Corrupted completion and entirely absent from the regular table.

**Every seed and the pet are independent per-completion rolls, not
multiplied by how many times the main table is rolled.** `[[Reward Chest
(The Gauntlet)]]`: "roll twice on the regular loot table" / "roll three
times on the corrupted loot table" describes the ordinary
weapons/runes/gems/other pool; "each item on the tertiary tables is rolled
independently" is the seeds and the pet, and the money-making guide's own
`Output` fields confirm it - `1*(1/2000)`, not `2*(1/2000)`.

### Corrupted needs a regular completion first

"After completing the Gauntlet once, players may try the Corrupted
Gauntlet" - a one-time prerequisite, exactly the shape
`costing/tzhaar.py`'s `INFERNO_ENTRY_COST` is for the Inferno's fire cape,
and priced the same way: one regular run, added once rather than per run.

Pure: `FightPlan`/`PuzzlePlan` construction only, no `osrs_dps` import.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from chunksim.costing import encounter
from chunksim.costing.encounter import EXPERIENCE, FightPlan, KillSeconds, Objective, PuzzlePlan, UNIQUE

REGULAR, CORRUPTED = "The Gauntlet", "Corrupted Gauntlet"

#: Upstream's own challenge for the chest's loot - one category, both
#: variants. See the module docstring.
LOOT_TASK = "Reward chest The Gauntlet loot*"

#: Each variant's own boss - both bare `osrs_dps` keys, no version
#: ambiguity.
BOSS: Mapping[str, str] = {REGULAR: "Crystalline Hunllef", CORRUPTED: "Corrupted Hunllef"}

#: This project's own estimate - see the module docstring on why the wiki's
#: 600s/450s timer caps are not it. Midpoints of "2-3 minutes" (regular) and
#: "5-6 minutes" (corrupted).
PREP_SECONDS: Mapping[str, float] = {REGULAR: 150.0, CORRUPTED: 330.0}

#: `Money making guide/Completing The Gauntlet`: `kph = 7`.
#: `Money making guide/Completing The Corrupted Gauntlet`: `kph = 6`.
PUBLISHED_RUNS_PER_HOUR: Mapping[str, float] = {REGULAR: 7.0, CORRUPTED: 6.0}
PUBLISHED_SECONDS: Mapping[str, float] = {
    variant: 3600.0 / rate for variant, rate in PUBLISHED_RUNS_PER_HOUR.items()
}

#: `{item: chance one completion gives it}`, per variant - `[[Reward Chest
#: (The Gauntlet)]]`'s own tertiary tables, matching the money-making
#: guides' `Output` fields exactly. `Gauntlet cape` is corrupted-only,
#: "awarded if the player does not already have" one - priced as guaranteed
#: here, matching every other guaranteed-once reward in this subpackage
#: (`costing/colosseum.py`'s quiver, `costing/tzhaar.py`'s capes).
UNIQUE_CHANCE: Mapping[str, Mapping[str, float]] = {
    REGULAR: {
        "Crystal weapon seed": 1 / 120,
        "Crystal armour seed": 1 / 120,
        "Enhanced crystal weapon seed": 1 / 2000,
        "Youngllef": 1 / 2000,
    },
    CORRUPTED: {
        "Crystal weapon seed": 1 / 50,
        "Crystal armour seed": 1 / 50,
        "Enhanced crystal weapon seed": 1 / 400,
        "Youngllef": 1 / 800,
        "Gauntlet cape": 1.0,
    },
}


def item_chances(variant: str) -> dict[str, float]:
    """`{item: chance one completion of `variant` gives it}`."""
    return dict(UNIQUE_CHANCE.get(variant, {}))


def best_item_chances() -> dict[str, float]:
    """`{item: chance}`, the better of the two variants per item - see the
    module docstring on why this is not "pick a variant and stick with it":
    the export's one collection-log category accepts either."""
    found: dict[str, float] = {}
    for variant in (REGULAR, CORRUPTED):
        for item, chance in item_chances(variant).items():
            if chance > found.get(item, 0.0):
                found[item] = chance
    return found


def plans(variant: str) -> tuple[FightPlan | PuzzlePlan, ...]:
    """One run: the preparation phase, then the boss."""
    return (
        PuzzlePlan(name="preparation", seconds=PREP_SECONDS[variant]),
        FightPlan(name=BOSS[variant], target=BOSS[variant]),
    )


def run(variant: str, kill_seconds: KillSeconds) -> encounter.Encounter | None:
    """One completed run, or `None` if the boss cannot be priced."""
    return encounter.build(variant, plans(variant), kill_seconds)


def entry_seconds(variant: str, kill_seconds: KillSeconds) -> float:
    """What has to be done *before* the first `variant` run.

    Only the Corrupted Gauntlet carries one - a single regular completion,
    published as the unlock condition. `None` from `run(REGULAR, ...)`
    (the boss cannot be priced) means the entry itself is unpriceable, and
    `0.0` is the honest floor rather than a silent skip - callers that need
    to know should check `run(REGULAR, kill_seconds)` themselves.
    """
    if variant != CORRUPTED:
        return 0.0
    regular = run(REGULAR, kill_seconds)
    return regular.seconds if regular is not None else 0.0


def total_seconds(variant: str, overrides: Mapping[str, float] = {}) -> float:
    """How long one completed `variant` takes, correction applied - the
    **flat, published** figure, not the sequencer's map-driven one.

    **The two paths are kept apart on purpose**, matching
    `costing/tzhaar.py`'s own reasoning: `run()` prices the boss from the
    map's own gear and adds `PREP_SECONDS`'s guessed overhead on top, which
    is right for the item walk and the goal walk once real gear exists to
    price. `total_seconds` is `PUBLISHED_SECONDS`, correctable through
    `overrides` (`Heuristics.run_seconds`, the `runs` branch), for callers
    that ask before that - `costing/instanced.py`'s kill-goal path chief
    among them, which is asked about a monster with no `KillSeconds`
    callable in scope at all.
    """
    got = overrides.get(variant)
    if isinstance(got, (int, float)) and not isinstance(got, bool) and got > 0:
        return float(got)
    return PUBLISHED_SECONDS[variant]


#: `final boss -> its own variant`. Both bosses answer to one collection-log
#: category but need different totals, which is why `costing/instanced.py`
#: dispatches on the monster rather than on a shared place the way every
#: other entry there does.
FINAL_BOSS: Mapping[str, str] = {BOSS[REGULAR]: REGULAR, BOSS[CORRUPTED]: CORRUPTED}


def variant_of_boss(monster: str) -> str | None:
    """Which variant `monster` ends, or `None` if it ends neither."""
    return FINAL_BOSS.get(monster)


def kill_seconds(monster: str, overrides: Mapping[str, float] = {}) -> float | None:
    """Seconds for **one** kill of `monster`, one of the two Hunllefs, or
    `None`.

    A run's boss is the run - `costing/instanced.py`'s own reason for
    existing - so this is `total_seconds` plus, for the Corrupted Hunllef,
    one regular completion's published total, matching
    `costing/tzhaar.kill_seconds`'s own shape for the Inferno's entry fee.
    """
    variant = variant_of_boss(monster)
    if variant is None:
        return None
    total = total_seconds(variant, overrides)
    if variant == CORRUPTED:
        total += total_seconds(REGULAR, overrides)
    return total


@dataclass(frozen=True)
class Answer:
    """What one variant costs for one objective."""

    variant: str
    encounter_: encounter.Encounter
    #: Completions expected, or `inf` where the objective cannot be met.
    runs: float
    #: Seconds paid once before the first run - a regular completion, for
    #: the Corrupted Gauntlet.
    entry_seconds: float = 0.0

    @property
    def seconds(self) -> float:
        return self.encounter_.seconds * self.runs + self.entry_seconds

    @property
    def hours(self) -> float:
        return self.seconds / 3600.0


def answer(
    variant: str, kill_seconds: KillSeconds, objective: Objective = encounter.FULL_LOG
) -> Answer | None:
    """`objective` priced against `variant`, or `None` if the boss cannot be
    priced."""
    built = run(variant, kill_seconds)
    if built is None:
        return None
    entry = entry_seconds(variant, kill_seconds)
    chances = item_chances(variant)
    if objective.kind == UNIQUE:
        runs = encounter.expected_runs(chances.get(objective.item, 0.0))
    elif objective.kind == EXPERIENCE:
        # **Not answered here rather than answered badly**, matching every
        # other encounter module's refusal - see `costing/combat_xp.py`.
        return None
    else:
        runs = encounter.runs_for_all(list(chances.values()))
    return Answer(variant=variant, encounter_=built, runs=runs, entry_seconds=entry)


def _best_variant_for(item: str) -> str:
    """Whichever of the two gives `item` the higher per-completion chance,
    `REGULAR` on a tie - it carries no entry fee, so a tie is never worth
    paying for."""
    regular = UNIQUE_CHANCE[REGULAR].get(item, 0.0)
    corrupted = UNIQUE_CHANCE[CORRUPTED].get(item, 0.0)
    return CORRUPTED if corrupted > regular else REGULAR


def item_seconds() -> dict[str, float]:
    """`{item: seconds}` for the item walk, at `PUBLISHED_SECONDS` - see
    `costing/raids.item_seconds` for the shape and the reason it is
    published rather than modelled at this point in the pipeline.

    **The Corrupted Gauntlet's own entries carry a regular completion**, its
    published unlock condition, matching `costing/tzhaar.item_seconds`'s
    own Inferno entries carrying a Fight Caves run.
    """
    found: dict[str, float] = {}
    for item, chance in best_item_chances().items():
        if chance <= 0:
            continue
        variant = _best_variant_for(item)
        run_seconds = PUBLISHED_SECONDS[variant]
        if variant == CORRUPTED:
            run_seconds += PUBLISHED_SECONDS[REGULAR]
        found[item] = run_seconds / chance
    return found


def activity_for(item: str) -> str | None:
    """`REGULAR` if `item` is one of the chest's own rewards, else `None` -
    `costing/tzhaar.activity_for`'s exact shape, matched case-insensitively
    for the same reason that module's docstring gives. Named for the
    regular Gauntlet regardless of which variant actually earns the row
    fastest - both share the one collection-log category, and "The
    Gauntlet" is what a reader would look this activity up as.
    """
    wanted = item.lower()
    return REGULAR if wanted in {name.lower() for name in best_item_chances()} else None
