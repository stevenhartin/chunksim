"""Tests for the on-disk cache layer.

Every test passes an explicit `root`, so the project's real `cache/` is never
touched.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from fray_claude.cache import (
    CHUNKINFO_ENV_VAR,
    FETCHED,
    SIMULATED,
    CacheMissError,
    blob_path,
    cache_path,
    chunkinfo_source,
    claim_sim_batch,
    derived_path,
    derived_root,
    file_digest,
    list_derived,
    prune_derived,
    read_derived,
    write_derived,
    list_maps,
    project_root,
    read_blob,
    read_cache,
    read_chunkinfo,
    remove_all_simulated,
    remove_map,
    resolve_map_path,
    run_dir,
    sims_root,
    split_map_id,
    write_blob,
    write_cache,
    write_sim_run,
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


# --- simulated maps ----------------------------------------------------------


def _sim(root: Path, batch: str, index: int = 1, **payload: Any) -> Path:
    """Write one simulated run directly, without running a simulation."""
    directory = run_dir(sims_root(root) / batch, index)
    return write_sim_run(
        directory,
        map_id=f"{batch}/{directory.name}",
        data={"chunks": {"unlocked": payload or {"100": "100"}}},
        simulation={"run": directory.name, "seed": 7, "rolls": ["101"], "base_map": "fray"},
        ledger=[],
    )


def test_a_run_records_its_default_provenance(tmp_path: Path) -> None:
    envelope = json.loads(_sim(tmp_path, "Demo").read_text(encoding="utf-8"))

    assert envelope["source"] == "simulated from 'fray'"


def test_a_run_can_override_its_provenance_line(tmp_path: Path) -> None:
    # `fray unlock --cache-map` writes here too; the `source` line is the only
    # thing separating the two, `is_simulated` staying true for both.
    directory = run_dir(sims_root(tmp_path) / "Candidate", 1)
    path = write_sim_run(
        directory,
        map_id="Candidate/run-001",
        data={"chunks": {"unlocked": {"100": "100"}}},
        simulation={"run": "run-001", "origin": "unlock", "base_map": "fray"},
        ledger=[],
        source="unlock 101 from 'fray'",
    )
    envelope = json.loads(path.read_text(encoding="utf-8"))

    assert envelope["source"] == "unlock 101 from 'fray'"
    assert envelope["is_simulated"] is True
    assert read_cache("Candidate", root=tmp_path)["simulation"]["origin"] == "unlock"


def test_a_simulated_run_is_readable_by_its_full_id(tmp_path: Path) -> None:
    _sim(tmp_path, "Demo", 2)

    envelope = read_cache("Demo/run-002", root=tmp_path)

    assert envelope["is_simulated"] is True
    assert envelope["simulation"]["seed"] == 7


def test_a_one_run_batch_resolves_from_its_bare_name(tmp_path: Path) -> None:
    _sim(tmp_path, "Demo")

    assert read_cache("Demo", root=tmp_path)["map_id"] == "Demo/run-001"


def test_a_multi_run_batch_refuses_to_guess_which_run_was_meant(tmp_path: Path) -> None:
    _sim(tmp_path, "Demo", 1)
    _sim(tmp_path, "Demo", 2)

    with pytest.raises(CacheMissError, match="Demo/run-001, Demo/run-002"):
        read_cache("Demo", root=tmp_path)


def test_a_fetched_map_wins_over_a_simulated_batch_of_the_same_name(tmp_path: Path) -> None:
    write_cache("Demo", {"chunks": {"unlocked": {"1": "1"}}}, root=tmp_path)
    _sim(tmp_path, "Demo")

    assert resolve_map_path("Demo", tmp_path) == cache_path("Demo", tmp_path)


def test_the_flag_marks_fetched_maps_as_not_simulated(tmp_path: Path) -> None:
    write_cache("fray", {}, root=tmp_path)

    assert read_cache("fray", root=tmp_path)["is_simulated"] is False


@pytest.mark.parametrize(
    "map_id", ["../escape", "/etc/passwd", "a/b", "Demo/run-x", "Demo/run-001/x", ""]
)
def test_a_map_id_cannot_escape_the_cache_directory(tmp_path: Path, map_id: str) -> None:
    with pytest.raises(CacheMissError, match="invalid map id|expected"):
        resolve_map_path(map_id, tmp_path)


def test_split_map_id_accepts_a_bare_name_and_a_run(tmp_path: Path) -> None:
    assert split_map_id("Demo") == ("Demo", None)
    assert split_map_id("Demo/run-012") == ("Demo", "run-012")


def test_claiming_a_taken_batch_name_appends_a_suffix(tmp_path: Path) -> None:
    first = claim_sim_batch("Demo", tmp_path)
    second = claim_sim_batch("Demo", tmp_path)
    third = claim_sim_batch("Demo", tmp_path)

    assert [d.name for d in (first, second, third)] == ["Demo", "Demo-2", "Demo-3"]
    assert all(d.is_dir() for d in (first, second, third))


def test_claiming_avoids_a_name_a_fetched_map_already_holds(tmp_path: Path) -> None:
    """Otherwise `--map Demo` would mean two different things."""
    write_cache("Demo", {}, root=tmp_path)

    assert claim_sim_batch("Demo", tmp_path).name == "Demo-2"


def test_listing_reports_both_kinds(tmp_path: Path) -> None:
    write_cache("fray", {"chunks": {"unlocked": {"1": "1", "2": "2"}}}, root=tmp_path)
    write_blob("chunkinfo", {}, "test", root=tmp_path)
    _sim(tmp_path, "Demo")

    entries = {entry.map_id: entry for entry in list_maps(tmp_path)}

    assert entries["fray"].kind == FETCHED
    assert entries["fray"].unlocked_chunks == 2
    assert entries["Demo"].kind == SIMULATED
    assert entries["Demo"].runs == 1
    # The chunkinfo/tasks-map blobs are not maps.
    assert "chunkinfo" not in entries


def test_listing_can_expand_a_batch_into_its_runs(tmp_path: Path) -> None:
    _sim(tmp_path, "Demo", 1)
    _sim(tmp_path, "Demo", 2)

    ids = [entry.map_id for entry in list_maps(tmp_path, expand_runs=True)]

    assert ids == ["Demo", "Demo/run-001", "Demo/run-002"]


def test_removing_a_single_run_leaves_the_rest_of_the_batch(tmp_path: Path) -> None:
    _sim(tmp_path, "Demo", 1)
    _sim(tmp_path, "Demo", 2)

    remove_map("Demo/run-001", tmp_path)

    assert not (sims_root(tmp_path) / "Demo" / "run-001").exists()
    assert read_cache("Demo", root=tmp_path)["map_id"] == "Demo/run-002"


def test_removing_a_batch_takes_all_of_its_runs(tmp_path: Path) -> None:
    _sim(tmp_path, "Demo", 1)
    _sim(tmp_path, "Demo", 2)

    remove_map("Demo", tmp_path)

    assert not (sims_root(tmp_path) / "Demo").exists()


def test_removing_a_fetched_map_needs_saying_so(tmp_path: Path) -> None:
    write_cache("fray", {}, root=tmp_path)

    with pytest.raises(CacheMissError, match="--include-fetched"):
        remove_map("fray", tmp_path)
    assert cache_path("fray", tmp_path).is_file()

    remove_map("fray", tmp_path, include_fetched=True)
    assert not cache_path("fray", tmp_path).is_file()


def test_cleaning_removes_simulations_and_nothing_else(tmp_path: Path) -> None:
    write_cache("fray", {}, root=tmp_path)
    write_blob("chunkinfo", {"a": 1}, "test", root=tmp_path)
    _sim(tmp_path, "Demo")
    _sim(tmp_path, "Other")

    assert remove_all_simulated(tmp_path) == ["Demo", "Other"]
    assert cache_path("fray", tmp_path).is_file()
    assert blob_path("chunkinfo", tmp_path).is_file()
    assert list(sims_root(tmp_path).iterdir()) == []


# --- the derived cache -------------------------------------------------------

_KEY = "a" * 64 + ".pkl.zst"
_OTHER_KEY = "b" * 64 + ".pkl.zst"


def test_a_derived_entry_round_trips(tmp_path: Path) -> None:
    write_derived(_KEY, b"payload", root=tmp_path)

    assert read_derived(_KEY, root=tmp_path) == b"payload"


def test_a_missing_derived_entry_is_a_miss_not_an_error(tmp_path: Path) -> None:
    """Every caller's answer to a miss is the same - compute it - so this
    returns `None` rather than raising."""
    assert read_derived(_KEY, root=tmp_path) is None


def test_reading_a_derived_entry_refreshes_its_last_access(tmp_path: Path) -> None:
    """mtime *is* the last-accessed field: `prune_derived` reads it, and one
    `os.utime` needs no lock or ledger to stay correct across processes."""
    path = write_derived(_KEY, b"payload", root=tmp_path)
    stale = datetime.now(UTC) - timedelta(days=30)
    os.utime(path, (stale.timestamp(), stale.timestamp()))

    read_derived(_KEY, root=tmp_path)

    assert list_derived(tmp_path)[0].accessed_at > stale


def test_rewriting_a_derived_entry_leaves_one_valid_file(tmp_path: Path) -> None:
    """Two workers computing the same key wrote the same bytes, so the last
    atomic rename winning is correct either way - and neither leaves a
    temp file behind."""
    write_derived(_KEY, b"first", root=tmp_path)
    write_derived(_KEY, b"second", root=tmp_path)

    assert read_derived(_KEY, root=tmp_path) == b"second"
    assert [p.name for p in derived_root(tmp_path).iterdir()] == [_KEY]


@pytest.mark.parametrize("key", ["../escape.pkl", "/etc/passwd", "nothex.pkl", "abc", ""])
def test_a_derived_key_cannot_escape_the_cache_directory(tmp_path: Path, key: str) -> None:
    with pytest.raises(CacheMissError, match="invalid derived-cache key"):
        derived_path(key, tmp_path)


def test_listing_derived_entries_orders_by_least_recently_used(tmp_path: Path) -> None:
    write_derived(_KEY, b"old", root=tmp_path)
    stale = (datetime.now(UTC) - timedelta(days=3)).timestamp()
    os.utime(derived_path(_KEY, tmp_path), (stale, stale))
    write_derived(_OTHER_KEY, b"new", root=tmp_path)
    # Junk in the directory is not an entry.
    (derived_root(tmp_path) / "notes.txt").write_text("hi", encoding="utf-8")

    assert [entry.key for entry in list_derived(tmp_path)] == [_KEY, _OTHER_KEY]
    assert list_derived(tmp_path)[0].size == 3


def test_pruning_drops_entries_by_last_access_not_creation(tmp_path: Path) -> None:
    """An entry read every day is worth keeping however old it is."""
    write_derived(_KEY, b"stale", root=tmp_path)
    stale = (datetime.now(UTC) - timedelta(days=30)).timestamp()
    os.utime(derived_path(_KEY, tmp_path), (stale, stale))
    write_derived(_OTHER_KEY, b"fresh", root=tmp_path)

    removed = prune_derived(tmp_path, max_age_days=14)

    assert [entry.key for entry in removed] == [_KEY]
    assert [entry.key for entry in list_derived(tmp_path)] == [_OTHER_KEY]


def test_pruning_with_no_age_empties_the_cache(tmp_path: Path) -> None:
    write_derived(_KEY, b"a", root=tmp_path)
    write_derived(_OTHER_KEY, b"b", root=tmp_path)

    assert len(prune_derived(tmp_path)) == 2
    assert list_derived(tmp_path) == []


def test_pruning_an_absent_cache_is_not_an_error(tmp_path: Path) -> None:
    assert prune_derived(tmp_path) == []


def test_file_digest_tracks_content(tmp_path: Path) -> None:
    path = tmp_path / "export.json"
    path.write_text("{}", encoding="utf-8")
    first = file_digest(path)
    path.write_text('{"a": 1}', encoding="utf-8")

    assert first != file_digest(path)
    assert file_digest(tmp_path / "missing.json") == ""


def test_chunkinfo_source_names_the_file_read_chunkinfo_would_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(CHUNKINFO_ENV_VAR, raising=False)
    assert chunkinfo_source(root=tmp_path) == blob_path("chunkinfo", tmp_path)

    override = tmp_path / "raw.json"
    assert chunkinfo_source(override, tmp_path) == override

    monkeypatch.setenv(CHUNKINFO_ENV_VAR, str(tmp_path / "env.json"))
    assert chunkinfo_source(root=tmp_path) == tmp_path / "env.json"
