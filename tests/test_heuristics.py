"""Tests for the heuristics config: its defaults, its joins and its merge."""

from __future__ import annotations

import json
import pathlib
import re
from typing import Any

import pytest

from chunksim.store.cache import PACKAGED_OVERRIDES

PROJECT = pathlib.Path(__file__).resolve().parent.parent

from chunksim.model.chunkinfo import ChunkInfo
from chunksim.costing.heuristics import (
    TABLE_KINDS,
    DEFAULT_CURRENCY_PER_HOUR,
    burning_rate,
    PICKPOCKET_CYCLE_SECONDS,
    DEFAULT_KPH,
    DEFAULT_QUEST_HOURS,
    DEFAULT_XP_PER_HOUR,
    Rate,
    SlayerTask,
    activity_name,
    build_config,
    disagreements,
    hours_for_length,
    load,
    merge,
    primary_training_tasks,
    stems,
    streak_factor,
)
from chunksim.remote.skill_tables import SkillRow
from chunksim.remote.wiki import Assignment, MmgRates


def _info(**data: Any) -> ChunkInfo:
    return ChunkInfo(data)


# --- defaults --------------------------------------------------------------


def test_length_words_map_to_the_hours_plan_md_specifies() -> None:
    assert hours_for_length("Very Short") == 0.17
    assert hours_for_length("Short") == 1.0
    assert hours_for_length("Medium") == 2.0
    assert hours_for_length("Long") == 4.0
    assert hours_for_length("Very Long") == 6.0


def test_a_range_takes_its_midpoint() -> None:
    # About a fifth of quests hedge with a range; the en-dash is the wiki's.
    assert hours_for_length("Short – Medium") == 1.5
    assert hours_for_length("Long - Very Long") == 5.0


def test_an_unknown_length_falls_back_to_medium() -> None:
    assert hours_for_length("") == DEFAULT_QUEST_HOURS
    assert hours_for_length("Special") == DEFAULT_QUEST_HOURS


def test_always_is_certain_and_a_meaningless_word_is_none() -> None:
    heuristics = load({})

    assert heuristics.rarity("Always") == 1.0
    assert heuristics.rarity("rare") == heuristics.rarity("Rare")
    # `Varies`/`Unknown` say nothing; inventing a number would be worse than
    # reporting the item unpriced.
    assert heuristics.rarity("Varies") is None
    assert heuristics.rarity("Unknown") is None


def test_an_unjoined_monster_defaults_by_what_kind_it_is() -> None:
    heuristics = load(
        {}, boss_monsters=frozenset({"Zulrah"}), slayer_monsters=frozenset({"Gargoyle"})
    )

    assert heuristics.kills_per_hour("Zulrah") == Rate(DEFAULT_KPH["boss"], "default:boss")
    assert heuristics.kills_per_hour("Gargoyle").source == "default:slayer"
    assert heuristics.kills_per_hour("Goblin").value == DEFAULT_KPH["regular"]


def test_an_unjoined_training_method_reads_the_low_default() -> None:
    rate = load({}).xp_per_hour("Mine ~|sunstone rocks|~", "Mining")

    assert rate.value == DEFAULT_XP_PER_HOUR
    assert rate.match == "default"


# --- joins -----------------------------------------------------------------


def test_activity_name_takes_the_marked_span() -> None:
    assert (
        activity_name("Participate in ~|Underwater Agility and Thieving|~ for Agility xp")
        == "Underwater Agility and Thieving"
    )
    assert activity_name("Barrows") == "Barrows"


def test_primary_training_tasks_finds_only_the_primary_ones() -> None:
    info = _info(
        challenges={
            "Mining": {
                "Mine ~|sunstone rocks|~": {"Primary": True, "Level": 50},
                "Mine a ~|rune ore|~ once": {"Primary": False, "Level": 85},
            }
        }
    )

    assert primary_training_tasks(info) == {"Mine ~|sunstone rocks|~": "Mining"}


def _config(**kwargs: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "quest_pages": {},
        "mmg_pages": {},
        "assignments": {},
        "mob_data": {},
    }
    defaults.update(kwargs)
    info = defaults.pop("info")
    return build_config(info, **defaults)


def test_a_guide_joins_when_the_activity_contains_the_name() -> None:
    # The real case: `Killing General Graardor` for `General Graardor`.
    info = _info(drops={"General Graardor": {"Bandos chestplate": {"1": "1/381"}}})
    config = _config(
        info=info,
        mmg_pages={
            "Money making guide/Killing General Graardor": MmgRates(
                activity="Killing General Graardor", kph=27.0
            )
        },
    )

    assert config["monsters"]["General Graardor"]["value"] == 27.0
    # `Killing` is filler, so the identity-bearing words are identical - as
    # trustworthy as the names agreeing outright.
    assert config["monsters"]["General Graardor"]["match"] == "exact"


def test_a_plural_guide_title_still_joins() -> None:
    # `Adamant dragon` against `Killing adamant dragons` - without stemming
    # this falls through to nothing.
    info = _info(drops={"Adamant dragon": {"Bones": {"1": "Always"}}})
    config = _config(
        info=info,
        mmg_pages={"g": MmgRates(activity="Killing adamant dragons", kph=60.0)},
    )

    assert config["monsters"]["Adamant dragon"]["value"] == 60.0


def test_an_unrelated_guide_does_not_join() -> None:
    # An edit-distance fallback matched `Albatross` to `Barrows`; a wrong
    # rate reads as evidence, so no match is the right answer.
    info = _info(drops={"Albatross": {"Bones": {"1": "Always"}}})
    config = _config(info=info, mmg_pages={"g": MmgRates(activity="Barrows", kph=12.0)})

    assert "Albatross" not in config["monsters"]


