"""`gui/settings.py` - what a preference means, before anything stores it.

The route tests live with the routes (`test_gui_actions.py`, `test_gui_view.py`)
and the disk tests with the disk (`test_cache.py`); this file is only about the
validation, which is where the interesting refusals are.
"""

from __future__ import annotations

from typing import Any

import pytest

from chunksim.gui import settings


def _bands(*bounds: float | None) -> list[dict[str, Any]]:
    return [
        {"name": f"band {index}", "upto": bound} for index, bound in enumerate(bounds)
    ]


def test_nothing_sent_gives_the_defaults_whole() -> None:
    settled = settings.sanitise({})
    assert settled["hours_scale"] == "log"
    assert [band["name"] for band in settled["hours_bands"]] == [
        "Free", "Quick", "Grind", "Brutal", "Death"
    ]
    assert [band["upto"] for band in settled["hours_bands"]] == [1.0, 10.0, 100.0, 300.0, None]


def test_every_key_is_present_so_a_reader_needs_no_defaults_of_its_own() -> None:
    """The point of returning a whole object rather than a patch."""
    assert set(settings.sanitise({})) == set(settings.KEYS)
    assert set(settings.sanitise({"hours_scale": "linear"}, {})) == set(settings.KEYS)


def test_the_defaults_are_copied_rather_than_shared() -> None:
    """A caller mutating one answer must not change the next one."""
    first = settings.sanitise({})
    first["hours_bands"][0]["name"] = "clobbered"
    assert settings.sanitise({})["hours_bands"][0]["name"] == "Free"


@pytest.mark.parametrize("scale", ["log", "linear"])
def test_both_scales_are_accepted(scale: str) -> None:
    assert settings.sanitise({"hours_scale": scale})["hours_scale"] == scale


def test_an_unknown_scale_leaves_the_stored_one_alone() -> None:
    """Refuse rather than coerce - a silently-rewritten choice is invisible."""
    stored = {"hours_scale": "linear"}
    assert settings.sanitise({"hours_scale": "sqrt"}, stored)["hours_scale"] == "linear"


def test_unrecognised_keys_are_dropped() -> None:
    settled = settings.sanitise({"evil": "--headless", "hours_scale": "linear"})
    assert "evil" not in settled


def test_a_valid_band_list_survives_with_its_names_trimmed() -> None:
    sent = [
        {"name": "  Free  ", "upto": 2},
        {"name": "Quick", "upto": 20},
        {"name": "Grind", "upto": 200},
        {"name": "Ouch", "upto": 500},
        {"name": "Death", "upto": None},
    ]
    bands = settings.sanitise({"hours_bands": sent})["hours_bands"]
    assert [band["name"] for band in bands] == ["Free", "Quick", "Grind", "Ouch", "Death"]
    assert [band["upto"] for band in bands] == [2.0, 20.0, 200.0, 500.0, None]


@pytest.mark.parametrize(
    "sent",
    [
        pytest.param(_bands(1, 10, 100, 300), id="too few"),
        pytest.param(_bands(1, 10, 100, 300, 900, None), id="too many"),
        pytest.param(_bands(1, 10, 5, 300, None), id="not ascending"),
        pytest.param(_bands(1, 10, 10, 300, None), id="equal, so one band is empty"),
        pytest.param(_bands(0, 10, 100, 300, None), id="a zero-width first band"),
        pytest.param(_bands(-5, 10, 100, 300, None), id="negative"),
        pytest.param(_bands(1, 10, 100, 300, 900), id="a bounded top band"),
        pytest.param("not a list", id="not a list at all"),
        pytest.param([1, 2, 3, 4, 5], id="not objects"),
    ],
)
def test_a_bad_band_list_is_refused_whole(sent: Any) -> None:
    """All or nothing: the bands are only meaningful as an ordered partition,
    and half of an edit is not one."""
    stored = settings.sanitise({})
    assert settings.sanitise({"hours_bands": sent}, stored)["hours_bands"] == stored["hours_bands"]


def test_a_nameless_band_is_refused() -> None:
    sent = _bands(1, 10, 100, 300, None)
    sent[2]["name"] = "   "
    stored = settings.sanitise({})
    assert settings.sanitise({"hours_bands": sent}, stored)["hours_bands"] == stored["hours_bands"]


