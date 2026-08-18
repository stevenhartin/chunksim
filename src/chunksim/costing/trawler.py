"""Filling leaks on the Fishing Trawler, which is a ceiling rather than a rate.

**Every term is published and the mechanic is a budget.** The wiki tabulates
what each action on the boat is worth:

| Action | Points | Skill | XP |
|---|---|---|---|
| Bailing water | 2 | - | - |
| Filling a leak with swamp paste | 5 | Construction | 5 |
| Repairing the net with a rope | 7 | Crafting | 5 |
| Attacking the kraken (per chop) | 10 | Woodcutting | 5 |
| Fixing a broken rail | 10 | Construction | 5 |

and caps the lot: "A maximum of 255 points may be earned per game". So the
game is a 255-point budget, and what a skill can take out of it is decided by
its action's **points per experience** rather than by how fast anyone clicks.

**Filling leaks is the best Construction can do**, at one point per
experience - fixing a rail pays the same 5 experience for twice the points, so
a player training Construction ignores the rails. 255 points of leaks is
`255 / 5 = 51` of them and `51 x 5 = 255` experience, which is the whole
Construction ceiling for one game.

**A round is 6.5 minutes**: "5 minutes of trawling, 1 minute of docking, and
15 seconds of cutscene at both the start and end of the trawl", so 9.23 games
an hour and **2,354 experience an hour before materials**.

### Why this is a ceiling and says so

Two assumptions sit on top of the published arithmetic, both optimistic, and
neither is checkable from anything the wiki states.

- **Every point comes from leaks.** In a real game the player also bails,
  repairs the net and fights the kraken, and each of those points is one the
  leaks did not get. A player ignoring everything else may also find the boat
  sinking, which ends the game early.
- **Leaks spawn fast enough to absorb 255 points.** Nothing published says
  how often they appear, so 51 in five minutes is assumed rather than known.

`costing/troublebrewing.py` is the same shape and says the same thing: an
arithmetic ceiling is worth having when every term in it is published, and is
worth labelling as one.

### What is deliberately not modelled

**Crafting's net repair, for want of a curve.** Its row is right there in the
table - 7 points, 5 Crafting - but "the chance to successfully fix the net
depends on the player's Crafting level" and the page's only
`{{Skilling success chart}}` is for the *fish*, against Fishing. A rate
computed as though every repair landed would be wrong by exactly the thing
nobody has charted, which is the call `costing/pickpocket.py` makes for the
seven NPCs nothing charts and `costing/shortcuts.py` for its 37. The kraken's
Woodcutting is the same, and has no challenge in the export either.

**Filling a leak has no such chance** - swamp paste on a leak simply works -
which is why Construction is modelled and its two neighbours are not.

Pure: the levels and the item walk come in as arguments.
"""

from __future__ import annotations

from typing import Callable, Mapping

from chunksim.costing.gathering import CONFIRMED
from chunksim.costing.heuristics import ComputedMethod

#: "In total, a round takes roughly 6.5 minutes (5 minutes of trawling, 1
#: minute of docking, and 15 seconds of cutscene at both the start and end)."
ROUND_SECONDS = 6.5 * 60.0

#: "A maximum of 255 points may be earned per game."
POINT_CAP = 255

#: Filling a leak: what it pays in points and in Construction experience. The
#: one-to-one is what makes it the best use of the budget - fixing a rail is
#: the same 5 experience for 10 points.
LEAK_POINTS = 5
LEAK_XP = 5.0

#: Swamp paste a leak eats, and the export's own name for it.
PASTE_ITEM = "Swamp paste"

#: Upstream's own challenges. The Construction one carries `Level: 1` and a
#: `Player-owned house` chunk (the wiki: "A POH must be owned in order to
#: receive Construction XP"); the *Fishing* one carries the real gate, since
#: "15 Fishing is required" to board at all.
TASK = "Fill holes on ~|Fishing Trawler|~"
GATE_TASK = "Train fishing on the ~|Fishing Trawler|~"

#: What the band is called wherever a rate is shown.
METHOD = "Fishing Trawler (leaks)"


def leaks_per_game() -> int:
    """Leaks the point budget allows, floored - the cap is per game."""
    return POINT_CAP // LEAK_POINTS


def xp_per_game() -> float:
    """The Construction ceiling for one game: 255, the cap itself."""
    return leaks_per_game() * LEAK_XP


def seconds_per_game(
    material_seconds: Callable[[str, float], float | None] | None = None,
) -> float | None:
    """One round, with the swamp paste it eats, or `None` with no route to it."""
    if material_seconds is None:
        return ROUND_SECONDS
    paste = material_seconds(PASTE_ITEM, float(leaks_per_game()))
    return None if paste is None else ROUND_SECONDS + paste


def rate(
    material_seconds: Callable[[str, float], float | None] | None = None,
) -> float:
    """Construction an hour, or zero where the paste has no route.

    **Flat in the Construction level**, unlike most of this directory: the
    experience is a property of the action rather than of the player, so a
    level-1 builder and a level-99 one fill leaks at the same rate.
    """
    seconds = seconds_per_game(material_seconds)
    if seconds is None or seconds <= 0:
        return 0.0
    return xp_per_game() * 3600.0 / seconds


def methods(
    valid: Mapping[str, Mapping[str, object]],
    material_seconds: Callable[[str, float], float | None] | None = None,
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Construction": (band,)}`, or empty where the map cannot play.

    **Gated on the Fishing challenge**, which is where upstream states the
    15 Fishing needed to board - its Construction twin says `Level: 1`, and a
    rate written against that would offer the minigame to a player who cannot
    get on the boat. The house is upstream's own `Player-owned house` chunk on
    the Construction challenge, which the derivation already enforces.

    One band, not a curve: see `rate` on why the level does not enter.
    """
    if GATE_TASK not in (valid.get("Fishing") or {}):
        return {}
    if TASK not in (valid.get("Construction") or {}):
        return {}
    found = rate(material_seconds)
    if found <= 0:
        return {}
    return {
        "Construction": (
            ComputedMethod(
                method=METHOD,
                xp_per_hour=found,
                level=None,
                match=CONFIRMED,
                knob=f"training/{TASK}/Construction",
            ),
        )
    }