def test_a_guide_that_does_not_count_kills_cannot_price_a_monster() -> None:
    """The real case: `Grinding unicorn horns` priced `Unicorn` at 9,000/hr.

    The join is correct - the guide really is about unicorns - but its `kph`
    counts horns ground, not unicorns killed. Only the label separates them.
    """
    info = _info(drops={"Unicorn": {"Unicorn horn": {"1": "Always"}}})
    config = _config(
        info=info,
        mmg_pages={
            "Money making guide/Grinding unicorn horns": MmgRates(
                activity="Grinding unicorn horns",
                kph=9000.0,
                kph_name="Horns per hour",
            )
        },
    )

    assert "Unicorn" not in config["monsters"]


def test_a_skilling_guide_still_prices_training() -> None:
    """Rejecting it as a *kill* rate must not reject it as an XP rate.

    Units per hour times XP per unit is exactly what a non-kill guide is for,
    so the two paths deliberately see different pools of guides.
    """
    info = _info(
        drops={"Unicorn": {"Unicorn horn": {"1": "Always"}}},
        challenges={
            "Herblore": {
                "Do ~|Grinding unicorn horns|~ for Herblore xp": {
                    "Primary": True,
                    "Level": 5,
                }
            }
        },
    )
    config = _config(
        info=info,
        mmg_pages={
            "g": MmgRates(
                activity="Grinding unicorn horns",
                kph=9000.0,
                kph_name="Horns per hour",
                experience={"Herblore": 1.0},
            )
        },
    )

    task = "Do ~|Grinding unicorn horns|~ for Herblore xp"
    assert "Unicorn" not in config["monsters"]
    assert config["training"][task]["Herblore"]["value"] == 9000.0


def test_a_training_method_is_priced_as_xp_per_unit_times_rate() -> None:
    info = _info(
        challenges={
            "Agility": {
                "Participate in ~|Underwater Agility and Thieving|~ for Agility xp": {
                    "Primary": True,
                    "Level": 1,
                }
            }
        }
    )
    config = _config(
        info=info,
        mmg_pages={
            "Money making guide/Underwater Agility and Thieving": MmgRates(
                activity="Underwater Agility and Thieving",
                kph=200.0,
                experience={"Agility": 4.5},
            )
        },
    )

    task = "Participate in ~|Underwater Agility and Thieving|~ for Agility xp"
    assert config["training"][task]["Agility"]["value"] == 900.0
    assert config["training"][task]["Agility"]["match"] == "exact"


def test_a_guide_without_this_skills_xp_cannot_price_it() -> None:
    info = _info(challenges={"Mining": {"Mine ~|Barrows|~": {"Primary": True}}})
    config = _config(
        info=info,
        mmg_pages={"g": MmgRates(activity="Barrows", kph=12.0, experience={"Prayer": 5.0})},
    )

    assert config["training"] == {}


def test_every_quest_gets_an_entry_even_without_a_page() -> None:
    info = _info(
        challenges={
            "Quest": {
                "~|Cook's Assistant|~ 1": {"BaseQuest": "Cook's Assistant"},
                "~|Nowt|~ 1": {"BaseQuest": "Nowt"},
            }
        }
    )
    config = _config(
        info=info,
        quest_pages={"Cook's Assistant": "{{Quest details|length = Very Short}}"},
    )

    assert config["quests"]["Cook's Assistant"] == {
        "hours": 0.17,
        "length": "Very Short",
        "difficulty": "",
        "source": "wiki",
    }
    # Present, defaulted, and flagged as such - there is always a line to fix.
    assert config["quests"]["Nowt"]["source"] == "default"
    assert config["quests"]["Nowt"]["hours"] == DEFAULT_QUEST_HOURS


def test_the_slayer_section_pairs_wiki_sizes_with_sheet_rates() -> None:
    info = _info(slayerMasterTasks={"Duradel": {"Aberrant spectres": {"Weight": 7}}})
    config = _config(
        info=info,
        assignments={"Duradel": [Assignment("Aberrant spectres", 7, 130, 200)]},
        mob_data={
            "aberrant spectres": SlayerTask(
                mean_count=0.0, xp_per_kill=106.0, kills_per_hour=340.0
            )
        },
    )

    entry = config["slayer"]["Duradel"]["Aberrant spectres"]
    assert entry["mean_count"] == 165.0
    assert (entry["xp_per_kill"], entry["kills_per_hour"]) == (106.0, 340.0)
    assert entry["source"] == "wiki+sheet"


def test_weights_are_not_copied_into_the_config() -> None:
    # The export owns them; duplicating would let the two disagree.
    info = _info(slayerMasterTasks={"Duradel": {"Bats": {"Weight": 7}}})
    config = _config(info=info, assignments={"Duradel": [Assignment("Bats", 7, 10, 20)]})

    assert "weight" not in config["slayer"]["Duradel"]["Bats"]


# --- the merge -------------------------------------------------------------


def test_an_override_wins_over_the_scrape() -> None:
    merged = merge(
        {"quests": {"Nowt": {"hours": 2.0, "length": "Medium"}}},
        {"quests": {"Nowt": {"hours": 9.0}}},
    )

    # Deep, so pinning the hours doesn't erase the length beside it.
    assert merged["quests"]["Nowt"] == {"hours": 9.0, "length": "Medium"}


def test_an_override_for_something_unscraped_is_kept() -> None:
    assert merge({}, {"monsters": {"X": {"value": 5.0}}})["monsters"]["X"]["value"] == 5.0


def test_disagreements_names_what_the_scrape_now_says() -> None:
    found = disagreements(
        {"quests": {"Nowt": {"hours": 2.0}, "Other": {"hours": 1.0}}},
        {"quests": {"Nowt": {"hours": 9.0}, "Other": {"hours": 1.0}}},
    )

    assert found == ["quests.Nowt.hours: 2.0 -> 9.0"]


