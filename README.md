# chunksim

**Offline tooling for [source-chunk](https://github.com/source-chunk/chunk-picker-v2/) chunkman
maps — a command line and a browser world map over your own cached state.**

chunksim reads a map's live state from source-chunk, caches it locally, and derives things from that
cache entirely offline: which sections of the unlocked chunks are reachable, what items, monsters and
objects they give access to, which challenges are currently valid and which one is the goal per
skill, best-in-slot equipment per combat style, what a candidate chunk unlock would add, roughly how
many hours the outstanding work would take, and simulated multi-roll futures.

**It belongs to no particular account.** Point it at any map id — the `?<map-id>` part of your
chunk-picker URL — and it works the same. There is no default map, and nothing here is specific to
one player's world.

source-chunk is upstream and read-only from here — chunksim never writes back to it.

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
  cached map you can point every other command at (`chunksim tasks --map NAME`), `--runs R` to generate a
  batch of them, and `--jobs J` to control how wide it runs (it already uses every core; `--jobs 1`
  makes it serial).
- **`maps`** — list what's cached, fetched and simulated alike; `maps rm NAME` and `maps clean`
  remove them again.
- **`heuristics`** — pulls the numbers an estimate needs from the OSRS wiki and a public
  spreadsheet: quest lengths, kills per hour, XP rates, slayer assignment data, and the per-bone
  and per-altar figures Prayer is priced from. Run about as often as `chunkinfo`.
- **`estimate`** — roughly how long the outstanding work would take, in five buckets: quests, boss
  drops, monster drops, activity unlocks and skilling. Deliberately a heuristic — see below.
- **`derived`** — inspect or clean the cache of computed results (see below).

Everything after the initial `fetch`/`chunkinfo` runs offline, against the local cache.

## The map (`chunksim-gui`)

There is a second command. `chunksim-gui` starts a local server and opens a browser on an interactive
OSRS world map — the wiki's cartography render, drawn from the game's own cache, at twice the detail
of the published map and with the icons on it. It is the *whole* world: every dungeon, instance and
boss room as well as the overworld, on one grid, with a selector for which floor to draw and the
rooms named on it — Kurask Lair, Karuulm Slayer Dungeon, Grotesque Guardians' Lair. Every place the
export knows about has a square, including the ones it stores only by name. Your
unlocked chunks are bright against a greyed-out world, with a thin grid showing every chunk
boundary, and a thick border traced around the *outside* of the unlocked region — no heavy
line between two chunks you already hold. Pan by dragging, zoom with the wheel, click a chunk to
open it in the panel. Press <kbd>F</kbd> to fly the camera to whatever is under the cursor, or
<kbd>U</kbd> to unlock it — which saves a new map in Browse, and joins the pending set in Edit.
An **edited** map opens in Edit mode, since editing in place is what it is for.

**The first run sets itself up.** With nothing cached there is nothing to draw, so instead of a black
map you get a setup screen that downloads the chunk export, draws the world as soon as it lands, and
pulls the wiki data behind it. It then asks for your map id — and if you skip that, or have no map
yet, it opens a blank **untitled** map in Edit mode that you can unlock squares on and Commit. The
question is asked once; the answer lives in `cache/gui/settings.json`, so emptying the cache brings it
back. A blank map is seeded with source-chunk's own default rules rather than none, because a map with
no rules is the most permissive one there is rather than a neutral one.

```
chunksim-gui                              # serve http://127.0.0.1:8731 and open it
chunksim-gui --compare my-sim             # start in diff mode: gains green, losses red
chunksim-gui --no-browser --port 0        # bind an OS-assigned port, open nothing
chunksim-gui --no-browser --keep-alive --host 100.93.219.108   # serve it to another machine
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
and **Unlock** then saves that world as a map of its own — the same thing `chunksim unlock --cache-map`
does, named in a dialog and then opened, with its new chunk drawn green. In edit mode the same button
reads **Add to edit** instead and costs nothing until you commit. The category chips are
checkboxes, not tabs — all on to begin with, so you can look at monsters and NPCs together, or
narrow to one.

### Five modes

A coloured ribbon under the toolbar says which one you are in, with the map named on it.

**Browse** is the map as it is. **Compare** puts you in **Diff**: pick a second map and its world is
what you see — gains green, what it lost red and washed out like anything else you do not hold — with
both selectors on the ribbon so the pair is changeable without leaving, and **Breakdown** opening the
whole of `chunksim diff` in a panel (sections, tasks, sources and BiS, both directions). A floating
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

**Heatmap** is the only mode that is about a *batch* rather than a map. Pick a batch out of the map
picker and its dialog lists one row per run; once every run has been priced, **Show heatmap** paints
the world the batch was rolled from with what each square actually cost — the mean over every run
that took it, in the same five bands the timeline strip colours its bars with. The number varies
because a chunk's price depends on what was already unlocked when it landed, which is what the mean
is worth having. Clicking a square opens that spread: one row per run, the roll it landed on, the
tasks it opened, its hours, and the three longest single grinds behind them — and a run's name takes
you into that run at that roll. It is read-only, and the panel is put away for the duration, since a
square that several futures took has no one chain of unlocks behind it to describe. **Exit heatmap**
returns to the batch.

The panel covers the rest of the CLI. **Tasks** is what you are actually doing — checkbox chips per
category and a toggle for what is already done; quests show only the step you are on, and
collection-log entries read *Barrows Chests / dharok's greataxe* rather than the raw
`(Barrows Chests) Obtain a ~|dharok's greataxe|~`. Squares you can walk into without having rolled them — dungeon interiors, which the game stores in a
block north of the surface and which upstream tracks by *name* rather than by chunk id — are outlined
in dashed blue. They are reachable, not owned, so they do not count toward the number in the bar.

**Estimate** is the hours as a donut you hover for
the figure, then the same buckets again as lists of what is actually in them. **Click a row to see
the numbers it was priced off** — the kill rate, the shop price, the slayer table, a quest's length,
the training rate behind a climb — with the layer each came from, and correct any of them in place.
Rows that cannot be argued with say so instead of offering an editor: a ground spawn is priced
entirely from constants, and a Slayer climb comes off a master's whole assignment table rather than
any single entry. A number nobody has set shows what it actually resolves to rather than the word
"default", anything you have overridden is bordered and flagged with a **Revert** beside it, and the
names the wiki has a page for are links — clicking one frames its chunks exactly as **Find** does. Where the correction
is saved depends on where you are: in **Browse** it goes to `src/chunksim/heuristics/overrides.json`, which is
checked in and applies to every map; in **Timeline** or **Edit** it belongs to that map alone, in
`cache/overrides/`. Emptying the box takes the correction back out. **Find** searches the
whole world as you type, puts what you can reach first, and fits the camera around every place a
thing comes from. **Maps** lists what is cached, with the actions that make and remove it — including the two things every number rests on, the chunk export and the wiki rates, each with the date it was last fetched. Each row also carries a **Stats icon**, which opens that map's skill levels as the game's own Stats tab. The rates are scraped automatically the first time you open the GUI without them, since otherwise every hour in **Estimate** is a fallback default.


**The levels every hour is priced against are a floor, and a map can say who is playing it.** With
nothing else to go on, a skill's level is the highest one this map's *completed* challenges prove: a
ticked `Buy the Defence cape` is 99 Defence, and nothing at all proves anything about Attack, which
then reads as whatever the ledger happens to show. The Stats icon on the **Maps** tab opens the grid
of all twenty-four, each coloured by what decided it — blue for that inferred floor, yellow for a
linked account, green for a figure typed in here — and lets you **Link RSN** to pull an account's
hiscores, or set any single skill's experience by hand. **A map made from another one inherits
it** — a simulated batch, an unlocked candidate, a committed edit — since rolling two more chunks
does not change who is playing. Every run of a batch reads the batch's link, so linking an account
against a forty-run batch relinks all forty futures at once.

**No layer may lower a skill**, because a floor is a proof rather than a guess: a linked account
reading below one is a different account, a reset, or a typo, so the floor is priced instead and the
cell turns red saying both numbers. That state is not hypothetical — the reference account reads
Fishing 80 against a floor of 85 and Smithing 98 against 99, which are the exact margins of an
admiral pie and a dwarven stout. The map proves a *boosted* level, which is worth knowing about a
ledger and is now visible rather than averaged away.

A simulated run gets a **timeline**: a strip across the bottom with a slider that steps through the
rolls, redrawing the world after each one. `chunksim simulate` has always written every roll down and
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

It re-reads the cache as it goes, so a `chunksim fetch` or `chunksim simulate` in another terminal appears
in the browser a couple of seconds later. You can also drive both from the page itself. **Fetch
Named Map** takes an id rather than the map on screen — every source-chunk map is a public read, so
you can pull down one you have never cached, or a friend's. The box is required: there is no
default map, because a fetch names someone's world and guessing whose is not this tool's business.
The Maps tab carries two simulations, and they ask opposite questions.

**Roll Simulation** simulates N chunks, saves each run as a cached map and opens the result as a
comparison. The progress card counts rolls rather than runs — `47/300` on a three-run job — and
carries a stop button: stopping keeps every roll already finished, as an ordinary map you can open,
derive and step through. `chunksim maps` marks it `(stopped)` so a run that ended short is not
mistaken for one that finished.

**Next Grind Simulation** holds the opposite thing fixed. You give it a number of hours and a number
of simulations, and each simulation rolls until a chunk puts more than that many hours of new work in
front of you — so the roll count is the *answer* rather than the input. It stops early if the map runs
out of chunks to roll instead. The result is a distribution: a histogram of how many chunks the
simulations got, and under it the chunks that ended them, collated by share and by what each one cost
on average. Pressing a chunk lists every simulation that hit it, longest first; pressing one of those
opens that run's timeline at the roll that ended it, and a breadcrumb comes back.

It is the slower of the two by a long way, and for a reason worth knowing: a roll simulation prices
every roll against the state the run *ends* in, one calculation for the whole run, but a grind cannot
— it does not know where it will end until it has decided to stop, and it decides by pricing. So every
roll is derived and priced on its own, at roughly two and a half seconds each rather than two seconds
for an entire roll simulation. Forty simulations is minutes, not seconds. The runs are spread across
every core, one simulation per worker.

Those two sets of numbers are not interchangeable, and the tool will not let them be mixed: a grind
run's timeline is marked as priced roll by roll, and the **Compute hours** button that reprices a roll
simulation refuses it rather than quietly replacing a real measurement with a different one.

`?map=…&compare=…&candidates=1&sections=1&step=4&tab=estimate` reproduces a view, so a particular question
is shareable and a screenshot is reproducible.

It remembers the size and position you left the window at. Chrome will not do that for a page whose
URL changes between launches, which this one's does, so the page reports its own geometry back; the
first run opens maximised.

**Both apps say which install answered.** `chunksim` prints one line to stderr before anything
else — `chunksim 0.1.0 · installed 3h ago` — and the map carries the same thing as a faint watermark in its
bottom-left corner, read from the server rather than baked into the page. This is not decoration:
an install can be older than the checkout it came from and behave exactly as if it were not —
`pipx install` on a package whose version has not moved is a silent no-op, so a wheel install can sit
weeks behind with no symptom. An editable install cannot go stale, and says `editable, linked 3h ago`
instead: its date is the age of the link, its code is whatever the checkout holds right now. `CHUNKSIM_NO_WATERMARK=1` silences the line;
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
chunksim-gui --no-browser --keep-alive --host 100.93.219.108
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
downloaded, cached or served by `chunksim-gui` — it hands the page a URL and the page uses it. That is
deliberate: the tiles are CC BY-NC-SA 3.0 and this project is GPL-3.0, so keeping a copy would make it a
redistributor of NonCommercial artwork, while linking makes it a page with a picture on it. The
credit sits in the corner of the map, which is what that licence asks for. If the wiki ever moves
its tiles, `CHUNKSIM_TILE_VERSION` pins a render by hand.

The section masks and skill icons *are* fetched — they come from source-chunk, one file at a time as
you first look at them rather than all 1,558 up front.

**This is a genuine, but deliberately partial, reimplementation of source-chunk's own validity logic**
— not a wrapper around it. `tasks`/`unlock`/`simulate` cover 28 of the 29 challenge categories, plus
`BiS`, which upstream synthesises at runtime rather than storing and which is computed here separately.
What's left out is left out explicitly rather than silently approximated. The two gaps you're most
likely to notice:

- **Best-in-slot set effects** — the Void/Obsidian/Inquisitor/Verac's/Crystal/Karil's DPS overrides
  aren't modelled, so a set-bonus item can be under-rated against a raw-stats rival.
- **Manual choices during simulation** — chunk selection and blacklisting, and the `roll2`/`roll5`
  bonus rerolls. `chunksim simulate` rolls the way an untouched map would.

The five level gates — `QuestPointsNeeded`, `CombatPointsNeeded`, `KudosNeeded`, `TotalLevelNeeded`
and `CombatLevelNeeded` — used to be exactly this shape (unsupported for want of a running total the
export doesn't publish), and were the *only* thing that ever landed in `chunksim tasks`' `unsupported`
line. They're implemented now: quest points, Combat Achievement points and kudos are each summed from
whatever this map's own derivation says is valid, recomputed every pass the same way a `Tasks`
dependency already is, so a challenge gated on one opens the moment this map earns enough. Run
`chunksim tasks` and read the `unsupported` line on *your* map — it should read zero.

**`chunksim estimate` is a rough guide, not a projection.** The chunk-info export contains no durations,
no kill rates and no XP figures of any kind, so every number it spends comes from the OSRS wiki, a
community spreadsheet, or a default — and any of them can be wrong for you. Three things to know
before believing a total:

- **A skill is priced method by method as each one unlocks**, not at one rate for the whole climb —
  Herblore 1→99 on a real map is nine bands, from cleaning guams at level 3 up to super combats at
  90, and `chunksim estimate skilling` prints them with the level range and the XP each covers. Rates
  come from four places and each band says which: a money-making guide (225 of the export's 2,657
  training methods — most training doesn't make money, so most has no guide), the wiki's own skill
  and training-page tables (Agility, Thieving, Firemaking, Woodcutting, Hunter and part of Fishing), a per-action
  calculation from the wiki's recipe data, and for the five combat skills the damage you deal. On a real map that prices **943 of the 1,323 methods it
  can reach**; what is left sits at a deliberately low 1,000 xp/hr so it looks slow rather than free,
  and under bands that floor usually applies to the bottom of a climb rather than all of it.
  151 of the guide joins are matched by *containment* rather than exactly — usually right,
  occasionally not, and `src/chunksim/heuristics/overrides.json` is where you disagree.
- **Getting a thing costs what it costs.** An item is priced by the cheapest route this map has to
  it, and none of them are free: a shop charges its price at 500,000 gp an hour (or 25,000 Tokkul,
  or 19.5 marks of grace — all tunable) plus thirty seconds to walk there, a ground spawn is limited
  by how fast you can hop worlds to a fresh one, and performing an action costs its own time. What
  cannot be priced is *said* rather than skipped: `chunksim estimate` lists what it could not cost, and
  items sold for currencies with no agreed rate stay on that list.
- **A shop's own stock and restock timer are part of the price, not just its coin cost.** Toci's Gem
  Store sells an uncut ruby for 100 coins, but it only ever has one in stock and takes six hours to
  get another — buying in bulk means hopping to a fresh world every time, at ten seconds a hop, and a
  restock slower than an hour is refused outright rather than modelled, the same as any other mechanic
  this project cannot bound (a gem-store shelf split across two hundred worlds and the rest of the
  playerbase is exactly that). Where a better-stocked shop sells the same item — TzHaar-Hur-Rin's Ore
  and Gem Store keeps sixteen uncut sapphires on a one-minute timer — the item walk finds it instead,
  which is what a real player training on gems bought there would do too.
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
git clone git@github.com:stevenhartin/chunksim.git
cd chunksim
pip install -e ".[dev]"
```

This is an editable install: it links the `chunksim` console script to your checkout and pulls in the
`dev` extra (`pytest`), so edits take effect immediately without reinstalling.

To get `chunksim` and `chunksim-gui` on your `PATH` outside the checkout while still tracking it, install
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
make check           # compile the extensions, then mypy, then the whole suite
```

Or the pieces:

```sh
make compile         # build the mypyc extensions in place (~4.8s when unchanged)
make test            # the suite, against those extensions
make interpreted     # drop them and run pure Python instead
mypy                 # strict type checking; run from the repo root
.venv/bin/pytest     # whole test suite
```

`mypy` and `pytest` are invoked differently on purpose: `mypy` is a *system* install pointed at
`.venv/bin/python` for stubs, so it needs the repo root and an existing virtualenv, while `pytest`
comes from the `dev` extra and so isn't on `PATH` at all.

**The development loop runs compiled**, which is what the Windows installer ships and about 18%
faster per simulated roll (26% with the optional DPS calculator built the same way). A compiled
module is a `.so` that shadows the `.py` beside it *silently*, so the test suite refuses to start
while any extension is older than its source, and tells you to `make compile`. Running one test file
with a bare `.venv/bin/pytest` stays safe for that reason.

Tests that check against a real ~10MB chunkinfo export are opt-in and skipped by default. They compare
against source-chunk's own recorded answers, which makes them the suite's real correctness signal —
run them before trusting a change to the derivation modules:

```sh
make oracles         # or, spelled out:
CHUNKSIM_CHUNKINFO=cache/reference/chunkinfo.json CHUNKSIM_MAP_CACHE=1 .venv/bin/pytest
```

That is the whole setup once `chunksim chunkinfo` and `chunksim fetch` have run — the variable takes the
cached file as it is written, or a raw export if you have one. Without the variables the same tests
skip, so a fresh clone stays green.

The library is six subpackages under `src/chunksim/`: `model/` (what upstream's data is),
`remote/` (the only outbound calls), `store/` (the only disk), `derive/` (the pure layer),
`costing/` (derivation to hours) and `runs/` (a base state plus a sequence of rolls), with `cli/`
and `gui/` as the two apps on top. Tests are flat in `tests/` and named for what they cover, so
`tests/test_cli_estimate.py` goes with `cli/estimate.py`.

See `CLAUDE.md` for the module-by-module architecture and the testing conventions in full.

## Deploying

`chunksim` is a local CLI, not a service, so there's no server to deploy — "deploying" here just
means producing an installable copy on a machine that isn't your development checkout, without the
dev extras or an editable install.

**Option A — install straight from the repository:**

```sh
pip install git+https://github.com/stevenhartin/chunksim.git
```

**Option B — build a wheel and ship it:**

```sh
pip install build
python -m build             # writes dist/chunksim-<version>-py3-none-any.whl
```

Copy the resulting `.whl` to the target machine and install it there:

```sh
pip install chunksim-<version>-py3-none-any.whl
```

Either way, the target machine only needs Python 3.14+ — there's nothing else to provision.

## Usage (once `chunksim` is installed)

`chunksim` stores everything in a `cache/` directory, and where that lands depends on how you're
running it. Inside a checkout of this repository, it's the checkout — so your data sits beside the
code you're changing. Installed, it's your own data directory: `%LOCALAPPDATA%\chunksim` on Windows,
`~/Library/Application Support/chunksim` on macOS, `~/.local/share/chunksim` elsewhere. Set
`CHUNKSIM_CACHE` to put it anywhere you like.

Despite the name it isn't disposable: fetched maps re-download, but simulated batches and hand-edited
maps are your own work and nothing can recompute them.

1. **Fetch your map's live state** (replace `your-map-id` with your actual source-chunk map id —
   it's the `?<map-id>` part of your chunk-picker URL, and `--map` is required):

   ```sh
   chunksim fetch --map your-map-id
   ```

2. **Fetch the upstream reference data** (~10MB; static game-world data, not personal state, so this
   only needs repeating when source-chunk itself updates it):

   ```sh
   chunksim chunkinfo
   ```

   **You do not need to fetch the numbers `chunksim estimate` spends** - they ship with the code, in
   `src/chunksim/heuristics/`. The two commands below regenerate them and are *developer* tools: they
   reach ~200 wiki pages to answer questions that only move on a game update, and their output is
   checked in so an install never asks the wiki anything.

   ```sh
   chunksim heuristics                     # developer: guides, skill tables, monster hp, port tasks
   chunksim recipes                        # developer: xp per action, tick costs, and item renames
   ```

   The first also brings back both **port task tables** - all 432 courier deliveries between the
   game's 30 ports with the coordinates that place them, and all 163 bounties with the health of
   every sea monster. Those are what let `chunksim estimate` work out which sailing route your ports
   and your stretch of ocean make best, and which sea monster is worth hunting. See
   `costing/courier.py` and `costing/bounty.py`.

   The second is what stops most training methods being priced at a flat 1,000 xp/hour: it brings
   back what one action of a method actually pays and how long it takes, for 4,043 recipes. It now
   outranks a money-making guide where both describe the same method, because a guide is evidence
   about the action and a recipe is evidence about the action plus your map - the one exception is a
   recipe that reaches several methods at once, which fills a gap but does not overrule a guide. See
   `chunksim estimate skilling`, which prints where each band's rate came from.

   `chunksim recipes` also takes `--chunkinfo` and is the only fetch that reads an export. After the
   recipes land it asks the wiki about the item names no recipe answered to, because **the chunk
   picker's vocabulary lags the game's**: `Bronze javelin heads` was renamed to `Bronze javelin
   tips` in November 2025 and the export still says `heads`, so six Smithing methods had no rate at
   all. The renames it finds go in `cache/reference/wiki_aliases.json`. Skip the export and you get
   the recipes without the rename check, which is how this worked before.

   **You do not need to fetch anything for the gathering skills.** Fishing, Mining, Woodcutting,
   Hunter and Thieving are *modelled* rather than looked up - the success chance at your level, the
   roll interval for your best reachable axe or pickaxe, how many traps your level allows, and how
   long the node takes to come back - and the tables behind that ship with the package. So a
   willow tree is priced for the axe your map actually holds rather than for the dragon axe a
   training guide assumes, and the rate climbs as you level instead of one figure covering the whole
   climb. Bands from that model are marked `modelled`.

   Three of the five are worth knowing about specifically. **Pickpocketing is priced with its
   failures**, where the published figure has no success chance in it at all - measured over every
   pickpocket row in the export, the guide is `experience x 3600/3.5`, one cadence for a target you
   fail once in twenty and for one you fail two times in five. So the model disagrees with it in
   both directions and neither is a defect: a warrior at 94% success reads 2.3x the guide, and a
   vyre at 59% reads 0.6x. **Stalls and chests are priced at their
   restock time**, because each hands over one item and is empty until it comes back — which covers
   all forty-one the wiki tabulates rather than the handful a guide mentions. Where several sit
   together, as the three chests at the Rogues' Castle do, the wait is shared between them and the
   cost becomes the looting itself. **Every rock is priced at its own respawn** for the same reason,
   read off each rock's own wiki infobox: copper comes back in 2.4 seconds and runite in 720, a
   spread no single figure could stand for, which is why runite reads as the non-method it is rather
   than as fast iron. And **barbarian fishing
   is priced as the cascade it is** — sturgeon, then salmon on that failing, then trout on that —
   so the action is paid for all three of its rolls instead of one.

   **Where a model and a guide describe the same method, the model wins** - a
   guide figure is one number and a model is a curve, and the curve is
   evaluated at your level with your gear. That had been true of the node walk
   for a long time and was not true of the computed activities until recently,
   which cost real accuracy: an hour of Underwater Thieving reads 84,560 in the
   money-making guide and 1,005 at level 1 in the model, and the flat figure was
   winning the whole bottom half of the climb. A hand correction in
   `overrides.json` still beats both.

   A method the model cannot describe keeps its guide rate rather than being guessed at; `chunksim
   estimate skilling` marks a band `modelled` when the model priced it. Where the model does have to
   assume, it says so: every success chance it uses is tagged `confirmed` (read off the wiki),
   `inferred` (built from a measurement of the same kind of thing, as the uncharted butterflies borrow
   a charted one) or `guess` (a round conservative number so the method has one at all). There are
   three guesses, all pitfall cats. Where the wiki charts nothing but publishes
   hourly figures against level, the chance is **recovered from those figures**
   rather than guessed - rubium and calcified rocks are priced that way, and
   both reproduce every published row within 1.25x. Three rocks nobody charted
   at all (lovakite, nickel, daeyalt) are interpolated from the charted ores
   either side, which reproduces every charted ore held out of its own
   prediction at a geometric mean of 1.03x. Crashed stars need none of that -
   the wiki charts them and states an outcome for the whole loop, and the model
   lands on 30,212/hr against a published 30,000. A handful of methods are
   priced from prose alone, where the wiki states the mechanic rather than
   charting it: an essence rock and a soil spot never fail, a soil spot is dug
   every four ticks whatever you hold, an amalgamation averages 2.5, and the
   three Ghorrock salts never fail but run out on a flat 1/7 chance per mine,
   and the salt deposit under Duke Sucellus never runs out at all - 5 experience
   every 2.83 ticks, which is 10,601/hr against a reported 10,600 with nothing
   fitted. A rubium geode pays one of eleven equally-likely figures and the
   wiki averages them for you: exactly 40, and infernal shale's ten values
   weight out to 42.73.

   **Tick manipulation is deliberately not modelled**, so a method whose only
   published figure assumes it is priced as ordinary play instead. Granite is
   quoted at 87,000/hr for 3-tick mining and infernal shale rocks at 40-60k
   with Jim's wet cloth; both are priced here for the swing a player actually
   makes, and the technique is simply absent rather than folded into a success
   chance. The bloodwood tree is the same call made between two *objects*
   rather than two techniques: the standard tree is "a two tick cycle" of
   "clicking multiple times a tick" across three trees at once for ~210,000/hr,
   and the engorged tree beside it is the "lower-intensity alternative more
   similar to traditional woodcutting" at 65,000-70,000. One task covers both,
   so it is priced at the one you can play.

   And where a method is priced by how far you *run* rather than how fast you
   swing, that is modelled too: sixteen ash piles scattered over a volcano
   never fail, yield four each and respawn in thirty seconds, none of which
   binds - so what the rate measures is six and a half seconds of running per
   pile. The blisterwood tree is the opposite case and its page states both
   halves: it never goes away (`time = 0 seconds`) but has a flat 1/10 chance
   of stopping you with every log, so the only downtime is the tick it takes
   to click it again. Charged like an ordinary tree - one that falls, and a
   walk to the next - it read 48,122/hr against a published 85,000; charged
   for what actually happens it reads 81,780, and 4 ticks at the charted 73%
   puts the ceiling at 83,273 whatever you do.

   **Cutting jungle is the one activity that speeds up with your level rather
   than with what you hold**, and it is modelled from the sentence that says
   so: 16 ticks a swing at level 10, one tick less every ten levels, eight from
   90 on. The machete is still the chance - four charted series of it - and the
   patch is four sections before it depletes and 90 seconds before it comes
   back. Light jungle runs 2,859/hr at level 10 to 10,240 from 90, where the
   respawn stops the swinging being what you wait for. Nothing publishes an
   hourly figure for jungle, so there is no row to check that against; every
   input is a sentence off the page instead.

   The Kharidian cactus is the smallest thing the model prices and worth
   reading as a shape rather than a number: one series, "no way to increase the
   chance of success", 10 experience, and a minute before the cactus is healthy
   again. The chance climbs from 12% to 99% across the whole skill and the rate
   does not move, because the minute is what you wait for either way - a flat
   1,200/hr, which says "this is a way to fill a waterskin" without having to
   be told.

   **The juniper tree is the one assumption left in Woodcutting**, and it is
   the shape of assumption this project prefers: everything else about it is
   read. Its page states the four-tick roll, the 1-in-16 chance of depleting
   and the eight-second respawn, and then says only that it has "a very low
   cut difficulty" - prose, with no numbers behind it. So it spends the maple
   tree's chart, which opens three levels away, and reports `inferred` for it.
   That is deliberately a floor rather than a match: the same sentence says
   players at a high level "likely max out the chance", where maple reaches
   37% with a dragon axe, and the difference between those two readings is
   19,277/hr against 52,500. Nothing published chooses between them, so it
   takes the low one.

   **Tempoross is priced by which harpoon you hold and at what level**, from
   the wiki's own table of four harpoons at five levels each. It replaced three
   invented figures - one per harpoon tier, flat across the whole climb - that
   were wrong in both directions: a plain harpoon at level 35 is 30,000 an hour
   rather than 80,000, and a crystal and an infernal harpoon are 95,000 and
   76,000 rather than one number for both. The best harpoon is chosen by *rate*
   rather than by tier, because the tiers are not ordered, and it is re-chosen
   at every band for the reason an axe is: a map holding a crystal harpoon
   swings a plain one until 71.

   **Stealing artefacts is the one activity here that derives completely.**
   Both halves of what an artefact pays are stated in prose - 750 experience
   for picking the lock, and "40 times the current Thieving level" for
   delivering it - and the page tabulates how long a run takes from each of
   the six houses, which averages to 75 seconds and so 48 an hour, against its
   own "approximately 48". Multiplying the two reproduces the wiki's published
   experience table at **all eleven of its levels with no residual**: 130,080
   at 49 and 226,080 at 99, to the coin. The mean of the six houses matters
   rather than the quickest, because you are told which house to rob - taking
   the best would read 60 an hour and miss the column by a quarter.

   **Stealing valuables is a transcription and the estimator says so**: none
   of the burgling loop is charted, so there is no curve to build a rate out
   of, and what the wiki publishes instead is the answer as a level-to-rate
   table. It is carried because the same page states the activity four other
   ways and all four agree - 45 experience a valuable against "about
   1,600-2,300 valuables" an hour, a 180-190 second house cycle against "18-19
   houses per hour", one key a house against "around 3900xp at level 50 and
   5700xp at level 99", and a prose range whose ends are the table's own. Four
   measurements of one activity that happen to agree is the most a
   transcription can offer. Note that these figures are the burgling
   "exclusively", and getting the keys means pickpocketing wealthy citizens,
   which is priced separately - the same hour, so the two are alternatives
   rather than a total.

   **An Agility course is a lap and a lap time**, and their product is the
   guide's own figure - within 5.2% on thirteen of the eighteen,
   and within 1% on eight. `Rooftop Agility Courses` tabulates
   all nine rooftop courses together - obstacles, experience per lap and lap
   time in ticks - and the other four state the same two things on their own
   pages. That the numbers barely move is the point: the Agility scrape was
   checked first and found accurate, so what the model buys is that a rate is
   now two facts about the game multiplied rather than somebody's estimate,
   which can be followed through a game update instead of waited on. **The
   base rate is priced and not the diary one**, which the guide quotes for
   three of the courses: a hard Achievement Diary wants tasks all over its
   region, which is exactly what a chunk-restricted map does not have. Three
   courses publish a **minimum** lap rather than an average - Gnome Stronghold
   and both Shayzien courses - and this prices the minimum, because their own
   pages show the two figures to be the same lap run less carefully rather
   than two measurements. The Shayzien advanced course is the one carried as
   two bands: its own page says players "stop failing the obstacles ... at
   around level 64", so its 30,000 is an average over the stretch where you
   fail and its 39,545 is what the lap gives once you stop. **The two Colossal Wyrm
   courses are the case for doing any of this.** They looked like an
   irreconcilable 1.7x disagreement, and the cause turned out to be a
   rebalance on 12 August 2026 that lengthened both laps and raised their
   experience - after which `wiki:courses` still carried the old figure, and
   carried it for *both* courses. The page reconciles once the current numbers
   are read: 31,916 an hour on the basic course and 43,900 on the advanced,
   against one scraped 44,000 that was the basic course's *pre-buff* rate. The
   basic course had been priced 1.38x too fast, and a guide can be right about
   a course that no longer exists in a way a lap and a lap time cannot.

   **The Agility Pyramid shows what a bad join costs.** Its money-making rate
   of 34,380 an hour reached all three of the export's pyramid challenges, and
   one of those opens at Agility **1** where the pyramid itself needs 30 - so a
   rate for a course you cannot enter won every level from 1 to 50, against
   real courses paying 10,000. The page also scales it with level, because you
   fail obstacles until you stop: 25,000 at 55, 33,000 at 67, 42,100 at 75 and
   44,700 from 88. Nothing is offered below 55, and that is the wiki's own
   limit rather than a gap - it says outright that the fail rates for lower
   levels are not known, and inventing a curve for them would be the opposite
   of what everything else here does.

   **The Hallowed Sepulchre is five floors and the guide priced them as one.**
   Its five `Access the Nth floor` challenges open at Agility 52, 62, 72, 77
   and 87 - which is the wiki's own level column exactly - and every one of
   them was reading 58,425 an hour, where the published table runs 40,000 on
   the first floor to 98,500 on the fifth. So the flat figure was half again
   too fast at the bottom and two thirds too slow at the top, and the second
   is the expensive half: the fifth floor is the fastest Agility in the game
   from level 87, and a rate a third too low kept it out of the climb
   altogether. Priced per floor, an Agility climb falls from 183.6 hours to
   140.6.

   **The Sorceress's Garden is the simplest thing here**, and the one place a
   published lap time and a published hourly yield check each other. Each
   garden page states how long a lap takes and how much juice an hour it
   yields, and the two agree through a mechanic neither states: one sq'irk a
   lap, and five, four, three or two sq'irks to a juice as the gardens get
   deeper. So autumn has the slowest lap of the four and pays five times
   winter. A level buys a *better garden* rather than a faster lap or a better
   chance, which is why nothing in these rates reads one: 11,900, 33,750,
   56,400 and 150,000 an hour. Two of the four pages check their own
   arithmetic - spring's "about 28,350 xp/h" and summer's "maximum experience
   possible per hour is 150,000" - and both come out.

   **Underwater Agility and Thieving is priced as a parabola**, because almost
   none of its experience is earned where it is paid: you collect glistening
   tears and hand them to Mairin for experience that scales with the *square*
   of your level. One coefficient per skill reproduces every row of the wiki's
   own table - `0.027 x level^2` for Agility alone and `0.099` for Thieving -
   and 220 tears an hour turns those into all four of the hourly figures the
   page quotes at 99, every one within 0.03%. What is priced is the
   **both-skills** exchange rather than the faster single-skill one, and not
   because it is quicker: it is the only mode where an hour credited to
   Agility is the same hour credited to Thieving, and pricing the other would
   let one hour be spent in two columns.

   **Pyramid Plunder is priced from what one five-minute game holds**, because
   the wiki publishes all of it: experience per urn, chest and door for each of
   the eight rooms, thirteen urns a room (twelve in the third), four doors with
   one way onward, ten experience for the spear trap, and success charts for
   the urn, the chest, the door and the sarcophagus. The strategy priced is the
   wiki's own - chests from room 4, and every urn in the last two rooms. Two
   things are not published and neither needed guessing at: the seconds per
   action turn out not to matter, since the plan wants 4.2 seconds each and
   anything quicker finishes it, so the answer is flat over the whole plausible
   range; and the time between games is the one fitted number, taken from two
   published rows that agree within 2% and checked against a third. It reads
   1.00x, 1.00x and 0.96x against those three, and covers rooms 1 to 5 that no
   guide prices at all. The sarcophagi pay **Strength** rather than Thieving,
   on a chart that gets harder the deeper you go - and the two rates cannot
   both be had, because the Thieving route skips them.

   **What a Motherlode Mine ore costs is a cascade**, and getting it wrong was
   worth an order of magnitude. The export carries `Obtain ~|runite ore|~ from
   pay-dirt` with `Output: Runite ore` and no stated pace, so the item walk
   priced it at the four-tick default - it believed pay-dirt handed over
   runite ore every 3.5 seconds, which made a runite bar *cheaper* than an
   adamantite one. `Pay-dirt` publishes both halves of the real answer: a
   success chart for mining one, and a second chart with `cascade=yes` for
   what it turns out to be. The cascade is Mod Ash's own description - "pay-
   dirt rolls for each ore in descending order, starting from the top tier
   you're eligible to get" - so an ore's chance is its own roll times the
   chance every richer one failed, and coal's series is always true, which
   makes it the remainder. It reproduces the published shares at 99 on five of
   six and sums to exactly 100%; the sixth is the page disagreeing with itself,
   where its chart says 18.85% for adamantite and a sentence beside it says
   18.18%. A runite ore goes from 3.5 seconds to 241, and the walk stops
   preferring pay-dirt to simply mining the rock. **The Blast Mine is the same
   defect in a second activity**, and it was the answer to "what shop sells
   runite ore?" - none did, `Obtain ~|runite ore|~ from blasted ore` did, at
   the same four-tick default. Its page publishes an ore distribution, 330
   blasts an hour (confirmed twice, since lighting the dynamite pays 50
   Firemaking and it quotes 16,500 an hour) and an experience figure at level
   70 that turns the rest into a count of ores. The answer there is a number
   rather than a refusal, because the Blast Mine genuinely is the best runite
   in the game: 91 seconds an ore against 240 for mining the rock. It was out
   by a factor of fourteen, not wrong to prefer it.

   **A monster named beside a different output is a kill, not an action.**
   `Cut magic logs from an ~|ent|~` names the ent and outputs magic logs, so
   the item walk priced a magic log at 3.6 seconds - the same 3.6 as an oak
   log, because the four-tick default knows nothing about either - against
   25.6 for chopping one. An ent is a Forestry event. The walk already refused
   kills on the other side of that test, for the stated reason that "a kill
   has a route of its own", and now does here too. Fletching 1-99 goes 41.3
   hours to 84.4 on the back of it, because Vale Totems had been fed magic
   logs at an oak log's price.

   **The Giants' Foundry is priced from an alloy, not from a tier**, which is
   the whole of Smithing's climb above level 15. A preform is 28 bars in
   whatever ratio you choose between two metals, and the strategy guide
   tabulates all fifteen pairs against all 27 splits; that gives a metal
   score, the mould adds a stated 59, and the main page's closed formula
   `(floor(q^2/73) + floor(1.5q) + 1) x 30` turns the total into experience -
   so mithril and adamant at 14 each is 59 + 95 = 154 quality and 16,680 a
   sword. The score also sets the difficulty, and so the time: six sections at
   45 seconds plus a 30-second hand-in is 300 seconds, twelve swords an hour,
   200,160 experience. **The tier summary in the release patch notes cannot
   express the actual choice**: bronze with rune scores 60 against bronze with
   adamant's 50 and is *slower*, because 60 crosses into a fifth section. Note
   what the estimator then does to any of these: a preform eats bars, so the
   walk charges the time to get them and 200,160 an hour becomes 44,823. That is the same layering that makes `Smelt a ~|gold bar|~` read
   about 14,000 where the wiki's own comparison says gold at the Blast Furnace
   is 375,000 - the guide quotes a method with its bars to hand, and this
   charges you for getting them, which on a chunk-restricted map is usually
   the truthful half.

   **Wintertodt is the one activity here with no chance in it at all.** The
   wiki states its experience as multipliers on your level - 0.3x to cut a
   bruma root, 0.6x to fletch it, 3.8x to burn the kindling, and 100x for
   subduing with 500+ points - so a rate is those times a count of games
   rather than anything modelled. The regime priced is the world-hopped one:
   twenty kindling is exactly the 500 points the reward caps at, so you earn
   it and leave rather than spend a longer game on the same bonus. Twenty-four
   games an hour pays 14,256 Woodcutting, 28,512 Fletching and 418,176
   Firemaking at 99. It replaced a hand-written 400,000/hr, which was one
   number for a rate that is linear in the level - close at the top and half
   wrong at 50, where Firemaking opens the boss.

   **A Chambers sapling is the one action whose *payout* climbs with the
   level**, rather than its speed or its odds - it hands over more kindling
   the higher you are, and pays 30 experience a chop at level 1 against 58.2
   at 96. Two twitter citations on the wiki give the whole of it: the yield is
   "a random number 0-max inclusive ... If it rolls 0, it treats it as 1" with
   the max being your level over twelve, and a chop for `k` kindling pays
   `30 * H_k`. That formula reproduces the wiki's published table exactly at
   six of eight rows, shows the last two to be its own rounding, and catches a
   typo in a seventh - its avg-kindling column says 2.2667 at level 60 where
   the distribution gives 2.6667, which the wiki's own experience figure on
   that row confirms. So the table here is computed rather than copied. It
   comes out as the best method in the game up to level 14 and behind every
   real tree by 99, which is what a sapling should be.

   A few methods are not training methods and the estimator says so rather
   than offering a bad number. Mining has five: mining an elemental rock pays
   nothing (it spawns the monster whose drop is the ore), lunar ore's own
   infobox states zero, a Motherlode rockfall is an obstacle in front of the
   vein beside it, and panning falls below the 1,000/hr floor anything would
   be quoted at. Woodcutting has three: two outfits, which are a bonus on
   whatever you were already chopping rather than an action you repeat, and
   the swaying tree, which is one object worth one experience. **Refusing
   these by name is the point** - an absent rate reads as a gap somebody
   should go and close, and a refusal reads as the decision it is, which is
   why `chunksim training` files them under `refused` rather than `unpriced`
   and prints the sentence that settled each.
   Sunstone's curve comes from a sentence rather than a chart - "scaling from
   75% success rate at level 50 to a 100% success rate at level 92" - and two
   points fix the game's own interpolation exactly. The infected root is the case
   where a page states the whole loop *and* then checks it: a four-tick roll,
   a charted cut chance, 10 experience for a demon tear at 15/17 and 25 for a
   log at 2/17, and roots that "don't deplete". Those price it at 12,960/hr at
   99 with a dragon axe, which reads 42% over a headline of "rates *up to*
   ... ~9,100 experience per hour" until you reach the worked example further
   down the same page - "a single click will yield an average of 202.5 demon
   tears and 2,700 Woodcutting experience before the inventory is filled with
   27 logs". Twenty-seven logs at 2/17 is 229.5 cuts, which is 202.5 tears and
   2,700 experience exactly, and 750 seconds of chopping: 12,960 an hour. The
   two figures are one activity on different clocks, and this project prices
   the loop rather than the trips between them, here as everywhere.

   Where a method is not a training method the model says so rather than
   omitting it - a Motherlode rockfall is an obstacle in front of the ore vein
   beside it, and it is refused by name.

   **The same tables charge a production skill for what it burns or fletches.** A published rate is
   quoted with the materials to hand — "394,778 an hour burning magic logs" describes the burning,
   not the tree — which on a chunk map is most of the cost. So a method is priced on what it pays
   *and* on the time to obtain what it consumes. Both figures are kept: every band carries
   `published_xp_per_hour` beside the rate it was costed at, which `--export-json` writes out and the
   GUI's Estimate tab shows. On the reference map this takes Fletching 1→99 from 30.0 to 244.9 hours,
   and Firemaking from 35.2 to 81.3.

   Rebuilding those tables is a developer job and needs the checkout:

   ```sh
   chunksim gather-tables                  # ~15 requests -> src/chunksim/heuristics/gathering.json
   ```

3. **Look at what you've got:**

   ```sh
   chunksim show
   ```

   Counts of unlocked chunks, active tasks and enabled rules. It also prints a `slayer locked` line
   *when there is one* — the map records the Slayer task you are stuck on and the level it holds you
   at, and that quietly caps every Slayer requirement in every other answer this tool gives.

4. **Derive things offline**, no network required from here on:

   ```sh
   chunksim sections                       # reachable sections of your unlocked chunks
   chunksim sources                        # items/objects/monsters/npcs/shops available to you
   chunksim tasks                          # which challenges are currently valid
   chunksim tasks Woodcutting              # your current goal for one skill, and what it supersedes
   chunksim tasks Diary                    # outstanding diary tasks, grouped by diary and tier
   chunksim tasks BiS                      # best-in-slot equipment: still to get, already got, outdated
   chunksim search "abyssal whip"          # where in the world would I get this?
   chunksim unlock --chunk 12082           # what unlocking chunk 12082 would add
   chunksim diff --map1 A --map2 B     # what's different between two cached maps, both ways
   chunksim estimate                       # roughly how long the outstanding work would take
   chunksim estimate skilling              # ... and which training method each skill would use
   chunksim training --map fray            # the best method each skill can reach on that map
   chunksim training Agility --map fray    # every Agility method it can reach, best first
   chunksim training                       # every method in the export, counted by what priced it
   chunksim neighbours                     # which chunks I could unlock next, and their roll numbers
   chunksim simulate --rolls 20 --seed 1   # simulate 20 rolls; --seed makes it reproducible
   ```

   **`chunksim training` is the one command where omitting `--map` asks a different question**
   rather than defaulting one: with a map it is about that world's methods, without it is about the
   *export* - how many of its 2,707 primary training methods are modelled here, how many are
   somebody else's published figure, how many are a guess, how many nothing has priced at all,
   how many are **refused** (this project declined to quote a number and the row says why -
   an impling nothing publishes a rate for, a fishing spot whose own page disclaims it),
   how many are a **one-off** (a decoration upstream files as training that nobody trains with -
   the trophy mounts and boat cosmetics), and how many are **uncompletable** - which the report
   then breaks down by *what* the world lacks. That last category is upstream's own gates rather than a gap here, and it is worth
   its own column for the reason the breakdown exists: a method behind a rule you switched off,
   or wanting a Leagues reward that no longer exists, is not a number waiting to be improved,
   while one blocked by nothing the report can name is worth chasing.
   That report still needs a world to price against, so it builds one holding every rollable chunk
   and borrows a cached map's rules (`--rules-from MAP`), because a rule is a player's choice and
   the export has no permissive defaults to fall back on. **Pass `--rules-from` whenever more than
   one map is cached**: with no rules at all every rule-gated method reads as `uncompletable`
   instead, which is not a smaller version of the real answer but a different and much emptier
   one - the report says so in a warning line, and the counts underneath it are not worth reading.
   What it does **not** borrow is that map's *closures*: a section or area the player sealed by
   hand is dropped, since the ceiling asks whether anybody could ever do a thing and a shut door
   is one player's choice. The openings are kept, because those reach places nothing else does.

   **`--show-category STATUS` turns any of those counts back into its list**, which is the
   follow-up the table always provokes:

   ```bash
   chunksim training --rules-from fray --show-category unpriced Construction  # that skill's
   chunksim training --rules-from fray --show-category unpriced --limit 3     # every skill's
   ```

   Both the status and the skill are matched case-insensitively against the names the table
   prints (so `guessed` reaches `guess` and `construction` reaches `Construction`), and a name
   that matches nothing lists the valid values rather than printing an empty section.

   An `unpriced` row names the ingredient it wanted where it joined a recipe and lost one
   (`needs Granite (5kg)`); a blank there means no recipe joined at all, so there is nothing
   to name. A `refused` row is the other half of that question - the absence is deliberate,
   and the sentence beside it says whose call it was and on what grounds.

   `sections`, `sources`, `tasks` and `diff` print counts by default and take an optional positional
   to list one branch's contents in full; `--limit N` caps that.

   Add `--export-json -` (to print JSON to stdout, for piping into `jq` or similar) or
   `--export-json PATH` (to write it to a file) to `sections`, `sources`, `tasks`, `search`, `unlock`,
   `diff`, `estimate`, `neighbours` or `simulate` for the full structured result behind the
   human-readable summary.

   If you'd rather point at a chunk-info export you already have on disk instead of fetching it,
   pass `--chunkinfo PATH` to any of those commands, or set the `CHUNKSIM_CHUNKINFO` environment variable.

   Working out what's valid takes about a second, so the answer is cached under `cache/derived/` and
   reused until something it depended on changes — your map, the chunk-info export, or the chunks
   you asked about. A repeat command takes about a tenth of a second, and because the cache is keyed
   on those inputs rather than on the command, `chunksim sections` reuses what `chunksim tasks` just worked
   out. Nothing needs invalidating by hand: a `chunksim fetch` simply produces a different answer to
   "what did this depend on". Pass `--recompute` to any of those commands to ignore the cache and
   redo the work, `chunksim derived` to see what's stored, and `chunksim derived clean` to drop entries you
   haven't used in a fortnight (`--all` for the lot). Deleting them only ever costs recomputation.

   The same cache holds the other slow thing, if you have the `dps` extra: recomputing every kill
   rate from your map's own gear takes about two thirds of a second, and dwarfs the estimate it
   feeds — so that gets stored too, and `chunksim estimate` drops from 1.7s to 0.2s on a repeat. It is
   keyed on the rates, your `src/chunksim/heuristics/overrides.json` *and* the calculator's own source, so
   editing an override or upgrading `osrs-dps` recomputes rather than quietly serving you the old
   number.

   A simulation derives a state per roll, and by default all of them are kept — so re-running a
   seeded batch takes about a quarter of a second instead of eight, at roughly 118 KiB per state.
   `chunksim simulate --cache-behaviour extremities` keeps only the state each run starts from and the
   one it ends on (that last one being what the saved simulated map holds, so reading the map back is
   immediate), and `--cache-behaviour none` keeps nothing at all.

5. **Keep a possible future and work against it**, instead of just reading the summary:

   ```sh
   chunksim simulate --rolls 50 --cache-map Future            # saved as cache/maps/simulated/Future/run-001
   chunksim unlock --chunk 12082 --cache-map Candidate        # the same, for one chosen chunk
   chunksim tasks --map Future                                # the same commands, against that world
   chunksim diff --map1 Candidate --map2 Future               # ... or against each other
   chunksim simulate --rolls 50 --cache-map Sweep --runs 100    # a batch, as wide as the machine
   chunksim maps                                              # what's cached, fetched and simulated
   chunksim maps rm Sweep                                     # ... and remove one again
   chunksim maps clean                                        # remove every simulated map
   ```

   `unlock --cache-map` saves into the same place a simulation does, so everything below applies to
   it too — it's just a one-run batch whose single "roll" you chose rather than rolled.

   A batch writes one directory per run, addressable as `--map Sweep/run-007`; a bare `--map Sweep`
   works whenever the batch holds exactly one run. Each run records the seed it used, so any single
   run can be reproduced on its own with `chunksim simulate --seed <that>`. `cache/maps/simulated/<name>/batch.json`
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
   bar's total being `chunksim estimate`'s number for that map to the penny. The GUI's **Reprice** button is left for
   the cases where a stored series has stopped describing the world: the wiki rates moved, the `dps`
   extra arrived since, or the run was made under an older pricing model.

Run `chunksim <command> --help` for the full option list of any command, or `chunksim --help` for the list of
commands.

## Updates

The GUI checks GitHub once a day for a newer release and says so on the version line in the corner;
clicking it offers the release notes, and on Windows a **Download & Install** that fetches the
installer, checks it against the checksum published with the release, and hands over to it. Nothing
is downloaded or run without you pressing that button, and an asset with no published checksum is
refused rather than trusted to HTTPS alone.

Every failure is silent. No network, no releases, a version neither side can parse — the line just
says what it always said. Turn the check off entirely with `update_check` in settings.

## License

GNU GPL v3.0 or later — see [LICENSE](LICENSE).

It was MIT until the optional [`osrs-dps`](https://github.com/stevenhartin/osrs-dps) extra needed to
ship in the same distribution. That library is GPL-3.0, so a combined work has to be, and matching it
was the simpler half of the choice. Versions released before the change stay MIT; nothing takes that
back.

## Credits

The world map is the OSRS Wiki's own cartography, loaded live from its CDN and never cached by this
project — see `gui/routes_reference.py`'s `_tile_source` for why. Section masks, skill icons and
the Windows installer's icon (a limpwurt root, cropped from the
[wiki's own item-detail render](https://oldschool.runescape.wiki/w/Limpwurt_root)) are the OSRS
Wiki's [CC BY-NC-SA 3.0](https://creativecommons.org/licenses/by-nc-sa/3.0/) media, used under that
license — non-commercial, attributed here, and any redistributed derivative (the installer icon
among them) carries the same terms.
