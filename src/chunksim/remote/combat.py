"""What combat experience is made of: monster hitpoints, and spell base xp.

**Combat is the one thing this project could already compute and never spent.**
XP comes from damage - 4 per point in melee and Ranged, 2 in Magic, 1.33 to
Hitpoints - and damage per hour is `kills_per_hour * hitpoints`, both of which
`costing/` already has for every reachable monster. The only missing number was
the monster's hitpoints, which the chunk export does not carry for any of its
872 monsters.

Two wiki sources, both cheap:

- **`infobox_monster`**, one Bucket query. 3,234 rows, 1,382 distinct named
  monsters with hitpoints. It also carries `experience_bonus`, which is the
  "certain high defence monsters have higher experience per hitpoint damage
  ratio" the Combat article describes - a **percentage**, and 361 monsters have
  a non-zero one (Mithril dragon +5%, King Black Dragon +7.5%, Khazard warlord
  **-75%**). Only those are kept: a stored zero for the other thousand would be
  a thousand rows saying nothing.
- **The three spellbook pages**, for Magic. A cast pays base xp *whether or not
  it hits*, and on the numbers that dominates: Fire Surge is 50.5 xp a cast
  against roughly 24 xp of damage, so getting the spell wrong is worse than
  getting the damage wrong.

**Telling an attack spell from a utility spell is the hard part here, and
`infobox_spell` cannot do it.** Fire Surge, Charge and Vengeance have identical
infoboxes - same `type: Combat`, same shape - and the MediaWiki categories
disagree with themselves (Ice Barrage is in `Combat spells`, Fire Surge is not,
Vengeance is). Taking the highest-xp "combat" spell picks **Charge at 180 xp**,
a utility cast with a seven-minute cooldown, and overstates Magic by 2.4x.

The filter that does work is the wiki's own table layout: each spellbook page
puts its attack spells in the one table carrying a **base max hit** column, and
everything else in tables without one. A spell you can autocast is a spell with
a max hit, which is as close to a definition as the wiki offers.

**And `infobox_spell` carries the other half a cast costs: its runes.** The
`cost` field is rendered HTML - `<sup>2</sup>[[File:Law rune.png|...|link=Law
rune]]` - so the quantity and the item are both there and both machine-readable,
which is the pair the chunk export states nowhere. That makes casting the one
family where a per-action material cost can be computed rather than hand-entered
(see `costing/inputs.py`'s `hand_material_costs`, which is the hand version and
which this does not replace).

**Only the first `white-space:nowrap` span is read, and that restriction is the
filter.** The wiki puts a spell's consumed runes in that span and its *required
equipment* in a `plinkp-template` span after it, so reading the whole field
charges Iban Blast for a staff and the Dark Lure for a book - the same "an axe is
not a material" error `costing/estimate.py` refuses through the `*` marker.
Measured over all 201 spells the restriction leaves 17 items, every one of them
genuinely consumed: fifteen runes, `Unpowered orb` and the Ape Atoll `Banana`.

Pure parsing; `remote/api.py` fetches.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from collections import Counter
from typing import Any, Mapping, Sequence

from chunksim.remote.wikitable import column_index, names_in, number, rows, table_with

#: The spellbook pages holding an attack table. Lunar has none - it is a
#: utility book - so asking for it would cost a request to find nothing.
SPELLBOOK_PAGES: tuple[str, ...] = (
    "Standard spellbook",
    "Ancient Magicks",
    "Arceuus spellbook",
)

#: What marks the attack table on a spellbook page. The wiki spells it two
#: ways, so both are accepted; a page whose tables carry neither contributes
#: nothing rather than contributing its utility spells.
_MAX_HIT_HEADERS: tuple[str, ...] = ("max hit", "maximum magic hit")


@dataclass(frozen=True)
class MonsterStats:
    """One monster's hitpoints, and its experience multiplier if it has one.

    `experience_bonus` is a percentage as the wiki writes it: `5` means 5%
    more experience per point of damage, `-75` means a quarter of the usual.
    Zero is the overwhelming common case and is not stored.
    """

    name: str
    hitpoints: float
    experience_bonus: float = 0.0

    @property
    def xp_multiplier(self) -> float:
        return 1.0 + self.experience_bonus / 100.0

    def as_dict(self) -> dict[str, Any]:
        return {"hitpoints": self.hitpoints, "experience_bonus": self.experience_bonus}


@dataclass(frozen=True)
class AttackSpell:
    """One autocastable spell: the level it needs and the xp a cast pays."""

    name: str
    level: int
    experience: float
    spellbook: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "level": self.level,
            "experience": self.experience,
            "spellbook": self.spellbook,
        }


@dataclass(frozen=True)
class SpellCost:
    """What one cast consumes and what it pays, from `infobox_spell`."""

    name: str
    experience: float
    items: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"experience": self.experience, "items": dict(sorted(self.items.items()))}


#: The consumed half of a spell's `cost`. The wiki wraps the runes in this span
#: and the required equipment in a sibling one, so this is what tells a material
#: from a tool - see the module docstring.
_CONSUMED_SPAN = re.compile(r'<span style="white-space:nowrap">(.*?)</span>', re.S)

#: One entry inside it: an optional `<sup>` quantity, then a file link whose
#: `link=` target is the item. A missing `<sup>` means one, which 8 of the 201
#: spells rely on.
_COST_ENTRY = re.compile(r"(?:<sup>(\d+)</sup>\s*)?\[\[File:[^\]]*?link=([^\]|]+)\]\]")


def monster_query(limit: int = 5000) -> str:
    """The Bucket query for every monster's hitpoints and xp bonus."""
    return (
        "bucket('infobox_monster')"
        ".select('name','hitpoints','experience_bonus')"
        f".limit({limit}).run()"
    )


