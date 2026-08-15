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
import re
import tomllib
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
PACKAGE = SRC / "chunksim"


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
