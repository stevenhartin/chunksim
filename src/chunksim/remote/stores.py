"""What a shop charges, and in what currency.

**The last thing in this project that was free and should not have been.**
`estimate._route_hours` prices a shop route at zero seconds on the grounds that
buying is instant, which is true of the transaction and false of the money. It
was harmless while the estimator only asked for one abyssal whip; it became the
dominant error the moment Construction was priced, because a build is a stack
of bought planks and a menagerie steel dragon reads `Coins x 10,000,000`.

The export knows which shops stock what (`shopItems`, 435 shops, 4,163 pairs)
and nothing about prices. The wiki's `storeline` Bucket has both, plus the one
field that turns out to matter most:

    bucket('storeline')
      .select('sold_by','sold_item','store_sell_price','store_currency')
      .limit(5000).offset(0).run()

**`store_currency` is why this is not just a price list.** 4,438 of the 6,326
lines are priced in coins, 126 in Tokkul, and the rest in points, trading
sticks, castle wars tickets and half a dozen other things nobody converts into
gold. A single "price" column would have said an obsidian weapon costs 375 and
let it be bought with the gold rate.

**The API caps a query at 5,000 rows whatever `limit` says**, so this pages
with `offset`; two requests cover the table. Measured against the export: 403
of 435 shops join exactly on name, and 3,798 of 4,163 shop-item pairs get a
price - the misses are shops the wiki writes differently (`Al-Kharid General
Store`) and stock the wiki does not list.

`store_sell_price` is what the *player pays*, already multiplied out - the
`store_sell_multiplier` beside it is the percentage of item value that produced
it, not a factor still to apply. Checked against Toktz-xil-ul, which reads
`sell=375 buy=37` and costs 375 Tokkul in game.

Pure parsing; `remote/api.py` fetches.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from chunksim.remote.wikitable import column_index, name_in, rows, table_with

#: How many rows one Bucket query will return, whatever `limit` asks for.
PAGE_SIZE = 5000

#: The fee inside `{{coins|1500}}`, which is how the wiki writes a price in
#: running text rather than in a store table.
_COST_IN_TEMPLATE = re.compile(r"([\d,]+(?:\.\d+)?)")

#: The page listing what a sawmill charges to turn a log into a plank.
#: **Upstream models the conversion and not its fee** - all seven
#: `Process <X> logs` challenges list only the logs - so a mahogany plank came
#: out costing exactly one mahogany log and nothing else. The wiki keeps the
#: prices in a plain table on the operator's page rather than as store stock,
#: which is why this is a page parse and not another `storeline` query.
SAWMILL_PAGE = "Sawmill operator"


@dataclass(frozen=True)
class ShopPrice:
    """What one shop charges for one item, in whatever it charges."""

    price: float
    currency: str

    def as_dict(self) -> dict[str, Any]:
        return {"price": self.price, "currency": self.currency}


def store_query(limit: int = PAGE_SIZE, offset: int = 0) -> str:
    """One page of the storeline table."""
    return (
        "bucket('storeline')"
        ".select('sold_by','sold_item','store_sell_price','store_currency')"
        f".limit({limit}).offset({offset}).run()"
    )


def parse_conversion_fees(text: str) -> dict[str, ShopPrice]:
    """`{item: what a sawmill charges to make it}`, from `SAWMILL_PAGE`.

    Keyed by the **output** - `Mahogany plank`, not `Mahogany logs` - because
    that is what the export's `Process mahogany logs` challenge produces and
    so what a caller has in hand when it needs the fee.

    Always coins: the sawmill takes nothing else. Kept as a `ShopPrice` anyway
    so the currency travels with the number and one rate table serves both.
    """
    table = table_with(text, "Cost")
    found: dict[str, ShopPrice] = {}
    body = list(rows(table))
    if not body:
        return found
    width = Counter(len(cells) for cells in body).most_common(1)[0][0]
    at_item = column_index(table, "item", width=width)
    at_cost = column_index(table, "cost", width=width)
    if at_item is None or at_cost is None:
        return found
    for cells in body:
        if len(cells) <= max(at_item, at_cost):
            continue
        item = name_in(cells[at_item])
        # `{{coins|1500}}`, so the figure has to be dug out of a template -
        # `_number` above is for Bucket fields, which arrive bare.
        found_cost = _COST_IN_TEMPLATE.search(cells[at_cost])
        cost = float(found_cost.group(1).replace(",", "")) if found_cost else None
        if item and cost is not None and cost >= 0:
            found[item] = ShopPrice(price=cost, currency="Coins")
    return found


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return float(value.replace(",", "").strip())
    except ValueError:
        return None


def parse_storelines(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, ShopPrice]]:
    """`{shop: {item: ShopPrice}}`, cheapest kept when a shop lists an item twice.

    A shop can stock the same item at two prices - `TzHaar-Hur-Tel's Equipment
    Store` lists Toktz-xil-ul at 375 and at 325 - and the cheaper is the one a
    buyer would pay.

    A row with no price is dropped rather than treated as free: "the wiki does
    not say" and "it costs nothing" are the distinction this module exists to
    preserve.
    """
    found: dict[str, dict[str, ShopPrice]] = {}
    for row in rows:
        shop, item = row.get("sold_by"), row.get("sold_item")
        price = _number(row.get("store_sell_price"))
        if not isinstance(shop, str) or not isinstance(item, str) or price is None:
            continue
        if price < 0:
            continue
        currency = row.get("store_currency")
        entry = ShopPrice(
            price=price,
            currency=str(currency).strip() if isinstance(currency, str) else "",
        )
        standing = found.setdefault(shop, {}).get(item)
        if standing is None or entry.price < standing.price:
            found[shop][item] = entry
    return found
