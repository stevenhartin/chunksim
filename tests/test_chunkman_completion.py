"""Whether a maxed account, playing the real random-roll mechanism from a
real starting chunk and auto-completing everything achievable along the
way, ever gets stuck before the whole export - every chunk, every quest,
every diary, every combat achievement, every boss - is done.

**Why this is a different check from `test_quest_step_cycles.py`'s.** That
scanner asks a synthetic, per-quest question: "assume every *other* quest
is already done - does *this* quest's own step chain still get stuck?" It
is blind to a failure shape that only shows up when the *order* chunks
unlock in matters - a stall caused by which chunk the random walk happened
to reach first, not by any single quest's own gates. `run_chunkman`
(`runs/completion.py`) walks the real `neighbours.py` eligibility mechanism
end to end, so it can see that shape where the scanner structurally cannot.

**The starting section is seeded, not derived - and this was found the hard
way.** The first version of this test's own discovery run got stuck on step
0, immediately after unlocking chunk `12850` (Lumbridge) alone: none of its
own sections are reachable from nothing, and none of its neighbours'
declared connections target section `0` (the one every unlocked chunk gets
for free) either. Confirmed by tracing `neighbours._qualifying_edge`
directly - not a chunksim defect, but a real property of the `Connect`
graph, which only ever describes walking between already-reachable places
and has no vocabulary for "the game teleports you into a specific section."
`run_chunkman`'s `start_section` parameter (default `"1"`, matching where a
fresh account is actually placed) exists precisely for this - see its own
docstring for the confirmed pool this produces: `{12594, 12849, 12851,
13106}`, the four grid neighbours of `12850`, each via a declared
connection into `12850-1`.

**Discovery-then-pin, same as `test_quest_step_cycles.py`.** Implemented,
verified against a 25-step smoke run (no errors, steady task growth, no
stall), then run once for real. **The real run genuinely got stuck** -
298 of 1,172 chunks, after 317s. Every auto-completed category reached
`gap 0` (everything valid got completed) except `Hunter` (`gap -11`, worth
its own look - completed *exceeding* valid should not be possible if
`valid` only ever grows monotonically within a run) and `Sailing` (`0/0` -
not one of the export's 243 Sailing challenges was ever valid across the
whole run, which lines up with the rejected-neighbour cluster below sitting
almost entirely in the `7985`-`15158` id range this project's own water
pocket investigation already named). This is the actual finding the user
asked this tool to surface, not a bug in the tool - see `_KNOWN_*` below for
exactly what was pinned and `cache/reports/chunkman/latest.json` /
`chunksim show --map chunkman-stuck` for the full detail behind it.
Investigating *why* is real follow-up work, not part of pinning the current
state.
"""

from __future__ import annotations

import pytest

from chunksim.derive.pipeline import MapState
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.runs.completion import AUTO_COMPLETE_CATEGORIES, run_chunkman


