"""A tick written back into a map payload.

**The one place this project writes to upstream's data rather than reading
it.** Everything else here treats a fetched payload as immutable input; the
GUI's edit mode needs the opposite, and the surgery is small enough that the
danger is not complexity but silence: a mis-encoded key writes a tick that
`firebase.decode_challenge_keyed` cannot read back, and the map then derives
exactly as though the task had never been ticked. Nothing errors. That is why
`firebase.encode_key` is pinned by a round-trip property over all 49,721
interned names rather than by a handful of examples.

**A tick is stored by encoded name, not by `t_N` id.** Upstream interns
lazily - `tasksMap.json` carries a `currentNextIndex` counter and a name that
has never been interned is stored literally - so a literal is a shape upstream
already produces and `decode_challenge_keyed` already handles. Minting an id
would mean editing upstream's interning table, which is a much larger claim to
make about somebody else's data.

Pure, and rebuilds every branch it touches rather than mutating: the payload
handed in is safe to reuse, which is the same contract
`simulate.simulated_payload` keeps and for the same reason.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from chunksim.model import firebase
from chunksim.model.summary import _mapping


def apply_ticks(
    payload: Mapping[str, Any], ticked: Mapping[str, Sequence[str]]
) -> dict[str, Any]:
    """`payload` with every name in `ticked` marked complete in its category.

    `ticked` is keyed by challenge category (`Slayer`, `BiS`, `Diary`, a skill
    name) holding **raw, markup-bearing** task names - the form
    `challenges.strip_task_markup` strips for display and everything else keys
    by. They are encoded on the way in.

    Ticking something already ticked is a no-op rather than an error: the
    browser holds a pending set and the map may have moved under it, and
    refusing the whole commit over one redundant tick would be a poor trade.
    """
    if not ticked:
        return dict(payload)

    result = dict(payload)
    chunkinfo = dict(_mapping(result, "chunkinfo"))
    completed = {
        category: dict(names)
        for category, names in _mapping(chunkinfo, "completedChallenges").items()
        if isinstance(names, Mapping)
    }
    for category, names in ticked.items():
        entries = dict(completed.get(category, {}))
        for name in names:
            entries[firebase.encode_key(name)] = True
        completed[category] = entries
    chunkinfo["completedChallenges"] = completed
    result["chunkinfo"] = chunkinfo
    return result
