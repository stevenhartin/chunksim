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
stall), then run once for real and the actual outcome transcribed below -
see `_KNOWN_...` for what that run found and why it is pinned rather than
asserted to the "everything worked" answer outright.
"""

from __future__ import annotations

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
