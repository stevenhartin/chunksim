"""`chunksim training`: what can train each skill, and what priced it."""

from __future__ import annotations

import pytest

from chunksim.cli import training
from chunksim.costing import coverage


def test_the_statuses_are_ordered_worst_first() -> None:
    """Which is the order a reader wants them counted in: the tail is the work
    left to do."""
    assert coverage.STATUSES[0] == "unpriced"
    assert coverage.STATUSES[-1] == "modelled"
    assert set(coverage.STATUSES) == set(training.STATUS_LABELS)


def test_a_guess_is_not_counted_as_modelled() -> None:
    """It is the one that should shrink and the one a reader most needs
    warning about: it looks exactly like a rate and is an admission."""
    assert coverage.status_of("guess") == "guess"
    assert coverage.status_of("modelled") == "modelled"
    assert coverage.status_of("computed") == "modelled"
    assert coverage.status_of("confirmed") == "modelled"


def test_a_pin_outranks_whatever_it_looks_like() -> None:
    """An override lands in `training` looking exactly like the guide row it
    replaced, so `Heuristics.pinned` is the only way to tell."""
    assert coverage.status_of("exact", pinned=True) == "pinned"
    assert coverage.status_of("exact") == "published"
    assert coverage.status_of("contained") == "published"


def test_the_floor_is_unpriced_rather_than_a_rate() -> None:
    assert coverage.status_of("default") == "unpriced"
    assert coverage.status_of("") == "unpriced"


def test_categories_that_are_not_skills_are_left_out() -> None:
    """The export files `Quest`, `Diary`, `Extra` and `Nonskill` alongside the
    real skills, and `Combat` is a category rather than a skill - a training
    report listing those would be listing five things nobody levels."""
    assert "Agility" in coverage.SKILLS
    assert not {"Quest", "Diary", "Extra", "Nonskill", "Combat"} & set(coverage.SKILLS)
    assert len(coverage.SKILLS) == 24


def test_omitting_the_map_is_a_different_question_not_a_default() -> None:
    """`cli/app.main` infers the sole cached map for every other family; this
    one opts out, because without `--map` it reports on the export."""
    import argparse

    parser = argparse.ArgumentParser()
    training.add_arguments(parser.add_subparsers(dest="command", required=True))

    assert parser.parse_args(["training"]).infer_map is False
    assert parser.parse_args(["training"]).map_id is None
    assert parser.parse_args(["training", "--map", "fray"]).map_id == "fray"
    assert parser.parse_args(["training", "Agility"]).skill == "Agility"


@pytest.mark.real_cache
def test_the_map_report_names_a_method_for_every_trainable_skill(
    real_state: tuple[object, dict[str, bool]], real_derived: object
) -> None:
    """**The point of the overview**: a skill with no reachable method reads as
    one, and every other names the method the estimate would actually spend."""
    from chunksim.costing import inputs
    from chunksim.store.derived_cache import Digests

    state, unlocked = real_state
    answer = inputs.training_answer(
        state,  # type: ignore[arg-type]
        unlocked,
        real_derived,  # type: ignore[arg-type]
        Digests(chunkinfo="test"),
        map_id="fray",
    )

    assert set(answer.best) == set(coverage.SKILLS)
    named = {skill for skill, option in answer.best.items() if option is not None}
    assert len(named) > 12, "the reference map trains most skills"
    for skill in named:
        option = answer.best[skill]
        assert option is not None
        # **Gated on the level the map is at.** "Best" for somebody at 40 is
        # not the level-90 method.
        assert option.level is None or option.level <= answer.levels[skill]
        assert option.effective_xp_per_hour > 0


def test_the_export_report_caches_its_derivation_and_keys_it_honestly() -> None:
    """**The ceiling state is the biggest derivation there is, and the first
    version of this command was the one place that never cached it** - every
    invocation paid ~4.3s of `pipeline.derive` again, which is what made a
    coverage report read as a slow command. It must go through
    `derive_cached` like every other subcommand, and its digests must be the
    real file hashes: the placeholder `Digests(chunkinfo="training")` it
    shipped with served a stale pricing straight across an export refetch,
    because nothing in the key moved when the export did.
    """
    import inspect

    from chunksim.cli import training as module

    source = inspect.getsource(module._report_export)
    assert "derive_cached(" in source, "the ceiling derivation must be cached"
    assert "digests(args)" in source, "and keyed by the real file digests"
    assert "pipeline.derive(" not in source
    assert 'Digests(chunkinfo="training")' not in inspect.getsource(module)
