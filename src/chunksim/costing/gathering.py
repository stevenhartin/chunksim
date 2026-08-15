"""How fast a resource comes out of the ground, computed rather than looked up.

**One model for five skills, because the game has one.** Fishing, Mining,
Woodcutting, Hunter and Thieving are the same loop wearing different animations:
stand at a node, roll every so many ticks, sometimes get the thing, and lose
time when the node runs out. Three numbers decide the rate and
`remote/gathering.py` reads all three off the wiki, so this module is arithmetic
over a config file and nothing else:

    xp/hr = experience * 3600 / (
        max(respawn, roll_seconds / chance / units / duty + stun * failures)
        + bank_share
    )

**What it replaces is a published figure, not a gap.** `remote/skill_tables.py`
joins hourly rates off training guides, which is real data but somebody else's -
their level, their axe, their account - and it reaches only the methods somebody
wrote a guide about. A computed rate answers for *every* method the chart data
covers, at *this* map's level and with *this* map's best reachable tool, which
is the thing a published number structurally cannot do. That is why this layer
sits **above** the scrape where `costing/recipe_rates.py` sits below it: a recipe
and a money-making guide answer different questions, but a success curve and a
guide answer the same one, and the curve knows whose account it is describing.

**The three inputs, and which is easy to forget.**

1. *Roll interval.* Fixed per skill for four of the five - a tree rolls every
   four ticks whatever you swing at it. Mining is the exception and the wiki
   states why: "Your level affects the chance of getting ore each time the game
   rolls; your pickaxe affects how often that happens" (Mod Ash, 28 October
   2019). So one skill reads its interval off the tool and the rest read a
   constant, which `SkillProfile.tool_axis` is the whole of.
2. *Success chance.* `success_chance` below, exact game arithmetic.
3. *Inactivity.* **This is the one that looks optional and is not.** Priced with
   rolls alone, a normal tree reads 37,500 xp/hr against the wiki's published
   12,500 - because a normal tree hands over one log and vanishes. Charge the
   despawn/respawn cycle and it is 12,162, which is 0.97x the published figure.
   Measured across the nine tabulated trees, rolls-alone runs 1.05x to 3.00x
   fast and the published rate always lands *between* the no-downtime bound and
   the single-node one; how many of them you work at once is what picks a point
   between them, and it is `SkillProfile.worked`.

**Inactivity has four published shapes, not one**, and which one a node has is
the difference between a model and a fitted constant:

- a *duty cycle*, for a node that yields for a window and then regrows - every
  tree the Woodcutting page tabulates;
- a *flat charge per resource*, for a node that hands over one thing and
  vanishes - every rock, and every tree below oak, whose downtime nothing
  publishes and which is therefore fitted;
- a *restock floor*, for a node that is empty until it comes back. A stall is
  this and the wiki tabulates all thirty, so `max(respawn, rolling)` is the
  whole of Thieving's stall half and there is nothing left to fit;
- a *stun*, for a loop where failing costs more than trying. A failed
  pickpocket locks you out for eight ticks against a two-tick attempt, both
  stated on the Pickpocketing page.

**And one loop rolls more than once per action.** `Skilling success rate`
documents a *cascade*: the best outcome is rolled, and on failing it the next,
until one lands or all fail. Barbarian fishing is sturgeon, then salmon, then
trout, and pricing it as a single roll left two thirds of what the action pays
uncounted - it read 0.73x and was refused for it. `SkillProfile.cascades` names
the order, and the expectation over the whole thing is what `xp_per_hour`
prices, while the *marginal* branch is what `seconds_per_item` charges, so the
item walk still knows a sturgeon is not an average fish. Herbiboar is the other
cascade in the game and is not modelled.

**Throughput is not always one node at a time, and that is one idea rather than
a per-skill quirk.** `units_worked` resolves a single count - a per-node figure
where a location publishes one, else a published level table, else the skill's
default - and `rate_at` spends it against whatever that node makes you wait for:

- a *cycle* node fills its gap, via `duty_cycle`, capped at having no wait. Two
  trees is Woodcutting's fitted answer.
- a *restock* node divides its wait, **but only where you can get back before
  it finishes**. Three chests share one room at the Rogues' Castle, so 20.4
  seconds of restock becomes 6.8 and stops binding at all; Ardougne market
  holds several stalls of one type too far apart to be worth the walk, so they
  wait. That test is a fact about a route rather than about a node, nothing
  publishes it and the export cannot supply it - see `SkillProfile.worked_at`,
  which is therefore a hand entry per method and defaults to one.
- a **simultaneous** loop divides the *rolling*, the only one of the three that
  beats one-at-a-time throughput. Box trapping, net trapping and bird snaring
  run 1 to 5 traps across levels 1 to 80 off the Hunter page's table, with a
  sixth in the Wilderness, and it is most of why hunting speeds up with level -
  none of which is in a success curve.

Rotation never makes the *action* quicker: you swing at one tree and open one
chest at a time. Letting the count reach the rolling was a real regression when
these were unified, and the fit is what found it - every untabulated tree
chopped twice as fast, and `node_seconds` moved 2.4 -> 3.7 to absorb it.

**Banking is deliberately not charged here.** A published gathering rate is
quoted for a player dropping what they gather, and that is also how the item
walk wants it: when Fletching buys its logs from this model, the trip that
carries them is the *production* action's overhead and is charged there. Adding
it to both is how a material gets billed twice, which is the mistake
`costing/training._material_cost` already exists to prevent.

**Per-skill quirks are properties, not branches.** `SkillProfile` carries them
and every gathering skill has one, so a quirk that turns out to matter for a
second skill costs a field value rather than an `if`. `tool_tiers` is the
clearest case: a `Willow tree` chart's nine series are axe tiers, where a
`Warrior (Thieving)` chart's four are equipment bonuses and a `Black
chinchompa` chart's three are different creatures - so exactly one skill reads
series as tools, and the rest take the first series, which is the unassisted
case and the same conservative reading `remote/skill_tables.parse_hunter` takes.

**A published figure is quoted for a player, and three things follow from
that.** It carries a bank run where the method banks and none where the method
drops - `bank_seconds` against `unbanked`, which is the difference between
ordinary fishing and barbarian fishing *inside one skill*. It is quoted at the
level the method opens at, which is why a cascade must be compared at one level
and counted once: the three barbarian challenges are one action, and scoring
them separately at 99 triple-counts one observation against two figures
describing other players. And it assumes whatever facility the guide's author
had - a Wilderness three-chest rotation, for instance, which is a fact about
the location rather than about the method and has to be modelled as one:
`parallel_bonus` carries the count, and for a restock-bound loop it divides the
*wait* rather than the clicking, because three chests do not let you open any
faster - they mean the first has restocked by the time you are back at it.

**Every success chance says where it came from**, in three words and no more:
`confirmed` for a reading - a chart, or prose stating the odds outright -
`inferred` for one constructed from a measurement of the same kind of thing,
and `guess` for a number chosen so the method has one. It rides on the
`NodeRate` because by the time a chance has been through the arithmetic nobody
downstream could tell the three apart, and the scraped tables carry it too so
the file says what it is. There are three guesses today, all of them pitfall
cats, and they are the first thing to replace.

**A rate is only as good as its weakest half**, so an interval borrowed from a
sibling loop caps the provenance too: rabbit snaring has a measured success
chance and box trapping's cadence, and reports `inferred` for it. Where the
calculator's own `type` is blank or a grab-bag, `loop_at` says which loop a node
really belongs to - the export names the trap in `Items`, which is the better
authority than a column meant for grouping a table.

**A curve can be borrowed, which is one of two places this model assumes rather
than reads.** The wiki keeps `Category:Needs skilling success chart` - its own list
of what nobody has measured - and three butterflies on it are methods a map can
actually train. What makes a borrow defensible is that the charted butterflies
climb *identically*: black warlock, sunlight moth and moonlight moth all gain
`276/98` of a catch per level and differ only in what they are worth where they
open, 0.57, 0.79 and 0.82. So the line is real and only its position is unknown,
and `assumed_curves` moves the worst of the three sideways until it opens where
the borrower does. It is the only inference here that is not a reading, it is
marked `assumed: <donor>` in the rate it produces, and an entry should be
deleted rather than updated when a real chart appears.

**Two of the five reproduce their published figures by construction, and that is
not agreement.** Thieving's fifteen tabulated stalls come out at exactly 1.00x
because the wiki's own column is `3600 / respawn * xp` and so is this - the
model cannot be wrong about them and cannot be shown right either. What it buys
there is *coverage*, thirty stalls against the fifteen the scrape reached, and
the half the published column cannot express: where the restock is faster than
the rolling, the rolling is what you wait for. Mining's single fitted row is the
same standing for the opposite reason - one parameter, one observation, exactly
identified.

Pure: the caller supplies the tables and the reachable-item set, so nothing here
reads disk or network and no module-level state survives a call.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from chunksim.costing.heuristics import ComputedMethod, Rate, activity_name
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.model.summary import _mapping

#: One game tick, in seconds. The whole engine runs on it.
TICK_SECONDS = 0.6

#: `Rate.source` for a rate this module computed. Read by
#: `costing/training._material_cost`, which must **not** charge materials on top
#: of it: a gathering action consumes nothing, so the figure already is the
#: whole cycle.
GATHERING_SOURCE = "computed:gathering"

#: How this module labels its rates in `Rate.match`. Distinct from
#: `recipe_rates.COMPUTED_MATCH` because the two layer differently - this one
#: beats a scrape and that one loses to it - and a reader looking at a band
#: should be able to tell which model produced the number.
GATHERING_MATCH = "modelled"

#: **Where a success chance came from, and the only three answers there are.**
#: The model fills gaps the wiki has not measured, and a reader has to be able
#: to tell a reading from a construction from an invention without going to the
#: source. Carried on every `NodeRate`, and written into the shipped tables so
#: the scraped half says so itself.
#:
#: - `confirmed` - read off the wiki, whether from a `{{Skilling success
#:   chart}}` or from prose stating the odds outright ("players will always
#:   succeed in hunting sunlight antelopes").
#: - `inferred` - constructed from a measurement of the same kind of thing, as
#:   `assumed_curves` moves a charted butterfly's line onto an uncharted one.
#: - `guess` - a number chosen so there is one. It should be conservative, it
#:   should be rare, and it should be the first thing replaced.
CONFIRMED = "confirmed"
INFERRED = "inferred"
GUESS = "guess"

#: Levels at which a curve is re-read, on top of the method's own requirement.
#: **A gathering rate is a function of level and the band walk wants points.**
#: A willow tree is 28% at level 30 and 77% at 99; quoting one figure for the
#: whole climb is the error `costing/training.py` was written to remove, and
#: `training_bands` already turns several (level, rate) points into bands by
#: running maximum. Ten levels apart is fine-grained enough that the worst
#: within-band error is under 4% on the steepest curve measured, and coarse
#: enough that a skill contributes bands rather than a hundred of them.
CURVE_STEPS: tuple[int, ...] = (10, 20, 30, 40, 50, 60, 70, 80, 90, 99)

#: The export's "this is the skill's version of that name" suffix. Same list as
#: `heuristics._DISAMBIGUATOR` and for the same reason: the export writes
#: `Black chinchompa (Hunter)` where the wiki's calculator writes the bare name.
_DISAMBIGUATOR = re.compile(
    r"\s*\((?:Hunter|Prayer|Construction|Crafting|Cooking|Farming|Firemaking"
    r"|Fishing|Fletching|Magic|Mining|Runecraft|Slayer|Smithing"
    r"|Thieving|Woodcutting|Agility|Attack|Defence|Strength|Hitpoints|Ranged"
    r"|Sailing)\)\s*$",
    re.IGNORECASE,
)


def success_chance(level: int, low: float, high: float) -> float:
    """The game's own skilling success function, at `level`.

    **Exact arithmetic, not a heuristic, and deliberately not overridable** -
    the same standing `model/experience.py` has for the XP curve. The wiki
    states it as

        P(L) = (1 + floor(low*(99-L)/98 + high*(L-1)/98 + 0.5)) / 256

    clamped to `[0, 1]`, and the integer `floor` is part of it rather than a
    rounding convenience: the worked example on `Skilling success rate` gives
    monkfish at level 74 as exactly 80/256, which only comes out with the floor
    inside the numerator.

    `level` is clamped to 99 because the function's input is - a visible boost
    over 99 is disregarded entirely, per the same page.
    """
    capped = max(1, min(int(level), 99))
    raw = low * (99 - capped) / 98 + high * (capped - 1) / 98 + 0.5
    return max(0.0, min(1.0, (1 + math.floor(raw)) / 256))


@dataclass(frozen=True)
class SkillProfile:
    """How one skill's gathering loop differs from the others.

    Every field has a default that is the common case, so adding a skill is a
    line naming what is unusual about it rather than a full description. A
    field exists here **only** when some skill needs it to differ; anything the
    five agree on is a constant above.
    """

    #: Ticks between rolls where neither the tool nor the loop decides it.
    #: Four is Woodcutting's, which the wiki states outright.
    roll_ticks: float = 4.0
    #: Ticks between rolls **per calculator `kind`**, which is the loop the
    #: action belongs to. This is the generic form of the per-skill quirk: one
    #: skill's techniques can be as different from each other as two skills
    #: are, and Hunter is that skill - a box trap, a bird snare and a falconry
    #: catch share nothing but the word. A kind absent here falls back to
    #: `roll_ticks` only when `strict_kinds` is off; where it is on, an
    #: unmeasured loop is refused rather than given another loop's pace.
    roll_ticks_by_kind: Mapping[str, float] = field(default_factory=dict)
    #: Whether a `kind` with no measured interval is refused. On for the skills
    #: whose loops genuinely differ, so a new technique reads as unpriced
    #: rather than silently borrowing the last one that was measured.
    strict_kinds: bool = False
    #: Resources this model declines to price **by name**, lowercased.
    #:
    #: **A `kind` is not always a mechanic**, which is why refusing whole kinds
    #: is not enough. The wiki's Fishing calculator files a plain five-tick
    #: cage catch (`Raw lobster`) under `Miscellaneous` beside barbarian
    #: fishing and aerial fishing, which are two mechanics this model does not
    #: implement - so refusing the kind loses lobster and keeping it invents a
    #: rate for the other two. Naming the exceptions is the only reading that
    #: gets both right, and each name here has a stated reason.
    refuses: frozenset[str] = frozenset()
    #: What the tool changes: `"chance"` (Woodcutting - a better axe raises the
    #: success curve), `"interval"` (Mining - a better pickaxe rolls more
    #: often), or `""` (the rest - the tool is a gate, not a speed).
    tool_axis: str = ""
    #: Whether a multi-series chart's labels name tool tiers of the challenge's
    #: own `[+]` family. True for Woodcutting alone; see the module docstring
    #: for the two charts that prove it cannot be assumed.
    tool_tiers: bool = False
    #: **How many of a node you work at once.** One means standing at a single
    #: one and waiting out every respawn; higher means walking to the next.
    #:
    #: This is the skill's default and the bottom of three layers - a per-node
    #: count in `worked_at` beats it, and a published level table in
    #: `Tables.parallel` beats that. See `units_worked`, which is the one place
    #: they are resolved, and `rate_at` for the three different ways the answer
    #: can pay off.
    worked: float = 1.0
    #: Per-node counts, where the game puts several of a thing near enough
    #: together to be worth walking between.
    #:
    #: **Not how many exist - how many you can be back at before the restock
    #: finishes.** Those are different numbers and the second is the one that
    #: decides a rate. Ardougne market is the counter-example that makes the
    #: distinction concrete: it holds several stalls of one type, and they are
    #: far enough apart that waiting out the restock beats running to the next,
    #: so the right count there is one however many the map shows. The Rogues'
    #: Castle is the other way round - three chests in a room, 20.4 seconds
    #: shared three ways, and the wait stops binding at all.
    #:
    #: **Nothing published decides this and the export cannot either**, which is
    #: why it is a hand entry per method rather than a table. The export says
    #: only which chunk a thing is in, never how far apart two of them are, and
    #: no wiki page tabulates "can you get back in time" because the answer
    #: depends on the route as much as on the node. So each entry is a judgement
    #: about one training method, written down with its reasoning beside it -
    #: and an absent entry is the conservative reading, one node and the full
    #: wait.
    worked_at: Mapping[str, float] = field(default_factory=dict)
    #: Seconds lost per resource for a node whose cycle is **not** published.
    #: A normal tree hands over one log and vanishes, and a rock one ore; the
    #: wiki tabulates despawn and respawn for thirteen trees and for nothing
    #: else, so what a rock costs you between ores is the one number here that
    #: no page states. **Fitted against the rates the wiki does publish**, and
    #: `0.0` for the skills whose nodes do not deplete at all.
    node_seconds: float = 0.0
    #: The calculator `kind`s a published level table in `Tables.parallel`
    #: applies to.
    #:
    #: **The table says how many; this says what it is about.** The Hunter page
    #: tabulates 1, 2, 3, 4, 5 traps at levels 1, 20, 40, 60 and 80 and names
    #: the loops it applies to in prose - box trapping, net trapping and bird
    #: snaring, but not falconry or tracking - so that sentence has to be
    #: encoded somewhere, and a set of loops beside the table is the least it
    #: can be. Nothing else is gated on this: a node with no table and no
    #: `worked_at` entry simply works one at a time.
    parallel_kinds: frozenset[str] = frozenset()
    #: The calculator `kind`s where a node with a published restock time and
    #: **no** success chart does not fail, rather than being unknown.
    #:
    #: Thieving's stalls are the case and the wiki states it: "Unlike
    #: pickpocketing, stealing from stalls has a 100% success rate." The five
    #: Ape Atoll stalls that *can* fail carry a chart of their own and are
    #: priced off it, so the absence of a chart is itself the statement. Gated
    #: on the restock time being published, so this can never turn "nothing is
    #: known about this node" into a rate.
    certain_kinds: frozenset[str] = frozenset()
    #: The calculator `kind`s whose rate *is* a restock time, so a node without
    #: one published is refused however much else is known about it.
    #:
    #: **The guard that keeps `certain_kinds` honest.** A stall and a chest are
    #: priced by the wait, not by the clicking; without a restock the model
    #: would fall back to the two-tick interaction cadence and read
    #: `Shop Counter (ore)` as the fastest thing on the map. Crab trapping is
    #: certain in the same way and is *not* restock-bound - its rate is an
    #: interval - which is why this is a set beside that one rather than the
    #: same set.
    restock_kinds: frozenset[str] = frozenset()
    #: Nodes whose published rate is a **drop** rate, so no trip is charged.
    #:
    #: `bank_seconds` exists because every published Fishing figure has a bank
    #: run inside it where every published Woodcutting one does not - but that
    #: is a fact about each *method*, not about the skill, and barbarian
    #: fishing is the counter-example inside Fishing itself: the catch is
    #: dropped, and charging a trip for it read the whole activity 0.69x at the
    #: level its guide is quoted for. Named per node rather than per loop
    #: because the loop it belongs to (`Miscellaneous`) is a grab-bag that also
    #: holds cage fishing, which really is banked.
    unbanked: frozenset[str] = frozenset()
    #: Node -> the loop it really belongs to, overriding the calculator's own
    #: `type`.
    #:
    #: **The calculator's grouping is a display choice and sometimes it is
    #: wrong.** A tropical wagtail is caught in a bird snare - the export says
    #: so in its `Items` - and the calculator leaves its `type` blank; a white
    #: rabbit is rabbit snaring and the calculator files it under `Other`
    #: beside an imp, which is a different activity entirely. Neither is a
    #: judgement about mechanics, so neither should decide which interval
    #: applies.
    loop_at: Mapping[str, str] = field(default_factory=dict)
    #: Loops whose interval is **borrowed** from a sibling rather than fitted
    #: or read. Every rate they produce is `INFERRED` at best, however well
    #: measured its success chance is - a rate is only as good as its weakest
    #: input, and saying `confirmed` because half of it was measured would be
    #: the exact mistake provenance exists to stop.
    inferred_loops: frozenset[str] = frozenset()
    #: Node -> `(chance, provenance)`, for a creature whose odds are stated in
    #: prose or are not stated at all.
    #:
    #: **The two shapes it holds are not alike and the provenance is what says
    #: so.** Sunlight and moonlight antelopes are `1.0, CONFIRMED`, because
    #: their pages say outright that "players will always succeed"; the three
    #: cats hunted the same way are `0.5, GUESS`, because nothing anywhere
    #: states their odds and half is a round, conservative stand-in chosen so
    #: the method has a number rather than none. A guess should be rare, it
    #: should be the first thing replaced, and it should never be mistaken for
    #: the antelope beside it - which is the whole reason this is a pair and
    #: not a float.
    fixed_chances: Mapping[str, tuple[float, str]] = field(default_factory=dict)
    #: Node -> the node whose success chart to borrow, for a creature the wiki
    #: has not charted yet.
    #:
    #: **Re-anchored to the borrower's own unlock level, not copied.** A chart
    #: is a line, and what makes two of them comparable is where each one
    #: starts: black warlock, sunlight moth and moonlight moth all climb at
    #: `276/98` per level and differ only in what they are worth at the level
    #: they open at - 0.56, 0.79 and 0.82 of a catch. So the borrowed line
    #: keeps its slope and is moved sideways until it opens where the borrower
    #: does, which is the whole of what "the same curve" can mean between two
    #: creatures unlocked sixty levels apart.
    #:
    #: **Black warlock is the donor because it is the worst of the three**, and
    #: an assumed number should be the pessimistic one. `Category:Needs
    #: skilling success chart` is the wiki's own list of what is unmeasured;
    #: every entry here is on it, and an entry should be *deleted* rather than
    #: updated when a real chart appears.
    #:
    #: Keyed by node rather than by loop, because the loop is no guide: 29
    #: calculator rows share `Butterfly net` and most of them are implings,
    #: which are caught by a different mechanic entirely.
    assumed_curves: Mapping[str, str] = field(default_factory=dict)
    #: Node -> the ordered loop it is rolled inside, best reward first.
    #:
    #: **A cascade is several success rolls in one action**, which
    #: `Skilling success rate` documents under that name: the best outcome is
    #: rolled, and on failing it the next is rolled, until one lands or all
    #: fail. Barbarian fishing is the case - sturgeon, then salmon, then trout -
    #: and priced as a single roll it read 0.73x, because two thirds of what
    #: the action pays was going uncounted. Every node in one cascade names the
    #: same tuple, so the entry reads the same whichever task asked.
    cascades: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    #: Node -> units *beyond* what the level table allows there.
    #:
    #: Additive rather than absolute, and it has to be: the Wilderness lets a
    #: sixth trap out for black chinchompas and black salamanders, and writing
    #: `6` would stop the count tracking the table at every level below 80.
    #: Where there is no table to add to, use `worked_at` instead.
    parallel_bonus: Mapping[str, float] = field(default_factory=dict)
    #: Seconds charged for a *failed* roll, on top of the roll itself.
    #: Thieving is the skill that needs it - a failed pickpocket stuns you,
    #: which is real downtime the success curve says nothing about - and it is
    #: why the curve alone reads a systematic 1.37x fast there.
    fail_seconds: float = 0.0
    #: The same, **per calculator `kind`**, for a skill whose loops fail
    #: differently. Thieving is that skill and it is why this exists: a failed
    #: pickpocket locks you out for eight ticks, and a failed stall steal
    #: costs you nothing but the attempt. One number could only be wrong for
    #: one of them.
    fail_seconds_by_kind: Mapping[str, float] = field(default_factory=dict)
    #: Whether a published node cycle applies at all. A fishing spot moves
    #: rather than running out and a pickpocket target never does, so charging
    #: either would invent downtime that does not happen.
    depletes: bool = True
    #: Seconds one bank trip costs, and how many resources a trip carries.
    #:
    #: **Only charged when the caller asks for a training rate**, never when it
    #: asks what a material cost - see `NodeRate.seconds_per_item` against
    #: `NodeRate.training_seconds`. The two questions genuinely differ: you bank
    #: the fish you are training on, and you do not bank the logs you are about
    #: to fletch in the same trip. Charging both is how a material gets billed
    #: for a trip the production action is already paying for.
    #:
    #: Zero where the skill is trained by *dropping* what it gathers, which is
    #: how every published Woodcutting and Mining figure is quoted - and the
    #: fit confirms it, those two landing at 1.07x and 1.00x with no bank
    #: charge at all.
    bank_seconds: float = 0.0
    #: Resources one trip carries back. Twenty-seven: an inventory is 28 slots
    #: and one holds the tool.
    carry: float = 27.0


#: The five skills this model answers for, and what is unusual about each.
#:
#: **Membership is the gate**: a skill absent here is not modelled, which is the
#: refusal this project takes everywhere rather than approximating. Agility is
#: deliberately out - an obstacle is a fixed-time course lap rather than a node
#: with a respawn, and `remote/skill_tables.py` already reads a real per-course
#: hourly figure for it, which is the better answer and not a stopgap.
#: The five skills this model answers for, and what is unusual about each.
#:
#: **Membership is the gate and it is not the same as being priced.** A skill
#: here is modelled only for the *loops* whose numbers have been checked
#: against something the wiki publishes; `strict_kinds` refuses the rest, which
#: is why Thieving appears with an empty table and prices nothing. Agility is
#: absent outright - an obstacle is a fixed-time course lap rather than a node
#: with a respawn, and `remote/skill_tables.py` already reads a real per-course
#: hourly figure for it, which is the better answer and not a stopgap.
#:
#: **Every fitted number is `costing/gathering_overhead.py`'s**, and that
#: harness is the authority - re-run it rather than adjusting one by eye. What
#: each skill's evidence actually is, measured against the wiki's own training
#: guides over every method in the export:
#:
#: | skill | rows | geometric mean | within 1.25x |
#: |---|---|---|---|
#: | Woodcutting | 17 | 1.07x | 12/17 |
#: | Fishing | 4 | 1.04x | 4/4 |
#: | Mining | 1 | 1.00x | 1/1 |
#: | Hunter (Falconry) | 3 | 0.99x | 3/3 |
#: | Hunter (other loops) | 3 | - | refused |
#: | Thieving | 3 | - | refused |
PROFILES: dict[str, SkillProfile] = {
    # **Four ticks is the wiki's, not a fit** - the Woodcutting page states it -
    # and pinning it is what makes the other two constants mean something. Left
    # free the fit pulls it to 2.5 to absorb the spread between oak and willow.
    # `node_seconds` is what a tree the wiki tabulates no cycle for costs you:
    # a normal tree hands over one log and vanishes.
    "Woodcutting": SkillProfile(
        roll_ticks=4.0,
        tool_axis="chance",
        tool_tiers=True,
        worked=2.0,
        node_seconds=2.4,
    ),
    # A pickaxe changes how often the game rolls, never whether the roll wins.
    # **No rock's respawn is published anywhere** - not on the skill page, not
    # in the scenery infobox, not in any Module - so the whole of a rock's
    # downtime is the fitted constant, and it is fitted against a single row.
    # That is thin and is recorded as thin: it reproduces iron at 1.00x and
    # nothing else has been able to check it, because the three tabulated
    # headings (granite, gem rocks, calcified) all fail the experience join.
    "Mining": SkillProfile(tool_axis="interval", node_seconds=1.1),
    # **A fishing spot does not deplete**; it relocates. Five ticks a roll is
    # the game's rather than a fit - net, bait, harpoon and cage share it - and
    # what the fit moves is the bank run, which every published Fishing figure
    # has inside it where every published Woodcutting one does not.
    #
    # `Miscellaneous` is deliberately absent, which refuses barbarian fishing:
    # it is a **cascading** roll (sturgeon, then salmon, then trout, each on
    # the previous one failing) and this model rolls once. Priced as a single
    # roll it read 0.73x, and the gap is the mechanic rather than the constant.
    "Fishing": SkillProfile(
        depletes=False,
        strict_kinds=True,
        roll_ticks_by_kind={
            "Small net": 5.0,
            "Big net": 5.0,
            "Bait": 5.0,
            "Fly": 5.0,
            "Harpoon": 5.0,
            "Lantern harpoon": 5.0,
            "Small net, Big net": 5.0,
            # The calculator's catch-all, and it really is one - see `refuses`.
            "Miscellaneous": 5.0,
        },
        # Barbarian fishing is trained by dropping, so its published figures
        # carry no bank run - see `unbanked`.
        unbanked=frozenset({"leaping sturgeon", "leaping salmon", "leaping trout"}),
        cascades={
            # **Barbarian fishing, and the order is the mechanic.** The best
            # fish is rolled first and each failure falls through to the next,
            # which `Skilling success rate` documents under "Cascading
            # chances". Priced as a single roll these read 0.73x, because two
            # of the three rolls an action makes were going uncounted.
            node: ("Leaping sturgeon", "Leaping salmon", "Leaping trout")
            for node in ("leaping sturgeon", "leaping salmon", "leaping trout")
        },
        refuses=frozenset(
            {
                # **Aerial fishing is not the skilling success function at
                # all** - it is a Hunter catch that pays Fishing experience,
                # and `Skilling success rate` names it as an activity the
                # formula does not describe.
                "greater siren",
                "mottled eel",
                "bluegill",
                "common tench",
            }
        ),
        bank_seconds=74.0,
    ),
    # **Traps are the mechanic, and they are published.** Box trapping, net
    # trapping and bird snaring run several traps at once, 1 to 5 across levels
    # 1 to 80, and the Wilderness allows a sixth for black chinchompas - which
    # the Hunter and Box trap pages both state, and which is the only reason
    # black reads faster than carnivorous when the two share a curve exactly.
    #
    # The intervals are still fitted, and they are the honest kind of fitted:
    # what the model cannot see is how often prey walks past a trap, which no
    # page publishes, so one number per loop stands in for prey density. Four
    # loops carry one, and `Deadfall`'s is a single row against a single
    # parameter - exactly identified, so its 1.00x is arithmetic rather than
    # agreement, the same standing as Mining's `node_seconds`.
    #
    # **`Bird snare` and `Pitfall` are absent because nothing published can
    # check them**, and `strict_kinds` therefore refuses both. They keep their
    # place in `parallel_kinds` all the same: the trap table is a fact about
    # those loops whether or not this model prices one.
    #
    # **`Bird snare` is the one interval derived rather than fitted, and it is
    # three inferences deep.** No page isolates a bird-snaring rate; the only
    # figure that mentions one is the training guide's "up to 20,000
    # experience per hour with two traps" for levels 15-21, which is ruby
    # harvests caught *while* two snares run. Subtracting what this model says
    # the butterflies pay at 21 - 13,018 - leaves 6,982 for the birds, and two
    # traps at a 0.578 chance on 61 xp put a bird in a snare every 60.6 ticks.
    # So it rests on the borrowed butterfly curve and on the butterfly interval
    # as well as on the guide, and should be the first thing re-derived if
    # either moves.
    #
    # It earns its place at the bottom rather than the top: a crimson swift is
    # 1,319/hr at level 1, which is the only thing at all between level 1 and
    # the butterflies at 15, and it beats the floor that stood there.
    #
    # **Anchored at two traps, so the five-trap end is extrapolation**, and it
    # reads too fast there: a cerulean twitch comes out at 25,416/hr at level
    # 60, above the swamp lizards nobody would leave for it. The suspect step
    # is that traps divide the interval, which assumes bird density scales with
    # how many snares you set rather than being a property of the area. Neither
    # cached map reaches a bird area, so no band moves on the evidence to hand;
    # a map that does should be read with this in mind, and one published
    # high-level figure would settle it.
    #
    # The residual is density and reads as density. The two Wilderness rows sit
    # slow (black chinchompa 0.77x, black salamander 0.69x) and the lowest-level
    # row sits fast (swamp lizard 1.48x), which is what one number per loop
    # buys against guides quoting their best spot.
    "Hunter": SkillProfile(
        depletes=False,
        strict_kinds=True,
        roll_ticks_by_kind={
            "Falconry": 10.0,
            "Box trap": 90.0,
            "Deadfall": 105.0,
            "Net trapping": 154.0,
            "Crab trapping": 57.0,
            "Butterfly net": 7.0,
            "Bird snare": 61.0,
            # **Two observations, one parameter.** Both antelopes are certain
            # catches, so their published rates say only how often one walks
            # into a pit: 30.0 ticks off the moonlight figure and 27.3 off the
            # sunlight one, which 28.5 splits at 1.05x and 0.96x.
            "Pitfall": 28.5,
            # **Borrowed from box trapping, not fitted**, because nothing
            # publishes a rabbit-snaring rate to fit against. The Hunter page
            # groups rabbit snaring with box, net and bird as the four loops
            # run several traps at a time, so a rabbit approaching a snare is
            # taken to happen as often as a chinchompa approaching a box. That
            # makes every white-rabbit rate `INFERRED` - see `inferred_loops`.
            "Rabbit snare": 101.0,
            # Fitted against feldip weasel and razor-backed kebbit, the two
            # tracked creatures with published rates.
            "Tracking": 21.5,
            # **Borrowed from box trapping, which is what it is.** A magic box
            # is placed and an imp walks into it, and imps are ordinary fixed
            # spawns that keep to their wander radius rather than the roaming
            # world spawns their name suggests - so the density a box-trap
            # interval encodes is the right kind of quantity here, where it is
            # not for a wandering impling. Nothing publishes an imp rate, so
            # this is `INFERRED` like rabbit snaring.
            "Magic box": 90.0,
        },
        # **What the calculator groups by is not always what the game does.**
        # The export names the trap in each challenge's `Items`, which is the
        # better authority: a tropical wagtail carries `Bird snare` where the
        # calculator states no loop at all, and a white rabbit carries
        # `Rabbit snare` where the calculator files it under `Other` next to an
        # imp.
        loop_at={
            "tropical wagtail": "Bird snare",
            "rabbit hole": "Rabbit snare",
            "white rabbit": "Rabbit snare",
            # `Other` is the calculator's shrug, and the wiki's own name for
            # this is magic box trapping.
            "imp": "Magic box",
        },
        inferred_loops=frozenset({"Rabbit snare", "Magic box"}),
        # **The pitfall five, and the two kinds of number in one place.** The
        # antelope pages state the odds outright - "players will always succeed
        # in hunting sunlight antelopes" - so those are readings. The three
        # cats hunted the same way have no chart anywhere and no prose either;
        # half is a stand-in so the method has a number, and it is marked as
        # one. Anything that turns up about them replaces it.
        fixed_chances={
            "sunlight antelope": (1.0, CONFIRMED),
            "moonlight antelope": (1.0, CONFIRMED),
            "spined larupia": (0.5, GUESS),
            "horned graahk": (0.5, GUESS),
            "sabre-toothed kyatt": (0.5, GUESS),
        },
        # **Three butterflies the wiki has not charted, given the worst chart
        # it has.** `Category:Needs skilling success chart` lists ruby harvest,
        # snowy knight and sapphire glacialis; black warlock, sunlight moth and
        # moonlight moth are charted and climb identically, differing only in
        # what they are worth where they open. Black warlock opens lowest, so
        # it is the one lent - an assumed curve should be the pessimistic one.
        # Delete an entry when its own chart appears; do not update it.
        assumed_curves={
            "ruby harvest": "Black warlock",
            "snowy knight": "Black warlock",
            "sapphire glacialis": "Black warlock",
            # **The wiki says this one outright**: "The hunting technique is
            # the same as for chinchompas", and the ferret is on
            # `Category:Needs skilling success chart` like the butterflies
            # above. Its two box-trap siblings, the embertailed jerboa and the
            # letvek, say no such thing and stay refused - a shared trap is not
            # a shared chance, and the sentence is what makes this one safe.
            # **Every box-trap creature is the same technique**, which the
            # ferret's page says outright - "The hunting technique is the same
            # as for chinchompas" - and which the trap itself implies for the
            # rest. Only the carnivorous chinchompa is charted; the others
            # borrow that chart moved to their own level.
            "ferret (hunter)": "Chinchompa (Hunter)",
            "embertailed jerboa": "Chinchompa (Hunter)",
            "letvek (hunter)": "Chinchompa (Hunter)",
            # **Noose-wand tracking, of which one of five is charted.** Polar
            # kebbit carries the chart and the other four are the same trail
            # followed to the same burrow, so they borrow it. Unlike the box
            # traps this one can be *checked*: two of the five have published
            # rates, and the interval fitted against them lands within 6% of
            # both.
            "common kebbit": "Polar kebbit",
            "feldip weasel": "Polar kebbit",
            "desert devil": "Polar kebbit",
            "razor-backed kebbit": "Polar kebbit",
        },
        refuses=frozenset(
            {
                # **`Butterfly net` is a grab-bag, the way Fishing's
                # `Miscellaneous` is**, and the twelve implings in it share the
                # tool and nothing else. A butterfly field puts one in front of
                # you; an impling is a rare wandering spawn you chase, and the
                # seven-tick interval is fitted against ruby harvest and
                # sapphire glacialis, which are neither. Nothing published
                # prices an impling, so there is no way to tell how far wrong
                # that would be - and unrefused they took 50 -> 99 on the
                # second cached map at 24,750/hr, which is a whole climb
                # decided by an extrapolation.
                "baby impling",
                "young impling",
                "gourmet impling",
                "earth impling",
                "essence impling",
                "eclectic impling",
                "nature impling",
                "magpie impling",
                "ninja impling",
                "crystal impling",
                "dragon impling",
                "lucky impling",
            }
        ),
        certain_kinds=frozenset({"Crab trapping"}),
        parallel_kinds=frozenset(
            {
                "Box trap",
                "Net trapping",
                "Bird snare",
                "Rabbit snare",
                "Crab trapping",
                # The `Magic box` page carries its own copy of the trap table,
                # identical to the Hunter page's, so the skill-wide steps serve
                # it and no second table is needed.
                "Magic box",
            }
        ),
        parallel_bonus={
            "black chinchompa (hunter)": 1.0,
            "black salamander (hunter)": 1.0,
        },
    ),
    # **Both halves of Thieving are published outright; neither is fitted.**
    #
    # *Pickpocketing*: "NPCs may be pickpocketed every two ticks (1.2 seconds)"
    # and a failure "prevents the player from ... further pickpocketing for
    # eight ticks (4.8s)". The roll already charges two of those eight, so the
    # stun costs the other six - 3.6 seconds - which is what `fail_seconds`
    # means. This is what supersedes `wiki:pickpockets`, and non-circularly:
    # that source is `experience * 3600 / 1.2`, the right cadence with the
    # wrong assumption, since it prices every level as though you never fail.
    #
    # *Stalls*: a stall hands over one item and restocks, so the published
    # restock time is the floor and `Tables.respawns` carries it for all
    # thirty. Two ticks is **the game's minimum interaction cadence rather
    # than a measurement**, and it is deliberately a lower bound: the floor is
    # a `max`, so a rolling time that is too short can only make the respawn
    # win, which it does for every stall the wiki tabulates a rate for.
    # A failed stall steal costs the attempt and nothing else - there is no
    # stun - hence `fail_seconds_by_kind`.
    #
    # `Chests` and `Other` stay unmeasured and `strict_kinds` refuses them.
    "Thieving": SkillProfile(
        depletes=False,
        strict_kinds=True,
        # **A chest cycle is not a stall's.** A stall is two ticks of clicking
        # against a restock that is nearly always the longer of the two, so its
        # interval barely shows. A chest has to be searched for traps, opened
        # and looted, and at the one location anybody publishes a rate for you
        # walk between three of them - which is the whole cost, since three in
        # rotation means the restock never binds. **One parameter against one
        # observation**, the same standing as Mining's `node_seconds`: 15.5
        # ticks is what reproduces the Rogues' Castle figure of 270,154/hr, and
        # nothing else published can check it.
        roll_ticks_by_kind={"Pickpocket": 2.0, "Stalls": 2.0, "Chests": 15.5},
        fail_seconds=3.6,
        fail_seconds_by_kind={"Stalls": 0.0, "Chests": 0.0},
        certain_kinds=frozenset({"Stalls", "Chests"}),
        restock_kinds=frozenset({"Stalls", "Chests"}),
        # **Three chests sit together at the Rogues' Castle**, which its own
        # `{{Map}}` pins show and which is why the guide's rate beats anything
        # one chest could give: 20.4 seconds of restock shared three ways is
        # 6.8, shorter than the cycle, so the wait stops mattering at all.
        # Every other chest and stall the wiki tabulates is worked one at a
        # time, which is what the published figures for them describe.
        worked_at={"chest (rogues' castle)": 3.0},
    ),
}


@dataclass(frozen=True)
class NodeRate:
    """One gathering method, priced at one level."""

    task: str
    skill: str
    level: int
    xp_per_hour: float
    #: What the roll pays when it wins.
    experience: float
    #: Chance of one roll succeeding at `level`.
    chance: float
    #: Seconds between rolls, tool included where the tool decides it.
    roll_seconds: float
    #: Share of the hour actually spent rolling, after node respawns. `1.0`
    #: where the node does not deplete.
    duty: float
    #: The wiki page the success curve was read off, and the tool tier chosen.
    node: str
    tool: str = ""
    #: Seconds of banking charged per resource, `0.0` where the skill drops
    #: what it gathers. Carried rather than folded in so the two questions the
    #: model answers can be told apart - see `seconds_per_item`.
    bank_seconds_per_item: float = 0.0
    #: Where `chance` came from: `CONFIRMED`, `INFERRED` or `GUESS`. Carried on
    #: the rate rather than worked out again later, for the reason every other
    #: provenance in this project is recorded where it is read - by the time a
    #: number has been through an arithmetic nobody can tell what it was.
    provenance: str = CONFIRMED

    @property
    def seconds_per_item(self) -> float:
        """Seconds to obtain one, **excluding banking**.

        What the item walk wants: `costing/estimate.py` charges the trip that
        carries a material as part of the production action, so a material
        priced with a bank run inside it is billed for that trip twice.
        """
        if self.xp_per_hour <= 0 or self.experience <= 0:
            return 0.0
        return self.experience * 3600.0 / self.xp_per_hour - self.bank_seconds_per_item

    @property
    def training_seconds(self) -> float:
        """Seconds to obtain one, banking included - the training rate's basis."""
        if self.xp_per_hour <= 0 or self.experience <= 0:
            return 0.0
        return self.experience * 3600.0 / self.xp_per_hour

    def as_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "skill": self.skill,
            "level": self.level,
            "xp_per_hour": round(self.xp_per_hour, 1),
            "experience": self.experience,
            "chance": round(self.chance, 4),
            "roll_seconds": round(self.roll_seconds, 3),
            "duty": round(self.duty, 3),
            "node": self.node,
            "tool": self.tool,
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class GatheringCoverage:
    """What the model reached, per skill, so a total can be read honestly."""

    #: Skill -> (methods priced, primary methods offered).
    skills: dict[str, tuple[int, int]] = field(default_factory=dict)
    #: Methods that named a node with no success curve on the wiki.
    no_curve: tuple[str, ...] = ()
    #: Methods whose experience no skill calculator states.
    no_experience: tuple[str, ...] = ()

    @property
    def priced(self) -> int:
        return sum(priced for priced, _ in self.skills.values())

    @property
    def offered(self) -> int:
        return sum(offered for _, offered in self.skills.values())

    def as_dict(self) -> dict[str, Any]:
        return {
            "priced": self.priced,
            "offered": self.offered,
            "skills": {
                skill: {"priced": priced, "offered": offered}
                for skill, (priced, offered) in sorted(self.skills.items())
            },
            "no_curve": list(self.no_curve),
            "no_experience": list(self.no_experience),
        }


