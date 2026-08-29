"""The one thing `pyproject.toml` cannot declare: an optional compiled build.

Everything about this package is in `pyproject.toml`. This file exists solely
because `mypyc` needs `ext_modules`, which is Python rather than TOML, and
because compiling has to be a *choice* rather than what happens when somebody
types `pip install`.

### It is off unless you ask, and `make` is what asks

`CHUNKSIM_COMPILE=1` turns it on. Nothing else does, and a bare
`pip install` still gets a pure-Python wheel:

- **A pure-Python wheel runs anywhere.** Compiling makes the wheel specific to
  one interpreter and one platform, which is a real cost to pay by accident.
- **The source stays canonical.** A compiled build is the same code made
  faster; if the two ever disagree the `.py` is right and the build is a bug.
  `make interpreted` is how you ask the canonical one.

**The development loop compiles, through the `Makefile` rather than through
the install.** `make compile` builds the extensions in place and every target
that runs anything depends on it, so `make test`, `make check` and `make
oracles` all measure what the Windows installer ships.

That is safe only because of the guard, and the guard is the point. A `.so`
shadows the `.py` beside it **silently** - an edited source that has not been
rebuilt still imports and still answers, with the old code - so
`tests/conftest.py` refuses to collect at all while any extension is older
than its source, naming the files and the fix. Without it a green suite would
mean nothing after any edit to these six modules. An incremental rebuild is
~4.8s, which is what makes gating every target on it reasonable; a checkout
with no extensions has nothing to be stale and runs interpreted as before.

### What is compiled, and what is deliberately not

`COMPILED` below is the list, and it is short because it was measured rather
than guessed. On a real map, per roll of a grind simulation:

| | |
|---|---|
| interpreted | 2.98s |
| this project compiled | 2.44s (-18%) |
| `osrs-dps` compiled as well | **2.21s** (-26%) |

`osrs-dps` is a second project with its own `OSRS_DPS_COMPILE=1` and its own
module list; the Windows installer builds both, and so should a checkout that
wants the same numbers.

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

`packaging/build.bat` runs the whole installer build **on a Windows machine**,
so the wheel it ships is built there and compiles there too - it needs a C
toolchain (MSVC Build Tools) and `mypy` on the build interpreter, both of which
`build.bat` checks for and names rather than discovering halfway through.

`build_windows.py` passes `CHUNKSIM_COMPILE=1` and `verify_payload` treats a
payload with no extension modules as a **build failure**, for the reason that
file already applies to the GPL source archives: an installer that is quietly
22% slower than it should be is exactly the "subtly wrong" the build is
arranged to make impossible. `/nocompile` is the way to say you meant it.
"""

from __future__ import annotations

import os
import sys

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

    # **`--python-executable` is not optional here, and the reason is a
    # portability trap rather than a preference.** `mypycify` reads this
    # project's own `[tool.mypy]`, which pins `python_executable` to
    # `.venv/bin/python` so the checker can see pytest's stubs. That path is
    # relative to the checkout and does not exist on Windows at all, where a
    # virtualenv puts its interpreter in `Scripts/`. Left alone, a Windows
    # build fails with `Invalid python executable '.venv/bin/python'` and a
    # build from anywhere but the checkout root fails the same way.
    #
    # The interpreter running the build is the right one to compile against by
    # definition - it is the one the extension will be imported by.
    return mypycify([f"--python-executable={sys.executable}", *COMPILED])


setup(ext_modules=_ext_modules())
