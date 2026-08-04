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

import re
from dataclasses import dataclass, field

#: Every money-making guide is a subpage of this, which is how they are
#: enumerated - there is no category or Cargo table to query.
MMG_PREFIX = "Money making guide/"

#: A slayer master's assignment table is on this subpage, not on the master's
#: own page, which only links to it.
ASSIGNMENTS_PAGE = "Slayer assignments"

#: `<!-- ... -->`, including the multi-line ones real infoboxes carry.
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

#: The first number in a value, commas allowed (`1,200`), decimals kept
#: (`422.8`). Anchored nowhere, so it survives trailing markup.
_NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")

#: `[[Slayer task/Aberrant spectres|Aberrant Spectres]]` -> the target, which
#: is the canonical task name; the display half is inconsistently capitalised.
_TASK_LINK_RE = re.compile(r"\[\[Slayer task/([^|\]]+)")

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
    """

    activity: str = ""
    kph: float | None = None
    experience: dict[str, float] = field(default_factory=dict)


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
    for index in range(1, 9):
        skill = params.get(f"experience{index}", "").strip()
        amount = parse_number(params.get(f"experience{index}num", ""))
        if skill and amount is not None:
            experience[skill] = amount

    return MmgRates(
        # The one value returned cooked rather than raw: `Activity` reads
        # `Killing [[General Graardor]]`, and it exists to be joined against
        # a monster or activity name, so the link markup is never wanted.
        activity=strip_links(params.get("activity", "")).strip(),
        kph=parse_number(params.get("kph", "")),
        experience=experience,
    )


def slayer_assignments(text: str) -> list[Assignment]:
    """Every assignment row on a `<Master>/Slayer assignments` page.

    One row is one `|-`-separated block; within it the task link, the first
    quantity range and the weight template are found by pattern. A block
    missing any of the three is skipped - the tables carry header and note
    rows that match none of them.
    """
    assignments: list[Assignment] = []
    for block in strip_comments(text).split("|-"):
        task = _TASK_LINK_RE.search(block)
        weight = _WEIGHT_RE.search(block)
        amount = _RANGE_RE.search(block)
        if task is None or weight is None or amount is None:
            continue
        low = int(amount.group(1).replace(",", ""))
        high = int(amount.group(2).replace(",", ""))
        assignments.append(
            Assignment(
                task=task.group(1).strip(),
                weight=int(weight.group(1)),
                low=min(low, high),
                high=max(low, high),
            )
        )
    return assignments
