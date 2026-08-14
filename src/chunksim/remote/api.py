"""HTTP access to the chunk-picker database and the reference data around it.

Four hosts, no credentials anywhere: the chunk-picker Firebase Realtime
Database, upstream's `gh-pages` raw files, the OSRS wiki (its MediaWiki API and
one rendered page), and one published Google Sheet. The web app reaches Firebase
through the JS SDK, but the REST API exposes the same data and the database is
world-readable, so a plain GET is enough.

**The map tiles are a fifth host this module never calls.** `MAP_TILE_URL` is a
template handed to the browser, which loads the tiles itself - see that
constant for why keeping the bytes out of this process is a licence decision
rather than an optimisation. The only request made on their behalf is
`fetch_map_tile_version`, and that asks the wiki for a page of HTML.

**`User-Agent` differs by host, and the two rules are not in tension.** The
Firebase and GitHub calls send none: urllib's default identifies neither
the user nor this project, and adding one would only publish information nobody
asked for. The wiki calls send `WIKI_USER_AGENT`, because an anonymous request
there is answered with HTTP 403 - it applies MediaWiki's user-agent policy,
which asks automated clients to say what they are. Both rules come from the
same principle: send what the endpoint needs to serve the request and nothing
more about who is asking.

The only module that touches the network; raises `FetchError`. Note that an
unknown map comes back as HTTP 200 with a bare `null` rather than a 404, so
that is the *only* "no such map" signal available.

`urllib` is imported inside the two functions that fetch, not at module scope.
`cache.py` imports this module for `map_url` alone, so every command paid
`urllib.request`'s ~11ms import (it drags in `logging` and `traceback`) to reach
one `str.format` - and only `fetch`/`chunkinfo` ever open a socket. Patching
`urllib.request.urlopen` still works: the name is resolved on the module object
at call time, which is what `tests/test_api.py` does.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from chunksim.remote.wiki import map_tile_version

MAP_URL = "https://chunkpicker.firebaseio.com/maps/{map_id}.json"

#: Where this project's own releases are published. A **fifth host**, and the
#: only one that is about `chunksim` rather than about the game.
#:
#: **It has to be a public repository.** GitHub answers an unauthenticated
#: request for a private one with 404 rather than 403, so an update check
#: against a private repo cannot tell "no release yet" from "not allowed" - and
#: the fix is not a token. A token shipped inside a distributed application is
#: a published token, granting read access to everything the account owns.
#:
#: **`latest` excludes pre-releases and drafts, so this 404s while every
#: published release is one.** That is not a fault to go looking for: it is the
#: pre-release checkbox doing its job, and the update check correctly says
#: nothing rather than offering a build its author marked as not ready.
#: Measured against `v0.1.0` on 2026-08-14 - the release existed, its asset and
#: digest were exactly right, and this endpoint still answered 404. Reading
#: `/releases` and filtering would change that, and would need a channel
#: setting to be worth having.
RELEASES_URL = "https://api.github.com/repos/stevenhartin/chunksim/releases/latest"

#: The installer asset a Windows build publishes, by convention. Matched
#: case-insensitively against each asset's name; anything else in the release
#: (source archives, other platforms) is ignored rather than offered.
INSTALLER_ASSET_SUFFIX = "-setup.exe"

# gh-pages is upstream's default branch and where the live site is served
# from; `main` 404s.
_UPSTREAM_RAW = "https://raw.githubusercontent.com/source-chunk/chunk-picker-v2/gh-pages/{path}"
CHUNKINFO_URL = _UPSTREAM_RAW.format(path="chunkpicker-chunkinfo-export.json")
TASKS_MAP_URL = _UPSTREAM_RAW.format(path="tasksMap.json")
#: The OSRS wiki's cartography tiles, which the browser loads **directly**.
#:
#: **This project never fetches, stores or serves a tile.** The template is
#: handed to the page and the page puts it in an `<img>`, so the bytes go from
#: the wiki's CDN to the user's browser cache and touch nothing here. That is
#: deliberate and it is about the licence: the tiles are CC BY-NC-SA 3.0 and
#: this project is GPL-3.0, so caching them in `cache/` or serving them off
#: `127.0.0.1` would make this a redistributor of NonCommercial artwork. The
#: relicense from MIT changed nothing here and could not: a NonCommercial
#: clause is an added restriction, which GPL-3.0 forbids outright.
#: Pointing at them makes it a page with a picture on it, which is what every
#: other site embedding a map is.
#:
#: `{version}` is `MAP_TILE_VERSION_URL`'s answer; `{map_id}` selects a tile
#: set (see `MAP_TILE_MAP_ID`); `{z}` is -3..3 with `256 / 2**z` game tiles per
#: 256px tile, so **z=2 is exactly one chunk per tile**; `{plane}` is the
#: floor, 0..3; and `{x}`/`{y}` are the tile indices, y counting *northward*
#: like the game's own coordinates rather than downward like an image row.
#:
#: Both halves are `wgKartographerDataConfig`'s own `baseTileURL` and
#: `tileURLFormat`, read off a page that embeds a map. Kartographer writes the
#: y as `{-y}` because Leaflet counts rows downward and this scheme does not;
#: nothing here has a Leaflet to undo, so it is a plain `{y}`.
MAP_TILE_URL = (
    "https://maps.runescape.wiki/osrs/versions/{version}"
    "/tiles/rendered/{map_id}/{z}/{plane}_{x}_{y}.png"
)

#: **`-1` is "Full Map", and it is the whole point of using this tiling.**
#: `0` is the surface alone; `-1` is every rendered region including the 219
#: named dungeons, instances and boss rooms - and where the two overlap the
#: tiles are *byte-identical* (checked by hash on Lumbridge, Varrock and Al
#: Kharid), so there is nothing to trade away. It is also what the wiki's own
#: `World_map` page asks for. That single change takes the chunks this project
#: can draw from 1,176 to 1,905 of the export's 1,919 numeric ids.
MAP_TILE_MAP_ID = -1

#: Where `MAP_TILE_URL`'s `{version}` comes from: the MediaWiki message
#: Kartographer itself reads (`mw.message('kartographer-map-version')`),
#: served raw. There is no index of renders anywhere - no `versions.json`, no
#: directory listing - so this *is* the published answer rather than a
#: workaround, and `?action=raw` returns the bare string and nothing else.
MAP_TILE_VERSION_URL = (
    "https://oldschool.runescape.wiki/w/MediaWiki:Kartographer-map-version?action=raw"
)

#: The credit the page shows beside the map. CC BY-NC-SA 3.0 asks for
#: attribution, and this is the whole of what that costs when you link rather
#: than copy.
MAP_TILE_ATTRIBUTION = "Map tiles © OSRS Wiki (CC BY-NC-SA 3.0)"

#: The per-section masks the GUI shades a split chunk with, and the skill
#: icons the tasks panel labels rows with. Same artwork argument as the world
#: map, and the same answer: fetched, never committed. **One file at a time
#: and only when asked** - there are 1,534 masks and a chunk has a handful of
#: sections, so anything eager here would spend 14MiB to draw one square.
SECTION_OVERLAY_URL = _UPSTREAM_RAW.format(path="resources/section_overlays/{name}.png")
SKILL_ICON_URL = _UPSTREAM_RAW.format(path="resources/{skill}_skill.png")
#: The six Combat Achievement tier badges, from the wiki rather than from
#: upstream - source-chunk ships no icon for them. ~300 bytes each, and the
#: **wiki**, so this is the one image fetch that needs `WIKI_USER_AGENT`.
CA_TIER_ICON_URL = "https://oldschool.runescape.wiki/images/Combat_Achievements_-_{tier}_tier_icon.png"


WIKI_API_URL = "https://oldschool.runescape.wiki/api.php"

#: KodakKid3's OSRS Slayer Spreadsheet, published to the web, read as CSV.
SLAYER_SHEET_ID = "1KR92OY-sK6I8wAAuFLt2TgLq-xadG7yA6Bzgb5YnVQM"
SLAYER_SHEET_TAB = "Mob Data"
#: The tab holding assignment sizes, ordinary and extended, per master.
TASK_LENGTHS_TAB = "Task Lengths"
_SHEET_CSV = "https://docs.google.com/spreadsheets/d/{doc}/gviz/tq?tqx=out:csv&sheet={sheet}"

#: **The wiki requires this and the rest of this module deliberately has no
#: equivalent.** An anonymous `urlopen` to the OSRS wiki is answered with HTTP
#: 403 - measured, not assumed - because it follows MediaWiki's user-agent
#: policy, which asks automated clients to identify themselves and what they
#: are. That is the *opposite* of the reason the Firebase and GitHub calls
#: below send no `User-Agent`: there, urllib's default identifies neither the
#: user nor this project, so adding one would only leak information. Here the
#: information is what is being asked for, and withholding it fails the
#: request. It names the project and its repository, and nothing about who is
#: running it.
WIKI_USER_AGENT = "chunksim/0.1 (+https://github.com/stevenhartin/chunksim)"

#: The MediaWiki API's cap on `titles` for an anonymous caller.
WIKI_TITLES_PER_REQUEST = 50

DEFAULT_TIMEOUT = 30.0


class FetchError(Exception):
    """A map could not be retrieved, or was not in the expected shape."""


@dataclass(frozen=True)
class ReleaseAsset:
    """A downloadable file attached to a release."""

    name: str
    url: str
    size: int
    #: `sha256:<hex>` as GitHub reports it, or `None` for an older release that
    #: predates the field. **`None` means the installer path refuses to run**:
    #: an executable this project is about to launch is not something to take
    #: on the strength of the transport alone.
    digest: str | None

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "url": self.url, "size": self.size, "digest": self.digest}


@dataclass(frozen=True)
class Release:
    """The newest published release, as the update check needs it."""

    version: str
    #: The release page, for a human to read before deciding.
    url: str
    installer: ReleaseAsset | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "url": self.url,
            "installer": self.installer.as_dict() if self.installer else None,
        }


def fetch_latest_release(timeout: float = DEFAULT_TIMEOUT) -> Release | None:
    """The newest published release, or `None` if there are none yet.

    `None` is an ordinary answer, not a failure: a repository with no releases
    answers 404, and so does a private one - which is why `RELEASES_URL` says
    the repository has to be public. Everything else raises `FetchError`, and
    **every caller is expected to swallow it**. An update check that interrupts
    someone to say it could not run is worse than one that quietly does not.

    No custom headers, like every other public endpoint here. urllib's default
    User-Agent satisfies GitHub's requirement that API requests carry one, and
    it says nothing about who is asking.
    """
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(RELEASES_URL, timeout=timeout) as response:
            payload: Any = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise FetchError(f"HTTP {exc.code} checking for updates") from exc
    except TimeoutError as exc:
        raise FetchError(f"timed out after {timeout:g}s checking for updates") from exc
    except urllib.error.URLError as exc:
        raise FetchError(f"network error checking for updates: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise FetchError(f"malformed JSON checking for updates: {exc}") from exc

    if not isinstance(payload, dict):
        raise FetchError("unexpected shape checking for updates")
    tag = payload.get("tag_name")
    if not isinstance(tag, str) or not tag:
        raise FetchError("release carries no tag")

    return Release(
        # `v0.2.0` and `0.2.0` are the same release; the comparison is over
        # numbers, so the prefix is dropped here rather than everywhere after.
        version=tag[1:] if tag.startswith("v") else tag,
        url=str(payload.get("html_url") or ""),
        installer=_installer_asset(payload.get("assets")),
    )


def _installer_asset(assets: Any) -> ReleaseAsset | None:
    """The Windows installer among a release's assets, if it published one."""
    if not isinstance(assets, list):
        return None
    for entry in assets:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        url = entry.get("browser_download_url")
        if not isinstance(name, str) or not isinstance(url, str):
            continue
        if not name.lower().endswith(INSTALLER_ASSET_SUFFIX):
            continue
        digest = entry.get("digest")
        size = entry.get("size")
        return ReleaseAsset(
            name=name,
            url=url,
            size=size if isinstance(size, int) else 0,
            digest=digest if isinstance(digest, str) and digest else None,
        )
    return None


