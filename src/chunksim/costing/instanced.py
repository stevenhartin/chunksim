"""Monsters you cannot walk up to, and the one place that says what killing
one costs.

**Three layers had independently decided what a boss kill is worth, and two of
them were wrong.** `costing/combat_xp.py` knew a raid room is not a training
spot; `costing/estimate.py`'s item walk knew a raid drop is priced by the
raid; and `costing/estimate.py`'s *kill-goal* path knew neither, so four
Grandmaster Combat Achievements naming `TzKal-Zuk` shared **0.05 hours**
between them at the fallback twenty kills an hour. Each layer asking its own
question the same way is how that happened, and this module is the single
answer all of them now ask for.

### The rule

**A monster reachable only inside a run costs a run.** Not a kill, not a
kill-rate: entering is the price, and everything the run yields - experience,
drops, the boss's death - is bought with the same completion. Whoever wants a
number about such a monster asks here first, and gets `None` only when this
module genuinely cannot answer, never as a licence to fall back on a
kills-per-hour that does not describe the activity.

### Places are resolved from the export, never listed by name

This started as a frozenset of seven area names in `costing/combat_xp.py`, and
that shape had a hole in it big enough to matter: **the export files the same
place under both a name and a numbered chunk**, and only the name was in the
set. Fourteen numbered chunks carry an instanced area's `Name` -
`9551` is the Fight Caves, `9043` the Inferno, `13197` the Tombs of Amascut,
five separate squares are the Theatre - and a map holding one of *those*
had its monsters read as ordinary: farmable for experience, drops priced at a
kills-per-hour, a boss kill worth three minutes.

So `place_ids` resolves the names against `chunkinfo.chunks` every call and
returns both vocabularies. That is deliberately not a checked-in alias table:
an alias table is a second thing to keep in step with an export that grows,
and this project has retired more than one of those. A new square for an
existing raid is picked up with nothing edited.

### What is *not* claimed

**Only a run's final boss is priced.** Killing one is completing the run, so
the two are the same sentence and the arithmetic is exact. The rank-and-file
are just as unreachable, but the cheapest way to reach one is to fight up to
wherever it first appears - a partial run - and neither `costing/tzhaar.py`
nor the raid modules carry the wave or room *ordering* that would need. They
return `None`, and the day a map's goal actually needs one is the day the
ordering has to come back rather than the day a plausible number gets
invented.

**The Theatre's bosses are absent from the export's chunk lists entirely** -
`Theatre of Blood` and its five numbered squares carry no `Monster` branch at
all - so no map can be asked to kill Verzik through this path. `FINAL_BOSS`
names her anyway, because the export growing one is a change to upstream's
data and not to this argument.

Pure: the export is handed in, and the run durations come from the modules
that own them.
"""

from __future__ import annotations

from typing import Iterable, Mapping

from chunksim.costing import colosseum, gauntlet, raids, tzhaar
from chunksim.model.chunkinfo import ChunkInfo

#: The places whose monsters are fought as part of a run rather than found
#: standing about. **Names**; `place_ids` adds the export's numbered squares.
#:
#: `Gauntlet Lobby` and `Tombs of Amascut Lobby` are here for the reason the
#: arenas are: a lobby's monsters belong to the run you are about to start.
#: **`Fortis Colosseum Underground` is that same shape for the Colosseum** -
#: the eleven-wave roster and Sol Heredit have no chunk of their own at all,
#: matching the Theatre's own absence (see the module docstring), so the
#: lobby is the only chunk there is to name; `FINAL_BOSS` and
#: `DEFAULT_RUN_SECONDS` still key the run itself as `"Fortis Colosseum"`,
#: matching `costing/colosseum.FORTIS_COLOSSEUM` and every other activity
#: name here.
RUN_ONLY_PLACES: frozenset[str] = frozenset(
    {
        "Chambers of Xeric",
        "Theatre of Blood",
        "Tombs of Amascut",
        "Tombs of Amascut Lobby",
        "Inferno",
        "Fight Caves",
        "Gauntlet Lobby",
        "Fortis Colosseum",
        "Fortis Colosseum Underground",
    }
)

