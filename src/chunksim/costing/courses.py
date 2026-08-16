"""Agility courses, derived from a lap and a lap time.

**Two published numbers a course, and their product is the guide's own
figure.** `Rooftop Agility Courses` tabulates all nine rooftop courses with
their obstacle count, experience per lap and lap time in ticks; the four
non-rooftop courses modelled here state the same two things in prose on their
own pages. Multiplied out, every one lands on the rate `wiki:courses`
publishes - within 5.2% on all thirteen and within 1% on eight:

    course          xp/lap   lap s   derived  published  ratio
    Draynor            120    43.2    10,000     10,000  1.000
    Al Kharid          216    64.2    12,112     12,000  1.009
    Varrock            270    66.0    14,727     14,000  1.052
    Canifis            240    43.8    19,726     19,700  1.001
    Falador            586    58.2    36,247     35,000  1.036
    Seers' Village     570    43.8    46,849     46,800  1.001
    Pollnivneach       890    60.6    52,871     52,300  1.011
    Rellekka           780    51.0    55,059     55,000  1.001
    Ardougne           889    45.6    70,184     70,000  1.003
    Barbarian Outpost  153.3  32.0    17,246     18,200  0.948
    Gnome Stronghold   110.5  34.0    11,700     10,000  1.170
    Shayzien Basic     153.5  51.0    10,835     10,000  1.084
    Shayzien Advanced  507.5  46.2    39,545     30,000  1.318
    Colossal Wyrm Bas  633    71.4    31,916     44,000  0.725
    Colossal Wyrm Adv  1053.6 86.4    43,900     44,000  0.998
    Wilderness         571.4  45.0    64,112     66,600  0.963
    Werewolf           730    38.0    69,158     69,500  0.995
    Dorgesh-Kaan     2,750   156.0    63,462     63,000  1.007

**That the numbers barely move is the point.** The Agility scrape was checked
before any of this was written and found accurate, so what a model buys here
is not a better answer but a *followable* one: a rate that is two facts about
the game multiplied can be carried through a game update, where somebody's
estimate has to be waited on.

### The base rate is priced, not the diary rate

Three of the rooftop courses pay more once a hard Achievement Diary is done -
Seers' by way of a teleport that shortens the lap, Pollnivneach and Rellekka
by paying more experience for the same lap - and `wiki:courses` quotes the
*diary* figure for all three. This prices the base, which is the conservative
reading and the likelier one on a chunk-restricted map: a hard diary wants
tasks all over its region, which is exactly what such a map does not have.
`diary_experience_per_lap` and `diary_lap_seconds` carry the other half so the
difference is visible rather than lost - it is 46,849 against 58,000 on Seers',
and 55,059 against 65,000 on Rellekka.

### The three rows that do not reproduce the guide, and why that is fine

Gnome Stronghold and both Shayzien courses state a **minimum** lap rather than
an average, and this prices the minimum. The pages themselves show the two
figures are the same lap rather than two measurements - Gnome Stronghold's
reads "a lap will take a minimum of 34 seconds to complete. Therefore the
average experience per hour will be around 10,000, depending on the player's
concentration", which is its own 34 seconds run less carefully. Agility is
about the easiest skill in the game to run tick-perfect, and this project
prices a method done properly everywhere else - `wintertodt` world-hopped,
`tempoross` not cooking, `sepulchre` not looting.

**The Shayzien advanced course is the interesting one**, because its gap is
not concentration and the page says what it is: "players can expect to stop
failing the obstacles that make up the advanced course at around level 64
Agility". So its 30,000 is an average over a stretch where you fail and its
39,545 is what the lap gives once you stop, and pricing either alone would be
wrong at one end. It is the one course here carried as **two bands** - the
stated average from 45, the lap-derived rate from 64 - which is what having
both numbers is for.

### The Colossal Wyrm pair, and a guide that had gone stale

These two were left to the guide for a while on what looked like an
irreconcilable 1.7x disagreement, and the disagreement was real but the cause
was not the model. **Both courses were rebalanced on 12 August 2026** - "the
duration of the basic course has been increased by ~25%", "the advanced course
by ~40%", and "increased experience ... on both courses" - and `wiki:courses`
still carried the figure from before it.

The page reconciles every number once the current ones are read. It gives 633
experience for a basic lap and 1,053.6 for an advanced one, laps of 1:07.80 and
1:22.80, "3.6 seconds of downtime between laps", and its own rates of ~31,000
and ~43,000. Those come out at 31,916 and 43,900. And the same page states the
*pre-buff* laps, 54.0 and 58.8 seconds - at which the basic course paid
633 / 54.0s = 42,200 an hour, which is where the scraped 44,000 came from and
why it was given to both courses.

So the guide is not wrong about a course, it is right about a course that no
longer exists. The correction is real: **the basic course was priced 1.38x
too fast**, at the advanced course's old figure.

### `Canafis`

The export spells it `Canafis Rooftop Course` and the wiki spells it
`Canifis`. The task name is the key, so this file carries upstream's spelling;
there is nothing to reconcile, only one place with two spellings of which one
happens to be a lookup.

Pure: nothing but the valid set comes in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from chunksim.costing.gathering import CONFIRMED
from chunksim.costing.heuristics import ComputedMethod

SKILL = "Agility"


@dataclass(frozen=True)
class Course:
    """One course, as its own row states it."""

    #: The export's challenge, which is the key everywhere.
    task: str
    #: The Agility level it opens at, per the export.
    level: int
    #: What one full lap pays.
    experience_per_lap: float
    #: Seconds for a lap, "including running back to the first obstacle".
    lap_seconds: float
    #: Experience an hour on top of the lapping. Only the Wilderness course
    #: pays one: its lap counter is worth "up to 18,400 bonus experience
    #: assuming players play for at least an hour".
    bonus_per_hour: float = 0.0
    #: What a lap pays with the relevant hard diary done, where that differs.
    #: Carried, not spent - see the module docstring.
    diary_experience_per_lap: float | None = None
    #: The lap time with that diary, where the diary shortens the lap rather
    #: than enriching it. Seers' Village is the only one.
    diary_lap_seconds: float | None = None
    #: What a course pays *while you are still failing it*, where the page
    #: states both that and the level at which failing stops. The Shayzien
    #: advanced course is the only one that does: 30,000 an hour against the
    #: 39,545 its lap and lap time give, and "players can expect to stop
    #: failing the obstacles that make up the advanced course at around level
    #: 64 Agility". Priced as two bands rather than as one average, which is
    #: what the two figures are for.
    failing_rate: float | None = None
    #: The level the failing stops at, which is where `failing_rate` gives way
    #: to the lap-derived one.
    no_fail_level: int | None = None
    #: Seconds between laps that the lap time does not already contain. Only
    #: the two Colossal Wyrm courses state one - "including 3.6 seconds of
    #: downtime between laps" - and stating it separately is what keeps
    #: `lap_seconds` meaning the same thing on every row.
    downtime_seconds: float = 0.0


COURSES: tuple[Course, ...] = (
    # **The one lap time here that is a minimum rather than an average**, and
    # taken as one deliberately. The page says "a lap will take a minimum of
    # 34 seconds to complete. Therefore the average experience per hour will
    # be around 10,000, depending on the player's concentration" - so the
    # guide's 10,000 is the *unconcentrated* reading of the same 34 seconds,
    # not a different measurement. Seven simple obstacles and a completion
    # bonus is about the easiest course in the game to run tick-perfect, so
    # this prices the minimum and comes out at 11,700, which is 1.17x the
    # guide and the only row here that does not reproduce it. That is the
    # claim being made: not that the guide is wrong, but that its figure is
    # the same lap run less carefully.
    Course("Access the ~|Gnome Stronghold Agility Course|~", 1, 110.5, 34.0),
    Course("Access the ~|Draynor Village Rooftop Course|~", 1, 120.0, 43.2),
    # Both Shayzien courses state their own lap experience and a minimum lap
    # in one sentence: "yields 153.5 Agility experience for completion. The
    # basic course takes a minimum of 51.0 seconds to complete."
    Course("Access the ~|Shayzien Basic Course|~", 1, 153.5, 51.0),
    Course("Access the ~|Al Kharid Rooftop Course|~", 20, 216.0, 64.2),
    # 108-110 ticks; the slower end, which is the reading without the
    # diagonal-running trick the table's footnote describes.
    Course("Access the ~|Varrock Rooftop Course|~", 30, 270.0, 66.0),
    Course("Access the ~|Barbarian Outpost Agility Course|~", 35, 153.3, 32.0),
    Course("Access the ~|Canafis Rooftop Course|~", 40, 240.0, 43.8),
    # The advanced course adds the level its failures stop at, which is what
    # makes it two bands instead of one.
    Course(
        "Access the ~|Shayzien Advanced Course|~", 45, 507.5, 46.2,
        failing_rate=30_000.0, no_fail_level=64,
    ),
    Course("Access the ~|Falador Rooftop Course|~", 50, 586.0, 58.2),
    # **Both Colossal Wyrm courses were rebalanced on 12 August 2026** and the
    # guide had not caught up - see the module docstring. "Players never fail
    # obstacles on either course", so neither needs a failing band.
    Course(
        "Access the ~|Colossal Wyrm Basic Course|~", 50, 633.0, 67.8,
        downtime_seconds=3.6,
    ),
    Course("Access the ~|Wilderness Agility Course|~", 52, 571.4, 45.0, 18_400.0),
    Course(
        "Access the ~|Seers' Village Rooftop Course|~", 60, 570.0, 43.8,
        diary_experience_per_lap=570.0, diary_lap_seconds=36.0,
    ),
    Course("Access the ~|Werewolf Agility Course|~", 60, 730.0, 38.0),
    Course(
        "Access the ~|Colossal Wyrm Advanced Course|~", 62, 1_053.6, 82.8,
        downtime_seconds=3.6,
    ),
    Course("Access the ~|Dorgesh-Kaan Agility Course|~", 70, 2_750.0, 156.0),
    Course(
        "Access the ~|Pollnivneach Rooftop Course|~", 70, 890.0, 60.6,
        diary_experience_per_lap=1_016.0,
    ),
    Course(
        "Access the ~|Rellekka Rooftop Course|~", 80, 780.0, 51.0,
        diary_experience_per_lap=920.0,
    ),
    Course("Access the ~|Ardougne Rooftop Course|~", 90, 889.0, 45.6),
)

#: The courses left to the guide, and why. Named rather than merely absent, so
#: a reader can tell "nobody has looked at this" from "this was looked at".
#: Courses left to the guide. **Empty, and worth keeping as a place to say
#: so**: every one of the eighteen the export offers is now derived from a lap
#: and a lap time, and a course that stops being derivable should be named
#: here with the reason rather than quietly falling back.
UNMODELLED: dict[str, str] = {}


def laps_per_hour(course: Course, *, diary: bool = False) -> float:
    """Laps an hour, from the lap time and any stated downtime."""
    seconds = course.lap_seconds
    if diary and course.diary_lap_seconds is not None:
        seconds = course.diary_lap_seconds
    return 3600.0 / (seconds + course.downtime_seconds)


def rate_at(course: Course, *, diary: bool = False) -> float:
    """Agility experience an hour: the lapping, and any lap-counter bonus.

    No level in it. A course is a fixed lap for a fixed reward, and what a
    level buys is *a better course* - which is why each carries its own
    opening level instead.
    """
    paid = course.experience_per_lap
    if diary and course.diary_experience_per_lap is not None:
        paid = course.diary_experience_per_lap
    return paid * laps_per_hour(course, diary=diary) + course.bonus_per_hour


def bands_for(course: Course) -> tuple[tuple[int, float], ...]:
    """`(level, experience an hour)` for a course, one point or two.

    Two where the page states both what the course pays while you are still
    failing it and the level that stops - see `Course.failing_rate`. One
    everywhere else, because a course is a fixed lap for a fixed reward.
    """
    full = rate_at(course)
    if course.failing_rate is None or course.no_fail_level is None:
        return ((course.level, full),)
    return ((course.level, course.failing_rate), (course.no_fail_level, full))


def methods(
    valid: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Agility": (...)}` for whichever courses a map can reach."""
    reachable = valid.get(SKILL) or {}
    bands = tuple(
        ComputedMethod(
            method=_display(course.task),
            xp_per_hour=paid,
            level=level,
            match=CONFIRMED,
            knob=f"training/{course.task}/{SKILL}",
        )
        for course in COURSES
        if course.task in reachable
        for level, paid in bands_for(course)
    )
    return {SKILL: bands} if bands else {}


def _display(task: str) -> str:
    """`Access the ~|Ardougne Rooftop Course|~` -> `Ardougne Rooftop Course`."""
    inner = task.partition("~|")[2].rpartition("|~")[0]
    return inner or task
