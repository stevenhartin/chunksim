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
  batch of them, and `--jobs J` to control how wide it runs (it already uses every core; `--jobs 1`
  makes it serial).
- **`maps`** — list what's cached, fetched and simulated alike; `maps rm NAME` and `maps clean`
  remove them again.
- **`heuristics`** — pulls the numbers an estimate needs from the OSRS wiki and a public
  spreadsheet: quest lengths, kills per hour, XP rates, slayer assignment data, and the per-bone
  and per-altar figures Prayer is priced from. Run about as often as `chunkinfo`.
- **`estimate`** — roughly how long the outstanding work would take, in four buckets: quests, boss
  drops, activity unlocks and skilling. Deliberately a heuristic — see below.
- **`derived`** — inspect or clean the cache of computed results (see below).

Everything after the initial `fetch`/`chunkinfo` runs offline, against the local cache.

## The map (`fray-gui`)

There is a second command. `fray-gui` starts a local server and opens a browser on an interactive
OSRS world map — the wiki's cartography render, drawn from the game's own cache, at twice the detail
of the published map and with the icons on it. It is the *whole* world: every dungeon, instance and
boss room as well as the overworld, on one grid, with a selector for which floor to draw and the
rooms named on it — Kurask Lair, Karuulm Slayer Dungeon, Grotesque Guardians' Lair. Every place the
export knows about has a square, including the ones it stores only by name. Your
unlocked chunks are bright against a greyed-out world, with a thin grid showing every chunk
boundary, and a thick border traced around the *outside* of the unlocked region — no heavy
line between two chunks you already hold. Pan by dragging, zoom with the wheel, click a chunk to
open it in the panel. Press <kbd>F</kbd> to fly the camera to whatever is under the cursor.

```
fray-gui                              # serve http://127.0.0.1:8731 and open it
fray-gui --compare my-sim             # start in diff mode: gains green, losses red
fray-gui --no-browser --port 0        # bind an OS-assigned port, open nothing
fray-gui --no-browser --keep-alive --host 100.93.219.108   # serve it to another machine
```

It opens as its own window — no tabs, no address bar — and **closing that window stops the server**,
so there is nothing left running afterwards. That uses whichever Chromium-family browser you already
have (Chrome, Edge, Brave, Chromium…); it is not a dependency, and if you have none, it opens an
ordinary tab instead and shuts down about fifteen seconds after you close it. `--tab` forces that
second behaviour if you would rather have your own profile and extensions.

**Candidates** draws the chunks you could roll next, each carrying the number source-chunk's own
canvas gives it — the decision the game asks you to make, as a picture rather than a list.
**Sections** shades the inside of split chunks using source-chunk's own masks: green where you can
reach, red where you cannot — including chunks you have not unlocked, which is where the question
matters most. A chunk that is *not* split is shaded whole, since one undivided section is still a
section.

Click any chunk for its contents, grouped by kind, with anything behind a door you cannot open
greyed out; for one you do not own yet, **What would this add?** derives both worlds and tells you,
and **Unlock** then saves that world as a map of its own — the same thing `fray unlock --cache-map`
does, named in a dialog and then opened, with its new chunk drawn green. In edit mode the same button
reads **Add to edit** instead and costs nothing until you commit. The category chips are
checkboxes, not tabs — all on to begin with, so you can look at monsters and NPCs together, or
narrow to one.

### Four modes

A coloured ribbon under the toolbar says which one you are in, with the map named on it.

**Browse** is the map as it is. **Compare** puts you in **Diff**: pick a second map and its world is
what you see — gains green, what it lost red and washed out like anything else you do not hold — with
both selectors on the ribbon so the pair is changeable without leaving, and **Breakdown** opening the
whole of `fray diff` in a panel (sections, tasks, sources and BiS, both directions). A floating
**Exit diff view** takes you back.

**Edit** is entered by making an edit: click a task in the panel and it asks first. Ticked tasks
strike through, chunks added from the chunk panel light up amber on the map, and *nothing is
computed* until you press **Commit** — which writes it all as a new map under `cache/maps/edited/`,
leaving the one you started from untouched. The ribbon counts what is waiting; leaving the mode or
changing map asks before discarding it.

**Timeline** is the only mode a simulation is seen in, because a run is fifty worlds rather than one.
Choosing one asks whether you meant to replay it, and declining leaves you where you were. The strip
along the bottom is the run's history: drag it, click a bar to fly to the chunk that roll added, or
press **Details** for what it opened — the furthest task per skill, the same rule the Tasks tab
applies, including the case where the roll made a skill trainable at all and everything it had been
sitting on became worth doing at once.

