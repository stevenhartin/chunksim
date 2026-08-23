"""The wiki's courier task table, and the coordinates that place its ports.

**Two pages, and the second is the one that makes the first usable.** `Courier
tasks` lists every delivery as a `{{CourierTaskLine}}` - a level, an
experience, a notice board, a cargo location, a destination and a crate count -
and names its ports in prose. `Module:CourierTaskLine` carries the tables that
turn those names into places: `ledgerTableLocations` for all thirty ports and
`noticeBoardLocations` for the twenty-three that have a board.

Reading the module rather than hand-writing a port table is what keeps this a
scrape. Upstream states a chunk for twenty-two ports and nothing for the other
eight, and the wiki's coordinate reduces to upstream's chunk on **17 of the 22**
- the five that differ are ports straddling a chunk boundary, where upstream
picked the board's chunk and the module's ledger sits one chunk over. So the two
sources agree wherever they can, and the module fills in what upstream lacks.

**The notice board is always the cargo location or the destination**, on all 439
rows, which is what makes a task's usability a property of one sailing leg
rather than of a route. `costing/courier.py` is the consumer and its docstring
carries the model; this module only reads.

Seven rows state no experience - deliveries whose figure the wiki has not filled
in - and are dropped here rather than downstream, since a task with no payout
cannot enter a rate either way.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping

#: The page carrying the task table.
TASKS_PAGE = "Courier tasks"

#: The page carrying both coordinate tables.
LOCATIONS_PAGE = "Module:CourierTaskLine"

_LINE = re.compile(r"\{\{CourierTaskLine\|([^}]*)\}\}")
#: **The quote character has to be back-referenced.** Two port names carry an
#: apostrophe, so the module writes `["Land's End"]` and `["Void Knights'
#: Outpost"]` in double quotes; a character class matching either quote ends
#: the name at the apostrophe and silently loses both ports.
_COORD = re.compile(r"""\[(['"])(.+?)\1\]\s*=\s*\{\s*(\d+)\s*,\s*(\d+)\s*\}""")


@dataclass(frozen=True)
class CourierTask:
    """One row of the wiki's table."""

    level: int
    experience: int
    notice_board: str
    cargo: str
    destination: str
    crates: int

    @property
    def displaced(self) -> bool:
        """The "ABA" shape: the board is the destination, not the cargo.

        The wiki's own rule is that experience follows the distance the *task*
        spans, so a delivery whose cargo is somewhere else pays for the round
        trip while costing one leg of sailing - "tasks where the noticeboard
        and the cargo are in different locations will offer more experience per
        hour". Measured over the table it is exactly a factor of two.
        """
        return self.notice_board != self.cargo

    def as_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "experience": self.experience,
            "notice_board": self.notice_board,
            "cargo": self.cargo,
            "destination": self.destination,
            "crates": self.crates,
        }


def parse_tasks(text: str) -> tuple[CourierTask, ...]:
    """Every `{{CourierTaskLine}}` on the page, minus the rows with no payout."""
    found: list[CourierTask] = []
    for body in _LINE.findall(text):
        args: dict[str, str] = {}
        for part in body.split("|"):
            if "=" in part:
                key, value = part.split("=", 1)
                args[key.strip()] = value.strip()
        if not args.get("experience", args.get("xp", "")).isdigit():
            continue
        if not args.get("level", "").isdigit():
            continue
        found.append(
            CourierTask(
                level=int(args["level"]),
                experience=int(args["xp"]),
                notice_board=args["noticeBoard"],
                cargo=args["cargoLocation"],
                destination=args["destination"],
                crates=int(args["qty"]) if args.get("qty", "").isdigit() else 1,
            )
        )
    return tuple(found)


def parse_locations(text: str, table: str) -> dict[str, tuple[int, int]]:
    """One `p.<table> = { ['Name'] = {x, y}, ... }` block, as `{name: (x, y)}`.

    Bounded to the named table rather than swept over the whole module,
    because the two tables differ - a ledger port need not have a board - and
    reading both as one would give seven ports a board they do not have.
    """
    start = text.find(f"p.{table}")
    if start < 0:
        return {}
    # **The table closes on its own line**, and looking for a bare `}` before a
    # newline finds the *last entry's* instead - that entry has no trailing
    # comma, so the block would end one port early and lose it silently.
    end = text.find("\n}", start)
    body = text[start : end if end > start else len(text)]
    return {m.group(2): (int(m.group(3)), int(m.group(4))) for m in _COORD.finditer(body)}


def region_of(x: int, y: int) -> str:
    """The chunk id containing a game coordinate.

    Upstream's chunk ids are region ids, so this is the game's own arithmetic
    rather than a mapping this project chose: `(x / 64) << 8 | (y / 64)`,
    verified against the twenty-two ports upstream states a chunk for.
    """
    return str(((x // 64) << 8) | (y // 64))


@dataclass(frozen=True)
class CourierTables:
    """Everything the scrape reads, ready to be written as one blob."""

    tasks: tuple[CourierTask, ...]
    #: Every port, including the eight with no notice board.
    ledgers: Mapping[str, tuple[int, int]]
    #: The twenty-three ports that have one.
    boards: Mapping[str, tuple[int, int]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "tasks": [task.as_dict() for task in self.tasks],
            "ports": {
                name: {
                    "chunk": region_of(*xy),
                    "x": xy[0],
                    "y": xy[1],
                    "board": name in self.boards,
                }
                for name, xy in sorted(self.ledgers.items())
            },
        }


def build_tables(
    fetch_pages: Callable[[list[str]], Mapping[str, str]],
) -> CourierTables:
    """Read both pages and pair them up.

    Two requests, which is why this rides along on `chunksim heuristics`
    rather than earning a subcommand: it is the same kind of question at the
    same cadence, and the table only moves when Jagex adds a port.
    """
    pages = fetch_pages([TASKS_PAGE, LOCATIONS_PAGE])
    tasks = parse_tasks(pages.get(TASKS_PAGE, ""))
    module = pages.get(LOCATIONS_PAGE, "")
    return CourierTables(
        tasks=tasks,
        ledgers=parse_locations(module, "ledgerTableLocations"),
        boards=parse_locations(module, "noticeBoardLocations"),
    )