def test_load_round_trips_a_generated_config() -> None:
    config = {
        "quests": {"Nowt": {"hours": 3.0, "length": "Long", "source": "wiki"}},
        "monsters": {"Zulrah": {"value": 30.0, "source": "mmg:x", "match": "exact"}},
        "training": {"t": {"Mining": {"value": 55.0, "source": "mmg:y"}}},
        "slayer": {"M": {"Bats": {"mean_count": 15.0, "xp_per_kill": 2.0, "kills_per_hour": 800.0}}},
        "rarities": {"varies": 0.5},
    }

    heuristics = load(config)

    assert heuristics.quest_hours("Nowt").hours == 3.0
    assert heuristics.kills_per_hour("Zulrah").value == 30.0
    assert heuristics.xp_per_hour("t", "Mining").value == 55.0
    assert heuristics.slayer["M"]["Bats"].kills_per_hour == 800.0
    # An override may add a rarity the defaults deliberately leave out.
    assert heuristics.rarity("Varies") == 0.5


def test_load_tolerates_a_malformed_entry() -> None:
    heuristics = load({"monsters": {"X": {"value": "fast"}}, "quests": "nonsense"})

    assert heuristics.kills_per_hour("X").value == 0.0
    assert heuristics.quests == {}


def test_stems_covers_the_irregular_plurals() -> None:
    # One rule always loses something: -ies wants `jelly`, -es wants `axe`,
    # -s wants `zombie`. Generating the candidates costs nothing.
    assert "jelly" in stems("jellies")
    assert "axe" in stems("axes")
    assert "zombie" in stems("zombies")
    assert stems("bloodveld") == {"bloodveld"}


def test_stems_undoes_the_f_to_ves_plural() -> None:
    """Slayer names four task categories this way and none matched without it.

    `Wolves`, `Elves`, `Dwarves` and `Werewolves` are all real task names, and
    -s/-es/-ies between them get none of `wolf`, `elf` or `dwarf`. Both `-f`
    and `-fe` go in because English does both.
    """
    assert "wolf" in stems("wolves")
    assert "elf" in stems("elves")
    assert "dwarf" in stems("dwarves")
    assert "werewolf" in stems("werewolves")
    assert "knife" in stems("knives")


def test_a_plural_task_matches_a_singular_sheet_row() -> None:
    # The real one: the export says `Jellies`, the spreadsheet says `Jelly`,
    # and `rstrip("s")` read the first as `jellie` so they never met.
    info = _info(slayerMasterTasks={"Krystilia": {"Jellies": {"Weight": 5}}})
    config = _config(
        info=info,
        assignments={"Krystilia": [Assignment("Jellies", 5, 100, 150)]},
        mob_data={
            "jelly": SlayerTask(mean_count=0.0, xp_per_kill=88.38, kills_per_hour=1500.0)
        },
    )

    entry = config["slayer"]["Krystilia"]["Jellies"]
    assert (entry["xp_per_kill"], entry["kills_per_hour"]) == (88.38, 1500.0)
    assert entry["mean_count"] == 125.0
    assert entry["source"] == "wiki+sheet"


def test_a_singular_wiki_row_sizes_a_plural_task() -> None:
    # `[[Ankou]]` on the wiki against `Ankous` in the export.
    info = _info(slayerMasterTasks={"Krystilia": {"Ankous": {"Weight": 6}}})
    config = _config(
        info=info, assignments={"Krystilia": [Assignment("Ankou", 6, 75, 125)]}
    )

    assert config["slayer"]["Krystilia"]["Ankous"]["mean_count"] == 100.0


def test_konars_location_suffix_is_stripped_before_lookup() -> None:
    # Konar keys 93 tasks `<task> - <location>`; the rates are recorded
    # against the task alone, so the suffix has to come off to find them.
    info = _info(
        slayerMasterTasks={
            "Konar quo Maten": {"Aberrant spectres - Catacombs of Kourend": {"Weight": 2}}
        }
    )
    config = _config(
        info=info,
        assignments={"K": [Assignment("Aberrant spectres", 2, 130, 200)]},
        mob_data={
            "aberrant spectre": SlayerTask(
                mean_count=0.0, xp_per_kill=106.0, kills_per_hour=340.0
            )
        },
    )

    # Keyed by the full name, since that is what the export asks for.
    entry = config["slayer"]["Konar quo Maten"]["Aberrant spectres - Catacombs of Kourend"]
    assert (entry["mean_count"], entry["kills_per_hour"]) == (165.0, 340.0)


def test_the_streak_factor_reproduces_the_wikis_worked_example() -> None:
    # The wiki puts a 1,000-task Krystilia streak at 44,375 points on a base
    # of 25. That figure is what settles the stacking question: only the
    # highest applicable milestone is paid, never the sum.
    assert 25 * 1000 * streak_factor() == pytest.approx(44_375)


def test_only_the_highest_milestone_is_paid() -> None:
    # Task 1,000 is also a 250th, a 100th, a 50th and a 10th. Summing them
    # gives 53,500 against the wiki's 44,375.
    assert 25 * 1000 * streak_factor() != pytest.approx(53_500)


def test_a_table_with_no_milestones_leaves_the_rate_alone() -> None:
    assert streak_factor({}) == 1.0


def test_a_single_milestone_amortises_over_its_interval() -> None:
    # Nine ordinary tasks and one paying 5x is (9 + 5) / 10.
    assert streak_factor({10: 5.0}) == pytest.approx(1.4)


def test_a_stackable_tasks_rate_reads_as_multi_target() -> None:
    """3,360 kills an hour is one every 1.07 seconds - chinchompas, not a weapon."""
    from chunksim.costing.heuristics import MULTI_TARGET_KPH, SlayerTask

    spiders = SlayerTask(mean_count=150, xp_per_kill=12.8, kills_per_hour=3360)
    ankous = SlayerTask(mean_count=150, xp_per_kill=98.0, kills_per_hour=1500)

    assert spiders.is_multi_target
    assert ankous.is_multi_target
    assert MULTI_TARGET_KPH == 1000.0


