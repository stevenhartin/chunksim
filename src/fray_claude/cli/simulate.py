"""`fray simulate`: roll chunks from this map's state, N times over.

`--cache-map NAME` saves each run as a cached map rather than only printing
it, `--runs N` asks for N independent simulations, and `--jobs N` spreads them
over worker processes. `runs/batch.py` owns all three; `store/cache.py` owns
the layout they land in.

**`--jobs` defaults to 0, meaning every core this process may use.** A roll is
a full derivation and the runs are independent, so the serial default this
used to carry made a ten-run batch of fifty rolls a six-minute wait on a
machine that could do it in under one. `--jobs 1` is how to ask for a single
process back. `runs/batch.py`'s own default stays at 1, since a *library* that
forks the machine behind a GUI thread is a different proposition - its
docstring says so.

**`--runs` without `--cache-map` is an error rather than a silent single
run** - there would be nowhere to put the other N-1. `--cache-behaviour`
chooses how much of a run's derived state to keep (all of it by default, so
re-running a seed is served from disk).

`--jobs` must never change a result. That property belongs to `derive/`, which
has no module-level mutable state for exactly this reason.
"""

from __future__ import annotations
import argparse

from pathlib import Path

from fray_claude.cli.common import DEFAULT_MAP, digests, emit_json, error, load_state
from fray_claude.runs.batch import RunResult, run_batch
from fray_claude.runs.simulate import simulate_rolls
from fray_claude.store.cache import read_cache
from fray_claude.store.derived_cache import CacheBehaviour, RollCache


def _simulate_to_cache(args: argparse.Namespace) -> int:
    """`fray simulate --cache-map`: persist each run as its own cached map."""
    envelope = read_cache(args.map_id)
    quiet = args.export_json == "-"

    def report(result: RunResult) -> None:
        print(f"  {result.name} {len(result.rolls)} rolls -> {result.unlocked_chunks} chunks")

    batch = run_batch(
        name=args.cache_map,
        payload=envelope["data"],
        base_map=args.map_id,
        base_fetched_at=envelope.get("fetched_at"),
        rolls=args.rolls,
        runs=args.runs,
        jobs=args.jobs,
        seed=args.seed,
        chunkinfo_path=args.chunkinfo,
        cache_behaviour=CacheBehaviour(args.cache_behaviour),
        on_complete=None if quiet else report,
    )

    if not quiet:
        if batch.name != args.cache_map:
            print(f"name {args.cache_map!r} was taken; saved as {batch.name!r}")
        print(f"batch        {batch.name} ({batch.directory})")
        print(f"runs         {len(batch.runs)} x {args.rolls} rolls")
        read_as = batch.name if len(batch.runs) == 1 else f"{batch.name}/{batch.runs[0].name}"
        print(f"read with    fray tasks --map {read_as}")
    if args.export_json is not None:
        emit_json(batch.as_dict(), args.export_json)
    return 0


def _cmd_simulate(args: argparse.Namespace) -> int:
    if args.rolls < 1:
        return error("--rolls must be at least 1")
    if args.runs < 1:
        return error("--runs must be at least 1")
    if args.jobs < 0:
        return error("--jobs must not be negative")
    if args.cache_map is not None:
        return _simulate_to_cache(args)
    if args.runs > 1:
        return error("--runs needs --cache-map: without it there is nowhere to put the runs")

    state, unlocked = load_state(args)
    ledger = simulate_rolls(
        state,
        unlocked,
        rolls=args.rolls,
        seed=args.seed,
        cache=RollCache(digests(args), CacheBehaviour(args.cache_behaviour)),
    )
    total_tasks = sum(len(names) for record in ledger for names in record.new_tasks.values())
    total_bis = sum(len(record.bis_upgrades) for record in ledger)

    if args.export_json != "-":
        seed_note = f" (seed {args.seed})" if args.seed is not None else ""
        print(f"map          {args.map_id}")
        print(f"rolls        {len(ledger)} of {args.rolls} requested{seed_note}")
        for record in ledger:
            task_count = sum(len(names) for names in record.new_tasks.values())
            section_count = sum(len(s) for s in record.new_sections.values())
            bis_count = len(record.bis_upgrades)
            print(
                f"  {record.order:>3} {record.chunk_id:<8} tasks+{task_count} "
                f"sections+{section_count} bis+{bis_count}"
            )
        print(f"total new tasks {total_tasks}")
        if total_bis:
            print(f"total bis upgrades {total_bis}")

    if args.export_json is not None:
        emit_json(
            {
                "map_id": args.map_id,
                "seed": args.seed,
                "rolls_requested": args.rolls,
                "rolls": [record.as_dict() for record in ledger],
            },
            args.export_json,
        )
    return 0


def add_arguments(
    subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """This family's subcommands and their flags."""
    simulate = subcommands.add_parser(
        "simulate", help="simulate N chunk rolls from the cached map and accumulate their tasks"
    )
    simulate.add_argument(
        "--rolls", type=int, required=True, help="number of chunks to roll"
    )
    simulate.add_argument(
        "--seed", type=int, default=None, help="RNG seed, for a reproducible run"
    )
    simulate.add_argument(
        "--cache-map",
        dest="cache_map",
        metavar="NAME",
        default=None,
        help="save each run as a cached map under NAME, readable with --map",
    )
    simulate.add_argument(
        "--runs",
        type=int,
        default=1,
        help="number of independent simulations to run (needs --cache-map; default: %(default)s)",
    )
    simulate.add_argument(
        "--cache-behaviour",
        dest="cache_behaviour",
        choices=[behaviour.value for behaviour in CacheBehaviour],
        default=CacheBehaviour.ALL.value,
        help="which derived states to keep in the derivation cache (default: %(default)s)",
    )
    simulate.add_argument(
        "--jobs",
        type=int,
        default=0,
        help=(
            "worker processes to spread the runs over; 0 uses every core this "
            "process may use, 1 runs them inline (default: %(default)s)"
        ),
    )
    simulate.add_argument(
        "--map", dest="map_id", default=DEFAULT_MAP, help="map id (default: %(default)s)"
    )
    simulate.add_argument(
        "--chunkinfo",
        type=Path,
        default=None,
        help="path to a chunkinfo export, overriding the cache and FRAY_CHUNKINFO",
    )
    simulate.add_argument(
        "--export-json",
        metavar="PATH",
        default=None,
        help="write the full result as JSON to PATH, or to stdout if PATH is '-'",
    )
    simulate.add_argument(
        "--recompute",
        action="store_true",
        help="ignore any cached derivation and compute (and re-store) a fresh one",
    )
    simulate.set_defaults(func=_cmd_simulate)
