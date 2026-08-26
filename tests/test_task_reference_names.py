"""A `Tasks` reference that differs from the challenge it names only by
letter case - the general form of the check that first found the Combat
Achievements gap this pins.

**The shape.** A challenge's `Tasks` field maps another challenge's *name*
to the category it lives in (`{"Slay a ~|Basilisk Knight|~": "Slayer"}`), and
`challenges._tasks_requirement_met` looks that name up as an exact key of
`valid[category]` - a plain dict membership test, with no case folding
anywhere, matching upstream's own `hasOwnProperty` checks in `worker.js`
(confirmed by reading it directly, not inferred). Two of the export's
Combat Achievements tasks reference `"Slay a ~|basilisk knight|~"` and
`"Slay a ~|skeletal wyvern|~"` (lower-case), but the real Slayer challenges
are keyed `'Slay a ~|Basilisk Knight|~'` and `'Slay a ~|Skeletal Wyvern|~'`
(capitalised) - so the reference can never resolve, however far the account
otherwise progresses, and the two Combat Achievements tasks stay
permanently invalid.

**Why this is pinned rather than fixed.** Confirmed directly against
`chunk-picker-v2/worker.js` that upstream's own live tool has the identical
case-sensitive lookup and the identical typo in its own export - this is not
a chunksim porting gap, the same standard `quest_jumps.py`'s own entries were
held to before being modelled. Correcting it here would mean silently
diverging from what a real player's own source-chunk session actually
computes, which this project's "port only" default explicitly rules out
(see CLAUDE.md's Dragon Slayer I discussion for the same call made the same
way). Pinning it is the point: once a case mismatch is understood and
recorded here, re-discovering it while investigating some *other* stuck
report (as happened once already, chasing the Combat Achievements count) is
wasted effort - a name coming *off* this set means upstream corrected the
typo, and the fix is to delete that entry, not to touch any production code.

**Why scanned generally, not hand-checked for just these two.** Mirrors
`test_quest_step_cycles.py`'s own reasoning: a check a user happened to
notice by hand only proves that one instance clean; this walks every
`Tasks` reference in the whole export, across every category, so a case
mismatch anywhere else is caught the same way. `[+]` family references are
skipped - they resolve through `codeItems.tasksPlus`, a different lookup
entirely, not a direct key match, so a bare-name miss there isn't this bug.

**Cost.** A pure export scan, no `derive()` calls - cheap enough to run
every time, unlike the `slow`-marked scanners elsewhere in this suite.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from chunksim.model.chunkinfo import ChunkInfo

#: One entry per real `Tasks` mismatch: `(category, challenge_name,
#: task_skill, broken_task_name)`. `category`/`challenge_name` name the
#: challenge carrying the broken reference; `task_skill`/`broken_task_name`
#: are its own `Tasks` entry, verbatim.
TaskReferenceMismatch = tuple[str, str, str, str]


def find_task_reference_case_mismatches(
    chunk_info: ChunkInfo,
) -> frozenset[TaskReferenceMismatch]:
    """Every `Tasks` reference across the whole export whose exact name is
    not a key of its target category, but a case-insensitively identical
    name is - see the module docstring for what this means and why it is
    worth telling apart from a reference that doesn't exist at all (a
    different, and more concerning, kind of gap this function does not
    report on)."""
    challenges = chunk_info.challenges
    casefold_index: dict[str, dict[str, str]] = {
        category: {name.casefold(): name for name in entries}
        for category, entries in challenges.items()
        if isinstance(entries, Mapping)
    }

    found: set[TaskReferenceMismatch] = set()
    for category, entries in challenges.items():
        if not isinstance(entries, Mapping):
            continue
        for name, challenge in entries.items():
            if not isinstance(challenge, Mapping):
                continue
            tasks = challenge.get("Tasks")
            if not isinstance(tasks, Mapping):
                continue
            for task_name, task_skill in tasks.items():
                if not isinstance(task_skill, str) or "[+]" in task_name:
                    continue
                target = challenges.get(task_skill)
                if not isinstance(target, Mapping) or task_name in target:
                    continue
                if task_name.casefold() in casefold_index.get(task_skill, {}):
                    found.add((category, name, task_skill, task_name))
    return frozenset(found)


class TestFindTaskReferenceCaseMismatches:
    def test_an_exact_match_is_not_reported(self) -> None:
        info = ChunkInfo(
            {
                "challenges": {
                    "Quest": {"~|Q|~ 1": {"Tasks": {"Slay a dragon": "Slayer"}}},
                    "Slayer": {"Slay a dragon": {}},
                }
            }
        )
        assert find_task_reference_case_mismatches(info) == frozenset()

    def test_a_case_only_mismatch_is_reported(self) -> None:
        info = ChunkInfo(
            {
                "challenges": {
                    "Quest": {"~|Q|~ 1": {"Tasks": {"slay a dragon": "Slayer"}}},
                    "Slayer": {"Slay a Dragon": {}},
                }
            }
        )
        assert find_task_reference_case_mismatches(info) == {
            ("Quest", "~|Q|~ 1", "Slayer", "slay a dragon")
        }

    def test_a_reference_with_no_match_at_all_is_not_reported(self) -> None:
        """A name that doesn't exist under any case is a different (and
        more concerning) kind of gap than this function reports on - see
        the module docstring."""
        info = ChunkInfo(
            {
                "challenges": {
                    "Quest": {"~|Q|~ 1": {"Tasks": {"Slay a griffin": "Slayer"}}},
                    "Slayer": {"Slay a dragon": {}},
                }
            }
        )
        assert find_task_reference_case_mismatches(info) == frozenset()

    def test_a_plus_family_reference_is_skipped(self) -> None:
        """`[+]` families resolve through `codeItems.tasksPlus`, not a
        direct key match - a bare-name miss there isn't this bug."""
        info = ChunkInfo(
            {
                "challenges": {
                    "Quest": {"~|Q|~ 1": {"Tasks": {"slayermasters[+]x1": "Slayer"}}},
                    "Slayer": {},
                }
            }
        )
        assert find_task_reference_case_mismatches(info) == frozenset()


