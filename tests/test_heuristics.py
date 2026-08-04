"""Tests for the heuristics config: its defaults, its joins and its merge."""

from __future__ import annotations

from typing import Any

from fray_claude.chunkinfo import ChunkInfo
from fray_claude.heuristics import (
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
)
from fray_claude.wiki import Assignment, MmgRates


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
    assert config["monsters"]["General Graardor"]["match"] == "contained"


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

    entry = config["slayer"]["Aberrant spectres"]
    assert entry["mean_count"] == 165.0
    assert (entry["xp_per_kill"], entry["kills_per_hour"]) == (106.0, 340.0)
    assert entry["source"] == "wiki+sheet"


def test_weights_are_not_copied_into_the_config() -> None:
    # The export owns them; duplicating would let the two disagree.
    info = _info(slayerMasterTasks={"Duradel": {"Bats": {"Weight": 7}}})
    config = _config(info=info, assignments={"Duradel": [Assignment("Bats", 7, 10, 20)]})

    assert "weight" not in config["slayer"]["Bats"]


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
        "slayer": {"Bats": {"mean_count": 15.0, "xp_per_kill": 2.0, "kills_per_hour": 800.0}},
        "rarities": {"varies": 0.5},
    }

    heuristics = load(config)

    assert heuristics.quest_hours("Nowt").hours == 3.0
    assert heuristics.kills_per_hour("Zulrah").value == 30.0
    assert heuristics.xp_per_hour("t", "Mining").value == 55.0
    assert heuristics.slayer["Bats"].kills_per_hour == 800.0
    # An override may add a rarity the defaults deliberately leave out.
    assert heuristics.rarity("Varies") == 0.5


def test_load_tolerates_a_malformed_entry() -> None:
    heuristics = load({"monsters": {"X": {"value": "fast"}}, "quests": "nonsense"})

    assert heuristics.kills_per_hour("X").value == 0.0
    assert heuristics.quests == {}
