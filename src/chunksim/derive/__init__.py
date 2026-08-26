"""The pure layer: what the unlocked chunks mean.

The derivation chain `sections -> sources -> challenges -> bis ->
active_tasks/other_tasks`, wired by `pipeline.derive`, plus everything that
walks or diffs the result: `boosts`, `graph`, `neighbours`, `unlock`, `delta`,
`search`.

**The rule this directory carries, once, for all sixteen modules: no
module-level mutable state.** No `lru_cache`, no memo dicts, no globals. Not
tidiness - `chunksim simulate --jobs N` and `batch.price_steps` run this code in
worker processes, and a cache in a "pure" module breaks that silently, in the
form of runs that disagree. `MapState` and `Derived` are frozen for the same
reason. `_UNARMED_SOURCES` and `_UNIVERSAL_PRIMARY` are read-only constants and
are the only module-level data here.

Nothing in here reads the network or the disk. Where a result is expensive
enough to be worth storing, the storing happens in `store/derived_cache.py` and
this layer stays unaware of it - which is what keeps the opt-in oracles an
honest signal.

The modules, and what each owns:

- `sections.py` - which sections of the unlocked chunks are reachable, plus
  named-area unlocking and the one place this project overrules the export.
  `connected_sections` is the ordinary `Connect` graph's second door: a
  valid `ConnectsSections` challenge (an Agility shortcut, a minigame
  crossing) opens sections nothing in `chunkinfo['sections']` itself
  connects - entirely unported until this was found stranding real
  content (`11317-2`, confirmed against the `verf` oracle).
- `sources.py` - what the unlocked chunks make available (`SourceIndex`),
  including `taskUnlocks` over items *and* entities, and `isSlayerValid` over
  a slayer monster's `skillItems.Slayer` table.
- `task_names.py` - `strip_task_markup`, the one place the raw task-name markup
  is undone. **Display-only**, and over challenge and task names alone. Split
  out of `challenges.py` so its thirteen callers need not import a convergence
  loop to print a word.
- `challenges.py` - which challenges are valid, as a two-phase fixed point.
  **`BiS` is never evaluated here.** Also **where every derivation command
  spends its time**: read the static/dynamic gate split before touching the
  loop. The five aggregate level gates (`QuestPointsNeeded`, kudos, …) are
  real now, not a raise - see `_aggregate_gates_met`.
- `bis.py` - best-in-slot per (combat style, slot). Inherently
  **non-monotonic**: recomputed fresh per state, never accumulated.
- `active_tasks.py` - per-skill active/obsolete/completed classification. A
  *display* winner only; it never changes `ChallengeResult.valid`.
- `other_tasks.py` - the three non-skill categories, `Diary`/`Quest`/`Extra`.
  No single winner.
- `injected.py` - the challenges upstream **builds at runtime** rather than
  reading from the export. The export is not the whole challenge list, and a
  name that is only ever constructed is invisible to every other module.
  Definitions are overlaid via `ChunkInfo.with_challenges`, never forced valid -
  the ordinary gates still judge them.
- `boosts.py` - temporary skill boosts. With `rules['Boosting']` on, this is a
  **dependency** of `challenges` and `bis` rather than a feature.
- `pipeline.py` - `MapState` and `derive`. Owns the **loop** where upstream's
  area-unlock circularity lives, and the `slayerLocked` fold. Raises
  `ConvergenceError` rather than returning a truncated derivation. Also folds
  `quest_jumps.quest_jump_sections` into the same accumulator as
  `connected_sections`, once per pass.
- `unlock.py` - what one candidate unlock adds, by diffing two `derive` calls.
  **Owns the project's attribution rule.** Additions-only. Records *eligibility*
  and the two boost clamps as well as validity - a diff of `valid` alone cannot
  see a skill becoming trainable, and ranks on the wrong number when a boost
  applies.
- `delta.py` - the **symmetric** comparison of two derived states. `unlock.py`
  projects its primitives down to a one-directional view, and the two must
  agree.
- `neighbours.py` - which chunks are eligible to roll next, upstream's canvas
  numbering, and the `sectionsLimits` gate. Also offers `quest_jumps`'s and
  `object_links`' chunk-level candidates as fallbacks, tried only where
  ordinary connectivity does not already qualify a chunk.
- `graph.py` - the export's `sections` branch as a **directed** graph: the
  shared substrate `sections.py`, `neighbours.py` and `runs/simulate.py` all
  build on, and shaped for the not-yet-written pathfinding search besides.
- `quest_jumps.py` - one of two places this project departs from "port
  only": a small, hand-authored registry of quest-narrative shortcuts
  upstream's own connectivity data cannot express (`KNOWN_QUEST_JUMPS`).
  Consulted by `pipeline.py`'s loop (a landing section forced open, same as
  `connected_sections`' own) and by `neighbours.py` (a not-yet-unlocked target
  made a roll candidate). See CLAUDE.md's "Quest jumps" section for why this
  exists at all.
- `object_links.py` - the other departure: chunks linked by a shared physical
  `Object` (a portal) rather than a quest gate - narrower than `quest_jumps.py`
  in every way that matters (symmetric, no trigger, the linked set is scanned
  from the live export rather than named). Consulted by `neighbours.py` only;
  no known entry needs a landing section forced open. See its own module
  docstring for why this is a second registry rather than folded into
  `quest_jumps.py`.
- `search.py` - world-wide fuzzy search over the *raw* export, a strict superset
  of what `chunksim sources` can list.
"""
