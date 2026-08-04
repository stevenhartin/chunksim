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
  `Diary`, `Quest` or `Other` for the non-skill categories, grouped the way source-chunk's own panel
  groups them; `BiS` for your best-in-slot equipment tasks (see below).
- **`search`** — fuzzy-search any item, monster, NPC, object, shop or task across the *whole* world,
  unlocked or not, to answer "where would I get this". Unlike `sources`, it isn't limited to chunks
  you already hold.
- **`unlock --chunk ID`** — what a single candidate chunk unlock would add on top of your current
  state: new tasks, new reachable sections, and any best-in-slot upgrades it makes reachable. Add
  `--cache-map NAME` to keep the resulting world as a cached map you can point every other command at.
- **`diff --map1 A --map2 B`** — compare two cached maps of any kind, in both directions: what the
  second has that the first doesn't, *and* what it's lost. Unlike `unlock`, which only ever adds one
  chunk to one map, two arbitrary maps can differ either way — so a task valid on one side and not
  the other shows up whichever side it's on.
- **`neighbours`** — which chunks you're currently eligible to unlock, each with the number
  source-chunk's own canvas puts on it, and the connection that makes it reachable.
- **`simulate --rolls N`** — simulate N chunk rolls in sequence and accumulate what each one adds,
  with a `--seed` for reproducible runs. Add `--cache-map NAME` to keep each simulated future as a
  cached map you can point every other command at (`fray tasks --map NAME`), `--runs R` to generate a
  batch of them, and `--jobs J` to spread that batch over worker processes.
- **`maps`** — list what's cached, fetched and simulated alike; `maps rm NAME` and `maps clean`
  remove them again.
- **`heuristics`** — pulls the numbers an estimate needs from the OSRS wiki and a public
  spreadsheet: quest lengths, kills per hour, XP rates, and slayer assignment data. Run about as
  often as `chunkinfo`.
- **`estimate`** — roughly how long the outstanding work would take, in four buckets: quests, boss
  drops, activity unlocks and skilling. Deliberately a heuristic — see below.
- **`derived`** — inspect or clean the cache of computed results (see below).

Everything after the initial `fetch`/`chunkinfo` runs offline, against the local cache.

## The map (`fray-gui`)

There is a second command. `fray-gui` starts a local server and opens a browser on an interactive
OSRS world map: your unlocked chunks bright against a greyed-out world, with a thick border traced
around the *outside* of the unlocked region — no line between two chunks you already hold. Pan by
dragging, zoom with the wheel, click a chunk to copy its id.

```
fray-gui                              # serve http://127.0.0.1:8731 and open it
fray-gui --compare my-sim             # delta mode: gains green, losses red
fray-gui --no-browser --port 0        # bind an OS-assigned port, open nothing
```

It re-reads the cache as it goes, so a `fray fetch` or `fray simulate` in another terminal appears
in the browser a couple of seconds later. You can also drive both from the page itself: **fetch**
re-downloads the current map, and **simulate** rolls N chunks, saves each run as a cached map and
opens the result as a comparison against where you started.

**It binds `127.0.0.1` and is not authenticated.** A page you have open in another tab cannot read
anything from it — the same-origin policy stops that — and its `fetch`/`simulate` buttons are
guarded by the `Sec-Fetch-Site` and `Host` headers. `--host` will bind elsewhere, and the help text
says what that exposes; think before using it on a shared network.

The world map image is **not** part of this repository. It is Jagex's artwork, so `fray-gui`
downloads it from source-chunk to `cache/assets/` on first run — the same thing `fray chunkinfo`
already does with the 10MB export — and nothing this project distributes contains it. Point
`FRAY_WORLD_MAP` at a local copy to skip the download.

**This is a genuine, but deliberately partial, reimplementation of source-chunk's own validity logic**
— not a wrapper around it. `tasks`/`unlock`/`simulate` cover 28 of the 29 challenge categories, plus
`BiS`, which upstream synthesises at runtime rather than storing and which is computed here separately.
What's left out is left out explicitly rather than silently approximated. The three gaps you're most
likely to notice:

- **Five level gates** — `QuestPointsNeeded`, `CombatPointsNeeded`, `KudosNeeded`, `TotalLevelNeeded`
  and `CombatLevelNeeded`. Computing these needs state (quest points earned, kudos, …) that nothing
  in the export provides, so a task carrying one is reported as *unsupported* instead of guessed at.
  That's the only thing that ever lands in that bucket — 42 tasks on the map this was built against.
  Run `fray tasks` and read the `unsupported` line for the count on *your* map.
- **Best-in-slot set effects** — the Void/Obsidian/Inquisitor/Verac's/Crystal/Karil's DPS overrides
  aren't modelled, so a set-bonus item can be under-rated against a raw-stats rival.
- **Manual choices during simulation** — chunk selection and blacklisting, and the `roll2`/`roll5`
  bonus rerolls. `fray simulate` rolls the way an untouched map would.

**`fray estimate` is a rough guide, not a projection.** The chunk-info export contains no durations,
no kill rates and no XP figures of any kind, so every number it spends comes from the OSRS wiki, a
community spreadsheet, or a default — and any of them can be wrong for you. Three things to know
before believing a total:

- The money-making guides only cover **243 of the 2,710** ways of training a skill, because most
  training methods don't make money and so have no guide. Everything else sits at a deliberately low
  1,000 xp/hr so it looks slow rather than free. `fray estimate` prints which skills are on that
  default; correcting them in `heuristics/overrides.json` is where the accuracy comes from.
- **Your skill levels aren't in the map.** source-chunk records a level *cap* and a passively
  reachable level, neither of which is where you actually are, so the estimate counts from the
  passive floor unless you set `levels` in the overrides file. Every skill row prints the level it
  assumed.
