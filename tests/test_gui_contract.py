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
`app.js` or `style.css` change needs**, and with `chunksim-gui` installed editable
that change needs no reinstall either - so the whole front-end loop is edit,
run this file, reload the tab.

Reading the three resource files 42 times over costs 8.7ms measured, so they
are read per test rather than through a session fixture. The fixture would save
eight milliseconds and put an argument on every test in the file.
"""

from __future__ import annotations

import re
from pathlib import Path

from chunksim.gui import players
from chunksim.store import cache

def _app_js() -> str:
    from chunksim.gui.http import RESOURCE_DIR

    return (RESOURCE_DIR / "app.js").read_text(encoding="utf-8")

def test_the_edge_bits_agree_across_the_two_languages() -> None:
    """`app.js` masks the same bitfield `worldmap.Edge` sets.

    Nothing forces these to match - the value crosses as a plain integer in
    JSON - so a renumbered flag would draw the hull on the wrong sides and
    every test on either side would still pass.
    """
    from chunksim.gui.worldmap import Edge

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
    nobody notices until they paste the id into `chunksim unlock`.
    """
    from chunksim.gui.worldmap import MAX_REGION_Y, MIN_REGION_X, REGION_STRIDE

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
    from chunksim.gui.worldmap import MAX_TILE_ZOOM, MIN_TILE_ZOOM, TILE_PIXELS

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
    from chunksim.gui.worldmap import MAX_REGION_Y

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

    A future edit that proxies tiles through `chunksim-gui` "for caching" would
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
    from chunksim.gui.http import RESOURCE_DIR

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
    from chunksim.gui.routes_derived import WHOLE_CHUNK_SECTION

    match = re.search(r'const WHOLE_CHUNK = "([^"]+)";', _app_js())
    assert match is not None
    assert match.group(1) == WHOLE_CHUNK_SECTION

def _resources() -> tuple[str, str, str]:
    from chunksim.gui.http import RESOURCE_DIR

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

def test_the_reachable_blue_is_one_colour() -> None:
    """The canvas outlines a reachable area with `REACHABLE_STROKE` and the Find
    dialog borders the same square with `--reachable`. Two literals for one
    meaning is how they come to disagree."""
    _, js, css = _resources()

    assert _match(r"--reachable: (#[0-9a-f]{6});", css) == _match(
        r'const REACHABLE_STROKE = "(#[0-9a-f]{6})";', js
    )


def test_the_skill_states_are_one_vocabulary() -> None:
    """`players.STATE_COLOURS` names four states; `app.js` labels them and
    `style.css` paints them. Nothing links the three, so a fifth state added
    to the model would render as an unlabelled blue cell - the default - and
    look like a working panel showing the wrong thing."""
    _, js, css = _resources()

    model = set(players.STATE_COLOURS.values())
    labelled = set(re.findall(r"^  (\w+): \[\"", _match(r"const SKILL_STATES = \{(.*?)\n\};", js), re.MULTILINE))

    assert labelled == model, f"app.js and players.py disagree: {labelled ^ model}"
    for state in model:
        # `floor` is the unqualified rule the others override, so it is painted
        # by `.skill-cell` itself rather than by a `[data-state=]` of its own.
        token = f"--level-{state}"
        assert f"{token}:" in css, f"no colour defined for {state}"
        assert f"var({token})" in css, f"{state} has a colour nothing uses"


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

