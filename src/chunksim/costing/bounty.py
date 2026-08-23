"""Bounty tasks: kill a sea monster until it drops what a port asked for.

**Boat combat pays one Sailing experience for every point of damage dealt**,
which is the fact the whole model turns on: a kill is worth the monster's
hitpoints before the bounty pays anything, so `Boat combat`'s health table is
half the rate and `remote/bounty.py` scrapes it beside the task list.

    kills   = quantity / rarity            (both published, per task)
    damage  = kills x hitpoints            (and the experience that damage pays)
    seconds = damage / dps + the sail out and back
    hours   = (damage + the bounties' own experience) / seconds

**The bounty payout dominates.** Experience is a property of the *monster*
rather than the task - all nine Albatross bounties pay 14,575 whatever the item
or the quantity - and it runs 3,465 to 47,080 across the twenty. Against a
Great white shark's 243 hitpoints over a hundred kills that is 24,300 of damage
experience beside 80,740 of bounties, so what makes this a training method is
the hand-in, not the fighting.

### What the map has to hold

Three things, and the middle one is what upstream does not model:

- **A notice board**, because a bounty is taken at one. Upstream's own
  `Take ~|port tasks|~ from X` challenges are the gate, shared with
  `costing/courier.py`.
- **The monster**, which is `derived.source_index.monsters` - the derivation's
  own answer about what this map's chunks contain.
- **A sea route from a board to the monster's water**, over
  `costing/courier.py`'s graph and restricted to chunks the map holds. Upstream
  gates the challenge on one port location and a bounty monster and says
  nothing about the water; requiring the crossing is deliberately stricter, and
  it is also what prices the trip.

The bounty itself is **not** tied to where it was taken - `Sailing training`
says so outright, "once the task is accepted, all monsters of that type can
drop it regardless of their location" - so the route is board to monster and
back, and any board will do for the hand-in.

### Stacking is sequential, which is the trap

A player holds three tasks at level 30, four at 56 and five at 84, and can take
several for one monster provided they name different drops. It is tempting to
treat that as parallel progress and it is not: the 17 June 2026 update made
bounty items roll one at a time, so "you will not receive drops from the second
task until all the drops for the first task are collected". Stacking therefore
saves **the sail**, not the kills, and `_chosen` sums the kill counts rather
than taking their maximum. Getting that backwards would roughly halve every
figure here.

### The damage model, and the constant that fitted to nothing

The player's own kill rate is `Heuristics.kills_per_hour`, which is the DPS
bridge's answer where it has one - 19 of the 20 monsters - and `DEFAULT_KPH`
where it does not. Multiplied by hitpoints that is damage an hour, and divided
by 3,600 it is the player's damage a second, which is what `CANNON_DPS` is
added to: the crew firing cannons while the player fights with ranged or magic,
which is what `Sailing training` recommends and what the bridge is already
modelling for the player's half.

**`CANNON_DPS` is zero, and it is zero because it fitted there.** The only
published figure for this method is that bounty tasks are "a middle ground
between salvaging and trials, with optimal rates in-between the two" - so on
the every-rollable-chunk map the answer must land between this project's own
88,923 for the Barracuda trials and 171,000 for salvage sorting. It reads
**138,313 with no cannon term at all**, and five damage a second of crew would
put it at 211,027, outside the band on the wrong side.

The reason is structural rather than a coincidence: `kills_per_hour` is a
*wall-clock* rate carrying banking and respawn (`dps_bridge.KillEstimate.
overhead`), and boat combat has neither - a corpse is netted where it floats.
So the overhead the bridge charges and the damage the crew adds are the same
size and cancel, and no evidence here can separate them. The constant is kept
as a named term rather than dropped, so the day somebody measures a crewmate's
cannon it is one number and not a rewrite.

Every band is a `GUESS`: the kill rate is the bridge's, the crew is unmeasured,
and the only check is a range in a sentence.

Pure: the valid set, the derivation and the scraped tables, all handed in.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Iterable, Mapping, Sequence

from chunksim.costing import courier
from chunksim.costing.gathering import GUESS
from chunksim.costing.heuristics import ComputedMethod

SKILL = "Sailing"

#: Upstream's own primary challenge.
TASK = "Complete ~|bounty tasks|~"

METHOD = "bounty tasks"

#: One Sailing experience a point of damage - `Boat combat`, stated.
XP_PER_DAMAGE = 1.0

#: `Bounty tasks`' own table: three slots at 30, four at 56, five at 84.
TASK_SLOTS: tuple[tuple[int, int], ...] = ((30, 3), (56, 4), (84, 5))

#: Damage a second the crew's cannons add to the player's own. **Fitted, and
#: it fitted to zero** - see the module docstring, which is also why it is
#: still here rather than deleted.
CANNON_DPS = 0.0

#: The wiki's bounty table against upstream's export, in that direction. One
#: entry, because one monster is spelled differently in the two vocabularies -
#: `costing/recipe_rates.py`'s rule that an alias table runs one way and
#: conflating the directions searches the wrong dictionary.
MONSTER_ALIASES: Mapping[str, str] = {"Mogre (sea)": "Mogre (Sailing)"}

SECONDS_PER_HOUR = 3600.0


def slots_at(level: int) -> int:
    """How many port tasks can be held at `level`, per the published table."""
    return max(
        (slots for gate, slots in TASK_SLOTS if level >= gate), default=0
    )


@dataclass(frozen=True)
class Bounty:
    """One bounty, as the wiki tabulates it."""

    level: int
    experience: int
    notice_board: str
    monster: str
    item: str
    quantity: int
    rarity: str

    @property
    def kills(self) -> float:
        """Expected kills to finish it, `quantity / rarity`."""
        chance = Fraction(self.rarity)
        return float(self.quantity / chance) if chance else 0.0

    @property
    def upstream_monster(self) -> str:
        """The export's spelling of `monster`."""
        return MONSTER_ALIASES.get(self.monster, self.monster)


