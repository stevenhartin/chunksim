"""`derive/quest_jumps.py`'s own two functions, against small hand-built
registries, plus a real-export check that both registered entries actually
fire the way their own comments in `quest_jumps.py` claim.

**Why hand-built tests monkeypatch `KNOWN_QUEST_JUMPS` rather than testing
against the real registry directly**: `quest_jump_sections`/
`quest_jump_candidates` are pure functions of whatever `KNOWN_QUEST_JUMPS`
holds - the interesting behaviour to pin here is the *mechanism* (does a
trigger/anchor/membership check work correctly in isolation), not the two
specific entries, which the real-export integration tests below cover
separately and are the ones that would actually notice a real regression in
either registered jump.

**Numeric chunk ids throughout - explicitly not letters.**
`challenges.contains_sections`/`_chunk_reachable` parse a chunk-section
reference as `NUM-SECTION`; a letter id silently falls into the
bare-literal-membership branch instead and can pass or fail for reasons
that have nothing to do with what a fixture claims to test - this exact
mistake was made and fixed twice already this session
(`test_quest_step_cycles.py`, `test_chunkman_completion.py`); worth
repeating the guardrail here too.
"""

from __future__ import annotations

import pytest

from chunksim.derive import quest_jumps
from chunksim.derive.graph import Node
from chunksim.derive.pipeline import MapState, derive
from chunksim.derive.neighbours import eligible_neighbours
from chunksim.derive.quest_jumps import (
    QuestJump,
    quest_jump_candidates,
    quest_jump_sections,
)
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.model.experience import MAX_SKILL_LEVEL
from chunksim.model.rules import default_rules


