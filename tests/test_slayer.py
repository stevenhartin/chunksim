"""Tests for the slayer rate model.

The first test is the load-bearing one: the two-task master is worked through
by hand, so the weighting is pinned by arithmetic rather than by whatever the
code happens to do.
"""

from __future__ import annotations

from typing import Any

import pytest

from fray_claude.chunkinfo import ChunkInfo
from fray_claude.heuristics import (
    DEFAULT_SLAYER_XP_PER_HOUR,
    Heuristics,
    SlayerTask,
    Superior,
)
from fray_claude.slayer import (
    SheetFormatError,
    best_master,
    master_rates,
    parse_mob_data,
    parse_task_lengths,
    superior_rolls_per_hour,
    superior_table_items,
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


def _heuristics(*, master: str = "M", **tasks: SlayerTask) -> Heuristics:
    """A per-master slayer table. Every master in a fixture shares it, so a
    test naming two masters does not have to restate the rates."""
    table = {name.replace("_", " "): rate for name, rate in tasks.items()}
    return Heuristics(slayer=_everywhere(table))


def _everywhere(table: dict[str, SlayerTask]) -> dict[str, dict[str, SlayerTask]]:
    return {name: dict(table) for name in ("M", "Slow", "Fast", "Duradel", "Konar quo Maten")}


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
        valid={},
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
        info, heuristics, reachable_monsters=frozenset(), valid={}, levels={}
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
        info, heuristics, reachable_monsters=frozenset(), valid={},
        levels={"Slayer": 50},
    )[0]

    # B is never offered at all, so it is not a skip and not a cost - it
    # simply never comes up. Coverage is of what *is* offered.
    assert [task.task for task in rate.tasks] == ["A"]
    assert rate.offered == 0.5
    assert rate.coverage == 1.0
    assert rate.skip_rate == 0.0


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
        info, heuristics, reachable_monsters=frozenset(), valid={}, levels={}
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
        info, heuristics, reachable_monsters=frozenset({"Bear"}), valid={},
        levels={},
    )[0]

    assert [task.task for task in rate.tasks] == ["Bears"]
    assert rate.coverage == 0.25


def test_an_unpriced_task_is_folded_in_at_the_poor_default() -> None:
    # Excluding it flattered whoever had the most gaps: a master's rate is a
    # mixture over what it assigns, so dropping half of it silently
    # reweighted the rest.
    info = _info(slayerMasterTasks={"M": {"A": {"Weight": 1}, "B": {"Weight": 1}}})
    heuristics = _heuristics(A=SlayerTask(mean_count=100, xp_per_kill=10, kills_per_hour=100))

    rate = master_rates(
        info, heuristics, reachable_monsters=frozenset(), valid={}, levels={}
    )[0]

    assert sorted(task.task for task in rate.tasks) == ["A", "B"]
    assert [task.defaulted for task in rate.tasks if task.task == "B"] == [True]
    # A alone is 1,000 xp/hr; B comes in at the 7,000 default, so the mixture
    # lands between the two rather than pretending B is not assigned.
    assert 1_000 < rate.xp_per_hour < DEFAULT_SLAYER_XP_PER_HOUR


def test_a_defaulted_task_takes_a_typical_assignment_length() -> None:
    # Nothing is known about how long it takes, so it gets the master's own
    # typical length - assuming a duration too would be a second invention.
    info = _info(slayerMasterTasks={"M": {"A": {"Weight": 1}, "B": {"Weight": 1}}})
    heuristics = _heuristics(A=SlayerTask(mean_count=100, xp_per_kill=10, kills_per_hour=50))

    rate = master_rates(
        info, heuristics, reachable_monsters=frozenset(), valid={}, levels={}
    )[0]
    defaulted = next(task for task in rate.tasks if task.defaulted)

    assert defaulted.hours == pytest.approx(2.0)  # A is 100/50 = 2h
    assert defaulted.xp / defaulted.hours == pytest.approx(DEFAULT_SLAYER_XP_PER_HOUR)


