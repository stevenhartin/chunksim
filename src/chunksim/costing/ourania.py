"""The Ourania Altar, where the published rates assume the essence was bought.

**The whole method is published, twice over.** `Ourania Altar` tabulates an
experience rate for every ten-level band, and it does not merely state the
numbers - each cell is a wiki expression over its own components, with the
formula written out in a hidden comment beside the table:

    xp_per_ess * ess_per_lap * (seconds_in_hour - npc_contact_time_per_hour)
        / seconds_per_lap

So this module is `costing/barracuda.py`'s relationship again: read the
components, land on the published column exactly, and the scrape stops being
the source and becomes the **oracle**. `rate_at` with no material cost
reproduces all fourteen rows to the experience point, and
`tests/test_costing_ourania.py` asserts it, so the day the wiki re-times a lap
the next run fails a test instead of the two drifting apart.

### The three components, and why the middle one is not a magic number

- **`xp_per_essence`** is the page's own `XP/essence` column, 9.39 at level 1
  rising to 15.58 at 99. It is the rune distribution (a Mod Ash table, banded
  every ten levels) times the altar's flat 1.7x, and the page publishes the
  product so nothing here has to walk the distribution.
- **`essence_per_lap`** is 29, 34, 42, 53, 66 - and it is **the pouches**, not
  an observation. A 28-slot inventory less one for the rune pouch and one per
  essence pouch, plus what the pouches hold: `26+3`, `25+3+6`, `24+3+6+9`,
  `23+3+6+9+12`, and then `26+40` when the colossal pouch at 85 replaces all
  four. Every step in the column falls out of a pouch unlocking.
- **`contact_seconds`** is the Astral Contact casting that repairs degrading
  pouches, which the page charges as 15 seconds an hour per pouch tier
  unlocked. **It goes to zero at 99**, and that is not a rounding: the
  Runecraft cape "prevents essence pouches from degrading, removing the need
  for the Astral Contact spell". A quotient would have hidden that; the
  components make it the reason the last band jumps.

`LAP_SECONDS` is the page's own stated assumption, "approximate ~48
seconds/lap", and it says the tick-perfect rates are about 5% higher.

### What this project has to change, and it is most of the answer

**The published rates assume the essence is in the bank.** A chunk map mines
it, and one pure essence walks out of `estimate.material_seconds` at about 2.4
seconds - one mining action. At 66 essence a lap that is 158 seconds of mining
against 48 of running, so the mining is three quarters of the method:

| Runecraft | published | with the essence mined |
|---|---|---|
| 1 | 20,423 | 8,336 |
| 50 | 42,077 | 13,573 |
| 99 | 77,121 | 17,935 |

**And the correction flattens the curve, which is the finding.** Published, the
climb spans 3.8x from level 1 to 99; mined, it spans 2.2x. A bigger pouch buys
fewer trips and buys nothing at all against the pickaxe, so the pouch tiers -
which are what the published column's biggest steps are made of - are worth
much less here than to a player who buys essence. That is the same asymmetry
`costing/valetotems.py` found in Fletching and `costing/production.py`
generalised: a guide's figure and a chunk map's differ by exactly the gathering
the guide assumes away.

The essence is folded into each band's own lap rather than declared through
`Heuristics.material_seconds_per_xp`, for `costing/crane.py`'s reason: that map
is one number per task and the cost per experience here moves with the band,
since `xp_per_essence` rises while the essence keeps costing the same. **No
route to a pure essence is no rate** - `crane.py`'s refusal, and
`recipe_rates.rate_for`'s before it.

### A ceiling, and the assumptions are the page's own

`costing/trawler.py`'s sense. The page states what its table assumes - "players
are using a rune pouch, have all of the essence pouches available at each
level, and the Ourania Teleport spell is being used" - and the teleport wants
71 Magic and Lunar Diplomacy while the pouches come out of the Abyss. A map may
hold none of that. Those assumptions ride along unchanged rather than being
re-derived, which is `costing/coxchest.py`'s call: the components are only
meaningful together, and a lap time recovered under one regime cannot be spent
under another.

**The Astral Contact deduction stays per hour** even though a mined lap is
three times longer, so it is charged against fewer laps than actually happen.
That over-charges, by at most 1.7%, and keeping the page's shape is what lets
the zero-material case be an identity rather than an approximation.

**Daeyalt essence is deliberately not modelled.** The page tabulates it beside
pure at a flat 1.5x, but upstream writes `Items: ["Pure essence*"]` on the
challenge and nothing else - the signal is upstream's `Items` rather than what
the wiki also permits - and no cached map can route a daeyalt essence anyway.

**The Ardougne diary's extra runes are not modelled either**, and cost nothing:
the page says outright that they arrive with "no extra experience".

`CONFIRMED`: every term is the page's, and the material cost is the item walk's.

Pure: the valid set and a material-cost closure, both handed in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from chunksim.costing.gathering import CONFIRMED
from chunksim.costing.heuristics import ComputedMethod

SKILL = "Runecraft"

#: Upstream's one challenge. Its `Level` is 1 and the altar needs no talisman,
#: tiara or level - "players do not need a specific Runecraft level in order to
#: craft at this altar".
TASK = "Craft runes at the ~|Ourania Altar|~"

#: What a band calls the activity.
METHOD = "Ourania Altar"

#: The one essence upstream names. See the module docstring on daeyalt.
ESSENCE = "Pure essence"

#: The page's own stated lap, "approximate ~48 seconds/lap". It notes that
#: tick-perfect play is about 5% faster, which is not spent -
#: `costing/sepulchre.py`'s "tick-perfect is not a rate".
LAP_SECONDS = 48.0

SECONDS_PER_HOUR = 3600.0


@dataclass(frozen=True)
class Band:
    """One ten-level row of the page's `Experience rates` table."""

    #: Where the row opens.
    level: int
    #: The page's `XP/essence` column: the rune distribution times 1.7.
    xp_per_essence: float
    #: Inventory space plus pouches - see the module docstring, where every
    #: step is derived from a pouch unlocking.
    essence_per_lap: int
    #: Seconds an hour lost to Astral Contact repairing the pouches. Zero at
    #: 99, where the Runecraft cape stops them degrading.
    contact_seconds: float
    #: The page's own `XP/h` for this row. **A check, not a source**: it is
    #: this row's other three fields multiplied, so carrying it is what lets a
    #: test notice the wiki re-timing the lap.
    published: int


