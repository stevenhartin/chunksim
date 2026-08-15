"""Fitting the four constants `costing/gathering.py` cannot read off a page.

**No caller in `src/`.** Like `recipe_overhead.py` and `dps_overhead.py`, this
exists to be re-run when someone doubts a number in `gathering.PROFILES` - run
it, read what it says, and change the profile if the fit has moved.

    .venv/bin/python -m chunksim.costing.gathering_overhead

**Most of the model's inputs are published and this file exists for the rest.**
A success curve, a roll interval, a tree's despawn/respawn and - since the
`{{Mining info}}` scrape - every rock's respawn are all on the wiki and read by
`remote/gathering.py`. What is nowhere is what a normal *tree* costs you between
logs, or a failed pickpocket in stun time. Those are fitted here against the
rates the wiki does publish.

**The rock half of that used to be here and was wrong.** This file said a rock's
downtime was published nowhere - "not on the skill page, not in the scenery
infobox, not in any Module" - and it is in the scenery infobox, on 96 pages, in
a `time` field. The search had been for a Woodcutting-style *table*, and finding
none was read as finding nothing. The superseded version is kept here because it
is the tempting mistake: absence of a table is not absence of data, and the
per-page infobox is where this project should look first next time.

**What it is fitted against matters more than how.** The targets are the wiki's
own training-guide figures, joined *exactly*, and nothing else:
`remote/skill_tables.py`'s Woodcutting, Mining and pickpocket tables. Money
making guides are deliberately excluded and it is not fastidiousness - a
`Money making guide/Catching lobsters` figure is about profit, so it is quoted
with a bank run inside it that this model does not charge, and fitting to it
would fold somebody's banking into a constant that means "node downtime".
Measured, the mmg rows disagree with the model 2.5x where the exact rows agree
within 1.1x, and letting them into the fit moves every constant the wrong way.

**Three fits, in descending order of how much they are worth.** `STATED_RATES`
recovers a whole curve from a table of hourly figures against level - six or
seven rows against two parameters, of one method. `CHECKED_RATES` fits nothing
at all: a published figure quoted *with* its level and tool, which the model
must reproduce. `STATED_CHANCES` is the weak one, and is labelled so - one flat
chance against one published figure, which is all a single number supports.
All three run under `--stated-curves`.

**Two fits, and they are not alike.** `fit` pins one constant per *skill*
against one published figure per method - the shape this project distrusts and
prints residuals for. `fit_stated_curves` recovers a success curve for one
*node* from a table of hourly figures against level: two parameters against six
or seven rows of one method, which is the better-supported of the two by a wide
margin. Run it with `--stated-curves`.

**One free parameter per skill, fitted on a grid.** There is not enough data for
anything cleverer - sixteen woodcutting rows and five fishing ones - and a one-parameter fit over eight points is already the shape this
project distrusts, which is why the residuals are printed per row rather than
summarised. Read them: a constant that fits six rows and misses two badly is
telling you the two are a different mechanic, not that the constant is wrong.
"""

from __future__ import annotations

import argparse
import math
from dataclasses import replace
from typing import Any, Callable, Mapping, Sequence

from chunksim.cli.common import load_state
from chunksim.costing import gathering, inputs
from chunksim.derive.pipeline import derive
from chunksim.derive.search import build_world_index
from chunksim.store.cache import read_gathering

#: The rate sources the fit will believe: figures a wiki *training guide*
#: publishes as an hourly rate, read by `remote/skill_tables.py`.
#:
#: **`wiki:pickpockets` and `wiki:shortcuts` are deliberately absent, and that
#: is the sharpest lesson in this file.** They look like wiki data and are not:
#: `heuristics._table_rates` computes them as `experience * 3600 /
#: PICKPOCKET_CYCLE_SECONDS`, where the cycle is a constant this project chose.
#: Fitting a model against them recovers that constant and calls it agreement -
#: it did, at four rows within 1.00x, which is what a circular fit looks like.
#: `PICKPOCKET_CYCLE_SECONDS`' own docstring says a single constant "cannot
#: follow" a success rate that climbs with level, which is precisely what this
#: model exists to fix, so it cannot also be the thing that judges it.
TRUSTED_SOURCES: tuple[str, ...] = (
    "wiki:woodcutting",
    "wiki:mining",
    "wiki:fishing",
    "wiki:hunter",
    "wiki:stalls",
    # The hand entry in `heuristics/overrides.json`, whose source names the
    # wiki page it was copied off. **Mining's only trusted row** - its three
    # tabulated headings (granite, gem rocks, calcified) all fail the
    # experience join, because the calculator names the gem and the challenge
    # names the rock.
    "wiki:Pay-to-play Mining training",
)

