"""What a herb costs, when farming them is time-gated and killing is not.

**Herbs are the input Herblore is made of, and neither way of getting them is
an ordinary gathering loop.** The item walk had two routes and both were
wrong on their own:

- **Farming**, which it priced at the clicking alone - 60 seconds a patch over
  8.8 herbs, so 6.8 seconds a herb. That is the *active* cost and says nothing
  about the eighty minutes a herb takes to grow. You cannot do it back to back.
- **Drops**, priced per herb, which asks "how long to get a ranarr" of a table
  that hands out thirteen herbs without being asked which.

**So this models the cycle rather than either action.** A herb run is
`RUN_SETUP_MINUTES` to bank and gear up plus `PATCH_MINUTES` a patch, and it
returns `farming.HERBS_PER_SEED` from each - four patches is six minutes for
35.2 herbs. The rest of the eighty minutes is not idle: it is spent on the
best *active* herb source the map reaches, and the two together are what a
player actually gets an hour.

**The drops are pooled, and that is the point of them.** A monster's herb
table is non-discriminatory - thirteen herbs, and you take what falls - so the
question is never "how long for a ranarr" but "which source drops the most
herbs". Pricing each herb separately asks a question the game does not pose,
and answers it with the rarity of one line of a table nobody rolls for
individually. `pooled_rate` sums a source's whole herb table; a herb is a herb.

**A consequence worth stating: a herb costs the same whichever it is.** That
is right for a *climb*, where you brew whatever your herbs allow, and wrong
for a single goal that needs one ranarr. The estimate's Herblore hours are the
first question, so that is the one this answers.

Pure: the patch count and the active rate come in as arguments.
"""

from __future__ import annotations

from typing import Callable, Iterable, Mapping

from chunksim.costing.farming import HERBS_PER_SEED

#: Minutes a herb patch takes to grow. The gate the farming route ignored.
HERB_CYCLE_MINUTES = 80.0

#: Minutes a run costs before the first patch - teleport to a bank, gear up.
RUN_SETUP_MINUTES = 2.0

#: Minutes each patch costs once you are running: travel, pick, replant.
PATCH_MINUTES = 1.0

#: The prefix every uncleaned herb shares, in the export and on the wiki.
GRIMY_PREFIX = "grimy "


def run_minutes(patches: int) -> float:
    """Minutes one herb run takes with `patches` patches, or 0 for none."""
    return RUN_SETUP_MINUTES + PATCH_MINUTES * patches if patches > 0 else 0.0


def herbs_per_hour(patches: int, active_per_hour: float) -> float:
    """Herbs an hour from `patches` patches plus the best active source.

    One eighty-minute cycle is a run and then whatever is left of the cycle
    spent killing. With four patches: six minutes for 35.2 herbs, then
    seventy-four minutes of the active rate.
    """
    run = min(run_minutes(patches), HERB_CYCLE_MINUTES)
    farmed = HERBS_PER_SEED * patches
    killed = active_per_hour * (HERB_CYCLE_MINUTES - run) / 60.0
    return (farmed + killed) * 60.0 / HERB_CYCLE_MINUTES


def seconds_per_herb(patches: int, active_per_hour: float) -> float:
    """Seconds one herb costs, or `0.0` when there is no way to get any."""
    per_hour = herbs_per_hour(patches, active_per_hour)
    return 3600.0 / per_hour if per_hour > 0 else 0.0


def pooled_rate(
    providers: Iterable[str],
    herbs: Iterable[str],
    yield_of: Callable[[str, str], float],
    kills_per_hour: Callable[[str], float],
) -> tuple[str, float]:
    """The best `(source, herbs an hour)` over every source's whole herb table.

    **Summed across herbs, never taken one at a time.** A chaos druid's table
    is one roll that lands on some herb; asking it for ranarr specifically
    prices a line of the table rather than the activity. Measured on the
    every-rollable-chunk map the best is a little over 300 herbs an hour.
    """
    best = ("", 0.0)
    for provider in providers:
        rate = kills_per_hour(provider)
        if rate <= 0:
            continue
        per_kill = sum(yield_of(provider, herb) for herb in herbs)
        found = per_kill * rate
        if found > best[1]:
            best = (provider, found)
    return best


def herb_items(items: Iterable[str]) -> tuple[str, ...]:
    """Every uncleaned herb among `items`, which is what the pool is over."""
    return tuple(sorted(i for i in items if i.lower().startswith(GRIMY_PREFIX)))


def costs(
    items: Iterable[str], patches: int, active_per_hour: float
) -> dict[str, float]:
    """`{herb: seconds}` - one figure, applied to every herb alike."""
    seconds = seconds_per_herb(patches, active_per_hour)
    if seconds <= 0:
        return {}
    return {herb: seconds for herb in herb_items(items)}


def patch_count(
    locations: Iterable[str],
    unlocked: Mapping[str, object],
    sections: Mapping[str, Mapping[str, object]] = {},
) -> int:
    """How many of the export's twelve herb patches this map can stand in.

    **A location is a chunk or a chunk *and a section*.** The export writes
    both - `13141` is a whole chunk, `11321-2` is section 2 of chunk 11321 -
    and comparing the second against the unlocked-chunk keys silently matches
    nothing. That undercounted the every-rollable-chunk map at 5 patches of
    12, which is the shape of mistake `derive/sections.py` exists to prevent:
    unlocking a chunk only makes section `0` reachable.
    """
    found = 0
    for place in locations:
        chunk, _, section = str(place).partition("-")
        if section:
            if sections.get(chunk, {}).get(section):
                found += 1
        elif chunk in unlocked:
            found += 1
    return found
