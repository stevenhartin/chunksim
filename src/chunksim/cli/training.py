"""`chunksim training`: what can train each skill, and what priced it.

Three questions, and which one is asked comes from the arguments:

    chunksim training                 every primary method in the export, by status
    chunksim training --map fray      the best method for each skill on that map
    chunksim training Agility --map fray   every Agility method it can reach

**The no-map report is about the *project*, not about a world.** It answers
"what has been modelled and what is still unpriced", which is a question about
this code rather than about anybody's chunks. What it needs a world for is that
every computed layer is a function of one: a recipe's inputs have to be
reachable, a gathering curve needs a tool, a lectern needs to be buildable.

So it builds the ceiling the GUI already calls the uber map - **every rollable
chunk, on a cached map's own rules** - and reports what that can price.
Rollable is `chunkinfo['sections']` rather than `chunkinfo['chunks']`, for the
reason `gui/actions._uber_map` gives: the other 1,062 are unwalkable squares
and named areas a roll can never land on.

**The rules have to come from a real map, and that is not a shortcut.** A rule
is a *player's* choice and the export has no permissive defaults to borrow:
seeded with `model/rules.default_rules` the state derives 4,932 valid challenges
where a real map's rules give 10,111, because most defaults are `False` and a
`False` rule *refuses* its gate. Leaving the branch out entirely is more
permissive still for refusal-gates (9,273) and stays wrong for the ones that
*widen* - `Boosting` is the example, and Construction reads 566 unpriced there
against 83 on a real ceiling. Setting every rule `True` is refused outright by
`derive`, which has an unported `KeyItem Bosses` pass. So the base map is asked
for its rules and nothing else, and the report says which map it borrowed.

With no cached map at all there is nothing to borrow and the rules-free state is
used, with a warning: the counts are then a floor on what is modelled rather
than a reading of it.

The rendering is here and the assembly is `costing/inputs.py`', shared with the
GUI's methods overlay - so the row a reader sees in one cannot rank differently
from the row they see in the other.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from chunksim.cli.common import (
    MapAmbiguityError,
    derive_cached,
    digests,
    emit_json,
    load_state,
    resolve_map,
)
from chunksim.costing import coverage, inputs
from chunksim.costing.training import TrainingOption
from chunksim.derive import pipeline
from chunksim.derive.task_names import strip_task_markup
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.store import cache
from chunksim.store.derived_cache import Digests

#: What a status is called on screen, and the order they are counted in -
#: worst first, because the tail is the work left to do.
STATUS_LABELS: dict[str, str] = {
    "unpriced": "unpriced",
    "guess": "guessed",
    "published": "published",
    "pinned": "hand-pinned",
    "modelled": "modelled",
}


def _cmd_training(args: argparse.Namespace) -> int:
    if args.map_id is None:
        return _report_export(args)
    return _report_map(args)


def _report_export(args: argparse.Namespace) -> int:
    """Every primary method in the export, priced against the ceiling."""
    info = ChunkInfo(cache.read_chunkinfo(override=args.chunkinfo))
    base, payload = _ceiling_payload(info, args)
    state, unlocked = pipeline.load_map_state(payload, info, {})
    derived = pipeline.derive(state, unlocked)
    statuses = inputs.training_statuses(
        state, unlocked, derived, Digests(chunkinfo="training"), valid=False
    )
    if args.export_json is not None:
        emit_json(
            {
                "scope": "export",
                "rules_from": base,
                "skills": {
                    skill: [row.as_dict() for row in rows] for skill, rows in statuses.items()
                },
            },
            args.export_json,
        )
        if args.export_json == "-":
            return 0

    rows = [row for skill_rows in statuses.values() for row in skill_rows]
    print("scope        the whole export, against every rollable chunk")
    if base:
        print(f"rules        {base}'s, since a rule is a player's choice")
    else:
        print(
            "rules        none cached, so none applied - these counts are a floor"
            " on what is modelled rather than a reading of it"
        )
    print(f"methods      {len(rows):,} primary training methods\n")
    _print_status_table(statuses)
    if args.skill:
        _print_skill_statuses(statuses.get(args.skill) or (), args.skill, args.limit)
    return 0


def _ceiling_payload(
    info: ChunkInfo, args: argparse.Namespace
) -> tuple[str, dict[str, object]]:
    """`(base map or "", the payload to derive)` for the export-wide report.

    The base map is asked for its `rules` branch and its progress and nothing
    else - the chunks are replaced wholesale. See the module docstring for why
    borrowing them beats any default this could invent.
    """
    unlocked = dict.fromkeys(info.sections, True)
    base = args.rules_from
    if base is None:
        try:
            base = resolve_map(None)
        except MapAmbiguityError:
            # **Several cached maps and no way to choose.** Their rules differ
            # - 41 of one real map's 104 are off - so picking one silently
            # would make the report depend on cache order. Name the flag.
            print(
                "note         several maps are cached; pass --rules-from MAP to borrow"
                " one's rules"
            )
            return "", {"chunks": {"unlocked": unlocked}}
    try:
        data = dict(cache.read_cache(base)["data"])
    except cache.CacheMissError:
        return "", {"chunks": {"unlocked": unlocked}}
    data["chunks"] = {**(data.get("chunks") or {}), "unlocked": unlocked}
    return base, data


def _print_status_table(statuses: dict[str, tuple[coverage.MethodStatus, ...]]) -> None:
    """One row a skill, one column a status."""
    order = list(reversed(coverage.STATUSES))
    head = "".join(f"{STATUS_LABELS[name]:>12}" for name in order)
    print(f"{'skill':<14}{head}{'total':>9}")
    totals = dict.fromkeys(order, 0)
    for skill, rows in sorted(statuses.items()):
        if not rows:
            continue
        counts = {name: sum(1 for row in rows if row.status == name) for name in order}
        for name in order:
            totals[name] += counts[name]
        cells = "".join(f"{counts[name] or '':>12}" for name in order)
        print(f"{skill:<14}{cells}{len(rows):>9,}")
    cells = "".join(f"{totals[name]:>12,}" for name in order)
    print(f"{'all':<14}{cells}{sum(totals.values()):>9,}")


def _print_skill_statuses(
    rows: tuple[coverage.MethodStatus, ...], skill: str, limit: int | None
) -> None:
    print(f"\n{skill} — {len(rows):,} primary methods, worst first")
    for row in rows[: limit or len(rows)]:
        # **No rate beside an unpriced method.** What `heuristics.xp_per_hour`
        # returns there is `DEFAULT_XP_PER_HOUR`, and printing the floor in a
        # column headed by a rate is how a placeholder gets read as a number.
        rate = f"{row.xp_per_hour:>10,.0f}/hr" if row.status != "unpriced" else " " * 14
        level = f"lvl {row.level}" if row.level else ""
        source = row.source if row.status != "unpriced" else ""
        # **The whole task, not `activity_name`.** The verb is what tells six
        # Herblore unlocks apart; stripped, they all read `Herblore`.
        print(
            f"  {STATUS_LABELS[row.status]:<11} {rate}  {level:<8}"
            f" {strip_task_markup(row.task)}{'  ' + source if source else ''}"
        )


def _report_map(args: argparse.Namespace) -> int:
    state, unlocked = load_state(args)
    known = digests(args)
    derived = derive_cached(args, state, unlocked, known)
    answer = inputs.training_answer(
        state,
        unlocked,
        derived,
        known,
        skill=args.skill,
        refresh=args.recompute,
        map_id=args.map_id,
    )
    if args.export_json is not None:
        emit_json(answer.as_dict(args.map_id), args.export_json)
        if args.export_json == "-":
            return 0

    print(f"map          {args.map_id}")
    if args.skill:
        return _print_skill_methods(answer, args.skill, args.limit)
    print(f"{'skill':<14}{'lvl':>4}  {'rate':>12}  {'source':<22} method")
    for skill, option in sorted(answer.best.items()):
        if option is None:
            continue
        print(
            f"{skill:<14}{answer.levels.get(skill, 1):>4}"
            f"  {option.effective_xp_per_hour:>10,.0f}/hr"
            f"  {_provenance(option):<22} {option.method}"
        )
    missing = [skill for skill, option in sorted(answer.best.items()) if option is None]
    if missing:
        print(f"\nno reachable method: {', '.join(missing)}")
    return 0


def _print_skill_methods(
    answer: inputs.TrainingAnswer, skill: str, limit: int | None
) -> int:
    options = answer.methods.get(skill) or ()
    if not options:
        print(f"\n{skill}: no reachable method with a real rate")
        return 0
    at = answer.levels.get(skill, 1)
    print(f"{'skill':<14}{skill} (level {at})")
    print(f"\n{len(options):,} reachable method{'' if len(options) == 1 else 's'}, best first")
    print(f"  {'rate':>12}  {'headline':>12}  {'lvl':>4}  {'source':<22} method")
    for option in options[: limit or len(options)]:
        # **A method above the level is still listed and marked.** It is the
        # answer to "what am I working towards" and leaving it out would make
        # the list disagree with the climb the estimate prints.
        gate = " " if option.level is None or option.level <= at else "*"
        headline = (
            f"{option.xp_per_hour:>10,.0f}/hr"
            if abs(option.xp_per_hour - option.effective_xp_per_hour) > 1
            else " " * 14
        )
        print(
            f" {gate}{option.effective_xp_per_hour:>10,.0f}/hr  {headline}"
            f"  {option.level if option.level else '':>4}"
            f"  {_provenance(option):<22} {option.method}"
        )
    if any(option.level and option.level > at for option in options):
        print("\n  * above this map's level for the skill")
    if any(abs(o.xp_per_hour - o.effective_xp_per_hour) > 1 for o in options):
        print(
            "  the headline column is the rate before what the method consumes is"
            " charged; the first column is what it is worth here"
        )
    return 0


def _provenance(option: TrainingOption) -> str:
    """`modelled` and what modelled it, or the guide's own name."""
    status = coverage.status_of(option.match)
    if option.source:
        return f"{status}:{option.source}"[:22]
    return status