#: Roll intervals are searched in half ticks to thirty and whole ticks to three
#: hundred. **The long tail is for the traps.** A box-trap interval is not an
#: animation, it is how long one trap waits for prey to walk into it, and once
#: the model runs five traps at once that number is minutes rather than
#: seconds. Capped at thirty the fit simply sat on the bound, which is the
#: model saying "longer than this" and being disbelieved.
_TICK_GRID: tuple[float, ...] = tuple(x / 2 for x in range(2, 61)) + tuple(
    float(x) for x in range(31, 301)
)

#: Which profile fields each skill's fit moves, and the grid to search each on.
#: **A field is fitted only against the rows it actually changes**, which the
#: harness works out by varying it - so a tree the wiki tabulates a cycle for
#: never votes on `node_seconds`, and one it does not never votes on
#: `worked`. Without that the two fight over every row and neither lands.
FITTED: dict[str, tuple[tuple[str, tuple[float, ...]], ...]] = {
    # **`roll_ticks` is not fitted here and must not be.** The Woodcutting page
    # states four ticks outright, so it is data like the success curve is; left
    # free the fit pulls it to 2.5 to absorb the spread between oak and willow,
    # which trades a published mechanic for noise and makes every other
    # constant meaningless.
    "Woodcutting": (
        ("worked", tuple(x / 2 for x in range(2, 21))),
        ("node_seconds", tuple(x / 10 for x in range(0, 301))),
    ),
    # **Mining is deliberately absent and its rows are deliberately still
    # printed.** Every rock's respawn is published in its own infobox now, so
    # the only number left in the profile is the hop, which is one tick; and
    # the three `wiki:mining` rows below cannot judge it anyway - one is
    # explicitly a tick-manipulation figure and the other two are the low end
    # of a range quoted against a level band this harness does not evaluate at.
    # The reasoning is in `gathering.PROFILES["Mining"]`. Fitting to them
    # anyway is exactly the `mmg:` mistake in a different costume: a number
    # that measures something else, absorbed into a constant that then means
    # nothing.
    # **Per loop, not per skill.** `roll_ticks_by_kind` is fitted one `kind` at
    # a time against the rows of that kind alone - see `_fit_kinds`.
    # **The interval is pinned, the banking is fitted.** Net, bait, harpoon and
    # cage fishing all roll every 5 ticks; left free the fit pulls the interval
    # to 7.5 instead, which is not a mechanic - it is 5 ticks with the guide's
    # bank run folded into it, the same contamination `mmg:` rows carry.
    "Fishing": (("bank_seconds", tuple(float(x) for x in range(0, 241))),),
    "Hunter": (("roll_ticks_by_kind", _TICK_GRID),),
    # **Thieving is deliberately absent, and that is the result rather than an
    # omission.** Both of its constants are published - two ticks between
    # pickpocket attempts, eight ticks locked out after a failure - and the
    # stall half is not a rate at all but a restock time the wiki tabulates for
    # all thirty stalls. There is nothing left to fit, and fitting anyway would
    # trade a stated mechanic for noise, which is the mistake the Woodcutting
    # note above describes.
    # Nothing to fit: the model's answer for these is checked, not tuned.
}
#: Skills whose profile the fit leaves alone entirely.
_UNFITTED: tuple[str, ...] = ()

#: Skills whose trusted rows must not be read as agreement, and why - printed
#: with the block so a ratio cannot be quoted without its caveat.
#:
#: **Every Mining row is the bottom of a range quoted against a level band**,
#: and this harness evaluates at 99. `46,000-75,000 ... at levels 50-99`
#: contributes 46,000; `23,500-49,000 normally at levels 50-99` contributes
#: 23,500 - the *level 50* figure, against a model asked for level 99, which is
#: why calcified reads 2.08x here and 1.00x in `fit_stated_curves`, off the
#: same wiki table. Nothing in the scrape carries the level a figure was
#: quoted at, so this cannot be fixed by joining harder.
_ROWS_NOT_COMPARABLE: dict[str, str] = {
    "Mining": (
        "every wiki:mining row is a range low-end quoted at a level band, and "
        "granite's is a tick-manipulation figure - see PROFILES['Mining']. Run "
        "--stated-curves for the targets that can be compared"
    ),
}


