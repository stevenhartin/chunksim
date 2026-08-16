"""Pyramid Plunder: a five-minute game, priced from what one game holds.

**Everything about this activity is published except one number, and the one
number turns out not to matter.** That is unusual enough to be the reason this
module exists rather than a scraped rate for three of the eight rooms and
nothing at all for the other five.

What the wiki states outright:

- experience per urn, per chest and per door, for each of the eight rooms, and
  the Strength experience a sarcophagus pays;
- "Every room contains exactly 13 lootable urns (bar the third room, which
  contains one fewer)", one Grand Gold Chest and one sarcophagus;
- four tomb doors a room, one of which leads onward;
- 10 Thieving experience for disarming the spear trap;
- "a timer of five minutes will commence";
- rooms opening at Thieving 21, 31, 41, 51, 61, 71, 81 and 91.

And four `{{Skilling success chart}}`s, all already scraped by
`chunksim gather-tables`: the urn, the chest, the tomb door, and the
sarcophagus - the last against **Strength** level and with its own curve per
room, which is the only chart in the project that gets *harder* the further in
you go.

**The strategy priced is the wiki's own**, not one chosen here: "the golden
chests in room 4 and beyond" and "all urns in the second to last and last
possible room". Sarcophagi are excluded from the Thieving side because they
pay no Thieving experience at all.

### The two unknowns, and why neither needed a guess

*Seconds per action.* The plan needs 72 actions at level 91 and 68 at 71, so
in 300 seconds it wants 4.2 seconds each. Anything **faster** than about seven
ticks finishes the plan, so the answer is flat over the whole plausible range
and this module never picks a cadence. The number nobody published is the one
the rate does not depend on.

*Between-game overhead.* The rate is `experience per game * 3600 / (300 +
overhead)`, and the overhead is the only fitted quantity here. It is fitted on
two rows and checked on a third:

    room 6 implies 35.4s      fitted:  35.1s
    room 7 implies 34.7s
    room 8 implies 21.2s      held out

Rooms 6 and 7 land within 2% of each other without being made to, and with
`OVERHEAD_SECONDS` the model reads 1.00x, 1.00x and **0.96x** against the
three published rows. One parameter, two rows fitted, the third reproduced -
which is why the rates here are `CONFIRMED` rather than `INFERRED`. Thirty-five
seconds is a teleport, a word with the mummy and the occasional resupply; it
moves the answer by a tenth and an efficient player moves it back.

Room 8's residual is not noise and the page names its cause: "a Pharaoh's
sceptre will nullify the time spent entering the pyramid", and a sceptre is
what farming room 8 is *for*. A player deep enough to run it has less overhead
than one who is not, which is exactly the 21 seconds that row implies.

### Strength, and the honest thing about it

A sarcophagus pays Strength and nothing else, and the wiki is explicit that
the Thieving-optimal route skips them: they "grant no Thieving experience and
take some time to open". So the two rates here are **not simultaneously
achievable at their full value** - a run that maximises Thieving opens no
sarcophagi and pays no Strength at all.

What `strength_rate` gives is the ceiling for a player who opens the one
sarcophagus in every room they pass through anyway, and it is small: 9,884/hr
at 99 in both skills, against combat's hundreds of thousands. It will never
open a band, and that is the answer - it is here so the activity is described
completely, not because anybody should train Strength this way.

**And it is a ceiling in a second sense: the Strength level decides *whether*
a sarcophagus pays, not how much.** A sarcophagus always grants its experience
when it opens, so a low level buys retries rather than a smaller reward - and
the retries cost time this module does not price, because the timer is not
modelled as a constraint at all. Measured, that matters: at 99 Strength the
eight sarcophagi take about ten attempts between them and at 40 they take
twenty-seven, on top of a plan that already wants seventy-two. So a
low-Strength player really does pay for them in Thieving experience, and the
figure here does not say so. The level shows up only where the chart clamps to
no chance at all, which is rooms 7 and 8 at Strength 1.

There is no Strength *task* in the export for any of this, which is why it
reaches `costing/training.py` through `Heuristics.computed` the way combat and
Prayer do, rather than through a challenge.

Pure: every level comes in as an argument.
"""

