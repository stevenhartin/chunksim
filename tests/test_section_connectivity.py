"""Every section this project's own derivation can never reach, however
many chunks are unlocked and however permissive the account behind them -
the export's own gap, not a defect here.

**The question, precisely**: run the *full* derivation - `unlocked_sections`
**and** `connected_sections` **and** `calc_challenges`, to a real fixed
point via `pipeline.derive` - with every rollable chunk unlocked, no
`manualSections`/`manualAreas` override, and a blank synthetic account (no
completed challenges, no skills, upstream's own seed rules). Which non-`0`
sections does that never mark reachable?

**Why the full pipeline, when the first version of this test called
`unlocked_sections` alone**: that version could only ever see the ordinary
`Connect` graph. `sections.connected_sections` - a whole reachability
mechanism this project had never ported at all until this test's own first
run found it - opens sections *only* a valid `ConnectsSections` challenge
names, and "valid" needs `calc_challenges`, which needs an account. A
`Connect`-only check was blind to every one of those, and over-reported: on
the same export, the first version's answer was 209; this one's is 79. See
`pipeline.py`'s own module docstring for the mechanism itself.

**Why a blank account, not a real map's**: reproducibility. `fray`'s own
real progress resolves this ceiling far further - 13, not 79, confirmed by
hand - but that number moves every time `fray`'s account does, which is a
fact about a player, not about this code or the export. A synthetic account
with nothing completed and nothing trained is the same answer every time,
so **this pins the pessimistic bound**: every section here is unreachable
*regardless* of account state, which is the strongest claim worth pinning.
A section that resolves only for a real, progressed account (`11317-2` among
them - see `pipeline.py`) is correctly absent from this list and is not a
regression; it is the fix working as intended.

**What this actually found, the first time the fixed pipeline ran
(2026-08-25 export)**: 79 sections, still real `Connect`/`ConnectsSections`
gaps rather than the `"???"` unresolved placeholder `sections.
_unresolved_only` already works around - the biggest cluster is the
49-section water pocket around chunks 7985-9016, gated on `ConnectsSections`
challenges ("Access stormy seas", "Access crystal-flecked waters") whose own
requirements a blank account cannot clear, not on a missing `Connect` edge
at all. **Before reporting any of these upstream, check whether it needs
only account progress this synthetic ceiling cannot supply, or a genuine
missing edge** - the two look identical from this test alone.

**A second, stricter ceiling: pure connectivity.** The 79 above still conflate two
different questions - "is there a path at all" and "has this account done enough to
walk it" - because a blank account cannot clear ordinary `Tasks`/`Skills`/`Items`
gates either, and most of the 79 are that, not a missing edge (the module docstring
above calls this out explicitly for the water pocket). `pure_connectivity_orphans`
answers the first question alone: every challenge in every category is assumed
already completed (`calc_challenges` itself is bypassed - patched out in
`chunksim.derive.pipeline`, per this project's own patch-target convention - rather
than gated normally) and every skill is capped at 99, so only the two genuinely
structural mechanisms remain able to say no: the `Connect` graph `unlocked_sections`
walks, and the `UnlocksArea`/`ConnectsSections` structural checks
(`_area_is_connected`, `connected_sections`'s `chunksValid`/`oneSectionValid`).
**The answer, over the whole 2026-08-25 export, is zero** - no section in the game
is unreachable by connectivity alone once every account gate is assumed cleared, so
`_KNOWN_PURE_CONNECTIVITY_ORPHANS` is pinned empty rather than to a number, and a
single name appearing there is worth investigating as a genuine missing edge, not
filed away as "another account-progress case" the way an addition to the 79 usually
is.

**Pinned rather than asserted to zero**, for the reason `test_other_tasks.py`'s
own `_KNOWN_ORACLE_DELTA` already gives: upstream is live, and an exact-zero
assertion would fail the moment any new content shipped with a temporary gap,
which is a different, less interesting finding than *this* map's own
lineage of already-known ones. Two directions of drift are both worth
seeing separately - a name added (a genuinely new problem, or new content
this test has not been taught about yet) and a name removed (something
upstream fixed, or this project's own model of `ConnectsSections` improved -
shrink the pinned set and go tell someone this worked).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from chunksim.derive.challenges import ChallengeResult
from chunksim.derive.pipeline import MapState, derive
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.model.experience import MAX_SKILL_LEVEL
from chunksim.model.rules import default_rules

#: The 23 real skills, for `_maxed_ceiling_state` - `max_skill`/`passive_skill`
#: are read by name (`sections._skills_needed_met`), not enumerated from the
#: export, so a played-with-every-skill-known ceiling has to name them itself.
_ALL_SKILLS: tuple[str, ...] = (
    "Attack", "Strength", "Defence", "Ranged", "Prayer", "Magic", "Runecraft",
    "Construction", "Hitpoints", "Agility", "Herblore", "Thieving", "Crafting",
    "Fletching", "Slayer", "Hunter", "Mining", "Smithing", "Fishing", "Cooking",
    "Firemaking", "Woodcutting", "Farming",
)


def _blank_ceiling_state(chunk_info: ChunkInfo) -> MapState:
    """A synthetic account with nothing completed, nothing trained, and
    upstream's own most-permissive seed rules - see the module docstring
    on why this, not a real map, is what the pinned test runs against."""
    return MapState(
        chunk_info=chunk_info,
        rules=default_rules(),
        settings={},
        manual_sections={},
        manual_areas={},
        manual_monsters={},
        manual_equipment={},
        backlogged_sources={},
        max_skill={},
        passive_skill={},
        completed_challenges={},
        checked_challenges={},
        manual_tasks={},
        backlog={},
        active_tasks={},
    )


def orphaned_sections(chunk_info: ChunkInfo) -> frozenset[str]:
    """Every non-`0` section unreachable at the full derivation's own
    ceiling - every rollable chunk unlocked, no manual overrides, a blank
    account. See the module docstring for exactly what that means and why.
    """
    chunk_ids = {chunk_id: True for chunk_id in chunk_info.sections}
    derived = derive(_blank_ceiling_state(chunk_info), chunk_ids)
    reachable = derived.reachable_sections
    orphans: set[str] = set()
    for chunk_id, chunk_sections in chunk_info.sections.items():
        if not isinstance(chunk_sections, dict):
            continue
        for section_id in chunk_sections:
            if section_id == "0":
                continue
            if not reachable.get(chunk_id, {}).get(section_id):
                orphans.add(f"{chunk_id}-{section_id}")
    return frozenset(orphans)


def _maxed_ceiling_state(chunk_info: ChunkInfo) -> MapState:
    """A synthetic account with every skill at 99 - the skill-gate half of
    `pure_connectivity_orphans`'s "assume everything cleared". `calc_challenges`
    itself is bypassed by `pure_connectivity_orphans`, so `completed_challenges`
    here is inert; carried anyway for a `MapState` that reads honestly on its
    own terms."""
    maxed = {skill: MAX_SKILL_LEVEL for skill in _ALL_SKILLS}
    return MapState(
        chunk_info=chunk_info,
        rules=default_rules(),
        settings={},
        manual_sections={},
        manual_areas={},
        manual_monsters={},
        manual_equipment={},
        backlogged_sources={},
        max_skill=maxed,
        passive_skill=maxed,
        completed_challenges={},
        checked_challenges={},
        manual_tasks={},
        backlog={},
        active_tasks={},
    )


def pure_connectivity_orphans(chunk_info: ChunkInfo) -> frozenset[str]:
    """Every non-`0` section unreachable by connectivity **alone** - every
    rollable chunk unlocked, every skill at 99, and every challenge in every
    category assumed already completed. See the module docstring for why
    this bypasses `calc_challenges` rather than feeding it a permissive
    account, and why the answer is pinned empty rather than to a count.
    """
    chunk_ids = {chunk_id: True for chunk_id in chunk_info.sections}

    def _assume_everything_valid(*args: object, **kwargs: object) -> ChallengeResult:
        valid: dict[str, dict[str, int | str | bool]] = {
            category: {str(name): True for name in names}
            for category, names in chunk_info.challenges.items()
            if isinstance(names, dict)
        }
        return ChallengeResult(valid=valid, unsupported=frozenset())

    with patch("chunksim.derive.pipeline.calc_challenges", side_effect=_assume_everything_valid):
        derived = derive(_maxed_ceiling_state(chunk_info), chunk_ids)

    reachable = derived.reachable_sections
    orphans: set[str] = set()
    for chunk_id, chunk_sections in chunk_info.sections.items():
        if not isinstance(chunk_sections, dict):
            continue
        for section_id in chunk_sections:
            if section_id == "0":
                continue
            if not reachable.get(chunk_id, {}).get(section_id):
                orphans.add(f"{chunk_id}-{section_id}")
    return frozenset(orphans)


class TestOrphanedSections:
    """`orphaned_sections` against small, hand-built graphs - the real
    export's own 79 are covered by the pinned regression test below, not
    reproduced here."""

    def test_a_section_reachable_only_by_a_bare_chunk_ref_is_not_orphaned(self) -> None:
        """`["D"]` (no `-section`) means "reachable once D is unlocked at
        all" - `sections._any_connection_open`'s own bare-ref branch."""
        info = ChunkInfo(
            {"sections": {"C": {"1": ["D"]}, "D": {"0": []}}}
        )
        assert orphaned_sections(info) == frozenset()

    def test_two_sections_that_only_reference_each_other_are_both_orphaned(self) -> None:
        """The shape most of the real export's orphan pockets are: real
        `Connect` refs, but only to each other."""
        info = ChunkInfo(
            {"sections": {"A": {"1": ["B-1"]}, "B": {"1": ["A-1"]}}}
        )
        assert orphaned_sections(info) == frozenset({"A-1", "B-1"})

    def test_a_pocket_reachable_through_one_real_edge_is_not_orphaned(self) -> None:
        """The fix this test exists to help find, worked backwards: one
        entrance edge from something already reachable clears a whole
        pocket at once."""
        info = ChunkInfo(
            {
                "sections": {
                    "A": {"1": ["B-1"]},
                    "B": {"1": ["A-1", "C-1"]},
                    "C": {"1": ["D"]},
                    "D": {"0": []},
                }
            }
        )
        assert orphaned_sections(info) == frozenset()

    def test_section_zero_is_never_reported(self) -> None:
        info = ChunkInfo({"sections": {"A": {"0": ["???"]}}})
        assert orphaned_sections(info) == frozenset()

    def test_a_valid_connects_sections_challenge_clears_a_pocket(self) -> None:
        """The mechanism the first version of this test could not see at
        all - `sections.connected_sections`, threaded through the same
        `pipeline.derive` this test now runs. No gate on the challenge, so
        a blank account still satisfies it."""
        info = ChunkInfo(
            {
                "sections": {"A": {"1": ["???"], "2": []}},
                "chunks": {"A": {"Sections": {"1": {}, "2": {}}}},
                "challenges": {
                    "Nonskill": {
                        "A-1 to A-2": {"Sections": ["A-1", "A-2"], "ConnectsSections": True}
                    }
                },
            }
        )
        assert orphaned_sections(info) == frozenset()

    def test_a_gated_connects_sections_challenge_leaves_the_pocket_orphaned(self) -> None:
        """A blank account cannot clear a real gate - this is the shape
        the 49-section water pocket in the real export turned out to be."""
        info = ChunkInfo(
            {
                "sections": {"A": {"1": ["???"], "2": []}},
                "chunks": {"A": {"Sections": {"1": {}, "2": {}}}},
                "challenges": {
                    "Nonskill": {
                        "A-1 to A-2": {
                            "Sections": ["A-1", "A-2"],
                            "ConnectsSections": True,
                            "Skills": {"Agility": 70},
                        }
                    }
                },
            }
        )
        assert orphaned_sections(info) == frozenset({"A-2"})


