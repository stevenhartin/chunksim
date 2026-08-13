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

from fray_claude.store.cache import (
    CHUNKINFO_BLOB_NAME,
    _migrated,
    migrate_layout,
    kind_root,
    claim_batch,
    COMPUTED_KINDS,
    EDITED,
    section_overlay_path,
    write_asset_at,
    write_gui_window,
    gui_settings_path,
    gui_window_path,
    read_gui_settings,
    write_gui_settings,
    WIKI_RATES_BLOB_NAME,
    TILE_VERSION_BLOB_NAME,
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
    overrides_path,
    reference_stamp,
    list_derived,
    prune_derived,
    read_derived,
    read_tile_version,
    tile_version_override,
    write_tile_version,
    write_derived,
    list_maps,
    project_root,
    read_blob,
    read_cache,
    read_chunkinfo,
    remove_computed,
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

    assert path == tmp_path / "missing" / "cache" / "maps" / "fetched" / "fray.json"
    assert path.is_file()


def test_cache_path_is_named_after_the_map(tmp_path: Path) -> None:
    assert cache_path("other", root=tmp_path) == tmp_path / "cache" / "maps" / "fetched" / "other.json"


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
    assert blob_path("tasks_map", root=tmp_path) == tmp_path / "cache" / "reference" / "tasks_map.json"


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


def test_an_overridden_envelope_is_unwrapped_to_its_export(tmp_path: Path) -> None:
    """**The project's sharpest footgun, closed.**

    `cache/reference/chunkinfo.json` is the file anyone naturally reaches for,
    and it is the envelope rather than the export. Pointing the override at it
    used to return the envelope, whose keys contain no `chunks` and no
    `sections`, so every accessor answered "absent" and the derivation came out
    empty and plausible. The documented workaround was to extract the inner
    object into a temp file by hand.
    """
    export: dict[str, Any] = {"chunks": {"12850": {}}, "sections": {}}
    write_blob("chunkinfo", export, "https://example.invalid/x.json", root=tmp_path)
    envelope = blob_path("chunkinfo", root=tmp_path)

    assert read_chunkinfo(override=envelope, root=tmp_path) == export


def test_an_export_carrying_a_data_branch_is_not_unwrapped(tmp_path: Path) -> None:
    """The unwrap matches the envelope's **whole** key set, not "has a `data`
    key" - a looser rule would be a new version of the bug it replaces."""
    export: dict[str, Any] = {"chunks": {}, "data": {"chunks": {"wrong": True}}}
    override = tmp_path / "raw.json"
    override.write_text(json.dumps(export), encoding="utf-8")

    assert read_chunkinfo(override=override, root=tmp_path) == export


def test_an_overridden_map_is_refused_rather_than_unwrapped(tmp_path: Path) -> None:
    """A map is an envelope too, and its contents are not an export. Unwrapping
    it would trade one silent wrong answer for another."""
    write_cache("fray", {"chunks": {"unlocked": {}}}, root=tmp_path)

    with pytest.raises(CacheMissError, match="cached map, not a chunk export"):
        read_chunkinfo(override=cache_path("fray", tmp_path), root=tmp_path)


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

    assert remove_computed(tmp_path) == ["Demo", "Other"]
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


def test_an_asset_write_is_atomic_and_leaves_no_temp_file(tmp_path: Path) -> None:
    """Temp-file-plus-rename, so a reader never sees a partial PNG.

    The path comes in already built, because every asset left here is a nested
    one whose name `section_overlay_path` or `skill_icon_path` has validated -
    the world map, which was the one asset with a constant name, is not stored
    at all any more.
    """
    target = section_overlay_path("12850-1", root=tmp_path)
    path = write_asset_at(target, b"\x89PNG payload")

    assert path.read_bytes() == b"\x89PNG payload"
    assert [p.name for p in path.parent.iterdir()] == ["12850-1.png"]


def test_a_tile_version_round_trips_with_its_age(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The GUI remembers which render to ask for, so a restart does not scrape.

    The *age* comes back rather than a verdict: whether an old version is worth
    re-scraping is a network decision, and `cache.py` makes none.
    """
    monkeypatch.delenv("FRAY_TILE_VERSION", raising=False)
    write_tile_version("2026-07-29_a", "https://example.invalid", root=tmp_path)

    version, age = read_tile_version(root=tmp_path)

    assert version == "2026-07-29_a"
    assert age < 1.0
    assert tile_version_override() is None

    monkeypatch.setenv("FRAY_TILE_VERSION", "2020-01-01_z")
    assert tile_version_override() == "2020-01-01_z"


def test_a_tile_version_blob_is_not_a_map(tmp_path: Path) -> None:
    """It lives in `cache/` beside the maps and is emphatically not one."""
    write_cache("fray", {"chunks": {"unlocked": {}}}, root=tmp_path)
    write_tile_version("2026-07-29_a", "https://example.invalid", root=tmp_path)

    assert [entry.map_id for entry in list_maps(root=tmp_path)] == ["fray"]
    assert TILE_VERSION_BLOB_NAME == "tile_version"


def test_the_blobs_beside_the_maps_are_not_maps(tmp_path: Path) -> None:
    """`cache/` holds JSON that is not a map, and listing it as one is silent.

    `wiki_rates` and the GUI's window file both ended up in the map picker,
    where choosing one fails somewhere much further down. The exclusion is
    built from the blob-name constants so a new blob cannot be forgotten.
    """
    write_cache("fray", {"chunks": {"unlocked": {"12850": "12850"}}}, root=tmp_path)
    write_blob(WIKI_RATES_BLOB_NAME, {"rates": {}}, "https://example.invalid", root=tmp_path)
    write_gui_window({"width": 800, "height": 600, "x": 0, "y": 0}, root=tmp_path)

    assert [entry.map_id for entry in list_maps(root=tmp_path)] == ["fray"]


# --- the layout ------------------------------------------------------------


def test_only_maps_are_listed_as_maps(tmp_path: Path) -> None:
    """**The invariant the layout exists for.**

    `list_maps` used to glob `cache/*.json` and skip the names it knew were
    not maps, so a new blob had to be *remembered* or it turned up in the
    picker as a map that failed the moment it was chosen - `wiki_rates` and
    the GUI's window file were both missed exactly that way. It now reads a
    directory that holds one kind of thing, so there is no list to forget.
    """
    write_cache("fray", {"chunks": {"unlocked": {"1": "1"}}}, root=tmp_path)
    write_blob(CHUNKINFO_BLOB_NAME, {"chunks": {}}, "https://example.invalid", root=tmp_path)
    write_blob(WIKI_RATES_BLOB_NAME, {"rates": {}}, "https://example.invalid", root=tmp_path)
    write_tile_version("2026-07-29_a", "https://example.invalid", root=tmp_path)
    write_gui_window({"width": 8, "height": 8, "x": 0, "y": 0}, root=tmp_path)

    assert [entry.map_id for entry in list_maps(root=tmp_path)] == ["fray"]
    # And every one of those blobs really was written, under `reference/`.
    assert (tmp_path / "cache" / "reference" / "chunkinfo.json").is_file()
    assert (tmp_path / "cache" / "reference" / "wiki_rates.json").is_file()
    assert (tmp_path / "cache" / "gui" / "window.json").is_file()
    assert not list((tmp_path / "cache").glob("*.json"))


def test_each_kind_has_its_own_directory(tmp_path: Path) -> None:
    """Three kinds, three directories, and a name belongs to one of them."""
    assert kind_root(FETCHED, tmp_path).name == "fetched"
    assert kind_root(SIMULATED, tmp_path).name == "simulated"
    assert kind_root(EDITED, tmp_path).name == "edited"
    assert kind_root(FETCHED, tmp_path).parent.name == "maps"

    with pytest.raises(ValueError, match="unknown map kind"):
        kind_root("guessed", tmp_path)


def test_a_batch_name_is_claimed_across_every_kind(tmp_path: Path) -> None:
    """`--map foo` takes a bare name, so only one thing may answer to it.

    Claiming per-kind would let a simulated `foo` and an edited `foo` both
    exist, and `resolve_map_path` would have to guess which was meant.
    """
    write_cache("fray", {"chunks": {}}, root=tmp_path)
    first = claim_batch("run", tmp_path, kind=SIMULATED)
    second = claim_batch("run", tmp_path, kind=EDITED)
    fetched_clash = claim_batch("fray", tmp_path, kind=SIMULATED)

    assert first.name == "run"
    assert second.name == "run-2"          # taken by the simulated one
    assert fetched_clash.name == "fray-2"  # taken by the fetched map


def test_removing_computed_maps_leaves_the_fetched_ones(tmp_path: Path) -> None:
    write_cache("fray", {"chunks": {}}, root=tmp_path)
    claim_batch("rolled", tmp_path, kind=SIMULATED)
    claim_batch("added", tmp_path, kind=EDITED)

    removed = remove_computed(root=tmp_path)

    assert sorted(removed) == ["added", "rolled"]
    assert [entry.map_id for entry in list_maps(root=tmp_path)] == ["fray"]


def test_a_pre_split_cache_is_migrated_rather_than_refetched(tmp_path: Path) -> None:
    """Some of what is down there is expensive: the chunk export is a 10MB
    download and `assets/` is fifteen hundred files pulled one at a time.

    A fetched map is identified by elimination here - which is the reasoning
    the new layout retires - and that is exactly why it happens once, on
    migration, rather than on every read.
    """
    old = tmp_path / "cache"
    (old / "sims" / "batch" / "run-001").mkdir(parents=True)
    (old / "sims" / "batch" / "run-001" / "map.json").write_text(
        json.dumps({"map_id": "batch/run-001", "is_simulated": True, "data": {"chunks": {}}})
    )
    (old / "fray.json").write_text(json.dumps({"map_id": "fray", "data": {"chunks": {}}}))
    (old / "chunkinfo.json").write_text(json.dumps({"name": "chunkinfo", "data": {}}))
    (old / "gui-window.json").write_text(json.dumps({"width": 800}))

    moved = migrate_layout(tmp_path)

    assert moved, "nothing was migrated"
    assert (old / "maps" / "fetched" / "fray.json").is_file()
    assert (old / "maps" / "simulated" / "batch" / "run-001" / "map.json").is_file()
    assert (old / "reference" / "chunkinfo.json").is_file()
    assert (old / "gui" / "window.json").is_file()
    assert not (old / "fray.json").exists()

    # And an envelope written before `kind` existed still reads as one.
    assert read_cache("fray", root=tmp_path)["kind"] == FETCHED
    assert read_cache("batch/run-001", root=tmp_path)["kind"] == SIMULATED


def test_migrating_twice_changes_nothing(tmp_path: Path) -> None:
    """It sits on the path of every cache read, so it has to be idempotent."""
    write_cache("fray", {"chunks": {}}, root=tmp_path)
    _migrated.discard((tmp_path / "cache").resolve())
    _migrated.discard(tmp_path / "cache")

    assert migrate_layout(tmp_path) == []
    assert (tmp_path / "cache" / "maps" / "fetched" / "fray.json").is_file()


def test_every_envelope_written_today_states_its_kind(tmp_path: Path) -> None:
    """`_with_kind` exists for caches written before the field did.

    If a fresh write still needed it, the field would be decoration and the
    inference would be the real contract - which is exactly the arrangement
    `is_simulated` had, and the reason a rolled map and an unlocked one could
    not be told apart.
    """
    path = write_cache("fray", {"chunks": {}}, root=tmp_path)

    assert json.loads(path.read_text())["kind"] == FETCHED

    directory = claim_batch("rolled", tmp_path, kind=SIMULATED)
    run = run_dir(directory, 1)
    write_sim_run(
        run,
        map_id="rolled/run-001",
        data={"chunks": {}},
        simulation={"base_map": "fray"},
        ledger=[],
        kind=SIMULATED,
    )

    assert json.loads((run / "map.json").read_text())["kind"] == SIMULATED


def test_a_fourth_kind_costs_one_tuple_entry(tmp_path: Path) -> None:
    """**The claim this layout was built on, now cashed.** `EDITED` was added
    for the GUI's edit mode by naming it in `COMPUTED_KINDS` and nothing else -
    and removal, resolution, listing and cross-kind name claiming all followed.

    A name is claimed across *every* kind, so `--map foo` never has to guess
    which directory meant it; the clash suffixes rather than collides.
    """
    assert EDITED in COMPUTED_KINDS
    assert kind_root(EDITED, tmp_path).name == "edited"

    first = claim_batch("demo", tmp_path, kind=EDITED)
    second = claim_batch("demo", tmp_path, kind=SIMULATED)

    assert first.name == "demo"
    assert second.name == "demo-2"


def test_the_retired_unlocked_kind_migrates_into_edited(tmp_path: Path) -> None:
    """**Two kinds that decided nothing become one.** `unlocked` and `edited`
    both mean "this project made this by hand from another map"; they removed
    the same way, browsed the same way, and the picker saying which made a
    reader work out a distinction with no consequence.

    A per-batch move rather than a directory rename, since both may exist -
    and a name cannot clash, because `_name_taken` has always claimed across
    every kind.
    """
    legacy = tmp_path / "cache" / "maps" / "unlocked" / "Candidate" / "run-001"
    legacy.mkdir(parents=True)
    (legacy / "map.json").write_text("{}", encoding="utf-8")
    (tmp_path / "cache" / "maps" / "edited" / "kept").mkdir(parents=True)

    moved = migrate_layout(tmp_path)

    assert "unlocked/Candidate -> edited/Candidate" in moved
    assert (tmp_path / "cache" / "maps" / "edited" / "Candidate" / "run-001" / "map.json").is_file()
    assert (tmp_path / "cache" / "maps" / "edited" / "kept").is_dir()
    assert not (tmp_path / "cache" / "maps" / "unlocked").exists()
    assert "unlocked" not in COMPUTED_KINDS


def test_reference_stamp_moves_when_a_blob_is_written(tmp_path: Path) -> None:
    """**The guard on the GUI's reference memo, and the only thing under it.**

    `Derivations.reference` keeps the rate scrape, the recipes and the
    checked-in overrides in memory for the life of the server, and those
    overrides are a file someone edits by hand. So the memo is validated
    against this rather than merely remembered - a stale copy would not just
    be old, it would key the enrichment cache, filing fresh numbers under a
    pre-edit key.
    """
    empty = reference_stamp(tmp_path)
    assert empty == ((0, 0), (0, 0), (0, 0)), "nothing on disk stamps as absent"

    write_blob(WIKI_RATES_BLOB_NAME, {"a": 1}, "test", tmp_path)
    written = reference_stamp(tmp_path)
    assert written != empty

    overrides = overrides_path(tmp_path)
    overrides.parent.mkdir(parents=True, exist_ok=True)
    overrides.write_text(json.dumps({"levels": {"Attack": 70}}), encoding="utf-8")
    assert reference_stamp(tmp_path) != written


def test_reference_stamp_notices_a_same_size_edit(tmp_path: Path) -> None:
    """Size alone would miss this, which is why the stamp carries mtime too:
    correcting a rate in place is exactly the edit that keeps the byte count.
    """
    overrides = overrides_path(tmp_path)
    overrides.parent.mkdir(parents=True, exist_ok=True)
    overrides.write_text('{"levels": {"Attack": 70}}', encoding="utf-8")
    before = reference_stamp(tmp_path)

    os.utime(overrides, ns=(0, 0))
    overrides.write_text('{"levels": {"Attack": 71}}', encoding="utf-8")

    assert reference_stamp(tmp_path) != before


def test_settings_read_as_empty_before_anything_saves_them(tmp_path: Path) -> None:
    """A first run is not a fault - the caller's answer to "nothing saved" is
    `gui.settings.DEFAULTS`."""
    assert read_gui_settings(tmp_path) == {}


def test_settings_round_trip(tmp_path: Path) -> None:
    write_gui_settings({"hours_scale": "linear"}, tmp_path)
    assert read_gui_settings(tmp_path) == {"hours_scale": "linear"}


def test_settings_live_beside_the_window_geometry_and_not_among_the_maps(
    tmp_path: Path,
) -> None:
    """`cache/maps/` holds maps and nothing else holds maps - a preference is
    not one, and must never turn up in the picker."""
    write_cache("fray", {"chunks": {}}, root=tmp_path)
    write_gui_settings({"hours_scale": "log"}, tmp_path)
    assert gui_settings_path(tmp_path).parent == gui_window_path(tmp_path).parent
    assert [entry.map_id for entry in list_maps(root=tmp_path)] == ["fray"]


def test_an_unreadable_settings_file_reads_as_empty(tmp_path: Path) -> None:
    """Tolerant on the way in; `gui.settings.sanitise` is what refuses."""
    path = gui_settings_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json at all", encoding="utf-8")
    assert read_gui_settings(tmp_path) == {}

