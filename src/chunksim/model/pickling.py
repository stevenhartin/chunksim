"""Making a frozen dataclass survive a pickle when it is compiled.

**Nothing here changes what any object *is*.** It changes how one is put back
together, and it exists for a single reason: a `@dataclass(frozen=True)` that
`mypyc` has compiled cannot be unpickled by the default machinery.

### The mechanism, because the failure is not obvious

Pickle reconstructs an ordinary object by making an empty one and then
restoring its state - `__reduce_ex__` hands back `__newobj__` plus a state
dict, and the state is applied straight onto `__dict__`, which bypasses
`__setattr__` and so bypasses the frozen guard. That is why a frozen dataclass
pickles perfectly well under the interpreter.

A compiled class has **no `__dict__`**. Its attributes live in native slots, so
pickle falls back to `setattr` for each one - and `setattr` is exactly what
`frozen=True` refuses:

    FrozenInstanceError: cannot assign to field 'valid'

Nothing warns; it raises on the *load*, potentially long after the dump, and in
this project it surfaced as `derived_cache.decode` quietly returning `None` for
every entry it had just written.

### The fix, and why it is this one

Reconstruct through the class's own constructor instead of assembling an
instance behind its back. `__dataclass_fields__` survives compilation and is
already in the order the constructor takes, so the object is rebuilt exactly as
it was first built - by the same code path, with the same invariants.

Two consequences worth knowing:

- **It is not conditional on being compiled.** The same `__reduce__` runs under
  the interpreter, so there is one behaviour to reason about rather than two,
  and the compiled build cannot diverge from the one the tests exercise.
- **Pickles written before this still load.** Unpickling reads whatever the
  stream says to do; only new dumps take the constructor route. A populated
  `cache/derived/` does not need clearing.

Only classes that actually cross a pickle need it - `Derived`'s own fields, and
anything sent through a pool. A class that never leaves the process is not
harmed by having it and is not helped either, so it does not get one.
"""

from __future__ import annotations

from typing import Any


def by_fields(obj: Any) -> tuple[Any, tuple[Any, ...]]:
    """`__reduce__` for a frozen dataclass: rebuild it through its own
    constructor, in declared field order.

    Read off `__dataclass_fields__` rather than a hand-written tuple so that
    adding a field cannot silently drop it from every pickle - which would not
    raise, it would restore an object missing whatever was added last.
    """
    return (obj.__class__, tuple(getattr(obj, name) for name in obj.__dataclass_fields__))
