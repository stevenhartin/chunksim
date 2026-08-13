"""The contract between `app.js` and the Python that has to agree with it.

**These tests read source text; they never build a `Context` or call
`handle_request`.** Two constants cross into JavaScript as plain integers over
JSON - the `Edge` bitfield and the projection - with nothing enforcing
agreement, so a renumbered flag draws the hull on the wrong sides while every
test on either side still passes. The same goes for the tile pyramid, the
`WHOLE_CHUNK_SECTION` sentinel, and the interface rules that each replaced a
bug: one tooltip system, chip strips recording what is *off*, an action's reply
shape deciding whether it is polled.

They live apart from `test_gui_server.py` because they answer a different
question and are needed at a different time: **these are the only tests an
`app.js` or `style.css` change needs**, and with `fray-gui` installed editable
that change needs no reinstall either - so the whole front-end loop is edit,
run this file, reload the tab.

Reading the three resource files 42 times over costs 8.7ms measured, so they
are read per test rather than through a session fixture. The fixture would save
eight milliseconds and put an argument on every test in the file.
"""

from __future__ import annotations

import re
from pathlib import Path

from fray_claude.store import cache

def _app_js() -> str:
    from fray_claude.gui.http import RESOURCE_DIR

    return (RESOURCE_DIR / "app.js").read_text(encoding="utf-8")

def test_the_edge_bits_agree_across_the_two_languages() -> None:
    """`app.js` masks the same bitfield `worldmap.Edge` sets.

    Nothing forces these to match - the value crosses as a plain integer in
    JSON - so a renumbered flag would draw the hull on the wrong sides and
    every test on either side would still pass.
    """
    from fray_claude.gui.worldmap import Edge

    match = re.search(
        r"const TOP = (\d+), BOTTOM = (\d+), LEFT = (\d+), RIGHT = (\d+);", _app_js()
    )
    assert match is not None
    top, bottom, left, right = (int(value) for value in match.groups())

    assert (top, bottom, left, right) == (
        Edge.TOP.value,
        Edge.BOTTOM.value,
        Edge.LEFT.value,
        Edge.RIGHT.value,
    )

def test_the_hover_readout_inverts_the_real_projection() -> None:
    """The browser turns a square back into a chunk id without a round trip.

    That means it carries its own copy of the projection, and a copy that
    drifts would name the wrong chunk under the cursor - the sort of thing
    nobody notices until they paste the id into `fray unlock`.
    """
    from fray_claude.gui.worldmap import MAX_REGION_Y, MIN_REGION_X, REGION_STRIDE

    source = _app_js()
    # `gridToChunk`, which the hover readout and the candidate overlay both use.
    assert re.search(
        rf"\(gx \+ {MIN_REGION_X}\) \* {REGION_STRIDE} \+ \({MAX_REGION_Y} - gy\)", source
    )
    # `chunkToGrid`, the same projection run backwards.
    assert re.search(rf"\(id >> 8\) - {MIN_REGION_X}", source)
    assert re.search(rf"{MAX_REGION_Y} - \(id & 0xff\)", source)

def test_the_tile_pyramid_agrees_across_the_two_languages() -> None:
    """Three numbers cross into JavaScript with nothing enforcing agreement.

    `app.js` computes tile indices itself - a round trip per tile would be
    absurd - so it carries its own copy of the pyramid. Disagree and every
    tile is fetched at the wrong level, which draws a plausible-looking map of
    the wrong place.
    """
    from fray_claude.gui.worldmap import MAX_TILE_ZOOM, MIN_TILE_ZOOM, TILE_PIXELS

    source = _app_js()
    assert f"const TILE_PIXELS = {TILE_PIXELS};" in source
    assert f"const MIN_TILE_ZOOM = {MIN_TILE_ZOOM};" in source
    assert f"const MAX_TILE_ZOOM = {MAX_TILE_ZOOM};" in source
    # The span relation, which is the one piece of arithmetic that has to
    # match the wiki's scheme rather than merely match Python.
    assert "return TILE_PIXELS / Math.pow(2, z);" in source

def test_the_tile_placement_uses_the_edge_row_not_the_cell_row() -> None:
    """The off-by-one that draws a plausible map of the wrong place.

    `gridToChunk` uses `MAX_REGION_Y - region_y`, which numbers a *cell*:
    region 65 is row 0. `worldToScreenY` maps a world coordinate to where that
    *line* falls, and the line along the top of row 0 is region 65's north
    edge - one region further on. So it needs `MAX_REGION_Y + 1`, and using 65
    in both places puts every tile one row high.

    Caught by comparing the canvas against a raw tile, which matched to 0.016
    mean channel difference once fixed and 13.7 one pixel out. Pinned here
    because nothing else would notice.
    """
    from fray_claude.gui.worldmap import MAX_REGION_Y

    match = re.search(r"const GRID_TOP_REGION_Y = (\d+);", _app_js())
    assert match is not None
    assert int(match.group(1)) == MAX_REGION_Y + 1

def test_the_plane_reaches_the_tile_url_and_nothing_else() -> None:
    """**Changing floor changes the picture and no data at all.**

    A chunk is a region and a region contains every plane, so the unlocked
    set, the hull and every panel are identical on floor 3 and floor 0 - only
    the tiles differ. If a plane change ever started refetching a view, that
    would be a derivation per floor for no answer.
    """
    source = _app_js()

    assert "plane: 0," in source                      # part of the camera state
    assert '.replace("{plane}"' in source             # substituted into the URL
    # The handler invalidates and does nothing else - no loadView, no fetch.
    handler = re.search(
        r'el\.plane\.addEventListener\("change", \(\) => \{(.*?)\}\);', source, re.DOTALL
    )
    assert handler is not None
    body = handler.group(1)
    assert "invalidate()" in body
    assert "loadView" not in body and "getJSON" not in body