**The panel follows the roll you stop on.** Tasks, Estimate and Find all describe the world as it
stood after that roll rather than the finished run, so stepping back through a simulation is a way
of asking what you would have been doing at the time and what was still ahead of you. Dragging the
slider only moves the map; letting go is what re-asks the panel, because the map is a read and each
panel is a derivation. **Snapshot** saves the world at the roll you are looking at as
a map in its own right — which is how you get out of a timeline: it browses, edits and diffs like any
other map, where the run itself cannot.

The panel covers the rest of the CLI. **Tasks** is what you are actually doing — checkbox chips per
category and a toggle for what is already done; quests show only the step you are on, and
collection-log entries read *Barrows Chests / dharok's greataxe* rather than the raw
`(Barrows Chests) Obtain a ~|dharok's greataxe|~`. **Estimate** is the hours as a donut you hover for
the figure, then the same buckets again as lists of what is actually in them. **Click a row to see
the numbers it was priced off** — the kill rate, the shop price, the slayer table, a quest's length,
the training rate behind a climb — with the layer each came from, and correct any of them in place.
Rows that cannot be argued with say so instead of offering an editor: a ground spawn is priced
entirely from constants, and a Slayer climb comes off a master's whole assignment table rather than
any single entry. A number nobody has set shows what it actually resolves to rather than the word
"default", anything you have overridden is bordered and flagged with a **Revert** beside it, and the
names the wiki has a page for are links — clicking one frames its chunks exactly as **Find** does. Where the correction
is saved depends on where you are: in **Browse** it goes to `heuristics/overrides.json`, which is
checked in and applies to every map; in **Timeline** or **Edit** it belongs to that map alone, in
`cache/overrides/`. Emptying the box takes the correction back out. **Find** searches the
whole world as you type, puts what you can reach first, and fits the camera around every place a
thing comes from. **Maps** lists what is cached, with the actions that make and remove it — including the two things every number rests on, the chunk export and the wiki rates, each with the date it was last fetched. The rates are scraped automatically the first time you open the GUI without them, since otherwise every hour in **Estimate** is a fallback default.

A simulated run gets a **timeline**: a strip across the bottom with a slider that steps through the
rolls, redrawing the world after each one. `fray simulate` has always written every roll down and
nothing ever read it back, so a simulation could tell you where you ended up and not what each roll
bought you. A run carries its own past, so stepping costs nothing — drag the slider and the map
follows.

Above it, a bar per roll, and both series are there the moment the simulation finishes. **Tasks** is
the challenges that chunk made valid, with a breakdown per skill on hover. **Hours** is what that
roll newly put in front of you — a simulation prices every roll as it goes, which costs it almost
nothing, since the work of deriving each state is what a roll already is.

The hours axis is **logarithmic** by default, ruled at 10, 100, 1,000 and 10,000 hours, because a
run's rolls span four decades and a linear axis spends the whole strip on the largest one; **Linear**
beside it is the older behaviour. The bars are coloured by how much of your life a roll costs —
*Free*, *Quick*, *Grind*, *Brutal*, *Death* — and **Edit** under the graph moves those edges and
renames them. That is a preference rather than data about a map, so it is kept in
`cache/gui/settings.json` beside the window geometry, and applies to every map you open.

Clicking a bar moves the slider to that roll, selects the chunk it rolled and flies the camera to
it; **Details** then opens that roll in full — every task it made valid, by skill, rather than the
counts the bars draw. They are two gestures rather than one because a dialog would cover the map
the click had just framed.

A simulation is stored as the map it started from plus the sequence of rolls, so a run can be
replayed and re-costed even if the map it came from has since been refetched or removed — and because
the sequence is measured against that fixed starting point, re-costing it reuses everything the
simulation already worked out.

A bar is what that roll *cost you*, assuming everything before it is already done — so most are
empty, because on a mature map a new chunk usually adds no work at all, and none are negative. A
chunk that merely opens a cheaper route to something you already needed has added nothing: the saving
is real, and it is not something that roll did. For the same reason the bars do not add up to the
figure on the Estimate tab; they are what each roll cost, not a breakdown of what is left.

