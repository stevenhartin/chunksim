"""Turning a derivation into hours.

`heuristics` owns every hand-correctable number and the
`defaults < scraped < computed < overrides` merge; `slayer` owns the one rate
that is a distribution rather than a choice; `estimate` walks the active set and
prices it; `dps_bridge` is the optional seam to `osrs-dps`; `inputs` assembles
what the two apps feed the others, so they cannot disagree.

**`dps_bridge.py` is the only module in the project that may import
`osrs_dps`**, and that is a boundary rather than a preference: the extra is one
a user opts into, so every other module here has to work without it. It was a
*licence* boundary too until this project became GPL-3.0-or-later to match the
library; the optionality is what survived, and it is the half the code was
always enforcing. Importing `dps_bridge` is always safe; calling into it
without the extra raises `DpsUnavailableError`.

The export contains no durations, no kill rates and no XP figures at all, so
every number this directory spends comes from the scrape, the checked-in
overrides, or a default - except `model/experience.py`'s XP curve, which is
exact and deliberately not overridable.

The modules, and what each owns:

- `heuristics.py` - every hand-correctable number, and the
  `defaults < scraped < overrides` merge. Owns the joins and their
  `exact`/`contained` provenance; **no fuzzy tier, by measurement.**
- `estimate.py` - the five buckets over the **active** set (`BUCKETS`: quests,
  boss drops, monster drops, activities, skilling - `_bucket_for` tells a boss
  from an ordinary monster from a real activity/shop/recipe route by asking
  `WorldIndex` rather than by the shape of `source`). **Costs the unique
  *item*, not the task**, and **clamps per source**. Owns the item walk and the
  gates on it, and records the `Heuristics` entries each number was read off -
  where they are read, never reconstructed. **The kill route's `providers` is
  `combat_xp.farmable_providers`, not `levels.reachable_providers`** - some
  raids place their own bosses in a chunk (Chambers of Xeric files Skeletal
  Mystic and Muttadile under its own name), and left reachable a scrape-free
  boss like that priced its drops at `DEFAULT_KPH`'s 150 kills an hour, the
  same bug the raid/wave-minigame item tables already exist to keep out of
  the *drop* route reappearing through the *kill* route instead. **A
  `skillItems.Nonskill` table keyed by a raid's own place name is the same
  bug a third way**: Theatre of Blood's Sanguine dust/ornament kit/staff
  table is keyed `"Theatre of Blood"`, which coincides with the literal
  `Object` name of the raid's own entrance portal - a real, reachable
  provider - so `_kill_facts`/`_kill_hours` called generic
  `Heuristics.kills_per_hour("Theatre of Blood")` on it and hit the same
  150/hr default. `_provider_kills_per_hour`/`_provider_knob` catch this:
  a `default`-sourced rate for a name in `instanced.RUN_ONLY_PLACES` is
  replaced by `3600 / instanced.run_seconds(...)`, knobbed through
  `instanced.knob_for` rather than `monsters/{name}`, and a real hand
  override still wins first. **A fourth way, and this one is not instanced
  at all**: `dps_bridge.GROUP_BOSSES` already refuses to *simulate* a kill
  time for a boss that is not soloable ("the wiki's rates for these describe
  a team, so comparing against them is meaningless too" - its own
  docstring), but nothing kept that same team-describing wiki rate out of
  the *kill route* `providers`/`walk.available` still offered it through.
  `_GROUP_BOSS_SOLO_ALTERNATIVE` closes the one pair that has a real fix:
  `The Nightmare` yields to `Phosani's Nightmare` in `providers` whenever
  both are reachable, since she shares the drop table, is genuinely
  soloable, and already carries a real DPS-modelled rate - `Nightmare
  staff` moved from a guide's 12/hr team figure to her own 5.8/hr. The other
  ten `GROUP_BOSSES` entries have no such solo sibling and stay as they
  were: refused for DPS, still wiki-rated for the kill route, because
  excluding them outright would leave items only they carry unpriced rather
  than merely mispriced. A leaf item priced by a one-off
  `make:`/`shop:`/`spawn:`/`recipe:`/`currency:` route (no real repeatable
  source of its own) displays under the Diary/CA task that wants it instead of
  under its own recipe name (`ItemEstimate.group`, off `_leaf_task_groups`'
  index into `other_tasks`); `_group_total`'s **max within a source, sum
  across sources** is what keeps that clustering and the clamp agreeing with
  each other and with the un-clustered case. `_route_hours`' certainty gate
  (a `Monsters`-named `task:` route with no stated pace refuses, since a
  monster is not a four-tick action) now makes one exception: a `*`-marked
  `Items` entry is upstream's own consumed-secondary marker
  (`derive.challenges._is_secondary`'s docstring), not a tool like an ent's
  bare `Axe[+]`, and the walk already knows the real cost of a consumed
  ingredient. Yama's five `Contract of <X>*` sigil offerings and two
  Nightmare/vampyre loot tables had no other route at all and reclaim one
  here, going from `unpriced` to priced off the contract's own cost. `Chest
  (Bryophyta's lair)*`'s `Mossy key*` is the same shape but was never
  `unpriced` - see `keyed_chests.py` for the wrong number it *was* getting,
  through a different route this gate does not touch. `_Priced` carries an
  opt-in `children` field (each material's own `_Priced`, and the item name
  it answers for on `.label`) and a `trace` parameter threaded through
  `_item_hours`/`_settle`/`_best_route`/`_route_hours` to fill it - `False`
  everywhere but `training.trace_option`, the only caller that needs the
  tree rather than the flat total the rest of this module has always read
  off `.hours` alone.
- `training.py` - how fast a skill goes. **A climb is priced band by band as
  methods unlock**, so the floor can only ever be the first band. Each band
  carries the override path behind its rate, set where the rate is chosen.
  `trace_option` is a further drill-down for one method - its material chain
  as a tree, `MaterialNode` by `MaterialNode` - built by re-deriving the
  winning `recipe_rates.Recipe` (`ActionRate` deliberately does not keep it)
  and walking its materials with `estimate.priced_material`'s `trace=True`.
  **Refuses rather than approximates**: only a method whose rate came off a
  real recipe (`recipe_rates.RECIPE_SOURCE`) has one - gathering, combat,
  GOTR, spells and every other computed source prices its own materials its
  own way with nothing here to walk, and `trace_option` returns `None` for
  the rest rather than guess. `rate_material_tree` is pure arithmetic on top:
  `option.effective_xp_per_hour` divided by the root's own xp-per-action
  gives actions an hour, and every node's `per_hour` is that figure times
  its own `quantity` multiplied down the path from the root, not read off in
  isolation - a child's `quantity` is per one *parent* action.
- `recipe_rates.py` - a recipe turned into an XP rate, joined exactly on
  `Output` **and on the wiki's own variant label**, so the two ways of smelting
  a bar are two answers rather than one given twice. Owns
  `defaults < scraped < computed < overrides`, and **an ambiguous join may fill
  the floor but may not replace the scrape** - one recipe reaching several
  tasks is the guard the flip needed, and it is keyed on the recipe chosen, not
  on the item made. Also `trip_seconds`: a bank trip's share, scaled by what an
  action consumes. `_skill_join_tables` is the per-skill setup
  `computed_rates`'s own loop builds once for every task in a skill;
  `recipe_for_task` rebuilds it for one task alone, re-running the identical
  join and `rate_for` selection so `training.trace_option` can get the real
  `Recipe` back - never a second implementation of the choice, only a
  narrower call to the same two functions.
- `barbarian.py` - barbarian fishing's **Strength and Agility**, off the same
  cascade the Fishing node walk already rolls. Nothing new is modelled: the
  rolls are read a second time with the ancillary experience column, so the two
  cannot drift. The wiki's own Str/Agi-to-Fishing ratio checks it at 0.089
  against 0.090-0.092.
- `library.py` - the Arceuus library, which pays **a multiple of the level you
  already have**: 15x for Magic, 5x for Runecraft, one tome a book at a
  measured 110 books an hour. One activity, two challenges, and a straight-line
  curve - it was sitting in the export unpriced under a name no rate table
  would join.
- `herbs.py` - what a herb costs, as a **supply rather than a route**. Farming
  priced at the clicking ignores the 80 minutes a herb grows; a drop priced per
  herb asks a table that hands out thirteen without being asked which. So the
  cycle is the unit - a run of `2 + patches` minutes, then the rest of the
  eighty spent on the best **pooled** herb source. Checked before the routes in
  `_item_hours`, like currency.
- `salvage.py` - shipwreck salvaging **and** the sorting upstream makes a
  second challenge of. The find is raised by *one* crewmate rather than the
  guides' two, worth `D^2/125` - it rolls every 5 ticks to the player's 4 and
  is paid `D/10` a salvage - so the best in the game is +12.8%, not a second
  player. Sorting runs at the station's 1,800/hr and **is charged the salvage
  it eats**, which is what keeps 171,000/hr on paper down to 8,400 in fact.
- `barracuda.py` - the three Barracuda trials, **counted rather than quoted**.
  `Sailing training` states all nine rates as wiki expressions over components
  each trial's own page publishes, so this reads the components and reproduces
  the scrape to the experience point - deliberately, since an identity is
  worthless as evidence and valuable as a check: the scrape is now this
  model's oracle. A boat-speed model was attempted and **refused** - the two
  published observations imply exponents of 0.75 and 0.235, so there is no
  curve both support.
- `firemaking.py` - burning a log, which is **two methods the export always
  carried as two and the pricing gave one number to**. A line rolls against the
  skill's own `{{Skilling success chart}}` (65/256 at level 1, certain from 43)
  and a forester's campfire is a flat 9 ticks that never rolls, so the two
  cross over at level 12 - the old figure was wrong in both directions at once.
  Checked against the wiki's own two failure-docked bands to under 1%.
- `pickpocket.py` - the wiki's own `np/(10-8p)` over each NPC's own success
  chart, where a flat 3.5-second cycle stood. Every figure in it is published: a
  2-tick attempt, an 8-tick stun, and a `low`/`high` per NPC. It reproduces the
  guide's geared Knight of Ardougne to 1.6% and its tick-perfect rate exactly,
  then **spends the plain curve** - no diary, no necklace, no gloves - because
  those are things a map may not have. The seven NPCs the wiki has never
  charted keep **no rate**: the constant was 2x to 3.6x fast on all eighteen it
  can be checked against, so leaving it on the rest is quoting a number there
  is evidence against.
- `wiremachine.py` - the Dorgesh-Kaan wire machine, which is **a stall that can
  fail**. Its page states the cycle ("a total of 10 ticks per wire stolen"), the
  22 experience and a success chart fitted to 23,848 attempts, so the rate is
  `13,200 x p` and nothing is assumed. It reads 7,167/hr where it opens at 44
  and 12,943 at 99, against the flat 9,240 of the guide it displaces - the last
  published Thieving rate on any cached map.
- `coverage.py` - **what the rates are made of**, rather than what they are.
  Every primary method with the status that priced it - `modelled`, `guess`,
  `published`, `pinned`, `unpriced`, `refused` - plus the best method per skill
  and one skill's full list. `guess` is separated from `modelled` because it is
  the one that should shrink; `pinned` from `published` because an override is
  not a gap; and **`refused` from `unpriced` because they are opposite claims**
  - a gap somebody should close against an absence some model chose, with that
  module's own sentence beside the row (`Heuristics.refused`). It renames only
  what would otherwise be `unpriced`, so a model that later prices the method
  simply wins. What `chunksim training` and the GUI's methods overlay both
  read.
- `disclaimed.py` - the methods whose **own source says they are not for
  training**, each quoted. One entry: the Stranglewood fishing spot, whose page
  says "it is not recommended for training Fishing". A money-making guide's
  experience an hour is a by-product of a rate about loot, and nothing publishes
  the cadence a model would need - a chance fitted to the guide's own figure
  would be the guide with extra steps. Takes away only the scrape's own tiers,
  so a model or a hand pin survives.
- `trawler.py` - filling leaks on the Fishing Trawler, which is a **budget
  rather than a pace**: the wiki tabulates what each action pays in
  contribution points and caps a game at 255, so what a skill can take out is
  decided by its action's points-per-experience. A leak is one point per
  experience - the best Construction can do, since a rail is the same 5
  experience for twice the points - giving 51 leaks and 255 experience a game,
  9.23 games an hour, **2,354/hr before the swamp paste**. Labelled a ceiling
  for `troublebrewing.py`'s reason. Crafting's net repair sits in the same
  table and is **not** carried: its success chance depends on Crafting level
  and nothing charts it, which is `pickpocket.py`'s call for its seven NPCs.
- `tempoross.py` also carries a **third regime**: repairing masts pays
  Construction `4 x level` - the reward table's 40 is *points*, not experience
  - and at one repair a game and five games an hour that is `20 x level`.
  Its bands are `GUESS`, because nothing publishes how many waves a game holds
  and one invented factor makes the product invented.
- `valetotems.py` - the Fletching minigame, and the little Construction it
  pays. Two published tables that both close exactly: a totem is
  `4 x (build/carve + decorate)` on all six log tiers, and Construction is
  `104 x level` on all nine rows - which is where the 104 totems an hour comes
  from. **The published rates assume bought logs**, so this charges the five a
  totem eats and a chunk map turns out to be log-limited: redwood is 28.6
  totems an hour, not 104. The two skills want different logs, since only
  Fletching's payout scales with the tier.
- `yields.py` - a gathering action's own **weight tiers**, which are yields
  rather than drops: mining granite hands over one of three weights at
  20.7/22.15/25.39%, so a 5kg block is one mine in four rather than a rare
  drop, and `estimate._route_hours`' certainty gate was refusing it. Priced as
  a **flat per-item cost** and checked only after every route has failed -
  routing it would divide the quantity by a fractional share, and a fractional
  quantity is a fixpoint key nothing else matches (measured twice: `fray-uber`
  failed to price in three minutes even gated to eight items). The boundary is
  a gap in the data rather than a knob: nothing at all sits between 8.33% and
  19.92%.
- `crane.py` - a Port Piscarilius fishing crane, **one action paying two
  skills** and every term published: 10 ticks an attempt, a
  `{{Skilling success chart}}` read at the *higher* of Crafting and
  Construction, `4 x level` experience in each separately, and nine nails plus
  three planks a success with one more nail bent per failure. The curve check
  is real - the chart's `low1`/`high1` reproduce the page's own "20% at 30 to
  30% at 99". World-hopped, like `wintertodt.py`, so the crane's 30-60 second
  respawn never binds. **Materials are folded into the rate** rather than into
  `material_seconds_per_xp`, because upstream files one task name under both
  skills and that table is keyed by task alone - they halve it, 71,466/hr to
  39,546 at 99.
- `oneoff.py` - the seven challenges upstream files as training and nobody
  trains with: four trophy mounts (the *display* is the repeatable action and
  is priced; the mount consumes a 1/1000-1/3000 fish per repeat, ~3 xp/hr) and
  three boat cosmetics. **Not "one-time"** - the wiki says duplicates do pay -
  but a decoration rather than a loop, which is a claim about the challenge
  rather than about how well this priced it, so it is its own `coverage`
  status beside `unreachable` rather than a refusal. Named individually:
  upstream flags all seven `Primary` exactly as it flags `wooden fence`.
- `gotr.py` - Guardians of the Rift as **one minigame, not twelve rune
  methods**. The rune is the game's decision - two portals, one elemental and
  one catalytic - so the curve is the *rune mix* at a level, and throughput is
  recovered from the published bands rather than modelled. Bands carry the
  minigame's level, not the rune's, which is what stops a level-1 player being
  offered it.
- `herblore.py` - one of three durations the wiki does not publish (see
  `recipe_rates.stated_ticks` for the merge): cleaning a grimy
  herb is not tick-gated, so its `{{Recipe}}` carries `ticks = ""` and
  `recipe_rates` refused all eighteen. Timed from the bank cycle instead - 18
  ticks an inventory of 28 - and **detected from the recipes rather than
  listed**, so the `Degrime` spell variants stay out.
- `fishcutting.py` - the knife, whose output upstream names `Marlin loot` and
  the wiki has no page for. So the join runs on the **fish going in**, inside
  this family only, and that displaced a money-making guide about *cooking* a
  marlin which had been pricing a level-1, two-experience knife action at
  292,500/hr - the whole Cooking climb on the uber map. Also states the three
  ticks a knife costs on the three crabs the wiki leaves untimed, which is the
  wiki's own figure for the same knife on a fish.
- `spells.py` - a cast priced from the wiki's own `|speed =` and the
  challenge's own `Items`. **Utility spells only**, on the infobox's own
  `type`: a teleport's speed is the animation rather than the method and a
  combat cast belongs to `combat_xp.py`. The materials are upstream's, not the
  infobox's - `Cast ~|bones to bananas|~` eats a big bone the rune list never
  mentions - so the rate is all-inclusive and sits under the recipes, over the
  scrape. Took Magic from 57 priced methods to 77 on the uber map, high level
  alchemy included.
- `lectern.py` - a teleport's tablet, which is the only repeatable way to cast
  one: the travel cast moves you somewhere you cannot cast it again. Says which
  `Cast ~|X teleport|~` tasks have a tablet route, gated on the cheapest
  player-owned-house lectern that makes it (`Lectern space`'s own table) - and
  on nothing at all for the Arceuus tablets, whose dark essence block is
  already its own gate. Everything else is refused, which is what stops the
  wiki's silence about Ancient tablets reading as permission.
- `sacredeel.py` - a Cooking method with no Cooking time in it. The knife is
  spammable, so an hour of dissecting is an hour of *catching*: throughput is
  the Fishing model's own roll read a second time (21.09% at 87, the wiki's own
  figure) and the pay is a step function of **Cooking** level, since that
  decides the scales. The bands are Cooking's and the Fishing level is handed
  in - the opposite assignment to `barbarian.py`, and the same question from
  the other side.
- `troublebrewing.py` - the minigame's Cooking, which is a woodcutting loop:
  chop a scrapey tree, fletch the log, deposit the bark for 100 Cooking xp,
  one to one all the way. Prices the two published mechanics (a chop attempt
  every 4 ticks, a 1/8 depletion) and charges the untimed fletch and deposit
  **nothing**, which makes it an arithmetic ceiling rather than an estimate -
  and the ceiling is 100,000/hr, below a community guide's 200,000.
- `chisel.py` - the other untimed duration, and it is **zero**: a dark essence
  block is chiselled *while running* to the blood or soul altar, on a trip the
  rune's own recipe already pays for. Names the one output rather than reaching
  for a rule over chisels, because a gem cut at a bank is emphatically not free.
  The export carries no challenge for it, so a stated zero can only ever be read
  by the item walk and can never become a training rate of its own.
- `yewtree.py` - a third untimed duration, and the smallest kind: five ticks,
  read off every sibling on the same POH garden page (oak/willow/maple/
  magic/spirit tree (Construction) all state it) rather than off a rule -
  650 of the corpus's 4,043 recipes carry no stated ticks, far too broad a
  net to trust by family resemblance alone.
- `greenman.py` - the same shape with the evidence the other way round: the
  carving's four ticks were **measured in game**, and `Greenman statue`'s
  published 4 for the same action one log tier down is the check on that
  rather than its source. One named output, and not the `(Construction)` page
  of the same name, which times itself. **Fletching's last unpriced method.**
- `shortcuts.py` - an Agility shortcut priced from the attempt: eight ticks,
  the experience its own page states, the experience a *failure* pays, and the
  published success curve. Replaced an 18-second cycle whose comment called it
  "a stated target, not a measurement". **Upstream's `Primary` flag is nearly
  the "is this a training method" answer here** - 93 of 162 shortcuts pay
  nothing and almost all are non-primary - but not quite, so `REFUSED` names
  the two that are primary, join a real page and award nothing. The 33
  challenges upstream states no `Objects` for are deliberately *not* in there:
  that is a hand lookup somebody can do, which is what `unpriced` means.
- `production.py` - what a production method consumes, for the methods no
  `{{Recipe}}` describes, read off `Module:Skill calc` by way of the gathering
  tables. **It supplies a material cost, never a rate**: a calculator row has
  no ticks, so it composes with whatever rate wins rather than competing with
  one. Joins on upstream's own `~|...|~` span.
- `gathering.py` - the generic node model for Fishing/Mining/Woodcutting/
  Hunter/Thieving, and the exact skilling-success formula. Owns
  `defaults < scraped < modelled < overrides`, so **it outranks
  `recipe_rates.py` as well as the scrape**, and the docstring says why. Per-skill quirks
  are `SkillProfile` fields, never branches, and the four inactivity shapes
  (duty cycle, flat charge, restock floor, stun) are what separate a model from
  a fitted constant. Mining is the one skill that pays two of them - the
  published respawn *and* the hop to the next rock - which is `hops`, and the
  reason it is a field rather than a branch. Where no chart exists the curve
  itself has three fallbacks in order, all `INFERRED`: recovered from published
  hourly rates (`stated_curves`), borrowed from a comparable node
  (`assumed_curves`), or interpolated between the charted nodes either side
  (`interpolated`). A *cascade* is the one shape that is not inactivity:
  several success rolls inside one action, which is barbarian fishing. **How
  many of a node you work at once is one idea across all five skills** -
  `units_worked` resolves it, and what it buys depends on what that node makes
  you wait for.
- `implings.py` - Puro-Puro, priced as **one** method rather than as twelve
  creatures. Not a node, so it sits beside the gathering walk rather than
  inside it: what your level buys is which implings the spawn tables let you
  keep, not a faster loop. Overworld implings are not a training method and
  upstream says so too.
- `aerial.py` - aerial fishing: one action that **never misses** and pays
  Fishing and Hunter at once, so what a level buys is a better fish rather than
  a better chance. A mix, like Puro-Puro, not a node.
- `herbiboar.py` - a puzzle rather than a loop: no chance, no interval, no
  tool, just a published experience-per-level table times a stated trails per
  hour. Stays out of `SkillProfile` for that reason.
- `forestry.py` - the nine Forestry events, which you meet a share of rather
  than choose between, and which pay **six** skills at once off one table of
  level-carrying formulas.
- `strut.py` - repairing Motherlode Mine struts, where **the rate is the
  world-hopping and not the hammering**. Dividing the wiki's eight-row hourly
  table by the published `1.5 x level` a repair pays leaves repairs an hour,
  and it is constant to 4.9% across the whole table - where the success chance
  it would otherwise depend on runs 12.11% to 27.73%. The chart is carried as
  the check that this is the right page and deliberately not spent.
- `valeoffering.py` - what a vale offering's reward table costs, which is
  the totem behind it: 100 offerings a rummage, one roll, `Ent branch` at
  65/399 - and a totem is priced by `valetotems` with its five logs charged,
  so a map that must chop redwood pays for chopping redwood. Flat
  `{item: seconds}` like `yields.py`, for the same reason: the share is
  fractional and the route would never memo.
- `lootsack.py` - what a Hunters' loot sack's reward table costs, which is the
  rumour behind it. **The export records the share of one *roll* and an open is
  5/7/9/11 of them**, per tier and published, so reading the figure as a
  per-open chance undercounts a sack by that factor. Flat `{item: seconds}`
  beside `valeoffering.py`, and the only one of the three whose pace is a guess
  - it spends `rumours.RUMOURS_PER_HOUR` and adds nothing to it. One item,
  because `Hunter spear tips` is the only one of the four sacks' 31 members a
  `Primary` method consumes.
- `feathering.py` - the largest `stated_ticks` contributor: **145 of
  Fletching's 158 untimed recipes** are a stack of feathers onto a stack of
  tips, and the four feathered recipes the wiki *does* time are all **2
  ticks** (`Headless arrow`, `Headless atlatl dart`, `Flighted ogre arrow`,
  `Seeking headless arrow`). Twenty of Fletching's unpriced methods were that
  one gap wearing twenty names.
- `calcified.py` - smashing a calcified deposit, the Smithing third of Cam
  Torum mining: 1 experience in 3 ticks, stated twice on the deposit's own
  page. The headline 2,000/hr is the action's; a deposit is a 1/75 roll off a
  mine, and `training.effective_xp_per_hour` plus `yields.py` are what turn
  that into an honest figure. The Mining third is already
  `gathering.stated_curves`; the Prayer third is blocked upstream.
- `blastfurnace.py` - the building's two treadmills, the simplest mechanics
  here: the pump is "2 Strength experience every tick" and the pedals "1 xp",
  a hundred minutes between reclicks, and so a flat 12,000 and 6,000 an hour
  at every level - each the page's own stated figure and the same arithmetic
  twice, so `published_per_hour` is carried as a *check*. Both are ceilings
  and on different things: the pump on the furnace staying stoked by other
  players, the pedals on energy restoration items, since pedalling costs 0.5%
  energy a tick and runs out after 271-385 of them.
- `blackjack.py` - the three NPCs you knock out before taking their pocket, so
  the chart that decides the rate is the **knock-out** one and the two
  pickpockets after it are free. `pickpocket.py` prices the awake method and
  nobody uses it on these: the Menaphite Thug is 104,422/hr awake against a
  published 265,000 blackjacked. One knockout attempt plus two pockets at two
  ticks each reproduces the page's own stated ceiling of 275,000 exactly.
- `coxchest.py` - the Chambers of Xeric thieving room, whose chest **rolls
  every game tick** until it opens, the sharpest cadence in the skill. The one
  method here whose experience the wiki states nowhere, so it is recovered:
  the guide's "about one hour of raid time to level from 1-40" and its
  "30,000-50,000 experience an hour" bound one open to `[8.67, 11.70]` and 10
  is the round number inside. `GUESS` for that, and the only place this project
  spends a tooled curve - the lockpick comes from inside the raid.
- `wallsafe.py` - the Rogues' Den lobby safes, where **one click is a run of
  attempts**: the safe re-tries itself every 4 ticks until it cracks or springs
  the trap, so the thing with a success chance is the attempt and the thing
  that pays 70 experience is the run. The page's own trap rule -
  `(100% - p) / 2` - turns the chart into the published 49%/77% overall rates
  with no free parameter, and its "looted every 8 ticks ... 52,500 an hour"
  ceiling is what the model reduces to when nothing fails.
- `wintertodt.py` - one boss, **two regimes**, and the only activity here with
  **no chance in it at all**: the wiki states its experience as multipliers on
  your level, so a rate is those times a count of games. World-hopped pays
  Woodcutting, Fletching and Firemaking, and replaced a hand-written 400,000/hr
  that was one number for a method linear in the level. Solo pays less
  Firemaking and is the only way the boss pays **Construction**, whose whole
  published table is one constant per skill times the *Firemaking* level.
  **Also owns the phoenix pet** - `Wintertodt` is absent from `drops`
  entirely, the same chest gap `costing/raids.py` closes for the raids, and
  `item_seconds` reuses the world-hopped regime's own `GAMES_PER_HOUR`
  since its 500-point game is exactly the reward cart's own milestone.
- `tempoross.py` - the wiki's rate for four harpoons at five levels each,
  which **replaced three invented tier figures in `stated.py`**. Best harpoon
  by *rate* rather than by tier, since the tiers are not ordered. Also the
  **cooking** regime, which is the page's other table and is one flat number
  because every part of it is fixed: the `max permits` walkthrough counts out
  55 fish a game, a game is 12 minutes including the wait, and a harpoonfish
  pays 10. The two challenges are two choices rather than halves of one method.
  **Also owns the Tiny Tempor pet**, the same chest-absent-from-`drops` gap
  `wintertodt.py`'s phoenix closes, reusing the max-permits regime's own
  `GAMES_PER_HOUR` and its own published permits-per-game figure - earning
  permits, not redeeming them, is the real bottleneck.
- `artefacts.py` - stealing artefacts for Captain Khaled, and **the one
  activity here that derives completely**: both halves of what an artefact pays
  are stated in prose, the run count is the mean of six tabulated house times,
  and the product reproduces the wiki's own eleven-row table with no residual.
- `valuables.py` - Stealing valuables in Civitas illa Fortis, which upstream
  calls `Varlamore thieving`. **A transcription rather than a derivation** -
  nothing in the burgling loop is charted - carried because the same page
  states the activity four other ways and all four agree with the table.
- `blastmine.py` - the same shape as `paydirt.py` in a second activity: a
  published ore distribution, 330 blasts an hour, and an ores-per-blast derived
  from the page's own hourly anchor. **The Blast Mine really is the best runite
  in the game** - 91 seconds an ore against 240 for mining the rock - which is
  why the answer is a number and not a refusal.
- `paydirt.py` - what a Motherlode Mine ore costs, from the **cascade** chart
  on `Pay-dirt`: an ore's chance is its own roll times the chance every richer
  one failed. Feeds `action_seconds`, because it is a fact about ore and not
  about any skill that consumes it.
- `foundry.py` - the Giants' Foundry, which is the whole of Smithing's climb
  above 15. Jagex's release patch notes give swords an hour against experience
  a sword, and their product is the scraped figure on all five alloy tiers.
- `courses.py` - the Agility courses, as **a lap and a lap time**: their
  product is the guide's own figure within 5.2% on all ten that publish both.
  Names the eight it leaves alone and why, including the Colossal Wyrm pair,
  whose own page disagrees with the guide by 1.7x.
- `pyramid.py` - the Agility Pyramid, whose money-making rate the scrape gave
  to a **level-1** challenge for a course needing 30. Bands from 55, which is
  where the wiki's table starts and below which it declines to guess.
- `brimhaven.py` - the Brimhaven Agility Arena, which is **a tag rate plus a
  downtime rate** rather than a lap. The tagging half derives exactly and
  reproduces four published passive figures plus the elite diary's stated
  bonus; the downtime half needs one number nothing states - what share of
  each minute is travel - recovered from the training guide's ungloved
  45,000-50,000 at level 40 and checked against the arena page's own 68,000
  at 99 with gloves and the elite diary, which it predicts at 0.92x. Three
  challenges, one arena, bands from 20 whichever asked. Its finding: the
  level-40 obstacles are **slower per tick** than the level-20 floor spikes,
  so 40 buys route options rather than a method.
- `skullball.py` - Werewolf Skullball, where the lap is published three ways
  and the **reset between laps is not**. 750 experience under four minutes and
  a stated decay past it, against a `Run recommended route` of 2:20-2:45; the
  run back is 8 tiles off the wiki's own tile-marker module and the dialogue
  and ball positioning are the one invented number, which makes every band a
  `GUESS`. Bounded rather than open-ended - the lap dominates - and it names
  the single band on one map its guess decides.
- `cox.py` - the two Chambers of Xeric methods the ordinary layers cannot
  reach: its **herb patches**, where two plots and a 30-second grow are stated
  outright and each plant's `{{Farming info}}` gives the pay (3,360 to
  10,080/hr, a ceiling because seeds are not charged); and its **braziers**,
  refused because 48 experience a kindling is published and nothing times the
  burn - a gap that would decide bands here rather than nothing.
- `denserunestone.py` - the Crafting half of mining dense essence, which one
  swing pays alongside Mining. Scales the node walk's own Mining bands by the
  wiki's stated `8/12` rather than recomputing the loop, so the two cannot
  drift - `barbarian.py`'s rule.
- `fremennikicons.py` - three of the four Fremennik ring icons, which the wiki
  leaves untimed against a `Seers icon` that states 4 ticks. `gnomecooking.py`
  the other way up: one published sibling and three blanks.
- `gnomecooking.py` - the one gnome crunchy the wiki leaves untimed, against
  three siblings on the same page that all state one tick. `costing/yewtree.py`
  reversed: a small, closed, uniform family where the odd one out is the blank.
- `leechfin.py` - cutting a leechfin, which the wiki times in prose ("once per
  tick ... providing 20 Cooking experience each") and never in a `{{Recipe}}`,
  because the cut makes a *chance* of a blood sac rather than a product. The
  fish is the whole cost and is charged in full through
  `material_seconds_per_xp`.
- `measured.py` - the last resort: a duration somebody **timed in game** where
  the wiki states none and no sibling could fill it. Two outputs, both
  Cooking. Fills only where the wiki is blank, so a published figure appearing
  later wins with nothing edited.
- `mess.py` - the Hosidius Mess, whose three foods join a `{{Recipe}}` and lose
  their inputs because a servery pie shell exists nowhere in the export's item
  graph. Priced as an activity instead: the page states a level, a turn-in
  figure, a per-inventory figure and an hourly band for each, and the first two
  check the third. **Charges nothing for materials**, which is the point - the
  page's own "without any requirements to gather materials" is why the Mess
  beats fish this project has to charge for.
- `statuette.py` - chipping a blessed bone statuette, whose rate is an hour of
  Stealing valuables rather than anything about the chip: upstream's `3/520.8`
  share times the wiki's 1,600-2,300 valuables an hour, at 5 experience each.
  **46/hr**, the slowest Crafting method there is, and every term published.
- `tarnished.py` - polishing the nine Vampyrium tarnished items, which no
  `{{Recipe}}` describes because upstream's `Output` is a **loot-table name**.
  One tick and 200-250 experience, both stated on every one of the nine pages,
  which is 1,200,000/hr on paper - so the drop behind it is declared through
  `material_seconds_per_xp` (`costing/salvage.py`'s arrangement) and the nine
  read 92 to 549/hr.
- `toymouse.py` - catching a wound-up clockwork mouse for 3 experience, whose
  charted catch chance reproduces **Mod Ash's own** "24% - 98%" for levels 1
  and 99. Nothing states how long a wind-release-catch cycle takes, on the
  toy's page or on its three clockwork siblings, so `CATCH_TICKS` is invented
  and every band is a `GUESS` - safe because the whole plausible range sits
  below every other Agility method on every map.
- `sepulchre.py` - the Hallowed Sepulchre, counted in ticks: a lap runs floors
  1 to N in order, so the Strategies page's tick-perfect floor times plus six
  ticks a staircase give the Agility rate, and fifteen more per floor for one
  coffin give the **Thieving** one, which no rate table anywhere states. The
  published `Realistic No looting XP/hour` column is kept as the oracle: no
  constant overhead reconciles it with tick-perfect play, so a `MISTAKE_FACTOR`
  on the floor time is calibrated to 91,805 for five floors - inside what a
  good player sustains, and 1.04x the wiki's own row. `GUESS`, because the
  staircase, the lobby return and the mistake factor are all invented.
- `bounty.py` - bounty tasks, the other half of a port's notice board. **Boat
  combat pays one Sailing experience a point of damage**, so a kill is worth
  the monster's hitpoints before the bounty pays - and the bounty pays far
  more, which is what makes it a training method. Gated on a board, on the
  monster being in the map's chunks, and on a sea route out to it over
  `courier.py`'s graph. Stacking is **sequential** since 17 June 2026, so two
  tasks cost the sum of their kills; `CANNON_DPS` is a named term that fitted
  to zero, because `kills_per_hour` already carries overhead boat combat does
  not have. `GUESS`, checked against the wiki's "middle ground between
  salvaging and trials".
- `courier.py` - courier tasks, the one method whose rate is the map's shape.
  Reads the scraped table of 432 deliveries over 30 ports and finds the best
  sailing leg the map's boards, ledgers and water allow. **The travelling
  salesman collapses**: the notice board is always on the leg (all 432 rows)
  and summoning a boat to any dock is free, so a circuit can never beat the
  best leg in it - the circuits in the guide are about board supply, which is
  not geometry. Ports come from upstream's own per-port challenges; the sea is
  grid adjacency over the ocean group, because the `sections` branch is
  walking connectivity and breaks the water into 56 pieces. Both time
  constants are fitted to the guide's 200k/hr, so every band is a `GUESS`.
- `nagua.py` - sulphurous essence, a Runecraft rate paid as a by-product of
  melee training: 12.5 experience a kill is published and the kills an hour
  are `Heuristics.kills_per_hour`'s, so the answer moves with the map's gear.
  Where that lookup is still a bare `DEFAULT_KPH` the page's own
  2,500-3,400/hr stands in, recovered as 200 kills an hour and reported
  `INFERRED` rather than `CONFIRMED`. No material cost and no combat credit -
  the hour is already the killing, and combat experience does nothing for a
  Runecraft climb.
- `ourania.py` - the ZMI altar, whose published table is a wiki expression per
  cell rather than a set of observations, so reading the components lands on
  the column exactly and the scrape becomes the oracle. Every step in
  `essence_per_lap` is a pouch unlocking, and the Astral Contact term goes to
  zero at 99 because the Runecraft cape stops pouches degrading. **The
  published rates assume the essence was bought**; mining it at 2.4s a piece
  is three quarters of a lap, which takes level 99 from 77,121/hr to 17,935
  and flattens the 1-99 span from 3.8x to 2.2x - a bigger pouch saves running
  and saves nothing at the rock.
- `desiccated.py` - the Royal Titans' `Take pages` option turned into
  Runecraft: 14.5 pages a kill (the wiki's own mean of a `10-19` `Always`
  line), 48 kills an hour from the two money-making guides, and 50 experience
  a page at any of the three plinths. **The guides' `*0.5` duo contribution
  cancels against their kill rate**, so 348 pages an hour is one player's
  share however many are fighting - which is the one thing about this boss a
  chunk map could not otherwise answer. A ceiling: nothing states the
  `Reinvigorate` cadence, and a page is stackable so the plinth trip
  amortises. `costing/dps_bridge.py` puts the same figure at 258-303, inside
  the boss bias it documents on itself.
- `levels.py` also owns `TaskGate`: the slayer assignment a monster demands
  **and where it demands it**. The place is load-bearing - `Konar quo Maten`
  keys all 93 of his tasks by location, so a bare `Hydras` matched none and a
  Konar-only map left every gated monster unpriced. `slayer.MasterRate.key_for`
  is the join, matched on the place because 23 of his families span up to six
  of them and a prefix match would shorten the wait for an assignment most of
  its weight does not satisfy.
- `instanced.py` - **the one answer to "what does killing this boss cost".**
  Three layers had decided that for themselves and two were wrong, which is
  how four Grandmaster Combat Achievements naming `TzKal-Zuk` came to share
  0.05 hours. Also owns which places *are* runs, resolved against the export
  rather than listed: the same place is filed under a name **and** a numbered
  square, and the name-only set this replaced missed fourteen of them -
  `9551` is the Fight Caves, `9043` the Inferno. Prices a run's **final boss
  only**; the rank-and-file need a room ordering no module here carries, and
  are refused rather than guessed. Owns the `runs` knob branch, which is the
  one duration in this subpackage that no scrape reaches - so it is the one
  most worth correcting, and one correction moves every answer spending a run.
  `Sol Heredit` is the one boss `costing/colosseum.py` adds here - the
  eleven-wave roster has no chunk of its own, matching the Theatre's own
  absence, so `Fortis Colosseum Underground` (the lobby) is the only chunk
  there is to gate on. **Barrows and Perilous Moons are deliberately absent**:
  their monsters stand in ordinary, ungated chunks (`Barrows Crypts`,
  `Neypotzli`), so a kill-goal for one of them is a plain kill, not a run -
  only their *chest* needs a module, which is what `costing/barrows.py` and
  `costing/moons.py` are for. **Both Hunllefs share the one `Gauntlet
  Lobby` chunk but need different durations**, which every other entry
  here answers by place alone - so `FINAL_BOSS` still points both at
  `Gauntlet Lobby` (for the `run_only`/`RUN_ONLY_PLACES` contract) but
  `kill_seconds` special-cases them to `gauntlet.kill_seconds`, dispatched
  by monster rather than by place, before `DEFAULT_RUN_SECONDS` is ever
  consulted.
- `tzhaar.py` - the Fight Caves and the Inferno, as the *runs* they are
  rather than the monsters the export files them as. **One wave schedule, two
  rosters**: both minigames field the same 48/40/36/34/33 rank-and-file across
  their waves, and the roles filling those tiers swap between them. Fixes the
  same defect `raids.py` does, one activity over - `Jal-nib-rek` read 5.0
  hours as a 1/100 off a monster killed twenty times an hour, against a
  hundred Infernos - and **the kill-goal path had it too**, four Grandmaster
  Combat Achievements naming `TzKal-Zuk` sharing 0.05 hours between them. `PER_WAVE_SECONDS` is invented and `RUN_SECONDS` is a
  maintainer's figure rather than a publication; both say so.
- `raids.py` - all three raids at once, and the only place that **adds**
  rather than picks: the export carries each raid's rewards as its own
  collection log entries, so a player needs all three logs and the total is
  their sum. Each tier-five cape wants 2,000 completions, so the answer is
  very nearly "six thousand raids" and **where a cape binds the best drop rate
  is the wrong thing to optimise** - the Theatre's hard mode is better per raid
  and loses. `best_for` picks, and is only meaningful for a named unique.
  **`activity_for(item)` names which raid earns `item`** - `tzhaar.py`'s and
  `colosseum.py`'s own shape, missing here until every unique/cape/pet
  `item_seconds()` prices read a bare `source="raids"` with no knob at all.
  `_by_raid()` is `item_seconds()`'s three contributions kept apart so
  `activity_for` need not re-derive the drop chances; both match
  **case-insensitively**, because `_item_hours` resolves an item to the
  export's own spelling (`Scythe of vitur (uncharged)`, `Lil' zik`) before
  either function ever sees it, not the wiki's (`Scythe of Vitur
  (uncharged)`, `Lil' Zik`) that these tables are keyed by - an exact-match
  first cut missed every Theatre unique and pet outright.
- `barrows.py` - the Barrows: six brothers, any order, one chest -
  `Chest (Barrows)` is absent from `drops` entirely, the same gap
  `raids.py` closes for the three raids. No `FightScript` needed - the six
  brothers' melee defences are close enough together that the ordinary
  style search already picks correctly. `UNIQUE_CHANCE` is the money-making
  guide's own `7/2448` for each of the twenty-four pieces, cross-checked
  against `[[Chest (Barrows)]]`'s separately-stated "approximately
  1/350.14". **`_full_log_runs` is a closed-form reduction of
  `encounter.runs_for_all`**, not a call to it - twenty-five items is
  `2**25` inclusion-exclusion terms, over a minute for one answer, where
  twenty-four sharing one chance collapses to twenty-four terms by
  symmetry; verified against the wiki's own "All 6 sets is 1319.26 chests"
  and against the brute-force formula on a small fixture.
- `colosseum.py` - the Fortis Colosseum: eleven waves of a fixed roster then
  Sol Heredit, `costing/tzhaar.py`'s shape with a real published `kph`
  (`2.5`, a 1,440-second run) in place of that module's maintainer's band.
  Sol Heredit needs no script - one bare `osrs_dps` key at `hitpoints=1500`,
  and his published mechanics punish a slow kill rather than forcing a real
  zero-damage window, the same considered refusal `dps_bridge.SCRIPTS`
  already states for Araxxor and Cerberus. The roster is the wave
  breakdown's *guaranteed* composition only - the 40-second reinforcement
  timer is excluded for `costing/tzhaar.py`'s own "ceiling on the speed, not
  an expectation" reason. `Rewards Chest (Fortis Colosseum)` is absent from
  `drops`; every chance here is transcribed from the guide's own summed
  wave-by-wave arithmetic rather than re-derived.
- `moons.py` - Perilous Moons: three solo bosses, each weak to a melee
  substyle the other two resist, feeding one `Lunar Chest` (also absent
  from `drops`). **The first module needing `dps_bridge.MELEE_SUBSTYLES`**:
  Blue Moon, Blood Moon and the Eclipse Moon each carry `defence_crush`/
  `defence_slash`/`defence_stab=0` against `100` on the other two - Zulrah's
  magma-form shape repeated on a melee-substyle axis nothing before this
  resolved - so each Moon is registered as its own one-phase `FightScript`,
  `styles` restricted to the one substyle that actually damages it.
  `UNIQUE_CHANCE` is the guide's own uniform `1/224` across all twelve
  pieces; `kph = 10` is "kills all 3 bosses", one full clear.
- `gauntlet.py` - The Gauntlet and the Corrupted Gauntlet: a preparation
  phase that dwarfs the boss fight, and `Reward Chest (The Gauntlet)`
  (absent from `drops`, one collection-log category for both variants).
  Neither Hunllef needs a `FightScript` - both carry uniform defence across
  every damage type in `osrs_dps`, so no generic loadout is ever wrong the
  way a Moons one is. **`PREP_SECONDS` is this project's own estimate, not
  the wiki's** - the 10-minute/7:30 figures on `[[The Gauntlet]]` are the
  timer's cap, not a typical efficient player's spend, so this module states
  its own midpoints (150s regular, 330s corrupted) explicitly as a `GUESS`.
  `item_seconds` offers **the better of the two variants per item** -
  `raids.best_for`'s "offer the best available" choice - since the export
  gates all four shared uniques under one category regardless of which
  Hunllef gave them; the Corrupted Gauntlet's own entries carry a regular
  completion on top, its published unlock prerequisite, matching
  `costing/tzhaar.py`'s Inferno-entry-fee shape exactly.
- `encounter.py` - the generic sequencer: a run of fights and puzzles priced as
  one unit, because a raid's duration belongs to the *run* and its chance
  belongs to the run's end. Knows no raid. Carries `Mechanic` (uptime and idle
  seconds, so a fight is not assumed to be a damage race - usable by standalone
  bosses too), `Objective` (green log by default, or a named unique, or
  experience), and the coupon-collector arithmetic a green log actually is.
  **`attackers` divides the time-to-kill and nothing else**, which is the line
  between a party helping and a party making a raid free.
- `tombs.py` - the Tombs of Amascut, whose reward is a function of a *setting*
  rather than a mode, so the answer is an optimisation over the invocation
  dial. **Points are damage here** - the wiki says so outright and tabulates
  the multipliers - which is the exact contrast with `xeric.py`, where they
  are not. The chest's piecewise `RL` scaling reproduces the wiki's own worked
  example (level 400 -> 3,700 points a percent), caps at 55% and never rolls
  twice. `Icthlarin's shroud (tier 5)` wants 2,000 completions and entry mode
  does not advance it. **The six boss health bars understate the points about
  fourfold** - the raid scores on every NPC in it - which biases the safe way:
  it makes the cape look less likely to bind, not more.
- `xeric.py` - the Chambers of Xeric: a drawn layout priced as its **mean**
  rather than as a draw, since a player running 2,000 raids gets the average.
  **Points are not damage** - a solo raid's rooms come to ~4,300 hitpoints
  against a published 30,000 points, because the braziers and the grubs
  dominate - so the guide's own figure is the anchor and reproduces its other
  two. The chest is exact: 1% a 8,676 points, capped at 65.7% per roll, up to
  six rolls. **Only Challenge Mode can close the log** (the colour kit and the
  dust are its alone, named at zero elsewhere so the arithmetic says so), and
  what binds it is `Xeric's champion` at 2,000 completions rather than any
  drop rate. The Guardians are a puzzle, not a fight.
- `theatre.py` - the Theatre of Blood: six rooms in a fixed order, no puzzles,
  no points, which is why the sequencer was built against it. Three modes as
  separate `osrs-dps` monsters whose suffixes do not follow a rule, so every
  key is spelled out. **The chest rolls once per team and one player keeps
  it**, so a trio sees 1/27.3 rather than 1/9.1. The money-making guide's
  twenty-minute trio is a **floor** rather than a fit - its gear list contains
  a Scythe of Vitur, a Theatre drop - so `UPTIME` is invented and every figure
  is a `GUESS`.
- `barricade.py` - repairing Pest Control's barricades, an upper bound built
  deliberately. Five experience a repair and two minutes a game are both the
  wiki's (the second is its own ideal-conditions assumption, published with the
  warning that reality is three times worse); **how many repairs a game is
  invented**, at four times the commendation threshold the game dropped for
  being too easy to meet. 6,000/hr, and the whole plausible range loses by six
  times to the slowest Crafting band - which is why a guess closes the row
  where a refusal would only have named it.
- `lightorb.py` - fixing a Dorgesh-Kaan lamp, which pays **500 Crafting and
  500 Firemaking** for one click and had been priced off the glassblowing that
  makes the orb it consumes - a level 87 recipe standing in for a level 52
  action. The orb is ~19 seconds of the walk's own arithmetic and is folded
  into the rate, `crane.py`-style, because upstream files one task under both
  skills; the wrong join's `material_seconds_per_xp` **and its credit** are
  dropped by name, the credit being the half that was false rather than merely
  imprecise. A ceiling - the walk between lamps is uncharged - and it decides
  Firemaking bands on a map without Wintertodt.
- `potionsteps.py` - two Herblore durations the wiki leaves blank in families
  that publish the rest: the one barbarian potion mix of twenty-nine it never
  timed, and the sanfew serum's collapsed recipe, whose three combines are
  checked by the steps' experience summing to its own. A `stated_ticks`
  contributor like `greenman.py` and `gnomecooking.py`, never overwriting a
  published figure.
- `sailtrim.py` - trimming the sails, the one Sailing method paid by a clock
  rather than by an action: 120 trims an hour at the tier's own published
  payout, 1,260/hr on the quest raft up to 15,000 on rosewood. The hull is
  irrelevant (the wiki's three tables carry the same trimming column) and a
  band opens at the level to **build** its mast, which upstream states on its
  own `Build a ~|...|~` challenge. A ceiling, and an ancillary one - what it
  decides is the stretch below Sailing 15 where nothing was priced at all.
- `sorceress.py` - the Sorceress's Garden, where a level buys a **better
  garden** rather than a faster lap or a better chance. Flat rates, and the one
  place a published lap time and a published hourly yield check each other.
- `swimming.py` - Underwater Agility and Thieving, where the experience is
  paid by handing in tears rather than by earning it, and **scales with the
  square of the level**. Prices the *both-skills* exchange rather than the
  faster single-skill one, because that is the only mode where one hour can
  honestly be credited to two skills.
- `pyramid_plunder.py` - a five-minute game priced from what one game holds:
  every container count, experience figure and success chart is published, and
  the only fitted number is the **between-game overhead**, which two rows agree
  on and a third checks. Pays Thieving and Strength, and is the one activity
  here whose two skills **cannot both be maximised** - the Thieving route skips
  the sarcophagi that pay Strength.
- `chambers.py` - the Chambers of Xeric ladders, seven bats for Hunter and
  seven fish for Fishing, where **two** skills gate which one you are given and
  the lower of them decides. Four ticks each, no roll.
- `driftnet.py` - drift net fishing, read as the hourly table the wiki costs
  it as. Pays Hunter and Fishing, and **stops scaling at 70** in both.
**A computed method replaces the scrape for the *same task*, and loses to a
pin.** That is the layering above, and until recently `training.training_options`
did not apply it: a `ComputedMethod` was *added* to the scraped list, so a flat
guide figure won wherever the curve was below it - which is the low-level
stretch a curve exists to correct. Measured, five tasks were priced by the guide
over part of their range despite having a model, the worst being Underwater
Thieving at 84,560 flat against 1,005 at level 1. See `_modelled_tasks`.

- `stated.py` - the methods whose rate is stated rather than computed: a moss
  lizard's exact experience formula at a guessed pace, the lantern harpoon,
  Tempoross' harpoon tiers, the Fishing Trawler, Temple Trekking's tomes,
  Trouble Brewing, and Guardians of the Rift - the last being the one
  *arithmetic ceiling* here rather than an estimate, 250 fragments a game by
  six games by 5 experience. Every band from it is marked `guess`, a ceiling
  included, because what a cap allows is not what a player averages.
- `rumours.py` - Hunters' Rumours: an exact experience formula at an invented
  pace, so every band it produces is marked `guess`. The one number to set.
- `combat_xp.py` - combat XP, which is damage and almost nothing else. Owns the
  three gates and the two credits that each removed a wrong answer.
- `slayer.py` - Slayer's rate, which is a *distribution* rather than a chosen
  method, and the points economy that decides where you train.
  `task_kills_per_hour`/`best_modelled_candidate` prefer a reachable
  candidate's real `dps_bridge` simulation over the spreadsheet's own
  task-level clear speed - `defaults < scraped < computed < modelled` applied
  to the one number in this module that still deferred to the wiki once a
  model existed.
  **`MasterRate.hours_to_be_assigned` excludes the task itself from the
  average it waits on** - the wait is downtime on *other* tasks alone, and
  `estimate._task_hours` adds the gated monster's own kill time back
  separately, so folding it into both halves (an earlier version did, via
  `average_hours`'s blend) counted one fight twice. Caught on `Grotesque
  Guardians`: `Vannaka`'s `Gargoyles` task fed a wait computed from the
  ordinary Gargoyle's own rate - real, but not what gates the boss, and
  wrong to add on top of the boss's own kill time regardless of whose rate
  it used. **The exclusion also means `slayer/<master>/<task>`'s own
  `kills_per_hour` is never read by a gated item's price at all** - a
  correction there could never move the number it sat beside, which is a
  worse confusion than an unexplained one. `heuristics.wait_hours` (the
  `wait` branch, `Heuristics`' own docstring) is the fix: a leaf that *is*
  the wait, read first in both `_task_hours` and its hoisted twin
  `_kill_facts`, and named by the item's own `knobs` tuple instead of
  `slayer/...`. `gui/knobs.BRANCH_NOTES["wait"]` and `routes_view.
  resolve_knob`'s special case (the computed fallback needs the whole
  master's task list, which a bare `Heuristics` cannot supply) are the
  other two pieces.
- `prayer.py`, `farming.py` - the two skills whose limit is not a rate: bone
  supply, and a **schedule** measured in calendar days beside its active hours.
- `levels.py` - `infer_levels`/`goal_levels`/`reachable_providers` and the
  gating helpers. **The map records no skill levels**; the floor is read out of
  completed challenges. `resolve_levels` lays two more layers over that floor -
  the experience of an account linked to the map, then any set by hand for it -
  and **no layer may lower a skill**: a floor is a proof, so each is `max`ed
  against it and a figure that would have crossed it is reported as
  `BELOW_FLOOR` rather than quietly raised. The usual cause of a real
  disagreement is a *boosted* completion, which proves the boosted level.
- `inputs.py` - what `chunksim estimate` and the Estimate tab must agree about,
  assembled once, because the two had already drifted. Also `ReferenceBlobs`:
  the reference files read **once per invocation** and threaded, rather than
  four times by four callers - and the one place the four override layers are
  merged, so no reader can apply three of them. `aliases` is the fifth blob:
  the wiki's redirects for the item names upstream has not renamed yet.
  **`PricedLayers.levels` is `blobs.levels` alone, deliberately** -
  `priced_heuristics` needs the map's own hand-set floor to price the recipe
  layer at ("recipes first, then fights"), not a linked account's XP. But
  `estimate_answer` used to hand that same hand-only figure to `estimate()`
  as its `level_overrides`, which is what the Skilling section's
  `current_level` and its xp-still-needed are computed from - the eighth
  `{**infer_levels(state), **blobs.levels}` write `levels.py`'s own docstring
  above already names seven of, missed because it lives one module over. A
  skill with no hand override at all read the map's own ticked-off floor,
  never a linked account's real XP - Attack 75 shown against a real 99, and
  the hours to a target already passed off read as outstanding.
  `estimate_answer` now passes `effective_levels(state, layers.blobs)` to
  `estimate()` instead.
- `dps_bridge.py` - the seam to `osrs-dps`. **Optional import** - check
  `DPS_AVAILABLE`, never assume it. Prices only `reachable_providers`, which it
  imports rather than copying. **`best_kill` checks `fightscripts.SCRIPTS`
  first** - a phased boss is priced by its script, not by which of its
  ambiguous library versions dies quickest. `MELEE_SUBSTYLES` builds three
  more loadouts (`Stab`/`Slash`/`Crush`) from BiS picks `derived.bis.picks`
  has always carried but `build_loadouts` never read - additive for every
  caller before `costing/moons.py`, which is the one boss where a generic
  `Melee` loadout is wrong for two-thirds of the fight. `_apply_gated_bosses`
  corrects `Hespori`, `Skotizo`, `Giant Mole`, `Duke Sucellus`, `Vorkath`,
  `Nex` and `Zalcano`'s already-computed `Rate`s for what gates a real
  kill beyond the fight - see each one's own module.
  `_SIMPLE_GATED_CORRECTIONS` is the table for the five that are a pure
  function of their own kill time (`Zalcano`'s ignores that input
  entirely rather than correcting it - see its own module);
  `Skotizo`'s totem search also needs other monsters' rates, so it stays a
  named special case. Applied to `enrich`'s whole result every call, but to
  only the *freshly priced* slice of `enrich_incremental`'s, so a `Rate`
  already corrected on an earlier roll and merely carried forward by the
  reuse path is never corrected a second time. `keyed_chests`' two chests
  are a **synthesis**, not a correction - neither is ever combat-simulated,
  so neither reaches `monsters` for the `freshly_priced` guard to key off,
  and the guard does not apply: their rate is a pure function of *other*
  monsters' already-resolved rates, so re-deriving it costs nothing and
  always runs.
- `hespori.py` - Hespori's own drop table is already in the export (unlike a
  raid's chest), so the fix here is not a missing table but a missing
  overhead: `GROW_SECONDS` is the hespori seed's own published farming time,
  "1,920 minutes (3x640 min = 32 hours)" - not a guess, unlike almost every
  other overhead constant in this subpackage. `effective_seconds` adds it to
  whatever the fight itself takes, which `dps_bridge._apply_gated_bosses`
  applies directly to the `Rate` `price_monsters` already computed.
- `skotizo.py` - Skotizo needs a dark totem to fight at all, one consumed
  per attempt and assembled from three pieces dropped elsewhere in the
  Catacombs of Kourend, strictly in sequence ("dropped in that order...
  duplicates drop after all three are obtained"). `piece_chance` is the
  totem's own published `1/(500-H)`; `totem_seconds` **optimises** over
  `CANDIDATE_HITPOINTS` - six low-hitpoint monsters curated because the rest
  of the dungeon's `1/(500-H)` improvement "is very small" against their far
  slower kill times - rather than hardcoding the wiki's own named example
  (hill giants) as the answer for every map.
- `keyed_chests.py` - Bryophyta's and Obor's lair chests, `skillItems`
  activities with no stat block and so no scraped or simulated rate:
  `Heuristics.kills_per_hour` fell to `DEFAULT_KPH["regular"]` (150/hr),
  pricing everything inside the chest as though it opened on demand. It
  does not - each opening consumes a `Mossy key`/`Giant key`, a rare drop
  off the boss **or** off the ordinary giants sharing its name, whichever
  is cheaper. `CANDIDATE_CHANCE` is read straight off the export's own
  `drops` tables rather than guessed, and `effective_seconds` **optimises**
  over every candidate the same way `skotizo.totem_seconds` does, plus one
  default action to open the chest with the key in hand.
- `larran.py` - the same shape of gap as `keyed_chests.py`, for Larran's
  small and big chests, except the key's own rate is not a fixed drop
  fraction: "Wilderness Slayer tasks from Krystilia" is the only source, so
  `keys_per_hour` runs her whole `slayer.MasterRate` through the wiki's own
  published combat-level formula, its +20% Slayer-monster bonus
  (`chunk_info.slayer_monsters`' own list) and a superior's guaranteed key
  (`slayer.superior_spawns_per_hour`). The Wilderness Slayer Cave's further
  +15% is the one deliberately unmodelled piece - nothing here can say which
  of a task's locations counts as that specific sub-area - so the rate is a
  stated underestimate rather than a guess. Wired in `estimate.py` directly
  rather than through `dps_bridge._apply_gated_bosses`, because Krystilia's
  economy needs no DPS simulation to exist at all.
- `giant_mole.py` - her own drop table is already in the export; the fix is
  the published burrow mechanic ("every attack... has a 25% chance of
  causing her to burrow", between 50% and 5% health). Two guessed
  constants, stated as such: an assumed four-tick attack speed (the
  correction has no access to the map's real one, only an already-computed
  `Rate`) and a chase-time-per-burrow figure nothing publishes.
- `duke_sucellus.py` - two fixes in one module. `SCRIPT` pins the
  repeatable `Post-quest, Awake` version explicitly - unscripted, the
  330-hitpoint one-time Desert Treasure II quest fight (fought exactly
  once ever) is the fastest of three ambiguous `osrs_dps` versions and
  would have been priced as the whole activity, the same softest-form
  defect the Hydra's and Zulrah's own scripts fix. `effective_seconds`
  doubles the fight's own time for the preparation phase - `PREP_FRACTION
  = 1.0` is this project's own accepted estimate, not a wiki figure.
- `kalphite_queen.py` - two full-health forms (`osrs_dps`'s own "one shared
  pool" shape), `Crawling` weak to crush and `Airborne` weak to
  ranged/magic, matched exactly to the published "Protect from Magic and
  Missiles" / "Protect from Melee" mechanic. The one published, exact
  transition constant in this pairing: twelve seconds, stated on the
  boss's own page.
- `vorkath.py` - the same version-pin `duke_sucellus.py` needs
  (`Post-quest`, not the 460-hitpoint quest-only version), plus a
  correction shaped differently from every other boss module here: the
  published freeze/acid cycle repeats every six of *Vorkath's own*
  attacks throughout one continuous fight rather than at a health
  threshold, so it cannot be expressed as a `Phase.reduced_seconds`
  window and is instead a closed-form steady-state multiplier over
  `effective_seconds`.
- `phantom_muspah.py` - a ranged/melee alternation sized in *damage dealt*
  ("roughly every 100 damage in ranged form and 80 damage in melee form"),
  converted to `hp_share`s by that ratio rather than assumed equal, then a
  shield phase against a wholly separate `hitpoints=75` pool - "a shield
  which won't appear as actual damage on the boss," the third `Phase`
  shape, the same one `costing/sire.py`'s lung phase and this pairing's
  own `royal_titans.py` both are.
- `hueycoatl.py` - four targets, one published total (`5 x 250 + 2,500 +
  300 = 4,050`, matched exactly): five 250-hitpoint body segments, her own
  2,500 split in half by a published 50% shield threshold, and a separate
  300-hitpoint tail pool in between. **The tail phase is a stated
  ceiling**, not an accurate estimate - the published damage cap (4, or 9
  with crush as the highest attack bonus, missed hits rounded up to 1) has
  no path into `osrs_dps`'s ordinary combat formula, so a real tail phase
  runs longer than this prices it, especially for a small team.
- `nex.py` - one stat block throughout (`osrs_dps` carries no
  phase-specific version of her, unlike every other multi-phase boss in
  this subpackage), four bodyguards gating 20%-health thresholds, and a
  published 500-hitpoint heal on the final phase folded into her own
  `hp_share` rather than a separate phase. **Priced as the duo the wiki
  states fighting her effectively requires** - `PARTY_SIZE = 2`,
  `effective_seconds` halving the scripted total, the real semantic
  `costing/encounter.build`'s own `attackers` parameter states, applied
  separately because Nex's phase structure needs
  `costing/fightscripts.py` rather than `costing/encounter.py`.
- `royal_titans.py` - two identical bosses (`osrs_dps` gives `Eldric the
  Ice King` and `Branda the Fire Queen` the same `hitpoints=600` and the
  same `StatBlock`) fought together for one shared encounter - killing
  either requires killing both, so `hp_share=2.0` prices the whole
  1,200-hitpoint encounter against either one's own key, the third
  `Phase` shape with two different monsters standing in for "the same
  target killed twice."
- `vetion.py` - Vet'ion and Calvar'ion, another two-bosses-one-module pair,
  but for the opposite reason to `royal_titans.py`: `osrs_dps` carries each
  only as `#Normal`/`#Enraged`, which `dps_bridge.candidate_targets`
  correctly refuses as version-ambiguous (an `Enraged` suffix matches the
  sequential-phase marker), so the bare boss name had no route to a `dps`
  rate at all until this script gave it one. Six independent full-health
  targets per kill - each form to 50%, a fresh-pool pair of hellhounds mid-
  form, the form's remaining half - matched to the wiki's own published
  split. `HELLHOUND_DELAY_SECONDS` is this project's own guess (only
  Vet'ion's page states the resistance window; charged on both since the
  fight is otherwise identical). No `Phase.styles` restriction, the same
  reasoning `royal_titans.py` gives: `dcrush=-10` against defence in the
  hundreds is a weakness the ordinary style search already finds unaided.
  **Its own oracle test cannot assert a `kph` ratio**: both guides describe
  "High melee stats" in prose rather than a `{{SCP|Attack|...}}` template,
  so `oracle.py`'s unstated-level floor (never assumed maxed) prices a
  level-1 weapon and lands two orders of magnitude short - the harness
  being conservative, not the script being wrong, per `oracle_ttk`'s own
  docstring. `tests/test_costing_vetion.py` substitutes maxed levels for
  the guide's unstated ones instead, following `grotesque_guardians.py`'s
  and `zulrah.py`'s precedent for the same gap.
- `zalcano.py` - the one gated boss where the simulated kill time is not
  real at all rather than merely incomplete: she is "immune to
  traditional combat damage," fought with Mining/Smithing/Runecraft
  actions no combat style represents, and `osrs_dps` carries her with
  every defence bonus at zero because the library has no notion of that
  immunity. `effective_seconds` therefore **ignores its own argument** and
  returns `Money making guide/Killing Zalcano`'s own published group
  throughput (48 kills/hour on a themed world) rather than correcting a
  number that was never a real answer. Her own `drops` table already
  carries `Smolcano` at the correct published `1/2,250`, so - unlike
  every chest-shaped fix in this subpackage - nothing else needed adding
  once the rate itself was right.
- `fightscripts.py` - the primitive a phased boss needs and
  `costing/encounter.py`'s raid shape does not fit: a `Phase` is a *slice* of
  one kill (`hp_share`), not a whole kill multiplied (`FightPlan.count`), and
  carries its own reduced-output window (`reduced_seconds`/
  `reduced_dps_fraction`) for a vent, a totem, anything that costs real but
  diminished time rather than none at all. `hp_share` takes three different
  shapes depending on the boss - one shared pool (Hydra, Zulrah), several
  independent targets each fully depleted (Grotesque Guardians), or one
  small target killed several times over (Abyssal Sire's respiratory
  systems) - see the `Phase` docstring. `Phase.styles` restricts which
  combat styles a phase will even try, for the rare case (Grotesque
  Guardians' Dawn and Dusk) where the *rest* of the fight, not the numbers,
  rules a style out entirely and `osrs_dps`'s own stat block does not
  encode that. Pure - no `osrs_dps` import; `costing/dps_bridge._scripted_kill` is what prices one.
- `hydra.py` - the Alchemical Hydra's script: four phases, each an exact
  `osrs_dps` key, `hp_share=0.25` apiece straight off the wiki's own
  825/550/275/0 thresholds. **Fixed the softest-form pick**: before this
  existed, `best_kill`'s ordinary version resolution priced a quarter of the
  boss's health bar as if it were the whole fight. `VENT_SECONDS` is this
  project's own figure - nothing publishes how long finding a vent takes -
  and every rate this module produces is a `GUESS` because of it, however
  published the 75% reduction and the phase thresholds are.
- `oracle.py` - prices a money-making guide's own stated gear and levels, so
  a scripted boss's `kph` can be checked against the guide's **without** the
  guide's near-max assumptions inflating a chunk map's own gear-restricted
  answer. Single-boss guides only - a raid's or a wave minigame's `kph`
  describes a *run*, not one monster, and comparing against it would not be
  the same question. Two known gaps, both measured rather than guessed at: a
  guide's prose often never names a body, legs or ammo slot at all
  (`"Ranged armour"` - `tests/test_costing_hydra.py` measures the cost), and
  ranking a magic weapon on `magic_damage` alone ties a powered staff against
  a melee weapon at zero, since a staff's real damage comes through
  `attack_magic` instead - found by Phosani's Nightmare's own guide handing
  a magic loadout a crush mace, fixed in `_RANK_FIELDS`, pinned in
  `tests/test_costing_oracle.py`.
- `nightmare.py` - Phosani's Nightmare, priced as **one continuous fight**
  rather than the page's four sub-phases: the totem mechanic triggers "a
  powerful hit" against her own health, and nothing publishes how that burst
  divides across the library's 3200 hitpoints, so splitting `hp_share` the
  way `costing/hydra.py` does would need a number this project does not
  have. What *is* modelled is the two mechanics asked for by name - the
  totem ("pillar") phase and the sleepwalker phase - as zero-rate downtime
  (`reduced_dps_fraction=0.0`) on top of the plain damage race, both guessed
  constants grounded in the wiki's own published counts (4 totems needing
  200 charge each; 2/3/4 sleepwalkers at the ends of phases 1-3). Its own
  oracle comparison found and fixed two real bugs in `costing/oracle.py`
  itself - see that entry.
- `zulrah.py` - one health bar, three forms, priced as a **time-weighted
  blend** rather than an HP split: unlike the Hydra's published phase
  thresholds, nothing states what fraction of a kill each form takes, so the
  three `hp_share`s are read off `Zulrah/Strategies`' own phase-by-phase
  rotation tables - 173 attacks summed across all four published rotations,
  95/16/62 by form. **Fixed the same softest-form bug Hydra's script did**,
  worse here: the easiest form (Serpentine, where `defence_magic` is a
  *bonus*) was priced for the whole 500 HP, when two much tankier forms are
  not optional in a real fight. No oracle test - her own guide recommends a
  hybrid loadout switched per form, which `costing/oracle.py` cannot build.
- `sire.py` - the Abyssal Sire: a lung phase killing four `Respiratory
  system` targets (50 hp each, none of it the Sire's own bar) followed by
  three combat phases split at the wiki's own published 210/140-hitpoint
  thresholds (215/70/140 of 425). **Found and fixed a real gap in
  `dps_bridge._scripted_kill` itself**: the lung phase's target is a
  genuinely different monster, not an `Abyssal Sire#...` key, so the
  candidate list `best_kill`'s ordinary callers already build (scoped to the
  boss's own name) never carries it - `_scripted_kill` now falls back to a
  passed-through `MonsterIndex` for exactly this case, and every real caller
  in `dps_bridge.py` threads one through. `TRANSITION_SECONDS` is this
  project's own figure for the published-but-undurationed 50% transition
  reduction, applied to all three combat phases (unlike the Hydra's one
  excepted phase). No oracle test: the guide's own `Item=` field points at a
  separate phase-by-phase equipment page rather than naming gear itself, so
  `gear_from_guide` correctly resolves to nothing - see
  `tests/test_costing_sire.py::TestAgainstTheGuide` for what that test
  checks instead.
- `grotesque_guardians.py` - Dawn and Dusk, each fought to ~50% and finished
  later - the "several independent targets, each fully depleted" shape
  `fightscripts.Phase` names this boss as the worked example of, `hp_share`s
  summing to `2.0` across the script rather than `1.0`. **The first script
  needing `Phase.styles`**: both monsters carry ordinary all-zero defence in
  `osrs_dps`, so nothing there marks that Dawn "cannot be targeted by
  non-halberd melee weapons" or Dusk is "completely immune to magic and
  ranged damage" - an unrestricted search would happily price a style that
  deals zero damage in-game. `TRANSITION_SECONDS` is the one guessed number,
  for the one flight-transition the changelog confirms still happens. No
  formal oracle test, matching `zulrah.py`'s precedent: the guide
  recommends a hybrid Ranged/Melee loadout `oracle.py`'s one-style builder
  cannot construct, so `tests/test_costing_grotesque_guardians.py` checks a
  hand-built mixed loadout against the guide's `kph=24` for order of
  magnitude instead. **Araxxor and Cerberus were both considered for this
  round and refused**: Araxxor's real enrage mechanic has no separate
  `osrs_dps` key to price against (one bare `Araxxor` entry despite the
  wiki's own infobox naming an enraged version), and fabricating defence
  numbers by hand would invent exactly what this project has no authority
  to reproduce; Cerberus's Summoned Souls costs prayer and damage but never
  stops the player attacking her directly, so it is a resource cost, not
  the downtime shape a `Phase` prices. Neither got a module - there was
  nothing to write one about.
- `yama.py` - two `osrs_dps` stat blocks for her own bar (`hp_share=2/3` +
  `1/3` against the published 66.6%/33.3% thresholds, exact thirds rather
  than the page's rounding) plus a Judge of Yama fought twice in between,
  the "small target killed several times over" shape (`hp_share=2.0`). The
  Judge's own "always land as both successful and maximum hits" and
  alternating-style requirement have no path into `osrs_dps`'s ordinary
  formula, so that phase is a **ceiling in the slow direction**, same
  posture as `nightmare.py`'s totems.
- `doom_of_mokhaiotl.py` - eight independent full-health targets, one per
  delve level (`#Delve 1`-`#Delve 8`, hitpoints rising 525 to 675, matched
  exactly), each carrying a guessed `MECHANIC_SECONDS_PER_DELVE` for the
  shield/larvae/rock-throw mechanics none of which states its own downtime.
  **The one thing this module states rather than resolves**: the wiki
  publishes that loot rolls once per delve level, but the export's own
  drop table is one flat rate with no notion of depth - whether that rate
  means one level's roll or a whole climb's is not knowable from what
  either side publishes, and an hours figure for a specific unique should
  be read with that in mind.
- `dps_overhead.py`, `recipe_overhead.py`, `gathering_overhead.py` - the
  harnesses that fitted the overhead constants. **No caller in `src/`**; they
  exist to be re-run when someone doubts them.
"""
