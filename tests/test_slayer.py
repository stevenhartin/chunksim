"""Tests for the slayer rate model.

The first test is the load-bearing one: the two-task master is worked through
by hand, so the weighting is pinned by arithmetic rather than by whatever the
code happens to do.
"""

from __future__ import annotations

from typing import Any

import pytest

from fray_claude.chunkinfo import ChunkInfo
from fray_claude.heuristics import Heuristics, SlayerTask
from fray_claude.slayer import (
    SheetFormatError,
    best_master,
    master_rates,
    parse_mob_data,
)

_CSV = (
    '"Task","Fixed Variables Monster Variant","XP/Kill","Raw Kills/Hour",'
    '"Raw XP/Hour","Data Quality"\n'
    '"Abberant Spectre","Aberrant Spectre (Slayer Tower)","115.01","240","27601.6","4"\n'
    '"Abberant Spectre","Aberrant Spectre (Stronghold)","106.07","340","36062.7","3"\n'
    '"Bloodveld","Bloodveld (Catacombs)","150.00","300","45000.0","5"\n'
)


def _info(**data: Any) -> ChunkInfo:
    return ChunkInfo(data)


def _heuristics(**tasks: SlayerTask) -> Heuristics:
    return Heuristics(slayer={name.replace("_", " "): rate for name, rate in tasks.items()})


def test_the_rate_is_the_time_weighted_mean() -> None:
    # Worked by hand. Task A: weight 1, 100 kills at 10 xp over 100/100 = 1h.
    # Task B: weight 3, 100 kills at 20 xp over 100/50 = 2h.
    #   P(A)=0.25 P(B)=0.75
    #   E[xp]    = 0.25*1000 + 0.75*2000 = 1750
    #   E[hours] = 0.25*1    + 0.75*2    = 1.75
    #   rate     = 1750 / 1.75 = 1000
    info = _info(slayerMasterTasks={"Duradel": {"A": {"Weight": 1}, "B": {"Weight": 3}}})
    heuristics = _heuristics(
        A=SlayerTask(mean_count=100, xp_per_kill=10, kills_per_hour=100),
        B=SlayerTask(mean_count=100, xp_per_kill=20, kills_per_hour=50),
    )

    rate = master_rates(
        info,
        heuristics,
        reachable_monsters=frozenset(),
        valid_quests=frozenset(),
        levels={"Slayer": 99},
    )[0]

    assert rate.xp_per_hour == pytest.approx(1000.0)
    assert rate.coverage == 1.0


def test_a_plain_mean_of_rates_would_give_a_different_answer() -> None:
    # The same two tasks. Weighted mean of the per-task rates is
    # 0.25*1000 + 0.75*1000 = 1000 here only because they coincide, so use a
    # pair where they don't: A is 10 xp/kill at 100 kph = 1000 xp/hr, B is
    # 20 xp/kill at 50 kph = 1000 xp/hr... both 1000. Make B slower instead.
    #   A: weight 1, 100 kills, 10 xp, 100 kph -> 1000 xp/hr, 1h
    #   B: weight 1, 100 kills, 10 xp,  25 kph ->  250 xp/hr, 4h
    # Plain mean of rates: (1000 + 250) / 2 = 625.
    # Time-weighted:  (1000+1000)/2 / (1+4)/2 = 1000 / 2.5 = 400.
    # 400 is right: over two assignments you earn 2000 xp across 5 hours.
    info = _info(slayerMasterTasks={"M": {"A": {"Weight": 1}, "B": {"Weight": 1}}})
    heuristics = _heuristics(
        A=SlayerTask(mean_count=100, xp_per_kill=10, kills_per_hour=100),
        B=SlayerTask(mean_count=100, xp_per_kill=10, kills_per_hour=25),
    )

    rate = master_rates(
        info, heuristics, reachable_monsters=frozenset(), valid_quests=frozenset(), levels={}
    )[0]

    assert rate.xp_per_hour == pytest.approx(400.0)
    assert rate.xp_per_hour != pytest.approx(625.0)


def test_a_task_above_the_players_slayer_level_is_excluded() -> None:
    info = _info(
        slayerMasterTasks={"M": {"A": {"Weight": 1}, "B": {"Weight": 1, "Level": 85}}}
    )
    heuristics = _heuristics(
        A=SlayerTask(mean_count=100, xp_per_kill=10, kills_per_hour=100),
        B=SlayerTask(mean_count=100, xp_per_kill=99, kills_per_hour=100),
    )

    rate = master_rates(
        info, heuristics, reachable_monsters=frozenset(), valid_quests=frozenset(),
        levels={"Slayer": 50},
    )[0]

    assert [task.task for task in rate.tasks] == ["A"]
    assert rate.coverage == 0.5


def test_a_task_whose_quest_is_not_done_is_excluded() -> None:
    info = _info(
        slayerMasterTasks={
            "M": {
                "A": {"Weight": 1},
                "B": {"Weight": 1, "Tasks": {"~|Priest in Peril|~ Complete the quest": "Quest"}},
            }
        }
    )
    heuristics = _heuristics(
        A=SlayerTask(mean_count=100, xp_per_kill=10, kills_per_hour=100),
        B=SlayerTask(mean_count=100, xp_per_kill=10, kills_per_hour=100),
    )

    rate = master_rates(
        info, heuristics, reachable_monsters=frozenset(), valid_quests=frozenset(), levels={}
    )[0]

    assert [task.task for task in rate.tasks] == ["A"]


