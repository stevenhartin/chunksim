"""The Barracuda trials, counted from the mechanic instead of read as a quotient."""

from __future__ import annotations

import pytest

from chunksim.costing import barracuda
from chunksim.derive.task_names import strip_task_markup
from chunksim.store import cache


def _scraped() -> dict[str, float]:
    """`{task: xp/hour}` for every `wiki:sailing` row the scrape carries.

    Read from the shipped `wiki_rates.json`, which is checked in - so this
    needs neither the export nor a populated `cache/`.
    """
    training = cache.read_blob(cache.WIKI_RATES_BLOB_NAME)["data"]["training"]
    return {
        task: per_skill["Sailing"]["value"]
        for task, per_skill in training.items()
        if per_skill.get("Sailing", {}).get("source") == "wiki:sailing"
    }


def test_the_scrape_is_this_models_oracle() -> None:
    """**Every computed rate reproduces the scraped one to the experience
    point**, which is the whole reason this module is worth having. `Sailing
    training` states each figure as a wiki expression over components each
    trial's own page publishes; reading the components and re-doing the
    arithmetic must land in the same place, and a day it does not is a day
    the game moved. That makes this an identity - worthless as evidence, and
    exactly what a regression test wants.
    """
    scraped = _scraped()

    assert len(scraped) == 9, "three trials at three ranks"
    for task, published in scraped.items():
        named = barracuda.rank_of(task)
        assert named is not None, f"{task} is not joined by rank_of"
        trial, rank = named
        assert barracuda.xp_per_hour(trial, rank) == pytest.approx(published)


def test_the_join_is_upstreams_own_task_name() -> None:
    """The scrape joins `Complete <trial> at <rank> rank` structurally and so
    does this, so the two cannot disagree about which challenge a figure is
    about."""
    assert barracuda.rank_of("Complete ~|The Jubbly Jive|~ at Shark rank") == (
        "The Jubbly Jive",
        "Shark",
    )
    assert barracuda.rank_of("Complete ~|The Jubbly Jive|~ at Barracuda rank") is None
    assert barracuda.rank_of("Salvage at a ~|small shipwreck|~") is None


def test_a_lap_is_the_completion_plus_what_it_collects() -> None:
    """The Tempor Tantrum's own reward table: 385 for finishing at Swordfish
    rank, 14 lost supplies at 15 each, and two rum shipments at 19.5."""
    swordfish = barracuda.TRIALS["The Tempor Tantrum"].ranks["Swordfish"]

    assert swordfish.lap_experience == pytest.approx(385 + 14 * 15 + 2 * 19.5)


def test_the_one_time_rank_bonus_is_not_in_the_rate() -> None:
    """A rank's bonus - 1,000 to 50,000 experience - is paid once for beating
    the target time, not once a lap. Folding it in would make the first run of
    a rank the rate of every run: the Gwenith Glide's Marlin bonus alone is
    50,000, against 19,410 for the lap itself."""
    marlin = barracuda.TRIALS["The Gwenith Glide"].ranks["Marlin"]

    assert marlin.lap_experience == pytest.approx(16050 + 3360)


def test_the_restart_is_charged_and_it_is_not_free() -> None:
    """`Sailing training`'s own `+10` on every target time. It is the one
    figure here that comes off that page rather than off a trial's, and
    dropping it would raise the rates by 3% to 9%."""
    assert barracuda.RESTART_SECONDS == 10.0

    shark = barracuda.TRIALS["The Tempor Tantrum"].ranks["Shark"]
    charged = shark.xp_per_hour
    free = shark.lap_experience * 3600.0 / shark.target_seconds

    assert charged < free
    assert free / charged == pytest.approx(181 / 171)


def test_a_denser_rank_pays_better_per_second() -> None:
    """The three ranks of one trial are not the same lap run for longer -
    higher ranks collect more per second as well as taking longer, which is
    why each is its own method rather than the trial being one rate."""
    for trial in barracuda.TRIALS.values():
        rates = [trial.ranks[rank].xp_per_hour for rank in ("Swordfish", "Shark", "Marlin")]
        assert rates == sorted(rates)


def test_the_jubbly_jives_marlin_row_takes_the_counted_form() -> None:
    """**The one place two wiki pages disagree.** The trial's reward table says
    1,300 for lost supplies where its own prose says the rank collects 56
    boxes, and its Swordfish and Shark rows both pay 25 a box - so 1,400 is
    what its own text implies. On the other term the table says 704 and
    `Sailing training` says `9*64` = 576, and nothing decides between eleven
    trims and nine, so this takes the lower.
    """
    marlin = barracuda.TRIALS["The Jubbly Jive"].ranks["Marlin"]

    assert marlin.extras == ((56, 25.0), (9, 64.0))
    assert marlin.lap_experience == pytest.approx(6200 + 1400 + 576)
    # The trial page's own cells would give 8,204, which is 0.3% adrift.
    assert marlin.lap_experience != pytest.approx(8204.0)


