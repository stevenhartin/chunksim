"""`chunksim training`: what can train each skill, and what priced it.

Three questions, and which one is asked comes from the arguments:

    chunksim training                 every primary method in the export, by status
    chunksim training --map fray      the best method for each skill on that map
    chunksim training Agility --map fray   every Agility method it can reach

The status table's counts provoke a follow-up - *which* methods are those? -
and `--show-category` answers it, for one skill or across all of them:

    chunksim training --rules-from fray --show-category unpriced Construction
    chunksim training --rules-from fray --show-category unpriced --limit 3

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
from collections import Counter
from pathlib import Path

from chunksim.cli.common import (
    MapAmbiguityError,
    derive_cached,
    digests,
    emit_json,
    load_state,
    resolve_map,
)
from chunksim.costing import coverage, inputs, oneoff
from chunksim.costing.training import TrainingOption
from chunksim.derive import pipeline
from chunksim.derive.task_names import strip_task_markup
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.store import cache

#: What a status is called on screen, and the order they are counted in -
#: worst first, because the tail is the work left to do.
STATUS_LABELS: dict[str, str] = {
    "uncompletable": "uncompletable",
    "unreachable": "unreachable",
    "one-off": "one-off",
    "unpriced": "unpriced",
    "guess": "guessed",
    "published": "published",
    "pinned": "hand-pinned",
    "modelled": "modelled",
}

#: Statuses whose rate is not a number the estimator would ever spend, so the
#: listing leaves the column blank rather than printing a leftover.
#: `unpriced` shows `DEFAULT_XP_PER_HOUR`, the floor, and `unreachable` shows
#: whatever the raw scrape left behind for a challenge nothing was asked
#: about - printing either under a heading that says "rate" is how a
#: placeholder gets read as a measurement.
QUIET_STATUSES = frozenset({"unpriced", "unreachable", "uncompletable", "one-off"})

#: What each `coverage.BLOCKERS` kind reads as. Printed in `BLOCKERS` order,
#: which puts the volume first and `unstated` last - and **`unstated` is the
#: one to chase**: it is the only kind that names nothing at all, so it is a
#: rule, a `Category` gate or a defect here rather than a fact about the game.
BLOCKER_LABELS: dict[str, str] = {
    "rule": "a rule the base map has switched off — a player's choice",
    "superseded": "upstream's own fallback form of a challenge that is valid",
    "npc": "an NPC or monster nothing in the world provides",
    "unstated": "no stated requirement — worth chasing",
    "task": "a quest or task the ceiling cannot finish",
    "item": "an item nothing in the world provides",
    "object": "an object nothing in the world provides",
    "location": "a chunk or section outside the rollable set",
}


def _cmd_training(args: argparse.Namespace) -> int:
    # **Both names are matched case-insensitively, and a miss is an error.**
    # Both used to be looked up with `.get`, so `training construcion` and
    # `--show-category unpricd` each printed an empty section and exit 0 -
    # a typo reading as "nothing here", which is a real answer this report
    # gives for other reasons.
    try:
        args.skill = _resolve(args.skill, coverage.SKILLS, "skill")
        args.show_category = _resolve(args.show_category, _CATEGORIES, "category")
    except ValueError as error:
        print(error)
        return 2
    if args.show_category and args.map_id is not None:
        # The `--map` report is `TrainingAnswer` - best-per-skill and one
        # skill's priced methods - and carries no statuses to filter by.
        print(
            "--show-category describes the export-wide report, so it cannot be"
            " combined with --map; drop --map (optionally with --rules-from MAP)"
        )
        return 2
    if args.map_id is None:
        return _report_export(args)
    return _report_map(args)


#: What `--show-category` accepts, mapping every spelling a reader might copy
#: to the status itself. The table prints `STATUS_LABELS`, so `guessed` and
#: `hand-pinned` have to be accepted beside `guess` and `pinned` - a flag that
#: rejects the word printed in the column it filters is a trap.
_CATEGORIES: dict[str, str] = {
    **{status: status for status in coverage.STATUSES},
    **{label: status for status, label in STATUS_LABELS.items()},
}


def _resolve(
    given: str | None, allowed: dict[str, str] | tuple[str, ...], what: str
) -> str | None:
    """`given` matched case-insensitively against `allowed`, or `None`.

    Raises `ValueError` naming the valid values, which the caller prints -
    argparse `choices` would do this too, but only for the flag, and the
    positional skill needs the same treatment.
    """
    if given is None:
        return None
    folded = {
        name.lower(): (allowed[name] if isinstance(allowed, dict) else name)
        for name in allowed
    }
    found = folded.get(given.strip().lower())
    if found is None:
        raise ValueError(
            f"unknown {what} {given!r}; choose one of: "
            + ", ".join(sorted(set(folded.values())))
        )
    return found


def _report_export(args: argparse.Namespace) -> int:
    """Every primary method in the export, priced against the ceiling."""
    info = ChunkInfo(cache.read_chunkinfo(override=args.chunkinfo))
    base, payload, why = _ceiling_payload(info, args)
    state, unlocked = pipeline.load_map_state(payload, info, {})
    # **Cached derivation and real digests, like every other subcommand.**
    # The ceiling state is the biggest derivation there is (~4.3s), and the
    # first version of this called `pipeline.derive` directly - so the one
    # command whose derive is most worth caching was the one that never did,
    # and every invocation paid it again. The digests must be the real file
    # hashes for the same reason `derive_cached` insists on them everywhere:
    # a placeholder here served a stale pricing across an export refetch.
    known = digests(args)
    derived = derive_cached(args, state, unlocked, known)
    statuses = inputs.training_statuses(state, unlocked, derived, known, valid=False)
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
    print(
        "note         `uncompletable` means the ceiling itself cannot do it, so no"
        " layer was ever asked - see the breakdown below"
    )
    if base:
        print(f"rules        {base}'s, since a rule is a player's choice")
    else:
        # **A rules-less world is not a smaller version of a real one.** Every
        # rule-gated challenge fails a gate `coverage.blocker_for` cannot name
        # - there is no rules branch for it to point at - so they land in the
        # `unstated` bucket the docstring elsewhere insists is empty: 866 of
        # them against zero once any map's rules are borrowed. Say so, rather
        # than letting a reader take the `unpriced` column for the real count.
        print(
            "rules        "
            + (
                "several maps are cached and none was chosen - pass --rules-from MAP"
                if why == "ambiguous"
                else "no map cached to borrow any from - run: chunksim fetch --map ID"
            )
        )
        print(
            "warning      with no rules every rule-gated method reads as"
            " uncompletable, so `unpriced` here is far below the real count"
        )
    print(f"methods      {len(rows):,} primary training methods\n")
    _print_status_table(statuses)
    _print_blockers(statuses)
    if args.skill:
        _print_skill_statuses(
            statuses.get(args.skill) or (), args.skill, args.limit, args.show_category
        )
    elif args.show_category:
        _print_category(statuses, args.show_category, args.limit)
    return 0


def _print_blockers(statuses: dict[str, tuple[coverage.MethodStatus, ...]]) -> None:
    """Why the uncompletable ones are uncompletable.

    **A count on its own is not actionable and this is the whole point of the
    category.** "307 uncompletable" reads as a number to be worried about;
    split by the requirement that blocked each one it reads as 134 items the
    world does not contain, 108 quest gates, and a residue worth looking at.
    """
    blocked = [
        row
        for rows in statuses.values()
        for row in rows
        if row.status == "uncompletable"
    ]
    if not blocked:
        return
    counts = Counter(row.blocker for row in blocked)
    print(f"\nuncompletable — {len(blocked):,}, by what upstream asks for and the world lacks")
    for kind in coverage.BLOCKERS:
        if not counts[kind]:
            continue
        print(f"  {counts[kind]:>5}  {BLOCKER_LABELS[kind]}")
        # One example, because the label says the shape and a name says the
        # case: `Trailblazer rug` reads as a Leagues reward at a glance.
        example = next(row for row in blocked if row.blocker == kind)
        named = (
            f" ({strip_task_markup(example.blocked_by)})" if example.blocked_by else ""
        )
        print(f"         e.g. {strip_task_markup(example.task)}{named}")


def _ceiling_payload(
    info: ChunkInfo, args: argparse.Namespace
) -> tuple[str, dict[str, object], str]:
    """`(base map or "", payload to derive, why there is no base)`.

    The base map is asked for its `rules` branch and its progress and nothing
    else - the chunks are replaced wholesale. See the module docstring for why
    borrowing them beats any default this could invent.

    **The third element exists because "no rules" has two causes and they read
    completely differently.** A checkout with nothing fetched has no rules to
    borrow; a checkout with several maps has plenty and no way to choose
    between them. Both used to return `""` and be reported as "none cached",
    which contradicted the note printed directly above it in the ambiguous
    case and read as "there is nothing to borrow" when the fix was one flag.
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
            #
            # `resolve_map` raises the same error for an *empty* cache, which
            # is the opposite situation and the opposite advice, so the count
            # is read here rather than inferred from the exception.
            fetched = [entry for entry in cache.list_maps() if entry.kind == cache.FETCHED]
            return (
                "",
                {"chunks": {"unlocked": unlocked}},
                "ambiguous" if fetched else "missing",
            )
    try:
        data = dict(cache.read_cache(base)["data"])
    except cache.CacheMissError:
        return "", {"chunks": {"unlocked": unlocked}}, "missing"
    data["chunks"] = {**(data.get("chunks") or {}), "unlocked": unlocked}
    return base, data, ""


