"""A challenge requirement (`Tasks`, `Monsters`, `NPCs`, `Objects`) that
differs from the real name it points at only by letter case - the general
form of the check that first found the Combat Achievements gap this pins,
generalised to every field the same shape of typo can hide in.

**The shape.** `challenges._tasks_requirement_met` looks a `Tasks` name up
as an exact key of `valid[category]`; `challenges._presence_requirement_met`
does the same for `Monsters`/`NPCs` against the derived source index (and
this project's own `Objects` check, elsewhere, follows the identical
pattern). All three are plain dict-membership tests, with no case folding
anywhere - matching upstream's own `worker.js`, confirmed by reading it
directly rather than inferred (`hasOwnProperty`/`!monsters[monster]`/
`!npcs[npc]`, every one case-sensitive). A reference differing from the real
name only by case can therefore never resolve, however far the account
otherwise progresses.

**Why pinned rather than fixed.** Every entry below was confirmed against
`chunk-picker-v2/worker.js` to be a real export typo upstream's own live
tool has too, not a chunksim porting gap - the same standard `quest_jumps.py`
`entries` were held to before being modelled, and the same call CLAUDE.md's
Dragon Slayer I discussion makes for the same reason: correcting it here
would silently diverge from what a real player's own source-chunk session
actually computes, and this project's "port only" default rules that out.
Pinning it is the point: once a case mismatch is understood and recorded
here, re-discovering it while investigating some *other* stuck report (as
happened twice already - the two `Tasks` cases chasing Combat Achievements'
incomplete count, then the `Monsters`/`NPCs` cases chasing Shellbane
gryphon specifically) is wasted effort. A name coming *off* this set means
upstream corrected the typo; delete that entry rather than leaving it stale.

**Why scanned generally, across every field, not hand-checked one boss at a
time.** Mirrors `test_quest_step_cycles.py`'s own reasoning: a check a user
happened to notice by hand only proves that one instance clean. Chasing
"Shellbane Gryphon" (capitalised, the Combat Achievements spelling) against
the real chunk-resident monster "Shellbane gryphon" (lower-case `g`) found
seven more `Monsters` mismatches this way, plus an unrelated eighth
(`Their bane awaits.`, a Cryptic clue step) and a wholly separate `NPCs`
case (`Moonlight Moth`/`Moonlight moth`) neither investigation was
looking for - exactly the shape a hand-check misses.

**`Items` is deliberately not scanned here.** Unlike a monster/NPC/object's
chunk-presence, an item's availability is a fixpoint over recipes and
gathering, not a flat name lookup - `costing/`'s own item walk. A bare-name
"miss" there is very often a real item nothing crafts *yet* being checked
against a table that only grows the walk resolves, not a typo, so a naive
case-fold scan would misreport routine gaps as export bugs. Scoped to the
three fields that really are flat presence checks.

**`[+]` family references are skipped** in every field - they resolve
through `codeItems.{tasksPlus,monstersPlus,npcsPlus,objectsPlus}`, a
different lookup entirely, not a direct key match, so a bare-name miss
there isn't this bug.

**Cost.** A pure export scan, no `derive()` calls - cheap enough to run
every time, unlike the `slow`-marked scanners elsewhere in this suite.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from chunksim.model.chunkinfo import ChunkInfo

#: One entry per real mismatch: `(category, challenge_name, field_label,
#: broken_name)`. `category`/`challenge_name` name the challenge carrying
#: the broken reference. `field_label` is `f"Tasks->{target_category}"` for
#: a `Tasks` entry (the target category matters and is worth keeping), or
#: plainly `"Monsters"`/`"NPCs"`/`"Objects"` for the other three fields.
#: `broken_name` is the challenge's own reference, verbatim.
ReferenceCaseMismatch = tuple[str, str, str, str]


def _chunk_level_names(chunk_info: ChunkInfo, field: str) -> frozenset[str]:
    """Every name appearing anywhere as a top-level or per-section `field`
    key across every chunk - the real vocabulary `Monsters`/`NPCs`/`Objects`
    requirements are ultimately checked against (via the derived source
    index), reduced here to a flat name scan since presence, not
    reachability, is all a case-fold check needs."""
    names: set[str] = set()
    for entry in chunk_info.chunks.values():
        if not isinstance(entry, Mapping):
            continue
        names.update(entry.get(field, {}) if isinstance(entry.get(field), Mapping) else {})
        sections = entry.get("Sections")
        if isinstance(sections, Mapping):
            for section_entry in sections.values():
                if isinstance(section_entry, Mapping):
                    values = section_entry.get(field)
                    if isinstance(values, Mapping):
                        names.update(values)
    return frozenset(names)


def _find_case_mismatches(
    names: frozenset[str], referenced: list[str]
) -> list[str]:
    """Every non-`[+]` name in `referenced` that isn't in `names` exactly,
    but is once both are case-folded."""
    casefold_index = {name.casefold(): name for name in names}
    return [
        ref
        for ref in referenced
        if "[+]" not in ref and ref not in names and ref.casefold() in casefold_index
    ]


def find_reference_case_mismatches(chunk_info: ChunkInfo) -> frozenset[ReferenceCaseMismatch]:
    """Every `Tasks`/`Monsters`/`NPCs`/`Objects` reference across the whole
    export whose exact name doesn't exist where it points, but a
    case-insensitively identical one does - see the module docstring for
    what this means and why it is worth telling apart from a reference
    that doesn't exist under any case at all (a different, and more
    concerning, kind of gap this function does not report on)."""
    challenges = chunk_info.challenges
    tasks_casefold_index: dict[str, dict[str, str]] = {
        category: {name.casefold(): name for name in entries}
        for category, entries in challenges.items()
        if isinstance(entries, Mapping)
    }
    presence_names = {
        field: _chunk_level_names(chunk_info, field) for field in ("Monster", "NPC", "Object")
    }
    presence_field_labels = {"Monster": "Monsters", "NPC": "NPCs", "Object": "Objects"}

    found: set[ReferenceCaseMismatch] = set()
    for category, entries in challenges.items():
        if not isinstance(entries, Mapping):
            continue
        for name, challenge in entries.items():
            if not isinstance(challenge, Mapping):
                continue

            tasks = challenge.get("Tasks")
            if isinstance(tasks, Mapping):
                for task_name, task_skill in tasks.items():
                    if not isinstance(task_skill, str) or "[+]" in task_name:
                        continue
                    target = challenges.get(task_skill)
                    if not isinstance(target, Mapping) or task_name in target:
                        continue
                    if task_name.casefold() in tasks_casefold_index.get(task_skill, {}):
                        found.add((category, name, f"Tasks->{task_skill}", task_name))

            for chunk_field, chall_field in (
                ("Monster", "Monsters"),
                ("NPC", "NPCs"),
                ("Object", "Objects"),
            ):
                referenced = challenge.get(chall_field)
                if not isinstance(referenced, list):
                    continue
                for mismatch in _find_case_mismatches(
                    presence_names[chunk_field],
                    [ref for ref in referenced if isinstance(ref, str)],
                ):
                    found.add((category, name, presence_field_labels[chunk_field], mismatch))
    return frozenset(found)


class TestFindReferenceCaseMismatches:
    def test_an_exact_task_match_is_not_reported(self) -> None:
        info = ChunkInfo(
            {
                "chunks": {},
                "challenges": {
                    "Quest": {"~|Q|~ 1": {"Tasks": {"Slay a dragon": "Slayer"}}},
                    "Slayer": {"Slay a dragon": {}},
                },
            }
        )
        assert find_reference_case_mismatches(info) == frozenset()

    def test_a_case_only_task_mismatch_is_reported(self) -> None:
        info = ChunkInfo(
            {
                "chunks": {},
                "challenges": {
                    "Quest": {"~|Q|~ 1": {"Tasks": {"slay a dragon": "Slayer"}}},
                    "Slayer": {"Slay a Dragon": {}},
                },
            }
        )
        assert find_reference_case_mismatches(info) == {
            ("Quest", "~|Q|~ 1", "Tasks->Slayer", "slay a dragon")
        }

    def test_a_task_with_no_match_at_all_is_not_reported(self) -> None:
        """A name that doesn't exist under any case is a different (and
        more concerning) kind of gap than this function reports on - see
        the module docstring."""
        info = ChunkInfo(
            {
                "chunks": {},
                "challenges": {
                    "Quest": {"~|Q|~ 1": {"Tasks": {"Slay a griffin": "Slayer"}}},
                    "Slayer": {"Slay a dragon": {}},
                },
            }
        )
        assert find_reference_case_mismatches(info) == frozenset()

    def test_a_plus_family_task_reference_is_skipped(self) -> None:
        info = ChunkInfo(
            {
                "chunks": {},
                "challenges": {
                    "Quest": {"~|Q|~ 1": {"Tasks": {"slayermasters[+]x1": "Slayer"}}},
                    "Slayer": {},
                },
            }
        )
        assert find_reference_case_mismatches(info) == frozenset()

    def test_a_case_only_monster_mismatch_is_reported(self) -> None:
        info = ChunkInfo(
            {
                "chunks": {"1": {"Monster": {"Shellbane gryphon": 1}}},
                "challenges": {
                    "Diary": {"~|CA|~ Task": {"Monsters": ["Shellbane Gryphon"]}},
                },
            }
        )
        assert find_reference_case_mismatches(info) == {
            ("Diary", "~|CA|~ Task", "Monsters", "Shellbane Gryphon")
        }

    def test_a_sectioned_monster_placement_is_indexed_too(self) -> None:
        info = ChunkInfo(
            {
                "chunks": {"1": {"Sections": {"1": {"Monster": {"Shellbane gryphon": 1}}}}},
                "challenges": {
                    "Diary": {"~|CA|~ Task": {"Monsters": ["Shellbane Gryphon"]}},
                },
            }
        )
        assert find_reference_case_mismatches(info) == {
            ("Diary", "~|CA|~ Task", "Monsters", "Shellbane Gryphon")
        }

    def test_a_case_only_npc_mismatch_is_reported(self) -> None:
        info = ChunkInfo(
            {
                "chunks": {"1": {"NPC": {"Moonlight moth": 1}}},
                "challenges": {
                    "Hunter": {"Catch a moth": {"NPCs": ["Moonlight Moth"]}},
                },
            }
        )
        assert find_reference_case_mismatches(info) == {
            ("Hunter", "Catch a moth", "NPCs", "Moonlight Moth")
        }

    def test_a_plus_family_monster_reference_is_skipped(self) -> None:
        info = ChunkInfo(
            {
                "chunks": {"1": {"Monster": {"Dragon": 1}}},
                "challenges": {
                    "Slayer": {"Task": {"Monsters": ["dragons[+]"]}},
                },
            }
        )
        assert find_reference_case_mismatches(info) == frozenset()


#: Confirmed against upstream's own `worker.js` (see the module docstring)
#: to be real export typos, not chunksim porting gaps - pinned rather than
#: fixed. A name coming *off* this set means upstream corrected it; delete
#: that entry rather than leaving it stale. A name appearing that isn't
#: here is a new, uninvestigated case and must be confirmed against
#: upstream's own source the same way before being added.
_KNOWN_REFERENCE_CASE_MISMATCHES: frozenset[ReferenceCaseMismatch] = frozenset(
    {
        (
            "Diary",
            "~|Combat Achievements#Elite|~ Reflecting on This Encounter",
            "Tasks->Slayer",
            "Slay a ~|basilisk knight|~",
        ),
        (
            "Diary",
            "~|Combat Achievements#Medium|~ A Frozen Foe from the Past",
            "Tasks->Slayer",
            "Slay a ~|skeletal wyvern|~",
        ),
        ("Nonskill", "Their bane awaits.", "Monsters", "Shellbane Gryphon"),
        (
            "Diary",
            "~|Combat Achievements#Easy|~ Dry Cleaning",
            "Monsters",
            "Shellbane Gryphon",
        ),
        (
            "Diary",
            "~|Combat Achievements#Easy|~ Shellbane Adept",
            "Monsters",
            "Shellbane Gryphon",
        ),
        (
            "Diary",
            "~|Combat Achievements#Medium|~ Shellbane Veteran",
            "Monsters",
            "Shellbane Gryphon",
        ),
        (
            "Diary",
            "~|Combat Achievements#Medium|~ Shellbane Speedrunner",
            "Monsters",
            "Shellbane Gryphon",
        ),
        (
            "Diary",
            "~|Combat Achievements#Medium|~ Perfect Shellbane",
            "Monsters",
            "Shellbane Gryphon",
        ),
        (
            "Diary",
            "~|Combat Achievements#Hard|~ Featherweight Fighter",
            "Monsters",
            "Shellbane Gryphon",
        ),
        (
            "Diary",
            "~|Combat Achievements#Hard|~ Shellbane Survivor",
            "Monsters",
            "Shellbane Gryphon",
        ),
        ("Hunter", "Barehanded catch a ~|moonlight moth|~", "NPCs", "Moonlight Moth"),
    }
)


@pytest.mark.real_export
def test_no_undocumented_reference_case_mismatch(real_export: ChunkInfo) -> None:
    found = find_reference_case_mismatches(real_export)

    added = found - _KNOWN_REFERENCE_CASE_MISMATCHES
    assert not added, (
        f"{len(added)} newly-found reference case mismatch(es): {added} - confirm each is a real "
        "export typo (not a chunksim bug) against upstream's own worker.js before adding it to "
        "_KNOWN_REFERENCE_CASE_MISMATCHES"
    )

    fixed = _KNOWN_REFERENCE_CASE_MISMATCHES - found
    assert not fixed, (
        f"{len(fixed)} known mismatch(es) no longer found: {fixed} - upstream corrected the typo, "
        "remove the entry from _KNOWN_REFERENCE_CASE_MISMATCHES rather than leaving it stale"
    )
