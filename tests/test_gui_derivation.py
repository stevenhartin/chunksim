"""Tests for `gui/derivation.py`: the boundary between cheap and expensive.

The step walk is the part with a claim to prove. Everything else here is
loading and memoising, which the route tests already exercise end to end.
"""

from __future__ import annotations

import pytest

from fray_claude.gui.derivation import Derivations
from fray_claude.gui.panels import task_panel
from fray_claude.store import cache


RUN = "verf-sim/run-001"


@pytest.fixture
def run_length() -> int:
    """How many rolls `RUN` holds, or a skip when it is not cached."""
    try:
        return len(cache.read_rolls(RUN, cache.project_root()))
    except cache.CacheMissError:  # pragma: no cover - depends on the developer's cache
        return pytest.skip(f"{RUN} is not in this checkout's cache")


@pytest.mark.real_cache
def test_the_last_step_is_the_map_itself(run_length: int) -> None:
    """**The equality the whole feature rests on.**

    A run's `map.json` *is* its base with every roll applied, so asking for
    the last step and asking for the map have to be the same question. If they
    are not, then stepping to the end of a timeline shows something the map
    never was, and every number in the panel is quietly about a different
    world.

    Compared at the panel rather than at `Derived`, because the panel is what
    a person sees and it is where the one real difference showed up: deriving
    from the base state *unmodified* left the pre-simulation
    ticked-this-chunk marker on three groups, which `Derived.__eq__` would
    have reported as a difference in `other_tasks` without saying it was only
    a label. `load_step` commits that ledger for the same reason
    `simulate.simulated_payload` does.
    """
    derivations = Derivations(root=cache.project_root())

    whole = derivations.load(RUN)
    last = derivations.load_step(RUN, run_length)

    assert task_panel(last.derived) == task_panel(whole.derived)
    assert set(last.unlocked) == set(whole.unlocked)


@pytest.mark.real_cache
def test_a_step_holds_what_the_run_had_rolled_by_then(run_length: int) -> None:
    """Step k is the base plus k rolls - so the unlocked set only grows, and
    step 0 is the world the run started from rather than the one it reached."""
    derivations = Derivations(root=cache.project_root())

    sizes = [len(derivations.load_step(RUN, step).unlocked) for step in (0, 1, run_length)]

    assert sizes[0] < sizes[-1], "the run unlocked nothing"
    assert sizes[0] + 1 == sizes[1]
    assert sizes[-1] == sizes[0] + run_length


@pytest.mark.real_cache
def test_a_step_outside_the_run_is_refused(run_length: int) -> None:
    """Raised rather than clamped: a caller asking for roll 99 of a 50-roll
    run has a bug, and answering roll 50 hides it."""
    derivations = Derivations(root=cache.project_root())

    with pytest.raises(IndexError):
        derivations.load_step(RUN, run_length + 1)
    with pytest.raises(IndexError):
        derivations.load_step(RUN, -1)


@pytest.mark.real_cache
def test_a_step_records_which_one_it_answered(run_length: int) -> None:
    """`DerivedState.step` is how a route says what it was about; the map's
    own load leaves it `None`, which is the difference the panels turn on."""
    derivations = Derivations(root=cache.project_root())

    assert derivations.load_step(RUN, 1).step == 1
    assert derivations.load(RUN).step is None
