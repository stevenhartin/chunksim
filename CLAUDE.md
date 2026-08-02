# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

fray-claude is a command-line tool that reads data from a web app called **source-chunk**, caches it
locally, and performs offline operations on it (simulation, image generation, statistics). It extends
the web app's behaviour rather than modifying it — the web app is upstream and read-only from here.

**Status: no source code exists yet.** The sections below describe intended design and the verified
local toolchain. Update this file as the actual layout lands.

## Upstream data source: source-chunk

- Source: https://github.com/source-chunk/chunk-picker-v2/
- Production: https://source-chunk.github.io/chunk-picker-v2/
- Instances are selected by URL argument (`/?<account>`). **Only the `fray` instance matters:**
  https://source-chunk.github.io/chunk-picker-v2/?fray

source-chunk imposes an artificial rule set on Old School RuneScape by adding barriers to the game
world. It holds the set of currently chosen chunks, tracks goals for the active chunk, and randomly
selects the next chunk to unlock from an allowed list of neighbouring chunks. That random selection
and the neighbour-eligibility rules are what this tool needs to reproduce faithfully offline — read
the upstream source before implementing the roll logic rather than inferring it from observed output.

## Domain glossary

- **RuneScape** — the Jagex MMO; here always Old School RuneScape (OSRS).
- **Tile** — the smallest interactable square of the game world. The avatar occupies one tile.
- **Chunk** — a fixed square block of tiles; the unit source-chunk unlocks and this tool simulates.

## Planned capabilities

- Read current state from the published URL
- Cache that data locally
- Simulate chunk rolls
- Render a world-map image for a locally simulated state
- Generate heatmaps of likely chunk rolls over N attempts
- Estimate time to complete all goals

## Toolchain

Verified present on this machine:

- Python 3.14.6 (`python` and `python3` both resolve to it)
- mypy at `/usr/bin/mypy`
- pip (no `uv` installed)

Type-check before committing:

```bash
mypy .
```

Install dependencies with pip.

## Code style

- PEP 8
- Type hints on all functions; code must pass mypy

## Git

Remote is `git@github.com:stevenhartin/fray-claude.git` (SSH), default branch `main`. Note the
account handle is `stevenhartin` — a `stevehhartin` spelling does not exist.

`.gitignore` is GitHub's Python template; check it before adding ignore rules, as most Python
artefacts (`__pycache__`, venvs, `.mypy_cache`) are already covered.

Commit after completing a change, and run the type checker before each commit.

This directory sits inside `/home/steven/Documents/repos`, which is itself an unrelated AUR clone of
`yay`. That only matters if the nested `.git` here is ever removed — git would then silently walk up
and target the `yay` repo instead.

## Permissions

`.claude/settings.json` (committed) pre-approves `Edit`/`Write` and `Bash` for `git`, `python`,
`python3`, `mypy`, `pip` and `pip3`, so those run without prompting.

Permission rules only take effect from that file — rules written as prose in this file are
documentation, not configuration, and the harness does not enforce them.
