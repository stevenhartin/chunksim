# heuristics/

Hand-written corrections to the numbers `fray estimate` spends. Checked in, so
they are diffable, survive a re-scrape, and travel with the repo — which
nothing under the gitignored `cache/` would.

## The three layers

```
defaults (heuristics.py)  <  scraped (cache/wiki_rates.json)  <  overrides.json
```

The deepest value wins, key by key, so pinning one quest's hours does not
erase the length recorded beside it. `fray heuristics` regenerates the middle
layer and reports any value here that now disagrees with it — the override
still wins, it just says so rather than winning silently.

## What is worth correcting

Run `fray estimate` and look at what it flags:

- **Skills using the default training rate.** The money-making guides only
  cover 243 of the export's 2,710 training methods, because most ways of
  training a skill do not make money and so have no guide. Everything else
  sits at 1,000 xp/hr, deliberately low so it looks slow rather than free.
  These are the entries that move a total.
- **A low slayer coverage figure.** Below about 50%, the master's rate has
  been renormalised over so few reachable tasks that it flatters the map.
- **Anything in `unpriced`.** Those are tasks whose items have no route this
  project can price at all; a `monsters` or `slayer` entry may fix them.

`cache/wiki_rates.json` is the full generated config and lists *every* quest,
monster and training method in the export, defaulted where nothing was found.
Copy the entry you want to change out of it and into the matching section
here, then edit the value.

## Sections

| Section | Key | Shape |
|---|---|---|
| `levels` | skill | your current level, an integer |
| `quests` | quest name | `{"hours": 4.0}` |
| `monsters` | monster name | `{"value": 27.0}` — kills per hour |
| `training` | the full task name | `{"<skill>": {"value": 50000.0}}` — XP per hour |
| `slayer` | **master**, then task | `{"mean_count": 165, "xp_per_kill": 106, "kills_per_hour": 340, "extended": false}` |
| `rarities` | a rate word | a probability, e.g. `{"varies": 0.02}` |

`levels` has no scraped layer and exists only here. **The map records no
current skill levels** — `maxSkill` is a declared cap and `passiveSkill` is
what is reachable *without* a training method — so the estimator counts from
the passive floor unless you say otherwise. Every skill row prints the level
it assumed, so a wrong one is visible.

Example:

```json
{
  "levels": {"Mining": 74, "Slayer": 62},
  "monsters": {"General Graardor": {"value": 30.0}},
  "training": {
    "Mine ~|sunstone rocks|~": {"Mining": {"value": 62000.0}}
  }
}
```

The task names in `training` are the export's own, markup included. Copy them
verbatim from `cache/wiki_rates.json` rather than retyping them.

## Slayer masters

`fray estimate skilling` prints every reachable master with a `pts/task`
column: points earned on the tasks you can do, less the 30 you pay cancelling
the ones the master offers but your chunks cannot reach. A **negative** figure
means training there bleeds points however good the XP looks.

Tasks the master will not offer at all — level-gated, quest-gated — cost
nothing and are not counted as skips. Only what you are handed and have to
throw away is.

Point values are the wiki's published figures. Override per master:

```json
{"masters": {"Vannaka": {"points": 8, "skip_cost": 30}}}
```

Worth doing if you have a diary that raises them (Konar 18 → 20 with Kourend
& Kebos elite, Nieve 12 → 15 with Western Provinces elite), which nothing
here detects.

## Extended slayer tasks

`slayer` is keyed by **master first**, because assignment sizes differ by
master — Duradel sends you for 165 abyssal demons, Krystilia for 100.

Each task carries both sizes: `mean_count` is the ordinary assignment and
`extended_count` the one with the *Extended* unlock bought from the slayer
rewards shop. **Extended is off by default**, because it is a paid unlock and
assuming it would silently lengthen every task for someone who has not bought
it. Turn it on per task:

```json
{
  "slayer": {
    "Krystilia": {
      "Abyssal demons": {"extended": true},
      "Ankous": {"extended": true}
    }
  }
}
```

Longer tasks are not automatically better: they shift the time-weighted
average towards whatever you are extending, so a slow task extended can lower
a master's overall XP rate. `fray estimate skilling` prints the rate, so
compare before and after.

`extended_count` is `0.0` for tasks that have no extended size, and the flag
is ignored there rather than inventing one.