def add_arguments(
    subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """This family's subcommands and their flags."""
    training = subcommands.add_parser(
        "training",
        help="what can train each skill, and what priced it",
        description=(
            "With no --map: every primary training method in the export, counted by "
            "what priced it, against a state holding every rollable chunk. With "
            "--map: the best method for each skill on that map, or every method for "
            "one SKILL."
        ),
    )
    training.add_argument(
        "skill",
        nargs="?",
        default=None,
        metavar="SKILL",
        help="drill into one skill",
    )
    training.add_argument(
        "--limit", type=int, default=None, help="cap the methods listed for SKILL"
    )
    training.add_argument(
        "--map",
        dest="map_id",
        default=None,
        help="map id; omitted, the report is about the export rather than a map",
    )
    training.add_argument(
        "--rules-from",
        metavar="MAP",
        default=None,
        help=(
            "with no --map: borrow this cached map's rules for the export-wide report."
            " A rule is a player's choice and the export has no permissive defaults"
        ),
    )
    training.add_argument(
        "--chunkinfo",
        type=Path,
        default=None,
        help="path to a chunkinfo export, overriding the cache and CHUNKSIM_CHUNKINFO",
    )
    training.add_argument(
        "--export-json",
        metavar="PATH",
        default=None,
        help="write the full result as JSON to PATH, or to stdout if PATH is '-'",
    )
    training.add_argument(
        "--recompute",
        action="store_true",
        help="ignore any cached derivation and compute (and re-store) a fresh one",
    )
    # **Omitting `--map` is a different question, not a defaulted one.** See
    # `cli/app.main`, which infers the sole cached map for every other family.
    training.set_defaults(func=_cmd_training, infer_map=False)
