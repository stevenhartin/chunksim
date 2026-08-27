"""Tests for `remote/stores.py`: what a shop charges, and in what.

The fixtures are trimmed from the live table, keeping the shapes that mattered:
a currency that is not coins, a shop listing the same item twice, and a fee
written as `{{coins|1500}}` inside prose rather than as store stock.
"""

from __future__ import annotations

import pytest

from chunksim.remote.stores import (
    SAWMILL_PAGE,
    ShopPrice,
    parse_conversion_fees,
    parse_storelines,
    store_query,
)

_SAWMILL = """
==Prices==
{| class="wikitable"
|-
!colspan=2|Item
!Cost
!colspan=2|Log needed
|-
|{{plinkt|Plank}}
|{{coins|100}}
|{{plinkt|Logs}}
|-
|{{plinkt|Mahogany plank}}
|{{coins|1500}}
|{{plinkt|Mahogany logs}}
|}
"""


def test_a_price_carries_its_currency() -> None:
    """**375 Tokkul is not 375 coins.** Flattening the two into one number is
    what let an obsidian fence read 2,902,235 Construction xp/hr."""
    parsed = parse_storelines(
        [
            {
                "sold_by": "TzHaar-Hur-Tel's Equipment Store",
                "sold_item": "Toktz-xil-ul",
                "store_sell_price": "375",
                "store_currency": "Tokkul",
            }
        ]
    )

    assert parsed["TzHaar-Hur-Tel's Equipment Store"]["Toktz-xil-ul"] == ShopPrice(
        price=375.0, currency="Tokkul"
    )


def test_the_cheaper_of_two_listings_wins() -> None:
    """A shop can stock one item at two prices, and a buyer pays the lower."""
    parsed = parse_storelines(
        [
            {"sold_by": "S", "sold_item": "X", "store_sell_price": "375", "store_currency": "Tokkul"},
            {"sold_by": "S", "sold_item": "X", "store_sell_price": "325", "store_currency": "Tokkul"},
        ]
    )

    assert parsed["S"]["X"].price == 325.0


def test_a_line_with_no_price_is_dropped_rather_than_freed() -> None:
    """"The wiki does not say" and "it costs nothing" are the distinction this
    whole module exists to preserve."""
    parsed = parse_storelines(
        [
            {"sold_by": "S", "sold_item": "Priceless", "store_currency": "Coins"},
            {"sold_by": "S", "sold_item": "Free", "store_sell_price": "0", "store_currency": "Coins"},
        ]
    )

    assert "Priceless" not in parsed.get("S", {})
    assert parsed["S"]["Free"].price == 0.0


def test_the_sawmill_fee_is_keyed_by_what_it_makes() -> None:
    """**Upstream models the conversion and not its price.** All seven
    `Process <X> logs` challenges list only the logs, so a mahogany plank came
    out costing exactly one mahogany log and nothing else. Keyed by the output
    because that is what the challenge produces."""
    fees = parse_conversion_fees(_SAWMILL)

    assert fees["Plank"] == ShopPrice(price=100.0, currency="Coins")
    assert fees["Mahogany plank"] == ShopPrice(price=1500.0, currency="Coins")


def test_a_fee_table_whose_headers_follow_its_first_separator_is_still_found() -> None:
    """The sawmill's table opens with `|-` and puts its `!` lines after it, so
    reading "everything before the first separator" finds only the `{|` line."""
    assert parse_conversion_fees(_SAWMILL)
    assert parse_conversion_fees("no table here") == {}


def test_stock_and_restock_are_read_off_the_same_row() -> None:
    """Toci's Gem Store's uncut ruby, straight off a live query: `store_stock`
    is `"1"` and `restock_time` is `"36000"` ticks - the wiki's own page
    states "1 in stock" and "6h restock", and `36000 * 0.6 = 21600` seconds
    is exactly six hours."""
    parsed = parse_storelines(
        [
            {
                "sold_by": "Toci's Gem Store",
                "sold_item": "Uncut ruby",
                "store_sell_price": "100",
                "store_currency": "Coins",
                "store_stock": "1",
                "restock_time": "36000",
            }
        ]
    )

    entry = parsed["Toci's Gem Store"]["Uncut ruby"]
    assert entry.stock == 1
    assert entry.restock_seconds == pytest.approx(21_600.0)


def test_an_unparseable_stock_is_unknown_rather_than_unlimited_or_zero() -> None:
    """`Module:StoreLine` writes `"inf"`/`"∞"` for a shop that never runs dry -
    a string this module cannot read as a count, and reading it as `0` would
    refuse every route through it while reading it as free would ungate a
    line the wiki is actually describing as bottomless. `None` means
    "unknown", which `costing/estimate.py` treats as unconstrained."""
    parsed = parse_storelines(
        [
            {
                "sold_by": "S",
                "sold_item": "Bottomless",
                "store_sell_price": "1",
                "store_currency": "Coins",
                "store_stock": "inf",
                "restock_time": "N/A",
            }
        ]
    )

    entry = parsed["S"]["Bottomless"]
    assert entry.stock is None
    assert entry.restock_seconds is None


def test_a_line_with_no_stock_columns_at_all_carries_none() -> None:
    """A row from a shop the scrape has always covered without these two new
    columns - the ordinary case for any fixture this suite already had -
    must not turn into a stock of zero or a hop cost from nowhere."""
    parsed = parse_storelines(
        [{"sold_by": "S", "sold_item": "X", "store_sell_price": "1", "store_currency": "Coins"}]
    )

    assert parsed["S"]["X"] == ShopPrice(price=1.0, currency="Coins")


def test_the_query_pages_with_an_offset() -> None:
    """The API caps a query at 5,000 rows whatever `limit` says."""
    assert "offset(5000)" in store_query(offset=5000)
    assert SAWMILL_PAGE == "Sawmill operator"
