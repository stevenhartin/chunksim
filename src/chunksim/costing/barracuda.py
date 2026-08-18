"""The Barracuda trials, counted from the mechanic instead of read as a quotient.

**The last published figures in Sailing, and they were already arithmetic.**
`Sailing training` states each of the nine trial-and-rank rates as a wiki
expression - `{{#expr:(385 + 14*15 + 2*19.5)*60*60/(108+10)}}` - so what
`remote/skill_tables.parse_sailing` reads is not an observation but a sum
somebody wrote down, evaluated. Every component of it is published on the
trial's own page, which is where this reads them from instead.

**So this reproduces the scrape exactly, and that is the point rather than a
disappointment.** Eight of the nine agree to the experience point and the ninth
is a disagreement between two wiki pages, resolved below. An identity is
worthless as evidence - `costing/gathering_overhead.py`'s docstring says so
about Thieving's stalls - but it is worth a great deal as a *check*:
`tests/test_costing_barracuda.py` asserts every computed rate against the
scraped row, so the day Jagex moves a trial's experience and the wiki follows,
the next `chunksim heuristics` makes a test fail instead of letting the two
drift apart silently. The scrape becomes this model's oracle.

What the move buys beyond that is the components. The training page's factor
order is inconsistent - the Tempor Tantrum writes `14*15` as count-then-each
and the Jubbly Jive writes `25*20` as each-then-count - so a reader of the
scrape cannot tell how many crates a rank collects, and a reader of this can.

### The mechanic

One run of the course is one action. It pays the rank's completion experience
plus everything collected along the way - lost supplies at a fixed rate each,
and whatever the trial's own objective is (rum shipments at the Tempor Tantrum,
sail trims and wind motes at the Jubbly Jive) - and it takes the rank's target
time. The trial's page states all of it in one table.

**The target time is a rank threshold, not a lap time**, and that is the
standing bias in all nine figures. Completion pays "regardless of time taken";
the target is what you must beat *once* for the one-time rank bonus. So the
rate is the rate of a player who exactly ties the threshold - above what a
minimum boat manages and below what a good one does. The wiki's own Gwenith
Glide observation is 5:20 against a 6:09 target. The one-time bonuses (1,000 to
50,000 experience) are correctly absent: they are paid once, not per lap.

**`RESTART_SECONDS` is the training page's own charge** and the only figure here
that comes off it rather than off a trial page. Nothing states what the ten
seconds is; sailing back to the trial master and starting again is the obvious
reading, and the December 2025 change note ("Barracuda Trials now finish when
you sail away, meaning you can only start a trial when close by") is consistent
with it. Dropping it would raise these rates by 3% to 9%.

### The boat-speed model, attempted and refused

The wiki is insistent that the rate depends on the hull - "a rosewood hull to
increase your base boat speed by 20% ... will increase lap speeds and
experience per hour by ~15%", and the Jubbly Jive's page quotes Marlin at
85,000/hr on a teak or mahogany hull against 90,000 on a camphor or ironwood
one. That is exactly the shape this project likes: `Hull` tabulates a boat
speed per tier (1.5 through 3.0) against a Sailing and a Construction level, so
the map would decide which is buildable.

**The two published observations contradict each other.** Rosewood over
ironwood is +20% speed for +15% experience, a 0.75 exponent; camphor over
mahogany is +25% speed for +5.9% experience, a 0.235 one. Lap time is evidently
not a function of boat speed in any form these two figures both support - a
trial is turning, collecting and waiting as much as it is sailing - so there is
no curve to fit and this refuses to invent one. The target time is used for
every rank, which is at least the same assumption everywhere.

Pure: the tables are stated and the join is on upstream's own task name.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from chunksim.costing.heuristics import ComputedMethod
from chunksim.derive.task_names import strip_task_markup

#: What a band calls the activity.
ACTIVITY = "barracuda trials"

#: What this labels its rates.
BARRACUDA_MATCH = "modelled"
BARRACUDA_SOURCE = "computed:barracuda"

#: The skill every trial pays.
SKILL = "Sailing"

#: Seconds between one run ending and the next beginning. **The `Sailing
#: training` table's own `+10`**, and the only figure in this module that does
#: not come off a trial's page - see the module docstring.
RESTART_SECONDS = 10.0


@dataclass(frozen=True)
class Rank:
    """One difficulty of one trial: what a lap pays and how long it is given.

    `extras` is `(count, experience each)` for everything the lap collects
    beyond completing it, kept as terms rather than as a total because that is
    how the disagreement below was found. A term the wiki states *only* as a
    total is one term of one.
    """

    #: Experience for completing the trial at this rank.
    completion: float
    #: `(count, experience each)` for what the lap collects.
    extras: tuple[tuple[int, float], ...]
    #: The rank's time limit, in seconds.
    target_seconds: float

    @property
    def lap_experience(self) -> float:
        """What one run pays, one-time rank bonuses excluded."""
        return self.completion + sum(count * each for count, each in self.extras)

    @property
    def xp_per_hour(self) -> float:
        """Runs an hour times what a run pays."""
        return self.lap_experience * 3600.0 / (self.target_seconds + RESTART_SECONDS)


@dataclass(frozen=True)
class Trial:
    """One Barracuda trial, at the three ranks it can be run at."""

    #: The Sailing level it opens at. Not boostable, which upstream records
    #: as `NoBoost` on every one of these challenges.
    level: int
    #: Rank name -> what that rank pays and is given, in upstream's own order.
    ranks: dict[str, Rank]


#: Trial name -> its ranks, transcribed from each trial's own reward table.
#:
#: **Every figure is stated on the trial's page** except where a note says
#: otherwise. Lost supplies pay 15 experience each at the Tempor Tantrum and 25
#: at the Jubbly Jive; the trial-specific term is a rum shipment at 19.5 and a
#: sail trim or wind mote at 64.
#:
#: **The Jubbly Jive's Marlin row is where the two pages disagree**, and this
#: takes the counted form on both halves. Its reward table says 1,300 for lost
#: supplies where its own prose says the rank collects 56 boxes, and 25 a box is
#: what its Swordfish and Shark rows both pay - so 1,400 is the figure its own
#: text implies and 1,300 is a stale cell. On the other term the table says 704
#: and `Sailing training` says `9*64` = 576; nothing decides between eleven
#: trims and nine, so this takes the lower, as everywhere else here.
#:
#: **The Gwenith Glide publishes no counts at all** - its table has one `Lost
#: supplies` column and no per-crate figure anywhere - so each rank carries one
#: term holding the stated total. The two pages agree on it exactly.
TRIALS: dict[str, Trial] = {
    "The Tempor Tantrum": Trial(
        level=30,
        ranks={
            "Swordfish": Rank(385.0, ((14, 15.0), (2, 19.5)), 108.0),
            "Shark": Rank(650.0, ((25, 15.0), (4, 19.5)), 171.0),
            "Marlin": Rank(1250.0, ((36, 15.0), (6, 19.5)), 270.0),
        },
    ),
    "The Jubbly Jive": Trial(
        level=55,
        ranks={
            "Swordfish": Rank(1700.0, ((20, 25.0), (3, 64.0)), 123.0),
            "Shark": Rank(3000.0, ((38, 25.0), (5, 64.0)), 180.0),
            "Marlin": Rank(6200.0, ((56, 25.0), (9, 64.0)), 321.0),
        },
    ),
    "The Gwenith Glide": Trial(
        level=72,
        ranks={
            "Swordfish": Rank(3050.0, ((1, 1050.0),), 120.0),
            "Shark": Rank(7250.0, ((1, 2065.0),), 222.0),
            "Marlin": Rank(16050.0, ((1, 3360.0),), 369.0),
        },
    ),
}


def task_name(trial: str, rank: str) -> str:
    """Upstream's own name for one trial at one rank, markup and all.

    **The markup form is the key everywhere**, so this builds it rather than
    stripping it off the export: `training` is keyed by the raw task name, and
    so is `overrides.json`.
    """
    return f"Complete ~|{trial}|~ at {rank} rank"


def rank_of(task: str) -> tuple[str, str] | None:
    """`(trial, rank)` for a Barracuda trial challenge, or `None`.

    Joined on the task name with its markup stripped, which is the same join
    `heuristics._table_rates` makes for the scrape it replaces - so the two
    cannot disagree about which challenge a figure is about.
    """
    plain = strip_task_markup(task)
    for trial, found in TRIALS.items():
        for rank in found.ranks:
            if plain == strip_task_markup(task_name(trial, rank)):
                return trial, rank
    return None


def xp_per_hour(trial: str, rank: str) -> float:
    """A trial's Sailing experience an hour at `rank`, or `0.0` if unknown."""
    found = TRIALS.get(trial)
    if found is None:
        return 0.0
    at_rank = found.ranks.get(rank)
    return at_rank.xp_per_hour if at_rank is not None else 0.0