def _print_status_table(statuses: dict[str, tuple[coverage.MethodStatus, ...]]) -> None:
    """One row a skill, one column a status."""
    counted = {
        skill: Counter(row.status for row in rows)
        for skill, rows in sorted(statuses.items())
        if rows
    }
    # **Only the columns that happen.** The two absent statuses are exclusive
    # by construction - a report is about one world, so it says `unreachable`
    # or `uncompletable` and never both - and an always-empty column is a
    # heading you go looking for a number under and never find.
    order = [
        name
        for name in reversed(coverage.STATUSES)
        if any(counts[name] for counts in counted.values())
    ]
    width = max(14, *(len(STATUS_LABELS[name]) + 2 for name in order))
    head = "".join(f"{STATUS_LABELS[name]:>{width}}" for name in order)
    print(f"{'skill':<14}{head}{'total':>9}")
    totals: Counter[str] = Counter()
    for skill, counts in counted.items():
        totals.update(counts)
        cells = "".join(f"{counts[name] or '':>{width}}" for name in order)
        print(f"{skill:<14}{cells}{sum(counts.values()):>9,}")
    cells = "".join(f"{totals[name]:>{width},}" for name in order)
    print(f"{'all':<14}{cells}{sum(totals.values()):>9,}")


def _print_category(
    statuses: dict[str, tuple[coverage.MethodStatus, ...]],
    status: str,
    limit: int | None,
) -> None:
    """Every method of one status, across every skill, grouped by skill.

    The whole-export answer to "what is still unpriced", where
    `_print_skill_statuses` answers it for one skill. Skills with none are
    left out rather than printed empty - the point of asking is the list.
    """
    found = {
        skill: [row for row in rows if row.status == status]
        for skill, rows in sorted(statuses.items())
    }
    found = {skill: rows for skill, rows in found.items() if rows}
    total = sum(len(rows) for rows in found.values())
    print(f"\n{STATUS_LABELS[status]} — {total:,} across {len(found)} skill(s)")
    for skill, rows in found.items():
        print(f"\n  {skill} ({len(rows):,})")
        for row in rows[: limit or len(rows)]:
            _print_status_row(row, indent="    ")
        if limit is not None and len(rows) > limit:
            print(f"    … {len(rows) - limit:,} more")


