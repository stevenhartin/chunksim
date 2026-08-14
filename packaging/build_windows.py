"""Assemble the Windows payload: an embeddable CPython with chunksim beside it.

**Nothing is frozen and nothing is compiled.** `chunksim` has no required
runtime dependencies, so there is no dependency graph to resolve and no import
hooks to install - the whole application is a package directory. That makes the
embeddable distribution the honest choice over PyInstaller:

- `gui.RESOURCE_DIR` and `cache.PACKAGED_OVERRIDES` are `__file__`-relative.
  Under a one-file freeze that resolves into a temporary extraction directory
  that is re-made on every launch; here `__file__` keeps meaning what it means
  in a checkout.
- `store/build_info.py` reads `importlib.metadata.distribution("chunksim")`, so
  the watermark and the update check need real `.dist-info` next to the code.
  This copies it; a freeze has to be told to.
- A single opaque executable is what antivirus heuristics and SmartScreen are
  most suspicious of. A directory of `.pyd` and `.py` files is ordinary.

Run it from anywhere; it writes `packaging/build/payload/`, which is what the
Inno Setup script in `chunksim.iss` packages:

    python packaging/build_windows.py [--python-version 3.14.6]

**The interpreter is downloaded, not built**, from python.org over HTTPS, and
its published SHA-256 is checked before anything is unpacked. There is no
`pip` in an embeddable distribution and nothing here needs one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

#: The interpreter the payload carries. `pyproject.toml` requires >= 3.14, and
#: `store/derived_cache.py` wants `compression.zstd` (PEP 784, 3.14) - it
#: degrades to plain pickle without it, so a build that quietly lost the module
#: would still work and only be slower, which is the kind of silent regression
#: `verify_payload` exists to catch.
DEFAULT_PYTHON = "3.14.6"

EMBED_URL = "https://www.python.org/ftp/python/{version}/python-{version}-embed-amd64.zip"

PROJECT = Path(__file__).resolve().parent.parent
BUILD = PROJECT / "packaging" / "build"
PAYLOAD = BUILD / "payload"

#: Everything the payload needs that is not the interpreter or the package.
#: `LICENSE` is not decoration: this is GPL-3.0-or-later, and a binary handed
#: to someone has to carry its terms.
EXTRAS = ("LICENSE", "README.md")


def download(url: str, into: Path) -> Path:
    """Fetch `url` into `into`, reusing an existing copy."""
    target = into / url.rsplit("/", 1)[-1]
    if target.is_file():
        print(f"  have {target.name}")
        return target
    into.mkdir(parents=True, exist_ok=True)
    print(f"  fetching {url}")
    with urllib.request.urlopen(url, timeout=120) as response:
        target.write_bytes(response.read())
    return target


def published_digest(version: str, name: str) -> str | None:
    """python.org's own SHA-256 for `name`, read out of the release's SBOM.

    **The SBOM is where the digest is**, not a `SHA256SUMS` file - python.org
    publishes `<artifact>.spdx.json` alongside a sigstore bundle and nothing
    else machine-readable. The SPDX document describes the artifact as a
    package with a `SHA256` checksum, which is exactly the one field wanted.

    What this proves is that the bytes are the ones python.org says it
    published; it is served from the same host over the same TLS, so it
    catches a truncated or substituted *download* rather than a compromised
    python.org. Verifying the sigstore bundle would answer the second
    question and needs a dependency this build does not have.

    `None` when the document cannot be read or does not name the file, so a
    changed shape shows up as a loud warning rather than verification quietly
    switching itself off.
    """
    url = f"https://www.python.org/ftp/python/{version}/{name}.spdx.json"
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            document = json.load(response)
    except (OSError, json.JSONDecodeError):
        return None
    for package in document.get("packages", []):
        if package.get("packageFileName") != name:
            continue
        for checksum in package.get("checksums", []):
            if checksum.get("algorithm") == "SHA256":
                value = checksum.get("checksumValue")
                return value if isinstance(value, str) else None
    return None


def interpreter(version: str) -> Path:
    """The extracted embeddable interpreter, verified before it is unpacked."""
    archive = download(EMBED_URL.format(version=version), BUILD / "downloads")
    expected = published_digest(version, archive.name)
    if expected is not None:
        got = hashlib.sha256(archive.read_bytes()).hexdigest()
        if got != expected:
            archive.unlink()
            raise SystemExit(f"{archive.name} does not match python.org's SHA-256")
        print(f"  checksum ok ({expected[:12]}…)")
    else:
        print("  WARNING: python.org published no checksum this build could read")

    target = PAYLOAD / "python"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(target)
    return target


def point_path_file(python_dir: Path) -> Path:
    """Teach the interpreter where the application is.

    An embeddable distribution reads `pythonXY._pth` **instead of** computing
    `sys.path`, and it deliberately leaves out the current directory and any
    user site - which is most of what makes it self-contained. Adding one line
    is the whole configuration: the app lives beside the interpreter, so the
    entry is relative and the tree can be installed anywhere.
    """
    paths = list(python_dir.glob("python*._pth"))
    if len(paths) != 1:
        raise SystemExit(f"expected exactly one ._pth in {python_dir}, found {len(paths)}")
    path_file = paths[0]
    lines = path_file.read_text(encoding="utf-8").splitlines()
    if "../app" not in lines:
        lines.insert(0, "../app")
    path_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path_file


def application(dist_info: Path | None) -> Path:
    """Copy the package and its metadata beside the interpreter."""
    app = PAYLOAD / "app"
    if app.exists():
        shutil.rmtree(app)
    app.mkdir(parents=True)
    shutil.copytree(
        PROJECT / "src" / "chunksim",
        app / "chunksim",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    if dist_info is not None:
        shutil.copytree(dist_info, app / dist_info.name)
    return app


def built_metadata() -> Path | None:
    """The `.dist-info` from a built wheel, for `importlib.metadata`.

    Without it `read_build` reports "uninstalled source" and the update check
    has no version to compare, so the watermark and the updater both go quiet.
    Built by `pyproject-build`, which is not otherwise part of this project's
    development loop - hence a clear message rather than an import of it.
    """
    wheels = sorted((PROJECT / "dist").glob("chunksim-*.whl"))
    if not wheels:
        print("  no wheel in dist/ - run `pyproject-build` for a versioned build")
        return None
    unpacked = BUILD / "wheel"
    if unpacked.exists():
        shutil.rmtree(unpacked)
    with zipfile.ZipFile(wheels[-1]) as bundle:
        bundle.extractall(unpacked)
    found = sorted(unpacked.glob("chunksim-*.dist-info"))
    return found[0] if found else None


def launchers() -> None:
    """Two entry points, and they are not alike.

    The console script is a `.cmd` on `PATH`, because that is what a terminal
    wants and it costs no build tooling. The GUI is started through
    `pythonw.exe`, which has no console at all - a window opening behind a
    black rectangle is the tell of a Python program pretending to be an app.
    """
    (PAYLOAD / "chunksim.cmd").write_text(
        '@echo off\r\n"%~dp0python\\python.exe" -m chunksim %*\r\n', encoding="utf-8"
    )
    (PAYLOAD / "chunksim-gui.cmd").write_text(
        '@echo off\r\nstart "" "%~dp0python\\pythonw.exe" -m chunksim.gui %*\r\n', encoding="utf-8"
    )


def verify_payload() -> list[str]:
    """What must be true of the tree, checked rather than assumed."""
    problems: list[str] = []
    required = [
        PAYLOAD / "python" / "python.exe",
        PAYLOAD / "python" / "pythonw.exe",
        PAYLOAD / "app" / "chunksim" / "__init__.py",
        # The two `__file__`-relative resources. A wheel that lost either still
        # imports, so only a check like this notices.
        PAYLOAD / "app" / "chunksim" / "gui" / "resources" / "app.js",
        PAYLOAD / "app" / "chunksim" / "heuristics" / "overrides.json",
        PAYLOAD / "chunksim.cmd",
        PAYLOAD / "chunksim-gui.cmd",
        PAYLOAD / "LICENSE",
    ]
    problems += [f"missing {path.relative_to(PAYLOAD)}" for path in required if not path.exists()]
    if not any((PAYLOAD / "python").glob("_zstd*.pyd")):
        problems.append("no _zstd in the interpreter: derived caches fall back to plain pickle")
    if not sorted((PAYLOAD / "app").glob("chunksim-*.dist-info")):
        problems.append("no .dist-info: the watermark and the update check go quiet")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--python-version", default=DEFAULT_PYTHON)
    args = parser.parse_args(argv)

    print(f"payload -> {PAYLOAD}")
    PAYLOAD.mkdir(parents=True, exist_ok=True)
    python_dir = interpreter(args.python_version)
    print(f"  path file: {point_path_file(python_dir).name}")
    print(f"  app: {application(built_metadata())}")
    launchers()
    for extra in EXTRAS:
        shutil.copy2(PROJECT / extra, PAYLOAD / extra)

    problems = verify_payload()
    for problem in problems:
        print(f"  ! {problem}", file=sys.stderr)
    total = sum(p.stat().st_size for p in PAYLOAD.rglob("*") if p.is_file())
    print(f"  {total / 1e6:.1f} MB in {sum(1 for _ in PAYLOAD.rglob('*') if _.is_file())} files")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