from __future__ import annotations

from typing import Mapping

from chunksim.costing.gathering import CONFIRMED, success_chance
from chunksim.costing.heuristics import ComputedMethod

#: Room -> `(Thieving level, urn xp, chest xp, door xp, sarcophagus Strength
#: xp)`, straight off the wiki's experience table. Room 8's doors are `0`
#: because there are none to pick: "If a player tries to pick the doors in the
#: final room, they will instead cause the player to exit the minigame."
ROOMS: dict[int, tuple[int, float, float, float, float]] = {
    1: (21, 60.0, 40.0, 40.0, 20.0),
    2: (31, 90.0, 60.0, 60.0, 30.0),
    3: (41, 150.0, 100.0, 100.0, 50.0),
    4: (51, 215.0, 140.0, 140.0, 70.0),
    5: (61, 300.0, 200.0, 200.0, 100.0),
    6: (71, 450.0, 300.0, 300.0, 150.0),
    7: (81, 675.0, 450.0, 450.0, 225.0),
    8: (91, 825.0, 550.0, 0.0, 275.0),
}

#: The export's own name for each room, which is what a rate is written to.
TASKS: dict[int, str] = {
    1: "Access the first room of ~|Pyramid Plunder|~",
    2: "Access the second room of ~|Pyramid Plunder|~",
    3: "Access the third room of ~|Pyramid Plunder|~",
    4: "Access the fourth room of ~|Pyramid Plunder|~",
    5: "Access the fifth room of ~|Pyramid Plunder|~",
    6: "Access the sixth room of ~|Pyramid Plunder|~",
    7: "Access the seventh room of ~|Pyramid Plunder|~",
    8: "Access the eighth room of ~|Pyramid Plunder|~",
}

#: "Every room contains exactly 13 lootable urns (bar the third room, which
#: contains one fewer)."
def urns_in(room: int) -> int:
    return 12 if room == 3 else 13

#: `(low, high)` for the three Thieving charts. The door pair is the *normal*
#: series rather than the lockpick one, because "experience for opening doors
#: is halved when using a lockpick" - a better chance bought with half the
#: numerator is not obviously the faster method, and the plain one is the
#: conservative reading.
URN_CURVE = (100.0, 180.0)
CHEST_CURVE = (130.0, 220.0)
DOOR_CURVE = (130.0, 220.0)

#: Room -> the sarcophagus's `(low, high)`, against **Strength**. The only
#: chart here that gets harder deeper in - room 1 opens at 59 and room 8 at
#: -11, which clamps to no chance at all for a low-level player.
SARCOPHAGUS_CURVES: dict[int, tuple[float, float]] = {
    1: (59.0, 249.0),
    2: (49.0, 239.0),
    3: (39.0, 229.0),
    4: (29.0, 219.0),
    5: (19.0, 209.0),
    6: (9.0, 199.0),
    7: (-1.0, 189.0),
    8: (-11.0, 179.0),
}

#: Disarming the spear trap, once a room.
TRAP_EXPERIENCE = 10.0

#: "The player will appear in the first room, and a timer of five minutes will
#: commence."
GAME_SECONDS = 300.0

#: **The one fitted number in this module.** See the module docstring: fitted
#: on rooms 6 and 7, which independently imply 35.4 and 34.7, and checked
#: against room 8.
OVERHEAD_SECONDS = 35.1

#: Doors opened before the right one is found. Four a room, one correct, so
#: the number you open is uniform on 1-4 and averages this. You are paid for
#: the wrong ones too - "players can fail in opening the doors, although no
#: consequences will occur if they fail" is about *failing*, not about opening
#: a dead end.
DOORS_OPENED = 2.5

#: The first room the chests are worth looting, per the wiki's strategy: "the
#: golden chests in room 4 and beyond. With low Thieving, it is advisable to
#: also search chests in earlier rooms."
CHEST_FROM_ROOM = 4

