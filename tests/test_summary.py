"""Tests for the pure reduction layer."""

from __future__ import annotations

from typing import Any

from fray_claude.model.summary import summarise

PAYLOAD: dict[str, Any] = {
    "chunks": {
        "unlocked": {"50_50": True, "50_51": True, "51_50": True},
        "stickered": {"50_50": True},
    },
    "chunkOrder": {"1709907279995": "50_50", "1709907280506": "50_51"},
    "chunkinfo": {
        "activeTasks": {
            "Diary": {"a": {}, "b": {}},
            "BiS": {"c": {}},
        }
    },
    "rules": {"All Shops": True, "Boosting": False, "BIS Skilling": True},
}


def test_summarise_counts_unlocked_chunks() -> None:
    assert summarise(PAYLOAD).unlocked_chunks == 3


def test_summarise_counts_chunk_order_entries() -> None:
    # Deliberately fewer than the unlocked count: a partial log, not an order.
    assert summarise(PAYLOAD).chunk_order_entries == 2


def test_summarise_groups_active_tasks_by_category() -> None:
    summary = summarise(PAYLOAD)

    assert summary.active_tasks == {"BiS": 1, "Diary": 2}
    assert list(summary.active_tasks) == ["BiS", "Diary"], "categories should be sorted"
    assert summary.active_task_total == 3


def test_summarise_counts_only_enabled_rules() -> None:
    summary = summarise(PAYLOAD)

    assert (summary.rules_enabled, summary.rules_total) == (2, 3)


def test_summarise_ignores_truthy_non_boolean_rules() -> None:
    # `rules_enabled` tests identity, so only a real `true` counts as enabled.
    summary = summarise({"rules": {"Boosting": "yes", "All Shops": 1, "BIS Skilling": True}})

    assert (summary.rules_enabled, summary.rules_total) == (1, 3)


def test_summarise_skips_non_mapping_task_categories() -> None:
    summary = summarise({"chunkinfo": {"activeTasks": {"Diary": ["a", "b"], "BiS": {"c": {}}}}})

    assert summary.active_tasks == {"BiS": 1}


def test_summarise_tolerates_empty_payload() -> None:
    # Firebase drops empty containers rather than storing them, so every branch
    # in a real payload can simply be absent.
    summary = summarise({})

    assert summary.unlocked_chunks == 0
    assert summary.chunk_order_entries == 0
    assert summary.active_tasks == {}
    assert summary.active_task_total == 0
    assert (summary.rules_enabled, summary.rules_total) == (0, 0)


def test_summarise_tolerates_branches_of_the_wrong_type() -> None:
    summary = summarise({"chunks": "unexpected", "rules": None, "chunkOrder": []})

    assert summary.unlocked_chunks == 0
    assert summary.chunk_order_entries == 0
    assert summary.rules_total == 0


def test_summarise_reads_a_slayer_lock() -> None:
    payload = {"chunkinfo": {"slayerLocked": {"level": "42", "monster": "Aberrant spectres"}}}

    assert summarise(payload).slayer_locked == ("Aberrant spectres", 42)


def test_summarise_reports_no_lock_when_slayer_is_free() -> None:
    assert summarise({"chunkinfo": {}}).slayer_locked is None


def test_summarise_refuses_a_lock_whose_level_will_not_parse() -> None:
    """A guessed cap would silently hold Slayer somewhere it is not held."""
    payload = {"chunkinfo": {"slayerLocked": {"level": "soon", "monster": "Bats"}}}

    assert summarise(payload).slayer_locked is None