def test_a_master_with_nothing_assignable_is_reported_at_zero() -> None:
    # Zero rather than absent, so a caller can tell "cannot train here" from
    # "no such master". Nothing *assignable* - an assignable task with no
    # data is defaulted rather than dropped.
    info = _info(
        slayerMasterTasks={"M": {"A": {"Weight": 1, "Level": 90}}},
    )

    rates = master_rates(
        info, Heuristics(), reachable_monsters=frozenset(), valid={}, levels={"Slayer": 3}
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
            info, heuristics, reachable_monsters=frozenset(), valid={},
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
        info, heuristics, reachable_monsters=frozenset(), valid={}, levels={}
    )[0]

    # Both halves are assignable, so coverage is full; half of it is a
    # guess, which is what `unpriced` is for. The two are orthogonal.
    assert rate.coverage == 1.0
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
        info, heuristics, reachable_monsters=frozenset({"Bear"}), valid={},
        levels={},
    )[0]

    assert rate.coverage == 0.5
    assert rate.unpriced == 0.0


def test_a_prerequisite_is_checked_in_its_own_category() -> None:
    # `Tasks` maps a name to its *category*, and the category was being
    # thrown away: every prerequisite was looked up under `Quest`, so
    # Krystilia's `Magic axes` (a Thieving unlock) could never be assigned.
    info = _info(
        slayerMasterTasks={
            "M": {
                "Magic axes": {
                    "Weight": 1,
                    "Tasks": {"Unlock the ~|door (Magic axe hut)|~": "Thieving"},
                }
            }
        }
    )
    heuristics = _heuristics(
        Magic_axes=SlayerTask(mean_count=100, xp_per_kill=10, kills_per_hour=100)
    )

    granted = master_rates(
        info,
        heuristics,
        reachable_monsters=frozenset(),
        valid={"Thieving": {"Unlock the ~|door (Magic axe hut)|~": True}},
        levels={},
    )[0]
    refused = master_rates(
        info,
        heuristics,
        reachable_monsters=frozenset(),
        valid={"Quest": {"Unlock the ~|door (Magic axe hut)|~": True}},
        levels={},
    )[0]

    assert [task.task for task in granted.tasks] == ["Magic axes"]
    assert refused.tasks == ()


def test_a_quest_prerequisite_may_be_a_single_step() -> None:
    # `Desert Treasure I 7c1`, not `Complete the quest` - so the lookup has
    # to be by name rather than by matching a completion entry.
    info = _info(
        slayerMasterTasks={
            "M": {
                "Dust devils": {
                    "Weight": 1,
                    "Tasks": {"~|Desert Treasure I|~ 7c1": "Quest"},
                }
            }
        }
    )
    heuristics = _heuristics(
        Dust_devils=SlayerTask(mean_count=100, xp_per_kill=10, kills_per_hour=100)
    )

    rate = master_rates(
        info,
        heuristics,
        reachable_monsters=frozenset(),
        valid={"Quest": {"~|Desert Treasure I|~ 7c1": True}},
        levels={},
    )[0]

    assert [task.task for task in rate.tasks] == ["Dust devils"]


def test_an_entrys_chunks_gate_is_honoured() -> None:
    info = _info(slayerMasterTasks={"M": {"Jellies": {"Weight": 1, "Chunks": ["1234"]}}})
    heuristics = _heuristics(
        Jellies=SlayerTask(mean_count=100, xp_per_kill=10, kills_per_hour=100)
    )
    kwargs: dict[str, Any] = {
        "reachable_monsters": frozenset(),
        "valid": {},
        "levels": {},
    }

    assert master_rates(info, heuristics, unlocked={"1234": True}, **kwargs)[0].tasks
    assert master_rates(info, heuristics, unlocked={"9999": True}, **kwargs)[0].tasks == ()


def test_a_skills_requirement_is_honoured() -> None:
    info = _info(
        slayerMasterTasks={"M": {"Aviansies": {"Weight": 1, "Skills": {"Agility": 60}}}}
    )
    heuristics = _heuristics(
        Aviansies=SlayerTask(mean_count=100, xp_per_kill=10, kills_per_hour=100)
    )

    met = master_rates(
        info, heuristics, reachable_monsters=frozenset(), valid={}, levels={"Agility": 70}
    )[0]
    unmet = master_rates(
        info, heuristics, reachable_monsters=frozenset(), valid={}, levels={"Agility": 40}
    )[0]

    assert met.tasks and unmet.tasks == ()


