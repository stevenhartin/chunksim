"""Slayer's XP rate, which is a distribution rather than a method you pick.

Every other skill has a fastest training method you choose and stick to, so
its rate is a lookup (`heuristics.xp_per_hour`). Slayer's is whatever your
master assigns: a weighted mixture of tasks, each with its own kill rate and
its own XP per kill. `bis.py` and `boosts.py` are the precedent for a module
shaped around one skill's peculiarity.

**The rate, per master.** For each assignable task `t` with weight `w`::

    P(t) = w / sum(weights)
    XP(t) = mean_count(t) * xp_per_kill(t)
    T(t)  = mean_count(t) / kills_per_hour(t)

    master xp/hr = sum(P(t) * XP(t)) / sum(P(t) * T(t))

That last line is a **time-weighted** mean, not a plain weighted mean of the
per-task rates. The two differ whenever tasks take different lengths of time,
which they always do: a plain mean counts a 20-minute task and a two-hour task
equally, when in reality you spend six times as long inside the second and
your average rate is dragged towards it. Same inputs, one extra denominator,
and it is the version that survives someone checking it.

**Where the three inputs come from.** Weights are in the *export*
(`slayerMasterTasks`), so they are never scraped and never duplicated into the
config - the export and the config cannot disagree about them. Assignment
sizes come from the wiki's `<Master>/Slayer assignments` tables. XP per kill
and kills per hour come from KodakKid3's spreadsheet, the only source found
for slayer kill rates.

**Which tasks count, and the lie in it.** Only tasks the player can actually
do: slayer level met, combat level met, quest prerequisites valid, and the
task's monsters reachable in the unlocked chunks. The surviving weights are
then renormalised, and *that is an approximation which flatters a sparse map*:
in the real game a blocked task is still assigned and costs you a skip, so a
map holding two of a master's thirty tasks does not really train Slayer at the
rate of those two. `MasterRate.coverage` is the surviving fraction of total
weight, reported precisely so the size of that lie is visible rather than
folded into a number.

**The spreadsheet has no stability contract.** It is a community document that
gets restructured between versions, so columns are read by *header name* and a
missing header raises rather than defaulting to zero. A renamed column should
produce "slayer data unavailable", never a plausible wrong answer.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Any

from fray_claude.chunkinfo import ChunkInfo
from fray_claude.heuristics import Heuristics, SlayerTask
from fray_claude.search import normalise
from fray_claude.summary import _mapping

#: Columns `parse_mob_data` needs. Read by name, and their absence is an
#: error: the sheet has been restructured and any number derived from
#: guessing at positions would be wrong without looking wrong.
TASK_COLUMN = "Task"
XP_COLUMN = "XP/Kill"
KPH_COLUMN = "Raw Kills/Hour"
XP_HOUR_COLUMN = "Raw XP/Hour"
QUALITY_COLUMN = "Data Quality"


class SheetFormatError(Exception):
    """The slayer spreadsheet is not in the shape this module can read."""


@dataclass(frozen=True)
class TaskRate:
    """One assignable task, priced."""

    task: str
    weight: int
    mean_count: float
    xp_per_kill: float
    kills_per_hour: float

    @property
    def xp(self) -> float:
        """Total XP for one assignment of this task."""
        return self.mean_count * self.xp_per_kill

    @property
    def hours(self) -> float:
        """How long one assignment of this task takes."""
        return self.mean_count / self.kills_per_hour if self.kills_per_hour > 0 else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "weight": self.weight,
            "mean_count": self.mean_count,
            "xp_per_kill": self.xp_per_kill,
            "kills_per_hour": self.kills_per_hour,
            "xp": self.xp,
            "hours": self.hours,
        }


@dataclass(frozen=True)
class MasterRate:
    """One master's expected XP per hour, and what it was computed from."""

    master: str
    xp_per_hour: float
    tasks: tuple[TaskRate, ...] = ()
    #: Fraction of the master's total assignment weight that survived the
    #: accessibility filter. Low means the number is optimistic - read the
    #: module docstring before quoting it.
    coverage: float = 0.0
    #: Fraction of that weight dropped for want of *data* rather than access:
    #: a task you can be assigned and could do, but which no rate could be
    #: found for. Reported apart from `coverage` because the two call for
    #: opposite responses - one is a fact about the map, the other is a hole
    #: in the config, and reading a hole as a fact is how "27% reachable" got
    #: quoted for a master whose tasks were nearly all reachable.
    unpriced: float = 0.0

    @property
    def average_hours(self) -> float:
        """How long one assignment takes on average, whatever it turns out to be."""
        total = sum(task.weight for task in self.tasks)
        return (
            sum(task.weight * task.hours for task in self.tasks) / total if total else 0.0
        )

    def probability(self, task: str) -> float:
        """The chance a fresh assignment is `task`, over what is reachable."""
        total = sum(entry.weight for entry in self.tasks)
        weight = next((entry.weight for entry in self.tasks if entry.task == task), 0)
        return weight / total if total else 0.0

    def hours_to_be_assigned(self, task: str) -> float | None:
        """Expected hours of slaying before `task` comes up, `None` if it can't.

        One assignment in `1 / P(task)` is the one you want, and each costs
        `average_hours` whatever it is, so the wait is the two multiplied.
        This is what makes a task-gated boss expensive: you cannot simply go
        and kill it, you have to be sent.
        """
        chance = self.probability(task)
        return self.average_hours / chance if chance > 0 else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "master": self.master,
            "xp_per_hour": self.xp_per_hour,
            "coverage": self.coverage,
            "unpriced": self.unpriced,
            "tasks": [task.as_dict() for task in self.tasks],
        }