def test_an_ordinary_rate_does_not() -> None:
    """Black dragons at 195 an hour is somebody hitting one dragon."""
    from chunksim.costing.heuristics import SlayerTask

    assert not SlayerTask(
        mean_count=150, xp_per_kill=262.0, kills_per_hour=195
    ).is_multi_target


def test_the_threshold_is_conservative_and_says_so() -> None:
    """`Dust devils` at 950 is a bursting task and sits under the line.

    Recorded rather than fixed: the threshold is not trying to be clever, and
    an override is the place to correct a row that matters.
    """
    from chunksim.costing.heuristics import SlayerTask

    assert not SlayerTask(
        mean_count=150, xp_per_kill=105, kills_per_hour=950
    ).is_multi_target


def test_a_guide_named_exactly_is_not_given_away_by_containment() -> None:
    """**"Combat potion" is not "super combat potion".**

    `_best_match`'s containment tier is right far more often than not - a guide
    called "Cleaning grimy torstol" really is the one for cleaning torstol - but
    it cannot tell a padded title from a *different, better* item. `Mix a
    ~|combat potion|~` contains itself in "Making super combat potions" and
    inherited its 315,000 xp/hr, which under the band walk would open a
    315,000/hr band at level 36 and wipe out most of a Herblore climb.

    The rule needs no word list: if another method names that guide exactly,
    the guide is that method's. What is left has no rate at all, which is the
    honest answer - a method with no viable route should look like one.
    """
    info = ChunkInfo(
        {
            "challenges": {
                "Herblore": {
                    "Mix a ~|combat potion|~": {"Primary": True, "Level": 36},
                    "Mix a ~|super combat potion|~": {"Primary": True, "Level": 90},
                }
            }
        }
    )
    training = _config(
        info=info,
        mmg_pages={
            "Money making guide/Making super combat potions": MmgRates(
                kph=1500.0,
                experience={"Herblore": 210.0},
                activity="Super combat potion",
            )
        },
    )["training"]

    assert "Mix a ~|super combat potion|~" in training
    assert "Mix a ~|combat potion|~" not in training


def test_agility_and_thieving_join_the_wiki_tables_structurally() -> None:
    """**The join no guide could make.** A course joins on its own name, a
    shortcut and a stall on the object they act on, a pickpocket on the NPC -
    all exact strings, which is why there is no `contained` tier here."""
    info = ChunkInfo(
        {
            "challenges": {
                "Agility": {
                    "Access the ~|Falador Rooftop Course|~": {"Primary": True, "Level": 50},
                    "Access the Yanille climbing rocks ~|shortcut|~": {
                        "Primary": True,
                        "Level": 5,
                        "Objects": ["Climbing rocks (Yanille)"],
                    },
                },
                "Thieving": {
                    "Pickpocket a ~|farmer|~": {
                        "Primary": True,
                        "Level": 10,
                        "Output": "Farmer[+]",
                    },
                },
            }
        }
    )
    tables = {
        "courses": [SkillRow(name="Falador Rooftop Course", level=50, xp_per_hour=35_000.0)],
        "shortcuts": [SkillRow(name="Climbing rocks (Yanille)", level=5, experience=25.0)],
        "pickpockets": [SkillRow(name="Farmer", level=10, experience=14.5)],
    }

    config = build_config(
        info,
        quest_pages={},
        mmg_pages={},
        assignments={},
        mob_data={},
        skill_tables=tables,
    )
    training = config["training"]

    assert training["Access the ~|Falador Rooftop Course|~"]["Agility"]["value"] == 35_000.0
    # **A shortcut is priced by `costing/shortcuts.py`, not by this table** -
    # it needs the failure experience and the success curve, which a
    # `SkillRow` cannot carry - so the list alone leaves it unrated.
    assert "Access the Yanille climbing rocks ~|shortcut|~" not in training
    # `Farmer[+]` means "or its variants"; the wiki row is just `Farmer`.
    assert training["Pickpocket a ~|farmer|~"]["Thieving"]["value"] == pytest.approx(
        14.5 * 3600.0 / PICKPOCKET_CYCLE_SECONDS
    )
    assert training["Pickpocket a ~|farmer|~"]["Thieving"]["match"] == "exact"


def test_a_guide_that_names_the_method_exactly_keeps_it() -> None:
    """The table join outranks a *contained* guess but not an exact one - the
    same rule that settles every other contest in this module: the more
    specific claim wins."""
    info = ChunkInfo(
        {
            "challenges": {
                "Agility": {
                    "Access the ~|Agility Pyramid|~": {"Primary": True, "Level": 30}
                }
            }
        }
    )
    guides = {
        "Agility Pyramid": MmgRates(
            activity="Agility Pyramid",
            experience={"Agility": 1.0},
            kph=34_380.0,
            kph_name="Laps per hour",
        )
    }

    config = build_config(
        info,
        quest_pages={},
        mmg_pages=guides,
        assignments={},
        mob_data={},
        skill_tables={
            "courses": [SkillRow(name="Agility Pyramid", level=30, xp_per_hour=44_750.0)]
        },
    )

    entry = config["training"]["Access the ~|Agility Pyramid|~"]["Agility"]
    assert entry["value"] == 34_380.0
    assert entry["match"] == "exact"



