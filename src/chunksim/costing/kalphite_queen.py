"""The Kalphite Queen: two forms, two styles, one published transition.

**Why this needs a script.** `osrs_dps` indexes her as `Kalphite Queen#
Crawling` and `#Airborne`, both carrying the full `hitpoints=255` -
`costing/hydra.py`'s "one shared pool, several stat blocks" shape, since
`[[Kalphite Queen]]` states outright: "Each form has 255 Hitpoints." Before
this module existed, `dps_bridge.best_kill`'s ordinary version resolution
would price whichever form dies faster as if it were the whole fight - the
same softest-form defect fixed for the Hydra and Zulrah, here caused by two
forms rather than four or three.

### The two forms genuinely favour different styles, and neither is hard-locked

"The first form will simultaneously have Protect from Magic and Protect
from Missiles active, while the second form will only have Protect from
Melee active" - and `osrs_dps`'s own stat blocks say exactly how much:
`Crawling` carries `defence_crush=10` against `defence_stab=defence_slash=
50` and `defence_magic=defence_ranged=100`; `Airborne` carries
`defence_stab=defence_slash=defence_crush=100` against `defence_magic=
defence_ranged=10`. Crush melee is the clear answer in phase one and
ranged or magic in phase two, but neither is a hard exclusion the way
Perilous Moons' `0`-vs-`100` split is - "it is recommended to bring two
[styles] for an easier fight," not required, and nothing is fully immune -
so, matching Sol Heredit and the Royal Titans, no `Phase.styles`
restriction is applied: the ordinary search finds the right style on its
own from the stat gap alone, without this module asserting a wall that
does not exist.

### The transition, published exactly

"When the first form is killed, it takes 20 game ticks (12 seconds) for the
transition into the second airborne form" - not a guess, unlike almost
every other transition constant in this subpackage. Modelled as
`idle_seconds` on the second phase: a hard stop with real animation and no
damage, rather than `reduced_seconds`' partial-rate window, since nothing
publishes any output at all during it.

### What stays unmodelled

The 20-minute revert-to-first-form timer only matters for a kill slower
than 20 minutes at whatever gear the map has - any priced kill this project
would call reasonable finishes well inside that, so it is not scripted.
Stat-drain carrying over between forms is a player choice (a special attack
used or not) rather than a mechanic every kill pays, so it is not modelled
either.

Pure: no `osrs_dps` import - `costing/dps_bridge._scripted_kill` is what
turns this into a priced kill.
"""

from __future__ import annotations

from chunksim.costing.fightscripts import FightScript, Phase

KALPHITE_QUEEN = "Kalphite Queen"

#: Published on the boss's own page: "20 game ticks (12 seconds)" between
#: the first form's death and the second's arrival.
TRANSITION_SECONDS = 12.0

SCRIPT = FightScript(
    name=KALPHITE_QUEEN,
    phases=(
        Phase(
            name="Crawling (first form)",
            target="Kalphite Queen#Crawling",
            hp_share=1.0,
            note="Weak to crush melee (defence_crush=10 against "
            "defence_stab=defence_slash=50) and tanky to ranged/magic "
            "(100 each) - Protect from Magic and Missiles are both active.",
        ),
        Phase(
            name="Airborne (second form)",
            target="Kalphite Queen#Airborne",
            hp_share=1.0,
            idle_seconds=TRANSITION_SECONDS,
            note="Weak to ranged/magic (defence_magic=defence_ranged=10) "
            "and tanky to every melee style (100 each) - Protect from "
            "Melee is active. Carries the published 12-second transition "
            "from the first form's death.",
        ),
    ),
    note="Money-making guide 'Killing the Kalphite Queen' publishes "
    "kph=22 - see tests/test_costing_kalphite_queen.py::TestAgainstTheGuide "
    "for the oracle comparison.",
)
