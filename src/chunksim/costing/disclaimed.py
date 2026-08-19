"""Methods whose own source says they are not for training.

**A published rate is evidence about an action; it is not evidence that the
action is a training method.** The two come apart exactly once in the export
today, and the case is worth a rule rather than an exception: `Fish at a
~|fishing spot (The Stranglewood)|~` carried
`mmg:Money making guide/Stranglewood fishing` at 750/hr, and the spot's own
page says, in as many words, *"it is not recommended for training Fishing, not
even when trying to obtain raw pike or caskets"*.

That figure is not wrong. It is a **money**-making guide, and its experience an
hour is a by-product of a rate about loot - the spot yields newspapers, old
boots and lobster pots three catches in five. Carrying it as a training rate
quotes a number whose own source disclaims the use it is being put to.

### Why this is a refusal and not a model

Everything needed for a model is published except the one thing that matters.
`{{Fishing info}}` states the experience a catch pays (7.5) and the level (1);
what nothing states is the cadence, and the page's only word on it is
qualitative - "items are gathered from this spot much more slowly than most
other fishing spots in the game". There is no `{{Skilling success chart}}` for
the spot, and upstream's `Output` is the bundle `Fishing spot (The Stranglewood)
loot`, which no experience table answers to.

**A chance fitted to the guide's own figure would be the guide with extra
steps** - one parameter against one observation, where the observation *is* the
number being replaced, so the model could never disagree with it. That is the
shape `costing/gathering_overhead.py` warns about when it says to read a 1.00x
as a claim about arithmetic. So this refuses.

**And the report says so rather than saying nothing.** `DISCLAIMED` is keyed
by task and its value is the sentence, so it rides straight to
`Heuristics.refused` and the row reads `refused` with the wiki's own words
beside it. That is the correction to what this module used to claim - "the
1,000/hr floor says what is true: nothing priced it". The floor says *nothing
reached this*, which is a gap somebody should go and close, and it is the one
reading a refusal exists to deny.

### What it will not take away

Only the scrape's own tiers (`recipe_rates.REPLACEABLE`). A computed or
modelled rate survives, so the day somebody finds the cadence the model wins
without this having to be edited; and a hand pin survives, because
`overrides.json` is the top of the layering and somebody who has sat at the
dock and counted outranks a wiki sentence.

Pure: takes a rate table and returns one.
"""

from __future__ import annotations

from typing import Any, Mapping

from chunksim.costing.recipe_rates import REPLACEABLE

#: Task -> the sentence on its own page that disclaims it, quoted so a reader
#: can check the judgement rather than take it. **Keyed by the raw task name**,
#: which is what `training` and `overrides.json` are keyed by.
#:
#: One entry, and it should stay short: this is for a source contradicting
#: itself, not for methods that merely look slow. A slow method has a rate and
#: `training_bands` will decline to use it.
DISCLAIMED: dict[str, str] = {
    "Fish at a ~|fishing spot (The Stranglewood)|~": (
        "it is not recommended for training Fishing, not even when trying to "
        "obtain raw pike or caskets"
    ),
}


def refuse(
    training: Mapping[str, dict[str, Any]], pinned: frozenset[str] = frozenset()
) -> dict[str, dict[str, Any]]:
    """Strip the scraped rate from every method in `DISCLAIMED`."""
    kept: dict[str, dict[str, Any]] = {}
    for task, per_skill in training.items():
        if task not in DISCLAIMED or task in pinned:
            kept[task] = per_skill
            continue
        rest = {
            skill: rate
            for skill, rate in per_skill.items()
            if getattr(rate, "match", "") not in REPLACEABLE
        }
        if rest:
            kept[task] = rest
    return kept
