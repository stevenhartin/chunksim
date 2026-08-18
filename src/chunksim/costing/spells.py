"""A cast priced from the wiki's own speed, for the spells nothing else reaches.

**Magic was the worst-covered skill in the project and the missing number was
one field.** The export lists 175 primary Magic challenges and 57 of them had a
rate; the rest were `Cast ~|high level alchemy|~` and its kind - the archetypal
Magic training method, absent entirely. What was already here is the *cost*:
`infobox_spell` states the runes a cast eats, and `heuristics.spell_materials`
has been joining them onto the export's `Cast ...` tasks for a while, 190 of
214. What was missing is how long a cast takes, and the infobox states that
too, as `|speed = 5 ticks`.

**It is not in the Bucket, which is why nobody had it.** `infobox_spell`
exposes six fields - cost, exp, level, slayerlevel, spellbook, type - and a
duration is not among them, so `chunksim heuristics` now sends the same page
names back through `fetch_wiki_pages` and reads the line. Four batched requests
for 201 pages; 200 state a speed and 156 of the export's 190 joined tasks end
up timed.

### Only utility spells, and upstream's own field says which

The infobox's `type` splits the 190 into **Combat 86, Utility 53, Teleport
51**, and only one of those three has a speed that is the whole cost of a cast:

- **Utility** is a spell aimed at an item in your inventory - alchemy,
  superheat, the enchants, charge orbs, bones to bananas, plank make, tan
  leather. You cast, the item changes, you cast again. `speed` is the loop.
- **Teleport** is the animation and nothing else. `Cast ~|camelot teleport|~`
  is 3 ticks to leave and then however long it takes to get back somewhere you
  can cast it again, which no page states. Priced on the animation alone a
  teleport reads 111,000/hr. **Refused here and answered elsewhere**: a
  teleport is only castable twice at a *lectern*, and `costing/lectern.py`
  prices that from the tablet's own recipe. Where a map can build no lectern
  that makes the tablet, the teleport has no rate at all - see
  `refuse_untabled`, which is why that is the honest answer rather than a gap.
- **Combat** is priced here too, and the figure is the **base experience a
  cast pays whether or not it lands**. That is a real method - splashing is
  what the whole of low-level Magic training used to be - and every term it
  needs is published: 5 ticks (checked on 22 combat spells, all flat, none
  carrying the `(N on autocast)` aside an earlier version of this docstring
  claimed), the base experience, and the runes.

  **What it deliberately does not count is damage experience.** A cast that
  hits also pays `2 x damage`, and that depends on the target, the gear and
  the gates - which is `costing/combat_xp.py`'s question and is answered there
  far better than a bare speed could. So this is a *floor* on casting the
  spell, correct for splashing and conservative for fighting, and it never
  competes with the combat answer because `training_bands` takes the maximum.

  This module used to refuse the kind outright on the grounds that
  `combat_xp.py` "already prices it". That is true of the *skill* and false of
  these *challenges*: `combat_xp` keys its rates on `monster_stats/<monster>`,
  so all 56 combat `Cast ...` methods read `unpriced` while Magic itself was
  covered - the model having an answer to a different question.

### The materials are the export's, not the infobox's

`spell_materials` carries the runes, and the runes are not the whole cost:
`Cast ~|bones to bananas|~` eats a **big bone**, `Cast ~|lvl-3 enchant|~` a
piece of ruby jewellery, `Smelt a ~|steel bar|~ with superheat item` an iron
ore and a coal. Upstream lists every one of them in the challenge's own
`Items`, so that is what is charged - through the same `input_seconds` closure
`recipe_rates` uses, so the walk answers "how long to get a big bone" once and
both layers spend the same answer. Priced on runes alone bones to bananas
reads 150,000/hr, which is a spell that would have won the whole climb.

**So the rate is all-inclusive and says so.** `SPELL_SOURCE` joins
`RECIPE_SOURCE` in `training._ALL_INCLUSIVE_SOURCES`: the figure already has
the materials in it and `material_seconds_per_xp` must not add them again.

### Where it sits: under the recipes, over the scrape

`apply` runs *after* `recipe_rates.apply` and fills only what that left at the
floor or on a guide - the same `REPLACEABLE` whitelist, imported rather than
restated. A recipe knows which variant of an action it describes and carries
its own tick cost; where both reach a task the recipe is the more specific
claim. Where nothing reaches it, a cast timed by the wiki and charged by the
export beats a money-making guide, which is the layering's standing rule.

Pure: the challenges, the costs and the pricing closure all come in as
arguments.
"""