def test_a_higher_plane_sinks_the_ground_and_not_the_floor() -> None:
    """**A plane-N tile is one flat image holding both**, which is the whole
    difficulty.

    It is the ground floor faded back with this floor drawn over it - no
    transparency, and no separate overlay tile to ask for. Darkening the tile
    darkens the floor along with the ground, which is the bug this replaces.
    The fade is linear, so it is fitted per tile (`a` runs 0.13 to 0.52, so it
    cannot be assumed) and only the pixels that *fit* are sunk.
    """
    source = _app_js()

    assert "function composeFloor(" in source
    assert "function fitFade(" in source
    # The draw path and the coarse fallback both go through the composition,
    # or a fallback tile would come out undarkened.
    assert "const image = composedTile(z, x, y);" in source
    assert "composedTile(z - up, x >> up, y >> up)" in source
    # The ground floor is never composed against itself.
    assert "if (!state.plane || !floor) return floor;" in source
    # A whole-canvas scrim would darken the overlays too, and is gone.
    assert "drawPlaneScrim" not in source
    # Separating costs ~3ms a tile, so it is rationed per frame rather than
    # spent all at once; unbudgeted tiles draw unseparated, never blank.
    assert "composeBudget = PLANE_COMPOSE_BUDGET;" in source
    assert "if (composeBudget <= 0) {" in source

def test_a_missing_tile_falls_back_to_a_coarser_one() -> None:
    """A tile that is not there should look blurry, not black.

    Every level of the pyramid covers the same world, so the level above
    contains this tile at half the resolution. Without the walk a dropped
    request is a black square for the rest of the session - `onerror` cannot
    tell a 404 from a connection the browser gave up on, so a miss is also
    retried before it counts as absent.
    """
    source = _app_js()

    assert "function tileAncestor(" in source
    assert "tileAncestor(z, x, y)" in source          # drawTiles actually uses it
    # A miss is provisional: more than one attempt before it is remembered.
    match = re.search(r"const TILE_TRIES = (\d+);", source)
    assert match is not None and int(match.group(1)) > 1
    assert 'tileCache.delete(url)' in source          # so a later frame retries

def test_the_coarse_fallback_flips_y_and_not_x() -> None:
    """The one line in the fallback that can be silently wrong.

    Tile indices count *northward* while image rows run *southward*, so within
    an ancestor the child with the highest y is at the **top**. Getting it
    backwards mirrors every fallback vertically - which still looks like a
    plausible piece of map. Checked against real tiles: each of the four
    quadrants matched its parent crop and was the best of the four.
    """
    source = _app_js()

    assert "sx: (x & (step - 1)) * size," in source
    assert "sy: (step - 1 - (y & (step - 1))) * size," in source

def test_the_page_loads_tiles_from_the_wiki_and_not_from_here() -> None:
    """The licence lives in this assertion as much as in any docstring.

    A future edit that proxies tiles through `fray-gui` "for caching" would
    turn this project into a redistributor of NonCommercial artwork, and it
    would look like a performance win while doing it.
    """
    source = _app_js()

    assert "tiles.template" in source
    # No same-origin tile route, and no re-introduced world-map fetch.
    assert "/world_map" not in source
    assert 'image.crossOrigin = "anonymous";' in source

