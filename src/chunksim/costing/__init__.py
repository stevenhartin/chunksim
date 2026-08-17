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
- `gotr.py` - Guardians of the Rift as **one minigame, not twelve rune
  methods**. The rune is the game's decision - two portals, one elemental and
  one catalytic - so the curve is the *rune mix* at a level, and throughput is
  recovered from the published bands rather than modelled. Bands carry the
  minigame's level, not the rune's, which is what stops a level-1 player being
  offered it.
- `herblore.py` - the one duration the wiki does not publish: cleaning a grimy
  herb is not tick-gated, so its `{{Recipe}}` carries `ticks = ""` and
  `recipe_rates` refused all eighteen. Timed from the bank cycle instead - 18
  ticks an inventory of 28 - and **detected from the recipes rather than
  listed**, so the `Degrime` spell variants stay out.
- `chisel.py` - the other untimed duration, and it is **zero**: a dark essence
  block is chiselled *while running* to the blood or soul altar, on a trip the
  rune's own recipe already pays for. Names the one output rather than reaching
  for a rule over chisels, because a gem cut at a bank is emphatically not free.
  The export carries no challenge for it, so a stated zero can only ever be read
  by the item walk and can never become a training rate of its own.
- `shortcuts.py` - an Agility shortcut priced from the attempt: eight ticks,
  the experience its own page states, the experience a *failure* pays, and the
  published success curve. Replaced an 18-second cycle whose comment called it
  "a stated target, not a measurement". **Upstream's `Primary` flag is already
  the "is this a training method" answer here** - 93 of 162 shortcuts pay
  nothing and are non-primary, so no filter is needed.
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
- `wintertodt.py` - one game paying Woodcutting, Fletching and Firemaking, and
  the only activity here with **no chance in it at all**: the wiki states its
  experience as multipliers on your level, so the rate is those times a count
  of games. Replaced a hand-written 400,000/hr that was one number for a method
  linear in the level.
- `tempoross.py` - the wiki's rate for four harpoons at five levels each,
  which **replaced three invented tier figures in `stated.py`**. Best harpoon
  by *rate* rather than by tier, since the tiers are not ordered.
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
- `sepulchre.py` - the Hallowed Sepulchre's five floors, which the scrape
  priced at **one** rate from level 52 to 87 where the published table runs
  40,000 to 98,500. Prices the no-looting column, for the reason `tempoross`
  prices not-cooking.
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