#: Transcribed from `Ourania Altar`'s `Experience rates` table, one entry per
#: row, in the page's order.
BANDS: tuple[Band, ...] = (
    Band(1, 9.39, 29, 0.0, 20_423),
    Band(10, 10.52, 29, 0.0, 22_881),
    Band(20, 11.34, 29, 0.0, 24_664),
    Band(25, 11.34, 34, 15.0, 28_797),
    Band(30, 12.27, 34, 15.0, 31_158),
    Band(40, 12.90, 34, 15.0, 32_758),
    Band(50, 13.47, 42, 30.0, 42_077),
    Band(60, 13.63, 42, 30.0, 42_577),
    Band(70, 14.59, 42, 30.0, 45_576),
    Band(75, 14.59, 53, 45.0, 57_270),
    Band(80, 14.90, 53, 45.0, 58_487),
    Band(85, 14.90, 66, 60.0, 72_526),
    Band(90, 15.35, 66, 60.0, 74_716),
    Band(99, 15.58, 66, 0.0, 77_121),
)


def rate_at(band: Band, essence_seconds: float = 0.0) -> float:
    """Experience an hour on `band`, with the essence costing what it costs.

    At `essence_seconds == 0` this is the page's own expression exactly, which
    is what makes the published column an oracle rather than a source. Above
    zero the mining joins the lap, where it belongs: a pouch saves running and
    saves nothing at the rock.
    """
    lap = LAP_SECONDS + band.essence_per_lap * essence_seconds
    if lap <= 0:
        return 0.0
    working = SECONDS_PER_HOUR - band.contact_seconds
    return band.xp_per_essence * band.essence_per_lap * working / lap


def methods(
    valid: Mapping[str, Mapping[str, object]],
    material_seconds: Callable[[str, float], float | None] | None = None,
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Runecraft": bands}` if the map can reach the altar, else nothing.

    `material_seconds` prices the essence into each lap. Omitted, the figures
    are the page's own - a ceiling, and the one this module's tests pin, since
    a walk is a property of a map rather than of the game.
    """
    if TASK not in (valid.get(SKILL) or {}):
        return {}
    essence = 0.0
    if material_seconds is not None:
        priced = material_seconds(ESSENCE, 1.0)
        if priced is None:
            # **No route to an essence is no rate.** `costing/crane.py`'s
            # refusal: tick-math over an input nothing can price is a
            # made-up number, and here it would be the whole method.
            return {}
        essence = priced
    return {
        SKILL: tuple(
            ComputedMethod(
                method=METHOD,
                xp_per_hour=rate_at(band, essence),
                level=band.level,
                match=CONFIRMED,
                knob=f"training/{TASK}/{SKILL}",
            )
            for band in BANDS
        )
    }
