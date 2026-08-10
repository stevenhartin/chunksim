"""`sections`, `sources` and `tasks`: what the unlocked chunks actually hold.

Each takes an optional positional - `list` or a chunk id; one of
`sources.CATEGORIES`; a challenge category - to list that branch's contents
instead of its counts.

**`fray tasks <category>` branches four ways**, which is most of this module:

- `Diary`/`Quest`/`Other` (or `Extra`; both accepted case-insensitively and
  displayed `Other (Extra)`) list `derived.other_tasks` grouped under headers,
  showing each task's `Description` where the export has one.
- `BiS` lists `derived.bis.active`/`completed`/`outdated`. BiS is not a
  category in `chunk_info.challenges` at all - see `derive/challenges.py` - so
  it renders through `BisResult.display_sorted` rather than as raw names, and
  lines read `[<slot>] Obtain a granite ring (i)` with this chunk's
  completions floated to the top. The raw `~|...|~` names stay the keys in
  `--export-json`.
- A real skill category shows **active -> completed -> obsolete**, plus an
  opportunistic comparison against `state.active_tasks[skill]` ("not cached"
  when absent, which is the common case - see `derive/active_tasks.py`).
- Anything else keeps the flat valid listing.

Every path renders through `render.display_tasks`, which **sorts on the
stripped form** so the visible order matches the screen; sorting raw would
file every marked-up name under `~`.
"""

from __future__ import annotations
import argparse

from pathlib import Path

from fray_claude.cli.common import DEFAULT_MAP, derive_cached, emit_json, error, load_state
from fray_claude.cli.render import display_tasks, print_capped, print_grouped
from fray_claude.derive.challenges import strip_task_markup
from fray_claude.derive.other_tasks import CATEGORIES as OTHER_CATEGORIES, CategoryTasks, display_name, task_text
from fray_claude.derive.sections import describe_sections, expand_chunk_areas
from fray_claude.derive.sources import CATEGORIES as SOURCE_CATEGORIES
from fray_claude.model.chunkinfo import ChunkInfo


def _resolve_other_category(category: str | None) -> str | None:
    """Map a user-typed category onto one of `other_tasks.CATEGORIES`.

    Both the export's `Extra` and the app's `Other` are accepted; matching is
    case-insensitive so `fray tasks other` works like every other argument
    here would if it were typed loosely.
    """
    if category is None:
        return None
    folded = category.casefold()
    for name in OTHER_CATEGORIES:
        if folded in (name.casefold(), display_name(name).casefold()):
            return name
    return None


def _other_lines(tasks: CategoryTasks, chunk_info: ChunkInfo) -> list[str]:
    """One `[Group] description` line per active task, group order preserved."""
    challenges = chunk_info.challenges.get(tasks.category) or {}
    return [
        f"[{group.name}] {task_text(name, challenges.get(name) or {})}"
        for group in tasks.groups
        for name in group.active
    ]


def _cmd_sections(args: argparse.Namespace) -> int:
    state, unlocked = load_state(args)
    result = derive_cached(args, state, unlocked)

    if args.target is None:
        total_sections = sum(len(s) for s in result.reachable_sections.values())
        # `--export-json -` replaces the text summary on stdout, so a pipe
        # sees only JSON; a file destination leaves stdout for the summary.
        if args.export_json != "-":
            print(f"map                {args.map_id}")
            print(f"unlocked chunks    {len(unlocked)}")
            print(f"sectioned chunks   {len(result.reachable_sections)}")
            print(f"reachable sections {total_sections}")
        if args.export_json is not None:
            emit_json(
                {
                    "map_id": args.map_id,
                    "unlocked_chunks": len(unlocked),
                    "sections": result.reachable_sections,
                },
                args.export_json,
            )
        return 0

    expanded = expand_chunk_areas(unlocked)
    entries = describe_sections(expanded, result.reachable_sections, state.chunk_info)

    if args.target == "list":
        if args.export_json != "-":
            print(f"map             {args.map_id}")
            print(f"unlocked chunks {len(entries)}")
            shown = entries if args.limit is None else entries[: args.limit]
            for entry in shown:
                label = f"{entry.chunk_id:<8} {entry.name or '':<20}"
                print(f"  {label} {', '.join(entry.reachable)}")
            if args.limit is not None and len(entries) > args.limit:
                print(f"  ... and {len(entries) - args.limit} more (--limit {len(entries)})")
        if args.export_json is not None:
            emit_json(
                {"map_id": args.map_id, "chunks": [e.as_dict() for e in entries]}, args.export_json
            )
        return 0

    match = next((e for e in entries if e.chunk_id == args.target), None)
    if match is None:
        return error(f"chunk {args.target!r} is not unlocked on map {args.map_id!r}")
    if args.export_json != "-":
        print(f"map       {args.map_id}")
        print(f"chunk     {match.chunk_id}")
        print(f"name      {match.name or 'unknown'}")
        print(f"reachable {', '.join(match.reachable)}")
        print(f"locked    {', '.join(match.locked) if match.locked else 'none'}")
    if args.export_json is not None:
        emit_json({"map_id": args.map_id, **match.as_dict()}, args.export_json)
    return 0


