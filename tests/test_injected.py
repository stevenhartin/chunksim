"""Tests for the challenges upstream builds at runtime."""

from __future__ import annotations

from typing import Any

import pytest

from chunksim.derive.injected import injected_challenges
from chunksim.derive.pipeline import Derived
from chunksim.model.chunkinfo import ChunkInfo

_QUEST_CAPE = "Buy the quest point cape*"
_MAX_CAPE = "Buy the ~|Max cape|~"


def _info(**data: Any) -> ChunkInfo:
    return ChunkInfo(data)


def _quests() -> ChunkInfo:
    return _info(
        challenges={
            "Quest": {
                "~|Cook's Assistant|~ 1": {"QuestPoints": 1},
                "~|Dragon Slayer I|~ 1": {"QuestPoints": 2},
                "~|Not a quest|~": {},
            }
        }
    )


def test_the_quest_cape_needs_only_its_chunk() -> None:
    """No rule guards it - upstream gates the quest point cape on holding
    12338 and nothing else, which is why both cached maps were missing it."""
    definitions = injected_challenges(_quests(), {"12338": "12338"}, {})

    assert list(definitions) == ["Nonskill"]
    assert list(definitions["Nonskill"]) == [_QUEST_CAPE]


def test_each_cape_answers_only_to_its_own_chunk() -> None:
    """The two are independent: holding Mac's hut says nothing about the Wise
    Old Man's house, and a map holding neither gets an empty overlay."""
    mac_only = injected_challenges(_quests(), {"11063": "11063"}, {"Skillcape": True})

    assert list(mac_only) == ["Extra"]
    assert list(mac_only["Extra"]) == [_MAX_CAPE]
    assert injected_challenges(_quests(), {}, {"Skillcape": True}) == {}


def test_the_max_cape_needs_the_rule_and_the_chunk() -> None:
    held = {"11063": "11063"}

    assert _MAX_CAPE in injected_challenges(_quests(), held, {"Skillcape": True})["Extra"]
    assert injected_challenges(_quests(), held, {"Skillcape": False}) == {}
    assert injected_challenges(_quests(), {}, {"Skillcape": True}) == {}


def test_the_quest_cape_bar_is_the_export_summed() -> None:
    """`QuestPointsNeeded` is computed, not constant: upstream totals every
    `QuestPoints` in the export, so adding a quest raises the bar. A `Quest`
    entry carrying none contributes nothing rather than raising."""
    definitions = injected_challenges(_quests(), {"12338": "12338"}, {})

    assert definitions["Nonskill"][_QUEST_CAPE]["QuestPointsNeeded"] == 3


def test_membership_counts_whatever_the_chunk_maps_to() -> None:
    """Upstream tests the chunk list with `hasOwnProperty`, and this
    project's decoded `unlocked` maps an id to itself rather than to `True`."""
    assert injected_challenges(_quests(), {"12338": False}, {})["Nonskill"]


def test_the_overlay_leaves_the_original_alone() -> None:
    base = _info(challenges={"Nonskill": {"Something": {"Level": 1}}}, chunks={"1": {}})

    overlaid = base.with_challenges({"Nonskill": {"New": {"Level": 2}}})

    assert set(overlaid.challenges["Nonskill"]) == {"Something", "New"}
    assert set(base.challenges["Nonskill"]) == {"Something"}
    # Everything else is the same data, not a copy of it.
    assert overlaid.chunks is base.chunks


def test_an_empty_overlay_is_the_same_object() -> None:
    base = _info(challenges={"Nonskill": {}})

    assert base.with_challenges({}) is base


def test_derived_carries_no_injections_by_default() -> None:
    """`Derived.injected` has to default, or every test and every cached
    derivation built before it would need rewriting."""
    assert "injected" in Derived.__dataclass_fields__


@pytest.mark.real_cache
def test_the_quest_cape_is_reported_unjudgeable_rather_than_valid(
    real_derived: Derived,
) -> None:
    """The oracle regression this shape exists to prevent.

    Forcing the injected cape valid - which is what upstream's own `valids`
    seeding looks like in isolation - made `Quest point cape (t)` a reachable
    item, and that made `Perform the Quest point cape emote` an active
    Lumbridge Elite diary task on a map where upstream lists neither. The
    definition is overlaid so the challenge exists; its `QuestPointsNeeded`
    gate is unported, so it lands in `unsupported` and seeds nothing.
    """
    assert real_derived.injected == {
        "Nonskill": {_QUEST_CAPE: real_derived.injected["Nonskill"][_QUEST_CAPE]}
    }
    assert f"Nonskill/{_QUEST_CAPE}" in real_derived.challenges.unsupported
    assert _QUEST_CAPE not in real_derived.challenges.valid.get("Nonskill", {})
    assert "Quest point cape (t)" not in real_derived.challenges.available_items