- Slayer's rate is averaged over the tasks your master can assign *and* you can reach; the reported
  coverage says how much of the master's task list that was. A low figure means an optimistic number.

That list is the short version, and it moves as the port advances. **Each module's docstring carries
the precise, current statement of what it implements, what it approximates, and what it refuses to
guess at** — `challenges.py`, `bis.py`, `active_tasks.py`, `other_tasks.py`, `sources.py` and
`simulate.py` are the ones to read before trusting a number.

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

Before committing:

```sh
mypy                 # strict type checking; run from the repo root
.venv/bin/pytest     # whole test suite
```

The two are invoked differently on purpose: `mypy` is a *system* install pointed at
`.venv/bin/python` for stubs, so it needs the repo root and an existing virtualenv, while `pytest`
comes from the `dev` extra and so isn't on `PATH` at all.

Tests that check against a real ~7MB chunkinfo export are opt-in and skipped by default. They compare
against source-chunk's own recorded answers, which makes them the suite's real correctness signal —
run them before trusting a change to the derivation modules:

```sh
FRAY_CHUNKINFO=/path/to/raw-export.json .venv/bin/pytest
```

See `CLAUDE.md` for the module-by-module architecture and the testing conventions in full.

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

   If you want `fray estimate`, also pull the rates it spends (~18 requests to the OSRS wiki and one
   published spreadsheet). Like `chunkinfo`, this only needs repeating occasionally:

   ```sh
   fray heuristics
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
   fray tasks Diary                    # outstanding diary tasks, grouped by diary and tier
   fray tasks BiS                      # best-in-slot equipment: still to get, already got, outdated
   fray search "abyssal whip"          # where in the world would I get this?
   fray unlock --chunk 12082           # what unlocking chunk 12082 would add
   fray diff --map1 fray --map2 Future # what's different between two cached maps, both ways
   fray estimate                       # roughly how long the outstanding work would take
   fray estimate skilling              # ... and which training method each skill would use
   fray neighbours                     # which chunks I could unlock next, and their roll numbers
   fray simulate --rolls 20 --seed 1   # simulate 20 rolls; --seed makes it reproducible
   ```

   `sections`, `sources`, `tasks` and `diff` print counts by default and take an optional positional
   to list one branch's contents in full; `--limit N` caps that.

   Add `--export-json -` (to print JSON to stdout, for piping into `jq` or similar) or
   `--export-json PATH` (to write it to a file) to `sections`, `sources`, `tasks`, `search`, `unlock`,
   `diff`, `estimate`, `neighbours` or `simulate` for the full structured result behind the
   human-readable summary.

   If you'd rather point at a chunk-info export you already have on disk instead of fetching it,
   pass `--chunkinfo PATH` to any of those commands, or set the `FRAY_CHUNKINFO` environment variable.

   Working out what's valid takes about a second, so the answer is cached under `cache/derived/` and
   reused until something it depended on changes — your map, the chunk-info export, or the chunks
   you asked about. A repeat command takes about a tenth of a second, and because the cache is keyed
   on those inputs rather than on the command, `fray sections` reuses what `fray tasks` just worked
   out. Nothing needs invalidating by hand: a `fray fetch` simply produces a different answer to
   "what did this depend on". Pass `--recompute` to any of those commands to ignore the cache and
   redo the work, `fray derived` to see what's stored, and `fray derived clean` to drop entries you
   haven't used in a fortnight (`--all` for the lot). Deleting them only ever costs recomputation.

   A simulation derives a state per roll, and by default all of them are kept — so re-running a
   seeded batch takes about a quarter of a second instead of eight, at roughly 118 KiB per state.
   `fray simulate --cache-behaviour extremities` keeps only the state each run starts from and the
   one it ends on (that last one being what the saved simulated map holds, so reading the map back is
   immediate), and `--cache-behaviour none` keeps nothing at all.

5. **Keep a possible future and work against it**, instead of just reading the summary:

   ```sh
   fray simulate --rolls 50 --cache-map Future            # saved as cache/sims/Future/run-001
   fray unlock --chunk 12082 --cache-map Candidate        # the same, for one chosen chunk
   fray tasks --map Future                                # the same commands, against that world
   fray diff --map1 Candidate --map2 Future               # ... or against each other
   fray simulate --rolls 50 --cache-map Sweep --runs 100 --jobs 8   # a batch, 8 processes wide
   fray maps                                              # what's cached, fetched and simulated
   fray maps rm Sweep                                     # ... and remove one again
   fray maps clean                                        # remove every simulated map
   ```

   `unlock --cache-map` saves into the same place a simulation does, so everything below applies to
   it too — it's just a one-run batch whose single "roll" you chose rather than rolled.

   A batch writes one directory per run, addressable as `--map Sweep/run-007`; a bare `--map Sweep`
   works whenever the batch holds exactly one run. Each run records the seed it used, so any single
   run can be reproduced on its own with `fray simulate --seed <that>`. `cache/sims/<name>/batch.json`
   holds every run's rolled chunks in one small file, which is what to read for "how often did chunk X
   come up". Naming a batch something already taken saves it alongside as `<name>-2` rather than
   overwriting, and `maps rm`/`maps clean` refuse to touch a *fetched* map unless you pass
   `--include-fetched` (they never touch the chunk-info download).

   A roll costs a full derivation — a few seconds — so a 50-roll run takes a couple of minutes and
   `--jobs` is how a large batch finishes in a reasonable time. `--jobs` only changes which process a
   run executes in: the same seed gives the same rolls either way.

Run `fray <command> --help` for the full option list of any command, or `fray --help` for the list of
commands.

## License

MIT — see [LICENSE](LICENSE).