class TestChunkmanLoop:
    """`run_chunkman` against small, hand-built graphs - the real export's
    own outcome is covered by the pinned regression test below.

    **Numeric chunk ids throughout - explicitly not letters.**
    `challenges.contains_sections`/`_chunk_reachable` parse a chunk-section
    reference as `NUM-SECTION`; a letter id like `"A-1"` never matches that
    pattern and silently falls into the bare-literal-membership branch
    instead, so a fixture using letters can pass or fail for reasons that
    have nothing to do with what it claims to test. This exact mistake was
    made and fixed earlier in `test_quest_step_cycles.py` - worth repeating
    the guardrail here rather than relearning it.
    """

    def test_auto_complete_marks_a_valid_task_done_and_it_stays_done(self) -> None:
        """The step this file exists to defend: completing isn't a no-op,
        and a completed task is never re-completed or un-done on a later
        step. Two chunks, both reachable, so the run also ends `COMPLETE`
        rather than `STUCK` - the simplest possible non-stuck shape."""
        info = ChunkInfo(
            {
                "sections": {"1": {"1": []}, "2": {"1": ["1-1"]}},
                "chunks": {"1": {"Sections": {"1": {}}}, "2": {"Sections": {"1": {}}}},
                "challenges": {"Crafting": {"Make a thing": {}}},
            }
        )
        outcome = run_chunkman(info, {}, start_chunk_id="1", start_section="1", seed=1)

        assert outcome.stuck is False
        assert outcome.every_chunk_unlocked is True
        assert outcome.steps[0].newly_completed == {"Crafting": ["Make a thing"]}
        assert outcome.final_state.completed_challenges["Crafting"] == {"Make a thing": True}
        # Never re-completed on a later step, once it's already done.
        assert all("Make a thing" not in step.newly_completed.get("Crafting", []) for step in outcome.steps[1:])

    def test_a_pool_that_empties_ends_the_run_stuck(self) -> None:
        """A third, unreachable "island" chunk keeps the run from ever
        completing - the pool empties once `1` and `2` are both unlocked,
        and the run stops there rather than looping forever."""
        info = ChunkInfo(
            {
                "sections": {"1": {"1": []}, "2": {"1": ["1-1"]}, "99": {"1": []}},
                "chunks": {
                    "1": {"Sections": {"1": {}}},
                    "2": {"Sections": {"1": {}}},
                    "99": {"Sections": {"1": {}}},
                },
                "challenges": {},
            }
        )
        outcome = run_chunkman(info, {}, start_chunk_id="1", start_section="1", seed=1)

        assert outcome.stuck is True
        assert outcome.every_chunk_unlocked is False
        assert outcome.steps[-1].chunk_id is None
        assert outcome.steps[-1].pool_size_before_roll == 0
        assert set(outcome.final_unlocked) == {"1", "2"}
        assert any(step.chunk_id == "2" for step in outcome.steps)

    def test_a_pool_that_exhausts_every_section_ends_the_run_complete(self) -> None:
        """The success shape: every `chunk_info.sections` entry unlocked,
        `stuck` false."""
        info = ChunkInfo(
            {
                "sections": {"1": {"1": []}, "2": {"1": ["1-1"]}, "3": {"1": ["2-1"]}},
                "chunks": {
                    "1": {"Sections": {"1": {}}},
                    "2": {"Sections": {"1": {}}},
                    "3": {"Sections": {"1": {}}},
                },
                "challenges": {},
            }
        )
        outcome = run_chunkman(info, {}, start_chunk_id="1", start_section="1", seed=1)

        assert outcome.stuck is False
        assert outcome.every_chunk_unlocked is True
        assert set(outcome.final_unlocked) == {"1", "2", "3"}

    def test_a_boss_never_placed_in_any_unlocked_chunk_is_reported_missing(self) -> None:
        info = ChunkInfo(
            {
                "sections": {"1": {"1": []}, "2": {"1": ["1-1"]}},
                "chunks": {"1": {"Sections": {"1": {}}}, "2": {"Sections": {"1": {}}}},
                "challenges": {},
                "codeItems": {"bossMonsters": {"Some Boss": True}},
            }
        )
        outcome = run_chunkman(info, {}, start_chunk_id="1", start_section="1", seed=1)

        assert outcome.bosses_missing == ("Some Boss",)

    def test_auto_complete_categories_include_sailing_and_combat_not_nonskill(self) -> None:
        """The two scope decisions actually discussed with the user, not
        assumed - see the module docstring on `AUTO_COMPLETE_CATEGORIES`
        for why Nonskill is excluded and Sailing/Combat are not."""
        assert "Sailing" in AUTO_COMPLETE_CATEGORIES
        assert "Combat" in AUTO_COMPLETE_CATEGORIES
        assert "Nonskill" not in AUTO_COMPLETE_CATEGORIES


#: The 2026-08-25 export's own answer - see the module docstring's
#: "discovery-then-pin" paragraph. **The chunk count and the rejected-
#: neighbour set are pinned exactly** - both are small and are the concrete,
#: actionable diagnostic data an investigation actually works from. The four
#: headline-criteria lists are pinned as **counts only**: `combat_achievements_
#: incomplete` alone is 652 names, and enumerating all four by hand here would
#: make this file worse at its job, not better - the full names live in
#: `cache/reports/chunkman/latest.json` (rewritten every run) and the
#: persisted `chunkman-stuck` cached map, not duplicated into source.
#: A count shrinking is progress; the chunk count reaching 1,172 with
#: `stuck=False` is the day this whole pinned block should be deleted.
_KNOWN_UNLOCKED_COUNT = 298

