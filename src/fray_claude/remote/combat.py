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

Pure parsing; `remote/api.py` fetches.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from collections import Counter
from typing import Any, Mapping, Sequence

from fray_claude.remote.wikitable import column_index, names_in, number, rows, table_with

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


def parse_spell_json(bucket_rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """`{spell: base xp}` from `infobox_spell`, for cross-checking a page parse.

    Not the source of truth - it cannot tell an attack spell from a utility one
    - but it covers every spell, so it is what `parse_attack_spells` is checked
    against when a spellbook page changes shape.
    """
    found: dict[str, float] = {}
    for row in bucket_rows:
        name, blob = row.get("page_name"), row.get("json")
        if not isinstance(name, str) or not isinstance(blob, str):
            continue
        try:
            parsed = json.loads(blob)
        except json.JSONDecodeError:
            continue
        experience = parsed.get("exp") if isinstance(parsed, dict) else None
        try:
            found[name] = float(str(experience))
        except (TypeError, ValueError):
            continue
    return found
