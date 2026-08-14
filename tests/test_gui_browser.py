"""Tests for finding a browser and for the idle shutdown.

Nothing here launches a browser: `open_app_window` is exercised through a
stubbed `subprocess.Popen`, because a real window needs a display and would
outlive the test on a machine that has one.
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Any

import pytest

from chunksim.gui import allowed_hosts, browser
from chunksim.gui.jobs import JobRegistry
from chunksim.gui.http import Context, idle_seconds, should_stop, touch


def test_the_search_prefers_what_is_most_likely_installed() -> None:
    """Chrome first, then Edge - which ships with Windows 10 and 11.

    The order is by likelihood rather than preference: the flags are identical
    across the whole Chromium family, so the only question is which one is
    there.
    """
    names = browser._CANDIDATES

    assert names.index("google-chrome") < names.index("microsoft-edge")
    assert names.index("microsoft-edge") < names.index("chromium")
    assert "firefox" not in names


def test_no_browser_found_is_none_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A machine with only Firefox falls back to a tab; it does not fail."""
    monkeypatch.setattr("chunksim.gui.browser.shutil.which", lambda name: None)
    monkeypatch.setattr(browser, "_MACOS_APPS", ())
    monkeypatch.setattr(browser, "_WINDOWS_APPS", ())

    assert browser.find_app_browser() is None


def test_the_window_gets_its_own_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**The flag that makes the whole approach work.**

    Without `--user-data-dir` Chrome hands the URL to an already-running
    instance and the launched process exits at once - so waiting on it would
    stop the server the moment it started.
    """
    seen: list[list[str]] = []

    def fake_popen(command: list[str], **kwargs: Any) -> Any:
        seen.append(command)
        return _FakeProcess()

    monkeypatch.setattr("chunksim.gui.browser.subprocess.Popen", fake_popen)
    profile = tmp_path / "profile"

    window = browser.open_app_window(
        "http://127.0.0.1:8731/", profile, browser=Path("/usr/bin/chromium")
    )

    assert window is not None
    assert f"--user-data-dir={profile}" in seen[0]
    assert "--app=http://127.0.0.1:8731/" in seen[0]
    assert profile.is_dir()


def test_a_browser_that_will_not_run_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Found on disk is not the same as runnable - a broken snap, say."""
    def explode(command: list[str], **kwargs: Any) -> Any:
        raise OSError("permission denied")

    monkeypatch.setattr("chunksim.gui.browser.subprocess.Popen", explode)

    assert browser.open_app_window("http://x/", tmp_path, browser=Path("/x")) is None


def test_closing_insists_if_asking_does_not_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    process = _FakeProcess(ignores_terminate=True)
    monkeypatch.setattr("chunksim.gui.browser.subprocess.Popen", lambda *a, **k: process)
    window = browser.open_app_window("http://x/", tmp_path, browser=Path("/x"))

    assert window is not None
    window.close()

    assert process.killed


# --- the heartbeat ---------------------------------------------------------


def test_a_server_nobody_has_opened_is_not_idle() -> None:
    """Zero rather than infinity for never-seen, and it matters.

    `should_stop` compares against a timeout, so infinity would stop a server
    the instant it started - which is exactly what `--no-browser` is while the
    user is still pasting the URL.
    """
    context = Context()

    assert idle_seconds(context) == 0.0
    assert not should_stop(context)


def test_a_client_that_just_asked_holds_it_open() -> None:
    context = Context()
    touch(context)

    assert not should_stop(context)


def test_a_gone_client_lets_it_stop() -> None:
    context = Context()
    context.last_seen[0] = 1.0  # far in the past on a monotonic clock

    assert should_stop(context)


def test_keep_alive_holds_it_open_with_nobody_there() -> None:
    """`--keep-alive` is for a server driven over ssh, which outlives the
    browser that reads it: a closed laptop lid must not leave the user
    reconnecting to restart it."""
    context = Context(keep_alive=True)
    context.last_seen[0] = 1.0  # far in the past on a monotonic clock

    assert not should_stop(context)


def test_a_running_job_holds_it_open() -> None:
    """Closing the tab must not throw away a simulation already begun."""
    registry = JobRegistry()
    started = threading.Event()
    release = threading.Event()

    def work(progress: Any, _stop: Any) -> dict[str, Any]:
        started.set()
        release.wait(timeout=5)
        return {}

    registry.submit("simulate", work)
    started.wait(timeout=5)
    context = Context(jobs=registry)
    context.last_seen[0] = 1.0

    try:
        assert not should_stop(context)
    finally:
        release.set()


class _FakeProcess:
    """Enough of `Popen` for the launch paths."""

    def __init__(self, ignores_terminate: bool = False) -> None:
        self.ignores_terminate = ignores_terminate
        self.killed = False
        self._returncode: int | None = None

    def poll(self) -> int | None:
        return self._returncode

    def wait(self, timeout: float | None = None) -> int:
        if self.ignores_terminate and timeout is not None:
            raise subprocess.TimeoutExpired("chromium", timeout)
        self._returncode = 0
        return 0

    def terminate(self) -> None:
        if not self.ignores_terminate:
            self._returncode = 0

    def kill(self) -> None:
        self.killed = True
        self._returncode = -9


# --- what names this server ------------------------------------------------


def test_the_bind_seeds_the_host_allowlist() -> None:
    """`--host <tailnet address>` should need no second flag to be usable."""
    assert allowed_hosts("100.93.219.108") == frozenset({"100.93.219.108"})


def test_a_wildcard_bind_names_nothing() -> None:
    """`0.0.0.0` is every interface, not an address anyone types - so it cannot
    stand in for the one they will, and actions stay refused until
    `--allow-host` says what to expect."""
    assert allowed_hosts("0.0.0.0") == frozenset()
    assert allowed_hosts("::") == frozenset()
    assert allowed_hosts("0.0.0.0", ["devbox.tailnet.ts.net"]) == frozenset(
        {"devbox.tailnet.ts.net"}
    )


def test_loopback_is_never_listed() -> None:
    """`_origin_ok` accepts it unconditionally, so repeating it here would be a
    second place for the same rule to live."""
    assert allowed_hosts("127.0.0.1") == frozenset()
    assert allowed_hosts("localhost", ["::1"]) == frozenset()