def parse_monster_stats(bucket_rows: Sequence[Mapping[str, Any]]) -> dict[str, MonsterStats]:
    """`{name: MonsterStats}`, keeping the **first** row for each name.

    A monster with several versions (`TzHaar-Xil` appears three times) gets one
    entry rather than whichever the iteration happened to end on. Rows with no
    usable hitpoints are dropped: a zero would make the monster free to kill
    and infinitely fast to train on.
    """
    found: dict[str, MonsterStats] = {}
    for row in bucket_rows:
        name = row.get("name")
        hitpoints = row.get("hitpoints")
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(hitpoints, (int, float)) or isinstance(hitpoints, bool):
            continue
        if hitpoints <= 0 or name in found:
            continue
        bonus = row.get("experience_bonus")
        found[name] = MonsterStats(
            name=name,
            hitpoints=float(hitpoints),
            experience_bonus=(
                float(bonus)
                if isinstance(bonus, (int, float)) and not isinstance(bonus, bool)
                else 0.0
            ),
        )
    return found


def parse_attack_spells(pages: Mapping[str, str]) -> tuple[AttackSpell, ...]:
    """Every autocastable spell in `pages`, cheapest level first.

    One table per page - the one with a max-hit column - and its **columns
    located by header name**, because the three books do not agree on their
    order: the standard book leads with the spell, Ancient Magicks leads with
    two icon columns and puts a coin price before the XP. Reading "the second
    number on the row" gets a level from one page and a coin price from the
    other, and both look plausible.

    See the module docstring for why a max-hit column is the filter and
    `type: Combat` is not.
    """
    found: list[AttackSpell] = []
    for page, text in sorted(pages.items()):
        table = next(
            (
                candidate
                for header in _MAX_HIT_HEADERS
                if (candidate := table_with(text, header))
            ),
            "",
        )
        if not table:
            continue
        body = list(rows(table))
        if not body:
            continue
        # The width the *data* uses, not the one the header claims.
        width = Counter(len(cells) for cells in body).most_common(1)[0][0]
        at_name = column_index(table, "spell", width=width)
        at_level = column_index(table, "level", width=width)
        at_experience = column_index(table, "xp", "experience", width=width)
        if at_name is None or at_level is None or at_experience is None:
            continue
        for cells in body:
            if len(cells) <= max(at_name, at_level, at_experience):
                continue
            names = names_in(cells[at_name])
            level = number(cells[at_level])
            experience = number(cells[at_experience])
            if not names or level is None or experience is None:
                continue
            if level <= 0 or experience <= 0:
                continue
            found.append(
                AttackSpell(
                    name=names[0],
                    level=int(level),
                    experience=experience,
                    spellbook=page,
                )
            )
    return tuple(sorted(found, key=lambda spell: (spell.level, spell.name)))


def spell_query(limit: int = 5000) -> str:
    """The Bucket query for every spell's experience and rune cost."""
    return (
        "bucket('infobox_spell')"
        ".select('page_name','json')"
        f".limit({limit})"
        ".run()"
    )


def parse_cost(cost: str) -> dict[str, int]:
    """The items one cast consumes, from `infobox_spell`'s rendered `cost`.

    Reads only the first `white-space:nowrap` span, which is what separates a
    consumed rune from required equipment - see the module docstring. A repeated
    item is summed rather than overwritten, since nothing promises the wiki
    lists each only once.
    """
    span = _CONSUMED_SPAN.search(cost)
    if span is None:
        return {}
    found: dict[str, int] = {}
    for quantity, item in _COST_ENTRY.findall(span.group(1)):
        name = item.strip()
        if name:
            found[name] = found.get(name, 0) + int(quantity or 1)
    return found


def parse_spell_costs(bucket_rows: Sequence[Mapping[str, Any]]) -> dict[str, SpellCost]:
    """`{spell page: SpellCost}` from `infobox_spell`.

    Covers **every** spell, attack or utility, which is the opposite of what
    `parse_attack_spells` wants and exactly what pricing wants: a teleport pays
    no damage and still costs three runes a cast. A spell with no experience or
    no cost is dropped rather than stored as a zero - both halves are needed to
    turn it into seconds per XP.
    """
    found: dict[str, SpellCost] = {}
    for row in bucket_rows:
        name, blob = row.get("page_name"), row.get("json")
        if not isinstance(name, str) or not isinstance(blob, str):
            continue
        try:
            parsed = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        try:
            experience = float(str(parsed.get("exp")))
        except (TypeError, ValueError):
            continue
        items = parse_cost(str(parsed.get("cost") or ""))
        if experience > 0 and items:
            found[name] = SpellCost(name=name, experience=experience, items=items)
    return found