class TestPureConnectivityOrphans:
    """`pure_connectivity_orphans` against small, hand-built graphs - the
    real export's own answer (zero, over the whole 2026-08-25 export) is
    covered by the pinned regression test below."""

    def test_a_skill_gate_a_blank_account_fails_is_cleared(self) -> None:
        """The exact differentiator from `orphaned_sections`: a `Skills`
        gate on a `ConnectsSections` challenge blanks out `orphaned_sections`
        (see `test_a_gated_connects_sections_challenge_leaves_the_pocket_orphaned`
        above) but not this - `calc_challenges` is bypassed entirely, so the
        gate is never even asked."""
        info = ChunkInfo(
            {
                "sections": {"A": {"1": ["???"], "2": []}},
                "chunks": {"A": {"Sections": {"1": {}, "2": {}}}},
                "challenges": {
                    "Nonskill": {
                        "A-1 to A-2": {
                            "Sections": ["A-1", "A-2"],
                            "ConnectsSections": True,
                            "Skills": {"Agility": 70},
                        }
                    }
                },
            }
        )
        assert orphaned_sections(info) == frozenset({"A-2"})
        assert pure_connectivity_orphans(info) == frozenset()

    def test_no_edge_at_all_is_still_orphaned(self) -> None:
        """Assuming every gate cleared cannot invent a `Connect` edge that
        was never in the export - a genuinely missing edge stays missing."""
        info = ChunkInfo({"sections": {"A": {"1": []}, "B": {"1": []}}})
        assert pure_connectivity_orphans(info) == frozenset({"A-1", "B-1"})


