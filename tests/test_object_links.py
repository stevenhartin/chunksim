"""`derive/object_links.py`'s own `object_link_candidates`, against a small
hand-built `ChunkInfo`, plus a real-export check that the registered Bounty
Hunter portal entry fires the way its own comment in `object_links.py`
claims - in both directions, without a full chunkman rerun.

**Why hand-built tests monkeypatch `KNOWN_OBJECT_LINKS` rather than testing
against the real registry directly**: same reasoning as
`test_quest_jumps.py`'s own - the mechanism is what's interesting to pin
here, not the one registered entry, which the real-export test below covers
on its own.
"""

from __future__ import annotations

import pytest

from chunksim.derive import object_links
from chunksim.derive.graph import chunk_node
from chunksim.derive.neighbours import eligible_neighbours
from chunksim.derive.object_links import ObjectLink, object_link_candidates
from chunksim.derive.pipeline import MapState, derive
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.model.experience import MAX_SKILL_LEVEL
from chunksim.model.rules import default_rules

#: Duplicated rather than shared - `tests/` is not a package, so a test file
#: cannot import from another (`test_quest_jumps.py`, `test_quest_step_cycles.py`
#: carry their own copies for the same reason).
_ALL_SKILLS: tuple[str, ...] = (
    "Attack", "Strength", "Defence", "Ranged", "Prayer", "Magic", "Runecraft",
    "Construction", "Hitpoints", "Agility", "Herblore", "Thieving", "Crafting",
    "Fletching", "Slayer", "Hunter", "Mining", "Smithing", "Fishing", "Cooking",
    "Firemaking", "Woodcutting", "Farming",
)

#: See `test_quest_jumps.py`'s own copy for what these two flags mean and
#: why they stay off.
_RESTRICTION_FLAGS = frozenset({"F2P", "Skiller", "KeyItem Bosses"})


def _maxed_ceiling_state(chunk_info: ChunkInfo) -> MapState:
    """Every skill at 99, nothing completed, every ordinary rule flag on -
    see `test_quest_jumps.py`'s own copy of this fixture for the full
    rationale."""
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


