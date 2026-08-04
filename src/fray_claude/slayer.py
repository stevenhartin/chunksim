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

**Two very different reasons a task drops out, and they must not be
confused.** `_is_offered` applies the *game's* requirements - `Level`,
`CombatLevel`, `Skills`, and `Tasks` in whatever category each names. A task
failing those is never assigned, so it costs nothing: it never comes up.
`_is_reachable` applies this project's artificial one - `Chunks`, the
export's location gate, with a monster-name heuristic only where an entry
carries none. A task failing *that* was offered, and you have to **pay to
skip it**.

That distinction is the whole of the points economy. `MasterRate.skip_rate`
is the share of offered weight you must cancel, and `points_delta` is what a
master is worth per assignment once you net the skips off::

    points_delta = (1 - skip_rate) * points_per_task - skip_rate * skip_cost

Two thirds doable at 10 points a task against 30 a skip is `-3.3` - the
master *costs* points to train at, however good the XP looks, and that
decides where you go as much as the rate does. Point values are the wiki's
published figures (`heuristics.SLAYER_POINTS`), lifted by
`heuristics.streak_factor` so the milestone bonuses are in the average rather
than in a footnote - 1.775x on the standard table, which takes Krystilia from
25 a task to 44.4. The skip cost is the flat 30, not the far larger `block`
cost tabulated beside it, blocking being permanent and a different decision,
and cancelling does not break the streak - Turael-skipping is what does.

The surviving weights are then renormalised, and *that flatters a sparse
map*: a blocked task is still assigned and still eats the time you spend
cancelling it. `coverage` is what survived, of what was offered.

**Tasks with no rate data are folded in, not dropped.** They are the
low-level ones nobody has bothered to measure, and excluding them from a
master's mixture silently reweights the rest in that master's favour -
Vannaka reached 23% of his list with 24% of it unmeasured and came out
*fastest*, which is backwards. They now enter at
`heuristics.DEFAULT_SLAYER_XP_PER_HOUR` for the master's own typical
assignment length, which moved Vannaka from 57,675 xp/hr to 32,176 and made
Krystilia - who has no gaps at all - the pick.

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
from fray_claude.heuristics import (
    DEFAULT_SLAYER_XP_PER_HOUR,
    streak_factor,
    Heuristics,
    SlayerTask,
    TaskLength,
    stems,
)
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
    #: True when no rate was found and the poor default stood in.
    defaulted: bool = False

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
            "defaulted": self.defaulted,
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
    #: Fraction of the total weight that had no rate data and was folded in
    #: at `DEFAULT_SLAYER_XP_PER_HOUR` instead. Orthogonal to `coverage`:
    #: that says how much of the list you can be assigned, this says how much
    #: of it is a guess. The two call for opposite responses - one is a fact
    #: about the map, the other a hole in the config - and reading a hole as
    #: a fact is how "27% reachable" got quoted for a master whose tasks were
    #: nearly all reachable.
    unpriced: float = 0.0
    #: Fraction of the master's whole list they will actually offer you, the
    #: rest being level- or quest-gated and so never assigned.
    offered: float = 0.0
    #: Fraction of what *is* offered that has to be cancelled, because the
    #: monsters are somewhere this map cannot reach. **This is the one that
    #: costs points**, and it is a different thing entirely from a task the
    #: master never offers: that one never comes up, this one is handed to
    #: you and thrown away.
    skip_rate: float = 0.0
    points_per_task: float = 0.0
    skip_cost: float = 0.0
    #: Net slayer points per assignment: what you earn on the tasks you can
    #: do, less what you pay cancelling the ones you cannot. Negative means
    #: the master costs you points to train at, however good the XP looks -
    #: two thirds doable at 10 a task against 30 a skip is `-3.3`.
    points_delta: float = 0.0

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
            "offered": self.offered,
            "skip_rate": self.skip_rate,
            "points_per_task": self.points_per_task,
            "skip_cost": self.skip_cost,
            "points_delta": self.points_delta,
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


def task_monsters(chunk_info: ChunkInfo, task: str, *, world: bool = False) -> set[str]:
    """Which monsters a task category covers.

    Public because `dps_bridge.py` needs the same join to price a task the
    config has no rate for, and two spellings of it would drift apart.

    The export names tasks in the plural (`Aberrant spectres`) and monsters in
    the singular (`Aberrant spectre`), sometimes with a `#Level 96` variant
    suffix, so matching is on depluralised words rather than equality.

    **`slayerMonsters` holds 95 entries and they are the slayer-specific
    ones** - abyssal demons, gargoyles, nechryael. A master's easy list is
    mostly ordinary world monsters, so `Cows`, `Goblins`, `Bats` and 26 other
    categories match nothing in it at all. `world` widens the search to every
    monster with a drop table, which covers them.

    **Off by default, because widening it changes what "reachable" means.**
    `_is_reachable` reads an empty result as "no opinion" and lets the task
    through; handing it a populated set instead turns that into a real gate,
    which is a different question from the one this was written for. Only
    pricing asks for `world`.
    """
    if not normalise(task):
        return set()
    found = {
        monster
        for monster in chunk_info.slayer_monsters
        if _words_match(task, monster)
    }
    if found or not world:
        return found
    return {monster for monster in chunk_info.drops if _words_match(task, monster)}


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


