"""Every section this project's own connectivity graph can never reach,
however many chunks are unlocked - the export's own gap, not a defect here.

**The question, precisely**: with every rollable chunk unlocked and no
`manualSections`/`manualAreas` override at all, which non-`0` sections does
`sections.unlocked_sections`' real fixed point still never mark reachable?
That is a stronger ceiling than any one map's own state - a base map's own
`manualSections` seal (`fray` closes `13878`'s sections 2-5) or a `Connect`
gap both show up here, and the two are worth telling apart before reporting
anything upstream: a seal is a player's choice this project should not
inherit (`gui.actions._uber_map` already drops it); a genuine `Connect` gap
is upstream's own data never declaring a way in.

**What this actually found, the first time it ran (2026-08-25 export)**:
209 orphaned sections, every one of them with *real* `Connect` refs - never
the `"???"` unresolved placeholder `sections._unresolved_only` already works
around. They cluster into 28 self-contained pockets (2 to 49 sections each)
that reference each other freely but never link back to anything reachable -
the biggest is 49 water sections (`W`-suffixed), the next two are 30 and 20
ordinary ones. Every pocket looks like the same one mistake repeated: the
*exit* edges out of it are declared, the *entrance* edge from the reachable
world into it never was - exactly the shape `Weaponsmaster`'s circular
`taskUnlocks` gate turned out to be a cousin of, and exactly what stranded
`Shilo Village` step 3 behind `11566-3`.

**Pinned rather than asserted to zero**, for the reason `test_other_tasks.py`'s
own `_KNOWN_ORACLE_DELTA` already gives: upstream is live, and an exact-zero
assertion would fail the moment any new content shipped with a temporary gap,
which is a different, less interesting finding than *this* map's own
lineage of already-known ones. Two directions of drift are both worth
seeing separately - a name added (a genuinely new problem, or new content
this test has not been taught about yet) and a name removed (something
upstream fixed - shrink the pinned set and go tell someone this worked).
"""

from __future__ import annotations

import pytest

from chunksim.derive.sections import unlocked_sections
from chunksim.model.chunkinfo import ChunkInfo


def orphaned_sections(chunk_info: ChunkInfo) -> frozenset[str]:
    """Every non-`0` section unreachable with every rollable chunk unlocked
    and no manual overrides at all - `chunk_info.sections`' own ceiling.

    Section `0` is excluded because it is never a real entry in
    `unlocked_sections`' own `reachable` table - it is implicitly reachable
    the moment its chunk is unlocked (`sections.py`'s own `section_id ==
    "0"` skip), so asking whether it is "in" the table asks the wrong
    question.
    """
    chunk_ids = {chunk_id: True for chunk_id in chunk_info.sections}
    reachable = unlocked_sections(chunk_ids, chunk_info)
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
    export's own 209 are covered by the pinned regression test below, not
    reproduced here."""

    def test_a_section_reachable_only_by_a_bare_chunk_ref_is_not_orphaned(self) -> None:
        """`["D"]` (no `-section`) means "reachable once D is unlocked at
        all" - `sections._any_connection_open`'s own bare-ref branch."""
        info = ChunkInfo(
            {"sections": {"C": {"1": ["D"]}, "D": {"0": []}}}
        )
        assert orphaned_sections(info) == frozenset()

    def test_two_sections_that_only_reference_each_other_are_both_orphaned(self) -> None:
        """The exact shape every one of the real export's 28 pockets is:
        real `Connect` refs, but only to each other."""
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


