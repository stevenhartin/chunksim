"""Shipwreck salvaging, and the crewmate who does some of it for you.

**A low-intensity activity with two published halves and a multiplier.** The
`Shipwreck` page states, per wreck, the Sailing level, the experience one
salvage pays for *finding* it, and the experience for *sorting* it at a
station; the money-making guides state a salvage-per-hour for each. What
neither states is a rate this project can use directly, for two reasons.

**Upstream splits the activity where the guides do not.** The export carries
`Salvage at a ~|small shipwreck|~` and `Process some ~|small salvage|~ at a
salvaging station` as two challenges, and the guides bundle both experiences
into one figure - `10+5.5` for a small wreck. Charging the sorting experience
to the salvaging challenge credits it to the wrong method, so this prices the
*find* alone and leaves sorting to its own challenge.

**And the guides assume a crew this model does not.** Three of them are solo
(small, fisherman's, barracuda) and the other five assume two crewmates on two
hooks, each stating its own split - "2/3 of salvages are done by crew on
salvaging hooks for 35% experience". Backing that out gives the player's own
salvage rate, which is what a crewmate multiplies.

**The multiplier is exact, and it is the wiki's own arithmetic.** A crewmate
rolls every 5 ticks against the player's 4, and its chance to find salvage is
the player's scaled by deckhandiness - "10% for D=1, 20% for D=2". So it finds
`(4/5) x (D/10)` of what the player does. It is also paid `D/10` of the
experience per salvage. The two compose:

    crew experience / player experience = (0.8 D/10) x (D/10) = D^2 / 125

which the page states outright. One crewmate at D=4 is therefore **+12.8%**,
not the doubling two hooks and two crew would suggest.

**Crewmates are a Sailing unlock and the curve steps where they arrive.** The
first is Jobless Jim at level 40 (D=3, +7.2%); Cabin Boy Jenkins at 60 is the
first D=4 (+12.8%), and nothing better exists. Below 40 there is no crewmate
and the player salvages alone, so a wreck opening before then is priced solo
until it.

Pure: the level comes in as an argument.
"""

from __future__ import annotations

from typing import Any, Mapping

from chunksim.costing.heuristics import ComputedMethod

#: What a band calls the activity.
ACTIVITY = "shipwreck salvaging"

#: What this labels its rates.
SALVAGE_MATCH = "modelled"
SALVAGE_SOURCE = "computed:salvage"

#: `Output` -> `(Sailing level, experience for finding one salvage, salvages
#: the *player* finds an hour)`.
#:
#: **Levels and find experience are the `Shipwreck` table's**; the hourly
#: figure is each money-making guide's `kph` reduced to the player's own share
#: by the split that guide states. Small, fisherman's and barracuda are solo
#: guides and need no reduction; the rest assume two crewmates doing a stated
#: fraction, so 360/hr at a large wreck with "2/3 done by crew" is 120 the
#: player found.
#:
#: Stated rather than parsed because the two halves come off different pages
#: and one of them is a template expression - the same standing as
#: `farming.DEFAULT_HARVESTS_PER_DAY`. Sorting experience is deliberately
#: absent: it belongs to the `Process some ...` challenge.
SHIPWRECKS: dict[str, tuple[int, float, float]] = {
    "Small salvage": (15, 10.0, 140.0),
    "Fishy salvage": (26, 17.0, 160.0),
    "Barracuda salvage": (35, 31.0, 220.0),
    "Large salvage": (53, 48.0, 120.0),
    "Plundered salvage": (64, 76.0, 120.0),
    "Martial salvage": (73, 138.0, 157.5),
    "Fremennik salvage": (80, 162.0, 103.3),
    "Opulent salvage": (87, 200.0, 93.3),
}

#: Sailing level -> the best deckhandiness hireable at it. **Only the steps
#: that matter**: Jobless Jim (D=3) at 40 is the first crewmate at all, and
#: Cabin Boy Jenkins (D=4) at 60 is the best there has ever been - Jolly Jim
#: at 85 is a second D=4 rather than an upgrade. Everything hired between is
#: worse than what is already held.
CREW_UNLOCKS: tuple[tuple[int, int], ...] = ((40, 3), (60, 4))


def crew_bonus(level: int) -> float:
    """The share one crewmate adds to the player's experience at `level`.

    `D^2 / 125`, and `0.0` below level 40 where there is no crewmate to hire.
    """
    best = max((deck for need, deck in CREW_UNLOCKS if need <= level), default=0)
    return best * best / 125.0


def steps_for(level: int) -> tuple[int, ...]:
    """The levels a wreck opening at `level` changes rate at.

    Its own, and each crewmate unlock above it - the rate is flat between,
    because nothing else in the model moves with level.
    """
    return (level, *(need for need, _ in CREW_UNLOCKS if need > level))


def xp_per_hour(output: str, level: int) -> float:
    """A wreck's Sailing experience an hour at Sailing `level`.

    The player's own salvage rate times what a find pays, raised by the one
    crewmate the level allows. `0.0` for anything not a shipwreck.
    """
    found = SHIPWRECKS.get(output)
    if found is None:
        return 0.0
    _, experience, per_hour = found
    return per_hour * experience * (1.0 + crew_bonus(level))


def methods(
    challenges: Mapping[str, Any], valid: Mapping[str, Any]
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{skill: bands}` for every shipwreck a map can salvage.

    Bands rather than one rate, because the crewmate unlocks move it: a wreck
    open at 15 is worth 1,400/hr alone, 1,501 once Jobless Jim can be hired at
    40, and 1,579 from Cabin Boy Jenkins at 60.
    """
    found: list[ComputedMethod] = []
    for task in sorted(valid or {}):
        challenge = challenges.get(task)
        if not isinstance(challenge, dict) or challenge.get("Primary") is not True:
            continue
        output = challenge.get("Output")
        if not isinstance(output, str) or output not in SHIPWRECKS:
            continue
        opens = SHIPWRECKS[output][0]
        found.extend(
            ComputedMethod(
                method=ACTIVITY,
                xp_per_hour=xp_per_hour(output, step),
                level=step,
                match=SALVAGE_MATCH,
                knob=f"training/{task}/Sailing",
            )
            for step in steps_for(opens)
        )
    return {"Sailing": tuple(found)} if found else {}