#: The tool each family is fitted with. **The best in the game, not the best on
#: a map** - a published training figure describes a player who owns a dragon
#: axe, so pairing it with whatever a particular chunk map happens to reach
#: would fold that map's poverty into a constant about the game.
BEST_TOOLS: dict[str, str] = {"Axe[+]": "Dragon axe", "Pickaxe[+]": "Dragon pickaxe"}


def _targets(map_id: str) -> list[dict[str, Any]]:
    """Every method with both a modelled rate and a trusted published one.

    **Every challenge in the export, not the reachable ones.** The constants
    being fitted are facts about the game, so restricting the evidence to one
    map's unlocked chunks throws away most of it for no reason - measured, the
    reference map offers eight woodcutting rows where the export offers
    nineteen, and none of Fishing's seven or Hunter's twenty-one.
    """
    args = argparse.Namespace(map_id=map_id, chunkinfo=None, recompute=False)
    state, unlocked = load_state(args)
    derived = derive(state, unlocked)
    blobs = inputs.load_reference(None, map_id)
    heuristics, _ = inputs.load_heuristics(state.chunk_info, None, blobs)

    tables = blobs.gathering
    families = gathering.expand_families(state.chunk_info)
    found: list[dict[str, Any]] = []
    seen: set[tuple[str, str, float]] = set()
    for skill in sorted(gathering.PROFILES):
        challenges = state.chunk_info.challenges.get(skill) or {}
        for task, challenge in sorted(challenges.items()):
            if not isinstance(challenge, dict) or challenge.get("Primary") is not True:
                continue
            rate = heuristics.training.get(task, {}).get(skill)
            if rate is None or not rate.source.startswith(TRUSTED_SOURCES):
                continue
            # **A cascade is one method wearing three names.** Barbarian
            # fishing rolls sturgeon, then salmon, then trout in one action, so
            # the three challenges share a rate - and the guide quotes each at
            # the level it opens at, where this compares everything at 99.
            # Keeping all three would triple-count one observation and score
            # two of them against a number describing a different player. The
            # head of the cascade is the method at 99, so it is the one kept.
            profile = gathering.PROFILES[skill]
            node, _ = gathering._curve_for(
                tables, families, challenge, task, skill
            )
            cascade = profile.cascades.get(node.lower())
            if cascade and cascade[0].lower() != node.lower():
                continue
            # **One node quoted at one rate is one observation, however many
            # challenges name it.** The export carries `Catch a ~|ruby
            # harvest|~`, the same `in a jar`, and the barehanded variant, and
            # the guide has a single figure for all three - so keeping them all
            # would let butterflies outvote everything else three to one. Same
            # for `Chop ~|yew logs|~` against the Forestry event that reads off
            # it. Scored on the pair, not on the task name.
            seen_key = (skill, node.lower(), round(float(rate.value), 3))
            if seen_key in seen:
                continue
            seen.add(seen_key)
            family = gathering._tool_family(challenge)
            found.append(
                {
                    "skill": skill,
                    "task": task,
                    "challenge": challenge,
                    "tool": BEST_TOOLS.get(family, ""),
                    "published": rate.value,
                    "source": rate.source,
                }
            )
    return found


def _modelled(
    tables: gathering.Tables,
    families: Mapping[str, Sequence[str]],
    profile: gathering.SkillProfile,
    row: Mapping[str, Any],
) -> float | None:
    """The model's rate for one row at 99, which is what a guide describes."""
    rate = gathering.rate_at(
        tables,
        families,
        profile,
        str(row["task"]),
        str(row["skill"]),
        row["challenge"],
        99,
        tool=str(row["tool"]),
    )
    return rate.xp_per_hour if rate is not None else None


