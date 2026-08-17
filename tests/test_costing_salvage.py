"""Shipwreck salvaging, and the crewmate who does some of it for you."""

from __future__ import annotations

import pytest

from chunksim.costing import salvage


def test_a_crewmate_is_worth_d_squared_over_125() -> None:
    """**The wiki's own arithmetic, and it composes from two halves.** A
    crewmate rolls every 5 ticks against the player's 4 and finds salvage at
    `D/10` of the player's chance, so it finds `(4/5)(D/10)` as much - and it
    is paid `D/10` of the experience for each. The product is `D^2/125`, which
    the page states outright.
    """
    assert salvage.crew_bonus(60) == pytest.approx(16 / 125)  # D=4
    assert salvage.crew_bonus(40) == pytest.approx(9 / 125)   # D=3


def test_there_is_no_crewmate_before_level_forty() -> None:
    """Jobless Jim is the first hireable crewmate at all, so a wreck opening
    at 15 is salvaged alone until then - which is why the rate steps rather
    than being one number."""
    assert salvage.crew_bonus(39) == 0.0
    assert salvage.crew_bonus(1) == 0.0


def test_deckhandiness_four_is_the_ceiling() -> None:
    """Cabin Boy Jenkins at 60 is the best there has ever been; Jolly Jim at
    85 is a second D=4 rather than an upgrade, and everything hired between is
    worse than what is already held."""
    assert salvage.crew_bonus(60) == salvage.crew_bonus(85) == salvage.crew_bonus(99)


def test_a_wreck_steps_where_the_crewmates_arrive() -> None:
    """Nothing else in the model moves with level, so the rate is flat between
    unlocks and the bands say so."""
    assert salvage.steps_for(15) == (15, 40, 60)
    assert salvage.steps_for(73) == (73,)


def test_only_the_finding_experience_is_charged_here() -> None:
    """**Upstream splits the activity where the guides do not.** `Salvage at a
    ~|small shipwreck|~` and `Process some ~|small salvage|~` are two
    challenges; the guide bundles `10+5.5` into one figure. Charging the
    sorting experience here would credit it to the wrong method - so a small
    wreck is 140 salvages an hour at 10 each, not at 15.5."""
    assert salvage.xp_per_hour("Small salvage", 1) == pytest.approx(140.0 * 10.0)
    # The guide's 2,170/hr is exactly that plus the sorting half.
    assert 140.0 * 15.5 == pytest.approx(2170.0)


def test_the_players_own_rate_is_what_a_crewmate_multiplies() -> None:
    """The crewed guides state their own split - "2/3 of salvages are done by
    crew" - so 360 an hour at a large wreck is 120 the player found. A
    crewmate raises *that*, not the guide's total."""
    solo = salvage.xp_per_hour("Large salvage", 1)

    assert solo == pytest.approx(120.0 * 48.0)
    assert salvage.xp_per_hour("Large salvage", 60) == pytest.approx(solo * (1 + 16 / 125))


def test_a_non_shipwreck_is_not_priced() -> None:
    assert salvage.xp_per_hour("Guam leaf", 99) == 0.0


def test_every_wreck_opens_where_the_export_says() -> None:
    """The levels are the `Shipwreck` table's and must stay ordered with the
    experience: a bigger wreck opens later and pays more per salvage."""
    rows = sorted(salvage.SHIPWRECKS.values())
    assert [level for level, _, _ in rows] == sorted(level for level, _, _ in rows)
    assert [xp for _, xp, _ in rows] == sorted(xp for _, xp, _ in rows)


def test_sorting_is_the_page_s_own_cadence() -> None:
    """"When used optimally close to 1800 salvages per hour can be achieved" -
    a three-tick sort with the banking runs already in it, since a bare three
    ticks would be 2,000."""
    assert salvage.SORT_PER_HOUR == 1800.0


def test_sorting_costs_the_salvage_it_eats() -> None:
    """**The bound that stops sorting running away with the skill.** A station
    takes 1,800 salvages an hour whatever they are, so opulent salvage reads
    171,000/hr on its own - more than twice the best Barracuda trial. Every one
    of them had to be found first, at roughly 34 seconds each, and charging
    that is what turns the pair back into one activity.
    """
    challenges = {
        "Process some ~|opulent salvage|~ at a salvaging station": {
            "Level": 87, "Primary": True, "Items": ["Opulent salvage*"],
        },
    }

    per_xp = salvage.material_seconds_per_xp(
        challenges, dict.fromkeys(challenges, {}), 99
    )

    (cost,) = per_xp.values()
    assert cost == pytest.approx(salvage.salvage_seconds("Opulent salvage", 99) / 95.0)
    # Sorting on paper against sorting once the finding is paid for.
    raw = salvage.SORT_PER_HOUR * 95.0
    effective = 3600.0 / (3600.0 / raw + cost)
    assert raw > 150_000 and effective < 10_000


def test_a_salvage_costs_what_finding_it_costs() -> None:
    """Without this the walk charged `estimate.DEFAULT_ACTION_SECONDS` for a
    salvage, and sorting read as the fastest thing in Sailing by an order of
    magnitude. A crewmate makes finding faster, so the cost falls."""
    solo = salvage.salvage_seconds("Opulent salvage", 1)
    crewed = salvage.salvage_seconds("Opulent salvage", 60)

    assert solo == pytest.approx(3600.0 / 93.3)
    assert crewed < solo


def test_a_wreck_is_not_a_sorting_challenge() -> None:
    """Joined on the export's own `Items`: a sorting challenge is the one that
    *eats* a salvage, where the wreck produces it."""
    wreck = {"Level": 87, "Primary": True, "Output": "Opulent salvage"}

    assert salvage._sorted_salvage(wreck) is None