def test_neither_language_carries_a_default_map_id() -> None:
    """**There is no house map id, and the page must not invent one.**

    This replaced a contract test that pinned a JavaScript constant against a
    Python one. Both are gone: a fetch names someone's world on a public
    database, so blank is refused rather than defaulted. The failure this
    guards is a placeholder growing back on one side only, which would promise
    a fetch the server now rejects.
    """
    _, js, _ = _resources()

    assert "DEFAULT_MAP_ID" not in js
    assert not hasattr(cache, "DEFAULT_MAP_ID")

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

    Neither picker is a `<select>` any more, so the validation those elements
    were quietly doing - blanking on a value they have no option for - has to
    be explicit on **both** sides of the pair: an id is accepted when the
    listing holds it and refused otherwise, multi-run batches included, which
    `resolve_map_path` will not guess a run for.
    """
    _, js, _ = _resources()

    assert "el.map.value" not in js, "a reader is still going to the DOM"
    assert "el.compare.value" not in js, "a reader is still going to the DOM"
    for name in ("setMap", "setCompare"):
        setter = re.search(rf"function {name}\(id\) \{{(.*?)\n\}}", js, re.DOTALL)
        assert setter is not None, name
        assert "state.maps.find((m) => m.map_id === wanted)" in setter.group(1), name
        assert "row.runs > 1" in setter.group(1), f"{name}: a multi-run batch is selectable"

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

    # Read the modes out of the page rather than repeating them here, or a
    # sixth mode arrives with no colour and the ribbon silently keeps the
    # fifth's.
    modes = re.findall(r"^  (\w+):\s*\{ label:", _match(r"const MODES = \{(.*?)\n\};", js),
                       re.MULTILINE)
    assert len(modes) >= 5, f"the mode table did not parse: {modes}"
    for mode in modes:
        assert f"--mode-{mode}:" in css, f"{mode} has no colour"
        assert f'.ribbon[data-mode="{mode}"]' in css, f"{mode} tint is not selected for"

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
    # A picker row calls whatever its spec named, and the base map's spec names
    # `chooseMap` - so there is still exactly one way in.
    assert "spec.onChoose(button.dataset.map)" in js
    spec = _match(r'initPicker\(el\["map-picker"\], \{(.*?)\n\}\)', js)
    assert "onChoose: chooseMap" in spec

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

    body = _match(r"function renderPickerMenu\(root\) \{(.*?)\n\}\n", js)
    # The batch is a heading with a submenu under it, never a row you can
    # choose: only `row()` carries `data-map`, and a batch does not go through
    # it. A run belongs to its batch, not to the top level as well.
    assert "runs.length < 2" in body
    assert 'x.map_id.includes("/")' in body
    assert 'data-batch=' in body and 'aria-haspopup="true"' in body

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
    # `commitStep` is `setStep` plus the panels; a click is a commit, so the
    # panels follow it - see `test_a_drag_moves_the_world_and_a_commit_moves_the_panels`.
    assert "commitStep(step)" in body.group(1)
    assert "selectChunk(" in body.group(1) and "focusChunk(" in body.group(1)
    # The overlay is opened by the button, not by the column.
    assert "slot.onclick = () => goToRoll(" in js
    assert 'el["tl-details"].addEventListener' in js


def test_a_drag_moves_the_world_and_a_commit_moves_the_panels() -> None:
    """**The two costs are nothing alike and the events have to reflect that.**

    Rewinding the world is a 36KB read; each panel is a derivation, ~3ms warm
    and ~0.6s cold. So `input` - once per frame of a drag - may only call
    `setStep`, and `change` is what pays for the panels. Wiring `commitStep`
    to `input` would put a derivation on every frame, which is the cost the
    strip was built to avoid.
    """
    _, js, _ = _resources()

    drag = _match(r'el\["tl-slider"\]\.addEventListener\("input",(.*?)\);', js)
    commit = _match(r'el\["tl-slider"\]\.addEventListener\("change",(.*?)\);', js)
    assert "setStep(" in drag and "commitStep(" not in drag
    assert "commitStep(" in commit
    # Both step buttons commit: they are single steps, not a scrub.
    for control in ("tl-prev", "tl-next"):
        assert f'el["{control}"].addEventListener("click", () => commitStep(' in js


def test_a_panel_asks_about_the_step_and_the_view_asks_about_the_map() -> None:
    """**Two questions, two builders, and they must stay adjacent.**

    `mapQuery` says which chunk arrived and sends a step whenever there is
    one; `panelQuery` says which world and sends one only when Timeline has
    actually rewound. Every derivation-backed route takes the second, or a
    panel describes the finished run under a rewound map.
    """
    _, js, _ = _resources()

    for route in ("/api/tasks", "/api/estimate", "/api/training", "/api/sections",
                  "/api/chunk", "/api/unlock", "/api/neighbours"):
        assert _match(rf'"{re.escape(route)}\?" \+ (\w+)\(\)', js) == "panelQuery", (
            f"{route} must scope to the step"
        )
    assert '"&" + panelQuery() + "&limit=40"' in js, "Find must scope to the step too"
    # The cheap view keeps the other one.
    assert '"/api/view?" + mapQuery()' in js
    # Adjacent, which is the only thing keeping the two rules from drifting.
    assert 0 < js.index("function panelQuery(") - js.index("function mapQuery(") < 2000

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
    from chunksim.gui import settings

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
    for band in ("free", "quick", "grind", "brutal", "death"):
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
    for name in ("Free", "Quick", "Grind", "Brutal", "Death"):
        assert name not in rules


def test_the_band_count_agrees_across_the_two_languages() -> None:
    from chunksim.gui import settings

    _, _, css = _resources()
    selectors = re.findall(r'\.tl-bar\[data-band="(\d+)"\]', css)
    assert sorted({int(v) for v in selectors}) == list(range(settings.BAND_COUNT))


def test_the_band_name_length_agrees_across_the_two_languages() -> None:
    """The input's `maxlength` and the server's trim must be the same number,
    or typing to the limit produces a name the page did not show you."""
    from chunksim.gui import settings

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
    from chunksim.gui import settings

    _, js, _ = _resources()
    assert 'reset: ["hours_bands"]' in js
    assert "hours_bands" in settings.KEYS


def test_saving_a_setting_redraws_from_the_answer() -> None:
    """Not from the request - which is the only way a refusal shows up."""
    _, js, _ = _resources()
    body = _match(r"async function saveSettings\(patch\) \{(.*?)\n\}", js)
    assert "state.settings = await postJSON" in body
    assert "renderTimeline()" in body



def test_a_marked_span_becomes_a_link_rather_than_being_stripped() -> None:
    """**`~|...|~` marks a thing the wiki has a page for**, and the panel's
    only use for that had been to strip it. In a knob path it is a shop or a
    monster, and "where is that" is the question a knob about it provokes - so
    it goes to `highlight`, which is what the Find pane calls."""
    _, js, _ = _resources()

    # The scan itself lives in `nameParts`, which every renderer shares - one
    # parse, three renderings, so the third is not the one that forgets.
    scan = _match(r"function nameParts\(text\) \{(.*?)\n\}", js)
    assert '"~|"' in scan and '"|~"' in scan
    body = _match(r"function linked\(text\) \{(.*?)\n\}", js)
    assert "nameParts(text)" in body and "find-link" in body
    # The link searches for the key, not for what it shows.
    assert 'data-term="${part.raw}"' in body
    # **Delegated and propagation-stopping**, because a marked span can sit
    # inside a row that is itself a control - a task row ticks, an estimate
    # row opens its knobs - and following the link must not also do that.
    handler = _match(r'document\.addEventListener\("click", \(event\) => \{(.*?)\n\}, true\)', js)
    assert '.find-link' in handler and "stopPropagation" in handler
    # The same framing Find does, not a second implementation of it.
    assert "highlight(best)" in _match(r"async function findTerm\(term\) \{(.*?)\n\}", js)


def test_a_knob_path_is_drawn_from_the_servers_own_split() -> None:
    """`BRANCH_DEPTH` lives in `gui/knobs.py`; a second copy here is a second
    thing to get wrong about a key with a slash in it."""
    _, js, _ = _resources()

    body = _match(r"function knobPath\(knob\) \{(.*?)\n\}", js)
    assert "knob.parts" in body
    assert "split(" not in body, "the page must not re-split the path"


def test_an_overridden_knob_is_marked_and_can_be_reverted() -> None:
    """**A knob you changed looks changed**, and the way back is next to it.

    Revert clears the layer actually in force rather than the one Save would
    write to: those differ when a site override shows while the page would
    save to the map, and a button that cleared the empty one would look broken
    in the one case somebody most wants it to work.
    """
    _, js, css = _resources()

    body = _match(r"const rows = knobs\.map\(\(knob, index\) => \{(.*?)\n  \}\)", js)
    assert 'knob.layer === "site" || knob.layer === "map"' in body
    assert "knob-flag" in body and "knob-revert" in body
    revert = _match(r"async function revertKnob\((.*?)\n\}", js)
    assert "value: null" in revert and "scope: layer" in revert

    styles = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    assert ".knob.mine" in styles and ".knob-flag" in styles


def test_glyphs_are_drawn_outside_the_stretched_graph() -> None:
    """**`preserveAspectRatio="none"` is right for a bar and wrong for a
    glyph.**

    It lets a column fill its width at any panel size, and scales every letter
    by the same ratio on the way - which is why the decade labels came out
    stretched. Lines do not care and text does, so anything with a shape of
    its own lives in an HTML overlay where a percentage is still a percentage
    and 10px is 10px.
    """
    _, js, css = _resources()

    assert 'preserveAspectRatio="none"' in js, "the bars still fill their columns"
    body = _match(r"function tlBars\(steps, key, current\) \{(.*?)\n\}", js)
    # The label is a span in the overlay, not a <text> in the graph.
    assert "tl-tick" in body and '<text class="tl-zero-label"' not in body
    assert 'class="tl-over"' in body

    styles = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    assert ".tl-over" in styles and ".tl-tick" in styles
    # The overlay is positioned against the graph, so the graph has to be a
    # containing block. Matched on the rule that sizes it, since `.tl-graph`
    # also appears in a collapsed-strip rule that only sets `display`.
    assert "position: relative" in _match(
        r"\.tl-graph \{([^}]*height: 92px[^}]*)\}", styles
    )


def test_the_worst_band_is_marked_where_its_colour_cannot_be_seen() -> None:
    """The death bar is near-black on a near-black strip, so the bar that
    matters most is the one hardest to pick out."""
    html, js, css = _resources()

    assert 'id="i-skull"' in html
    body = _match(r"function tlBars\(steps, key, current\) \{(.*?)\n\}", js)
    assert "#i-skull" in body
    # Guarded, or the Tasks series - which has no bands at all - throws.
    assert "bands !== null && band === bands.length - 1" in body
    styles = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    assert ".tl-skull" in styles
    # **The graph's own `svg` rule must not reach the overlay's.** `.tl-graph
    # svg` out-specifies `.tl-skull` and sized every skull to the whole strip.
    assert ".tl-graph > svg" in styles and ".tl-graph svg" not in styles


def test_the_backdrop_dismisses_only_on_a_press_and_release_that_both_land_on_it() -> None:
    """**`click` cannot express this**, which is why it is two listeners.

    It fires on the nearest common ancestor of the press and the release, so a
    press that began on the dialog and drifted off it - selecting text to the
    edge, missing a button by a pixel - arrives as a click on the overlay and
    is indistinguishable from a real one. The reverse does too. Neither is a
    dismissal, and a dismissed dialog is the one thing you cannot get back.
    """
    _, js, _ = _resources()

    assert 'el.overlay.addEventListener("mousedown"' in js
    release = _match(r'el\.overlay\.addEventListener\("mouseup", \(e\) => \{(.*?)\n\}\)', js)
    assert "overlayPressed && e.target === el.overlay" in release
    # The old single-handler form is what this replaces.
    assert 'el.overlay.addEventListener("click", (e) => { if (e.target === el.overlay)' not in js


def test_many_sources_open_a_list_rather_than_framing_the_world() -> None:
    """**Fitting the camera around eight scattered chunks frames most of the
    world**, which answers "roughly where" when the question was "which one".
    One source has no choice in it and still flies."""
    _, js, css = _resources()

    body = _match(r"function highlight\(result\) \{(.*?)\n\}", js)
    assert "placed.length > 1" in body and "showChunks(name, placed)" in body

    grid = _match(r"function showChunks\(title, ids, shown = CHUNKS_SHOWN\) \{(.*?)\n\}", js)
    # Unlocked first, then by id - "which can I already reach" is the question.
    assert "chunkOrder" in grid
    assert "CHUNKS_SHOWN" in js and "Show ${String(rest)} more" in grid
    # The art is the chunk itself: one 256px tile is one chunk at this level.
    assert "CHUNK_TILE_ZOOM" in grid
    assert "const CHUNK_TILE_ZOOM = 2;" in js

    styles = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    assert ".chunk-grid" in styles and ".chunk-card" in styles


def test_a_chunks_tile_comes_from_its_id_not_from_the_map_view() -> None:
    """`state.view.cells` holds only the squares the export places, and plenty
    of what a search finds is an underground or instanced region with no
    square - the Abyssal Nexus among them. Those still have artwork."""
    _, js, _ = _resources()

    body = _match(r"function chunkRegion\(chunkId\) \{(.*?)\n\}", js)
    assert "id >> 8" in body and "id & 0xff" in body
    # And the images are not lazy: the overlay is built and shown in one frame,
    # so the browser has no layout to decide visibility from and leaves every
    # one pending - neither loaded nor failed.
    assert 'class="chunk-art" loading="lazy"' not in js


def test_a_submenu_survives_the_gap_between_it_and_its_row() -> None:
    """**The gap belongs to neither.** The submenu is placed a few pixels clear
    of its row so the two read as separate strips, so travelling into it leaves
    the nest on the way - and closing on that `mouseleave` meant crossing in a
    single frame or not at all.

    The grace alone was not enough: a pointer that *rested* in those pixels ran
    the clock out and lost the menu. So the clearance is bridged by the
    submenu's own `::before`, and the width of that bridge is the number
    `app.js` places the submenu by. A narrower bridge leaves a hole; a wider one
    reaches over the row beside it.
    """
    _, js, css = _resources()

    assert "const SUBMENU_GRACE" in js
    leave = _match(r'nest\.addEventListener\("mouseleave", \(\) => \{(.*?)\n    \}\)', js)
    assert "setTimeout" in leave and "SUBMENU_GRACE" in leave
    enter = _match(r'nest\.addEventListener\("mouseenter", \(\) => \{(.*?)\n    \}\)', js)
    assert "clearTimeout" in enter, "arriving anywhere in the nest must cancel the close"

    bridge = _match(r"\.submenu::before \{(.*?)\}", css)
    assert "width: var(--submenu-gap)" in bridge
    # And the bridge must not be inside a scroll container, which clips it in
    # both axes and leaves it painted nowhere - the trap that put the submenu on
    # `position: fixed` to begin with.
    assert "overflow" not in _match(r"\n\.submenu \{(.*?)\}", css)
    assert "overflow-y: auto" in _match(r"\.submenu-body \{(.*?)\}", css)
    assert '.submenu[data-side="right"]::before' in css
    assert '.submenu[data-side="left"]::before' in css
    assert "submenu.dataset.side" in js, "the bridge needs the side app.js chose"
    assert _match(r"--submenu-gap: (\d+)px", css) == _match(
        r"const SUBMENU_GAP = (\d+);", js
    ), "the bridge must be exactly as wide as the clearance it covers"


def test_a_closing_submenu_takes_no_other_one_with_it() -> None:
    """**Moving between two neighbouring batches lost the submenu.**

    Hiding was one sweep over every nest, so the close pending for the nest just
    left ran a fifth of a second later and shut the one just arrived at. The
    pointer was by then inside the row that owned it, so no `mouseenter` was
    coming to bring it back - you had to leave every batch and return.

    A nest may only hide itself; showing one is what hides the rest, and it
    cancels their pending closes on the way so none can fire behind it.
    """
    _, js, _ = _resources()

    show = _match(r"const show = \(nest, on\) => \{(.*?)\n  \};", js)
    assert "querySelectorAll" not in show, "hiding must not sweep the other nests"

    enter = _match(r'nest\.addEventListener\("mouseenter", \(\) => \{(.*?)\n    \}\)', js)
    assert "clearTimeout(other.closing)" in enter, "a close left pending outlives the arrival"
    assert "show(other, false)" in enter and "show(nest, true)" in enter


def test_every_map_is_chosen_through_one_picker() -> None:
    """**Three places choose a map and only one of them was a real picker.**

    The comparison on the ribbon and the one in the Compare dialog were
    `<select>`s: no dot for the kind, no submenu for a batch's runs, and a popup
    drawn in the platform's own colours - dark text on light grey inside a dark
    page, capped at 20ch. So all three are the same component now, and the
    dialog builds its markup from the same function rather than a copy.
    """
    html, js, _ = _resources()

    assert re.findall(r'<select\s+id="([a-z-]+)"', html) == ["plane"], (
        "a map is being chosen through a <select> again"
    )
    # One builder, and the dialog's copy comes out of it rather than by hand.
    assert js.count("initPicker(") == 4, "a picker built without the component"
    assert "pickerMarkup(" in _match(r"async function askCompare\(\) \{(.*?)\n\}", js)

    # The menu escapes its container the way the submenu does, because one of
    # the three opens inside `.sheet > div`, which scrolls.
    assert "position: fixed" in _match(r"\n\.menu \{(.*?)\}", _resources()[2])
    assert "function placeMenu" in js


def test_a_pane_never_outlives_the_world_it_describes() -> None:
    """**Choosing another map left the Tasks pane showing the previous one's
    list.** The memo was dropped and the pane was not reloaded, so the rows on
    screen were about a map you were no longer on - and pressing "Show more"
    re-rendered from a null payload, threw, and swallowed the click. It read as
    the button being stuck, and swapping tabs "fixed" it because that is what
    refetched.

    Every way the world moves under the panes goes through one function now.
    """
    _, js, _ = _resources()

    reload = _match(r"async function reloadPanels\(\) \{(.*?)\n\}", js)
    assert "taskPanel = null" in reload and "estimatePayload = null" in reload
    for tab in ("tasks", "estimate", "find", "chunk"):
        assert f'state.tab === "{tab}"' in reload, tab

    # The three ways the world moves: a step, a map, and the file changing
    # under a live page.
    for caller in (r"async function commitStep\(step\) \{(.*?)\n\}",
                   r"async function chooseMap\(id\) \{(.*?)\n\}",
                   r"async function poll\(\) \{(.*?)\n\}"):
        assert "reloadPanels()" in _match(caller, js)

    # And a pane asked to draw with no payload fetches one rather than throwing.
    assert "if (!taskPanel) return loadTasks();" in js


def test_the_heatmap_is_a_layer_that_names_no_colour() -> None:
    """**The canvas cannot read a stylesheet**, so the tempting thing is five
    more hex literals beside the ones the map already carries - a second copy of
    a palette the strip's swatches draw from.

    The page holds the token *names* instead and reads their values at draw
    time, so a band's colour is still defined exactly once. Positional, because
    `bandOf` returns an index and the band names are the user's to change.
    """
    _, js, css = _resources()

    tokens = re.findall(r'"(--band-[a-z]+)"', _match(r"const BAND_TOKENS = \[(.*?)\];", js))
    drawn = set(re.findall(r'\.tl-bar\[data-band="(\d)"\]', css))
    assert len(tokens) == len(drawn), (
        "the canvas knows a different number of bands than the strip draws"
    )
    for token in tokens:
        assert f"{token}:" in css, f"{token} is not defined"

    fill = _match(r"function drawHeatmap\(\) \{(.*?)\n\}", js)
    assert "#" not in fill, "a band colour literal has leaked onto the canvas"
    assert "bandColour(bandOf(" in fill, "the fill must be the band the mean falls in"

    # Fills under the hull, labels over it - a number with a line through it is
    # the reason `drawAreas` sits where it does too.
    order = _match(r"const LAYERS = \[(.*?)\];", js)
    assert order.index("drawStates") < order.index("drawHeatmap") < order.index("drawHull")
    assert order.index("drawHull") < order.index("drawHeatLabels")


def test_the_heat_union_is_pure() -> None:
    """It folds ten timelines the dialog is already holding into one number per
    square. Reading the page instead would make it un-testable and would tie a
    batch's arithmetic to whichever map happened to be selected - which is a
    different map from the one the heat is about until `enterHeatmap` moves it.
    """
    _, js, _ = _resources()

    body = _match(r"function heatOf\(runs, timelines\) \{(.*?)\n\}\n", js)
    assert "state." not in body, "the union is reading the page"
    assert "getJSON" not in body, "the union is fetching; its inputs are its arguments"
    # The mean is of what a roll *added*, which is what the bands are cut
    # against. `total_hours` is the outstanding estimate and runs to thousands.
    assert "row.hours" in body and "total_hours" not in body


def test_the_heatmap_is_read_only_and_puts_itself_back() -> None:
    """**A tile is a summary over several futures**, so there is no one chain of
    unlocks behind it whose tasks a panel could list - which is why the panel
    goes away rather than showing the map's own.

    Read-only needs no rule of its own: `ensureEditing` already refuses every
    mode but Browse. What does need saying is that everything the entry moved is
    moved back, since the way out is a dialog rather than a page load.
    """
    _, js, _ = _resources()

    enter = _match(r"async function enterHeatmap\(batch, runs, timelines\) \{(.*?)\n\}", js)
    assert 'setMode("heatmap")' in enter
    assert "baseMapOf(batch)" in enter, "the heat must sit on the world the runs rolled from"
    assert "hideStrip()" in enter, "a batch is not a run and has no slider"

    # **Two ways out, one teardown.** The pill returns to the dialog; a run's
    # name in that dialog goes into that run at that roll. Sharing `leaveHeatmap`
    # is what stops the second from having to undo the first's reopened dialog.
    teardown = _match(r"function leaveHeatmap\(\) \{(.*?)\n\}", js)
    assert "state.heatmap = null" in teardown
    assert "panel-pin" in teardown, "the panel must come back if it was up"
    # Once as the definition, once per way out.
    assert js.count("leaveHeatmap()") == 3, "a way out that does not share the teardown"

    leave = _match(r"async function exitHeatmap\(\) \{(.*?)\n\}", js)
    assert "showSimulations(batch)" in leave, "the way out is the dialog it came from"
    assert 'if (state.mode === "heatmap") return exitHeatmap();' in js

    # Nothing here writes. The dialog's only request is the ledger read behind
    # the grinds column.
    grinds = _match(r"async function fillGrinds\(index, roll\) \{(.*?)\n\}", js)
    assert "postJSON" not in grinds and '"/api/roll?map="' in grinds


def test_a_bar_past_the_cap_keeps_the_band_it_is_in() -> None:
    """**The two axes cap at different heights**, so recolouring an overflowing
    bar made the same roll two different colours depending on the scale: a
    death-band roll of 1,400 hours came out black on the log axis, whose ceiling
    it never reached, and amber on the linear one.

    Which band a roll is in is a fact about the roll; running off the end is a
    fact about the axis. So the band keeps the fill and the overflow takes the
    outline.
    """
    _, _, css = _resources()

    over = _match(r"\n\.tl-bar\.over \{(.*?)\}", css)
    assert "stroke:" in over and "fill:" not in over
    # Except where there is no band to protect, which is the unbanded page.
    assert '.tl-bar.over[data-band=""] { fill: var(--amber); }' in css


def test_a_batch_row_asks_about_its_runs_rather_than_pinning_a_strip() -> None:
    """**Ten runs of one map are ten futures**, and what you want to know
    before opening one is which was kind and which was brutal - a submenu of
    names cannot say that.

    The press used to pin the submenu open, which existed to make the runs
    reachable without a steady hand. The dialog does that better and carries
    the answer as well, so the pin is gone rather than duplicated.

    **Which dialog is now a question the row has to ask**, since a grind batch
    is `simulated` like any other and answers something else entirely - so the
    press goes through `openBatch` and both dialogs stay reachable.
    """
    _, js, css = _resources()

    assert "spec.onBatch(nest.dataset.batch)" in js
    assert "onBatch: openBatch" in js
    dispatch = _match(r"function openBatch\(id\) \{(.*?)\n\}", js)
    assert "showGrind(id)" in dispatch and "showSimulations(id)" in dispatch
    # Replaced, not kept alongside - the word survives in unrelated prose
    # ("pinned at either end" of a zoom), so this looks for the state itself.
    assert "let pinned" not in js and "pinned = nest" not in js

    # The bars are what each roll *added*; the finish line is the outstanding
    # total after the last one, and the two are not the same sum.
    body = _match(r"function runOutstanding\(timeline\) \{(.*?)\n\}", js)
    assert "total_hours" in body

    styles = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    assert ".sim-table" in styles


def test_the_maps_pane_offers_two_simulations_and_names_them_apart() -> None:
    """**Two kinds of run need two names.** "Simulate" was unambiguous while
    there was one; beside a second it names neither, and the two ask genuinely
    different questions - a roll count in, against a roll count out."""
    _, js, _ = _resources()

    assert "<h3>Roll Simulation</h3>" in js
    assert "<h3>Next Grind Simulation</h3>" in js
    for element in ("do-sim", "sim-rolls", "sim-runs", "do-grind", "grind-hours", "grind-runs"):
        assert f'id="{element}"' in js, element
        assert f'getElementById("{element}")' in js, element


def test_grinding_opens_its_summary_rather_than_the_map() -> None:
    """**The deliberate difference from the Roll button**, which opens its
    result as the map because a roll makes one future and that future is the
    answer. A grind makes forty and the answer is what they agree about, so
    opening one of them would be picking a sample and calling it the result.
    """
    _, js, _ = _resources()

    handler = _match(r'runAction\(`Grind past \$\{hours\}h`(.*?)\n    \};', js)
    assert "showGrind(result.grind)" in handler
    assert "openMap(" not in handler, "a grind result is not the map"


def test_the_distribution_scales_uniformly_so_its_labels_are_not_stretched() -> None:
    """**The inverse of the timeline strip's rule, for the same reason.**
    `tlBars` stretches to fill a resizable panel, so every glyph in it has to
    live in an HTML overlay. A dialog has a settled width and pays nothing for
    uniform scaling, so its axis labels are ordinary `<text>`. Setting
    `preserveAspectRatio="none"` here would put stretched letters back.
    """
    _, js, _ = _resources()

    body = _match(r"function grindHistogram\(distribution\) \{(.*?)\n\}", js)
    assert "<text" in body
    assert 'preserveAspectRatio="none"' not in body


def test_the_distribution_counts_simulations_and_so_carries_no_band() -> None:
    """The five bands are the *hours* vocabulary. This axis counts
    simulations, so borrowing their colours would say a 12-chunk column was
    somehow more brutal than a 3-chunk one."""
    _, js, css = _resources()

    body = _match(r"function grindHistogram\(distribution\) \{(.*?)\n\}", js)
    assert "data-band" not in body
    # And the bars still name no colour of their own - CSS picks, as ever.
    assert "fill=" not in body
    styles = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    assert ".gd-bar" in styles


def test_the_grind_drilldown_gets_back_by_a_breadcrumb() -> None:
    """`renderTrail` already draws one and every other drill-down uses it, so
    a Back button here would be a second vocabulary for one gesture. It
    re-renders held data rather than re-fetching, which is what makes the
    crumb a fold rather than navigation."""
    _, js, _ = _resources()

    body = _match(r"function showGrindChunk\(chunkId\) \{(.*?)\n\}", js)
    assert "trail: [{ label: data.batch, go: renderGrind }]" in body
    assert "getJSON(" not in body, "the way back is a re-render, not a fetch"


def test_the_grind_drilldown_opens_the_run_at_the_roll_that_ended_it() -> None:
    """The one thing the dialog cannot show is the chain that got there, and
    the run's own timeline is where that lives - `showHeatChunk`'s gesture,
    reused rather than reinvented."""
    _, js, _ = _resources()

    body = _match(r"function showGrindChunk\(chunkId\) \{(.*?)\n\}", js)
    assert "chooseMap(at.run)" in body
    assert "goToRoll(at.step)" in body


def test_the_stats_link_is_offered_only_by_work_that_has_stats() -> None:
    """A link that opens an empty panel is worse than no link. Most jobs report
    a sentence and nothing else, so the control appears only when structured
    progress actually arrived - see `jobs.Job.detail`."""
    html, js, _ = _resources()

    assert 'id="progress-more"' in html
    assert "hidden" in _match(r'(<button class="progress-more".*?>)', html)
    body = _match(r"function showProgress\(title, \{(.*?)\n\}", js)
    assert "el[\"progress-more\"].hidden = !jobStats" in body


def test_the_stats_panel_redraws_itself_while_the_job_runs() -> None:
    """**It rides the poll rather than fetching.** `followJob` already asks
    every 400ms, so the rows come with it; a panel of its own would be a second
    request saying the same thing at a different moment."""
    _, js, _ = _resources()

    follow = _match(r"async function followJob\(id, label, onDone\) \{(.*?)\n\}", js)
    assert "stats: tick.detail" in follow
    assert "getJSON" not in follow, "the rows ride the poll"
    # And whatever takes the overlay away stops it redrawing over the top.
    assert "overlayIsStats = false" in _match(r"function openOverlay\((.*?)\n\}", js)
    assert "overlayIsStats = false" in _match(r"function closeOverlay\(\) \{(.*?)\n\}", js)


def test_the_stats_panel_does_not_claim_a_queued_run_is_running() -> None:
    """Idle workers are counted from what is *rolling*, not from what is left
    to do - with more simulations than workers most are queued, and calling
    those running would report a machine busier than it is."""
    _, js, _ = _resources()

    body = _match(r"function renderJobStats\(\) \{(.*?)\n\}", js)
    assert "rows.filter((row) => !row.done)" in body
    assert "stats.workers - running.length" in body
    # A queued simulation is counted, never drawn as a row of blanks.
    assert "stats.simulations - rows.length" in body
    assert "not started yet" in body


def test_a_finished_simulation_keeps_its_clock() -> None:
    """How long a run *took* is the more useful half of "how long has this been
    going": it is what says whether the batch is down to one straggler, which
    is how a grind batch actually ends. An earlier version blanked it the
    moment a run finished."""
    _, js, _ = _resources()

    body = _match(r"function renderJobStats\(\) \{(.*?)\n\}", js)
    assert "${seconds(row.seconds)}" in body
    assert 'row.done ? "—" : seconds(row.seconds)' not in body


def test_the_grind_outcomes_are_one_vocabulary() -> None:
    """Named once in `runs/grind.py` and once here, with nothing enforcing
    agreement - which is what this file is for."""
    from chunksim.runs import grind

    _, js, _ = _resources()

    labels = _match(r"const GRIND_OUTCOMES = \{(.*?)\n\};", js)
    named = set(re.findall(r"^\s*(\w+):", labels, re.MULTILINE))
    assert named == set(grind.OUTCOMES)


def test_costing_a_batch_runs_one_at_a_time() -> None:
    """Each pricing job already spreads itself across every core, so starting
    ten at once has them fight over the same cores and finish no sooner - and
    the progress card can only describe one thing."""
    _, js, _ = _resources()

    body = _match(r"async function costSimulations\(batch, runs, timelines\) \{(.*?)\n\}", js)
    assert "await runAction(" in body and "for (let index" in body


def test_type_comes_from_the_scale_like_every_other_length() -> None:
    """**Font size was the one length that escaped the rule.**

    Thirty-seven literals across six values in a five-pixel range - 9, 10, 11,
    12, 13, 14 - with 11 and 12 both carrying secondary text. A one-pixel
    difference between neighbours is not hierarchy, it is jitter, and it is
    what "inconsistent fonts" turned out to mean. Four steps now, named for
    the job rather than the size.
    """
    _, _, css = _resources()
    styles = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)

    assert re.search(r"font-size: \d", styles) is None, "a size literal is back"
    assert re.search(r"font-weight: \d", styles) is None, "a weight literal is back"
    for step in ("--t-micro", "--t-note", "--t-body", "--t-title"):
        assert f"{step}:" in styles and f"var({step})" in styles


def test_the_two_faces_are_tokens_and_nothing_is_downloaded() -> None:
    """A stack that leads with rounded humanists and lands on `system-ui`.
    Nothing is fetched: the CSP forbids it and the project ships no fonts."""
    _, _, css = _resources()
    styles = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)

    assert "--sans:" in styles and "--mono:" in styles
    assert "var(--sans)" in styles and "var(--mono)" in styles
    assert "@font-face" not in styles and "@import" not in styles
    # Figures are tabular: half of what this shows is a column read downward,
    # and proportional digits shuffle it sideways as values change.
    assert "tabular-nums" in styles


def test_reachable_areas_are_drawn_apart_from_the_unlocked_blob() -> None:
    """**Reachable, not rolled.**

    Upstream tracks dungeon access by name, and those names are also the names
    of real squares - the block the wiki draws north of the surface, because
    that is where the game keeps interiors. They cost no chunk, so they get
    their own outline rather than joining the hull, and the count in the bar
    stays the number of chunks the map has.
    """
    _, js, _ = _resources()

    assert "const REACHABLE_STROKE" in js
    body = _match(r"function drawHull\(\) \{(.*?)\n\}", js)
    assert "state.reachable" in body and "setLineDash" in body
    # Dashes floored, or they scale below a pixel at low zoom and the outline
    # reads as solid - the one thing it must not be mistaken for.
    assert "Math.max(4, 6 * state.zoom)" in body
    # And explained, like every other colour on the map.
    legend = _match(r"function renderLegend\(\) \{(.*?)\n\}", js)
    assert "Reachable area" in legend


def test_a_square_is_described_in_one_set_of_words() -> None:
    """**The page had three.** The Chunk pane said `Unlocked`/`Locked`, the
    hover readout printed the server's own lower-case `unlocked`/`added`, and
    the legend had a third set - so the same square read three ways depending
    on where you looked at it.

    `added` still changes name with the mode, because a chunk the *other* map
    has is gained where a chunk this run rolled is rolled. That decision is
    made once now instead of once per reader.
    """
    _, js, _ = _resources()

    assert "function chunkStateLabel(cellState)" in js
    # Every reader goes through it.
    legend = _match(r"function renderLegend\(\) \{(.*?)\n\}", js)
    assert 'chunkStateLabel("added")' in legend and 'chunkStateLabel("removed")' in legend
    assert "cell.state)" not in _match(r"function renderCounts\(\) \{(.*?)\n\}", js)


def test_every_reader_of_candidacy_shares_one_source() -> None:
    """**One map, so they cannot disagree.**

    I had this down as an inconsistency - the Chunk pane naming a candidate
    while the bar counted them only with the layer on - and it was not one:
    `loadCandidates` empties `state.candidates` when the toggle is off, so
    both readers see nothing together. What is worth pinning is the shared
    source, since a second one would be a second answer.
    """
    _, js, _ = _resources()

    assert "state.candidates = new Map();" in js
    for reader in (r"function chunkStatus\(chunkId\) \{(.*?)\n\}",
                   r"function renderCounts\(\) \{(.*?)\n\}"):
        assert "state.candidates" in _match(reader, js)


def test_mono_is_for_what_you_would_type() -> None:
    """**`tabular-nums` retired the old argument for monospacing a number.**

    Counts, hours, progress and axis labels were all monospaced on the
    reasoning that a figure wants a fixed advance; that holds in any face now,
    so a column of hours aligns in sans and reads as language rather than as
    output. What keeps mono is identity - an id, a path, a snippet, the
    single-character marker column whose width *is* its alignment.
    """
    _, _, css = _resources()
    styles = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)

    users = re.findall(r"([^{}]+)\{[^{}]*font-family: var\(--mono\)", styles)
    selectors = {part.strip() for group in users for part in group.split(",")}
    assert selectors <= {"code", ".mono", "ul.list .mark", ".chunk-id"}, (
        f"mono has spread again: {sorted(selectors)}"
    )
    # And the quantities that lost it keep their column.
    assert ".num { font-variant-numeric: tabular-nums; }" in styles


def test_the_ribbon_says_only_what_the_picker_cannot() -> None:
    """**The map's name was in two places thirty pixels apart** - the picker
    button, whose label it is, and the ribbon under it. What the picker has no
    way to say is *which* of a run's worlds is on screen, so that is what the
    ribbon keeps, and it says nothing at all when the panels are not rewound.
    """
    html, js, _ = _resources()

    body = _match(r"function renderRibbon\(\) \{(.*?)\n  for", js)
    assert "state.map" not in body, "the ribbon is naming the map again"
    assert "roll ${state.step} of ${last}" in body
    assert 'id="ribbon-map" class="ribbon-map" hidden' in html


def test_everything_that_decides_what_the_map_draws_is_in_one_row() -> None:
    """Candidates, Sections and the floor are three answers to one question.
    Two were in the bar and the third was pinned to the map's top-right - an
    argument about weight rather than about where it belongs. The bar is where
    this page changes what it shows; the overlays on the map are where it
    reads back."""
    html, _, css = _resources()

    bar = _match(r"<header class=\"bar\">(.*?)</header>", html)
    for control in ('id="candidates"', 'id="masks"', 'id="plane"'):
        assert control in bar, f"{control} is not in the bar"

    styles = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    assert "position: fixed" not in _match(r"\.plane-pick \{([^}]*)\}", styles)


def test_a_reachable_area_shows_the_way_in_when_you_look_at_it() -> None:
    """**The outline says "you can get here" and never "from where".** A
    reachable area is nowhere near its entrance - the Catacombs of Kourend are
    a hundred rows north of their door - so selecting either end draws the
    line, and only then: every link at once is a hundred lines across the map
    and the question is always about one place."""
    _, js, _ = _resources()

    body = _match(r"function drawEntrances\(\) \{(.*?)\n\}", js)
    assert "state.selected" in body and "cell.entrances" in body
    # Either end, and every door - an area can have several.
    assert "String(cell.chunk_id) !== chosen && String(entrance) !== chosen" in body
    assert "setLineDash" in body
    assert "drawEntrances();" in _match(r"function drawHull\(\) \{(.*?)\n\}", js)


def test_an_area_name_is_qualified_wherever_it_is_shown() -> None:
    """`Mor Ul Rek#Outer Area` is the same `#` a task name carries, and the
    Chunk pane's heading printed it raw."""
    _, js, _ = _resources()

    assert "qualified(detail.nickname)" in js


