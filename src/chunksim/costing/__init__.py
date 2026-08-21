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
- `estimate.py` - the four buckets over the **active** set. **Costs the unique
  *item*, not the task**, and **clamps per source**. Owns the item walk and the
  gates on it, and records the `Heuristics` entries each number was read off -
  where they are read, never reconstructed.
- `training.py` - how fast a skill goes. **A climb is priced band by band as
  methods unlock**, so the floor can only ever be the first band. Each band
  carries the override path behind its rate, set where the rate is chosen.
- `recipe_rates.py` - a recipe turned into an XP rate, joined exactly on
  `Output` **and on the wiki's own variant label**, so the two ways of smelting
  a bar are two answers rather than one given twice. Owns
  `defaults < scraped < computed < overrides`, and **an ambiguous join may fill
  the floor but may not replace the scrape** - one recipe reaching several
  tasks is the guard the flip needed, and it is keyed on the recipe chosen, not
  on the item made. Also `trip_seconds`: a bank trip's share, scaled by what an
  action consumes.
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
- `tempoross.py` - the wiki's rate for four harpoons at five levels each,
  which **replaced three invented tier figures in `stated.py`**. Best harpoon
  by *rate* rather than by tier, since the tiers are not ordered. Also the
  **cooking** regime, which is the page's other table and is one flat number
  because every part of it is fixed: the `max permits` walkthrough counts out
  55 fish a game, a game is 12 minutes including the wait, and a harpoonfish
  pays 10. The two challenges are two choices rather than halves of one method.
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
- `sepulchre.py` - the Hallowed Sepulchre, counted in ticks: a lap runs floors
  1 to N in order, so the Strategies page's tick-perfect floor times plus six
  ticks a staircase give the Agility rate, and fifteen more per floor for one
  coffin give the **Thieving** one, which no rate table anywhere states. The
  published `Realistic No looting XP/hour` column is kept as the oracle: no
  constant overhead reconciles it with tick-perfect play, so a `MISTAKE_FACTOR`
  on the floor time is calibrated to 91,805 for five floors - inside what a
  good player sustains, and 1.04x the wiki's own row. `GUESS`, because the
  staircase, the lobby return and the mistake factor are all invented.
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
- `prayer.py`, `farming.py` - the two skills whose limit is not a rate: bone
  supply, and a **schedule** measured in calendar days beside its active hours.
- `levels.py` - `infer_levels`/`goal_levels`/`reachable_providers` and the
  gating helpers. **The map records no skill levels**; the floor is read out of
  completed challenges.
- `inputs.py` - what `chunksim estimate` and the Estimate tab must agree about,
  assembled once, because the two had already drifted. Also `ReferenceBlobs`:
  the reference files read **once per invocation** and threaded, rather than
  four times by four callers - and the one place the four override layers are
  merged, so no reader can apply three of them. `aliases` is the fifth blob:
  the wiki's redirects for the item names upstream has not renamed yet.
- `dps_bridge.py` - the seam to `osrs-dps`. **Optional import** - check
  `DPS_AVAILABLE`, never assume it. Prices only `reachable_providers`, which it
  imports rather than copying.
- `dps_overhead.py`, `recipe_overhead.py`, `gathering_overhead.py` - the
  harnesses that fitted the overhead constants. **No caller in `src/`**; they
  exist to be re-run when someone doubts them.
"""
