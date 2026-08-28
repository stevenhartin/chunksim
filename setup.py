"""The one thing `pyproject.toml` cannot declare: an optional compiled build.

Everything about this package is in `pyproject.toml`. This file exists solely
because `mypyc` needs `ext_modules`, which is Python rather than TOML, and
because compiling has to be a *choice* rather than what happens when somebody
types `pip install`.

### It is off unless you ask

`CHUNKSIM_COMPILE=1` turns it on. Nothing else does, and that default is
load-bearing rather than cautious:

- **The development loop is an editable install**, and its whole value is that
  a Python edit is live immediately (see CLAUDE.md). A compiled module is a
  `.so` that shadows the `.py` beside it, so a build-on-install would replace
  "edit, reload the tab" with "edit, rebuild, reload the tab" - and would do it
  silently, because the stale `.so` still imports.
- **A pure-Python wheel runs anywhere.** Compiling makes the wheel specific to
  one interpreter and one platform, which is a real cost to pay by accident.
- **The source stays canonical.** A compiled build is the same code made
  faster; if the two ever disagree the `.py` is right and the build is a bug.

### What is compiled, and what is deliberately not

`COMPILED` below is the list, and it is short because it was measured rather
than guessed. On a real map, per roll of a grind simulation:

| | |
|---|---|
| interpreted | 2.72s |
| compiled | **2.13s** (-22%) |

**`costing/estimate.py` is excluded and must stay excluded.** Compiled, it is
**3.8x slower** - 10.26s a roll against 2.71s - and on its own it accounted for
the whole of a 3.5x regression when a first attempt compiled it along with the
rest. The item walk is a fixpoint over tuple-keyed dicts holding small frozen
objects, and whatever mypyc does with that shape, CPython 3.14's specialising
interpreter does better. Anyone adding it back should measure first and will
find the same thing.

`derive/pipeline.py` is excluded for a different reason: `_MAX_AREA_PASSES` is
monkeypatched by three tests, and a compiled module's attributes are read-only.

### The frozen-dataclass trap

A compiled `@dataclass(frozen=True)` **cannot be unpickled** by the default
machinery, which matters here because `cache/derived/` is pickles and the
process pool is pickles. `model/pickling.py` carries the mechanism and the fix;
any class added to a compiled module that crosses a pickle needs its
`__reduce__`.

### Windows

`packaging/build_windows.py` builds its payload on Linux, and a Linux
toolchain cannot produce Windows extension modules. So the Windows payload is
**pure Python**, and is correct rather than merely acceptable: the same source,
without the speed-up. Compiling it would need a Windows build host.
"""

from __future__ import annotations

import os

from setuptools import setup

#: The modules a compiled build accelerates, measured rather than assumed.
#: Order is irrelevant; every one of them is hot, mypy-clean and free of the
#: two traps the module docstring names.
COMPILED: tuple[str, ...] = (
    "src/chunksim/derive/challenges.py",
    "src/chunksim/derive/sources.py",
    "src/chunksim/model/summary.py",
    "src/chunksim/model/rates.py",
    "src/chunksim/model/pickling.py",
    "src/chunksim/costing/gathering.py",
)

#: Set to `1` to build compiled extensions. See the module docstring for why
#: this is opt-in and why it is not the development default.
COMPILE_ENV = "CHUNKSIM_COMPILE"


def _ext_modules() -> list:
    """The extensions to build, or none at all.

    Imported inside the branch so that `mypy` is needed only by a build that
    actually compiles - an ordinary `pip install` of this package must not
    require a type checker to be present.
    """
    if os.environ.get(COMPILE_ENV) != "1":
        return []
    from mypyc.build import mypycify

    return mypycify(list(COMPILED))


setup(ext_modules=_ext_modules())
