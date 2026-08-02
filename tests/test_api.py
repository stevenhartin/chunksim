"""Tests for the HTTP layer.

`urlopen` is replaced throughout, so no test reaches the network.
"""

from __future__ import annotations

import io
import urllib.error
import urllib.request
from collections.abc import Callable
from email.message import Message
from typing import Any

import pytest

from fray_claude.api import (
    CHUNKINFO_URL,
    DEFAULT_TIMEOUT,
    TASKS_MAP_URL,
    FetchError,
    fetch_chunkinfo,
    fetch_map,
    fetch_tasks_map,
    map_url,
)


def _patch_urlopen(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[str, float], io.BytesIO]
) -> list[tuple[str, float]]:
    """Route `urlopen` to `handler`, returning the list of calls it receives."""
    calls: list[tuple[str, float]] = []

    def fake_urlopen(url: str, timeout: float = DEFAULT_TIMEOUT) -> io.BytesIO:
        calls.append((url, timeout))
        return handler(url, timeout)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return calls


def _responds(body: bytes) -> Callable[[str, float], io.BytesIO]:
    return lambda url, timeout: io.BytesIO(body)


def _raises(exc: Exception) -> Callable[[str, float], io.BytesIO]:
    def handler(url: str, timeout: float) -> io.BytesIO:
        raise exc

    return handler


def test_map_url_points_at_the_maps_collection() -> None:
    assert map_url("fray") == "https://chunkpicker.firebaseio.com/maps/fray.json"


def test_fetch_map_returns_the_decoded_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, _responds(b'{"chunks": {"unlocked": {"50_50": true}}}'))

    payload: dict[str, Any] = fetch_map("fray")

    assert payload == {"chunks": {"unlocked": {"50_50": True}}}


def test_fetch_map_requests_the_mapped_url_and_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_urlopen(monkeypatch, _responds(b"{}"))

    fetch_map("other", timeout=1.5)

    assert calls == [("https://chunkpicker.firebaseio.com/maps/other.json", 1.5)]


def test_fetch_map_treats_a_null_body_as_a_missing_map(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An unknown path answers 200 with `null`, so this is the only 404 signal.
    _patch_urlopen(monkeypatch, _responds(b"null"))

    with pytest.raises(FetchError, match="no such map: 'nope'"):
        fetch_map("nope")


def test_fetch_map_rejects_a_non_object_body(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, _responds(b"[1, 2]"))

    with pytest.raises(FetchError, match="expected an object.*got list"):
        fetch_map("fray")


def test_fetch_map_rejects_malformed_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, _responds(b"{not json"))

    with pytest.raises(FetchError, match="malformed JSON"):
        fetch_map("fray")


def test_fetch_map_reports_the_http_status(monkeypatch: pytest.MonkeyPatch) -> None:
    error = urllib.error.HTTPError(map_url("fray"), 503, "Service Unavailable", Message(), None)
    _patch_urlopen(monkeypatch, _raises(error))

    with pytest.raises(FetchError, match="HTTP 503"):
        fetch_map("fray")


def test_fetch_map_reports_a_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, _raises(TimeoutError()))

    with pytest.raises(FetchError, match="timed out after 2s"):
        fetch_map("fray", timeout=2.0)


def test_fetch_map_reports_a_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, _raises(urllib.error.URLError("name resolution failed")))

    with pytest.raises(FetchError, match="network error.*name resolution failed"):
        fetch_map("fray")


def test_fetch_chunkinfo_requests_the_gh_pages_export(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_urlopen(monkeypatch, _responds(b'{"chunks": {}}'))

    payload = fetch_chunkinfo(timeout=5.0)

    assert payload == {"chunks": {}}
    assert calls == [(CHUNKINFO_URL, 5.0)]
    assert "gh-pages" in CHUNKINFO_URL


def test_fetch_tasks_map_requests_the_gh_pages_tasks_map(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_urlopen(monkeypatch, _responds(b'{"Obtain a whip": "t_1"}'))

    payload = fetch_tasks_map(timeout=5.0)

    assert payload == {"Obtain a whip": "t_1"}
    assert calls == [(TASKS_MAP_URL, 5.0)]


def test_fetch_chunkinfo_rejects_a_non_object_body(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, _responds(b"[1, 2]"))

    with pytest.raises(FetchError, match="expected an object.*got list"):
        fetch_chunkinfo()


def test_fetch_chunkinfo_reports_the_http_status(monkeypatch: pytest.MonkeyPatch) -> None:
    error = urllib.error.HTTPError(CHUNKINFO_URL, 503, "Service Unavailable", Message(), None)
    _patch_urlopen(monkeypatch, _raises(error))

    with pytest.raises(FetchError, match="HTTP 503"):
        fetch_chunkinfo()