#: Confirmed against upstream's own `worker.js` (see the module docstring)
#: to be a real export typo, not a chunksim porting gap - pinned rather
#: than fixed. A name coming *off* this set means upstream corrected it;
#: delete that entry rather than leaving it stale. A name appearing that
#: isn't here is a new, uninvestigated case and must be confirmed against
#: upstream's own source the same way before being added.
_KNOWN_TASK_REFERENCE_CASE_MISMATCHES: frozenset[TaskReferenceMismatch] = frozenset(
    {
        (
            "Diary",
            "~|Combat Achievements#Elite|~ Reflecting on This Encounter",
            "Slayer",
            "Slay a ~|basilisk knight|~",
        ),
        (
            "Diary",
            "~|Combat Achievements#Medium|~ A Frozen Foe from the Past",
            "Slayer",
            "Slay a ~|skeletal wyvern|~",
        ),
    }
)


@pytest.mark.real_export
def test_no_undocumented_task_reference_case_mismatch(real_export: ChunkInfo) -> None:
    found = find_task_reference_case_mismatches(real_export)

    added = found - _KNOWN_TASK_REFERENCE_CASE_MISMATCHES
    assert not added, (
        f"{len(added)} newly-found Tasks case mismatch(es): {added} - confirm each is a real "
        "export typo (not a chunksim bug) against upstream's own worker.js before adding it to "
        "_KNOWN_TASK_REFERENCE_CASE_MISMATCHES"
    )

    fixed = _KNOWN_TASK_REFERENCE_CASE_MISMATCHES - found
    assert not fixed, (
        f"{len(fixed)} known mismatch(es) no longer found: {fixed} - upstream corrected the typo, "
        "remove the entry from _KNOWN_TASK_REFERENCE_CASE_MISMATCHES rather than leaving it stale"
    )
