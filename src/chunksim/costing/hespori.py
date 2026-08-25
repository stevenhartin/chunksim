"""Hespori: a sporadic boss whose 32-hour growth dwarfs the fight that ends
it.

**The fight is not the rate.** `Hespori` already carries a real drop table in
the export - a bottomless compost bucket at 1/35, the seeds - so
`dps_bridge.price_monsters` prices a kill the ordinary way and nothing here
is missing the way a raid's chest is. What is missing is the wait: "you must
first plant a hespori seed in the hespori patch within the cave, and then
wait 22-32 hours for it to grow... after killing it, the seed may be
harvested." A model that only asked how long the fight itself takes would
report the bottomless compost bucket at whatever `Hespori`'s own combat kph
implies - a monster fought and regrown in minutes, when a real kill is
gated behind a day and a half regardless of how fast the fight goes.

### `GROW_SECONDS` is published, not guessed

Unlike `costing/gauntlet.py`'s `PREP_SECONDS` or `costing/tzhaar.py`'s
`PER_WAVE_SECONDS`, this is not this project's own figure: the
[[hespori seed]]'s own farming recipe states `time = 1,920 minutes (3x640
min = 32 hours)` outright, and the boss's own page: "wait 22-32 hours for it
to grow (depending on planting time)" - the range is timing variance within
one growth cycle, not a different total, so 32 hours (the recipe's own
stated figure, and the top of the wiki's own range) is what this module
spends rather than an invented midpoint.

### Where the correction happens

**Not a `FightScript` and not a `costing/raids.py`-style chest fix** - the
fight is ordinary and the drops are already priced. This module is instead
applied by `costing/dps_bridge.enrich` directly to the `Rate` that
`price_monsters` already computed for `Hespori`: the ordinary combat-only
kph is converted back to a time-to-kill, `GROW_SECONDS` is added, and the
result is converted back to a kph. `Rate.value` moves; `Rate.source` and
`Rate.match` do not, so a reader can still see the fight was genuinely
simulated.

### What stays unmodelled

Only one Hespori exists per player at a time, and this project has no
notion of "in progress" state - it prices the steady-state rate of an
uninterrupted plant/kill/replant cycle, not a save with a Hespori already
mid-growth. The 22-hour end of the wiki's own range (the fastest possible
timing) is not modelled either; 32 hours is the ceiling on speed, matching
this subpackage's usual convention of stating the slower, more defensible
figure rather than the best case.

Pure: a constant and one function, no `osrs_dps` import.
"""

from __future__ import annotations

HESPORI = "Hespori"

#: Published on the hespori seed's own farming recipe: "1,920 minutes
#: (3x640 min = 32 hours)". See the module docstring on why this is not an
#: invented figure the way most other overhead constants in this subpackage
#: are.
GROW_SECONDS = 32.0 * 3600.0


def effective_seconds(kill_seconds: float) -> float:
    """One real Hespori cycle: the 32-hour grow, plus `kill_seconds` for
    the fight itself."""
    return GROW_SECONDS + kill_seconds