def test_the_setup_steps_name_refresh_targets_the_server_accepts() -> None:
    """**`SETUP_STEPS` is a list of strings the server validates and rejects.**

    `_refresh_job` raises on an unknown `what`, so a typo here is a first run
    that shows a failed step to someone who has never seen the app work - and
    only on a cold cache, which is the state hardest to get back to. The blob
    names have to match `routes_reference._REFERENCE_BLOBS` for the same
    reason: a step keyed to a blob nothing reports reads as permanently
    missing and re-downloads on every boot.
    """
    from chunksim.gui import routes_reference

    js = _app_js()
    block = re.search(r"const SETUP_STEPS = \[(.*?)\];", js, re.DOTALL)
    assert block is not None

    whats = re.findall(r'what:\s*"([^"]+)"', block.group(1))
    blobs = re.findall(r'blob:\s*"([^"]+)"', block.group(1))

    known = {row[2] for row in routes_reference._REFERENCE_BLOBS}
    assert set(whats) == known, f"setup steps and refresh targets disagree: {whats} vs {known}"
    assert set(blobs) == {row[0] for row in routes_reference._REFERENCE_BLOBS}


def test_the_export_is_the_first_setup_step() -> None:
    """Order is a dependency, not a preference: the heuristics scrape runs
    through `ctx.derivations.chunk_info()`, so asking for rates before the
    export is on disk ends that job failed."""
    block = re.search(r"const SETUP_STEPS = \[(.*?)\];", _app_js(), re.DOTALL)
    assert block is not None

    assert re.findall(r'what:\s*"([^"]+)"', block.group(1))[0] == "chunkinfo"