def test_a_fractional_weight_counts() -> None:
    # Konar splits a task across locations and gives each a third of the
    # weight (1.67). An `isinstance(x, int)` test dropped all 93 of her tasks.
    info = _info(
        slayerMasterTasks={
            "Konar quo Maten": {
                "Aberrant spectres - Catacombs": {"Weight": 1.67},
                "Aberrant spectres - Slayer Tower": {"Weight": 1.67},
            }
        }
    )
    heuristics = Heuristics(
        slayer=_everywhere(
            {
                "Aberrant spectres - Catacombs": SlayerTask(100, 10, 100),
                "Aberrant spectres - Slayer Tower": SlayerTask(100, 10, 100),
            }
        )
    )

    rate = master_rates(
        info, heuristics, reachable_monsters=frozenset(), valid={}, levels={}
    )[0]

    assert len(rate.tasks) == 2
    assert rate.coverage == pytest.approx(1.0)


_LENGTHS = (
    '"Duradel Tasks","Min","Max","eMin","eMax",'
    '"Konar Tasks","Location","Min","Max","eMin","eMax",'
    '"Krystilia Tasks","Min","Max","eMin","eMax"\n'
    '"Abyssal Demon","130","200","200","250",'
    '"Abyssal Demon","Catacombs","120","170","200","250",'
    '"Abyssal Demons","75","125","200","250"\n'
    '"Jelly","120","170","","",'
    '"","","","","","",'
    '"Jelly","100","150","",""\n'
)


def test_task_lengths_are_read_per_master() -> None:
    # Flattening looks harmless and is not: the sheet writes Duradel's row
    # `Abyssal Demon` and Krystilia's `Abyssal Demons`, so a flat table keeps
    # both and every master matches whichever spelling looks closest.
    lengths = parse_task_lengths(_LENGTHS)

    assert lengths["Duradel"]["abyssal demon"].mean_count == 165.0
    assert lengths["Krystilia"]["abyssal demons"].mean_count == 100.0
    assert lengths["Krystilia"]["jelly"].mean_count == 125.0


def test_the_extra_location_column_does_not_shift_the_numbers() -> None:
    # Konar's group is a column wider than the others, so the Min/Max labels
    # are found inside each group rather than at a fixed offset.
    assert parse_task_lengths(_LENGTHS)["Konar"]["abyssal demon"].mean_count == 145.0


def test_extended_sizes_are_read_where_they_exist() -> None:
    lengths = parse_task_lengths(_LENGTHS)

    assert lengths["Duradel"]["abyssal demon"].extended_count == 225.0
    # Most tasks have none, and an absent one is 0.0 rather than a guess.
    assert lengths["Duradel"]["jelly"].extended_count == 0.0


def test_a_task_uses_its_ordinary_size_unless_extended_is_set() -> None:
    ordinary = SlayerTask(mean_count=100, xp_per_kill=10, kills_per_hour=100, extended_count=225)
    extended = SlayerTask(
        mean_count=100, xp_per_kill=10, kills_per_hour=100, extended_count=225, extended=True
    )

    # Extended is a paid unlock; assuming it would lengthen every task for a
    # player who has not bought it.
    assert ordinary.count == 100
    assert extended.count == 225


def test_extended_with_no_extended_size_falls_back() -> None:
    task = SlayerTask(mean_count=100, xp_per_kill=10, kills_per_hour=100, extended=True)

    assert task.count == 100


def test_the_extended_flag_lengthens_the_average_assignment() -> None:
    info = _info(slayerMasterTasks={"M": {"A": {"Weight": 1}}})
    plain = Heuristics(
        slayer={"M": {"A": SlayerTask(100, 10, 100, extended_count=200)}}
    )
    longer = Heuristics(
        slayer={"M": {"A": SlayerTask(100, 10, 100, extended_count=200, extended=True)}}
    )
    kwargs: dict[str, Any] = {
        "reachable_monsters": frozenset(),
        "valid": {},
        "levels": {},
    }

    assert master_rates(info, plain, **kwargs)[0].average_hours == pytest.approx(1.0)
    assert master_rates(info, longer, **kwargs)[0].average_hours == pytest.approx(2.0)