def _with(
    profile: gathering.SkillProfile, field_name: str, value: object
) -> gathering.SkillProfile:
    """`dataclasses.replace` with the field named at runtime.

    Wrapped because `replace(profile, **{name: value})` is opaque to a type
    checker - it cannot know which field is being set, so it checks the value
    against every one of them and reports a failure for each. The cast is
    honest: `FITTED` names only real fields, and a typo there is a `TypeError`
    from `replace` itself rather than a wrong number.
    """
    changed: dict[str, Any] = {field_name: value}
    return replace(profile, **changed)


def _kind_of(tables: gathering.Tables, families: Any, row: Mapping[str, Any]) -> str:
    """Which calculator loop a row belongs to, or `""`."""
    return gathering._experience_for(
        tables, families, str(row["skill"]), row["challenge"], str(row["task"])
    )[1]


def _fit_kinds(
    tables: gathering.Tables,
    families: Any,
    profile: gathering.SkillProfile,
    subject: Sequence[Mapping[str, Any]],
    grid: Sequence[float],
    score: Callable[[gathering.SkillProfile, Sequence[Any]], float],
) -> gathering.SkillProfile:
    """Fit one roll interval per `kind`, against that kind's rows alone.

    **A kind with no published rate gets no entry**, and `strict_kinds` then
    refuses it rather than lending it another loop's pace. That is the whole
    reason this is per kind: fitted as one number over Hunter's six tabulated
    methods the answer is 18 ticks, which is not any loop's interval - it is a
    box trap and a falconry catch averaged, and it prices both wrongly.
    """
    by_kind: dict[str, list[Mapping[str, Any]]] = {}
    for row in subject:
        by_kind.setdefault(_kind_of(tables, families, row), []).append(row)
    fitted = dict(profile.roll_ticks_by_kind)
    for kind, group in sorted(by_kind.items()):
        fitted[kind] = min(
            grid,
            key=lambda value: score(
                replace(profile, roll_ticks_by_kind={**fitted, kind: value}), group
            ),
        )
    return replace(profile, roll_ticks_by_kind=fitted)


def fit(map_id: str = "fray") -> None:
    """Fit each skill's free parameter and print the residuals."""
    tables = gathering.load_tables(read_gathering())
    args = argparse.Namespace(map_id=map_id, chunkinfo=None, recompute=False)
    state, _ = load_state(args)
    families = gathering.expand_families(state.chunk_info)
    rows = _targets(map_id)

    import math

    # **Every profile, not every fit.** A skill with nothing left to fit still
    # has rows to answer for, and Thieving is the case that proves it: both its
    # constants are published, so it appears in `PROFILES` and not in `FITTED`,
    # and reporting only the fitted skills would have hidden its evidence
    # exactly when it stopped being tuned.
    for skill in sorted(gathering.PROFILES):
        fields = FITTED.get(skill, ())
        subject = [row for row in rows if row["skill"] == skill]
        if not subject:
            print(f"{skill}: no trusted rows to fit against\n")
            continue
        profile = gathering.PROFILES[skill]
        base = profile

        def score(candidate: gathering.SkillProfile, over: Sequence[Any]) -> float:
            """Sum of squared log ratios - symmetric in over and under.

            **Log space, not linear.** A method the model reads 2x fast and one
            it reads 2x slow are the same size of mistake, and a plain residual
            calls the first one twice as bad while letting a 300,000/hr method
            outvote six 30,000/hr ones.
            """
            total = 0.0
            for row in over:
                got = _modelled(tables, families, candidate, row)
                if got is None or got <= 0:
                    continue
                total += math.log(got / float(row["published"])) ** 2
            return total

        # **Coordinate descent, three passes.** The fields interact only through
        # which rows they touch, so one pass is usually enough; three costs
        # nothing and makes the answer independent of the order they are listed.
        for _pass in range(3):
            for field_name, grid in fields:
                if field_name == "roll_ticks_by_kind":
                    profile = _fit_kinds(
                        tables, families, profile, subject, grid, score
                    )
                    continue
                moved = [
                    row
                    for row in subject
                    if _modelled(tables, families, profile, row)
                    != _modelled(
                        tables, families, _with(profile, field_name, grid[-1]), row
                    )
                ]
                if not moved:
                    continue
                profile = _with(
                    profile,
                    field_name,
                    min(
                        grid,
                        key=lambda value: score(_with(profile, field_name, value), moved),
                    ),
                )

        changes = ", ".join(
            f"{name}={dict(sorted(getattr(profile, name).items()))}"
            if name == "roll_ticks_by_kind"
            else f"{name} {getattr(base, name):g} -> {getattr(profile, name):g}"
            for name, _ in fields
        )
        print(f"{skill}: {changes or 'no free parameter - see the profile for why'}")
        caveat = _ROWS_NOT_COMPARABLE.get(skill)
        if caveat:
            print(f"  !! {caveat}")
        print(f"  {'task':<40}{'kind':<16}{'modelled':>10}{'published':>11}{'ratio':>8}")
        ratios: list[float] = []
        for row in sorted(subject, key=lambda entry: str(entry["task"])):
            got = _modelled(tables, families, profile, row)
            if got is None:
                continue
            ratio = got / float(row["published"])
            ratios.append(ratio)
            print(
                f"  {str(row['task'])[:39]:<40}"
                f"{_kind_of(tables, families, row)[:15]:<16}{got:>10,.0f}"
                f"{float(row['published']):>11,.0f}{ratio:>7.2f}x"
            )
        if ratios:
            ratios.sort()
            geometric = math.exp(sum(math.log(r) for r in ratios) / len(ratios))
            within = sum(1 for r in ratios if 1 / 1.25 <= r <= 1.25)
            print(
                f"  geometric mean {geometric:.2f}x, "
                f"{within}/{len(ratios)} within 1.25x either way\n"
            )


