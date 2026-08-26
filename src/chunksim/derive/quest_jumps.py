"""The one place this project departs from "port only": a small,
hand-authored registry of quest-narrative shortcuts upstream's own
connectivity data cannot express, and the two functions that fold each
entry into the ordinary derivation.

**Why this exists at all.** Building `runs/completion.py` (an end-to-end
simulation of a maxed account playing the real random chunk-roll mechanism
from a fixed start) found that the export is genuinely, permanently
uncompletable without it - not a bug in this project's port, confirmed by
reading upstream's own real source directly. `neighbours.py`'s
`eligible_neighbours` is a faithful port of `selectAllNeighborsCanvas`
(index.js:3035-3084), which does exactly three things per candidate:
grid-adjacency to something unlocked, F2P walkability, and a declared
`Connect` reference satisfying `sectionsLimits` - no reference to quest or
challenge state anywhere. `sections.connected_sections` is an equally
faithful port of the `ConnectsSections` handling inside `calcChallenges`
(worker.js:2112-2121), which requires *every* chunk named in a crossing to
already be a member of the unlocked set before it does anything at all - it
can open a section of a chunk you already have, never discover a brand-new
one. Neither mechanism, upstream or ported, has any way to say "a quest
step transports you somewhere the ordinary map graph cannot reach" - and
for two real quests, that is exactly what happens.

**Both entries below were verified against a real cached export via direct
`derive()` calls, not assumed** - see each entry's own comment for the
measurement behind it. Adding a third entry should meet the same bar:
confirm the target has no other path in (grep every `chunkinfo['sections']`
entry for a reference to it), confirm the trigger is non-circular (does the
quest step chosen as the trigger, or anything the target's own reachability
would need to prove, depend on the target already being reachable?), and
write down what was checked - a bare entry with no justification is exactly
the "guessed rather than measured" shape CLAUDE.md warns against elsewhere
in this project.

**The two shapes an entry can take**, and why both are needed:

- A **section-level jump** (`anchor=None`): the target chunk is already
  ordinarily, independently unlocked - there is nothing to roll, only a
  section of it that no `Connect`/`ConnectsSections` data ever opens.
  `quest_jump_sections` forces it reachable once the trigger is valid,
  folding into `pipeline.derive`'s existing `connected` accumulator exactly
  alongside `connected_sections`' own contribution.
- A **chunk-level jump** (`anchor` set): the target chunk has never been
  independently rollable at all. `quest_jump_candidates` offers it as a
  roll candidate once the trigger is valid *and* the anchor - the
  chunk-section you must already be standing in for the game to "teleport"
  you - is reachable, folding into `neighbours.eligible_neighbours`'s own
  candidate set as a fallback, tried only when ordinary connectivity does
  not already qualify the chunk.

See CLAUDE.md's "Quest jumps" section for the project-level statement of
why this is here and the discipline expected of any addition.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from chunksim.derive.graph import Edge, Node
from chunksim.derive.task_names import strip_task_markup


@dataclass(frozen=True)
class QuestJump:
    """A quest-narrative shortcut this project models directly, because
    upstream's own connectivity data cannot express it - see this module's
    own docstring and CLAUDE.md's "Quest jumps" section for why this exists
    and why it is a deliberate, documented departure from "port only".
    """

    #: The challenge category the trigger is judged under - "Quest" for
    #: both current entries, but not hardcoded narrower than that.
    trigger_category: str
    #: The trigger's raw, markup-bearing name, exactly as it appears as a
    #: key of `challenges.valid[trigger_category]` once valid.
    trigger_name: str
    #: The chunk this jump lands on.
    target_chunk: str
    #: Forced reachable once `target_chunk` is a `chunk_ids` member and the
    #: trigger is valid. `None` when the export's own `ConnectsSections`
    #: data already opens the landing section for free once the chunk is
    #: unlocked (confirmed per-entry below, not assumed).
    landing_section: str | None
    #: The `(chunk, section)` you must already be standing in for
    #: `target_chunk` to become a roll candidate. `None` when `target_chunk`
    #: is already independently unlockable - nothing to roll, only a
    #: section to open.
    anchor: tuple[str, str] | None


KNOWN_QUEST_JUMPS: tuple[QuestJump, ...] = (
    # Dragon Slayer I, step 6 ("Talk to Ned in Draynor Village"), to
    # Crandor. Chunk 11314 is already an ordinary, independently-unlocked
    # chunk - its own chunkinfo['sections']['11314']['1'] connects to
    # 11313-1, an ordinary nearby land chunk with nothing to do with the
    # quest - so this entry needs no candidacy half (anchor=None). What it
    # lacks is a path into section 3 (Crandor): chunkinfo['sections']
    # ['11314'] declares no connection into '3' from anywhere, confirmed
    # directly against the real export - reachable_sections['11314'] never
    # contains '3' even with every chunk unlocked, every skill 99 and step
    # 6 already valid.
    #
    # Landing on step 6 rather than step 7 is load-bearing, not a style
    # choice: step 7 ("Sail to Crandor") still carries the export's own
    # unedited `Chunks: ['11314-2']`, so it can never become valid on its
    # own to serve as a trigger (circular - 11314-2 needs this jump's
    # target reachable, which needs step 7 valid, which needs 11314-2).
    # Step 6 is the step immediately before it ("arranging passage"), so
    # this is acyclic: forcing 11314/3 open once step 6 is valid lets the
    # already-ported "11314-3 to 11314-2" Agility-shortcut ConnectsSections
    # challenge fire, which opens 11314-2, which lets step 7's own
    # original, unedited Chunks gate resolve completely naturally.
    # Confirmed end to end via a direct derive() call with
    # manual_sections={"11314": {"3": True}}: reachable_sections['11314']
    # gains '2', and both step 7 and step 9 (previously stuck on the same
    # chain, see the now-empty tests/test_quest_step_cycles.py pin) become
    # valid.
    QuestJump(
        trigger_category="Quest",
        trigger_name="~|Dragon Slayer I|~ 6",
        target_chunk="11314",
        landing_section="3",
        anchor=None,
    ),
    # Pandemonium, step 4 ("wash ashore, then talk to Steve and Ribs"), to
    # the Shipyard (chunk 8234). 8234 has never been independently
    # rollable: grepped exhaustively across every chunkinfo['sections']
    # entry in the real export for any reference to 8234 by any section,
    # and the only hits are its own four grid-adjacent ocean-cluster
    # neighbours (7978/8233/8235/8490), which are themselves part of the
    # same disconnected ocean region - reachable only by already owning a
    # boat, which requires completing this very quest. A genuine circular
    # dependency, confirmed via `runs/completion.py`'s own end-to-end
    # simulation getting permanently stuck on it, not a porting gap.
    #
    # `landing_section` is deliberately `None` here, unlike Dragon Slayer
    # I - confirmed empirically, not assumed: the export carries a real
    # `ConnectsSections` entry, "12078-1 to 8234-1", gated on
    # `Tasks: {"~|Pandemonium|~ 4": "Quest"}` and NPC Junior Jim (present
    # at the already-reachable 12078-1) - real evidence of the quest's own
    # intended design. Once 8234 is a `chunk_ids` member at all, that
    # entry validates for real and the already-ported `connected_sections`
    # opens 8234-1 with no help from this module - confirmed directly by
    # adding "8234" to `chunk_ids` and reading back
    # `reachable_sections["8234"] == {"1": True, "W1": True}` using
    # unmodified code. So this entry only needs to solve the one thing
    # that is actually broken: getting 8234 into the unlocked set in the
    # first place. `anchor=("12078", "1")` - "The Pandemonium", the
    # quest's own ship, an ordinary, already-independently-reachable
    # chunk section - models "you must already be standing at the
    # departure point" before the crossing is offered as a roll.
    QuestJump(
        trigger_category="Quest",
        trigger_name="~|Pandemonium|~ 4",
        target_chunk="8234",
        landing_section=None,
        anchor=("12078", "1"),
    ),
)


def quest_jump_sections(
    valid: Mapping[str, Mapping[str, Any]],
    chunk_ids: Mapping[str, bool],
    reachable: Mapping[str, Mapping[str, bool]],
) -> dict[str, dict[str, bool]]:
    """Landing-section overrides for jumps whose trigger is valid this pass
    and whose target is already a `chunk_ids` member.

    Same "not already reachable" shape `connected_sections`' own return
    carries, and for the same reason: `pipeline.derive`'s exit test is
    `not new_connected`, so an entry that kept reporting itself every pass
    regardless of `reachable` would never let the loop converge.

    **The `chunk_ids`-membership check matters even though no entry needs
    it today**: skipping it would make a chunk-level jump (target not yet
    unlocked) report a "new" entry every pass forever while its trigger
    stays valid but the chunk stays un-rolled - a `ConvergenceError`
    waiting for the day a second chunk-level entry needs a landing section
    of its own, not a risk today only because Pandemonium's own entry
    carries `landing_section=None`.
    """
    result: dict[str, dict[str, bool]] = {}
    for jump in KNOWN_QUEST_JUMPS:
        if jump.landing_section is None:
            continue
        if jump.trigger_name not in valid.get(jump.trigger_category, {}):
            continue
        if jump.target_chunk not in chunk_ids:
            continue
        if reachable.get(jump.target_chunk, {}).get(jump.landing_section):
            continue
        result.setdefault(jump.target_chunk, {})[jump.landing_section] = True
    return result


def quest_jump_candidates(
    unlocked: Mapping[str, bool],
    reachable_sections: Mapping[str, Mapping[str, bool]],
    valid: Mapping[str, Mapping[str, Any]],
) -> dict[str, Edge]:
    """Not-yet-unlocked chunk-level jump targets that currently qualify as
    roll candidates, shaped as `Edge`s so they drop into
    `eligible_neighbours`'s own `qualifying` dict unchanged - no new
    `Neighbour` field, no second code path in the final construction.

    `source` is the target's own landing node (what `via_section` shows -
    which section of the candidate this jump lands you in); `target` is the
    anchor (what makes it reachable). `limit_key`/`limit` are inert
    placeholders: this `Edge` never flows through `_qualifying_edge`'s own
    `sectionsLimits` gate, since the trigger/anchor check here already is
    that gate.
    """
    candidates: dict[str, Edge] = {}
    for jump in KNOWN_QUEST_JUMPS:
        if jump.anchor is None or jump.target_chunk in unlocked:
            continue
        if jump.trigger_name not in valid.get(jump.trigger_category, {}):
            continue
        anchor_chunk, anchor_section = jump.anchor
        if not reachable_sections.get(anchor_chunk, {}).get(anchor_section):
            continue
        candidates[jump.target_chunk] = Edge(
            source=Node(jump.target_chunk, jump.landing_section or "0"),
            target=Node(anchor_chunk, anchor_section),
            ref=f"quest jump: {strip_task_markup(jump.trigger_name)}",
            limit_key="",
            limit=None,
        )
    return candidates