@dataclass(frozen=True)
class Tables:
    """The scraped tables, indexed for lookup.

    Built from `cache.read_gathering()`'s dict once per invocation and threaded,
    the shape `costing/inputs.ReferenceBlobs` already uses - so the JSON is
    parsed once rather than per method, and nothing here is a module global that
    a worker process could inherit.
    """

    #: Lowercased page title -> its success curves, in written order, each
    #: `(label, low, high, req)`. **`req` is carried because a curve can be
    #: lent**: re-anchoring one creature's chart onto another needs the level
    #: the original was drawn from - see `SkillProfile.assumed_curves`.
    curves: dict[str, tuple[tuple[str, float, float, int, str], ...]] = field(
        default_factory=dict
    )
    #: Tool item -> ticks between rolls.
    tool_ticks: dict[str, float] = field(default_factory=dict)
    #: Lowercased node name -> (despawn seconds, respawn seconds).
    cycles: dict[str, tuple[float, float]] = field(default_factory=dict)
    #: Skill -> lowercased action name -> (experience per action, its `kind`).
    #: **The kind travels with the figure** because it is what says how often
    #: the action rolls: `Box trap`, `Bird snare` and `Falconry` are three
    #: different Hunter loops and one interval cannot describe them - fitted
    #: free over all six tabulated Hunter methods it lands on 18 ticks, which
    #: is not a mechanic, it is the average of three.
    experience: dict[str, dict[str, tuple[float, str]]] = field(default_factory=dict)
    #: Skill -> lowercased action name -> what one action *consumes*,
    #: `((item, quantity), ...)` in the calculator's own order.
    #:
    #: **Read here and spent in `costing/production.py`**, which is the only
    #: caller: a gathering rate has nothing to consume, and the same tables
    #: happen to carry the one pair a production method needs and the export
    #: does not state. Keeping the two in one file is what stops a second
    #: scrape of the same eighteen pages.
    materials: dict[str, dict[str, tuple[tuple[str, float], ...]]] = field(
        default_factory=dict
    )
    #: Lowercased stall name -> seconds to restock.
    #:
    #: **Kept apart from `cycles` because the mechanic is different.** A tree
    #: yields for a whole despawn window and its wait is a duty cycle; a stall
    #: yields exactly one item and then the wait *is* the rate. Folding them
    #: would make one of the two arithmetics wrong.
    respawns: dict[str, float] = field(default_factory=dict)
    #: Hunter level -> experience for one herbiboar, for
    #: `costing/herbiboar.py`.
    herbiboar_xp: dict[int, float] = field(default_factory=dict)
    #: Spawn-tier name -> `(impling, share)`, for `costing/implings.py`.
    spawn_tiers: dict[str, tuple[tuple[str, float], ...]] = field(default_factory=dict)
    #: Skill -> loop -> `(level, units)` steps, `""` being the skill's default.
    #: Keyed by loop because Hunter publishes two tables that disagree: the
    #: general one opens at level 1 with five steps, crab trapping's at 21 with
    #: four.
    parallel: dict[str, dict[str, tuple[tuple[int, float], ...]]] = field(
        default_factory=dict
    )

    @property
    def empty(self) -> bool:
        """True when `chunksim gather-tables` has never run.

        A supported state: the estimator keeps every older source and simply
        has no modelled layer, which is a gap rather than a wrong number.
        """
        return not self.curves