#: `final boss -> the place it ends`. Matched on the base name, before any
#: `#version` suffix: the export writes `Great Olm#Head`, `#Left claw` and
#: `#Right claw`, and killing any of them is the same one raid.
#: **Both Hunllefs point at the one `Gauntlet Lobby` chunk** - there is no
#: separate arena chunk for either variant to be keyed on, matching the
#: Colosseum's own absence - but they need *different* durations, which is
#: exactly why `kill_seconds` below special-cases them by monster rather
#: than trusting the shared place to answer.
FINAL_BOSS: Mapping[str, str] = {
    "TzKal-Zuk": "Inferno",
    "TzTok-Jad": "Fight Caves",
    "Great Olm": "Chambers of Xeric",
    "Verzik Vitur": "Theatre of Blood",
    "Tumeken's Warden": "Tombs of Amascut",
    "Elidinis' Warden": "Tombs of Amascut",
    "Sol Heredit": colosseum.FORTIS_COLOSSEUM,
    gauntlet.BOSS[gauntlet.REGULAR]: "Gauntlet Lobby",
    gauntlet.BOSS[gauntlet.CORRUPTED]: "Gauntlet Lobby",
}

#: Where each place's run duration comes from. **The raids and the
#: Colosseum spend their published figure and the wave minigames spend
#: `costing/tzhaar.py`'s band**, which is the same split those modules
#: already document - and the reason this is a table rather than an `if`: a
#: place with no entry is a place this module refuses to price, loudly and
#: in one spot. `Fortis Colosseum Underground` duplicates the Colosseum's
#: own figure for the same reason `Tombs of Amascut Lobby` duplicates the
#: Tombs' - `run_only` can name either chunk and `run_seconds` must answer
#: for both. **`Gauntlet Lobby` stores the regular variant's own figure** -
#: it is only ever read by `unpriced_bosses`' membership check and by a
#: caller asking about the bare place rather than a specific Hunllef;
#: `kill_seconds` never reaches it for either boss, since both are
#: special-cased to `gauntlet.kill_seconds` before this dict is consulted.
DEFAULT_RUN_SECONDS: Mapping[str, float] = {
    "Chambers of Xeric": raids.PUBLISHED_RAID_SECONDS[raids.CHAMBERS],
    "Theatre of Blood": raids.PUBLISHED_RAID_SECONDS[raids.THEATRE],
    "Tombs of Amascut": raids.PUBLISHED_RAID_SECONDS[raids.TOMBS],
    "Tombs of Amascut Lobby": raids.PUBLISHED_RAID_SECONDS[raids.TOMBS],
    "Inferno": tzhaar.RUN_SECONDS[tzhaar.INFERNO],
    "Fight Caves": tzhaar.RUN_SECONDS[tzhaar.FIGHT_CAVES],
    colosseum.FORTIS_COLOSSEUM: colosseum.PUBLISHED_SECONDS,
    "Fortis Colosseum Underground": colosseum.PUBLISHED_SECONDS,
    "Gauntlet Lobby": gauntlet.PUBLISHED_SECONDS[gauntlet.REGULAR],
}


def place_ids(chunk_info: ChunkInfo) -> frozenset[str]:
    """Every chunk id that *is* one of `RUN_ONLY_PLACES` - the names, plus
    every numbered square whose `Name` is one of them.

    **Resolved from the export rather than listed**, which is the whole point
    - see the module docstring on the fourteen squares the name-only set
    missed.
    """
    found = set(RUN_ONLY_PLACES)
    for chunk_id, body in chunk_info.chunks.items():
        if isinstance(body, dict) and body.get("Name") in RUN_ONLY_PLACES:
            found.add(chunk_id)
    return frozenset(found)


