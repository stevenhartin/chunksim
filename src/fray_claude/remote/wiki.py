"""Parse the handful of OSRS wiki structures the estimator needs.

Pure: no network (that is `api.py`) and no disk (that is `cache.py`), so every
case here is testable on a fixture string. What it reads, and why each one:

- `{{Quest details |length = Medium}}` - the only place quest length exists.
  Note **`Quest details`, not `Infobox Quest`**: the infobox holds the name,
  number, release and developer, and carries no length at all. Checked
  against the live pages, because assuming the infobox is where it lives
  parses cleanly and returns `None` for every quest in the game.
  `Quests/List` renders a Length column but holds no data either: it is a DPL
  query, and the values come from each quest's own `Quest details`.
- `{{Mmgtable |kph = 27 |Experience1 = Thieving |Experience1num = 422.8}}` -
  the money-making guides. One template serves two unrelated needs: `kph` is
  kills per hour for a boss drop, and `Experience{N}num * kph` is XP per hour
  for a training method.
- `<Master>/Slayer assignments` table rows - assignment quantities
  (`130-200`). The export already has the *weights* (`slayerMasterTasks`), so
  this is only wanted for the amount; the master's own page does not carry the
  table, its `/Slayer assignments` subpage does.
- `{{Infobox Monster |slayxp = 150}}` - slayer XP per kill, as a cross-check
  on the third-party sheet `slayer.py` reads.
- **`MediaWiki:Kartographer-map-version`** - the current map-tile render, as
  one bare string. Barely a parse, and it is here anyway because the check it
  does is the point: see `map_tile_version`.

**Comments are stripped first, and that is not defensive.** Gargoyle's infobox
reads `slayxp = 105<!-- before changing this, remember that the morytania
diary gives bonus experience -->`; a parse that takes the value verbatim gets
nonsense, and one that takes the leading digits gets it right by luck rather
than by rule.

**Parameter splitting is brace- and bracket-aware.** A `|` inside a nested
`{{SCP|Quest}}` or `[[Slayer task/X|Y]]` is part of the value, not a
separator, and infobox values contain both constantly. Values are returned
raw and uninterpreted: mapping `Medium` onto a number of hours is
`heuristics.py`'s job, because that mapping is a guess a user may correct and
this is a transcription that they may not.

Assignment rows are matched **by pattern, not by column position** - the task
link, the first range, and the `{{+=|weight|N}}` call are each found wherever
they sit in the row. A wikitable's column order is not a contract, and these
tables carry optional columns (extended amounts, alternatives) that come and
go per master.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

#: Every money-making guide is a subpage of this, which is how they are
#: enumerated - there is no category or Cargo table to query.
MMG_PREFIX = "Money making guide/"

#: A slayer master's assignment table is on this subpage, not on the master's
#: own page, which only links to it.
ASSIGNMENTS_PAGE = "Slayer assignments"

#: The one page listing every superior slayer monster against the ordinary
#: one it replaces. The export knows nothing about them.
SUPERIORS_PAGE = "Superior slayer monster"

#: The MediaWiki message naming the current map-tile render. Kartographer
#: reads this one itself (`mw.message('kartographer-map-version')`), so it is
#: the published answer rather than something inferred.
MAP_VERSION_PAGE = "MediaWiki:Kartographer-map-version"

#: `2026-07-29_a`. A date and a letter that increments within the day - which
#: is exactly why a version is never *constructed* from today's date.
_TILE_VERSION_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}_[0-9a-z]+\Z")

#: `<!-- ... -->`, including the multi-line ones real infoboxes carry.
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

#: The first number in a value, commas allowed (`1,200`), decimals kept
#: (`422.8`). Anchored nowhere, so it survives trailing markup.
#: A number as the wiki writes one. **The leading dot is not optional to
#: support**: `Experience1num = .5273*20 + .4727*30` is real, and a pattern
#: demanding a leading digit matched `5273` there - ten thousand times the
#: intended 0.5273, which reached the estimate as a Fishing rate of
#: 2,604,862 xp/hr.
_NUMBER_RE = re.compile(r"-?(?:\d[\d,]*(?:\.\d+)?|\.\d+)")

#: `[[Slayer task/Aberrant spectres|Aberrant Spectres]]` -> the target, which
#: is the canonical task name; the display half is inconsistently capitalised.
_TASK_LINK_RE = re.compile(r"\[\[Slayer task/([^|\]]+)")

#: Any link plus whatever word characters trail it, because half the masters'
#: tables write the task as `[[Abyssal demon]]s` - the plural lives *outside*
#: the link, and the export keys on the plural.
_ANY_LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\](\w*)")

#: `[[General Graardor]]` / `[[Foo|bar]]` -> the visible text. Guide titles
#: are written `Killing [[General Graardor]]`, and the join wants the words.
_LINK_RE = re.compile(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]")

#: `{{+=|weight|7|echo=2}}` - the wiki's running-total template, whose second
#: positional argument is the assignment weight.
_WEIGHT_RE = re.compile(r"\{\{\s*\+=\s*\|\s*weight\s*\|\s*(\d+)")

#: `130-200`, `35-45`. Hyphen or en-dash, either spaced or not.
_RANGE_RE = re.compile(r"(\d[\d,]*)\s*[-–]\s*(\d[\d,]*)")


@dataclass(frozen=True)
class MmgRates:
    """One money-making guide's rates.

    `experience` is XP *per unit* keyed by skill, not per hour - it is the
    `Experience{N}num` value as written, and only becomes a rate once
    multiplied by `kph`. Keeping them separate here means a guide with a
    `kph` and no experience (a pure boss drop) and one with both (a skilling
    activity) parse through the same path.

    **`kph` is not always kills.** The template counts whatever the guide is
    about, and `kph name` relabels the column when it is not kills - see
    `counts_kills`.
    """

    activity: str = ""
    kph: float | None = None
    experience: dict[str, float] = field(default_factory=dict)
    #: The `kph name` override as written, or `""` when the guide leaves the
    #: column with its default name of `Kills per hour`.
    kph_name: str = ""
    #: Skills whose `Experience{N}num` is **already per hour**, flagged by the
    #: template's `Experience{N}isph`. Ten guide-skill pairs across the 1,111
    #: guides, and one of them mattered a great deal: Subduing Tempoross
    #: states 62,000 Fishing xp per hour, which multiplied by its 60 permits
    #: an hour came out as 3,720,000.
    per_hour: frozenset[str] = frozenset()

    @property
    def counts_kills(self) -> bool:
        """Whether `kph` is a rate of *killing something*.

        **The template serves every kind of money maker, and `kph` counts
        whatever the guide is about** - berries picked, pockets picked, horns
        ground. A guide relabels the column with `kph name` when it is not
        kills, so the absence of that parameter is the wiki's own statement
        that the number is a kill rate.

        Measured over the 97 guides that were reaching monster names: all 82
        without a `kph name` are titled `Killing ...` or `Looting ...`, and no
        guide with a different verb omits it. The parameter is also *better*
        than the title, which is why it is what this reads - `Killing cows and
        tanning cowhide` counts `Leather made per hour` and `Looting ogre
        coffins` counts `Coffins per hour`, and both would pass a title test.
        """
        return not self.kph_name or self.kph_name.strip().casefold() == "kills per hour"


@dataclass(frozen=True)
class Assignment:
    """One row of a slayer master's assignment table."""

    task: str
    weight: int
    low: int
    high: int

    @property
    def mean_count(self) -> float:
        return (self.low + self.high) / 2