def _is_offered(
    requirement: dict[str, Any],
    *,
    levels: dict[str, int],
    combat_level: int,
    valid: Mapping[str, Mapping[str, Any]],
) -> bool:
    """Would the master assign this task at all?

    **The game's own requirements only** - slayer level, combat level, other
    skills, and the `Tasks` prerequisites in whatever category each names.
    A task failing these is never offered, so it costs nothing: it simply
    never comes up.

    Deliberately *not* including `Chunks`. That gate is this project's
    artificial one, and the master knows nothing about it - they will happily
    send you somewhere you cannot go, and you pay to skip it. See
    `_is_reachable`.
    """
    if _below(requirement.get("Level"), levels.get("Slayer")):
        return False

    combat = requirement.get("CombatLevel")
    if isinstance(combat, (int, float)) and combat > combat_level:
        return False

    skills = requirement.get("Skills")
    if isinstance(skills, dict):
        for skill, needed in skills.items():
            if _below(needed, levels.get(str(skill))):
                return False

    prerequisites = requirement.get("Tasks")
    if isinstance(prerequisites, dict):
        for name, category in prerequisites.items():
            if name not in (valid.get(str(category)) or {}):
                return False
    return True


def _below(needed: Any, held: int | None) -> bool:
    """Is the level held short of `needed`? Unknown counts as 1.

    That is only honest because the caller infers levels from the player's
    *completed challenges* (`estimate.infer_levels`) rather than reading
    `passiveSkill`, which names five skills on the real map. Vannaka's
    basilisks want `Defence: 20`; the ledger says a Defence cape was bought,
    so the floor is 99 and the task is offered - and then skipped, because
    the Fremennik Slayer Dungeon is not unlocked. Without the inference this
    read as "never offered", which is the opposite claim and costs nothing.
    """
    if not isinstance(needed, (int, float)) or isinstance(needed, bool):
        return False
    return needed > (held if held is not None else 1)


def _is_reachable(
    requirement: dict[str, Any],
    task: str,
    *,
    chunk_info: ChunkInfo,
    reachable_monsters: frozenset[str],
    unlocked: Mapping[str, bool],
    reachable_sections: Mapping[str, Mapping[str, bool]],
) -> bool:
    """Can the task actually be done, once offered?

    The `Chunks` gate is the export's own location test - 128 entries carry
    one, with named areas and `[+]` families - and
    `challenges.chunks_requirement_met` already implements exactly those
    semantics. Only where an entry has none does a monster-name heuristic get
    a say.

    Failing *this* is what costs a skip, because the master offered it.
    """
    if not chunks_requirement_met(requirement, unlocked, reachable_sections, chunk_info):
        return False
    if "Chunks" not in requirement:
        monsters = task_monsters(chunk_info, task)
        if monsters and not (monsters & reachable_monsters):
            return False
    return True


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
        unknown: list[tuple[str, float, float]] = []
        unpriced_weight = 0.0
        offered_weight = 0.0
        skipped_weight = 0.0
        for task, entry in tasks.items():
            if not isinstance(entry, dict):
                continue
            weight = _weight(entry)
            if weight <= 0:
                continue
            if not _is_offered(
                entry, levels=levels, combat_level=combat_level, valid=valid
            ):
                # Never assigned, so never a cost. Not the same thing at all
                # as a task you are handed and cannot go to.
                continue
            offered_weight += weight
            if not _is_reachable(
                entry,
                task,
                chunk_info=chunk_info,
                reachable_monsters=reachable_monsters,
                unlocked=unlocked or {},
                reachable_sections=reachable_sections or {},
            ):
                skipped_weight += weight
                continue
            rate = (heuristics.slayer.get(master) or {}).get(task)
            if rate is None or rate.kills_per_hour <= 0 or rate.count <= 0:
                # Assignable and doable, just unknown to the config. Counted
                # apart from the accessibility drops above, and folded back
                # in at a poor default rather than dropped - see `_defaulted`.
                unpriced_weight += weight
                unknown.append((task, weight, rate.count if rate else 0.0))
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

        priced.extend(_defaulted(unknown, priced))
        rates.append(
            _combine(
                master,
                priced,
                total_weight,
                unpriced_weight,
                offered_weight,
                skipped_weight,
                heuristics.slayer_points(master),
                heuristics.slayer_skip_cost(master),
            )
        )

    rates.sort(key=lambda rate: (-rate.xp_per_hour, rate.master))
    return rates