def test_the_setup_screen_cannot_be_dismissed() -> None:
    """It is not the overlay, and that is the point: until the export lands
    there is nothing behind it to dismiss back to. A close button or an
    `aria-modal` sheet here would mean someone can reach a black map."""
    html, _, _ = _resources()
    setup = re.search(r'<div class="setup" id="setup".*?\n</div>', html, re.DOTALL)
    assert setup is not None

    assert "overlay" not in setup.group(0)
    assert "-close" not in setup.group(0)


def test_the_first_run_flag_is_spelled_the_same_on_both_sides() -> None:
    """The page reads it off `/api/settings` and writes it back; `settings.KEYS`
    is what decides whether the write survives `sanitise`."""
    from chunksim.gui import settings

    assert "first_run_done" in settings.KEYS
    assert 'first_run_done: true' in _app_js() or '"first_run_done"' in _app_js()


def test_the_page_watches_rather_than_waiting_to_be_told() -> None:
    """**Panels heal themselves; nothing has to remember to refresh them.**

    `poll` compares two tokens from `/api/revision` - `data` for the files an
    answer is computed from, `revision` for the map itself. Watching only the
    second was the bug: the map file does not change when the export arrives,
    so a panel that rendered before it landed stayed on its placeholder for
    ever, and the fix could not be "call reloadPanels here too" because the
    number of places that would need it is the problem.
    """
    js = _app_js()

    assert "state.dataStamp" in js, "the data token must be remembered to be compared"
    assert re.search(r"answer\.data !== state\.dataStamp", js), "the comparison is the mechanism"
    assert "reloadPanels()" in js