def test_every_supply_figure_is_per_unit_where_the_wiki_publishes_one() -> None:
    """The Gwenith Glide is the exception and says so: its table has one `Lost
    supplies` column and no per-crate figure anywhere, so each rank carries a
    single term holding the stated total. Nothing is invented to fill the
    count in."""
    for rank in barracuda.TRIALS["The Gwenith Glide"].ranks.values():
        assert len(rank.extras) == 1
        assert rank.extras[0][0] == 1
    for name in ("The Tempor Tantrum", "The Jubbly Jive"):
        for rank in barracuda.TRIALS[name].ranks.values():
            assert len(rank.extras) == 2
            assert all(count > 1 for count, _ in rank.extras)


def test_methods_are_offered_only_for_valid_primary_challenges() -> None:
    """A trial the map cannot reach is not a training option, and neither is
    the `Start ~|...|~ trial with ...` challenge, which is not `Primary`."""
    challenges = {
        "Complete ~|The Tempor Tantrum|~ at Marlin rank": {"Primary": True, "Level": 30},
        "Start ~|The Tempor Tantrum|~ trial with Rum-dashed Ralph": {"Primary": False},
        "Complete ~|The Jubbly Jive|~ at Shark rank": {"Primary": True, "Level": 55},
    }
    valid: dict[str, dict[str, object]] = dict.fromkeys(challenges, {})

    found = barracuda.methods(challenges, valid)["Sailing"]

    assert len(found) == 2
    assert {method.level for method in found} == {30, 55}
    assert all(method.method == barracuda.ACTIVITY for method in found)
    assert all(method.match == "modelled" for method in found)


def test_a_method_names_the_knob_that_would_correct_it() -> None:
    """`training/<task>/Sailing`, keyed by the raw task name - which is what
    `training._modelled_tasks` reads to know the scrape has been superseded,
    and what `overrides.json` would be keyed by."""
    challenges = {"Complete ~|The Gwenith Glide|~ at Marlin rank": {"Primary": True}}

    found = barracuda.methods(challenges, dict.fromkeys(challenges, {}))["Sailing"]

    assert found[0].knob == "training/Complete ~|The Gwenith Glide|~ at Marlin rank/Sailing"


def test_nothing_outside_the_trials_is_claimed() -> None:
    """A Sailing map holds shipwrecks and courier tasks too; this must answer
    for the trials alone and leave the rest to `costing/salvage.py` and to
    whatever prices the rest."""
    challenges = {"Salvage at a ~|small shipwreck|~": {"Primary": True}}

    assert barracuda.methods(challenges, dict.fromkeys(challenges, {})) == {}


def test_the_task_name_round_trips_through_the_markup() -> None:
    """Task names are markup-bearing keys, so this builds the `~|...|~` form
    rather than stripping it off the export."""
    built = barracuda.task_name("The Tempor Tantrum", "Swordfish")

    assert built == "Complete ~|The Tempor Tantrum|~ at Swordfish rank"
    assert strip_task_markup(built) == "Complete The Tempor Tantrum at Swordfish rank"


@pytest.mark.real_export
def test_the_export_agrees_about_every_trials_level(real_export: object) -> None:
    """**The level a rate is offered at is a claim about the activity**, so it
    is stated in `TRIALS` rather than read off the challenge - and this pins
    that the two agree, so a game update moving a requirement fails here
    instead of quietly offering a trial to someone who cannot enter it.

    Also pins that upstream still carries all nine challenges under exactly the
    names this joins on. The trials arrived with Sailing in November 2025 and
    the export is refetched, so a rename is a live possibility.
    """
    challenges = real_export.challenges["Sailing"]  # type: ignore[attr-defined]

    seen = 0
    for trial, found in barracuda.TRIALS.items():
        for rank in found.ranks:
            task = barracuda.task_name(trial, rank)
            assert task in challenges, f"upstream no longer carries {task!r}"
            challenge = challenges[task]
            assert challenge["Primary"] is True
            assert challenge["Level"] == found.level
            # Not boostable, which is why a trial's level is a hard gate.
            assert challenge["NoBoost"] is True
            seen += 1
    assert seen == 9
