# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

fray-claude is a CLI that reads state from the source-chunk web app, caches it locally, and runs
offline operations on that cache. source-chunk is upstream and read-only from here.

Landed: derive reachable sections/available sources/valid tasks from a cached map, per-chunk unlock
deltas, multi-roll simulation (`fray unlock`/`fray simulate`), category listings, world-wide fuzzy
search (`fray search`), best-in-slot equipment synthesis (`bis.py`, surfaced via `fray tasks BiS`
and as upgrade deltas in `fray unlock`/`fray simulate`), and active/obsolete/completed task
classification per skill (`active_tasks.py`, surfaced via `fray tasks <Skill>`), and the non-skill
categories Diary/Quest/Other (`other_tasks.py`, surfaced via `fray tasks Diary|Quest|Other`) — see
`challenges.py`'s, `bis.py`'s, `active_tasks.py`'s and `other_tasks.py`'s docstrings for what's
deliberately unsupported before trusting the numbers.
Planned: render a world-map image for a simulated state, generate heatmaps of likely rolls over N
attempts, estimate time to complete all goals (needs a task-duration source; the export has none).

## source-chunk

- Source: https://github.com/source-chunk/chunk-picker-v2/
- Live instance, the only one that matters: https://source-chunk.github.io/chunk-picker-v2/?fray

It imposes an artificial rule set on Old School RuneScape by adding barriers to the world: it holds
the set of chosen chunks, tracks goals for the active chunk, and randomly selects the next chunk to
unlock from the allowed neighbours. Reproducing that selection and the neighbour-eligibility rules is
the core of this tool — read the upstream source for them rather than inferring from observed output.

`?fray` is a map ID, not page state — the real backend is a public Firebase Realtime Database, read
with a plain unauthenticated GET: `https://chunkpicker.firebaseio.com/maps/<map_id>.json`. Chunk
adjacency/neighbour data isn't there; it's `chunkpicker-chunkinfo-export.json` in the upstream repo,
served from the **`gh-pages`** branch — that's upstream's default branch; `main` 404s.

