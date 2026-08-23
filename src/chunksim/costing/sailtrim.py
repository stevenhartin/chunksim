"""Trimming the sails, the one Sailing method that is paid by a clock.

**Every term is published and none of them is a rate**, which is why this had
no number until now. `Mast and sails` states the cadence in its opening
paragraph - the sails "can be trimmed every 30 seconds for a short speed boost
and some Sailing experience, depending on the tier of the equipment" - and
tabulates a `Sailing Trimming experience` column against the tier. Two hundred
and forty words apart, those are an hourly rate: 120 trims and whatever the
tier pays.

| Mast and sails | Sailing | Trim xp | xp/hr |
|---|---|---|---|
| Wooden, linen | 1 | 10.5 | 1,260 |
| Oak, linen | 24 | 19.5 | 2,340 |
| Teak, canvas | 36 | 30 | 3,600 |
| Mahogany, canvas | 52 | 48 | 5,760 |
| Camphor, canvas | 68 | 64 | 7,680 |
| Ironwood, cotton | 83 | 80 | 9,600 |
| Rosewood, cotton | 94 | 125 | 15,000 |

**The hull is not part of the answer**, which is what makes one challenge
enough for upstream and one table enough here. The page prints the tiers three
times - once for rafts, once for skiffs, once for sloops - and the trimming
column is identical in all three; what changes with the hull is the
Construction experience for *building* the thing and the speed boost's
duration. So a trim is priced by the mast alone.

### The level is the build's, and upstream states it

The gate moved twice in one day. `Mast and sails`' own changelog carries the
7 January 2026 QoL entry - "Players now require a Sailing level to trim sails,
which is the same level required as to build the sail" - and the `Sailing`
page carries the hotfix that followed it, letting a captain "trim all sails,
regardless of their Sailing level", so that a boosted build stays usable.

**Neither of those is the binding constraint for a chunk map, and that is the
point.** A solo player is the captain, so the trim itself checks nothing; what
they cannot do is *have* a mast they could not build. So a band opens at the
level to build its tier, which upstream states on its own `Build a ~|...|~`
challenge as `Skills: {"Sailing": N}` - read from there rather than compared
here, for `costing/wintertodt.py`'s reason. `PUBLISHED_LEVEL` carries the
wiki's own column beside it as the check, and the two agree on all seven rows.

**The wooden tier is exempt from the gate rather than gated at 1.** It is
what the quest hands over - `Sailing training` says the raft from Pandemonium
"will grant 10.5 experience for every trim" - so a map that cannot build a
mast at all still trims the one it was given. Upstream agrees: the trim
challenge asks for `AnyBoat[+]` and nothing else.

### A ceiling, and an ancillary one

`costing/trawler.py`'s sense of the word. The 30 seconds is a cadence rather
than an action - the `Sailing` page describes a gust that "will appear around
the sails of a boat allowing players to trim them within 12 seconds", and the
official client draws a countdown to the next one - so 120 an hour is an hour
spent at sea taking every gust offered. Nothing states how many are missed.

It is also **ancillary in a way nothing else here is**: `Sailing training`
lists trimming beside courier tasks and ocean encounters and then says to
"always trim their sails when training, to collect the additional experience".
An hour of trimming is an hour of sailing, and so is every other method in the
skill - so the honest reading of this rate is a floor under a skill rather
than a thing anybody does on its own. `training_bands` takes the maximum, so
that is exactly how it behaves: 15,000/hr at the top of the tree loses to the
Barracuda trials' 88,923 and to salvage sorting's 171,000, and what it decides
is the stretch below Sailing 15 where **nothing at all was priced**.

**No material cost, and this is one of the few places that is right.** A trim
consumes nothing; the mast is built once and trimmed for ever, so charging the
logs would bill a one-off against every thirty seconds of an infinite loop -
`recipe_rates.RETURNED_MATERIALS`' argument, arriving where there is not even
a loop to return to.

### The wind catcher is a different method and is deliberately not priced

An activated wind catcher "reduces the experience granted by 25%" per trim and
banks a wind mote worth 40 on release (70 with a gale catcher), which is far
better than a bare trim at every tier below rosewood. Three things keep it
out. Releasing a mote is its own action and **upstream carries no challenge
for it** - it carries the two catchers under Construction, as things to build.
The catcher needs Sailing 53, Construction 47, a Barracuda Trial rank and
10,000 air runes, which is `costing/pickpocket.py`'s split between what a
figure is calibrated on and what an estimate here may assume. And a catcher
can be deactivated, so the bare trim is the floor either way.

`CONFIRMED`: the cadence, the seven payouts and the seven levels are all
published, and nothing here is invented.

Pure: nothing but the valid set comes in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from chunksim.costing.gathering import CONFIRMED
from chunksim.costing.heuristics import ComputedMethod

#: The skill a trim pays, and the one the bands are filed under.
SKILL = "Sailing"

#: The skill upstream files the seven `Build a ~|...|~` challenges under.
BUILD_SKILL = "Construction"

#: Upstream's one challenge for the whole family. Every band is emitted on it,
#: because upstream does not distinguish the tiers here and a band landing on a
#: task nobody asked about reads as `unpriced` - see `costing/stated.py`'s
#: lantern harpoon for the bug that rule was written after.
TRIM_TASK = "Trim the ~|mast and sails|~ on your boat"

#: **Published**, in `Mast and sails`' opening paragraph.
TRIM_SECONDS = 30.0

SECONDS_PER_HOUR = 3600.0


@dataclass(frozen=True)
class Mast:
    """One tier of mast and sails, as the wiki tabulates it."""

    #: What a band calls the tier.
    tier: str
    #: Upstream's own build challenge, which is both the gate and the level.
    #: `None` for the tier the Pandemonium raft arrives with - see the module
    #: docstring.
    build_task: str | None
    #: The `Sailing Trimming experience` column, identical across rafts,
    #: skiffs and sloops.
    trim_experience: float
    #: The wiki's own `Sailing Level` column. **A check, not the source** -
    #: `methods` reads upstream's `Skills` instead, and
    #: `tests/test_costing_sailtrim.py` asserts the two agree.
    published_level: int

    @property
    def xp_per_hour(self) -> float:
        """Flat within a tier: a trim pays the same at every level."""
        return self.trim_experience * SECONDS_PER_HOUR / TRIM_SECONDS


MASTS: tuple[Mast, ...] = (
    Mast("wooden", None, 10.5, 1),
    Mast("oak", "Build an ~|oak mast and linen sails|~", 19.5, 24),
    Mast("teak", "Build a ~|teak mast and canvas sails|~", 30.0, 36),
    Mast("mahogany", "Build a ~|mahogany mast and canvas sails|~", 48.0, 52),
    Mast("camphor", "Build a ~|camphor mast and canvas sails|~", 64.0, 68),
    Mast("ironwood", "Build an ~|ironwood mast and cotton sails|~", 80.0, 83),
    Mast("rosewood", "Build a ~|rosewood mast and cotton sails|~", 125.0, 94),
)

#: The wooden tier's own build challenge. It is **not** what gates the wooden
#: band - the quest raft is - but it is what the level check is asserted
#: against, so it is named rather than left out of the module.
WOODEN_BUILD_TASK = "Build a ~|wooden mast and linen sails|~"


def level_for(mast: Mast, builds: Mapping[str, object]) -> int:
    """The Sailing level `mast` opens at, preferring upstream's own statement.

    Upstream writes it on the build challenge as `Skills: {"Sailing": N}`.
    Falling back to `published_level` covers the tier with no build gate and
    the day upstream stops stating one; the two agree on the real export.
    """
    challenge = builds.get(mast.build_task or WOODEN_BUILD_TASK)
    if isinstance(challenge, Mapping):
        stated = challenge.get("Skills")
        if isinstance(stated, Mapping):
            level = stated.get(SKILL)
            if isinstance(level, int):
                return level
    return mast.published_level


def methods(
    valid: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Sailing": bands}` for the mast tiers this map can trim.

    Nothing at all unless upstream's own trim challenge is valid, since that
    is the statement that this map has a boat. Above that, a tier is offered
    where its **build** challenge is - the mast has to exist before it can be
    trimmed - except the wooden one, which arrives with the quest raft.
    """
    if TRIM_TASK not in (valid.get(SKILL) or {}):
        return {}
    builds = valid.get(BUILD_SKILL) or {}
    bands = tuple(
        ComputedMethod(
            method=f"trimming {mast.tier} sails",
            xp_per_hour=mast.xp_per_hour,
            level=level_for(mast, builds),
            match=CONFIRMED,
            knob=f"training/{TRIM_TASK}/{SKILL}",
        )
        for mast in MASTS
        if mast.build_task is None or mast.build_task in builds
    )
    return {SKILL: bands} if bands else {}
