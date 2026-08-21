"""`costing/lootsack.py`: the export's share is per roll, an open is several."""

from __future__ import annotations

from typing import Any

from chunksim.costing import lootsack, rumours


class _Info:
    def __init__(self, tables: dict[str, Any]) -> None:
        self.skill_items = {"Nonskill": tables}


#: A basic sack cut down to its shape: six resource rows at `1/7` and one
#: unique at `1/50`, the way upstream writes it.
_BASIC = {
    "Hunter spear tips": {"15-30": "1/7"},
    "Quetzal feed": {"1": "1/7"},
    "Coins": {"750-1250": "1/7"},
    "Blessed bone shards": {"100-200": "1/7"},
    "Raw kyatt": {"2 (noted)": "1/7"},
    "Raw pyre fox": {"3": "1/7"},
    "Guild hunter top": {"1": "1/50"},
}
_NOVICE = "Complete a novice ~|Hunters' Rumour|~"
_MASTER = "Complete a master ~|Hunters' Rumour|~"


def _info(**tables: Any) -> _Info:
    return _Info(dict(tables))


def _basic_only() -> _Info:
    return _info(**{"Hunters' loot sack (basic) loot": _BASIC})


class TestTheRollCountIsTheWholePoint:
    """The export records the share of *one roll* and the wiki's own rarity
    column writes the pair as `5 x 1/7`. Read as a per-open chance it
    undercounts a sack five to eleven times."""

    def test_a_basic_sack_is_five_rolls(self) -> None:
        seconds = lootsack.seconds_for(_basic_only(), {"Hunter": {_NOVICE: {}}})

        # 5 rolls x 1/7 x mean(15, 30) = 16.07 tips a sack.
        assert seconds is not None
        assert seconds == 3600.0 / rumours.RUMOURS_PER_HOUR / (5 * (1 / 7) * 22.5)

    def test_reading_it_per_open_would_be_five_times_dearer(self) -> None:
        """The defect this module exists to avoid, stated as a number."""
        seconds = lootsack.seconds_for(_basic_only(), {"Hunter": {_NOVICE: {}}})
        naive = 3600.0 / rumours.RUMOURS_PER_HOUR / ((1 / 7) * 22.5)

        assert seconds is not None
        assert round(naive / seconds, 6) == 5.0


class TestOnlyResourceRowsAreMultiplied:
    """A sack's uniques sit outside the roll loop - the wiki writes the armour
    as a flat `1/50` where a resource carries the `N x` prefix. Scaling a
    unique would claim a 1/50 hat drops one open in ten."""

    def test_the_resource_share_is_read_rather_than_stated(self) -> None:
        assert lootsack._resource_share(_BASIC) == 1 / 7

    def test_a_unique_is_not_priced(self) -> None:
        """`ITEM` is the only member this module answers for, so the guard is
        asserted on the share reader rather than through a second output."""
        assert lootsack._resource_share({"Only": {"1": "1/50"}}) == 1 / 50


class TestTheTierIsGatedByUpstreamsOwnTask:
    """A map that cannot complete a master rumour cannot open a master sack."""

    def test_an_unreachable_tier_is_skipped(self) -> None:
        info = _info(
            **{
                "Hunters' loot sack (basic) loot": _BASIC,
                "Hunters' loot sack (master) loot": {
                    "Hunter spear tips": {"15-30": "1/15"}
                },
            }
        )

        with_master = lootsack.seconds_for(info, {"Hunter": {_NOVICE: {}, _MASTER: {}}})
        without = lootsack.seconds_for(info, {"Hunter": {_NOVICE: {}}})

        # 11 x 1/15 beats 5 x 1/7, so the master tier is the cheaper answer -
        # and it must vanish entirely when the task is not valid.
        assert with_master is not None and without is not None
        assert with_master < without

    def test_no_rumour_at_all_prices_nothing(self) -> None:
        assert lootsack.costs(_basic_only(), {"Hunter": {}}) == {}

    def test_a_map_with_no_hunter_branch_prices_nothing(self) -> None:
        assert lootsack.costs(_basic_only(), {}) == {}


def test_the_cheapest_reachable_tier_wins() -> None:
    """`_item_hours` takes the `min` over routes and so does this."""
    info = _info(
        **{
            "Hunters' loot sack (basic) loot": _BASIC,
            "Hunters' loot sack (master) loot": {"Hunter spear tips": {"15-30": "1/15"}},
        }
    )

    seconds = lootsack.seconds_for(info, {"Hunter": {_NOVICE: {}, _MASTER: {}}})

    assert seconds == 3600.0 / rumours.RUMOURS_PER_HOUR / (11 * (1 / 15) * 22.5)


def test_the_pace_is_rumours_own_and_nothing_is_added_to_it() -> None:
    """`RUMOURS_PER_HOUR` is the one invented number in the chain, and this
    module spends it rather than inventing a second - so doubling it halves
    every cost here and changes nothing else."""
    valid: dict[str, dict[str, Any]] = {"Hunter": {_NOVICE: {}}}
    before = lootsack.seconds_for(_basic_only(), valid)

    original = rumours.RUMOURS_PER_HOUR
    try:
        rumours.RUMOURS_PER_HOUR = original * 2
        after = lootsack.seconds_for(_basic_only(), valid)
    finally:
        rumours.RUMOURS_PER_HOUR = original

    assert before is not None and after is not None
    assert round(before / after, 6) == 2.0
