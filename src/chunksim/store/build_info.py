"""When the code being run was installed, so a stale install is visible.

**The failure this exists for.** `pipx install` on an already-installed package
whose version has not moved is a silent no-op - it prints "already seems to be
installed" and exits 0 - so the `chunksim` on `PATH` can be last week's wheel while
the checkout is today's, and every manual check made against it is a check of
the wrong code. `--force` is the fix and forgetting it has no symptom, which is
what makes a printed stamp worth its line: it turns "I think I reinstalled" into
something you can read off the screen.

**The timestamp is the installer's own metadata directory, not a build stamp
baked into the wheel.** pip writes those files fresh rather than restoring the
zip's timestamps - measured, a wheel built at 18:11 and installed at 23:02
gives 23:02 - so the mtime of `*.dist-info/` answers "when did this code land
here", which is the question being asked. Baking a stamp in at build time would
answer a different one (when was the wheel made) and would need a build hook
this project's empty `dependencies` has no room for.

**An editable install dates the `pip install -e`, not the code**, and there is
no honest way around that: the code is whatever the checkout says this second.
So `kind` is reported beside the date everywhere the date is shown, and the
wording changes with it - "installed 3h ago" is a fact about a wheel and a
half-truth about a checkout.

Reading an mtime is disk, which by this project's rules belongs to `cache.py`.
The exception is the same one `gui/server.py` makes for its packaged resources:
this reads the *package's own* installation metadata, never anything under
`cache/`, and it is read once per process. Nothing here is cached - see the
no-module-level-state rule - and nothing here raises: a watermark that could
kill `chunksim tasks` would be a bad trade for a line of provenance.
"""

from __future__ import annotations

import importlib.metadata as metadata
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from chunksim.model.summary import format_age

#: The distribution these two apps ship as. Both `chunksim` and `chunksim-gui` are
#: console scripts of it, so one lookup answers for either.
DISTRIBUTION = "chunksim"

#: What `kind` can be. `wheel` is an ordinary install (pip or pipx), `editable`
#: is `pip install -e`, and `source` is neither - a checkout on `sys.path`,
#: which `python -m chunksim` reaches without installing anything.
KINDS = ("wheel", "editable", "source")


@dataclass(frozen=True)
class Build:
    """Where this process's `chunksim` came from, and when."""

    version: str
    #: ISO-8601 UTC, or `None` when the metadata is missing or unreadable.
    #: `None` is not an error - it is what a source checkout looks like.
    installed_at: str | None
    kind: str
    #: The package directory actually imported. The other half of "which
    #: install is this": two venvs is the normal state of this project.
    path: str

    def as_dict(self) -> dict[str, str | None]:
        """The JSON the GUI renders. Flat, and stable across kinds."""
        return {
            "version": self.version,
            "installed_at": self.installed_at,
            "kind": self.kind,
            "path": self.path,
        }


def _dist_info_dir(dist: metadata.Distribution) -> Path | None:
    """The `*.dist-info` directory backing `dist`, if it has one on disk.

    Found through `files`/`locate` rather than `PathDistribution._path`: the
    latter is private, and the only thing wanted from it is a directory that
    `METADATA` already names.
    """
    for entry in dist.files or ():
        if entry.name != "METADATA":
            continue
        located = Path(str(entry.locate())).parent
        if located.suffix == ".dist-info":
            return located
    return None


def _installed_at(directory: Path | None) -> str | None:
    if directory is None:
        return None
    try:
        mtime = directory.stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(mtime, UTC).isoformat()


def _is_editable(dist: metadata.Distribution) -> bool:
    """Whether pip recorded this as an editable install.

    `direct_url.json` is PEP 610's record of where the install came from, and
    `dir_info.editable` is the flag pip sets for `-e`. Absent for a wheel from
    an index, present-but-false for one installed from a local path.
    """
    try:
        raw = dist.read_text("direct_url.json")
    except OSError:
        return False
    if not raw:
        return False
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return False
    if not isinstance(parsed, dict):
        return False
    info = parsed.get("dir_info")
    return isinstance(info, dict) and bool(info.get("editable"))


