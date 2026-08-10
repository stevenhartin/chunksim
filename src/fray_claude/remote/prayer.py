"""Bones, altars, and the two numbers that turn one into Prayer experience.

**Prayer is trained by an action the export does not model.** Its 94 challenges
are prayers to activate and shields to bless; the six carrying `Primary: true`
offer fish at a shrine or blessed bone shards at a libation bowl. *Burying a
bone* - the thing every player actually does from level 1 - is not a challenge
anywhere in the export, so there was no method to join a rate to and the whole
climb sat on the 1,000/hr floor.

What the export does have is the bones themselves, on 29 monsters' drop tables,
and the altars: `Chaos altar (Prayer)` as an object in five chunks, and ten
`Build a ~|<x> altar|~` Construction challenges. So the only missing halves are
how much experience a bone pays and how much an altar multiplies it - both of
which the wiki states outright.

| source | rows | gives |
|---|---|---|
| `Template:Prayer info`, 193 transclusions | 41 bones | name, level, xp per bone |
| seven altar pages | 7 | the base and two-burner multipliers |

**The bone table is a template, not a table.** `{{Prayer info}}` is invoked once
per remains page with `name`/`level`/`xp`/`type`, and `type` is what separates
the 41 bones from the 68 spectral, 31 bonemeal, 23 reanimated and 5 ashes rows -
none of which is buried. Ashes are *scattered* and no altar multiplies them,
which is why `bone` is the only type read here.

**Two name shapes need care.** Three jogre and four monkey pages carry a `name`
holding `<br>[[File:…` markup for their cooked variants, and one page invokes
the template twice under two different names. Names are cut at the first `<br>`
and deduplicated keeping the *highest* experience, which is the real burial
value: `Alan's bones` also declares a `Bones` at 3 xp where the `Bones` page
itself says 4.5.

**An altar's multiplier is prose, and the sentence forms are consistent.** Each
page states the base ("It gives 250% Prayer experience when a bone is used with
it") and the lit one ("When both are lit, it gives 350%"), and the oak altar
states its base as the word *normal* rather than a figure - which is why an
unstated base is 100% rather than a parse failure. Measured across all seven,
each burner is worth exactly +50 percentage points (oak 100/150/200 through
gilded 250/300/350); `tests/test_prayer.py` asserts that regularity rather than
computing from it, so a page that stops saying so is a test failure and not a
silent number.

Pure parsing only - `remote/api.py` does the fetching, as it does for every
other host, and `costing/prayer.py` decides what rate a bone implies.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any
from collections.abc import Mapping

#: The template every remains page invokes, and the list this module is built
#: from. 193 pages transclude it; 41 of the 195 invocations are bones.
BONE_TEMPLATE = "Template:Prayer info"

#: The seven altars that multiply a bone's experience. `Marble altar` has no
#: Construction challenge in the export and so joins nothing - it is asked for
#: anyway, because "the wiki lists seven" is a fact about the game and "the
#: export models six" is a fact about the export, and conflating them is how a
#: later export change becomes a silent gap.
ALTAR_PAGES = (
    "Oak altar",
    "Teak altar",
    "Cloth altar",
    "Mahogany altar",
    "Limestone altar",
    "Marble altar",
    "Gilded altar",
)

_TEMPLATE = re.compile(r"\{\{Prayer info(.*?)\}\}", re.DOTALL)
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")


@dataclass(frozen=True)
class Bone:
    """One set of remains, and what burying it pays."""

    name: str
    experience: float
    #: The Prayer level needed to offer it at all - 1 for every bone but
    #: superior dragon bones, which need 70.
    level: int

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "experience": self.experience, "level": self.level}


@dataclass(frozen=True)
class Altar:
    """A player-owned-house altar, and what it multiplies a bone by.

    `base` is the altar alone and `lit` is the altar with both incense burners
    going. They are carried separately because the burners are their own
    Construction challenges, at levels 61-69, and a map that reaches the altar
    need not reach them.
    """

    name: str
    base: float
    lit: float

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "base": self.base, "lit": self.lit}


def _fields(body: str) -> dict[str, str]:
    """The `|key = value` pairs of one template invocation."""
    found: dict[str, str] = {}
    for part in body.split("|"):
        key, sep, value = part.partition("=")
        if sep:
            found[key.strip()] = value.strip()
    return found


def _number(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value.replace(",", "").strip())
    except ValueError:
        return None


def _clean(name: str) -> str:
    """A template's `name`, as the item is actually called.

    Seven pages append `<br>[[File:…]]` to distinguish a cooked variant; the
    name is what precedes it, with the wiki's HTML entities decoded so
    `Marinated j&#39; bones` matches an apostrophe the export writes plainly.
    """
    return html.unescape(name.split("<br>")[0]).strip()


def parse_bones(pages: Mapping[str, str]) -> tuple[Bone, ...]:
    """Every `type = bone` invocation across `pages`, by name.

    Deduplicated keeping the highest experience per name - see the module
    docstring - and sorted by experience descending, so the caller reading the
    first entry it can reach is reading the best one.
    """
    best: dict[str, Bone] = {}
    for text in pages.values():
        for match in _TEMPLATE.finditer(text):
            fields = _fields(match.group(1))
            if fields.get("type", "").strip().lower() != "bone":
                continue
            name = _clean(fields.get("name", ""))
            experience = _number(fields.get("xp"))
            if not name or experience is None or experience <= 0:
                continue
            level = _number(fields.get("level")) or 1.0
            found = Bone(name=name, experience=experience, level=int(level))
            if name not in best or found.experience > best[name].experience:
                best[name] = found
    return tuple(sorted(best.values(), key=lambda bone: (-bone.experience, bone.name)))


def parse_altars(pages: Mapping[str, str]) -> tuple[Altar, ...]:
    """The base and two-burner multipliers stated on each altar's page.

    Read sentence by sentence, because one page states three figures and only
    two of them are wanted: a sentence naming *one* burner is skipped, a
    sentence saying *both* or *two … burners* gives `lit`, and a sentence with
    a percentage and no burner at all gives `base`. An altar whose base is the
    word "normal" - the oak altar - states no figure and is 100%.
    """
    found: list[Altar] = []
    for page, text in sorted(pages.items()):
        base, lit = 1.0, 0.0
        for sentence in re.split(r"(?<=[.])\s+", text):
            if "%" not in sentence or "experience" not in sentence:
                continue
            percents = [float(value) for value in _PERCENT.findall(sentence)]
            if not percents:
                continue
            burner = "burner" in sentence
            if "both" in sentence or ("two" in sentence and burner):
                lit = max(lit, max(percents) / 100.0)
            elif not burner:
                base = max(base, min(percents) / 100.0)
        if lit or base > 1.0:
            found.append(Altar(name=page.lower(), base=base, lit=max(lit, base)))
    return tuple(found)
