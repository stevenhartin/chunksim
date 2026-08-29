"""What the wheel must contain, asserted without building one.

**This file exists because the development loop stopped building wheels.**
`pipx install --editable` means `fray` on `PATH` imports the checkout directly,
which is the point - there is nothing to rebuild and nothing to forget. What it
also means is that `[tool.setuptools.packages.find]` is no longer exercised on
every change, and that discovery has one silent failure mode: **a directory
without an `__init__.py` is a perfectly good import target for the editable
install and is simply absent from the wheel.** The first symptom would be an
`ImportError` on someone else's machine.

So the invariants the build used to check by accident are checked here on
purpose, in milliseconds and with no `dist/` involved. Building a wheel is still
worth doing before a release - `python -m zipfile -l dist/*.whl` is the
end-to-end version of these assertions - but it is no longer the only thing
standing between a new subdirectory and a broken install.

Named for the distribution rather than for a module, since that is what it is
about; there is no `packaging.py` to sit beside.
"""

from __future__ import annotations

import importlib.metadata as metadata
import os
import re
import sys
import tomllib
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
PACKAGE = SRC / "chunksim"
PROJECT = SRC.parent
# `setup.py` lives at the project root, which is not on the path for a
# test run from anywhere else - and it is the only module here that is
# imported for what it *declares* rather than for what it does.
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def _source_dirs() -> list[Path]:
    """Every directory under `src/` that holds Python this project wrote."""
    return sorted(
        {
            path.parent
            for path in PACKAGE.rglob("*.py")
            if "__pycache__" not in path.parts
        }
    )


def test_every_source_directory_is_an_importable_package() -> None:
    """The one failure mode an editable install hides.

    `packages.find` discovers packages, not directories: a subpackage that
    forgot its `__init__.py` imports fine from a checkout (Python 3 allows
    namespace packages) and is then missing from every wheel built afterwards.
    """
    missing = [
        directory.relative_to(SRC)
        for directory in _source_dirs()
        if not (directory / "__init__.py").is_file()
    ]

    assert missing == [], f"no __init__.py, so absent from the wheel: {missing}"


def test_the_guis_resources_are_where_package_data_says_they_are() -> None:
    """`package-data` is a glob in `pyproject.toml`, matched at build time.

    Nothing at runtime notices if it stops matching - the editable install
    serves the files from the checkout either way - so the wheel would ship a
    GUI with no HTML and the tests would all pass.
    """
    with open(PACKAGE.parent.parent / "pyproject.toml", "rb") as handle:
        config = tomllib.load(handle)
    globs = config["tool"]["setuptools"]["package-data"]["chunksim"]

    assert "gui/resources/*" in globs
    served = {path.name for path in (PACKAGE / "gui" / "resources").iterdir()}
    assert {"index.html", "app.js", "style.css"} <= served


def test_the_heuristics_json_ships_with_the_package() -> None:
    """Both files under `heuristics/` are numbers the estimator spends.

    Same trap as the GUI's resources and a quieter one: an editable install
    reads them out of the checkout whatever the glob says, so a wheel that
    stopped matching would ship an estimator that prices every skill
    differently and says nothing about why. `overrides.json` is the hand
    corrections; `gathering.json` is the scraped tables behind
    `costing/gathering.py`, and without it that whole model goes quiet - which
    is a supported state, and not one a packaging mistake should reach.
    """
    with open(PACKAGE.parent.parent / "pyproject.toml", "rb") as handle:
        config = tomllib.load(handle)
    globs = config["tool"]["setuptools"]["package-data"]["chunksim"]

    assert "heuristics/*.json" in globs
    shipped = {path.name for path in (PACKAGE / "heuristics").iterdir()}
    assert {"overrides.json", "gathering.json"} <= shipped


def test_both_console_scripts_resolve() -> None:
    """`chunksim` and `chunksim-gui` are dotted strings in `pyproject.toml` that nothing
    else checks. A module rename that misses them is a `pipx install` that
    succeeds and two commands that fail on their first line."""
    try:
        entries = metadata.distribution("chunksim").entry_points
    except metadata.PackageNotFoundError:  # pragma: no cover - fresh clone
        pytest.skip("chunksim is not installed into this environment")

    scripts = {entry.name: entry for entry in entries if entry.group == "console_scripts"}

    assert set(scripts) == {"chunksim", "chunksim-gui"}
    for entry in scripts.values():
        assert callable(entry.load()), f"{entry.name} -> {entry.value} does not resolve"


def _installer_script() -> str:
    return (SRC.parent / "packaging" / "chunksim.iss").read_text(encoding="utf-8")


def test_the_installer_is_named_what_the_updater_looks_for() -> None:
    """**A cross-file contract with nothing else enforcing it.**

    `_installer_asset` finds the download among a release's assets by matching
    `INSTALLER_ASSET_SUFFIX` against each name. Inno Setup decides that name.
    Rename it on either side and the release still publishes, the check still
    reports an update, and the Download & Install button silently never
    appears - which is the sort of failure only a real release would surface.
    """
    from chunksim.remote.api import INSTALLER_ASSET_SUFFIX

    match = re.search(r"OutputBaseFilename=(\S+)", _installer_script())

    assert match is not None
    produced = match.group(1).replace("{#AppName}", "chunksim").replace("{#AppVersion}", "0.1.0")
    assert (produced + ".exe").endswith(INSTALLER_ASSET_SUFFIX)


