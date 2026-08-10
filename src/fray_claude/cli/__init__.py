"""The `fray` command: argparse and rendering, one module per subcommand family.

**This file is an entry-point contract and nothing else.** `pyproject.toml`
names `fray_claude.cli:main` in `[project.scripts]`, and that string is not
changing, so `main` has to be reachable here. It is the single exception to the
rule that every `__init__.py` in this project is docstring-only: re-exports
elsewhere would rebuild the god-module this split exists to retire, and put
"which tests do I run" back to "all of them".

Everything else lives beside its own parser: `app.py` (the parser and `main`),
`common.py` (what the handlers share), `args.py` (the flags several
subcommands carry), `render.py`, and one module per family - `io_commands`,
`listing`, `search`, `unlock`, `diff`, `estimate`, `maps`, `derived`,
`simulate`. Changing a flag edits one file, and `tests/test_cli_<family>.py`
is the file that checks it.

New *logic* still goes in a pure module, not here. That rule did not change
when this stopped being one file.
"""

from fray_claude.cli.app import main

__all__ = ["main"]
