"""Set the project's version in the two files that have to agree about it.

    python packaging/set_version.py 0.2.0

`pyproject.toml` is what `importlib.metadata` reports and therefore what the
running program calls itself; `packaging/chunksim.iss` is what the installer
calls itself and what its filename carries. **They are two files saying one
thing**, which is why `tests/test_packaging.py` pins them together - a drift
ships an installer that disagrees with the program inside it, and an updater
that either offers the same version forever or never offers anything.

**Editing them is Python's job, not the batch file's.** A regex over TOML in
`cmd` is how a `pyproject.toml` gets corrupted on a machine nobody can debug
from; here the substitution is anchored, counted, and refuses rather than
guesses.

Refuses to go backwards, using `build_info.is_newer` - the same comparison the
update check makes, so a version this accepts is one the updater can act on. A
release numbered below the last one is invisible to every install already out
there, which is a mistake that only shows up as silence.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chunksim.store.build_info import is_newer, parse_version  # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent

#: Each file, the pattern that finds its version, and how to put one back.
#: Anchored to the line so a version-looking string elsewhere in the file - a
#: dependency pin, a URL - cannot be rewritten by accident.
TARGETS = (
    (PROJECT / "pyproject.toml", re.compile(r'^(version = ")([^"]+)(")$', re.MULTILINE)),
    (PROJECT / "packaging" / "chunksim.iss", re.compile(r'^(#define AppVersion ")([^"]+)(")$', re.MULTILINE)),
)


def current() -> str:
    """The version as `pyproject.toml` states it - the one that ships."""
    text = TARGETS[0][0].read_text(encoding="utf-8")
    match = TARGETS[0][1].search(text)
    if match is None:
        raise SystemExit("pyproject.toml has no version line this understands")
    return match.group(2)


def apply(version: str) -> list[Path]:
    """Write `version` into every target, returning the files that changed."""
    changed: list[Path] = []
    for path, pattern in TARGETS:
        text = path.read_text(encoding="utf-8")
        found = pattern.findall(text)
        if len(found) != 1:
            raise SystemExit(f"{path.name}: expected one version line, found {len(found)}")
        updated = pattern.sub(rf"\g<1>{version}\g<3>", text, count=1)
        if updated != text:
            path.write_text(updated, encoding="utf-8")
            changed.append(path)
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", nargs="?", help="the new version, e.g. 0.2.0")
    parser.add_argument(
        "--allow-same", action="store_true",
        help="accept the version already set, rather than requiring a newer one",
    )
    args = parser.parse_args(argv)

    now = current()
    if args.version is None:
        print(now)
        return 0

    wanted = args.version.strip().removeprefix("v")
    if parse_version(wanted) is None:
        print(f"error: {wanted!r} is not a version this project can compare.", file=sys.stderr)
        print("       Use digits and dots only, like 0.2.0 - see build_info.parse_version.", file=sys.stderr)
        return 2
    if wanted == now:
        if not args.allow_same:
            print(f"error: {wanted} is already the version. Nothing to do.", file=sys.stderr)
            return 2
    elif not is_newer(wanted, now):
        print(f"error: {wanted} is not newer than {now}.", file=sys.stderr)
        print("       A release numbered below the last one is invisible to every", file=sys.stderr)
        print("       install already out there - it just never offers an update.", file=sys.stderr)
        return 2

    changed = apply(wanted)
    for path in changed:
        print(f"  {path.relative_to(PROJECT)} -> {wanted}")
    if not changed:
        print(f"  already {wanted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