def map_url(map_id: str) -> str:
    """Return the REST endpoint holding `map_id`'s state."""
    return MAP_URL.format(map_id=map_id)


def fetch_map(map_id: str, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Return the live state for `map_id`.

    No custom headers are sent: urllib's default User-Agent identifies neither
    the user nor this project, so setting one would only add information.
    """
    import urllib.error
    import urllib.request

    url = map_url(map_id)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload: Any = json.load(response)
    except urllib.error.HTTPError as exc:
        raise FetchError(f"HTTP {exc.code} fetching map {map_id!r}") from exc
    except TimeoutError as exc:
        raise FetchError(f"timed out after {timeout:g}s fetching map {map_id!r}") from exc
    except urllib.error.URLError as exc:
        raise FetchError(f"network error fetching map {map_id!r}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise FetchError(f"malformed JSON for map {map_id!r}: {exc}") from exc

    # An unknown path yields HTTP 200 with a bare `null` rather than a 404, so
    # this is the only signal that the map does not exist.
    if payload is None:
        raise FetchError(f"no such map: {map_id!r}")
    if not isinstance(payload, dict):
        raise FetchError(
            f"expected an object for map {map_id!r}, got {type(payload).__name__}"
        )
    return payload


def fetch_chunkinfo(timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Return upstream's chunk/section/challenge reference data (~10MB, static)."""
    return _fetch_json_object(CHUNKINFO_URL, timeout, what="chunkinfo export")


def fetch_tasks_map(timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Return upstream's task-name <-> `t_N` id interning table."""
    return _fetch_json_object(TASKS_MAP_URL, timeout, what="tasks map")


def slayer_sheet_url(doc: str = SLAYER_SHEET_ID, sheet: str = SLAYER_SHEET_TAB) -> str:
    """The CSV export endpoint for one tab of a published Google Sheet."""
    import urllib.parse

    return _SHEET_CSV.format(doc=doc, sheet=urllib.parse.quote(sheet))


def fetch_wiki_page_titles(prefix: str, timeout: float = DEFAULT_TIMEOUT) -> list[str]:
    """Every wiki page whose title starts with `prefix`.

    Walks `list=allpages` through its `continue` cursor, so the ~500 money
    making guides come back in one call rather than one per page.
    """
    titles: list[str] = []
    cursor: str | None = None
    while True:
        query = {
            "action": "query",
            "list": "allpages",
            "apprefix": prefix,
            "aplimit": "500",
            "format": "json",
            "formatversion": "2",
        }
        if cursor is not None:
            query["apcontinue"] = cursor
        payload = _fetch_json_object(
            _wiki_url(query), timeout, what=f"wiki page list for {prefix!r}", wiki=True
        )
        pages = _listing(payload.get("query"), "allpages")
        titles.extend(str(page["title"]) for page in pages if isinstance(page, dict))

        follow = payload.get("continue")
        cursor = follow.get("apcontinue") if isinstance(follow, dict) else None
        if cursor is None:
            return titles


def fetch_wiki_transclusions(template: str, timeout: float = DEFAULT_TIMEOUT) -> list[str]:
    """Every article-namespace page that transcludes `template`.

    The counterpart to `fetch_wiki_page_titles` for data held in a template
    rather than under a title prefix: `{{Prayer info}}` is invoked by 193
    remains pages whose names have nothing in common, so a prefix walk cannot
    find them and a hardcoded list would go stale silently.

    `einamespace=0` keeps it to articles - the template's own documentation and
    the sandbox copies transclude it too and carry no data.
    """
    titles: list[str] = []
    cursor: str | None = None
    while True:
        query = {
            "action": "query",
            "list": "embeddedin",
            "eititle": template,
            "einamespace": "0",
            "eilimit": "500",
            "format": "json",
            "formatversion": "2",
        }
        if cursor is not None:
            query["eicontinue"] = cursor
        payload = _fetch_json_object(
            _wiki_url(query), timeout, what=f"pages using {template!r}", wiki=True
        )
        pages = _listing(payload.get("query"), "embeddedin")
        titles.extend(str(page["title"]) for page in pages if isinstance(page, dict))

        follow = payload.get("continue")
        cursor = follow.get("eicontinue") if isinstance(follow, dict) else None
        if cursor is None:
            return titles


def fetch_wiki_pages(
    titles: Sequence[str], timeout: float = DEFAULT_TIMEOUT
) -> dict[str, str]:
    """Return `{requested title: wikitext}` for each of `titles`.

    Batched at `WIKI_TITLES_PER_REQUEST`, and keyed by the title the *caller*
    asked for rather than the one the API answered with. MediaWiki normalises
    titles and follows redirects, so `Dragon Slayer` comes back as
    `Dragon Slayer I`; keying on the response would silently drop every title
    that needed either, which is the whole join for those quests. A page that
    does not exist is simply absent.
    """
    fetched: dict[str, str] = {}
    for start in range(0, len(titles), WIKI_TITLES_PER_REQUEST):
        batch = list(titles[start : start + WIKI_TITLES_PER_REQUEST])
        payload = _fetch_json_object(
            _wiki_url(
                {
                    "action": "query",
                    "prop": "revisions",
                    "rvprop": "content",
                    "rvslots": "main",
                    "redirects": "1",
                    "titles": "|".join(batch),
                    "format": "json",
                    "formatversion": "2",
                }
            ),
            timeout,
            what=f"{len(batch)} wiki page(s)",
            wiki=True,
        )
        fetched.update(_wiki_contents(payload, batch))
    return fetched


def fetch_bucket(query: str, timeout: float = DEFAULT_TIMEOUT) -> list[dict[str, Any]]:
    """Run one Bucket query against the wiki and return its rows.

    Bucket is the wiki's own structured-data extension - `{{Recipe}}`,
    `{{Mmgtable}}` and the quest infoboxes all write into it - so one request
    answers what would otherwise be a page fetch and a wikitext parse per item.
    `bucket('recipe').select('page_name','production_json').where('uses_skill','Herblore').limit(5000).run()`
    returns every Herblore recipe with its level, experience, materials and
    tick cost.

    **A failed query is HTTP 200 with an `error` key**, which is the same trap
    as Firebase answering an unknown map with a bare `null`: read the status
    only and a typo in a field name parses as "this skill has no recipes". So
    the key is checked explicitly and raised as a `FetchError`.
    """
    payload = _fetch_json_object(
        _wiki_url({"action": "bucket", "format": "json", "query": query}),
        timeout,
        what="a bucket query",
        wiki=True,
    )
    error = payload.get("error")
    if error:
        raise FetchError(f"bucket query refused: {error}")
    rows = payload.get("bucket")
    if not isinstance(rows, list):
        raise FetchError(f"expected rows for a bucket query, got {type(rows).__name__}")
    return [row for row in rows if isinstance(row, dict)]


def fetch_text(
    url: str, timeout: float = DEFAULT_TIMEOUT, *, what: str, wiki: bool = False
) -> str:
    """Fetch `url` as text.

    The sibling of `_fetch_json_object` for a body that is not JSON - the
    slayer spreadsheet's CSV export, and the wiki's rendered map page. Same
    four failure conversions, and no shape validation to do beyond decoding.

    `wiki` sends `WIKI_USER_AGENT`, for the same reason `_fetch_json_object`
    has the flag: the sheet is a Google export that wants no header and the
    wiki answers an anonymous client with a 403.
    """
    import urllib.error
    import urllib.request

    target: Any = (
        urllib.request.Request(url, headers={"User-Agent": WIKI_USER_AGENT}) if wiki else url
    )
    try:
        with urllib.request.urlopen(target, timeout=timeout) as response:
            raw: bytes = response.read()
    except urllib.error.HTTPError as exc:
        raise FetchError(f"HTTP {exc.code} fetching {what}") from exc
    except TimeoutError as exc:
        raise FetchError(f"timed out after {timeout:g}s fetching {what}") from exc
    except urllib.error.URLError as exc:
        raise FetchError(f"network error fetching {what}: {exc.reason}") from exc

    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FetchError(f"undecodable response for {what}: {exc}") from exc


def _wiki_url(query: dict[str, str]) -> str:
    import urllib.parse

    return f"{WIKI_API_URL}?{urllib.parse.urlencode(query)}"


def _listing(container: Any, key: str) -> list[Any]:
    """A list under `container[key]`, or empty - the API omits empty results."""
    if not isinstance(container, dict):
        return []
    value = container.get(key)
    return value if isinstance(value, list) else []


def _wiki_contents(payload: dict[str, Any], requested: list[str]) -> dict[str, str]:
    """Map each requested title onto its page content.

    `normalized` and `redirects` are the API's own record of what it did to
    each title, and following them backwards is what lets the result be keyed
    by what was asked for.
    """
    query = payload.get("query")
    resolved: dict[str, str] = {}
    for hop in ("normalized", "redirects"):
        for entry in _listing(query, hop):
            if isinstance(entry, dict) and "from" in entry and "to" in entry:
                resolved[str(entry["from"])] = str(entry["to"])

    def final(title: str) -> str:
        seen = {title}
        while (nxt := resolved.get(title)) is not None and nxt not in seen:
            title = nxt
            seen.add(title)
        return title

    by_title: dict[str, str] = {}
    for page in _listing(query, "pages"):
        if not isinstance(page, dict):
            continue
        revisions = page.get("revisions")
        if not isinstance(revisions, list) or not revisions:
            continue
        slots = revisions[0].get("slots") if isinstance(revisions[0], dict) else None
        main = slots.get("main") if isinstance(slots, dict) else None
        content = main.get("content") if isinstance(main, dict) else None
        if isinstance(content, str):
            by_title[str(page.get("title"))] = content

    return {title: by_title[final(title)] for title in requested if final(title) in by_title}


def fetch_map_tile_version(timeout: float = DEFAULT_TIMEOUT) -> str:
    """The current map-tile render, read from the wiki message that names it.

    **The only request this project makes on the tiles' behalf**, and it is
    for a dozen bytes of text rather than for artwork - the tiles themselves
    the browser fetches directly.

    A wiki URL, so it sends `WIKI_USER_AGENT` like every other call to that
    host; the tile CDN behind it 403s an anonymous client too, but that is the
    browser's request to make and browsers always identify themselves.

    Raises `FetchError` when the message cannot be read *or* when it does not
    look like a version, because both leave the caller in the same position -
    holding nothing usable - and a message page that starts returning an error
    document would otherwise become a version string made of HTML.
    """
    raw = fetch_text(MAP_TILE_VERSION_URL, timeout, what="map tile version", wiki=True)
    version = map_tile_version(raw)
    if version is None:
        raise FetchError(
            f"no tile version in {MAP_TILE_VERSION_URL} - the wiki's map page "
            "no longer embeds a tile URL; set CHUNKSIM_TILE_VERSION to pin one"
        )
    return version


def fetch_section_overlay(name: str, timeout: float = DEFAULT_TIMEOUT) -> bytes:
    """One section mask: a 192x192 1-bit PNG, `name` being `<chunk>-<section>`.

    The mask's opaque pixels are the section - a `tRNS` chunk makes grey 0
    transparent, which is what lets upstream composite several of them onto
    one square. Whoever draws it is relying on that, so it is recorded here
    rather than only in the JavaScript that depends on it.
    """
    return _fetch_bytes(
        SECTION_OVERLAY_URL.format(name=name), timeout, what=f"section overlay {name}"
    )


def fetch_skill_icon(skill: str, timeout: float = DEFAULT_TIMEOUT) -> bytes:
    """One skill's icon, as upstream names them (`Attack_skill.png`)."""
    return _fetch_bytes(
        SKILL_ICON_URL.format(skill=skill), timeout, what=f"{skill} icon"
    )


def fetch_ca_tier_icon(tier: str, timeout: float = DEFAULT_TIMEOUT) -> bytes:
    """One Combat Achievement tier badge (`easy` ... `grandmaster`).

    The wiki, not upstream, so it carries `WIKI_USER_AGENT` - an anonymous
    request for one of these is answered with HTTP 403 (measured).
    """
    return _fetch_bytes(
        CA_TIER_ICON_URL.format(tier=tier), timeout, what=f"{tier} tier icon", wiki=True
    )


def _fetch_bytes(url: str, timeout: float, *, what: str, wiki: bool = False) -> bytes:
    import urllib.error
    import urllib.request

    request = urllib.request.Request(
        url, headers={"User-Agent": WIKI_USER_AGENT} if wiki else {}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload: bytes = response.read()
    except urllib.error.HTTPError as exc:
        raise FetchError(f"HTTP {exc.code} fetching {what}") from exc
    except TimeoutError as exc:
        raise FetchError(f"timed out after {timeout:g}s fetching {what}") from exc
    except urllib.error.URLError as exc:
        raise FetchError(f"network error fetching {what}: {exc.reason}") from exc

    if not payload:
        raise FetchError(f"empty response fetching {what}")
    return payload


def _fetch_json_object(
    url: str, timeout: float, *, what: str, wiki: bool = False
) -> dict[str, Any]:
    import urllib.error
    import urllib.request

    # A plain string URL where no headers are needed, so the Firebase and
    # GitHub calls keep the exact request they always made.
    target: Any = (
        urllib.request.Request(url, headers={"User-Agent": WIKI_USER_AGENT}) if wiki else url
    )
    try:
        with urllib.request.urlopen(target, timeout=timeout) as response:
            payload: Any = json.load(response)
    except urllib.error.HTTPError as exc:
        raise FetchError(f"HTTP {exc.code} fetching {what}") from exc
    except TimeoutError as exc:
        raise FetchError(f"timed out after {timeout:g}s fetching {what}") from exc
    except urllib.error.URLError as exc:
        raise FetchError(f"network error fetching {what}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise FetchError(f"malformed JSON for {what}: {exc}") from exc

    if not isinstance(payload, dict):
        raise FetchError(f"expected an object for {what}, got {type(payload).__name__}")
    return payload
