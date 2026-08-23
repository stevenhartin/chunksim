"""Desiccated pages, where the contribution cancels and the rate falls out.

**A Runecraft method whose whole cost is a boss fight.** The Royal Titans
offer three things to do with a kill, and one of them is `Take pages`:
forfeit the drop table for a stack of [[desiccated page]]s. A page is walked
to one of three elemental plinths and reinvigorated, which is level 50
Runecraft, boostable "No", and **50 experience a page** - stated twice, on the
item's own page and again on `Book of Eternal Flame`. Upstream carries all
three conversions, one per plinth, and priced none of them: there is no
`{{Recipe}}` for a plinth, and the item walk cannot see the `Take pages`
choice at all - it reads the *drop tables*, where a page is a 2/56 roll of
6-24 rather than a guaranteed stack.

### Pages an hour, and why the party size does not matter

Both bosses' drop tables carry the same line under `dropversion=Take pages`:
`Desiccated page`, `quantity=10-19`, `rarity=Always`, and the wiki does the
arithmetic itself - "With an average roll of 14.5 pages". You loot **one** of
the two titans per kill, so that is one roll per encounter.

The other half is the money-making guides, one per titan, which state the same
`kph = 48` and price every output at `*0.5` - the duo contribution the fight is
designed around. So a player collects `48 x 0.5 = 24` full-contribution kills
an hour, and:

    348 pages an hour = 48 kph x 0.5 contribution x 14.5 pages
                      = 17,400 Runecraft experience

**The contribution cancels, which is what makes this robust.** Quantities scale
linearly with damage dealt - the wiki's own worked example is a player at 50%
rolling for 140-160 coal against 280-320 at 100% - so a solo player kills half
as often for twice the pages and lands on the same 348. The model therefore
never has to decide whether anyone is alone, which is the one thing about the
Royal Titans that a chunk map could not answer.

### The DPS model is the check, and it agrees within its own known bias

Asked directly, `costing/dps_bridge.py` puts both titans at 600 hitpoints and
86.3 seconds each with the gear the every-rollable-chunk map reaches - so 172.6
seconds of fighting, 20.9 encounters an hour before overhead and 17.8 with one,
which is **258 to 303 pages an hour against the guide's 348**. That ratio of
0.74-0.87 is the boss bias `dps_bridge` measures and documents on itself: "the
wiki assumes a maximum account with protection prayers and mid-fight style
switching, and this map fights with what `bis.py` could reach", landing bosses
at 0.71 overall. Two independent routes inside the documented gap is a check
rather than a coincidence.

**The published figure is the one spent**, for the reason that decides it
everywhere else here: `osrs-dps` is an optional extra and the estimator has to
answer without it, so a rate that existed only when the extra was installed
would be the only one in the project. What the check buys is the knowledge
that a real map's gear moves this by a quarter and not by a factor.

### A ceiling, because the conversion is not charged

`costing/trawler.py`'s sense of the word: every term above is published, and
what sits on top is not. Nothing anywhere states how long `Reinvigorate` takes,
and nothing states whether a stack converts in one action or one page at a
time. Neither is charged, and neither is invented - which is defensible here
in a way it would not be for a bank-bound recipe, because **a desiccated page
is stackable**. A whole session's pages ride in one inventory slot and one trip
to the plinth serves all of them, so the walk amortises the way
`costing/chisel.py`'s dark essence block does rather than being a per-page cost
somebody declined to count.

For scale: at 348 pages an hour a page arrives every 10.3 seconds, so even a
five-tick conversion charged per page would move this to 14,500 - inside the
gap the DPS check already brackets.

### One rate, three challenges

The page is the same page and only the plinth differs, so all three take the
same bands - `courses.Course.also`'s rule. Each is gated by its own challenge
being valid, which is upstream checking both the plinth object and a route to
`Desiccated page*`; the map having the titans is therefore already asserted by
the time this is asked, and no level is compared here.

`CONFIRMED`: the 14.5, the 48 and the 50 are all published, and the
contribution factor is the guides' own.

Pure: nothing but the valid set comes in.
"""

from __future__ import annotations

from typing import Mapping

from chunksim.costing.gathering import CONFIRMED
from chunksim.costing.heuristics import ComputedMethod

SKILL = "Runecraft"

#: Upstream's three conversions, one per elemental plinth. Same rate on each -
#: the plinth decides which page comes out, not how fast.
TASKS: tuple[str, ...] = (
    "Craft a ~|burnt page|~ from a desiccated page",
    "Craft a ~|soaked page|~ from a desiccated page",
    "Craft a ~|soiled page|~ from a desiccated page",
)

#: **Published** on both `Desiccated page` and `Book of Eternal Flame`.
XP_PER_PAGE = 50.0

#: The level both the item page and upstream state, `{{Boostable|No}}`. Carried
#: so a band opens where upstream's challenge does rather than at 1.
LEVEL = 50

#: The mean of the `10-19` the `Take pages` drop line states, and **the wiki's
#: own arithmetic** rather than this project's: both boss pages read "With an
#: average roll of 14.5 pages".
PAGES_PER_KILL = 14.5

#: `kph = 48`, stated identically by `Money making guide/Looting Eldric the Ice
#: King` and `.../Looting Branda the Fire Queen`. It is the *encounter* rate:
#: one kill of the pair, one loot.
KILLS_PER_HOUR = 48.0

#: The guides' own `*0.5` on every `Output`, being the duo the fight is built
#: for. It cancels against the kill rate - see the module docstring - so this
#: is the factor that turns a duo's kills into one player's share rather than
#: an assumption about how anybody plays.
CONTRIBUTION = 0.5


def pages_per_hour() -> float:
    """Desiccated pages one player collects in an hour of Royal Titans."""
    return KILLS_PER_HOUR * CONTRIBUTION * PAGES_PER_KILL


def xp_per_hour() -> float:
    """Runecraft experience an hour, if the plinth trip is free."""
    return pages_per_hour() * XP_PER_PAGE


def methods(
    valid: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Runecraft": bands}`, one per plinth this map can reach.

    Nothing is compared here: upstream's challenge already asks for the plinth
    *and* for `Desiccated page*`, so its validity is the statement that this
    map can both reach the titans and convert what they drop.
    """
    reachable = valid.get(SKILL) or {}
    bands = tuple(
        ComputedMethod(
            method="reinvigorating desiccated pages",
            xp_per_hour=xp_per_hour(),
            level=LEVEL,
            match=CONFIRMED,
            knob=f"training/{task}/{SKILL}",
        )
        for task in TASKS
        if task in reachable
    )
    return {SKILL: bands} if bands else {}
