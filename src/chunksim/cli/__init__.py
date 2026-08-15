"""The `chunksim` command: argparse and rendering, one module per subcommand family.

**This file is an entry-point contract and nothing else.** `pyproject.toml`
names `chunksim.cli:main` in `[project.scripts]`, and that string is not
changing, so `main` has to be reachable here. It is the single exception to the
rule that every `__init__.py` in this project is docstring-only: re-exports
elsewhere would rebuild the god-module this split exists to retire, and put
"which tests do I run" back to "all of them".

Everything else lives beside its own parser. There is deliberately no shared
`args.py`: a flag several families carry is declared in each of their
`add_parser` blocks, so changing one edits one file, and
`tests/test_cli_<family>.py` is the file that checks it.

The modules, and what each owns:

- `app.py` - the parser and `main`, and nothing else. If it is about a
  particular subcommand it does not belong here.
- `common.py` - what every family needs before it can answer: `load_state`,
  `derive_cached`, `emit_json`, `digests`, `error`, `DEFAULT_MAP`.
- `render.py` - the shared terminal formatting.
- one module per family, each holding its handlers **and** its `add_parser`
  block: `io_commands`, `listing`, `search`, `unlock`, `diff`, `estimate`,
  `neighbours`, `maps`, `derived`, `simulate`, `gather_tables`.

`gather_tables` is the odd one and says so in its own docstring: **the one
subcommand here that writes into `src/`**, and the one a user never runs.

New *logic* still goes in a pure module, not here. That rule did not change
when this stopped being one file.
"""

from chunksim.cli.app import main

__all__ = ["main"]
