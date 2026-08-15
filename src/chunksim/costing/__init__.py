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
  `Output`. Owns `defaults < computed < scraped < overrides`, **the one place a
  computed number does *not* beat the scrape**. Also `trip_seconds`: a bank
  trip's share, scaled by what an action consumes.
- `production.py` - what a production method consumes, for the methods no
  `{{Recipe}}` describes, read off `Module:Skill calc` by way of the gathering
  tables. **It supplies a material cost, never a rate**: a calculator row has
  no ticks, so it composes with whatever rate wins rather than competing with
  one. Joins on upstream's own `~|...|~` span.
- `gathering.py` - the generic node model for Fishing/Mining/Woodcutting/
  Hunter/Thieving, and the exact skilling-success formula. Owns
  `defaults < scraped < modelled < overrides`, so **it beats the scrape where
  `recipe_rates.py` loses to it**, and the docstring says why. Per-skill quirks
  are `SkillProfile` fields, never branches, and the four inactivity shapes
  (duty cycle, flat charge, restock floor, stun) are what separate a model from
  a fitted constant. A *cascade* is the one shape that is not inactivity:
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
- `chambers.py` - the Chambers of Xeric ladders, seven bats for Hunter and
  seven fish for Fishing, where **two** skills gate which one you are given and
  the lower of them decides. Four ticks each, no roll.
- `driftnet.py` - drift net fishing, read as the hourly table the wiki costs
  it as. Pays Hunter and Fishing, and **stops scaling at 70** in both.
- `stated.py` - the two whose rate is stated rather than computed: a moss
  lizard's exact experience formula at a guessed pace, and Trouble Brewing,
  which is a figure and nothing else. Every band from it is marked `guess`.
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
  merged, so no reader can apply three of them.
- `dps_bridge.py` - the seam to `osrs-dps`. **Optional import** - check
  `DPS_AVAILABLE`, never assume it. Prices only `reachable_providers`, which it
  imports rather than copying.
- `dps_overhead.py`, `recipe_overhead.py`, `gathering_overhead.py` - the
  harnesses that fitted the overhead constants. **No caller in `src/`**; they
  exist to be re-run when someone doubts them.
"""
