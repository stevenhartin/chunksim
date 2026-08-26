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
    # Underground Pass's own completion, to Tyras Camp (chunk 8753) - the
    # entry point to the whole Elf-lands pocket (Lletya, Tyras Camp,
    # Iorwerth Camp, Arandar and more - Roving Elves, Mourning's End I/II
    # and Song of the Elves all run through it). Confirmed circular from
    # every direction: Roving Elves' own step 1 ("Talk to Islwyn and
    # Eluned") already requires `ElunedChunks[+]` (`codeItems.itemsPlus`
    # resolves to `['9009-1', '8753-1']`), so even the *first* quest in
    # this chain cannot start without the pocket already open - there is
    # no quest-internal step to trigger from. `~|Underground Pass|~
    # Complete the quest` is independently already valid at chunkman's own
    # stuck point (confirmed directly) and needs chunk `10291` (Ardougne
    # Castle, King Lathas) reachable - the real quest's own narrative
    # justification: Underground Pass is how a player first reaches past
    # West Ardougne toward the elf border, before Roving Elves exists as
    # an option at all.
    #
    # `anchor=("10291", "0")` is `10291`'s *only* declared section -
    # finding this needed a fix to `quest_jump_candidates` itself
    # (`reachable_sections` never records section "0" explicitly, the same
    # "free the moment its chunk is unlocked" convention every other
    # reader of it already follows - the anchor check now special-cases it
    # the same way rather than silently never matching a chunk with only
    # a "0" section).
    #
    # `target_chunk="8753"`, `landing_section="1"` (its own raw
    # `Sections` has no `"0"` at all - nothing opens for free on unlock,
    # unlike Pandemonium's `8234`) - confirmed to cascade the *entire*
    # rest of the pocket via ordinary rolling once opened, with no further
    # jump entries needed: `neighbour_pool` offers `9009` and `8752` the
    # moment `8753`/`1` is reachable (both grid-adjacent to `8753`, each
    # with a real `Connect` edge into it), and `9009` itself is `8753`'s
    # own declared neighbour into `9265` (Lletya) in turn.
    QuestJump(
        trigger_category="Quest",
        trigger_name="~|Underground Pass|~ Complete the quest",
        target_chunk="8753",
        landing_section="1",
        anchor=("10291", "0"),
    ),
    # Troll Romance, step 4 ("Wax your sled"), to the Trollweiss pocket - a
    # closed 3-chunk loop (11066 Mountain Slope South, 11067 Mountain Slope
    # North, 11068 Trollweiss Mountain) whose only edges, per the real
    # export's own `sections` grid, are to each other:
    # `sections['11066'] == {'0': ['11067']}`,
    # `sections['11067'] == {'0': ['11066', '11068-1']}`,
    # `sections['11068'] == {'1': ['11067'], 'W1': [...]}` (that `W1` leads
    # only into the separately-unexamined Ocean Chunk chain, not out of this
    # pocket). None of the three has any other reference anywhere in
    # chunkinfo['sections'] - confirmed by grep - so nothing outside this
    # loop can ever unlock any member of it, matching its "no qualifying
    # section connection yet" classification for all three in the real
    # chunkman-stuck state.
    #
    # The blocking step is step 5 ("Pick a Trollweiss flower",
    # `Chunks: ['11067', '11068-1']`) - circular, since both chunks are
    # inside the loop it needs open. Steps 1-4 carry no `Chunks` requirement
    # at all (NPCs/Items only) and are confirmed already valid at
    # chunkman's own stuck point; step 4 ("Wax your sled") is the step
    # immediately before the block, so this is acyclic the same way Dragon
    # Slayer I's step 6 is.
    #
    # `anchor=("11575", "1")` - Burthorpe, specifically the section where
    # `Dunstan` (step 3's own NPC, "Get Dunstan to make you a sled") stands
    # - models departing for the mountain from where the sled was made and
    # waxed; already independently reachable at chunkman's own stuck point.
    #
    # `target_chunk="11067"` (Mountain Slope North) rather than either
    # neighbour: it is the loop's hub - its own `sections` entry is the only
    # one of the three with edges to *both* others - so landing here lets
    # ordinary rolling reach the rest with no further jump entries.
    # `landing_section=None`: `11067` declares no explicit `Sections` map at
    # all (a bare-chunk entry), so section "0" is free the moment the chunk
    # itself is unlocked, the same convention as every other bare chunk.
    # Confirmed end to end via direct `derive()`/`eligible_neighbours()`
    # calls against the real chunkman-stuck state: with only this entry
    # added, `11067` appears as a candidate with
    # `via_ref == "quest jump: Troll Romance 4"`; unlocking it alone makes
    # both `11066` and `11068` appear as ordinary neighbours (via `11067`)
    # on the next call; unlocking all three together resolves
    # `reachable_sections["11068"] == {"1": True}` and every remaining
    # Troll Romance step, including `Complete the quest`.
    QuestJump(
        trigger_category="Quest",
        trigger_name="~|Troll Romance|~ 4",
        target_chunk="11067",
        landing_section=None,
        anchor=("11575", "1"),
    ),
    # The Curse of Arrav, step 7 ("Mine through the puzzles and reach the
    # end of the cave"), to Zemouregal's Fortress (chunk 11324). Step 6
    # ("Enter the cave on Trollweiss Mountain", `Chunks: ["11068-1"]`) and
    # step 7 itself (`Chunks: ["Zemouregal's Fortress#Basement"]`) both
    # resolve for free once the Trollweiss jump above fires - the export
    # carries a real `Nonskill` challenge keyed exactly
    # "Zemouregal's Fortress#Basement" with `UnlocksArea: true`, gated on
    # step 6, and `11068`'s own `Sections["1"]["Connect"]` names `11168`
    # (the area's underlying chunk, `Name: "Zemouregal's Fortress#Basement"`)
    # - so `unlockable_areas`' ordinary connectivity check grants the area
    # the moment `11068`/`1` is reachable, no jump code involved. Confirmed
    # directly: unlocking only `11066`/`11067`/`11068` (the Trollweiss trio)
    # already makes both step 6 and step 7 valid.
    #
    # What does *not* resolve for free is step 8 ("Talk to Arrav and obtain
    # the base plans and key", `Chunks: ["11324"]`) - 11324 is a genuine
    # walkable chunk (`chunkinfo['sections']['11324'] == {'0': ['???']}`),
    # not a named area, and its only declared section connection is the
    # unresolved placeholder - confirmed via `graph.py`'s own accounting
    # that every `"???"`-only section has no connection-based way in at
    # all. Grid-adjacency alone cannot save it either: `eligible_neighbours`
    # requires *both* grid-adjacency *and* a resolved own-section
    # connection, and 11324 is grid-adjacent to 11068 (delta 256) but still
    # fails the second half. So the chunk stays unreachable forever without
    # a jump, despite sitting one step past content the jump above already
    # opens.
    #
    # `anchor=("11068", "1")` - the same Trollweiss cave entrance the
    # Basement area itself connects from, and the real quest's own route
    # (cave -> basement -> fortress). `landing_section=None`: 11324's
    # `"0"` is its only declared section and is free the moment the chunk
    # is unlocked, same convention as every other bare chunk. Trigger is
    # step 7, not step 6 or step 8 - non-circular (step 7 depends only on
    # the Basement area, never on 11324) and the step immediately before
    # the block, matching the pattern established for Dragon Slayer I and
    # Troll Romance. Confirmed end to end: with this entry added, 11324
    # appears as a candidate (`via_ref == "quest jump: The Curse of Arrav
    # 7"`) once the Trollweiss trio is unlocked, and unlocking it resolves
    # every remaining Curse of Arrav step through `Complete the quest`.
    QuestJump(
        trigger_category="Quest",
        trigger_name="~|The Curse of Arrav|~ 7",
        target_chunk="11324",
        landing_section=None,
        anchor=("11068", "1"),
    ),
    # While Guthix Sleeps, step 20 ("Return to the castle, then swap places
    # with Surok"), to Lucien's camp (chunk 11579) - step 21's own
    # description is literally "Teleport to Lucien's camp", the clearest
    # narrative-transport case of any entry here. 11579 has no other path
    # in at all: grepped every `chunkinfo['sections']` entry for a "11579"
    # ref and found none, and its own entry is the unresolved-only
    # `{'0': ['???']}` - no `Connect` field either, so not even an area
    # grant is possible, unlike Zemouregal's Fortress#Basement above.
    #
    # Step 20 requires `Chunks: ["11828-1", "Black Knights' Catacombs"]` -
    # nothing to do with 11579, so non-circular - and is the step
    # immediately before the block. `anchor=("11828", "1")` (Falador West)
    # is exactly where step 20 itself leaves the player - "swap places with
    # Surok" happens at the castle, 11828-1, the same chunk-section step
    # 20's own requirement names - modelling "you are teleported from where
    # the swap happens". `landing_section=None`: 11579 declares no
    # `Sections` map, so its `"0"` is free on unlock like every other bare
    # chunk. Confirmed end to end: with this entry added, 11579 appears as
    # a candidate once step 20 is valid; unlocking it resolves step 21
    # ("Teleport to Lucien's camp") and step 22 ("Jump to the roof of the
    # church", needing `11835`, already independently reachable).
    QuestJump(
        trigger_category="Quest",
        trigger_name="~|While Guthix Sleeps|~ 20",
        target_chunk="11579",
        landing_section=None,
        anchor=("11828", "1"),
    ),
    # Cold War, step 2 ("Talk to Larry again at Rellekka Dock"), to the
    # South Iceberg (chunk 10558) - not one of the 8 clusters originally
    # scoped from the rejected-neighbour scan, discovered as a genuine
    # prerequisite while chasing Ghorrock/Making Friends with My Arm below:
    # that quest's own step 1 needs Cold War complete, and Cold War's own
    # step 3 ("Travel to the Iceberg... talk to Larry", `Chunks:
    # ["10558-1"]`) turns out to be exactly the same shape as every other
    # entry here.
    #
    # `10558`'s only paths in, grepped exhaustively across every
    # `chunkinfo['sections']` entry: its own section `1` pairs with
    # `10559-1` (a tight two-chunk loop, each declaring the other as its
    # *only* land-section requirement), and both chunks' remaining sections
    # (`W1`-`W6`) resolve only into the same disconnected ocean network
    # `runs/completion.py` already found permanently unreachable elsewhere
    # (10557, 10814, 10302, 10303, 10560, 10815 among them) - not a new
    # kind of gap, the same one, reached from a different quest.
    #
    # Step 2 ("Talk to Larry again at Rellekka Dock", `Chunks:
    # ["10810-1"]`) is non-circular and the step immediately before the
    # block; its own description already reads as a departure point.
    # `anchor=("10810", "1")` - Rellekka Dock, already independently
    # reachable - models Larry's boat trip to the iceberg. `10558` was
    # never independently rollable (chunk-level, `anchor` required, same
    # shape as Pandemonium/Lucien's camp above) and its land section is
    # non-`"0"`, so `landing_section="1"` is also required, same as Dragon
    # Slayer I - the first entry here needing both halves at once, and nothing
    # about the mechanism needed to change to support it: candidacy (this
    # entry's `anchor`) gets the chunk into `chunk_ids`, and
    # `quest_jump_sections` picks it up from there exactly like a
    # section-level entry would. Confirmed end to end: `10558` becomes a
    # candidate once step 2 is valid; unlocking it forces `10558-1`
    # reachable, which makes `10559` an *ordinary* neighbour (via its own
    # `10558-1` ref - no jump needed for it); unlocking both resolves every
    # remaining Cold War step through `Complete the quest`.
    QuestJump(
        trigger_category="Quest",
        trigger_name="~|Cold War|~ 2",
        target_chunk="10558",
        landing_section="1",
        anchor=("10810", "1"),
    ),
    # Making Friends with My Arm, step 3 ("Talk to Larry"), to Weiss (chunk
    # 11325) - step 4's own description is literally "Talk to Larry to get
    # taken to Weiss" (`Chunks: ["11325-1"]`), the same "get taken"
    # narrative-transport shape as Lucien's camp above. Depends on the Cold
    # War entry above (step 1's own `Tasks` gate needs Cold War complete) -
    # confirmed this quest line stays blocked until that one resolves
    # first, not a separate coincidence.
    #
    # `11325`'s only paths in: its own `Sections['1']` pairs with
    # `11326-1`/`11581-1`, both themselves inside the same closed
    # ice/ocean pocket (11326, 11581, 11582, 11837, 11838...) nothing here
    # can otherwise reach; its `W1`/`W2` resolve only into the same
    # disconnected ocean network as the Cold War entry's iceberg. Step 3
    # (`Chunks: ["10810-1"]`, Rellekka Dock) has nothing to do with Weiss,
    # so non-circular, and is the step immediately before the block.
    # `anchor=("10810", "1")` - the same Rellekka Dock departure point as
    # the Cold War entry, matching the real geography (Larry ships you
    # north from the same dock for both quests). `landing_section="1"` -
    # 11325 has no `"0"` and was never independently rollable, so both
    # halves are needed, same shape as Cold War's own entry.
    #
    # Confirmed to cascade the *entire* rest of this icy pocket via
    # ordinary rolling with no further jump entries: unlocking only 11325
    # makes `11581` (Ghorrock Fortress) an ordinary neighbour (via its own
    # `11325-1` ref), and unlocking both resolves every remaining step of
    # both Making Friends with My Arm *and* Secrets of the North (which
    # shares chunk `11581` and was blocked on the same pocket) through
    # their own `Complete the quest`.
    QuestJump(
        trigger_category="Quest",
        trigger_name="~|Making Friends with My Arm|~ 3",
        target_chunk="11325",
        landing_section="1",
        anchor=("10810", "1"),
    ),
    # Desert Treasure II - The Fallen Empire, step 5a3 ("Search the desk and
    # drink the potion"), to Stranglewood Temple (chunk 4661). This whole
    # branch was actually blocked twice over: step 1 itself needs Secrets
    # of the North complete, which the Making Friends with My Arm entry
    # above already resolves - confirmed this quest's steps 1-4 all become
    # valid once that jump is in place, with no further help needed to get
    # this far.
    #
    # `4661`'s only paths in, grepped exhaustively: its own section pairs
    # with `4405-1`/`4405-2`/`4660-1`/`4917-3`; `4660` needs `4404`,
    # `4659` or `4916-2`; `4659` needs `4660-2`/`4660-3`; `4916`'s
    # relevant section needs `4660-2`; `4917`'s relevant section (`3`)
    # needs `4661` or `4916-1` (itself needing `4917-3` back) - a closed
    # pocket (4403/4404/4405/4659/4660/4661, plus the blocked halves of
    # 4916/4917) with nothing outside it as an entry.
    #
    # Step 5a4's own description is "Board the rowboat, then talk to and
    # defend Kasonde" - both `4661` and the anchor chunk `4917` (Custodia
    # Mountains Lake) declare a `Rowboat` object, the real quest's own
    # crossing. Step 5a3 (`Chunks: ["6968-1"]`, already independently
    # reachable) is non-circular and the step immediately before. `anchor
    # =("4917", "1")` is `4917`'s own section carrying that `Rowboat`
    # object, already reachable once step 1's Secrets of the North gate
    # clears. `landing_section=None`: `4661` declares no `"0"` at all but
    # was never independently rollable either - the same
    # "anchor-only, section free once granted" shape as Zemouregal's
    # Fortress and Lucien's camp above, since its sole declared section is
    # the bare `"0"`.
    #
    # Confirmed to cascade the entire rest of the pocket via ordinary
    # rolling with no further jump entries: unlocking only `4661` makes
    # both `4660` and `4405` (Vardorvis' own arena) ordinary neighbours;
    # from there `4404`, then `4659`, then `4403` each become ordinary
    # neighbours in turn - and steps 5a4 through 5a5b (and the sibling
    # 5b/5c/5d branches for the other three Vardorvis-order paths) all
    # resolve once `4405`/`4661` are unlocked.
    QuestJump(
        trigger_category="Quest",
        trigger_name="~|Desert Treasure II - The Fallen Empire|~ 5a3",
        target_chunk="4661",
        landing_section=None,
        anchor=("4917", "1"),
    ),
    # Sins of the Father, step 9 ("Talk to Ivan or Veliaf on the dock"), to
    # the Icyene Graveyard (chunk 14641) - one entry resolves both of the
    # two remaining original clusters at once, because they turn out to be
    # the same circular pair: `chunkinfo['sections']['14641'] ==
    # {'0': ['14642-2']}` and `['14898'] == {'0': ['14642-2']}` (Ver
    # Sinhaza Shore, the other original cluster), while `14642`'s own
    # section `2` needs `14641` *or* `14898` back
    # (`sections['14642']['2'] == ['14641', '14898']`) - so neither side
    # can ever open the other, and nothing outside the pair references
    # either chunk (confirmed by exhaustive grep). `14641` is also the very
    # first chunk both this quest (step 10) and The Blood Moon Rises (step
    # 1, gated on this quest's completion) need, so both quest lines were
    # blocked on this one pair.
    #
    # Step 9 (`Chunks: ["14129"]`) is non-circular - 14129 (Burgh de Rott
    # Pier, already independently reachable) has nothing to do with the
    # graveyard - and is the step immediately before step 10's own first
    # reference to `14641`. `anchor=("14129", "0")` - 14129's own Nickname
    # ("...Pier") already reads as a departure point, and its own
    # `Sections` declares no explicit map (bare `"0"` only), the same
    # `anchor_section == "0"` case the Underground Pass entry established.
    # `landing_section=None`: `14641`'s only declared section is likewise
    # the bare `"0"`, free the moment the chunk is unlocked.
    #
    # Confirmed end to end: with only this entry added, `14641` becomes a
    # candidate once step 9 is valid; unlocking it makes `14642`'s section
    # `2` reachable via the export's own *unmodified* `connected_sections`
    # (a bare ref in a `sections` list means chunk-set membership, not a
    # specific section - see `graph.py`'s own note on bare refs - so
    # `14641` alone satisfies `14642-2`'s `['14641', '14898']`
    # requirement with no jump needed for the pair's other half); `14898`
    # then appears as an *ordinary* neighbour (via `14642-2`) with no
    # second jump entry; and unlocking both resolves every remaining step
    # of Sins of the Father and The Blood Moon Rises through their own
    # `Complete the quest`.
    QuestJump(
        trigger_category="Quest",
        trigger_name="~|Sins of the Father|~ 9",
        target_chunk="14641",
        landing_section=None,
        anchor=("14129", "0"),
    ),
    # Regicide, step 2 ("Climb down the Well of Voyage"), to North Isafdar
    # (chunk 9010) - a second, deeper layer behind the Elf-lands pocket the
    # Underground Pass entry above already opens. Once that entry lands,
    # a static full-connectivity expansion from `chunkman-stuck` reaches
    # 8753/Tyras Camp and its immediate neighbours, but a further 9-chunk
    # mesh (Iorwerth Camp, Ithell & Iorwerth, Amlodd & Hefin, North/South
    # Isafdar, Cadarn & Trahaearn, Crwys & Meilyr, Arandar, Arandar
    # Mountain) stays unreachable - invisible to the original 39-chunk scan
    # because the outer pocket was still closed when that scan ran.
    #
    # Step 2's own requirement is `Chunks: ["Underground Pass"]` - the
    # dungeon area, not a numbered chunk, granted by a real `UnlocksArea`
    # challenge keyed `"Underground Pass"` and gated on this same step 2
    # (`Tasks: {"~|Underground Pass|~ 2": "Quest"}`) - already valid at
    # chunkman's own stuck point. But that area grant does not itself open
    # `9010`: the "Well of Voyage" is the export's own real object,
    # confirmed present at chunk `9366` (`Connect` to `9010` among others),
    # but `9366` is a `Name`-only container never itself in
    # `chunkinfo['sections']` - the dungeon interior isn't modelled as
    # walkable chunks at all, so nothing here can ever project the area's
    # own connectivity onto a real chunk automatically.
    #
    # Step 3 (`Chunks: ["9010-1"]`) is the first real, numbered target -
    # non-circular (step 2 has nothing to do with it) and the step
    # immediately before. `anchor=("10291", "0")` - the same Ardougne
    # Castle departure point the Underground Pass entry above uses,
    # matching the same real narrative (Regicide is Underground Pass's own
    # direct sequel, opened by the same King Lathas questline).
    # `landing_section="1"`: `9010` declares only `"1"`/`"2"`, no `"0"`,
    # and was never independently rollable. Confirmed to cascade the
    # entire rest of the 9-chunk mesh via ordinary rolling with no further
    # jump entries: a full expansion from `chunkman-stuck` with only this
    # entry (plus the Underground Pass one) added reaches every one of the
    # nine.
    QuestJump(
        trigger_category="Quest",
        trigger_name="~|Regicide|~ 2",
        target_chunk="9010",
        landing_section="1",
        anchor=("10291", "0"),
    ),
    # Ghosts Ahoy, step 8 ("Talk to the Ghost captain"), to Dragontooth
    # Island (chunk 15159) - step 9's own requirement (`Chunks: ["15159"]`,
    # "Dig up the book of Haricanto") is otherwise unreachable: 15159's
    # only declared section is the unresolved `"???"` placeholder, the
    # same shape as Zemouregal's Fortress and Lucien's camp above. The
    # Ghost captain - the real quest's own boat crossing to the island -
    # is present at `14646-1` (Port Phasmatys, already independently
    # reachable), matching the export's own `NPC` data. Step 8 is
    # non-circular (nothing to do with 15159) and the step immediately
    # before. `landing_section=None`: `15159`'s sole section is the bare
    # `"0"`, free once granted. Confirmed end to end: `15159` becomes a
    # candidate once step 8 is valid; unlocking it resolves every
    # remaining Ghosts Ahoy step through `Complete the quest`.
    #
    # This and the Bone Voyage entry below were found chasing a *second*
    # layer behind the 8 originally-scoped clusters: both are prerequisite
    # quests Dragon Slayer II's own step 1 needs complete, and both had
    # the same "closed pocket" shape, discovered only once a static
    # full-connectivity expansion from `chunkman-stuck` was run after the
    # first 8 entries landed.
    QuestJump(
        trigger_category="Quest",
        trigger_name="~|Ghosts Ahoy|~ 8",
        target_chunk="15159",
        landing_section=None,
        anchor=("14646", "1"),
    ),
    # Bone Voyage, step 10 ("Return to the barge and give out the items"),
    # to Museum Camp (chunk 14907) - step 11's own description is literally
    # "Sail the boat to Fossil Island" (`Chunks: ["14907-1"]`), the same
    # "get taken somewhere" shape as Lucien's camp and Weiss above. `14907`
    # was never independently rollable: its own declared section refs
    # (`14651`, `14906-1`, `14908-1`/`14908-2`) are all themselves inside
    # the same closed Fossil Island pocket this quest exists to open, and
    # nothing outside it references `14907` at all.
    #
    # Step 10 (`Chunks: ["13365"]`, the Digsite, already independently
    # reachable) is non-circular and the step immediately before. `anchor
    # =("13365", "0")` - the Digsite declares no `Sections` map at all, so
    # its `"0"` is the bare-chunk-membership case. `landing_section="1"`:
    # `14907` has no `"0"` of its own and was never independently
    # rollable, so both halves are needed. Confirmed to cascade the entire
    # Fossil Island pocket (all of `14637`-`15407` above) via ordinary
    # rolling with no further jump entries once unlocked, and resolves
    # every remaining Bone Voyage step through `Complete the quest`.
    QuestJump(
        trigger_category="Quest",
        trigger_name="~|Bone Voyage|~ 10",
        target_chunk="14907",
        landing_section="1",
        anchor=("13365", "0"),
    ),
    # Cabin Fever, step 2 ("Talk to Bill Teach on his boat"), to Pirate Base
    # (chunk 14638) - step 3's own description is literally "Complete the
    # tasks on the boat and sail to Mos Le'Harmless" (`Chunks:
    # ["14638-1"]`). Mos Le'Harmless is a separate landmass from Fossil
    # Island (the Bone Voyage entry above only opens the latter), reached
    # by this different quest's own boat crossing. Step 2 (`Chunks:
    # ["14902"]`, the School Boat, already independently reachable) is
    # non-circular and the step immediately before. `anchor=("14902",
    # "0")` - the School Boat declares no `Sections` map, so its `"0"` is
    # the bare-chunk-membership case. `landing_section="1"`: `14638` has
    # no `"0"` of its own and was never independently rollable (its own
    # declared refs are all inside the same closed pocket).
    #
    # Confirmed to cascade nearly the entire remaining Mos Le'Harmless
    # pocket via ordinary rolling with no further jump entries (14639,
    # 14894, 14895, 15150, 15151, 15406, 15407 all follow) - only Harmony
    # Island (15148) stays out, needing its own entry (see below).
    QuestJump(
        trigger_category="Quest",
        trigger_name="~|Cabin Fever|~ 2",
        target_chunk="14638",
        landing_section="1",
        anchor=("14902", "0"),
    ),
    # Creature of Fenkenstrain completion, to Harmony Island (chunk 15148) -
    # The Great Brain Robbery's own step 1 needs *both* `14638-1` and
    # `15148` at once (`Chunks: ["14638-1", "15148"]`), so unlike every
    # other entry here it has no earlier same-quest step to trigger from at
    # all - the whole quest is circular against its own first chunk
    # requirement. The real, non-circular gate is the *other* half of step
    # 1's `Tasks`: `~|Creature of Fenkenstrain|~ Complete the quest`,
    # already valid at chunkman's own stuck point and unrelated to either
    # target chunk.
    #
    # `15148`'s only declared section is the unresolved `"???"` placeholder
    # (the same shape as Zemouregal's Fortress, Lucien's camp and
    # Dragontooth Island above) - no export data can ever open it
    # ordinarily. `anchor=("11057", "1")` - Brimhaven, already
    # independently reachable - matches the real quest's own diving
    # crossing from there (step 1's own `Items` name a `Fishbowl helmet`
    # and `Diving apparatus`). `landing_section=None`: `15148`'s sole
    # section is the bare `"0"`, free once granted. Confirmed end to end:
    # `15148` becomes a candidate once Creature of Fenkenstrain is
    # complete; unlocking it alongside `14638` (already open via the Cabin
    # Fever entry above) resolves every step of The Great Brain Robbery
    # through `Complete the quest`.
    QuestJump(
        trigger_category="Quest",
        trigger_name="~|Creature of Fenkenstrain|~ Complete the quest",
        target_chunk="15148",
        landing_section=None,
        anchor=("11057", "1"),
    ),
    # Dragon Slayer II, step 9 ("Build the rowboat"), to Lithkren (chunk
    # 14142) - step 10's own description is literally "Row to Lithkren"
    # (`Chunks: ["14142"]`). `14142` and its neighbour `14398` (East
    # Lithkren) are a tight, fully isolated circular pair
    # (`sections['14142'] == {'0': ['14398-1', '14398-2']}`,
    # `sections['14398'] == {'1': ['14142'], '2': ['14142']}`) with no
    # other reference anywhere in the export - confirmed by grep. This
    # entry only became solvable once the Bone Voyage entry above opened
    # Fossil Island: step 9 itself needs chunk `14652` (Mushroom Forest),
    # part of that same pocket.
    #
    # Step 9 (already valid once Fossil Island is open) is non-circular
    # and the step immediately before. `anchor=("14652", "0")` - Mushroom
    # Forest, where the rowboat is built, declares no `Sections` map, so
    # its `"0"` is the bare-chunk-membership case. `landing_section=None`:
    # `14142`'s sole section is the bare `"0"`, free once granted.
    # Confirmed to cascade `14398` via ordinary rolling with no further
    # jump entries, and resolves every remaining Dragon Slayer II step
    # through `Complete the quest`.
    QuestJump(
        trigger_category="Quest",
        trigger_name="~|Dragon Slayer II|~ 9",
        target_chunk="14142",
        landing_section=None,
        anchor=("14652", "0"),
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
        # Section "0" is never itself recorded in `reachable_sections` - it
        # is free the moment its chunk is unlocked, the same convention
        # `sections.unlocked_sections` and every other reader of
        # `reachable_sections` already follows (see e.g.
        # `sections._section_is_reachable`'s own `section_id == "0"` check).
        # An anchor naming it needs the same exception, or a perfectly
        # ordinary anchor chunk with no other sections declared - like
        # Ardougne Castle, `10291` - could never satisfy this at all.
        anchor_open = (
            anchor_chunk in unlocked
            if anchor_section == "0"
            else bool(reachable_sections.get(anchor_chunk, {}).get(anchor_section))
        )
        if not anchor_open:
            continue
        candidates[jump.target_chunk] = Edge(
            source=Node(jump.target_chunk, jump.landing_section or "0"),
            target=Node(anchor_chunk, anchor_section),
            ref=f"quest jump: {strip_task_markup(jump.trigger_name)}",
            limit_key="",
            limit=None,
        )
    return candidates