def parse_mob_data(csv_text: str) -> dict[str, SlayerTask]:
    """Parse the spreadsheet's Mob Data tab, keyed by normalised task name.

    One row per location/method variant, so a task appears several times; the
    best `Raw XP/Hour` wins, tie-broken on the sheet's own `Data Quality`.
    That is the right pick for an estimate: a player choosing where to kill a
    task will choose the fast place, not the average one.
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    headers = set(reader.fieldnames or ())
    missing = {TASK_COLUMN, XP_COLUMN, KPH_COLUMN} - headers
    if missing:
        raise SheetFormatError(
            f"slayer sheet is missing column(s) {sorted(missing)}; "
            "it has probably been restructured - correct the values by hand instead"
        )

    best: dict[str, tuple[float, float, SlayerTask]] = {}
    for row in reader:
        task = (row.get(TASK_COLUMN) or "").strip()
        xp = _number(row.get(XP_COLUMN))
        kph = _number(row.get(KPH_COLUMN))
        if not task or xp is None or kph is None or kph <= 0:
            continue
        key = normalise(task)
        score = _number(row.get(XP_HOUR_COLUMN)) or xp * kph
        quality = _number(row.get(QUALITY_COLUMN)) or 0.0
        entry = SlayerTask(
            mean_count=0.0, xp_per_kill=xp, kills_per_hour=kph, source="sheet"
        )
        if key not in best or (score, quality) > best[key][:2]:
            best[key] = (score, quality, entry)
    return {key: entry for key, (_, _, entry) in best.items()}


def _number(raw: str | None) -> float | None:
    if raw is None:
        return None
    cleaned = raw.replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _task_monsters(chunk_info: ChunkInfo, task: str) -> set[str]:
    """Which `slayerMonsters` a task category covers.

    The export names tasks in the plural (`Aberrant spectres`) and monsters in
    the singular (`Aberrant spectre`), sometimes with a `#Level 96` variant
    suffix, so matching is on depluralised words rather than equality.
    """
    wanted = _stem_words(task)
    if not wanted:
        return set()
    return {
        monster
        for monster in chunk_info.slayer_monsters
        if wanted <= _stem_words(monster) or _stem_words(monster) <= wanted
    }


def _stem_words(text: str) -> frozenset[str]:
    return frozenset(word.rstrip("s") for word in normalise(text).split() if word)


def _requirements_met(
    requirement: dict[str, Any],
    *,
    levels: dict[str, int],
    combat_level: int,
    valid_quests: frozenset[str],
) -> bool:
    level = requirement.get("Level")
    if isinstance(level, (int, float)) and level > levels.get("Slayer", 1):
        return False
    combat = requirement.get("CombatLevel")
    if isinstance(combat, (int, float)) and combat > combat_level:
        return False
    prerequisites = requirement.get("Tasks")
    if isinstance(prerequisites, dict):
        return all(name in valid_quests for name in prerequisites)
    return True


def master_rates(
    chunk_info: ChunkInfo,
    heuristics: Heuristics,
    *,
    reachable_monsters: frozenset[str],
    valid_quests: frozenset[str],
    levels: dict[str, int],
    combat_level: int = 126,
    reachable_masters: frozenset[str] | None = None,
) -> list[MasterRate]:
    """Every reachable master's expected XP per hour, best first.

    **`reachable_masters` is the master's own NPC availability**, and leaving
    it out is how this module first went wrong: it happily picked Duradel on
    a map holding none of Duradel. A master you cannot walk up to assigns you
    nothing, so a rate computed from their task table is fiction. Pass the
    unlocked NPCs (`SourceIndex.npcs`); `None` means "do not filter", which
    only fixtures should want.

    A master with no priced, reachable task is returned with a rate of zero
    rather than omitted, so a caller can tell "cannot train here" from "no
    such master".
    """
    rates: list[MasterRate] = []
    for master, tasks in _mapping(chunk_info.data, "slayerMasterTasks").items():
        if not isinstance(tasks, dict):
            continue
        if reachable_masters is not None and master not in reachable_masters:
            continue
        total_weight = sum(
            weight
            for entry in tasks.values()
            if isinstance(entry, dict) and isinstance(weight := entry.get("Weight"), int)
        )
        priced: list[TaskRate] = []
        unpriced_weight = 0
        for task, entry in tasks.items():
            if not isinstance(entry, dict):
                continue
            weight = entry.get("Weight")
            if not isinstance(weight, int) or weight <= 0:
                continue
            if not _requirements_met(
                entry, levels=levels, combat_level=combat_level, valid_quests=valid_quests
            ):
                continue
            monsters = _task_monsters(chunk_info, task)
            if monsters and not (monsters & reachable_monsters):
                continue
            rate = heuristics.slayer.get(task)
            if rate is None or rate.kills_per_hour <= 0 or rate.mean_count <= 0:
                # Assignable and doable, just unknown to the config. Counted
                # apart from the accessibility drops above.
                unpriced_weight += weight
                continue
            priced.append(
                TaskRate(
                    task=task,
                    weight=weight,
                    mean_count=rate.mean_count,
                    xp_per_kill=rate.xp_per_kill,
                    kills_per_hour=rate.kills_per_hour,
                )
            )

        rates.append(_combine(master, priced, total_weight, unpriced_weight))

    rates.sort(key=lambda rate: (-rate.xp_per_hour, rate.master))
    return rates


def _combine(
    master: str, tasks: list[TaskRate], total_weight: int, unpriced_weight: int = 0
) -> MasterRate:
    """The time-weighted mean of `tasks` - see the module docstring."""
    surviving = sum(task.weight for task in tasks)
    share = unpriced_weight / total_weight if total_weight > 0 else 0.0
    if not tasks or surviving <= 0:
        return MasterRate(master=master, xp_per_hour=0.0, unpriced=share)

    expected_xp = sum(task.weight * task.xp for task in tasks) / surviving
    expected_hours = sum(task.weight * task.hours for task in tasks) / surviving
    return MasterRate(
        master=master,
        xp_per_hour=expected_xp / expected_hours if expected_hours > 0 else 0.0,
        tasks=tuple(sorted(tasks, key=lambda task: (-task.weight, task.task))),
        coverage=surviving / total_weight if total_weight > 0 else 0.0,
        unpriced=share,
    )


def best_master(rates: list[MasterRate]) -> MasterRate | None:
    """The fastest master that can train at all, or `None` if none can."""
    return next((rate for rate in rates if rate.xp_per_hour > 0), None)
