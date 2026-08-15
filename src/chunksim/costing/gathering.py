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
   the single-node one; how many nodes a player rotates is what picks a point
   between them, and it is `SkillProfile.nodes_worked`.

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

**Throughput is not always one loop at a time.** Box trapping, net trapping and
bird snaring run several traps at once, 1 to 5 across levels 1 to 80, and the
Hunter page publishes the table; the Wilderness allows a sixth for black
chinchompas and black salamanders. That divides the rolling outright, which is
what makes it different from `nodes_worked` - that one fills a wait and is
capped at having no wait, this one runs several independent loops. It is also
most of why hunting speeds up with level, and none of it is in a success curve.

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
    #: How many nodes a player rotates between while one respawns, **where the
    #: wiki publishes that node's cycle**. One means standing at a single node
    #: and waiting out every respawn; higher means walking to the next one.
    #: Fitted rather than chosen - see `costing/gathering_overhead.py`.
    nodes_worked: float = 1.0
    #: Seconds lost per resource for a node whose cycle is **not** published.
    #: A normal tree hands over one log and vanishes, and a rock one ore; the
    #: wiki tabulates despawn and respawn for thirteen trees and for nothing
    #: else, so what a rock costs you between ores is the one number here that
    #: no page states. **Fitted against the rates the wiki does publish**, and
    #: `0.0` for the skills whose nodes do not deplete at all.
    node_seconds: float = 0.0
    #: The calculator `kind`s worked several units at a time, against
    #: `Tables.parallel`'s published step table for the skill.
    #:
    #: **The generic form of "you can run five box traps".** Hunter publishes
    #: the count as a function of level - 1, 2, 3, 4, 5 at 1, 20, 40, 60 and 80
    #: - and it applies to box trapping, net trapping and bird snaring but not
    #: to falconry or tracking, which is why it is a set of kinds rather than a
    #: profile-wide flag. It multiplies throughput outright, which is what
    #: makes it different from `nodes_worked`: that one fills a wait and is
    #: capped at no wait, this one runs several loops at once.
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
    #: Node -> units *beyond* what the step table allows there, where the game
    #: says so. One entry today: the Wilderness lets a sixth trap out for black
    #: chinchompas, which the Hunter and Box trap pages both state.
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
        nodes_worked=2.0,
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
        refuses=frozenset(
            {
                # **Barbarian fishing is a cascade**: sturgeon is rolled, then
                # salmon on that failing, then trout on that failing. The wiki
                # documents it under "Cascading chances" and this model rolls
                # once, which read them 0.73x.
                "leaping sturgeon",
                "leaping salmon",
                "leaping trout",
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
    # The residual is density and reads as density. The two Wilderness rows sit
    # slow (black chinchompa 0.77x, black salamander 0.69x) and the lowest-level
    # row sits fast (swamp lizard 1.48x), which is what one number per loop
    # buys against guides quoting their best spot.
    "Hunter": SkillProfile(
        depletes=False,
        strict_kinds=True,
        roll_ticks_by_kind={
            "Falconry": 10.0,
            "Box trap": 101.0,
            "Deadfall": 105.0,
            "Net trapping": 154.0,
        },
        parallel_kinds=frozenset({"Box trap", "Net trapping", "Bird snare"}),
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
        roll_ticks_by_kind={"Pickpocket": 2.0, "Stalls": 2.0},
        fail_seconds=3.6,
        fail_seconds_by_kind={"Stalls": 0.0},
        certain_kinds=frozenset({"Stalls"}),
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

    #: Lowercased page title -> its success curves, in written order.
    curves: dict[str, tuple[tuple[str, float, float], ...]] = field(default_factory=dict)
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
    #: Skill -> `(level, units)` steps, for a loop worked several at a time.
    parallel: dict[str, tuple[tuple[int, float], ...]] = field(default_factory=dict)

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
    curves: dict[str, tuple[tuple[str, float, float], ...]] = {}
    for page, series in _mapping(raw, "curves").items():
        if not isinstance(series, list):
            continue
        read = tuple(
            (str(entry.get("label", "")), float(entry["low"]), float(entry["high"]))
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

    parallel: dict[str, tuple[tuple[int, float], ...]] = {}
    for skill, steps in _mapping(raw, "parallel").items():
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
            parallel[skill] = tuple(sorted(steps_read))

    return Tables(
        curves=curves,
        tool_ticks=ticks,
        cycles=cycles,
        experience=experience,
        materials=materials,
        respawns=respawns,
        parallel=parallel,
    )


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


def _curve_for(
    tables: Tables,
    families: Mapping[str, Sequence[str]],
    challenge: Mapping[str, Any],
    task: str,
    skill: str = "",
) -> tuple[str, tuple[tuple[str, float, float], ...]]:
    """The success curve for a challenge, and the page it was read off.

    Keys are tried most specific first and every one is a **whole string**:
    `Output` is upstream's own statement of what the action yields and is where
    Fishing's curves live (the chart is on `Raw lobster`, not on the spot);
    `Objects` and `NPCs` are where Woodcutting's, Mining's and Thieving's live.
    The disambiguated forms are offered *after* the plain ones, never instead,
    so a page the wiki really does title `Warrior (Thieving)` matches itself
    first and this can only add a join.
    """
    keys = _join_keys(
        challenge, families, ("Output", "Objects", "NPCs", "Monsters"), skill
    )
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
    for key in _join_keys(challenge, families, ("Output", "Objects", "NPCs"), skill):
        found = by_name.get(key.lower())
        if found:
            return found
    return 0.0, ""


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
    for key in _join_keys(challenge, families, ("Output", "Objects", "NPCs"), skill):
        if key.lower() in tables.respawns:
            return key
    return ""


def _tool_curve(
    curves: tuple[tuple[str, float, float], ...], profile: SkillProfile, tool: str
) -> tuple[str, float, float]:
    """Which series of a chart to spend.

    The first, except where the profile says the labels are tool tiers - in
    which case the one naming the tool held. A tool with no series of its own
    falls back to the first, which is the worst tier and therefore the
    conservative end, the same direction every other choice here leans.
    """
    if not profile.tool_tiers or not tool:
        return curves[0]
    # `Rune axe` -> `rune`, against a series labelled `Rune`.
    tier = tool.lower().split()[0]
    for series in curves:
        if series[0].strip().lower() == tier:
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

    node, curves = _curve_for(tables, families, challenge, task, skill)
    label = ""
    if curves:
        label, low, high = _tool_curve(curves, profile, tool)
        chance = success_chance(level, low, high)
    elif kind in profile.certain_kinds:
        # **No chart because there is nothing to chart.** An ordinary stall is
        # a 100% steal - the Thieving page says so outright - and the pages
        # that *do* carry a chart are the Ape Atoll ones, which really can
        # fail. So a loop declared certain reads a missing chart as certainty
        # rather than as ignorance. Gated on a published restock time as well,
        # which is what keeps "no chart" from meaning "no data at all".
        node = _respawn_key(tables, families, challenge, skill)
        if not node:
            return None
        chance = 1.0
    else:
        return None
    if node.lower() in profile.refuses:
        return None
    if chance <= 0:
        return None

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
    duty = 1.0
    per_resource = 0.0
    cycle = tables.cycles.get(node.lower()) if profile.depletes else None
    if cycle is not None:
        duty = duty_cycle(cycle[0], cycle[1], profile.nodes_worked)
    elif profile.depletes:
        per_resource = profile.node_seconds

    # **Several units of the loop at once**, where the game publishes how
    # many. Divides the rolling outright, unlike `duty`, which only fills a
    # wait - five box traps really are five independent chances at a time.
    units = 1.0
    if kind in profile.parallel_kinds:
        units = units_at(tables.parallel.get(skill, ()), level)
        units += profile.parallel_bonus.get(node.lower(), 0.0)
    if units <= 0:
        return None

    # A failed roll can cost more than the roll: see `SkillProfile.fail_seconds`.
    failures = (1.0 / chance) - 1.0
    stun = profile.fail_seconds_by_kind.get(kind, profile.fail_seconds)
    banking = (
        profile.bank_seconds / profile.carry if profile.carry > 0 else 0.0
    )
    working = (
        roll_seconds / chance / duty / units
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
    respawn = tables.respawns.get(node.lower())
    if respawn is not None:
        working = max(respawn, working)

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
        opening = min(rate.level for rate in rates)
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
