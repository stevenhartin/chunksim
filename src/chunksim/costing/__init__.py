"""Turning a derivation into hours.

`heuristics` owns every hand-correctable number and the
`defaults < scraped < computed < overrides` merge; `slayer` owns the one rate
that is a distribution rather than a choice; `estimate` walks the active set and
prices it; `dps_bridge` is the optional seam to `osrs-dps`; `inputs` assembles
what the two apps feed the others, so they cannot disagree.

**`dps_bridge.py` is the only module in the project that may import
`osrs_dps`**, and that is a boundary rather than a preference: the extra is one
a user opts into, so every other module here has to work without it. It was a
*licence* boundary too until this project became GPL-3.0-or-later to match the
library; the optionality is what survived, and it is the half the code was
always enforcing. Importing `dps_bridge` is always safe; calling into it
without the extra raises `DpsUnavailableError`.

The export contains no durations, no kill rates and no XP figures at all, so
every number this directory spends comes from the scrape, the checked-in
overrides, or a default - except `model/experience.py`'s XP curve, which is
exact and deliberately not overridable.
"""
