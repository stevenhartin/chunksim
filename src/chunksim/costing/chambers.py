"""Chambers of Xeric: whichever creature your level allows.

**You do not choose, you are given the best one you qualify for.**

**The gate is one skill and used to be two, which was a misreading of the
sentence it came from.** Every page states two requirements - `Psykk bat` says
"they require a **Hunter** level of 90 to catch and grant 29 Hunter
experience. Once caught, raw psykk bats can be **cooked** into a psykk bat
(6), requiring a **Cooking** level of 90" - and this module read the pair as a
compound gate, `min(skill, Cooking) >= requirement`. It is two requirements
for two actions. `{{Hunter info}}` states `level = 90` and no Cooking, and
upstream agrees: `Catch a ~|psykk bat|~` is Hunter 90 and `Cook a ~|psykk
bat|~` is a separate Cooking 90 challenge priced by its own recipe.

**What the misreading cost was the report rather than a rate.** The ladders
happen to match tier for tier, so on a map whose Cooking keeps up nothing
moved - but the band for a tier the map's Cooking could not reach was never
emitted at all, so its challenge got no knob and read **`unpriced`**: the one
word meaning "nothing reached this" about a method this module knows exactly
how to price. On the export census, which borrows a map's progress and infers
Cooking in the thirties, that hid six of the seven bats and six of the eight
fish.

Two families, one mechanic. Seven bats netted for Hunter and seven fish caught
for Fishing, on the same ladder of requirements - 1, 15, 30, 45, 60, 75, 90.

That makes each of them one method stepping through seven tiers rather than
seven methods competing, which is why they sit beside the gathering walk like
Puro-Puro and aerial fishing. No roll to fail and no supply to run out: four
ticks a catch, 1,500 an hour, times the tier's experience.

The reachability gate is upstream's: every one of these challenges carries
`Chunks: ["Chambers of Xeric"]`.

Pure: the table and the two levels come in as arguments.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from chunksim.costing.gathering import CONFIRMED, CURVE_STEPS, Tables
from chunksim.costing.heuristics import ComputedMethod


@dataclass(frozen=True)
class Family:
    """One ladder of Chambers creatures, and the skill it pays.

    `members` is `(challenge name, infobox page)` worst first - named rather
    than discovered because the infobox is keyed by the *item* page (`Raw psykk
    bat (6)`) and the name is the only thing tying the challenge to it.
    """

    skill: str
    members: tuple[tuple[str, str], ...]


#: Ticks to catch one. Fixed, and there is no roll to fail.
CATCH_TICKS = 4.0

#: The skill that gates both families. Its *level* decides which creature
#: appears; its experience is a separate action and is not counted here.
GATING_SKILL = "Cooking"

FAMILIES: tuple[Family, ...] = (
    Family(
        skill="Hunter",
        members=(
            ("guanic bat", "raw guanic bat (0)"),
            ("prael bat", "raw prael bat (1)"),
            ("giral bat", "raw giral bat (2)"),
            ("phluxia bat", "raw phluxia bat (3)"),
            ("kryket bat", "raw kryket bat (4)"),
            ("murng bat", "raw murng bat (5)"),
            ("psykk bat", "raw psykk bat (6)"),
        ),
    ),
    Family(
        skill="Fishing",
        members=(
            ("pysk fish", "raw pysk fish (0)"),
            ("suphi fish", "raw suphi fish (1)"),
            ("leckish fish", "raw leckish fish (2)"),
            ("brawk fish", "raw brawk fish (3)"),
            ("mycil fish", "raw mycil fish (4)"),
            ("roqed fish", "raw roqed fish (5)"),
            ("kyren fish", "raw kyren fish (6)"),
        ),
    ),
)


def catches_per_hour() -> float:
    """1,500 - four ticks each, continuously."""
    return 3600.0 / (CATCH_TICKS * 0.6)


def best(
    tables: Tables, family: Family, level: int) -> tuple[str, float] | None:
    """`(creature, experience)` for the best one `level` allows, or `None`.

    **One skill, not two** - see the module docstring on the sentence that
    used to be read as a compound gate.
    """
    entries = tables.skill_info.get(family.skill) or {}
    held = level
    found: tuple[str, float] | None = None
    for name, page in family.members:
        entry = entries.get(page)
        if entry is None:
            continue
        requirement, paid = entry
        if held >= requirement and paid > 0:
            found = (name, paid)
    return found


def methods(
    tables: Tables, valid: Mapping[str, Mapping[str, object]]
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{skill: (...)}` stepping through the tiers this map can reach."""
    if not tables.skill_info:
        return {}
    found: dict[str, tuple[ComputedMethod, ...]] = {}
    for family in FAMILIES:
        reachable = {
            name
            for name, _page in family.members
            if f"Catch a ~|{name}|~" in (valid.get(family.skill) or {})
        }
        if not reachable:
            continue
        banded: list[ComputedMethod] = []
        for level in (1, *CURVE_STEPS):
            chosen = best(tables, family, level)
            if chosen is None or chosen[0] not in reachable:
                continue
            name, paid = chosen
            banded.append(
                ComputedMethod(
                    method=name,
                    xp_per_hour=paid * catches_per_hour(),
                    level=level,
                    match=CONFIRMED,
                    knob=f"training/Catch a ~|{name}|~/{family.skill}",
                )
            )
        if banded:
            found[family.skill] = tuple(banded)
    return found
