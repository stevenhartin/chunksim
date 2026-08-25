"""Duke Sucellus: asleep until fed, and priced against the wrong Duke
without a script.

**Two independent problems, one module.** `Duke Sucellus` carries a real
drop table already, but `osrs_dps` has no bare key for him at all - only
`Duke Sucellus#Quest, Awake` (330 hitpoints, the one-time Desert Treasure II
quest fight), `Duke Sucellus#Awakened, Awake` (1,697, a much harder,
separately-unlocked state) and `Duke Sucellus#Post-quest, Awake` (485, the
version fought on every repeat kill afterward). None of the three names
matches `_SEQUENTIAL_VERSIONS`, so `dps_bridge.candidate_targets` treats
them as ordinary substitutable alternatives and `best_kill`'s un-scripted
resolution would pick whichever dies fastest - the 330-hitpoint quest-only
Duke, fought exactly once ever, the same softest-form defect
`costing/hydra.py` and `costing/zulrah.py` each already fixed for their own
bosses. `SCRIPT` below is a single, unsplit phase (`hp_share=1.0`) that
names `Post-quest, Awake` explicitly, for the same reason those two
modules' own single- or multi-phase scripts do: not a downtime mechanic,
just the correct target.

### The preparation phase

"Unlike the other members of the Forgotten Four, Duke Sucellus is not
available to fight immediately; rather, he is in a deep slumber and must be
fed with arder powder, musca powder or Arder-musca poison before he is
forcefully woken up to fight. During this preparation phase, the player
must gather materials from the hallways to his side, avoiding both his ice
magic and extremities... After the Duke is defeated, he remains 'dead' for
a few seconds... before beginning to sleep again." A real, mechanically
enforced phase before every single kill - not once per session, since he
returns to sleep and has to be re-woken each time.

**`PREP_FRACTION = 1.0` is this project's own accepted estimate: the
preparation phase takes about as long as the fight itself.** Nothing on
the wiki states a duration for it the way `[[Hespori seed]]`'s farming
recipe states 32 hours outright, so - matching every other overhead
constant in this subpackage that has no published figure to anchor on -
this is a stated `GUESS`, expressed as a multiplier on the fight's own
time rather than a flat second count, because unlike a wave minigame's
between-wave walk or a raid's room transition, the prep here scales with
how capable the map's own kit is at gathering the materials, which a flat
number could not represent at all.

### Where the correction happens

Applied by `costing/dps_bridge.enrich`, directly to the already-scripted
`Rate` for `Duke Sucellus` - `effective_seconds` simply doubles the fight's
own time-to-kill, matching `costing/hespori.py`'s and
`costing/giant_mole.py`'s shape: a pure function over `kill_seconds`, no
`osrs_dps` import, applied once per freshly-priced `Rate`.

Pure: `FightScript`/`Phase` construction and one function, no `osrs_dps`
import.
"""

from __future__ import annotations

from chunksim.costing.fightscripts import FightScript, Phase

DUKE_SUCELLUS = "Duke Sucellus"

#: This project's own estimate - see the module docstring. The
#: preparation phase costs as long again as the fight itself.
PREP_FRACTION = 1.0

SCRIPT = FightScript(
    name=DUKE_SUCELLUS,
    phases=(
        Phase(
            name=DUKE_SUCELLUS,
            target="Duke Sucellus#Post-quest, Awake",
            hp_share=1.0,
            note="The repeatable, post-quest Duke - not the 330-hitpoint "
            "one-time Desert Treasure II quest fight or the separately "
            "unlocked 1,697-hitpoint Awakened state, both of which share "
            "the bare name ambiguously. See the module docstring.",
        ),
    ),
    note="Money-making guide 'Killing Duke Sucellus' publishes kph=34 at "
    "excellent melee gear - see tests/test_costing_duke_sucellus.py for "
    "the oracle comparison, which prices only the fight, since the "
    "preparation-phase multiplier is this project's own estimate rather "
    "than something the guide's own kph could validate on its own.",
)


def effective_seconds(kill_seconds: float) -> float:
    """`kill_seconds`, plus the preparation phase's own share of it."""
    return kill_seconds * (1.0 + PREP_FRACTION)
