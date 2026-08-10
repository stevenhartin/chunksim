"""Prayer, which is one action repeated - so the whole model is the bone supply.

**The rate is not the question; the collection is.** Burying takes two ticks and
offering at an altar takes one, so an hour of pure clicking is 3,000 or 6,000
bones whatever else is true. Nobody has 6,000 bones. What decides how fast
Prayer goes is how long it takes to *get* one, and that is a question this
project already answers for every other material: the item walk in
`costing/estimate.py` prices the cheapest route to an item off the map's own
drop tables. So Prayer is priced the way a recipe is - an action cost plus what
its input costs - and `costing/prayer.py` is almost entirely the arithmetic
joining the two.

    xp_per_hour = experience_per_bone * 3600 / (offering_seconds + collect_seconds)

**Prayer has no burying challenge**, which is why this is a module and not a
rate in `heuristics.py`. The export's six `Primary: true` Prayer methods offer
fish at a shrine and shards at a libation bowl; the thing every player does from
level 1 is not modelled at all. So the rate reaches `training_options` through
`Heuristics.computed`, the same door `costing/combat_xp.py` uses for the five
combat skills, and for the same reason: the export has no task to join a rate
to because the game needs no task, it needs a bone.

**Three altars, and which one a map has changes the answer sevenfold.**

| offering | multiplier | seconds per bone collected |
|---|---|---|
| burying | 1x | 1.2 (two ticks) |
| a house altar, both burners lit | 2.0x - 3.5x | 0.6 (one tick) |
| the Wilderness Chaos Altar | **7x** | 1.2 |

The chaos altar is 3.5x per offering *and* has a 50% chance not to consume the
bone, so a bone collected is offered twice on average - which is why it is
modelled as two offerings rather than as a seven-times multiplier. That costs it
two ticks per bone, and still leaves it the best offering in the game by a
factor of two over a gilded altar.

**Which chaos altar, though, is the trap.** The export puts `Chaos altar
(Prayer)` in five chunks and only *one* of them trains Prayer: the Chaos Temple
church in level 38 Wilderness. The others - Varrock, the Yanille Agility
dungeon, the Underground Pass - are prayer-point recharges that do nothing for a
bone. Keying on the object name would hand a sevenfold rate to any map holding
the Varrock one, so the training altar is pinned to its region and identified in
`CHAOS_ALTAR_CHUNK` by the contents the wiki's own description of that temple
names: the wine of Zamorak spawn, the Elder Chaos druid and the Wilderness diary
entry. One documented constant, in the same spirit as `combat_xp.INSTANCED_AREAS`.

**A house altar is gated twice and both gates are real.** Reaching the
Construction challenge says the map contains a house; having the Construction
*level* says you can build it, and `infer_levels` reads that floor out of the
completed challenges. The incense burners are their own challenges at 61-69, so
an altar reachable without them takes its `base` multiplier rather than `lit` -
which on a gilded altar is the difference between 2.5x and 3.5x.

Pure: a function of `(ChunkInfo, Derived, bones, altars, levels)` and a callable
pricing an item. No disk, no network, no module-level mutable state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from collections.abc import Callable, Mapping, Sequence

from fray_claude.derive.pipeline import Derived
from fray_claude.derive.task_names import strip_task_markup
from fray_claude.model.chunkinfo import ChunkInfo
from fray_claude.model.summary import _mapping
from fray_claude.remote.prayer import Altar, Bone

#: One game tick, the unit both offerings are measured in.
TICK_SECONDS = 0.6

#: Burying is a two-tick action; offering at any altar is one.
BURY_TICKS = 2
ALTAR_TICKS = 1

#: The Chaos Temple church in level 38 Wilderness - the only one of the export's
#: five `Chaos altar (Prayer)` objects that takes bones. Identified by its
#: contents rather than by its name: region 11835 holds the wine of Zamorak
#: spawn, the Elder Chaos druid and the Wilderness diary entry that the wiki's
#: description of that temple names, where region 12856 ("Chaos Temple", the
#: hut south-east of Varrock) holds Simon's cape shop instead.
CHAOS_ALTAR_CHUNK = "11835"

#: The object the export names in that chunk. Both must hold: the right chunk,
#: and the altar still being in it.
CHAOS_ALTAR_OBJECT = "Chaos altar (Prayer)"

#: The chaos altar's own multiplier, and its chance not to consume the bone.
#: Stated by the wiki outright ("granting 3.5x Prayer experience per bone …
#: every bone offered has a 50% chance to not be consumed").
CHAOS_MULTIPLIER = 3.5
CHAOS_SAVE_CHANCE = 0.5


@dataclass(frozen=True)
class Offering:
    """Where a bone is offered, and what that costs and pays.

    `multiplier` is per *bone collected*, not per offering - which is how the
    chaos altar's bone save is expressed, and why `seconds` is not simply one
    tick there.
    """

    name: str
    multiplier: float
    seconds: float
    #: The Construction level the altar needed, for the tooltip. `0` for
    #: burying and for the chaos altar, neither of which needs a house.
    level: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "multiplier": round(self.multiplier, 3),
            "seconds": round(self.seconds, 3),
            "level": self.level,
        }


@dataclass(frozen=True)
class PrayerMethod:
    """One bone offered one way, priced end to end."""

    bone: str
    offering: str
    #: Prayer level, off the bone - 70 for superior dragon bones, 1 for the
    #: other thirty-eight.
    level: int
    experience: float
    offering_seconds: float
    collect_seconds: float

    @property
    def xp_per_hour(self) -> float:
        seconds = self.offering_seconds + self.collect_seconds
        return self.experience * 3600.0 / seconds if seconds > 0 else 0.0

    @property
    def method(self) -> str:
        return f"{self.bone} ({self.offering})"

    def as_dict(self) -> dict[str, Any]:
        return {
            "bone": self.bone,
            "offering": self.offering,
            "level": self.level,
            "experience": round(self.experience, 2),
            "offering_seconds": round(self.offering_seconds, 3),
            "collect_seconds": round(self.collect_seconds, 1),
            "xp_per_hour": round(self.xp_per_hour, 1),
        }


def _altar_name(task: str) -> str:
    """`Build a ~|gilded altar|~` -> `gilded altar`.

    A structural join, not a fuzzy one: the challenge's name carries the
    furniture and the wiki's page title *is* the furniture, so there is
    nothing to be approximate about.
    """
    plain = strip_task_markup(task).strip()
    for prefix in ("Build an ", "Build a "):
        if plain.startswith(prefix):
            return plain[len(prefix) :].strip().lower()
    return ""


def offerings(
    chunk_info: ChunkInfo,
    derived: Derived,
    altars: Sequence[Altar],
    levels: Mapping[str, int],
) -> tuple[Offering, ...]:
    """Every way this map can offer a bone, best first.

    Always at least one: burying needs nothing but the bone, so the list can
    never be empty and Prayer can never be unpriceable for want of an altar.
    """
    found = [Offering(name="buried", multiplier=1.0, seconds=BURY_TICKS * TICK_SECONDS)]

    if derived.expanded_chunks.get(CHAOS_ALTAR_CHUNK) and CHAOS_ALTAR_OBJECT in (
        derived.source_index.objects
    ):
        # Offered until it sticks: `1 / (1 - save)` offerings per bone, each
        # paying the full multiplier and each costing its own tick.
        offers = 1.0 / (1.0 - CHAOS_SAVE_CHANCE)
        found.append(
            Offering(
                name="Chaos Altar",
                multiplier=CHAOS_MULTIPLIER * offers,
                seconds=ALTAR_TICKS * TICK_SECONDS * offers,
            )
        )

    by_name = {altar.name: altar for altar in altars}
    construction = levels.get("Construction", 1)
    burners = any(
        "incense burner" in _altar_name(task)
        for task in derived.challenges.valid.get("Construction") or {}
    )
    challenges = _mapping(chunk_info.challenges, "Construction")
    for task in derived.challenges.valid.get("Construction") or {}:
        altar = by_name.get(_altar_name(task))
        if altar is None:
            continue
        entry = challenges.get(task)
        level = entry.get("Level") if isinstance(entry, dict) else None
        needed = int(level) if isinstance(level, (int, float)) else 1
        # **Reaching the challenge is not being able to build it.** The map
        # says a house exists; the level says you can put an altar in it.
        if construction < needed:
            continue
        found.append(
            Offering(
                name=altar.name,
                multiplier=altar.lit if burners else altar.base,
                seconds=ALTAR_TICKS * TICK_SECONDS,
                level=needed,
            )
        )
    return tuple(sorted(found, key=lambda o: (-o.multiplier / o.seconds, o.name)))


def prayer_methods(
    chunk_info: ChunkInfo,
    derived: Derived,
    bones: Sequence[Bone],
    altars: Sequence[Altar],
    levels: Mapping[str, int],
    collect_seconds: Callable[[str, float], float | None],
) -> tuple[PrayerMethod, ...]:
    """Every bone this map can obtain, offered the best way it can, best first.

    A bone with no route is dropped rather than priced at zero - the same
    reading `costing/recipe_rates.py` takes of an unpriceable material, and for
    the same reason: a free bone would make the rarest remains in the game the
    fastest Prayer training on the map.

    One `Offering` serves every bone. The altar does not care which bone it is
    given, so choosing it per bone would be the same choice thirty-nine times.
    """
    available = offerings(chunk_info, derived, altars, levels)
    if not available:
        return ()
    best = available[0]

    found: list[PrayerMethod] = []
    for bone in bones:
        collect = collect_seconds(bone.name, 1.0)
        if collect is None:
            continue
        found.append(
            PrayerMethod(
                bone=bone.name,
                offering=best.name,
                level=bone.level,
                experience=bone.experience * best.multiplier,
                offering_seconds=best.seconds,
                collect_seconds=collect,
            )
        )
    return tuple(sorted(found, key=lambda m: (-m.xp_per_hour, m.bone)))
