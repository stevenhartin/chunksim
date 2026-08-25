"""Tests for `costing/fightscripts.py` - the phased-boss primitive.

Pure: `Phase`/`FightScript` are plain data, so every test here builds fixture
values by hand rather than reading a real boss. `tests/test_costing_hydra.py`
covers the one real script this project ships.
"""

from __future__ import annotations

import pytest

from chunksim.costing.fightscripts import FightScript, Phase


class TestPhase:
    def test_a_phase_defaults_to_no_reduction_and_no_idle(self) -> None:
        phase = Phase(name="only", target="Goblin", hp_share=1.0)
        assert phase.reduced_seconds == 0.0
        assert phase.reduced_dps_fraction == 1.0
        assert phase.idle_seconds == 0.0

    def test_a_shared_pools_hp_shares_sum_to_one(self) -> None:
        """Not enforced by the dataclass itself, and not universal - see
        `Phase`'s own docstring on the three shapes a script can take. This
        is the "one shared pool" shape, which `costing/hydra.py` and
        `costing/zulrah.py` both are; a boss-specific test pins each one."""
        script = FightScript(
            name="Fixture",
            phases=(
                Phase(name="a", target="A", hp_share=0.5),
                Phase(name="b", target="B", hp_share=0.5),
            ),
        )
        assert sum(p.hp_share for p in script.phases) == pytest.approx(1.0)

    def test_hp_share_can_exceed_one_or_pair_off_by_target(self) -> None:
        """The other two shapes `Phase`'s docstring names: a small target
        killed several times over (`hp_share > 1`), and several independent
        targets each fully depleted (each target's own phases sum to `1.0`,
        the script's total does not)."""
        several_kills = Phase(name="lungs", target="Small thing", hp_share=4.0)
        assert several_kills.hp_share > 1.0

        script = FightScript(
            name="Duo",
            phases=(
                Phase(name="a-1", target="A", hp_share=0.5),
                Phase(name="b-1", target="B", hp_share=0.5),
                Phase(name="a-2", target="A", hp_share=0.5),
                Phase(name="b-2", target="B", hp_share=0.5),
            ),
        )
        by_target: dict[str, float] = {}
        for phase in script.phases:
            by_target[phase.target] = by_target.get(phase.target, 0.0) + phase.hp_share
        assert by_target == {"A": pytest.approx(1.0), "B": pytest.approx(1.0)}
        assert sum(p.hp_share for p in script.phases) == pytest.approx(2.0)


class TestFightScript:
    def test_a_script_is_named_for_the_bare_boss_name(self) -> None:
        """Never a `#`-suffixed key - that vocabulary belongs to
        `Phase.target` alone, and `dps_bridge.SCRIPTS` is keyed on this name
        to intercept `best_kill`'s ordinary resolution."""
        script = FightScript(
            name="Fixture Boss",
            phases=(Phase(name="only", target="Fixture Boss#Version", hp_share=1.0),),
        )
        assert "#" not in script.name
        assert script.phases[0].target == "Fixture Boss#Version"

    def test_frozen(self) -> None:
        phase = Phase(name="a", target="A", hp_share=1.0)
        with pytest.raises(AttributeError):
            phase.hp_share = 0.5  # type: ignore[misc]
        script = FightScript(name="X", phases=(phase,))
        with pytest.raises(AttributeError):
            script.name = "Y"  # type: ignore[misc]
