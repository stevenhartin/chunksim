"""Cutting a fish up with a knife, which upstream and the wiki name differently.

**A money-making guide about *cooking* a marlin was pricing the knife.** The
export carries both actions - `Cook a ~|marlin|~` at Cooking 91 for 225
experience, and `Cut up a ~|raw marlin|~` at Cooking **1** for **2** - and
`mmg:Money making guide/Cooking raw marlin` joined both, because the guide's
own activity normalises to the same words the cut-up's task does. So a
level-1, two-experience knife action carried **292,500/hr** and owned the
entire Cooking climb from 1 to 99 on the everything-unlocked map. Yellowfin
did the same at 260,000. That is the failure `heuristics._best_match`'s
docstring warns about in its sharpest form: a join that misses reads as a gap,
and a join that hits the *wrong* action reads as a fast method.

**The fix is the layering rather than a patch to the matcher**: a recipe
outranks a scrape, so the cut-up only needs its own recipe to join. It could
not, and the reason is a vocabulary difference neither side is wrong about.
Cutting a fish yields a bundle - offcuts, and a chance at scales or a beak -
so upstream names the `Output` **`Marlin loot`**, a name the wiki has no page
for. The wiki files the action under what the knife actually produces, `Fine
fish offcuts`, one `{{Recipe}}` per fish it accepts.

**So the join is on the *input*, and only inside this family.** A challenge
whose `Output` ends in `loot` and whose `Items` name a `Knife` is the knife
action on the fish beside it; the recipe is the one whose *material* is that
fish and whose output is an offcuts item. Joining on the fish alone would be
ambiguous and badly so - `Raw marlin` is also the material of `Marlin` (225
xp) and `Burnt marlin` - which is why `CUT_OUTPUTS` is the other half of the
key. Where a fish appears in two of them (a squid yields `Fine fish offcuts`
*and* a `Squid beak`) both recipes are 2 experience at 3 ticks, so which one
wins cannot move a number.

Measured on the uber map, this displaces the two guide rates and prices five
species; `Cut up a ~|leechfin|~` has no `{{Recipe}}` at all and stays
unpriced, which is the honest state for a join nothing here can verify.

Pure: the challenges and the recipes both come in as arguments.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from chunksim.remote.recipes import Recipe

#: The suffix upstream gives a bundle rather than an item.
LOOT_SUFFIX = " loot"

#: The tool that makes this a cut-up rather than a cook.
KNIFE = "knife"

#: What the wiki says a knife actually produces from a fish. **The other half
#: of the key**: joining on the fish alone would reach the cooked and burnt
#: recipes beside it, which are the same input and a different action.
CUT_OUTPUTS = frozenset({"Fish offcuts", "Fine fish offcuts", "Squid beak"})


def _bare(item: str) -> str:
    """An `Items` entry without upstream's consumed marker."""
    return item.replace("*", "").strip()


def cut_recipes(
    challenges: Mapping[str, Any], recipes: Sequence[Recipe]
) -> dict[str, tuple[Recipe, ...]]:
    """`{task: recipes}` for every cut-up challenge a `{{Recipe}}` describes.

    Absent from the result means no recipe names that fish, which the caller
    must treat as "no rate" rather than filling with a sibling's: the species
    differ in what the bundle contains, and the experience is the one thing
    this join is for.
    """
    by_material: dict[str, list[Recipe]] = {}
    for recipe in recipes:
        if recipe.output not in CUT_OUTPUTS:
            continue
        for material in recipe.materials:
            by_material.setdefault(material.name.lower(), []).append(recipe)

    found: dict[str, tuple[Recipe, ...]] = {}
    for task, body in challenges.items():
        if not isinstance(body, dict):
            continue
        output = body.get("Output")
        if not isinstance(output, str) or not output.lower().endswith(LOOT_SUFFIX):
            continue
        items = [_bare(item) for item in body.get("Items") or () if isinstance(item, str)]
        if not any(item.lower() == KNIFE for item in items):
            continue
        for item in items:
            rows = by_material.get(item.lower())
            if rows:
                found[task] = tuple(rows)
                break
    return found


#: Ticks a knife costs on one catch. **Not a guess - the wiki's own figure for
#: the same action**: every `{{Recipe}}` turning a `Raw ...` fish into offcuts
#: states three, and the untimed ones are the same knife on a crab.
CUT_TICKS = 3.0


def stated_ticks(
    challenges: Mapping[str, Any], recipes: Sequence[Recipe]
) -> dict[str, float]:
    """`{output: ticks}` for a knife action the wiki describes but never times.

    **Three crabs, over the whole export.** `Cut a red crab into ~|raw red
    crab meat|~` and its blue and rainbow siblings each join a `{{Recipe}}`
    carrying `ticks = 0`, so `rate_for` refused all three - rightly, since an
    action priced at no time at all is the fastest method in the game. What
    makes a figure available here rather than a guess is that the *same knife*
    is timed elsewhere: the offcuts recipes state three ticks for every raw
    fish they accept.

    Keyed by output to match `herblore.stated_ticks`, so the two merge, and
    filled only where **every** recipe for that output is untimed - a
    published figure is never overwritten by a stated one.
    """
    untimed: dict[str, list[Recipe]] = {}
    for recipe in recipes:
        untimed.setdefault(recipe.output, []).append(recipe)

    found: dict[str, float] = {}
    for body in challenges.values():
        if not isinstance(body, dict):
            continue
        items = [_bare(item) for item in body.get("Items") or () if isinstance(item, str)]
        if not any(item.lower() == KNIFE for item in items):
            continue
        output = body.get("Output")
        if not isinstance(output, str):
            continue
        rows = untimed.get(output)
        if rows and not any(recipe.timed for recipe in rows):
            found[output] = CUT_TICKS
    return found


def unclaimed(
    candidates: Sequence[Recipe], cuts: Mapping[str, Sequence[Recipe]]
) -> tuple[Recipe, ...]:
    """`candidates` without the recipes a species-specific cut task named.

    **`variant_candidates`' rule on the other axis.** Upstream lists the knife
    twice over: once per fish (`Cut up a ~|raw marlin|~`) and once for the
    whole family (`Cut raw fish into ~|fine fish offcuts|~`, whose `Items`
    name an item *family* rather than a fish). Both join `Fine fish offcuts`,
    and `rate_for` maximises - so the generic task took whichever species was
    cheapest that day, and the recipe then read as describing two tasks.
    `apply`'s ambiguity guard saw that collision and held the marlin's own
    money-making guide over its own recipe.

    A recipe a specific task named is that task's; what is left over is what
    the family task describes. Returns `candidates` unchanged when subtracting
    would leave nothing, because a task with no candidates is worse informed
    than one sharing them.
    """
    claimed = {id(recipe) for rows in cuts.values() for recipe in rows}
    rest = tuple(recipe for recipe in candidates if id(recipe) not in claimed)
    return rest or tuple(candidates)
