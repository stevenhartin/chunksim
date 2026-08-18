"""A gathering action's own weight tiers, which are yields rather than drops.

**`estimate._route_hours` refuses any table member that is not `Always`**, and
that gate is right about almost everything: multiplying a *defaulted* pace by a
real drop chance is how `Slay the ~|Alchemical Hydra|~ alt` once put Prayer at
11.3 hours. But it is wrong about a handful, and mining granite is the clearest
case - the table is

    Granite (500g)  20.70%    Granite (2kg)  22.15%    Granite (5kg)  25.39%

which is not a drop table at all. It is *one* action handing over one of three
weights of the thing you just mined, so a 5kg block is one mine in four and
"1/chance actions" is a real, short loop. Contrast `Raw bass loot`, where
`Raw bass` is `Always` and `Big bass` is a 1/1000 bonus roll beside it: there
the gate is doing exactly its job.

### Where the boundary is, and why it is not a knob

Measured over the whole export, against only the tables a gathering *model*
paces: of the 25 unpriceable non-`Always` members, **nothing at all sits
between 8.33% and 19.92%**.

| Share | What is there |
|---|---|
| 19.9-26.8% | granite's three weights, sandstone's four, the Cam Torum calcified deposit |
| 5.0-8.3% | Digsite soil finds - a vase, an old tooth, a broken staff |
| 0.02-0.1% | the big fish and the tecu salamander |

Anywhere from 9% to 19% selects the same eight items. `ORDINARY_SHARE` sits in
the middle of that gap.

### Why this is a flat cost and not a route

**Opening the certainty gate was tried twice and reverted twice.** The second
attempt is the instructive one: gated to exactly these eight items it *still*
failed to price `fray-uber` in three minutes. The count was never the problem.
`_route_hours` prices an uncertain member by dividing the quantity by the
share, and a fractional quantity is a fixpoint key nothing else ever matches -
so the memo stops hitting and Prayer's bone walk alone reached 2.5 million
`_item_hours` calls.

A yield has no such trouble because it needs no route. The action's own pace is
already known - `Heuristics.action_seconds` carries what the gathering model
computed for `Mine ~|granite|~` - so the cost of one 5kg block is that over the
share, a single number the walk reads and stops. `costing/herbs.py` is priced
this way for its own reasons and `estimate._best_route` checks the two side by
side.

**The pace must be the model's own curve.** `Rate.match == GATHERING_MATCH`
specifically, not merely non-default: `confirmed` and `computed` are what
`barbarian.py`, `gotr.py` and every minigame model use, and trusting those was
the first of the two reverted attempts.

Pure: the export, the paces and the shares come in as arguments.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from chunksim.costing.gathering import GATHERING_MATCH
from chunksim.model.summary import _mapping

#: The share below which a table member is a *find* rather than a yield. See
#: the module docstring for the gap in the data this sits in.
ORDINARY_SHARE = 0.10


def costs(
    chunk_info: Any,
    action_seconds: Mapping[str, float],
    rate_match: Callable[[str, str], str],
    share_of: Callable[[str, str], float],
) -> dict[str, float]:
    """`{item: seconds}` for every ordinary yield of a modelled action.

    `rate_match` is `(task, skill) -> Rate.match` and `share_of` is
    `(activity, member) -> chance`, both passed in so this module needs
    neither a `_Walk` nor a `Heuristics` - the same seam
    `costing/herbs.py` takes.

    **The cheapest wins a tie.** One item can be a yield of two actions; a
    lower cost is a better route to it, exactly as `_item_hours` takes the
    `min` over routes.
    """
    paced: dict[str, str] = {}
    for skill, challenges in getattr(chunk_info, "challenges", {}).items():
        if not isinstance(challenges, dict):
            continue
        for task, challenge in challenges.items():
            if not isinstance(challenge, dict):
                continue
            output = challenge.get("Output")
            seconds = action_seconds.get(task)
            if not isinstance(output, str) or not seconds or seconds <= 0:
                continue
            if rate_match(task, skill) == GATHERING_MATCH:
                paced[output] = task

    found: dict[str, float] = {}
    for activities in _mapping(getattr(chunk_info, "data", {}), "skillItems").values():
        if not isinstance(activities, dict):
            continue
        for activity, table in activities.items():
            task = paced.get(activity)
            if task is None or not isinstance(table, dict):
                continue
            for member in table:
                if not isinstance(member, str):
                    continue
                share = share_of(activity, member)
                # `>= 1.0` is the `Always` member, which needs no help - the
                # certainty gate lets it through already.
                if not ORDINARY_SHARE <= share < 1.0:
                    continue
                seconds = action_seconds[task] / share
                if member not in found or seconds < found[member]:
                    found[member] = seconds
    return found
