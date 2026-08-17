"""What a herb costs, when farming them is time-gated and killing is not."""

from __future__ import annotations

import pytest

from chunksim.costing import herbs
from chunksim.costing.farming import HERBS_PER_SEED


def test_a_run_is_setup_plus_a_minute_a_patch() -> None:
    """Teleport to a bank and gear up, then a minute each. Four patches is six
    minutes for 35.2 herbs."""
    assert herbs.run_minutes(4) == pytest.approx(6.0)
    assert herbs.run_minutes(0) == 0.0
    assert HERBS_PER_SEED * 4 == pytest.approx(35.2)


def test_the_rest_of_the_cycle_is_spent_killing() -> None:
    """**The eighty minutes a herb grows is not idle time.** Farming priced at
    the clicking alone said 6.8 seconds a herb and implied you could do it back
    to back; the cycle is the unit, and what fills it is the best active
    source."""
    farmed_only = herbs.herbs_per_hour(4, active_per_hour=0.0)
    with_killing = herbs.herbs_per_hour(4, active_per_hour=300.0)

    # 35.2 herbs per 80 minutes, and nothing else.
    assert farmed_only == pytest.approx(35.2 * 60 / 80)
    # ...plus 74 minutes of killing.
    assert with_killing == pytest.approx((35.2 + 300.0 * 74 / 60) * 60 / 80)


def test_no_patches_and_no_kills_is_no_herbs() -> None:
    """Rather than a division by zero or a free herb."""
    assert herbs.herbs_per_hour(0, 0.0) == 0.0
    assert herbs.seconds_per_herb(0, 0.0) == 0.0
    assert herbs.costs(["Grimy ranarr weed"], 0, 0.0) == {}


def test_the_drop_table_is_pooled_not_asked_for_one_herb() -> None:
    """**A monster's herb table is non-discriminatory** - thirteen herbs, and
    you take what falls - so the question is which source drops the most herbs,
    never how long for a ranarr. Asking per herb prices one line of a table
    nobody rolls for individually."""
    yields = {("Chaos druid", "Grimy guam leaf"): 0.2,
              ("Chaos druid", "Grimy ranarr weed"): 0.02,
              ("Goblin", "Grimy guam leaf"): 0.5}
    kph = {"Chaos druid": 300.0, "Goblin": 100.0}

    best = herbs.pooled_rate(
        ["Chaos druid", "Goblin"],
        ["Grimy guam leaf", "Grimy ranarr weed"],
        lambda provider, herb: yields.get((provider, herb), 0.0),
        lambda provider: kph.get(provider, 0.0),
    )

    # 0.22 x 300 = 66 beats 0.5 x 100 = 50, which asking for ranarr alone
    # would have got backwards.
    assert best[0] == "Chaos druid"
    assert best[1] == pytest.approx(66.0)


def test_a_patch_location_may_name_a_section() -> None:
    """**The export writes both** - `13141` is a whole chunk, `11321-2` is
    section 2 of chunk 11321 - and comparing the second against unlocked-chunk
    keys silently matches nothing. That undercounted the every-rollable-chunk
    map at 5 patches of 12."""
    unlocked = {"13141": True, "11321": True}
    sections = {"11321": {"2": True}, "9999": {"1": True}}

    assert herbs.patch_count(["13141", "11321-2"], unlocked, sections) == 2
    # The chunk being unlocked is not the section being reachable.
    assert herbs.patch_count(["11321-3"], unlocked, sections) == 0
    assert herbs.patch_count(["9999"], unlocked, sections) == 0


def test_every_herb_costs_the_same() -> None:
    """The consequence of pooling, stated rather than hidden: right for a
    climb where you brew whatever your herbs allow, wrong for a single goal
    that needs one ranarr."""
    found = herbs.costs(["Grimy ranarr weed", "Grimy guam leaf", "Coins"], 4, 300.0)

    assert set(found) == {"Grimy ranarr weed", "Grimy guam leaf"}
    assert len(set(found.values())) == 1
