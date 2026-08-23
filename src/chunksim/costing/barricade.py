"""Repairing Pest Control's barricades, and the one number nobody publishes.

**An upper bound built deliberately**, and the only reason it is safe to build
is that it loses by six times to the slowest Crafting band on any cached map.
Two of its three terms are the wiki's; the third is a guess with a floor under
it, and this module exists to say which is which.

### What is published

- **Five experience a repair.** `Pest Control/Strategies` states it outright:
  repairing barricades and gates "provides a small amount of Crafting
  experience (5 XP per repair)". The barricade's own page says only "some
  Crafting experience", so the strategy page is where the number lives.
- **Two minutes a game**, and it is the *wiki's* idealisation rather than this
  module's. `Pest Control` describes destroying all four portals as "the most
  common strategy, often completed in under two minutes", and its own
  commendation table says its estimates "are under ideal conditions (minimal to
  no wait time between games, no losses, etc.) and assume 2 minutes per game" -
  before adding that "a more realistic time for the novice lander is 12-14
  hours" against the 4 it tabulates. So the figure is published, and published
  with its own warning that reality is about three times worse.

### What is guessed, and the floor under it

**`REPAIRS_PER_GAME` is invented.** Nothing states how many barricades a game
offers or how many one player can reach, and it is the whole distance between
a floor and a ceiling here.

What bounds it below is a mechanic the game used to have and dropped, which
the wiki records in its trivia: "originally, players had to deal at least 50
points of damage **or repair 10 barricades** in the game in order to receive
commendations. This is no longer the case as of an update, due to player
complaints about participants simply meeting the minimum requirement and not
participating afterwards." So ten a game was reachable often enough that people
complained about it being *easy*, which makes `MINIMUM_REPAIRS_PER_GAME` a
floor with evidence rather than a round number.

**Forty is four times that floor**, chosen to be plainly optimistic rather than
plausible: the complaint the update answered was that a quarter of a game got
you to ten, so four times ten is roughly a whole game spent doing nothing else.
A repair is also gated by the player's weapon speed - the barricade's page says
"the speed of repairing the barricades is determined by the player's equipped
weapon's attack speed" - so a full game of darts is the shape being described,
and no map's Crafting climb notices either way.

### Why a ceiling and not a refusal

`costing/toymouse.py`'s argument. The whole plausible range - ten repairs a
game at 6.5 minutes through forty at two - spans roughly 460 to 6,000 an hour,
and the slowest Crafting band on either cached map is 37,462. Nothing here can
decide a band, so a guess closes the row where a refusal would only have named
it. `GUESS`, for `costing/tempoross.py`'s rule: one invented factor makes the
product invented, however well published the other two are.

Pure: nothing but the valid set comes in.
"""

from __future__ import annotations

from typing import Mapping

from chunksim.costing.gathering import GUESS
from chunksim.costing.heuristics import ComputedMethod

SKILL = "Crafting"

#: Upstream's own challenge. Level 1, a hammer and logs.
TASK = "Repair barricades in ~|Pest Control|~"

METHOD = "Pest Control barricades"

#: **Published** on `Pest Control/Strategies`.
XP_PER_REPAIR = 5.0

#: **The wiki's own ideal-conditions assumption**, stated twice - see the
#: module docstring, including its warning that reality is three times worse.
GAME_MINUTES = 2.0

#: The commendation threshold the game used to have and dropped because it was
#: too easy to meet. **A floor with evidence under it**, and not what is spent.
MINIMUM_REPAIRS_PER_GAME = 10.0

#: **Invented**, at four times that floor - the whole of what makes this a
#: ceiling rather than an estimate.
REPAIRS_PER_GAME = 40.0

#: Upstream files this at level 1 and so does the game.
LEVEL = 1

MINUTES_PER_HOUR = 60.0


def games_per_hour() -> float:
    """Games in an hour at the wiki's own two minutes."""
    return MINUTES_PER_HOUR / GAME_MINUTES


def xp_per_hour(repairs: float = REPAIRS_PER_GAME) -> float:
    """Experience an hour at `repairs` a game.

    Parameterised so the floor can be priced beside the ceiling without either
    being the module's answer - `tests/test_costing_barricade.py` uses it to
    pin that the whole range loses.
    """
    return repairs * XP_PER_REPAIR * games_per_hour()


def methods(
    valid: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Crafting": (one band,)}` if the map can reach the minigame."""
    if TASK not in (valid.get(SKILL) or {}):
        return {}
    return {
        SKILL: (
            ComputedMethod(
                method=METHOD,
                xp_per_hour=xp_per_hour(),
                level=LEVEL,
                match=GUESS,
                knob=f"training/{TASK}/{SKILL}",
            ),
        )
    }
