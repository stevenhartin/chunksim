"""The courier scrape: the task table and the coordinates that place its ports."""

from __future__ import annotations

import pytest

from chunksim.remote import courier

_TASKS = """
{{CourierTaskLine|level=1|xp=78|noticeBoard=Port Sarim|cargoLocation=Port Sarim|destination=The Pandemonium|item=Crate of platebodies|qty=1|taskId=1}}
|-
{{CourierTaskLine|level=1|xp=155|noticeBoard=Port Sarim|cargoLocation=The Pandemonium|destination=Port Sarim|item=Crate of spices|qty=2|taskId=2}}
|-
{{CourierTaskLine|level=5|xp=|noticeBoard=Land's End|cargoLocation=Land's End|destination=Hosidius|item=Crate of rope|qty=1|taskId=229}}
"""

_MODULE = """
p.ledgerTableLocations = {
\t['Aldarin'] = {1449,2969},
\t["Land's End"] = {1506,3407},
\t["Void Knights' Outpost"] = {2652,2673}
}

p.noticeBoardLocations = {
\t['Aldarin'] = {1438,2969},
\t["Land's End"] = {1502,3407}
}
"""


class TestTheTaskTable:
    def test_rows_parse_with_their_shape(self) -> None:
        tasks = courier.parse_tasks(_TASKS)
        assert [t.experience for t in tasks] == [78, 155]
        assert [t.displaced for t in tasks] == [False, True]
        assert tasks[1].crates == 2

    def test_a_row_with_no_payout_is_dropped(self) -> None:
        """Seven of the real table's rows state no experience. A task with no
        payout cannot enter a rate either way, so it is dropped at the parse
        rather than downstream."""
        assert len(courier.parse_tasks(_TASKS)) == 2

    def test_displaced_is_the_board_being_the_destination(self) -> None:
        tasks = courier.parse_tasks(_TASKS)
        assert tasks[1].notice_board == tasks[1].destination != tasks[1].cargo


class TestTheCoordinateTables:
    def test_both_tables_are_read_separately(self) -> None:
        """A ledger port need not have a board - seven of the thirty do not -
        so reading the module as one block would give them one."""
        ledgers = courier.parse_locations(_MODULE, "ledgerTableLocations")
        boards = courier.parse_locations(_MODULE, "noticeBoardLocations")
        assert set(ledgers) == {"Aldarin", "Land's End", "Void Knights' Outpost"}
        assert set(boards) == {"Aldarin", "Land's End"}

    def test_an_apostrophe_does_not_end_the_name(self) -> None:
        """**Two ports carry one**, so the module writes them in double quotes.
        A character class matching either quote stops at the apostrophe and
        loses both silently."""
        ledgers = courier.parse_locations(_MODULE, "ledgerTableLocations")
        assert ledgers["Void Knights' Outpost"] == (2652, 2673)

    def test_the_last_entry_has_no_trailing_comma_and_still_counts(self) -> None:
        """The block ends on its own line; looking for a bare `}` before a
        newline finds the last entry's instead and drops a port."""
        assert "Void Knights' Outpost" in courier.parse_locations(
            _MODULE, "ledgerTableLocations"
        )

    def test_a_missing_table_is_empty_rather_than_an_error(self) -> None:
        assert courier.parse_locations(_MODULE, "nothingLikeThis") == {}


class TestChunkArithmetic:
    def test_a_coordinate_reduces_to_upstreams_chunk_id(self) -> None:
        """A chunk id is a region id, so this is the game's own arithmetic
        rather than a mapping chosen here. Port Sarim's ledger sits in 12081,
        which is what upstream states for it."""
        assert courier.region_of(3028, 3194) == "12081"
        assert courier.region_of(1449, 2969) == "5678"


class TestTheBlobShape:
    def test_ports_carry_their_chunk_and_whether_they_have_a_board(self) -> None:
        tables = courier.CourierTables(
            tasks=courier.parse_tasks(_TASKS),
            ledgers=courier.parse_locations(_MODULE, "ledgerTableLocations"),
            boards=courier.parse_locations(_MODULE, "noticeBoardLocations"),
        )
        blob = tables.as_dict()
        assert blob["ports"]["Aldarin"] == {
            "chunk": "5678",
            "x": 1449,
            "y": 2969,
            "board": True,
        }
        assert blob["ports"]["Void Knights' Outpost"]["board"] is False
        assert len(blob["tasks"]) == 2

    def test_build_tables_reads_both_pages(self) -> None:
        asked: list[list[str]] = []

        def fetch(titles: list[str]) -> dict[str, str]:
            asked.append(titles)
            return {courier.TASKS_PAGE: _TASKS, courier.LOCATIONS_PAGE: _MODULE}

        tables = courier.build_tables(fetch)
        assert asked == [[courier.TASKS_PAGE, courier.LOCATIONS_PAGE]]
        assert len(tables.tasks) == 2
        assert len(tables.ledgers) == 3


@pytest.mark.real_export
class TestAgainstTheRealBlob:
    def test_the_shipped_table_is_the_size_the_docstrings_quote(self) -> None:
        """Upstream is live, so this defends the argument rather than the
        magnitude: the table must be a few hundred deliveries over ~30 ports,
        and every port must have a chunk."""
        from chunksim.store import cache

        blob = cache.read_blob(cache.COURIER_BLOB_NAME)["data"]
        assert len(blob["tasks"]) > 300
        assert len(blob["ports"]) > 25
        assert all(row["chunk"] for row in blob["ports"].values())
        boards = [name for name, row in blob["ports"].items() if row["board"]]
        assert len(boards) > 15

    def test_the_board_is_always_on_the_leg(self) -> None:
        """**The structural fact the model rests on.** If a board could be a
        third place, taking a task would cost a detour and the best-leg
        argument would not hold."""
        from chunksim.store import cache

        blob = cache.read_blob(cache.COURIER_BLOB_NAME)["data"]
        for row in blob["tasks"]:
            assert row["notice_board"] in (row["cargo"], row["destination"])
