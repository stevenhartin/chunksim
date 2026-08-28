"""What a *run* is: a base state, a sequence of rolls, and its replay.

`simulate` rolls chunks from a state and turns a finished ledger back into a map
payload; `batch` runs N of those across processes and owns the seed derivation
and both `ProcessPoolExecutor`s in the project; `timeline` replays one run a
roll at a time and prices what each roll cost.

These three are grouped because they share one non-obvious idea: **a run is
self-contained.** The state before roll k is `final - rolls[k:]`, so stepping
through one needs no base map, no export and no `derive` - which is why the
timeline redraws as you drag it, and why `tests/test_timeline.py` can replay a
run with its base map deleted. Change the on-disk shape of a run and every file
that has to agree is in this directory.

`--jobs` never changes a result, in either pool. That property belongs to
`derive/` (see its `__init__`) and is spent here. **A grind makes it harder to
keep and worth restating**: its scheduler splits some runs into legs and not
others, depending only on how busy the machine happened to be - so a split run
has to land exactly where an unsplit one would, which is why the random
generator's *position* travels with a `grind.Frontier` rather than the seed
being replayed.

The modules, and what each owns:

- `simulate.py` - seeded chunk-roll simulation, and `simulated_payload`.
  Records are never revisited by a later roll.
- `batch.py` - N simulations from one state. Owns the seed derivation and
  **both** `ProcessPoolExecutor`s in the project. **`--jobs` must never change a
  result** - nor may watching one: `on_roll` fires pooled as well as inline, over
  a manager queue that is **one-way**, so nothing a worker reports can reach
  what a worker computes. Also the single writer of the run metadata both apps
  read back (`run_metadata`), and the `body` seam a second kind of run is
  dispatched through - which is what says *how* runs are driven while leaving
  *what a run is* to the body. `_schedule` is the second way it drives one:
  whole legs while every worker has a run of its own, speculative waves once
  the pool drains and the spare capacity has nowhere else to go. **The parent
  is the only stateful thing in it and it is single-threaded**; workers stay
  pure functions and nothing one produces reaches another, so this added no
  synchronisation to the project.
- `grind.py` - one run that rolls until a chunk puts more than a given number
  of hours in front of you, or until the pool runs dry. **Owns the stopping
  rule and nothing else about rolling**: it prices each roll as it lands -
  `timeline.added_hours` against a basis computed on that roll's *own* state,
  not on the one the run ends in - and hands `simulate_rolls` a `should_stop`,
  exactly as `completion.py` owns when to stop and not how a chunk is picked.
  **Spawns nothing**: the five pieces `batch._schedule` drives it with
  (`advance`, `roll_ahead`, `price_wave`, `settle`, `write_leg`, bound by
  `leg_plan`) are plain functions, so there are still two pools in this
  project. Also `collate`, the pure aggregation over a batch of them; it names
  no chunk, because nothing here parses the export.
- `timeline.py` - replaying a run one roll at a time, and `added_hours`: what a
  roll *cost*, as a diff of what is being costed rather than of the totals.
  Also `basis`, which says *how* a stored series was priced beside
  `PRICING_MODEL`'s *when* - the one field in the stamp that is not an input,
  and the only thing keeping the two kinds of run from overwriting each other.
- `completion.py` - runs one seeded chunk-unlock sequence to the account's own
  completion state (fixed start, no bootstrap roll), auto-completing every
  valid Skills/Sailing/Combat/Quest/Diary/Extra task as it goes, and reports
  why it stopped. Reuses `simulate.py`'s `roll_pool`; owns nothing about *how*
  a chunk is picked, only when to stop and what to check at the end. A stuck
  run's final state is the one exception to "nothing here touches disk mid-run"
  - `persist_stuck_state` writes it as a real cached map, via `batch.save_edit`,
  precisely because a broken state is worth loading with this project's own
  tools and a finished one has nothing left to investigate.
"""
