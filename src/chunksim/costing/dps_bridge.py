"""Pricing a kill with the DPS calculator instead of a money-making guide.

`heuristics.py` gets its kills-per-hour from the OSRS wiki's money-making
guides, which cover **225 of the export's 2,657 training methods** - most ways
of killing a thing do not make money and so have no guide. Everything else
falls back to a flat `DEFAULT_KPH`. This module computes the number instead,
from the gear `bis.py` says the map can actually reach, using the `osrs-dps`
library.

**The dependency is optional and must stay optional.** Not for a licence
reason any more - this project is GPL-3.0-or-later, the same as `osrs-dps` -
but because `chunksim` has no required runtime dependencies at all and this
would be the first. It is something a user installs deliberately (`pip install
-e ../osrs-dps`). Every entry point here checks `DPS_AVAILABLE` and the
estimator falls back to the scraped rates without it. Import this module freely - importing is safe when the library is
absent; only calling is not.

**Time-to-kill is not a kill cycle.** The library returns seconds of
*fighting*; a kills-per-hour figure also carries banking and respawn, which is
what the wiki's guides bake in and the calculator cannot know. That gap is
`KillEstimate.overhead`, built from two measured parts rather than assumed -
read it before quoting a rate.

**How well it works, measured, and it is uneven.** Against the 81 monsters the
wiki also rates, the median is 0.95 and 44 of 81 fall within a factor of two.
The spread - mean absolute log ratio, which counts both directions - has come
down from 0.91 to 0.81 as the mechanical costs went in. The halves still
diverge, and knowing which half a number is in matters more than the median:

- **Non-bosses land at 1.46**, i.e. this still reports them faster than the
  wiki. Trash takes almost no damage, so the banking term is near zero and
  respawn is zero by construction, leaving the tick costs to carry the whole
  overhead. Walking any distance between spawns is not charged for.
- **Bosses land at 0.71.** The gap is the gear: the wiki assumes a maximum
  account with protection prayers and mid-fight style switching, and this map
  fights with what `bis.py` could reach.

Neither tail is silently wrong. The numbers are honest about the fight they
describe, which is one without protection prayers and without walking time.

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

**Worn gear is a fraction of what decides a kill.** Prayers, potions, the
spell being cast and defence draining are each worth more than an equipment
upgrade, and a fight priced without them is not the fight anyone has - the
map's BiS takes 6,789 seconds to kill Nex on bare gear. `Kit` carries all four
and `assemble_kit` derives them from what the map reaches, so they are gated
on availability like everything else rather than assumed. Passing no `Kit`
gives the bare-gear number, which is a floor and not an estimate.

**Magic needs a named spell or it does not work at all.** Without one the
library has no max hit to compute and refuses the loadout, so before `Kit`
existed the magic style silently priced *nothing* - `best_kill` caught the
refusal and moved on. A style that contributes nothing looks exactly like a
style that never wins, which is why this went unnoticed.

**All three styles are always tried.** A monster's defences are wildly uneven
and the right style is a property of the fight, not of the gear: Zulrah's
magma form takes nothing whatever from melee.

**What is still not supplied**, each of which makes the estimate
*conservative* rather than wrong - a missing bonus lengthens the kill:

- **Attack boosts.** The export's `boostItems` has no `Attack` table at all,
  so a melee attack roll never boosts. See `_BOOSTED_SKILLS`.
- **The Bandos godsword's drain.** See `_DRAIN_WEAPONS`.
- **Weapon category.** The export has no `category` field, so the effects
  keyed off one - `Polearm` reaching flying monsters, `Pickaxe` against
  Guardians, `Salamander` bypassing some melee immunities - never fire.
- **Prayer sustainability.** Prayers are applied for the whole fight however
  long it runs, which nothing restores in the model.

**Where the fight happens is part of the loadout.** The wilderness weapons are
worth +50% damage, gated on being in the wilderness *and* on the weapon being
charged - and the export expresses charge state as a name suffix where the
library expresses it as `weapon_version`. Both gates were failing at once: the
map's BiS had picked `Webweaver bow (u)` over the identically-statted
`Webweaver bow`, whose name is the one the library's special case looks for.
Fixing the pair took the Chaos Elemental from 149 to 78 seconds and the Chaos
Fanatic from 110 to 56. See `_WILDERNESS_WEAPONS` and `wilderness_monsters`.

**Group bosses are refused, not priced.** A solo kill time for team content is
not a number worth having, and the wiki's rate for one describes a team rather
than a player. See `GROUP_BOSSES`.

**Slayer's holes are the other thing this fills.** `slayer.py` folds a task it
has no data for back in at a flat 7,000 XP an hour, deliberately poor so a
master full of gaps looks slow rather than quietly fast. `price_slayer_tasks`
computes those, **and now every other task too**: the sheet's rates are real
observations of the *best* method, and the best method for a stackable task is
chinning or bursting, which wants a box trap or Desert Treasure I. On a map
without them that number describes an activity the player cannot perform. The
three reachable masters land at Krystilia 18,609 against the sheet's 50,126,
Vannaka 16,939 against 32,044, and Mazchna 14,780 against 14,569 - the last
barely moving, its list holding one multi-target row against Krystilia's seven.

Read `price_slayer_tasks` on why the XP comes from hitpoints, on why the
monster is chosen by XP an hour rather than by speed, and on why a master's
rate can *fall* when a guess is replaced by a number.

**Quote a master only after gating on its NPC.** `master_rates` takes
`reachable_masters` and defaults it to `None`, meaning "do not filter", which
is right for fixtures and wrong for every real map - this one holds three of
the ten masters, so an ungated table puts Konar at the top of a list of
masters the player cannot walk up to. `price_slayer_tasks` takes the same set
for the same reason: pricing a master's list is wasted work if nobody can be
assigned from it.

The tasks that are not priced are the ones whose monsters this map cannot
reach, and they are now counted as *skips* rather than as unpriced work - a
task you are handed and must cancel, which is what `slayer.py` always meant by
the word. That fell out of `slayer.task_monsters` reading the export's own
task-to-monster list, which gives its reachability test something to test.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace, field, replace
from typing import Any, Callable

from chunksim.derive.boosts import combat_boost
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.costing.levels import reachable_providers
from chunksim.costing.heuristics import Heuristics, Rate, SlayerTask
from chunksim.derive.pipeline import Derived
from chunksim.costing.slayer import task_monsters
from chunksim.model.summary import _mapping
from chunksim.costing import doom_of_mokhaiotl as _doom_of_mokhaiotl
from chunksim.costing import duke_sucellus as _duke_sucellus
from chunksim.costing import giant_mole as _giant_mole
from chunksim.costing import grotesque_guardians as _grotesque_guardians
from chunksim.costing import hespori as _hespori
from chunksim.costing import hueycoatl as _hueycoatl
from chunksim.costing import hydra as _hydra
from chunksim.costing import kalphite_queen as _kalphite_queen
from chunksim.costing import keyed_chests as _keyed_chests
from chunksim.costing import moons as _moons
from chunksim.costing import nex as _nex
from chunksim.costing import nightmare as _nightmare
from chunksim.costing import phantom_muspah as _phantom_muspah
from chunksim.costing import royal_titans as _royal_titans
from chunksim.costing import sire as _sire
from chunksim.costing import skotizo as _skotizo
from chunksim.costing import vetion as _vetion
from chunksim.costing import vorkath as _vorkath
from chunksim.costing import xeric as _xeric
from chunksim.costing import yama as _yama
from chunksim.costing import zalcano as _zalcano
from chunksim.costing import zulrah as _zulrah
from chunksim.costing.fightscripts import FightScript, Phase

try:  # pragma: no cover - exercised by whether the extra is installed
    from osrs_dps import (
        CombatStyle,
        DefenceReductions,
        Levels,
        Loadout,
        RaidInputs,
        StatBlock,
        Target,
        Unsupported,
        damage_taken_per_second,
        dps,
        scale,
    )
    from osrs_dps.data import MonsterIndex, load_monsters

    DPS_AVAILABLE = True
except ImportError:  # pragma: no cover - ditto
    DPS_AVAILABLE = False


#: One game tick.
SECONDS_PER_TICK = 0.6

#: Ticks lost between one kill and the next: at least one to shift focus to
#: another monster, and generally another to close the distance. Applied to
#: every kill, boss or not, though a boss's respawn dwarfs it.
RETARGET_TICKS = 2

#: Enforced respawn wait per kill, for a boss.
#:
#: **Respawn only costs anything when the monster is the scarce thing.** A
#: slayer cave holds enough aberrant spectres that the next one is always
#: ready; a boss lair holds one, so its timer lands on every kill. Rather than
#: read a per-monster timer off the wiki, this takes a flat 15 seconds for
#: anything in the export's `bossMonsters` and nothing for everything else -
#: which is wrong per boss and about right on average.
BOSS_RESPAWN_SECONDS = 15.0

#: Seconds to bank: teleport out, restock food and potions, return. Used for
#: everything that is not a boss; see `BOSS_BANKING_FRACTION` for why bosses
#: are handled the other way.
BANKING_SECONDS = 120.0

#: A boss's banking cost, as a share of the fight itself.
#:
#: **Bosses do not get the measured banking model, deliberately.** Working a
#: trip out from damage taken needs the damage to be right, and for a boss it
#: is not: nobody fights General Graardor without Protect from Melee, and
#: overhead prayers are not modelled - the library declines to, matching
#: upstream, because some monsters hit through them. Feeding roughly double
#: the real damage into a trip length put 10 of 33 bosses below one kill per
#: trip and dragged the whole boss half to 0.45 of the wiki's rate.
#:
#: A share of the fight is the better shape, and the arithmetic agrees: a
#: 120-second bank run over a plausible trip is 20% of a 20-second kill, 10%
#: of a 100-second one and 12% of a 200-second one - near enough flat across
#: the range, because an easier boss buys more kills per trip in proportion to
#: how much quicker it dies. 15% sits in the middle of that.
#:
#: Not fitted to the wiki, and it cannot be: the boss half already sits at
#: 0.70 with *no* banking at all, so any fit would be reading the gear gap and
#: calling it banking.
BOSS_BANKING_FRACTION = 0.15

#: Healing an inventory carries - roughly 15 food at 20 each. Added to the
#: player's Hitpoints level to give the damage a trip can absorb before it has
#: to end.
INVENTORY_HEALING = 300.0

#: Superseded. A flat 30 seconds on every kill was 43% of the median cycle and
#: 92% of a rat's - the fight was the minority of the reported time. Kept named
#: because `measure_overhead`'s samples were fitted against it.
DEFAULT_OVERHEAD_SECONDS = 30.0

#: The export stores magic damage as a display percentage; the library wants
#: upstream's `magic_str`, in tenths of a percent. See the module docstring.
MAGIC_DAMAGE_SCALE = 10

#: The BiS styles worth pricing a kill with. `bis.py` also emits Tank, Flinch,
#: Prayer and Weight Reducing winners, which are not ways of dealing damage.
OFFENSIVE_STYLES = ("Melee", "Ranged", "Magic")

#: **A melee weapon ranked by one damage type rather than the best of the
#: three.** `bis.py` already computes `Stab-weapon`/`Slash-weapon`/
#: `Crush-weapon` winners alongside its plain `Melee-weapon` one - upstream's
#: own BiS pages report all four - and `derived.bis.picks` (every real
#: caller's `picks`) has always carried them. `build_loadouts` simply never
#: read them, because nothing needed to: an ordinary monster's melee defence
#: is close enough across the three that the generic `Melee` winner is a fine
#: proxy.
#:
#: **`costing/moons.py` is the one place that gap is not a rounding error.**
#: Blue Moon, Blood Moon and the Eclipse Moon each carry a genuine `0`
#: defence against exactly one melee damage type and `100` against the other
#: two - not a preference, an exclusion the size of Zulrah's magma form
#: taking nothing from melee. A `Melee` loadout built from one weapon can
#: only be right for one of the three; the other two would price a
#: resisted attack type as if it were the map's best.
#:
#: `build_loadouts` builds one of these whenever `picks` carries a
#: `{style}-weapon`/`{style}-2h` entry for it, which happens today only when
#: a caller asks - every other consumer's `picks` already contains the keys
#: and has always ignored them, so this is additive and nothing already
#: working changes shape.
MELEE_SUBSTYLES = ("Stab", "Slash", "Crush")

#: The damage-maximising stance for each style, which is what someone killing
#: for a drop would use. Stance buys invisible level boosts that differ
#: between accuracy and max hit, so it cannot be inferred from the style.
#: The three substyles are still ordinary melee, so they share `Melee`'s.
_STANCES = {
    "Melee": "Aggressive",
    "Ranged": "Rapid",
    "Magic": "Accurate",
    **{style: "Aggressive" for style in MELEE_SUBSTYLES},
}

#: Ticks a stance adds to the weapon's own attack speed.
#:
#: **This is the caller's job, not the library's.** `osrs-dps` leaves
#: `getAttackSpeed` unported on the grounds that resolving a weapon and stance
#: into a speed is equipment resolution - it reads `Loadout.attack_speed` and
#: expects the stance already folded in. Declaring `stance="Rapid"` while
#: passing the weapon's base speed therefore bought the accuracy profile of
#: Rapid and none of its speed, costing every ranged kill a quarter of its
#: rate.
_STANCE_SPEED_TICKS = {"Rapid": -1}

#: Which skill's boost applies to each style's damage. **`Attack` is absent
#: from the export's `boostItems` entirely** - it is `null`, where `Strength`,
#: `Ranged`, `Magic` and `Defence` all have tables - so a melee attack roll
#: never boosts here even though a super combat potion boosts it in the game.
#: Following the export is the rule (see the module docstring); the effect is
#: to understate melee accuracy, which lengthens kills rather than shortening
#: them.
_BOOSTED_SKILLS = ("Strength", "Ranged", "Magic", "Defence")

#: Prayer tiers per style, strongest first: `(prayers, prayer level, defence
#: level, item required)`. The first tier the player qualifies for wins.
#:
#: Below the capes, the accuracy and strength prayers are **separate and
#: stack**, which is why these are sets rather than single names - a player at
#: 40 Prayer runs Ultimate Strength *and* Incredible Reflexes together.
#:
#: Rigour and Augury are gated on an item rather than only a level, because
#: they are unlocked by a scroll that has to be obtained. That makes them
#: checkable against what the map reaches, unlike Piety, whose quest
#: requirement nothing here records - Piety is granted on level alone, which
#: is the one optimistic assumption in this table.
_PRAYER_TIERS: dict[str, tuple[tuple[frozenset[str], int, int, str], ...]] = {
    "Melee": (
        (frozenset({"Piety"}), 70, 70, ""),
        (frozenset({"Chivalry"}), 60, 65, ""),
        (frozenset({"Ultimate Strength", "Incredible Reflexes"}), 34, 0, ""),
        (frozenset({"Superhuman Strength", "Improved Reflexes"}), 16, 0, ""),
        (frozenset({"Burst of Strength", "Clarity of Thought"}), 7, 0, ""),
    ),
    "Ranged": (
        (frozenset({"Rigour"}), 74, 0, "Dexterous prayer scroll"),
        (frozenset({"Eagle Eye"}), 44, 0, ""),
        (frozenset({"Hawk Eye"}), 26, 0, ""),
        (frozenset({"Sharp Eye"}), 8, 0, ""),
    ),
    "Magic": (
        (frozenset({"Augury"}), 77, 0, "Arcane prayer scroll"),
        (frozenset({"Mystic Might"}), 45, 0, ""),
        (frozenset({"Mystic Lore"}), 27, 0, ""),
        (frozenset({"Mystic Will"}), 9, 0, ""),
    ),
}

#: The strongest standard-spellbook attack spell at each Magic level. Without
#: one a magic loadout has **no max hit at all** and the library refuses it -
#: which is how magic silently priced nothing at all until this table existed.
#:
#: Runes are not checked. A map holding a magic weapon is assumed to be able
#: to cast with it, which is the optimistic direction and the one assumption
#: here that is not gated on reachability. Elemental spells resolve by tier
#: inside the library anyway, so naming the tier is what matters, not the
#: element.
_SPELL_TIERS: tuple[tuple[int, str], ...] = (
    (95, "Fire Surge"),
    (85, "Water Surge"),
    (75, "Fire Wave"),
    (65, "Water Wave"),
    (59, "Fire Blast"),
    (47, "Water Blast"),
    (35, "Fire Bolt"),
    (23, "Water Bolt"),
    (13, "Fire Strike"),
    (1, "Wind Strike"),
)

#: Defence-draining weapons this can model. A boss's defence drives accuracy,
#: which drives everything, so a map holding one of these kills far faster
#: than the plain numbers suggest - the Corporeal Beast is not sensibly
#: killable without one.
#:
#: **The Bandos godsword is deliberately absent.** Its `DefenceReductions`
#: field counts *damage dealt*, not specials landed, so filling it needs a
#: special-attack damage estimate this module does not have. Leaving it out
#: understates a map that holds one, which is the safe direction.
#:
#: `assemble_kit` names each of these explicitly rather than looping this
#: table, because `accursed` is a flag where the rest are counts.
_DRAIN_WEAPONS = (
    "Elder maul",
    "Dragon warhammer",
    "Arclight",
    "Emberlight",
    "Accursed sceptre",
)

#: The wilderness weapons, whose bonus is worth +50% damage and is gated on
#: **two** things the export cannot express: being in the wilderness, and the
#: weapon being charged.
#:
#: The export carries charge state *in the name* - `Webweaver bow` and
#: `Webweaver bow (u)` are separate entries with **identical stats** - where
#: the library carries it as `Loadout.weapon_version`. Identical stats mean
#: `bis.py` picks between them on a tie, and it picked the uncharged one; the
#: library's special case then never fired, because its name list holds only
#: `Webweaver bow`. Translating the suffix into `weapon_version` is what makes
#: the two models agree, and it is only done when the charged form is
#: genuinely reachable - a map holding only the uncharged one keeps it.
_WILDERNESS_WEAPONS = frozenset(
    {
        "Craw's bow",
        "Webweaver bow",
        "Viggora's chainmace",
        "Ursine chainmace",
        "Thammaron's sceptre",
        "Accursed sceptre",
    }
)

#: The uncharged suffix the export appends. Not a general rule - only the
#: weapons above have a charge state this library models.
_UNCHARGED_SUFFIX = " (u)"

#: The wilderness, as OSRS region coordinates. A chunk id **is** a region id
#: (`regionX * 256 + regionY`), verified against known chunks: 12850 is
#: Lumbridge, 11833 holds the Crazy archaeologist. The wilderness spans
#: x 2944-3392 and y 3520-3968, which is these bounds once divided by 64.
#:
#: The eastern edge matters: region x53 begins at x 3392 and holds the Slayer
#: Tower, so an inclusive upper bound of 52 is what keeps abyssal demons out
#: of the wilderness.
_WILDERNESS_REGION_X = range(46, 53)
_WILDERNESS_REGION_Y = range(55, 63)

#: Specials assumed landed before the fight proper. Two is a realistic opener
#: on a full bar, not a maximum - a longer fight regenerates energy and lands
#: more, which this does not model.
_OPENING_SPECIALS = 2

#: Bosses that are not soloable, and whose kill time is therefore not a number
#: this module should produce. The wiki's rates for these describe a *team*,
#: so comparing against them is meaningless too. Curated: nothing in the
#: export marks group content.
GROUP_BOSSES = frozenset(
    {
        "Nex",
        "Corporeal Beast",
        # The team version. `Phosani's Nightmare` is the solo one and stays
        # priceable, however badly.
        "The Nightmare",
        "Verzik Vitur",
        "Tekton",
        "Great Olm",
        "Nylocas Vasilias",
        "Pestilent Bloat",
        "Sotetseg",
        "Xarpus",
        "Maiden of Sugadinti",
    }
)

#: Every boss `costing/fightscripts.py` prices as phases rather than as one
#: damage race, keyed by the bare name `best_kill` is asked about. Composed
#: here rather than in `fightscripts.py` itself: that module is a pure leaf
#: like `encounter.py`, and a leaf importing every boss module it describes
#: would be `raids.py`'s job done in the wrong file. One entry per scripted
#: boss - `costing/hydra.py`, `costing/nightmare.py`, `costing/zulrah.py`,
#: `costing/sire.py` and `costing/grotesque_guardians.py` today, plus the
#: three `costing/moons.py` composes itself (one per Moon, keyed by name -
#: see that module for why it owns three rather than exporting one `SCRIPT`
#: like every other entry here) and the two `costing/vetion.py` composes for
#: the same reason `costing/royal_titans.py` does - `Vet'ion`/`Calvar'ion`
#: are each their own boss with their own drop table, not variants of one.
#: Araxxor and Cerberus were both considered
#: and refused a script: Araxxor's real enrage mechanic (25% health, +35
#: defence) has no separate `osrs_dps` key to price it against - the library
#: carries only one bare `Araxxor` entry despite the wiki's own infobox
#: declaring an enraged version - and fabricating one by hand-adjusting
#: defence would invent exactly what this project has no authority to
#: reproduce; Cerberus's Summoned Souls costs prayer and damage but never
#: stops the player attacking her directly, so it is a resource cost rather
#: than the downtime shape a `Phase` prices. Neither omission is a
#: `costing/` module - there is nothing here to write a docstring next to.
SCRIPTS: Mapping[str, FightScript] = {
    _doom_of_mokhaiotl.SCRIPT.name: _doom_of_mokhaiotl.SCRIPT,
    _duke_sucellus.SCRIPT.name: _duke_sucellus.SCRIPT,
    _grotesque_guardians.SCRIPT.name: _grotesque_guardians.SCRIPT,
    _hueycoatl.SCRIPT.name: _hueycoatl.SCRIPT,
    _hydra.SCRIPT.name: _hydra.SCRIPT,
    _kalphite_queen.SCRIPT.name: _kalphite_queen.SCRIPT,
    _nex.SCRIPT.name: _nex.SCRIPT,
    _nightmare.SCRIPT.name: _nightmare.SCRIPT,
    _phantom_muspah.SCRIPT.name: _phantom_muspah.SCRIPT,
    _sire.SCRIPT.name: _sire.SCRIPT,
    _vorkath.SCRIPT.name: _vorkath.SCRIPT,
    _yama.SCRIPT.name: _yama.SCRIPT,
    _zulrah.SCRIPT.name: _zulrah.SCRIPT,
    **_moons.SCRIPTS,
    **_royal_titans.SCRIPTS,
    **_vetion.SCRIPTS,
}

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

def _melee_attack_bonuses() -> tuple[tuple[str, "CombatStyle"], ...]:
    """The three melee bonuses paired with the style each one drives.

    **A function rather than a module-level tuple, and that is the whole
    point.** `CombatStyle` comes from the optional library, so building this at
    import time made `import chunksim.costing.dps_bridge` raise `NameError`
    wherever the extra was absent - which is every install that did not opt in,
    and contradicts the one promise this module makes: importing is always
    safe, only calling is not. The annotation was already quoted; the *values*
    were not, and a quoted annotation is exactly what hides that.

    Not memoised: it is three tuples built on a path that is already about to
    run a DPS calculation, and a module-level cache is what this module is not
    allowed to have.
    """
    return (
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
class Kit:
    """What the map brings to a fight beyond the gear it wears.

    Assembled by `assemble_kit` from what the map actually reaches, so an
    early chunk gets none of it and a late one gets all of it. Every field
    defaults inert, which makes an unsupplied `Kit` the plain-gear estimate
    rather than a silently boosted one.

    These are the four things the wiki's own kill rates assume and the bare
    gear numbers do not, and between them they are worth more than the gear:
    a boss that takes 6,700 seconds unprayed and unboosted is not the same
    fight the money-making guide is describing.
    """

    #: Skill name -> levels added, from reachable potions.
    boosts: Mapping[str, int] = field(default_factory=dict)
    #: Style name -> the prayers to run. See `_PRAYER_TIERS`.
    prayers: Mapping[str, frozenset[str]] = field(default_factory=dict)
    #: The strongest castable standard-book spell, or `""` for none.
    spell: str = ""
    #: Defence draining the map can bring, already counted in specials.
    reductions: DefenceReductions | None = None
    #: Items the map reaches, for the charge-state swap. See `_charged`.
    items: Mapping[str, Any] = field(default_factory=dict)
    #: Monsters the map places in the wilderness, which is half of what gates
    #: the wilderness weapons' +50%. See `wilderness_monsters`.
    wilderness: frozenset[str] = frozenset()


def assemble_kit(
    chunk_info: ChunkInfo,
    levels: Mapping[str, int],
    *,
    items: Mapping[str, Any],
    source_index: Any,
) -> Kit:
    """The boosts, prayers, spell and defence draining this map can bring.

    `items` is `ChallengeResult.available_items` and `source_index` the
    `SourceIndex` - the same pair `boosts.py` takes, and for the same reason:
    the narrower `SourceIndex.items` omits anything obtainable only by making
    it, which silently loses boosts that are baked rather than dropped.
    """
    _require()

    boosts = {
        skill: combat_boost(
            skill,
            levels.get(skill, 1),
            chunk_info=chunk_info,
            items=items,
            source_index=source_index,
        )
        for skill in _BOOSTED_SKILLS
    }

    prayers: dict[str, frozenset[str]] = {}
    for style, tiers in _PRAYER_TIERS.items():
        for names, prayer_level, defence_level, item in tiers:
            if levels.get("Prayer", 1) < prayer_level:
                continue
            if levels.get("Defence", 1) < defence_level:
                continue
            if item and item not in items:
                continue
            prayers[style] = names
            break

    magic = levels.get("Magic", 1) + boosts.get("Magic", 0)
    spell = next((name for level, name in _SPELL_TIERS if magic >= level), "")

    def specials(weapon: str) -> int:
        return _OPENING_SPECIALS if weapon in items else 0

    reductions = None
    if any(weapon in items for weapon in _DRAIN_WEAPONS):
        reductions = DefenceReductions(
            elder_maul=specials("Elder maul"),
            dragon_warhammer=specials("Dragon warhammer"),
            arclight=specials("Arclight"),
            emberlight=specials("Emberlight"),
            # A flag rather than a count: the sceptre's effect either applied
            # or it did not, where a hammer stacks per special landed.
            accursed="Accursed sceptre" in items,
        )

    return Kit(
        boosts=boosts,
        prayers=prayers,
        spell=spell,
        reductions=reductions,
        items=items,
        wilderness=wilderness_monsters(source_index),
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
    #: Damage the monster deals to the player per second of fighting, from the
    #: library's reverse calculation. This is what makes the banking half of
    #: the overhead a measurement rather than a guess.
    damage_taken: float = 0.0
    #: Whether the export calls this a boss, which is what decides if a
    #: respawn timer is on the critical path. See `BOSS_RESPAWN_SECONDS`.
    is_boss: bool = False
    #: The winning loadout's attack speed in ticks, already carrying its
    #: stance. Drives the tick quantisation in `overhead`.
    attack_speed: int = 4
    #: The target's health. **Carried here rather than looked up again**, so
    #: that anything multiplying a kill rate by hitpoints uses the health of
    #: the version that was actually simulated. `Wolf` has several versions
    #: and the wiki's first row is not necessarily the one the library fought.
    hitpoints: float = 0.0

    @property
    def cycle_seconds(self) -> float:
        """Seconds per attack, from the weapon and stance."""
        return self.attack_speed * SECONDS_PER_TICK

    @property
    def tick_waste(self) -> float:
        """Fighting time lost to the attack cycle not dividing the kill.

        **The game runs on ticks and a weapon fires on its own cadence**, so a
        kill does not end when the last point of health goes: it ends on the
        attack that took it, and nothing can happen until the next cycle comes
        round. A four-tick weapon acts every 2.4 seconds whatever the target
        is doing, so a kill is always a whole number of cycles long.

        **One caveat, because it flatters this number slightly.** `ttk` is a
        *mean* over kills that each already took a whole number of attacks, so
        rounding the mean up is not the same as rounding each kill up - it
        overstates by up to half a cycle. That bias is left in knowingly: it
        stands in for the walking between spawns that nothing else here
        charges for, and the measured spread is better with it than without
        (mean absolute log ratio 0.81 against 0.85).
        """
        cycle = self.cycle_seconds
        if cycle <= 0 or self.ttk <= 0:
            return 0.0
        return math.ceil(self.ttk / cycle) * cycle - self.ttk

    def overhead(
        self,
        *,
        health_pool: float = INVENTORY_HEALING + 99.0,
        banking: float = BANKING_SECONDS,
    ) -> float:
        """Seconds of not-fighting this kill costs.

        Every kill pays the same two small mechanical costs first: `tick_waste`
        for the attack cycle it cannot start early, and `RETARGET_TICKS` for
        shifting focus to the next monster. Neither depends on what is being
        killed, and together they are most of a trash mob's whole overhead.

        Then respawn plus banking, and **banking is worked out two different
        ways and which one applies is the interesting part**.

        *A boss* pays `BOSS_RESPAWN_SECONDS` for its timer, since its lair
        holds one of it, plus `BOSS_BANKING_FRACTION` of the fight. It does
        **not** use the damage measurement below: that needs the damage to be
        right, and for a boss it is not, because overhead prayers are not
        modelled and nobody fights one without them.

        *Everything else* pays no respawn - there is always another spectre in
        the cave - and a banking cost amortised over a trip. A trip ends when
        damage taken exhausts what the player can absorb, so it yields
        `health_pool / (damage_taken * ttk)` kills and each carries its share
        of one bank run. That reduces to `banking * damage_per_kill /
        health_pool`: **the banking cost is proportional to the damage a kill
        costs you**. A rat that never lands a hit needs no trip at all and
        gets nothing.

        The two branches meet in the middle rather than clashing: a boss's
        share-of-the-fight works out at 10-20% across the whole range of kill
        times, which is what the damage model would give if its damage input
        were trustworthy.
        """
        mechanical = self.tick_waste + RETARGET_TICKS * SECONDS_PER_TICK

        if self.is_boss:
            return mechanical + BOSS_RESPAWN_SECONDS + BOSS_BANKING_FRACTION * self.ttk

        damage_per_kill = self.damage_taken * self.ttk
        if damage_per_kill <= 0 or health_pool <= 0:
            return mechanical
        return mechanical + banking * damage_per_kill / health_pool

    def kills_per_hour(self, overhead: float | None = None) -> float:
        """Kills per hour: this kill's fighting time plus its overhead.

        `overhead` overrides the computed one, for callers comparing models.
        """
        cycle = self.ttk + (self.overhead() if overhead is None else overhead)
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


def in_wilderness(chunk_id: str) -> bool:
    """Whether a chunk id names a region inside the wilderness.

    A chunk id is an OSRS region id, so the coordinates fall straight out of
    it. See `_WILDERNESS_REGION_X`.
    """
    if not chunk_id.isdigit():
        return False
    region = int(chunk_id)
    return (region >> 8) in _WILDERNESS_REGION_X and (region & 0xFF) in _WILDERNESS_REGION_Y


def wilderness_monsters(source_index: Any) -> frozenset[str]:
    """Every monster the map places inside the wilderness.

    `SourceIndex.monsters` keys each monster's locations as `"{chunk}-{section}"`,
    so this is the chunk half of those keys run through `in_wilderness`. A
    monster placed in several chunks counts if *any* of them is in the
    wilderness, since that is where someone chasing its drop would go.
    """
    found = set()
    for monster, locations in source_index.monsters.items():
        for key in locations:
            if in_wilderness(str(key).split("-")[0]):
                found.add(monster)
                break
    return frozenset(found)


def _charged(worn: Mapping[str, str], items: Mapping[str, Any]) -> dict[str, str]:
    """`worn` with reachable wilderness weapons swapped to their charged form.

    See `_WILDERNESS_WEAPONS` for why the uncharged form gets picked in the
    first place and why leaving it alone silently disables a +50% bonus.
    """
    swapped = dict(worn)
    for slot, name in worn.items():
        if not name.endswith(_UNCHARGED_SUFFIX):
            continue
        base = name[: -len(_UNCHARGED_SUFFIX)]
        if base in _WILDERNESS_WEAPONS and base in items:
            swapped[slot] = base
    return swapped


def _melee_style(weapon: Mapping[str, Any]) -> CombatStyle:
    """The damage type a melee weapon rolls, by its own best attack bonus.

    `bis.py`'s `Melee` winner is a weapon, not a style - an abyssal whip is
    slash and a dragon dagger stab, and the export says which by where the
    bonus sits. Ties fall to stab, matching the field order.
    """

    def bonus(key: str) -> float:
        value = weapon.get(key, 0)
        return float(value) if isinstance(value, (int, float)) else 0.0

    _, style = max(_melee_attack_bonuses(), key=lambda pair: bonus(pair[0]))
    return style


def build_loadouts(
    chunk_info: ChunkInfo,
    picks: Mapping[str, str],
    levels: Mapping[str, int],
    kit: Kit | None = None,
) -> dict[str, Loadout]:
    """A `Loadout` per offensive style, from `BisResult.picks`.

    `picks` is keyed `"{style}-{slot}"`, so each style's worn set is every
    pick whose key starts with it. Slots the map cannot fill are simply
    absent, which is a thinner set rather than an error - an early chunk with
    no magic weapon should price a magic kill badly, not refuse to price it.

    `levels` is `estimate.infer_levels`'s floor, so an unproven skill reads as
    level 1 and the kill comes out slow. That is the conservative direction.

    `kit` adds the prayers, potion boosts and spell the map can reach. Without
    one the loadouts are bare gear, which is a *far* slower fight than anyone
    actually has - see `Kit`.

    **Also builds `MELEE_SUBSTYLES`' three loadouts, when `picks` carries
    them** - `Stab`/`Slash`/`Crush`, each ranked on its own attack bonus
    rather than the best of the three. `derived.bis.picks` always has the
    keys; every caller before `costing/moons.py` simply had nothing that
    needed them, so this is silent for everyone else.
    """
    _require()
    equipment = chunk_info.equipment
    kit = kit or Kit()
    loadouts: dict[str, Loadout] = {}

    for style in OFFENSIVE_STYLES + MELEE_SUBSTYLES:
        prefix = f"{style}-"
        worn = {
            key[len(prefix) :]: name for key, name in picks.items() if key.startswith(prefix)
        }
        if not worn:
            continue

        worn = _charged(worn, kit.items)
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
        base_speed = int(speed) if isinstance(speed, (int, float)) and speed > 0 else 4
        # Never below one tick, whatever the stance would take it to.
        attack_speed = max(1, base_speed + _STANCE_SPEED_TICKS.get(_STANCES[style], 0))
        two_handed = weapon.get("slot") == "2h"

        if style == "Melee" or style in MELEE_SUBSTYLES:
            # `_melee_style` reads the weapon's own bonuses, not the pick
            # key's name - a `Crush-weapon` winner that happens to be a
            # stabbing weapon (a thin BiS table, or a caller asking anyway)
            # still resolves to whatever it actually rolls as.
            combat_style = _melee_style(weapon)
        elif style == "Ranged":
            combat_style = CombatStyle.RANGED
        else:
            combat_style = CombatStyle.MAGIC

        def boosted(skill: str, floor: int = 1) -> int:
            return levels.get(skill, floor) + kit.boosts.get(skill, 0)

        loadouts[style] = Loadout(
            levels=Levels(
                # Attack alone never boosts: the export has no `boostItems`
                # table for it. See `_BOOSTED_SKILLS`.
                attack=levels.get("Attack", 1),
                strength=boosted("Strength"),
                defence=boosted("Defence"),
                ranged=boosted("Ranged"),
                magic=boosted("Magic"),
                hitpoints=levels.get("Hitpoints", 10),
                prayer=levels.get("Prayer", 1),
            ),
            bonuses=bonuses,
            attack_speed=attack_speed,
            style=combat_style,
            stance=_STANCES[style],
            prayers=kit.prayers.get(style, frozenset()),
            # Magic needs a named spell or it has no max hit at all and the
            # library refuses the loadout outright. The other two styles must
            # *not* carry one - a spell names a manual cast.
            spell=kit.spell if style == "Magic" else "",
            worn=frozenset(worn.values()),
            weapon_name=worn.get(weapon_pick, ""),
            # Charge state is a `version` in the library and a name suffix in
            # the export; `_charged` has already reconciled the two, so a
            # wilderness weapon reaching here is the charged one.
            weapon_version=(
                "Charged" if worn.get(weapon_pick, "") in _WILDERNESS_WEAPONS else ""
            ),
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


def version_index(index: MonsterIndex) -> dict[str, tuple[str, ...]]:
    """`bare name -> the library's versioned keys for it`, in index order.

    `candidate_targets` otherwise scans all ~1,382 keys per bare name, and
    `price_slayer_tasks` asks about the same names once per master per task.
    Built in one pass and threaded in; the order matches the scan it replaces,
    which is what keeps `best_kill`'s tie-break identical.
    """
    found: dict[str, list[str]] = {}
    for key in index:
        bare, sep, _ = key.partition("#")
        if sep:
            found.setdefault(bare, []).append(key)
    return {bare: tuple(keys) for bare, keys in found.items()}


def candidate_targets(
    index: MonsterIndex,
    name: str,
    versions_by_name: Mapping[str, tuple[str, ...]] | None = None,
) -> tuple[tuple[str, Target], ...]:
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
    versions = (
        list(versions_by_name.get(name, ()))
        if versions_by_name is not None
        else [key for key in index if key.startswith(prefix)]
    )
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


def kills_by_style(
    loadouts: Mapping[str, Loadout],
    name: str,
    candidates: Iterable[tuple[str, Target]],
    *,
    on_slayer_task: bool = False,
    reductions: DefenceReductions | None = None,
    wilderness: bool = False,
    boss: bool = False,
    prefer: str = "ttk",
    raid: RaidInputs | None = None,
) -> dict[str, KillEstimate]:
    """The best kill **per combat style**, for every style that can kill.

    `best_kill` is the minimum of this, and used to be the only thing on
    offer. That was right while the only question was "how long until the
    drop", where nobody cares which hand held the weapon - and wrong the
    moment combat *experience* was priced, because training Magic means
    casting at it even when a whip would be quicker. Collapsing to one style
    made every combat skill quote the same rate.

    One pass over both axes - style and monster version - keeping a winner for
    each style, so asking for three costs what asking for one used to.

    **`prefer` decides what "best" means, and the two answers differ by an
    order of magnitude.** For a drop, the quickest kill wins: `ttk`. For
    experience, the most *damage per hour* wins - `damage` - because XP is
    paid per point of health removed. `Wolf` has five versions between 10 and
    69 health; the level 11 one dies fastest and pays a sixth as much. Pricing
    combat off the fastest kill and then multiplying by some other version's
    health is how a wolf came to look like the best training in the game.
    """
    _require()
    pairs = tuple(candidates)
    if not pairs or not loadouts:
        return {}

    # The buffs depend on the loadout and the fight's *context*, neither of
    # which varies across `pairs` - so arm each style once rather than once
    # per version. `_with_buffs` is a pure `replace`, so these are the same
    # objects the loop used to build.
    armed_by_style = {
        style: _with_buffs(loadout, on_task=on_slayer_task, wilderness=wilderness)
        for style, loadout in loadouts.items()
    }

    best: dict[str, KillEstimate] = {}
    for key, target in pairs:
        fight = target
        if on_slayer_task and not target.is_slayer_monster:
            fight = _slayer_target(target)
        # **The raid inputs and the drain are one call, not two.** `scale`
        # reads every rule off one `RaidInputs`, so applying the defence drain
        # separately from a party size would run the scaling twice and compound
        # what the second pass read off the first pass's output.
        if raid is not None or reductions is not None:
            fight = scale(
                fight,
                replace(raid, defence_reductions=reductions)
                if raid is not None and reductions is not None
                else raid or RaidInputs(defence_reductions=reductions or DefenceReductions()),
            )
        for style, armed in armed_by_style.items():
            try:
                result = dps(armed, fight)
            except Unsupported:
                continue
            # A zero rate is the library saying "never killed"; its companion
            # ttk of 0.0 is a convention, not a fast kill. Read the pair.
            if result.dps <= 0 or result.expected_ttk <= 0:
                continue
            found = KillEstimate(
                monster=key,
                style=style,
                ttk=result.expected_ttk,
                dps=result.dps,
                max_hit=result.max_hit,
                accuracy=result.accuracy,
                match="exact" if key == name else "variant",
                # Measured against the gear that won, since that is what
                # the player is standing in while being hit.
                damage_taken=damage_taken_per_second(armed, fight),
                is_boss=boss,
                attack_speed=armed.attack_speed,
                # **`fight`, not `target`.** `fight` is what `dps()` just
                # fought - the slayer/raid-scaled `Target` - and `target` is
                # the library's own unscaled entry. They read identically
                # everywhere `raid`/slayer scaling never applies (`ttk`/`dps`
                # already come from `fight` two lines up), but a raid
                # monster's real health is nothing like its base row: Akkha
                # is 400 unscaled and 1,040 at raid level 400. A caller
                # multiplying this by a per-damage reward (`tombs.points_for`)
                # would have scored a raid-level-400 Tombs run on its
                # level-zero health.
                hitpoints=float(getattr(fight, "hitpoints", 0) or 0),
            )
            standing = best.get(style)
            if standing is None or _score(found, prefer) > _score(standing, prefer):
                best[style] = found
    return best


def _score(kill: KillEstimate, prefer: str) -> float:
    """How good a kill is, by whichever objective the caller asked for."""
    if prefer == "damage":
        return kill.kills_per_hour() * kill.hitpoints
    return -kill.ttk


def _phase_seconds(phase: Phase, target: Target, kill: KillEstimate) -> float | None:
    """One `Phase`'s own contribution to a scripted kill's total time.

    `kill` is `phase.target` priced as a whole fight from full health, so
    `target.hitpoints / kill.ttk` is this phase's own damage-per-second - the
    figure `Phase.hp_share` divides. `None` only when the phase genuinely
    cannot be damaged, which `kills_by_style` would already have refused
    upstream by returning no kill at all.
    """
    if kill.ttk <= 0 or target.hitpoints <= 0:
        return None
    base_dps = target.hitpoints / kill.ttk
    phase_hp = target.hitpoints * phase.hp_share
    if phase.reduced_seconds <= 0:
        return phase_hp / base_dps + phase.idle_seconds
    reduced_rate = base_dps * phase.reduced_dps_fraction
    reduced_damage = reduced_rate * phase.reduced_seconds
    if reduced_damage >= phase_hp:
        # Dies inside its own reduction window - a small `hp_share` against a
        # long `reduced_seconds`. Still priced rather than refused: the
        # reduced rate is real damage, just slower than the phase's normal
        # one.
        if reduced_rate <= 0:
            return None
        return phase_hp / reduced_rate + phase.idle_seconds
    remaining = phase_hp - reduced_damage
    return phase.reduced_seconds + remaining / base_dps + phase.idle_seconds


def _scripted_kill(
    script: FightScript,
    loadouts: Mapping[str, Loadout],
    candidates: Iterable[tuple[str, Target]],
    *,
    index: MonsterIndex | None = None,
    reductions: DefenceReductions | None,
    boss: bool,
) -> KillEstimate | None:
    """`script` priced against `candidates` - the same `(key, Target)` pairs
    `best_kill` was already handed for this boss's bare name - falling back
    to `index` for a phase `candidates` was never going to hold.

    **Usually reuses `candidates` rather than re-resolving the index**,
    because `candidate_targets(index, "Alchemical Hydra", versions)` already
    returns all four `#Serpentine`/`#Electric`/`#Fire`/`#Extinguished`
    entries - every key a `Phase.target` could name, since every phase's
    target shares the boss's own name prefix. **`costing/sire.py` is the
    exception**: its lung phase is fought against `Respiratory system`, a
    genuinely different monster with its own drop table, not an
    `Abyssal Sire#...` key - `candidate_targets(index, "Abyssal Sire", ...)`
    was never going to include it, because it is scoped to `"Abyssal
    Sire"`'s own name and versions by design. `index`, when given, is
    checked for exactly that case: a phase target absent from `candidates`
    but present in the library under its own bare name. A phase missing from
    *both* is refused rather than silently skipped, the same all-or-nothing
    rule `encounter.build` states for a raid room.

    Each phase gets its own style choice via `kills_by_style` on a
    single-entry candidate list - forcing the search onto exactly that
    phase's stats, which is what makes a form-swapping boss like Zulrah
    priceable per form rather than once for the whole fight.

    **Calls `kills_by_style` directly, never `best_kill`.** A phase whose
    `target` happens to equal the script's own `name` is not a hypothetical -
    `costing/nightmare.py`'s one phase is priced against `"Phosani's
    Nightmare"`, exactly the string `SCRIPTS` is keyed on - and `best_kill`
    checks `SCRIPTS` before anything else. Calling back into it here would
    recurse into this same function forever the day such a boss existed;
    calling the style search underneath it instead is both the fix and the
    right layer, since all this loop ever wanted from `best_kill` was "try
    every style, keep the fastest."
    """
    by_key = dict(candidates)
    total_seconds = 0.0
    total_hp = 0.0
    weighted_damage_taken = 0.0
    style = ""
    attack_speed = 4
    for phase in script.phases:
        target = by_key.get(phase.target)
        if target is None and index is not None:
            target = index.get(phase.target)
        if target is None:
            return None
        # `phase.styles` narrows which loadouts are even offered, rather than
        # letting a style that deals zero real damage in-game win a search
        # that has no way to know that on its own - see `Phase.styles`.
        phase_loadouts = (
            loadouts
            if phase.styles is None
            else {style: l for style, l in loadouts.items() if style in phase.styles}
        )
        if not phase_loadouts:
            return None
        styled = kills_by_style(
            phase_loadouts,
            phase.target,
            ((phase.target, target),),
            reductions=reductions,
            boss=boss,
        )
        kill = min(styled.values(), key=lambda k: k.ttk, default=None)
        if kill is None:
            return None
        priced = _phase_seconds(phase, target, kill)
        if priced is None or priced <= 0:
            return None
        total_seconds += priced
        phase_hp = target.hitpoints * phase.hp_share
        total_hp += phase_hp
        weighted_damage_taken += kill.damage_taken * phase_hp
        style, attack_speed = kill.style, kill.attack_speed
    if total_seconds <= 0 or total_hp <= 0:
        return None
    return KillEstimate(
        monster=script.name,
        # **The last phase's style, not a blend.** `style` exists so a
        # trainer knows which hand to credit XP to; a multi-phase fight
        # genuinely trains several, and picking one is already an
        # approximation `combat_xp.py` does not currently read for scripted
        # bosses - see the module docstring on that gap.
        style=style,
        ttk=total_seconds,
        dps=total_hp / total_seconds,
        # Neither is meaningful for a fight that changes style and target
        # every phase - `max_hit`/`accuracy` are read nowhere downstream of
        # `KillEstimate` beyond their own construction.
        max_hit=0,
        accuracy=0.0,
        match="scripted",
        damage_taken=weighted_damage_taken / total_hp,
        is_boss=boss,
        attack_speed=attack_speed,
        hitpoints=total_hp,
    )


def best_kill(
    loadouts: Mapping[str, Loadout],
    name: str,
    candidates: Iterable[tuple[str, Target]],
    *,
    index: MonsterIndex | None = None,
    on_slayer_task: bool = False,
    reductions: DefenceReductions | None = None,
    wilderness: bool = False,
    boss: bool = False,
    raid: RaidInputs | None = None,
) -> KillEstimate | None:
    """The fastest way to kill `name` with the gear on offer, or `None`.

    Fastest across **both** axes: which BiS style to use, and - when the name
    was ambiguous - which version of the monster. Trying all three styles is
    not a nicety: a monster's defences are wildly uneven, and Zulrah's magma
    form takes **nothing** from melee while answering ranged normally. Picking
    a style up front would price a fight nobody would choose to have.

    **A scripted boss is priced by its script first.** `SCRIPTS` names every
    boss `costing/fightscripts.py` knows is not one damage race - the
    Alchemical Hydra swaps its whole stat block four times in a kill, and
    "which version resolves fastest" is the wrong question to ask about it.
    `_scripted_kill` reuses this same function per phase, on that phase's own
    single-key candidate list, so the ordinary style search still runs - just
    once per phase instead of once for the whole fight. `candidates` still has
    to be passed for a scripted boss: it is where each phase's own `Target` is
    read from, and an empty or stale one is refused exactly as it is below.
    **`index`, when given, is `_scripted_kill`'s fallback** for a phase whose
    target is not merely a version of `name` - `costing/sire.py`'s lung
    phase fights `Respiratory system`, a wholly different monster, so
    `candidates` (scoped to `"Abyssal Sire"`'s own versions) never carries
    it. Every real caller in this module already has a `MonsterIndex` in
    scope and passes it through; `None` is only for a caller (or a test) that
    knows every phase it will ever ask about shares the boss's own prefix.

    `reductions` drains the target's defence before any of that, which is the
    difference between a plausible boss time and a nonsensical one - defence
    drives accuracy, and accuracy drives everything.

    `None` means no combination produced a kill: an empty `candidates`, a
    loadout that cannot damage the target (`dps == 0`, which the library
    reports with `expected_ttk == 0`), or every pairing refused as
    `Unsupported`. All three are "do not price this", not "price it at zero".
    """
    script = SCRIPTS.get(name)
    if script is not None:
        return _scripted_kill(
            script, loadouts, candidates, index=index, reductions=reductions, boss=boss
        )
    found = kills_by_style(
        loadouts,
        name,
        candidates,
        on_slayer_task=on_slayer_task,
        reductions=reductions,
        wilderness=wilderness,
        boss=boss,
        raid=raid,
    )
    return min(found.values(), key=lambda kill: kill.ttk, default=None)


def _with_buffs(loadout: Loadout, *, on_task: bool, wilderness: bool) -> Loadout:
    """`loadout` with the fight's circumstances set.

    Both are properties of *where and why* the fight happens rather than of
    the gear, which is why they are applied per monster rather than baked in
    when the loadout is built: the same bow is worth half as much again
    against a wilderness boss as against anything else.
    """
    if not on_task and not wilderness:
        return loadout
    return replace(
        loadout,
        buffs=replace(
            loadout.buffs, on_slayer_task=on_task, in_wilderness=wilderness
        ),
    )


def _slayer_target(target: Target) -> Target:
    """`target` marked as counting for a slayer assignment."""
    return replace(target, is_slayer_monster=True)


@dataclass(frozen=True)
class CombatRate:
    """The best monster to train one combat style on, and how fast.

    `damage_per_hour` is the whole answer: combat experience is a constant
    times damage, so this is what `costing/combat_xp.py` multiplies. It pairs
    **this library's** hitpoints with **this library's** kill rate, which is
    the reason it lives here rather than being assembled by the caller from
    two sources that need not agree about which `Wolf` is meant.
    """

    style: str
    monster: str
    damage_per_hour: float
    kills_per_hour: float
    hitpoints: float
    xp_multiplier: float = 1.0
    match: str = "exact"

    def as_dict(self) -> dict[str, Any]:
        return {
            "style": self.style,
            "monster": self.monster,
            "damage_per_hour": round(self.damage_per_hour, 1),
            "kills_per_hour": round(self.kills_per_hour, 2),
            "hitpoints": self.hitpoints,
            "xp_multiplier": self.xp_multiplier,
            "match": self.match,
        }


def price_combat(
    chunk_info: ChunkInfo,
    picks: Mapping[str, str],
    levels: Mapping[str, int],
    monsters: Iterable[str],
    *,
    index: MonsterIndex | None = None,
    slayer_monsters: frozenset[str] = frozenset(),
    boss_monsters: frozenset[str] = frozenset(),
    kit: Kit | None = None,
    multipliers: Mapping[str, float] | None = None,
    caps: Mapping[str, float] | None = None,
) -> dict[str, CombatRate]:
    """The best training target for each combat style: `{style: CombatRate}`.

    **Per style, because that is what decides the experience.** A map with a
    whip and no decent bow trains Ranged far more slowly than melee, and one
    figure for all three said otherwise.

    `caps` limits a monster's kills per hour - see `combat_xp.spawn_caps`,
    which is how "there are only two of these on the map" reaches a number
    that otherwise assumes an endless queue of them. `multipliers` is the
    monster's own experience bonus.
    """
    _require()
    monster_index = load_monster_index() if index is None else index
    versions = version_index(monster_index)
    loadouts = build_loadouts(chunk_info, picks, levels, kit)
    if not loadouts:
        return {}
    reductions = kit.reductions if kit is not None else None

    best: dict[str, CombatRate] = {}
    for name in monsters:
        if name in GROUP_BOSSES:
            continue
        for style, kill in kills_by_style(
            loadouts,
            name,
            candidate_targets(monster_index, name, versions),
            on_slayer_task=name in slayer_monsters,
            reductions=reductions,
            wilderness=name in kit.wilderness if kit is not None else False,
            boss=name in boss_monsters,
            prefer="damage",
        ).items():
            rate = kill.kills_per_hour()
            if rate <= 0 or kill.hitpoints <= 0:
                continue
            cap = None if caps is None else caps.get(name)
            if cap is not None and cap > 0:
                rate = min(rate, cap)
            multiplier = 1.0 if multipliers is None else multipliers.get(name, 1.0)
            damage = rate * kill.hitpoints * multiplier
            standing = best.get(style)
            if standing is None or damage > standing.damage_per_hour:
                best[style] = CombatRate(
                    style=style,
                    monster=name,
                    damage_per_hour=damage,
                    kills_per_hour=rate,
                    hitpoints=kill.hitpoints,
                    xp_multiplier=multiplier,
                    match=kill.match,
                )
    return best


@dataclass(frozen=True)
class PricedCombat:
    """One step's *training* fights, and what they were priced against.

    `PricedFights`' twin for the damage question, and deliberately not the
    same table: the two ask `kills_by_style` different things - `prefer="ttk"`
    for a drop, `prefer="damage"` for experience - and `kills_by_style`'s own
    docstring measures that at an order of magnitude, not a rounding.

    **The rows hold the simulation, before the cap and the multiplier.**
    Neither touches the fight - `spawn_caps` limits how many of a monster the
    map can queue up and the multiplier is its XP bonus, both arithmetic
    applied after - so a roll that moves either re-applies it to the carried
    row instead of re-simulating. That matters: a cap moves whenever a new
    chunk holds another spawn of the same monster, which is exactly the roll a
    carry would otherwise be thrown away on.

    What *does* invalidate a row is `fight_signature` moving, or the monster
    changing side of the ditch - `enrich_incremental`'s own two conditions,
    for its own reasons.
    """

    signature: tuple[Any, ...]
    #: `monster -> {style: (kills an hour, hitpoints, match)}`, uncapped.
    rows: Mapping[str, Mapping[str, tuple[float, float, str]]]
    #: Who was inside the ditch when these were priced.
    wilderness: frozenset[str] = frozenset()
    #: `(monster, style, skill) -> combat_curve_raw`'s own answer.
    curves: Mapping[tuple[str, str, str], Mapping[int, tuple[float, float]]] = field(
        default_factory=dict
    )


def price_combat_incremental(
    chunk_info: ChunkInfo,
    picks: Mapping[str, str],
    levels: Mapping[str, int],
    monsters: Iterable[str],
    *,
    previous: PricedCombat | None = None,
    index: MonsterIndex | None = None,
    slayer_monsters: frozenset[str] = frozenset(),
    boss_monsters: frozenset[str] = frozenset(),
    kit: Kit | None = None,
    multipliers: Mapping[str, float] | None = None,
    caps: Mapping[str, float] | None = None,
) -> tuple[dict[str, CombatRate], PricedCombat]:
    """`price_combat`, reusing whatever the previous roll already simulated.

    **`price_combat` is left alone on purpose**, exactly as `enrich` is beside
    `enrich_incremental`: only a timeline has a previous roll, so the reuse
    path is confined to the one caller that can use it and every other caller
    is provably unaffected. `tests/test_dps_bridge.py` asserts the two equal
    across a chain of real states rather than trusting the predicate - a wrong
    one here does not crash, it returns plausible numbers that drift.

    **The winner is recomputed over the current set every call**, never
    carried. A reused row says what a fight costs; which fight wins is a
    question about the whole set, and a new monster can take a style. Rows for
    monsters no longer in `monsters` are dropped rather than trusted, so the
    set shrinking - which measurement says does not happen, and which this
    does not need to assume - cannot leave a dethroned winner standing.
    """
    _require()
    monster_index = load_monster_index() if index is None else index
    versions = version_index(monster_index)
    loadouts = build_loadouts(chunk_info, picks, levels, kit)
    signature = fight_signature(picks, levels, kit) if kit is not None else ()
    here = kit.wilderness if kit is not None else frozenset()
    if not loadouts:
        return {}, PricedCombat(signature, {}, here)
    reductions = kit.reductions if kit is not None else None

    usable = previous if previous is not None and previous.signature == signature else None
    rows: dict[str, Mapping[str, tuple[float, float, str]]] = {}
    best: dict[str, CombatRate] = {}
    for name in monsters:
        if name in GROUP_BOSSES:
            continue
        row: Mapping[str, tuple[float, float, str]] | None = None
        if usable is not None and (name in here) == (name in usable.wilderness):
            row = usable.rows.get(name)
        if row is None:
            row = {
                style: (kill.kills_per_hour(), kill.hitpoints, kill.match)
                for style, kill in kills_by_style(
                    loadouts,
                    name,
                    candidate_targets(monster_index, name, versions),
                    on_slayer_task=name in slayer_monsters,
                    reductions=reductions,
                    wilderness=name in here,
                    boss=name in boss_monsters,
                    prefer="damage",
                ).items()
            }
        rows[name] = row
        cap = None if caps is None else caps.get(name)
        multiplier = 1.0 if multipliers is None else multipliers.get(name, 1.0)
        for style, (kills, hitpoints, match) in row.items():
            if kills <= 0 or hitpoints <= 0:
                continue
            rate = min(kills, cap) if cap is not None and cap > 0 else kills
            damage = rate * hitpoints * multiplier
            standing = best.get(style)
            if standing is None or damage > standing.damage_per_hour:
                best[style] = CombatRate(
                    style=style,
                    monster=name,
                    damage_per_hour=damage,
                    kills_per_hour=rate,
                    hitpoints=hitpoints,
                    xp_multiplier=multiplier,
                    match=match,
                )
    return best, PricedCombat(signature, rows, here, dict(usable.curves) if usable else {})


def combat_curve(
    chunk_info: ChunkInfo,
    picks: Mapping[str, str],
    levels: Mapping[str, int],
    monster: str,
    style: str,
    skill: str,
    *,
    index: MonsterIndex | None = None,
    kit: Kit | None = None,
    slayer_monsters: frozenset[str] = frozenset(),
    boss_monsters: frozenset[str] = frozenset(),
    caps: Mapping[str, float] | None = None,
    multiplier: float = 1.0,
) -> dict[int, float]:
    """`{level: damage_per_hour}` against `monster` in `style`, at every level
    1-99 of `skill` - everything else held at `levels`' own value.

    **One already-chosen target, not a search for a better one at each
    level.** `price_combat` has already picked the best monster for `style`;
    this asks how *that* fight scales as one stat rises, which is a cheap
    re-ask of `build_loadouts`/`kills_by_style` per level rather than a new
    kind of computation - `price_monsters` already prices ~750 monsters in
    under a second, and this is one monster asked up to 99 times. Whether a
    *different* target overtakes it partway up the climb is a harder question
    (which monster is reachable, at what level, for every combat skill) this
    does not attempt - see `combat_xp.CURVED_SKILLS` on which skills even
    have a real curve to ask for at all.

    A level with no supported kill (accuracy or damage too low for the
    library to land one at all) is simply absent from the result, the same
    "no route" the rest of this project gives rather than a zero it would
    have to explain.

    **The simulation is `combat_curve_raw` and this is the arithmetic on top**,
    so a timeline can carry the ninety-nine fights and re-apply a moved cap or
    multiplier without re-simulating any of them. One implementation, two
    entry points - see `PricedCombat`.
    """
    return _curve_applied(
        combat_curve_raw(
            chunk_info, picks, levels, monster, style, skill,
            index=index, kit=kit, slayer_monsters=slayer_monsters,
            boss_monsters=boss_monsters,
        ),
        None if caps is None else caps.get(monster),
        multiplier,
    )


def _curve_applied(
    raw: Mapping[int, tuple[float, float]], cap: float | None, multiplier: float
) -> dict[int, float]:
    """`combat_curve_raw`'s fights as damage an hour, capped and multiplied.

    **Neither term touches the fight**, which is what lets a carried curve
    survive a moved `spawn_caps` entry: they are arithmetic applied after the
    simulation, so re-applying them is a dict walk rather than 99 kills.
    """
    found: dict[int, float] = {}
    for level, (kills, hitpoints) in raw.items():
        rate = min(kills, cap) if cap is not None and cap > 0 else kills
        if rate <= 0:
            continue
        found[level] = rate * hitpoints * multiplier
    return found


def combat_curve_raw(
    chunk_info: ChunkInfo,
    picks: Mapping[str, str],
    levels: Mapping[str, int],
    monster: str,
    style: str,
    skill: str,
    *,
    index: MonsterIndex | None = None,
    kit: Kit | None = None,
    slayer_monsters: frozenset[str] = frozenset(),
    boss_monsters: frozenset[str] = frozenset(),
) -> dict[int, tuple[float, float]]:
    """`{level: (kills an hour, hitpoints)}` - `combat_curve`'s simulation
    alone, before the cap and the XP multiplier are spent on it.

    Separate so a carried curve is the expensive half and the cheap half is
    redone; `combat_curve` is this plus `_curve_applied` and nothing else.
    """
    _require()
    monster_index = load_monster_index() if index is None else index
    versions = version_index(monster_index)
    candidates = candidate_targets(monster_index, monster, versions)
    if not candidates:
        return {}
    reductions = kit.reductions if kit is not None else None
    wilderness = monster in kit.wilderness if kit is not None else False
    on_slayer_task = monster in slayer_monsters
    boss = monster in boss_monsters

    found: dict[int, tuple[float, float]] = {}
    for level in range(1, 100):
        sample_levels = dict(levels)
        sample_levels[skill] = level
        loadout = build_loadouts(chunk_info, picks, sample_levels, kit).get(style)
        if loadout is None:
            continue
        kill = kills_by_style(
            {style: loadout},
            monster,
            candidates,
            on_slayer_task=on_slayer_task,
            reductions=reductions,
            wilderness=wilderness,
            boss=boss,
            prefer="damage",
        ).get(style)
        if kill is None or kill.hitpoints <= 0:
            continue
        found[level] = (kill.kills_per_hour(), kill.hitpoints)
    return found


def _raid_kill_lookup(
    loadouts: Mapping[str, Loadout],
    monster_index: MonsterIndex,
    versions: Mapping[str, tuple[str, ...]],
    reductions: DefenceReductions | None,
    raid: RaidInputs,
) -> Callable[[str], KillEstimate | None]:
    """One raid setting's fastest kill, by name - the shared half of the
    three raid-model builders below, which differ only in which `RaidInputs`
    they hold and which field of the result they read back."""

    def lookup(name: str) -> KillEstimate | None:
        if not loadouts:
            return None
        candidates = candidate_targets(monster_index, name, versions)
        if not candidates:
            return None
        return best_kill(
            loadouts, name, candidates, index=monster_index,
            reductions=reductions, boss=True, raid=raid,
        )

    return lookup


def theatre_kill_seconds(
    chunk_info: ChunkInfo,
    picks: Mapping[str, str],
    levels: Mapping[str, int],
    *,
    index: MonsterIndex | None = None,
    kit: Kit | None = None,
    party_size: int = 3,
) -> Callable[[str], float | None]:
    """A `KillSeconds` lookup for every Theatre of Blood room, at
    `party_size` - `costing/theatre.py`'s own shape, since its six rooms are
    separate library monsters rather than one scaled by a mode flag.

    One `RaidInputs` serves all six: the Theatre scales only by party size,
    unlike the Chambers' per-mode flag or the Tombs' per-level dial.
    """
    _require()
    monster_index = load_monster_index() if index is None else index
    versions = version_index(monster_index)
    loadouts = build_loadouts(chunk_info, picks, levels, kit)
    reductions = kit.reductions if kit is not None else None
    raid = RaidInputs(
        party_size=party_size, defence_reductions=reductions or DefenceReductions()
    )
    lookup = _raid_kill_lookup(loadouts, monster_index, versions, reductions, raid)

    def kill_seconds(name: str) -> float | None:
        kill = lookup(name)
        return kill.ttk if kill is not None else None

    return kill_seconds


def chambers_kill_seconds_for(
    chunk_info: ChunkInfo,
    picks: Mapping[str, str],
    levels: Mapping[str, int],
    *,
    index: MonsterIndex | None = None,
    kit: Kit | None = None,
) -> Callable[[str], Callable[[str], float | None]]:
    """`mode -> KillSeconds`, `costing/xeric.py`'s own factory shape.

    Challenge Mode is the *same* monsters under `RaidInputs.challenge_mode`
    rather than separate library entries - so the raid input varies per
    mode and the lookup underneath it does not, matching `xeric.answer`'s
    own docstring on why this is a factory rather than a lookup.
    """
    _require()
    monster_index = load_monster_index() if index is None else index
    versions = version_index(monster_index)
    loadouts = build_loadouts(chunk_info, picks, levels, kit)
    reductions = kit.reductions if kit is not None else None

    def kill_seconds_for(mode: str) -> Callable[[str], float | None]:
        raid = RaidInputs(
            challenge_mode=(mode == _xeric.CHALLENGE),
            defence_reductions=reductions or DefenceReductions(),
        )
        lookup = _raid_kill_lookup(loadouts, monster_index, versions, reductions, raid)

        def kill_seconds(name: str) -> float | None:
            kill = lookup(name)
            return kill.ttk if kill is not None else None

        return kill_seconds

    return kill_seconds_for


def tombs_stats_for(
    chunk_info: ChunkInfo,
    picks: Mapping[str, str],
    levels: Mapping[str, int],
    *,
    index: MonsterIndex | None = None,
    kit: Kit | None = None,
) -> Callable[[int], Callable[[str], tuple[float, float] | None]]:
    """`raid_level -> StatsFor`, `costing/tombs.py`'s own factory shape:
    a room's seconds *and* its raid-scaled hitpoints, since the Tombs derives
    its own reward points from damage dealt rather than from a published
    total the way the Chambers does.

    **`toa_path_level` is left at zero.** `tombs.py`'s own model treats the
    raid level as the one dial the wiki tabulates rather than splitting it
    into the real game's separate invocation and path components - see its
    module docstring. Reading the whole level as `toa_invocation_level` is
    that same simplification carried one level down, not a new one.
    """
    _require()
    monster_index = load_monster_index() if index is None else index
    versions = version_index(monster_index)
    loadouts = build_loadouts(chunk_info, picks, levels, kit)
    reductions = kit.reductions if kit is not None else None

    def stats_for(raid_level: int) -> Callable[[str], tuple[float, float] | None]:
        raid = RaidInputs(
            toa_invocation_level=raid_level,
            defence_reductions=reductions or DefenceReductions(),
        )
        lookup = _raid_kill_lookup(loadouts, monster_index, versions, reductions, raid)

        def stats(name: str) -> tuple[float, float] | None:
            kill = lookup(name)
            return (kill.ttk, kill.hitpoints) if kill is not None else None

        return stats

    return stats_for


def tzhaar_kill_seconds(
    chunk_info: ChunkInfo,
    picks: Mapping[str, str],
    levels: Mapping[str, int],
    *,
    index: MonsterIndex | None = None,
    kit: Kit | None = None,
) -> Callable[[str], float | None]:
    """A `KillSeconds` lookup for every Fight Caves/Inferno monster,
    `costing/tzhaar.py`'s own shape - one lookup serves both variants'
    rosters, unlike the three raids' own builders above.

    **Not raid-scaled, deliberately.** `osrs_dps.core.scaling` has no
    `apply_fight_caves`/`apply_inferno` - neither wave minigame has a party
    size or a difficulty dial the library models, so the rank-and-file (and
    the two final bosses) are ordinary monsters at ordinary stats, priced
    exactly as `price_combat` prices any other target.
    """
    _require()
    monster_index = load_monster_index() if index is None else index
    versions = version_index(monster_index)
    loadouts = build_loadouts(chunk_info, picks, levels, kit)
    reductions = kit.reductions if kit is not None else None

    def kill_seconds(name: str) -> float | None:
        if not loadouts:
            return None
        candidates = candidate_targets(monster_index, name, versions)
        if not candidates:
            return None
        kill = best_kill(
            loadouts, name, candidates, index=monster_index,
            reductions=reductions, boss=True,
        )
        return kill.ttk if kill is not None else None

    return kill_seconds


def colosseum_kill_seconds(
    chunk_info: ChunkInfo,
    picks: Mapping[str, str],
    levels: Mapping[str, int],
    *,
    index: MonsterIndex | None = None,
    kit: Kit | None = None,
) -> Callable[[str], float | None]:
    """A `KillSeconds` lookup for the Fortis Colosseum's wave roster and Sol
    Heredit - `tzhaar_kill_seconds`'s own shape, one module over.

    **Not raid-scaled, for the same reason.** `osrs_dps.core.scaling` has no
    Colosseum wave modifier the way it has `RaidInputs.challenge_mode` or
    `party_size` - `costing/colosseum.py`'s own docstring on Sol Heredit
    needing no script gives the reason: nothing published states a duration
    a player is locked out of attacking for, so every target here is priced
    exactly as `price_combat` prices any other boss.
    """
    _require()
    monster_index = load_monster_index() if index is None else index
    versions = version_index(monster_index)
    loadouts = build_loadouts(chunk_info, picks, levels, kit)
    reductions = kit.reductions if kit is not None else None

    def kill_seconds(name: str) -> float | None:
        if not loadouts:
            return None
        candidates = candidate_targets(monster_index, name, versions)
        if not candidates:
            return None
        kill = best_kill(
            loadouts, name, candidates, index=monster_index,
            reductions=reductions, boss=True,
        )
        return kill.ttk if kill is not None else None

    return kill_seconds


def price_monsters(
    chunk_info: ChunkInfo,
    picks: Mapping[str, str],
    levels: Mapping[str, int],
    monsters: Iterable[str],
    *,
    index: MonsterIndex | None = None,
    overhead: float | None = None,
    slayer_monsters: frozenset[str] = frozenset(),
    boss_monsters: frozenset[str] = frozenset(),
    kit: Kit | None = None,
) -> dict[str, Rate]:
    """Kills-per-hour for `monsters`, as `Rate`s ready to merge.

    Returns only what it could price. A monster missing from the result is one
    the caller should leave to the scraped rate or the default - this never
    substitutes a guess, because a wrong kill time is indistinguishable from a
    right one once it reaches a total. `GROUP_BOSSES` are skipped for that
    reason: a solo kill time for team content is not a number worth having.

    The `Rate.source` is `dps`, and `Rate.match` carries `KillEstimate.match`
    so an estimate can show which numbers rest on a variant choice.
    """
    _require()
    monster_index = load_monster_index() if index is None else index
    versions = version_index(monster_index)
    loadouts = build_loadouts(chunk_info, picks, levels, kit)
    if not loadouts:
        return {}
    reductions = kit.reductions if kit is not None else None

    rates: dict[str, Rate] = {}
    for name in monsters:
        if name in GROUP_BOSSES:
            continue
        kill = best_kill(
            loadouts,
            name,
            candidate_targets(monster_index, name, versions),
            index=monster_index,
            on_slayer_task=name in slayer_monsters,
            reductions=reductions,
            wilderness=name in kit.wilderness if kit is not None else False,
            boss=name in boss_monsters,
        )
        if kill is None:
            continue
        kph = kill.kills_per_hour(overhead)
        if kph <= 0:
            continue
        rates[name] = Rate(value=kph, source="dps", match=kill.match)
    return rates


def price_slayer_tasks(
    chunk_info: ChunkInfo,
    picks: Mapping[str, str],
    levels: Mapping[str, int],
    *,
    heuristics: Heuristics,
    index: MonsterIndex | None = None,
    kit: Kit | None = None,
    reachable_masters: frozenset[str],
    boss_monsters: frozenset[str] = frozenset(),
    reachable_monsters: frozenset[str] = frozenset(),
) -> dict[str, dict[str, SlayerTask]]:
    """Rates for the slayer tasks the config has no measurement for.

    **Every task, not only the unmeasured ones.** The spreadsheet's rates are
    real observations, but of the *best* method, and the best method for a
    stackable task is chinning or bursting - `Spiders` at 3,360 kills an hour
    is one every 1.07 seconds, which is chinchompas into a stack. Those need
    Desert Treasure I or a box trap and the catching time behind it, so on a
    map without them the sheet is measuring an activity the player cannot
    perform. `SlayerTask.is_multi_target` names the 18 rows where that is
    unmistakable; the same objection applies more quietly to the rest, every
    one of which assumes gear this map does not have.

    So this computes the single-target rate for everything it can, and
    `with_slayer_rates` lets it win. The sheet's number stays reachable
    through `Heuristics.slayer` for anyone who wants to compare, and a task
    this cannot price keeps it.

    Two numbers make a task priceable, and both are now available:

    - **Kills per hour** from `best_kill`, with `on_slayer_task` set, since
      being on the task is exactly the condition a black mask keys off.
    - **XP per kill from the monster's hitpoints.** In Old School RuneScape a
      slayer kill awards experience equal to the monster's health, which held
      on every one of the nine monsters checkable against the wiki's `slayxp`
      - Banshee 22, Basilisk 75, Gargoyle 105, Abyssal demon 150. Note this is
      *not* what the community sheet's `xp_per_kill` holds: that is averaged
      over a task's whole monster mix, which is why a `Basilisks` task reads
      335 against a Basilisk's own 75. Comparing the two looks like a
      contradiction and is not.

    **The assignment size is left alone.** 115 of the 116 unpriced pairs on
    the real map already carry one from the wiki's assignment tables, so this
    fills in the rate beside a measured size rather than inventing both.

    **A task spanning several monsters is priced on the best XP an hour, not
    the fastest kill.** That is the one place this departs from `best_kill`'s
    policy, and it has to: a slayer kill pays the monster's health, so the
    quickest thing on a list is routinely the worst thing on it. `Scorpions`
    reaches a 2-hitpoint Scorpion that dies in 1.9 seconds and pays 1,500 XP
    an hour, and a King Scorpion that pays 16,176. Choosing on speed picked
    the former and under-reported the task tenfold; `Spiders` and `Zombies`
    were the same shape. Whichever monster wins, its hitpoints give the XP, so
    the two halves describe one monster rather than a mixture.

    **`reachable_monsters` narrows the candidates before the choice is made.**
    A `Dwarves` task names eight monsters and this map may hold two of them;
    pricing the fastest of all eight would quote a fight that is not on offer.
    Pass `SourceIndex.monsters`, which is already past its `taskUnlocks`
    gates. Passing nothing keeps every candidate, which is the wrong default
    for a real map and the right one for a test.

    **`reachable_masters` is the master's own NPC, and it is required**, as it
    is on `slayer.master_rates`: a master you cannot walk up to assigns
    nothing, so pricing their list is work spent on a rate no caller should
    quote. Neither takes a default, because a default that quietly means "do
    not filter" reads identically to a gated call and answers with fiction.
    The real map holds three of the ten masters.
    """
    _require()
    monster_index = load_monster_index() if index is None else index
    versions = version_index(monster_index)
    loadouts = build_loadouts(chunk_info, picks, levels, kit)
    if not loadouts:
        return {}
    reductions = kit.reductions if kit is not None else None
    wild = kit.wilderness if kit is not None else frozenset()

    filled: dict[str, dict[str, SlayerTask]] = {}
    # **One fight per monster, however many masters assign it.** The loop
    # below is master x task x candidate monster, and the same monster sits
    # on many lists - Hellhound is priced 30 times on the every-rollable-chunk
    # map, Greater demon 18 - while everything `best_kill` reads besides the
    # monster is loop-invariant: the loadouts, the reductions, the wilderness
    # and boss sets. A local memo, dying with this call like every cache in
    # the pure layer.
    fought: dict[str, tuple[KillEstimate | None, int]] = {}

    def fight(bare: str) -> tuple[KillEstimate | None, int]:
        held = fought.get(bare)
        if held is not None:
            return held
        candidates = candidate_targets(monster_index, bare, versions)
        kill = best_kill(
            loadouts,
            bare,
            candidates,
            index=monster_index,
            on_slayer_task=True,
            reductions=reductions,
            wilderness=bare in wild,
            boss=bare in boss_monsters,
        )
        hitpoints = 0
        if kill is not None:
            hitpoints = next(
                (
                    target.hitpoints
                    for key, target in candidates
                    if key == kill.monster
                ),
                0,
            )
        fought[bare] = (kill, hitpoints)
        return kill, hitpoints

    for master, tasks in _mapping(chunk_info.data, "slayerMasterTasks").items():
        if not isinstance(tasks, dict):
            continue
        if master not in reachable_masters:
            continue
        for task in tasks:
            known = (heuristics.slayer.get(master) or {}).get(task)
            if known is None or known.count <= 0:
                # No measured assignment size, so there is no size to put a
                # rate beside. `slayer.py`'s own fallback still covers it.
                continue

            # The export's own task-to-monster list, narrowed to the ones
            # this map can actually get to. `SourceIndex.monsters` is already
            # past its `taskUnlocks` gates, so what survives is a monster you
            # could walk up to and fight today.
            candidates_for = task_monsters(chunk_info, task)
            if reachable_monsters:
                candidates_for = candidates_for & reachable_monsters

            best: KillEstimate | None = None
            best_hitpoints = 0
            best_xp_per_hour = 0.0
            for monster in sorted(candidates_for):
                kill, hitpoints = fight(monster.split("#")[0])
                if kill is None:
                    continue
                # **XP per hour, not kills per hour.** A slayer kill is worth
                # the monster's health, so the quickest thing on the list is
                # routinely the worst thing to kill: a Scorpion dies in 1.9
                # seconds and pays 2 XP, where a King Scorpion on the same
                # task pays 30 and is worth ten times as much an hour.
                xp_per_hour = hitpoints * kill.kills_per_hour()
                if xp_per_hour > best_xp_per_hour:
                    best, best_hitpoints = kill, hitpoints
                    best_xp_per_hour = xp_per_hour

            if best is None or best_hitpoints <= 0:
                continue
            rate = best.kills_per_hour()
            if rate <= 0:
                continue
            filled.setdefault(master, {})[task] = replace(
                known,
                xp_per_kill=float(best_hitpoints),
                kills_per_hour=rate,
                source="dps",
            )
    return filled


def with_slayer_rates(
    heuristics: Heuristics,
    filled: Mapping[str, Mapping[str, SlayerTask]],
    *,
    pinned: Mapping[str, frozenset[str]] | None = None,
) -> Heuristics:
    """`heuristics` with `filled` merged into its slayer table.

    A new value rather than a mutation, so the pure layer stays shareable
    across processes.

    **`pinned` is what somebody wrote in `heuristics/overrides.json`, and it
    wins.** The layering is `defaults < scraped < computed < overrides`: a
    computed rate beats the spreadsheet because the spreadsheet measures a
    method this map may not have, but it does not beat a human who looked at
    the number and disagreed. That is the whole purpose of the overrides file,
    and a computed layer that silently outranked it would make hand
    corrections stop working with no sign that they had.
    """
    if not filled:
        return heuristics
    kept = pinned or {}
    merged = {master: dict(tasks) for master, tasks in heuristics.slayer.items()}
    for master, tasks in filled.items():
        for task, rate in tasks.items():
            if task in kept.get(master, frozenset()):
                continue
            merged.setdefault(master, {})[task] = rate
    return replace(heuristics, slayer=merged)


def with_monster_rates(
    heuristics: Heuristics,
    rates: Mapping[str, Rate],
    *,
    pinned: frozenset[str] = frozenset(),
) -> Heuristics:
    """`heuristics` with `rates` merged into its kills-per-hour table.

    Same layering as `with_slayer_rates`, and the same reason: `pinned` names
    the monsters `heuristics/overrides.json` speaks for, and those keep the
    number a person chose.
    """
    if not rates:
        return heuristics
    merged = dict(heuristics.monsters)
    merged.update({name: rate for name, rate in rates.items() if name not in pinned})
    return replace(heuristics, monsters=merged)


@dataclass(frozen=True)
class DpsCoverage:
    """What the bridge managed to price, for a command to report.

    Counts rather than the values themselves: this exists so `chunksim estimate`
    can say how much of its answer came from the calculator instead of the
    scrape, which is the one thing a reader needs to judge the total by.
    """

    monsters: int = 0
    #: How many monsters were *offered* to be priced - the reachable providers
    #: that have drops. Reported beside `monsters` because without it the
    #: count reads as coverage of the whole export, which it deliberately is
    #: not: pricing anything the estimate cannot ask about is work thrown
    #: away. See `enrich`.
    offered: int = 0
    slayer_tasks: int = 0
    #: The BiS styles that produced a usable loadout.
    styles: tuple[str, ...] = ()
    #: Entries left alone because `heuristics/overrides.json` speaks for them.
    pinned: int = 0

    @property
    def priced_anything(self) -> bool:
        return bool(self.monsters or self.slayer_tasks)

    def as_dict(self) -> dict[str, Any]:
        return {
            "monsters": self.monsters,
            "offered": self.offered,
            "slayer_tasks": self.slayer_tasks,
            "styles": list(self.styles),
            "pinned": self.pinned,
        }


#: `{monster: a pure "own kill seconds -> real seconds" correction}` - every
#: gated boss whose fix is a straightforward function of its own time-to
#: -kill and nothing else. `Skotizo` is not here: its correction also needs
#: *other* monsters' rates (the totem candidates), which none of these do.
#: See each module's own docstring for what the correction represents.
_SIMPLE_GATED_CORRECTIONS: Mapping[str, Callable[[float], float]] = {
    _hespori.HESPORI: _hespori.effective_seconds,
    _giant_mole.GIANT_MOLE: _giant_mole.effective_seconds,
    _duke_sucellus.DUKE_SUCELLUS: _duke_sucellus.effective_seconds,
    _vorkath.VORKATH: _vorkath.effective_seconds,
    _nex.NEX: _nex.effective_seconds,
    _zalcano.ZALCANO: _zalcano.effective_seconds,
}


def _apply_gated_bosses(
    monsters: Mapping[str, Rate], freshly_priced: Mapping[str, Rate]
) -> dict[str, Rate]:
    """`monsters`, with every entry in `_SIMPLE_GATED_CORRECTIONS` and
    `Skotizo` corrected for what gates a real kill beyond the fight itself,
    plus a `Rate` synthesised for each of `keyed_chests`' two chests - see
    each correction's own module for what it represents.

    **Only *corrects* an entry `freshly_priced` just computed.** Every
    correction reads `Rate.value` back into a time-to-kill and changes it;
    applying that twice - once here, once on a later call reusing the same
    corrected `Rate` - would silently compound the change every roll
    `enrich_incremental` reuses it for. `freshly_priced` is exactly what
    `price_monsters` returned *this call*, so a `Rate` already corrected on
    a previous call (and merely carried forward, unchanged, because the
    fight signature has not moved) is never corrected again. `enrich` has
    no reuse to guard against, so it passes the same dict for both
    parameters.

    `monsters` (as opposed to `freshly_priced`) is what `Skotizo`'s totem
    search and the chest synthesis below read a candidate's own kill time
    from - a candidate can be genuinely reachable and unchanged (reused, not
    fresh) on the very roll the thing depending on it first becomes
    reachable, and its rate is exactly as valid as a fresh one for the
    current signature.

    **The chests are a synthesis, not a correction, and the `freshly_priced`
    guard does not apply to them.** Neither chest is ever combat-simulated -
    it has no stat block - so neither ever appears in `freshly_priced` for
    the simple loop above to key off. Their rate is a pure function of
    *other* monsters' already-resolved rates, recomputed fresh every call;
    there is nothing self-referential to double-apply, so it always runs.
    """
    for name, correction in _SIMPLE_GATED_CORRECTIONS.items():
        if name not in freshly_priced:
            continue
        rate = freshly_priced[name]
        if rate.value <= 0:
            continue
        total = correction(3600.0 / rate.value)
        monsters = {
            **monsters,
            name: Rate(
                value=3600.0 / total if total > 0 else 0.0,
                source=rate.source,
                match=rate.match,
            ),
        }

    if _skotizo.SKOTIZO in freshly_priced:
        skotizo_rate = freshly_priced[_skotizo.SKOTIZO]

        def kill_seconds_for(name: str) -> float | None:
            rate = monsters.get(name)
            return 3600.0 / rate.value if rate is not None and rate.value > 0 else None

        totem = _skotizo.totem_seconds(kill_seconds_for)
        if totem is not None and skotizo_rate.value > 0:
            total = totem + 3600.0 / skotizo_rate.value
            monsters = {
                **monsters,
                _skotizo.SKOTIZO: Rate(
                    value=3600.0 / total if total > 0 else 0.0,
                    source=skotizo_rate.source,
                    match=skotizo_rate.match,
                ),
            }
        else:
            # No candidate reachable, or the fight itself could not be
            # priced - an uncorrected, too-fast combat-only rate is a wrong
            # number, not a missing one, so this refuses rather than
            # keeping it. See the module docstring.
            monsters = {k: v for k, v in monsters.items() if k != _skotizo.SKOTIZO}

    # **Bryophyta's and Obor's lair chests are never combat-simulated - they
    # have no stat block - so they never reach `monsters` on their own and
    # this is a synthesis rather than a correction.** Skotizo's `freshly_
    # priced` guard has nothing to protect against here: a chest's rate is a
    # pure function of *other* monsters' rates, recomputed the same way every
    # call, so re-deriving it on a roll where nothing about it changed costs
    # nothing and risks nothing. See `keyed_chests`'s module docstring for
    # the mechanic and where its numbers come from.
    def chest_kill_seconds(name: str) -> float | None:
        rate = monsters.get(name)
        return 3600.0 / rate.value if rate is not None and rate.value > 0 else None

    for chest in _keyed_chests.CANDIDATE_CHANCE:
        chest_total = _keyed_chests.effective_seconds(chest, chest_kill_seconds)
        # **Written explicitly either way, never left absent.** An absent
        # entry is exactly what let this bug happen -
        # `Heuristics.kills_per_hour` falls through to `DEFAULT_KPH` for
        # anything it has not heard of, and a chest has no stat block to be
        # heard of *from*. No priceable candidate is a real "no route", not
        # nothing said, so it is written as `Rate(0.0, ...)` - `kills_per_
        # hour` returns that value as-is rather than defaulting, and every
        # reader downstream already treats a non-positive rate as unpriced.
        value = 3600.0 / chest_total if chest_total is not None and chest_total > 0 else 0.0
        monsters = {
            **monsters,
            chest: Rate(value=value, source=f"derived:{chest}", match="keyed"),
        }

    return dict(monsters)


def enrich(
    heuristics: Heuristics,
    chunk_info: ChunkInfo,
    derived: Derived,
    levels: Mapping[str, int],
    *,
    index: MonsterIndex | None = None,
    pinned_monsters: frozenset[str] = frozenset(),
    pinned_slayer: Mapping[str, frozenset[str]] | None = None,
) -> tuple[Heuristics, DpsCoverage]:
    """`heuristics` with every rate this can compute, and what it computed.

    The one entry point a command needs: it builds the `Kit`, loads the
    monster index once, prices both the kill rates and the slayer tasks, and
    merges them at the right layer. Everything it needs about the map comes
    off `derived`, so a caller does not have to know which branch feeds which
    gate.

    **Nothing here is a fallback.** A monster this cannot price keeps whatever
    the scrape or the default gave it, so the result is never worse-informed
    than the input - only differently informed where a fight could actually be
    simulated.

    `levels` should be the same ones the estimate itself will spend. On the
    real map that means `estimate.goal_levels` - the levels the chunk *ends*
    at rather than today's - because that is what `slayer.py` already judges a
    master at, and pricing the same fight at two different levels in one
    command would be indefensible.
    """
    _require()
    monster_index = load_monster_index() if index is None else index
    kit = assemble_kit(
        chunk_info,
        levels,
        items=derived.challenges.available_items,
        source_index=derived.source_index,
    )
    loadouts = build_loadouts(chunk_info, derived.bis.picks, levels, kit)
    if not loadouts:
        return heuristics, DpsCoverage()

    bosses = frozenset(_mapping(chunk_info.code_items, "bossMonsters"))
    reachable = frozenset(derived.source_index.monsters)
    masters = frozenset(derived.source_index.npcs)

    # **Only what the estimate could ever ask about.** Every
    # `kills_per_hour` lookup in `estimate.py` is gated on this same set, so
    # a rate for anything outside it is computed and never spent - and on the
    # real map that was 753 monsters priced against 11 consulted. Restricting
    # it leaves the answer identical to four decimal places (3969.1204h
    # either way, buckets, per-item hours and `unpriced` all unchanged) and
    # makes this call ~3.8x faster. `estimate.reachable_providers` is
    # imported rather than reproduced so the gate cannot drift from the
    # thing it is gating.
    #
    # **`drop_rates`, not `chunk_info.drops`** - and that was a real defect,
    # not a tidier spelling. A monster with no `drops` entry can still have a
    # loot table: every slayer monster's lives in `skillItems.Slayer`, which
    # is `sources._slayer_skill_items_for`'s whole job. Gating on the export
    # branch excluded all of them from the calculator, so `Abyssal demon`
    # kept `DEFAULT_KPH['slayer']` at a flat 60/hr against the 24.3 it
    # simulates, and `Alchemical Hydra` the boss default of 20 against 2.9 -
    # 20 monsters on one cached map, 27 on the other. `SourceIndex.drop_rates`
    # is keyed by whatever the index actually recorded a rate for, whichever
    # branch supplied it, so it cannot drift from what the walk can ask.
    priceable = sorted(reachable_providers(derived) & frozenset(derived.source_index.drop_rates))
    monsters = price_monsters(
        chunk_info,
        derived.bis.picks,
        levels,
        priceable,
        index=monster_index,
        slayer_monsters=frozenset(chunk_info.slayer_monsters),
        boss_monsters=bosses,
        kit=kit,
    )
    # Every call here is a fresh simulation - no reuse to guard against, so
    # the whole result is "freshly priced". See `_apply_gated_bosses`.
    monsters = _apply_gated_bosses(monsters, monsters)
    tasks = price_slayer_tasks(
        chunk_info,
        derived.bis.picks,
        levels,
        heuristics=heuristics,
        index=monster_index,
        kit=kit,
        reachable_masters=masters,
        boss_monsters=bosses,
        reachable_monsters=reachable,
    )

    kept = pinned_slayer or {}
    pinned_count = sum(1 for name in monsters if name in pinned_monsters) + sum(
        1
        for master, names in tasks.items()
        for name in names
        if name in kept.get(master, frozenset())
    )

    enriched = with_monster_rates(heuristics, monsters, pinned=pinned_monsters)
    enriched = with_slayer_rates(enriched, tasks, pinned=pinned_slayer)
    return enriched, DpsCoverage(
        monsters=sum(1 for name in monsters if name not in pinned_monsters),
        offered=len(priceable),
        slayer_tasks=sum(
            1
            for master, names in tasks.items()
            for name in names
            if name not in kept.get(master, frozenset())
        ),
        styles=tuple(sorted(loadouts)),
        pinned=pinned_count,
    )


@dataclass(frozen=True)
class PricedFights:
    """One step's priced fights, and what they were priced against.

    Carried from one roll of a timeline to the next so the next roll can keep
    what cannot have changed. See `enrich_incremental` for why that is almost
    everything.
    """

    signature: tuple[Any, ...]
    monsters: Mapping[str, Rate]
    tasks: Mapping[str, Mapping[str, SlayerTask]]
    wilderness: frozenset[str] = frozenset()
    #: Per master, the reachable monsters *its own tasks* can name. A master's
    #: table is decided by that set and nothing wider, so a new monster
    #: somewhere else on the map leaves it alone - see `_master_candidates`.
    candidates: Mapping[str, frozenset[str]] = field(default_factory=dict)


def fight_signature(
    picks: Mapping[str, str], levels: Mapping[str, int], kit: Kit
) -> tuple[Any, ...]:
    """Everything that can change a kill time except *which monster it is*.

    Two states with the same signature price any given monster identically, so
    a timeline can carry the previous roll's rates forward instead of
    re-simulating 7,335 fights to arrive at the same numbers.

    **`kit.items` is deliberately not in here wholesale.** It moved on 17 of 20
    rolls of a measured run, because it grows with every item the map reaches -
    and it feeds exactly one thing, `_charged`, which swaps a worn *uncharged
    wilderness weapon* for its charged form. A new potion appearing cannot
    change a fight the potion is not in. So what enters is precisely the
    charge swaps available to the *picked* gear, which is what `build_loadouts`
    actually reads.

    `wilderness` is excluded for a different reason: it is per monster, not per
    state, so `enrich_incremental` compares membership itself rather than
    invalidating every rate because one monster moved.
    """
    charged = frozenset(
        name[: -len(_UNCHARGED_SUFFIX)]
        for name in picks.values()
        if name.endswith(_UNCHARGED_SUFFIX)
        and name[: -len(_UNCHARGED_SUFFIX)] in _WILDERNESS_WEAPONS
        and name[: -len(_UNCHARGED_SUFFIX)] in kit.items
    )
    return (
        tuple(sorted(picks.items())),
        tuple(sorted(levels.items())),
        tuple(sorted(kit.boosts.items())),
        tuple(sorted((style, tuple(sorted(names))) for style, names in kit.prayers.items())),
        kit.spell,
        kit.reductions,
        charged,
    )


def enrich_incremental(
    heuristics: Heuristics,
    chunk_info: ChunkInfo,
    derived: Derived,
    levels: Mapping[str, int],
    *,
    previous: PricedFights | None = None,
    index: MonsterIndex | None = None,
    pinned_monsters: frozenset[str] = frozenset(),
    pinned_slayer: Mapping[str, frozenset[str]] | None = None,
) -> tuple[Heuristics, DpsCoverage, PricedFights]:
    """`enrich`, reusing whatever the previous roll of a timeline already priced.

    **A chunk roll only ever adds.** Measured over a 20-roll run on the real
    export: the reachable-provider set grew by 0-8 a roll and never shrank, and
    of 4,094 monster rates recomputed, **3,867 (94%) were byte-identical to the
    roll before** - 16 of the 20 rolls changed not a single one. Slayer task
    rates came out at 95%. All the change is concentrated on the two rolls
    where BiS moved.

    So this prices a monster only when it is new, when its wilderness
    membership flipped, or when `fight_signature` says the gear, levels,
    boosts, prayers, spell, defence draining or charge swaps moved. On the
    measured run that is 5,185 pricings down to 1,000.

    **`enrich` is left alone on purpose.** Only a timeline has a "previous
    roll"; `chunksim estimate` and the GUI's panel do not, so the reuse path is
    confined to the one caller that can use it and every other caller is
    provably unaffected. The two must agree, and
    `tests/test_dps_bridge.py` asserts that against a real run rather than
    trusting the predicate - a wrong one here is *silently* wrong, the numbers
    staying entirely plausible.
    """
    _require()
    monster_index = load_monster_index() if index is None else index
    kit = assemble_kit(
        chunk_info,
        levels,
        items=derived.challenges.available_items,
        source_index=derived.source_index,
    )
    loadouts = build_loadouts(chunk_info, derived.bis.picks, levels, kit)
    signature = fight_signature(derived.bis.picks, levels, kit)
    bosses = frozenset(_mapping(chunk_info.code_items, "bossMonsters"))
    reachable = frozenset(derived.source_index.monsters)
    masters = frozenset(derived.source_index.npcs)
    if not loadouts:
        # Nothing priced, and honestly so: the next roll reusing an empty
        # table is correct, since with the same signature and the same
        # reachable set it would price nothing either.
        return heuristics, DpsCoverage(), PricedFights(
            signature, {}, {}, kit.wilderness, _master_candidates(chunk_info, masters, reachable)
        )

    # The same set `enrich` offers, and for the same reason - see its comment
    # on why this is `drop_rates` rather than the export's `drops` branch.
    priceable = sorted(reachable_providers(derived) & frozenset(derived.source_index.drop_rates))
    # Built once: the membership test below is inside a comprehension over a
    # thousand-odd monsters, so rebuilding it per item was quadratic.
    priced_set = frozenset(priceable)

    usable = previous if previous is not None and previous.signature == signature else None
    if usable is None:
        stale: frozenset[str] = priced_set
        monsters: dict[str, Rate] = {}
    else:
        # Everything the previous roll priced is still right, bar the monsters
        # that were not there and the ones that changed side of the ditch.
        flipped = {
            name
            for name in usable.monsters
            if (name in kit.wilderness) != (name in usable.wilderness)
        }
        stale = frozenset(name for name in priceable if name not in usable.monsters) | frozenset(
            flipped
        )
        monsters = {
            name: rate
            for name, rate in usable.monsters.items()
            if name not in flipped and name in priced_set
        }

    if stale:
        fresh = price_monsters(
            chunk_info,
            derived.bis.picks,
            levels,
            sorted(stale),
            index=monster_index,
            slayer_monsters=frozenset(chunk_info.slayer_monsters),
            boss_monsters=bosses,
            kit=kit,
        )
        monsters.update(fresh)
        # `fresh` (not `monsters`) is "priced this call" - see
        # `_apply_gated_bosses` on why a reused, already-corrected `Rate`
        # must never be corrected a second time.
        monsters = _apply_gated_bosses(monsters, fresh)

    # **The slayer half is reusable per master, not per task.** A master's
    # table is decided by which of *its own* assignable monsters are reachable
    # plus the fight signature, so a new monster elsewhere on the map leaves
    # it untouched. Gating on the whole reachable set instead recomputed all
    # three masters on 10 of 20 measured rolls; per master, 50 of 60
    # master-tables were reusable.
    candidates = _master_candidates(chunk_info, masters, reachable)
    if usable is None:
        stale_masters = set(masters)
        tasks: dict[str, Mapping[str, SlayerTask]] = {}
    else:
        stale_masters = {
            master
            for master in masters
            if candidates.get(master) != usable.candidates.get(master)
        }
        tasks = {m: t for m, t in usable.tasks.items() if m in masters and m not in stale_masters}
    if stale_masters:
        tasks.update(
            price_slayer_tasks(
                chunk_info,
                derived.bis.picks,
                levels,
                heuristics=heuristics,
                index=monster_index,
                kit=kit,
                reachable_masters=frozenset(stale_masters),
                boss_monsters=bosses,
                reachable_monsters=reachable,
            )
        )

    kept = pinned_slayer or {}
    pinned_count = sum(1 for name in monsters if name in pinned_monsters) + sum(
        1
        for master, names in tasks.items()
        for name in names
        if name in kept.get(master, frozenset())
    )
    enriched = with_monster_rates(heuristics, monsters, pinned=pinned_monsters)
    enriched = with_slayer_rates(enriched, tasks, pinned=pinned_slayer)
    coverage = DpsCoverage(
        monsters=sum(1 for name in monsters if name not in pinned_monsters),
        offered=len(priceable),
        slayer_tasks=sum(
            1
            for master, names in tasks.items()
            for name in names
            if name not in kept.get(master, frozenset())
        ),
        styles=tuple(sorted(loadouts)),
        pinned=pinned_count,
    )
    return enriched, coverage, PricedFights(
        signature, monsters, tasks, kit.wilderness, candidates
    )


def _master_candidates(
    chunk_info: ChunkInfo, masters: frozenset[str], reachable: frozenset[str]
) -> dict[str, frozenset[str]]:
    """Per master, the reachable monsters its own task list can name.

    The unit a slayer table's reuse turns on. `price_slayer_tasks` picks the
    best *reachable* monster for each task it assigns, so its answer moves
    only when that intersection moves - and a chunk full of monsters no master
    assigns moves nothing at all.
    """
    out: dict[str, frozenset[str]] = {}
    for master, tasks in _mapping(chunk_info.data, "slayerMasterTasks").items():
        if master not in masters or not isinstance(tasks, dict):
            continue
        named: set[str] = set()
        for task in tasks:
            named |= task_monsters(chunk_info, task) & reachable
        out[master] = frozenset(named)
    return out


def library_version() -> str | None:
    """The installed `osrs-dps` version, or `None` when it is absent.

    For `chunksim show`, which reports whether the calculator is in play at all -
    an estimate computed with it and one computed without are different
    numbers, and nothing else on that screen would say so.
    """
    if not DPS_AVAILABLE:
        return None
    import osrs_dps

    version: str = osrs_dps.__version__
    return version


__all__ = [
    "CombatRate",
    "DEFAULT_OVERHEAD_SECONDS",
    "MonsterIndex",
    "DPS_AVAILABLE",
    "GROUP_BOSSES",
    "MAGIC_DAMAGE_SCALE",
    "RETARGET_TICKS",
    "SECONDS_PER_TICK",
    "OFFENSIVE_STYLES",
    "MELEE_SUBSTYLES",
    "DpsCoverage",
    "DpsUnavailableError",
    "KillEstimate",
    "Kit",
    "OverheadSample",
    "assemble_kit",
    "best_kill",
    "kills_by_style",
    "price_combat",
    "in_wilderness",
    "build_loadouts",
    "candidate_targets",
    "chambers_kill_seconds_for",
    "combat_curve",
    "enrich",
    "library_version",
    "load_monster_index",
    "measure_overhead",
    "price_monsters",
    "price_slayer_tasks",
    "theatre_kill_seconds",
    "tombs_stats_for",
    "tzhaar_kill_seconds",
    "wilderness_monsters",
    "with_monster_rates",
    "with_slayer_rates",
]
