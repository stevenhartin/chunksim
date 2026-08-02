"""Tests for the on-disk cache layer.

Every test passes an explicit `root`, so the project's real `cache/` is never
touched.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from fray_claude.cache import (
    CHUNKINFO_ENV_VAR,
    CacheMissError,
    blob_path,
    cache_path,
    project_root,
    read_blob,
    read_cache,
    read_chunkinfo,
    write_blob,
    write_cache,
)


def test_write_then_read_round_trips_the_payload(tmp_path: Path) -> None:
    data = {"chunks": {"unlocked": {"50_50": True}}}

    write_cache("fray", data, root=tmp_path)

    assert read_cache("fray", root=tmp_path)["data"] == data


def test_write_cache_records_provenance(tmp_path: Path) -> None:
    path = write_cache("fray", {}, root=tmp_path)
    envelope = json.loads(path.read_text(encoding="utf-8"))

    assert envelope["map_id"] == "fray"
    assert envelope["source"] == "https://chunkpicker.firebaseio.com/maps/fray.json"
    stamp = datetime.fromisoformat(envelope["fetched_at"])
    assert stamp.tzinfo is not None
    assert abs((datetime.now(UTC) - stamp).total_seconds()) < 60


def test_write_cache_creates_the_cache_directory(tmp_path: Path) -> None:
    path = write_cache("fray", {}, root=tmp_path / "missing")

    assert path == tmp_path / "missing" / "cache" / "fray.json"
    assert path.is_file()


def test_cache_path_is_named_after_the_map(tmp_path: Path) -> None:
    assert cache_path("other", root=tmp_path) == tmp_path / "cache" / "other.json"


def test_read_cache_reports_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(CacheMissError, match="no cached data for map 'fray'"):
        read_cache("fray", root=tmp_path)


def test_read_cache_hint_names_the_requested_map(tmp_path: Path) -> None:
    with pytest.raises(CacheMissError, match="fray fetch --map other"):
        read_cache("other", root=tmp_path)


def test_read_cache_rejects_invalid_json(tmp_path: Path) -> None:
    path = cache_path("fray", root=tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(CacheMissError, match="not valid JSON"):
        read_cache("fray", root=tmp_path)


@pytest.mark.parametrize("envelope", ['["a"]', "{}", '{"data": "unexpected"}'])
def test_read_cache_rejects_an_envelope_without_a_data_object(
    tmp_path: Path, envelope: str
) -> None:
    path = cache_path("fray", root=tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(envelope, encoding="utf-8")

    with pytest.raises(CacheMissError, match="malformed"):
        read_cache("fray", root=tmp_path)


def test_project_root_walks_up_to_the_marker(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    nested = tmp_path / "src" / "fray_claude"
    nested.mkdir(parents=True)

    assert project_root(nested) == tmp_path.resolve()


def test_project_root_falls_back_to_the_starting_directory(tmp_path: Path) -> None:
    # tmp_path has no ancestor holding a pyproject.toml.
    assert project_root(tmp_path) == tmp_path.resolve()


def test_write_then_read_blob_round_trips_the_payload(tmp_path: Path) -> None:
    data = {"chunks": {"3883": {"Nickname": "Lumbridge"}}}

    write_blob("chunkinfo", data, "https://example.invalid/chunkinfo.json", root=tmp_path)

    assert read_blob("chunkinfo", root=tmp_path)["data"] == data


def test_write_blob_records_provenance(tmp_path: Path) -> None:
    path = write_blob("chunkinfo", {}, "https://example.invalid/chunkinfo.json", root=tmp_path)
    envelope = json.loads(path.read_text(encoding="utf-8"))

    assert envelope["name"] == "chunkinfo"
    assert envelope["source"] == "https://example.invalid/chunkinfo.json"


def test_blob_path_is_named_after_the_blob(tmp_path: Path) -> None:
    assert blob_path("tasks_map", root=tmp_path) == tmp_path / "cache" / "tasks_map.json"


def test_read_blob_reports_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(CacheMissError, match="no cached data for 'chunkinfo'"):
        read_blob("chunkinfo", root=tmp_path)


def test_read_chunkinfo_falls_back_to_the_cached_blob(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A `FRAY_CHUNKINFO` set in the ambient environment must not shadow this.
    monkeypatch.delenv(CHUNKINFO_ENV_VAR, raising=False)
    data: dict[str, Any] = {"chunks": {}}
    write_blob("chunkinfo", data, "https://example.invalid/chunkinfo.json", root=tmp_path)

    assert read_chunkinfo(root=tmp_path) == data


def test_read_chunkinfo_prefers_an_explicit_override(tmp_path: Path) -> None:
    override = tmp_path / "local-chunkinfo.json"
    override.write_text(json.dumps({"chunks": {"local": True}}), encoding="utf-8")
    write_blob("chunkinfo", {"chunks": {"cached": True}}, "source", root=tmp_path)

    assert read_chunkinfo(override=override, root=tmp_path) == {"chunks": {"local": True}}


def test_read_chunkinfo_falls_back_to_the_env_var(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    override = tmp_path / "local-chunkinfo.json"
    override.write_text(json.dumps({"chunks": {"local": True}}), encoding="utf-8")
    monkeypatch.setenv(CHUNKINFO_ENV_VAR, str(override))

    assert read_chunkinfo(root=tmp_path) == {"chunks": {"local": True}}


def test_read_chunkinfo_reports_a_missing_override_file(tmp_path: Path) -> None:
    with pytest.raises(CacheMissError, match="not found"):
        read_chunkinfo(override=tmp_path / "missing.json", root=tmp_path)


def test_read_chunkinfo_reports_an_override_that_is_not_an_object(tmp_path: Path) -> None:
    override = tmp_path / "local-chunkinfo.json"
    override.write_text("[1, 2]", encoding="utf-8")

    with pytest.raises(CacheMissError, match="not a JSON object"):
        read_chunkinfo(override=override, root=tmp_path)
