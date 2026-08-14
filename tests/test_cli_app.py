"""Tests for `cli/app.py`: the parser, `main`'s exit codes and the provenance line.

`project`, `cached_map`, `simulatable` and `derived_entries` come from
`conftest.py`, so the cache under test is a temporary one rather than the
project's own.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from fray_claude.remote.api import DEFAULT_TIMEOUT
from fray_claude.cli.app import build_parser, main
from fray_claude.cli.common import MapAmbiguityError, resolve_map
from fray_claude.model.summary import format_age
from fray_claude.store.cache import write_cache


def test_fetch_requires_a_map_because_nothing_local_can_imply_one() -> None:
    """The one `--map` with no default. Every other subcommand reads a map
    that is already cached; `fetch` names one that by definition is not."""
    with pytest.raises(SystemExit):
        build_parser().parse_args(["fetch"])

    args = build_parser().parse_args(["fetch", "--map", "fray"])

    assert (args.map_id, args.timeout) == ("fray", DEFAULT_TIMEOUT)


def test_an_omitted_map_resolves_to_the_sole_cached_one(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None]
) -> None:
    """**There is no house map id.** What a command can honestly infer is the
    cache: one map cached is unambiguously the one you meant."""
    cached_map({"chunks": {"unlocked": {"50_50": True}}}, {})

    args = build_parser().parse_args(["show"])
    assert args.map_id is None

    assert resolve_map(None) == "fray"


def test_an_empty_cache_and_an_ambiguous_one_fail_differently(project: Path) -> None:
    """An empty cache needs a fetch; an ambiguous one needs a choice. Saying
    so precisely is the whole value of refusing to guess."""
    with pytest.raises(MapAmbiguityError, match="no maps cached"):
        resolve_map(None)

    for name in ("one", "two"):
        write_cache(name, {"chunks": {"unlocked": {}}})

    with pytest.raises(MapAmbiguityError, match="one, two"):
        resolve_map(None)


def test_parser_requires_a_subcommand() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_every_command_stamps_which_install_answered(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """**`pipx install` without `--force` is a silent no-op**, so `fray` on
    `PATH` can be an older build than the checkout and nothing says so. The
    line goes to **stderr**, because nine subcommands can write their whole
    answer to stdout with `--export-json -`.
    """
    monkeypatch.delenv("FRAY_NO_WATERMARK", raising=False)
    monkeypatch.setattr(
        "fray_claude.cli.io_commands.fetch_map",
        lambda map_id, timeout=DEFAULT_TIMEOUT: {"chunks": {"unlocked": {"50_50": True}}},
    )

    assert main(["fetch", "--map", "fray"]) == 0

    captured = capsys.readouterr()
    assert captured.err.startswith("fray ")
    assert "fray " not in captured.out.split("\n")[0]


def test_the_stamp_stays_off_the_stream_the_answer_goes_to(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`fray maps list --export-json -` has to stay pipeable into `jq`."""
    monkeypatch.delenv("FRAY_NO_WATERMARK", raising=False)
    monkeypatch.setattr(
        "fray_claude.cli.io_commands.fetch_map",
        lambda map_id, timeout=DEFAULT_TIMEOUT: {"chunks": {"unlocked": {"50_50": True}}},
    )
    main(["fetch", "--map", "fray"])
    capsys.readouterr()

    assert main(["maps", "list", "--export-json", "-"]) == 0

    assert json.loads(capsys.readouterr().out)  # not "fray 0.1.0 ...{"


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(seconds=5), "5s ago"),
        (timedelta(minutes=3), "3m ago"),
        (timedelta(hours=5), "5h ago"),
        (timedelta(days=2), "2d ago"),
        (timedelta(seconds=-30), "0s ago"),
    ],
)
def test_format_age_buckets(delta: timedelta, expected: str) -> None:
    assert format_age((datetime.now(UTC) - delta).isoformat()) == expected


def test_format_age_assumes_utc_for_a_naive_timestamp() -> None:
    naive = datetime.now(UTC).replace(tzinfo=None).isoformat()

    assert format_age(naive) == "0s ago"


@pytest.mark.parametrize("value", ["not a timestamp", None, 1709907279995])
def test_format_age_reports_unusable_input_as_unknown(value: object) -> None:
    assert format_age(value) == "unknown"
