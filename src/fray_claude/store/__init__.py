"""Everything that touches the disk.

`cache.py` owns `cache/` - the purpose-sorted layout, the provenance envelope,
the atomic writes and the cross-kind name claim. `derived_cache.py` owns
`cache/derived/`, the content-keyed store of the two expensive computations.
`build_info.py` reads this installation's own metadata, which is disk of a
different kind and the same exception `gui/server.py` makes for its packaged
resources.

**The mirror of `remote/`**: "only `cache.py` touches disk" becomes "only
`store/` touches disk", one directory to audit rather than a rule to remember.

`derived_cache.py` is the one **upward** edge in the layering - it imports from
`derive/` and `costing/` because it caches their results. That is deliberate
and worth stating here rather than discovering: a store of results has to know
the shape of what it stores, and the alternative (results knowing about their
cache) is what the no-module-level-state rule forbids.
"""
