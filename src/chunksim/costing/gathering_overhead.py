"""Fitting the four constants `costing/gathering.py` cannot read off a page.

**No caller in `src/`.** Like `recipe_overhead.py` and `dps_overhead.py`, this
exists to be re-run when someone doubts a number in `gathering.PROFILES` - run
it, read what it says, and change the profile if the fit has moved.

    .venv/bin/python -m chunksim.costing.gathering_overhead

**Three of the model's inputs are published and one is not.** A success curve, a
roll interval and a tree's despawn/respawn are all on the wiki and are read by
`remote/gathering.py`. What is nowhere - not on the skill page, not in the
scenery infobox, not in any Module - is what a *rock* costs you between ores, or
a normal tree between logs, or a failed pickpocket in stun time. Those are
fitted here against the rates the wiki does publish.

**What it is fitted against matters more than how.** The targets are the wiki's
own training-guide figures, joined *exactly*, and nothing else:
`remote/skill_tables.py`'s Woodcutting, Mining and pickpocket tables. Money
making guides are deliberately excluded and it is not fastidiousness - a
`Money making guide/Catching lobsters` figure is about profit, so it is quoted
with a bank run inside it that this model does not charge, and fitting to it
would fold somebody's banking into a constant that means "node downtime".
Measured, the mmg rows disagree with the model 2.5x where the exact rows agree
within 1.1x, and letting them into the fit moves every constant the wrong way.

**One free parameter per skill, fitted on a grid.** There is not enough data for
anything cleverer - eight woodcutting rows, five pickpocket rows, four mining
rows - and a one-parameter fit over eight points is already the shape this
project distrusts, which is why the residuals are printed per row rather than
summarised. Read them: a constant that fits six rows and misses two badly is
telling you the two are a different mechanic, not that the constant is wrong.
"""

from __future__ import annotations

import argparse
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

#: Roll intervals are searched in half ticks up to thirty, which covers
#: everything from a two-tick pickpocket to a box trap you come back to.
_TICK_GRID: tuple[float, ...] = tuple(x / 2 for x in range(2, 61))

#: Which profile fields each skill's fit moves, and the grid to search each on.
#: **A field is fitted only against the rows it actually changes**, which the
#: harness works out by varying it - so a tree the wiki tabulates a cycle for
#: never votes on `node_seconds`, and one it does not never votes on
#: `nodes_worked`. Without that the two fight over every row and neither lands.
FITTED: dict[str, tuple[tuple[str, tuple[float, ...]], ...]] = {
    # **`roll_ticks` is not fitted here and must not be.** The Woodcutting page
    # states four ticks outright, so it is data like the success curve is; left
    # free the fit pulls it to 2.5 to absorb the spread between oak and willow,
    # which trades a published mechanic for noise and makes every other
    # constant meaningless.
    "Woodcutting": (
        ("nodes_worked", tuple(x / 2 for x in range(2, 21))),
        ("node_seconds", tuple(x / 10 for x in range(0, 301))),
    ),
    "Mining": (("node_seconds", tuple(x / 10 for x in range(0, 301))),),
    # **Per loop, not per skill.** `roll_ticks_by_kind` is fitted one `kind` at
    # a time against the rows of that kind alone - see `_fit_kinds`.
    # **The interval is pinned, the banking is fitted.** Net, bait, harpoon and
    # cage fishing all roll every 5 ticks; left free the fit pulls the interval
    # to 7.5 instead, which is not a mechanic - it is 5 ticks with the guide's
    # bank run folded into it, the same contamination `mmg:` rows carry.
    "Fishing": (("bank_seconds", tuple(float(x) for x in range(0, 241))),),
    "Hunter": (("roll_ticks_by_kind", _TICK_GRID),),
    "Thieving": (("roll_ticks_by_kind", _TICK_GRID),),
    # Nothing to fit: the model's answer for these is checked, not tuned.
}
#: Skills whose profile the fit leaves alone entirely.
_UNFITTED: tuple[str, ...] = ()


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

    found: list[dict[str, Any]] = []
    for skill in sorted(gathering.PROFILES):
        challenges = state.chunk_info.challenges.get(skill) or {}
        for task, challenge in sorted(challenges.items()):
            if not isinstance(challenge, dict) or challenge.get("Primary") is not True:
                continue
            rate = heuristics.training.get(task, {}).get(skill)
            if rate is None or not rate.source.startswith(TRUSTED_SOURCES):
                continue
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

    for skill, fields in sorted(FITTED.items()):
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
        print(f"{skill}: {changes}")
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", default="fray", help="which cached map to fit against")
    fit(parser.parse_args().map)


if __name__ == "__main__":
    main()