class TestObjectLinkCandidates:
    _PORTAL = ObjectLink(object_name="Test portal")

    #: Three chunks carrying the same object - enough to confirm the
    #: mechanism doesn't stop after finding one other member.
    _CHUNK_INFO = ChunkInfo(
        {
            "sections": {"1": {"0": []}, "2": {"0": []}, "3": {"0": []}},
            "chunks": {
                "1": {"Object": {"Test portal": 1}},
                "2": {"Object": {"Test portal": 1}},
                "3": {"Object": {"Test portal": 1}},
            },
        }
    )

    def test_no_member_unlocked_offers_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(object_links, "KNOWN_OBJECT_LINKS", (self._PORTAL,))
        result = object_link_candidates(unlocked={}, chunk_info=self._CHUNK_INFO)
        assert result == {}

    def test_one_member_unlocked_offers_every_other_member(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(object_links, "KNOWN_OBJECT_LINKS", (self._PORTAL,))
        result = object_link_candidates(unlocked={"1": True}, chunk_info=self._CHUNK_INFO)
        assert set(result) == {"2", "3"}
        edge = result["2"]
        assert edge.source == chunk_node("2")
        assert edge.target == chunk_node("1")
        assert edge.ref == "object link: Test portal"

    def test_an_already_unlocked_member_is_not_re_offered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(object_links, "KNOWN_OBJECT_LINKS", (self._PORTAL,))
        result = object_link_candidates(
            unlocked={"1": True, "2": True}, chunk_info=self._CHUNK_INFO
        )
        assert set(result) == {"3"}

    def test_a_different_object_name_has_no_effect(self, monkeypatch: pytest.MonkeyPatch) -> None:
        other = ObjectLink(object_name="Some other object")
        monkeypatch.setattr(object_links, "KNOWN_OBJECT_LINKS", (other,))
        result = object_link_candidates(unlocked={"1": True}, chunk_info=self._CHUNK_INFO)
        assert result == {}

    def test_a_sectioned_placement_is_not_matched(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`_linked_chunks` only reads a chunk's *top-level* `Object` map -
        see the module docstring for why (no known entry needs the
        sectioned case, and adding it speculatively would need its own
        landing-section-forcing half, unlike every current entry)."""
        info = ChunkInfo(
            {
                "sections": {"1": {"0": []}, "4": {"1": []}},
                "chunks": {
                    "1": {"Object": {"Test portal": 1}},
                    "4": {"Sections": {"1": {"Object": {"Test portal": 1}}}},
                },
            }
        )
        monkeypatch.setattr(object_links, "KNOWN_OBJECT_LINKS", (self._PORTAL,))
        result = object_link_candidates(unlocked={"1": True}, chunk_info=info)
        assert result == {}


#: 12600's own ordinary grid-adjacent connections (`chunkinfo['sections']
#: ['12600'] == {'0': ['12344', '12599', '12601', '12856']}`) - excluded
#: alongside 12600 itself in the reverse-direction test below, or ordinary
#: connectivity would qualify 12600 the moment 13631 is unlocked (12600 is
#: a well-connected hub) and the test would pass for the wrong reason,
#: exactly the `_SHIPYARD_CLUSTER` lesson from `test_quest_jumps.py`.
_FEROX_ENCLAVE_CLUSTER = frozenset({"12600", "12344", "12599", "12601", "12856"})

#: 13631's own declared refs (`chunkinfo['sections']['13631'] ==
#: {'0': ['13375', '13630', '13632', '13887']}`) - the rest of Daimon's
#: Crater. Excluding only `13631` itself is not enough in the "every
#: rollable chunk unlocked" ceiling fixture: with the rest of the crater
#: left unlocked, ordinary connectivity already qualifies `13631` via
#: `13630`/`13632` before the object link ever gets a chance - confirmed by
#: hand (`via 13375`, not `via object link: ...`) before this was caught,
#: the same lesson `_SHIPYARD_CLUSTER` exists for.
_DAIMONS_CRATER_CLUSTER = frozenset({"13631", "13375", "13630", "13632", "13887"})


@pytest.mark.real_export
def test_bounty_hunter_portal_links_ferox_enclave_and_daimons_crater(
    real_export: ChunkInfo,
) -> None:
    """The registered entry, against the real export, in both directions -
    confirmed without a full chunkman rerun, per the user's own request:
    only 12600 and 13631 need checking, not the whole map."""
    state = _maxed_ceiling_state(real_export)

    # Forward: 12600 already unlocked (as it always is at chunkman-stuck -
    # East Ferox Enclave is ordinarily reachable), the whole Daimon's
    # Crater cluster excluded (see _DAIMONS_CRATER_CLUSTER's own comment)
    # so only the object link can qualify 13631.
    forward_chunk_ids = {
        chunk_id: True
        for chunk_id in real_export.sections
        if chunk_id not in _DAIMONS_CRATER_CLUSTER
    }
    forward = derive(state, forward_chunk_ids)
    forward_neighbours = {
        n.chunk_id: n for n in eligible_neighbours(state, forward_chunk_ids, forward)
    }
    assert "13631" in forward_neighbours
    assert forward_neighbours["13631"].via_ref == "object link: Bounty Hunter portal"

    # Reverse: 13631 unlocked, 12600 and its own ordinary neighbours
    # excluded - see _FEROX_ENCLAVE_CLUSTER's own comment.
    reverse_chunk_ids = {
        chunk_id: True
        for chunk_id in real_export.sections
        if chunk_id not in _FEROX_ENCLAVE_CLUSTER
    }
    reverse_chunk_ids["13631"] = True
    reverse = derive(state, reverse_chunk_ids)
    reverse_neighbours = {
        n.chunk_id: n for n in eligible_neighbours(state, reverse_chunk_ids, reverse)
    }
    assert "12600" in reverse_neighbours
    assert reverse_neighbours["12600"].via_ref == "object link: Bounty Hunter portal"