def test_the_poll_is_not_gated_on_having_a_view() -> None:
    """A page with nothing drawn is exactly the page that needs to notice data
    arriving, so the gate is `live` alone."""
    js = _app_js()
    body = re.search(r"async function poll\(\) \{(.*?)\n\}", js, re.DOTALL)

    assert body is not None
    assert "if (!state.live) return;" in body.group(1)
    assert "!state.view ||" not in body.group(1), "a viewless page must still watch"


def test_the_page_catches_up_when_it_becomes_visible() -> None:
    """Chrome throttles timers in a hidden tab to roughly once a minute, so the
    interval alone is not a promise about freshness. Asking on the way back is
    what makes the staleness invisible."""
    js = _app_js()

    assert 'addEventListener("visibilitychange"' in js
    assert re.search(r'visibilityState === "visible"\) poll\(\)', js)


def test_a_name_is_qualified_in_one_place_only() -> None:
    """**The `#` bug, fixed where it cannot come back.**

    `Spikey chain (Slayer Tower)#Advanced` is how the export writes a qualified
    name, and `#` reads as a typo on screen. `qualified` turns it into
    parentheses - but it used to be applied by each renderer, and only to
    *marked* spans, so an unmarked export name kept its `#`. There were four
    renderers by then and the same bug had been fixed in some of them twice.

    It now happens inside `nameParts`, so `.text` is the only way a name comes
    out. This asserts no renderer re-derives it, which is the shape the bug
    took every time.
    """
    js = _app_js()

    assert "qualified(part.raw)" not in js, "a renderer is qualifying names itself again"
    assert re.search(r"const part = \(marked, raw\) => \(\{ marked, raw, text: qualified\(raw\) \}\)", js)
    # Every renderer reads the display form rather than the source form.
    assert js.count("const shown = part.text;") >= 3


