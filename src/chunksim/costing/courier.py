"""Courier tasks: a maximum-ratio cycle over the ports a map can sail between.

**The one Sailing method whose rate is a property of the map's shape rather
than of an action.** A courier task is a crate carried from one port's ledger
table to another's, and `remote/courier.py` scrapes all 432 of them with the
coordinates that place their thirty ports. What this module does with them is
decide which *circuit* of ports pays best, gate it on what the map holds, and
turn that into an hourly figure.

### The experience law, which is measured rather than assumed

`Courier tasks` says only that experience is "based on distance travelled",
and that a task whose cargo is somewhere other than its notice board "will give
double the experience" - the round trip the board implies rather than the one
leg you sail. Both halves check out against the table:

- The **doubling is exact.** Every port pair carrying both shapes pays the
  displaced one exactly twice the plain one, to the rounding.
- **Within a level band, base experience is proportional to sea distance.**
  Regressed against the BFS hop count below, the median within-band `r` is
  **0.978** across the twenty bands with six or more tasks. Against
  straight-line distance it is 0.60 - routing round land is what makes it fit,
  which is the evidence that the "distance travelled" the wiki means is the
  sailing distance and not the map's.

So a task's experience already carries its distance, and the only thing left to
model is time.

### The route optimisation reduces to a maximum, and that is the finding

This looks like a travelling-salesman problem and is not one, for two reasons
that are both properties of the game rather than simplifications:

- **The notice board is always either the cargo location or the destination** -
  all 432 rows, no exceptions - so taking a task never costs a detour. Whichever
  shape it is, its board sits on the leg you were going to sail anyway, and a
  circuit is not needed to reach the boards that supply it.
- **Repositioning is free.** `Boat#Teleportation` summons your boat to any
  dock, which is why the optimisation guide calls a lesser teleport focus
  "essential". So a leg can be run again without sailing back.

A cycle's experience per second is a weighted mean of its legs', so it can
never beat the best leg in it; and with a free return, the best leg is
attainable on its own. `best_leg` is therefore the exact answer to "which route
pays best", not an approximation of one - and a cycle solver over the same legs
would return a strictly worse number for a route the player need not take.

**What the circuits in the guide are for is supply, which is not geometry.**
No leg carries more than one displaced task - 271 distinct legs, at most three
tasks on any and at most one of those displaced - so a board cannot keep
offering the same delivery, and the guide's answer is task storing and counting
board resets rather than a better route. That is the gap between this model and
a real player, and it is stated rather than fitted: the model prices somebody
who always has the task its best leg wants.

### The sea, and what "the chunks in between" means here

A port is a chunk, and sailing between two of them needs the water in between.
`navigable_chunks` is upstream's own `rollingChunks['ocean']` plus every chunk
declaring a `W` section, and `sea_hops` is a breadth-first search over **grid
adjacency** between those chunks, restricted to the ones this map has unlocked.

**Grid adjacency rather than the `sections` branch**, which is the one thing
here that is not a port of upstream. That branch is walking connectivity: taken
as a sailing graph it breaks the water into 56 components and cannot get a boat
from Port Sarim to Lunar Isle at all. Grid adjacency over the same chunks is one
component of 799 containing all twenty-two of upstream's ports, which is what
open water should look like. Upstream does not model the sea between ports -
`Complete ~|courier tasks|~` is gated on `PortTaskLocations[+]x2` and nothing
else - so requiring the crossing is stricter than upstream, deliberately: a
chunk map that owns two ports and none of the water between them cannot sail.

### The ports, from two sources that agree

A **notice board** port is upstream's own `Take ~|port tasks|~ from X`
challenge, which carries the chunk, the Sailing level and any quest, so its
validity is the whole gate. Upstream has twenty-two of the wiki's twenty-three.
A **ledger-only** port has no board and no upstream challenge - seven of them,
Hosidius and Entrana among others - and is reachable when its chunk is
unlocked. Where both sources speak they agree: the module's coordinate reduces
to upstream's chunk on 17 of 22, and the five that differ are ports straddling
a chunk boundary where upstream picked the board's side.

### The two constants, and what they cost

`SECONDS_PER_HOP` and `TASK_SECONDS` are **fitted, not published**. Nothing
anywhere states how long a chunk of open water takes or what a crate costs to
collect and deposit, and the only quantitative anchor is the optimisation
guide's "around 200k/hr" for a good route - one number against two unknowns.
They are pinned by requiring that the ceiling map at level 99 reads
`PUBLISHED_XP_PER_HOUR`, and that the cycle the model then picks is one the
guide itself names. That second condition is a check on a *ranking* rather than
a number, which is the most this evidence supports.

So **every band is a `GUESS`** - `costing/tempoross.py`'s rule, twice over -
and the figure should be read as "how much worse is this map's port set than a
complete one", which the model answers well, rather than as a clock.

**What is deliberately not modelled**: the guide is almost entirely about board
management - task storing, counting board resets, cancelling through the
captain's log - and its 200k assumes teleport-focus facilities on several
boats, optimal crew, keg drinks and portal tech. None of that is geometry and
none of it is here. The model prices a player who always has the tasks its
cycle wants, which is the ceiling that board management chases.

Pure: the valid set, the unlocked chunks and the scraped table, all handed in.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from chunksim.costing.gathering import GUESS
from chunksim.costing.heuristics import ComputedMethod

SKILL = "Sailing"

#: Upstream's own primary challenge for the activity.
TASK = "Complete ~|courier tasks|~"

#: What a band calls it.
METHOD = "courier tasks"

#: Upstream's per-port challenge, whose validity is the board gate.
BOARD_TASK = "Take ~|port tasks|~ from {port}"

#: How many tasks can be held at once, from `Courier tasks`' own table.
#: **Published**, and the one part of the stacking that is not a guess.
TASK_SLOTS: tuple[tuple[int, int], ...] = ((1, 1), (7, 2), (28, 3), (56, 4), (84, 5))

#: The optimisation guide's figure for a good route on a complete map:
#: "these tasks give 200k/h+ if not around that mark". The two constants below
#: are fitted to reproduce it at the ceiling.
PUBLISHED_XP_PER_HOUR = 200_000.0

#: Seconds to sail one chunk of open water. **Fitted** - see the module
#: docstring.
SECONDS_PER_HOP = 12.0

#: Seconds a task costs beyond the sailing: taking it, collecting its crates,
#: loading, unloading and depositing. **Fitted**, and the term that stops the
#: model preferring one-hop legs between adjacent ports.
TASK_SECONDS = 26.1

SECONDS_PER_HOUR = 3600.0


def slots_at(level: int) -> int:
    """How many tasks can be held at `level`, per the published table."""
    return max(slots for gate, slots in TASK_SLOTS if level >= gate)


@dataclass(frozen=True)
class Port:
    """One port, as the scrape describes it."""

    name: str
    chunk: str
    #: Whether it carries a notice board. A ledger-only port can be a task's
    #: cargo or destination but never offers one.
    board: bool


@dataclass(frozen=True)
class Task:
    """One delivery."""

    level: int
    experience: int
    notice_board: str
    cargo: str
    destination: str
    crates: int

    @property
    def displaced(self) -> bool:
        """The board is the destination rather than the cargo - twice paid."""
        return self.notice_board != self.cargo


def tasks_from(blob: Mapping[str, object]) -> tuple[Task, ...]:
    """The scraped table as `Task`s."""
    rows = blob.get("tasks")
    if not isinstance(rows, Sequence):
        return ()
    found: list[Task] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        found.append(
            Task(
                level=int(row["level"]),
                experience=int(row["experience"]),
                notice_board=str(row["notice_board"]),
                cargo=str(row["cargo"]),
                destination=str(row["destination"]),
                crates=int(row.get("crates", 1)),
            )
        )
    return tuple(found)


def ports_from(blob: Mapping[str, object]) -> dict[str, Port]:
    """The scraped port table."""
    rows = blob.get("ports")
    if not isinstance(rows, Mapping):
        return {}
    return {
        name: Port(name=name, chunk=str(row["chunk"]), board=bool(row.get("board")))
        for name, row in rows.items()
        if isinstance(row, Mapping)
    }


def navigable_chunks(
    ocean: Iterable[str], sections: Mapping[str, Mapping[str, object]]
) -> frozenset[str]:
    """Every chunk a boat can be in: upstream's ocean group plus any chunk
    declaring a `W` section, which is how a coastal chunk carries its water."""
    found = set(ocean)
    for chunk, entry in sections.items():
        if any(str(key).startswith("W") for key in entry):
            found.add(chunk)
    return frozenset(found)


def _grid_neighbours(chunk: str) -> tuple[str, str, str, str]:
    """The four orthogonally adjacent chunk ids. A chunk id is a region id, so
    north/south is +/-256 and east/west is +/-1."""
    n = int(chunk)
    return (str(n - 256), str(n + 256), str(n - 1), str(n + 1))


def sea_hops(
    source: str, navigable: frozenset[str], held: frozenset[str]
) -> dict[str, int]:
    """Chunks reachable by sea from `source`, and how many crossings each takes.

    `held` is the map's unlocked chunk set: a boat cannot cross water this map
    does not own, which is what makes a port pair unusable rather than merely
    distant.
    """
    if source not in navigable or source not in held:
        return {}
    seen = {source: 0}
    queue = deque([source])
    while queue:
        chunk = queue.popleft()
        for other in _grid_neighbours(chunk):
            if other in seen or other not in navigable or other not in held:
                continue
            seen[other] = seen[chunk] + 1
            queue.append(other)
    return seen


@dataclass(frozen=True)
class Leg:
    """One sailing leg, with the tasks a voyage along it can carry."""

    origin: str
    destination: str
    hops: int
    experience: int
    tasks: int

    @property
    def seconds(self) -> float:
        return self.hops * SECONDS_PER_HOP + self.tasks * TASK_SECONDS


def legs_for(
    tasks: Iterable[Task],
    ports: Mapping[str, Port],
    reachable: frozenset[str],
    boards: frozenset[str],
    distances: Mapping[str, Mapping[str, int]],
    level: int,
) -> tuple[Leg, ...]:
    """Every sailing leg this map can run, with its best cargo.

    A task counts when its level is met, its board is a reachable board port,
    both its ends are reachable ports, and there is a sea route between them
    through chunks the map holds.
    """
    slots = slots_at(level)
    grouped: dict[tuple[str, str], list[int]] = {}
    for task in tasks:
        if task.level > level:
            continue
        if task.notice_board not in boards:
            continue
        if task.cargo not in reachable or task.destination not in reachable:
            continue
        hops = distances.get(ports[task.cargo].chunk, {}).get(
            ports[task.destination].chunk
        )
        if hops is None or hops <= 0:
            continue
        grouped.setdefault((task.cargo, task.destination), []).append(task.experience)
    found: list[Leg] = []
    for (origin, destination), payouts in grouped.items():
        best = sorted(payouts, reverse=True)[:slots]
        hops = distances[ports[origin].chunk][ports[destination].chunk]
        found.append(
            Leg(
                origin=origin,
                destination=destination,
                hops=hops,
                experience=sum(best),
                tasks=len(best),
            )
        )
    return tuple(found)


def best_leg(legs: Sequence[Leg]) -> Leg | None:
    """The leg paying the most experience a second, or `None` for no route.

    The whole optimisation - see the module docstring for why a circuit cannot
    beat this and does not need to.
    """
    priced = [leg for leg in legs if leg.seconds > 0]
    if not priced:
        return None
    return max(priced, key=lambda leg: leg.experience / leg.seconds)


def rate_of(leg: Leg) -> float:
    """`leg` as experience an hour."""
    return leg.experience * SECONDS_PER_HOUR / leg.seconds if leg.seconds > 0 else 0.0


def reachable_ports(
    ports: Mapping[str, Port],
    valid: Mapping[str, Mapping[str, object]],
    held: frozenset[str],
) -> tuple[frozenset[str], frozenset[str]]:
    """`(every reachable port, those with a usable notice board)`.

    **A board is upstream's gate and nothing else.** `Take ~|port tasks|~ from
    X` carries the chunk, the Sailing level and any quest, so its validity is
    the whole question and no level is compared here - `costing/wintertodt.py`'s
    reason. A ledger-only port has no such challenge and is reachable when its
    chunk is unlocked, which is the most the export says about it.
    """
    sailing = valid.get(SKILL) or {}
    usable: set[str] = set()
    boards: set[str] = set()
    for name, port in ports.items():
        if port.board and BOARD_TASK.format(port=name) in sailing:
            usable.add(name)
            boards.add(name)
        elif port.chunk in held:
            usable.add(name)
    return frozenset(usable), frozenset(boards)


def methods(
    valid: Mapping[str, Mapping[str, object]],
    held: Mapping[str, bool],
    ocean: Iterable[str],
    sections: Mapping[str, Mapping[str, object]],
    blob: Mapping[str, object],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Sailing": bands}`, one per level where the best route improves.

    Nothing at all unless upstream's own challenge is valid, which already
    asserts `PortTaskLocations[+]x2` - two ports with boards. This adds the
    crossing between them, which upstream does not model.
    """
    if TASK not in (valid.get(SKILL) or {}):
        return {}
    tasks = tasks_from(blob)
    ports = ports_from(blob)
    if not tasks or not ports:
        return {}
    owned = frozenset(chunk for chunk, on in held.items() if on)
    usable, boards = reachable_ports(ports, valid, owned)
    if len(boards) < 2:
        return {}
    navigable = navigable_chunks(ocean, sections)
    distances = {
        ports[name].chunk: sea_hops(ports[name].chunk, navigable, owned)
        for name in usable
    }
    bands: list[ComputedMethod] = []
    best = 0.0
    # **A band per level where the answer moves**, which is where a port opens,
    # a task tier opens or a slot is won - all of which show up as a change in
    # the best leg, so the levels are read off the tasks rather than listed.
    for level in sorted({task.level for task in tasks} | {slot for slot, _ in TASK_SLOTS}):
        leg = best_leg(legs_for(tasks, ports, usable, boards, distances, level))
        if leg is None:
            continue
        rate = rate_of(leg)
        if rate <= best + 1.0:
            continue
        best = rate
        bands.append(
            ComputedMethod(
                method=f"{METHOD} ({leg.origin} to {leg.destination})",
                xp_per_hour=rate,
                level=level,
                match=GUESS,
                knob=f"training/{TASK}/{SKILL}",
            )
        )
    return {SKILL: tuple(bands)} if bands else {}