def methods(
    challenges: Mapping[str, Any], valid: Mapping[str, Any]
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{skill: methods}` for every Barracuda trial rank a map can attempt.

    One point each rather than bands: nothing in the model moves with level.
    A trial is the same course at the same target time whatever the player's
    Sailing is, and the three ranks of one trial all open at the trial's own
    level, so `training_bands` picks the fastest of them from the moment the
    trial opens. That is right in substance - the ranks must be earned in
    order, but a run is minutes and the climb is hours.
    """
    found: list[ComputedMethod] = []
    for task in sorted(valid or {}):
        challenge = challenges.get(task)
        if not isinstance(challenge, dict) or challenge.get("Primary") is not True:
            continue
        named = rank_of(task)
        if named is None:
            continue
        trial, rank = named
        rate = xp_per_hour(trial, rank)
        if rate <= 0:
            continue
        found.append(
            ComputedMethod(
                method=ACTIVITY,
                xp_per_hour=rate,
                # **The trial's level, not the challenge's.** They agree today
                # on all nine, and a test pins that they do - but the level a
                # rate is offered at is a claim about the activity, and this
                # module is where the activity is described.
                level=TRIALS[trial].level,
                match=BARRACUDA_MATCH,
                knob=f"training/{task}/{SKILL}",
            )
        )
    return {SKILL: tuple(found)} if found else {}
