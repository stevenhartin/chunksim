"""A task name as a person reads it, rather than as everything else keys it.

**The raw `~|...|~` form is the key everywhere** - `ChallengeResult.valid`,
every ledger lookup, `--export-json`, the BiS task names. This module is the one
place that undoes it, and only for display.

It lived in `challenges.py`, which is 1,700 lines of fixed point that three
callers had to import in full to reach these fifty. It is here because the
markup is a property of a *name*, not of the validity calculation - and because
`cli/render.py`, `gui/panels.py` and `other_tasks.py` should not have to load a
convergence loop to print a word.

Applies to challenge and task names **only**. Other branches of the export use
`~` and `|` for real, so a blanket strip would quietly corrupt them - which is
why `search.py` strips per hit type rather than over its whole result.
"""

from __future__ import annotations

import re



_TASK_MARKUP = re.compile(r"[~|]")


def strip_task_markup(task_name: str) -> str:
    """Drop the `~|...|~` delimiters a task name wraps its subject in,
    preserving the text (and its casing) between them.

    The markers exist so the web app can style the item/monster a task
    names; nothing downstream of a terminal wants them. Removes the
    delimiter *characters* rather than the `~|`/`|~` pairs, because four
    real names are malformed - `Carve a ~log |canoe|~` has the opening
    `|` four characters late, and pair-stripping leaves the visible
    wreckage `Carve a ~log |canoe`. Character-stripping renders those as
    `Carve a log canoe` and is byte-identical to pair-stripping on all
    14,688 well-formed names in the export, where no `|` and no `~` ever
    appears outside this markup.

    **Only ever call this on a challenge/task name.** Names from other
    branches can use these characters for real (the shop `~ Uglug's
    stuffsies ~`), which is why `cli.py`'s `search` output applies it to
    task hits and `task:` routes rather than to every hit.

    Deliberately does *not* touch the `#` variant separator
    (`~|wooden hull#Raft|~`) or the trailing `*` secondary marker: both are
    real parts of the stored name, and rendering them is upstream behaviour
    this project hasn't located. Unlike `search.normalise`, this is for
    *display*, so it neither lowercases nor collapses anything.
    """
    return _TASK_MARKUP.sub("", task_name)
