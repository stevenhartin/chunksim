"""OSRS-style drop-rate string parsing/formatting.

`chunkinfo.json`'s `drops`/`codeItems.dropTables` store rates as strings
(`"1/128"`, `"Always"`, `"~5/256"`) rather than numbers, and upstream's
`gatherChunksInfo`/`calcChallengesWork` parse them inline with
`parseFloat`/`.split('/')`/`.replaceAll('~', '')` at every use site rather
than through a shared helper. This module centralises that parsing, plus
`findFraction` (worker.js), the `1/N`-style rate formatter whose output is
embedded verbatim in synthesized "Every Drop"/"All Droptables" task names.

Because that output ends up inside a task *name*, `find_fraction`'s
half-away-from-zero rounding and no-trailing-zero formatting deliberately
match JS's `Math.round`/`Number.toString` rather than Python's own.
"""

from __future__ import annotations

import math
import re


def parse_ratio(raw: str) -> float:
    """Parse a rate string ('1/128', '~1/50') to a probability in [0, 1].

    A non-fraction token ('Always' and similar) has no '/', so this returns
    `nan` - matching `parseFloat` on a non-numeric JS string. Callers branch
    on `math.isnan` exactly as upstream branches on `isNaN`, to bypass
    rate-threshold checks for unconditional drops.

    **A zero denominator is `inf`, not an exception**, because that is what
    the code being ported does: JS `1/0` is `Infinity` and `0/0` is `NaN`,
    neither of which raises. Python disagrees, and the difference is not
    academic - a real map (`verf`) sets `Secondary Primary Amount` to `0`,
    which reaches here as `"1/0"` through `build_secondary_primary_num` and
    took down every derivation command with a `ZeroDivisionError`. An
    infinite threshold is also the sensible reading of that rule being zero:
    no rate is ever common enough to pass it, so the rate-based branches
    simply turn off, and `verf`'s own `activeTasks` oracle agrees with that.
    """
    cleaned = raw.replace("~", "")
    numerator_str, separator, denominator_str = cleaned.partition("/")
    if not separator:
        return math.nan
    try:
        numerator, denominator = float(numerator_str), float(denominator_str)
    except ValueError:
        return math.nan
    if denominator == 0:
        # JS: 1/0 -> Infinity, -1/0 -> -Infinity, 0/0 -> NaN.
        if numerator == 0:
            return math.nan
        return math.inf if numerator > 0 else -math.inf
    return numerator / denominator


def looks_non_numeric(raw: str) -> bool:
    """Port of the repeated `isNaN(x.replaceAll('/', '').replaceAll('@', ''))`
    check: does `raw` fail to parse as a number once `/` and `@` are
    stripped? True for `'Always'`-like tokens; false for ordinary fractions
    ('1/128' -> '1128', still numeric) - this is *not* "is this a fraction",
    it detects a genuinely non-numeric rate marker. Unlike `parse_ratio`,
    upstream does not strip `~` here, so a tilde-prefixed rate also counts
    as non-numeric in this specific check - reproduced as-is.
    """
    stripped = raw.replace("/", "").replace("@", "")
    try:
        float(stripped)
    except ValueError:
        return True
    return False


def build_rare_drop_num(rare_drop_amount: str) -> float:
    """Port of `rareDropNum = "1/" + rules['Rare Drop Amount']` (index.js:3664),
    with an amount of `0` substituting a threshold so small every rate clears
    it.

    Read literally, `"1/0"` is `Infinity` in JS, which would make
    `rate > rareDropNum` reject *every* rate-based drop. That reading was
    tried and is **wrong in effect** - the map's own `activeTasks` oracle
    lists `(Callisto and Artio) Obtain a ~|tyrannical ring|~`, an ordinary
    `drops` entry at `1/716` with no `skillItems` fallback in play, which an
    infinite threshold can never admit; it also dropped `Abyssal whip` out of
    `SourceIndex` entirely. Something upstream of `rareDropNum` evidently
    stops an amount of `0` reaching this comparison - most likely the
    `Rare Drop` rule being off short-circuiting it - and that path has not
    been located, so this keeps the behaviour that matches the oracle rather
    than the arithmetic that doesn't.

    The location-specific drops an infinite threshold appeared to fix are
    really `taskUnlocks['Items']`' job - see `sources.apply_item_task_unlocks`.
    """
    if rare_drop_amount == "0":
        return parse_ratio("1/999999999999999")
    return parse_ratio(f"1/{rare_drop_amount}")


