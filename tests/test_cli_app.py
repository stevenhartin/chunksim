"""Tests for `cli/app.py`: the parser, `main`'s exit codes and the provenance line.

`project`, `cached_map`, `simulatable` and `derived_entries` come from
`conftest.py`, so the cache under test is a temporary one rather than the
project's own.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fray_claude.remote.api import DEFAULT_TIMEOUT
from fray_claude.cli.app import build_parser, main
from fray_claude.model.summary import format_age


def test_parser_defaults_to_the_fray_map() -> None:
    args = build_parser().parse_args(["fetch"])

    assert (args.map_id, args.timeout) == ("fray", DEFAULT_TIMEOUT)


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

    assert main(["fetch"]) == 0

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
    main(["fetch"])
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