#: `{rejected chunk id: why}` - every chunk grid-adjacent to the stuck run's
#: unlocked set that still didn't qualify. Fixing the root cause should
#: shrink or empty this set; a name added here is worth investigating before
#: assuming it is more of the same.
_KNOWN_REJECTED_NEIGHBOURS: frozenset[str] = frozenset(
    {
        "8758", "8759", "8760", "9007", "9008", "9012", "9013", "9017", "9262",
        "9265", "9267", "9274", "9516", "9517", "9518", "9522", "9523", "9529",
        "9771", "9784", "10027", "10041", "10283", "10295", "10298", "10540",
        "10541", "10555", "10797", "10799", "10800", "10812", "11052", "11059",
        "11066", "11067", "11308", "11315", "11324", "11564", "11579", "11580",
        "11581", "11820", "11838", "12075", "12077", "12094", "12331", "12333",
        "12336", "12350", "12586", "12606", "12842", "12862", "13097", "13118",
        "13353", "13374", "13610", "13624", "13625", "13626", "13627", "13628",
        "13629", "13867", "13868", "13880", "14125", "14126", "14127", "14128",
        "14136", "14384", "14392", "14641", "14648", "14898", "14903", "15155",
        "15156", "15157", "15158",
    }
)

#: Every boss `code_items['bossMonsters']` names that the stuck run never
#: reached. Small enough to pin exactly, unlike the quest/diary/CA lists.
_KNOWN_BOSSES_MISSING: tuple[str, ...] = (
    "Alchemical Hydra", "Amoxliatl", "Dagannoth Prime", "Dagannoth Rex",
    "Dagannoth Supreme", "Demonic Brutus", "Deranged archaeologist",
    "Doom of Mokhaiotl", "Duke Sucellus", "Hespori", "Mad Angel",
    "Maggot King", "Phantom Muspah", "Sarachnis", "Shellbane gryphon",
    "Skotizo", "Tekton", "The Hueycoatl", "The Leviathan", "The Mimic",
    "The Whisperer", "Vardorvis", "Vorkath", "Yama", "Zalcano", "Zulrah",
)

_KNOWN_QUESTS_INCOMPLETE_COUNT = 66
_KNOWN_DIARIES_INCOMPLETE_COUNT = 110
_KNOWN_COMBAT_ACHIEVEMENTS_INCOMPLETE_COUNT = 652


@pytest.mark.real_export
@pytest.mark.real_cache
@pytest.mark.slow
def test_chunkman_reaches_a_documented_state(
    real_export: ChunkInfo, real_state: tuple[MapState, dict[str, bool]]
) -> None:
    """The regression guard: see the module docstring for what this run
    found and why each piece is pinned the way it is. ~5 minutes on the
    2026-08-25 export - far faster than the hours a naive per-step cost
    estimate suggested, since most of a chunkman run's steps happen while
    only a small fraction of the export is unlocked and `derive()` has far
    less to evaluate; `test_quest_step_cycles.py`'s own scan runs every
    iteration against the *full* uber-map chunk set, which is the more
    expensive shape.
    """
    fray_state, _ = real_state
    outcome = run_chunkman(real_export, fray_state.rules)

    assert outcome.stuck is True, (
        "the pinned run got stuck; a completed run needs this whole test "
        "rewritten, not just its constants - see the module docstring"
    )
    assert len(outcome.final_unlocked) == _KNOWN_UNLOCKED_COUNT
    assert set(outcome.rejected_neighbours) == _KNOWN_REJECTED_NEIGHBOURS
    assert outcome.bosses_missing == _KNOWN_BOSSES_MISSING
    assert len(outcome.quests_incomplete) == _KNOWN_QUESTS_INCOMPLETE_COUNT
    assert len(outcome.diaries_incomplete) == _KNOWN_DIARIES_INCOMPLETE_COUNT
    assert (
        len(outcome.combat_achievements_incomplete)
        == _KNOWN_COMBAT_ACHIEVEMENTS_INCOMPLETE_COUNT
    )