#: See the module docstring for what this is, why 79 rather than the first
#: version's 209, and why it is pinned rather than asserted empty. Before
#: adding a name here, confirm it needs a genuine missing edge rather than
#: just account progress a blank ceiling cannot supply (a real map's own
#: `derive` result may already clear it - see the module docstring's `fray`
#: figure of 13). `gui.actions._uber_map`'s docstring has the `fray`/`13878`
#: worked example of telling a `manualSections` seal apart from either.
_KNOWN_ORPHANED_SECTIONS: frozenset[str] = frozenset(
    {
        "11059-3", "11059-4", "11314-2", "11314-3", "11315-1", "11315-2",
        "11325-1", "11326-1", "11581-1", "7985-W2", "7986-W2", "8240-W2",
        "8241-W2", "8242-W2", "8243-W2", "8244-W2", "8245-W2", "8246-W2",
        "8246-W3", "8247-W2", "8248-W2", "8252-1", "8252-2", "8252-3",
        "8253-1", "8253-2", "8253-3", "8495-W3", "8496-W2", "8497-W1",
        "8498-W1", "8499-2", "8499-W2", "8500-1", "8500-W2", "8501-1",
        "8501-W1", "8501-W2", "8502-W1", "8502-W2", "8502-W3", "8502-W4",
        "8502-W5", "8503-W1", "8503-W2", "8503-W3", "8504-W2", "8504-W3",
        "8504-W4", "8508-1", "8509-1", "8509-2", "8755-3", "8756-1",
        "8756-2", "8756-3", "8757-1", "8757-2", "8757-W1", "8758-W1",
        "8758-W2", "8759-W1", "8759-W2", "8759-W3", "8759-W4", "8760-W2",
        "8760-W3", "8760-W4", "9012-1", "9012-2", "9013-1", "9013-W1",
        "9013-W2", "9014-W1", "9014-W2", "9014-W3", "9014-W4", "9015-W1",
        "9016-W2",
    }
)


