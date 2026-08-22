"""The Hosidius Mess, which hands you the ingredients.

**A Cooking minigame that charges nothing for what it cooks**, and that is
both why it is worth modelling and why nothing else here could reach it. The
page says it outright: "The Mess is notable for offering Cooking training
without any requirements to gather materials, making it particularly useful
for Ironman and Ultimate Ironman accounts." Flour, meat, potatoes, cheese,
tomatoes, pineapples, bowls, dishes and knives all come out of cupboards
inside the building.

That is exactly the asymmetry `recipe_rates.apply` describes from the other
side. A `{{Recipe}}` exists for each of the three foods and joins upstream's
challenges perfectly well - and then loses its input, because `Servery
uncooked pie` has no route anywhere in the export and never will: it is made
in a kitchen a chunk map either holds or does not. Priced through the recipe
layer the method is dropped; priced as an activity it is one of the best
Cooking rates in the game, precisely because everything else is charged for
its materials and this is not.

### Three foods, three levels, and every figure published

`Mess` states the gate for each - "20 Cooking is required to cook servery meat
pie, 25 for servery stew, and 65 for servery pineapple pizza" - which is
upstream's own `Level` on all three, exactly. It then states each food's rate
twice over, and the two agree:

    food             lvl   per turn-in   per inventory   realistic    perfect
    Servery meat pie  20        ~160       ~2,300 (14)   48,000-55,000  60,000+
    Servery stew      25        ~168       ~2,400 (14)   60,000-69,000  72,000+
    Pineapple pizza   65        ~369       ~5,000 (13)  165,000-180,000 200,000+

**The two columns are a real check on each other.** 14 x 160 is 2,240 against
a stated 2,300; 14 x 168 is 2,352 against 2,400; 13 x 369 is 4,797 against
5,000 - each 2.5% to 4% low, and in the same direction for the same reason.
The turn-in is not the whole of what an inventory pays: cooking the servery
raw meat and cooking the uncooked pie are Cooking actions too, and the
per-inventory figure carries them where the turn-in figure does not.

### Which figure is spent, and what that costs

**The low end of the realistic band**, which is `costing/pyramid.py`'s rule
for a range the page itself hedges ("depending on Cooking level and
concentration levels"). The stated ceilings are recorded and not spent, for
`costing/sepulchre.py`'s reason: "with perfect clicks" is a claim about a
human rather than a mechanic, and tick-perfect is not a rate.

The cost is stated rather than hidden. The pizza reads **165,000/hr** where
the page's perfect figure is above 200,000, and there is a further 94,000/hr
stew variant on the page - dropping the meat and unfinished stews and picking
them up one at a time - which is not carried either, being a strictly harder
regime than the one its own band was observed under.

**Nothing is banded within a food.** The page ties the level dependence to
burning and states two of the three thresholds (58 for stews, 68 for plain
pizzas) but bundles it with concentration in one range, so where inside the
band a given level falls is not something the page says. Three foods opening
at 20, 25 and 65 already give the activity a three-step curve, and
`training_bands` takes the running maximum over them.

### No material cost, deliberately

`Heuristics.material_seconds_per_xp` is filled from the recipe corpus, and
these three fill nothing there because their inputs have no route - so a
`ComputedMethod` here carries no material charge, which is the right answer
rather than a lucky one. It is the same trap `costing/gotr.py` fell into from
the other direction: an activity that gathers what it consumes must carry no
material cost at all, and charging the essence twice cost Runecraft its whole
climb.

Pure: nothing but the valid set comes in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from chunksim.costing.gathering import CONFIRMED
from chunksim.costing.heuristics import ComputedMethod

SKILL = "Cooking"


@dataclass(frozen=True)
class Food:
    """One of the three foods, and everything the page states about it."""

    task: str
    #: What a report calls it.
    name: str
    #: The Cooking level the page gates it at, which is upstream's own.
    level: int
    #: Experience for turning one in, per the page's "About N Cooking
    #: experience is gained when turning in a ...".
    turn_in: float
    #: How many fit in the inventory the strategy section describes.
    per_inventory: int
    #: What that inventory pays, which includes the intermediate cooking the
    #: turn-in figure does not.
    inventory_experience: float
    #: The low and high ends of "at lower levels, expect to get around ...".
    realistic: tuple[float, float]
    #: "With perfect clicks, it is possible to get above ...". Recorded, not
    #: spent - see the module docstring.
    perfect: float
    #: The level at which the food stops burning, where the page states one.
    no_burn_level: int | None = None

    @property
    def xp_per_hour(self) -> float:
        """The rate this carries: the low end of the realistic band."""
        return self.realistic[0]

    @property
    def inventories_per_hour(self) -> float:
        """What `xp_per_hour` implies, as a check on it being a real cadence."""
        return self.xp_per_hour / self.inventory_experience


#: The three foods, in the order the page lists them.
FOODS: tuple[Food, ...] = (
    Food(
        task="Make a ~|servery meat pie|~",
        name="servery meat pie",
        level=20,
        turn_in=160.0,
        per_inventory=14,
        inventory_experience=2_300.0,
        realistic=(48_000.0, 55_000.0),
        perfect=60_000.0,
    ),
    Food(
        task="Make a ~|servery stew|~",
        name="servery stew",
        level=25,
        turn_in=168.0,
        per_inventory=14,
        inventory_experience=2_400.0,
        realistic=(60_000.0, 69_000.0),
        perfect=72_000.0,
        no_burn_level=58,
    ),
    Food(
        task="Make a ~|servery pineapple pizza|~",
        name="servery pineapple pizza",
        level=65,
        turn_in=369.0,
        per_inventory=13,
        inventory_experience=5_000.0,
        realistic=(165_000.0, 180_000.0),
        perfect=200_000.0,
        no_burn_level=68,
    ),
)

#: The stew variant the page describes and this does not carry: "It is
#: possible to achieve around 94,000 experience per hour by dropping the meat
#: and unfinished stews before cooking them, and picking them up one at a
#: time to use on the range." A strictly harder regime than the one the band
#: beside it was observed under, so it is recorded rather than spent.
STEW_DROP_TRICK_PER_HOUR = 94_000.0


def methods(
    valid: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Cooking": (...)}` for whichever foods a map can reach.

    One band a food rather than a curve within one - see the module docstring
    on why the page's own range cannot be located against level. The three
    opening levels give the activity its curve, and `training_bands` takes the
    running maximum over them.
    """
    reachable = valid.get(SKILL) or {}
    found = tuple(
        ComputedMethod(
            method=food.name,
            xp_per_hour=food.xp_per_hour,
            level=food.level,
            match=CONFIRMED,
            knob=f"training/{food.task}/{SKILL}",
        )
        for food in FOODS
        if food.task in reachable
    )
    return {SKILL: found} if found else {}
