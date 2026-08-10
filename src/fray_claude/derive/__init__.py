"""The pure layer: what the unlocked chunks mean.

The derivation chain `sections -> sources -> challenges -> bis ->
active_tasks/other_tasks`, wired by `pipeline.derive`, plus everything that
walks or diffs the result: `boosts`, `graph`, `neighbours`, `unlock`, `delta`,
`search`.

**The rule this directory carries, once, for all thirteen modules: no
module-level mutable state.** No `lru_cache`, no memo dicts, no globals. Not
tidiness - `fray simulate --jobs N` and `batch.price_steps` run this code in
worker processes, and a cache in a "pure" module breaks that silently, in the
form of runs that disagree. `MapState` and `Derived` are frozen for the same
reason. `_UNARMED_SOURCES` and `_UNIVERSAL_PRIMARY` are read-only constants and
are the only module-level data here.

Nothing in here reads the network or the disk. Where a result is expensive
enough to be worth storing, the storing happens in `store/derived_cache.py` and
this layer stays unaware of it - which is what keeps the opt-in oracles an
honest signal.
"""