def test_a_boolean_is_not_a_threshold() -> None:
    """`True` is an `int` in Python; a caller sending one means nonsense."""
    sent = _bands(1, 10, 100, 300, None)
    sent[0]["upto"] = True
    stored = settings.sanitise({})
    assert settings.sanitise({"hours_bands": sent}, stored)["hours_bands"] == stored["hours_bands"]


@pytest.mark.parametrize("bound", [float("inf"), float("nan")])
def test_a_non_finite_threshold_is_refused(bound: float) -> None:
    sent = _bands(1, 10, 100, 300, None)
    sent[1]["upto"] = bound
    stored = settings.sanitise({})
    assert settings.sanitise({"hours_bands": sent}, stored)["hours_bands"] == stored["hours_bands"]


def test_a_long_name_is_cut_rather_than_refused() -> None:
    """A length is presentation, where an ordering is meaning - so this one is
    trimmed instead of throwing the whole edit away."""
    sent = _bands(1, 10, 100, 300, None)
    sent[0]["name"] = "x" * 200
    bands = settings.sanitise({"hours_bands": sent})["hours_bands"]
    assert bands[0]["name"] == "x" * settings.MAX_BAND_NAME


def test_stored_settings_win_over_the_defaults_and_a_patch_wins_over_both() -> None:
    stored = settings.sanitise({"hours_scale": "linear", "hours_bands": _bands(2, 20, 200, 400, None)})
    settled = settings.sanitise({"hours_scale": "log"}, stored)
    assert settled["hours_scale"] == "log"
    # Untouched by the patch, so it keeps what was stored rather than resetting.
    assert settled["hours_bands"] == stored["hours_bands"]


def test_reset_names_the_key_to_forget() -> None:
    stored = settings.sanitise({"hours_scale": "linear", "hours_bands": _bands(2, 20, 200, 400, None)})
    settled = settings.sanitise({"reset": ["hours_bands"]}, stored)
    assert settled["hours_bands"] == settings.sanitise({})["hours_bands"]
    # Only the named key, so a reset is not a wipe.
    assert settled["hours_scale"] == "linear"


def test_reset_ignores_a_key_this_module_has_never_heard_of() -> None:
    stored = settings.sanitise({"hours_scale": "linear"})
    assert settings.sanitise({"reset": ["evil", "hours_scale"]}, stored)["hours_scale"] == "log"


def test_a_reset_and_a_value_for_the_same_key_takes_the_value() -> None:
    """The patch is applied after the drop, so "reset then set" is one step."""
    stored = settings.sanitise({"hours_scale": "linear"})
    settled = settings.sanitise({"reset": ["hours_scale"], "hours_scale": "linear"}, stored)
    assert settled["hours_scale"] == "linear"


def test_a_band_still_carrying_a_superseded_default_name_is_brought_up_to_date() -> None:
    """**Renaming a default is otherwise invisible to anyone who has opened
    the page**, because settings are stored whole: the old name is already in
    their file, and nothing here can tell "the default, saved" from "what I
    picked". Matching the *edge* as well is what makes the difference - a
    stored band at the old name and the old bound is one nobody chose.
    """
    stored = {
        "hours_scale": "log",
        "hours_bands": [
            {"name": "Free", "upto": 1.0},
            {"name": "Quick", "upto": 10.0},
            {"name": "Grind", "upto": 100.0},
            {"name": "Minor Death", "upto": 300.0},
            {"name": "Death", "upto": None},
        ],
    }

    settled = settings.sanitise({}, stored)

    assert [band["name"] for band in settled["hours_bands"]][3] == "Brutal"


def test_the_same_name_over_a_moved_edge_is_a_choice_and_is_kept() -> None:
    """Someone who typed it, or moved it, meant it."""
    stored = {
        "hours_scale": "log",
        "hours_bands": [
            {"name": "Free", "upto": 1.0},
            {"name": "Quick", "upto": 10.0},
            {"name": "Grind", "upto": 100.0},
            {"name": "Minor Death", "upto": 250.0},
            {"name": "Death", "upto": None},
        ],
    }

    settled = settings.sanitise({}, stored)

    assert [band["name"] for band in settled["hours_bands"]][3] == "Minor Death"