def test_keys_keep_the_exports_own_spelling() -> None:
    """`.raw` must survive: the search index is keyed the way the export writes
    it, so `zygomite#Level 86` is what finds the zygomite and
    `zygomite (Level 86)` finds nothing."""
    js = _app_js()

    assert "data-term" in js and "part.raw" in js


def test_the_find_pane_filters_by_asking_rather_than_hiding() -> None:
    """**The strip re-runs the search; it does not hide rows.**

    `/api/search` ranks across the types it was given and keeps the best forty.
    A page that asked for everything and then hid four categories would be
    showing the best forty of a question nobody asked - and could show nothing
    at all where items existed but forty monsters scored higher.
    """
    js = _app_js()

    assert '"&type=" + encodeURIComponent(name)' in js, "the types must reach the server"
    body = re.search(r"function renderFindChips\(\) \{(.*?)\n\}", js, re.DOTALL)
    assert body is not None and "runFind()" in body.group(1)


def test_the_find_pane_uses_the_same_chip_gesture_as_the_tasks_pane() -> None:
    """One gesture across the interface: click for only this, again for all,
    shift adds, ctrl removes - and a strip records what is *off*, so a kind
    nobody has deselected is on by default for ever."""
    js = _app_js()

    assert "const findOff = new Set();" in js
    assert re.search(r"applyChipGesture\(findOff, chip\.dataset\.findType, FIND_TYPES, event\)", js)


