# fray-claude

A command-line tool that reads state from the [source-chunk](https://github.com/source-chunk/chunk-picker-v2/)
web app, caches it locally, and derives things from that cache entirely offline: which sections of
your unlocked chunks are reachable, what items/monsters/objects they give you access to, which
challenges are currently valid and which are your current goal per skill, your best-in-slot equipment
per combat style, what a candidate chunk unlock would add, and simulated multi-roll outcomes.

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
- **`tasks`** — which challenges are currently valid, given that access. Pass a skill category to see
  which single challenge is your *current* goal for that skill and which lower tiers it supersedes;
  pass `BiS` for your best-in-slot equipment tasks (see below).
- **`search`** — fuzzy-search any item, monster, NPC, object, shop or task across the *whole* world,
  unlocked or not, to answer "where would I get this". Unlike `sources`, it isn't limited to chunks
  you already hold.
- **`unlock --chunk ID`** — what a single candidate chunk unlock would add on top of your current
  state: new tasks, new reachable sections, and any best-in-slot upgrades it makes reachable.
- **`simulate --rolls N`** — simulate N chunk rolls in sequence and accumulate what each one adds,
  with a `--seed` for reproducible runs.

Everything after the initial `fetch`/`chunkinfo` runs offline, against the local cache.

**This is a genuine, but deliberately partial, reimplementation of source-chunk's own validity logic**
— not a wrapper around it. `tasks`/`unlock`/`simulate` cover 28 of the 29 challenge categories, plus
`BiS`, which upstream synthesises at runtime rather than storing and which is computed here separately.
What's left out is left out explicitly rather than silently approximated. The main gaps:

- **Five level gates** — `QuestPointsNeeded`, `CombatPointsNeeded`, `KudosNeeded`, `TotalLevelNeeded`
  and `CombatLevelNeeded`. Computing these needs state (quest points earned, kudos, …) that nothing
  in the export provides, so a task carrying one is reported as *unsupported* instead of guessed at.
  That's the only thing that ever lands in that bucket — 42 tasks on the map this was built against.
- **Best-in-slot set effects** — the Void/Obsidian/Inquisitor/Verac's/Crystal/Karil's DPS overrides
  aren't modelled, so a set-bonus item can be under-rated against a raw-stats rival.
- **Anything needing history you don't have** — boost ownership, manual per-task overrides, and
  manual chunk selection/blacklisting during simulation.

Run `fray tasks` and read the `unsupported` line it prints for the count on *your* map. The module
docstrings in `challenges.py`, `bis.py`, `active_tasks.py`, `sources.py` and `simulate.py` carry the
full, precise list of what each one does and doesn't implement — read them before trusting a number.

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

`pytest` comes from the `dev` extra, so it lives in the virtualenv you installed into rather than on
`PATH` — activate that environment first, or call it by path (`.venv/bin/pytest`). `mypy` is expected
to be a system install: it's configured to point at `.venv/bin/python` for stubs, so it must run from
the repo root and the virtualenv has to exist.

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
   fray tasks Woodcutting              # your current goal for one skill, and what it supersedes
   fray tasks BiS                      # best-in-slot equipment: still to get, already got, outdated
   fray search "abyssal whip"          # where in the world would I get this?
   fray unlock --chunk 12082           # what unlocking chunk 12082 would add
   fray simulate --rolls 20 --seed 1   # simulate 20 rolls; --seed makes it reproducible
   ```

   `sections`, `sources` and `tasks` print counts by default and take an optional positional to list
   one branch's contents in full; `--limit N` caps that.

   Add `--export-json -` (to print JSON to stdout, for piping into `jq` or similar) or
   `--export-json PATH` (to write it to a file) to `sections`, `sources`, `tasks`, `search`, `unlock`,
   or `simulate` for the full structured result behind the human-readable summary.

   If you'd rather point at a chunk-info export you already have on disk instead of fetching it,
   pass `--chunkinfo PATH` to any of those commands, or set the `FRAY_CHUNKINFO` environment variable.

Run `fray <command> --help` for the full option list of any command, or `fray --help` for the list of
commands.

## License

MIT — see [LICENSE](LICENSE).