def _cmd_sources(args: argparse.Namespace) -> int:
    state, unlocked = load_state(args)
    index = derive_cached(args, state, unlocked).source_index

    if args.category is None:
        if args.export_json != "-":
            print(f"map        {args.map_id}")
            print(f"items      {len(index.items)}")
            print(f"objects    {len(index.objects)}")
            print(f"monsters   {len(index.monsters)}")
            print(f"npcs       {len(index.npcs)}")
            print(f"shops      {len(index.shops)}")
        if args.export_json is not None:
            emit_json({"map_id": args.map_id, **index.as_dict()}, args.export_json)
        return 0

    contents = index.category(args.category)
    names = sorted(contents)
    if args.export_json != "-":
        print(f"map      {args.map_id}")
        print(f"category {args.category}")
        print(f"count    {len(names)}")
        print_capped(names, args.limit)
    if args.export_json is not None:
        emit_json(
            {"map_id": args.map_id, "category": args.category, args.category: contents},
            args.export_json,
        )
    return 0


def _cmd_tasks(args: argparse.Namespace) -> int:
    state, unlocked = load_state(args)
    derived = derive_cached(args, state, unlocked)
    result = derived.challenges

    if args.category is None:
        total_valid = sum(len(names) for names in result.valid.values())
        classifications = derived.task_classification.skills
        active_count = sum(1 for c in classifications.values() if c.active is not None)
        obsolete_count = sum(len(c.obsolete) for c in classifications.values())
        completed_count = sum(len(c.completed) for c in classifications.values())
        if args.export_json != "-":
            # The per-category `valid` breakdown this used to print is mostly
            # tasks a higher tier has already superseded - the totals stay for
            # scale, and each category lists its *active* tasks instead, which
            # is the part you can act on. `--export-json` still carries the
            # full per-category `valid` mapping.
            print(f"map          {args.map_id}")
            print(f"valid tasks  {total_valid}")
            print(f"unsupported  {len(result.unsupported)} individual tasks (see challenges.py)")
            print(
                f"skill tasks  active {active_count}, completed {completed_count}, "
                f"obsolete {obsolete_count} (across {len(classifications)} skill categories)"
            )
            print_capped(
                [
                    f"{skill:<13} {strip_task_markup(classification.active)}"
                    for skill, classification in sorted(classifications.items())
                    if classification.active is not None
                ],
                args.limit,
            )
            bis_line = f"BiS          active {len(derived.bis.active)}, completed {len(derived.bis.completed)}"
            if derived.bis.outdated:
                bis_line += f", outdated {len(derived.bis.outdated)}"
            print(bis_line)
            print_capped(derived.bis.display_sorted(derived.bis.active), args.limit)
            for category in OTHER_CATEGORIES:
                tasks = derived.other_tasks.categories.get(category)
                if tasks is None:
                    continue
                print(
                    f"{tasks.label:<12} active {tasks.active_total}, "
                    f"completed {tasks.completed_total}"
                )
                print_capped(_other_lines(tasks, state.chunk_info), args.limit)
        if args.export_json is not None:
            emit_json(
                {
                    "map_id": args.map_id,
                    **result.as_dict(),
                    "bis": derived.bis.as_dict(),
                    "task_classification": derived.task_classification.as_dict(),
                    "other_tasks": derived.other_tasks.as_dict(),
                },
                args.export_json,
            )
        return 0

    if args.category == "BiS":
        bis = derived.bis
        if args.export_json != "-":
            print(f"map       {args.map_id}")
            print("category  BiS")
            print(f"active    {len(bis.active)}")
            print_capped(bis.display_sorted(bis.active), args.limit)
            print(f"completed {len(bis.completed)}")
            print_capped(bis.display_sorted(bis.completed), args.limit)
            if bis.outdated:
                print(f"outdated  {len(bis.outdated)}")
                for name in sorted(bis.outdated, key=lambda n: (n not in bis.current_chunk, n)):
                    print(f"  {bis.display_name(name)}  ({bis.outdated[name]})")
        if args.export_json is not None:
            emit_json({"map_id": args.map_id, "category": "BiS", **bis.as_dict()}, args.export_json)
        return 0

    other_category = _resolve_other_category(args.category)
    if other_category is not None:
        tasks = derived.other_tasks.categories[other_category]
        label = tasks.label
        heading = label if label == other_category else f"{label} ({other_category})"
        if args.export_json != "-":
            print(f"map      {args.map_id}")
            print(f"category {heading}")
            print(f"active   {tasks.active_total}")
            print_grouped(tasks, state.chunk_info, "active", args.limit)
            print(f"completed {tasks.completed_total}")
            print_grouped(tasks, state.chunk_info, "completed", args.limit)
        if args.export_json is not None:
            emit_json({"map_id": args.map_id, **tasks.as_dict()}, args.export_json)
        return 0

    if args.category in derived.task_classification.skills:
        classification = derived.task_classification.skills[args.category]
        oracle = state.active_tasks.get(args.category, {})
        oracle_active = next(iter(oracle), None)
        if oracle_active is None:
            oracle_note = "not cached"
        elif oracle_active == classification.active:
            oracle_note = f"matches cached active task ({strip_task_markup(oracle_active)!r})"
        else:
            oracle_note = f"cached active task is {strip_task_markup(oracle_active)!r} (mismatch)"
        active_name = (
            strip_task_markup(classification.active) if classification.active else "(none)"
        )
        if args.export_json != "-":
            print(f"map      {args.map_id}")
            print(f"category {args.category}")
            print(f"active   {active_name}  [{oracle_note}]")
            print(f"completed {len(classification.completed)}")
            print_capped(display_tasks(classification.completed), args.limit)
            print(f"obsolete {len(classification.obsolete)}")
            print_capped(display_tasks(classification.obsolete), args.limit)
        if args.export_json is not None:
            emit_json(
                {
                    "map_id": args.map_id,
                    "category": args.category,
                    **classification.as_dict(),
                    "cached_active_task": oracle_active,
                },
                args.export_json,
            )
        return 0

    if args.category not in state.chunk_info.challenges:
        return error(f"unknown task category: {args.category!r}")

    names = sorted(result.valid.get(args.category, {}))
    if args.export_json != "-":
        print(f"map      {args.map_id}")
        print(f"category {args.category}")
        print(f"valid    {len(names)}")
        print_capped(display_tasks(names), args.limit)
    if args.export_json is not None:
        emit_json(
            {"map_id": args.map_id, "category": args.category, "valid": names},
            args.export_json,
        )
    return 0


