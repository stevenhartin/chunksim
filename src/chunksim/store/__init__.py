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

The modules, and what each owns:

- `cache.py` - the disk. **`overrides_path` is where a correction is *written*
  and `overrides_source` is the file actually *read***; they differ on an
  installed build that has never had a knob edited, and anything keying a cache
  on "which corrections were these" wants the second. Both resolve the same way
  however `root` arrived, or the two apps price one map two ways. Also
  **`data_root`**, where everything hangs off - `CHUNKSIM_CACHE`, else the
  checkout, else the user's own data directory - and the envelope, the
  `--chunkinfo`/`CHUNKSIM_CHUNKINFO` override, `--map` resolution across kinds,
  the atomic writes, the cross-kind name claim, `migrate_layout`, and both
  override files. **The two sidecars keyed by map id rather than stored beside
  the map** - `cache/overrides/` and `cache/players/` - travel with it:
  `copy_player` gives a map made from another one its account, `player_source`
  is the single place a run's read falls back to its batch's file, and
  `_remove_sidecars` takes both away with the map, since a name is
  reclaimable.
- `derived_cache.py` - the on-disk cache of the **two** expensive per-state
  computations, and both their keys. **Read it before changing what `derive`
  returns**, including a *nested* result dataclass, which `_RESULT_TYPES` must
  list or the key will not move.
- `build_info.py` - which install is running and when it was made. Never raises
  and never guesses a date. Also `parse_version`/`is_newer`, a **strict**
  reading of `X.Y.Z` that returns `None` rather than guess, since there is no
  PEP 440 parser in the stdlib and no dependency to add one.
"""
