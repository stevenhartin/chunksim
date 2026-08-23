"""The bounty scrape: the task table and the sea monsters' health."""

from __future__ import annotations

import pytest

from chunksim.remote import bounty

_TASKS = """
{{BountyTaskLine|level=50|xp=14575|noticeBoard=Catherby|monster=Albatross|item=Albatross beak|qty=5|rarity=1/10|taskId=465}}
|-
{{BountyTaskLine|level=50|xp=14575|noticeBoard=Brimhaven|monster=Albatross|item=Albatross feather|qty=20|rarity=1/2|taskId=469}}
|-
{{BountyTaskLine|level=|xp=|noticeBoard=Nowhere|monster=Ghost|item=Nothing|qty=|rarity=1/2|taskId=0}}
"""

_COMBAT = """
==Monsters==
Some prose about krakens.
{| class="wikitable"
|-
|[[Dolphin]]
|45
|{{Yes|No}}
|-
|[[Mogre (sea)|Mogre]]
|59
|{{Yes|No}}
|-
|[[Albatross]]
|135
|{{No|Yes}}
|}
===Notable drops===
|[[Orca]]
|999
"""


class TestTheTaskTable:
    def test_rows_parse(self) -> None:
        tasks = bounty.parse_tasks(_TASKS)
        assert [t.item for t in tasks] == ["Albatross beak", "Albatross feather"]
        assert tasks[0].quantity == 5 and tasks[0].rarity == "1/10"

    def test_a_row_with_no_level_or_payout_is_dropped(self) -> None:
        assert len(bounty.parse_tasks(_TASKS)) == 2

    def test_kills_is_quantity_over_rarity(self) -> None:
        """The mean of a negative binomial, which is the honest figure for
        something run for hours."""
        beak, feather = bounty.parse_tasks(_TASKS)
        assert beak.kills == 50.0
        assert feather.kills == 40.0

    def test_experience_is_a_property_of_the_monster(self) -> None:
        """Both Albatross rows pay the same whatever the item or quantity, so
        two rows are not two pieces of evidence about a payout."""
        assert len({t.experience for t in bounty.parse_tasks(_TASKS)}) == 1


class TestTheHealthTable:
    def test_health_is_read_for_every_monster(self) -> None:
        health = bounty.parse_hitpoints(_COMBAT)
        assert health["Dolphin"] == 45
        assert health["Albatross"] == 135

    def test_both_halves_of_a_piped_link_are_kept(self) -> None:
        """**Three vocabularies meet here**: the wiki's article title, its
        display name, and upstream's export spelling. Keeping both handles is
        what leaves the consumer something to join on."""
        health = bounty.parse_hitpoints(_COMBAT)
        assert health["Mogre (sea)"] == 59
        assert health["Mogre"] == 59

    def test_the_drop_sections_below_are_not_read_as_rows(self) -> None:
        """They link monsters too, and sweeping the whole page reads them."""
        assert "Orca" not in bounty.parse_hitpoints(_COMBAT)


class TestTheBlob:
    def test_build_tables_reads_both_pages(self) -> None:
        asked: list[list[str]] = []

        def fetch(titles: list[str]) -> dict[str, str]:
            asked.append(titles)
            return {bounty.TASKS_PAGE: _TASKS, bounty.COMBAT_PAGE: _COMBAT}

        tables = bounty.build_tables(fetch)
        assert asked == [[bounty.TASKS_PAGE, bounty.COMBAT_PAGE]]
        blob = tables.as_dict()
        assert len(blob["tasks"]) == 2
        assert blob["hitpoints"]["Albatross"] == 135


@pytest.mark.real_export
class TestAgainstTheRealBlob:
    def test_the_shipped_table_covers_every_bounty_monster(self) -> None:
        """**The join that would fail silently.** Every monster the table
        names must have health, or its bounty prices at nothing."""
        from chunksim.store import cache

        blob = cache.read_blob(cache.BOUNTY_BLOB_NAME)["data"]
        assert len(blob["tasks"]) > 100
        named = {row["monster"] for row in blob["tasks"]}
        assert len(named) > 15
        assert all(name in blob["hitpoints"] for name in named)
