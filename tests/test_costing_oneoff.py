"""Actions upstream files as training methods and nobody trains with."""

from __future__ import annotations

import pytest

from chunksim.costing import coverage, oneoff
from chunksim.model.chunkinfo import ChunkInfo


def test_every_entry_is_named_individually() -> None:
    """**Named individually, never inferred.** Upstream flags all of these
    `Primary: True`, exactly as it flags `Build a ~|wooden fence|~`, so there
    is no property of the export to key a rule on."""
    decorations = {
        "Build a ~|mounted bass|~",
        "Build a ~|mounted swordfish|~",
        "Build a ~|mounted shark|~",
        "Build an ~|alchemical hydra heads (mounted)|~",
        "Build one of the boat ~|flags|~",
        "Apply a ~|boat paint|~ to a boat",
        "Apply a ~|sail colour|~ to a sail",
    }
    # The second shape: a loop whose cadence belongs to a supply nothing
    # states - a drop table's or a growth clock's, not the action's.
    supply_bound = {
        "Cast ~|basic reanimation|~",
        "Cast ~|adept reanimation|~",
        "Cast ~|expert reanimation|~",
        "Cast ~|master reanimation|~",
        "Cast ~|resurrect crops|~",
    }

    # The third: a permanent fusion that destroys both halves. There is one
    # boot slot and the inputs are gone, so a second is not a slower repeat.
    fusions = {
        "Create ~|avernic treads (et)|~",
        "Create ~|avernic treads (pe)|~",
        "Create ~|avernic treads (pr)|~",
        "Create ~|avernic treads (pe)(et)|~",
        "Create ~|avernic treads (pr)(et)|~",
        "Create ~|avernic treads (pr)(pe)|~",
        "Create ~|avernic treads (max)|~",
        # The same shape one weapon over: three unique Araxxor drops.
        "Craft a ~|noxious halberd|~",
        # And from a single drop - a `Tanzanite fang` at 1/1024 off Zulrah.
        # Dismantling returns 20,000 Zulrah's scales and no fang, which is
        # what separates it from the sword mounts below.
        "Fletch a ~|toxic blowpipe|~",
    }
    # One `Scurrius' spine` and three mutually exclusive weapons, so at most
    # one of the three ever happens. The wiki says what a second spine is for
    # and it is not a second bow: an experience lamp from Historian Aldo.
    rat_bone = {
        "Make a ~|bone mace|~",
        "Make a ~|bone shortbow|~",
        "Make a ~|bone staff|~",
    }

    # The fourth: an obstacle opened once and permanently open after. A rope
    # is tied to the God Wars Dungeon rock at Agility 70 and climbed free for
    # ever, so there is no second tie to put a cadence on.
    opened_once = {
        "Access the rope descent to ~|Saradomin's Encampment|~",
    }

    assert set(oneoff.ONE_OFF) == (
        decorations | supply_bound | fusions | rat_bone | opened_once
    )


@pytest.mark.real_export
def test_every_named_task_exists_and_is_primary(real_export: ChunkInfo) -> None:
    """**A key that matches nothing is silently inert**, which is the failure
    mode this whole module is one typo away from: `reason` returns `""` and the
    row goes back to reading `unpriced` with nothing to say it was meant to be
    exempt. Upstream also has to still call each one `Primary`, since a status
    that renames a training method has no business on anything else."""
    primary = {
        name
        for challenges in real_export.challenges.values()
        if isinstance(challenges, dict)
        for name, entry in challenges.items()
        if isinstance(entry, dict) and entry.get("Primary")
    }

    assert set(oneoff.ONE_OFF) <= primary


def test_every_entry_says_why() -> None:
    """The reason is the whole content of the status - it is printed in the
    column a priced method uses for its source."""
    assert all(reason.strip() for reason in oneoff.ONE_OFF.values())


def test_the_god_wars_rope_is_here_and_not_among_the_refusals() -> None:
    """**Two homes were possible and only one survives the disagreement.**
    `Rock (God Wars Dungeon)`'s own `{{Agility info}}` states `xp = 0` where
    the `Shortcuts` list's `XP` column says 6, and `shortcuts.REFUSED`'s test
    *is* the zero - so filing it there would rest the answer on the half of a
    contradiction this project cannot adjudicate. `one_off` is checked ahead
    of every priced tier, so the row reads the same whichever figure is
    right, and the reason it gives is the mechanic rather than the number."""
    from chunksim.costing import shortcuts

    task = "Access the rope descent to ~|Saradomin's Encampment|~"
    assert oneoff.reason(task)
    assert task not in shortcuts.refused()


def test_a_sword_mount_is_not_swept_in() -> None:
    """A rule over `(mounted)` names would take the three sword mounts, which
    are a real build-and-destroy loop: the wiki says the sword is returned
    when the object is destroyed (`recipe_rates.RETURNED_MATERIALS`)."""
    for task in (
        "Build a ~|darklight (mounted)|~",
        "Build a ~|silverlight (mounted)|~",
        "Build an ~|excalibur (mounted)|~",
    ):
        assert oneoff.reason(task) == ""


def test_ordinary_furniture_is_not_swept_in() -> None:
    assert oneoff.reason("Build a ~|wooden fence|~") == ""


def test_a_rat_bone_weapon_that_had_a_rate_is_still_exempt() -> None:
    """`Make a ~|bone mace|~` was the only one of the three with stated ticks
    on its `{{Recipe}}`, so it alone priced - at 357/hr, a plausible number on
    a real task. Having a rate is not the test; repeating being the point is."""
    assert oneoff.reason("Make a ~|bone mace|~")
    assert coverage.status_of("modelled", one_off=True) == coverage.ONE_OFF


def test_the_other_blowpipes_are_ordinary_fletching() -> None:
    """The Sailing-era blowpipes share a word and nothing else: each is logs
    and a squid beak, both of which the world provides repeatedly."""
    for task in (
        "Fletch a ~|camphor blowpipe|~",
        "Fletch an ~|ironwood blowpipe|~",
        "Fletch a ~|rosewood blowpipe|~",
    ):
        assert oneoff.reason(task) == ""


def test_the_status_beats_every_priced_tier() -> None:
    """A decoration a map can reach is exempt from being priced at all, rather
    than priced badly - the mounts come out at ~3 xp/hr if walked."""
    assert coverage.status_of("modelled", one_off=True) == coverage.ONE_OFF
    assert coverage.status_of("exact", one_off=True) == coverage.ONE_OFF
    assert coverage.status_of("default", one_off=True) == coverage.ONE_OFF
    assert coverage.status_of("modelled", pinned=True, one_off=True) == coverage.ONE_OFF


def test_unreachable_still_wins() -> None:
    """A decoration a map cannot reach is first of all unreachable: the report
    is about one world, and `one-off` is a claim about the challenge."""
    assert (
        coverage.status_of("default", reachable=False, one_off=True)
        == coverage.UNREACHABLE
    )
    assert (
        coverage.status_of(
            "default", reachable=False, one_off=True, absent=coverage.UNCOMPLETABLE
        )
        == coverage.UNCOMPLETABLE
    )


def test_the_whole_tread_family_is_named() -> None:
    """Upstream carries all seven under Smithing and Runecraft alike, with the
    same `Items` and the same `Priority` block - so naming six would leave one
    reading as a gap for no reason."""
    named = {task for task in oneoff.ONE_OFF if "avernic treads" in task}
    assert len(named) == 7
