"""`fray diff`: the symmetric comparison of two cached maps.

The one subcommand taking two maps, hence `--map1`/`--map2` rather than this
package's usual `--map`; both are required and either can name a fetched or a
computed map. It builds a single `ChunkInfo` and derives both sides against it.

**It reports both directions, which `fray unlock` deliberately does not.**
Adding a chunk is very nearly monotone, so `unlock` is additions-only; two
arbitrary maps are not related that way at all. Read `derive/delta.py` before
assuming the two commands answer the same question.
"""

from __future__ import annotations
import argparse

from collections.abc import Mapping
from pathlib import Path

from fray_claude.cli.common import derive_cached, emit_json, error, load_state
from fray_claude.cli.render import display_tasks, name_or_none, print_capped
from fray_claude.derive.delta import BRANCHES, BranchDelta, MapSide, StateDelta, compare_maps
from fray_claude.derive.other_tasks import display_name


def _delta_lines(branch: BranchDelta, *, strip: bool = False) -> list[str]:
    """One `+ name`/`- name` line each, gains before losses."""
    added = display_tasks(branch.added) if strip else sorted(branch.added)
    removed = display_tasks(branch.removed) if strip else sorted(branch.removed)
    return [f"+ {name}" for name in added] + [f"- {name}" for name in removed]


def _nested_delta_lines(
    branches: Mapping[str, BranchDelta], *, strip: bool = False, label: str = ""
) -> list[str]:
    """Each key's gains and losses indented under its own header."""
    lines: list[str] = []
    for key in sorted(branches):
        lines.append(f"{label}{key}")
        lines.extend(f"  {line}" for line in _delta_lines(branches[key], strip=strip))
    return lines


def _print_diff_branch(delta: StateDelta, branch: str, limit: int | None) -> None:
    """One branch's names in full. `--limit` caps printed *lines*, headers
    included, so a capped listing still shows which keys it got through.
    """
    lines: list[str] = []
    if branch == "chunks":
        lines = _delta_lines(delta.chunks)
    elif branch == "sections":
        lines = _nested_delta_lines(delta.sections)
    elif branch == "tasks":
        lines = _nested_delta_lines(delta.tasks, strip=True)
    elif branch == "unsupported":
        lines = _delta_lines(delta.unsupported, strip=True)
    elif branch == "sources":
        lines = _nested_delta_lines(delta.sources)
    elif branch == "bis":
        lines = [
            f"{key:<24} {name_or_none(before)} -> {name_or_none(after)}"
            for key, (before, after) in sorted(delta.bis_picks.items())
        ]
        lines.extend(_nested_delta_lines(delta.bis_tasks, strip=True))
    elif branch == "skills":
        for skill in sorted(delta.skills):
            change = delta.skills[skill]
            lines.append(skill)
            if change.active is not None:
                was, now = change.active
                lines.append(f"  goal {name_or_none(was)} -> {name_or_none(now)}")
            lines.extend(f"  obsolete {line}" for line in _delta_lines(change.obsolete, strip=True))
            lines.extend(
                f"  completed {line}" for line in _delta_lines(change.completed, strip=True)
            )
    else:
        for category in sorted(delta.other):
            lines.append(display_name(category))
            for name, changed in sorted(delta.other[category].items()):
                lines.extend(f"  {name} {line}" for line in _delta_lines(changed, strip=True))
    print_capped(lines, limit)


def _print_diff_summary(delta: StateDelta, branch: str | None) -> None:
    """`+gained -lost` per branch. With `--branch`, only that one: the others
    weren't computed, and printing them as zeroes would read as "unchanged".
    """
    print(f"map1         {delta.before_map}")
    print(f"map2         {delta.after_map}")
    for name, (added, removed) in delta.counts().items():
        if branch is None or branch == name:
            print(f"{name:<12} +{added} -{removed}")
    if delta.bis_picks:
        print(f"bis picks    {len(delta.bis_picks)} changed")
    goals = sum(1 for change in delta.skills.values() if change.active is not None)
    if goals:
        print(f"skill goals  {goals} changed")


def _cmd_diff(args: argparse.Namespace) -> int:
    if args.branch is not None and args.branch not in BRANCHES:
        return error(f"unknown branch {args.branch!r} (expected one of {', '.join(BRANCHES)})")

    # One `ChunkInfo` for both sides: parsing the ~10MB export is the expensive
    # part, and the two maps are read against the same world by definition.
    # Taking it from the first side rather than building it up front also keeps
    # a missing *map* the first thing reported, as in every other subcommand.
    before_state, before_unlocked = load_state(args, args.map1)
    after_state, after_unlocked = load_state(args, args.map2, chunk_info=before_state.chunk_info)
    delta = compare_maps(
        MapSide(before_state, before_unlocked, args.map1),
        MapSide(after_state, after_unlocked, args.map2),
        derive_with=lambda s, u: derive_cached(args, s, u),
        branches=None if args.branch is None else frozenset({args.branch}),
    )

    if args.export_json != "-":
        _print_diff_summary(delta, args.branch)
        if args.branch is not None:
            _print_diff_branch(delta, args.branch, args.limit)
    if args.export_json is not None:
        emit_json(delta.as_dict(), args.export_json)
    return 0


def add_arguments(
    subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """This family's subcommands and their flags."""
    diff = subcommands.add_parser(
        "diff", help="compare two cached maps: what the second has that the first doesn't, and back"
    )
    diff.add_argument("--map1", required=True, metavar="MAPID", help="the map to compare from")
    diff.add_argument("--map2", required=True, metavar="MAPID", help="the map to compare to")
    diff.add_argument(
        "branch",
        nargs="?",
        default=None,
        metavar="BRANCH",
        help=f"list one branch's names in full, one of: {', '.join(BRANCHES)}",
    )
    diff.add_argument("--limit", type=int, default=None, help="cap the lines printed for BRANCH")
    diff.add_argument(
        "--chunkinfo",
        type=Path,
        default=None,
        help="path to a chunkinfo export, overriding the cache and FRAY_CHUNKINFO",
    )
    diff.add_argument(
        "--export-json",
        metavar="PATH",
        default=None,
        help="write the full result as JSON to PATH, or to stdout if PATH is '-'",
    )
    diff.add_argument(
        "--recompute",
        action="store_true",
        help="ignore any cached derivation and compute (and re-store) a fresh one",
    )
    diff.set_defaults(func=_cmd_diff)