def _defaulted(
    unknown: list[tuple[str, float, float]], priced: list[TaskRate]
) -> list[TaskRate]:
    """Fold the tasks with no rate data back in at a poor default.

    **Excluding them flattered whoever had the most gaps.** A master's rate
    is a mixture over what it assigns, so dropping a quarter of that mixture
    silently reweights the rest - Vannaka reached only 23% of his list with
    24% unpriced and came out *fastest*, which is exactly backwards: those
    are the low-level tasks nobody has bothered to measure, and being sent on
    them is time not spent earning.

    Nothing is known about how long they take, so they are given the
    master's own typical assignment length and
    `DEFAULT_SLAYER_XP_PER_HOUR` while on it. Assuming a *duration* would be
    inventing a second number on top of the first; assuming a typical one
    keeps the guess to the rate alone.
    """
    if not unknown:
        return []
    typical = _typical_hours(priced)
    filled: list[TaskRate] = []
    for task, weight, count in unknown:
        size = count if count > 0 else 100.0
        filled.append(
            TaskRate(
                task=task,
                weight=weight,
                mean_count=size,
                # Chosen so `xp / hours` is the default rate exactly, at the
                # typical assignment length.
                xp_per_kill=DEFAULT_SLAYER_XP_PER_HOUR * typical / size,
                kills_per_hour=size / typical,
                defaulted=True,
            )
        )
    return filled


def _typical_hours(priced: list[TaskRate]) -> float:
    """How long this master's measured assignments take, on average."""
    total = sum(task.weight for task in priced)
    if total <= 0:
        return 1.0
    average = sum(task.weight * task.hours for task in priced) / total
    return average if average > 0 else 1.0


def _combine(
    master: str,
    tasks: list[TaskRate],
    total_weight: float,
    unpriced_weight: float = 0.0,
    offered_weight: float = 0.0,
    skipped_weight: float = 0.0,
    points: float = 0.0,
    skip_cost: float = 0.0,
) -> MasterRate:
    """The time-weighted mean of `tasks` - see the module docstring."""
    surviving = sum(task.weight for task in tasks)
    share = unpriced_weight / offered_weight if offered_weight > 0 else 0.0
    skip_rate = skipped_weight / offered_weight if offered_weight > 0 else 0.0
    offered = offered_weight / total_weight if total_weight > 0 else 0.0
    # Milestones are folded into what a completed task pays; a cancelled
    # one pays nothing and costs the skip.
    earned = points * streak_factor()
    points_delta = (1 - skip_rate) * earned - skip_rate * skip_cost
    if not tasks or surviving <= 0:
        return MasterRate(
            master=master,
            xp_per_hour=0.0,
            unpriced=share,
            offered=offered,
            skip_rate=skip_rate,
            points_per_task=earned,
            skip_cost=skip_cost,
            points_delta=points_delta,
        )

    expected_xp = sum(task.weight * task.xp for task in tasks) / surviving
    expected_hours = sum(task.weight * task.hours for task in tasks) / surviving
    return MasterRate(
        master=master,
        xp_per_hour=expected_xp / expected_hours if expected_hours > 0 else 0.0,
        tasks=tuple(sorted(tasks, key=lambda task: (-task.weight, task.task))),
        coverage=surviving / offered_weight if offered_weight > 0 else 0.0,
        unpriced=share,
        offered=offered,
        skip_rate=skip_rate,
        points_per_task=earned,
        skip_cost=skip_cost,
        points_delta=points_delta,
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


def superior_spawns_per_hour(
    master: MasterRate, chunk_info: ChunkInfo, heuristics: Heuristics
) -> float:
    """Expected *superior spawns* per hour slaying for `master`.

    **Not the same thing as `superior_rolls_per_hour`, and confusing the two
    is easy.** A superior appears roughly 1 in 200 kills; it then rolls the
    shared drop table only 1 in 43 to 1 in 142 times depending on which
    superior it is. So Vannaka sees a superior about every 1.9 hours and one
    of the four shared items about every 163 - two orders of magnitude apart.

    This is the one a player recognises, so it is what gets reported; the
    other is what prices the items.
    """
    if master.average_hours <= 0:
        return 0.0
    total_weight = sum(task.weight for task in master.tasks)
    if total_weight <= 0:
        return 0.0

    per_assignment = 0.0
    for task in master.tasks:
        chance = _superior_spawn_chance(task.task, chunk_info, heuristics)
        if chance > 0:
            per_assignment += (task.weight / total_weight) * task.mean_count * chance
    return per_assignment / master.average_hours


def _superior_spawn_chance(task: str, chunk_info: ChunkInfo, heuristics: Heuristics) -> float:
    """Chance one kill of `task`'s monsters spawns a superior at all."""
    monsters = task_monsters(chunk_info, task)
    if not monsters:
        return 0.0
    return max(
        (
            superior.spawn_rate
            for superior in heuristics.superiors.values()
            if superior.base in monsters and superior.spawn_rate > 0
        ),
        default=0.0,
    )


def _superior_table_chance(task: str, chunk_info: ChunkInfo, heuristics: Heuristics) -> float:
    """Chance one kill of `task`'s monsters yields a superior-table roll.

    Zero for the many tasks with no superior at all, which is most of them.
    """
    monsters = task_monsters(chunk_info, task)
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
