"""Every quest whose own step chain can never finish, however permissive the
account behind it - a genuine "chicken and egg" in the export's `Quest`
data, not a defect here.

**The shape this hunts, precisely**: Dragon Slayer I step 7 ("Sail to
Crandor") carried `Chunks: ['11314-2']`, but `11314-2` was only ever made
reachable by unlocking `Crandor and Karamja Dungeon#North` - a `Nonskill`
`UnlocksArea` challenge whose own `Tasks` field named step 7. Step 7 needed
`11314-2`; `11314-2` needed North; North needed step 7. No account, however
progressed, could ever complete it - this was pinned in
`tests/test_section_connectivity.py`'s `_KNOWN_ORPHANED_SECTIONS` before
being understood, then root-caused and fixed (`Crandor and Karamja
Dungeon#North`'s `Tasks` retargeted from step 7 to step 6 - see that
module's own history). `quest_chunk_cycle_targets`, below, is the general
form of the check that found it: run *every* quest through the same
question, not just the one a user happened to notice by hand.

**The question, per quest**: with every rollable chunk unlocked, every
skill at 99, and every *other* quest's own steps assumed already
completed - does this quest's own step chain still get stuck on a `Chunks`
requirement it can never satisfy?

**Why "assume every other quest done", not a blank or a maxed-but-real
account**: a step failing because *Land of the Goblins* hasn't been done
yet is not this quest's own problem, and a whole-export scan needs to
isolate one quest's own chain from the prerequisite web around it, or
every quest late in that web reports every quest before it as "stuck" -
noise, not signal. The scan this file pins was rewritten twice over this
exact question during development; see "Why not a static graph" and
"Why not a `calc_challenges` monkeypatch" below for the two approaches
that looked right and were not.

**Why not a static graph.** A pure `Tasks`+`Chunks` dependency graph, built
by hand from the export and cycle-detected with Tarjan's algorithm, was
tried first. It is fast (no `derive()` calls) but wrong in a way that is
hard to see from the graph alone: a `Chunks` reference can be satisfied by
*any one* of several routes (a `[+]` item/chunk family, a `ConnectsSections`
challenge with more than one already-open sibling, the raw per-chunk
`Connect` fallback into a named area `sections.unlocked_sections` itself
does not see) - real OR-of-AND satisfiability, not a plain reachability
question a cycle-in-a-directed-graph check can decide correctly without
re-deriving the very fixed point `pipeline.derive` already computes
correctly. Reimplementing that resolution by hand chased one bug into the
next (missing the raw-`Connect`-into-a-named-area edge, then miscounting
`ConnectsSections`' "one sibling already open" condition) with no end in
sight - the real fixed point was always going to be more trustworthy than
a second implementation of it.

**Why not a `calc_challenges` monkeypatch.** The next attempt patched
`chunksim.derive.pipeline.calc_challenges` to run the real function and then
widen its *returned* `valid` dict, so every quest but the one under test
would read as already complete. This looked right and was not:
`calc_challenges` takes no "already-valid" seed at all - every call
recomputes `Tasks`/`Chunks`/`Skills`/the five aggregate gates from the raw
export and `chunk_ids`/`reachable_sections` alone, so patching what a
*previous* call returned never reaches the *next* call's own internal
resolution of some other quest's real (and, before the fix, genuinely
broken) chain. It produced 129 of 209 quests "stuck" - almost all of them
an artifact of this, not a real second bug, the worst of it two flags this
project already has hardcoded, inverted semantics for
(`_level_gates_met`'s `Not F2P`/`Not Skiller`: `rules['F2P'] = True` means
*restrict to F2P*, not *allow it*, so blindly flipping every rule flag to
`True` for "maximum permissiveness" rejected `Not F2P` content instead of
admitting it).

**What actually works: edit the data, not the result.** `_stripped_chunk_info`
builds a real `ChunkInfo` where every `Quest`/`Diary`/`Extra` challenge
that is neither one of `base_quest`'s own steps nor a structural connector
(`UnlocksArea`/`ConnectsSections`) is replaced with a bare stub carrying
only what the aggregate/seeding machinery reads across *every* challenge
regardless of category - `Output`, `Output Object`, `QuestPoints`,
`CombatPoints`, `Kudos`, `Reward` - stripped of every gate. The *real*,
unmodified `calc_challenges` then computes "assume everything else is
already done" correctly, because it is no longer being asked to recompute
some other quest's genuinely-broken chain at all: that chain's own gates
are gone from the data it reads. Two narrower mistakes on the way to this:
stripping `Skill`-category challenges too (breaks `_skills_requirement_met`'s
own "is this skill trainable at all" check, which needs at least one real
valid entry per skill - Legends' Quest step 2's `Skills: {Crafting: 50}`
failed *only* because every Crafting challenge had been stripped away, not
for any reachability reason), and stripping `Reward` off the stub (Dragon
Slayer II step 12 needs `Catspeak amulet(e)`, a reward-only item from an
unrelated quest, seeded by `_dynamic_gates_met`'s own `Reward` scan - see
`challenges.py`'s per-valid-challenge reward loop - which a stub missing
`Reward` can never produce).

**Cost, and why `slow`**: `derive()` over the ~2,700-challenge export costs
seconds even with a quest's worth of gates stripped out, and this runs it
once per quest - roughly 12s x 209 quests, ~40 minutes, measured on the
2026-08-25 export. `@pytest.mark.slow`, gated the same way every other
minutes-scale oracle in this suite is.

**Pinned rather than asserted empty**, for the same reason
`test_section_connectivity.py`'s own pinned sets are: upstream is live, and
an exact-empty assertion would fail the moment new content shipped with a
temporary gap of its own, burying the one finding worth seeing (a name
*added*) under noise the module never claimed to explain. A name coming
*off* the pinned set means a fix landed - update `_KNOWN_QUEST_CHUNK_CYCLES`
rather than leaving a stale entry.
"""

