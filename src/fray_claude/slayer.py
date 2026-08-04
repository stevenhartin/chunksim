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
sizes come from KodakKid3's Task Lengths tab where it has the master (it is
also the only source for the *extended* sizes) and the wiki's
`<Master>/Slayer assignments` tables for the six masters that tab omits. XP
per kill and kills per hour come from the same spreadsheet's Mob Data tab, the
only source found for slayer kill rates.

**Sizes are per master, and flattening them is a trap.** Duradel assigns
130-200 abyssal demons where Krystilia assigns 75-125, and the sheet even
spells the row differently for each (`Abyssal Demon` against
`Abyssal Demons`), so a per-task table keeps both spellings and hands every
master whichever looks closest. Read `heuristics.SlayerTask` on the shape,
and its `count` rather than `mean_count` - that is what applies the
Extended-unlock flag.

**Which tasks count, and the lie in it.** Only tasks the player can actually
be assigned. `_requirements_met` checks all five gates an entry can carry -
`Level`, `CombatLevel`, `Skills`, `Tasks` (*in the category each names*, which
is as often `Thieving` or `Nonskill` as `Quest`, and as often a single quest
*step* as a completion) and `Chunks`, the export's own location gate. Only
where an entry has no `Chunks` does a monster-name heuristic get a say.
The surviving weights are
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
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fray_claude.challenges import chunks_requirement_met
from fray_claude.chunkinfo import ChunkInfo
from fray_claude.heuristics import Heuristics, SlayerTask, TaskLength, stems
from fray_claude.rates import parse_ratio
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

#: The drop table every superior slayer monster shares.
SUPERIOR_TABLE = "SuperiorDropTable+"


class SheetFormatError(Exception):
    """The slayer spreadsheet is not in the shape this module can read."""


@dataclass(frozen=True)
class TaskRate:
    """One assignable task, priced."""

    task: str
    weight: float
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


def parse_task_lengths(csv_text: str) -> dict[str, dict[str, TaskLength]]:
    """Parse the spreadsheet's Task Lengths tab: assignment sizes per task.

    The layout is column *groups*, one per master, and they are not the same
    width - Konar's carries an extra `Location` column because she splits a
    task across places. So the header is scanned for `<Master> Tasks` columns
    and the `Min`/`Max`/`eMin`/`eMax` labels are found *within* each group
    rather than at fixed offsets.

    `eMin`/`eMax` are the sizes with the Extended unlock bought, which is the
    only place those numbers exist at all - the wiki's tables carry a column
    for them but not consistently, and nothing else does.

    **Returned per master, because it is per master.** Flattening it looks
    harmless and is not: the sheet writes Duradel's row `Abyssal Demon` and
    Krystilia's `Abyssal Demons`, so a flat table keeps *both* under different
    keys and every master then matches whichever spelling happens to look
    closest. Duradel came out assigning 100 abyssal demons - Krystilia's
    number - rather than his own 165.

    The master label is the header minus its ` Tasks` suffix, and is the
    sheet's short form (`Konar`) rather than the export's (`Konar quo Maten`);
    `heuristics._slayer_section` resolves between them.
    """
    rows = list(csv.reader(io.StringIO(csv_text)))
    if not rows:
        return {}

    header = rows[0]
    starts = [index for index, name in enumerate(header) if name.strip().endswith(" Tasks")]
    lengths: dict[str, dict[str, TaskLength]] = {}

    for position, start in enumerate(starts):
        master = header[start].strip().removesuffix(" Tasks").strip()
        per_master = lengths.setdefault(master, {})
        end = starts[position + 1] if position + 1 < len(starts) else len(header)
        columns = {
            header[index].strip().lower(): index for index in range(start + 1, end)
        }
        wanted = {label: columns.get(label) for label in ("min", "max", "emin", "emax")}
        if wanted["min"] is None or wanted["max"] is None:
            continue

        for row in rows[1:]:
            task = row[start].strip() if len(row) > start else ""
            if not task:
                continue
            key = normalise(task)
            if key in per_master:
                continue
            low, high = _cell(row, wanted["min"]), _cell(row, wanted["max"])
            if low is None or high is None:
                continue
            extended_low = _cell(row, wanted["emin"])
            extended_high = _cell(row, wanted["emax"])
            per_master[key] = TaskLength(
                task=task,
                low=min(low, high),
                high=max(low, high),
                extended_low=min(extended_low, extended_high)
                if extended_low is not None and extended_high is not None
                else 0.0,
                extended_high=max(extended_low, extended_high)
                if extended_low is not None and extended_high is not None
                else 0.0,
            )
    return lengths


