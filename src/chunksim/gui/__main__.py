"""`python -m chunksim.gui`, the counterpart to `python -m chunksim`.

`[project.scripts]` names `chunksim.gui:main`, which a console script can call
and `-m` cannot: without this file the module is a package and `-m` refuses it.
That only mattered once something had to start the GUI **without** the
generated console script - the Windows payload, where the launcher is a `.cmd`
next to an embeddable interpreter and there are no entry-point wrappers at all.
"""

from __future__ import annotations

from chunksim.gui import main

if __name__ == "__main__":
    raise SystemExit(main())