def bounties_from(blob: Mapping[str, object]) -> tuple[Bounty, ...]:
    """The scraped table as `Bounty`s."""
    rows = blob.get("tasks")
    if not isinstance(rows, Sequence):
        return ()
    found: list[Bounty] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        found.append(
            Bounty(
                level=int(row["level"]),
                experience=int(row["experience"]),
                notice_board=str(row["notice_board"]),
                monster=str(row["monster"]),
                item=str(row.get("item", "")),
                quantity=int(row["quantity"]),
                rarity=str(row.get("rarity", "1/1")),
            )
        )
    return tuple(found)


def hitpoints_from(blob: Mapping[str, object]) -> dict[str, int]:
    """`Boat combat`'s health table."""
    rows = blob.get("hitpoints")
    if not isinstance(rows, Mapping):
        return {}
    return {str(name): int(health) for name, health in rows.items()}


def monster_chunks(chunks: Mapping[str, Any]) -> dict[str, frozenset[str]]:
    """`{monster: the chunks it is in}`, from the export's own placements.

    Both the whole-chunk and the per-section forms, because a sea monster
    turns up under either depending on whether its chunk is split.
    """
    found: dict[str, set[str]] = {}
    for chunk, entry in chunks.items():
        if not isinstance(entry, Mapping):
            continue
        wells: list[Any] = [entry.get("Monster")]
        sections = entry.get("Sections")
        if isinstance(sections, Mapping):
            wells.extend(body.get("Monster") for body in sections.values()
                         if isinstance(body, Mapping))
        for well in wells:
            if isinstance(well, Mapping):
                for monster in well:
                    found.setdefault(str(monster), set()).add(chunk)
    return {monster: frozenset(where) for monster, where in found.items()}


def _chosen(bounties: Sequence[Bounty], level: int) -> tuple[Bounty, ...]:
    """The tasks a player would hold for one monster, fewest kills first.

    **One per distinct item**, since two bounties for the same drop cannot be
    held at once, and no more than the level allows.
    """
    picked: dict[str, Bounty] = {}
    for bounty in sorted(bounties, key=lambda b: b.kills):
        if bounty.level <= level:
            picked.setdefault(bounty.item, bounty)
    return tuple(picked.values())[: slots_at(level)]


@dataclass(frozen=True)
class Hunt:
    """One monster's best answer at a level."""

    monster: str
    hitpoints: int
    #: Sea chunks from the nearest board to the nearest water holding it.
    hops: int
    tasks: tuple[Bounty, ...]
    #: The player's own damage a second, before `CANNON_DPS`.
    player_dps: float

    @property
    def kills(self) -> float:
        return sum(task.kills for task in self.tasks)

    @property
    def seconds(self) -> float:
        dps = self.player_dps + CANNON_DPS
        if dps <= 0:
            return 0.0
        fighting = self.kills * self.hitpoints / dps
        return fighting + 2 * self.hops * courier.SECONDS_PER_HOP

    @property
    def experience(self) -> float:
        """The damage plus the hand-ins."""
        return self.kills * self.hitpoints * XP_PER_DAMAGE + sum(
            task.experience for task in self.tasks
        )

    @property
    def xp_per_hour(self) -> float:
        seconds = self.seconds
        return self.experience * SECONDS_PER_HOUR / seconds if seconds > 0 else 0.0