#: How many rooms' urns are looted: "all urns in the second to last and last
#: possible room".
URN_ROOMS = 2


def top_room(level: int) -> int:
    """The deepest room `level` can reach, or `0` below 21 Thieving."""
    reached = [room for room, entry in ROOMS.items() if level >= entry[0]]
    return max(reached) if reached else 0


def thieving_per_game(level: int) -> float:
    """Thieving experience from one five-minute game at `level`.

    The timer is not modelled as a constraint - see the module docstring: the
    plan fits inside 300 seconds for any cadence up to about seven ticks, so
    what one game holds is what the strategy names rather than what the clock
    allows.
    """
    top = top_room(level)
    if top < 1:
        return 0.0
    chest_chance = success_chance(level, *CHEST_CURVE)
    paid = 0.0
    for room in range(1, top + 1):
        opens, urn_xp, chest_xp, door_xp, _strength = ROOMS[room]
        paid += TRAP_EXPERIENCE
        if room < top:
            paid += DOORS_OPENED * door_xp
        if room >= CHEST_FROM_ROOM or top < CHEST_FROM_ROOM:
            # "No experience is gained from the chest if a Scarab swarm is
            # found", so the chest pays its experience only when it opens
            # cleanly - the artefact arrives either way and is not priced here.
            paid += chest_xp * chest_chance
        if room > top - URN_ROOMS:
            paid += urns_in(room) * urn_xp
    return paid


def strength_per_game(thieving_level: int, strength_level: int) -> float:
    """Strength experience from the sarcophagi of every room passed through.

    Not simultaneously achievable with `thieving_per_game` at full value - see
    the module docstring. A sarcophagus always pays when it opens, so the
    chance costs time rather than experience and does not appear here.
    """
    top = top_room(thieving_level)
    if top < 1:
        return 0.0
    return sum(
        ROOMS[room][4]
        for room in range(1, top + 1)
        if success_chance(strength_level, *SARCOPHAGUS_CURVES[room]) > 0.0
    )


def games_per_hour() -> float:
    """How many five-minute games an hour holds, overhead included."""
    return 3600.0 / (GAME_SECONDS + OVERHEAD_SECONDS)


def thieving_rate(level: int) -> float:
    """Thieving experience an hour at `level`."""
    return thieving_per_game(level) * games_per_hour()


def strength_rate(thieving_level: int, strength_level: int) -> float:
    """Strength experience an hour, for a player who opens the sarcophagi."""
    return strength_per_game(thieving_level, strength_level) * games_per_hour()


def methods(
    valid: Mapping[str, Mapping[str, object]],
    strength_level: int = 1,
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{skill: (...)}` for whichever rooms a map can reach.

    One Thieving band per room, opening where that room does, because the rate
    steps every ten levels as a room unlocks and that is the shape the band
    walk wants. Strength gets a single series over the same rooms.
    """
    thieving = valid.get("Thieving") or {}
    reached = [room for room, task in TASKS.items() if task in thieving]
    if not reached:
        return {}
    found: dict[str, tuple[ComputedMethod, ...]] = {}
    bands = tuple(
        ComputedMethod(
            method=f"Pyramid Plunder (room {room})",
            xp_per_hour=thieving_rate(ROOMS[room][0]),
            level=ROOMS[room][0],
            match=CONFIRMED,
            knob=f"training/{TASKS[room]}/Thieving",
        )
        for room in sorted(reached)
        if thieving_rate(ROOMS[room][0]) > 0
    )
    if bands:
        found["Thieving"] = bands
    deepest = max(reached)
    paid = strength_rate(ROOMS[deepest][0], strength_level)
    if paid > 0:
        # **No task to hang this on**, so no knob either: the export models no
        # Strength training for the minigame and `overrides.json` has nothing
        # it could name.
        found["Strength"] = (
            ComputedMethod(
                method="Pyramid Plunder sarcophagi",
                xp_per_hour=paid,
                level=None,
                match=CONFIRMED,
            ),
        )
    return found