def test_the_installer_version_matches_the_project() -> None:
    """The installer names its own version, and `read_build` reads the wheel's.
    A drift shows up as an update that installs itself forever, or never."""
    with open(SRC.parent / "pyproject.toml", "rb") as handle:
        version = tomllib.load(handle)["project"]["version"]

    match = re.search(r'#define AppVersion "([^"]+)"', _installer_script())

    assert match is not None and match.group(1) == version


def test_the_installer_upgrades_rather_than_stacking() -> None:
    """A fixed `AppId` is what makes a new version replace the old one instead
    of leaving two entries in Add/Remove Programs - and what lets the in-app
    updater hand over with `/SILENT` and get a replacement."""
    script = _installer_script()

    assert re.search(r"^AppId=\{\{[0-9A-F-]{36}\}?$", script, re.MULTILINE), "AppId must be a fixed GUID"


def test_uninstalling_asks_before_deleting_anyones_maps() -> None:
    """Fetched maps re-download; simulated batches and hand-edited maps are the
    user's own work and nothing can recompute them. Deleting the data directory
    silently would be the most destructive thing this installer could do."""
    script = _installer_script()

    assert "localappdata}\\chunksim" in script
    assert "MB_DEFBUTTON2" in script, "the safe answer must be the default"
    assert "DelTree" in script and "mbConfirmation" in script


def test_the_wiki_derived_config_ships_with_the_package() -> None:
    """**The estimator must not need a wiki fetch to price anything.**

    `chunksim heuristics` and `chunksim recipes` reach ~200 wiki pages to
    answer questions that only move on a game update, so their output is
    config rather than cache: checked in, packaged, and regenerated by a
    developer. Measured before the move, 1,229 of 2,411 reachable training
    methods priced *only* when the fetched blobs were present.

    Two halves, and both matter. The files have to be there, and the glob in
    `pyproject.toml` has to carry them into the wheel - `heuristics/*.json`
    does, which is why adding one needs no packaging change and why this
    asserts the glob rather than a list of names.
    """
    import tomllib

    from chunksim.store import cache

    for name in cache.SHIPPED_BLOB_NAMES:
        assert cache.packaged_blob(name).is_file(), f"{name} does not ship"

    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    globs = config["tool"]["setuptools"]["package-data"]["chunksim"]
    assert "heuristics/*.json" in globs


def test_a_shipped_blob_is_read_from_the_package_not_the_cache(tmp_path: Path) -> None:
    """A cache directory with no wiki blobs in it must still price, which is
    the whole point of shipping them. `blob_source` answers with the packaged
    copy only for an *installed* build - a checkout, real or a test fixture,
    is a closed world and reads its own."""
    from chunksim.store import cache

    for name in cache.SHIPPED_BLOB_NAMES:
        # No checkout and no cache copy under `tmp_path`, so an installed
        # build falls through to what it shipped with.
        assert cache.blob_source(name).is_file()
        # ...but an explicit root never reaches the developer's real config.
        assert not cache.blob_source(name, tmp_path).is_file()


