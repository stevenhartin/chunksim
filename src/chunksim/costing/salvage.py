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

#: What a band calls the other half of it.
SORTING = "sorting salvage"

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

#: `Output` -> experience for sorting one salvage at a station, from the
#: `Salvaging station` table. **The other half of the activity, and upstream's
#: own second challenge** - `Process some ~|opulent salvage|~ at a salvaging
#: station` - which is why it is not added to the find above.
SORTING_EXPERIENCE: dict[str, float] = {
    "Small salvage": 5.5,
    "Fishy salvage": 9.0,
    "Barracuda salvage": 15.5,
    "Large salvage": 24.0,
    "Plundered salvage": 31.5,
    "Martial salvage": 63.5,
    "Fremennik salvage": 75.0,
    "Opulent salvage": 95.0,
}

#: Salvage sorted an hour at a station. **The page's own figure** - "when used
#: optimally close to 1800 salvages per hour can be achieved" - which is a
#: three-tick sort with the banking runs already in it (a bare three ticks
#: would be 2,000).
#:
#: **It is a cadence, not a rate**, and the difference is the whole of why
#: sorting does not run away with the skill: you can only sort what you
#: salvaged. The station will take 1,800 opulent salvages an hour and 95
#: experience each - 171,000/hr on paper - but each one costs a salvage, and
#: `estimate`'s item walk charges that through `action_seconds` on the wreck.
#: What comes out is bounded by the finding, which is the honest answer.
SORT_PER_HOUR = 1800.0

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


def salvage_seconds(output: str, level: int) -> float:
    """Seconds one salvage of `output` takes to find, crewmate included.

    **What the item walk charges the sorting challenge.** Without it a salvage
    priced at `estimate.DEFAULT_ACTION_SECONDS` and sorting read as the
    fastest thing in Sailing by an order of magnitude.
    """
    found = SHIPWRECKS.get(output)
    if found is None:
        return 0.0
    per_hour = found[2] * (1.0 + crew_bonus(level))
    return 3600.0 / per_hour if per_hour > 0 else 0.0


def action_seconds(
    challenges: Mapping[str, Any], valid: Mapping[str, Any], level: int
) -> dict[str, float]:
    """`{task: seconds}` for finding one salvage, per wreck a map reaches."""
    found: dict[str, float] = {}
    for task in valid or {}:
        challenge = challenges.get(task)
        if not isinstance(challenge, dict):
            continue
        output = challenge.get("Output")
        if isinstance(output, str) and output in SHIPWRECKS:
            seconds = salvage_seconds(output, level)
            if seconds > 0:
                found[task] = seconds
    return found


def material_seconds_per_xp(
    challenges: Mapping[str, Any], valid: Mapping[str, Any], level: int
) -> dict[str, float]:
    """`{task: gathering seconds per experience}` for the sorting challenges.

    **The bound that stops sorting running away with the skill.** A station
    takes 1,800 salvages an hour whatever they are, so opulent salvage reads
    171,000 experience an hour on its own - more than twice the best Barracuda
    trial. It is not a training method at that rate, because every one of those
    salvages had to be found first, at roughly 34 seconds each. Charging that
    here is what turns the pair into the single activity it really is.

    Sailing has no `{{Recipe}}` anywhere, so nothing else fills this in for
    these tasks - `recipe_priced` builds the map from the recipe corpus, and
    the whole skill is absent from it.
    """
    found: dict[str, float] = {}
    for task in valid or {}:
        challenge = challenges.get(task)
        if not isinstance(challenge, dict):
            continue
        consumed = _sorted_salvage(challenge)
        if consumed is None:
            continue
        experience = SORTING_EXPERIENCE[consumed]
        seconds = salvage_seconds(consumed, level)
        if experience > 0 and seconds > 0:
            found[task] = seconds / experience
    return found


def material_xp_per_xp(
    challenges: Mapping[str, Any], valid: Mapping[str, Any]
) -> dict[str, float]:
    """`{task: same-skill experience gathering pays, per experience earned}`.

    **The salvage a sorting challenge eats was found by salvaging, and that
    paid Sailing too.** Charging the 34 seconds without crediting the 200
    experience they earned prices the pair as though the finding were somebody
    else's work. Opulent salvage is 95 for sorting against 200 for finding, so
    this is 200/95 - and the effective rate stops being a fraction of the
    station's cadence and becomes the whole activity's.

    Independent of level: both halves scale with the crewmate together, so the
    *ratio* does not move.
    """
    found: dict[str, float] = {}
    for task in valid or {}:
        challenge = challenges.get(task)
        if not isinstance(challenge, dict):
            continue
        consumed = _sorted_salvage(challenge)
        if consumed is None:
            continue
        sorting = SORTING_EXPERIENCE[consumed]
        finding = SHIPWRECKS[consumed][1]
        if sorting > 0:
            found[task] = finding / sorting
    return found


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
    # **Sorting is flat in level and so gets one point.** Nothing about the
    # station changes as the player climbs; what changes is the salvage it
    # consumes, and that is charged through the item walk rather than here.
    for task in sorted(valid or {}):
        challenge = challenges.get(task)
        if not isinstance(challenge, dict) or challenge.get("Primary") is not True:
            continue
        consumed = _sorted_salvage(challenge)
        if consumed is None:
            continue
        found.append(
            ComputedMethod(
                method=SORTING,
                xp_per_hour=SORT_PER_HOUR * SORTING_EXPERIENCE[consumed],
                level=SHIPWRECKS[consumed][0],
                match=SALVAGE_MATCH,
                knob=f"training/{task}/Sailing",
            )
        )
    return {"Sailing": tuple(found)} if found else {}


def _sorted_salvage(challenge: Mapping[str, Any]) -> str | None:
    """The salvage a sorting challenge consumes, or `None` if it is not one.

    Joined on the export's own `Items` rather than the task's words: a sorting
    challenge is the one that *eats* a salvage, where the wreck produces it.
    """
    for required in challenge.get("Items") or ():
        if not isinstance(required, str):
            continue
        name = required.replace("*", "").strip()
        if name in SORTING_EXPERIENCE and name in SHIPWRECKS:
            return name
    return None