def _superior_info() -> ChunkInfo:
    return ChunkInfo(
        {
            "slayerMasterTasks": {
                "M": {"Abyssal demons": {"Weight": 1}, "Bats": {"Weight": 1}}
            },
            "slayerMonsters": {"Abyssal demon": 85, "Bat": 1},
            "codeItems": {
                "dropTables": {
                    "SuperiorDropTable+": {"Imbued heart": "1/8@1", "Dust battlestaff": "3/8@1"}
                }
            },
            "skillItems": {
                "Slayer": {"Greater abyssal demon": {"SuperiorDropTable+": {"1": "1/2"}}}
            },
        }
    )


def _superior_heuristics() -> Heuristics:
    return Heuristics(
        slayer={
            "M": {
                "Abyssal demons": SlayerTask(100, 10, 100),
                "Bats": SlayerTask(100, 10, 100),
            }
        },
        superiors={
            "Greater abyssal demon": Superior("Greater abyssal demon", "Abyssal demon", 1 / 200)
        },
    )


def test_superior_rolls_aggregate_over_a_masters_whole_task_list() -> None:
    # Half the assignments are abyssal demons; each is 100 kills at 1/200
    # supers, and each super rolls the table at 1/2. So per assignment:
    #   0.5 * 100 * (1/200) * (1/2) = 0.125 rolls
    # An assignment takes 100/100 = 1h, so 0.125 rolls an hour.
    rate = master_rates(
        _superior_info(),
        _superior_heuristics(),
        reachable_monsters=frozenset({"Abyssal demon", "Bat"}),
        valid={},
        levels={},
    )[0]

    rolls = superior_rolls_per_hour(rate, _superior_info(), _superior_heuristics())

    assert rolls == pytest.approx(0.125)


def test_a_task_with_no_superior_contributes_nothing() -> None:
    # Bats have no superior, so they dilute the rate rather than adding to
    # it - which is exactly right, that time is spent not seeing supers.
    info = _superior_info()
    heuristics = _superior_heuristics()
    only_bats = ChunkInfo({**info.data, "slayerMasterTasks": {"M": {"Bats": {"Weight": 1}}}})

    rate = master_rates(
        only_bats,
        heuristics,
        reachable_monsters=frozenset({"Bat"}),
        valid={},
        levels={},
    )[0]

    assert superior_rolls_per_hour(rate, only_bats, heuristics) == 0.0


def test_the_shared_table_is_read_with_its_shares() -> None:
    shares = superior_table_items(_superior_info())

    assert shares == {"Imbued heart": pytest.approx(1 / 8), "Dust battlestaff": pytest.approx(3 / 8)}


def test_a_plural_task_finds_its_singular_monster() -> None:
    # `rstrip("s")` lived here too and read `Jellies` as `jellie`, so
    # Krystilia's jelly task matched no monster, found no superior, and
    # contributed nothing at all to her superior rate.
    info = ChunkInfo(
        {
            "slayerMasterTasks": {"M": {"Jellies": {"Weight": 1}}},
            "slayerMonsters": {"Jelly": 52},
            "codeItems": {"dropTables": {"SuperiorDropTable+": {"Imbued heart": "1/8@1"}}},
            "skillItems": {"Slayer": {"Vitreous Jelly": {"SuperiorDropTable+": {"1": "1/2"}}}},
        }
    )
    heuristics = Heuristics(
        slayer={"M": {"Jellies": SlayerTask(100, 10, 100)}},
        superiors={"Vitreous Jelly": Superior("Vitreous Jelly", "Jelly", 1 / 200)},
    )

    rate = master_rates(
        info, heuristics, reachable_monsters=frozenset({"Jelly"}), valid={}, levels={}
    )[0]

    assert superior_rolls_per_hour(rate, info, heuristics) > 0


