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
`derive/` (see its `__init__`) and is spent here.
"""
