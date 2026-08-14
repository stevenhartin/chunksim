"""What a preference *means*, as opposed to where it is stored.

`store/cache.py` reads and writes `cache/gui/settings.json` and knows nothing
about what is in it; this module owns the whole vocabulary and nothing else
does. That split is the point: the page will grow more preferences, and the
alternative shape - validation inside the POST handler, defaults inside the
JavaScript, ranges inside the CSS - is how the same setting ends up meaning
three things.

**Refuse rather than coerce, per key.** `sanitise` takes what was sent and what
is currently stored, and returns a whole valid settings object: a key whose new
value does not survive validation keeps the value it had, rather than being
clamped into range or dropped to a default. A slider that silently rewrites
what you typed is worse than one that ignores you, because only the second is
visible. Unrecognised keys are dropped outright - the same discipline
`actions._window_state` applies, and for the same reason: this file is read
back on the next launch, so a hostile or stale caller must not be able to put
arbitrary JSON into it.

**Bands are five, and that is a decision rather than a limit of the code.** The
five colours are the stylesheet's (`--band-*`), and the stylesheet owns colours
here for the reason `test_the_mode_palette_is_defined_once` pins elsewhere: the
page names the *state* and never the hue. A user-editable band *count* would
mean a user-editable palette, which puts colour literals back into the page. So
the names and the thresholds move and the count does not.

**Per checkout when you are working on this, per user when you installed it.**
`cache/` is resolved by `cache.data_root()`, so two clones of this repo have two
sets of preferences and neither travels - while an installed `chunksim` keeps
one set under the platform's own data directory. This docstring used to say a
genuinely per-user store would be the first `Path.home()` in the project;
`cache.user_data_root()` is now that call, and it arrived because an installed
program cannot keep its data in whatever directory it was run from.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: How the hours graph maps a number to a bar height. `log` spreads four
#: decades over the strip so a 3h roll and a 300h roll are both readable;
#: `linear` is the older behaviour, which scales to the tallest bar and clips.
SCALES: tuple[str, ...] = ("log", "linear")

#: The bands the hours bars are coloured by, cheapest first. `upto` is an
#: exclusive upper bound in hours and the last band's is `None` - unbounded, so
#: every value lands in exactly one band. Names are the user's to change; the
#: count is not (see the module docstring).
DEFAULT_BANDS: tuple[dict[str, Any], ...] = (
    {"name": "Free", "upto": 1.0},
    {"name": "Quick", "upto": 10.0},
    {"name": "Grind", "upto": 100.0},
    {"name": "Brutal", "upto": 300.0},
    {"name": "Death", "upto": None},
)

BAND_COUNT = len(DEFAULT_BANDS)

#: The longest a band name may be. Not a security bound - `tmpl` escapes it
#: either way - but a legend is a strip of five labels and a paragraph in one
#: of them makes the other four unreadable.
MAX_BAND_NAME = 24

DEFAULTS: dict[str, Any] = {
    "hours_scale": "log",
    "hours_bands": [dict(band) for band in DEFAULT_BANDS],
    "first_run_done": False,
}


def defaults() -> dict[str, Any]:
    """A fresh copy of the defaults, safe for a caller to mutate."""
    return {
        "hours_scale": DEFAULTS["hours_scale"],
        "hours_bands": [dict(band) for band in DEFAULT_BANDS],
        "first_run_done": DEFAULTS["first_run_done"],
    }


def _number(value: Any) -> float | None:
    """`value` as a float, or `None` if it is not a real finite number.

    `bool` is excluded deliberately: `True` is an `int` in Python and a
    threshold of `1.0` arrived at that way is a caller sending nonsense, not a
    caller meaning one hour.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def _bands(value: Any) -> list[dict[str, Any]] | None:
    """`value` as the band list, or `None` if any part of it is not.

    All or nothing: a list where the fourth threshold is nonsense is refused
    whole rather than merged band by band, because the bands are only
    meaningful as an ordered partition and half of an edit is not one.
    """
    if not isinstance(value, list) or len(value) != BAND_COUNT:
        return None
    out: list[dict[str, Any]] = []
    previous = 0.0
    for index, entry in enumerate(value):
        if not isinstance(entry, Mapping):
            return None
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            return None
        last = index == BAND_COUNT - 1
        upto = entry.get("upto")
        if last:
            # The top band has to be open, or a value above it belongs to no
            # band and the bars it draws have no colour.
            if upto is not None:
                return None
            out.append({"name": name.strip()[:MAX_BAND_NAME], "upto": None})
            continue
        bound = _number(upto)
        # Strictly ascending and strictly positive, so every band is non-empty
        # and every hours figure lands in exactly one of them.
        if bound is None or bound <= previous:
            return None
        previous = bound
        out.append({"name": name.strip()[:MAX_BAND_NAME], "upto": bound})
    return out


