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


def test_both_console_scripts_resolve() -> None:
    """`fray` and `chunksim-gui` are dotted strings in `pyproject.toml` that nothing
    else checks. A module rename that misses them is a `pipx install` that
    succeeds and two commands that fail on their first line."""
    try:
        entries = metadata.distribution("chunksim").entry_points
    except metadata.PackageNotFoundError:  # pragma: no cover - fresh clone
        pytest.skip("chunksim is not installed into this environment")

    scripts = {entry.name: entry for entry in entries if entry.group == "console_scripts"}

    assert set(scripts) == {"fray", "chunksim-gui"}
    for entry in scripts.values():
        assert callable(entry.load()), f"{entry.name} -> {entry.value} does not resolve"