from __future__ import annotations

from typing import Any, Callable, Container, Mapping

from chunksim.costing.heuristics import MaterialCost, Rate
from chunksim.costing.recipe_rates import REPLACEABLE
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.model.summary import _mapping

#: What this labels its rates. A separate source from `recipe`'s because the
#: two are separate claims, and because `training._ALL_INCLUSIVE_SOURCES` has
#: to name it.
SPELL_SOURCE = "spell"

#: The tier a spell rate lands at - the same one a recipe rate uses, since both
#: are this project computing an answer rather than reading one.
SPELL_MATCH = "computed"

#: The `infobox_spell` types whose stated speed is the whole cost of a cast.
#: See the module docstring for why `Teleport` is refused rather than
#: approximated, and for what a `Combat` figure here does and does not claim.
PRICED_KINDS = frozenset({"Utility", "Combat"})

#: One game tick, in seconds.
TICK_SECONDS = 0.6

#: Upstream's marker for an item a challenge consumes rather than merely needs.
#: Stripped before pricing, exactly as `estimate._route_hours` strips it.
CONSUMED = "*"


def castable(costs: Mapping[str, MaterialCost]) -> dict[str, MaterialCost]:
    """The entries this module will price: utility spells with a stated speed.

    A zero speed is dropped with the untimed ones. Magic Imbue states `0
    ticks`, and an action priced at no time is the fastest method in the game -
    the same refusal `recipe_rates.rate_for` makes of an untimed recipe.
    """
    return {
        task: cost
        for task, cost in costs.items()
        if cost.kind in PRICED_KINDS
        and cost.ticks is not None
        and cost.ticks > 0
        and cost.experience > 0
    }


def cast_seconds(cost: MaterialCost) -> float:
    """Seconds one cast takes, before its materials."""
    return (cost.ticks or 0.0) * TICK_SECONDS


def rate_for(
    challenge: Mapping[str, Any],
    cost: MaterialCost,
    input_seconds: Callable[[str, float], float | None],
) -> float | None:
    """Experience an hour for one cast, or `None` where an input has no route.

    **Refused rather than quoted**, on the rule `recipe_rates.rate_for` states:
    tick-math over inputs nothing can price is a made-up number, and the
    inputs in question are exactly the ones too hard to price.
    """
    seconds = cast_seconds(cost)
    for item in challenge.get("Items") or ():
        if not isinstance(item, str):
            continue
        priced = input_seconds(item.replace(CONSUMED, "").strip(), 1.0)
        if priced is None:
            return None
        seconds += priced
    if seconds <= 0:
        return None
    return cost.experience * 3600.0 / seconds


def unroutable(
    challenge: Mapping[str, Any],
    input_seconds: Callable[[str, float], float | None],
) -> str:
    """The first item of `challenge` the walk cannot route, or `""`.

    **The diagnosis behind a refused cast**, so `unpriced` can say which
    reagent it wanted rather than only that it wanted one - the same job
    `recipe_rates.unroutable` does for a dropped recipe, and called on the
    same terms: only once `rate_for` has already returned `None`, over the
    memoised closure, so the succeeding path pays nothing for it.
    """
    for item in challenge.get("Items") or ():
        if not isinstance(item, str):
            continue
        wanted = item.replace(CONSUMED, "").strip()
        if input_seconds(wanted, 1.0) is None:
            return wanted
    return ""