class TestQuestJumpSections:
    """The section-level half - `quest_jump_sections`."""

    _SECTION_JUMP = QuestJump(
        trigger_category="Quest",
        trigger_name="~|Q|~ trigger",
        target_chunk="1",
        landing_section="3",
        anchor=None,
    )

    def test_trigger_not_valid_has_no_effect(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(quest_jumps, "KNOWN_QUEST_JUMPS", (self._SECTION_JUMP,))
        result = quest_jump_sections(
            valid={"Quest": {}}, chunk_ids={"1": True}, reachable={}
        )
        assert result == {}

    def test_target_not_yet_unlocked_has_no_effect(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The convergence-correctness case: a chunk-level jump's target
        must never contribute here before it is a `chunk_ids` member, or
        `pipeline.derive`'s `not new_connected` exit test would never see
        a quiet pass - see `quest_jump_sections`'s own docstring."""
        monkeypatch.setattr(quest_jumps, "KNOWN_QUEST_JUMPS", (self._SECTION_JUMP,))
        result = quest_jump_sections(
            valid={"Quest": {"~|Q|~ trigger": True}}, chunk_ids={}, reachable={}
        )
        assert result == {}

    def test_trigger_valid_and_target_unlocked_forces_the_section_open(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(quest_jumps, "KNOWN_QUEST_JUMPS", (self._SECTION_JUMP,))
        result = quest_jump_sections(
            valid={"Quest": {"~|Q|~ trigger": True}}, chunk_ids={"1": True}, reachable={}
        )
        assert result == {"1": {"3": True}}

    def test_an_already_reachable_section_is_not_re_reported(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(quest_jumps, "KNOWN_QUEST_JUMPS", (self._SECTION_JUMP,))
        result = quest_jump_sections(
            valid={"Quest": {"~|Q|~ trigger": True}},
            chunk_ids={"1": True},
            reachable={"1": {"3": True}},
        )
        assert result == {}

    def test_a_chunk_level_jump_with_no_landing_section_never_contributes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Matches the real Pandemonium entry's own shape - a jump whose
        `landing_section` is `None` relies entirely on the export's own
        `ConnectsSections` data once its target is unlocked."""
        jump = QuestJump(
            trigger_category="Quest", trigger_name="~|Q|~ trigger",
            target_chunk="9", landing_section=None, anchor=("1", "1"),
        )
        monkeypatch.setattr(quest_jumps, "KNOWN_QUEST_JUMPS", (jump,))
        result = quest_jump_sections(
            valid={"Quest": {"~|Q|~ trigger": True}}, chunk_ids={"9": True}, reachable={}
        )
        assert result == {}


class TestQuestJumpCandidates:
    """The chunk-level half - `quest_jump_candidates`."""

    _CHUNK_JUMP = QuestJump(
        trigger_category="Quest",
        trigger_name="~|Q|~ trigger",
        target_chunk="9",
        landing_section="1",
        anchor=("1", "1"),
    )

    def test_trigger_not_valid_is_not_a_candidate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(quest_jumps, "KNOWN_QUEST_JUMPS", (self._CHUNK_JUMP,))
        result = quest_jump_candidates(
            unlocked={"1": True}, reachable_sections={"1": {"1": True}}, valid={"Quest": {}}
        )
        assert result == {}

    def test_anchor_not_reachable_is_not_a_candidate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(quest_jumps, "KNOWN_QUEST_JUMPS", (self._CHUNK_JUMP,))
        result = quest_jump_candidates(
            unlocked={"1": True},
            reachable_sections={},
            valid={"Quest": {"~|Q|~ trigger": True}},
        )
        assert result == {}

    def test_an_already_unlocked_target_is_not_offered_again(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(quest_jumps, "KNOWN_QUEST_JUMPS", (self._CHUNK_JUMP,))
        result = quest_jump_candidates(
            unlocked={"1": True, "9": True},
            reachable_sections={"1": {"1": True}},
            valid={"Quest": {"~|Q|~ trigger": True}},
        )
        assert result == {}

    def test_a_section_level_jump_is_never_a_candidate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`anchor=None` means "nothing to roll" - matches the real Dragon
        Slayer I entry's own shape (target already ordinarily unlocked)."""
        jump = QuestJump(
            trigger_category="Quest", trigger_name="~|Q|~ trigger",
            target_chunk="1", landing_section="3", anchor=None,
        )
        monkeypatch.setattr(quest_jumps, "KNOWN_QUEST_JUMPS", (jump,))
        result = quest_jump_candidates(
            unlocked={}, reachable_sections={}, valid={"Quest": {"~|Q|~ trigger": True}}
        )
        assert result == {}

    def test_the_happy_path_offers_the_target_as_a_candidate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(quest_jumps, "KNOWN_QUEST_JUMPS", (self._CHUNK_JUMP,))
        result = quest_jump_candidates(
            unlocked={"1": True},
            reachable_sections={"1": {"1": True}},
            valid={"Quest": {"~|Q|~ trigger": True}},
        )
        assert set(result) == {"9"}
        edge = result["9"]
        assert edge.source == Node("9", "1")
        assert edge.target == Node("1", "1")
        assert "quest jump" in edge.ref


#: The 23 real skills - see `test_quest_step_cycles.py`'s own `_ALL_SKILLS`
#: for why this is duplicated rather than shared (small, stable, and a test
#: file cannot import from another test file - `tests/` is not a package).
_ALL_SKILLS: tuple[str, ...] = (
    "Attack", "Strength", "Defence", "Ranged", "Prayer", "Magic", "Runecraft",
    "Construction", "Hitpoints", "Agility", "Herblore", "Thieving", "Crafting",
    "Fletching", "Slayer", "Hunter", "Mining", "Smithing", "Fishing", "Cooking",
    "Firemaking", "Woodcutting", "Farming",
)


#: `F2P`/`Skiller` are *restriction* switches (`True` means "reject"), the
#: opposite of every ordinary rule flag - flipping them to `True` for
#: permissiveness would reject real content instead of admitting it.
#: `KeyItem Bosses` gates an unported mechanic (`sources.gather_chunks_info`
#: raises `NotImplementedError` if it is on). Matches
#: `test_quest_step_cycles.py`'s own `_RESTRICTION_FLAGS`.
_RESTRICTION_FLAGS = frozenset({"F2P", "Skiller", "KeyItem Bosses"})


def _maxed_ceiling_state(chunk_info: ChunkInfo) -> MapState:
    """Every skill at 99, nothing completed, every ordinary rule flag on -
    see `_RESTRICTION_FLAGS` for the two left off. Permissive rules matter
    here specifically: Dragon Slayer I's own step chain runs through a
    Crafting recipe gated by the `Multi Step Processing` rule, which
    `default_rules()`'s all-`False` seed would block long before step 6 is
    ever reached - confirmed directly, `default_rules()` alone fails this
    test."""
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


@pytest.mark.real_export
def test_dragon_slayer_one_jump_opens_crandor(real_export: ChunkInfo) -> None:
    """The registered entry, against the real export: once Dragon Slayer I
    step 6 is valid, chunk 11314's section 3 opens - and, via the
    already-ported "11314-3 to 11314-2" Agility-shortcut `ConnectsSections`
    challenge, so does section 2, which is what actually resolves the
    quest's own step 7 (see `quest_jumps.py`'s own comment for the full
    chain). Every rollable chunk unlocked, so this is purely testing the
    jump's section-forcing half, not chunk-level candidacy."""
    chunk_ids = {chunk_id: True for chunk_id in real_export.sections}
    state = _maxed_ceiling_state(real_export)
    derived = derive(state, chunk_ids)

    assert "~|Dragon Slayer I|~ 6" in derived.challenges.valid.get("Quest", {})
    assert derived.reachable_sections.get("11314", {}).get("3") is True
    assert derived.reachable_sections.get("11314", {}).get("2") is True
    assert "~|Dragon Slayer I|~ 7" in derived.challenges.valid.get("Quest", {})


#: 8234 (the Shipyard) plus its four direct grid-neighbours - the *only*
#: chunks `_qualifying_edge` would ever check to qualify 8234 via ordinary
#: connectivity (its own `chunkinfo['sections']['8234']['W1']` names
#: exactly these four, bare refs). Excluding just 8234 itself is not
#: enough to isolate the jump: with the rest of this cluster left
#: unlocked, `7978` (etc.) already qualifies 8234 the ordinary way, and an
#: earlier version of this test passed for that wrong reason - confirmed
#: by hand (`via 7978`, not `via quest jump: ...`) before this was caught.
_SHIPYARD_CLUSTER = frozenset({"8234", "7978", "8233", "8235", "8490"})


@pytest.mark.real_export
def test_pandemonium_jump_offers_the_shipyard_as_a_candidate(real_export: ChunkInfo) -> None:
    """The registered entry, against the real export: once Pandemonium
    step 4 is valid and chunk 12078's section 1 is reachable, chunk 8234
    (the Shipyard) - otherwise permanently unrollable, see
    `quest_jumps.py`'s own comment - appears as an eligible roll candidate,
    specifically *via the jump* rather than via any ordinary connectivity
    that happens to also be available (see `_SHIPYARD_CLUSTER`'s own
    comment for why the whole cluster, not just 8234, must be excluded).
    """
    chunk_ids = {
        chunk_id: True for chunk_id in real_export.sections if chunk_id not in _SHIPYARD_CLUSTER
    }
    state = _maxed_ceiling_state(real_export)
    derived = derive(state, chunk_ids)

    assert "~|Pandemonium|~ 4" in derived.challenges.valid.get("Quest", {})
    assert derived.reachable_sections.get("12078", {}).get("1") is True
    neighbours = {n.chunk_id: n for n in eligible_neighbours(state, chunk_ids, derived)}
    assert "8234" in neighbours
    assert "quest jump" in neighbours["8234"].via_ref