@pytest.mark.real_export
def test_no_undocumented_change_in_orphaned_sections(real_export: ChunkInfo) -> None:
    """The regression guard: see the module docstring for what "orphaned"
    means and why the answer is pinned rather than zero.

    Two separate assertions on purpose - a name **added** and a name
    **removed** are different findings and pytest's own failure output
    should say which happened rather than one opaque set diff.
    """
    found = orphaned_sections(real_export)

    added = found - _KNOWN_ORPHANED_SECTIONS
    assert not added, (
        f"{len(added)} newly-orphaned section(s) upstream has never "
        f"connected to anything reachable: {sorted(added)} - confirm it "
        "is a real Connect/ConnectsSections gap (not a base map's own "
        "manualSections seal) before adding it to _KNOWN_ORPHANED_SECTIONS"
    )

    fixed = _KNOWN_ORPHANED_SECTIONS - found
    assert not fixed, (
        f"{len(fixed)} section(s) are reachable now and should come off "
        f"the pinned list: {sorted(fixed)} - update "
        "_KNOWN_ORPHANED_SECTIONS in this file"
    )


#: See the module docstring's "pure connectivity" section - empty over the
#: whole 2026-08-25 export. A name appearing here is a genuine missing
#: `Connect`/`ConnectsSections` edge, not another account-progress case.
_KNOWN_PURE_CONNECTIVITY_ORPHANS: frozenset[str] = frozenset()


@pytest.mark.real_export
def test_no_undocumented_change_in_pure_connectivity_orphans(real_export: ChunkInfo) -> None:
    """The stricter regression guard: see the module docstring's "pure
    connectivity" section for what this measures and why it is pinned
    empty rather than to a count, unlike `_KNOWN_ORPHANED_SECTIONS`.
    """
    found = pure_connectivity_orphans(real_export)

    added = found - _KNOWN_PURE_CONNECTIVITY_ORPHANS
    assert not added, (
        f"{len(added)} section(s) are unreachable by connectivity alone, "
        f"even assuming every account gate cleared: {sorted(added)} - this "
        "is a genuine missing Connect/ConnectsSections edge, not account "
        "progress a ceiling can't supply; confirm before adding it here"
    )

    fixed = _KNOWN_PURE_CONNECTIVITY_ORPHANS - found
    assert not fixed, (
        f"{len(fixed)} section(s) are reachable now and should come off "
        f"the pinned list: {sorted(fixed)} - update "
        "_KNOWN_PURE_CONNECTIVITY_ORPHANS in this file"
    )