def hunts_for(
    bounties: Iterable[Bounty],
    hitpoints: Mapping[str, int],
    reachable_monsters: Iterable[str],
    placements: Mapping[str, frozenset[str]],
    board_chunks: Mapping[str, Mapping[str, int]],
    kills_per_hour: Mapping[str, float],
    level: int,
) -> tuple[Hunt, ...]:
    """Every monster this map can hunt at `level`, priced.

    `board_chunks` is one sea-hop map per reachable notice board, so the trip
    charged is from the nearest board to the nearest water the monster is in.
    """
    reachable = frozenset(reachable_monsters)
    grouped: dict[str, list[Bounty]] = {}
    for bounty in bounties:
        grouped.setdefault(bounty.monster, []).append(bounty)
    found: list[Hunt] = []
    for monster, offered in grouped.items():
        upstream = MONSTER_ALIASES.get(monster, monster)
        if upstream not in reachable:
            continue
        health = hitpoints.get(monster) or hitpoints.get(upstream)
        if not health:
            continue
        tasks = _chosen(offered, level)
        if not tasks:
            continue
        hops = min(
            (
                distance
                for chunk in placements.get(upstream, frozenset())
                for hops_from in board_chunks.values()
                if (distance := hops_from.get(chunk)) is not None
            ),
            default=None,
        )
        if hops is None:
            # **No water route is no hunt.** A monster in a sea this map does
            # not own cannot be sailed to, whatever the export says about the
            # chunk holding it.
            continue
        rate = kills_per_hour.get(upstream, 0.0)
        if rate <= 0:
            continue
        found.append(
            Hunt(
                monster=monster,
                hitpoints=health,
                hops=hops,
                tasks=tasks,
                player_dps=rate * health / SECONDS_PER_HOUR,
            )
        )
    return tuple(found)


def methods(
    valid: Mapping[str, Mapping[str, object]],
    derived_monsters: Iterable[str],
    chunks: Mapping[str, Any],
    held: Mapping[str, bool],
    ocean: Iterable[str],
    sections: Mapping[str, Mapping[str, object]],
    courier_blob: Mapping[str, object],
    bounty_blob: Mapping[str, object],
    kills_per_hour: Mapping[str, float],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Sailing": bands}`, one per level where the best hunt improves.

    Nothing unless upstream's own challenge is valid, which already asserts a
    port location and a bounty monster. This adds the water between them.
    """
    if TASK not in (valid.get(SKILL) or {}):
        return {}
    bounties = bounties_from(bounty_blob)
    health = hitpoints_from(bounty_blob)
    if not bounties or not health:
        return {}
    owned = frozenset(chunk for chunk, on in held.items() if on)
    ports = courier.ports_from(courier_blob)
    _, boards = courier.reachable_ports(ports, valid, owned)
    if not boards:
        return {}
    navigable = courier.navigable_chunks(ocean, sections)
    board_chunks = {
        name: courier.sea_hops(ports[name].chunk, navigable, owned) for name in boards
    }
    offered = tuple(b for b in bounties if b.notice_board in boards)
    if not offered:
        return {}
    placements = monster_chunks(chunks)
    bands: list[ComputedMethod] = []
    best = 0.0
    for level in sorted({b.level for b in offered} | {gate for gate, _ in TASK_SLOTS}):
        hunts = hunts_for(
            offered, health, derived_monsters, placements, board_chunks,
            kills_per_hour, level,
        )
        if not hunts:
            continue
        hunt = max(hunts, key=lambda h: h.xp_per_hour)
        rate = hunt.xp_per_hour
        if rate <= best + 1.0:
            continue
        best = rate
        bands.append(
            ComputedMethod(
                method=f"{METHOD} ({hunt.monster})",
                xp_per_hour=rate,
                level=level,
                match=GUESS,
                knob=f"training/{TASK}/{SKILL}",
            )
        )
    return {SKILL: tuple(bands)} if bands else {}
