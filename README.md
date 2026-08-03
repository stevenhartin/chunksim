# fray-claude

A command-line tool that reads state from the [source-chunk](https://github.com/source-chunk/chunk-picker-v2/)
web app, caches it locally, and derives things from that cache entirely offline: which sections of
your unlocked chunks are reachable, what items/monsters/objects they give you access to, which
challenges are currently valid, what a candidate chunk unlock would add, and simulated multi-roll
outcomes.

source-chunk is upstream and read-only from here — `fray-claude` never writes back to it.

## What it does

- **`fetch`** — pulls your live map state from source-chunk's Firebase backend.
- **`chunkinfo`** — pulls upstream's chunk/section/challenge reference data (the static rules of the
  game world, not your personal state).
- **`show`** — a quick human summary of your cached map.
- **`sections`** — which sections of your unlocked chunks are actually reachable (some chunks are
  split into numbered sub-areas; unlocking the chunk alone doesn't open all of them).
- **`sources`** — every item, object, monster, NPC and shop your unlocked chunks currently give you
  access to.
- **`tasks`** — which challenges are currently valid, given that access.
- **`unlock --chunk ID`** — what a single candidate chunk unlock would add on top of your current
  state: new tasks, new reachable sections.
- **`simulate --rolls N`** — simulate N chunk rolls in sequence and accumulate what each one adds,
  with a `--seed` for reproducible runs.

Everything after the initial `fetch`/`chunkinfo` runs offline, against the local cache.

**This is a genuine, but deliberately partial, reimplementation of source-chunk's own validity logic**
— not a wrapper around it. `tasks`/`unlock`/`simulate` are correct for the majority of challenge
categories, but a few things are explicitly out of scope for now rather than silently approximated:
`BiS` (best-in-slot) tasks aren't computed at all, and any task whose item requirement uses an item
*family* (e.g. "any axe") or the secondary-item marker is reported separately as unsupported rather
than evaluated. Run `fray tasks` and read the `unsupported`/`not computed` lines it prints, or see the
`challenges.py` module docstring for the full, precise list of what's covered and what isn't.

## Requirements

- Python 3.14 or later
- `pip`

No other runtime dependencies.

## Installation (for development)

```sh
git clone git@github.com:stevenhartin/fray-claude.git
cd fray-claude
pip install -e ".[dev]"
```

This is an editable install: it links the `fray` console script to your checkout and pulls in the
`dev` extra (`pytest`), so edits take effect immediately without reinstalling.

Before committing, run the same checks CI would expect:

```sh
mypy      # strict type checking, from the repo root
pytest    # whole test suite
```

See `CLAUDE.md` for the module-by-module architecture, testing conventions, and — importantly — the
precise list of what each derivation module does and doesn't implement.

## Deploying

`fray-claude` is a local CLI, not a service, so there's no server to deploy — "deploying" here just
means producing an installable copy on a machine that isn't your development checkout, without the
dev extras or an editable install.

**Option A — install straight from the repository:**

```sh
pip install git+https://github.com/stevenhartin/fray-claude.git
```

**Option B — build a wheel and ship it:**

```sh
pip install build
python -m build             # writes dist/fray_claude-<version>-py3-none-any.whl
```

Copy the resulting `.whl` to the target machine and install it there:

```sh
pip install fray_claude-<version>-py3-none-any.whl
```

Either way, the target machine only needs Python 3.14+ — there's nothing else to provision.

## Usage (once `fray` is installed)

`fray` stores its cache in a `cache/` directory. If you're running it from inside a checkout of this
repository (or any directory tree containing a `pyproject.toml`), that's where `cache/` lands;
otherwise it's created in whatever directory you're in when you run `fray`.

1. **Fetch your map's live state** (replace `your-map-id` with your actual source-chunk map id; it
   defaults to `fray`):

   ```sh
   fray fetch --map your-map-id
   ```

2. **Fetch the upstream reference data** (~10MB; static game-world data, not personal state, so this
   only needs repeating when source-chunk itself updates it):

   ```sh
   fray chunkinfo
   ```

3. **Look at what you've got:**

   ```sh
   fray show
   ```

4. **Derive things offline**, no network required from here on:

   ```sh
   fray sections                       # reachable sections of your unlocked chunks
   fray sources                        # items/objects/monsters/npcs/shops available to you
   fray tasks                          # which challenges are currently valid
   fray unlock --chunk 12082           # what unlocking chunk 12082 would add
   fray simulate --rolls 20 --seed 1   # simulate 20 rolls; --seed makes it reproducible
   ```

   Add `--export-json -` (to print JSON to stdout, for piping into `jq` or similar) or
   `--export-json PATH` (to write it to a file) to `sections`, `sources`, `tasks`, `unlock`, or
   `simulate` for the full structured result behind the human-readable summary.

   If you'd rather point at a chunk-info export you already have on disk instead of fetching it,
   pass `--chunkinfo PATH` to any of those commands, or set the `FRAY_CHUNKINFO` environment variable.

Run `fray <command> --help` for the full option list of any command, or `fray --help` for the list of
commands.

## License

MIT — see [LICENSE](LICENSE).
