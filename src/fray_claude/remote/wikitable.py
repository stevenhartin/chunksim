"""Reading a wikitable, which is harder than it looks.

**Shared because two modules parse tables from the same wiki and one splitter
is the whole difficulty.** Wikitext separates cells with a newline `|` or an
inline `||`, and both appear inside templates - `{{Coins|{{GEP|Amylase
crystal|10*13.8}}}}` has four `|` and none of them is a cell break. A naive
`split("|")` reads a level out of half a template and looks like it worked, so
the depth counter here is the difference between a rate and a plausible number.

Nothing about any particular skill lives here; `remote/skill_tables.py` and
`remote/combat.py` own what their tables *mean*.
"""

from __future__ import annotations

import re
from typing import Iterator


NUMBER = re.compile(r"^\s*([\d,]+(?:\.\d+)?)")
SCP_LEVEL = re.compile(r"\{\{SCP\|(?P<skill>[A-Za-z ]+)\|(?P<level>\d+)")
LINK_TARGET = re.compile(r"\[\[([^\]|#]+)")
PLINK_NAME = re.compile(r"\{\{(?:plink|chatl)[a-z]*\|([^|}]+)")
PLINK_TEXT = re.compile(r"\|txt=([^|}]+)")


def split_cells(row: str) -> list[str]:
    """A table row's cells, respecting `{{...}}` and `[[...]]` nesting.

    Wikitext separates cells with a newline `|` or an inline `||`, and both
    appear inside templates (`{{Coins|{{GEP|Amylase crystal|10*13.8}}}}`) where
    they mean nothing of the sort. A depth counter is the difference between
    reading a level and reading half a template.
    """
    cells: list[str] = []
    current: list[str] = []
    depth = 0
    index = 0
    while index < len(row):
        pair = row[index : index + 2]
        if pair in ("{{", "[["):
            depth += 1
            current.append(pair)
            index += 2
            continue
        if pair in ("}}", "]]"):
            depth = max(0, depth - 1)
            current.append(pair)
            index += 2
            continue
        if depth == 0 and pair == "||":
            cells.append("".join(current))
            current = []
            index += 2
            continue
        if depth == 0 and row[index] == "\n" and row[index + 1 : index + 2] == "|":
            cells.append("".join(current))
            current = []
            index += 2
            continue
        current.append(row[index])
        index += 1
    cells.append("".join(current))
    return [cell.strip() for cell in cells]


def tables(text: str) -> Iterator[str]:
    """Every `{| ... |}` block in `text`, outermost only."""
    depth = 0
    start = 0
    for match in re.finditer(r"\{\||\|\}", text):
        if match.group(0) == "{|":
            if depth == 0:
                start = match.start()
            depth += 1
        elif depth:
            depth -= 1
            if depth == 0:
                yield text[start : match.end()]


def table_with(text: str, *needles: str) -> str:
    """The first table whose header cells mention all of `needles`.

    **Header lines, not "everything before the first row separator".** A table
    may open with `|-` and put its `!` lines after it - the sawmill's fee table
    does - and looking only at the text before that separator finds nothing but
    the `{| class="wikitable"` line.
    """
    for table in tables(text):
        head = "\n".join(
            line for line in table.splitlines() if line.lstrip().startswith("!")
        )
        if all(needle in head for needle in needles):
            return table
    return ""


def rows(table: str) -> Iterator[list[str]]:
    """Data rows of `table`, header skipped, as cell lists."""
    for chunk in table.split("\n|-")[1:]:
        body = chunk.split("\n|}")[0]
        cells = [cell for cell in split_cells(body) if cell]
        if cells:
            yield cells


def number(cell: str) -> float | None:
    found = NUMBER.match(cell.replace("&nbsp;", " ").strip())
    return float(found.group(1).replace(",", "")) if found else None


def names_in(cell: str) -> tuple[str, ...]:
    """Every joinable name a cell offers, in order, deduplicated.

    **Targets, not display text**, because `[[Rocks (Corsair Cove)|Rocks]]`
    renders as "Rocks" and joins as nothing - the export names the
    disambiguated object. But `{{plinkt|Warrior (Thieving)|txt=Warrior}}`
    needs the *other* half too: the page is disambiguated where the export's
    NPC is not, so both spellings are offered and the caller keeps whichever
    joins.

    All of them rather than the first, because one cell can name two things -
    `{{plinkt|Man}}/[[Woman]]` is two NPCs on one row, and taking either alone
    silently loses a level-1 training method.
    """
    found = [
        *(match.group(1).strip() for match in PLINK_NAME.finditer(cell)),
        *(match.group(1).strip() for match in PLINK_TEXT.finditer(cell)),
        *(match.group(1).strip() for match in LINK_TARGET.finditer(cell)),
    ]
    # **An icon is not a name.** Several of these tables lead with an image
    # column, and `[[File:Ice Barrage.png]]` is a perfectly good link target -
    # it just names a picture, and reading it gives every Ancient Magicks spell
    # a name ending in `.png`.
    return tuple(
        dict.fromkeys(
            name
            for name in found
            if name and not name.lower().startswith(("file:", "image:"))
        )
    )


def name_in(cell: str) -> str:
    """The first joinable name in a cell, or `""`."""
    names = names_in(cell)
    return names[0] if names else ""


def header_columns(table: str, width: int | None = None) -> list[str]:
    """The table's column labels, one entry per *column*, `colspan` expanded.

    **Positional indexing does not survive two pages.** The standard spellbook
    writes Spell, Level, Runes, XP, Max hit; Ancient Magicks writes Icon,
    Mobile, Spell, Level, Runes, Coins, XP, Max hit. Reading "the second
    number" gets a level from one and a coin price from the other, and both
    look like plausible numbers. So a caller asks for the column it wants by
    name and gets its index.

    Labels are lowercased and stripped of markup, and a `colspan=N` header
    yields the same label N times so that the indices line up with what
    `rows` returns.
    """
    labels: list[str] = []
    for line in table.splitlines():
        stripped = line.strip()
        if not stripped.startswith("!"):
            continue
        for cell in re.split(r"!!", stripped.lstrip("!")):
            span = re.search(r"colspan\s*=\s*\"?(\d+)", cell)
            label = cell.split("|")[-1] if "|" in cell else cell
            label = re.sub(r"\{\{[^}]*\}\}|\[\[|\]\]|<[^>]*>|<ref.*", " ", label)
            label = re.sub(r"[^a-z0-9 ]+", " ", label.lower()).strip()
            labels.extend([label] * (int(span.group(1)) if span else 1))
    if width is None or len(labels) == width:
        return labels
    # **A `colspan` header does not always mean two data cells.** The standard
    # spellbook writes `! colspan=2 |Spell` and then renders the icon and the
    # name from one `{{plinkt}}` in a single cell, so expanding the span
    # over-counts by one and every column after it is read one to the left.
    # Collapsing repeats is the only reading that agrees with the data, so it
    # is taken when - and only when - it makes the two line up.
    collapsed = [
        label for index, label in enumerate(labels) if index == 0 or label != labels[index - 1]
    ]
    return collapsed if len(collapsed) == width else labels


def column_index(table: str, *needles: str, width: int | None = None) -> int | None:
    """The index of the first column whose label contains any of `needles`.

    Pass `width` - the number of cells the data rows actually have - so a
    `colspan` that does not match the body can be resolved against it.
    """
    for index, label in enumerate(header_columns(table, width)):
        if any(needle in label for needle in needles):
            return index
    return None