def _print_skill_statuses(
    rows: tuple[coverage.MethodStatus, ...],
    skill: str,
    limit: int | None,
    status: str | None = None,
) -> None:
    if status is not None:
        rows = tuple(row for row in rows if row.status == status)
        print(f"\n{skill} — {len(rows):,} {STATUS_LABELS[status]} primary methods")
    else:
        print(f"\n{skill} — {len(rows):,} primary methods, worst first")
    for row in rows[: limit or len(rows)]:
        _print_status_row(row)
    if limit is not None and len(rows) > limit:
        print(f"  … {len(rows) - limit:,} more")


def _print_status_row(row: coverage.MethodStatus, indent: str = "  ") -> None:
    """One method's line, shared by the per-skill and per-category listings."""
    # **No rate beside an unpriced method.** What `heuristics.xp_per_hour`
    # returns there is `DEFAULT_XP_PER_HOUR`, and printing the floor in a
    # column headed by a rate is how a placeholder gets read as a number.
    quiet = row.status in QUIET_STATUSES
    rate = " " * 14 if quiet else f"{row.xp_per_hour:>10,.0f}/hr"
    level = f"lvl {row.level}" if row.level else ""
    # A blocked row says what blocked it where a priced one says what
    # priced it: both answer "why is this number what it is".
    source = row.source
    if quiet:
        source = f"needs {row.blocked_by}" if row.blocked_by else ""
    # A one-off says *why* it is not a training method, which is the whole
    # content of the status - see `costing/oneoff.py`.
    if row.status == coverage.ONE_OFF:
        source = oneoff.reason(row.task)
    # **The whole task, not `activity_name`.** The verb is what tells six
    # Herblore unlocks apart; stripped, they all read `Herblore`.
    print(
        f"{indent}{STATUS_LABELS[row.status]:<11} {rate}  {level:<8}"
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
        "--show-category",
        metavar="STATUS",
        default=None,
        help=(
            "list the methods of one status - "
            + ", ".join(coverage.STATUSES)
            + ". With SKILL, that skill's; without, every skill's, grouped."
            " Export-wide report only, so not with --map"
        ),
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