from __future__ import annotations

import pytest

from chunksim.derive.challenges import chunks_requirement_met
from chunksim.derive.pipeline import MapState, derive
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.model.experience import MAX_SKILL_LEVEL
from chunksim.model.rules import default_rules

#: The 23 real skills - `max_skill`/`passive_skill` are read by name
#: (`_skills_requirement_met`, `sections._skills_needed_met`), not
#: enumerated from the export, so a "every skill known" account has to
#: name them itself. Small and stable enough to duplicate rather than
#: share with `test_section_connectivity.py`'s own copy - see
#: `conftest.py`'s own rule about what earns a shared fixture.
_ALL_SKILLS: tuple[str, ...] = (
    "Attack", "Strength", "Defence", "Ranged", "Prayer", "Magic", "Runecraft",
    "Construction", "Hitpoints", "Agility", "Herblore", "Thieving", "Crafting",
    "Fletching", "Slayer", "Hunter", "Mining", "Smithing", "Fishing", "Cooking",
    "Firemaking", "Woodcutting", "Farming",
)

#: `_level_gates_met`'s two hardcoded flags are *restriction* switches
#: (`rules['F2P'] = True` means "reject `Not F2P` content", the opposite of
#: every ordinary `_category_gate_met` flag's "`True` means admit it") -
#: flipping them to `True` for permissiveness rejects real content instead
#: of admitting it. `KeyItem Bosses` gates an unported mechanic
#: (`sources.gather_chunks_info` raises `NotImplementedError` if it is on).
#: Every other boolean rule is an ordinary opt-in switch and is safe to
#: flip to `True`.
_RESTRICTION_FLAGS = frozenset({"F2P", "Skiller", "KeyItem Bosses"})

#: Categories that participate in the "assume every other quest already
#: completed" ablation. `Skill` categories and non-connector `Nonskill`
#: challenges stay fully real - see the module docstring's "why not a
#: static graph"/skills-stripping mistake for why touching those breaks
#: unrelated machinery this check has no business touching.
_STRIPPABLE_CATEGORIES = frozenset({"Quest", "Diary", "Extra"})