def test_the_vaguer_of_two_contained_claims_loses_the_guide() -> None:
    """**A level-1 method inherited a level-66 rate.** `Chop ~|logs|~` is
    contained in "Cutting camphor logs" exactly as `Chop ~|camphor logs|~` is,
    and nothing named that guide exactly - so the existing exact rule never
    fired and the generic claim kept an 82,512/hr rate from level 1 upwards,
    which the band walk then applied to the whole climb.
    """
    info = ChunkInfo(
        {
            "challenges": {
                "Woodcutting": {
                    "Chop ~|logs|~": {"Primary": True, "Level": 1},
                    "Chop ~|camphor logs|~": {"Primary": True, "Level": 66},
                }
            }
        }
    )
    guides = {
        "Cutting camphor logs": MmgRates(
            activity="Cutting camphor logs",
            experience={"Woodcutting": 143.5},
            kph=575.0,
            kph_name="Logs cut per hour",
        )
    }

    training = build_config(
        info, quest_pages={}, mmg_pages=guides, assignments={}, mob_data={}
    )["training"]

    assert "Chop ~|camphor logs|~" in training
    assert "Chop ~|logs|~" not in training


def test_every_priced_currency_is_a_stated_figure_someone_can_correct() -> None:
    """**These are decisions, not measurements**, so they are pinned here: a
    silent edit to one moves every item bought with it. Marks of grace are the
    exception and come from the rooftop table, so only its floor is pinned.
    """
    assert DEFAULT_CURRENCY_PER_HOUR["Coins"] == 500_000.0
    assert DEFAULT_CURRENCY_PER_HOUR["Tokkul"] == 25_000.0
    assert DEFAULT_CURRENCY_PER_HOUR["Abyssal pearls"] == 40.0
    assert DEFAULT_CURRENCY_PER_HOUR["Tithe"] == 80.0
    assert DEFAULT_CURRENCY_PER_HOUR["Zeal Tokens"] == 200.0
    assert DEFAULT_CURRENCY_PER_HOUR["Mahogany Homes Reward Shop:Points"] == 100.0
    # 20 minutes a game plus a non-dedicated world's 2-minute wait, 2 tickets
    # for a scored draw: 60/11 an hour. User-stated method, wiki-checked
    # timing - see the constant's own comment.
    assert DEFAULT_CURRENCY_PER_HOUR["Castle Wars ticket"] == pytest.approx(60.0 / 11.0)
    # **Unqualified `Points` must stay unrated.** 127 store lines use the name
    # and they are not interchangeable; giving it a rate would hand Mage
    # Training Arena and Pest Control gear Mahogany Homes' pace.
    assert "Points" not in DEFAULT_CURRENCY_PER_HOUR


def test_default_shop_prices_fill_the_shop_the_scrape_cannot_reach() -> None:
    """`~|Castle Wars Ticket Exchange|~`'s wiki page is a hand-written stock
    table rather than a `{{Shop}}` infobox, which is the only shape
    `remote/stores.py`'s Bucket query reads - so nothing here ever comes from
    a re-scrape and the floor has to be right by itself."""
    from chunksim.costing.heuristics import DEFAULT_SHOP_PRICES

    prices = DEFAULT_SHOP_PRICES["~|Castle Wars Ticket Exchange|~"]
    assert prices["Decorative helm (red)"].price == 4.0
    assert prices["Decorative armour (red platebody)"].price == 8.0
    assert prices["Decorative shield (red)"].price == 6.0
    assert prices["Decorative helm (white)"].price == 40.0
    assert prices["Decorative armour (white platebody)"].price == 80.0
    assert prices["Decorative shield (white)"].price == 60.0
    assert prices["Decorative helm (gold)"].price == 400.0
    assert prices["Decorative armour (gold platebody)"].price == 800.0
    assert prices["Decorative shield (gold)"].price == 600.0
    assert {entry.currency for entry in prices.values()} == {"Castle Wars ticket"}


def test_the_scrape_would_win_a_collision_with_the_default_shop() -> None:
    """The same layering `DEFAULT_CURRENCY_PER_HOUR` gets: a shop the wiki's
    `{{Shop}}` scrape does reach always wins, merged shop by shop rather than
    wholesale so a scraped shop missing one item does not lose a default it
    never had."""
    from chunksim.costing.heuristics import load

    heuristics = load(
        {
            "shops": {
                "~|Castle Wars Ticket Exchange|~": {
                    "Decorative helm (red)": {"price": 999.0, "currency": "Coins"}
                }
            }
        }
    )

    prices = heuristics.shop_prices["~|Castle Wars Ticket Exchange|~"]
    assert prices["Decorative helm (red)"].price == 999.0
    assert prices["Decorative helm (red)"].currency == "Coins"
    # Everything the scrape did not mention keeps the hand-verified floor.
    assert prices["Decorative armour (red platebody)"].price == 8.0


def test_a_default_shop_with_no_scrape_entry_at_all_still_loads() -> None:
    from chunksim.costing.heuristics import load

    heuristics = load({})

    prices = heuristics.shop_prices["~|Castle Wars Ticket Exchange|~"]
    assert prices["Decorative helm (red)"].price == 4.0


def test_burning_a_log_is_an_inventory_at_a_time() -> None:
    """**Firemaking is a constant plus a number.** A fire every four ticks,
    27 logs to an inventory, then a ten-second bank - so normal logs are
    52,000 an hour and willow 117,000, which is what the skill does.

    Burning is not a `{{Recipe}}` and no guide covers the bottom of the skill,
    so the only rated method used to be magic logs at level 75 and
    **Firemaking 1 -> 99 priced at 1,738 hours** with 1,210 of them floored.
    """
    assert burning_rate(40.0) == pytest.approx(51_979, rel=1e-3)
    assert burning_rate(90.0) == pytest.approx(116_952, rel=1e-3)
    # Linear in the log's experience, since only the log varies.
    assert burning_rate(80.0) == pytest.approx(2 * burning_rate(40.0))