If you have the `dps` extra, *Reprice with gear* recomputes those hours from the gear the map
actually reaches rather than the wiki's assumed setup. That is real work — nearly all of it is
simulating fights — so it runs across every core, keeps whatever the previous roll already worked out
(a chunk roll only ever *adds*, and 94% of kill rates come out identical), and is stored afterwards.
A 20-roll run takes about half a second once its states are worked out. Simulations skip it by
default because doing it inline would nearly triple a large batch, and most batches are never
opened.

`?map=…&step=4` deep-links a particular roll.

It re-reads the cache as it goes, so a `fray fetch` or `fray simulate` in another terminal appears
in the browser a couple of seconds later. You can also drive both from the page itself. **Fetch
Named Map** takes an id rather than the map on screen — every source-chunk map is a public read, so
you can pull down one you have never cached, or a friend's; leaving the box empty fetches `fray`.
**Roll** simulates N chunks, saves each run as a cached map and opens the result as a comparison. The
progress card counts rolls rather than runs — `47/300` on a three-run job — and carries a stop button:
stopping keeps every roll already finished, as an ordinary map you can open, derive and step through.
`fray maps` marks it `(stopped)` so a run that ended short is not mistaken for one that finished.

`?map=…&compare=…&candidates=1&sections=1&step=4&tab=estimate` reproduces a view, so a particular question
is shareable and a screenshot is reproducible.

It remembers the size and position you left the window at. Chrome will not do that for a page whose
URL changes between launches, which this one's does, so the page reports its own geometry back; the
first run opens maximised.

**Both apps say which install answered.** `fray` prints one line to stderr before anything else —
`fray 0.1.0 · installed 3h ago` — and the map carries the same thing as a faint watermark in its
bottom-left corner, read from the server rather than baked into the page. This is not decoration:
an install can be older than the checkout it came from and behave exactly as if it were not —
`pipx install` on a package whose version has not moved is a silent no-op, so a wheel install can sit
weeks behind with no symptom. An editable install cannot go stale, and says `editable, linked 3h ago`
instead: its date is the age of the link, its code is whatever the checkout holds right now. `FRAY_NO_WATERMARK=1` silences the line;
stderr keeps it clear of `--export-json -` either way.

**It binds `127.0.0.1` and is not authenticated.** A page you have open in another tab cannot read
anything from it — the same-origin policy stops that — and its `fetch`/`simulate` buttons are
guarded by the `Sec-Fetch-Site` and `Host` headers. `--host` will bind elsewhere, and the help text
says what that exposes; think before using it on a shared network.

**To drive it over ssh and read it from another machine**, there are two ways and the first needs no
flags. Forward the port — `ssh -N -L 8731:127.0.0.1:8731 devbox`, then open
`http://127.0.0.1:8731/` on the laptop — and as far as the server is concerned nothing has changed.
Or serve the address directly:

```
fray-gui --no-browser --keep-alive --host 100.93.219.108
```

`--host` binds it *and* names it, so the page served there can use its buttons rather than rendering
in full and refusing every action. `--allow-host` adds a name the bind does not spell — a MagicDNS
name, or anything at all when `--host` is a wildcard, since `0.0.0.0` names no address anyone types.
`--keep-alive` disarms the idle shutdown, which otherwise stops the server fifteen seconds after the
last client goes away: right for a closed tab, wrong for a server you left running in tmux. **The
address is the whole of the access control** — a tailnet address is a very different proposition
from `0.0.0.0` on a café network — so the startup line says outright when the bind is reachable by
other machines.

**The map is the OSRS wiki's, and your browser loads it directly from their CDN.** No map image is
downloaded, cached or served by `fray-gui` — it hands the page a URL and the page uses it. That is
deliberate: the tiles are CC BY-NC-SA 3.0 and this project is MIT, so keeping a copy would make it a
redistributor of NonCommercial artwork, while linking makes it a page with a picture on it. The
credit sits in the corner of the map, which is what that licence asks for. If the wiki ever moves
its tiles, `FRAY_TILE_VERSION` pins a render by hand.

The section masks and skill icons *are* fetched — they come from source-chunk, one file at a time as
you first look at them rather than all 1,558 up front.

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

