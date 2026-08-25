"""Vet'ion and Calvar'ion: two forms each, two hellhound adds mid-form, and
why neither was ever going to resolve on its own.

### Why `dps_bridge.best_kill` refused both outright

`osrs_dps` carries no bare `Vet'ion`/`Calvar'ion` key at all - only
`Vet'ion#Normal`/`Vet'ion#Enraged` (and the `Calvar'ion` equivalents), which
makes both **version-ambiguous** in `candidate_targets`' sense. That
function's own certainty gate then refuses them a second time, harder:
`_SEQUENTIAL_VERSIONS` matches `"Enraged"` in the version suffix and returns
`()` outright, on exactly the reasoning stated there - two forms of one
fight are not two alternatives to pick the faster of. That refusal is
correct; it just means the item walk fell all the way back to the wiki's
own `kills_per_hour` for want of anyone having written the phases down, the
same gap `costing/hydra.py` and `costing/grotesque_guardians.py` closed for
their own bosses.

### The fight, off `[[Vet'ion]]`/`[[Calvar'ion]]`

Both pages describe the identical shape, Calvar'ion merely weaker: "he has
two forms, a 'normal' and 'enraged' form. When he reaches half health in his
first form for the first time, he summons two ... skeleton hellhounds ...
and must be killed as they grant him complete damage immunity while alive.
Upon being forced into his next stage, [he] will become enraged ... In this
form, he will attack faster, his attacks will deal more damage ... he
summons two ... greater skeleton hellhounds ... and must also be killed."
Six independent full-health targets, not one damage race: Normal to 50%,
two hellhounds each fully depleted, Normal's remaining 50%, Enraged to 50%,
two greater hellhounds each fully depleted, Enraged's remaining 50% - the
"several independent targets, each fully depleted" shape `Phase`'s own
docstring names Grotesque Guardians as the example of, just with four extra
targets instead of one. `hp_share` sums to `1.0` across each form's own pair
of phases (a fresh 255/150-hitpoint pool each, per `osrs_dps`'s identical
`hitpoints` on both `#Normal` and `#Enraged`) and to `1.0` on each hellhound
- `HELLHOUND_HP_SHARE`/`GREATER_HELLHOUND_HP_SHARE` name that explicitly
rather than leaving it implicit at the phase's own default.

**No `Phase.styles` restriction, on the same reasoning `royal_titans.py`
gives.** Both bosses are "highly resistant to any combat style other than
crush" - `dcrush=-10` against `dstab`/`dslash` in the hundreds - which is a
weakness `dps_bridge`'s ordinary style search already finds on the strength
of the numbers alone, not a hard exclusion nothing in `Target.bonuses`
would otherwise encode. The four hellhound variants are `attack_style=
'crush'` themselves in the library and carry the same lopsided defence, so
the search reaches the same answer for them too.

### The one guessed number

**`HELLHOUND_DELAY_SECONDS` is this project's own figure**, in the same
shape `costing/grotesque_guardians.py`'s `TRANSITION_SECONDS` is. Only
Vet'ion's own page states a mechanic for it - "Vet'ion will gain 90% damage
resistance after falling below half health but before the skeletal
hellhounds spawn" - but the fight is otherwise identical on both pages
("Calvar'ion is fought similarly to Vet'ion") and neither publishes a
duration, so the same small idle window is charged once at the start of
each hellhound pair on both bosses rather than modelled on Vet'ion alone and
silently dropped for Calvar'ion. Modelled as `idle_seconds` - dead time, not
a reduced rate - because nothing is worth attacking during it: Vet'ion is
90% resistant and the hellhounds have not spawned yet.

### What stays unmodelled

The "occasionally spawns only 1 or 0" hellhound bug, the 5-minute
enraged-form revert (never binding at any competent kill speed), and the
shield-bash stun (avoidable, per the wiki, by standing off the targeted
tile) are not costed, matching every other module in this subpackage's
stance on avoidable or bugged mechanics.

Pure: `FightScript`/`Phase` construction only, no `osrs_dps` import -
`dps_bridge.py` registers both into `SCRIPTS`.
"""