def computed_rates(
    chunk_info: ChunkInfo,
    valid: Mapping[str, Mapping[str, Any]],
    costs: Mapping[str, MaterialCost],
    input_seconds: Callable[[str, float], float | None],
    dropped: dict[str, str] | None = None,
) -> dict[str, float]:
    """`{task: experience an hour}` for every reachable utility spell.

    Only methods in `valid`, so this inherits the derivation's reachability
    gate rather than inventing a second one - and only `Primary` ones, since a
    challenge upstream does not call a training method is not one here either.
    """
    challenges = _mapping(chunk_info.challenges, "Magic")
    priced: dict[str, float] = {}
    for task, cost in castable(costs).items():
        if task not in (valid.get("Magic") or {}):
            continue
        challenge = challenges.get(task)
        if not isinstance(challenge, dict) or challenge.get("Primary") is not True:
            continue
        rate = rate_for(challenge, cost, input_seconds)
        if rate is not None and rate > 0:
            priced[task] = rate
        elif dropped is not None:
            # Diagnosed only on failure - see `unroutable`.
            dropped[task] = unroutable(challenge, input_seconds)
    return priced


def apply(
    training: Mapping[str, Mapping[str, Rate]],
    computed: Mapping[str, float],
    pinned: frozenset[str] = frozenset(),
) -> dict[str, dict[str, Rate]]:
    """`training` with a spell rate wherever nothing better already describes it.

    **Run after `recipe_rates.apply` and sharing its whitelist.** A recipe
    knows which variant of an action it describes and carries its own tick
    cost, so where both reach a task the recipe is the more specific claim and
    keeps it; `REPLACEABLE` is imported rather than restated so the two
    layers cannot drift about what a computed rate may overwrite.

    A hand pin outranks both, as everywhere else.
    """
    merged = {task: dict(skills) for task, skills in training.items()}
    for task, value in computed.items():
        if task in pinned:
            continue
        existing = merged.get(task, {}).get("Magic")
        if existing is not None and existing.match not in REPLACEABLE:
            continue
        merged.setdefault(task, {})["Magic"] = Rate(
            value=value, source=SPELL_SOURCE, match=SPELL_MATCH
        )
    return merged


#: The infobox kind whose only repeatable form is a tablet - see
#: `costing/lectern.py`.
TELEPORT_KIND = "Teleport"

#: The `Rate.match` tiers a teleport with no tablet route loses. The same three
#: `recipe_rates.REPLACEABLE` names, and for the same reason: a scrape and the
#: floor are claims this project is entitled to overrule, and a model is not.
REFUSED_WHEN_UNTABLED = REPLACEABLE


def refuse_untabled(
    training: Mapping[str, Mapping[str, Rate]],
    costs: Mapping[str, MaterialCost],
    tabled: Container[str],
    pinned: Container[str] = frozenset(),
) -> dict[str, dict[str, Rate]]:
    """`training` with the scraped rate removed from every untabled teleport.

    **A bare teleport cast is not a training method**, which is the whole
    reason `castable` refuses the kind: the cast moves you somewhere you cannot
    cast it again. So the only honest rate a teleport can carry is a tablet
    rate, and a map that can build no lectern making that tablet has no method
    - not a slow one.

    What this stops is the shape the marlin did: `mmg:Money making guide/
    Creating Varrock teleport tablets` is a real figure for a real method, and
    on a map with no player-owned house it is a figure for a method that map
    does not have. Measured, it is one task on each cached map - Varrock on the
    reference map, which builds no lectern at all, and teleport to house on the
    second, which builds every lectern below the mahogany eagle one.

    A hand pin survives, and so does anything above the scrape: a `modelled`
    rate is a model's own answer about a whole activity rather than a claim
    about which lectern was built.
    """
    merged = {task: dict(skills) for task, skills in training.items()}
    for task, cost in costs.items():
        if cost.kind != TELEPORT_KIND or task in tabled or task in pinned:
            continue
        rate = merged.get(task, {}).get("Magic")
        if rate is not None and rate.match in REFUSED_WHEN_UNTABLED:
            del merged[task]["Magic"]
    return merged
