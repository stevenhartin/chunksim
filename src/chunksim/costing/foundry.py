"""The Giants' Foundry, priced from an alloy rather than from a tier.

**The release patch notes are a summary and this used to be built on them.**
They give five "alloy tiers" against a swords-an-hour and an
experience-a-sword column, which multiply out to the six figures
`wiki:Giants' Foundry` carries - and which describe none of what a player
actually chooses. What is really going on is on the strategy page, and every
piece of it is published.

### One preform is 28 bars in whatever ratio you like

You pick two metals and how many of each, to a combined 28, and the pair and
ratio give a **metal score** - `Giants' Foundry/Strategies` tabulates all
fifteen pairs against all 27 ratios. `ALLOYS` carries the best ratio for each
pair, which is where the mixed-bar figures come from: mithril and adamant
peak at 95 with 14 of each, and adamant and rune at 130.

### A sword's quality is that score plus the mould

`quality = mould score + metal score - mistakes`, and the strategy page states
what a mould is worth: "the average mould score using optimal purchased moulds
is 59" - `MOULD_SCORE` - against 38 for the default ones, which
`DEFAULT_MOULD_SCORE` carries but nothing spends. Mistakes are assumed away,
which is what "optimal" means everywhere else in this directory.

So mithril and adamant at 14/14 is `59 + 95 = 154`.

### And the experience is a closed formula

The main page gives it exactly:

    (floor(q^2 / 73) + floor(1.5 * q) + 1) * 30

At `q = 154` that is 16,680 experience for the sword.

### The time is the metal score again, through the difficulty table

A higher score is a harder sword: 10-19 needs three hammer/grind/polish
sections, 20-59 four, 60-89 five, 90-119 six and 120-130 seven. A sword costs
`PREAMBLE_SECONDS` to hand in and set up plus `SECONDS_PER_SECTION` for each
section, so 154 quality at six sections is 300 seconds - twelve swords an hour
and 200,160 experience.

**This is why the tier summary was the wrong model and not merely a coarse
one: the best alloy is not the highest-scoring one.** Bronze with rune scores
60 and bronze with adamant 50, but the 60 crosses into five sections and comes
out *slower* - 157,553 an hour against 167,657. A model built on tiers cannot
express that, because the tier is the thing being chosen against.

### Checked against the strategy page's own hourly table

That page tabulates swords an hour and experience an hour for five alloys, and
this lands within 9% on all of them and within 2.1% on the two a player at 70
or above would actually run:

    alloy               wiki xp/h   here      ratio
    bronze/iron            97,920   106,971   1.092
    iron/steel            133,920   145,543   1.087
    steel/mithril         164,640   168,141   1.021
    mithril/adamant       198,000   200,160   1.011
    adamant/rune          253,110   241,983   0.956

The two four-section rows are the loose ones, and the cause is visible: the
table's swords-an-hour are integers, and its 16 implies 225 seconds a sword
where 30 + 4 x 45 is 210. Its own numbers also imply a mould score of 58 on
every row rather than the 59 the same page states in prose. Both are followed
here as stated rather than back-fitted, which is what makes the residual
readable.

Pure: nothing but the valid set comes in.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping

from chunksim.costing.gathering import CONFIRMED
from chunksim.costing.heuristics import ComputedMethod

SKILL = "Smithing"

#: "The average mould score using optimal purchased moulds is 59."
MOULD_SCORE = 59.0

#: "The average mould score using the optimal default moulds is 38." Carried
#: because it is the measurement `MOULD_SCORE` is the *other* of, and a map
#: that cannot buy moulds is a real case somebody may want to price one day.
DEFAULT_MOULD_SCORE = 38.0

#: Seconds to hand a sword in and load the next preform. Fixed per sword.
PREAMBLE_SECONDS = 30.0

#: Seconds for one hammer/grind/polish section.
SECONDS_PER_SECTION = 45.0

#: Bars in a preform, however they are split between the two metals.
BARS_PER_PREFORM = 28

#: Metal score -> sections, from the main page's difficulty table.
DIFFICULTY: tuple[tuple[int, int, int], ...] = (
    (10, 19, 3),
    (20, 59, 4),
    (60, 89, 5),
    (90, 119, 6),
    (120, 130, 7),
)


@dataclass(frozen=True)
class Alloy:
    """One bar pair at its best ratio, off the strategy page's table."""

    first: str
    second: str
    #: Smithing level the pair needs, which is the higher metal's.
    level: int
    #: The pair's best metal score, over all 27 ratios.
    metal_score: int
    #: The split that reaches it, as `(first, second)` counts summing to 28.
    ratio: tuple[int, int]


