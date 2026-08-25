"""The Hueycoatl: five body segments, then the head, then a shielded tail
phase that costs real, uncapped-by-this-project's-model time.

**Four targets, one published total.** `[[The Hueycoatl/Strategies]]`
states the whole encounter's shape outright: "a fight consists of five
body parts (with each having 250 health), the head itself (with 2,500
health), and the tail (with 300 health), requiring a total of 4,050 damage
to clear the encounter" - `5 x 250 + 2,500 + 300 = 4,050`, matched exactly.
Four `osrs_dps` keys carry it: `#Body` (250), `#Normal` (2,500, her own
health), `#Tail` (300, a separate pool from her own) and `#Shielded`
(2,500 again, "the whole fight as if only this stat block existed" - not
priced directly, since nothing can be dealt to her while shielded).

### The four phases

- **Body** (`hp_share=5.0` against `#Body`'s own 250) - "there are five
  parts of the Hueycoatl's body that can be attacked, all of which must be
  defeated before the tail is forced to clear the way." The third
  `Phase` shape, one small target killed several times over, the same
  shape `costing/sire.py`'s lung phase and `costing/royal_titans.py`'s
  twin encounter both are.
- **Head, first half** (`hp_share=0.5` against `#Normal`) - "once players
  get her to half health, she will shield herself." An exact published
  threshold, not assumed.
- **Tail** (`hp_share=1.0` against `#Tail`'s own 300) - a separate pool,
  like the body phase; see below on why this phase's own time is a floor
  rather than a real estimate.
- **Head, second half** (`hp_share=0.5` against `#Normal` again) - "once
  the tail's health is depleted, the Hueycoatl's shield dissipates,
  allowing players to resume their attack on her," finishing the
  remaining half.

### The tail phase is a stated ceiling, not a modelled cap

"The tail has only 300 hitpoints, but attacks made on the tail have a
heavy damage cap which can significantly prolong the phase for small
teams. Damage is usually capped at 4, but this can be increased to 9 if
the player's crush attack bonus is their highest attack bonus, in
addition to having all missed hits rounded up to 1 damage." That is not a
defence stat `osrs_dps`'s ordinary combat formula can express - a flat cap
on every hit's damage, applied regardless of the attacker's own max hit,
plus a floor under every miss. `dps_bridge.py` has no path from a
`Loadout`/`Target` pair to "cap every hit at N" today, and building one for
this single mechanic was judged out of proportion to the rest of this
module - so the tail phase is priced by the ordinary uncapped formula, and
this is a **stated ceiling**: a real tail phase, especially for a small
team, takes longer than this prices it, exactly the caveat
`costing/fightscripts.py`'s own docstring asks a script to state rather
than hide.

### The respawn, published exactly

"She will 'respawn' in 30 seconds" between kills - carried as
`idle_seconds` on the body phase, which is what a returning player faces
next. Not a guess: the thirty seconds is the wiki's own figure.

### What stays unmodelled

The glowing-symbol dodge mechanic, the protection-prayer flicking and the
tail's slam shockwave are avoidable per the wiki's own strategy sections
and are not costed, matching every other boss module in this subpackage.
The three-or-more-player brazier damage bonus is a team mechanic this
module does not model - see the module docstring's own note that this is
priced as a solo encounter, unlike `costing/nex.py`.

Pure: no `osrs_dps` import - `costing/dps_bridge._scripted_kill` is what
turns this into a priced kill.
"""

from __future__ import annotations

from chunksim.costing.fightscripts import FightScript, Phase

HUEYCOATL = "The Hueycoatl"

#: Published on `[[The Hueycoatl/Strategies]]`: "she will 'respawn' in 30
#: seconds" between kills.
RESPAWN_SECONDS = 30.0

SCRIPT = FightScript(
    name=HUEYCOATL,
    phases=(
        Phase(
            name="Body (five segments)",
            target="The Hueycoatl#Body",
            hp_share=5.0,
            idle_seconds=RESPAWN_SECONDS,
            note="Five 250-hitpoint segments, all of which must fall "
            "before the tail clears the path to the summit. Carries the "
            "published 30-second respawn wait before this phase can "
            "begin.",
        ),
        Phase(
            name="Head (first half)",
            target="The Hueycoatl#Normal",
            hp_share=0.5,
            note="Published exact threshold: 'once players get her to "
            "half health, she will shield herself.'",
        ),
        Phase(
            name="Tail (shield phase)",
            target="The Hueycoatl#Tail",
            hp_share=1.0,
            note="A separate 300-hitpoint pool. **A stated ceiling, not "
            "an accurate estimate** - the published damage cap (4, or 9 "
            "with crush as the highest attack bonus) is not modelled, so "
            "a real tail phase runs longer than this prices it, "
            "especially for a small team. See the module docstring.",
        ),
        Phase(
            name="Head (second half)",
            target="The Hueycoatl#Normal",
            hp_share=0.5,
            note="The remaining half, once the shield dissipates.",
        ),
    ),
    note="Money-making guide 'Killing Hueycoatl (Solo)' publishes kph=7 - "
    "a slow published rate consistent with the tail phase's own "
    "'significantly prolong[ing]' claim for small teams. See "
    "tests/test_costing_hueycoatl.py for what is pinned. Priced solo; "
    "the three-or-more-player brazier damage bonus is not modelled.",
)
