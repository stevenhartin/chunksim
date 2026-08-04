"""Tests for the HTTP layer.

`urlopen` is replaced throughout, so no test reaches the network.
"""

from __future__ import annotations

import io
import json
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
    WIKI_API_URL,
    WIKI_TITLES_PER_REQUEST,
    WIKI_USER_AGENT,
    WORLD_MAP_URL,
    FetchError,
    fetch_chunkinfo,
    fetch_map,
    fetch_tasks_map,
    fetch_text,
    fetch_wiki_page_titles,
    fetch_wiki_pages,
    fetch_world_map,
    map_url,
    slayer_sheet_url,
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


# --- the wiki and the slayer sheet ------------------------------------------


def _patch_wiki(
    monkeypatch: pytest.MonkeyPatch, bodies: list[bytes]
) -> list[urllib.request.Request]:
    """Serve `bodies` in order, recording each `Request` the wiki calls make."""
    requests: list[urllib.request.Request] = []
    remaining = list(bodies)

    def fake_urlopen(target: Any, timeout: float = DEFAULT_TIMEOUT) -> io.BytesIO:
        requests.append(target)
        return io.BytesIO(remaining.pop(0))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return requests


def _page(title: str, content: str) -> dict[str, Any]:
    return {"title": title, "revisions": [{"slots": {"main": {"content": content}}}]}


def test_wiki_requests_identify_the_project(monkeypatch: pytest.MonkeyPatch) -> None:
    # An anonymous request is answered with HTTP 403 - the wiki applies
    # MediaWiki's user-agent policy. See `api.WIKI_USER_AGENT`.
    requests = _patch_wiki(monkeypatch, [json.dumps({"query": {"pages": []}}).encode()])

    fetch_wiki_pages(["Cook's Assistant"])

    assert requests[0].get_header("User-agent") == WIKI_USER_AGENT
    assert requests[0].full_url.startswith(WIKI_API_URL)


def test_fetch_wiki_pages_returns_content_by_title(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {"query": {"pages": [_page("Cook's Assistant", "{{Quest details|length = Very Short}}")]}}
    _patch_wiki(monkeypatch, [json.dumps(body).encode()])

    assert fetch_wiki_pages(["Cook's Assistant"]) == {
        "Cook's Assistant": "{{Quest details|length = Very Short}}"
    }


def test_fetch_wiki_pages_keys_by_what_was_asked_for(monkeypatch: pytest.MonkeyPatch) -> None:
    # The API normalises and redirects; keying on the response would drop
    # every title that needed either.
    body = {
        "query": {
            "normalized": [{"from": "dragon slayer", "to": "Dragon slayer"}],
            "redirects": [{"from": "Dragon slayer", "to": "Dragon Slayer I"}],
            "pages": [_page("Dragon Slayer I", "wikitext")],
        }
    }
    _patch_wiki(monkeypatch, [json.dumps(body).encode()])

    assert fetch_wiki_pages(["dragon slayer"]) == {"dragon slayer": "wikitext"}


def test_a_missing_page_is_absent_rather_than_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = {"query": {"pages": [{"title": "Nowhere", "missing": True}]}}
    _patch_wiki(monkeypatch, [json.dumps(body).encode()])

    assert fetch_wiki_pages(["Nowhere"]) == {}


def test_fetch_wiki_pages_batches_at_the_api_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    titles = [f"Page {index}" for index in range(WIKI_TITLES_PER_REQUEST + 3)]
    bodies = [
        json.dumps({"query": {"pages": [_page(title, title) for title in titles[:50]]}}).encode(),
        json.dumps({"query": {"pages": [_page(title, title) for title in titles[50:]]}}).encode(),
    ]
    requests = _patch_wiki(monkeypatch, bodies)

    fetched = fetch_wiki_pages(titles)

    assert len(requests) == 2
    assert len(fetched) == len(titles)


def test_fetch_wiki_page_titles_follows_the_continue_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bodies = [
        json.dumps(
            {
                "query": {"allpages": [{"title": "Money making guide/A"}]},
                "continue": {"apcontinue": "Money making guide/B"},
            }
        ).encode(),
        json.dumps({"query": {"allpages": [{"title": "Money making guide/B"}]}}).encode(),
    ]
    requests = _patch_wiki(monkeypatch, bodies)

    titles = fetch_wiki_page_titles("Money making guide/")

    assert titles == ["Money making guide/A", "Money making guide/B"]
    assert len(requests) == 2


def test_fetch_text_returns_the_decoded_body(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, _responds(b'"Task","XP/Kill"\n"Gargoyle","105"\n'))

    assert fetch_text(slayer_sheet_url(), what="slayer sheet").startswith('"Task","XP/Kill"')


def test_fetch_text_reports_the_http_status(monkeypatch: pytest.MonkeyPatch) -> None:
    error = urllib.error.HTTPError("https://example.test", 404, "Not Found", Message(), None)
    _patch_urlopen(monkeypatch, _raises(error))

    with pytest.raises(FetchError, match="HTTP 404 fetching slayer sheet"):
        fetch_text("https://example.test", what="slayer sheet")


def test_the_slayer_sheet_url_names_the_tab() -> None:
    assert "Mob%20Data" in slayer_sheet_url()
    assert "out:csv" in slayer_sheet_url()


def test_the_world_map_comes_back_as_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    """A PNG, not JSON, so it does not go through `_fetch_json_object`."""
    png = b"\x89PNG\r\n\x1a\n" + b"payload"
    calls = _patch_urlopen(monkeypatch, _responds(png))

    assert fetch_world_map() == png
    assert calls[0][0] == WORLD_MAP_URL
    assert WORLD_MAP_URL.endswith("/osrs_world_map.png")


def test_an_empty_world_map_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zero bytes would be cached and then served as a broken image forever."""
    _patch_urlopen(monkeypatch, _responds(b""))

    with pytest.raises(FetchError, match="empty response"):
        fetch_world_map()


def test_a_world_map_http_error_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(
        monkeypatch,
        _raises(urllib.error.HTTPError(WORLD_MAP_URL, 404, "Not Found", Message(), None)),
    )

    with pytest.raises(FetchError, match="HTTP 404 fetching world map image"):
        fetch_world_map()
