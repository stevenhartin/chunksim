"""One account's experience, read off the official hiscores.

**A map records no skill levels**, so `costing/levels.infer_levels` reads a
*floor* out of what has been ticked off - a completed `Buy the ~|Defence
cape|~` proves 99 Defence and nothing proves anything about Attack. That floor
is honest and it is often far below the truth: the account behind the reference
map holds 99 Attack while its ledger only proves 75.

This is the other end of that. `index_lite.json` answers for any account by
name, and its `xp` is the live figure - so a player who tells this project who
they are gets their real levels instead of a lower bound.

### What it reads and what it does not

**The experience, not the level.** Both are in the payload and the level is
derived from the experience by a curve this project already holds
(`model/experience.py`), so storing the level would be storing an answer where
the question is cheaper to keep - and an experience total survives a curve
change that a level does not.

**`Overall` is dropped.** It is a sum rather than a skill, and leaving it in
would put a 2,004-level pseudo-skill into a mapping every consumer iterates.

**An unranked skill reads zero and that is correct.** The payload gives
`rank: -1, level: 1, xp: 0` for a skill the account has never trained -
Sailing, on the account checked here - and zero experience is level one, which
is exactly what the floor would have said anyway.

### The join needs no aliases, which is worth recording

The hiscores name 24 skills and **every one of them is a skill the export also
names**; the export's only extra is `Combat`, which is a derived pseudo-skill
rather than a trainable one. So there is no alias table here and there should
not be - `tests/test_hiscores.py` asserts the two vocabularies still agree, so
a rename upstream fails a test rather than silently dropping a skill.

Pure: the payload comes in as an argument. `remote/api.fetch_hiscores` is the
only thing that opens the socket.
"""

from __future__ import annotations

from typing import Any, Mapping

#: The sum row, which is not a skill.
OVERALL = "Overall"


def parse(payload: Mapping[str, Any]) -> dict[str, int]:
    """`{skill: experience}` from `index_lite.json`, minus `Overall`.

    Tolerant in the way `model/` is tolerant: a row missing a name or an
    experience is skipped rather than raising, because the shape of a live
    endpoint is not this project's to guarantee.
    """
    rows = payload.get("skills")
    if not isinstance(rows, list):
        return {}
    found: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        name = row.get("name")
        experience = row.get("xp")
        if not isinstance(name, str) or name == OVERALL:
            continue
        if not isinstance(experience, (int, float)) or isinstance(experience, bool):
            continue
        found[name] = max(0, int(experience))
    return found


def account_name(payload: Mapping[str, Any]) -> str:
    """The name the hiscores answered with, which may re-case what was asked."""
    name = payload.get("name")
    return name if isinstance(name, str) else ""