def add_arguments(
    subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """This family's subcommands and their flags."""
    sections = subcommands.add_parser(
        "sections", help="reachable sections for the cached map's unlocked chunks"
    )
    sections.add_argument(
        "target",
        nargs="?",
        default=None,
        metavar="[list|CHUNK_ID]",
        help="'list' for every unlocked chunk, or a chunk id to inspect; omit for counts only",
    )
    sections.add_argument(
        "--limit", type=int, default=None, help="cap the number of chunks printed by 'list'"
    )
    sections.add_argument(
        "--map", dest="map_id", default=DEFAULT_MAP, help="map id (default: %(default)s)"
    )
    sections.add_argument(
        "--chunkinfo",
        type=Path,
        default=None,
        help="path to a chunkinfo export, overriding the cache and FRAY_CHUNKINFO",
    )
    sections.add_argument(
        "--export-json",
        metavar="PATH",
        default=None,
        help="write the full result as JSON to PATH, or to stdout if PATH is '-'",
    )
    sections.add_argument(
        "--recompute",
        action="store_true",
        help="ignore any cached derivation and compute (and re-store) a fresh one",
    )
    sections.set_defaults(func=_cmd_sections)

    sources = subcommands.add_parser(
        "sources", help="items/objects/monsters/npcs/shops the cached map's unlocked chunks give"
    )
    sources.add_argument(
        "category",
        nargs="?",
        default=None,
        choices=SOURCE_CATEGORIES,
        help=f"one of {SOURCE_CATEGORIES} to list its contents; omit for counts only",
    )
    sources.add_argument(
        "--limit", type=int, default=None, help="cap the number of names printed"
    )
    sources.add_argument(
        "--map", dest="map_id", default=DEFAULT_MAP, help="map id (default: %(default)s)"
    )
    sources.add_argument(
        "--chunkinfo",
        type=Path,
        default=None,
        help="path to a chunkinfo export, overriding the cache and FRAY_CHUNKINFO",
    )
    sources.add_argument(
        "--export-json",
        metavar="PATH",
        default=None,
        help="write the full result as JSON to PATH, or to stdout if PATH is '-'",
    )
    sources.add_argument(
        "--recompute",
        action="store_true",
        help="ignore any cached derivation and compute (and re-store) a fresh one",
    )
    sources.set_defaults(func=_cmd_sources)

    tasks = subcommands.add_parser(
        "tasks", help="which challenges are currently valid for the cached map"
    )
    tasks.add_argument(
        "category",
        nargs="?",
        default=None,
        help="a challenge category (e.g. Cooking, Nonskill) to list its valid tasks",
    )
    tasks.add_argument(
        "--limit", type=int, default=None, help="cap the number of tasks printed"
    )
    tasks.add_argument(
        "--map", dest="map_id", default=DEFAULT_MAP, help="map id (default: %(default)s)"
    )
    tasks.add_argument(
        "--chunkinfo",
        type=Path,
        default=None,
        help="path to a chunkinfo export, overriding the cache and FRAY_CHUNKINFO",
    )
    tasks.add_argument(
        "--export-json",
        metavar="PATH",
        default=None,
        help="write the full result as JSON to PATH, or to stdout if PATH is '-'",
    )
    tasks.add_argument(
        "--recompute",
        action="store_true",
        help="ignore any cached derivation and compute (and re-store) a fresh one",
    )
    tasks.set_defaults(func=_cmd_tasks)