def test_a_table_answers_only_for_its_own_skill() -> None:
    """**Two tables are keyed on the same thing and mean different numbers.**

    The Firemaking table is keyed on the log (`Burn ~|magic logs|~` joins
    through `Items`) and so is the Woodcutting one (`Chop ~|magic logs|~`
    joins through `Output`). Tried in one fixed order for every skill -
    which was harmless only while no two tables shared a key space - the
    first match won, and `Chop ~|magic logs|~` was priced at the rate for
    *burning* a magic log. Woodcutting 1-99 came out at 35.3 hours against
    a true 176.4, which is roughly what the fastest method in the game does.
    """
    info = _info(
        challenges={
            "Woodcutting": {
                "Chop ~|magic logs|~": {
                    "Primary": True,
                    "Level": 75,
                    "Output": "Magic logs",
                    "Items": ["Magic logs"],
                }
            },
            "Firemaking": {
                "Burn ~|magic logs|~": {
                    "Primary": True,
                    "Level": 75,
                    "Items": ["Magic logs"],
                }
            },
        }
    )
    tables = {
        "burning": (SkillRow(name="Magic logs", level=75, experience=303.8),),
        "woodcutting": (
            SkillRow(name="Magic logs", level=75, xp_per_hour=27_500.0),
        ),
    }

    training = _config(info=info, skill_tables=tables)["training"]

    assert training["Chop ~|magic logs|~"]["Woodcutting"]["source"] == "wiki:woodcutting"
    assert training["Chop ~|magic logs|~"]["Woodcutting"]["value"] == 27_500.0
    assert training["Burn ~|magic logs|~"]["Firemaking"]["source"] == "wiki:burning"


def test_every_gathering_skill_now_has_a_table() -> None:
    """**Mining was refused twice and the refusal was wrong both times.**

    Its per-item table publishes experience per *action* (the figure
    `Module:Skill calc` already carries) and its summary table keys hourly
    figures by a prose method name - and from those two it was concluded that
    nothing joined. What that missed is the shape already proven on Hunter:
    three of its **section headings** name a rock the export names, each
    owning a `level -> XP/h` table of its own.

    So all four gathering skills have a table now. What differs is how many
    headings name something the export does: every one of Hunter's six, four
    of Fishing's twelve (`FISHING_BY_FISH`), three of Mining's six
    (`MINING_BY_ROCK`). The rest name techniques covering several things each,
    and are still refused.
    """
    assert set(TABLE_KINDS) == {
        "Agility", "Thieving", "Firemaking", "Woodcutting", "Hunter", "Fishing",
        "Mining", "Herblore",
        # Not a gathering skill and here for the opposite reason: dart
        # fletching is not tick-gated, so no page publishes an hourly figure
        # and the table states experience per *dart*.
        "Fletching",
        # Sailing is here because its guide caught up - when
        # `estimate.UNRATED_SKILLS` was written nothing published a rate for
        # any of its 27 methods, and the barracuda table now does.
        "Sailing",
        # Cooking is the third of the per-action kind, after darts and
        # Firemaking: a range's pace does not depend on what is on it.
        "Cooking",
        "Crafting",
    }


def test_the_giants_foundry_is_no_longer_pinned_by_hand() -> None:
    """**A pin that was standing in for a model, until there was one.**

    All six preform challenges were once unrated, so `training_options`
    dropped them and Smithing 1-99 walked on recipe tick-math: 874 hours,
    topped by a bronze platebody. They were then pinned to the five alloy
    tiers of Jagex's release patch notes, which took it to 144.5h.

    `costing/foundry.py` supersedes those. The patch notes are a *summary* -
    they describe five tiers where a player picks two metals and a ratio out
    of fifteen pairs and 27 splits, and the tier is the thing being chosen
    against, so a tier model cannot express that a lower-scoring alloy can be
    faster. The module derives from the strategy page's alloy table, the
    stated mould score and the main page's closed experience formula.

    **The pins had to go rather than merely be outranked**, because
    `training.training_options` lets a hand pin beat a computed method by
    design - which is right, and which is exactly why a pin left behind after
    its model arrives is silently load-bearing.
    """
    overrides = json.loads(PACKAGED_OVERRIDES.read_text())

    assert not [t for t in overrides["training"] if "Giants' Foundry" in t]


def test_the_giants_foundry_charges_28_bars_and_says_so_consistently() -> None:
    """**The rate was being spent with the bars free**, which is the material
    bias with a minigame behind it. A foundry challenge declares
    `Items: ["AdamantMats[+]*", "BucketOrGloves[+]"]` - family placeholders,
    not items - and `Output: None`, so no recipe joins it and nothing charged
    for the metal. Smithing 1-99 on `fray` read 54.5h.

    The wiki states both numbers the export does not: the crucible "needs to
    be filled with 28 bars worth of metal", and Jagex's alloy-tier table gives
    the average experience a sword. Those two are what `material_seconds_per_xp`
    is built from - bars per sword over experience per sword - and they are
    still needed now that `costing/foundry.py` owns the *rate*, because a
    module supplies what a method pays and not what it consumes.

    **Bars rather than the family's smithed members**, which the crucible also
    accepts: an item contributes one bar *less* than it cost to smith, so it is
    strictly worse per bar of value.
    """
    overrides = json.loads(PACKAGED_OVERRIDES.read_text())
    materials = {
        task: entry
        for task, entry in overrides["materials"].items()
        if "Giants' Foundry" in task
    }

    assert {
        task: entry["items"] for task, entry in materials.items()
    } == {
        "Forge a bronze ~|preform|~ in the Giants' Foundry": {"Bronze bar": 28},
        "Forge an iron ~|preform|~ in the Giants' Foundry": {"Iron bar": 28},
        "Forge a steel ~|preform|~ in the Giants' Foundry": {"Steel bar": 28},
        "Forge a mithril ~|preform|~ in the Giants' Foundry": {"Mithril bar": 28},
        "Forge an adamant ~|preform|~ in the Giants' Foundry": {"Adamantite bar": 28},
        "Forge a rune ~|preform|~ in the Giants' Foundry": {"Runite bar": 28},
    }

    #: Jagex's "Average XP per sword" column, which is what the `experience`
    #: field on each entry has to be for `material_seconds_per_xp` to come out
    #: as seconds of bar-gathering per experience.
    experience_per_sword = {
        "bronze": 2_400,
        "n iron": 2_400,
        "steel": 5_000,
        "mithril": 9_000,
        "n adamant": 15_000,
        "rune": 23_000,
    }
    for task, entry in materials.items():
        tier = task.split("Forge a")[-1].split("~|")[0].strip()
        assert entry["experience"] == experience_per_sword[tier], tier


