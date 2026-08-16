"""What a Blast Mine ore costs, which is not one blast.

**The same defect as `costing/paydirt.py`, in a second activity.** The export
carries `Obtain ~|runite ore|~ from blasted ore` with `Output: Runite ore` and
no stated pace, so the item walk priced it at `DEFAULT_ACTION_SECONDS` and
believed the Blast Mine handed over runite ore every 6.6 seconds. On the
every-rollable-chunk map that made a runite bar cost 17 seconds, which is what
the question "what shop sells runite ore?" turned up - no shop did; this did.

**And the Blast Mine really is the best runite in the game**, which is why the
right answer is a number rather than a refusal: 91 seconds an ore against 240
for mining the rock. Getting it wrong by a factor of fourteen is not the same
as it being a bad route.

### Everything needed is published

- **330 blasts an hour**, stated outright and confirmed by the page's own
  second figure: lighting the dynamite pays 50 Firemaking experience and the
  page quotes 16,500 Firemaking an hour, which is 330 lights.
- **The ore distribution**, as a five-row table summing to 100%.
- **Base experience** per ore, and the Mining level each needs - note these are
  the *blast mine's* levels, which are ten lower than the rock's own: "the
  blast mine allows players to obtain ores as though their Mining level were 10
  levels higher (e.g. a player can obtain runite ore with only 75 Mining
  instead of the usual 85)".
- **55,000 Mining experience an hour at level 70**, which is the anchor that
  turns the rest into a count of ores.

That last one is what `ores_per_blast` is derived from rather than guessed:
excavating pays 20 Mining a blast, so 330 x 20 = 6,600 of the 55,000 is the
digging and the other 48,400 is ore. At level 70 runite is still locked, so
the four remaining shares renormalise to 137.3 experience an ore - and 48,400
over that is 352.5 ores an hour, or **1.068 an ore per blast**.

### A locked ore redistributes rather than vanishing

A player below an ore's level does not roll it at all and the rest of the
table shares its 11.2% out, which is why the same activity pays 137.3
experience an ore at level 70 and 151.1 at 75.

Pure: the level comes in as an argument.
"""

from __future__ import annotations

#: Ore -> `(Mining level the blast mine needs, base experience, share of the
#: table as a percentage)`. The levels are the blast mine's own, ten below the
#: rock's.
ORES: dict[str, tuple[int, float, float]] = {
    "Coal": (43, 33.0, 4.5),
    "Gold ore": (43, 66.0, 14.3),
    "Mithril ore": (43, 120.0, 31.4),
    "Adamantite ore": (60, 190.0, 38.6),
    "Runite ore": (75, 260.0, 11.2),
}

#: The export's challenge per ore. Only three, which is upstream's choice.
OBTAIN: dict[str, str] = {
    "Mithril ore": "Obtain ~|mithril ore|~ from blasted ore",
    "Adamantite ore": "Obtain ~|adamantite ore|~ from blasted ore",
    "Runite ore": "Obtain ~|runite ore|~ from blasted ore",
}

#: "Assuming 330 dynamite used per hour", and the page's 16,500 Firemaking an
#: hour over 50 experience a light says the same thing.
BLASTS_PER_HOUR = 330.0

#: "Excavating the hard rock earns 20 Mining experience", once a blast.
EXCAVATE_EXPERIENCE = 20.0

#: The anchor `ores_per_blast` is derived from: "at level 70, players can
#: expect approximately 55,000 Mining experience".
ANCHOR_LEVEL = 70
ANCHOR_EXPERIENCE_PER_HOUR = 55_000.0


def shares(level: int) -> dict[str, float]:
    """Each ore's share of one blasted ore at `level`, summing to one.

    An ore below its level is not rolled, and the rest take its share.
    """
    usable = {ore: entry for ore, entry in ORES.items() if level >= entry[0]}
    total = sum(entry[2] for entry in usable.values())
    if total <= 0:
        return {}
    return {ore: entry[2] / total for ore, entry in usable.items()}


def experience_per_ore(level: int) -> float:
    """What one blasted ore pays on average at `level`."""
    return sum(share * ORES[ore][1] for ore, share in shares(level).items())


def ores_per_blast() -> float:
    """Blasted ores a blast yields, from the page's own hourly anchor.

    Derived rather than stated: the page gives an experience an hour and the
    experience of every part of it, so the count is the only unknown left.
    """
    digging = BLASTS_PER_HOUR * EXCAVATE_EXPERIENCE
    per_ore = experience_per_ore(ANCHOR_LEVEL)
    if per_ore <= 0:
        return 0.0
    return (ANCHOR_EXPERIENCE_PER_HOUR - digging) / per_ore / BLASTS_PER_HOUR


def ores_per_hour() -> float:
    return BLASTS_PER_HOUR * ores_per_blast()


def action_seconds(level: int) -> dict[str, float]:
    """`{challenge: seconds}` for each `Obtain ... from blasted ore`.

    An ore the level cannot reach is omitted rather than priced, which the
    item walk reads as "no stated pace" - the honest answer, and the one that
    keeps it off the four-tick default.
    """
    per_hour = ores_per_hour()
    if per_hour <= 0:
        return {}
    got = shares(level)
    return {
        task: 3600.0 / (per_hour * got[ore])
        for ore, task in OBTAIN.items()
        if got.get(ore, 0.0) > 0.0
    }
