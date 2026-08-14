"""What the provenance line is allowed to claim.

Every test here builds its own `*.dist-info` under `tmp_path` rather than
asking about whatever is installed while the suite runs - which is an editable
install in a developer's checkout and a wheel in a fresh clone's, so an
assertion about the real one would pass for a different reason in each.
"""

from __future__ import annotations

import importlib.metadata as metadata
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from chunksim.store.build_info import (
    NO_WATERMARK_ENV,
    Build,
    describe,
    print_watermark,
    read_build,
    watermark,
)


def _dist(tmp_path: Path, *, editable: bool | None = None, mtime: float | None = None) -> metadata.Distribution:
    """A real `PathDistribution` over a hand-built `*.dist-info` directory."""
    site = tmp_path / "site-packages"
    info = site / "demo-1.2.3.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text("Metadata-Version: 2.1\nName: demo\nVersion: 1.2.3\n")
    # `files` reads RECORD, and the paths in it are relative to site-packages.
    (info / "RECORD").write_text("demo-1.2.3.dist-info/METADATA,,\ndemo/__init__.py,,\n")
    if editable is not None:
        (info / "direct_url.json").write_text(
            json.dumps({"url": "file:///somewhere", "dir_info": {"editable": editable}})
        )
    if mtime is not None:
        os.utime(info, (mtime, mtime))
    return metadata.PathDistribution(info)


def test_a_wheel_install_is_dated_by_its_metadata_directory(tmp_path: Path) -> None:
    """**pip writes those files fresh rather than restoring the zip's dates**,
    so the mtime is when the code landed here - which is the question - and not
    when the wheel was built."""
    stamped = datetime(2026, 8, 9, 21, 2, 57, tzinfo=UTC)

    build = describe(_dist(tmp_path, mtime=stamped.timestamp()), tmp_path / "demo")

    assert build.version == "1.2.3"
    assert build.kind == "wheel"
    assert build.installed_at is not None
    assert datetime.fromisoformat(build.installed_at) == stamped


def test_an_editable_install_says_so(tmp_path: Path) -> None:
    """Its date is the age of the *link*, not of the code, and the wording has
    to change with it or the line is a small lie told on every run."""
    build = describe(_dist(tmp_path, editable=True), tmp_path / "demo")

    assert build.kind == "editable"
    assert "editable install, linked" in watermark("chunksim", build)


def test_a_local_wheel_is_not_an_editable_install(tmp_path: Path) -> None:
    """`direct_url.json` is present for any install from a path - it is
    `dir_info.editable` that separates `-e` from a plain one."""
    assert describe(_dist(tmp_path, editable=False), tmp_path / "demo").kind == "wheel"


def test_an_unreadable_direct_url_is_not_an_editable_install(tmp_path: Path) -> None:
    """Malformed metadata should cost the *distinction*, never the command."""
    dist = _dist(tmp_path, editable=True)
    (tmp_path / "site-packages" / "demo-1.2.3.dist-info" / "direct_url.json").write_text("{not json")

    assert describe(dist, tmp_path / "demo").kind == "wheel"


def test_an_uninstalled_checkout_has_no_date_and_says_where_it_is() -> None:
    """`python -m chunksim` off a checkout on `sys.path` reaches the code
    without any installer having recorded anything. Inventing a date there
    would be worse than the honest answer."""
    build = read_build("no-such-distribution-anywhere")

    assert build.kind == "source"
    assert build.installed_at is None
    assert build.version == "unknown"
    assert build.path.endswith("chunksim")
    assert "uninstalled source at" in watermark("chunksim", build)


def test_the_real_install_answers_and_never_raises() -> None:
    """Whatever this checkout is, the line must be printable."""
    build = read_build()

    assert build.kind in ("wheel", "editable", "source")
    assert watermark("chunksim", build).startswith("chunksim ")


def test_the_json_the_page_reads_is_flat_and_the_same_shape_for_every_kind(
    tmp_path: Path,
) -> None:
    keys = {"version", "installed_at", "kind", "path"}

    assert set(describe(_dist(tmp_path), tmp_path / "demo").as_dict()) == keys
    assert set(read_build("no-such-distribution-anywhere").as_dict()) == keys


def test_the_watermark_names_the_app_it_was_printed_by() -> None:
    build = Build(version="0.1.0", installed_at=None, kind="wheel", path="/x")

    assert watermark("chunksim-gui", build).startswith("chunksim-gui 0.1.0")


def test_the_environment_can_silence_it(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(NO_WATERMARK_ENV, "1")
    print_watermark("chunksim")

    assert capsys.readouterr() == ("", "")


def test_it_goes_to_stderr_by_default(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """**Nine subcommands can write their whole answer to stdout** with
    `--export-json -`; a line of provenance in front of it is a parse error."""
    monkeypatch.delenv(NO_WATERMARK_ENV, raising=False)
    print_watermark("chunksim")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("chunksim ")