from __future__ import annotations

from typing import Mapping

from chunksim.costing.fightscripts import FightScript, Phase

VETION = "Vet'ion"
CALVARION = "Calvar'ion"

#: Each form's own pool split at the wiki's stated threshold - "reaches half
#: health in his first form" - not an assumption.
FORM_HP_SHARE = 0.5
#: Each hellhound (or greater hellhound) is fully depleted, once per hound.
HELLHOUND_HP_SHARE = 1.0
GREATER_HELLHOUND_HP_SHARE = 1.0
#: Guessed - see the module docstring on why it is charged for both bosses
#: despite only Vet'ion's page stating the mechanic.
HELLHOUND_DELAY_SECONDS = 3.0

_TRANSITION_NOTE = (
    "Vet'ion gains 90% damage resistance between falling below half health "
    "and the hellhounds spawning' (Vet'ion's own page; not restated on "
    "Calvar'ion's, charged on both regardless since the fight is otherwise "
    "identical) - duration unpublished, this project's own guess."
)


def _script(
    name: str, normal: str, enraged: str, hellhound: str, greater_hellhound: str
) -> FightScript:
    return FightScript(
        name=name,
        phases=(
            Phase(
                name=f"{name} (Normal, to 50%)",
                target=normal,
                hp_share=FORM_HP_SHARE,
                note="'Reaches half health in his first form' - the published split.",
            ),
            Phase(
                name=f"{hellhound} (1 of 2)",
                target=hellhound,
                hp_share=HELLHOUND_HP_SHARE,
                idle_seconds=HELLHOUND_DELAY_SECONDS,
                note=_TRANSITION_NOTE,
            ),
            Phase(
                name=f"{hellhound} (2 of 2)",
                target=hellhound,
                hp_share=HELLHOUND_HP_SHARE,
                note="'Two' hellhounds, published - the second, no further delay.",
            ),
            Phase(
                name=f"{name} (Normal, finish)",
                target=normal,
                hp_share=FORM_HP_SHARE,
                note="The first form's remaining half, immunity lifted once "
                "both hellhounds are down.",
            ),
            Phase(
                name=f"{name} (Enraged, to 50%)",
                target=enraged,
                hp_share=FORM_HP_SHARE,
                note="'Upon being forced into his next stage' - a fresh "
                "full-health pool at the enraged stat block.",
            ),
            Phase(
                name=f"{greater_hellhound} (1 of 2)",
                target=greater_hellhound,
                hp_share=GREATER_HELLHOUND_HP_SHARE,
                idle_seconds=HELLHOUND_DELAY_SECONDS,
                note=_TRANSITION_NOTE,
            ),
            Phase(
                name=f"{greater_hellhound} (2 of 2)",
                target=greater_hellhound,
                hp_share=GREATER_HELLHOUND_HP_SHARE,
                note="The second greater hellhound, no further delay.",
            ),
            Phase(
                name=f"{name} (Enraged, finish)",
                target=enraged,
                hp_share=FORM_HP_SHARE,
                note="The enraged form's remaining half.",
            ),
        ),
        note="Two forms, each a fresh full-health pool, each interrupted "
        "once by a pair of fully-depleted hellhounds that must die before "
        "damage resumes - see the module docstring for the wiki's own "
        "description of the mechanic.",
    )


#: Both bosses' own encounters, keyed by whichever name a caller asks about.
SCRIPTS: Mapping[str, FightScript] = {
    VETION: _script(
        VETION,
        "Vet'ion#Normal",
        "Vet'ion#Enraged",
        "Skeleton Hellhound (Vet'ion)",
        "Greater Skeleton Hellhound (Vet'ion)",
    ),
    CALVARION: _script(
        CALVARION,
        "Calvar'ion#Normal",
        "Calvar'ion#Enraged",
        "Skeleton Hellhound (Calvar'ion)",
        "Greater Skeleton Hellhound (Calvar'ion)",
    ),
}
