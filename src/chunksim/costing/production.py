"""What a production method consumes, when no `{{Recipe}}` says.

**A processing rate quoted with the materials to hand is the wrong number for
a chunk account, and this is the general fix for it.** The published figure -
394,778/hr burning magic logs - describes the burning. It says nothing about
the tree, and on a map where the tree is the whole cost that omission is not a
rounding error: Firemaking 1 -> 99 read **35.2 hours** with the logs free.

`costing/training.py` has always known how to charge for that: an option
carries `material_seconds_per_xp` and `effective_xp_per_hour` composes the two
halves exactly. What it lacked was *supply*. Three things state what one action
consumes against the XP that action pays, and the export states neither half
(0 of its 2,710 primary challenges carry a quantity anywhere in `Items`):

- a `{{Recipe}}`, via `costing/recipe_rates.py` - the most specific, because it
  describes the actual variant and its ticks;
- `infobox_spell`, via `inputs.spell_material_costs` - 190 of 214 casts;
- **`Module:Skill calc/<Skill>`, which is this module** - 1,500 rows across
  eighteen skills, already fetched and already checked in as part of
  `heuristics/gathering.json`, because the gathering model needed the same
  pages for their experience column.

So this costs no new scrape and no new file. It is the same tables read for a
different column.

**Where it sits: below everything and above nothing.** A recipe knows which
variant is being made; a spell's infobox is measured against 214 named
challenges; a hand entry is somebody's deliberate correction. A calculator row
is the broadest statement of the three and the least specific, so it fills gaps
and never overrides - see `inputs.recipe_priced` for the merge.

**The join reads upstream's own markup span, not a stripped verb.** Every task
name marks the thing it is about between `~|` and `|~` - `Burn ~|magic logs|~`,
`Craft a ~|ruby amulet|~` - and that span is exactly what a calculator row is
named after, whether the skill names its input (Firemaking) or its product
(Crafting). `Output` and `Output Object` follow it. All whole-string
comparisons, case-insensitively: no fuzzy tier, the same rule as everywhere
else in `costing/`.

**A verb list was tried first and the span beats it outright**, which is worth
recording because the verb route is the obvious one and `recipe_rates` uses it.
Stripping a leading verb reaches the span only when the verb and the span are
the whole name, so every task with a trailing qualifier missed: `Burn ~|magic
logs|~ at a fire` left `magic logs at a fire`, which is not a row. Measured on
the reference map, primary methods joined by span against by verb: Firemaking
**15/15 against 7/15**, Crafting 98 against 97, and 430 against 421 across the
bucket - with nothing the verb route reached that the span did not.

That miss was not merely a gap. **An unjoined method outranks its own charged
twin**, because the export carries both `Burn ~|magic logs|~` and `Burn ~|magic
logs|~ at a fire`, they render to the same words, and the one charged nothing
for its log won the band at 394,778/hr against the other'"'"'s 171,362.

**Which skills, and why it is a set rather than a branch.** Gathering skills
are excluded because they consume nothing - their calculator rows carry no
materials at all (Woodcutting, Mining, Thieving: 0 of 118 rows) - and because
`costing/gathering.py` already prices them from the node. Prayer is excluded
because `inputs._prayer_methods` already charges the bone, and Magic because
the spell layer above is measured against the export's own `Cast` challenges
where this would be a second, blunter answer to the same question. Farming is
excluded because its limit is a schedule rather than a rate. What is left is
the production bucket, named once in `PRODUCTION_SKILLS`, so adding a skill to
this layer is an edit to a set.

Pure: the tables and the challenges come in as arguments and the pricing is the
caller's own item walk, so nothing here reads disk or network.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from chunksim.costing.gathering import Tables
from chunksim.costing.heuristics import MaterialCost
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.model.summary import _mapping

#: The skills whose calculator rows describe consumption - see the docstring
#: on each exclusion. **A set, so widening this layer is one edit**, which is
#: the shape a skill-specific quirk takes everywhere in `costing/`.
PRODUCTION_SKILLS = frozenset(
    {
        "Cooking",
        "Construction",
        "Crafting",
        "Firemaking",
        "Fletching",
        "Herblore",
        "Runecraft",
        "Smithing",
    }
)

#: The `~|...|~` span: upstream'"'"'s own mark for what a task is about.
#:
#: **Non-greedy, and first-span-wins.** A handful of names carry two spans
#: (`Fletch ~|logs|~ into ~|javelin shafts|~`); the first is the thing the task
#: opens on, which is what the calculator row is named after.
_SPAN = re.compile(r"~\|(.+?)\|~")


def join_keys(challenge: Mapping[str, Any], task: str) -> tuple[str, ...]:
    """Every name a challenge offers a calculator row, most likely first.

    **The span comes first**, which is the inverse of `recipe_rates.join_keys`
    and the whole reason this is a separate function: a calculator row is named
    for the action, and a consumption action is named for its input. `Burn
    ~|magic logs|~` names `Magic logs`, which is the row; its `Output` is
    `Ashes`, which is not.

    `Output` and `Output Object` follow, for the skills that name their product
    instead - and for the few tasks carrying no span at all.
    """
    keys: list[str] = []
    span = _SPAN.search(task)
    if span is not None:
        keys.append(span.group(1).strip())
    for field in ("Output", "Output Object"):
        value = challenge.get(field)
        if isinstance(value, str) and value.strip():
            keys.append(value.strip())
    return tuple(key for key in dict.fromkeys(keys) if key)


def calculator_costs(
    chunk_info: ChunkInfo,
    valid: Mapping[str, Mapping[str, Any]],
    tables: Tables,
    skills: frozenset[str] = PRODUCTION_SKILLS,
) -> dict[str, MaterialCost]:
    """`{task: MaterialCost}` for every reachable primary method that joins.

    Only methods in `valid`, so this inherits the derivation's reachability
    gate rather than inventing a second one - the same rule
    `recipe_rates.computed_rates` follows.

    **A row that consumes nothing is skipped rather than recorded as free.**
    `priced_materials` would drop it anyway (no items, no seconds), but leaving
    it out here keeps the returned map a statement about methods that really do
    cost something, which is what a coverage count of it means.
    """
    costs: dict[str, MaterialCost] = {}
    for skill in sorted(skills):
        rows = tables.materials.get(skill) or {}
        paid = tables.experience.get(skill) or {}
        if not rows:
            continue
        challenges = _mapping(chunk_info.challenges, skill)
        for task in sorted(valid.get(skill) or {}):
            challenge = challenges.get(task)
            if not isinstance(challenge, dict) or challenge.get("Primary") is not True:
                continue
            key = next(
                (
                    candidate.lower()
                    for candidate in join_keys(challenge, task)
                    if candidate.lower() in rows
                ),
                None,
            )
            if key is None:
                continue
            consumed = rows[key]
            experience = paid.get(key, (0.0, ""))[0]
            if not consumed or experience <= 0:
                continue
            costs[task] = MaterialCost(
                experience=experience,
                items={item: quantity for item, quantity in consumed},
            )
    return costs