def test_the_points_delta_matches_the_worked_example() -> None:
    # Two of three tasks doable, 10 points a completion, 30 a skip:
    #   (2/3)*10 - (1/3)*30 = 6.67 - 10 = -3.33 points per assignment.
    info = _info(
        slayerMasterTasks={
            "M": {
                "A": {"Weight": 1},
                "B": {"Weight": 1},
                "C": {"Weight": 1, "Chunks": ["9999"]},
            }
        }
    )
    heuristics = Heuristics(
        slayer={"M": {name: SlayerTask(100, 10, 100) for name in "ABC"}},
        master_points={"M": 10.0},
    )

    rate = master_rates(
        info,
        heuristics,
        reachable_monsters=frozenset(),
        valid={},
        levels={},
        unlocked={"1": True},
    )[0]

    assert rate.skip_rate == pytest.approx(1 / 3)
    assert rate.points_delta == pytest.approx(-10 / 3)


def test_a_task_the_master_never_offers_is_not_a_skip() -> None:
    # Level- and quest-gated tasks are not offered at all, so they cost
    # nothing. Only a task you are *handed* and cannot go to costs points.
    info = _info(
        slayerMasterTasks={"M": {"A": {"Weight": 1}, "B": {"Weight": 1, "Level": 90}}}
    )
    heuristics = Heuristics(
        slayer={"M": {"A": SlayerTask(100, 10, 100), "B": SlayerTask(100, 10, 100)}},
        master_points={"M": 10.0},
    )

    rate = master_rates(
        info, heuristics, reachable_monsters=frozenset(), valid={}, levels={"Slayer": 50}
    )[0]

    assert rate.offered == 0.5
    assert rate.skip_rate == 0.0
    assert rate.points_delta == pytest.approx(10.0)


def test_an_unreachable_offered_task_costs_a_skip() -> None:
    info = _info(
        slayerMasterTasks={"M": {"A": {"Weight": 1}, "B": {"Weight": 1, "Chunks": ["9999"]}}}
    )
    heuristics = Heuristics(
        slayer={"M": {"A": SlayerTask(100, 10, 100), "B": SlayerTask(100, 10, 100)}},
        master_points={"M": 10.0},
    )

    rate = master_rates(
        info,
        heuristics,
        reachable_monsters=frozenset(),
        valid={},
        levels={},
        unlocked={"1": True},
    )[0]

    assert rate.offered == 1.0
    assert rate.skip_rate == 0.5
    # 0.5*10 - 0.5*30 = -10
    assert rate.points_delta == pytest.approx(-10.0)


def test_the_published_point_values_are_used_by_default() -> None:
    info = _info(slayerMasterTasks={"Krystilia": {"A": {"Weight": 1}}})
    heuristics = Heuristics(slayer={"Krystilia": {"A": SlayerTask(100, 10, 100)}})

    rate = master_rates(
        info, heuristics, reachable_monsters=frozenset(), valid={}, levels={}
    )[0]

    assert rate.points_per_task == 25.0
    assert rate.skip_cost == 30.0


def test_an_unknown_skill_level_does_not_block_a_task() -> None:
    # The map records no skill levels, so treating a missing one as level 1
    # blocks every task with a requirement outside the handful `passiveSkill`
    # happens to name. Vannaka's basilisks want Defence 20 and read as "never
    # offered" - which costs nothing - instead of "offered and unreachable",
    # which costs a skip.
    info = _info(
        slayerMasterTasks={
            "M": {"Basilisks": {"Weight": 8, "Level": 15, "Skills": {"Defence": 20}}}
        }
    )
    heuristics = Heuristics(slayer={"M": {"Basilisks": SlayerTask(100, 10, 100)}})

    offered = master_rates(
        info, heuristics, reachable_monsters=frozenset(), valid={}, levels={"Slayer": 45}
    )[0]
    blocked = master_rates(
        info,
        heuristics,
        reachable_monsters=frozenset(),
        valid={},
        levels={"Slayer": 45, "Defence": 3},
    )[0]

    # Unknown Defence: assumed met, so the task is offered.
    assert offered.offered == 1.0
    # A Defence level we *do* know, and it is short: genuinely not offered.
    assert blocked.offered == 0.0