def test_the_dart_materials_are_the_published_xp_per_dart() -> None:
    """**Where the material bias was measured winning a band, and now does not.**
    Nothing describes dart fletching as a `{{Recipe}}` - two clicks make a set
    of ten and no guide times it - so the tips priced at zero and dragon darts
    took the top of Fletching at 1,500,000 xp/hr.

    **The granularity cancels**, which is what makes this statable at all and
    is the opposite of what this project's notes first assumed: a set is ten
    darts and ten tips, and `material_seconds_per_xp` is seconds per action
    over XP per action, so ten-of-each over ten-times-the-XP is the same
    number as one over one. Only the *ratio* has to be right.

    So the entry is one tip and one feather against the table's published XP
    per dart - which is `parse_darts`' own figure, and the rate the scrape
    carries is that times `3600 / DART_CYCLE_SECONDS` (60,000 darts an hour).
    Measured: `fray` Fletching 21.3h -> 30.0h and `verf` 114.8h -> 244.9h,
    with dragon darts falling from 1,500,000 published to **197** effective.
    """
    overrides = json.loads(PACKAGED_OVERRIDES.read_text())
    darts = {
        task.split("~|")[1].removesuffix("|~"): entry
        for task, entry in overrides["materials"].items()
        if task.startswith("Fletch") and "dart|~" in task
    }

    assert {tier: entry["experience"] for tier, entry in darts.items()} == {
        "bronze dart": 1.8,
        "iron dart": 3.8,
        "steel dart": 7.5,
        "mithril dart": 11.2,
        "adamant dart": 15.0,
        "rune dart": 18.8,
        "amethyst dart": 21.0,
        "dragon dart": 25.0,
    }
    #: One tip and one feather a dart, both `*`-marked in the export.
    for tier, entry in darts.items():
        assert entry["items"] == {f"{tier.capitalize()} tip": 1, "Feather[+]": 1}, tier


@pytest.mark.real_export
def test_every_hand_material_names_a_task_the_export_carries(
    real_export: ChunkInfo,
) -> None:
    """A materials entry is keyed by the export's own task name, markup and
    all, and a typo would be silent: `material_seconds_per_xp` is looked up by
    that key, misses, and the method keeps its rate with nothing charged -
    exactly the state this file exists to fix.
    """
    overrides = json.loads(PACKAGED_OVERRIDES.read_text())
    known = {
        name
        for tasks in real_export.challenges.values()
        if isinstance(tasks, dict)
        for name in tasks
    }

    assert set(overrides["materials"]) <= known


def test_a_challenge_two_skills_claim_still_joins_for_both() -> None:
    """**`primary_training_tasks` keeps one skill per task**, so a challenge
    listed under several loses all but the last - 50 of the export's 2,657 are
    claimed by more than one skill.

    The three barbarian-fishing challenges are `Primary` for Agility, Fishing
    *and* Strength, and went to Strength - whose copy carries no `Output`, so
    Fishing silently lost a join it had a table row for. `_table_rates` walks
    per skill instead.
    """
    info = _info(
        challenges={
            "Fishing": {
                "Catch a ~|leaping trout|~": {
                    "Primary": True,
                    "Level": 48,
                    "Output": "Leaping trout",
                }
            },
            # Written last, so the task-keyed mapping would answer `Strength`.
            "Strength": {
                "Catch a ~|leaping trout|~": {"Primary": True, "Level": 48}
            },
        }
    )
    tables = {"fishing": (SkillRow(name="Leaping trout", level=48, xp_per_hour=23_000.0),)}

    training = _config(info=info, skill_tables=tables)["training"]

    assert training["Catch a ~|leaping trout|~"]["Fishing"]["value"] == 23_000.0
    assert training["Catch a ~|leaping trout|~"]["Fishing"]["source"] == "wiki:fishing"


def test_the_rifts_rate_has_already_paid_for_its_own_essence() -> None:
    """**The essence is mined inside the minigame** - that is most of what the
    twenty minutes is - and the published figure is what comes out of the
    whole thing. Charging the rune's essence on top would bill the same work
    twice, which is the mistake `_material_cost` was written to stop for
    recipe rates and which the Rift is the second case of.
    """
    from chunksim.costing.heuristics import (
        GOTR_SOURCE,
        TITHE_SOURCE,
        Heuristics,
        Rate,
    )
    from chunksim.costing.recipe_rates import RECIPE_SOURCE
    from chunksim.costing.spells import SPELL_SOURCE
    from chunksim.costing.training import _ALL_INCLUSIVE_SOURCES, _material_cost

    # Tithe Farm is the third and for the same reason: its seeds come out of
    # the minigame, so the published figure has already paid for them.
    # A spell is the fourth: `costing/spells.py` charges the challenge's own
    # `Items`, so adding the runes again would bill half of it twice.
    assert _ALL_INCLUSIVE_SOURCES == {
        RECIPE_SOURCE,
        GOTR_SOURCE,
        TITHE_SOURCE,
        SPELL_SOURCE,
    }

    heuristics = Heuristics(material_seconds_per_xp={"task": 0.3})
    charged = Rate(value=40_000.0, source="mmg:whatever", match="exact")
    inclusive = Rate(value=40_000.0, source=GOTR_SOURCE, match="exact")
    assert _material_cost(heuristics, "task", charged) == 0.3
    assert _material_cost(heuristics, "task", inclusive) == 0.0