def _setup_declares() -> tuple[str, tuple[str, ...], str]:
    """`(COMPILE_ENV, COMPILED, source)` read out of `setup.py` without running it.

    **Parsed rather than imported**, for the same reason `test_gui_contract.py`
    reads `app.js` as text: the file declares a contract, and importing it here
    would need `setuptools` in the test venv - which this project deliberately
    does not put there. `ast` reads the declaration without executing a line.
    """
    import ast

    source = (PROJECT / "setup.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    found: dict[str, object] = {}
    for node in tree.body:
        # Annotated and bare assignments alike - `COMPILED` carries a type and
        # `COMPILE_ENV` does not, and which is which is not this test's point.
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is not None:
                found[node.target.id] = ast.literal_eval(node.value)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found[target.id] = ast.literal_eval(node.value)
    return str(found["COMPILE_ENV"]), tuple(found["COMPILED"]), source  # type: ignore[arg-type]


def test_compiling_is_off_unless_asked_for() -> None:
    """**The development loop depends on this default.**

    An editable install's whole value is that a Python edit is live
    immediately (CLAUDE.md). A compiled module is a `.so` that shadows the
    `.py` beside it, so a build-on-install would turn "edit, reload the tab"
    into "edit, rebuild, reload the tab" - and would do it *silently*, because
    the stale extension still imports and still answers.
    """
    env, _, source = _setup_declares()

    assert env == "CHUNKSIM_COMPILE"
    # The gate is a positive opt-in, not a negative opt-out: anything but an
    # explicit `1` has to leave the build pure.
    assert 'os.environ.get(COMPILE_ENV) != "1"' in source
    assert "return []" in source
    # And the import that needs a type checker lives behind that gate, so an
    # ordinary `pip install` never requires mypy to be present.
    gate = source.index('!= "1"')
    assert source.index("from mypyc.build import mypycify") > gate


def test_the_item_walk_is_never_compiled() -> None:
    """**Measured, and the opposite of what was expected.**

    `costing/estimate.py` compiled runs at **10.26s a roll against 2.71s** -
    3.8x *slower* - and on its own accounted for the whole of a 3.5x
    regression when a first attempt compiled it alongside the rest. The item
    walk is a fixpoint over tuple-keyed dicts of small frozen objects, and
    CPython 3.14's specialising interpreter handles that shape better than
    mypyc does.

    Pinned rather than left as a comment because the module is the hottest
    thing in the project by call count, which makes it the obvious candidate
    for exactly the change that makes everything four times slower.
    """
    _, compiled, _ = _setup_declares()

    assert "src/chunksim/costing/estimate.py" not in compiled
    # `pipeline.py` is excluded for an unrelated reason worth keeping apart:
    # three tests monkeypatch `_MAX_AREA_PASSES`, and a compiled module's
    # attributes are read-only.
    assert "src/chunksim/derive/pipeline.py" not in compiled


def test_every_compiled_module_exists() -> None:
    """A path that has moved would not fail the build - `mypycify` would
    simply compile nothing under that name, and the wheel would be quietly
    slower than it claims to be."""
    _, compiled, _ = _setup_declares()

    assert compiled
    for path in compiled:
        assert (PROJECT / path).is_file(), path


def test_a_compiled_frozen_dataclass_can_still_be_unpickled() -> None:
    """**The trap `model/pickling.py` exists for**, asserted on the classes
    that actually cross a pickle.

    A compiled `@dataclass(frozen=True)` has no `__dict__`, so pickle restores
    state with `setattr` and the frozen guard raises - on the *load*, long
    after the dump. Here that meant `derived_cache.decode` returning `None`
    for every entry it had just written, with nothing else complaining.

    Asserted through a real round trip rather than by checking `__reduce__`
    exists, since the point is that the object comes back whole.
    """
    import pickle

    from chunksim.derive.challenges import ChallengeResult
    from chunksim.derive.sources import SourceIndex

    result = ChallengeResult(valid={"Slayer": {"a": True}}, unsupported=frozenset({"x"}))
    index = SourceIndex(
        items={"Bones": {"Cow": "primary-drop"}}, objects={}, monsters={},
        npcs={}, shops={}, drop_rates={},
    )
    for original in (result, index):
        assert pickle.loads(pickle.dumps(original)) == original
        # Constructor order, not field order by luck: a reduce built from a
        # hand-written tuple would pass the equality above and still drop a
        # field added later.
        assert original.__reduce__()[1] == tuple(
            getattr(original, name) for name in original.__dataclass_fields__
        )


def test_the_windows_installer_ships_compiled_unless_told_not_to() -> None:
    """**The installer is where compiling actually reaches a user.**

    `build.bat` runs the whole build on a Windows machine, so the wheel it
    ships is built there and can compile there - which is the difference
    between a released installer that is 22% faster a roll and one that is
    not. The flag exists for a build host without a C toolchain, and has to be
    asked for.
    """
    bat = (PROJECT / "packaging" / "build.bat").read_text(encoding="utf-8")
    builder = (PROJECT / "packaging" / "build_windows.py").read_text(encoding="utf-8")

    assert '"%~1"=="/nocompile"' in bat
    assert 'set "NOCOMPILE=--no-compile"' in bat
    assert "%DPSARG% %NOCOMPILE%" in bat, "the flag has to reach build_windows.py"
    # Named before the build starts rather than surfacing as a compiler error
    # three minutes into the payload - the same discipline the `build` check
    # above it follows.
    assert "import mypyc" in bat
    assert "--no-compile" in builder


def test_only_chunksims_own_wheel_is_compiled() -> None:
    """The measurement behind `setup.py`'s module list is this project's.
    Compiling `osrs-dps` on the strength of it would be a guess about someone
    else's hot loop, which is a question to ask separately."""
    builder = (PROJECT / "packaging" / "build_windows.py").read_text(encoding="utf-8")

    assert "build_dists(PROJECT, compile_ext=not args.no_compile)" in builder
    assert "build_dists(args.dps_checkout)" in builder


def test_a_payload_that_lost_its_extensions_is_a_build_failure() -> None:
    """**Compiling fails silently when it fails to *apply*.** The `.py` beside
    a missing extension imports perfectly well and answers correctly - just
    slower - so nothing but a check like this notices that the installer being
    shipped is not the one that was measured.

    The same reasoning `verify_payload` already applies to the GPL source
    archives: some things are wrong in a way that looks fine.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_bw", PROJECT / "packaging" / "build_windows.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    source = (PROJECT / "packaging" / "build_windows.py").read_text(encoding="utf-8")
    assert 'rglob("*.pyd")' in source, "extensions are .pyd on Windows"
    assert "compiled and not list" in source
    # And the check is skippable exactly once, by the flag that says so.
    assert "compiled: bool = True" in source
    assert "compiled=not args.no_compile" in source
