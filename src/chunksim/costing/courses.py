"""Agility courses, derived from a lap rather than read off a guide.

**Two published numbers a course, and their product is the guide's own
figure.** Every course page states what a lap pays - as a per-obstacle table
this parses, or in prose - and how long a lap takes; multiply and you get the
rate `wiki:courses` publishes, within 5.2% on all ten courses that state both
and within 1% on six of them:

    course                       xp/lap  lap s   derived  scraped  ratio
    Canifis Rooftop                 240   43.8    19,726   19,200  1.027
    Seers' Village Rooftop          570   43.8    46,849   45,600  1.027
    Pollnivneach Rooftop          1,016   60.6    60,356   60,000  1.006
    Rellekka Rooftop                920   51.0    64,941   65,000  0.999
    Ardougne Rooftop                889   45.6    70,184   70,000  1.003
    Barbarian Outpost             153.3   32.0    17,246   18,200  0.948
    Wilderness                    571.4   45.0    64,112   66,600  0.963
    Werewolf                        730   38.0    69,158   69,500  0.995
    Dorgesh-Kaan                  2,750  156.0    63,462   63,000  1.007
    Falador Rooftop                 586   60.0    35,160   35,000  1.005

**So this changes almost no number, and that is the point.** The Agility
scrape was checked before any of it was written and found accurate - eleven of
the thirteen courses whose pages state a rate agree with `wiki:courses` within
2.6%, and the two that looked wrong were the guide being *more* right, since
Rellekka's 65,000 is the hard Fremennik Diary figure and Wilderness's 66,600
includes the lap bonus. What the model buys is not accuracy, it is that the
figure is now a *derivation from two facts about the game* rather than
somebody's estimate, so a game update that changes a lap or an obstacle can be
followed rather than waited on.

### The eight courses this does not model

Gnome Stronghold, Draynor, Al Kharid, Varrock, both Shayzien courses and both
Colossal Wyrm courses keep their scraped rate, for two different reasons.

Five simply do not state a lap time. Gnome Stronghold states a *minimum* - "a
lap will take a minimum of 34 seconds" - which is not an average and reads
17% fast against the guide if used as one, so it is left out rather than
quietly treated as one.

**The Colossal Wyrm pair is the one real disagreement and is left alone
deliberately.** Its pages give 633 experience for a basic lap and "about 90
seconds per lap", which is 25,320 an hour against a scraped 44,000 - a factor
of 1.7 that nothing on the page reconciles. A model that disagrees with a
verified guide by that much is a question, not an improvement, and replacing
the guide with it would be trading a checked number for an unchecked one.

### `Canafis`

The export spells it `Canafis Rooftop Course` and the wiki spells it
`Canifis`. The task name is the key here, so this file carries upstream's
spelling; nothing tries to reconcile the two, because there is nothing to
reconcile - they are one place with two spellings and only one of them is a
lookup.

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
    """One course, as its own page states it."""

    #: The export's challenge, which is the key everywhere.
    task: str
    #: The Agility level it opens at, per the export.
    level: int
    #: What one full lap pays, summed over the page's obstacle table.
    experience_per_lap: float
    #: Seconds for a lap, "assuming perfect laps" where the page says so.
    lap_seconds: float
    #: Experience an hour on top of the lapping, where a course pays one. Only
    #: the Wilderness course does: its lap counter pays "up to 18,400 bonus
    #: experience assuming players play for at least an hour".
    bonus_per_hour: float = 0.0


COURSES: tuple[Course, ...] = (
    Course("Access the ~|Barbarian Outpost Agility Course|~", 35, 153.3, 32.0),
    Course("Access the ~|Canafis Rooftop Course|~", 40, 240.0, 43.8),
    Course("Access the ~|Falador Rooftop Course|~", 50, 586.0, 60.0),
    Course("Access the ~|Wilderness Agility Course|~", 52, 571.4, 45.0, 18_400.0),
    Course("Access the ~|Seers' Village Rooftop Course|~", 60, 570.0, 43.8),
    Course("Access the ~|Werewolf Agility Course|~", 60, 730.0, 38.0),
    Course("Access the ~|Dorgesh-Kaan Agility Course|~", 70, 2_750.0, 156.0),
    Course("Access the ~|Pollnivneach Rooftop Course|~", 70, 1_016.0, 60.6),
    Course("Access the ~|Rellekka Rooftop Course|~", 80, 920.0, 51.0),
    Course("Access the ~|Ardougne Rooftop Course|~", 90, 889.0, 45.6),
)

#: The courses left to the scrape, and why. Named rather than merely absent so
#: a reader can tell "nobody has done this one" from "this one was looked at".
UNMODELLED: dict[str, str] = {
    "Access the ~|Gnome Stronghold Agility Course|~": "states a minimum lap, not an average",
    "Access the ~|Draynor Village Rooftop Course|~": "no lap time published",
    "Access the ~|Al Kharid Rooftop Course|~": "no lap time published",
    "Access the ~|Varrock Rooftop Course|~": "no lap time published",
    "Access the ~|Shayzien Basic Course|~": "no lap time published",
    "Access the ~|Shayzien Advanced Course|~": "no lap time published",
    "Access the ~|Colossal Wyrm Basic Course|~": "derives 25,320 against a scraped 44,000",
    "Access the ~|Colossal Wyrm Advanced Course|~": "derives 25,320 against a scraped 44,000",
}


def laps_per_hour(course: Course) -> float:
    """Laps an hour, from the lap time alone."""
    return 3600.0 / course.lap_seconds


def rate_at(course: Course) -> float:
    """Agility experience an hour: the lapping, and any lap-counter bonus.

    No level in it. A course is a fixed lap for a fixed reward, and what a
    level buys is *a better course* - which is why every one of these carries
    its own opening level instead.
    """
    return course.experience_per_lap * laps_per_hour(course) + course.bonus_per_hour


def methods(
    valid: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Agility": (...)}` for whichever courses a map can reach."""
    reachable = valid.get(SKILL) or {}
    bands = tuple(
        ComputedMethod(
            method=_display(course.task),
            xp_per_hour=rate_at(course),
            level=course.level,
            match=CONFIRMED,
            knob=f"training/{course.task}/{SKILL}",
        )
        for course in COURSES
        if course.task in reachable
    )
    return {SKILL: bands} if bands else {}


def _display(task: str) -> str:
    """`Access the ~|Ardougne Rooftop Course|~` -> `Ardougne Rooftop Course`."""
    inner = task.partition("~|")[2].rpartition("|~")[0]
    return inner or task