def _cell(row: list[str], index: int | None) -> float | None:
    if index is None or len(row) <= index:
        return None
    return _number(row[index])


def _number(raw: str | None) -> float | None:
    if raw is None:
        return None
    cleaned = raw.replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _weight(entry: Mapping[str, Any]) -> float:
    """An entry's assignment weight. **Floats are real**: Konar splits a task
    across locations and gives each a third of the weight (`1.67`), so an
    `isinstance(x, int)` test drops all 93 of her tasks."""
    value = entry.get("Weight")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


def _task_monsters(chunk_info: ChunkInfo, task: str) -> set[str]:
    """Which `slayerMonsters` a task category covers.

    The export names tasks in the plural (`Aberrant spectres`) and monsters in
    the singular (`Aberrant spectre`), sometimes with a `#Level 96` variant
    suffix, so matching is on depluralised words rather than equality.
    """
    if not normalise(task):
        return set()
    return {
        monster
        for monster in chunk_info.slayer_monsters
        if _words_match(task, monster)
    }


def _words_match(left: str, right: str) -> bool:
    """Do two names mean the same monster, allowing for plurals?

    Word by word through `heuristics.stems`, which knows English has no one
    rule. `rstrip("s")` lived here too and read `Jellies` as `jellie`, so
    Krystilia's jelly task matched no monster, found no superior, and
    contributed nothing to her superior rate.
    """
    first = [word for word in normalise(left).split() if word]
    second = [word for word in normalise(right).split() if word]
    if not first or not second:
        return False
    return all(any(stems(word) & stems(other) for other in second) for word in first) or all(
        any(stems(word) & stems(other) for other in first) for word in second
    )


def _requirements_met(
    requirement: dict[str, Any],
    *,
    chunk_info: ChunkInfo,
    levels: dict[str, int],
    combat_level: int,
    valid: Mapping[str, Mapping[str, Any]],
    unlocked: Mapping[str, bool],
    reachable_sections: Mapping[str, Mapping[str, bool]],
) -> bool:
    """Can this master assign this task at all?

    Five gates, and the entries really do use all five::

        "Dust devils": {"Chunks": ["Wilderness Slayer Cave"], "Level": 65,
                        "Tasks": {"~|Desert Treasure I|~ 7c1": "Quest"},
                        "Weight": 5}

    **`Tasks` maps a name to its *category*, and the category is the half that
    was being thrown away.** Checking every prerequisite against the `Quest`
    branch alone silently failed the nine that are not quests - Krystilia's
    `Magic axes` wants a `Thieving` challenge, her `Pirates` a `Nonskill` one,
    Nieve's `Frost dragons` a `Sailing` one - so those tasks could never be
    assigned however much of the map was unlocked. Note also that a quest
    prerequisite is frequently a *step* (`Desert Treasure I 7c1`), not the
    whole quest, which is why the lookup has to be by name rather than by
    matching a `Complete the quest` entry.

    `Chunks` was not checked at all, and it is the authoritative location
    gate - 128 entries carry one, using named areas and `[+]` families.
    `challenges.chunks_requirement_met` already implements exactly those
    semantics, so it is reused rather than approximated here.
    """
    level = requirement.get("Level")
    if isinstance(level, (int, float)) and level > levels.get("Slayer", 1):
        return False

    combat = requirement.get("CombatLevel")
    if isinstance(combat, (int, float)) and combat > combat_level:
        return False

    skills = requirement.get("Skills")
    if isinstance(skills, dict):
        for skill, needed in skills.items():
            if isinstance(needed, (int, float)) and needed > levels.get(str(skill), 1):
                return False

    prerequisites = requirement.get("Tasks")
    if isinstance(prerequisites, dict):
        for name, category in prerequisites.items():
            if name not in (valid.get(str(category)) or {}):
                return False

    return chunks_requirement_met(requirement, unlocked, reachable_sections, chunk_info)