def test_an_unreachable_task_drops_out_and_coverage_falls() -> None:
    # Coverage is the honest measure of how much the renormalisation flatters
    # a sparse map - see the module docstring.
    info = _info(
        slayerMasterTasks={"M": {"Bats": {"Weight": 3}, "Bears": {"Weight": 1}}},
        slayerMonsters={"Bat": 1, "Bear": 1},
    )
    heuristics = _heuristics(
        Bats=SlayerTask(mean_count=100, xp_per_kill=10, kills_per_hour=100),
        Bears=SlayerTask(mean_count=100, xp_per_kill=10, kills_per_hour=100),
    )

    rate = master_rates(
        info, heuristics, reachable_monsters=frozenset({"Bear"}), valid_quests=frozenset(),
        levels={},
    )[0]

    assert [task.task for task in rate.tasks] == ["Bears"]
    assert rate.coverage == 0.25


def test_an_unpriced_task_is_not_counted() -> None:
    info = _info(slayerMasterTasks={"M": {"A": {"Weight": 1}, "B": {"Weight": 1}}})
    heuristics = _heuristics(A=SlayerTask(mean_count=100, xp_per_kill=10, kills_per_hour=100))

    rate = master_rates(
        info, heuristics, reachable_monsters=frozenset(), valid_quests=frozenset(), levels={}
    )[0]

    assert [task.task for task in rate.tasks] == ["A"]


def test_a_master_with_nothing_doable_is_reported_at_zero() -> None:
    # Zero rather than absent, so a caller can tell "cannot train here" from
    # "no such master".
    info = _info(slayerMasterTasks={"M": {"A": {"Weight": 1}}})

    rates = master_rates(
        info, Heuristics(), reachable_monsters=frozenset(), valid_quests=frozenset(), levels={}
    )

    assert rates[0].xp_per_hour == 0.0
    assert best_master(rates) is None


def test_the_fastest_master_is_chosen() -> None:
    info = _info(
        slayerMasterTasks={"Slow": {"A": {"Weight": 1}}, "Fast": {"B": {"Weight": 1}}}
    )
    heuristics = _heuristics(
        A=SlayerTask(mean_count=100, xp_per_kill=10, kills_per_hour=100),
        B=SlayerTask(mean_count=100, xp_per_kill=50, kills_per_hour=100),
    )

    chosen = best_master(
        master_rates(
            info, heuristics, reachable_monsters=frozenset(), valid_quests=frozenset(),
            levels={},
        )
    )

    assert chosen is not None and chosen.master == "Fast"


# --- the spreadsheet -------------------------------------------------------


def test_parse_mob_data_keeps_the_best_variant() -> None:
    parsed = parse_mob_data(_CSV)

    # Two Aberrant Spectre rows; the higher Raw XP/Hour wins, because a
    # player picking where to kill a task picks the fast place.
    assert parsed["abberant spectre"].kills_per_hour == 340.0
    assert parsed["abberant spectre"].xp_per_kill == 106.07


def test_the_sheets_misspelling_is_preserved_for_joining() -> None:
    # The sheet really does say "Abberant". The join is by normalised name,
    # so the typo has to survive parsing to be matched against.
    assert "abberant spectre" in parse_mob_data(_CSV)


def test_a_renamed_column_fails_loudly() -> None:
    # A restructured sheet must not quietly price every task at zero.
    renamed = _CSV.replace("Raw Kills/Hour", "Kills Per Hour")

    with pytest.raises(SheetFormatError, match="Raw Kills/Hour"):
        parse_mob_data(renamed)


def test_rows_without_usable_numbers_are_skipped() -> None:
    parsed = parse_mob_data(
        '"Task","XP/Kill","Raw Kills/Hour"\n"Ghost","","120"\n"Imp","5","0"\n"Rat","3","60"\n'
    )

    assert set(parsed) == {"rat"}


def test_a_task_with_no_rate_data_is_counted_apart_from_unreachable_ones() -> None:
    # The distinction that matters: `coverage` is a fact about the map,
    # `unpriced` is a hole in the config, and conflating them reported "27%
    # reachable" for a master whose tasks were nearly all reachable.
    info = _info(
        slayerMasterTasks={"M": {"Known": {"Weight": 5}, "Unknown": {"Weight": 5}}}
    )
    heuristics = _heuristics(
        Known=SlayerTask(mean_count=100, xp_per_kill=10, kills_per_hour=100)
    )

    rate = master_rates(
        info, heuristics, reachable_monsters=frozenset(), valid_quests=frozenset(), levels={}
    )[0]

    assert rate.coverage == 0.5
    assert rate.unpriced == 0.5


def test_an_unreachable_task_is_not_counted_as_unpriced() -> None:
    info = _info(
        slayerMasterTasks={"M": {"Bats": {"Weight": 5}, "Bears": {"Weight": 5}}},
        slayerMonsters={"Bat": 1, "Bear": 1},
    )
    heuristics = _heuristics(
        Bats=SlayerTask(mean_count=100, xp_per_kill=10, kills_per_hour=100),
        Bears=SlayerTask(mean_count=100, xp_per_kill=10, kills_per_hour=100),
    )

    rate = master_rates(
        info, heuristics, reachable_monsters=frozenset({"Bear"}), valid_quests=frozenset(),
        levels={},
    )[0]

    assert rate.coverage == 0.5
    assert rate.unpriced == 0.0