def test_the_tile_attribution_is_on_screen() -> None:
    """CC BY-NC-SA asks for credit, and a credit behind a menu is not one."""
    from fray_claude.gui.http import RESOURCE_DIR

    html = (RESOURCE_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="attribution"' in html
    assert "renderAttribution" in _app_js()

def test_the_whole_chunk_section_sentinel_agrees_across_the_two_languages() -> None:
    """An unsplit chunk's one section is drawn, not fetched.

    `server.WHOLE_CHUNK_SECTION` is a value the browser has to recognise to
    know it must fill the square itself. Disagree and it asks for
    `<chunk>-*.png`, which `cache.section_overlay_path` rejects - so the
    failure is a shading hole plus a 400 per square, in a mode nothing tests.
    """
    from fray_claude.gui.routes_derived import WHOLE_CHUNK_SECTION

    match = re.search(r'const WHOLE_CHUNK = "([^"]+)";', _app_js())
    assert match is not None
    assert match.group(1) == WHOLE_CHUNK_SECTION

def _resources() -> tuple[str, str, str]:
    from fray_claude.gui.http import RESOURCE_DIR

    return (
        (RESOURCE_DIR / "index.html").read_text(encoding="utf-8"),
        (RESOURCE_DIR / "app.js").read_text(encoding="utf-8"),
        (RESOURCE_DIR / "style.css").read_text(encoding="utf-8"),
    )

def test_every_element_the_page_reaches_for_exists() -> None:
    """`app.js` looks its elements up once, by id, into `el`.

    A renamed or dropped element leaves `el.thing` undefined and the failure
    lands wherever it is *used*, which may be three tabs away and only on a
    map that has something to show. Checking the list against the markup is
    the cheapest place to catch it.
    """
    html, js, _ = _resources()

    ids = set(re.findall(r'id="([^"]+)"', html))
    loop = re.search(r"for \(const id of \[(.*?)\]\)", js, re.DOTALL)
    assert loop is not None
    asked = set(re.findall(r'"([^"]+)"', loop.group(1)))

    assert asked, "the boot loop found no ids at all"
    assert asked <= ids, f"asked for but not in the markup: {sorted(asked - ids)}"

def test_every_style_token_is_defined() -> None:
    """The stylesheet's lengths all come from one scale.

    `var(--s7)` where the scale stops at `--s6` is not an error anywhere - the
    declaration is simply dropped and the element loses its padding, which
    reads as a layout bug with no cause.
    """
    _, _, css = _resources()

    defined = set(re.findall(r"^\s*(--[a-z0-9-]+)\s*:", css, re.MULTILINE))
    used = set(re.findall(r"var\((--[a-z0-9-]+)", css))

    assert used - defined == set(), f"undefined tokens: {sorted(used - defined)}"
    assert defined - used == set(), f"dead tokens: {sorted(defined - used)}"

def test_there_is_one_tooltip_system() -> None:
    """`title` and `data-tip` both show a tooltip, and both at once shows two.

    The custom one can carry a heading, a note and a keyboard hint; the native
    one is a plain string on a browser delay. Mixing them meant the bar behaved
    differently from every list under it.
    """
    html, _, _ = _resources()

    assert 'title="' not in html
    assert "data-tip=" in html

def test_the_scrolling_panes_reserve_their_gutter() -> None:
    """Chrome's overlay scrollbar sits *on top* of the last characters of a
    long task name, so the thing you are reading is the thing it covers.

    `scrollbar-gutter: stable` takes the width out of the content box whether
    or not the bar is showing, which also stops the pane reflowing the moment
    a list grows past the fold.
    """
    _, _, css = _resources()

    pane = re.search(r"\.pane > div:last-child \{(.*?)\}", css, re.DOTALL)
    assert pane is not None
    assert "scrollbar-gutter: stable" in pane.group(1)

def test_an_action_that_answers_inline_is_not_polled_as_a_job() -> None:
    """**Three of the six actions finish before they reply**, and reading
    `{ job }` off all six is what left the Maps tab showing deleted maps.

    `fetch`, `simulate` and `refresh` hand back a job id; `maps/remove`,
    `derived/prune` and `window` do the work and hand back the result. Polling
    `/api/jobs/undefined` 404s, and the 404 path treated that as "nothing more
    to say" - so the refresh callback never ran.
    """
    _, js, _ = _resources()

    assert "if (reply && reply.job) return followJob(" in js
    # The inline branch runs the callback rather than dropping it.
    assert "await onDone?.(reply);" in js

def test_the_chip_gestures_are_click_shift_ctrl() -> None:
    """Everything on by default, and narrowing to one is a single click.

    The strip records what is *off* rather than what is on, which is what
    makes a category nobody has seen yet default to on - holding the selected
    set froze it at whatever the first chunk happened to contain.
    """
    _, js, _ = _resources()

    body = re.search(r"function applyChipGesture\(.*?\n\}", js, re.DOTALL)
    assert body is not None
    assert "event.shiftKey" in body.group(0) and "off.delete(key)" in body.group(0)
    assert "event.ctrlKey || event.metaKey" in body.group(0) and "off.add(key)" in body.group(0)
    assert "off.clear();" in body.group(0)
    # Nothing anywhere holds a positive selection any more.
    assert "chunkCategories" not in js and "taskSections" not in js
    # Clicking the isolated chip widens back to everything: narrowing to one is
    # one click, so the way out has to be one click on the same control.
    assert "let isolated = !off.has(key);" in body.group(0)
    assert "if (isolated) return;" in body.group(0)

def test_a_truncated_list_can_be_opened() -> None:
    """"17 more" used to be a dead grey line naming what it would not show."""
    _, js, css = _resources()

    assert "function withMore(" in js
    assert 'data-more="' in js
    # Collapsing is a second press, not something that happens on scroll.
    assert "Show fewer" in js
    body = re.search(r"function withMore\(.*?\n\}", js, re.DOTALL)
    assert body is not None and "scroll" not in body.group(0)
    assert ".more-toggle" in css

def test_removing_maps_asks_first() -> None:
    """`maps rm` deletes directories and is not undoable."""
    _, js, _ = _resources()

    assert "function confirmAction(" in js
    assert js.count("await confirmAction(") >= 2       # one map, and all of them
    # The derived cache is pure recomputation, so it is *not* gated.
    prune = re.search(r'getElementById\("prune"\)\.onclick.*?;', js, re.DOTALL)
    assert prune is not None and "confirmAction" not in prune.group(0)

def test_the_page_asks_the_server_which_build_it_is() -> None:
    """**Baking the stamp into `app.js` would answer the wrong question.**

    The page is served by an install that `--host` may put on a different
    machine from the checkout anyone is editing, so the answer has to be the
    server's. And the age is re-rendered on the poll rather than only at boot,
    or a tab left open all afternoon goes on claiming the install happened a
    minute ago.
    """
    _, js, css = _resources()

    assert '"/api/build"' in js
    assert ".watermark" in css
    poll = re.search(r"async function poll\(\) \{(.*?)\n\}", js, re.DOTALL)
    assert poll is not None and "renderBuild()" in poll.group(1)

def test_the_area_labels_are_drawn_over_the_hull_and_read_the_same_map() -> None:
    """Two things the panel and the canvas have to agree on.

    A label under the hull is a name with a line through it; a hover readout
    reading some other source is a name that disagrees with the one on screen.
    """
    source = _app_js()

    layers = re.search(r"const LAYERS = \[(.*?)\];", source, re.DOTALL)
    assert layers is not None
    order = [n.strip() for n in layers.group(1).replace("\n", " ").split(",") if n.strip()]
    assert order.index("drawAreas") > order.index("drawHull")
    # **Two maps, one request, no second copy that could drift.** `/api/areas`
    # carries `areas` (which regions *are* a named place, for the labels drawn
    # on the map) and `labels` (what to call a chunk, for every place an id is
    # written); `loadAreas` fills both and nothing else writes either.
    assert "state.areas = payload.areas" in source
    assert "state.labels = payload.labels" in source
    assert source.count("state.labels[chunkId]") == 1, "chunkLabel is the only reader"
    assert 'getJSON("/api/areas")' in source

def test_the_page_strips_task_markup_for_display() -> None:
    """Task names are markup-bearing keys and the raw form must not be shown.

    `~|Dom Onion's Reward Shop|~` is what everything is *keyed* by; stripping
    it is display-only, which is why the browser does it rather than the
    server. Mirrors `challenges.strip_task_markup`, and the page applies it
    only to names and details - other branches of the export use `~` and `|`
    for real.
    """
    source = _app_js()

    assert "function plain(" in source
    # Every place a task-ish string reaches innerHTML goes through it.
    assert source.count("plain(") >= 5

def test_no_unescaped_interpolation_lands_inside_an_attribute() -> None:
    """**`raw()` is for element content and never for an attribute.**

    Inside `data-tip="${...}"` it splices unescaped quotes straight through
    the closing quote and the markup after it lands on screen as text - which
    is what a tooltip built from `<span class="sub">` did. `tmpl` escapes an
    ordinary interpolation, and the browser decodes it again when
    `dataset.tip` is read, so the HTML arrives intact having never been able
    to escape its attribute.

    Cheap to get wrong and invisible in review, so it is asserted rather than
    remembered.
    """
    source = _app_js()

    offenders = re.findall(r'=\s*"\$\{raw\(', source)

    assert not offenders, f"{len(offenders)} raw() interpolations inside an attribute"

def test_the_default_map_id_agrees_across_the_two_languages() -> None:
    """The placeholder promises what blank does, and nothing enforces it.

    A third constant crossing into JavaScript over no wire at all - see the
    `Edge` bitfield and the projection. The symptom of drift is a box that
    says `fray` and fetches something else.
    """
    _, js, _ = _resources()

    declared = re.search(r'const DEFAULT_MAP_ID = "([^"]+)"', js)

    assert declared is not None
    assert declared.group(1) == cache.DEFAULT_MAP_ID

def test_the_panel_offers_both_halves_of_the_unlock(tmp_path: Path) -> None:
    """**Asking and taking are two verbs and the page carries both.**

    `GET /api/unlock` prices a candidate and keeps nothing; `POST /api/unlock`
    saves the world it was describing. The preview dialog is where you decide,
    so the save lives in its footer as well as on the chunk panel.
    """
    _, js, _ = _resources()

    assert 'id="do-unlock"' in js and 'id="preview-unlock"' in js
    assert "function askUnlock(" in js
    # It asks for a name before writing anything, and posts what it was given.
    body = re.search(r"function askUnlock\(.*?\n\}\n", js, re.DOTALL)
    assert body is not None
    assert 'getElementById("unlock-name")' in body.group(0)
    assert '"/api/unlock",' in body.group(0)

def test_the_strip_appears_only_for_a_run() -> None:
    """The page asks `/api/timeline` and shows the strip on a 200.

    A fetched map 404s, which is the honest answer - there is no sequence -
    and the strip has to treat that as "nothing to show" rather than as an
    error, or every fetched map gets a red toast.
    """
    _, js, css = _resources()

    assert "/api/timeline" in js
    assert ".timeline" in css
    body = re.search(r"async function loadTimeline\(.*?\n\}\n", js, re.DOTALL)
    assert body is not None
    assert "catch" in body.group(0), "a map with no ledger must not surface as an error"

def test_the_bottom_edge_is_shared_rather_than_stacked() -> None:
    """**The attribution must not end up behind the timeline strip.**

    CC BY-NC-SA asks for the credit to be visible, so "it is under there
    somewhere" is not good enough. `--strip-h` is what the bottom-anchored
    elements clear, and it is 0 whenever the strip is absent - so there is one
    rule rather than one per state. The legend moved to the top to make room,
    which is the other half of the same decision.
    """
    _, js, css = _resources()

    attribution = re.search(r"\.attribution \{(.*?)\}", css, re.DOTALL)
    assert attribution is not None
    assert "var(--strip-h)" in attribution.group(1), "the attribution ignores the strip"

    legend = re.search(r"\.legend \{(.*?)\}", css, re.DOTALL)
    assert legend is not None
    assert "top:" in legend.group(1) and "bottom:" not in legend.group(1)

    # The page is what knows how tall the strip actually is.
    assert '--strip-h' in js

def test_the_page_reads_its_identity_from_state_not_the_dom() -> None:
    """**Which map you are looking at is data, not a control's value.**

    It used to be read back out of a `<select>` in twenty-odd places, which
    made the control the source of truth and left no room for a state the
    controls do not have an option for.

    The map picker is now a menu rather than a `<select>`, so the validation
    that element was quietly doing - blanking on a value it has no option for -
    has to be explicit: `setMap` accepts an id the listing holds and refuses
    the rest, including a multi-run batch, which `resolve_map_path` will not
    guess a run for.
    """
    _, js, _ = _resources()

    assert "el.map.value" not in js, "a reader is still going to the DOM"
    setter = re.search(r"function setMap\(id\) \{(.*?)\n\}", js, re.DOTALL)
    assert setter is not None
    assert "state.maps.find((m) => m.map_id === wanted)" in setter.group(1)
    assert "row.runs > 1" in setter.group(1), "a multi-run batch is selectable"
    # `compare` is still a `<select>`, and still validates by being one.
    assert js.count("el.compare.value") == 3

    # `setCompare` still writes to its element and reads *back*: whatever the
    # `<select>` accepted is what state takes, so an unmatched id comes out
    # blank. `setMap` does the same job against the listing instead.
    setter = re.search(r"function setCompare\(id\) \{(.*?)\n\}", js, re.DOTALL)
    assert setter is not None
    assert "el.compare.value = id" in setter.group(1)
    assert "= el.compare.value" in setter.group(1)

def test_a_simulation_is_only_ever_seen_in_timeline_mode() -> None:
    """**A run is fifty worlds, not one**, and browsing it as though it were a
    map is the confusion the modes exist to remove.

    Choosing one out of the picker *is* choosing to replay it, so the mode
    follows without a dialog asking you to confirm what you just did - the
    ribbon says which mode you are in. What is still asked about is the one
    thing that would be lost silently: pending edits, which belong to the map
    they were made on and do not travel.
    """
    _, js, _ = _resources()

    select = re.search(r"async function selectMap\(id\) \{(.*?)\n\}", js, re.DOTALL)
    assert select is not None
    assert "Enter timeline mode" not in select.group(1), "an explicit choice is being confirmed"
    assert "unsaved change(s)?" in select.group(1), "edits are discarded without asking"
    assert "setMap(previous)" in select.group(1), "declining does not put it back"

    # The biconditional the whole design leans on, in one place.
    kind = re.search(r"function modeForMap\(mapId\) \{(.*?)\n\}", js, re.DOTALL)
    assert kind is not None
    assert '"simulated"' in kind.group(1) and '"timeline"' in kind.group(1)

def test_an_edit_is_pending_until_it_is_committed() -> None:
    """**What makes edit mode cheap is that it computes nothing.**

    A ticked row greys in place and an unlocked chunk lights up with no
    derivation at all; exactly one happens, on the world that results. A
    preview that re-derived per click would cost ~0.8s a tick to answer a
    question nobody asked half way through - so the pending set lives in the
    page, and `POST /api/commit` is the only thing that writes.
    """
    _, js, _ = _resources()

    assert "edits: { unlocked: new Set(), ticked: new Map() }" in js

    # The tick gesture asks the server nothing.
    handler = re.search(
        r'el\["tasks-body"\]\.addEventListener\("click".*?\n\}\);', js, re.DOTALL
    )
    assert handler is not None
    assert "getJSON" not in handler.group(0) and "postJSON" not in handler.group(0)
    assert "ensureEditing()" in handler.group(0)
    # Keyed the payload's way, not the panel's - see `panels._entry`.
    assert "row.dataset.category" in handler.group(0)

    # And the preview is a layer, drawn under the labels like every other.
    layers = re.search(r"const LAYERS = \[(.*?)\];", js, re.DOTALL)
    assert layers is not None
    order = layers.group(1)
    assert order.index("drawPending") < order.index("drawAreas")

def test_committing_is_the_only_writer_and_returns_what_it_claimed() -> None:
    """`claim_batch` suffixes a clash, so the name that landed is not always
    the name that was typed - and "anything that makes a map selects it"."""
    _, js, _ = _resources()

    commit = re.search(r"function askCommit\(\) \{(.*?)\n\}\n", js, re.DOTALL)
    assert commit is not None
    assert '"/api/commit"' in commit.group(1)
    assert "openMap(result.open)" in commit.group(1)
    assert "clearEdits()" in commit.group(1)

    # Leaving with work pending asks rather than dropping it silently.
    exit_body = re.search(r"async function exitMode\(\) \{(.*?)\n\}", js, re.DOTALL)
    assert exit_body is not None
    assert "confirmAction" in exit_body.group(1)

def test_the_mode_palette_is_defined_once() -> None:
    """The canvas constants and the legend's swatches are already two copies
    of this palette with nothing asserting they agree. The modes are not going
    to be a third: the stylesheet owns the colours and the page owns only
    which one is on, as an attribute."""
    html, js, css = _resources()

    for mode in ("browse", "edit", "diff", "timeline"):
        assert f"--mode-{mode}:" in css, f"{mode} has no colour"
        assert f'.ribbon[data-mode="{mode}"]' in css, f"{mode} tint is not selected for"
        assert f'{mode}:' in js, f"{mode} is not a mode the page knows"

    # The page names the mode; it never names a colour.
    ribbon = re.search(r"function renderRibbon\(\) \{(.*?)\n\}", js, re.DOTALL)
    assert ribbon is not None
    assert "dataset.mode" in ribbon.group(1)
    assert "#" not in ribbon.group(1), "a colour literal has leaked into the page"
    assert 'id="ribbon"' in html

def test_a_step_and_a_comparison_are_exclusive() -> None:
    """Two maps and a rewind would need a third colour for "gained by this
    roll but lost against the other side", which is nobody's question.

    It used to be enforced by an if-ladder over whichever control happened to
    hold a value. The modes make it structural instead: exactly one of them
    carries a comparison, and it is not one of the ones that step.
    """
    _, js, _ = _resources()

    query = re.search(r"function mapQuery\(\) \{(.*?)\n\}", js, re.DOTALL)
    assert query is not None
    assert "switch (state.mode)" in query.group(1), "the query still infers the mode"
    diff, rest = query.group(1).split('case "diff":', 1)
    body, default = rest.split("default:", 1)
    # The comparison is the diff arm's and the step is everybody else's.
    assert 'params.set("compare"' in body and 'params.set("step"' not in body
    assert 'params.set("step"' in default and 'params.set("compare"' not in default

    # And the strip is the timeline mode's, so it never has to check either.
    load = re.search(r"async function loadTimeline\(\) \{(.*?)\n\}", js, re.DOTALL)
    assert load is not None
    assert 'state.mode !== "timeline"' in load.group(1)
    assert "state.compare" not in load.group(1), "the strip is still second-guessing"

def test_switching_map_forgets_the_step() -> None:
    """A step index belongs to one run. Carried across, it rewinds the new map
    to a roll it never had - and the counts quietly disagree with the slider.

    `setMode` cannot be where this happens, because run to run is a map change
    with no mode change at all - so `selectMap` does it, on the map moving.
    """
    _, js, _ = _resources()

    select = re.search(r"async function selectMap\(id\) \{(.*?)\n\}", js, re.DOTALL)
    assert select is not None
    assert "state.map !== previous" in select.group(1)
    assert "state.step = null" in select.group(1)
    assert "state.timeline = null" in select.group(1)

    # And every way in goes through it rather than round it. The picker is a
    # menu rather than a `<select>` - two things a `<select>` cannot do,
    # colour a row and nest a batch's runs beside it - so what the rows call
    # is `chooseMap`, and that is the only caller of `selectMap` there is.
    chooser = re.search(r"async function chooseMap\(id\) \{(.*?)\n\}", js, re.DOTALL)
    assert chooser is not None
    assert "await selectMap(id)" in chooser.group(1)
    assert 'button.onclick = () => { closeMapMenu(); chooseMap(button.dataset.map); };' in js

def test_an_uncomputed_hours_series_is_not_drawn_as_zero() -> None:
    """**"Not computed" and "added no work" are different answers**, and both
    are common - eight of ten steps of a real run add exactly 0.0h. Drawing
    them the same would make a graph nobody could read."""
    _, js, _ = _resources()

    bars = re.search(r"function tlBars\(.*?\n\}\n", js, re.DOTALL)
    assert bars is not None
    # A null draws no bar at all; a zero still gets one, at a floor height.
    assert "value !== null && value !== undefined" in bars.group(0)
    assert "Math.max(1.5," in bars.group(0)
    # And the axis says so outright when nothing has been priced.
    assert "Compute hours" in bars.group(0)

def test_the_axis_only_reserves_room_for_negatives_when_there_are_some() -> None:
    """Tasks are never negative and hours usually are not, so a permanently
    centred zero line spent half the strip on empty space and halved the
    resolution of the bars actually there."""
    _, js, _ = _resources()

    bars = re.search(r"function tlBars\(.*?\n\}\n", js, re.DOTALL)
    assert bars is not None
    assert "known.some((v) => v < 0)" in bars.group(0)
    assert "down ? H * 0.62 : H - FOOT" in bars.group(0)

def test_the_legend_keys_off_the_counts_not_the_compared_map() -> None:
    """**A rewound run has green squares and no compared map.** Gating on the
    map left the chunks a run had rolled in a colour the legend never
    explained."""
    _, js, _ = _resources()

    legend = re.search(r"function renderLegend\(\) \{(.*?)\n\}", js, re.DOTALL)
    assert legend is not None
    assert "counts.added" in legend.group(1) and "counts.removed" in legend.group(1)
    # The expression, not the prose - the comment above it says the word too.
    assert "view.compare_map_id" not in legend.group(1)

def test_a_multi_run_batch_is_a_label_not_a_choice() -> None:
    """**Selecting one blanks the map**, and did before the timeline existed.

    `cache.resolve_map_path` refuses to guess which run a bare batch name
    means - picking one silently would make the same name describe a different
    world as runs were added - so it 404s `/api/view`, `/api/summary` and
    everything else. The picker offering it as a map was the bug.
    """
    _, js, _ = _resources()

    body = re.search(r"function mapOptions\(maps\) \{(.*?)\n\}", js, re.DOTALL)
    assert body is not None
    assert "<optgroup" in body.group(1)
    assert "m.runs > 1" in body.group(1)
    # A run belongs to its group, not to the top level as well.
    assert 'm.map_id.includes("/")' in body.group(1)

def test_rolling_opens_the_result_as_the_map(tmp_path: Path) -> None:
    """**It used to land in the compare slot, which is what hides the strip** -
    so rolling a simulation hid the one thing you rolled it to see.

    `openMap` rather than `setMap`, because a roll produces a simulation and a
    simulation belongs in timeline mode: selecting it without the mode would
    put a run on screen in the one place the modes forbid it.
    """
    _, js, _ = _resources()

    handler = re.search(r'runAction\(`Simulate \$\{rolls\} rolls`.*?\n    \};', js, re.DOTALL)
    assert handler is not None
    assert "openMap(result.open)" in handler.group(0)
    assert "loadTimeline()" in handler.group(0)

def test_making_a_map_enters_the_mode_that_map_needs() -> None:
    """**Selecting a simulation without its mode is the invariant's one hole.**

    `selectMap` guards the picker, but rolling one does not go through the
    picker - it selects the result directly - so a roll would have landed a
    run in Browse. `openMap` is the unprompted twin: no question, because you
    just made this, but the same mode arithmetic.
    """
    _, js, _ = _resources()

    body = re.search(r"function openMap\(id\) \{(.*?)\n\}", js, re.DOTALL)
    assert body is not None
    assert "setMode(modeForMap(state.map))" in body.group(1)
    # A step belongs to the map it was taken on.
    assert "state.step = null" in body.group(1)
    assert "confirmAction" not in body.group(1), "making a map should not ask"

def test_unlocking_opens_the_result_as_the_map() -> None:
    """**The same bug the Roll button had.** A saved unlock went into the
    compare slot, and comparing is exactly the state that hides the strip - so
    the act of unlocking a chunk hid the only record of what it added.

    Nothing is lost by selecting it instead: a saved unlock is a batch of one,
    so the chunk it added draws green from its own ledger the way a rolled one
    does, without a comparison being involved at all.
    """
    _, js, _ = _resources()

    handler = re.search(r'runAction\("Unlock " \+ chunkLabel\(chunkId\).*?\n      \}\);', js, re.DOTALL)
    assert handler is not None
    assert "openMap(result.open)" in handler.group(0)
    assert "loadTimeline()" in handler.group(0)

def test_a_ledger_outside_timeline_mode_is_a_caption_not_a_history() -> None:
    """**The situation `comparingNotice` explained no longer exists.**

    It hid the strip when a comparison was up and then apologised for it in
    the strip's own space. A simulation can no longer be compared at all, so
    there is nothing to apologise for - what is left is the honest case: a
    batch of one has a ledger of one roll, its step is pinned at the end so
    the view can say which chunk arrived, and there is nothing to drag.
    """
    _, js, css = _resources()

    assert "function comparingNotice" not in js
    assert 'id="tl-uncompare"' not in js
    assert ".timeline.notice" not in css, "the reduced strip's styling outlived it"

    body = re.search(r"async function loadTimeline\(\) \{(.*?)\n\}", js, re.DOTALL)
    assert body is not None
    assert 'state.mode !== "timeline"' in body.group(1)
    # Pinned, not dragged: no `state.timeline`, so the arrow keys do nothing.
    assert "state.timeline = null" in body.group(1)
    assert "hideStrip()" in body.group(1)

    # "No history" and "not yours to drag from here" are different states.
    assert "function hideStrip()" in js
    hide = re.search(r"function hideTimeline\(\) \{(.*?)\n\}", js, re.DOTALL)
    assert hide is not None
    assert "state.step = null" in hide.group(1)

def test_diff_is_entered_through_a_door_and_left_through_a_pill() -> None:
    """A second dropdown sitting permanently beside the first said the page
    was always half way into a comparison. Diff is a mode: you go in through
    one control and out through another, and while you are in it the pair is
    on the ribbon where the mode is announced."""
    html, js, css = _resources()

    assert 'id="compare-start"' in html
    assert 'id="exit-mode"' in html
    # The pair moved onto the ribbon rather than staying in the bar.
    ribbon = html[html.index('<div id="ribbon"'):html.index("<header class=\"bar\">")]
    assert 'id="compare"' in ribbon and 'id="breakdown"' in ribbon

    ribbon_js = re.search(r"function renderRibbon\(\) \{(.*?)\n\}", js, re.DOTALL)
    assert ribbon_js is not None
    assert 'mode !== "diff"' in ribbon_js.group(1)
    # Comparing from a timeline would show a simulation outside timeline mode.
    assert 'mode === "timeline"' in ribbon_js.group(1)

    # The way out rides above the strip rather than behind it.
    pill = re.search(r"\.exit-pill \{(.*?)\}", css, re.DOTALL)
    assert pill is not None
    assert "var(--strip-h)" in pill.group(1)

def test_the_page_fetches_both_scrapes_once_when_they_are_missing() -> None:
    """**Without them the Estimate tab is confidently wrong**, and the panel
    would say so in small print beside the number.

    Without the rates every hour falls back to a default; without the recipes
    Construction has no rated method at all and reads 13,034h against 191h,
    which looks like a modelling gap rather than like missing data. Thirty-one
    requests is a fair price for that not being the first impression - but only
    when missing, never on a schedule.
    """
    _, js, _ = _resources()

    body = re.search(r"async function warmReference\(\) \{(.*?)\n\}", js, re.DOTALL)
    assert body is not None
    assert '"wiki_rates", "heuristics"' in body.group(1)
    assert '"wiki_recipes", "recipes"' in body.group(1)
    assert "!row.cached" in body.group(1), "it must only fire when they are absent"
    # The 10MB export is deliberately not fetched on open. Quoted, because the
    # comment above the loop names it in prose to say exactly that.
    assert '"chunkinfo"' not in body.group(1)
    assert "warmReference();" in js

def test_the_progress_card_can_stop_a_job() -> None:
    """The control only appears while something is running that can stop, and
    it hides itself once asked - a button that stays lit after you press it
    reads as not having worked."""
    html, js, css = _resources()

    assert 'id="progress-cancel"' in html
    assert '"/api/cancel"' in js
    # Shown per job id, not unconditionally.
    assert 'el["progress-cancel"].hidden = !job' in js
    # Stopped is its own colour, not the loss one.
    assert ".progress.stopped" in css
    assert 'job.state === "cancelled"' in js

def test_a_bar_does_not_swallow_its_own_hover() -> None:
    """**The bars are drawn over the hit areas.** Without `pointer-events:
    none` the tooltip appeared on the empty background either side of a
    column but not on the column itself - hovering the very thing you are
    aiming at did nothing."""
    _, _, css = _resources()

    rule = re.search(r"\.tl-bar[^{]*\{([^}]*pointer-events[^}]*)\}", css)
    assert rule is not None, "the bars still take the pointer"
    assert "none" in rule.group(1)

def test_the_roll_tooltip_counts_rolls_not_the_whole_world() -> None:
    """`unlocked_chunks` counts the base map too, so the first roll of a
    simulation from a 106-chunk map read "106 chunks after this roll" - true,
    and not what a timeline is about."""
    _, js, _ = _resources()

    body = re.search(r"function tlTip\(.*?\n\}\n", js, re.DOTALL)
    assert body is not None
    assert "chunks rolled so far" in body.group(0)
    # The expression, not the prose - the comment above it explains why the
    # old field is wrong and so necessarily names it.
    assert "row.unlocked_chunks" not in body.group(0)

def test_clicking_a_column_frames_the_chunk_and_details_is_separate() -> None:
    """**They cannot be the same gesture**: a dialog would cover the map it
    had just framed. Click takes you to the roll - slider, selection, camera -
    and the breakdown is its own control."""
    html, js, _ = _resources()

    assert 'id="tl-details"' in html
    body = re.search(r"async function goToRoll\(step\) \{(.*?)\n\}", js, re.DOTALL)
    assert body is not None
    assert "setStep(step)" in body.group(1)
    assert "selectChunk(" in body.group(1) and "focusChunk(" in body.group(1)
    # The overlay is opened by the button, not by the column.
    assert "slot.onclick = () => goToRoll(" in js
    assert 'el["tl-details"].addEventListener' in js

def test_a_deep_link_to_a_run_falls_back_to_its_batch() -> None:
    """A one-run batch is offered under its bare name, so `?map=t/run-001` is
    a valid map id with no option to match - and a `<select>` handed one it
    does not have blanks silently, landing you on whatever was first."""
    _, js, _ = _resources()

    body = re.search(r"async function loadMaps\(\) \{(.*?)\n\}", js, re.DOTALL)
    assert body is not None
    assert '.split("/")[0]' in body.group(1)


def test_every_collapsible_list_has_an_owner_to_redraw_it() -> None:
    """**`Show 24 more` is wired by a naming convention, not by a handler.**

    The delegated click looks its owner up as `key.split(":")[0]`, so a list
    keyed `roll-hours` finds nothing and the button does nothing at all - no
    error, no redraw, just a control that ignores you. Every key `withMore` is
    given must therefore have a registered prefix before the first colon.
    """
    _, js, _ = _resources()

    keys = set(re.findall(r'withMore\([^,]+,\s*"([^"]+)"', js))
    keys |= {m for m in re.findall(r'withMore\([^,]+,\s*"([^"]+)" \+', js)}
    owners = set(re.findall(r'ownsMore\("([^"]+)"', js))

    assert owners, "no list owners registered at all"
    for key in keys:
        assert key.split(":")[0] in owners, f"{key!r} has no owner to redraw it"
    # **A registered prefix must be the part before the colon, not including
    # it.** `ownsMore("tasks:")` looks right beside `clearExpansions("tasks:")`
    # - which does want the colon, being a prefix match over whole keys - and
    # registers an owner the lookup can never find.
    assert not any(name.endswith(":") for name in owners), f"trailing colon: {sorted(owners)}"


def test_one_skill_tooltip_serves_both_surfaces() -> None:
    """The Estimate tab and the roll overlay ask the same question about a
    skill, so they render it with the same function.

    The tab's own version was three lines - level, target, hours - which said
    nothing about *why*. One renderer means the bands, the provenance and the
    quest head start reach both places, and the "one tooltip system" rule keeps
    meaning what it says.
    """
    _, js, _ = _resources()

    assert js.count("function skillTip(") == 1
    assert js.count("skillTip(skill)") == 1, "the Estimate tab builds its own again"
    assert js.count("skillTip(row)") >= 1, "the roll overlay stopped using it"
    # The bands are what the tooltip is for; a blended rate alone hides them.
    tip = re.search(r"function skillTip\(row\) \{(.*?)\n\}", js, re.DOTALL)
    assert tip is not None
    assert "row.bands" in tip.group(1)
    assert "b.match" in tip.group(1), "provenance must travel with each band"

def test_an_edit_of_an_edit_keeps_the_family_name() -> None:
    """**A cached map is immutable and an edit is not**, so editing is
    iterative - unlock a chunk, tick what it opened, unlock the next.
    `<map>-edit` per round gives `fray-edit-edit-edit`, which names the number
    of rounds and nothing anyone would look for.

    The trailing number is stripped rather than incremented, because only the
    server knows what is taken: suggesting `-4` when `-4` exists would be a
    name the dialog promises and `claim_batch` then changes.
    """
    _, js, _ = _resources()

    body = re.search(r"function defaultEditName\(mapId\) \{(.*?)\n\}", js, re.DOTALL)
    assert body is not None
    assert '"edited"' in body.group(1)
    assert "replace(/-\\d+$/" in body.group(1)


def _match(pattern: str, source: str) -> str:
    """The one capture of `pattern`, or a failure naming what was not found.

    The file already spells this out inline a dozen times; the tests below are
    dense enough in it to be worth the helper."""
    found = re.search(pattern, source, re.DOTALL)
    assert found is not None, f"nothing in the source matches {pattern!r}"
    return found.group(1)


def test_the_log_axis_ticks_agree_with_the_clamp() -> None:
    """A tick line above `HOURS_MAX` would be drawn on top of the clamp and
    read as an axis that continues past where it stops."""
    _, js, _ = _resources()
    ceiling = int(_match(r"const HOURS_MAX = (\d+);", js))
    ticks = [int(v) for v in _match(r"const HOURS_TICKS = \[([^\]]+)\]", js).split(",")]
    assert ticks == sorted(ticks)
    assert max(ticks) == ceiling


def test_the_hours_axis_is_logarithmic_by_default() -> None:
    """The default lives in Python, and the page must not carry a second copy
    of it - `tlScale` falls back to the older axis only when settings are
    unreadable, which is a different thing from a default."""
    from fray_claude.gui import settings

    assert settings.DEFAULTS["hours_scale"] == "log"
    _, js, _ = _resources()
    assert 'state.settings ? state.settings.hours_scale : "linear"' in js
    assert 'const log = key === "hours" && tlScale() === "log"' in js


def test_the_log_curve_can_place_a_roll_that_added_nothing() -> None:
    """`log10(0)` is minus infinity and most rolls add exactly nothing, so the
    curve has to be `log10(1 + v)`. Losing the `1 +` would put every empty
    column off the bottom of the strip."""
    _, js, _ = _resources()
    curve = _match(r"function logFrac\(value\) \{(.*?)\n\}", js)
    assert "Math.log10(1 + Math.min(" in curve
    assert "Math.log10(1 + HOURS_MAX)" in curve


def test_the_band_palette_is_defined_once_and_the_page_names_only_the_band() -> None:
    """The same division the mode tints keep: the stylesheet owns the colours
    and the page owns which one is on, as a data attribute."""
    _, js, css = _resources()
    for band in ("free", "quick", "grind", "minor", "death"):
        assert f"--band-{band}:" in css
        assert f"var(--band-{band})" in css
    for index in range(5):
        assert f'.tl-bar[data-band="{index}"]' in css
    # `bandOf` returns an index, never a colour.
    body = _match(r"function bandOf\(value, bands\) \{(.*?)\n\}", js)
    assert "#" not in body, "a colour literal has leaked into the page"


def test_the_bands_are_positional_so_a_renamed_band_keeps_its_colour() -> None:
    """Names are the user's to change; a colour that followed the name would
    move when a label did."""
    _, js, css = _resources()
    assert 'data-band="${band === null ? "" : String(band)}"' in js
    # Comments may name a band; a *selector* may not.
    rules = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for name in ("Free", "Quick", "Grind", "Minor Death", "Death"):
        assert name not in rules


def test_the_band_count_agrees_across_the_two_languages() -> None:
    from fray_claude.gui import settings

    _, _, css = _resources()
    selectors = re.findall(r'\.tl-bar\[data-band="(\d+)"\]', css)
    assert sorted({int(v) for v in selectors}) == list(range(settings.BAND_COUNT))


def test_the_band_name_length_agrees_across_the_two_languages() -> None:
    """The input's `maxlength` and the server's trim must be the same number,
    or typing to the limit produces a name the page did not show you."""
    from fray_claude.gui import settings

    _, js, _ = _resources()
    assert f'maxlength="{settings.MAX_BAND_NAME}"' in js
    assert f"slice(0, {settings.MAX_BAND_NAME})" in js


def test_the_hours_key_is_not_the_map_legend() -> None:
    """`#legend` describes the map and is anchored to the top of the window
    (see `test_the_bottom_edge_is_shared_rather_than_stacked`). The bar key
    belongs to a graph that comes and goes, so it is its own element."""
    html, js, css = _resources()
    assert 'id="tl-key"' in html
    assert ".tl-key {" in css
    key = _match(r"function renderBandKey\(\) \{(.*?)\n\}", js)
    assert "legend" not in key
    assert "#" not in key, "a colour literal has leaked into the page"


def test_a_refused_band_edit_is_not_reported_as_a_save() -> None:
    """`settings.sanitise` refuses by keeping the stored value and still
    answers 200, so the page has to compare the reply with what it sent."""
    _, js, _ = _resources()
    body = _match(r"async function applyBands\(patch\) \{(.*?)\n\}", js)
    assert "sameBands(" in body
    assert "toast(" in body


def test_a_reset_asks_for_the_key_by_name() -> None:
    """An empty band list is refused, so sending one leaves the stored bands
    exactly where they were - the opposite of a reset."""
    from fray_claude.gui import settings

    _, js, _ = _resources()
    assert 'reset: ["hours_bands"]' in js
    assert "hours_bands" in settings.KEYS


def test_saving_a_setting_redraws_from_the_answer() -> None:
    """Not from the request - which is the only way a refusal shows up."""
    _, js, _ = _resources()
    body = _match(r"async function saveSettings\(patch\) \{(.*?)\n\}", js)
    assert "state.settings = await postJSON" in body
    assert "renderTimeline()" in body

