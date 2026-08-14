"""`model/rules.py` - upstream's seed rules, and why a blank map needs them.

The shape assertions are cheap and run everywhere. The one that matters needs
the real export, because the claim is about what a *derivation* does with an
empty `rules` branch and no fixture can stand in for that.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from chunksim.derive.pipeline import derive, load_map_state
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.model.rules import DEFAULT_RULES, default_rules


def test_the_table_is_upstreams_and_is_all_off() -> None:
    """103 keys: 99 flags, every one off, and four amounts that are strings.

    Read from `index.js:348-452` on upstream's `gh-pages` branch. The count is
    pinned so a hand-edit that drops a line is a failing test rather than a
    quietly more permissive world.
    """
    assert len(DEFAULT_RULES) == 103

    flags = {key: value for key, value in DEFAULT_RULES.items() if isinstance(value, bool)}
    amounts = {key: value for key, value in DEFAULT_RULES.items() if isinstance(value, str)}

    assert len(flags) == 99
    assert not any(flags.values()), "a default that is on would silently widen every blank map"
    assert amounts == {
        "Secondary Primary Amount": "1",
        "Kill X Amount": "1",
        "Rare Drop Amount": "1000",
        "Collection Log Clues Amount": "100",
    }


def test_the_amounts_stay_strings() -> None:
    """`model/rates.py` parses these, and its whole point is that `"1/0"` is
    `inf` rather than a `ZeroDivisionError`. An int here would route a number
    around the parser that exists to handle it."""
    assert all(isinstance(DEFAULT_RULES[key], str) for key in (
        "Secondary Primary Amount", "Kill X Amount",
        "Rare Drop Amount", "Collection Log Clues Amount",
    ))


def test_a_copy_cannot_reach_back_into_the_table() -> None:
    """The constant is read-only and `default_rules` hands out a fresh dict:
    a caller about to build a payload must not be able to edit the defaults
    every later caller reads."""
    copy = default_rules()
    copy["Boss"] = True

    assert DEFAULT_RULES["Boss"] is False
    with pytest.raises(TypeError):
        DEFAULT_RULES["Boss"] = True  # type: ignore[index]


@pytest.mark.real_export
def test_an_absent_rules_branch_is_permissive_not_neutral(real_export: ChunkInfo) -> None:
    """**The measurement the blank map exists because of.**

    A missing rule key skips its gate (`challenges._category_gate_met`) where
    `False` refuses it, so a map with no `rules` is the most permissive world
    there is - 526 obtainable items on a three-chunk map, against none once
    upstream's own defaults are seeded. A blank map without this table would
    not be neutral, it would be silently, spectacularly wrong.
    """
    three = {chunk: chunk for chunk in ("6449", "6705", "8492")}

    def items_for(rules: Mapping[str, object] | None) -> int:
        payload: dict[str, object] = {"chunks": {"unlocked": three}}
        if rules is not None:
            payload["rules"] = rules
        state, unlocked = load_map_state(payload, real_export, {})
        return len(derive(state, unlocked).challenges.available_items)

    # The contrast is the finding, and only one side of it is exact. **Zero is
    # the claim** - upstream's own defaults reach nothing on three chunks - while
    # the other side is "hundreds", which was 526 on 2026-08-14 and moves with
    # every item upstream adds.
    assert items_for(None) > 300
    assert items_for(default_rules()) == 0