#: The nodes the wiki charts nothing for but quotes **hourly figures against
#: level** for, as `node -> (where it says so, ((level, xp/hr), ...))`.
#:
#: **A different kind of target from the one `FITTED` uses, and a much better
#: one.** `FITTED`'s rows are one published figure per method, spent to pin one
#: constant shared across a whole skill. These are a table per node: six and
#: seven rows against two free parameters, all of one method, and the two
#: parameters recovered are exactly what a `{{Skilling success chart}}` would
#: have stated had anyone drawn one.
#:
#: **The 3-tick column is refused where a page offers both.** Calcified rocks
#: are tabulated twice on the training guide, with and without tick
#: manipulation, and the second is taken - a technique this model cannot
#: represent would otherwise be absorbed into a success chance, which is the
#: same mistake as fitting granite's 87,000.
STATED_RATES: dict[str, tuple[str, tuple[tuple[int, float], ...]]] = {
    "rubium rocks": (
        "Rubium rocks#Experience rates",
        ((48, 39000), (61, 42000), (72, 46500), (80, 51000),
         (90, 52500), (97, 57000), (99, 63900)),
    ),
    "rubium deposit": (
        "Rubium deposit#Experience rates (the 97 row's low end)",
        ((75, 5000), (97, 10000)),
    ),
    # **The level attribution is this project's reading and not the page's.**
    # `Infernal shale deposit` says only "players can expect to receive 6k-9k
    # Mining experience ... per hour", with no levels against the ends, where
    # every other range this file meets names its band. Spreading it over the
    # method's own span - 78, its requirement, to 99 - is the only reading that
    # makes a range mean anything for one activity with one requirement, and a
    # 1.5x spread is what a mid-difficulty chance curve does over those
    # twenty-one levels. Two points against two parameters is exactly
    # determined, so what this buys is the shape between them.
    "infernal shale deposit": (
        "Infernal shale deposit (6k-9k, levels assumed 78 and 99)",
        ((78, 6000), (99, 9000)),
    ),
    "calcified rocks": (
        "Pay-to-play Mining training#Levels 41-99: Calcified rocks (w/o 3-tick)",
        ((50, 23500), (60, 27000), (70, 34000), (80, 39000), (90, 44000), (99, 49000)),
    ),
}


