"""`fray estimate`: hours, and the two caveats that have to travel with them.

The rendering half. What to price and how is `costing/inputs.py`', shared with
the GUI so the two apps cannot answer differently - read that module before
changing what appears here.

**Both caveats are printed rather than swallowed.** Without a scrape every
number falls back to a default and the total is thousands of hours light; with
the `dps` extra the rates are computed from the map's own gear and the total is
a different number again (3,969h against 2,816h on the real map). A confident
figure with neither statement beside it would be the least honest thing this
command could print.
"""

from __future__ import annotations
import argparse

from pathlib import Path

from fray_claude.cli.common import derive_cached, digests, emit_json, error, load_state
from fray_claude.costing import dps_bridge, inputs
from fray_claude.costing.estimate import BUCKETS, EstimateResult
from fray_claude.derive.task_names import strip_task_markup
def _cmd_estimate(args: argparse.Namespace) -> int:
    if args.bucket is not None and args.bucket not in BUCKETS:
        return error(f"unknown bucket {args.bucket!r} (expected one of {', '.join(BUCKETS)})")

    state, unlocked = load_state(args)
    # One `Digests` for the derivation and the estimate below: building it
    # hashes 13MB, and this handler used to do that twice.
    known = digests(args)
    derived = derive_cached(args, state, unlocked, known)
    # Everything about *what* to price lives in `costing.inputs`, shared with
    # the GUI so the two apps cannot answer differently; what is left here is
    # rendering.
    answer = inputs.estimate_answer(
        state, unlocked, derived, known, refresh=args.recompute, map_id=args.map_id
    )

    if args.export_json != "-":
        _print_estimate(
            answer.result,
            args.map_id,
            args.bucket,
            args.limit,
            answer.scraped_rates,
            answer.coverage,
        )
    if args.export_json is not None:
        emit_json(answer.as_dict(args.map_id), args.export_json)
    return 0