def test_a_find_row_says_which_of_the_maps_three_answers_it_is() -> None:
    """`available` is "in a chunk you hold" and has no idea about a square
    behind a dungeon entrance, which costs no chunk and is drawn outlined.
    `chunkStatus` is where that third answer lives, and Find is the pane whose
    disagreement with the map prompted it."""
    js = _app_js()
    _, _, css = _resources()

    assert re.search(r"function findHold\(result, chunks\)", js)
    assert 'chunkStatus(chunk).state === "reachable"' in js
    for hold in ("unlocked", "reachable"):
        assert f'.type-icon[data-hold="{hold}"]' in css


def test_the_chunk_pane_offers_nothing_for_a_square_you_walk_into() -> None:
    """**A reachable chunk is implicitly unlocked and cannot be rolled.**

    It costs no roll and never appears among the candidates - measured on the
    reference map, 92 reachable, 29 rollable and 106 held, with no overlap at
    all - so `chunksim unlock` on one would write a map claiming a roll that
    could not have happened.
    """
    js = _app_js()

    assert re.search(r'const offer = \(detail\.unlocked \|\| hold === "reachable"\) \? "" :', js)


def test_the_chunk_pill_carries_the_same_three_answers() -> None:
    """It said the right *word* for a walk-in square and coloured it grey,
    because the class came from `unlocked` alone. `data-hold` is the vocabulary
    the Find icons, the chunk cards and this now share."""
    js = _app_js()
    _, _, css = _resources()

    assert re.search(r'const hold = detail\.unlocked \? "unlocked" : at\.state;', js)
    assert '.pill[data-hold="reachable"]' in css