- **A skill is priced method by method as each one unlocks**, not at one rate for the whole climb —
  Herblore 1→99 on a real map is nine bands, from cleaning guams at level 3 up to super combats at
  90, and `fray estimate skilling` prints them with the level range and the XP each covers. Rates
  come from four places and each band says which: a money-making guide (225 of the export's 2,657
  training methods — most training doesn't make money, so most has no guide), the wiki's own skill
  and training-page tables (Agility, Thieving, Firemaking, Woodcutting, Hunter and part of Fishing), a per-action
  calculation from the wiki's recipe data, and for the five combat skills the damage you deal. On a real map that prices **943 of the 1,323 methods it
  can reach**; what is left sits at a deliberately low 1,000 xp/hr so it looks slow rather than free,
  and under bands that floor usually applies to the bottom of a climb rather than all of it.
  151 of the guide joins are matched by *containment* rather than exactly — usually right,
  occasionally not, and `heuristics/overrides.json` is where you disagree.
- **Getting a thing costs what it costs.** An item is priced by the cheapest route this map has to
  it, and none of them are free: a shop charges its price at 500,000 gp an hour (or 25,000 Tokkul,
  or 19.5 marks of grace — all tunable) plus thirty seconds to walk there, a ground spawn is limited
  by how fast you can hop worlds to a fresh one, and performing an action costs its own time. What
  cannot be priced is *said* rather than skipped: `fray estimate` lists what it could not cost, and
  items sold for currencies with no agreed rate stay on that list.
- **Your skill levels aren't in the map.** source-chunk records a level *cap* and a passively
  reachable level, neither of which is where you actually are, so the estimate counts from the
  passive floor unless you set `levels` in the overrides file. Every skill row prints the level it
  assumed — with a `*` when quests you can still finish pay experience into it, which the estimate
  takes off the front of the climb.
- **Some goals cannot be trained at all.** Attack, Defence, Hitpoints and Ranged carry no training
  method anywhere in the export — you train them by fighting — so those goals are reported as
  unpriced rather than being charged a made-up rate, or, as they once were, silently costed at zero.
- Slayer's rate is averaged over the tasks your master can assign *and* you can reach; the reported
  coverage says how much of the master's task list that was. A low figure means an optimistic number.

That list is the short version, and it moves as the port advances. **Each module's docstring carries
the precise, current statement of what it implements, what it approximates, and what it refuses to
guess at** — `derive/challenges.py`, `derive/bis.py`, `derive/active_tasks.py`,
`derive/other_tasks.py`, `derive/sources.py` and `runs/simulate.py` are the ones to read before
trusting a number.

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

To get `fray` and `fray-gui` on your `PATH` outside the checkout while still tracking it, install
them the same way with pipx — once, not per change:

```sh
pipx install --force --editable .
```

Everything then follows the source: a Python edit, and equally an edit to the GUI's `app.js` or
`style.css`, since the server reads those from the checkout too. Nothing needs rebuilding, and the
watermark reads `editable install` so you can tell at a glance which kind you are running. The
trade is that the checkout becomes load-bearing — move or delete it and both commands break.

Before committing:

```sh
mypy                 # strict type checking; run from the repo root
.venv/bin/pytest     # whole test suite
```

The two are invoked differently on purpose: `mypy` is a *system* install pointed at
`.venv/bin/python` for stubs, so it needs the repo root and an existing virtualenv, while `pytest`
comes from the `dev` extra and so isn't on `PATH` at all.

Tests that check against a real ~10MB chunkinfo export are opt-in and skipped by default. They compare
against source-chunk's own recorded answers, which makes them the suite's real correctness signal —
run them before trusting a change to the derivation modules:

```sh
FRAY_CHUNKINFO=cache/reference/chunkinfo.json FRAY_MAP_CACHE=1 .venv/bin/pytest
```

That is the whole setup once `fray chunkinfo` and `fray fetch` have run — the variable takes the
cached file as it is written, or a raw export if you have one. Without the variables the same tests
skip, so a fresh clone stays green.

The library is six subpackages under `src/fray_claude/`: `model/` (what upstream's data is),
`remote/` (the only outbound calls), `store/` (the only disk), `derive/` (the pure layer),
`costing/` (derivation to hours) and `runs/` (a base state plus a sequence of rolls), with `cli/`
and `gui/` as the two apps on top. Tests are flat in `tests/` and named for what they cover, so
`tests/test_cli_estimate.py` goes with `cli/estimate.py`.

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

   If you want `fray estimate`, also pull the numbers it spends. Two different sources, both from the
   wiki and both only worth repeating occasionally:

   ```sh
   fray heuristics                     # 30+ requests: guides, quest lengths, skill tables, monster hp, bones
   fray recipes                        # 13 requests: xp per action and tick costs, per skill
   ```

   The second is what stops most training methods being priced at a flat 1,000 xp/hour: it brings
   back what one action of a method actually pays and how long it takes, for 3,889 recipes. Where a
   money-making guide exists it still wins - see `fray estimate skilling`, which prints where each
   band's rate came from.

3. **Look at what you've got:**

   ```sh
   fray show
   ```

   Counts of unlocked chunks, active tasks and enabled rules. It also prints a `slayer locked` line
   *when there is one* — the map records the Slayer task you are stuck on and the level it holds you
   at, and that quietly caps every Slayer requirement in every other answer this tool gives.

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

   The same cache holds the other slow thing, if you have the `dps` extra: recomputing every kill
   rate from your map's own gear takes about two thirds of a second, and dwarfs the estimate it
   feeds — so that gets stored too, and `fray estimate` drops from 1.7s to 0.2s on a repeat. It is
   keyed on the rates, your `heuristics/overrides.json` *and* the calculator's own source, so
   editing an override or upgrading `osrs-dps` recomputes rather than quietly serving you the old
   number.

   A simulation derives a state per roll, and by default all of them are kept — so re-running a
   seeded batch takes about a quarter of a second instead of eight, at roughly 118 KiB per state.
   `fray simulate --cache-behaviour extremities` keeps only the state each run starts from and the
   one it ends on (that last one being what the saved simulated map holds, so reading the map back is
   immediate), and `--cache-behaviour none` keeps nothing at all.

5. **Keep a possible future and work against it**, instead of just reading the summary:

   ```sh
   fray simulate --rolls 50 --cache-map Future            # saved as cache/maps/simulated/Future/run-001
   fray unlock --chunk 12082 --cache-map Candidate        # the same, for one chosen chunk
   fray tasks --map Future                                # the same commands, against that world
   fray diff --map1 Candidate --map2 Future               # ... or against each other
   fray simulate --rolls 50 --cache-map Sweep --runs 100    # a batch, as wide as the machine
   fray maps                                              # what's cached, fetched and simulated
   fray maps rm Sweep                                     # ... and remove one again
   fray maps clean                                        # remove every simulated map
   ```

   `unlock --cache-map` saves into the same place a simulation does, so everything below applies to
   it too — it's just a one-run batch whose single "roll" you chose rather than rolled.

   A batch writes one directory per run, addressable as `--map Sweep/run-007`; a bare `--map Sweep`
   works whenever the batch holds exactly one run. Each run records the seed it used, so any single
   run can be reproduced on its own with `fray simulate --seed <that>`. `cache/maps/simulated/<name>/batch.json`
   holds every run's rolled chunks in one small file, which is what to read for "how often did chunk X
   come up". Naming a batch something already taken saves it alongside as `<name>-2` rather than
   overwriting, and `maps rm`/`maps clean` refuse to touch a *fetched* map unless you pass
   `--include-fetched` (they never touch the chunk-info download).

   A roll costs a full derivation — most of a second — so a 50-roll run is around forty seconds of
   CPU, and a batch spreads its runs over every core by default. `--jobs 1` makes it serial again if
   you'd rather have the machine back; `--jobs` only changes which process a run executes in, and the
   same seed gives the same rolls either way.

   Each roll also hands the map areas it discovered to the next one instead of rediscovering them,
   which is most of another 2× — 10×50 rolls take about 48 seconds rather than 84. That can't be
   *proved* to reach the same answer, only measured to, so every run checks itself: the state it
   finishes on is re-derived the ordinary way and compared, and the run fails loudly rather than
   saving a number it can't stand behind. `--no-carry-areas` turns it off and derives every roll from
   scratch.

   Its intermediate states are held rather than written until that check passes, so a carried run
   ends up caching every roll like a cold one — it just does it a moment later, and a run that
   diverges writes nothing at all.

   A run also **prices its own timeline** when it finishes, on exactly the basis the Estimate tab
   uses, so the hours are right the moment the simulation ends rather than after you press a button.
   That costs about 10% on a batch (16×50 goes from 48s to 53s) and roughly doubles its peak memory,
   which is the price of the real estimate rather than of the timeline; what it buys is the last
   bar's total being `fray estimate`'s number for that map to the penny. The GUI's **Reprice** button is left for
   the cases where a stored series has stopped describing the world: the wiki rates moved, the `dps`
   extra arrived since, or the run was made under an older pricing model.

Run `fray <command> --help` for the full option list of any command, or `fray --help` for the list of
commands.

## License

MIT — see [LICENSE](LICENSE).