def load_tables(raw: Mapping[str, Any]) -> Tables:
    """Index `cache.read_gathering()`'s dict for lookup.

    Keys are lowercased on the way in because the export and the wiki disagree
    about case and about nothing else - `Chop a ~|burnt tree|~` names `Burnt
    tree` where the page is `Burnt tree`, but `Mine ~|soft clay rocks|~` names
    `Soft clay rocks` against a page titled `Soft clay rock`. Case is the only
    fuzz allowed here; everything else is a whole-string match.
    """
    curves: dict[str, tuple[tuple[str, float, float, int, str], ...]] = {}
    for page, series in _mapping(raw, "curves").items():
        if not isinstance(series, list):
            continue
        read = tuple(
            (
                str(entry.get("label", "")),
                float(entry["low"]),
                float(entry["high"]),
                int(entry.get("requirement") or 1),
                str(entry.get("provenance") or CONFIRMED),
            )
            for entry in series
            if isinstance(entry, dict) and "low" in entry and "high" in entry
        )
        if read:
            curves[page.lower()] = read

    cycles: dict[str, tuple[float, float]] = {}
    for name, entry in _mapping(raw, "cycles").items():
        if isinstance(entry, dict) and "despawn" in entry and "respawn" in entry:
            cycles[name.lower()] = (float(entry["despawn"]), float(entry["respawn"]))

    experience: dict[str, dict[str, tuple[float, str]]] = {}
    materials: dict[str, dict[str, tuple[tuple[str, float], ...]]] = {}
    for skill, rows in _mapping(raw, "actions").items():
        if not isinstance(rows, list):
            continue
        by_name: dict[str, tuple[float, str]] = {}
        consumed: dict[str, tuple[tuple[str, float], ...]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            action, paid = row.get("name"), row.get("experience")
            if isinstance(action, str) and isinstance(paid, (int, float)) and paid > 0:
                # First wins: a calculator lists the cheapest variant first,
                # and a later duplicate is a different location for the same
                # action rather than a better one.
                by_name.setdefault(
                    action.lower(), (float(paid), str(row.get("kind", "")))
                )
                # **The same first-wins rule, and it has to be the same row.**
                # Taking experience from one duplicate and materials from
                # another would price an action against a cost it never had.
                if action.lower() not in consumed:
                    entries = row.get("materials")
                    consumed[action.lower()] = tuple(
                        (str(entry["name"]), float(entry["quantity"]))
                        for entry in (entries if isinstance(entries, list) else ())
                        if isinstance(entry, dict)
                        and isinstance(entry.get("name"), str)
                        and isinstance(entry.get("quantity"), (int, float))
                        and float(entry["quantity"]) > 0
                    )
        if by_name:
            experience[skill] = by_name
            materials[skill] = consumed

    ticks = {
        str(name): float(value)
        for name, value in _mapping(raw, "tool_ticks").items()
        if isinstance(value, (int, float))
    }
    respawns = {
        str(name).lower(): float(value)
        for name, value in _mapping(raw, "respawns").items()
        if isinstance(value, (int, float)) and value > 0
    }

    herbiboar_xp = {
        int(level): float(paid)
        for level, paid in _mapping(raw, "herbiboar_xp").items()
        if isinstance(paid, (int, float)) and float(paid) > 0 and str(level).isdigit()
    }

    spawn_tiers: dict[str, tuple[tuple[str, float], ...]] = {}
    for tier, entries in _mapping(raw, "spawn_tiers").items():
        if not isinstance(entries, list):
            continue
        read_tier = tuple(
            (str(entry[0]), float(entry[1]))
            for entry in entries
            if isinstance(entry, list) and len(entry) == 2 and float(entry[1]) > 0
        )
        if read_tier:
            spawn_tiers[tier] = read_tier

    parallel: dict[str, dict[str, tuple[tuple[int, float], ...]]] = {}
    for skill, loops in _mapping(raw, "parallel").items():
        if not isinstance(loops, dict):
            continue
        for loop, steps in loops.items():
            if not isinstance(steps, list):
                continue
            steps_read = tuple(
                (int(step[0]), float(step[1]))
                for step in steps
                if isinstance(step, list)
                and len(step) == 2
                and isinstance(step[0], (int, float))
                and isinstance(step[1], (int, float))
                and float(step[1]) > 0
            )
            if steps_read:
                parallel.setdefault(skill, {})[loop] = tuple(sorted(steps_read))

    return Tables(
        curves=curves,
        tool_ticks=ticks,
        cycles=cycles,
        experience=experience,
        materials=materials,
        respawns=respawns,
        spawn_tiers=spawn_tiers,
        herbiboar_xp=herbiboar_xp,
        parallel=parallel,
    )


def units_worked(
    tables: Tables,
    profile: SkillProfile,
    skill: str,
    kind: str,
    node: str,
    level: int,
) -> float:
    """How many of `node` this player works at once.

    **One number, three sources, most specific first.** A per-node count where
    the location publishes one; else the loop's own published level table,
    where the profile says that table applies here; else the skill's default,
    which is one for everything but Woodcutting.

    `parallel_bonus` is added on top of the table rather than replacing it,
    because the Wilderness trap is an extra one and has to keep tracking the
    table underneath.

    **What the answer buys depends on what the node waits for, and `rate_at`
    decides that, not this.** Three chests in a room and five box traps in a
    field are the same number here and opposite things there.
    """
    override = profile.worked_at.get(node.lower())
    if override is not None:
        return override
    units = profile.worked
    if kind in profile.parallel_kinds:
        loops = tables.parallel.get(skill) or {}
        # **The loop's own table wins over the skill's.** Crab trapping opens
        # at 21 where hunting generally opens at 1, and using the general table
        # would hand a level-21 player the wrong count.
        steps = loops.get(kind) or loops.get("")
        if steps:
            units = units_at(steps, level)
    return units + profile.parallel_bonus.get(node.lower(), 0.0)


def units_at(steps: Sequence[tuple[int, float]], level: int) -> float:
    """How many units a `(level, units)` table allows at `level`.

    The last step at or below the level, and `1.0` when the table says nothing
    - one of a thing being the case every loop shares, and the conservative
    reading besides.
    """
    allowed = 1.0
    for opens, units in steps:
        if level >= opens:
            allowed = units
    return allowed


def duty_cycle(despawn: float, respawn: float, nodes: float) -> float:
    """The share of an hour spent rolling, given a node that runs out.

    Work `nodes` of them in turn: each yields for `despawn`, so you are back at
    the first after `nodes * despawn` and it has had that long of its `respawn`
    already. Whatever is left is the wait.

    `1.0` when the numbers say there is no wait, which is what enough nodes
    buys and is the bound the published rates sit under.
    """
    if despawn <= 0 or respawn <= 0 or nodes <= 0:
        return 1.0
    active = nodes * despawn
    waiting = max(0.0, respawn - (nodes - 1.0) * despawn)
    return active / (active + waiting) if active + waiting > 0 else 1.0


def best_tool(
    chunk_info: ChunkInfo, family: str, level: int, available: frozenset[str]
) -> str:
    """The best member of `family` this map can reach and this level can hold.

    **Both gates, and the second is the one that is easy to lose.** The export
    carries `toolLevels`, which is the skill level each tool *needs* - so a rune
    axe sitting in a reachable chunk is not a rune axe at level 30, and pricing
    the climb as though it were would make every band above the first read like
    the top one.

    `""` when nothing in the family is reachable, which the caller must treat as
    "cannot price" rather than as the worst tool: a chunk map that holds no axe
    holds no woodcutting either.
    """
    members = _mapping(chunk_info.code_items, "itemsPlus").get(family)
    levels = _mapping(_mapping(chunk_info.data, "toolLevels"), family)
    if not isinstance(members, list):
        return ""
    lowered = {name.lower() for name in available}
    best = ""
    best_level = -1
    for member in members:
        if not isinstance(member, str) or member.lower() not in lowered:
            continue
        needs = levels.get(member)
        needs = int(needs) if isinstance(needs, (int, float)) else 1
        # Ordered worst to best in the export, and `toolLevels` agrees; the
        # highest requirement this level clears is the best tool held.
        if needs <= level and needs >= best_level:
            best, best_level = member, needs
    return best


def expand_families(chunk_info: ChunkInfo) -> dict[str, tuple[str, ...]]:
    """`Iron[+]` -> `("Iron rocks", "Iron vein")`, over objects, NPCs and monsters.

    **The export names a family where the wiki names a page**, and every Mining
    challenge does it: `Mine ~|iron ore|~` lists `Objects: ["Iron[+]"]`, whose
    members are the two things actually charted. Without this the whole skill
    joins nothing - measured, 1 of 29 methods priced - because `Iron` is not a
    page and `Iron rocks` is.

    Members stay in the export's own order, so the caller takes the first that
    has a curve. That is the plain rock rather than the vein, which is the
    ordinary case and the one the published rates describe.
    """
    found: dict[str, tuple[str, ...]] = {}
    for branch in ("objectsPlus", "npcsPlus", "monstersPlus", "itemsPlus"):
        for family, members in _mapping(chunk_info.code_items, branch).items():
            if isinstance(members, list) and family not in found:
                found[family] = tuple(
                    member for member in members if isinstance(member, str)
                )
    return found


#: The challenge fields that name the thing a method acts on, most specific
#: first.
#:
#: **One list, because keeping four in step failed three times.** `Monsters`
#: was missing from the experience lookup, so an embertailed jerboa was refused
#: before its curve was asked for; from the borrow lookup, so it could not have
#: been rescued; and from the loop lookup, so an imp - which names itself only
#: there - kept the calculator's `Other` and was refused again. Every lookup
#: that turns a challenge into a name reads this.
_NAME_FIELDS = ("Output", "Objects", "NPCs", "Monsters")


def _curve_for(
    tables: Tables,
    families: Mapping[str, Sequence[str]],
    challenge: Mapping[str, Any],
    task: str,
    skill: str = "",
) -> tuple[str, tuple[tuple[str, float, float, int, str], ...]]:
    """The success curve for a challenge, and the page it was read off.

    Keys are tried most specific first and every one is a **whole string**:
    `Output` is upstream's own statement of what the action yields and is where
    Fishing's curves live (the chart is on `Raw lobster`, not on the spot);
    `Objects` and `NPCs` are where Woodcutting's, Mining's and Thieving's live.
    The disambiguated forms are offered *after* the plain ones, never instead,
    so a page the wiki really does title `Warrior (Thieving)` matches itself
    first and this can only add a join.
    """
    keys = _join_keys(challenge, families, _NAME_FIELDS, skill)
    for key in keys:
        found = tables.curves.get(key.lower())
        if found:
            return key, found
    return "", ()


def _join_keys(
    challenge: Mapping[str, Any],
    families: Mapping[str, Sequence[str]],
    fields: Sequence[str],
    skill: str = "",
) -> tuple[str, ...]:
    """Every whole-string name a challenge offers, most specific first.

    A `[+]` field contributes its members in the export's order **as well as**
    the bare name, never instead of it: `Willow[+]` has no expansion and its
    own stripped form is what joins, while `Iron[+]` has two and neither is
    spelled `Iron`. The disambiguated forms come last for the same reason they
    do in `heuristics._join_keys` - so a page the wiki really does title
    `Warrior (Thieving)` matches itself before the bare `Warrior`.

    **Both directions of the disambiguator, because the two vocabularies
    disagree in both.** Stripping one turns the export's `Warrior (Thieving)`
    into the wiki's `Warrior`; *adding* the skill's own turns the export's
    `Black salamander` into the wiki's `Black salamander (Hunter)`, which is
    how the wiki separates a creature you hunt from the item it drops. Hunter
    is the skill that needs it and it is not a Hunter special case: the whole
    of net trapping and half of box trapping joined nothing without it, which
    is five methods on the reference map and every salamander in the export.
    Added last, so a page that really is titled plainly still wins.
    """
    keys: list[str] = []
    for field_name in fields:
        value = challenge.get(field_name)
        raw = [value] if isinstance(value, str) else value if isinstance(value, list) else []
        for name in raw:
            if not isinstance(name, str) or not name.strip():
                continue
            keys.extend(families.get(name.strip(), ()))
            keys.append(name.split("#")[0].replace("[+]", "").replace("*", "").strip())
    keys.extend(_DISAMBIGUATOR.sub("", key).strip() for key in list(keys))
    if skill:
        keys.extend(f"{key} ({skill})" for key in list(keys) if "(" not in key)
    return tuple(key for key in dict.fromkeys(keys) if key)


def _names(challenge: Mapping[str, Any], field_name: str) -> list[str]:
    """A challenge field as a list of clean names.

    `[+]`, `*` and `#section` come off: upstream uses them for "or its
    variants", "you keep this" and "this part of the page", none of which
    changes which wiki page describes the thing.
    """
    value = challenge.get(field_name)
    raw = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    return [
        name.split("#")[0].replace("[+]", "").replace("*", "").strip()
        for name in raw
        if isinstance(name, str) and name.strip()
    ]


def _experience_for(
    tables: Tables,
    families: Mapping[str, Sequence[str]],
    skill: str,
    challenge: Mapping[str, Any],
    task: str,
) -> tuple[float, str]:
    """What one successful action pays and which loop it belongs to.

    `(0.0, "")` where the calculator does not describe it, which drops the
    method. **Refused rather than defaulted**: experience per action is the
    whole numerator, and a stand-in for it would be a rate this project
    invented wearing a citation.
    """
    by_name = tables.experience.get(skill) or {}
    for key in _join_keys(challenge, families, _NAME_FIELDS, skill):
        found = by_name.get(key.lower())
        if found:
            return found
    return 0.0, ""


def _cascade(
    tables: Tables,
    skill: str,
    order: Sequence[str],
    node: str,
    level: int,
) -> tuple[float, float, float] | None:
    """`(marginal chance, experience per catch, any-catch chance)` for one node.

    **Two questions, answered as one pair so the ordinary arithmetic still
    works.** What the *action* pays is the expectation over the whole cascade -
    roll sturgeon, and on failing that salmon, and on failing that trout - while
    what *this fish* costs is only the branch that yields it. Returning the
    marginal chance with the expectation divided by it makes
    `experience * chance` the expected XP per roll, so `xp_per_hour` prices the
    activity, and `roll_seconds / chance` the time to obtain this one fish, so
    the item walk still prices a leaping sturgeon rather than an average fish.

    `None` if any member of the cascade is missing a curve or an experience
    figure: half a cascade is not a smaller cascade, it is a different one.
    """
    paid = tables.experience.get(skill) or {}
    survive = 1.0
    expected = 0.0
    marginal = 0.0
    for name in order:
        curves = tables.curves.get(name.lower())
        figure = paid.get(name.lower())
        if not curves or not figure:
            return None
        chance = success_chance(level, curves[0][1], curves[0][2])
        expected += survive * chance * figure[0]
        if name.lower() == node.lower():
            marginal = survive * chance
        survive *= 1.0 - chance
    if marginal <= 0 or expected <= 0:
        return None
    return marginal, expected / marginal, 1.0 - survive


def _loop_for(
    profile: SkillProfile,
    families: Mapping[str, Sequence[str]],
    challenge: Mapping[str, Any],
    skill: str,
) -> str:
    """The loop a profile assigns this node, or `""` to keep the calculator's."""
    if not profile.loop_at:
        return ""
    for key in _join_keys(challenge, families, _NAME_FIELDS, skill):
        found = profile.loop_at.get(key.lower())
        if found:
            return found
    return ""


def _fixed_chance(
    profile: SkillProfile,
    families: Mapping[str, Sequence[str]],
    challenge: Mapping[str, Any],
    skill: str,
) -> tuple[str, float, str] | None:
    """`(node, chance, provenance)` where a profile states one outright."""
    if not profile.fixed_chances:
        return None
    for key in _join_keys(challenge, families, _NAME_FIELDS, skill):
        found = profile.fixed_chances.get(key.lower())
        if found is not None:
            return key, found[0], found[1]
    return None


def _borrowed_curve(
    tables: Tables,
    profile: SkillProfile,
    families: Mapping[str, Sequence[str]],
    challenge: Mapping[str, Any],
    skill: str,
) -> tuple[str, str, float, float] | None:
    """`(node, label, low, high)` for a creature borrowing another's chart.

    **The slope is kept and the line is moved**, so the borrower reaches the
    donor's opening chance at its *own* opening level rather than at the
    donor's. See `SkillProfile.assumed_curves` for why that is what "the same
    curve" means here.

    The donor's first series is taken, which is the unassisted one - the same
    conservative reading `_tool_curve` falls back to - and the unlock level is
    the challenge's own `Level`. `None` where nothing is borrowed, where the
    donor is uncharted itself, or where the challenge states no level, since
    the whole construction is anchored on that number.
    """
    if not profile.assumed_curves:
        return None
    node = ""
    donor_name = ""
    for key in _join_keys(challenge, families, _NAME_FIELDS, skill):
        found = profile.assumed_curves.get(key.lower())
        if found:
            node, donor_name = key, found
            break
    if not donor_name:
        return None
    donor = tables.curves.get(donor_name.lower())
    opens = challenge.get("Level")
    if not donor or not isinstance(opens, (int, float)) or opens < 1:
        return None
    # **The worst series the donor has, not its first.** An assumed number
    # should be the pessimistic one, and "first" only happened to mean that for
    # the butterflies - the `Chinchompa` chart opens with grey, which is the
    # *easiest* of its three. Worst is measured where each series begins, since
    # that is the one point every series of a family can be compared at.
    label, low, high, donor_req, _provenance = min(
        donor, key=lambda series: series[1] + (series[2] - series[1]) * (series[3] - 1) / 98.0
    )
    slope = (high - low) / 98.0
    at_donor = low + slope * (donor_req - 1)
    moved = at_donor - slope * (int(opens) - 1)
    return node, f"assumed: {donor_name}", moved, moved + (high - low)


def _respawn_key(
    tables: Tables,
    families: Mapping[str, Sequence[str]],
    challenge: Mapping[str, Any],
    skill: str,
) -> str:
    """The first name a challenge offers that `Tables.respawns` knows.

    Separate from `_curve_for` because it answers a different question with the
    same keys: not "how often does this succeed" but "how long until there is
    another one".
    """
    for key in _join_keys(challenge, families, _NAME_FIELDS, skill):
        if key.lower() in tables.respawns:
            return key
    return ""


def _tool_curve(
    curves: tuple[tuple[str, float, float, int, str], ...],
    profile: SkillProfile,
    tool: str,
    opens: int = 0,
) -> tuple[str, float, float, int, str]:
    """Which series of a chart to spend. Three rules, in order.

    **A tool tier where the profile says the labels are tools** - Woodcutting
    alone - taking the one naming the axe held, and the first otherwise, which
    is the worst tier and the conservative end.

    **Otherwise the series drawn for *this* creature**, matched on the level it
    opens at. A chart is often shared by a family and drawn once: the
    `Chinchompa` chart carries Grey at 53, Red at 63 and Black at 73, and it
    appears verbatim on all three pages. Taking the first gave every chinchompa
    the grey one - certain at 99 where the other two are 0.895 - so red and
    black were priced about 12% fast at the top and further out below it, with
    the fitted box-trap interval quietly absorbing the difference. That is why
    the two of them looked identical when the wilderness trap was measured.

    **The first otherwise**, which is all a single-series chart has anyway.
    """
    if profile.tool_tiers and tool:
        # `Rune axe` -> `rune`, against a series labelled `Rune`.
        tier = tool.lower().split()[0]
        for series in curves:
            if series[0].strip().lower() == tier:
                return series
        return curves[0]
    if opens > 0:
        for series in curves:
            if series[3] == opens:
                return series
    return curves[0]


def rate_at(
    tables: Tables,
    families: Mapping[str, Sequence[str]],
    profile: SkillProfile,
    task: str,
    skill: str,
    challenge: Mapping[str, Any],
    level: int,
    *,
    tool: str = "",
) -> NodeRate | None:
    """Price one gathering method at one level, or `None` if it cannot be.

    Every input is refused rather than defaulted. A method with no curve, no
    experience figure, no reachable tool where one is needed, or a zero success
    chance is **not a slow method here; it is not a method at all** - the same
    posture `costing/recipe_rates.py` takes with an unpriceable ingredient, and
    for the same reason: a made-up numerator opens a band.
    """
    experience, kind = _experience_for(tables, families, skill, challenge, task)
    if experience <= 0:
        return None
    kind = _loop_for(profile, families, challenge, skill) or kind

    node, curves = _curve_for(tables, families, challenge, task, skill)
    label = ""
    provenance = CONFIRMED
    borrowed = _borrowed_curve(tables, profile, families, challenge, skill)
    fixed = _fixed_chance(profile, families, challenge, skill)
    if curves:
        opens = challenge.get("Level")
        label, low, high, _req, provenance = _tool_curve(
            curves, profile, tool, int(opens) if isinstance(opens, (int, float)) else 0
        )
        chance = success_chance(level, low, high)
    elif fixed is not None:
        # **Stated in prose, or not stated at all.** Either way there is no
        # curve to evaluate, so the chance does not move with level - which is
        # true of the antelopes and is the honest shape of a guess.
        node, chance, provenance = fixed
    elif borrowed is not None:
        node, label, low, high = borrowed
        provenance = INFERRED
        chance = success_chance(level, low, high)
    elif kind in profile.certain_kinds:
        # **No chart because there is nothing to chart.** An ordinary stall is
        # a 100% steal and crab traps "cannot fail" - both stated on the wiki -
        # and the pages that *do* carry a chart are the Ape Atoll stalls, which
        # really can fail. So a loop declared certain reads a missing chart as
        # certainty rather than as ignorance.
        node = _respawn_key(tables, families, challenge, skill) or node
        if not node:
            keys = _join_keys(challenge, families, _NAME_FIELDS, skill)
            node = keys[0] if keys else ""
        if not node:
            return None
        chance = 1.0
    else:
        return None
    if node.lower() in profile.refuses:
        return None
    # **Restock-bound loops need their restock.** See `restock_kinds`: without
    # it a stall falls back to the interaction cadence and reads as the fastest
    # method in the game.
    if kind in profile.restock_kinds and node.lower() not in tables.respawns:
        return None
    if chance <= 0:
        return None

    # **A cascade pays for every roll in it, not just the one asked about.**
    cascade = profile.cascades.get(node.lower())
    caught = 0.0
    if cascade:
        priced = _cascade(tables, skill, cascade, node, level)
        if priced is None:
            return None
        chance, experience, caught = priced

    ticks = profile.roll_ticks_by_kind.get(kind)
    if ticks is None and profile.strict_kinds:
        return None
    roll_seconds = (ticks if ticks is not None else profile.roll_ticks) * TICK_SECONDS
    if profile.tool_axis == "interval":
        ticks = tables.tool_ticks.get(tool)
        if ticks is None or ticks <= 0:
            return None
        roll_seconds = ticks * TICK_SECONDS

    # **Two shapes of downtime, and a node has exactly one of them.** A tree
    # the wiki tabulates yields for its whole despawn window, so its cost is a
    # duty cycle over the rolling. A node it does not tabulate - every rock,
    # and every tree below oak - hands over one resource and is gone, so its
    # cost is a flat charge per resource. Applying both would bill the same
    # wait twice.
    units = units_worked(tables, profile, skill, kind, node, level)
    if units <= 0:
        return None

    # **A borrowed interval caps how good the whole rate can be.** See
    # `inferred_loops`: a measured chance divided by a guessed cadence is not a
    # measurement, and reporting it as one would be worse than reporting
    # nothing.
    if kind in profile.inferred_loops and provenance == CONFIRMED:
        provenance = INFERRED

    # **Working several of a node pays off three different ways, and which one
    # is decided by what the node makes you wait for.** All three spend the
    # same `units`; none of them is about which skill it is.
    #
    # - a node the wiki publishes a *cycle* for yields over a window and then
    #   regrows, so more of them fills the gap: `duty_cycle`, capped at no wait.
    # - a node it publishes a *restock* for hands over one thing and is empty,
    #   so more of them divides the wait - three chests in a room means the
    #   first is back by the time you return to it.
    # - anything else with a count is a loop that runs **simultaneously**
    #   rather than in rotation, which is a trap line: it divides the rolling
    #   outright, and is the only one of the three that can beat one-at-a-time
    #   throughput.
    duty = 1.0
    per_resource = 0.0
    # **Only a simultaneous loop divides the rolling.** Rotation - a cycle or a
    # restock - never makes the *action* quicker; you still swing at one tree
    # and open one chest at a time. Letting `worked` reach the rolling was a
    # real regression when these were unified: every tree the wiki tabulates no
    # cycle for silently chopped twice as fast, and the fit absorbed it by
    # moving `node_seconds` from 2.4 to 3.7.
    rolling_units = units if kind in profile.parallel_kinds else 1.0
    cycle = tables.cycles.get(node.lower()) if profile.depletes else None
    restock = tables.respawns.get(node.lower())
    if cycle is not None:
        duty = duty_cycle(cycle[0], cycle[1], units)
    elif restock is None and profile.depletes:
        per_resource = profile.node_seconds

    # **Several units of the loop at once**, where the game publishes how
    # many. Divides the rolling outright, unlike `duty`, which only fills a
    # wait - five box traps really are five independent chances at a time.
    # A failed roll can cost more than the roll: see `SkillProfile.fail_seconds`.
    failures = (1.0 / chance) - 1.0
    stun = profile.fail_seconds_by_kind.get(kind, profile.fail_seconds)
    banking = (
        profile.bank_seconds / profile.carry if profile.carry > 0 else 0.0
    )
    if node.lower() in profile.unbanked:
        banking = 0.0
    elif cascade:
        # **A cascade banks what the action caught, not what the task asked
        # for.** One roll yields at most one fish and it is banked whichever of
        # the three it turned out to be, so the trip is charged against the
        # whole catch rate and then shared over this branch, rather than billed
        # to the rarest fish as though the other two were free to carry.
        banking = banking * caught / chance
    working = (
        roll_seconds / chance / duty / rolling_units
        + stun * failures
        + per_resource
    )

    # **A restocking node is a floor, not an addition.** A stall hands over one
    # item and is empty until it restocks, so however fast you can roll you
    # cannot take a second item sooner - and where the rolling is the slower of
    # the two, the rolling is what you wait for. `max` is the whole model, and
    # it is why this needs no fitted constant: both halves are published.
    #
    # **The floor is over the working time and not over the banking**, which is
    # charged after it. A trip does not happen while a stall restocks; it is
    # time on top, the same way it is for every other loop here.
    if restock is not None:
        working = max(restock / units, working)

    seconds_per_resource = working + banking
    if seconds_per_resource <= 0:
        return None
    return NodeRate(
        task=task,
        skill=skill,
        level=level,
        xp_per_hour=experience * 3600.0 / seconds_per_resource,
        experience=experience,
        chance=chance,
        roll_seconds=roll_seconds,
        duty=duty,
        node=node,
        tool=tool or label,
        bank_seconds_per_item=banking,
        provenance=provenance,
    )


def priced_methods(
    chunk_info: ChunkInfo,
    valid: Mapping[str, Mapping[str, Any]],
    tables: Tables,
    available: frozenset[str],
    levels: Mapping[str, int] | None = None,
) -> tuple[dict[str, tuple[NodeRate, ...]], GatheringCoverage]:
    """Every reachable gathering method, priced at each level it is worth
    re-reading.

    **Several rates per method, not one.** A success curve is a function of
    level and `costing/training.training_bands` already turns (level, rate)
    points into bands by running maximum, so handing it the curve's own shape
    costs nothing and stops one figure being charged for a seventy-level climb.
    See `CURVE_STEPS`.

    The tool is re-chosen at each step for the same reason: a map holding a rune
    axe gets a bronze one's curve until level 41 whatever is in the bank, and
    that boundary is a real band edge.

    Only methods in `valid` are considered, so this inherits the derivation's
    reachability gate rather than inventing a second one.
    """
    families = expand_families(chunk_info)
    priced: dict[str, tuple[NodeRate, ...]] = {}
    coverage: dict[str, tuple[int, int]] = {}
    no_curve: list[str] = []
    no_experience: list[str] = []

    for skill, profile in sorted(PROFILES.items()):
        challenges = _mapping(chunk_info.challenges, skill)
        offered = found = 0
        for task in sorted(valid.get(skill) or {}):
            challenge = challenges.get(task)
            if not isinstance(challenge, dict) or challenge.get("Primary") is not True:
                continue
            offered += 1
            opens = challenge.get("Level")
            opens = int(opens) if isinstance(opens, (int, float)) else 1
            family = _tool_family(challenge)

            rates: list[NodeRate] = []
            for level in (opens, *(step for step in CURVE_STEPS if step > opens)):
                tool = (
                    best_tool(chunk_info, family, level, available) if family else ""
                )
                if family and not tool:
                    continue
                rate = rate_at(
                    tables, families, profile, task, skill, challenge, level, tool=tool
                )
                if rate is not None and rate.xp_per_hour > 0:
                    rates.append(rate)
            if not rates:
                _record_miss(
                    tables, families, skill, challenge, task, no_curve, no_experience
                )
                continue
            found += 1
            priced[task] = tuple(rates)
        if offered:
            coverage[skill] = (found, offered)

    return priced, GatheringCoverage(
        skills=coverage,
        no_curve=tuple(sorted(no_curve)),
        no_experience=tuple(sorted(no_experience)),
    )


def _tool_family(challenge: Mapping[str, Any]) -> str:
    """The `[+]` tool family a challenge needs, or `""`.

    **Read off the challenge rather than off the skill**, because the export
    already states it: `Chop ~|willow logs|~` lists `Axe[+]` in its `Items` and
    `Mine ~|iron ore|~` lists `Pickaxe[+]`. A per-skill constant would say the
    same thing less accurately - Mining's `Dig at a ~|soil|~ spot` wants a
    trowel, not a pickaxe, and has no roll interval to read off one.
    """
    for name in _names(challenge, "Items"):
        family = f"{name}[+]"
        if name in ("Axe", "Pickaxe"):
            return family
    for value in challenge.get("Items") or ():
        if isinstance(value, str) and value.strip() in ("Axe[+]", "Pickaxe[+]"):
            return value.strip()
    return ""


def _record_miss(
    tables: Tables,
    families: Mapping[str, Sequence[str]],
    skill: str,
    challenge: Mapping[str, Any],
    task: str,
    no_curve: list[str],
    no_experience: list[str],
) -> None:
    """Say *which* input was missing, so coverage is diagnosable.

    "1,200 methods unpriced" is not actionable; "these named a node the wiki
    charts nothing for, and those have a chart but no experience figure" points
    at the page to go and read.
    """
    _, curves = _curve_for(tables, families, challenge, task, skill)
    if not curves:
        no_curve.append(task)
    elif _experience_for(tables, families, skill, challenge, task)[0] <= 0:
        no_experience.append(task)


def apply(
    training: Mapping[str, Mapping[str, Rate]],
    priced: Mapping[str, Sequence[NodeRate]],
    pinned: frozenset[str] = frozenset(),
) -> dict[str, dict[str, Rate]]:
    """`training` with a modelled rate wherever this model has one.

    **`defaults < scraped < modelled < overrides`, and the ordering is the
    point of the module.** It is the opposite of `recipe_rates.apply`, which
    puts its computed number *below* the scrape, and the difference is not
    taste:

    - A recipe and a money-making guide measure different things. The guide
      assumes you bought the silver bar; the recipe charges you six minutes for
      mining it. Neither is wrong and the guide is the better-known number, so
      it keeps the method.
    - A success curve and a training guide measure the **same** thing - how
      fast this action goes - and the curve is the better-informed of the two,
      because it is evaluated at this map's level with this map's best
      reachable axe where the guide is somebody else's account. So it wins, the
      same way `dps_bridge` puts a simulated fight above a scraped kill rate.

    The rate written is the one at the method's **opening level**, which is the
    conservative end of its own curve and the reading `_add_banded` already
    takes. The faster points go through `banded_methods` into the band walk,
    where a level can be attached to them.

    `pinned` is the set of task names `heuristics/overrides.json` speaks about;
    a hand pin outranks everything, as it does everywhere else.
    """
    merged = {task: dict(skills) for task, skills in training.items()}
    for task, rates in priced.items():
        if task in pinned or not rates:
            continue
        opening = min(rates, key=lambda rate: rate.level)
        merged.setdefault(task, {})[opening.skill] = Rate(
            value=opening.xp_per_hour, source=GATHERING_SOURCE, match=GATHERING_MATCH
        )
    return merged


def banded_methods(
    priced: Mapping[str, Sequence[NodeRate]],
    *,
    keep_first: bool = False,
) -> dict[str, tuple[ComputedMethod, ...]]:
    """The curve's higher points, as methods the band walk can open later.

    **Why this exists at all**: `Heuristics.training` is one rate per task, and
    a gathering rate is not one number. The rest of the curve therefore travels
    the way combat's and Prayer's rates already do - through
    `Heuristics.computed`, which carries a `level` per entry precisely so
    `training_bands` can open it at the right place.

    The method name is `activity_name(task)` for every point, so a climb reads
    as one method getting faster rather than as ten methods, which is what it
    is. The opening point is left out: `apply` has already written it into
    `training`, and offering it twice would put a duplicate in the tooltip.
    """
    found: dict[str, list[ComputedMethod]] = {}
    for task, rates in priced.items():
        if not rates:
            continue
        # **The opening point is normally already in `training`**, so offering
        # it again would put a duplicate in the tooltip. `keep_first` is for a
        # method that never went to `training` at all - see
        # `inputs._gathered` on Puro-Puro, whose challenge states a level that
        # is about holding the realm rather than about the method.
        opening = -1 if keep_first else min(rate.level for rate in rates)
        for rate in rates:
            if rate.level <= opening:
                continue
            found.setdefault(rate.skill, []).append(
                ComputedMethod(
                    method=activity_name(task),
                    xp_per_hour=rate.xp_per_hour,
                    level=rate.level,
                    match=GATHERING_MATCH,
                    # The config key is the challenge's own name, as everywhere
                    # else - `activity_name` is display only.
                    knob=f"training/{task}/{rate.skill}",
                )
            )
    return {
        skill: tuple(sorted(methods, key=lambda method: (method.level or 0, method.method)))
        for skill, methods in found.items()
    }