def _print_estimate(
    result: EstimateResult,
    map_id: str,
    bucket: str | None,
    limit: int | None,
    scraped_found: bool = True,
    coverage: dps_bridge.DpsCoverage | None = None,
) -> None:
    print(f"map          {map_id}")
    if coverage is not None and coverage.priced_anything:
        pinned = f", {coverage.pinned} pinned" if coverage.pinned else ""
        print(
            f"dps calc     {coverage.monsters} of {coverage.offered} reachable monsters, "
            f"{coverage.slayer_tasks} slayer tasks ({'/'.join(coverage.styles)}{pinned})"
        )
    for name, hours in result.buckets.items():
        if bucket is None or bucket == name:
            print(f"{name:<12} {hours:>9,.1f}h")
    if bucket is None:
        print(f"{'total':<12} {result.total_hours:>9,.1f}h")
        if result.unpriced:
            print(f"unpriced     {len(result.unpriced)} (no priceable route - see estimate.py)")
        _print_estimate_warnings(result, scraped_found)
        return

    if bucket == "skilling":
        for skill in sorted(result.skills, key=lambda skill: -skill.hours):
            flag = " (default rate)" if skill.defaulted else ""
            start = (
                f"{skill.effective_level:>3}"
                if skill.effective_level == skill.current_level
                else f"{skill.effective_level:>3}*"
            )
            print(
                f"  {skill.skill:<13} {start} -> {skill.target_level:<3}"
                f" {skill.xp:>10,} xp @ {skill.xp_per_hour:>9,.0f}/hr"
                f" = {skill.hours:>7,.1f}h  {skill.method}{flag}"
            )
            # **The bands are the reasoning, and a blended rate hides it.**
            # 130,000 xp/hr for Herblore is not a rate anybody trains at; it is
            # fourteen methods averaged, and which of them covers the 4.1M xp
            # from 75 to 90 is the number worth arguing with.
            for band in skill.bands:
                if len(skill.bands) == 1:
                    break
                note = "" if band.method else "  (no rate known)"
                print(
                    f"      {band.level_from:>3} -> {band.level_to:<3}"
                    f" {band.xp:>10,} xp @ {band.xp_per_hour:>9,.0f}/hr"
                    f" = {band.hours:>7,.1f}h  {band.method}{note}"
                    f"  [{band.match}]"
                )
            gathering = sum(band.material_hours for band in skill.bands)
            if gathering > 0.05:
                # **Why the rate looks low.** A guide quotes a method with its
                # materials to hand; on a chunk map obtaining them is often
                # most of the cost, and the climb is ranked on the total. Say
                # which half is which rather than leave a familiar figure
                # looking wrong.
                print(
                    f"      * {gathering:,.1f}h of that is gathering what the method"
                    f" consumes, which published rates assume you have"
                )
            if skill.xp_from_quests:
                print(
                    f"      * {skill.xp_from_quests:,} xp of that climb is paid by quests"
                    f" this map can finish"
                )
            if skill.days:
                # **Said, not added.** Farming's hours are the clicking; the
                # calendar is what actually constrains it, and the two are not
                # the same kind of number - so the total keeps the hours and
                # the reader gets the months.
                print(
                    f"      * {skill.days:,.0f} days of calendar time at that schedule"
                    f" - the hours above are clicking, not waiting"
                )
        for refused in result.unpriced_skills:
            print(
                f"  {refused.skill:<13} {refused.current_level:>3} ->"
                f" {refused.target_level:<3} {refused.xp:>10,} xp"
                f"   not priced: {refused.reason}"
            )
        for lamp in result.unallocated_quest_xp:
            where = ", ".join(lamp.skills) if lamp.skills else "any skill"
            print(
                f"  unspent      {lamp.count} x {lamp.xp:,} xp from {lamp.quest}"
                f" -> {where}"
            )
        _print_slayer_masters(result)
        return

    if bucket == "quests":
        rows = result.in_bucket(bucket)
        for task in rows if limit is None else rows[:limit]:
            print(f"  {task.hours:>8,.1f}h {strip_task_markup(task.task):<48} {task.detail}")
        if limit is not None and len(rows) > limit:
            print(f"  ... and {len(rows) - limit} more (--limit {len(rows)} to see all)")
        return

    # Grouped by source, because that is how the time is actually spent: the
    # items under one heading are earned together, so the heading carries
    # what the source costs and each item still shows its own expected time.
    groups = result.sources_in(bucket)
    for source, hours, entries in groups if limit is None else groups[:limit]:
        together = f"  ({len(entries)} items, earned together)" if len(entries) > 1 else ""
        print(f"  {hours:>8,.1f}h {source}{together}")
        for entry in entries:
            covers = f" x{len(entry.tasks)}" if len(entry.tasks) > 1 else ""
            print(f"      {entry.hours:>8,.1f}h {entry.item}{covers}")
    if limit is not None and len(groups) > limit:
        print(f"  ... and {len(groups) - limit} more (--limit {len(groups)} to see all)")


