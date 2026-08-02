# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

fray-claude is a CLI that reads state from the source-chunk web app, caches it locally, and runs
offline operations on that cache. source-chunk is upstream and read-only from here.

Planned: simulate chunk rolls, render a world-map image for a simulated state, generate heatmaps of
likely rolls over N attempts, estimate time to complete all goals.

## source-chunk

- Source: https://github.com/source-chunk/chunk-picker-v2/
- Live instance, the only one that matters: https://source-chunk.github.io/chunk-picker-v2/?fray

It imposes an artificial rule set on Old School RuneScape by adding barriers to the world: it holds
the set of chosen chunks, tracks goals for the active chunk, and randomly selects the next chunk to
unlock from the allowed neighbours. Reproducing that selection and the neighbour-eligibility rules is
the core of this tool — read the upstream source for them rather than inferring from observed output.

`?fray` is a map ID, not page state — the real backend is a public Firebase Realtime Database, read
with a plain unauthenticated GET: `https://chunkpicker.firebaseio.com/maps/<map_id>.json`. Chunk
adjacency/neighbour data isn't there; it's `chunkpicker-chunkinfo-export.json` in the upstream repo.

**Chunk** — a fixed square block of tiles; the unit source-chunk unlocks.
**Tile** — the smallest interactable square; the avatar occupies one at a time.

## Toolchain

Python 3.14.6, mypy, pip (no uv). Run `mypy .` before each commit.

## Conventions

- PEP 8, type hints on all functions
- Commit after completing a change
- No custom `User-Agent` on requests — the endpoint is public and unauthenticated, so there's nothing
  to disguise