def master_rates(
    chunk_info: ChunkInfo,
    heuristics: Heuristics,
    *,
    reachable_monsters: frozenset[str],
    valid: Mapping[str, Mapping[str, Any]],
    levels: dict[str, int],
    unlocked: Mapping[str, bool] | None = None,
    reachable_sections: Mapping[str, Mapping[str, bool]] | None = None,
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
            _weight(entry) for entry in tasks.values() if isinstance(entry, dict)
        )
        priced: list[TaskRate] = []
        unpriced_weight = 0.0
        for task, entry in tasks.items():
            if not isinstance(entry, dict):
                continue
            weight = _weight(entry)
            if weight <= 0:
                continue
            if not _requirements_met(
                entry,
                chunk_info=chunk_info,
                levels=levels,
                combat_level=combat_level,
                valid=valid,
                unlocked=unlocked or {},
                reachable_sections=reachable_sections or {},
            ):
                continue
            # `Chunks` is the export's own location gate and beats guessing.
            # Only where an entry has none does the monster-name heuristic
            # get a say - it matched `Spiders` to nothing and dropped a task
            # whose `SpidersWildernessTask[+]` chunks were plainly unlocked.
            if "Chunks" not in entry:
                monsters = _task_monsters(chunk_info, task)
                if monsters and not (monsters & reachable_monsters):
                    continue
            rate = (heuristics.slayer.get(master) or {}).get(task)
            if rate is None or rate.kills_per_hour <= 0 or rate.count <= 0:
                # Assignable and doable, just unknown to the config. Counted
                # apart from the accessibility drops above.
                unpriced_weight += weight
                continue
            priced.append(
                TaskRate(
                    task=task,
                    weight=weight,
                    mean_count=rate.count,
                    xp_per_kill=rate.xp_per_kill,
                    kills_per_hour=rate.kills_per_hour,
                )
            )

        rates.append(_combine(master, priced, total_weight, unpriced_weight))

    rates.sort(key=lambda rate: (-rate.xp_per_hour, rate.master))
    return rates


def _combine(
    master: str, tasks: list[TaskRate], total_weight: float, unpriced_weight: float = 0.0
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


def superior_rolls_per_hour(
    master: MasterRate, chunk_info: ChunkInfo, heuristics: Heuristics
) -> float:
    """Expected `SuperiorDropTable+` rolls per hour slaying for `master`.

    **Superiors share one drop table, so they are one source, not many.** The
    four items on it - imbued heart, eternal gem, and the dust and mist
    battlestaves - do not care which superior rolled them, and you are never
    hunting a particular superior anyway: you take the master's assignments
    and whatever supers appear, appear. Pricing an imbued heart against a
    single base monster asks the wrong question and answers it far too
    pessimistically.

    So the rate aggregates over everything the master can send you to::

        rolls per assignment = sum over tasks t of
            P(t) * count(t) * spawn_rate(superior of t) * table_rate(...)
        rolls per hour = that / average hours per assignment

    **Per master, because you serve one master at a time.** Krystilia's
    abyssal demons, jellies and nechryaels contribute together; Duradel's
    list is a different pool entirely, and adding the two would describe
    nobody's game.
    """
    if master.average_hours <= 0:
        return 0.0

    total_weight = sum(task.weight for task in master.tasks)
    if total_weight <= 0:
        return 0.0

    per_assignment = 0.0
    for task in master.tasks:
        chance = _superior_table_chance(task.task, chunk_info, heuristics)
        if chance > 0:
            per_assignment += (task.weight / total_weight) * task.mean_count * chance
    return per_assignment / master.average_hours


def _superior_table_chance(task: str, chunk_info: ChunkInfo, heuristics: Heuristics) -> float:
    """Chance one kill of `task`'s monsters yields a superior-table roll.

    Zero for the many tasks with no superior at all, which is most of them.
    """
    monsters = _task_monsters(chunk_info, task)
    if not monsters:
        return 0.0

    activities = _mapping(chunk_info.skill_items, "Slayer")
    best = 0.0
    for superior in heuristics.superiors.values():
        if superior.base not in monsters or superior.spawn_rate <= 0:
            continue
        rolls = _mapping(activities, superior.name).get(SUPERIOR_TABLE)
        if not isinstance(rolls, dict):
            continue
        for raw in rolls.values():
            rate = parse_ratio(str(raw).partition("@")[0])
            if not math.isnan(rate) and rate > 0:
                best = max(best, superior.spawn_rate * rate)
    return best


def superior_table_items(chunk_info: ChunkInfo) -> dict[str, float]:
    """The shared table's contents: item -> its share of a roll."""
    table = _mapping(chunk_info.code_items, "dropTables").get(SUPERIOR_TABLE)
    if not isinstance(table, dict):
        return {}
    shares: dict[str, float] = {}
    for item, raw in table.items():
        rate = parse_ratio(str(raw).partition("@")[0])
        if not math.isnan(rate) and rate > 0:
            shares[str(item)] = rate
    return shares