#: Published figures quoted **with the level and the tool they assume**, as
#: `node -> (where it says so, level, tool, xp/hr)`.
#:
#: **Checked, never fitted, and that is what makes them worth having.** Every
#: row in `TRUSTED_SOURCES` is a bare hourly number whose level the scrape does
#: not carry, which is the whole reason Mining's four rows read as disagreement
#: - the harness evaluates at 99 and the figures were quoted at 50. A page that
#: says "with a Dragon pickaxe and 90+ mining, players can expect approximately
#: 30,000 experience per hour" states all three, so the model can be asked the
#: same question the wiki answered.
#:
#: Nothing is tuned against these. The star's chance comes off the wiki's own
#: `{{Skilling success chart}}` and its interval off the pickaxe table, so the
#: agreement below is two published inputs meeting a published output with
#: nothing of this project's in between.
CHECKED_RATES: dict[str, tuple[str, int, str, float]] = {
    "shooting stars": (
        "Shooting Stars#Rewards", 90, "Dragon pickaxe", 30_000.0
    ),
    # Certain, endless, and priced entirely by the pickaxe table: 5 experience
    # every 2.83 ticks. Nothing about this figure was chosen.
    "salt deposit": ("reported in-game", 99, "Dragon pickaxe", 10_600.0),
}


#: Nodes with **one** published rate and no chart, as
#: `node -> (where it says so, level, tool, xp/hr)`.
#:
#: **One parameter against one observation, which is the weakest shape in this
#: file and is labelled as such.** A chart or a table of rates supports a
#: curve; a single figure supports a single flat chance, and `fixed_chances`
#: carries it as `INFERRED`. Reading a slope into one point would be inventing
#: the part nobody measured.
STATED_CHANCES: dict[str, tuple[str, int, str, float]] = {
    "ancient essence crystals": (
        "Ancient essence crystals", 90, "Crystal pickaxe", 10_000.0
    ),
}


def fit_stated_chances(map_id: str = "fray", skill: str = "Mining") -> None:
    """Recover one flat success chance from one published hourly figure.

    Fitted through `rate_at` for the reason `fit_stated_curves` gives at
    length: the hand-derived version of the entry below came out 14% fast the
    moment the node became `endless` and stopped paying a hop.
    """
    tables = gathering.load_tables(read_gathering())
    args = argparse.Namespace(map_id=map_id, chunkinfo=None, recompute=False)
    state, _unlocked = load_state(args)
    families = gathering.expand_families(state.chunk_info)
    base = gathering.PROFILES[skill]
    challenges = state.chunk_info.challenges.get(skill) or {}

    for node, (source, level, tool, published) in sorted(STATED_CHANCES.items()):
        task, challenge = _task_for(gathering, families, challenges, skill, node)
        if challenge is None:
            print(f"{node}: no challenge in this map names it\n")
            continue

        def modelled(chance: float) -> float:
            candidate = replace(
                base,
                fixed_chances={**base.fixed_chances, node: (chance, gathering.INFERRED)},
            )
            rate = gathering.rate_at(
                tables, families, candidate, task, skill, challenge, level, tool=tool
            )
            return 0.0 if rate is None else rate.xp_per_hour

        best = min(
            ((abs(math.log(got / published)), chance)
             for step in range(1, 1000)
             if (got := modelled(chance := step / 1000.0)) > 0),
            key=lambda found: found[0],
        )
        chance = best[1]
        got = modelled(chance)
        print(
            f"{node}: chance {chance}   modelled {got:,.0f} against "
            f"{published:,.0f} at level {level} ({tool}, {source})   "
            f"{got / published:.2f}x\n"
        )


def check_stated_rates(map_id: str = "fray", skill: str = "Mining") -> None:
    """Ask the model the question a page already answered."""
    tables = gathering.load_tables(read_gathering())
    args = argparse.Namespace(map_id=map_id, chunkinfo=None, recompute=False)
    state, _unlocked = load_state(args)
    families = gathering.expand_families(state.chunk_info)
    profile = gathering.PROFILES[skill]
    challenges = state.chunk_info.challenges.get(skill) or {}

    print(f"  {'node':<20}{'level':>6}{'modelled':>11}{'published':>11}{'ratio':>8}")
    for node, (source, level, tool, published) in sorted(CHECKED_RATES.items()):
        task, challenge = _task_for(gathering, families, challenges, skill, node)
        if challenge is None:
            print(f"  {node:<20} no challenge in this map names it")
            continue
        rate = gathering.rate_at(
            tables, families, profile, task, skill, challenge, level, tool=tool
        )
        if rate is None:
            print(f"  {node:<20} refused")
            continue
        print(
            f"  {node:<20}{level:>6}{rate.xp_per_hour:>11,.0f}{published:>11,.0f}"
            f"{rate.xp_per_hour / published:>7.2f}x   ({tool}, {source})"
        )
    print()


