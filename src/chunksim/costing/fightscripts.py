"""Bosses `costing/dps_bridge.py` cannot price as one damage race.

**A straight kill time is `hitpoints / dps`, and most bosses are exactly
that.** A phased boss is not: the Alchemical Hydra swaps its whole stat block
four times in one kill, Zulrah's three forms take different damage from the
same weapon, and both carry seconds of near-zero output that no `Target` in
`osrs_dps` represents at all - a vent to be lured to, a totem to be broken.
`FightScript` is the shape that names all of that; `dps_bridge._scripted_kill`
is what turns one into a real `KillEstimate`.

### Why this is not another `costing/encounter.py`

`encounter.py` already has the right vocabulary for "a fight costs more than
its damage race" - `Mechanic.uptime`/`idle_seconds` - and its own docstring
says a standalone boss should be able to use it. It is not reused directly
for two reasons:

- **A raid stage is killed once; a boss phase is a *slice* of one kill.**
  `FightPlan.count` multiplies a whole kill by how many the room holds -
  Verzik's three phases are three separate `#Phase N` targets fought to zero
  each. The Hydra's four `#Serpentine`/`#Electric`/`#Fire`/`#Extinguished`
  keys are not that: each one is the *same* fight simulated from full health,
  so a quarter of one phase's time-to-kill is what a quarter of its health
  bar costs, not four whole kills summed. `Phase.hp_share` says this
  explicitly rather than asking a caller to fake it with `count=0.25` and
  hope no one reads that as "a quarter of an encounter".
- **A vent is not idle time and it is not a rate.** `Mechanic.idle_seconds`
  is dead time the fight pays regardless of how fast the kill goes;
  `Mechanic.uptime` is a *constant* share of the whole fight spent attacking.
  Neither says "the first five seconds of this phase land at a quarter
  strength" - a window with real but reduced output, sized in real seconds
  rather than as a fraction of the fight. `Phase.reduced_seconds` /
  `reduced_dps_fraction` is that third shape, converted to a phase's own
  wasted time by `dps_bridge._scripted_kill` rather than forced through
  `idle_seconds` by a caller doing the arithmetic by hand.

Everything else - a fixed cost that is not a rate at all, a phase with
nothing special about it - is exactly what `Mechanic`'s `idle_seconds`
already says, so `Phase` carries one for it rather than inventing a fourth
term.

### What this refuses to model

**No phase ordering effect, no death, no per-attempt failure.** A `FightScript`
prices the mean kill as a sum of its phases' means; it cannot say "phase 3
usually goes badly" or "a third of attempts die in phase 2 and restart",
because nothing here tracks state across phases beyond total elapsed time.
That is the same ceiling `costing/tzhaar.py` states for the Inferno's wave
ordering, for the same reason: expressing it needs the sequence back, and the
day a boss's answer turns on getting the order right is the day this stops
being enough.

### Where the numbers come from

A phase's `target` and `hp_share` are read straight off the wiki - the
Hydra's own page states its phase thresholds in hitpoints, not as a rounded
fraction, so `hp_share` is quoted from that division rather than assumed
equal. `reduced_dps_fraction` is usually published too (the Hydra's page
states "75% damage reduction" outright). **`reduced_seconds` almost never
is** - nothing publishes how long a vent-lure or a totem-break actually
takes in practice - so it is this project's own figure, exactly as
`costing/tzhaar.py`'s `PER_WAVE_SECONDS` is, and every script says so beside
the constant rather than once here.

Pure: no `osrs_dps` import here or in a per-boss module - `dps_bridge.py`
stays the one module allowed that import, and a `FightScript` is inert data
until `dps_bridge._scripted_kill` prices it against a loadout.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Phase:
    """One slice of one kill - a share of *its own target's* health, at that
    target's own stats, with its own reduced-output window if it has one.

    **`hp_share` is relative to `target`, not to the script as a whole**, and
    what that means for a whole `FightScript` depends on the boss:

    - **One shared pool, several stat blocks** - the Hydra's four phases, or
      Zulrah's three forms - every `target` carries the *same* total health
      (each is "the whole fight, priced as if only this form existed"), so
      the phases' `hp_share`s sum to `1.0` across the script and each is
      `<= 1`.
    - **Several independent targets, each fully depleted** - Grotesque
      Guardians fights Dawn and Dusk in two instalments each, and each is
      its own 450-hitpoint total. Dawn's two phases sum to `1.0` on their
      own, and so do Dusk's; the *script's* total is 2.0, correctly pricing
      two separate full-health kills rather than one.
    - **One small target, killed several times over** - the Abyssal Sire's
      four respiratory systems are 50 hitpoints each and none of that
      damage touches the Sire's own bar at all, so `hp_share=4.0` against
      `Respiratory system` prices "kill this 50-hp target four times",
      exactly as `target.hitpoints * hp_share` computes it.

    `tests/test_fightscripts.py` has no single sum to assert across every
    script for this reason; what each boss's own tests pin is whichever of
    the shapes above that boss actually is.
    """

    name: str
    #: The `osrs_dps` key this phase's stats come from - the library's own
    #: spelling, `#version` suffix included. Never the bare boss name: that
    #: would re-enter the registry `dps_bridge._scripted_kill` is answering
    #: for and recurse into itself.
    target: str
    #: This phase's share of `target`'s own health - `0 < hp_share`, with no
    #: upper bound: `1.0` is the whole of `target`'s health, and a value
    #: above `1.0` is killing `target` more than once over. See the class
    #: docstring for which shape a given boss needs.
    hp_share: float
    #: Seconds at the start of this phase where output is
    #: `reduced_dps_fraction` of normal, before full-rate damage resumes.
    #: `0.0` for a phase with no such window.
    reduced_seconds: float = 0.0
    #: Damage dealt during `reduced_seconds`, as a fraction of normal -
    #: `0.25` for the Hydra's published 75% reduction. Meaningless when
    #: `reduced_seconds` is `0.0`.
    reduced_dps_fraction: float = 1.0
    #: Fixed dead time this phase costs beyond the reduction window - a walk,
    #: a forced animation, anything with no damage in it at all. Rare: most
    #: phase overhead already has a rate, however reduced, which is what
    #: `reduced_seconds` is for.
    idle_seconds: float = 0.0
    #: Which combat styles can actually damage `target` at all - `None`
    #: (every earlier script) means every style `kills_by_style` tries is
    #: genuinely usable, and the search picks whichever wins. Set this only
    #: when the *rest of the fight*, not the numbers, rules a style out
    #: entirely: the Grotesque Guardians' Dusk is "completely immune to
    #: magic and ranged damage" and Dawn "cannot be targeted by non-halberd
    #: melee weapons", but nothing in `osrs_dps`'s own `Target.bonuses`
    #: encodes either restriction - both monsters carry ordinary all-zero
    #: defence, so an unrestricted search would happily price a style that
    #: deals zero real damage. A script says so explicitly rather than
    #: `dps_bridge` guessing from stat shape which zero is a weakness and
    #: which is a total exclusion.
    styles: frozenset[str] | None = None
    #: Why these numbers, in the module's own words - which tier each one is
    #: (published, inferred, guessed) and the citation behind it.
    note: str = ""


@dataclass(frozen=True)
class FightScript:
    """One boss, as the phases a real kill actually has.

    `name` is the bare export/library name the boss is asked about under -
    `Alchemical Hydra`, never a `#`-suffixed key, which is reserved for a
    `Phase.target`. `dps_bridge.SCRIPTS` composes these from each boss's own
    module (`costing/hydra.py` today) and is checked by name inside
    `dps_bridge.best_kill`, before its ordinary version resolution.
    """

    name: str
    phases: tuple[Phase, ...]
    #: What this project measured, inferred or guessed beyond what each
    #: `Phase.note` already says - a reader assembling the whole fight reads
    #: this first.
    note: str = ""