ALLOYS: tuple[Alloy, ...] = (
    Alloy("bronze", "iron", 15, 21, (9, 19)),
    Alloy("bronze", "steel", 30, 30, (9, 19)),
    Alloy("iron", "steel", 30, 40, (14, 14)),
    Alloy("bronze", "mithril", 50, 40, (7, 21)),
    Alloy("iron", "mithril", 50, 51, (12, 16)),
    Alloy("steel", "mithril", 50, 65, (14, 14)),
    Alloy("bronze", "adamant", 70, 50, (5, 23)),
    Alloy("iron", "adamant", 70, 62, (11, 17)),
    Alloy("steel", "adamant", 70, 78, (13, 15)),
    Alloy("mithril", "adamant", 70, 95, (14, 14)),
    Alloy("bronze", "rune", 85, 60, (4, 24)),
    Alloy("iron", "rune", 85, 73, (10, 18)),
    Alloy("steel", "rune", 85, 91, (12, 16)),
    Alloy("mithril", "rune", 85, 110, (14, 14)),
    Alloy("adamant", "rune", 85, 130, (14, 14)),
)

#: Metal -> the export's challenge for it. A metal is usable exactly when its
#: challenge is valid, which is how a map that cannot reach rune bars is kept
#: from being priced at an adamant-and-rune alloy.
PREFORMS: dict[str, str] = {
    "bronze": "Forge a bronze ~|preform|~ in the Giants' Foundry",
    "iron": "Forge an iron ~|preform|~ in the Giants' Foundry",
    "steel": "Forge a steel ~|preform|~ in the Giants' Foundry",
    "mithril": "Forge a mithril ~|preform|~ in the Giants' Foundry",
    "adamant": "Forge an adamant ~|preform|~ in the Giants' Foundry",
    "rune": "Forge a rune ~|preform|~ in the Giants' Foundry",
}

#: The levels a new alloy becomes available at, which is where the rate steps.
BANDS: tuple[int, ...] = (15, 30, 50, 70, 85)


def sections_for(metal_score: int) -> int:
    """Hammer/grind/polish sections a sword of this score needs."""
    for low, high, sections in DIFFICULTY:
        if low <= metal_score <= high:
            return sections
    return DIFFICULTY[-1][2]


def quality(metal_score: int, *, mould_score: float = MOULD_SCORE) -> float:
    """`mould score + metal score`, mistakes assumed away."""
    return mould_score + metal_score


def experience_per_sword(quality_score: float) -> float:
    """The main page's closed formula for handing a sword in."""
    q = int(quality_score)
    return float((math.floor(q * q / 73) + math.floor(1.5 * q) + 1) * 30)


def seconds_per_sword(metal_score: int) -> float:
    """The preamble, plus a section's worth of work for each section."""
    return PREAMBLE_SECONDS + SECONDS_PER_SECTION * sections_for(metal_score)


def swords_per_hour(metal_score: int) -> float:
    return 3600.0 / seconds_per_sword(metal_score)


def rate_for(alloy: Alloy, *, mould_score: float = MOULD_SCORE) -> float:
    """Smithing experience an hour running this alloy at its best ratio."""
    paid = experience_per_sword(quality(alloy.metal_score, mould_score=mould_score))
    return paid * swords_per_hour(alloy.metal_score)


def best_alloy(level: int, metals: frozenset[str]) -> Alloy | None:
    """The fastest alloy a player at `level` holding `metals` can run.

    **By rate rather than by metal score**, which is the whole point of
    modelling this at all: bronze with rune scores 60 against bronze with
    adamant's 50 and is *slower*, because 60 crosses into a fifth section.
    """
    usable = [
        alloy
        for alloy in ALLOYS
        if alloy.level <= level
        and alloy.first in metals
        and alloy.second in metals
    ]
    return max(usable, key=rate_for) if usable else None


def methods(
    valid: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Smithing": (...)}` for the alloys a map's reachable bars allow.

    **Each band is emitted once, on the challenge for its dearer metal**, and
    that is not cosmetic: `training_options` charges a computed method for
    what its *task* consumes, so putting every alloy on every preform let the
    walk pair an adamant-and-rune rate with the bronze preform's bar cost and
    read Smithing at 106.9 hours. One band, one task, one material cost.

    The dearer metal is the alloy's second, which is also the one that gates
    its level. It is an over-estimate of the bars - the pairs are near enough
    to half and half - and over-estimating what a method consumes is the side
    to err on.

    Which challenges are valid decides which *metals* are on the table; the
    choice of alloy is then made inside the activity rather than between
    methods, which is why `best_alloy` picks by rate.

    **Bronze is never an alloy's dearer half**, so no band is emitted on its
    challenge and `Forge a bronze ~|preform|~` is left unpriced. The activity
    is still fully covered - bronze's one good alloy is bronze-and-iron, which
    is emitted on the *iron* challenge - so what is missing is a label rather
    than a method. Emitting it on the bronze challenge instead would attach
    bronze's cheap bars to an alloy that is 23 parts adamant, which is the
    error this whole arrangement exists to avoid.
    """
    reachable = valid.get(SKILL) or {}
    metals = frozenset(m for m, task in PREFORMS.items() if task in reachable)
    if not metals:
        return {}
    found: list[ComputedMethod] = []
    for level in BANDS:
        alloy = best_alloy(level, metals)
        if alloy is None:
            continue
        found.append(
            ComputedMethod(
                method=f"Giants' Foundry ({alloy.first}/{alloy.second})",
                xp_per_hour=rate_for(alloy),
                level=level,
                match=CONFIRMED,
                knob=f"training/{PREFORMS[alloy.second]}/{SKILL}",
            )
        )
    return {SKILL: tuple(found)} if found else {}