def _print_slayer_masters(result: EstimateResult) -> None:
    """Every reachable master, not just the one the estimate used.

    Slayer is the one skill whose rate depends on *who you talk to*, and XP
    per hour is not the only reason to pick one: a master with a fuller task
    list, fewer gaps in its data, a denser superior pool, or a points balance
    that does not bleed can be the better choice even when slower. The
    estimate still uses the fastest.

    Every column is computed at this chunk's *end* levels - see
    `estimate.goal_levels`. The list a master offers at Slayer 92 is the one
    that holds for the tail of the chunk, and the tail is where the time
    goes.
    """
    if not result.slayer_masters:
        return

    chosen = result.slayer.master if result.slayer else ""
    print(
        f"\n  {'slayer master':<18} {'xp/hr':>9} {'skip':>5} {'pts/task':>9} {'no data':>8}"
        "  sup. unique"
    )
    for rate in result.slayer_masters:
        # The shared unique table, not the superior itself: the drops are
        # what anyone is farming supers for.
        rolls = result.superior_rolls.get(rate.master, 0.0)
        supers = f"1 per {1 / rolls:,.0f}h" if rolls > 0 else "none"
        marker = " *" if rate.master == chosen else "  "
        print(
            f" {marker}{rate.master:<18} {rate.xp_per_hour:>9,.0f} {rate.skip_rate:>5.0%}"
            f" {rate.points_delta:>+9.1f} {rate.unpriced:>8.0%}  {supers}"
        )
    print("  * used by the estimate (fastest); the others are shown to compare")
    print("  skip = share of *offered* tasks whose monsters this map cannot reach")
    print("  pts/task = points earned, less points paid skipping those; negative bleeds points")
    print("  sup. unique = how often the shared superior table rolls - imbued heart,")
    print("  eternal gem, dust and mist battlestaff. A superior itself spawns far")
    print("  more often; the unique off one is what the hours are spent on")
    print("  all four assume this chunk's end levels - the task list you will")
    print("  spend most of it on - not the levels you hold today")


def _print_estimate_warnings(result: EstimateResult, scraped_found: bool = True) -> None:
    """What makes the total untrustworthy, said plainly rather than buried."""
    if not scraped_found:
        # The single biggest thing that can be wrong with a total, and the
        # easiest to miss: without the scrape there are no superior mappings
        # and no slayer assignment sizes, so whole classes of drop cannot be
        # priced and the total is light rather than wrong-looking.
        print(
            "\nno cached wiki rates: every rate below is a default."
            "\n  run: fray heuristics   (superior and task-gated drops cannot be"
            " priced without it)"
        )
    defaulted = [skill.skill for skill in result.skills if skill.defaulted]
    if defaulted:
        print(
            f"\n{len(defaulted)} skill(s) using the default training rate:"
            f" {', '.join(sorted(defaulted))}"
        )
        print("  correct them in heuristics/overrides.json - see heuristics.py")
    slayer = result.slayer
    if slayer is None:
        return
    # Two different problems, said as two different sentences: one is a fact
    # about the map, the other is a hole in the config.
    if slayer.coverage < 0.5:
        print(
            f"\nslayer: only {slayer.coverage:.0%} of {slayer.master}'s task weight is"
            " reachable, so its rate is optimistic (see slayer.py)"
        )
    if slayer.unpriced > 0.05:
        print(
            f"\nslayer: {slayer.unpriced:.0%} of {slayer.master}'s task weight has no rate"
            " data - reachable, but not costed"
        )
        print("  add them under `slayer` in heuristics/overrides.json")


def add_arguments(
    subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """This family's subcommands and their flags."""
    estimate_cmd = subcommands.add_parser(
        "estimate", help="roughly how long the outstanding active tasks would take"
    )
    estimate_cmd.add_argument(
        "bucket",
        nargs="?",
        default=None,
        metavar="BUCKET",
        help=f"drill into one bucket, one of: {', '.join(BUCKETS)}",
    )
    estimate_cmd.add_argument(
        "--limit", type=int, default=None, help="cap the tasks listed for BUCKET"
    )
    estimate_cmd.add_argument(
        "--map",
        dest="map_id",
        default=None,
        help="map id (default: the sole cached map)",
    )
    estimate_cmd.add_argument(
        "--chunkinfo",
        type=Path,
        default=None,
        help="path to a chunkinfo export, overriding the cache and FRAY_CHUNKINFO",
    )
    estimate_cmd.add_argument(
        "--export-json",
        metavar="PATH",
        default=None,
        help="write the full result as JSON to PATH, or to stdout if PATH is '-'",
    )
    estimate_cmd.add_argument(
        "--recompute",
        action="store_true",
        help="ignore any cached derivation and compute (and re-store) a fresh one",
    )
    estimate_cmd.set_defaults(func=_cmd_estimate)
