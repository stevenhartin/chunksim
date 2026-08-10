"""How fast a skill goes, and why.

**The climb is walked in bands, not priced at one rate.** `estimate.py` used to
take the fastest method open at the player's *current* level and apply it to the
whole climb to 99; when nothing open at that level had a scraped rate the climb
was priced at `DEFAULT_XP_PER_HOUR`, which is how Herblore 1-99 came out at
13,034 hours on a map that knew eighteen real Herblore rates. A player does not
train at one rate: they level into better methods.

Split out of `estimate.py` because "how fast does this skill go" is a
self-contained question that two other modules already wanted independently -
and because `estimate.py` was the largest module in `costing/`.

Pure, and a pure function of `(Derived, ChunkInfo, Heuristics, skill, levels)`:
no disk, no network, no module-level mutable state. The one ordering subtlety is
in `training_hours` - see the tie-break there, which exists so `--jobs` cannot
change the *labels* either.
"""

from __future__ import annotations

from typing import Any
from fray_claude.model.chunkinfo import ChunkInfo
from fray_claude.derive.pipeline import Derived
from fray_claude.costing.heuristics import Heuristics
from fray_claude.model.summary import _mapping
from fray_claude.costing.heuristics import activity_name
from dataclasses import dataclass


@dataclass(frozen=True)
class TrainingOption:
    """One way of training a skill, and what it would cost per hour."""

    method: str
    level: int | None
    xp_per_hour: float
    #: Where the rate came from - `exact`, `contained`, or `default` for the
    #: floor. A `default` option is not evidence of anything; it is the absence
    #: of evidence, priced conservatively.
    match: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "level": self.level,
            "xp_per_hour": round(self.xp_per_hour, 1),
            "match": self.match,
        }


def training_options(
    derived: Derived, chunk_info: ChunkInfo, heuristics: Heuristics, skill: str
) -> tuple[TrainingOption, ...]:
    """Every reachable primary method for `skill` that has a *real* rate.

    **The companion to `_training_rate`, and the answer to "why is this so
    slow".** That function picks the fastest method available at the player's
    *current* level and applies it to the whole climb; when the only methods
    open at that level have no scraped rate, the entire climb is priced at
    `DEFAULT_XP_PER_HOUR` - which is how Herblore 1-99 comes out at 13,034
    hours on a map where cleaning herbs would do it in a few hundred.

    That is deliberately conservative rather than wrong: the floor announces
    itself, where a guessed rate would not. But a number with no visible
    reasoning behind it is one a reader has to take on trust, so this lists
    what the estimator knows and could not use - name, level and rate - and
    the panel puts it in the tooltip. Sorted fastest first.

    Only methods with a real rate: a list of level-1 options all sitting at the
    floor would say "here are your alternatives" and mean "there are none".
    """
    challenges = _mapping(chunk_info.challenges, skill)
    found: list[TrainingOption] = []
    for name in derived.challenges.valid.get(skill) or {}:
        challenge = challenges.get(name)
        if not isinstance(challenge, dict) or challenge.get("Primary") is not True:
            continue
        rate = heuristics.xp_per_hour(name, skill)
        if rate.match == "default":
            continue
        level = challenge.get("Level")
        found.append(
            TrainingOption(
                method=activity_name(name),
                level=int(level) if isinstance(level, (int, float)) else None,
                xp_per_hour=rate.value,
                match=rate.match,
            )
        )
    return tuple(sorted(found, key=lambda option: -option.xp_per_hour))