def run_only(where: Iterable[str], places: frozenset[str]) -> bool:
    """Whether every chunk `where` names is part of a run.

    **"Every" rather than "any", deliberately.** A lizardman shaman is in the
    Chambers of Xeric *and* in the Lizardman Temple, and the temple is a place
    you can stand - so it is farmable and the Chambers' copy is beside the
    point. `places` is `place_ids`' answer, hoisted by the caller because it
    walks the whole export.
    """
    seen = list(where)
    return bool(seen) and all(chunk in places for chunk in seen)


#: The knob branch a run's duration is edited under, and the one place that
#: name is spelled. `costing/estimate.py` hands it to the panel and
#: `gui/knobs.py` resolves it back, so a rename is one edit rather than a
#: string that agrees with another string by luck.
KNOB_BRANCH = "runs"


def knob_for(place: str) -> str:
    """The knob path that edits `place`'s run duration."""
    return f"{KNOB_BRANCH}/{place}"


def run_seconds(place: str, overrides: Mapping[str, float] = {}) -> float | None:
    """How long one completion of `place` takes, correction applied.

    `overrides` is `Heuristics.run_seconds` - the `runs` branch. **The wave
    minigames defer to `costing/tzhaar.py`** rather than being answered here,
    so the entry-fee arithmetic has one owner.
    """
    if place in (tzhaar.INFERNO, tzhaar.FIGHT_CAVES):
        return tzhaar.run_seconds(place, overrides)
    got = overrides.get(place)
    if isinstance(got, (int, float)) and not isinstance(got, bool) and got > 0:
        return float(got)
    return DEFAULT_RUN_SECONDS.get(place)


def place_of_boss(monster: str) -> str | None:
    """Which run `monster` ends, or `None`. Ignores a `#version` suffix."""
    return FINAL_BOSS.get(monster.split("#")[0])


def kill_seconds(
    monster: str, overrides: Mapping[str, float] = {}
) -> float | None:
    """**The one answer to "what does killing this once cost".**

    Every layer that wants a boss's kill time asks this, so the item walk, the
    kill-goal path and anything added later cannot disagree about it - which
    they did, by a factor of thirty, until this existed.

    A run's final boss costs one completion of that run. The Inferno's carries
    a Fight Caves run as well, that being its published entry fee, and
    `costing/tzhaar.py` owns that arithmetic rather than this module
    duplicating it.

    `None` means "not a final boss", and callers should read it as *no opinion*
    rather than as free: the rank-and-file of a run are unreachable too, and
    what stops them being priced here is the missing room ordering, not a
    belief that they are cheap.
    """
    place = place_of_boss(monster)
    if place is None:
        return None
    if place in (tzhaar.INFERNO, tzhaar.FIGHT_CAVES):
        # `tzhaar` owns the entry fee, so ask it rather than re-deriving one.
        return tzhaar.kill_seconds(monster.split("#")[0], overrides)
    if place == "Gauntlet Lobby":
        # `gauntlet` owns which variant `monster` is and its entry fee - the
        # place alone cannot tell the two Hunllefs apart, see `FINAL_BOSS`.
        return gauntlet.kill_seconds(monster.split("#")[0], overrides)
    return run_seconds(place, overrides)


def unpriced_bosses() -> frozenset[str]:
    """Final bosses whose place has no run duration behind it.

    **The contract test's subject**, and the narrow version of that test on
    purpose. A place with no duration is only a hazard if something is
    supposed to *cost* one: `kill_seconds` would return `None`, the caller
    would fall back on a kills-per-hour, and the boss would silently read as
    three minutes again.

    A place with no boss and no monsters is inert, which is what
    `Gauntlet Lobby` is - the export gives it one NPC and nothing to fight, so
    it prices nothing and excludes nothing. It stays in `RUN_ONLY_PLACES`
    because the day the export puts the Hunllef in it, being already listed is
    the difference between this returning a name and a map training on a raid
    boss. `tests/test_costing_instanced.py` pins that emptiness so the change
    is noticed.
    """
    return frozenset(
        boss for boss, place in FINAL_BOSS.items() if place not in DEFAULT_RUN_SECONDS
    )
