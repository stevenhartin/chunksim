"""Opening a window, and knowing when it closed.

A server you have to remember to Ctrl-C is a server you leave running. This
module makes the window's lifetime the server's: it launches a Chromium-family
browser in **app mode** - no tabs, no address bar, its own taskbar entry - and
hands back a process to wait on. Close the window and `fray-gui` stops.

**`--user-data-dir` is what makes that work, and it is not a nicety.** Chrome
normally hands a URL to an already-running instance and the launched process
exits immediately; wait on *that* and the server stops the moment it starts.
Pointing it at a profile of our own forces a separate instance whose lifetime
really is the window's. The cost is a profile without your extensions or
logins, which for a page served from localhost is no cost at all.

**Any Chromium-family browser will do**, and the search order is by how likely
it is to be there rather than by preference: Chrome, then Edge - which ships
with Windows 10 and 11, so a Windows box essentially always has one - then
Brave, Chromium, Vivaldi, Opera. The flags are identical across all of them and
across platforms.

**Firefox is the gap.** It dropped site-specific-browser support and has no
`--app`; `--kiosk` is fullscreen with no controls, which is too aggressive to
inflict on someone who just typed `fray-gui`. A machine with only Firefox falls
back to an ordinary tab, and the heartbeat in `server.py` cleans up instead.

Nothing here adds a dependency. Embedding a real renderer - pywebview, Qt
WebEngine - would give a window with no browser installed at all, at the price
of PyGObject and WebKit2 as system packages or a hundred megabytes of Qt. That
is out of proportion to a window frame, and this project's zero-dependency rule
is load-bearing enough that `derived_cache.py` took zstd from the standard
library rather than PyPI.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

#: Executables that understand `--app`, most-likely-present first. Edge is
#: second because it ships with Windows; on Linux the same names are found on
#: `PATH` and on macOS under `/Applications`.
_CANDIDATES: tuple[str, ...] = (
    "google-chrome",
    "google-chrome-stable",
    "chrome",
    "microsoft-edge",
    "microsoft-edge-stable",
    "msedge",
    "brave-browser",
    "brave",
    "chromium",
    "chromium-browser",
    "vivaldi",
    "opera",
)

#: Where the bundled `.app`s live on macOS, which is not on `PATH`.
_MACOS_APPS: tuple[str, ...] = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
)

#: Windows installs to Program Files rather than to `PATH`.
_WINDOWS_APPS: tuple[str, ...] = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)


def find_app_browser() -> Path | None:
    """A browser that can open an app window, or `None` if there is none.

    `PATH` first, since that covers Linux and any browser the user has put
    there deliberately, then the per-platform install locations.
    """
    for name in _CANDIDATES:
        found = shutil.which(name)
        if found:
            return Path(found)

    extra = _MACOS_APPS if sys.platform == "darwin" else ()
    if os.name == "nt":
        extra = _WINDOWS_APPS
    for candidate in extra:
        path = Path(candidate)
        if path.is_file():
            return path
    return None


@dataclass(frozen=True)
class AppWindow:
    """A launched app window, and the process whose end means it closed."""

    process: subprocess.Popen[bytes]
    browser: Path
    profile: Path

    def wait(self) -> int:
        return self.process.wait()

    def close(self) -> None:
        """Ask the window to go away, and insist if it will not."""
        if self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()


def open_app_window(url: str, profile: Path, browser: Path | None = None) -> AppWindow | None:
    """Open `url` as an app window, or `None` if no browser can.

    The flags are the minimum that makes a launched browser behave like an
    application rather than like a browser: no first-run wizard, no
    default-browser nagging, and its own profile so the process we get back is
    really ours to wait on.
    """
    executable = browser or find_app_browser()
    if executable is None:
        return None

    profile.mkdir(parents=True, exist_ok=True)
    command = [
        str(executable),
        f"--app={url}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        # Nothing here is a web app wanting notifications or a session
        # restored; a crash bubble on top of the map would be noise.
        "--disable-session-crashed-bubble",
        "--disable-features=Translate",
    ]
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
    except OSError:
        # Found on disk but not runnable - a broken symlink, a snap without
        # permissions. Fall back rather than failing to start at all.
        return None
    return AppWindow(process=process, browser=executable, profile=profile)


__all__ = ["AppWindow", "find_app_browser", "open_app_window"]
