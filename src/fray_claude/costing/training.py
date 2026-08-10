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
from fray_claude.costing.heuristics import DEFAULT_XP_PER_HOUR
from fray_claude.model.chunkinfo import ChunkInfo
from fray_claude.model.experience import MAX_LEVEL, level_for_xp, xp_for_level
from fray_claude.derive.pipeline import Derived
from fray_claude.costing.heuristics import Heuristics
from fray_claude.model.summary import _mapping
from fray_claude.costing.heuristics import activity_name
from collections.abc import Sequence
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


@dataclass(frozen=True)
class TrainingBand:
    """One stretch of a climb, trained by one method at one rate."""

    level_from: int
    level_to: int
    xp: int
    xp_per_hour: float
    method: str
    #: `exact`, `contained`, or `default` for the floor. Carried per band
    #: rather than per skill because a climb can be part measured and part
    #: guessed, and which part is which is the first thing a reader asks.
    match: str

    @property
    def hours(self) -> float:
        return self.xp / self.xp_per_hour if self.xp_per_hour > 0 else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "level_from": self.level_from,
            "level_to": self.level_to,
            "xp": self.xp,
            "xp_per_hour": round(self.xp_per_hour, 1),
            "method": self.method,
            "match": self.match,
            "hours": round(self.hours, 2),
        }


def training_bands(
    options: Sequence[TrainingOption],
    start_xp: int,
    target_level: int,
    *,
    floor: float = DEFAULT_XP_PER_HOUR,
) -> tuple[TrainingBand, ...]:
    """The climb from `start_xp` to `target_level`, split where the rate changes.

    **Walked on the XP axis rather than the level axis**, which is what makes
    the arithmetic exact and the quest grant free: `start_xp` is a total, so a
    quest reward is added to it and the bands below it simply vanish - there is
    no separate level adjustment to keep in step.

    The method available at a level is a **running maximum**: a method open at
    54 is still open at 90, so the rate can only rise as the climb goes on, and
    a band boundary is a level where it does. That monotonicity is why **the
    floor can only ever be the first band** - which is the whole of "the floor
    stays visible". It is a named stretch carrying its own XP and hours, not a
    number averaged into the total where nobody can see it.

    Because `xp_for_level` is exact integers and the bands telescope,
    `sum(band.xp)` is exactly the XP between the two ends and
    `sum(band.hours)` is exactly `xp / blended_rate`.

    **The tie-break is load-bearing.** Two methods at the same level and the
    same rate must label their band identically in every worker process, or
    `--jobs` changes the text while leaving the number alone - which is worse
    than changing both, because nothing would catch it. Hence the sort on
    `(level, -rate, method)`.
    """
    target_xp = xp_for_level(min(int(target_level), MAX_LEVEL))
    if start_xp >= target_xp:
        return ()

    ranked = sorted(
        ((max(1, option.level or 1), option.xp_per_hour, option.method, option.match)
         for option in options),
        key=lambda entry: (entry[0], -entry[1], entry[2]),
    )
    steps: list[tuple[int, float, str, str]] = []
    best = 0.0
    for level, rate, method, match in ranked:
        if rate <= best:
            continue
        best = rate
        steps.append((xp_for_level(level), rate, method, match))

    edges = sorted(
        {start_xp, target_xp} | {xp for xp, *_ in steps if start_xp < xp < target_xp}
    )
    bands: list[TrainingBand] = []
    for lower, upper in zip(edges, edges[1:]):
        open_now = [step for step in steps if step[0] <= lower]
        rate, method, match = (
            open_now[-1][1:] if open_now else (floor, "", "default")
        )
        bands.append(
            TrainingBand(
                level_from=level_for_xp(lower),
                level_to=level_for_xp(upper),
                xp=upper - lower,
                xp_per_hour=rate,
                method=method,
                match=match,
            )
        )
    return tuple(bands)