def _maxed_ceiling_state(chunk_info: ChunkInfo) -> MapState:
    """Every skill at 99, nothing completed, every ordinary rule flag on -
    see the module docstring for the two flags this deliberately leaves
    off and why."""
    maxed = {skill: MAX_SKILL_LEVEL for skill in _ALL_SKILLS}
    permissive_rules = {
        key: (True if isinstance(value, bool) and key not in _RESTRICTION_FLAGS else value)
        for key, value in default_rules().items()
    }
    return MapState(
        chunk_info=chunk_info,
        rules=permissive_rules,
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


def _stripped_chunk_info(chunk_info: ChunkInfo, base_quest: str) -> ChunkInfo:
    """`chunk_info` with every `Quest`/`Diary`/`Extra` challenge that is
    neither one of `base_quest`'s own steps nor a structural connector
    reduced to a gate-free stub. See the module docstring's "what actually
    works" section for why this, and not a result patch, makes the real
    `calc_challenges` compute "assume everything else is done" correctly.
    """
    new_challenges: dict[str, object] = {}
    for category, names in chunk_info.challenges.items():
        if not isinstance(names, dict) or category not in _STRIPPABLE_CATEGORIES:
            new_challenges[category] = names
            continue
        new_bucket: dict[str, object] = {}
        for name, challenge in names.items():
            if not isinstance(challenge, dict):
                new_bucket[name] = challenge
                continue
            is_target_step = category == "Quest" and challenge.get("BaseQuest") == base_quest
            is_connector = challenge.get("UnlocksArea") is True or challenge.get("ConnectsSections") is True
            if is_target_step or is_connector:
                new_bucket[name] = challenge
                continue
            stub: dict[str, object] = {}
            for field in ("Output", "Output Object"):
                if isinstance(challenge.get(field), str):
                    stub[field] = challenge[field]
            for field in ("QuestPoints", "CombatPoints", "Kudos"):
                value = challenge.get(field)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    stub[field] = value
            if isinstance(challenge.get("Reward"), list):
                stub["Reward"] = challenge["Reward"]
            new_bucket[name] = stub
        new_challenges[category] = new_bucket
    return ChunkInfo({**chunk_info.data, "challenges": new_challenges})


def quest_chunk_cycle_targets(chunk_info: ChunkInfo, base_quest: str) -> dict[str, list[str]]:
    """`{step_name: Chunks}` for every one of `base_quest`'s own steps whose
    `Chunks` requirement never becomes reachable under
    `_stripped_chunk_info`'s ablation - see the module docstring for
    exactly what that assumes. Empty means the quest can complete given
    every other quest already done; a non-empty result is a genuine
    same-quest (or connector-mediated) chicken-and-egg.
    """
    quest_challenges = chunk_info.challenges.get("Quest") or {}
    quest_step_names = {
        name for name, challenge in quest_challenges.items()
        if isinstance(challenge, dict) and challenge.get("BaseQuest") == base_quest
    }
    stripped = _stripped_chunk_info(chunk_info, base_quest)
    chunk_ids = {chunk_id: True for chunk_id in stripped.sections}

    derived = derive(_maxed_ceiling_state(stripped), chunk_ids)

    valid_quest = derived.challenges.valid.get("Quest", {})
    reachable = derived.reachable_sections
    expanded = derived.expanded_chunks

    result: dict[str, list[str]] = {}
    for step in quest_step_names:
        if step in valid_quest:
            continue
        challenge = quest_challenges.get(step)
        if not isinstance(challenge, dict):
            continue
        if chunks_requirement_met(challenge, expanded, reachable, chunk_info):
            continue
        chunks = challenge.get("Chunks")
        if isinstance(chunks, list):
            result[step] = chunks
    return result


class TestQuestChunkCycleTargets:
    """`quest_chunk_cycle_targets` against small, hand-built graphs - the
    real export's own single finding (Dragon Slayer I) is covered by the
    pinned regression test below."""

    #: Numeric ids throughout, matching `challenges.contains_sections`'s own
    #: `NUM-SECTION` pattern - a letter id like `"A-1"` is never parsed as a
    #: chunk-section reference at all (it falls into the *bare*-ref branch
    #: of `_chunk_reachable`, checking literal membership of the string
    #: `"A-1"` in `chunk_ids`, which is never true), so an early version of
    #: this fixture using letters passed and failed for the wrong reasons
    #: entirely - a lesson worth a comment here so it isn't relearned.
    #:
    #: `"3"` is unsectioned (no `Sections` field), so `_area_is_connected`
    #: takes its early-return-True branch the moment `"3"` itself is
    #: unlocked (it always is - a bare, always-free rollable chunk) -
    #: exactly the shape `Crandor and Karamja Dungeon#South` was for the
    #: real bug. `"1-1"`'s own raw `Connect` (`_any_static_connect_open`'s
    #: own mechanism) names `"2"`, whose `Name` is `"Area"` - so `1-1`
    #: becomes reachable exactly when `Area` is unlocked, matching how the
    #: real `11314-3` became reachable once `Crandor ... North` was.
    _CONNECTOR_CHUNKS = {
        "sections": {"1": {"1": []}, "3": {"0": []}},
        "chunks": {
            "1": {"Sections": {"1": {"Connect": {"2": True}}}},
            "3": {"Connect": {"2": True}},
            "2": {"Name": "Area"},
        },
    }

    def test_a_two_step_cycle_is_reported(self) -> None:
        """The Dragon Slayer I shape, minimised: step 2 needs a chunk only
        a connector opens, and that connector needs step 2."""
        info = ChunkInfo(
            {
                **self._CONNECTOR_CHUNKS,
                "challenges": {
                    "Quest": {
                        "~|Q|~ 1": {"BaseQuest": "Q"},
                        "~|Q|~ 2": {"BaseQuest": "Q", "Chunks": ["1-1"], "Tasks": {"~|Q|~ 1": "Quest"}},
                    },
                    "Nonskill": {
                        "Area": {
                            "UnlocksArea": True,
                            "Tasks": {"~|Q|~ 2": "Quest"},
                        }
                    },
                },
            }
        )
        assert quest_chunk_cycle_targets(info, "Q") == {"~|Q|~ 2": ["1-1"]}

    def test_an_acyclic_chain_is_clean(self) -> None:
        """The same shape with the connector's `Tasks` pointing at an
        *earlier* step - no cycle, and the quest completes."""
        info = ChunkInfo(
            {
                **self._CONNECTOR_CHUNKS,
                "challenges": {
                    "Quest": {
                        "~|Q|~ 1": {"BaseQuest": "Q"},
                        "~|Q|~ 2": {"BaseQuest": "Q", "Chunks": ["1-1"], "Tasks": {"~|Q|~ 1": "Quest"}},
                    },
                    "Nonskill": {
                        "Area": {
                            "UnlocksArea": True,
                            "Tasks": {"~|Q|~ 1": "Quest"},
                        }
                    },
                },
            }
        )
        assert quest_chunk_cycle_targets(info, "Q") == {}

    def test_a_prerequisite_quest_left_undone_is_not_this_quests_problem(self) -> None:
        """The ablation this test exists to defend: step 1 needing another
        quest's completion is not a cycle in *this* quest, and the pinned
        list should never grow because of one."""
        info = ChunkInfo(
            {
                "sections": {},
                "chunks": {},
                "challenges": {
                    "Quest": {
                        "~|Other|~ Complete the quest": {"BaseQuest": "Other", "Chunks": ["Nowhere"]},
                        "~|Q|~ 1": {
                            "BaseQuest": "Q",
                            "Tasks": {"~|Other|~ Complete the quest": "Quest"},
                        },
                    },
                },
            }
        )
        assert quest_chunk_cycle_targets(info, "Q") == {}

    def test_a_reward_only_item_from_another_quest_is_still_available(self) -> None:
        """The `Reward` regression this test exists to defend - see the
        module docstring's Dragon Slayer II/`Catspeak amulet(e)` mistake."""
        info = ChunkInfo(
            {
                "sections": {},
                "chunks": {},
                "challenges": {
                    "Quest": {
                        "~|Other|~ Complete the quest": {"BaseQuest": "Other", "Reward": ["Rare item"]},
                        "~|Q|~ 1": {"BaseQuest": "Q", "Items": ["Rare item"]},
                    },
                },
            }
        )
        assert quest_chunk_cycle_targets(info, "Q") == {}


#: The single finding on the 2026-08-25 export - see the module docstring
#: for the full Dragon Slayer I story and the recommended fix
#: (`Crandor and Karamja Dungeon#North`'s `Tasks` retargeted from step 7 to
#: step 6). This local cache fixture still carries the *unfixed* data, so
#: this is pinned non-empty; once a re-fetch picks up the fix, this should
#: come back empty and `_KNOWN_QUEST_CHUNK_CYCLES` should shrink to match.
_KNOWN_QUEST_CHUNK_CYCLES: dict[str, frozenset[str]] = {
    "Dragon Slayer I": frozenset({"~|Dragon Slayer I|~ 7", "~|Dragon Slayer I|~ 9"}),
}


@pytest.mark.real_export
@pytest.mark.slow
def test_no_undocumented_quest_chunk_cycle(real_export: ChunkInfo) -> None:
    """The regression guard: every quest in the export, checked for a
    same-quest (or connector-mediated) chicken-and-egg. See the module
    docstring for the cost (~40 minutes) and why it is gated `slow`.
    """
    quest_challenges = real_export.challenges.get("Quest") or {}
    base_quest_names: set[str] = set()
    for challenge in quest_challenges.values():
        if isinstance(challenge, dict):
            base_quest = challenge.get("BaseQuest")
            if isinstance(base_quest, str):
                base_quest_names.add(base_quest)
    base_quests = sorted(base_quest_names)

    found: dict[str, frozenset[str]] = {}
    for base_quest in base_quests:
        stuck = quest_chunk_cycle_targets(real_export, base_quest)
        if stuck:
            found[base_quest] = frozenset(stuck)

    added = {quest: steps for quest, steps in found.items() if quest not in _KNOWN_QUEST_CHUNK_CYCLES}
    assert not added, (
        f"{len(added)} newly-cyclic quest(s) - a step needs a chunk only "
        f"reachable via a chain that needs that same step (or a later one) "
        f"first: {added} - confirm the cycle by hand before adding it to "
        "_KNOWN_QUEST_CHUNK_CYCLES"
    )

    fixed = {
        quest: steps for quest, steps in _KNOWN_QUEST_CHUNK_CYCLES.items()
        if quest not in found or found[quest] != steps
    }
    assert not fixed, (
        f"{len(fixed)} known cycle(s) changed or resolved: {fixed} - update "
        "_KNOWN_QUEST_CHUNK_CYCLES in this file (remove a quest entirely "
        "once its fix has been re-fetched)"
    )
