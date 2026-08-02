"""OSRS-style drop-rate string parsing/formatting.

`chunkinfo.json`'s `drops`/`codeItems.dropTables` store rates as strings
(`"1/128"`, `"Always"`, `"~5/256"`) rather than numbers, and upstream's
`gatherChunksInfo`/`calcChallengesWork` parse them inline with
`parseFloat`/`.split('/')`/`.replaceAll('~', '')` at every use site rather
than through a shared helper. This module centralises that parsing, plus
`findFraction` (worker.js), the `1/N`-style rate formatter whose output is
embedded verbatim in synthesized "Every Drop"/"All Droptables" task names.
"""

from __future__ import annotations

import math


def parse_ratio(raw: str) -> float:
    """Parse a rate string ('1/128', '~1/50') to a probability in [0, 1].

    A non-fraction token ('Always' and similar) has no '/', so this returns
    `nan` - matching `parseFloat` on a non-numeric JS string. Callers branch
    on `math.isnan` exactly as upstream branches on `isNaN`, to bypass
    rate-threshold checks for unconditional drops.
    """
    cleaned = raw.replace("~", "")
    numerator_str, separator, denominator_str = cleaned.partition("/")
    if not separator:
        return math.nan
    try:
        return float(numerator_str) / float(denominator_str)
    except ValueError:
        return math.nan


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
    """Port of `rareDropNum = "1/" + rules['Rare Drop Amount']` plus upstream's
    `"1/0"` special case (an amount of 0 would otherwise divide by zero;
    upstream substitutes a threshold so small every drop clears it).
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