#: See the module docstring for what this is and why it is pinned rather
#: than asserted empty. Regenerate with `orphaned_sections(real_export)`
#: after fixing (and re-fetching) any of these; add a name here only after
#: confirming it is a genuine `Connect` gap, not a base map's own
#: `manualSections` seal - `gui.actions._uber_map`'s docstring has the
#: `fray`/`13878` worked example of telling the two apart.
_KNOWN_ORPHANED_SECTIONS: frozenset[str] = frozenset(
    {
        "10018-1", "10018-2", "10019-1", "10028-1", "10043-1", "10044-1",
        "10274-1", "10274-2", "10275-1", "10275-2", "10284-1", "10300-1",
        "10556-1", "10558-1", "10559-1", "10794-1", "10794-2", "10794-3",
        "10794-4", "10795-1", "10795-2", "11050-1", "11050-2", "11050-3",
        "11050-4", "11050-5", "11051-1", "11056-W1", "11057-W1", "11059-3",
        "11059-4", "11062-3", "11312-W1", "11313-W1", "11313-W3", "11314-2",
        "11314-3", "11315-1", "11315-2", "11318-5", "11318-6", "11318-7",
        "11319-3", "11319-4", "11325-1", "11326-1", "11562-1", "11566-3",
        "11567-2", "11568-2", "11581-1", "11821-W1", "11822-1", "11823-1",
        "12077-W1", "12325-1", "12325-2", "12326-1", "12326-2", "12326-3",
        "12327-1", "12333-W1", "12580-1", "12581-1", "12581-2", "12582-1",
        "12582-2", "12582-3", "12582-4", "12582-5", "12583-1", "12583-2",
        "12589-W1", "12589-W2", "12836-1", "12836-2", "12836-3", "12836-4",
        "12837-1", "12837-2", "12837-3", "12837-4", "12837-5", "12837-6",
        "12838-1", "12838-2", "12839-1", "12839-2", "13092-1", "13093-1",
        "13093-2", "13094-1", "13104-W1", "13105-W1", "13618-2", "13619-1",
        "13619-2", "13620-1", "13620-2", "13620-4", "13621-1", "13622-3",
        "13622-4", "13622-5", "13874-2", "13874-3", "13875-1", "13875-2",
        "13875-3", "13876-1", "13877-1", "13877-2", "13878-2", "13878-3",
        "13878-5", "14130-2", "14130-3", "14131-2", "4395-2", "4650-1",
        "4651-1", "4651-2", "4907-1", "4910-2", "4911-2", "5677-3",
        "5678-3", "5933-1", "7985-W2", "7986-W2", "8240-W2", "8241-W2",
        "8242-W2", "8243-W2", "8244-W2", "8245-W2", "8246-W2", "8246-W3",
        "8247-W2", "8248-W2", "8252-1", "8252-2", "8252-3", "8253-1",
        "8253-2", "8253-3", "8495-2", "8495-W3", "8496-2", "8496-W2",
        "8497-W1", "8498-W1", "8499-2", "8499-W2", "8500-1", "8500-W2",
        "8501-1", "8501-W1", "8501-W2", "8502-W1", "8502-W2", "8502-W3",
        "8502-W4", "8502-W5", "8503-W1", "8503-W2", "8503-W3", "8504-W2",
        "8504-W3", "8504-W4", "8508-1", "8509-1", "8509-2", "8755-3",
        "8756-1", "8756-2", "8756-3", "8757-1", "8757-2", "8757-W1",
        "8758-W1", "8758-W2", "8759-W1", "8759-W2", "8759-W3", "8759-W4",
        "8760-W2", "8760-W3", "8760-W4", "9012-1", "9012-2", "9013-1",
        "9013-W1", "9013-W2", "9014-W1", "9014-W2", "9014-W3", "9014-W4",
        "9015-W1", "9016-W2", "9274-1", "9275-1", "9276-1", "9531-1",
        "9531-2", "9532-1", "9532-2", "9532-3", "9772-1",
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
        "is a real Connect gap (not a base map's own manualSections seal) "
        "before adding it to _KNOWN_ORPHANED_SECTIONS"
    )

    fixed = _KNOWN_ORPHANED_SECTIONS - found
    assert not fixed, (
        f"{len(fixed)} section(s) are reachable now and should come off "
        f"the pinned list: {sorted(fixed)} - update "
        "_KNOWN_ORPHANED_SECTIONS in this file"
    )