def fit_stated_curves(map_id: str = "fray", skill: str = "Mining") -> None:
    """Recover a success curve from a table of published hourly rates.

    **Fitted *through* `rate_at`, never through a copy of its arithmetic**, and
    that is the whole design of this function rather than an implementation
    detail. The first version of these two curves was fitted against a
    hand-written `xp * 3600 / (roll / chance + hop)`, which was the model at the
    time; giving calcified rocks a duty cycle then removed the hop, and the
    curve fitted against the old expression read 1.22x fast at every level
    while looking perfectly converged. A fit against a paraphrase of the model
    measures the paraphrase.

    Two passes: a whole-number sweep, then half-steps around what it found.
    """
    tables = gathering.load_tables(read_gathering())
    args = argparse.Namespace(map_id=map_id, chunkinfo=None, recompute=False)
    state, _unlocked = load_state(args)
    families = gathering.expand_families(state.chunk_info)
    base = gathering.PROFILES[skill]
    challenges = state.chunk_info.challenges.get(skill) or {}

    for node, (source, points) in sorted(STATED_RATES.items()):
        task, challenge = _task_for(gathering, families, challenges, skill, node)
        if challenge is None:
            print(f"{node}: no challenge in this map names it\n")
            continue
        tool = BEST_TOOLS.get(gathering._tool_family(challenge), "")

        def score(low: float, high: float) -> float:
            candidate = replace(base, stated_curves={**base.stated_curves, node: (low, high)})
            total = 0.0
            for level, published in points:
                rate = gathering.rate_at(
                    tables, families, candidate, task, skill, challenge, level, tool=tool
                )
                if rate is None or rate.xp_per_hour <= 0:
                    return float("inf")
                total += math.log(rate.xp_per_hour / published) ** 2
            return total

        best = min(
            ((score(float(low), float(high)), float(low), float(high))
             for low in range(-100, 200, 2)
             for high in range(2, 300, 2)),
            key=lambda found: found[0],
        )
        best = min(
            ((score(best[1] + dl / 2, best[2] + dh / 2), best[1] + dl / 2, best[2] + dh / 2)
             for dl in range(-4, 5)
             for dh in range(-4, 5)),
            key=lambda found: found[0],
        )
        _, low, high = best
        print(f"{node}: low {low}, high {high}   (target: {source})")
        print(f"  {'level':<8}{'chance':>8}{'modelled':>11}{'published':>11}{'ratio':>8}")
        candidate = replace(base, stated_curves={**base.stated_curves, node: (low, high)})
        ratios = []
        for level, published in points:
            rate = gathering.rate_at(
                tables, families, candidate, task, skill, challenge, level, tool=tool
            )
            if rate is None:
                continue
            ratios.append(rate.xp_per_hour / published)
            print(
                f"  {level:<8}{rate.chance:>8.3f}{rate.xp_per_hour:>11,.0f}"
                f"{published:>11,.0f}{ratios[-1]:>7.2f}x"
            )
        if ratios:
            geometric = math.exp(sum(math.log(r) for r in ratios) / len(ratios))
            within = sum(1 for r in ratios if 1 / 1.25 <= r <= 1.25)
            print(f"  geometric mean {geometric:.3f}, {within}/{len(ratios)} within 1.25x\n")


def _task_for(
    module: Any,
    families: Mapping[str, Sequence[str]],
    challenges: Mapping[str, Any],
    skill: str,
    node: str,
) -> tuple[str, Mapping[str, Any] | None]:
    """The primary challenge whose join keys reach `node`."""
    for task, challenge in sorted(challenges.items()):
        if not isinstance(challenge, dict) or challenge.get("Primary") is not True:
            continue
        keys = module._join_keys(challenge, families, module._NAME_FIELDS, skill, task)
        if any(key.lower() == node for key in keys):
            return task, challenge
    return "", None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", default="fray", help="which cached map to fit against")
    parser.add_argument(
        "--stated-curves",
        action="store_true",
        help="fit STATED_RATES instead: a success curve out of published hourly figures",
    )
    args = parser.parse_args()
    if args.stated_curves:
        check_stated_rates(args.map)
        fit_stated_curves(args.map)
        fit_stated_chances(args.map)
    else:
        fit(args.map)


if __name__ == "__main__":
    main()
