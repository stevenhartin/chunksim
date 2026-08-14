"""What a map's `rules` branch is before a player has touched it.

**A missing rule key is not the same as a rule turned off**, and that is the
whole reason this module exists. `_category_gate_met` skips a gate whose
category the map does not mention at all (`derive/challenges.py:1300`) but
refuses one the map sets to `False`, so an empty `rules` is *maximally
permissive*. Measured on the real export, three chunks unlocked:

    rules              valid tasks   available items
    {} (absent)                  7               526
    these defaults               1                 0
    a real player's              2                 3

**526 obtainable items on a three-chunk world** is the number that matters, and
it is not a rounding error - it is every item the map could reach if no rule
said otherwise. A blank map with no rules would not be a neutral map, it would
be a spectacularly wrong one, so a map this project makes from nothing seeds
these instead of leaving the branch out.

Ported from upstream's own seed literal, `let rules = {...}` at
**index.js:348-452** on the `gh-pages` branch, read 2026-08-14. It is upstream's
answer to "what does a new player start with", which is the only answer this
project is entitled to give; inventing a house default would be exactly the
guess the rest of the codebase refuses.

**103 keys: 99 flags, all off, and four amounts that are strings.** The amounts
are strings upstream and stay strings here - `model/rates.py` parses them and a
silent int would change what `"1/0"` means.

Two things a later reader will be tempted to "fix" and should not:

- **`Rare Drop Amount` is `"1000"` here** where `derive/sources.py:191-196`
  falls back to `"0"`. Both are right. This is what upstream *seeds*; that is
  what this project assumes when the key is **missing entirely**, which is a
  different question about a different map.
- **This is a strict subset of a real map's rules.** Live maps grow keys the
  seed literal has never carried - `Herblore Unlocked Exception` on both maps
  cached here, plus `Manually Add Tasks` and `Random Event Loot` on one. None of
  the three is read anywhere in this project, so their absence costs nothing;
  do not pad the table to match a particular player's map.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

#: Upstream's seed rules, read-only so no caller can edit the table every other
#: caller is about to read. Use `default_rules()` for a copy you may mutate.
DEFAULT_RULES: Mapping[str, bool | str] = MappingProxyType(
    {
        "Skillcape": False,
        "Rare Drop": False,
        "Pouch": False,
        "InsidePOH": False,
        "InsidePOH Primary": False,
        "Construction Milestone": False,
        "Construction Minigame": False,
        "Boss": False,
        "Boss Level": False,
        "Slayer Equipment": False,
        "Normal Farming": False,
        "Raking": False,
        "Sulphurous Fertiliser": False,
        "CoX": False,
        "Tithe Farm": False,
        "Kill X": False,
        "Kill X Boss": False,
        "Sorceress's Garden": False,
        "Spells": False,
        "Show Skill Tasks": False,
        "Show Quest Tasks": False,
        "Show Diary Tasks": False,
        "Show Best in Slot Tasks": False,
        "Show Best in Slot Prayer Tasks": False,
        "Show Best in Slot Defensive Tasks": False,
        "Show Best in Slot Flinching Tasks": False,
        "Show Best in Slot Weight Tasks": False,
        "Show Best in Slot Melee Style Tasks": False,
        "Show Best in Slot 1H and 2H": False,
        "Consumable Primary BiS": False,
        "Show Quest Tasks Complete": False,
        "Show Diary Tasks Complete": False,
        "Show Diary Tasks Any": False,
        "Highest Level": False,
        "BIS Skilling": False,
        "Collection Log": False,
        "Minigame": False,
        "PvP Minigame": False,
        "Shortcut Task": False,
        "Shortcut": False,
        "Wield Crafted Items": False,
        "Wield Crafted Items Override": False,
        "Multi Step Processing": False,
        "Shooting Star": False,
        "Forestry": False,
        "ForestryXp": False,
        "Puro-Puro": False,
        "Extra implings": False,
        "Collection Log Bosses": False,
        "Collection Log Raids": False,
        "Collection Log Clues": False,
        "Collection Log Minigames": False,
        "Collection Log Other": False,
        "Herblore Unlocked": False,
        "Farming Primary": False,
        "Tertiary Keys": False,
        "Wandering implings": False,
        "Secondary Primary": False,
        "Secondary Primary Amount": "1",
        "RDT": False,
        "Untracked Uniques": False,
        "Combat and Teleport Spells": False,
        "Primary Spawns": False,
        "Smithing by Smelting": False,
        "Pets": False,
        "Jars": False,
        "Stuffables": False,
        "Kill X Amount": "1",
        "Rare Drop Amount": "1000",
        "Collection Log Clues Amount": "100",
        "Manually Complete Tasks": False,
        "Every Drop": False,
        "Herblore Unlocked Snake Weed": False,
        "HigherLander": False,
        "Starting Items": False,
        "Tutor Ammo": False,
        "Secondary MTA": False,
        "Fossil Island Tasks": False,
        "Combat Diary Tasks": False,
        "PVP-Only Spells": False,
        "Skilling Pets": False,
        "Money Unlockables": False,
        "Additional Money Unlockables": False,
        "Prayers": False,
        "All Droptables": False,
        "All Droptables Nest": False,
        "Every Drop Implings": False,
        "F2P": False,
        "Skiller": False,
        "Fill Stash": False,
        "Fill POH": False,
        "All Shops": False,
        "Quest Skill Reqs": False,
        "Cleaning Herbs": False,
        "Boosting": False,
        "Superheat Furnace": False,
        "Partial Products": False,
        "POH Rooms": False,
        "KeyItem Bosses": False,
        "Sail Trimming": False,
        "Crewmates": False,
        "Sea Charting": False,
        "Fish Offcuts Valid Processing": False,
    }
)


def default_rules() -> dict[str, bool | str]:
    """A fresh mutable copy of upstream's seed rules.

    Mirrors `gui/settings.defaults()`: the constant is the statement of what
    the defaults *are*, and callers that are about to build a payload get their
    own dict rather than a reference into it.
    """
    return dict(DEFAULT_RULES)