#: The keys `sanitise` understands. Named once so `reset` cannot ask for
#: something no other part of this module has heard of.
KEYS: tuple[str, ...] = ("hours_scale", "hours_bands", "first_run_done")

#: Band names that were once the default and are not any more, and the bound
#: they shipped with. **Both halves are the check**: a stored band matching
#: name *and* edge is one nobody chose - it was written out because settings
#: are stored whole, not because anyone typed it - where the same name over a
#: moved edge is a deliberate choice and is left alone.
#:
#: Renaming a default is otherwise invisible to everyone who has already
#: opened the page, since their file holds the old one and this module has no
#: way to tell "the default, saved" from "what I picked". This is the
#: narrowest thing that fixes that, and it stops applying once it has applied.
_SUPERSEDED_NAMES: Mapping[tuple[str, float], str] = {
    ("Minor Death", 300.0): "Brutal",
}


def _renamed(current: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    """`current` with superseded default band names brought up to date."""
    bands = (current or {}).get("hours_bands")
    if current is None or not isinstance(bands, list):
        return current
    updated: list[Any] = []
    for band in bands:
        renamed = None
        if isinstance(band, dict):
            name, upto = band.get("name"), band.get("upto")
            if (
                isinstance(name, str)
                and isinstance(upto, (int, float))
                and not isinstance(upto, bool)
            ):
                renamed = _SUPERSEDED_NAMES.get((name, float(upto)))
        updated.append({**band, "name": renamed} if renamed else band)
    return {**current, "hours_bands": updated}


def sanitise(payload: Mapping[str, Any], current: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The settings to store, given what was sent and what is already there.

    Every key is present in the result, so what is written is always a whole
    settings object rather than a patch - which is what lets a reader hand its
    answer straight to the page without the page carrying its own defaults.

    **`reset` is a list of keys, and it has to be**, because "put this back to
    the default" cannot be said with a value: every value that means anything
    is a value the user could also have chosen, and the one value that does not
    - an empty band list, a missing key - is exactly what a partial or hostile
    payload looks like. Refusing those *is* the validation, so the reset has to
    arrive as its own instruction rather than as an absence.
    """
    settled = defaults()
    current = _renamed(current)
    reset = payload.get("reset")
    dropped = (
        {key for key in reset if key in KEYS}
        if isinstance(reset, list)
        else set()
    )
    kept = {key: value for key, value in (current or {}).items() if key not in dropped}
    for source in (kept, payload):
        scale = source.get("hours_scale")
        if isinstance(scale, str) and scale in SCALES:
            settled["hours_scale"] = scale
        bands = _bands(source.get("hours_bands"))
        if bands is not None:
            settled["hours_bands"] = bands
        # `_number` refuses `bool` on purpose, so a flag needs its own check -
        # and an exact `isinstance` rather than a truth test, because "the
        # setup ran" is a thing the page states, not a thing anything infers
        # from a stray 1 or "yes".
        done = source.get("first_run_done")
        if isinstance(done, bool):
            settled["first_run_done"] = done
    return settled