@pytest.mark.real_export
def test_a_challenge_says_what_a_method_needs_and_never_how_much(
    real_export: ChunkInfo,
) -> None:
    """**Why `computed_rates` is the only source of `material_seconds_per_xp`.**

    That figure is `material seconds per action / xp per action`, and a
    challenge states neither. This pins the measurement, because the tempting
    fix - "take the materials off the challenge's own `Items` instead of off a
    recipe row" - reads as a small change and is not possible at all. Three
    paragraphs of CLAUDE.md used to propose it.

    `{{Recipe}}` is the only place the two numbers exist together, so the
    limitation is a consequence of the data rather than an oversight. If this
    test ever fails, upstream has started publishing one of them and the fix
    becomes real.
    """
    quantity = re.compile(r"\sx\s*[\d,]+")
    quantities: list[str] = []
    rewards: list[str] = []
    for skill, group in real_export.challenges.items():
        if not isinstance(group, dict):
            continue
        for task, challenge in group.items():
            if not isinstance(challenge, dict) or challenge.get("Primary") is not True:
                continue
            quantities += [
                f"{skill}/{task}: {item}"
                for item in challenge.get("Items") or ()
                if isinstance(item, str) and quantity.search(item)
            ]
            if "XpReward" in challenge:
                rewards.append(f"{skill}/{task}")

    assert quantities == [], "no primary challenge states how many of anything"

    # `XpReward` exists, but it is a one-off lump on quests and diaries - the
    # grant `training.quest_xp_grants` spends - and never a per-action rate.
    assert rewards == [], "no primary challenge states what one action pays"


def test_tithe_farm_joins_on_upstreams_own_category() -> None:
    """**The export labels the three fruits `Category: ["Tithe Farm"]`**, which
    is a better key than any name rule - one of them is spelled `Grow a
    ~|golovanova fruit|~ alt`, a spelling nothing would want to encode.

    Only the level-74 fruit is rated. The guide publishes one figure, "from
    level 74 onwards, 90,000-100,000 experience per hour", and says of the
    lower tiers only that experience "may be gained" - and the minigame's rate
    climbs steeply with the seed tier, so lending them that number would
    invent one.
    """
    from chunksim.costing.heuristics import TITHE_SOURCE, _table_rates
    from chunksim.remote.skill_tables import SkillRow

    chunk_info = ChunkInfo(
        {
            "challenges": {
                "Farming": {
                    "Grow a ~|golovanova fruit|~ alt": {
                        "Level": 34, "Primary": True, "Category": ["Tithe Farm"],
                    },
                    "Grow a ~|logavano fruit|~": {
                        "Level": 74, "Primary": True, "Category": ["Tithe Farm"],
                    },
                    "Grow a ~|dragonfruit tree|~": {
                        "Level": 81, "Primary": True, "Category": ["Normal Farming"],
                    },
                }
            }
        }
    )
    bands = (SkillRow(name="Tithe Farm", level=74, xp_per_hour=90_000.0),)
    rated = _table_rates(chunk_info, {"tithe": bands})

    assert set(rated) == {"Grow a ~|logavano fruit|~"}
    assert rated["Grow a ~|logavano fruit|~"]["Farming"].value == 90_000.0
    assert rated["Grow a ~|logavano fruit|~"]["Farming"].source == TITHE_SOURCE


def test_a_table_of_made_things_joins_on_output_and_not_on_items() -> None:
    """**`Items` is a join key, and for a table of made things that is a trap.**

    Firemaking needs it - `Burn ~|oak logs|~` names the log there - but the
    glass table's `Empty light orb` row matched `Craft a ~|light orb|~`, whose
    `Items` are `["Empty light orb*", "Cave goblin wire*"]`. That challenge is
    the *assembly* step, not the blowing: it took the blowing's 122,500/hr
    with no glass charged against it, and won the Crafting climb with it.
    """
    from chunksim.costing.heuristics import OUTPUT_ONLY_KINDS, _table_rates
    from chunksim.remote.skill_tables import SkillRow

    chunk_info = ChunkInfo(
        {
            "challenges": {
                "Crafting": {
                    "Craft an ~|empty light orb|~": {
                        "Level": 87, "Primary": True, "Output": "Empty light orb",
                        "Items": ["Molten glass*", "Glassblowing pipe"],
                    },
                    "Craft a ~|light orb|~": {
                        "Level": 87, "Primary": True, "Output": "Light orb",
                        "Items": ["Empty light orb*", "Cave goblin wire*"],
                    },
                }
            }
        }
    )
    rows = (SkillRow(name="Empty light orb", level=87, xp_per_hour=122_500.0),)
    rated = _table_rates(chunk_info, {"glass": rows})

    assert "glass" in OUTPUT_ONLY_KINDS
    assert set(rated) == {"Craft an ~|empty light orb|~"}, "the blowing, not the assembly"


def test_the_declared_config_branches_are_the_ones_load_reads() -> None:
    """**A list that has to be remembered is a list that goes stale.**

    `CONFIG_BRANCHES` is what anything handing a user an editable path speaks,
    so a branch `load` reads but this omits is a correction nobody can be
    pointed at, and one it names that `load` ignores is a path that silently
    does nothing. Read out of the source rather than restated, because
    restating it is the failure.
    """
    from chunksim.costing import heuristics as module

    source = pathlib.Path(module.__file__).read_text(encoding="utf-8")
    read = {
        found or fallback
        for found, fallback in re.findall(
            r'_entries\(config, "([a-z_]+)"\)|_mapping\(config, "([a-z_]+)"\)', source
        )
    }

    assert read == set(module.CONFIG_BRANCHES)