**Chunk** — a fixed square block of tiles; the unit source-chunk unlocks.
**Tile** — the smallest interactable square; the avatar occupies one at a time.
**Section** — a chunk may be split into numbered sub-areas (`chunkinfo.json`'s `sections`); a chunk
being unlocked only makes section `0` reachable, not the rest — see `sections.py`.

Top-level keys of a map payload, for reference while `cache/` is empty: `activeSubTabs`,
`chunkOrder`, `chunkinfo`, `chunks`, `manualPrimary`, `recentFancyRollTime`, `recentLoginTime`,
`rules`, `settings`, `topbarSelection`, `uid`. `chunkOrder` is a partial log with repeating
timestamps — fewer entries than there are unlocked chunks — not an authoritative unlock order.

Map payload strings and object keys are selectively passed through a reversible Firebase-safe
encoding before being written (`.`/`#`/`/`/`'`/`,`/`+`/`!` become sentinel tokens, `%` becomes `-_-`,
purely-numeric keys gain a `*fb*_` prefix, and some fields intern task names to `t_N` ids via
upstream's `tasksMap.json`) — applied per-field by the app, not uniformly across the whole payload,
so which branches need `firebase.decode_payload` is only knowable by checking real fetched data, not
by inspecting the client source. `chunks.unlocked` and `chunkOrder` are stored plain; `chunkinfo`'s
`manualSections`/`stickeredNotes`/`activeTasks`/`completedChallenges`/`checkedChallenges`/`backlog`/
`manualTasks` are encoded. `activeTasks`/`completedChallenges`/`checkedChallenges`/`backlog` key
their entries by `t_N` task id, but **a single category can mix ids and literal encoded names**:
`tasksMap.json` interns names lazily (note its `currentNextIndex` counter), so a name that has never
been interned is stored literally instead. Real data had `completedChallenges.BiS` at 65 ids to 5
literals and `completedChallenges.Extra` at 277 to 1, every literal confirmed absent from
`tasksMap.json`. **Do not assume a category is literal-only from a small sample** — literal keys sort
before `t_N` ones (`'O' < 't'`), which is exactly how an early sample of `BiS` looked literal-only and
produced a real bug (see `firebase.decode_challenge_keyed`). `manualTasks` genuinely *is* literal
throughout, verified the opposite way: its names *are* in `tasksMap.json` yet are still stored by name.
`firebase.decode_challenge_keyed` handles both forms.

## Architecture

One responsibility per module, so the planned simulation work has a pure layer to build on:

- `api.py` — the only module that touches the network; raises `FetchError`. An unknown map comes back
  as HTTP 200 with a bare `null` rather than a 404, so that is the only "no such map" signal.
- `cache.py` — the only module that touches disk; raises `CacheMissError`. Stores the payload in an
  envelope (`map_id`/`fetched_at`/`source`/`data`), so readers go through the `data` key. Finds
  `cache/` by walking up to the nearest `pyproject.toml`, letting the CLI run from any subdirectory.
  Non-map blobs (the chunkinfo export, tasks map) go through the generic `write_blob`/`read_blob`
  pair instead; `read_chunkinfo` layers an override (`--chunkinfo` / `FRAY_CHUNKINFO` env var) in
  front of the cached copy, for working from an existing local export.
- `firebase.py` — pure; the Firebase-safe string codec (`decode_string`, `decode_key`, `decode_value`,
  `decode_payload`). Port of `decodeQueryParam`/`decodeObject` from upstream's `index.js`; run any map
  payload branch through this before treating it as real chunk ids, rule names, or task text.
  `decode_challenge_keyed` handles the `{category: {t_N_or_literal_key: value}}` shape shared by
  `activeTasks`/`completedChallenges`/`checkedChallenges`/`backlog`/`manualTasks`. It resolves `t_N`
  ids for every category (`decode_key`'s `'t_' in key` test can't false-positive on an encoded name —
  the encoding only emits `_` inside a `-_-` triple, so `_` is always preceded by `-`), with
  `skip_task_ids=True` only for `manualTasks`. Per the encoding note above, categories mix both key
  forms; special-casing one as literal-only is exactly the bug this function's docstring warns about.
- `chunkinfo.py` — pure; typed, tolerant accessors (`ChunkInfo`) over the parsed chunkinfo export.
  Parsing the ~7MB export is the expensive part, not attribute access, so build one `ChunkInfo` per
  command invocation and pass it down rather than re-parsing.
- `sections.py` — pure; which sections of the unlocked chunks are reachable (`unlocked_sections`), a
  fixed point over `chunkinfo.json`'s `sections`/`chunks` connectivity, **plus named-area unlocking**.
  Port of `findConnectedSections` and `getAllChunkAreas`. That function's *auto-add* branch is upstream
  dead code (a filter predicate with no `return`, always falsy) so only `manualAreas` adds chunks there
  (`expand_chunk_areas`), but its other output is live and ported as `area_connections`: upstream's
  `areasStructure` (named area -> connecting chunks), whose key set is `possibleAreas`. A named area is
  stored twice in the export — as the numbered entrance chunk carrying `Connect`/`Name` (`6727` ->
  `Grotesque Guardians' Lair`) and under the area's *name* as a top-level `chunks` key holding its
  contents — so adding the name to the unlocked set is what exposes its monsters/drops to
  `gather_chunks_info`. `unlockable_areas` ports the pass that decides when (worker.js:2102-2155): a
  currently-*valid* `Nonskill` challenge carrying `UnlocksArea` unlocks the area it names, subject to
  its `SkillsNeeded` gate and the area connecting to a chunk you already hold. Missing this was a real
  reported bug — `Spiritual mage`/`Grotesque Guardians` (hence `Dragon boots`/`Granite gloves`) were
  invisible, and the BiS oracle sat at 1/6. `sectionsLimits` deliberately isn't used here: it gates
  *rollable-neighbour* eligibility, not the connectivity of chunks already unlocked, so it belongs with
  `simulate.py` instead.
- `rates.py` — pure; OSRS drop-rate string parsing/formatting (`parse_ratio`, `find_fraction`,
  `looks_non_numeric`). Centralises what upstream re-parses inline at every use site; `find_fraction`'s
  output string is embedded verbatim in synthesized task names (stage 3), so its half-away-from-zero
  rounding and no-trailing-zero formatting deliberately match JS's `Math.round`/`Number.toString`
  rather than Python's.
- `sources.py` — pure; what the unlocked chunks make available (`gather_chunks_info` ->
  `SourceIndex`: items/objects/monsters/npcs/shops). Port of `gatherChunksInfo`, including the
  drop-rate threshold (`Rare Drop Amount`) and primary/secondary classification (`Secondary Primary
  Amount`) that decide whether/how an item appears — both feed ordinary challenge validity, unlike
  the quantity-keyed `dropTablesGlobal` side table (upstream's `calcedQuantity`), which only the
  dynamic "Every Drop"/"All Droptables" challenge synthesis in `calcChallengesWork` consumes and so
  belongs with `challenges.py` instead. The `KeyItem Bosses` rate-boosting pass is unported; a map
  with that rule on makes `gather_chunks_info` raise `NotImplementedError` rather than silently
  producing an incomplete index. `taskUnlocks` gating (`_task_unlocked`) is applied to
  `Monsters`/`NPCs`/`Objects`/`Shops`/`Spawns`: an entity present in a chunk can still be locked behind
  completing challenges *at that location* (the `Sir Tiffy Cashien (The Slug Menace)` shop needs that
  quest before it sells Proselyte armour; `White Knight Armoury` needs `Wanted!`). This makes source
  availability depend on challenge validity, so `pipeline.derive` feeds each pass's validity back in
  via `valid_tasks` — upstream instead deletes from an already-built index (`shouldDelete`,
  worker.js:2155). A monster with no `drops` entry falls back to its `skillItems.Slayer`
  entry (e.g. `Abyssal demon` -> `Abyssal whip`, gated by a simplified Slayer-level check rather than
  upstream's full `isSlayerValid`, which needs challenge-validity state this one-directional pipeline
  doesn't have — see `_slayer_skill_items_for`'s docstring); this was added as a prerequisite for
  `bis.py`, whose equipment candidates draw on the same item index.
- `challenges.py` — pure; which challenges are valid given the source index (`calc_challenges` ->
  `ChallengeResult`), a fixed point over 28 of the 29 categories. `BiS` (`UNSUPPORTED_CATEGORIES`) is
  never evaluated *here*, but it is computed — by `bis.py`, not this module (see below): unlike every
  other category, `BiS` challenges have no static definition anywhere in `chunkinfo.json`, so
  presence-checking a literal `challenges.BiS` branch with this module's generic engine would produce
  nonsense; `UNSUPPORTED_CATEGORIES` just guards against a hypothetical export that has one. Callers
  wanting BiS read `pipeline.Derived.bis`, not `ChallengeResult.valid['BiS']`, which stays unpopulated.
  Port of the core of `calcChallenges`/`calcChallengesWork` (~1,500 dense lines) for the other 28 —
  **still partial, read the module docstring before trusting output**. In short: `Chunks`/`Objects`/
  `Monsters`/`NPCs`/`Mix`/`Items` requirements (incl. `[+]`/`[+]xN` family matching via
  `codeItems.itemsPlus`) are exact. The `*` secondary marker is stripped and does **not** gate
  validity (verified against upstream, worker.js:4046/4064 — a docstring correction from an earlier
  stage, which had this backwards) — it only feeds a `Secondary` flag this module doesn't thread
  through, since its sole consumer (`checkPrimaryMethod`, not ported) and the `forcedPrimary` gate it
  feeds have zero real-export uses. Combat skills and `BIS Skilling`-category challenges additionally
  reject an item sourced *only* from another skill's crafted output (`_source_quality_ok`) unless
  `Not Equip`/`Wield Crafted Items`/a Slayer source/the requiring skill being Magic excuses it — the
  same mechanic `bis.py`'s `_source_reachable` implements for equipment candidates. `Skills`
  requirements go through `_check_primary_method`, a port of upstream's `checkPrimaryMethod` over its
  `universalPrimary` table ("is this skill actually *trainable* here"), replacing a loose
  "has any valid entry" stand-in that reported `Combat` untrainable on every real map and so killed
  every Slayer-master assignment. `Tasks` requirements support `[+]`/`[+]xN` families
  (`codeItems.tasksPlus`) and consult the previous fixed-point pass, without which a dependency
  pointing backwards through the export's category order (`Nonskill` -> `Slayer`) could never resolve.
  `sources.py`'s `taskUnlocks` gating depends on all three, which is why they landed together. `processingSkill`
  categories (Runecraft/Magic/Herblore/Cooking/Firemaking/Fletching/Smithing/Crafting/Construction) get
  the "Highest Level" grouping (`_group_processing_skill_challenges`): **rule off** (upstream's
  default) keeps only the *lowest*-`Level` consumer per available ingredient (e.g. smelting a bronze
  bar lets you smith a dagger, not every higher tier at once) — an earlier stage of this project had
  this backwards too; **rule on** (true of the map this was built against) keeps every consumer,
  matching plain presence checking with no grouping needed. Only ~42 challenges remain genuinely
  unsupported on that map — the `QuestPointsNeeded`/`CombatPointsNeeded`/`KudosNeeded`/
  `TotalLevelNeeded`/`CombatLevelNeeded` gates, which need state (quest points, kudos, ...) this module
  doesn't derive. **Untrainable skills are pruned** (`_prune_untrainable_skills`, worker.js:1521):
  when `checkPrimaryMethod` reports a skill untrainable and no `passiveSkill` floor covers it, every
  one of its challenges above `Level 1` is discarded. This is how upstream locks a skill behind a
  quest — `Herblore` is gated on `Unlock ~|Herblore|~ after Druidic Ritual`, and while that quest is
  out of reach the skill keeps nothing; missing it left 56 valid Herblore challenges and a proposed
  active task. It runs **once, after the fixed point converges**, not per pass: deciding trainability
  from a half-seeded item index prunes a skill whose own `Output` chain would have made it trainable,
  and the starved next pass then settles on the wrong fixed point (it broke `Magic`, and with it the
  BiS oracle's `Master wand`). `Monster[+]` is also a **wildcard** ("any monster at all",
  worker.js:4306) rather than a `monstersPlus` family — treating it as one made `Cast ~|wind strike|~`,
  Magic's only Level 1 `Primary` route, permanently invalid and so the whole skill untrainable.
  The **`Show Diary Tasks Any` waiver** is ported (`_diary_tier_waived`, worker.js:1360): a diary
  tier's completion challenge is marked by carrying a `Reward`, the next tier's tasks depend on it,
  and with that rule on the dependency is dropped so an Elite task shows without the Hard diary being
  finished (the dependent must carry no `Reward` itself, or the tiers collapse into each other).
  This was the whole of the Diary gap — outstanding Diary tasks 1 -> 5 against the map's own oracle.
  `BackupParent` is honoured (worker.js:1679): a challenge naming one is deleted once
  that parent is valid *or backlogged*, unless it carries `ManualValid`. All 17 real uses are
  `Hunter`'s barehanded catches — `Barehanded catch a wandering lucky impling` (Level 99) exists for
  players with no butterfly net and must vanish once the Level 89 net version is possible, which it
  wasn't doing (a reported bug: it outranked its own parent and became the active Hunter task).
  **This is the one *absence* check in the module**, so `valid` no longer strictly grows — 11
  challenges disappear on the real map once a net is reachable; see `unlock.py` for what that costs
  the attribution partition. `chunkinfo.constructionLocked` is honoured (worker.js:3758): when set — real data
  has `{'chunk': '10547'}` — every challenge whose name contains `contract for ~|Mahogany Homes|~` is
  invalid outright, since Mahogany Homes is gated behind a chunk the account hasn't taken. Missing
  this was a real reported bug (`fray tasks` proposed an expert contract as the Construction goal).
  `_seed_items_with_outputs` is the output-feedback half of the fixed point, and **is**
  a located port after all (worker.js:2848/2894/3030 — an earlier stage recorded it as this module's
  own invention because the mechanism wasn't found): a valid challenge's `Output` becomes an item,
  *and* doubles as the activity key into `skillItems[<that skill>]`, admitting everything that
  activity yields. That second half is the only route to non-Slayer `skillItems` — `Master wand`
  exists solely in `skillItems.Nonskill['Pizazz points loot']`, reached via the `~|Pizazz points|~*`
  challenge's `Output` (`sources.py` handles the *other* skillItems route, a Slayer monster physically
  present in a chunk). `backloggedSources['items']` is honoured here as upstream does — not cosmetic:
  a backlogged `Uncut onyx` otherwise re-enters at a 1/100,000,000 rate and drags an entire crafting
  chain with it. Simplified: everything is tagged `primary-` rather than split by drop rate, and the
  `Rare Drop Amount` filter on an activity's items isn't applied; the `bossLogs` gate is.
  `strip_task_markup` lives here too — the display-side counterpart to `search.normalise`, dropping a
  task name's `~|...|~` delimiters without lowercasing or collapsing anything. It is *only* for
  output: the raw names stay the keys everywhere (`valid`, `completedChallenges` lookups,
  `--export-json`), since those must match what upstream stores. It removes the delimiter
  **characters**, not the `~|`/`|~` pairs: four real names are malformed (`Carve a ~log |canoe|~` has
  its opening `|` four characters late), and pair-stripping left the visible wreckage `Carve a ~log
  |canoe`. Character-stripping renders those correctly and is byte-identical on all 14,688 well-formed
  names, where neither `~` nor `|` ever occurs outside this markup. **Only call it on a challenge/task
  name** — other branches use those characters for real (the shop `~ Uglug's stuffsies ~`), which is
  why `cli.py`'s `search` applies it per hit type rather than blanket. It deliberately leaves the `#`
  variant separator (`~|wooden hull#Raft|~`) and trailing `*` secondary marker alone — both are real
  parts of the stored name and how upstream renders them isn't something this project has located.
- `bis.py` — pure; best-in-slot equipment per (combat style, slot) (`compute_bis` -> `BisResult`).
  Port of `calcBIS` (worker.js, ~3,150 lines — mostly 19 hand-written copies of one scoring block,
  collapsed here into a `StyleSpec` data table). For each active style (Melee/Ranged/Magic always;
  Prayer/Tank/Flinch/Weight/Stab-Slash-Crush variants gated by `rules['Show Best in Slot ...']`),
  argmaxes a style-specific stat over reachable (`ChallengeResult.available_items` — *not*
  `SourceIndex.items`, which omits anything obtainable only by making it, e.g. `Granite ring (i)`,
  which exists solely as an imbue challenge's `Output`; feeding outputs in moved 19 of 43 picks and
  took the oracle 4/6 -> 5/6) and wearable
  (`_requirements_ok`/`_task_unlocks_ok`/`_consumable_ok`/`_source_reachable`) equipment, first-seen-
  wins on ties, resolves 2H-vs-(1H+shield) (ties to 1H+shield) by scoring **both sides with the
  *weapon* formula**, the shield's offensive stats summed into the 1H side and the weapon's own
  `attack_speed` retained — adding the shield's *armour* score instead compares a DPS-scale number
  against one scaled by 100000, so 1H+shield won unconditionally and every 2H pick was wrongly
  deleted (this is what made us miss `Webweaver bow (u)` and invent an `Odium ward` pick for a slot a
  2H bow should have removed). It sets the `ammo` slot from whatever is
  paired with the *winning launcher* rather than picking ammo independently (deleting it when that
  weapon takes none - otherwise a Melee build gets told to obtain javelins), and emits an
  "Obtain a/an X" task
  name/label per winner, joining multiple styles that pick the same item with upstream's literal
  `'/' + U+200B` (zero-width space) separator. Verified against a real, load-bearing oracle: the cached
  map's `chunkinfo.activeTasks.BiS` records upstream's own last-computed Melee BiS weapon as
  `Abyssal whip` (via the `sources.py` Slayer route above), reproduced exactly — see
  `tests/test_bis.py`'s opt-in oracle test, which asserts **all six** of the map's recorded picks.
  Every one of those six started out mismatched, and each mismatch was a distinct real bug (unported
  area unlocks, challenge `Output` items not reaching BiS, unported `skillItems`-via-`Output`,
  and unhonoured `backloggedSources`) — treat a mismatch there as a defect, not as oracle staleness,
  which is how an earlier stage wrongly explained five of them away. **Deliberately not ported**, documented in the module
  docstring: the set-effect DPS override chain (Void/Obsidian/Inquisitor/Verac's/Crystal/Karil's,
  ~1,738 of upstream's lines), ties-as-alternates and the greedy set-cover dedup pass, and the
  `Show Best in Slot 1H and 2H` rule's dual weapon/2h emission. BiS is inherently **non-monotonic**
  (a later chunk can surface a *better* item for a slot already filled) — per the project's agreed
  semantics, `compute_bis` recomputes the best-achievable set fresh per state rather than accumulating
  history; `unlock.py`/`simulate.py` diff two calls to report which (style, slot) picks improved,
  exempted from `unlock.py`'s monotonic task-partition guarantee (see its docstring). `BisResult`
  additionally splits `tasks` into `completed` (already obtained, cross-referenced against
  `completedChallenges.BiS` merged with `checkedChallenges.BiS`, whose task-name keys match
  `bis_task_name()`'s own output format) and
  `active` (not yet obtained), plus `outdated`: a completed pick whose slot has since been beaten by
  something better, resolved back to an item via a `formatted_name -> (item, slot)` index built from
  `equipment`. For *display* it also carries `slots` (task name -> slot, covering `tasks` and
  `outdated` alike, since `picks`' packed `"{style}-{slot}"` keys can't be reached from a task name)
  and `current_chunk` — the subset of `completed`/`outdated` still sitting in `checkedChallenges`,
  i.e. banked during the chunk in play rather than an earlier one. `bis_display_name` renders the pair
  as `[<slot>] Obtain a granite ring (i)` + a ` (Active)` suffix for the current chunk, and
  `display_sorted` floats those to the top, over `challenges.strip_task_markup`. `current_chunk`
  is intersected with what the result actually shows, so a checked entry naming neither a current pick
  nor a resolvable outdated one is left out rather than sitting unmatched. Candidates are iterated already-obtained-first
  (`_order_completed_first`), matching upstream's `{...completedEquipment, ...equipment}` pool: ties
  are first-seen-wins, so without it the tool proposed items you'd gain nothing from - `Defence
  cape(t)` over an identical, already-owned `Hitpoints cape(t)`, and `Amulet of glory` over
  `Amulet of avarice`. That index lowercases both sides on purpose — the same item can be stored under two
  spellings over time (`Craw's bow (u)` interned vs. a literal `craw's bow (u)`), so real data can
  carry an apparent duplicate for one item. Two real bugs were found here by checking against live
  data rather than fixtures: a completed 2H-slot item was never flagged outdated (`_finalize_slots`
  folds a 2H winner into the `weapon` key in `picks`, and the lookup wasn't normalised the same way),
  and `completed` came back empty entirely because `BiS` was wrongly skipping `t_N` resolution.
- `active_tasks.py` — pure; classifies each real skill category's (`_DISPLAY_SKILLS`, i.e.
  `challenges._SKILL_NAMES` **less `Combat`** — it is in upstream's `skillNames` because
  `Skills: {Combat: N}` requirements and its own `universalPrimary` line need it there, but it is not
  a levelled skill and upstream's own per-skill view filters it out, index.js:9570; its 14 challenges
  are 13 slayer-master assignments plus a quest requirement, all existing to satisfy *other*
  categories. Left in, it produced a phantom `Receive a Slayer assignment from ~|Vannaka|~` pick whose
  only distinguishing requirement, `Skills: {Slayer: 1}`, Slayer's own Level 92 pick had long since
  exceeded) valid
  challenges into `active` (the one current goal)/`obsolete` (superseded)/`completed` (already done)
  (`classify_tasks` -> `TaskClassification`). Port of `calcCurrentChallenges2`'s selection
  (worker.js:8383-8727) — **a different mechanism from `challenges._group_processing_skill_challenges`**
  ("Highest Level" grouping, which governs *fixed-point membership* for the 9 processing skills only);
  this one runs after that fixed point, over whatever ended up valid for *any* skill, and picks a
  single *display* winner — it never changes `ChallengeResult.valid`. Eligibility: `Primary` flag OR
  `Level == 1` OR a `passiveSkill` floor OR a `manualTasks` entry (real fields, present on 32%/30% of
  challenges for `Primary`/`Priority` respectively) - among eligible, non-backlogged candidates the
  highest `Level` wins, ties broken by lower `Priority`; a trivial (`Level <= 1`, non-`Primary`)
  winner is discarded entirely (no active task for that skill). Two corrections came out of reading
  the real `calcCurrentChallenges2` against five user-reported mismatches — **eligibility is
  `checkPrimaryMethod(skill)`, one boolean per skill** ("can this skill be trained here"), *not* the
  challenge's own `Primary` field, which is a different thing; and a candidate must **strictly
  exceed** `_completed_level_ceiling` (upstream's `highestChallengeLevelArr`: the highest `Level`
  among that skill's completed challenges), so equal-level candidates are settled too. The first
  broke both ways: real `Slayer` challenges are almost all `Primary: false`, so nothing above the
  passive floor could win (missing the Level 92 araxyte the map's own oracle records), while
  `Herblore` — untrainable per `checkPrimaryMethod` — still offered a Level 90 potion. The second
  covers `Agility`/`Woodcutting`/`Mining` (a boosted or skillcape completion outranking the proposal)
  *and* the equal-level pairs `Firemaking` (`Burn magic logs` 75 vs `... at a fire` 75) and
  `Smithing` (`rune platebody` 99 vs `rune plateskirt` 99). The ceiling reads the whole `completed`
  ledger rather than its currently-valid intersection, since completion is evidence regardless of
  present reachability, and gates *selection only* — feeding it back as an implied skill level into
  `challenges.py`'s `Level` gate would change what is `valid` and cascade far beyond this module.
  **A recorded completion is treated as proof, whatever the export says now** — a deliberate
  divergence, twice over: `completed` lists every entry in the skill's ledger rather than only those
  still `valid` (a requirement added by a later game update must not erase the fact that the task was
  done), and `_level_proven_elsewhere` credits a completion the skill's own table doesn't carry with
  whatever `Skills: {<skill>: N}` its definition states in *whatever* category it lives in. Real data
  needs both: `completedChallenges.Thieving` holds `~|Wilderness Diary#Elite|~ Task 5`, defined in
  `challenges.Diary` as "Steal from the Chest (Rogues' Castle)" with `Skills: {Thieving: 84}`, which
  upstream's `challenges[skill][name]['Level']`-only ceiling loop cannot see — it was reporting two of
  the map's three Thieving completions and proposing an equal-level Rogues' Castle task as the goal.
  `_never_show` recomputes upstream's `NeverShow` flag (set dynamically in `calcChallengesWork`, never
  present statically in the export) from the `Shortcut Task`/`Combat and Teleport Spells`/`Cleaning
  Herbs` rules. Expect many maxed skills to report no active pick at all (18 -> 4 on the map this was
  built against), which is the honest answer. `completedChallenges` is read
  directly, never re-derived - verified upstream never marks a lower tier "obsolete" in any stored
  field (`grep -i "obsolete\|supersed"` across index.js/worker.js: zero hits); "only show the highest"
  is a pure per-recompute display choice. Every level compared here is **boost-adjusted** (see
  `boosts.py`) — the ceiling via `completed_ceiling`, candidates via `real_level`, and hence
  `_is_eligible`'s `level == 1` test too, which is how an untrainable skill can still have a pick
  (`Clean a grimy guam leaf`, Level 3, boosts to 1 and becomes Herblore's active task). The
  backlog-alternate promotion and sub-skill `Skills`-requirement cross-propagation remain unmodelled. Scope
  (only real skill categories, not Quest/Diary/Extra/Nonskill/BiS) and the oracle-comparison approach
  were explicit user decisions - see the module docstring for the full reasoning. `activeTasks[skill]`
  is a real oracle for the computed `active` pick when present. Only `BiS`/`Diary`/`Extra`/`Slayer`
  carry entries on the map this was built against — and **`Slayer`'s is a load-bearing oracle, not
  the "unrelated slayer-master assignment" an earlier stage recorded it as**. It stores
  `{'Slay an ~|araxyte#Level 96|~': '92{5}'}` (Level 92 less a 5-point `Wild pie` boost), it was
  failing, and fixing it is what surfaced the `checkPrimaryMethod` bug above. Asserted by
  `tests/test_active_tasks.py`'s opt-in oracle test; treat a mismatch there as a defect, not staleness.
- `boosts.py` — pure; temporary skill boosts (`best_boost`, `real_level`, `completed_ceiling`). Port
  of the block upstream repeats verbatim at a dozen sites; with `rules['Boosting']` on, **every level
  comparison upstream makes is against a boosted level**, so this is a dependency of `active_tasks.py`
  and `challenges.py` rather than a feature of its own. `codeItems.boostItems[skill]` maps a boost to
  a flat amount or a `"N%+M"` proportional string; a `~` in the key names the `SourceIndex` category
  (`Oldak~npcs`); `codeItems.boostTaskBans` excludes per challenge (only Thieving's sq'irkjuice, which
  you'd need the boost to obtain); `Crystal saw` is Construction-only, `+3`, and applies solely to
  challenges whose `Items` include `Saw[+]`; a `NoBoost` challenge is exempt. **Availability is read
  from `ChallengeResult.available_items`, not `SourceIndex.items`** — the same trap `bis.py` hit: the
  oracle's own `Wild pie` is baked, not dropped, so the narrow index silently yields no boost at all.
  Two upstream quirks are reproduced rather than corrected, both tested: a `"4%"`-style value with no
  `+` contributes nothing (JS coerces it to `NaN`), and the two clamps differ — `real_level` floors at
  1 while `completed_ceiling` rewrites the boost to `Level - 1` and recomputes, yielding `-2` for a
  Construction `Saw[+]` challenge. `skillQuestXp` and the `Kill X` rule's own copy are unported.
- `other_tasks.py` — pure; groups the three **non-skill** categories, `Diary`/`Quest`/`Extra`
  (`classify_other_tasks` -> `OtherTasks`). Nothing like `active_tasks.py`: `calcCurrentChallenges2`
  excludes these from its per-skill loop outright (worker.js:8390), so there is no single winner —
  upstream's panel renders **every** valid challenge that isn't completed or backlogged
  (index.js:6702/6744/6767). Two things about that guard: it tests
  `completedChallenges` **alone**, so upstream keeps a task ticked this chunk in the *active* list
  with its checkbox set (index.js:6663/6745) — a terminal has no checkbox, so this module
  **deliberately diverges** and reports a ticked task as *completed*, sorted to the front of its group
  and of the category and marked `(Active)`, the same treatment `bis.py` gives its own current-chunk
  acquisitions. `CategoryTasks.current_chunk` names them, so the panel's own view is recoverable as
  `active` ∪ `current_chunk`, which is what the oracle test compares. Completions are also reported
  whether or not still valid, the same rule the skill categories follow. Grouping mirrors
  the panel: `Quest` by `BaseQuest`, `Diary` by the diary and tier in the name
  (`~|Morytania Diary#Elite|~ Task 5` -> *Morytania Diary - Elite*), `Extra` by its `Label` —
  `Collection Log`, `Permanent Unlockables`, `Untracked Uniques`, plus `Fill POH`/`Fill Stashes`/
  `BIS Skilling`/`Stuffables` when their rules are on (`challenges._category_gate_met` already
  decides which). `Extra` is the export's key and stays the key in `--export-json`; **`Other` is the
  display name**, and both are accepted by `fray tasks`. **`Quest` gets two extra passes**, both because a quest is a step
  chain: `_implied_completions` closes the *recorded* completions transitively (ticking a quest off
  stores only `~|X|~ Complete the quest`), and `_superseded` ports upstream's `markSubTasks(...,
  false)` (worker.js:485/1486) — being able to *reach* a step means its prerequisites are behind you
  whether or not anything recorded them, so only the furthest reachable step of a quest shows.
  Together they took Quest active 94 -> 7 -> 0 on the real map, and 0 is right: only 13 quests are
  fully reachable there and all 13 are done. `[+]` families expand to **every** member
  (worker.js:498/512) — `~|Shield of Arrav|~ 3` needs `ShieldOfArrav2Final[+]`, the last step of
  either route, and reaching it means whichever route you took is done; upstream can't tell which
  either. Note the family key is `name.split('[+]x')[0].replace('[+]','') + '[+]'` — the existing
  `[+]` comes *off* before one is appended, or `X[+]` looks up as `X[+][+]` and silently finds
  nothing. Both passes are guarded on a matching `BaseQuest`, and `_superseded` is kept as a set
  rather than written into `ChallengeResult.valid`, whose values mean "requirements met" everywhere
  else and which `unlock.py`/`simulate.py` diff.
- `pipeline.py` — pure; bundles the per-map inputs (`MapState`) and runs `unlocked_sections` ->
  `gather_chunks_info` -> `calc_challenges` -> `compute_bis` -> `classify_tasks` for a given
  unlocked-chunk-id set (`derive` -> `Derived`, carrying `bis`/`task_classification` alongside
  `reachable_sections`/`source_index`/`challenges`). `derive` runs that chain in a **loop** while
  newly-valid challenges unlock further named areas — this is where upstream's circularity lives (an
  `UnlocksArea` challenge only becomes valid once its requirements are met, and the area it unlocks
  adds *new sources* that can validate more challenges; upstream re-runs `gatherChunksInfo`
  mid-`calcChallenges` for the same reason). Keeping the loop here lets `sections.py`/`sources.py`/
  `challenges.py` each stay one-directional and separately testable. `load_map_state` decodes a raw cached-map
  payload into a `MapState` once (including `passive_skill` for `bis.py`'s skill-requirement gate,
  and `completed_challenges`/`manual_tasks`/`backlog`/`active_tasks` for `active_tasks.py`/`bis.py`'s
  completed split - where `completed_challenges` **merges `checkedChallenges` into
  `completedChallenges`**, since upstream keeps them apart only as a commit step: ticking a task writes
  `checkedChallenges`, and rolling the next chunk migrates the lot and clears it
  (`completeChallenges`, index.js:12718). Anything obtained during the *current* chunk therefore sits
  only in `checkedChallenges`, and ignoring it reported items you already hold as still to get.
  `MapState.checked_challenges` keeps that half addressable un-merged as well, feeding
  `compute_bis`'s `checked_bis`: it is a **display view, not a second source of truth** — every
  completion *test* reads the merged `completed_challenges`, of which it is a strict subset - these need an optional `tasks_map` argument, the reverse map from
  `firebase.reverse_tasks_map`, to resolve `t_N` ids; without one, every `t_N`-keyed entry is dropped
  rather than kept raw, so those fields decode empty except `BiS`/`manualTasks`, which never need it).
  `unlock.py`/`simulate.py` (and `cli.py`'s `sections`/`sources`/`tasks` subcommands) all call `derive`
  rather than re-deriving the same pipeline themselves.
- `unlock.py` — pure; what a single candidate chunk unlock adds (`tasks_added_by` -> `UnlockDelta`),
  by running `pipeline.derive` for the unlocked set and for that set plus the candidate, then diffing.
  This is the module the project's attribution rule lives in: because `ChallengeResult.valid` almost
  only ever grows (nearly every requirement `challenges.py` checks is a presence check — the sole
  exception is `BackupParent`, above, which can *remove* a task a later unlock supersedes),
  the diff partitions cleanly — each task belongs to exactly the one unlock that first made it valid,
  and a later unlock can never retroactively change an earlier delta. Diffing the *panel*'s
  active-task selection instead (`calcCurrentChallenges2`, now ported in `active_tasks.py`) would
  still be wrong for attribution even though it's computed: it picks only the single highest
  challenge per skill from whatever's currently valid, and a later chunk can promote a *different*
  one into that role, so it is not monotonic - the simulation ledger is built on `calc_challenges`'s
  `valid` directly, not `active_tasks.py`'s classification. `UnlockDelta.bis_upgrades`
  (`diff_bis_picks`) is the same non-monotonic case for BiS, deliberately exempted from the partition
  guarantee above: a later unlock can surface a *better* item for a slot already filled, so it records
  which `(style, slot)` picks changed, not tasks attributed to one unlock.
- `simulate.py` — pure; simulates chunk rolls and accumulates the tasks/sections/BiS upgrades they
  unlock (`simulate_rolls` -> `list[UnlockRecord]`), each record built via `unlock.delta_from` and
  never revisited by a later roll (`bis_upgrades` included — a later roll's improvement doesn't get
  folded back into an earlier record). Two roll mechanisms, ported from index.js: a "random start"
  bootstrap pool (`walkableChunks`/`walkableChunksF2P` filtered by `settings.rollingChunksOptions`)
  used only when nothing is unlocked yet, and an ongoing neighbour pool (port of
  `selectAllNeighborsCanvas`) — every chunk orthogonally grid-adjacent (`±1`, `±256`; the grid is 256
  chunks tall) to an unlocked chunk, expanded through `chunkinfo.json`'s `sections` connectivity graph
  and gated by `sectionsLimits`' task requirements (this is `sectionsLimits`' actual purpose — see
  `sections.py`). A seeded `random.Random` picks uniformly from whichever pool applies, over a *sorted*
  candidate list so the same seed reproduces the same run regardless of set/dict iteration order. Not
  modelled: manual chunk selection/blacklisting, `roll2`/`roll5` bonus rerolls, and the
  `chunkNeighboursOptions` UI conveniences — all user-interaction features orthogonal to a pure roll
  simulation.
- `search.py` — pure; world-wide fuzzy search (`build_world_index` -> `WorldIndex`, `search`) across
  items/monsters/npcs/objects/shops/tasks. Deliberately **not** built on `SourceIndex`: that only
  knows chunks you've already unlocked, so it can't answer "where would I get this". Instead it
  indexes the raw chunkinfo export directly, covering all five of an item's acquisition routes
  (verified against the real export — `drops` 1,640 distinct items, `skillItems` +882 unreachable any
  other way, `shopItems` 1,385, chunk `Spawn` blocks 357, challenge `Output` +2,347 unreachable any
  other way — union 5,962). Concretely: "Abyssal whip" is a `skillItems.Slayer` drop and appears
  nowhere in `drops`, so `sources.py`'s three-route index can never surface it, while `search.py` does
  — this means **`search`'s availability marking is a strict superset of `fray sources`'s**: a query
  can report an item "available" that `fray sources` would never list, since `sources.py` only covers
  3 of the 5 routes. `skillItems`' activity key is *not* reliably a monster (Mining: rocks, Fishing:
  fishing spots, Slayer: usually monsters), so resolving its location tries Monster/NPC/Object in turn
  rather than assuming one category. Fuzzy matching is a small stdlib ladder (exact/prefix/substring/
  `difflib.SequenceMatcher`) — no new dependency — over names with challenge-style `~|...|~`/`#`
  markup stripped first (`normalise`), since most challenge names carry it.
- `summary.py` — pure, I/O-free reductions over a raw payload; extend this layer, not `cli.py`.
  Firebase omits empty containers rather than storing them, so every lookup must tolerate a missing
  branch — `_mapping` exists for that; reuse it (`chunkinfo.py` does too, over the export instead of a
  map payload).
- `cli.py` — argparse subcommands only. `main()` funnels `FetchError`, `CacheMissError`, and
  `NotImplementedError` into a stderr message and exit 1; a new subcommand keeps its logic in a pure
  module (`_load_state` -> `pipeline.load_map_state` handles the common cache-read + decode step).
  `--export-json PATH` writes a subcommand's full result as JSON to `PATH`, or to
  stdout if `PATH` is `-` — in which case it replaces the human-readable summary on stdout rather than
  interleaving with it, so piping stays clean. It is carried by the six *derivation* subcommands
  (`sections`/`sources`/`tasks`/`unlock`/`simulate`/`search`) and deliberately not by the three I/O
  ones (`fetch`/`show`/`chunkinfo`), whose output is the cache file itself. `sections`/`sources`/`tasks`
  take an optional
  positional (`list`/a chunk id; one of `sources.CATEGORIES`; a challenge category) to list that
  branch's contents instead of just its counts, each capped by `--limit` — which defaults to `None`
  (full output) for those three, since piping to `grep`/`less` should just work without a flag, but to
  `10` for `search`, where the tail of a fuzzy ranking is noise rather than data. `fray tasks <category>` branches
  four ways: `Diary`/`Quest`/`Other` (or `Extra` — both accepted, case-insensitively, and displayed
  `Other (Extra)`) list `derived.other_tasks` grouped with headers, showing each task's `Description`
  where the export has one; `BiS` lists `derived.bis.active`/`completed`/`outdated` (BiS isn't a category in
  `state.chunk_info.challenges` at all - see `challenges.py`), rendered through
  `BisResult.display_sorted`/`display_name` rather than as raw task names, so lines read
  `[<slot>] Obtain a granite ring (i)` with this chunk's completions floated to the top and suffixed
  ` (Active)`; the raw `~|...|~` names stay the keys in `--export-json`; a real skill category
  (`derived.task_classification.skills`) shows **active -> completed -> obsolete** sections plus an
  opportunistic comparison against `state.active_tasks[skill]` ("not cached" when absent, the common
  case - see `active_tasks.py`); everything else keeps the flat valid listing. Every one of those
  paths renders through `_display_tasks` -> `challenges.strip_task_markup`, which **sorts on the
  stripped form** so the visible order matches the screen — sorting raw would file every marked-up
  name under `~`. `search` strips per hit type (task hits and `task:` routes only), never blanket, so
  a genuinely tilde-named shop survives. The bare `fray tasks` overview
  prints totals, the active/completed/obsolete split, and then each category's *active* tasks beneath
  its own line — one `<skill> <task>` row per skill that has a current goal, then the `BiS` picks in
  the same `[<slot>] Obtain ...` form `fray tasks BiS` uses, both capped by `--limit`. The
  per-category `valid` enumeration it used to carry instead is mostly tasks a higher tier has already
  superseded, and `--export-json` still has the full mapping for anyone who wants it. `fray unlock`/`fray simulate` print BiS upgrades alongside
  new tasks/sections when there are any; both report task *counts*, never names, so neither needs
  markup stripping.

## Toolchain

Python 3.14.6, mypy, pip (no uv). Run `mypy` before each commit.

## Commands

```
pip install -e ".[dev]"     # editable install into .venv; provides the `fray` script
fray fetch [--map ID]       # GET live state -> cache/<map>.json (default map: fray)
fray show  [--map ID]       # summarise the cached copy; no network
fray chunkinfo              # GET upstream's chunk/challenge reference data -> cache/{chunkinfo,tasks_map}.json
fray sections [list|CHUNK] [--limit N]   # reachable sections; list/drill down with a positional
fray sources  [CATEGORY]   [--limit N]   # items/objects/monsters/npcs/shops; list one with a positional
fray tasks    [CATEGORY]   [--limit N]   # valid/active/obsolete/completed, incl. BiS (partial - see challenges.py/bis.py/active_tasks.py)
fray unlock   --chunk ID    # tasks/sections one candidate chunk would add on top of the cached map
fray simulate --rolls N [--seed S]   # simulate N chunk rolls and accumulate their tasks/sections
fray search   QUERY [--type T ...] [--limit N]   # fuzzy search item/monster/npc/object/shop/task
python -m fray_claude ...   # same CLI without the console script
mypy                        # strict, over src/ and tests/; run from the repo root
.venv/bin/pytest            # whole suite
.venv/bin/pytest tests/test_summary.py::test_summarise_counts_unlocked_chunks   # single test
FRAY_CHUNKINFO=path .venv/bin/pytest tests/test_sections.py -k real   # opt-in oracle test against a real export
pyproject-build && pipx install --force dist/*.whl   # build + reinstall the `fray` command system-wide
```

`mypy` and `pytest` are invoked differently on purpose: mypy is the *system* install (there is no
`.venv/bin/mypy`), configured with `python_executable = ".venv/bin/python"` so it can see pytest's
stubs — which is why it must run from the repo root and needs the venv to exist. pytest is only a
`dev` extra inside the venv and is **not** on `PATH`, so a bare `pytest` fails with
"command not found"; call `.venv/bin/pytest` (or activate the venv first).

`cache/` is gitignored, so a fresh clone has no data and `fray show`/`fray sections` fail until
`fray fetch`/`fray chunkinfo` run. `fray chunkinfo` downloads ~10MB; `--chunkinfo PATH` or the
`FRAY_CHUNKINFO` env var point `fray sections` (and later commands) at an existing local export
instead.

`pyproject-build` (from the `build` package — `pip install build` or `pipx install build` if it's not
already on `PATH`) writes `dist/fray_claude-<version>-py3-none-any.whl`, independent of the `.venv`
editable install. `pipx install` installs that into its own managed venv and puts `fray` on `PATH` for
use outside this checkout. The `--force` is load-bearing, not optional: the version in `pyproject.toml`
doesn't change between builds, so a plain `pipx install dist/*.whl` on an already-installed package is
a silent no-op ("already seems to be installed") — it will not pick up new code.

## Conventions

- PEP 8, type hints on all functions
- Commit after completing a change
- After completing a task, rebuild and reinstall the CLI locally so the `fray` on `PATH` reflects it:
  `pyproject-build && pipx install --force dist/*.whl` (see Commands for why `--force` is required)
- Tests are pytest, in `tests/`, named after the module under test (`tests/test_summary.py`). No test
  touches the network or the real `cache/`: pass `cache.py`'s `root` a `tmp_path`, and monkeypatch
  `urllib.request.urlopen` (`tests/test_api.py`) or `fray_claude.cli.fetch_map` (`tests/test_cli.py`).
  Any test calling `cache.read_chunkinfo()` without an explicit `override` must
  `monkeypatch.delenv("FRAY_CHUNKINFO", raising=False)` first, or an ambient env var shadows `tmp_path`
- A test that needs the real (~7MB) chunkinfo export is opt-in, not run by default: build fixtures by
  hand for the normal suite, and gate the real-export check on `FRAY_CHUNKINFO` with
  `pytest.mark.skipif`, so a fresh clone stays green
  (`tests/test_sections.py::test_manual_sections_match_a_real_export` and
  `tests/test_bis.py::test_melee_bis_weapon_matches_the_live_oracle` are the existing examples).
  `FRAY_CHUNKINFO` must point at a *raw* export file, not this project's own envelope-wrapped
  `cache/chunkinfo.json` (`fray chunkinfo`'s output) — `cache.read_chunkinfo`'s override path reads it
  directly with no `["data"]` unwrapping, so pointing it at the envelope silently produces wrong or
  incomplete results rather than an error. Extract the raw export first if working from the cache
  (`json.load(open("cache/chunkinfo.json"))["data"]`).
- No custom `User-Agent` on requests — the endpoint is public and unauthenticated, so there's nothing
  to disguise
