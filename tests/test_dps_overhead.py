"""Tests for `costing/dps_overhead.py`: the harness behind the constants.

Nothing in `src/` calls it - it exists to be re-run when someone doubts the
overhead numbers - so this is the only thing keeping it honest.
"""

from __future__ import annotations

from typing import Any

import pytest

from fray_claude.costing import dps_bridge, dps_overhead
from fray_claude.costing.heuristics import Rate
from fray_claude.model.chunkinfo import ChunkInfo

pytestmark = pytest.mark.skipif(
    not dps_bridge.DPS_AVAILABLE, reason="needs the optional dps extra"
)


LEVELS = {"Attack": 75, "Strength": 70, "Ranged": 70, "Magic": 87, "Hitpoints": 99}


def _chunk_info() -> ChunkInfo:
    return ChunkInfo({"equipment": _equipment()})


class _FakeIndex:
    """Enough of `MonsterIndex` for the resolution tests."""

    def __init__(self, names: dict[str, Any]) -> None:
        self._names = names

    def get(self, name: str) -> Any:
        return self._names.get(name)

    def __iter__(self) -> Any:
        return iter(self._names)


def _target(**kwargs: Any) -> Any:
    from osrs_dps import Target

    return Target(**kwargs)


def _equipment() -> dict[str, Any]:
    """A handful of items, shaped exactly as the export shapes them."""
    return {
        "Abyssal whip": {
            "attack_slash": 82,
            "attack_stab": 0,
            "attack_crush": 0,
            "melee_strength": 82,
            "attack_speed": 4,
            "slot": "weapon",
        },
        "Dragon dagger": {
            "attack_stab": 40,
            "attack_slash": 25,
            "attack_crush": 0,
            "melee_strength": 40,
            "attack_speed": 4,
            "slot": "weapon",
        },
        "Rune platebody": {"defence_slash": 82, "attack_speed": 0, "slot": "body"},
        "Webweaver bow (u)": {
            "attack_ranged": 85,
            "ranged_strength": 65,
            "attack_speed": 4,
            "slot": "2h",
        },
        "Occult necklace": {"attack_magic": 10, "magic_damage": 5, "slot": "neck"},
        "Master wand": {
            "attack_magic": 20,
            "magic_damage": 10,
            "attack_speed": 4,
            "slot": "weapon",
        },
    }


def test_kills_per_hour_adds_the_overhead() -> None:
    """Fighting time is not a kill cycle; the difference is the overhead."""
    kill = dps_bridge.KillEstimate(
        monster="Rat", style="Melee", ttk=30.0, dps=1.0, max_hit=5, accuracy=0.5
    )

    assert kill.kills_per_hour(overhead=30.0) == pytest.approx(60.0)
    assert kill.kills_per_hour(overhead=0.0) == pytest.approx(120.0)


def test_measure_overhead_reports_samples_not_an_average() -> None:
    """Including the negative ones, which is the point.

    The wiki's rates assume near-max gear and these kill times come from
    chunk-restricted BiS, so where the map's gear is worse the implied
    overhead goes negative. Averaging that away would hide the gap.
    """
    index = _FakeIndex({"Rat": _target(name="Rat", hitpoints=8)})
    samples = dps_overhead.measure_overhead(
        _chunk_info(),
        {"Melee-weapon": "Abyssal whip"},
        LEVELS,
        {"Rat": Rate(value=100.0, source="wiki")},
        index=index,  # type: ignore[arg-type]
    )

    assert len(samples) == 1
    assert samples[0].monster == "Rat"
    assert samples[0].wiki_kph == 100.0
    assert samples[0].overhead == pytest.approx(36.0 - samples[0].ttk)