def build_secondary_primary_num(secondary_primary_amount: str) -> float:
    """Port of `secondaryPrimaryNum = "1/" + rules['Secondary Primary Amount']`."""
    return parse_ratio(f"1/{secondary_primary_amount}")


def secondary_primary_denominator(secondary_primary_amount: str) -> int:
    """The raw `Secondary Primary Amount` as an int, for the `> 50` checks
    that gate several primary/secondary classifications - upstream reads
    this via `parseInt(secondaryPrimaryNum.split('/')[1])`, i.e. the
    denominator of `"1/" + amount`, which is just `amount` itself.
    """
    try:
        return int(secondary_primary_amount)
    except ValueError:
        return 0


def _round_half_up(value: float, ndigits: int) -> float:
    """`Math.round` rounds halves away from zero; Python's `round` rounds
    halves to even. All our inputs are non-negative rates, so this only
    needs to handle that one direction.
    """
    scale = float(10**ndigits)
    return math.floor(value * scale + 0.5) / scale


def _format_js_number(value: float) -> str:
    """Render a float the way JS's implicit `Number` -> string coercion
    would (no trailing `.0`), with thousands separators on the integer part.
    """
    if value == int(value):
        return f"{int(value):,}"
    return f"{value:,}"


def find_fraction(value: float, rounded_denominator: bool = False) -> str:
    """Port of `findFraction`: render a probability as a `1/N` display string.

    `value` is a probability (e.g. `1/128 = 0.0078125`); this inverts it,
    rounds to 2 decimal places the way `Math.round` does (half away from
    zero, not Python's banker's rounding), floors to an integer when
    `rounded_denominator` is set, and formats with thousands separators.

    Upstream reaches this same numeric result via decimal-string-length
    scaling and a GCD reduction rather than a plain division - algebraically
    equivalent for any real probability, so it's not reproduced; what *is*
    reproduced is the half-away-from-zero rounding and JS's no-trailing-zero
    number formatting, since the exact string is embedded in a synthesized
    task's name in stage 3.
    """
    if math.isnan(value) or value == 0:
        return "NaN"
    ratio = _round_half_up(1 / value, 2)
    if rounded_denominator:
        ratio = math.floor(ratio)
    return f"1/{_format_js_number(ratio)}"


#: Anything in brackets after the number. `(noted)` says the drop arrives as a
#: bank note and `(F2P)` that the figure is the free-to-play one; neither
#: changes *how many* you get, which is the only question here.
_QUANTITY_NOTE = re.compile(r"\([^)]*\)")


def parse_quantity(raw: str) -> float | None:
    """How many of an item one drop yields: `"5-35 (noted)"` -> 20.

    **A range is its mean.** `5-35` is a uniform roll and the estimator asks
    "how long to accumulate one", which is a question about the average, not
    about the unlucky end. `1-2` is 1.5, and a single figure is itself.

    **Noted and unnoted are the same drop.** A note is the bankable form of
    exactly the same item and converts back one for one, so treating them
    differently would double-count the drop table's own entries - several
    monsters list both forms.

    `None` for anything that is not a count. The export has one such value in
    20,742 (`"1/26.79"`, a rate that has wandered into a quantity field), and
    guessing at it would be worse than pricing the drop as a single unit.
    """
    cleaned = _QUANTITY_NOTE.sub("", raw).replace(",", "").strip()
    if not cleaned:
        return None
    bounds = [part.strip() for part in cleaned.split("-") if part.strip()]
    try:
        numbers = [float(part) for part in bounds]
    except ValueError:
        return None
    if not numbers or any(number < 0 for number in numbers):
        return None
    return sum(numbers) / len(numbers)