def describe(dist: metadata.Distribution, path: Path) -> Build:
    """`dist` and the imported package directory as one `Build`.

    Separate from `read_build` so the interesting half is testable against a
    `PathDistribution` built in a `tmp_path`, rather than against whatever
    happens to be installed while the suite runs - which differs between a
    developer's checkout and a fresh clone, and is exactly the sort of thing
    that makes a test pass for the wrong reason.
    """
    return Build(
        version=dist.version,
        installed_at=_installed_at(_dist_info_dir(dist)),
        kind="editable" if _is_editable(dist) else "wheel",
        path=str(path),
    )


def _package_dir() -> Path:
    """The imported `chunksim` package directory.

    **Not `Path(__file__).parent`**, which is this module's own directory and
    therefore moved when this module did - it reported `.../chunksim/store`
    the moment `build_info.py` was grouped with the rest of the disk layer, and
    a watermark naming a subdirectory answers a question nobody asked. Asking
    the top-level package survives any further reshuffling.
    """
    import chunksim

    return Path(chunksim.__file__ or __file__).resolve().parent


def read_build(distribution: str = DISTRIBUTION) -> Build:
    """This process's provenance. Never raises, and never guesses a date."""
    path = _package_dir()
    try:
        dist = metadata.distribution(distribution)
    except metadata.PackageNotFoundError:
        # Importable without being installed: a checkout on `sys.path`. The
        # version is genuinely unknown here - `pyproject.toml` may not even be
        # beside the code - and inventing one would be worse than saying so.
        return Build(version="unknown", installed_at=None, kind="source", path=str(path))
    return describe(dist, path)


#: Set it to anything to silence the line. For a script that wants a clean
#: stderr; `2>/dev/null` does the same for anything that cannot set it.
NO_WATERMARK_ENV = "CHUNKSIM_NO_WATERMARK"


def watermark(app: str, build: Build | None = None) -> str:
    """One line naming which install answered, and how old it is.

    **The wording changes with the kind, because the date means different
    things.** A wheel's date is the age of the code. An editable install's is
    the age of the *link*, and its code is whatever the checkout holds this
    second - so calling that "installed" would be a small lie told on every
    run. A source checkout has no date at all and says where it is instead,
    which is the useful half in that case anyway.
    """
    build = read_build() if build is None else build
    if build.kind == "editable":
        return f"{app} {build.version} · editable install, linked {format_age(build.installed_at)}"
    if build.kind == "source":
        return f"{app} {build.version} · uninstalled source at {build.path}"
    return f"{app} {build.version} · installed {format_age(build.installed_at)}"


def print_watermark(app: str, stream: TextIO | None = None) -> None:
    """Print it, unless the environment asked not to.

    **stderr by default, and that is not a detail**: nine `chunksim` subcommands
    can write their whole answer to stdout with `--export-json -`, and a line
    of provenance in front of it turns valid JSON into a parse error. `chunksim-gui`
    passes stdout deliberately - it has no such mode, and its other startup
    lines are there.
    """
    if os.environ.get(NO_WATERMARK_ENV):
        return
    print(watermark(app), file=stream if stream is not None else sys.stderr)


__all__ = [
    "DISTRIBUTION",
    "KINDS",
    "NO_WATERMARK_ENV",
    "Build",
    "describe",
    "print_watermark",
    "read_build",
    "watermark",
]


def parse_version(text: str) -> tuple[int, ...] | None:
    """`"0.2.10"` as `(0, 2, 10)`, or `None` if it is not that shape.

    **Refusing is the point.** There is no PEP 440 parser in the standard
    library and this project has no runtime dependencies, so the choice was a
    strict reading of the simple case or a loose one of every case. A loose
    parser here would compare a release it half-understood and either nag
    forever or never mention an update at all, and both failures are silent.

    A `None` means the caller says nothing, which is the right answer to a
    version neither side can be sure it read correctly.
    """
    parts = text.strip().removeprefix("v").split(".")
    if not parts or any(not part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def is_newer(candidate: str, current: str) -> bool:
    """Whether `candidate` is a later version than `current`.

    False whenever either side is unparseable, or equal, or older - so the
    caller's question is only ever answered "yes" when both versions were
    understood. `(0, 2)` and `(0, 2, 0)` compare equal by zero-padding, since
    `0.2` and `0.2.0` are the same release named two ways.
    """
    left, right = parse_version(candidate), parse_version(current)
    if left is None or right is None:
        return False
    width = max(len(left), len(right))
    return left + (0,) * (width - len(left)) > right + (0,) * (width - len(right))