def test_every_chip_strip_is_glyphs_with_the_word_in_the_label() -> None:
    """**Three strips, one shape.** Chunk categories, task headings and find
    types are the same control doing the same job, and two of them used to say
    their word on the chip - which wrapped a 360px strip onto three lines and
    made them read as three different things.

    The word does not disappear: it moves to `aria-label` and the tooltip, so a
    screen reader and a hover both still get it. That is the part worth pinning
    - an icon-only button with no label is the accessibility bug this trade
    invites.
    """
    js = _app_js()

    strips = {
        "chunk": r'data-cat="\$\{key\}"',
        "task": r'data-section="\$\{s\.key\}"',
        "find": r'data-find-type="\$\{name\}"',
    }
    for name, marker in strips.items():
        match = re.search(marker + r'.*?</button>', js, re.DOTALL)
        assert match is not None, f"no {name} chip found"
        markup = match.group(0)
        assert "aria-label=" in markup, f"the {name} chip lost its accessible name"
        assert "${icon(" in markup, f"the {name} chip is not a glyph"


def test_every_task_heading_has_a_glyph_of_its_own() -> None:
    """A missing key would fall through to `dot`, which is the same mark for
    two different headings - so the map is asserted whole rather than trusted
    to a fallback nobody would notice."""
    js = _app_js()
    html, _, _ = _resources()

    block = re.search(r"const TASK_ICONS = \{(.*?)\};", js, re.DOTALL)
    assert block is not None
    icons = dict(re.findall(r'(\w+): "([\w-]+)"', block.group(1)))

    assert set(icons) == {"skills", "bis", "Diary", "Quest", "Extra"}
    for name in icons.values():
        assert f'id="i-{name}"' in html, f"no sprite for {name}"


def test_the_done_toggle_adds_rather_than_swaps() -> None:
    """**"Also show done", not "show done".** It used to replace the
    outstanding list with the finished one, which answers "what have I done"
    and loses "what am I doing" - and the two are read together."""
    js = _app_js()
    html, _, _ = _resources()

    assert 'state.showDone ? "both" : "active"' in js
    assert "Also show done" in html
    body = re.search(r"function rowsFor\(group, side\) \{(.*?)\n\}", js, re.DOTALL)
    assert body is not None
    assert "...group.active," in body.group(1), "the outstanding rows must come first"


def test_a_done_row_is_struck_through_and_says_when() -> None:
    """Amber for the chunk in play, green for before it - amber is the accent
    that means "current" everywhere else, and a task finished on the chunk you
    are looking at is still news. Line-through rather than dimming, because the
    list is additive now and a done row still has to be readable."""
    js = _app_js()
    _, _, css = _resources()

    assert 'row.when === "chunk" ? " done done-now" : " done"' in js
    assert "text-decoration: line-through" in css
    assert ".task.done-now .name" in css


def test_ticking_follows_the_row_rather_than_the_toggle() -> None:
    """The guard refused while `showDone` was on, which was right when that
    swapped the list and wrong the moment it started adding to it: the
    outstanding rows are still there and still tickable."""
    js = _app_js()

    assert 'if (!row || row.classList.contains("done")) return;' in js


def test_the_methods_overlay_is_reachable_from_both_surfaces() -> None:
    """**One dialog, two entrances.** The Estimate pane and a roll's Details
    overlay both open it, and it drills one level deeper from either - so both
    buttons have to exist and both have to hand `showMethods` a trail. A button
    wired to no trail would open a dialog you cannot get back from.
    """
    html, js, _ = _resources()

    assert 'id="estimate-methods"' in html
    assert 'id="roll-methods"' in js, "the Details overlay's button is built in JS"
    assert re.search(r'el\["estimate-methods"\]\.addEventListener\("click", \(\) => showMethods\(\[\]\)', js)
    assert re.search(r'roll-methods"\)\.onclick = \(\) =>\s*showMethods\(\[', js)


def test_the_trail_is_passed_in_rather_than_remembered() -> None:
    """A stack owned by `showMethods` would have to know which entrance it came
    through, and would be wrong the first time somebody opened it twice. Both
    functions take the trail as an argument, and the drill-down appends to the
    one it was given."""
    _, js, _ = _resources()

    assert "async function showMethods(trail)" in js
    assert "async function showSkillMethods(skill, trail)" in js
    assert "[...trail, { label: METHODS_TITLE, go: () => showMethods(trail) }]" in js


def test_the_crumbs_come_before_the_title() -> None:
    """The title *is* the last crumb, so reading left to right you pass what
    you came through and arrive at where you are."""
    html, _, _ = _resources()

    assert html.index('id="overlay-trail"') < html.index('id="overlay-title"')


def test_every_dialog_that_opened_before_still_opens_the_same_one() -> None:
    """`openOverlay`'s trail and tools are optional, so a caller that passes
    neither gets exactly the dialog it got before this existed - and both are
    written unconditionally, or a breadcrumb outlives the thing it was about."""
    _, js, _ = _resources()

    assert "function openOverlay(title, html, actions, opts) {" in js
    assert 'const { trail = [], tools = "", keepDrill = false } = opts || {};' in js
    assert 'el["overlay-tools"].innerHTML = tools;' in js
    assert 'renderTrail(el["overlay-trail"], trail);' in js


def test_the_methods_list_ranks_on_what_a_method_is_worth_here() -> None:
    """**Not on its headline.** A guide quotes a method with its materials to
    hand; on a chunk map obtaining them is often most of the cost, so the row
    shows `effective_xp_per_hour` rather than the headline `xp_per_hour` a
    guide would print - just the one number, not both."""
    _, js, _ = _resources()

    body = js[js.index("function methodRate(option)"):]
    body = body[: body.index("\n}")]

    assert "effective_xp_per_hour" in body
    assert "xp_per_hour" not in body.replace("effective_xp_per_hour", "")


def test_the_status_vocabulary_is_the_pure_layers() -> None:
    """`costing/coverage.status_of` sorts a `match` into a status and the page
    renders one; a `match` the page has never heard of must read as unpriced
    rather than as blank."""
    from chunksim.costing import coverage

    _, js, _ = _resources()
    table = js[js.index("const METHOD_STATUS = {"):]
    table = table[: table.index("\n};")]

    assert "METHOD_STATUS[match] || METHOD_STATUS.default" in js
    named = set(re.findall(r"^  (\w+):", table, re.M))
    assert coverage.MODELLED_MATCHES <= named
    assert coverage.GUESS_MATCHES <= named
    assert {"exact", "contained", "default"} <= named