def strip_comments(text: str) -> str:
    """Drop `<!-- ... -->` spans. Run before reading any value."""
    return _COMMENT_RE.sub("", text)


def strip_links(text: str) -> str:
    """Replace `[[target|display]]` and `[[target]]` with their visible text."""
    return _LINK_RE.sub(lambda match: match.group(1), text)


def parse_number(raw: str) -> float | None:
    """The first number in `raw`, or `None` if it holds none.

    Tolerant on purpose: wiki values arrive with thousands separators, units,
    references and stray markup around the figure that matters.
    """
    match = _NUMBER_RE.search(raw)
    if match is None:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:  # pragma: no cover - the regex cannot produce this
        return None


#: The characters a value may hold and still be arithmetic rather than prose.
_EXPRESSION_OK = set("0123456789.+-*/() \t")

#: How the template spells "yes" in its boolean flags.
_TRUE = {"y", "yes", "true", "1"}

#: The AST nodes `parse_amount` will evaluate. Anything else - a name, a call,
#: an attribute - is prose that happens to contain digits, and is refused.
_EXPRESSION_OPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub, ast.UAdd)


def _evaluate(node: ast.AST) -> float | None:
    """Evaluate a checked arithmetic node, or `None` if it is not one."""
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)
    if isinstance(node, ast.Constant):
        return float(node.value) if isinstance(node.value, (int, float)) else None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, _EXPRESSION_OPS):
        value = _evaluate(node.operand)
        return None if value is None else (-value if isinstance(node.op, ast.USub) else value)
    if isinstance(node, ast.BinOp) and isinstance(node.op, _EXPRESSION_OPS):
        left, right = _evaluate(node.left), _evaluate(node.right)
        if left is None or right is None:
            return None
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        return left / right if right else None
    return None


def parse_amount(raw: str) -> float | None:
    """A wiki numeric field, which is sometimes a sum rather than a number.

    **`Experience1num` is written as arithmetic when a method yields a mix.**
    `Catching sardines & herring` gives `.5273*20 + .4727*30` - 53% of catches
    at 20 xp and 47% at 30, so 24.7 xp a catch. Reading the first number out
    of that gets 0.5273 at best and, before `_NUMBER_RE` learned about leading
    dots, 5273.

    Evaluated through `ast` with the node types checked rather than with
    `eval`, and only when the whole value is arithmetic: anything carrying a
    letter is prose and falls back to `parse_number`, which takes the first
    figure as before.
    """
    stripped = strip_links(raw).strip()
    if stripped and set(stripped) <= _EXPRESSION_OK:
        # **A value that is entirely arithmetic is only ever arithmetic**, so
        # a failure here is refused rather than fed to `parse_number`. That
        # fallback would read `1/0` as 1 - a wrong number where the honest
        # answer is that the guide does not say.
        try:
            return _evaluate(ast.parse(stripped, mode="eval"))
        except (SyntaxError, ValueError, ZeroDivisionError):
            return None
    return parse_number(stripped)


def _template_body(text: str, template: str) -> str | None:
    """The text between `{{Template` and its matching `}}`.

    Matched case-insensitively on the first character and with `_`/space
    treated alike, since MediaWiki normalises both and pages use either.
    """
    pattern = re.compile(
        r"\{\{\s*" + "[ _]".join(re.escape(word) for word in template.split()) + r"\s*(?=[|}\n])",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if match is None:
        return None

    depth = 1
    index = match.end()
    while index < len(text):
        if text.startswith("{{", index):
            depth += 1
            index += 2
        elif text.startswith("}}", index):
            depth -= 1
            if depth == 0:
                return text[match.end() : index]
            index += 2
        else:
            index += 1
    # Unclosed template: take what there is rather than losing the page.
    return text[match.end() :]


def _split_params(body: str) -> list[str]:
    """Split a template body on its *top-level* `|` separators only."""
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    index = 0
    while index < len(body):
        pair = body[index : index + 2]
        if pair in {"{{", "[["}:
            depth += 1
            current.append(pair)
            index += 2
            continue
        if pair in {"}}", "]]"}:
            depth -= 1
            current.append(pair)
            index += 2
            continue
        if body[index] == "|" and depth <= 0:
            parts.append("".join(current))
            current = []
            index += 1
            continue
        current.append(body[index])
        index += 1
    parts.append("".join(current))
    return parts


def template_params(text: str, template: str) -> dict[str, str]:
    """Named parameters of the first `{{template}}` in `text`.

    Positional parameters are skipped - nothing here wants them. A repeated
    name keeps the *first*, matching MediaWiki, where a later duplicate is
    ignored rather than overriding.
    """
    body = _template_body(strip_comments(text), template)
    if body is None:
        return {}
    params: dict[str, str] = {}
    for part in _split_params(body):
        # The leading part is whatever sat between the name and the first
        # `|` - never a parameter, and dropped by the `=` test below.
        name, separator, value = part.partition("=")
        if not separator:
            continue
        key = name.strip().lower()
        if key and key not in params:
            params[key] = value.strip()
    return params


def quest_length(text: str) -> str | None:
    """A quest's `length` as written (`Medium`, `Short – Medium`), or `None`.

    From `{{Quest details}}`. `{{Infobox Quest}}` is the obvious guess and the
    wrong one - it has no `length` parameter, so reading it returns `None` for
    every quest without ever looking like a failure.
    """
    return template_params(text, "Quest details").get("length") or None


def quest_difficulty(text: str) -> str | None:
    """A quest's `difficulty` (`Novice`, `Experienced`, ...), or `None`.

    Alongside `length` in `{{Quest details}}`. Not used for the estimate -
    length is what maps to hours - but recorded in the config, since it is the
    obvious second signal to reach for when a length looks wrong by hand.
    """
    return template_params(text, "Quest details").get("difficulty") or None


def monster_slayer_xp(text: str) -> float | None:
    """A monster's slayer XP per kill (`slayxp`), or `None`.

    Note the parameter is `slayxp`, not `slayerxp` - the longer spelling
    appears nowhere and looking for it finds nothing on every page.
    """
    params = template_params(text, "Infobox Monster")
    return parse_number(params["slayxp"]) if "slayxp" in params else None


def mmg_rates(text: str) -> MmgRates | None:
    """One money-making guide's `kph` and per-unit XP, or `None` if absent.

    `Experience{N}`/`Experience{N}num` are paired by index; a skill named
    with no number (or the reverse) is dropped rather than half-recorded.
    """
    params = template_params(text, "Mmgtable")
    if not params:
        return None

    experience: dict[str, float] = {}
    per_hour: set[str] = set()
    for index in range(1, 9):
        skill = params.get(f"experience{index}", "").strip()
        amount = parse_amount(params.get(f"experience{index}num", ""))
        if skill and amount is not None:
            experience[skill] = amount
            if params.get(f"experience{index}isph", "").strip().lower() in _TRUE:
                per_hour.add(skill)

    return MmgRates(
        # The one value returned cooked rather than raw: `Activity` reads
        # `Killing [[General Graardor]]`, and it exists to be joined against
        # a monster or activity name, so the link markup is never wanted.
        activity=strip_links(params.get("activity", "")).strip(),
        kph=parse_amount(params.get("kph", "")),
        experience=experience,
        # Note the space: the parameter is `kph name`, not `kphname`, and
        # `template_params` lowercases but does not otherwise normalise keys.
        kph_name=params.get("kph name", ""),
        per_hour=frozenset(per_hour),
    )


def superior_pairs(text: str) -> list[tuple[str, str]]:
    """`(superior, the normal monster it replaces)` from the wiki's table.

    Each row is `|[[Crawling Hand|Crawling hand]]` followed by
    `|[[Crushing hand]]`, so the *first two* links in a row are the pair, in
    that order. Read positionally within the row because the table's other
    columns (combat level, hitpoints, unique-drop odds, slayer XP) are plain
    numbers and templates that carry no links to confuse them.
    """
    pairs: list[tuple[str, str]] = []
    for block in strip_comments(text).split("|-"):
        links = _LINK_RE.findall(block)
        targets = [
            match.group(1).strip()
            for match in re.finditer(r"\[\[([^\]|]+)", block)
            if not match.group(1).lower().startswith("file:")
        ]
        if len(links) < 2 or len(targets) < 2:
            continue
        base, superior = targets[0], targets[1]
        if base and superior and base != superior:
            pairs.append((superior, base))
    return pairs


def slayer_assignments(text: str) -> list[Assignment]:
    """Every assignment row on a `<Master>/Slayer assignments` page.

    One row is one `|-`-separated block; within it the task link, the first
    quantity range and the weight template are found by pattern. A block
    missing any of the three is skipped - the tables carry header and note
    rows that match none of them.
    """
    assignments: list[Assignment] = []
    for block in strip_comments(text).split("|-"):
        weight = _WEIGHT_RE.search(block)
        amount = _RANGE_RE.search(block)
        task = _row_task(block)
        if task is None or weight is None or amount is None:
            continue
        low = int(amount.group(1).replace(",", ""))
        high = int(amount.group(2).replace(",", ""))
        assignments.append(
            Assignment(
                task=task,
                weight=int(weight.group(1)),
                low=min(low, high),
                high=max(low, high),
            )
        )
    return assignments


def _row_task(block: str) -> str | None:
    """The task an assignment row is for, however the row spells it.

    Four masters route through `[[Slayer task/Abyssal demons|...]]`; the other
    six link the monster directly and put the plural outside the link, as
    `[[Abyssal demon]]s`. Only the first shape was handled, so Krystilia,
    Vannaka, Chaeldar, Konar, Spria and Mortimer parsed to nothing at all -
    which read downstream as "you cannot reach these tasks" rather than "no
    data was collected for them".

    The export keys on the plural, so the trailing text is part of the name.
    """
    canonical = _TASK_LINK_RE.search(block)
    if canonical is not None:
        return canonical.group(1).strip()

    match = _ANY_LINK_RE.search(block)
    if match is None:
        return None
    target, display, trailing = match.groups()
    if target.lower().startswith(("file:", "image:")):
        return None
    return f"{(display or target).strip()}{trailing}"


def map_tile_version(raw: str) -> str | None:
    """The map-tile render named by `MAP_VERSION_PAGE`, if it names one.

    **The value is one bare string, so this is a check rather than a parse -
    and the check is the reason it exists.** `?action=raw` on a page that has
    been deleted, renamed or protected does not fail; it answers with an error
    document, and interpolating *that* into a tile URL produces a request for
    something enormous and nonsensical rather than a visible failure.

    Deliberately **not** guessed at from today's date, either: the suffix is a
    letter that increments within a day, so a constructed version is wrong more
    often than not and a wrong one 404s silently into a blank map.

    Returns `None` rather than raising, because what to do about it is the
    caller's call - fall back to the version it cached last time, or say the
    map is unavailable - and not this function's.
    """
    candidate = raw.strip()
    return candidate if _TILE_VERSION_RE.match(candidate) else None
