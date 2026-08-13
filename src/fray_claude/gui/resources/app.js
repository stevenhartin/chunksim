"use strict";
/* The world map canvas, and the panel beside it.
 *
 * One classic script, no modules, no build step, no CDN for *code*. The
 * zero-dependency rule is about what a user has to install, and shipping a
 * bundler would break its spirit even though npm is not pip. The map tiles are
 * the one thing loaded from elsewhere, and deliberately so: see `tileUrl`.
 *
 * Pan and zoom are manual affine arithmetic rather than ctx.transform, matching
 * upstream's renderer so the two can be compared line by line: the map is one
 * drawImage at (panX, panY) scaled by zoom, and every chunk rect is
 * pan + zoom * grid * PIXELS_PER_CHUNK. Two departures are marked DEVIATION.
 *
 * Everything the panel renders arrives already shaped by gui/panels.py, so
 * this file decides how a row *looks* and never what a row *is*.
 */

const CANVAS = document.getElementById("canvas");
const CTX = CANVAS.getContext("2d");

/* Zoom is a multiplier on `geometry.pixels_per_chunk`, which is one chunk at
 * the tiles' native resolution (256px, i.e. 4px per game tile). So zoom 1.0 is
 * 1:1 with the source and these are really "a chunk may be 15 to 640 screen
 * pixels". The ceiling is above 1.0 on purpose - past there it is upscaling,
 * but reading a chunk's contents off the picture is worth a soft image. */
const MIN_ZOOM = 0.06;
const MAX_ZOOM = 2.5;
const ZOOM_STEP = 0.15;

/* **How close focusing gets you, when you were further out than this.** At
 * 0.06 a chunk is fifteen pixels and centring on one puts a speck in the
 * middle of the screen - technically the answer, and no use. 0.5 is a 128px
 * chunk: its own tiles are readable and its neighbours are still on screen,
 * which is what "look at this one" means on a map made of squares.
 *
 * It is a floor and not a target. Someone already at 1.8 asked to be there,
 * and hauling them back out to 0.5 because they clicked a row would be the
 * camera overriding a decision rather than serving one. */
const FOCUS_ZOOM = 0.5;

/* Upstream's own wash, so a screenshot of either is recognisably the same map. */
const LOCKED_WASH = "rgba(150, 150, 150, 0.6)";
const ADDED_FILL = "rgba(60, 200, 90, 0.45)";
const REMOVED_FILL = "rgba(220, 60, 60, 0.45)";
const CANDIDATE_FILL = "rgba(90, 190, 255, 0.34)";
/* A pending unlock: amber, because it is neither a gain the map has made nor
   a candidate it could make - it is a claim waiting to be committed. */
const PENDING_FILL = "rgba(255, 190, 0, 0.42)";
const PENDING_STROKE = "#ffbe00";
const CANDIDATE_STROKE = "#5abeff";
const HULL_STROKE = "#ffbe00";
const FOUND_FILL = "rgba(255, 190, 0, 0.30)";
const GRID_STROKE = "rgba(255, 255, 255, 0.14)";
const HOVER_FILL = "rgba(255, 255, 255, 0.10)";

/* Section shading. Strong enough to read at a glance rather than to be looked
 * for: this is a mode you turn on to answer one question, and the first pass
 * at 0.30 alpha over a busy map answered it only if you already knew where to
 * look. The edge carries no alpha at all, because it is the thing that
 * separates two adjacent sections that happen to shade the same colour. */
const SECTION_REACHED = { fill: "rgba(50, 210, 90, 0.52)", edge: "#8dffae" };
const SECTION_LOCKED = { fill: "rgba(225, 55, 55, 0.50)", edge: "#ff9090" };

/* The section id meaning "the whole square". Must match `server.py`'s
 * WHOLE_CHUNK_SECTION: an unsplit chunk has no mask to composite, so its one
 * section is drawn as the square itself. */
const WHOLE_CHUNK = "*";

/* The ring the mask outline is drawn with, in *mask* pixels. A one-pixel ring
 * on a 192-pixel canvas is a quarter of a screen pixel once that canvas is
 * drawn at 44px, which is to say invisible - the outline has to be built at a
 * width that survives the downscale. */
const RING = 3;

/* Below this on-screen chunk size the sections inside one square are a few
 * pixels each, so shading them is noise and fetching their masks is waste. */
const MASK_MIN_CELL = 44;
/* A ceiling on how many squares a single frame may ask upstream about. The
 * masks are cached on disk after the first fetch, but the first fetch of a
 * whole zoomed-out screen would be hundreds of requests for shapes too small
 * to read. */
const MASK_MAX_CHUNKS = 48;

/* Edge bit flags. Must match gui/worldmap.py's Edge. */
const TOP = 1, BOTTOM = 2, LEFT = 4, RIGHT = 8;

const state = {
  /* **What is on screen, as data.** `map`, `compare` and `tab` used to live in
   * DOM `value`s and be read back out of them in twenty-odd places, which made
   * the `<select>` the source of truth for what the page was looking at. They
   * are here instead, and the controls render *from* them - see `setMap`. */
  map: "",
  compare: "",
  tab: "",
  /* Which of the four modes the page is in - see `MODES`. The ribbon says so
   * in colour, and `mapQuery` switches on it rather than on which control
   * happens to hold a value. */
  mode: "browse",
  /* `/api/maps` as it came, so `kindOf` can answer what a map *is* without
   * asking the server again. Refreshed by `loadMaps`. */
  maps: [],
  /* **Edit mode's pending set, held here and nowhere else until Commit.**
   * That is what makes editing cheap: a tick greys a row and an unlock lights
   * a square with no derivation at all, and exactly one happens - on the
   * world that results. A preview that re-derived per click would cost ~0.8s
   * a tick to answer a question nobody asked half way through.
   *
   * `ticked` is category -> Set of raw task keys, keyed the way
   * `completedChallenges` is rather than the way the panel is grouped - see
   * `panels._entry`. */
  edits: { unlocked: new Set(), ticked: new Map() },
  view: null,
  cells: new Map(),        // "gx,gy" -> cell, for the locked-wash complement
  candidates: new Map(),   // chunk id -> neighbour entry
  found: new Set(),        // chunk ids highlighted by a search
  sections: {},            // chunk id -> {section: reachable}, for the masks
  areas: {},               // chunk id -> named area, for labels and the readout
  selected: null,
  hovered: null,
  /* Which section a hovered row in the Chunk tab is about, painted on the map
   * by `drawHoverSection`. `{chunk, sections[], reachable}` or null. */
  hoverSection: null,
  panX: 0, panY: 0, zoom: 0.5,
  plane: 0,
  needsDraw: false,
  live: true,
  showCandidates: false,
  showMasks: false,
  showDone: false,
  revision: null,
  /* A simulated run's replay. `step` is null when the map is not a run or the
   * slider is at the end - which is the same view as not asking for a step at
   * all, so the query stays clean for the common case. */
  timeline: null,
  step: null,
  /* Which install is serving this page, for the watermark. Fetched once. */
  build: null,
  /* Chunk id -> the name a person calls it. Static per export, fetched with
   * `areas` on boot. Empty until then, which `chunkLabel` treats as "no name
   * known" rather than as an error. */
  labels: {},

  /* The interface's own preferences, from `GET /api/settings`. `null` until
   * they land or if they cannot be read - see `tlBands`. */
  settings: null,
};

const el = {};
for (const id of [
  "map-pick", "map-pick-dot", "map-pick-name", "map-menu",
  "compare", "breakdown", "plane", "candidates", "masks", "live", "fit", "counts", "skipped",
  "hover", "panel-pin", "panel-pin-icon", "panel", "tabs", "toast", "legend", "tip",
  "ribbon", "ribbon-mode", "ribbon-map", "ribbon-vs", "compare-start", "exit-mode",
  "ribbon-edits", "do-commit",
  "progress", "progress-title", "progress-count", "progress-detail",
  "progress-track", "progress-fill", "progress-cancel",
  "overlay", "overlay-title", "overlay-body", "overlay-close", "overlay-actions",
  "chunk-head", "chunk-chips", "chunk-body", "task-chips", "tasks-body",
  "show-done", "estimate-total", "estimate-why", "estimate-body",
  "find-body", "find-form", "find-input", "maps-body", "attribution", "watermark",
  "timeline", "tl-title", "tl-chips", "tl-scale", "tl-key",
  "tl-hours", "tl-details", "tl-collapse", "tl-graph",
  "tl-prev", "tl-slider", "tl-next", "tl-step", "tl-snapshot",
]) el[id] = document.getElementById(id);

/* ---- geometry ---------------------------------------------------------- */

function cellSize() { return state.zoom * state.view.geometry.pixels_per_chunk; }

function toScreen(gx, gy) {
  const size = cellSize();
  return [state.panX + gx * size, state.panY + gy * size];
}

/* The browser inverts the projection itself rather than asking the server: a
 * chunk id is a function of its square, so a round trip per mousemove would be
 * absurd. Must match gui/worldmap.py's grid_position. */
function gridToChunk(gx, gy) { return String((gx + 14) * 256 + (197 - gy)); }

function chunkToGrid(chunkId) {
  const id = Number(chunkId);
  if (!Number.isFinite(id)) return null;
  const gx = (id >> 8) - 14, gy = 197 - (id & 0xff);
  const { grid_columns: cols, grid_rows: rows } = state.view.geometry;
  if (gx < 0 || gy < 0 || gx >= cols || gy >= rows) return null;
  return [gx, gy];
}

/* ---- camera ------------------------------------------------------------ */

/* A generic glide, because three different things want one: the focus key, a
 * search hit, and a chunk clicked in a list. Nothing about it knows what a
 * chunk is.
 *
 * **easeOutBack overshoots by design, and that is why zoom does not use it.**
 * A pan that runs past its mark and settles reads as momentum; a zoom that
 * does the same runs past MAX_ZOOM, gets clamped, and stalls visibly at the
 * end of the move. So the overshoot is applied to the translation and the
 * scale gets a plain decelerating curve.
 *
 * `BACK` is the overshoot's strength, and the textbook 1.7 - which puts the
 * camera ~10% past its mark - is too much on a map: the thing you asked to
 * look at leaves the middle of the screen before it comes back. 1.0 overshoots
 * 3.7%, which still reads as momentum rather than as a snap without ever
 * losing the target. (The peak is not `BACK` itself and is not linear in it:
 * 1.2 gives 5.3% and 0.7 gives 1.8%, so it is worth measuring rather than
 * guessing at.) */
const GLIDE_MS = 420;
const BACK = 1.0;

function easeOutBack(t) {
  const u = t - 1;
  return 1 + (BACK + 1) * u * u * u + BACK * u * u;
}

/* How far past 1 `easeOutBack` actually goes, which decides whether the zoom
 * can afford it. `f'(t) = 6u^2 + 2u` is zero at `u = -1/3`, and `f(-1/3)` is
 * `1 + 2(-1/27) + 1/9`. Derived rather than measured, so changing `BACK`
 * without changing this is a bug that shows up as a stall. */
const GLIDE_PEAK = 1 + 2 * Math.pow(-1 / 3, 3) + Math.pow(-1 / 3, 2);

function easeOutCubic(t) { return 1 - Math.pow(1 - t, 3); }

let glide = null;

function glideTo(target) {
  /* Reduced motion is a real preference and a map that lurches is exactly
   * what it is about. Honour it by arriving immediately. */
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    Object.assign(state, target);
    return invalidate();
  }
  glide = {
    from: { panX: state.panX, panY: state.panY, zoom: state.zoom },
    to: target,
    started: performance.now(),
  };
  requestAnimationFrame(stepGlide);
}

function stepGlide(now) {
  if (!glide) return;
  const t = Math.min(1, (now - glide.started) / GLIDE_MS);
  const { from, to } = glide;
  /* **The zoom gets the overshoot too, when it can afford it.** The rule the
   * comment above states is about the *clamp*, not about the curve: a scale
   * that runs past `MAX_ZOOM` is held there and the move stalls visibly at the
   * end. So the peak is computed and the curve chosen per glide - which means
   * a focus from far out, the common case, moves the way the pan does. */
  const peak = from.zoom + (to.zoom - from.zoom) * GLIDE_PEAK;
  const canBack = peak <= MAX_ZOOM && peak >= MIN_ZOOM;
  const pan = easeOutBack(t), scale = canBack ? easeOutBack(t) : easeOutCubic(t);
  state.panX = from.panX + (to.panX - from.panX) * pan;
  state.panY = from.panY + (to.panY - from.panY) * pan;
  state.zoom = from.zoom + (to.zoom - from.zoom) * scale;
  draw();
  if (t < 1) requestAnimationFrame(stepGlide);
  else glide = null;
}

function stopGlide() { glide = null; }

/* Where the camera would have to be for `chunkId` to sit in the middle of the
 * space the panel is not covering. */
function centredOn(chunkId, zoom) {
  const at = chunkToGrid(chunkId);
  if (!at) return null;
  const size = zoom * state.view.geometry.pixels_per_chunk;
  return {
    panX: (CANVAS.clientWidth - panelWidth()) / 2 - (at[0] + 0.5) * size,
    panY: (CANVAS.clientHeight + barHeight()) / 2 - (at[1] + 0.5) * size,
    zoom,
  };
}

function focusChunk(chunkId, { zoom } = {}) {
  if (!state.view) return;
  /* Focusing pulls you *in* to `FOCUS_ZOOM` and never pushes you out: further
   * than that and a chunk is a speck, closer and you are already looking at
   * what you asked for. An explicit `zoom` overrides both. */
  const wanted = zoom || Math.max(state.zoom, FOCUS_ZOOM);
  const target = centredOn(chunkId, clamp(wanted, MIN_ZOOM, MAX_ZOOM));
  if (target) glideTo(target);
}

/* ---- section masks ------------------------------------------------------ */

/* Upstream's 192x192 1-bit PNGs, one per (chunk, section). A `tRNS` chunk
 * makes grey 0 transparent, so the *opaque* pixels are the section - which is
 * what lets several of them composite onto one square.
 *
 * Tinting happens once per (mask, state) and is kept, because it is two
 * composite passes and a per-frame redraw would do it sixty times a second.
 * The outline is the classic trick: draw the silhouette four times, one pixel
 * off in each direction, then punch the unshifted silhouette back out. What
 * survives is a one-pixel ring, which is what keeps a section readable when
 * the fill alone would blend into its neighbour. */
const maskCache = new Map();   // "12850-1:reached" -> canvas | null | Promise
const maskMisses = new Set();  // names upstream has no mask for

function tintMask(image, colours) {
  const out = document.createElement("canvas");
  out.width = out.height = 192;
  const c = out.getContext("2d");

  c.drawImage(image, 0, 0);
  c.globalCompositeOperation = "source-in";
  c.fillStyle = colours.fill;
  c.fillRect(0, 0, 192, 192);

  const ring = document.createElement("canvas");
  ring.width = ring.height = 192;
  const r = ring.getContext("2d");
  /* Eight offsets rather than four: at RING pixels the four-way version leaves
   * the corners of a diagonal edge stepped, which reads as a jagged mask
   * rather than as a jagged coastline. */
  const d = RING, k = Math.round(RING * 0.71);
  for (const [dx, dy] of [
    [d, 0], [-d, 0], [0, d], [0, -d],
    [k, k], [-k, k], [k, -k], [-k, -k],
  ]) r.drawImage(image, dx, dy);
  r.globalCompositeOperation = "destination-out";
  r.drawImage(image, 0, 0);
  r.globalCompositeOperation = "source-in";
  r.fillStyle = colours.edge;
  r.fillRect(0, 0, 192, 192);

  c.globalCompositeOperation = "source-over";
  c.drawImage(ring, 0, 0);
  return out;
}

function maskFor(chunkId, section, reachable) {
  const name = chunkId + "-" + section;
  const key = name + (reachable ? ":reached" : ":locked");
  if (maskCache.has(key)) {
    const held = maskCache.get(key);
    return held instanceof Promise ? null : held;
  }
  if (maskMisses.has(name)) return null;

  const pending = new Promise((resolve) => {
    const image = new Image();
    image.onload = () => {
      const tinted = tintMask(image, reachable ? SECTION_REACHED : SECTION_LOCKED);
      maskCache.set(key, tinted);
      invalidate();
      resolve(tinted);
    };
    image.onerror = () => {
      /* Upstream drew a mask for every section it drew, and nothing promises
       * one for a section it did not. Absence is an answer: remember it, so
       * one 404 does not become one per frame. */
      maskMisses.add(name);
      maskCache.delete(key);
      resolve(null);
    };
    image.src = "/assets/section/" + encodeURIComponent(name) + ".png";
  });
  maskCache.set(key, pending);
  return null;
}

/* Whether drawing this chunk would put new requests on the wire. A mask
 * already tinted costs nothing, and one already in flight costs nothing
 * *again* - `maskCache` holds the Promise under the same key, which is what
 * makes "has" the right test for both. An unsplit chunk has no mask at all. */
function maskPending(chunkId, sections) {
  for (const [section, reachable] of Object.entries(sections)) {
    if (section === WHOLE_CHUNK) continue;
    const name = chunkId + "-" + section;
    if (!maskCache.has(name + (reachable ? ":reached" : ":locked")) && !maskMisses.has(name)) {
      return true;
    }
  }
  return false;
}

/* Which squares are worth shading: the one you selected, always, plus every
 * chunk on screen once a chunk is big enough for its sections to be legible.
 *
 * **The budget counts new fetches, not chunks.** MASK_MAX_CHUNKS exists to
 * stop one frame asking upstream about hundreds of files - and spending it on
 * chunks that need nothing is worse than useless: the loop walks
 * `state.sections` in the same order every frame, so counting already-cached
 * squares meant the first 48 kept the budget forever and the 49th onwards were
 * never requested at all. Every screen past about eight chunks wide had a
 * permanent unshaded remainder that no amount of waiting filled in. */
function maskTargets() {
  const size = cellSize();
  const wanted = [];
  let fetching = 0;
  if (state.selected && state.sections[state.selected]) wanted.push(state.selected);
  if (size >= MASK_MIN_CELL) {
    for (const chunkId of Object.keys(state.sections)) {
      if (chunkId === state.selected) continue;
      const at = chunkToGrid(chunkId);
      if (!at) continue;
      const [x, y] = toScreen(at[0], at[1]);
      if (!onScreen(x, y, size)) continue;
      if (maskPending(chunkId, state.sections[chunkId]) && ++fetching > MASK_MAX_CHUNKS) continue;
      wanted.push(chunkId);
    }
  }
  return wanted;
}

/* ---- drawing ----------------------------------------------------------- */

/* An ordered list, which is the extension point: the planned roll heatmaps are
 * one more entry plus one key in view.overlays, and nothing about pan, zoom or
 * the hull has to change. */
const LAYERS = [
  drawTiles, drawLockedWash, drawGrid, drawStates, drawMasks, drawHoverSection, drawFound,
  drawCandidates, drawPending, drawHull, drawAreas, drawHovered, drawSelected,
];

/* Below this on-screen chunk size a name is unreadable and the map is better
 * off without it. */
const AREA_LABEL_MIN_CELL = 54;

/* ---- the tile layer ---------------------------------------------------- */

/* **The map is the OSRS wiki's cartography tiles, loaded straight from their
 * CDN by this page.** Nothing about them passes through `fray-gui`: the server
 * hands over a URL template and this file puts it in an `Image`, so the bytes
 * go wiki -> browser cache and touch no disk of ours. That is a licence
 * decision, not a performance one - the tiles are CC BY-NC-SA 3.0 against this
 * project's MIT, and caching or re-serving them would make it a redistributor
 * of NonCommercial artwork. Linking to them makes it a page with a picture on
 * it. `MAP_TILE_ATTRIBUTION` is on screen for the same reason.
 *
 * The scheme is a standard pyramid keyed on the game's own coordinates:
 * `256 / 2**z` game tiles per 256px tile, y counting *northward*. So z=2 is
 * exactly one tile per chunk, z=1 covers 2x2 chunks, z=3 splits a chunk into
 * 2x2 - which means `tileZoom` only has to pick the level whose source
 * resolution is nearest the size a chunk is being drawn at, and the number of
 * requests on screen stays roughly constant however far you zoom out. */
const TILE_PIXELS = 256;
const MIN_TILE_ZOOM = -3;
const MAX_TILE_ZOOM = 3;

/* Where the tiles come from. Filled in by `/api/tiles`; until then there is
 * simply no base layer, and the grid, hull and overlays draw over nothing. */
const tiles = { template: "", version: "", map_id: -1, attribution: "", error: null };

const tileCache = new Map();   // url -> Image | "pending" | "missing"

/* Game tiles spanned by one 256px tile at this zoom. */
function tileSpan(z) { return TILE_PIXELS / Math.pow(2, z); }

/* The pyramid level to draw at: the coarsest one whose source is still at
 * least as detailed as the screen. Source pixels per chunk at level z is
 * `64 / tileSpan(z) * 256`; solving for cell size gives this log. */
function tileZoom() {
  const perChunk = cellSize();
  const wanted = Math.ceil(Math.log2(perChunk / 64));
  return Math.max(MIN_TILE_ZOOM, Math.min(MAX_TILE_ZOOM, wanted));
}

function tileUrl(z, x, y, plane) {
  return tiles.template
    .replace("{version}", tiles.version)
    .replace("{map_id}", String(tiles.map_id))
    .replace("{z}", String(z))
    .replace("{plane}", String(plane == null ? state.plane : plane))
    .replace("{x}", String(x))
    .replace("{y}", String(y));
}

/* How many times a tile is asked for again before it counts as absent.
 *
 * **A failed `Image` cannot tell you why it failed.** `onerror` fires the same
 * way for a 404 as for a connection the browser dropped because two hundred
 * requests went out at once - and one dropped request, remembered forever, is
 * a square that stays black for the rest of the session however long you look
 * at it. So a miss is provisional until it has happened `TILE_TRIES` times.
 * Absent tiles cost two extra requests each, once; transient ones recover. */
const TILE_TRIES = 3;

const tileFails = new Map();   // url -> how many times it has failed

function tileFor(z, x, y, plane) {
  const url = tileUrl(z, x, y, plane);
  const held = tileCache.get(url);
  if (held !== undefined) return held instanceof Image ? held : null;

  const image = new Image();
  /* The CDN answers `access-control-allow-origin: *`, so asking for CORS
   * costs nothing and keeps the canvas untainted - which matters the day
   * anything wants `getImageData` off it. */
  image.crossOrigin = "anonymous";
  image.onload = () => { tileCache.set(url, image); tileFails.delete(url); invalidate(); };
  image.onerror = () => {
    const failed = (tileFails.get(url) || 0) + 1;
    tileFails.set(url, failed);
    if (failed >= TILE_TRIES) {
      /* Ocean and off-world squares really have no tile. Remembering that is
       * what stops one 404 becoming one request per frame. */
      tileCache.set(url, "missing");
    } else {
      /* Dropping the entry is what lets a later frame ask again. */
      tileCache.delete(url);
      invalidate();
    }
  };
  image.src = url;
  tileCache.set(url, "pending");
  return null;
}

/* ---- separating a floor from the ground under it ------------------------ */

/* **A tile for plane N is not that floor on its own.** It is the whole ground
 * floor faded back, with this floor's own features drawn over the top - one
 * flat image, no transparency, and no separate overlay tile to ask for
 * (Kartographer's `basePlainTileURL` turns out to be the same URL as the
 * ordinary one on this wiki). So sinking the *background* while leaving the
 * floor bright means working out which pixels are which.
 *
 * A flat wash over the whole tile was the first attempt and it is not this:
 * it dimmed the floor along with the ground, which is the thing it was
 * supposed to separate.
 *
 * **The fade is linear, so it can be fitted and subtracted.** Across a tile,
 * `planeN ≈ a * plane0 + b` per channel holds for 70-90% of pixels to within
 * a few levels, and that majority *is* the ground. `a` is nothing like
 * constant - 0.13 on Lumbridge, 0.36 on Al Kharid, 0.52 on God Wars - which
 * is why it is fitted per tile rather than assumed. Whatever misses the fit
 * is what this floor added, and it is left exactly alone.
 *
 * The result is cached per tile: it costs two `getImageData` calls and a pass
 * over 65k pixels, which is the same bargain `tintMask` makes for the section
 * overlays. */
const PLANE_GHOST_SCRIM = 0.72;

/* How far a pixel may sit from the fitted fade and still count as ground.
 * Generous on purpose: the fade is fitted over a whole tile, so it is never
 * exact, while the features this has to spare are drawn in flat colour and
 * miss by far more than this. */
const PLANE_GHOST_TOLERANCE = 14;

const planeCache = new Map();   // plane-N tile url -> composed canvas

/* How many tiles may be separated in one frame.
 *
 * Measured at 3-4.5ms each, so a screenful of 91 cost 280ms in one go - a
 * hitch you feel every time you pan somewhere new on an upper floor. At this
 * budget the same 91 spread over seven frames with a worst frame of 55ms, and
 * the tiles waiting their turn draw *unseparated* rather than not at all, so
 * the map fills in and settles instead of stalling. Steady state is 0.9ms. */
const PLANE_COMPOSE_BUDGET = 12;
let composeBudget = 0;

/* `y = a*x + b` by least squares, from running sums - no matrices needed. */
function fitFade(under, over, channel) {
  let sx = 0, sy = 0, sxx = 0, sxy = 0;
  const n = under.length / 4;
  for (let i = channel; i < under.length; i += 4) {
    const a = under[i], b = over[i];
    sx += a; sy += b; sxx += a * a; sxy += a * b;
  }
  const denom = n * sxx - sx * sx;
  if (!denom) return [0, sy / n];
  const slope = (n * sxy - sx * sy) / denom;
  return [slope, (sy - slope * sx) / n];
}

function composeFloor(ground, floor) {
  const out = document.createElement("canvas");
  out.width = out.height = TILE_PIXELS;
  const c = out.getContext("2d", { willReadFrequently: true });

  c.drawImage(floor, 0, 0);
  const top = c.getImageData(0, 0, TILE_PIXELS, TILE_PIXELS);
  c.drawImage(ground, 0, 0);
  const under = c.getImageData(0, 0, TILE_PIXELS, TILE_PIXELS).data;
  const px = top.data;

  const fit = [0, 1, 2].map((channel) => fitFade(under, px, channel));
  const keep = 1 - PLANE_GHOST_SCRIM;
  for (let i = 0; i < px.length; i += 4) {
    let miss = 0;
    for (let ch = 0; ch < 3; ch++) {
      miss += Math.abs(fit[ch][0] * under[i + ch] + fit[ch][1] - px[i + ch]);
    }
    /* Ground: sink it. This floor's own features: leave them exactly alone. */
    if (miss / 3 < PLANE_GHOST_TOLERANCE) {
      px[i] *= keep; px[i + 1] *= keep; px[i + 2] *= keep;
    }
  }
  c.putImageData(top, 0, 0);
  return out;
}

/* The tile to draw for the current plane: raw on the ground floor, and the
 * floor lifted off its own background above it.
 *
 * Returns the *unseparated* tile while the ground floor is still on the wire,
 * and permanently if the ground floor has no tile at all. Both beat drawing
 * nothing, and the first self-corrects on the frame after the fetch lands. */
function composedTile(z, x, y) {
  const floor = tileFor(z, x, y, state.plane);
  if (!state.plane || !floor) return floor;

  const key = tileUrl(z, x, y, state.plane);
  const held = planeCache.get(key);
  if (held) return held;

  const ground = tileFor(z, x, y, 0);
  if (!ground) return floor;
  if (composeBudget <= 0) {
    /* Out of budget this frame. Draw the floor as it came and ask for another
     * frame, which will pick up where this one stopped. */
    invalidate();
    return floor;
  }
  composeBudget--;
  const composed = composeFloor(ground, floor);
  planeCache.set(key, composed);
  return composed;
}

/* The nearest loaded ancestor of a tile, and which part of it to draw.
 *
 * **A tile that is not there yet should look like a blurry version of itself,
 * not like a hole.** Every level of the pyramid covers the same world, so the
 * tile one level up contains this one at half the resolution - and its
 * grandparent at a quarter, and so on. Walking up until something is loaded
 * gives progressive refinement while panning, and it is also what rescues a
 * square whose own tile failed: the black squares this replaces were a
 * dropped request being remembered, drawn as nothing.
 *
 * The y arithmetic is the one part that is not obvious. Tile indices count
 * *northward* but image rows run *southward*, so within an ancestor the child
 * with the **highest** y sits at the **top**: hence `span - 1 - (y & mask)`
 * rather than the `x` form. Getting that backwards mirrors each fallback
 * vertically, which looks like a plausible piece of map.
 *
 * **This asks for the ancestors, it does not merely use ones already held**,
 * and the cost of that is bounded rather than merely small: each level up has
 * a quarter the tiles, so a screen of N tiles pulls at most N(1 + 1/4 + 1/16 +
 * ...) < 1.34N. In exchange the fallback works on a cold deep link, and
 * zooming back *out* is instant because those levels are already there. */
function tileAncestor(z, x, y) {
  for (let up = 1; z - up >= MIN_TILE_ZOOM; up++) {
    const step = 1 << up;
    const image = composedTile(z - up, x >> up, y >> up);
    if (!image) continue;
    const size = TILE_PIXELS / step;
    return {
      image,
      sx: (x & (step - 1)) * size,
      sy: (step - 1 - (y & (step - 1))) * size,
      size,
    };
  }
  return null;
}

/* Grid space <-> world-tile space. `gridToChunk` already encodes the
 * projection; these are the same arithmetic without the round trip through a
 * chunk id, because a tile boundary need not land on one.
 *
 * **The y constant is 66, not the 65 of `gridToChunk`, and that is not a
 * typo.** `grid_y = 65 - region_y` numbers a *cell*: region 65 is row 0. These
 * take a world coordinate and answer where that *line* is, and the line at the
 * top of row 0 is region 65's **north** edge - world y 4224, which is region
 * 66's south edge. Off by one and every tile draws one row high, which looks
 * like a plausible map of somewhere slightly wrong. */
const GRID_TOP_REGION_Y = 198;

function worldToScreenX(wx) { return state.panX + (wx / 64 - 14) * cellSize(); }
function worldToScreenY(wy) {
  return state.panY + (GRID_TOP_REGION_Y - wy / 64) * cellSize();
}
function screenToWorldX(sx) { return ((sx - state.panX) / cellSize() + 14) * 64; }
function screenToWorldY(sy) {
  return (GRID_TOP_REGION_Y - (sy - state.panY) / cellSize()) * 64;
}

function drawTiles() {
  if (!tiles.template || !tiles.version) return;
  composeBudget = PLANE_COMPOSE_BUDGET;
  const z = tileZoom(), span = tileSpan(z);
  const size = (span / 64) * cellSize();
  /* One pixel of overlap. Adjacent tiles land on fractional pixels at most
   * zooms, and rounding each independently leaves hairlines between them. */
  const bleed = 1;

  const x0 = Math.floor(screenToWorldX(0) / span);
  const x1 = Math.floor(screenToWorldX(CANVAS.clientWidth) / span);
  // Screen y runs opposite world y, so the top of the screen is the high one.
  const y1 = Math.floor(screenToWorldY(0) / span);
  const y0 = Math.floor(screenToWorldY(CANVAS.clientHeight) / span);

  const smoothing = CTX.imageSmoothingEnabled;
  for (let x = x0; x <= x1; x++) {
    for (let y = y0; y <= y1; y++) {
      if (x < 0 || y < 0) continue;
      const dx = worldToScreenX(x * span);
      const dy = worldToScreenY((y + 1) * span);
      const image = composedTile(z, x, y);
      if (image) {
        CTX.imageSmoothingEnabled = smoothing;
        CTX.drawImage(image, dx, dy, size + bleed, size + bleed);
        continue;
      }
      /* Not there - yet, or at all. Draw the same ground from a coarser level
       * rather than leaving a hole. Smoothing is forced on: this is always a
       * magnification, and blurry reads as "lower resolution" where blocky
       * reads as a rendering fault. */
      const coarse = tileAncestor(z, x, y);
      if (!coarse) continue;
      CTX.imageSmoothingEnabled = true;
      CTX.drawImage(
        coarse.image,
        coarse.sx, coarse.sy, coarse.size, coarse.size,
        dx, dy, size + bleed, size + bleed,
      );
    }
  }
  CTX.imageSmoothingEnabled = smoothing;
}

function onScreen(x, y, size) {
  return !(x > CANVAS.clientWidth || y > CANVAS.clientHeight || x + size < 0 || y + size < 0);
}

/* **The world drawn bright is the *compared* map's, not the base's.** A
 * comparison asks "what does A become if I take B", so the state you are
 * looking at has to be B's: a chunk B does not hold is locked *there*, and
 * leaving it bright because A held it draws a world neither map is in. So a
 * removed cell is washed like any other locked square and then tinted red on
 * top - present in the picture as something you would lose, absent from the
 * world the picture is of. The hull agrees: `build_view` traces it around
 * everything that is not removed, which is exactly B's set. */
function drawLockedWash() {
  const { grid_columns: cols, grid_rows: rows } = state.view.geometry;
  const size = cellSize();
  /* **Iterate what is on screen, not the whole grid.** The grid is 53x180 =
   * 9,540 cells now that underground is on it, against 1,632 when it was the
   * surface alone, and all but a handful are off screen at any time. */
  const [left, top] = toScreen(0, 0);
  const x0 = Math.max(0, Math.floor(-left / size));
  const x1 = Math.min(cols - 1, Math.ceil((CANVAS.clientWidth - left) / size));
  const y0 = Math.max(0, Math.floor(-top / size));
  const y1 = Math.min(rows - 1, Math.ceil((CANVAS.clientHeight - top) / size));

  CTX.fillStyle = LOCKED_WASH;
  for (let gx = x0; gx <= x1; gx++) {
    for (let gy = y0; gy <= y1; gy++) {
      const cell = state.cells.get(gx + "," + gy);
      if (cell && cell.state !== "removed") continue;
      const [x, y] = toScreen(gx, gy);
      CTX.fillRect(x, y, size, size);
    }
  }
}

/* The chunk grid, over locked and unlocked alike. Without it the map is a
 * continuous painting and the unit the whole game is played in is invisible
 * except where the hull happens to run.
 *
 * Drawn as two sets of full-length lines rather than a rect per cell: 48+34
 * strokes instead of 1,632, and no double-drawn shared edges to make some
 * lines twice as dark as others. Skipped entirely once a chunk is small
 * enough that the grid would be denser than the map underneath it. */
function drawGrid() {
  const size = cellSize();
  if (size < 14) return;
  const { grid_columns: cols, grid_rows: rows } = state.view.geometry;
  const [left, top] = toScreen(0, 0);
  const right = left + cols * size, bottom = top + rows * size;

  CTX.beginPath();
  for (let gx = 0; gx <= cols; gx++) {
    const x = Math.round(left + gx * size) + 0.5;
    if (x < 0 || x > CANVAS.clientWidth) continue;
    CTX.moveTo(x, Math.max(top, 0));
    CTX.lineTo(x, Math.min(bottom, CANVAS.clientHeight));
  }
  for (let gy = 0; gy <= rows; gy++) {
    const y = Math.round(top + gy * size) + 0.5;
    if (y < 0 || y > CANVAS.clientHeight) continue;
    CTX.moveTo(Math.max(left, 0), y);
    CTX.lineTo(Math.min(right, CANVAS.clientWidth), y);
  }
  CTX.strokeStyle = GRID_STROKE;
  CTX.lineWidth = 1;
  CTX.stroke();
}

function drawStates() {
  const size = cellSize();
  for (const cell of state.view.cells) {
    /* A plain unlocked chunk gets no fill at all, as upstream does it, so the
     * map shows through at full brightness and the wash is what reads as
     * "locked". */
    if (cell.state === "unlocked") continue;
    CTX.fillStyle = cell.state === "added" ? ADDED_FILL : REMOVED_FILL;
    const [x, y] = toScreen(cell.grid_x, cell.grid_y);
    CTX.fillRect(x, y, size, size);
  }
}

function drawMasks() {
  if (!state.showMasks) return;
  const size = cellSize();
  const inset = Math.max(1, Math.min(3, size / 40));
  for (const chunkId of maskTargets()) {
    const at = chunkToGrid(chunkId);
    if (!at) continue;
    const [x, y] = toScreen(at[0], at[1]);
    for (const [section, reachable] of Object.entries(state.sections[chunkId])) {
      const colours = reachable ? SECTION_REACHED : SECTION_LOCKED;
      /* An unsplit chunk is one section and that section is the square, so it
       * is filled directly. Same fill and same edge as a mask gets, because
       * the point of drawing it at all is that "not divided" should look like
       * one section rather than like missing data. */
      if (section === WHOLE_CHUNK) {
        CTX.fillStyle = colours.fill;
        CTX.fillRect(x, y, size, size);
        CTX.strokeStyle = colours.edge;
        CTX.lineWidth = inset;
        CTX.strokeRect(x + inset / 2, y + inset / 2, size - inset, size - inset);
        continue;
      }
      const tinted = maskFor(chunkId, section, reachable);
      if (tinted) CTX.drawImage(tinted, x, y, size, size);
    }
  }
}

/* **Which section a row in the Chunk tab is talking about, drawn where it
 * is.** The panel can say "Section 3" all it likes; the question a person
 * actually has is *which part of the square*, and the answer is a shape. So
 * hovering a row paints that section - green where you can reach it, red
 * where you cannot, the same two colours the Sections toggle uses so the
 * hover is a preview of that layer rather than a third vocabulary.
 *
 * Drawn whether or not the toggle is on: the hover is a question about one
 * section, and answering it should not need a mode turned on first. */
function drawHoverSection() {
  const hover = state.hoverSection;
  if (!hover) return;
  const at = chunkToGrid(hover.chunk);
  if (!at) return;
  const size = cellSize();
  const [x, y] = toScreen(at[0], at[1]);
  const inset = Math.max(1, Math.min(3, size / 40));
  for (const section of hover.sections) {
    const reachable = hover.reachable;
    const colours = reachable ? SECTION_REACHED : SECTION_LOCKED;
    /* **A chunk with one section has no mask, and that is not a miss.**
     * Upstream draws an overlay only where a square is *divided*; an undivided
     * one is the square, which is the same `WHOLE_CHUNK` case `drawMasks`
     * already has. Asking for `12339-0.png` gets an honest 404 and would leave
     * the hover silently drawing nothing on most of the map. */
    if (section === WHOLE_CHUNK || hover.whole) {
      CTX.fillStyle = colours.fill;
      CTX.fillRect(x, y, size, size);
      CTX.strokeStyle = colours.edge;
      CTX.lineWidth = inset;
      CTX.strokeRect(x + inset / 2, y + inset / 2, size - inset, size - inset);
      continue;
    }
    const tinted = maskFor(hover.chunk, section, reachable);
    if (tinted) CTX.drawImage(tinted, x, y, size, size);
  }
}

function drawFound() {
  if (!state.found.size) return;
  const size = cellSize();
  CTX.fillStyle = FOUND_FILL;
  for (const chunkId of state.found) {
    const at = chunkToGrid(chunkId);
    if (!at) continue;
    const [x, y] = toScreen(at[0], at[1]);
    if (onScreen(x, y, size)) CTX.fillRect(x, y, size, size);
  }
}

/* The one thing this interface is for that a terminal cannot do: the chunks
 * you could roll next, drawn where they are, carrying the number the app's own
 * canvas gives them. The decision the game asks you to make becomes a picture. */
/* **What Commit would add**, drawn without asking the server anything. Above
 * the candidates it overlaps and below the area labels, which have to stay
 * legible over every layer. */
function drawPending() {
  if (!state.edits.unlocked.size) return;
  const size = cellSize();
  CTX.lineWidth = Math.max(1, 1.5 * state.zoom);
  for (const chunkId of state.edits.unlocked) {
    const at = chunkToGrid(chunkId);
    if (!at) continue;
    const [x, y] = toScreen(at[0], at[1]);
    if (!onScreen(x, y, size)) continue;
    CTX.fillStyle = PENDING_FILL;
    CTX.fillRect(x, y, size, size);
    CTX.strokeStyle = PENDING_STROKE;
    CTX.setLineDash([4, 3]);
    CTX.strokeRect(x + 0.5, y + 0.5, size - 1, size - 1);
    CTX.setLineDash([]);
  }
}

function drawCandidates() {
  if (!state.showCandidates || !state.candidates.size) return;
  const size = cellSize();
  CTX.lineWidth = Math.max(1, 1.5 * state.zoom);
  CTX.textAlign = "center";
  CTX.textBaseline = "middle";
  CTX.font = `600 ${Math.round(size * 0.42)}px ui-monospace, Menlo, monospace`;

  for (const [chunkId, info] of state.candidates) {
    const at = chunkToGrid(chunkId);
    if (!at) continue;
    const [x, y] = toScreen(at[0], at[1]);
    if (!onScreen(x, y, size)) continue;
    CTX.fillStyle = CANDIDATE_FILL;
    CTX.fillRect(x, y, size, size);
    CTX.strokeStyle = CANDIDATE_STROKE;
    CTX.strokeRect(x + 0.5, y + 0.5, size - 1, size - 1);
    /* Below about 26px the glyph is unreadable and only muddies the square. */
    if (size >= 26) {
      CTX.fillStyle = "#04121c";
      CTX.fillText(info.number, x + size / 2 + 1, y + size / 2 + 1);
      CTX.fillStyle = "#eaf6ff";
      CTX.fillText(info.number, x + size / 2, y + size / 2);
    }
  }
}

/* **Names the dungeons.** Underground is 719 squares of unlabelled rooms
 * without this - the tiles show you a boss arena and nothing says which. 502
 * of them are part of a named area, and the name comes from the export rather
 * than from any match: a numbered region carrying `Name` *is* where that place
 * is. See `chunkinfo.area_names`.
 *
 * **One label per area, anchored to its top-left square that is on screen.**
 * Not one per square: `Hallowed Sepulchre` is 24 regions and writing its name
 * on each is a wall of repeated text. Not one per area *globally* either -
 * that anchor is often scrolled off, and a dungeon you are looking straight at
 * with its name somewhere else is worse than either. Re-anchoring per frame
 * costs a sort of what is visible and means every area you can see is named
 * exactly once. */
function drawAreas() {
  const size = cellSize();
  if (size < AREA_LABEL_MIN_CELL) return;

  const anchor = new Map();
  for (const [chunkId, area] of Object.entries(state.areas)) {
    const at = chunkToGrid(chunkId);
    if (!at) continue;
    const [x, y] = toScreen(at[0], at[1]);
    if (!onScreen(x, y, size)) continue;
    const held = anchor.get(area);
    /* Reading order: topmost row wins, then leftmost column. */
    if (!held || at[1] < held[1] || (at[1] === held[1] && at[0] < held[0])) {
      anchor.set(area, at);
    }
  }
  if (!anchor.size) return;

  CTX.textAlign = "left";
  CTX.textBaseline = "top";
  CTX.font = `600 ${Math.round(Math.min(15, size * 0.16))}px system-ui, sans-serif`;
  CTX.lineWidth = 3;
  CTX.lineJoin = "round";
  for (const [area, at] of anchor) {
    const [x, y] = toScreen(at[0], at[1]);
    /* Stroked underneath, so a name stays readable over both the bright side
     * of an unlocked square and the wash over a locked one. */
    CTX.strokeStyle = "rgba(4, 8, 12, .85)";
    CTX.strokeText(area, x + 4, y + 3);
    CTX.fillStyle = "#e8eef6";
    CTX.fillText(area, x + 4, y + 3);
  }
}

function drawHull() {
  /* One path, one stroke: the joins stay clean where edges meet at a corner,
   * and there is no per-cell state churn. */
  const size = cellSize();
  CTX.beginPath();
  for (const cell of state.view.cells) {
    if (!cell.edges) continue;
    const [x, y] = toScreen(cell.grid_x, cell.grid_y);
    if (cell.edges & TOP) { CTX.moveTo(x, y); CTX.lineTo(x + size, y); }
    if (cell.edges & BOTTOM) { CTX.moveTo(x, y + size); CTX.lineTo(x + size, y + size); }
    if (cell.edges & LEFT) { CTX.moveTo(x, y); CTX.lineTo(x, y + size); }
    if (cell.edges & RIGHT) { CTX.moveTo(x + size, y); CTX.lineTo(x + size, y + size); }
  }
  CTX.strokeStyle = HULL_STROKE;
  /* Upstream's fixed 3 vanishes at 0.2 and looks thin at 3.5. */
  CTX.lineWidth = Math.max(2, 2.5 * state.zoom);
  CTX.lineCap = "square";
  CTX.stroke();
}

/* A wash under the cursor, so the square you are about to click is the square
 * you think you are about to click. Deliberately fainter than every other
 * fill: it follows the mouse, and anything stronger would flicker. */
function drawHovered() {
  if (!state.hovered || state.hovered === state.selected) return;
  const at = chunkToGrid(state.hovered);
  if (!at) return;
  const size = cellSize();
  const [x, y] = toScreen(at[0], at[1]);
  CTX.fillStyle = HOVER_FILL;
  CTX.fillRect(x, y, size, size);
  CTX.strokeStyle = "rgba(255,255,255,.45)";
  CTX.lineWidth = 1;
  CTX.strokeRect(x + 0.5, y + 0.5, size - 1, size - 1);
}

function drawSelected() {
  if (!state.selected || !state.view) return;
  const at = chunkToGrid(state.selected);
  if (!at) return;
  const size = cellSize();
  const [x, y] = toScreen(at[0], at[1]);
  CTX.strokeStyle = "#ffffff";
  CTX.lineWidth = Math.max(2, 2 * state.zoom);
  CTX.setLineDash([Math.max(4, size / 12), Math.max(3, size / 16)]);
  CTX.strokeRect(x, y, size, size);
  CTX.setLineDash([]);
}

function draw() {
  state.needsDraw = false;
  CTX.clearRect(0, 0, CANVAS.clientWidth, CANVAS.clientHeight);
  if (!state.view) return;
  /* Smoothing is right in one direction and wrong in the other. The map is 2
   * pixels per game tile, so magnifying it past 1:1 with smoothing on turns
   * hand-drawn detail to mush - but *minifying* it with smoothing off aliases
   * every coastline into a staircase that crawls as you pan. So it follows the
   * zoom, which is the only thing that decides which of the two is happening.
   * Same call covers the section masks, which are almost always minified. */
  CTX.imageSmoothingEnabled = state.zoom < 1;
  for (const layer of LAYERS) layer();
}

function invalidate() {
  if (state.needsDraw) return;
  state.needsDraw = true;
  requestAnimationFrame(draw);
}

/* ---- viewport ---------------------------------------------------------- */

function resize() {
  /* DEVIATION from upstream: size the backing store by devicePixelRatio and
   * scale the context once, so every coordinate stays in CSS pixels and the
   * map is not blurry on a HiDPI screen. */
  const dpr = window.devicePixelRatio || 1;
  CANVAS.width = Math.round(CANVAS.clientWidth * dpr);
  CANVAS.height = Math.round(CANVAS.clientHeight * dpr);
  CTX.setTransform(dpr, 0, 0, dpr, 0, 0);
  invalidate();
}

function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }

/* How much of the right edge the panel is actually taking. A put-away panel
 * still leaves its sliver behind, and the camera has to know: framing to a
 * width that is 14px wider than the space available puts the edge of the world
 * under the handle. Read from the stylesheet so the two cannot drift. */
function panelWidth() {
  if (!el.panel.classList.contains("hidden")) return el.panel.offsetWidth;
  return parseFloat(getComputedStyle(document.documentElement)
    .getPropertyValue("--sliver")) || 0;
}

function barHeight() {
  return document.querySelector(".bar").offsetHeight;
}

function fitToCells() {
  if (!state.view) return;
  const cells = state.view.cells;
  const cell = state.view.geometry.pixels_per_chunk;
  if (!cells.length) {
    const { grid_columns: cols, grid_rows: rows } = state.view.geometry;
    return fitBox(0, 0, cols, rows, cell);
  }
  const xs = cells.map((c) => c.grid_x), ys = cells.map((c) => c.grid_y);
  fitBox(Math.min(...xs), Math.min(...ys), Math.max(...xs) + 1, Math.max(...ys) + 1, cell);
}

/* Where the camera has to be for a grid rectangle to fill the space the bar
 * and the panel are not covering. Split out from `fitBox` so the same
 * arithmetic can be glided to rather than jumped to. */
function boxCamera(minX, minY, maxX, maxY, cell) {
  const availW = CANVAS.clientWidth - panelWidth() - 80;
  const availH = CANVAS.clientHeight - 100;
  const zoom = clamp(
    Math.min(availW / ((maxX - minX) * cell), availH / ((maxY - minY) * cell)),
    MIN_ZOOM, MAX_ZOOM,
  );
  const size = zoom * cell;
  return {
    panX: (availW - (maxX - minX) * size) / 2 + 40 - minX * size,
    panY: (availH - (maxY - minY) * size) / 2 + 60 - minY * size,
    zoom,
  };
}

function fitBox(minX, minY, maxX, maxY, cell) {
  stopGlide();
  Object.assign(state, boxCamera(minX, minY, maxX, maxY, cell));
  invalidate();
}

/* Frame every one of `chunkIds`, gliding rather than jumping.
 *
 * **A single chunk is not a box worth fitting.** Its bounding rectangle is one
 * cell, so fitting it means slamming to MAX_ZOOM - which loses every landmark
 * around the thing you were looking for. One chunk keeps the zoom you were at
 * and only centres; two or more get the rectangle that holds them all. */
function frameChunks(chunkIds) {
  if (!state.view) return false;
  const placed = chunkIds.map(chunkToGrid).filter(Boolean);
  if (!placed.length) return false;
  if (placed.length === 1) {
    focusChunk(gridToChunk(placed[0][0], placed[0][1]));
    return true;
  }
  const xs = placed.map((p) => p[0]), ys = placed.map((p) => p[1]);
  glideTo(boxCamera(
    Math.min(...xs), Math.min(...ys),
    Math.max(...xs) + 1, Math.max(...ys) + 1,
    state.view.geometry.pixels_per_chunk,
  ));
  return true;
}

function zoomAt(sx, sy, direction) {
  /* DEVIATION from upstream: clamp first, then derive the applied factor from
   * the clamped result. Upstream anchors on the requested step and skips the
   * update entirely at a limit, which lets the point under the cursor drift on
   * every wheel tick once you are pinned at either end. */
  stopGlide();
  const next = clamp(state.zoom * (1 + direction * ZOOM_STEP), MIN_ZOOM, MAX_ZOOM);
  const applied = next / state.zoom - 1;
  state.panX -= (sx - state.panX) * applied;
  state.panY -= (sy - state.panY) * applied;
  state.zoom = next;
  invalidate();
}

/* ---- input ------------------------------------------------------------- */

let dragging = null;
let movedWhileDown = 0;

CANVAS.addEventListener("pointerdown", (e) => {
  /* DEVIATION from upstream: Pointer Events plus capture, so trackpads and
   * touch work and a drag released outside the canvas still ends. */
  stopGlide();
  dragging = { id: e.pointerId, x: e.clientX, y: e.clientY };
  movedWhileDown = 0;
  capture(true, e.pointerId);
  CANVAS.classList.add("dragging");
});

/* **Capture is an optimisation, not a precondition.** `setPointerCapture`
 * throws `NotFoundError` for a pointer the browser does not consider active -
 * which a synthetic event is - and an uncaught throw here took the *click*
 * down with it, because releasing runs before selecting. Panning still works
 * without capture; only a drag leaving the canvas degrades. */
function capture(on, pointerId) {
  try {
    if (on) CANVAS.setPointerCapture(pointerId);
    else CANVAS.releasePointerCapture(pointerId);
  } catch { /* not capturable; drags stay inside the canvas */ }
}

CANVAS.addEventListener("pointermove", (e) => {
  if (dragging && dragging.id === e.pointerId) {
    movedWhileDown += Math.abs(e.clientX - dragging.x) + Math.abs(e.clientY - dragging.y);
    state.panX += e.clientX - dragging.x;
    state.panY += e.clientY - dragging.y;
    dragging.x = e.clientX;
    dragging.y = e.clientY;
    invalidate();
  }
  showHovered(e.clientX, e.clientY);
});

CANVAS.addEventListener("pointerleave", () => {
  state.hovered = null;
  el.hover.textContent = "";
  invalidate();
});

function endDrag(e) {
  if (!dragging || dragging.id !== e.pointerId) return;
  dragging = null;
  capture(false, e.pointerId);
  CANVAS.classList.remove("dragging");
}

CANVAS.addEventListener("pointerup", (e) => {
  /* A click is a press that did not travel. Without this a drag that ends over
   * a chunk selects it, which is maddening. */
  const wasDrag = movedWhileDown > 4;
  endDrag(e);
  if (!wasDrag && state.view) selectChunk(hoveredChunk(e.clientX, e.clientY));
});
CANVAS.addEventListener("pointercancel", endDrag);

CANVAS.addEventListener("wheel", (e) => {
  e.preventDefault();
  zoomAt(e.clientX, e.clientY, e.deltaY < 0 ? 1 : -1);
}, { passive: false });

window.addEventListener("resize", () => { resize(); rememberWindow(); });

document.addEventListener("keydown", (e) => {
  if (e.target.matches("input, select, textarea")) return;
  if (e.key === "Escape") { closeOverlay(); return selectChunk(null); }
  if (e.key === "f" || e.key === "F") {
    /* Focus: whatever is under the cursor, or failing that whatever is
     * selected - so it works both while pointing and after clicking. */
    const chunkId = state.hovered || state.selected;
    if (chunkId) focusChunk(chunkId);
  } else if (e.key === "c") el.candidates.click();
  else if (e.key === "s") el.masks.click();
  else if (e.key === "p") el["panel-pin"].click();
  else if (e.key === "Home") el.fit.click();
  /* Only while a run is on screen, so the arrows stay free for whatever the
   * map wants them for on every other kind of map. */
  else if (e.key === "ArrowLeft" && state.timeline) setStep((state.step ?? 0) - 1);
  else if (e.key === "ArrowRight" && state.timeline) setStep((state.step ?? 0) + 1);
});

function hoveredChunk(sx, sy) {
  const size = cellSize();
  const gx = Math.floor((sx - state.panX) / size);
  const gy = Math.floor((sy - state.panY) / size);
  const { grid_columns: cols, grid_rows: rows } = state.view.geometry;
  if (gx < 0 || gy < 0 || gx >= cols || gy >= rows) return null;
  return gridToChunk(gx, gy);
}

function showHovered(sx, sy) {
  if (!state.view) return;
  const chunkId = hoveredChunk(sx, sy);
  if (chunkId !== state.hovered) { state.hovered = chunkId; invalidate(); }
  if (!chunkId) { el.hover.textContent = ""; return; }
  const at = chunkToGrid(chunkId);
  const cell = at && state.cells.get(at[0] + "," + at[1]);
  const candidate = state.candidates.get(chunkId);
  /* Name and id together - `chunkLabel` puts the name first, because that is
   * what you are looking for, and keeps the id, which is what you paste into
   * `fray unlock`. */
  const bits = [chunkLabel(chunkId)];
  if (cell) bits.push(cell.state);
  if (candidate) bits.push("#" + candidate.number);
  el.hover.textContent = bits.join("  ");
}

/* ---- lists that are too long to print ------------------------------------ */

/* **A truncated list is a control, not a caption.** "17 more" was a dead grey
 * line telling you what you were not being shown and offering no way to see
 * it; the only route to the rest was `--export-json`.
 *
 * `expanded` holds the keys currently opened. Collapsing is a second press,
 * not something that happens when the region scrolls out of view: a list that
 * folds itself while you are reading further down moves the thing you were
 * looking at, and a control that undoes itself when you look away is one you
 * stop trusting.
 *
 * The set survives a re-render - which is what makes the expansion *stay* open
 * while you change a chip - and is cleared when the underlying data is
 * refetched, because those keys are then about a list that no longer exists. */
const expanded = new Set();

function clearExpansions(prefix) {
  for (const key of [...expanded]) if (key.startsWith(prefix)) expanded.delete(key);
}

/* Render at most `limit` rows, plus the control that reveals the rest. */
function withMore(rows, key, limit, render) {
  const open = expanded.has(key);
  const shown = open ? rows : rows.slice(0, limit);
  let out = shown.map(render).join("");
  if (rows.length <= limit) return out;
  const hidden = rows.length - limit;
  out += tmpl`<li class="more"><button class="more-toggle" data-more="${key}"
      aria-expanded="${open}">${raw(icon(open ? "up" : "down").__raw)}
      <span>${open ? "Show fewer" : "Show " + hidden + " more"}</span></button></li>`;
  return out;
}

/* Who redraws when one of their lists is opened, keyed by the prefix their
 * keys carry. A pane registers itself as it renders, which keeps the knowledge
 * of *how* to redraw next to the code that knows *what* to draw. */
const moreOwners = new Map();

function ownsMore(prefix, redraw) { moreOwners.set(prefix, redraw); }

/* Delegated, so a list gets the behaviour by emitting the markup and never has
 * to remember to wire anything up. */
document.addEventListener("click", (event) => {
  const toggle = event.target.closest("[data-more]");
  if (!toggle) return;
  const key = toggle.dataset.more;
  if (expanded.has(key)) expanded.delete(key); else expanded.add(key);
  moreOwners.get(key.split(":")[0])?.();
});

/* ---- panel plumbing ---------------------------------------------------- */

/* Escapes every interpolation unless it is wrapped in `raw`. Chunk nicknames
 * and task names come from an export we do not control and land in innerHTML,
 * so this is not optional. */
function tmpl(strings, ...values) {
  return strings.reduce((out, chunk, i) => {
    const value = values[i - 1];
    if (value && value.__raw !== undefined) return out + value.__raw + chunk;
    const safe = String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    return out + safe + chunk;
  });
}

function raw(value) { return { __raw: String(value) }; }

/* **`raw` is for element content and never for an attribute.** Inside
 * `data-tip="${...}"` it splices unescaped `"` straight through the closing
 * quote, and the markup after it lands on screen as text - which is exactly
 * what `<span class="sub">` in a tooltip did. Tooltip bodies are therefore
 * ordinary interpolations: `tmpl` escapes the quotes going in, and the
 * browser decodes them again when `dataset.tip` is read, so the HTML arrives
 * intact without ever having been able to escape its attribute. */

/* Task and challenge names are markup-bearing keys: the raw `~|...|~` form is
 * what everything is keyed by, and stripping it is display-only. Mirrors
 * `challenges.strip_task_markup`, and applies *only* to names and details -
 * other branches of the export use `~` and `|` for real. */
function plain(text) { return String(text == null ? "" : text).replace(/~\|/g, "").replace(/\|~/g, ""); }

function icon(name) { return raw(`<svg class="icon" viewBox="0 0 24 24"><use href="#i-${name}"/></svg>`); }

/* Library vocabularies - `estimate.BUCKETS`, `search.TYPES` - are lower-case
 * because that is how `fray` prints them, and they stay that way as keys.
 * Only the label is capitalised, so the panel does not set "activities" next
 * to "Longest single items" and read as two different interfaces. */
function label(text) {
  const s = String(text || "");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function hours(value) { return Number(value || 0).toFixed(value >= 100 ? 0 : 1) + "h"; }

function bytes(value) {
  if (!value) return "—";
  const units = ["B", "KiB", "MiB", "GiB"];
  let n = value, i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return (i ? n.toFixed(1) : String(n)) + " " + units[i];
}

/* The same buckets `summary.format_age` uses, so one install is described the
 * same way in the terminal and on the page. */
function ago(iso) {
  if (!iso) return "unknown";
  const at = new Date(iso);
  if (Number.isNaN(at.valueOf())) return "unknown";
  const seconds = Math.max(0, Math.round((Date.now() - at.getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function when(iso) {
  if (!iso) return "unknown";
  const at = new Date(iso);
  return Number.isNaN(at.valueOf()) ? iso : at.toLocaleString();
}

function showTab(name) {
  state.tab = name;
  for (const b of el.tabs.querySelectorAll("button")) {
    b.classList.toggle("on", b.dataset.tab === name);
  }
  for (const p of document.querySelectorAll(".pane")) {
    p.classList.toggle("on", p.dataset.pane === name);
  }
  if (el.panel.classList.contains("hidden")) el["panel-pin"].click();
  if (name === "tasks") loadTasks();
  if (name === "estimate") loadEstimate();
  if (name === "maps") loadMapsPane();
}

el.tabs.addEventListener("click", (e) => {
  const button = e.target.closest("button[data-tab]");
  if (button) showTab(button.dataset.tab);
});

el["panel-pin"].addEventListener("click", () => {
  const hidden = el.panel.classList.toggle("hidden");
  /* Everything anchored to the right of the *map* reads `--rail`, so the
   * progress card and the attribution slide out with the panel instead of
   * hanging over the gap it left. */
  document.body.classList.toggle("no-panel", hidden);
  /* **The arrow points where the press will send it**, which is the whole of
   * what a handle has to say. `aria-expanded` says the same thing to a reader
   * that cannot see which way a chevron faces. */
  el["panel-pin-icon"].setAttribute("href", hidden ? "#i-ll" : "#i-rr");
  el["panel-pin"].setAttribute("aria-expanded", hidden ? "false" : "true");
  el["panel-pin"].dataset.tip = hidden
    ? "<b>Show the panel</b><span class='sub'>Tasks, chunk contents, search, estimate and maps.</span><span class='hint'>P</span>"
    : "<b>Hide the panel</b><span class='sub'>Gives the map the whole window; a sliver stays to bring it back.</span><span class='hint'>P</span>";
});

function toast(message) {
  el.toast.textContent = message;
  el.toast.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { el.toast.hidden = true; }, 2400);
}

/* One dialog, reused. An answer you asked a question to get needs somewhere
 * to live that is not "instead of the thing you were reading". */
function openOverlay(title, html, actions) {
  el["overlay-title"].textContent = title;
  el["overlay-body"].innerHTML = html;
  el["overlay-actions"].innerHTML = actions || "";
  el["overlay-actions"].hidden = !actions;
  el.overlay.hidden = false;
}

function closeOverlay() {
  el.overlay.hidden = true;
  /* A dialog that was asking a question and is dismissed has been answered
   * "no". Anything awaiting it has to hear that rather than wait forever. */
  if (closeOverlay.pending) { const answer = closeOverlay.pending; closeOverlay.pending = null; answer(false); }
}

/* **Ask before destroying something on disk.** `maps rm` is not undoable: a
 * simulated map can be rebuilt from its seed but only if you still know it,
 * and a batch of forty is forty directories. The dialog names what goes
 * rather than asking "are you sure", because the count *is* the question. */
function confirmAction(title, body, verb, { danger = true } = {}) {
  return new Promise((resolve) => {
    openOverlay(title, body, tmpl`<button id="confirm-no" type="button">Cancel</button>
      <button id="confirm-yes" class="${danger ? "danger" : ""}" type="button">${verb}</button>`);
    closeOverlay.pending = resolve;
    const answer = (value) => { closeOverlay.pending = null; el.overlay.hidden = true; resolve(value); };
    document.getElementById("confirm-no").onclick = () => answer(false);
    const yes = document.getElementById("confirm-yes");
    yes.onclick = () => answer(true);
    yes.focus();
  });
}

el["do-commit"].addEventListener("click", askCommit);
el["compare-start"].addEventListener("click", askCompare);
el["exit-mode"].addEventListener("click", exitMode);

el["overlay-close"].addEventListener("click", closeOverlay);
el.overlay.addEventListener("click", (e) => { if (e.target === el.overlay) closeOverlay(); });

/* Tooltips are delegated and read `data-tip`, so any row can have one by
 * carrying an attribute rather than by wiring two listeners. */
document.addEventListener("mouseover", (e) => {
  const host = e.target.closest("[data-tip]");
  if (!host) return;
  el.tip.innerHTML = host.dataset.tip;
  el.tip.hidden = false;
  moveTip(e);
});

document.addEventListener("mousemove", (e) => { if (!el.tip.hidden) moveTip(e); });

document.addEventListener("mouseout", (e) => {
  if (e.target.closest("[data-tip]")) el.tip.hidden = true;
});

function moveTip(e) {
  /* Flip to the other side of the pointer near an edge, rather than letting
   * the tip hang off the window where the last few words are unreadable. */
  const box = el.tip.getBoundingClientRect();
  const x = e.clientX + 14 + box.width > window.innerWidth
    ? e.clientX - 14 - box.width : e.clientX + 14;
  const y = e.clientY + 16 + box.height > window.innerHeight
    ? e.clientY - 12 - box.height : e.clientY + 16;
  el.tip.style.left = Math.max(4, x) + "px";
  el.tip.style.top = Math.max(4, y) + "px";
}

/* ---- data -------------------------------------------------------------- */

async function getJSON(path, options) {
  const response = await fetch(path, options);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || response.statusText);
  return payload;
}

async function postJSON(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const parsed = await response.json();
  if (!response.ok) throw new Error(parsed.error || response.statusText);
  return parsed;
}

/* **Four modes, and the exclusivity rules are theirs rather than the
 * controls'.**
 *
 * The page had three of these already, encoded as mutually exclusive
 * *conditions*: a compare box with something in it was Diff, a non-null step
 * was Timeline, neither was Browse. That works right up to the point where
 * something has to be explained - which is why `comparingNotice` existed, to
 * apologise for an interaction the interface refused to name.
 *
 * Naming them buys two things. `mapQuery` becomes a switch on what the page
 * *is* instead of an if-ladder over which control happens to be set, and the
 * ribbon can say so in colour: a state you can see is one you do not have to
 * infer from the fact that a button went grey.
 *
 * **`timeline` is the mode a simulation is seen in, and the only one.** A run
 * is fifty worlds rather than one, so browsing it as though it were a map is
 * the confusion the split exists to remove - choosing one out of the picker
 * *is* choosing to replay it, and the ribbon says so rather than a dialog
 * asking you to confirm the choice you just made. */
const MODES = {
  browse:   { label: "Browse", exit: null },
  edit:     { label: "Edit", exit: "Discard edits" },
  diff:     { label: "Diff", exit: "Exit diff view" },
  timeline: { label: "Timeline", exit: "Exit timeline" },
};

/* What a map is, from the listing rather than from a second request. Unknown
 * ids answer `fetched`, which is the shape with no history - the conservative
 * reading, since it never forces a mode on the strength of a guess. */
function kindOf(mapId) {
  const row = state.maps.find((m) => m.map_id === mapId);
  return row ? row.kind : "fetched";
}

/* A simulation is a sequence of worlds; everything else is one world. */
function modeForMap(mapId) {
  return kindOf(mapId) === "simulated" ? "timeline" : "browse";
}

/* **The single transition point.** Entry and exit work belongs here rather
 * than at each caller, or the third caller forgets one - which is how a step
 * belonging to one run used to survive into another. */
function setMode(next) {
  if (!MODES[next]) return state.mode;
  if (next !== "timeline") { state.step = null; state.timeline = null; }
  if (next !== "diff") setCompare("");
  state.mode = next;
  renderRibbon();
  return state.mode;
}

/* Mode in colour, map in words. The tint is a CSS decision keyed off the
 * attribute - the palette stays in the stylesheet rather than gaining a
 * fourth copy here beside the canvas constants and the legend's literals. */
function renderRibbon() {
  const mode = state.mode;
  el.ribbon.dataset.mode = mode;
  el["ribbon-mode"].textContent = MODES[mode].label;
  el["ribbon-map"].textContent = state.map || "no map";
  for (const id of ["ribbon-vs", "compare", "breakdown"]) el[id].hidden = mode !== "diff";
  const count = editCount();
  el["ribbon-edits"].hidden = mode !== "edit";
  el["do-commit"].hidden = mode !== "edit";
  el["do-commit"].disabled = count === 0;
  if (mode === "edit") {
    el["ribbon-edits"].textContent = count === 0
      ? "nothing changed yet" : count + " unsaved change" + (count === 1 ? "" : "s");
  }
  /* **Comparing from Timeline would show a simulation outside timeline
   * mode**, which is the one thing the modes exist to prevent - so the door is
   * not there rather than there and grey. A disabled control is a promise that
   * the thing is possible from here and you have not met its condition; this
   * one is possible from a *different* mode, which is a fact about the bar
   * rather than about the button. The way out stays Snapshot. */
  el["compare-start"].hidden = mode === "timeline";
  const exit = MODES[mode].exit;
  el["exit-mode"].hidden = !exit;
  if (exit) el["exit-mode"].textContent = exit;
}

/* Which map a computed one was made from. The listing carries it on the
 * *batch* rather than on each run, since every run of a batch rolled from the
 * same world - so a run asks its batch. */
function baseMapOf(mapId) {
  const row = state.maps.find((m) => m.map_id === mapId);
  if (row && row.base_map) return row.base_map;
  const batch = state.maps.find((m) => m.map_id === (mapId || "").split("/")[0]);
  return (batch && batch.base_map) || "";
}

/* **The guarded setter.** Choosing a simulation is choosing to replay it, and
 * that is a bigger move than picking a map - so it is asked about, and a
 * declined answer leaves the picker exactly where it was rather than half
 * way into a mode nobody agreed to. */
async function selectMap(id) {
  const previous = state.map;
  const wanted = modeForMap(id);
  /* **Pending edits belong to the map they were made on.** Carrying them to
   * another would commit a tick against a world that may not even hold the
   * task, which is a much worse thing to do quietly than to ask about. */
  if (state.mode === "edit" && id !== previous && editCount()) {
    const ok = await confirmAction("Discard " + editCount() + " unsaved change(s)?",
      tmpl`<p>They were made on <b>${previous}</b> and do not travel to another
        map. <b>Commit</b> writes them as a new map instead.</p>`, "Discard");
    if (!ok) { setMap(previous); return false; }
    clearEdits();
  }
  /* **Entering the timeline is not asked about, and the edit above is.** The
   * difference is who decided: picking a simulation out of the list is an
   * explicit choice of that map, and the mode follows from what the map *is*,
   * so a dialog asks you to confirm the thing you just did. Discarding edits
   * is the opposite - a side effect of a different action, on work the page
   * would otherwise throw away silently. The ribbon says which mode you are
   * in, which is the answer to "what just happened" that a prompt was
   * standing in for. */
  setMap(id);
  /* **A step index belongs to one run**, and one run is one map. Carried
   * across it rewinds the new map to a roll it never had, and the counts
   * quietly disagree with the slider. `setMode` cannot do this on its own:
   * run to run is a map change with no mode change at all. */
  if (state.map !== previous) { state.step = null; state.timeline = null; }
  setMode(wanted);
  return true;
}

/* How many changes are waiting. Both halves, because "3 unsaved" has to mean
 * three things whether they are ticks or chunks. */
function editCount() {
  let ticks = 0;
  for (const names of state.edits.ticked.values()) ticks += names.size;
  return ticks + state.edits.unlocked.size;
}

function clearEdits() {
  state.edits.unlocked.clear();
  state.edits.ticked.clear();
}

/* **The entry gesture is the edit itself.** A mode you have to arm before you
 * can do anything is a mode you forget to arm; asking on the first click is
 * one question at the moment it means something. Returns whether editing may
 * proceed, so a declined answer leaves the map untouched. */
async function ensureEditing() {
  if (state.mode === "edit") return true;
  if (state.mode !== "browse") {
    toast("Editing is a browse-mode thing — leave " + MODES[state.mode].label.toLowerCase() + " first");
    return false;
  }
  /* The promise differs by what you are editing, and saying the wrong one is
   * worse than saying nothing: a fetched map really is never touched, and an
   * edited one really is the thing being changed. */
  const ok = await confirmAction("Enter edit mode?",
    kindOf(state.map) === "edited"
      ? tmpl`<p>Ticks and unlocks are held in this page until you press
          <b>Commit</b>, which updates <b>${state.map}</b> in place. The map it
          was forked from is never touched, and <b>Save as a copy</b> is on the
          commit dialog if you would rather branch.</p>`
      : tmpl`<p>Ticks and unlocks are held in this page until you press
          <b>Commit</b>, which writes them as a new map under
          <code>cache/maps/edited/</code>. <b>${state.map}</b> is never touched.</p>`,
    "Enter edit mode", { danger: false });
  if (!ok) return false;
  setMode("edit");
  return true;
}

/* **Committing writes a map, so it asks for a name first** - the same shape as
 * `askUnlock`, and for the same reason: the default is the one thing you would
 * otherwise have to invent, and whatever name is claimed comes back either
 * way. */
/* **What to call the next edit, given what this one is called.**
 *
 * A cached map is upstream's and immutable; an edit forks it. What follows is
 * that editing is iterative - unlock a chunk, tick what it opened, unlock the
 * next - and each round has to be named. `<map>-edit` per round gives
 * `fray-edit-edit-edit`, which names the *number of rounds* and nothing you
 * would look for.
 *
 * So an edit of an edit reuses its own family name and lets `claim_batch`
 * number it: `fray-edit`, `fray-edit-2`, `fray-edit-3`. The trailing number is
 * stripped rather than incremented here, because the server is the only thing
 * that knows what is taken - suggesting `-4` when `-4` exists would be a name
 * the dialog promises and does not deliver. */
function defaultEditName(mapId) {
  const base = (mapId || DEFAULT_MAP_ID).replace(/\//g, "-");
  if (kindOf(mapId) === "edited") return base.replace(/-\d+$/, "");
  return base + "-edit";
}

/* **An edited map is edited; a fetched one forks.** Upstream's state is
 * immutable here, so the first change has to write somewhere new - but every
 * change after that is a change to *your* map, and minting `-2`, `-3`, `-4`
 * down the chunk you were planning is a new map per click rather than a map
 * you are working on. So Commit updates in place once the base is an edit,
 * and "Save as a copy" is the second button rather than the only one. */
function askCommit() {
  const count = editCount();
  if (!count) { toast("Nothing to commit"); return; }
  const editing = kindOf(state.map) === "edited";
  const suggested = defaultEditName(state.map);
  const ticks = count - state.edits.unlocked.size;
  const what = tmpl`${ticks} task${ticks === 1 ? "" : "s"} ticked off and
      ${state.edits.unlocked.size} chunk${state.edits.unlocked.size === 1 ? "" : "s"} unlocked`;
  openOverlay("Commit " + count + " change" + (count === 1 ? "" : "s"),
    (editing
      ? tmpl`<p>Updates <b>${state.map}</b> in place: ${what}. Its history keeps
          every chunk you have added by hand, and the map it was originally
          forked from is untouched.</p>`
      : tmpl`<p>Writes a new map holding everything <b>${state.map}</b> holds, with
          ${what}. Nothing existing is touched.</p>`)
      + tmpl`<div class="row" id="commit-as" ${raw(editing ? "hidden" : "")}>
        <input id="commit-name" type="text" value="${suggested}"
        aria-label="Name for the new map" spellcheck="false" autocomplete="off"
        data-tip="<b>Name for the new map</b><span class='sub'>A name already in use gains <code>-2</code>, <code>-3</code>, … rather than overwriting.</span>"></div>`,
    tmpl`<button id="commit-no" type="button">Cancel</button>`
      + (editing ? tmpl`<button id="commit-copy" type="button">Save as a copy</button>` : "")
      + tmpl`<button id="commit-yes" type="button">${editing ? "Update " + state.map : "Commit"}</button>`);

  const field = document.getElementById("commit-name");
  let replace = editing;
  const copy = document.getElementById("commit-copy");
  if (copy) {
    /* Revealing the name field *is* the choice, so the second press commits
     * rather than asking again - a button that only shows a box is a button
     * you have to press twice to do anything. */
    copy.onclick = () => {
      replace = false;
      document.getElementById("commit-as").hidden = false;
      document.getElementById("commit-yes").textContent = "Commit";
      field.focus();
      field.select();
    };
  }
  const go = () => {
    const name = replace ? state.map : (field.value.trim() || suggested);
    const ticked = {};
    for (const [category, names] of state.edits.ticked) ticked[category] = [...names];
    closeOverlay();
    runAction((replace ? "Update " : "Commit ") + name, "/api/commit",
      { map: state.map, name, replace, ticked, unlocked: [...state.edits.unlocked] },
      async (result) => {
        clearEdits();
        taskPanel = null;
        await loadMaps();
        if (result.open) openMap(result.open);
        syncBreakdown();
        await loadTimeline();
        await loadView({ refit: true });
        await loadCandidates();
        await loadSections();
        loadMapsPane();
      });
  };
  document.getElementById("commit-no").onclick = closeOverlay;
  document.getElementById("commit-yes").onclick = go;
  field.onkeydown = (event) => { if (event.key === "Enter") { event.preventDefault(); go(); } };
  field.focus();
  field.select();
}

/* **Anything that makes a map selects it, and the mode follows it in.** No
 * prompt, unlike `selectMap`: you just rolled this, so being asked whether you
 * meant to look at it is noise. Rolling produces a simulation, which means
 * timeline mode - going to Browse instead would put a run on screen outside
 * the one mode that is allowed to hold one. */
function openMap(id) {
  setMap(id);
  state.step = null;
  state.timeline = null;
  setMode(modeForMap(state.map));
}

/* **Entering Diff is choosing a second map**, so it asks for one rather than
 * dropping you into a mode with nothing to compare against. Any map may be on
 * the *compare* side, simulations included: the invariant is about the base -
 * what you are looking at and can act on - and the other side of a comparison
 * is neither. */
async function askCompare() {
  const options = mapOptions(state.maps.filter((m) => m.map_id !== state.map));
  openOverlay("Compare " + state.map + " with",
    tmpl`<p>Gains draw green and losses red, and the hull traces what
      <b>${state.map}</b> would become. Nothing is written.</p>
      <div class="row"><select id="compare-pick" class="pick" aria-label="Compare against">`
      + options + `</select></div>`,
    tmpl`<button id="compare-no" type="button">Cancel</button>
      <button id="compare-yes" type="button">Compare</button>`);
  const pick = document.getElementById("compare-pick");
  document.getElementById("compare-no").onclick = closeOverlay;
  document.getElementById("compare-yes").onclick = async () => {
    const chosen = pick.value;
    closeOverlay();
    if (!chosen) return;
    setMode("diff");
    setCompare(chosen);
    renderRibbon();
    syncBreakdown();
    await loadTimeline();
    await loadView({ refit: true });
  };
}

/* **The way out is back to what the map itself implies**, which is Browse for
 * an ordinary map. Leaving a timeline is the one that has to move the map as
 * well: the base is a simulation, so staying on it would mean staying in the
 * mode. Going back to the world it was rolled from is the honest answer. */
async function exitMode() {
  if (state.mode === "edit" && editCount()) {
    const ok = await confirmAction("Discard " + editCount() + " unsaved change(s)?",
      tmpl`<p>They are held in this page only - leaving edit mode throws them
        away. <b>Commit</b> writes them as a new map instead.</p>`, "Discard");
    if (!ok) return;
  }
  clearEdits();
  if (state.mode === "timeline") {
    const base = baseMapOf(state.map);
    if (!base) { toast("This run does not record what it was rolled from"); return; }
    if (!(await selectMap(base))) return;
  } else {
    setMode(modeForMap(state.map));
  }
  syncBreakdown();
  await loadTimeline();
  await loadView({ refit: true });
  await loadCandidates();
  await loadSections();
}

/* **A `<select>` silently blanks on a value it has no option for**, and that
 * rule is worth keeping rather than reimplementing: a one-run batch is offered
 * under its bare name, so `?map=t/run-001` is a valid map id with no option to
 * match. So the element stays the validator - written to, then read back - and
 * `state` takes whatever it actually accepted. */
/* **The listing is the validator now that the picker is not a `<select>`.**
 * An element that silently blanks on an unknown value was doing real work -
 * `?map=made-up` landed nowhere rather than on a wrong map - so the check is
 * kept and made explicit: a map id is accepted when `/api/maps` lists it, and
 * refused otherwise. A **multi-run batch is refused too**, for the reason
 * `mapMenu` nests them: `resolve_map_path` will not guess which run a bare
 * batch name means, so selecting one 404s every route and the map goes blank. */
function setMap(id) {
  const wanted = id || "";
  const row = state.maps.find((m) => m.map_id === wanted);
  state.map = row && !(row.runs > 1) ? wanted : "";
  renderMapPick();
  return state.map;
}

/* What the button shows: the kind's dot, and the name with its batch. */
function renderMapPick() {
  const kind = state.map ? kindOf(state.map) : "";
  el["map-pick-dot"].dataset.kind = kind;
  el["map-pick-dot"].hidden = !state.map;
  el["map-pick-name"].textContent = state.map || "No maps cached";
  el["map-pick"].disabled = !state.maps.length;
}

function setCompare(id) {
  el.compare.value = id || "";
  state.compare = el.compare.value;
  return state.compare;
}

function mapQuery() {
  const params = new URLSearchParams({ map: state.map });
  /* **A step and a comparison are exclusive, and the modes are what make them
   * so.** Two maps and a rewind would need a third colour for "gained by this
   * roll but lost against the other side", which is nobody's question - so
   * only one mode carries a comparison and it is not the one that steps.
   *
   * Browse keeps a step because a batch of one has exactly one, pinned at its
   * end: that is not a rewind but the only world the map has, and it is how
   * the server is asked which chunk arrived. */
  switch (state.mode) {
    case "diff":
      if (state.compare) params.set("compare", state.compare);
      break;
    default:
      if (state.step !== null) params.set("step", String(state.step));
  }
  return params.toString();
}

/* **A batch of several runs is not a map and must not be offered as one.**
 *
 * `cache.resolve_map_path` refuses to guess which run a bare batch name means
 * - picking one silently would make the same name describe a different world
 * as runs were added - so selecting it 404s *every* route and the map goes
 * blank. `/api/maps` lists the batch and its runs flat, so this nests the runs
 * under their batch and gives the batch itself no value to select: an
 * `<optgroup>` is a label, which is exactly what a batch is here.
 *
 * A one-run batch stays a plain option, because there its name is unambiguous
 * and `--map <batch>` resolves to that run everywhere else too. */
function mapOptions(maps) {
  const kindOf = (m) => (m.kind === "fetched" ? "" : "  (" + (KIND_LABELS[m.kind] || label(m.kind)) + ")");
  const option = (m, text) => tmpl`<option value="${m.map_id}">${text}${kindOf(m)}</option>`;
  const runsOf = (batch) => maps.filter((m) => m.map_id.startsWith(batch + "/"));

  let out = "";
  for (const m of maps) {
    if (m.map_id.includes("/")) continue;                 // emitted with its batch
    if (!(m.runs > 1)) { out += option(m, m.map_id); continue; }
    out += tmpl`<optgroup label="${m.map_id}${kindOf(m)}">`
      + runsOf(m.map_id).map((run) => option(run, run.map_id.split("/")[1])).join("")
      + "</optgroup>";
  }
  return out;
}

/* **Ordered by what a map is, then by name.** The three kinds answer three
 * different questions - what upstream holds, what a roll would give you, what
 * you changed by hand - and interleaving them alphabetically made the list a
 * lucky dip. Fetched first because everything else is derived from one. */
const KIND_ORDER = ["fetched", "simulated", "edited"];

function byKindThenName(a, b) {
  const order = KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind);
  return order || a.map_id.localeCompare(b.map_id);
}

/* **A batch's runs open beside it, not inside it.**
 *
 * `cache.resolve_map_path` refuses to guess which run a bare batch name means,
 * so a multi-run batch is a heading rather than a choice - and putting its ten
 * runs in the main list, which is what `<optgroup>` does, buries every other
 * map under them. A submenu says "this is one thing with parts" and costs one
 * row until you ask.
 *
 * A one-run batch stays a plain row: there the name is unambiguous and
 * `--map <batch>` resolves to that run everywhere else too. */
function renderMapMenu() {
  const runsOf = (batch) => state.maps.filter((m) => m.map_id.startsWith(batch + "/"));
  const row = (m, text, extra = "") => tmpl`<button class="menu-row ${
      m.map_id === state.map ? "on" : ""}" type="button" role="option" data-map="${m.map_id}"
      aria-selected="${m.map_id === state.map}" data-tip="${mapTip(m)}">
      <span class="dot" data-kind="${m.kind}"></span>
      <span class="name">${text}</span>${raw(extra)}</button>`;

  let out = "";
  for (const m of [...state.maps].filter((x) => !x.map_id.includes("/")).sort(byKindThenName)) {
    const runs = runsOf(m.map_id);
    if (runs.length < 2) { out += row(m, m.map_id); continue; }
    /* **The batch row carries no tooltip**, and that is not an oversight: it
     * would open in exactly the space the submenu needs and cover the runs it
     * is meant to introduce. What a batch is worth knowing about is per run,
     * and each run keeps its own. */
    out += tmpl`<div class="menu-nest" data-batch="${m.map_id}">
      <button class="menu-row" type="button" aria-haspopup="true" aria-expanded="false">
        <span class="dot" data-kind="${m.kind}"></span>
        <span class="name">${m.map_id}</span>
        <span class="num">${runs.length} runs</span>
        ${icon("next")}</button>
      <div class="submenu">` + runs.map((r) => row(r, r.map_id.split("/")[1])).join("")
      + "</div></div>";
  }
  el["map-menu"].innerHTML = out;
  for (const button of el["map-menu"].querySelectorAll("[data-map]")) {
    button.onclick = () => { closeMapMenu(); chooseMap(button.dataset.map); };
  }
  /* **Hover previews it, a press pins it**, which is one mechanism with two
   * ways in rather than two mechanisms. Hover alone is the fast path and is
   * also the fragile one - it closes the moment the pointer wanders, and
   * there is no hover at all on a touch screen or from a keyboard. Pinning is
   * what makes the runs reachable without a steady hand.
   *
   * Only one nest is open at a time, or two submenus land in the same strip
   * of screen. */
  let pinned = null;
  for (const nest of el["map-menu"].querySelectorAll(".menu-nest")) {
    const open = (on) => {
      for (const other of el["map-menu"].querySelectorAll(".menu-nest")) {
        const showing = (on && other === nest) || other === pinned;
        other.classList.toggle("open", showing);
        other.firstElementChild.setAttribute("aria-expanded", String(showing));
        if (showing) placeSubmenu(other);
      }
    };
    nest.addEventListener("mouseenter", () => { if (!pinned) open(true); });
    nest.addEventListener("mouseleave", () => { if (!pinned) open(false); });
    nest.firstElementChild.onclick = () => {
      pinned = pinned === nest ? null : nest;
      open(pinned === nest);
    };
  }
}

/* Where the submenu goes, since the stylesheet cannot say: it is `fixed` to
 * escape the scrolling menu's clip, so its coordinates are the batch row's
 * own, read at the moment it opens. Flips to the left when the right would
 * run off the window - the picker is at the left edge, so that is the rare
 * side, but a narrow window makes it the only one. */
function placeSubmenu(nest) {
  const submenu = nest.querySelector(".submenu");
  const row = nest.firstElementChild.getBoundingClientRect();
  const gap = 4;
  submenu.style.top = row.top + "px";
  submenu.style.left = "";
  submenu.style.right = "";
  const width = submenu.offsetWidth || 160;
  if (row.right + gap + width <= window.innerWidth) {
    submenu.style.left = row.right + gap + "px";
  } else {
    submenu.style.right = window.innerWidth - row.left + gap + "px";
  }
}

function openMapMenu() {
  renderMapMenu();
  el["map-menu"].hidden = false;
  el["map-pick"].setAttribute("aria-expanded", "true");
}

function closeMapMenu() {
  el["map-menu"].hidden = true;
  el["map-pick"].setAttribute("aria-expanded", "false");
}

el["map-pick"].addEventListener("click", () => {
  if (el["map-menu"].hidden) openMapMenu(); else closeMapMenu();
});

/* Anywhere else closes it, including the map - a menu that needs its own
 * button pressed again to go away is one you fight. */
document.addEventListener("pointerdown", (event) => {
  if (el["map-menu"].hidden) return;
  if (event.target.closest("#map-menu, #map-pick")) return;
  closeMapMenu();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !el["map-menu"].hidden) closeMapMenu();
});

async function loadMaps() {
  const maps = await getJSON("/api/maps");
  state.maps = maps;
  if (!maps.length) {
    /* An empty screen is an invitation to act. The first build showed a blank
     * dropdown and "missing required parameter 'map'", which is a dead end. */
    state.map = "";
    renderMapPick();
    el.counts.textContent = "";
    el["chunk-body"].innerHTML = tmpl`<p class="empty">Nothing cached yet. Run <code>fray fetch</code> in a terminal, or press <b>Fetch Named Map</b> on the Maps tab.</p>`;
    showTab("maps");
    return false;
  }
  const keepMap = state.map, keepCompare = state.compare;
  el.compare.innerHTML = "<option value=''>—</option>" + mapOptions(maps);
  setMap(BOOT.map || keepMap || maps[0].map_id);
  /* **`setMap` refuses an id the listing does not hold**, and a one-run batch
   * is listed under its bare name rather than as `<batch>/run-001` - so
   * `?map=t/run-001` is a perfectly valid map id the listing has no row for.
   * Fall back to the batch it names before giving up on the request. */
  if (!state.map && (BOOT.map || keepMap || "").includes("/")) {
    setMap((BOOT.map || keepMap).split("/")[0]);
  }
  if (!state.map) setMap(maps[0].map_id);
  setCompare(BOOT.compare || keepCompare || "");
  BOOT.map = BOOT.compare = "";
  /* The mode follows the map rather than the other way round, and no prompt:
   * nobody chose this, it is where the page already was. */
  state.mode = state.compare ? "diff" : modeForMap(state.map);
  renderRibbon();
  return true;
}

async function loadView({ refit = false } = {}) {
  if (!state.map) return;
  try {
    const view = await getJSON("/api/view?" + mapQuery());
    state.view = view;
    state.revision = view.revision;
    state.cells = new Map(view.cells.map((c) => [c.grid_x + "," + c.grid_y, c]));
    renderCounts();
    renderLegend();
    if (refit) fitToCells(); else invalidate();
  } catch (error) {
    el.counts.textContent = "";
    toast(error.message);
  }
}

function renderCounts() {
  const view = state.view;
  if (!view) return;
  const parts = [view.counts.unlocked + " unlocked"];
  if (view.counts.added) parts.push("+" + view.counts.added);
  if (view.counts.removed) parts.push("−" + view.counts.removed);
  if (state.showCandidates && state.candidates.size) {
    parts.push(state.candidates.size + " candidates");
  }
  el.counts.textContent = parts.join("  ·  ");

  /* Without this the canvas shows fewer chunks than the count, which reads as
   * a rendering bug rather than "these have no square on this map". */
  if (view.counts.skipped) {
    el.skipped.hidden = false;
    el.skipped.textContent = view.counts.skipped + " off-map";
    el.skipped.onclick = () => toast(view.skipped.join(", "));
  } else {
    el.skipped.hidden = true;
  }
}

/* The legend describes what is actually on screen. The first build always
 * claimed gained and lost, even with nothing to compare against. */
function renderLegend() {
  const items = [["#6f8f5a", "Unlocked"], ["#7e8288", "Locked"]];
  /* **Keyed off the counts, not off `compare_map_id`.** A rewound run has
   * green squares and no compared map, so gating on the map left eight
   * chunks on screen in a colour the legend never explained. */
  const counts = (state.view && state.view.counts) || {};
  if (counts.added) items.push(["rgba(60,200,90,.75)", state.step === null ? "Gained" : "Rolled"]);
  if (counts.removed) items.push(["rgba(220,60,60,.75)", "Lost"]);
  if (state.showCandidates && state.candidates.size) items.push([CANDIDATE_STROKE, "Candidate"]);
  /* A colour on screen the legend does not explain is a colour nobody trusts,
   * and a pending unlock is the one square that means neither gained nor
   * available but "waiting to be committed". */
  if (state.edits.unlocked.size) items.push([PENDING_STROKE, "Unsaved unlock"]);
  if (state.showMasks) {
    items.push([SECTION_REACHED.edge, "Section reached"], [SECTION_LOCKED.edge, "Section locked"]);
  }
  if (state.found.size) items.push(["rgba(255,190,0,.6)", "Found"]);
  el.legend.innerHTML =
    items.map(([colour, label]) => tmpl`<span><i class="sw" style="background:${colour}"></i>${label}</span>`).join("") +
    tmpl`<span><i class="sw" style="background:transparent;border:2px solid ${HULL_STROKE}"></i>Border</span>`;
}

async function loadCandidates() {
  if (!state.showCandidates) {
    state.candidates = new Map();
  } else {
    try {
      const payload = await getJSON("/api/neighbours?map=" + encodeURIComponent(state.map));
      state.candidates = new Map(payload.neighbours.map((n) => [n.chunk_id, n]));
    } catch (error) {
      state.candidates = new Map();
      toast(error.message);
    }
  }
  renderCounts();
  renderLegend();
  invalidate();
}

async function loadSections() {
  if (!state.showMasks || !state.map) { state.sections = {}; return; }
  try {
    const payload = await getJSON("/api/sections?map=" + encodeURIComponent(state.map));
    state.sections = payload.chunks;
  } catch (error) {
    state.sections = {};
    toast(error.message);
  }
  invalidate();
}

/* ---- chunk pane -------------------------------------------------------- */

const CATEGORY_ICONS = {
  monster: "monster", npc: "npc", object: "object", shop: "shop",
  spawn: "spawn", quest: "quest", clue: "clue", diary: "diary",
};

/* `label()` would give "Npc" and "Diarys". The keys are `_CONTENT_KEYS`
 * lower-cased, so this is the whole set and there is nothing to fall through
 * for except the sections chip. */
const CATEGORY_LABELS = {
  monster: "Monsters", npc: "NPCs", object: "Objects", shop: "Shops",
  spawn: "Spawns", quest: "Quests", clue: "Clues", diary: "Diaries",
  sections: "Sections",
};

function categoryLabel(key) { return CATEGORY_LABELS[key] || label(key); }

/* The sections chip is a category like the others as far as the strip is
 * concerned, and it is *not* one of `detail.contents`' keys - which is the
 * whole bug it used to have. `renderChunk` reset the selection to
 * `categories[0]` whenever it was not a content key, so clicking Sections
 * silently landed on whichever category happened to come first (Clue, on a
 * chunk holding nothing before it). Naming it here makes it a member of the
 * set the selection is validated against. */
const SECTIONS_CHIP = "sections";

let chunkDetail = null;
/* A Set, not a string: the chips are checkboxes, so several categories show
 * at once and the default is all of them. Kept across renders and across
 * chunks - if you narrowed to monsters, the next chunk you click means the
 * same question. */
/* Which categories are switched *off*. Empty means everything shows, which is
 * what a chunk you have just clicked should do. See `applyChipGesture`. */
const chunkOff = new Set();

async function selectChunk(chunkId) {
  state.selected = chunkId;
  invalidate();
  if (!chunkId) {
    chunkDetail = null;
    el["chunk-head"].innerHTML = "";
    el["chunk-chips"].innerHTML = "";
    el["chunk-body"].innerHTML = tmpl`<p class="empty">Click a chunk on the map.</p>`;
    return;
  }
  showTab("chunk");
  el["chunk-body"].innerHTML = tmpl`<p class="empty">Reading ${chunkLabel(chunkId)}…</p>`;
  try {
    chunkDetail = await getJSON(
      "/api/chunk?map=" + encodeURIComponent(state.map) +
      "&chunk=" + encodeURIComponent(chunkId));
    clearExpansions("chunk:");
    renderChunk();
  } catch (error) {
    el["chunk-body"].innerHTML = tmpl`<p class="empty">${error.message}</p>`;
  }
}

function renderChunk() {
  const detail = chunkDetail;
  const candidate = state.candidates.get(detail.chunk_id);
  const status = detail.unlocked
    ? '<span class="pill reachable">Unlocked</span>'
    : candidate
      ? '<span class="pill candidate">Candidate #' + candidate.number + "</span>"
      : '<span class="pill locked">Locked</span>';

  /* Two verbs for a locked chunk, and the order is the order you want them
   * in: ask what it gives you, then take it. Both derive twice, so neither is
   * something to do by accident - which is why "Unlock" opens a dialog naming
   * what it will write rather than writing it on the click. */
  /* **Three verbs as icons rather than as a sentence each.** "What would this
   * add?" is a question printed in full on a 360px header, and beside "Focus"
   * and "Unlock" it made a three-line wrap out of a row. What each does lives
   * in the tooltip, which is where every other control in this interface keeps
   * it - and the order is the order you want them in: look at it, ask what it
   * gives you, take it. */
  const offer = detail.unlocked ? "" : tmpl`
      <button id="what-if" class="icon-btn" type="button" aria-label="What would this add?"
        data-tip="<b>What would this add?</b><span class='sub'>Sections, tasks and BiS upgrades this chunk would bring, without saving anything.</span>">${icon("help")}</button>
      <button id="do-unlock" class="icon-btn" type="button" aria-label="Unlock"
        data-tip="<b>Unlock this chunk</b><span class='sub'>Save a new map with this chunk added by hand, the way <code>fray unlock --cache-map</code> does.</span>">${icon("unlock")}</button>`;

  el["chunk-head"].innerHTML = tmpl`<h3>${detail.nickname || "Chunk " + detail.chunk_id}</h3>
    <div class="row"><code>${detail.chunk_id}</code>${raw(status)}
      <span class="spacer"></span>
      <button id="chunk-focus" class="icon-btn" type="button" aria-label="Focus"
        data-tip="<b>Focus</b><span class='sub'>Centre the map on this chunk.</span><span class='hint'>F</span>">${icon("focus")}</button>
      ${raw(offer)}
    </div>`;
  document.getElementById("chunk-focus").onclick = () => focusChunk(detail.chunk_id);
  const whatIf = document.getElementById("what-if");
  if (whatIf) whatIf.onclick = () => previewUnlock(detail.chunk_id);
  const unlockNow = document.getElementById("do-unlock");
  /* **Two different verbs behind one button, and the mode decides which.** In
   * Browse, Unlock derives and writes a map of its own on the spot; in Edit it
   * joins the pending set with everything else and costs nothing until Commit.
   * Offering both at once would be two buttons a word apart. */
  if (unlockNow) unlockNow.onclick = async () => {
    if (state.mode !== "edit") return askUnlock(detail.chunk_id);
    if (state.edits.unlocked.has(detail.chunk_id)) state.edits.unlocked.delete(detail.chunk_id);
    else state.edits.unlocked.add(detail.chunk_id);
    renderRibbon();
    renderChunk();
    renderLegend();
    invalidate();
  };
  if (unlockNow && state.mode === "edit") {
    /* An icon has no label to swap, so the state is said in the tooltip and
     * shown by the button being pressed - which is what `aria-pressed` means
     * and what `.icon-btn[aria-pressed="true"]` already tints amber. */
    const pending = state.edits.unlocked.has(detail.chunk_id);
    unlockNow.setAttribute("aria-pressed", pending ? "true" : "false");
    unlockNow.dataset.tip = pending
      ? "<b>Take it back out</b><span class='sub'>Nothing has been written yet.</span>"
      : "<b>Unlock it on commit</b><span class='sub'>Held in this page with your other changes until you press Commit.</span>";
  }

  /* Categories as chips rather than as eight headings in one column: at 360px
   * a chunk with monsters, NPCs, objects and shops was four short lists you
   * had to scroll past each other to compare. They are *checkboxes*, so the
   * comparison can also be "monsters and NPCs together". */
  const categories = [...Object.keys(detail.contents), SECTIONS_CHIP];
  el["chunk-chips"].innerHTML = categories.map((key) => {
    const on = !chunkOff.has(key);
    const count = key === SECTIONS_CHIP ? detail.sections.length : detail.contents[key].length;
    const tip = tmpl`<b>${categoryLabel(key)}</b><span class="sub">${count} in this chunk</span><span class="hint">${CHIP_HINT}</span>`;
    return tmpl`<button class="chip ${on ? "on" : ""}" data-cat="${key}" data-tip="${tip}"
      role="checkbox" aria-checked="${on}" aria-label="${categoryLabel(key)}">
      ${icon(key === SECTIONS_CHIP ? "sections" : (CATEGORY_ICONS[key] || "dot"))}<span class="count">${count}</span></button>`;
  }).join("");
  for (const chip of el["chunk-chips"].querySelectorAll("[data-cat]")) {
    chip.onclick = (event) => {
      applyChipGesture(chunkOff, chip.dataset.cat, categories, event);
      renderChunk();
    };
  }

  const showing = categories.filter((key) => !chunkOff.has(key));
  if (!showing.length) {
    el["chunk-body"].innerHTML = tmpl`<p class="empty">No categories selected.</p>`;
    return;
  }
  el["chunk-body"].innerHTML = showing.map((key) => {
    const body = key === SECTIONS_CHIP ? renderSections(detail) : renderCategory(detail, key);
    /* One category selected is a list; several need saying which is which.
     * No count on the heading: the chip above it already carries one, and the
     * truncation control below says how many are hidden when any are. */
    if (showing.length === 1) return body;
    return tmpl`<h3>${categoryLabel(key)}</h3>` + body;
  }).join("");
  ownsMore("chunk", renderChunk);
}

/* **A chip strip records what is *off*, not what is on**, and that is the fix
 * for a real bug rather than a preference. Holding the selected set meant it
 * was frozen the first time a strip rendered: click a chunk with no shops and
 * the `shop` chip was simply absent, so the next chunk that *did* have one
 * showed it unchecked, with nothing to say why. Tracking exclusions instead
 * means a category nobody has ever seen is on by default, for ever, which is
 * what "all on to begin with" has to mean.
 *
 * Three gestures, matching how selection works in every file manager:
 *
 *   click        only this one
 *   shift-click  add this one to the selection
 *   ctrl-click   take this one out of the selection
 *
 * Plain click narrowing to one is the important half: with everything on by
 * default, "just show me monsters" is the common request and it should not
 * take eight clicks.
 *
 * **And clicking the isolated chip again puts everything back**, which is the
 * other half of the same gesture: narrowing to one is a single click, so
 * widening from one has to be too. Without it the only way out of "monsters
 * only" was to shift-click each of the other seven, and the chip you had just
 * pressed was the one control that did nothing. */
function applyChipGesture(off, key, keys, event) {
  if (event.shiftKey) return off.delete(key);
  if (event.ctrlKey || event.metaKey) return off.add(key);
  let isolated = !off.has(key);
  for (const other of keys) if (other !== key && !off.has(other)) isolated = false;
  off.clear();
  if (isolated) return;
  for (const other of keys) if (other !== key) off.add(other);
}

const CHIP_HINT = "Click for only this, again for all · shift adds · ctrl removes";

function renderSections(detail) {
  if (!detail.sections.length) return tmpl`<p class="empty">This chunk is not split.</p>`;
  let out = "<ul class='list'>";
  for (const section of detail.sections) {
    const tip = section.section === "0"
      ? "Section 0 opens with the chunk itself."
      : (section.reachable
          ? "Opened by a link from a section you already reach."
          : "Needs a link from somewhere you have not unlocked yet.");
    out += tmpl`<li data-tip="${tip}" data-sections="${section.section}"
      data-reachable="${section.reachable ? "1" : ""}"><span class="name">Section ${section.section}</span>
      <span class="pill ${section.reachable ? "reachable" : "locked"}">${section.reachable ? "Reachable" : "Unreached"}</span></li>`;
  }
  return out + "</ul>";
}

/* One list for the whole chunk, not one per section. Which section something
 * is in still decides whether you can *reach* it, so that stays - as a greyed
 * row and a note, rather than as structure you have to reassemble by eye. */
function renderCategory(detail, key) {
  const rows = detail.contents[key] || [];
  if (!rows.length) return tmpl`<p class="empty">Nothing recorded here.</p>`;
  return "<ul class='list'>" + withMore(rows, "chunk:" + detail.chunk_id + ":" + key,
    TASK_ROWS, (row) => {
    const tip = tmpl`<b>${plain(row.name)}</b><span class="sub">${
      row.sections.length === 1 ? "Section " + row.sections[0] : "Sections " + row.sections.join(", ")
    }</span><span class="sub">${row.reachable
      ? "You can reach this"
      : "Behind a section you have not opened"}</span>`;
    /* **The section number is gone from the row and drawn on the map
     * instead.** A column of `3`, `1, 4`, `0` beside forty names is the
     * busiest thing in the panel and answers a question - *which part of the
     * square* - that a number cannot answer at all. Hovering the row paints
     * the shape; the tooltip still spells the numbers out for anyone who
     * wants them. */
    return tmpl`<li class="${row.reachable ? "" : "unreached"}" data-tip="${tip}"
      data-sections="${row.sections.join(" ")}" data-reachable="${row.reachable ? "1" : ""}">
      <span class="name">${plain(row.name)}</span></li>`;
  }) + "</ul>";
}

/* Delegated over the whole pane, so every list gets the behaviour by emitting
 * `data-sections` and nothing has to be wired up per render. */
el["chunk-body"].addEventListener("mouseover", (event) => {
  const row = event.target.closest("li[data-sections]");
  if (!row || !chunkDetail) return hoverSection(null);
  hoverSection({
    chunk: chunkDetail.chunk_id,
    sections: row.dataset.sections.split(" ").filter(Boolean),
    reachable: row.dataset.reachable === "1",
    whole: chunkDetail.sections.length <= 1,
  });
});

el["chunk-body"].addEventListener("mouseleave", () => hoverSection(null));

function hoverSection(next) {
  const before = state.hoverSection;
  if (before === next) return;
  if (before && next && before.chunk === next.chunk && before.reachable === next.reachable
      && before.whole === next.whole
      && before.sections.join(" ") === next.sections.join(" ")) return;
  state.hoverSection = next;
  invalidate();
}

async function previewUnlock(chunkId) {
  openOverlay("If you unlocked " + chunkId, tmpl`<p class="empty">Deriving both worlds…</p>`);
  try {
    const delta = await getJSON(
      "/api/unlock?map=" + encodeURIComponent(state.map) +
      "&chunk=" + encodeURIComponent(chunkId));
    const tasks = Object.entries(delta.new_tasks).filter(([, v]) => Object.keys(v).length);
    const taskCount = tasks.reduce((n, [, v]) => n + Object.keys(v).length, 0);
    const sectionCount = Object.values(delta.new_sections)
      .reduce((n, v) => n + Object.keys(v).length, 0);

    let out = tmpl`<dl class="kv">
      <dt>Tasks</dt><dd>${taskCount}</dd>
      <dt>Sections</dt><dd>${sectionCount}</dd>
      <dt>BiS upgrades</dt><dd>${Object.keys(delta.bis_upgrades).length}</dd></dl>`;
    if (tasks.length) {
      out += "<h3>By category</h3><ul class='list'>";
      const sorted = tasks.sort((a, b) => Object.keys(b[1]).length - Object.keys(a[1]).length);
      out += withMore(sorted, "unlock:tasks", 8, ([category, names]) => {
        const keys = Object.keys(names);
        const tip = tmpl`<b>${category}</b>` + keys.slice(0, 8).map((n) => tmpl`<span class="sub">${plain(n)}</span>`).join("")
          + (keys.length > 8 ? tmpl`<span class="hint">and ${keys.length - 8} more</span>` : "");
        return tmpl`<li data-tip="${tip}"><span class="name">${category}</span><span class="num">${keys.length}</span></li>`;
      });
      out += "</ul>";
    }
    /* The answer to "what would this add" is exactly the moment you decide to
     * take it, so the way to take it is in the footer of the answer. */
    openOverlay("If you unlocked " + chunkId, out,
      tmpl`<button id="preview-unlock" type="button">Unlock this chunk</button>`);
    document.getElementById("preview-unlock").onclick = () => askUnlock(chunkId);
    ownsMore("unlock", () => previewUnlock(chunkId));
  } catch (error) {
    openOverlay("If you unlocked " + chunkId, tmpl`<p class="empty">${error.message}</p>`);
  }
}

/* **Unlocking writes a map, so it asks for a name first.** The default is the
 * one thing you would otherwise have to invent, and it is derived rather than
 * fixed so unlocking two chunks from one map does not collide - `claim_batch`
 * would suffix the second `-2`, which reads as an accident rather than as a
 * choice. Whatever name is claimed comes back in the reply either way. */
function askUnlock(chunkId) {
  const suggested = (state.map || DEFAULT_MAP_ID).replace(/\//g, "-") + "-" + chunkId;
  openOverlay("Unlock " + chunkLabel(chunkId),
    tmpl`<p>Writes a new map under <code>cache/maps/edited/</code> holding
      everything <b>${state.map}</b> holds plus this chunk. Nothing existing
      is touched, and the derivation takes a second or two.</p>
      <div class="row"><input id="unlock-name" type="text" value="${suggested}"
        aria-label="Name for the new map" spellcheck="false" autocomplete="off"
        data-tip="<b>Name for the new map</b><span class='sub'>A name already in use gains <code>-2</code>, <code>-3</code>, … rather than overwriting.</span>"></div>`,
    tmpl`<button id="unlock-no" type="button">Cancel</button>
      <button id="unlock-yes" type="button">Unlock</button>`);

  const field = document.getElementById("unlock-name");
  const go = () => {
    const name = field.value.trim() || suggested;
    closeOverlay();
    runAction("Unlock " + chunkLabel(chunkId), "/api/unlock",
      { map: state.map, chunk: chunkId, name },
      async (result) => {
        /* **Select rather than compare**, for the reason the Roll button was
         * changed: a comparison is exactly the state that hides the timeline,
         * so putting the new map there hid the one record of what the unlock
         * did. Nothing is lost by selecting it - a saved unlock replays its own
         * single roll, so the chunk it added still draws green from that ledger
         * rather than from a comparison. */
        const base = state.map;
        await loadMaps();
        if (result.open) {
          openMap(result.open);
        }
        syncBreakdown();
        await loadTimeline();
        await loadView();
        await loadCandidates();
        await loadSections();
        loadMapsPane();
        if (result.open) toast("Unlocked " + chunkLabel(chunkId) + " on " + base + " — the new chunk is green");
      });
  };
  document.getElementById("unlock-no").onclick = closeOverlay;
  document.getElementById("unlock-yes").onclick = go;
  field.onkeydown = (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    go();
  };
  field.focus();
  field.select();
}

/* ---- the full comparison ------------------------------------------------ */

/* The map answers "which chunks", in microseconds, from a set difference. This
 * answers "and what did they give me", which is a question about sections,
 * tasks, sources and BiS - and there is no way to it that does not derive both
 * sides. So it is a button rather than something the view carries: about two
 * seconds cold, and you press it when you want the answer.
 *
 * Both `unlock.py`'s preview and this one land in the same dialog on purpose.
 * They ask nearly the same thing at different scales - one candidate chunk
 * against one whole map - and giving them two shapes would be two things to
 * learn for one idea. */
const DIFF_BRANCHES = [
  ["chunks", "Chunks"],
  ["sections", "Sections"],
  ["tasks", "Skill tasks"],
  ["bis", "Best in slot"],
  ["other", "Diaries, quests, extras"],
  ["sources", "Sources"],
  ["skills", "Skill winners"],
  ["unsupported", "Unsupported"],
];

/* How many names of a branch to print before saying "and N more". A branch can
 * hold hundreds and the dialog is for reading, not for exporting - `fray diff`
 * is the tool that prints all of them. */
const DIFF_SAMPLE = 12;

function diffNames(branch) {
  /* `sections`, `tasks`, `sources` and `other` are keyed one level deeper -
   * per chunk, per skill, per category - and a flat list of what changed is
   * what the dialog reads best. The key is kept as the note, so a task still
   * says which skill it belongs to. */
  const added = [], removed = [];
  const take = (delta, key) => {
    for (const name of Object.keys(delta.added || {})) added.push([name, key]);
    for (const name of delta.removed || []) removed.push([name, key]);
  };
  if (branch && Array.isArray(branch.removed)) take(branch, "");
  else for (const [key, inner] of Object.entries(branch || {})) {
    if (Array.isArray(inner.removed)) take(inner, key);
    /* `other` is category -> {active, completed} -> BranchDelta. */
    else for (const [side, delta] of Object.entries(inner || {})) {
      if (delta && Array.isArray(delta.removed)) take(delta, key + " " + side);
    }
  }
  return { added, removed };
}

function diffList(rows, kind, key) {
  return tmpl`<ul class="list ${kind}">` + withMore(rows, key, DIFF_SAMPLE, ([name, note]) =>
    tmpl`<li><span class="mark">${kind === "gain" ? "+" : "−"}</span>
      <span class="name">${plain(name)}</span><span class="sub">${plain(note)}</span></li>`) + "</ul>";
}

async function showBreakdown() {
  const from = state.map, to = state.compare;
  if (!from || !to) return;
  const title = from + " → " + to;
  openOverlay(title, tmpl`<p class="empty">Deriving both worlds…</p>`);

  let delta;
  try {
    delta = await getJSON(
      "/api/diff?map1=" + encodeURIComponent(from) + "&map2=" + encodeURIComponent(to));
  } catch (error) {
    return openOverlay(title, tmpl`<p class="empty">${error.message}</p>`);
  }

  /* Built as a function so opening one of its lists redraws from the delta
   * already in hand. Re-running the comparison would derive both maps again
   * for a set the browser is holding. */
  const render = () => {
    /* The summary first, because "did anything change, and where" is the
     * question, and eight numbers answer it before any list is read. */
    let out = tmpl`<p class="sub">Everything <b>${to}</b> holds that <b>${from}</b> does not, and the reverse.</p><dl class="kv">`;
    for (const [key, name] of DIFF_BRANCHES) {
      const counts = delta.counts[key] || { added: 0, removed: 0 };
      if (!counts.added && !counts.removed) continue;
      out += tmpl`<dt>${name}</dt><dd><span class="gain">+${counts.added}</span>
        <span class="loss">−${counts.removed}</span></dd>`;
    }
    out += "</dl>";

    for (const [key, name] of DIFF_BRANCHES) {
      const counts = delta.counts[key] || { added: 0, removed: 0 };
      if (!counts.added && !counts.removed) continue;
      const { added, removed } = diffNames(delta[key === "bis" ? "bis_tasks" : key]);
      out += tmpl`<h3>${name} <span class="num">+${counts.added} −${counts.removed}</span></h3>`;
      if (added.length) out += diffList(added, "gain", "diff:" + key + ":gain");
      if (removed.length) out += diffList(removed, "loss", "diff:" + key + ":loss");
    }
    return out;
  };

  const changed = DIFF_BRANCHES.some(([key]) => {
    const counts = delta.counts[key] || { added: 0, removed: 0 };
    return counts.added || counts.removed;
  });
  if (!changed) {
    return openOverlay(title, tmpl`<p class="empty">These two derive identically. Every branch agrees.</p>`);
  }

  clearExpansions("diff:");
  openOverlay(title, render());
  ownsMore("diff", () => openOverlay(title, render()));
}

el.breakdown.addEventListener("click", showBreakdown);

/* Nothing to compare is not an error worth a message - it is a button that
 * does not apply yet. */
function syncBreakdown() {
  el.breakdown.disabled = !state.map || !state.compare;
}

/* ---- tasks pane -------------------------------------------------------- */

const GROUP_ICONS = {
  "Collection Log": "log",
  "Permanent Unlockables": "unlock",
  "Untracked Uniques": "star",
  "Ungrouped": "dot",
};

/* What `bis.slots` answers with, and the badge for each. The style is already
 * the heading, so what the row's own icon has to distinguish is a ring from a
 * pair of boots - which is the slot, not the style. */
const SLOT_ICONS = {
  head: "slot-head", cape: "slot-cape", neck: "slot-neck", weapon: "slot-weapon",
  "2h": "slot-2h", body: "slot-body", shield: "slot-shield", legs: "slot-legs",
  hands: "slot-hands", feet: "slot-feet", ring: "slot-ring",
};

/* At most this many rows of any one group before the rest folds into a
 * control. Nine because a 360px panel shows about that before the next
 * heading leaves the screen, and a category you cannot see the end of is one
 * you scroll past rather than read. */
const TASK_ROWS = 9;

/* A row's badge. Three sources and they do not overlap: a skill's own icon
 * from upstream, a Combat Achievement tier badge from the wiki, or an inline
 * slot glyph. `icon` carries which - `ca:easy` names the second. */
/* **A row with no badge is padded to where one would be.** Skills carry an
 * icon and diaries do not, so an unpadded list stepped left and right down the
 * column and the eye lost the edge it reads names against. The width is the
 * badge's, and it is one place because two would drift. */
const ICON_GAP = '<span class="icon-gap"></span>';

function rowBadge(name) {
  if (!name) return ICON_GAP;
  if (name.startsWith("ca:")) {
    return tmpl`<img class="skill-icon" src="/assets/ca/${name.slice(3)}.png" alt="${name.slice(3)}">`;
  }
  return tmpl`<img class="skill-icon" src="/assets/skill/${name}.png" alt="${name}">`;
}

let taskPanel = null;
/* Which task categories are switched *off*. The five answer one question
 * between them - "what is left" - so they all show until you say otherwise. */
const taskOff = new Set();

async function loadTasks() {
  if (taskPanel && taskPanel.map_id === state.map) return renderTasks();
  el["tasks-body"].innerHTML = tmpl`<p class="empty">Deriving…</p>`;
  try {
    taskPanel = await getJSON("/api/tasks?map=" + encodeURIComponent(state.map));
    clearExpansions("tasks:");
    renderTasks();
  } catch (error) {
    taskPanel = null;
    el["task-chips"].innerHTML = "";
    el["tasks-body"].innerHTML = tmpl`<p class="empty">${error.message}</p>`;
  }
}

function renderTasks() {
  const sections = taskPanel.sections;
  const keys = sections.map((s) => s.key);
  el["task-chips"].innerHTML = sections.map((s) => {
    const on = !taskOff.has(s.key);
    const count = state.showDone ? s.completed_total : s.active_total;
    const tip = tmpl`<b>${s.label}</b><span class="sub">${count} ${state.showDone ? "completed" : "outstanding"}</span><span class="hint">${CHIP_HINT}</span>`;
    return tmpl`<button class="chip ${on ? "on" : ""}" data-section="${s.key}" data-tip="${tip}"
      role="checkbox" aria-checked="${on}">
      ${s.label}<span class="count">${count}</span></button>`;
  }).join("");
  for (const chip of el["task-chips"].querySelectorAll("[data-section]")) {
    chip.onclick = (event) => {
      applyChipGesture(taskOff, chip.dataset.section, keys, event);
      renderTasks();
    };
  }

  const side = state.showDone ? "completed" : "active";
  const showing = sections.filter((s) => !taskOff.has(s.key));
  if (!showing.length) {
    el["tasks-body"].innerHTML = tmpl`<p class="empty">No categories selected.</p>`;
    return;
  }

  const out = renderTaskGroups(showing, side, "tasks", { tickable: true });
  el["tasks-body"].innerHTML = out ||
    tmpl`<p class="empty">Nothing ${state.showDone ? "completed" : "outstanding"} here.</p>`;
  ownsMore("tasks", renderTasks);
}

/* **One renderer, two surfaces.** The Tasks tab and a roll's Details overlay
 * ask the same question of the same shape - `panels.py` hands both a `Panel`
 * envelope - so they draw with the same code rather than with two copies that
 * drift. They already had: the overlay printed sixty Construction builds where
 * the tab shows the furthest one, and kept a `<group>#<tier>` prefix the tab
 * drops.
 *
 * `tickable` is the one real difference. Ticking writes to
 * `completedChallenges` on the map you are looking at; a roll's rows are a
 * record of what a *past* state opened, so clicking one has nothing to write.
 *
 * **A heading carries no count.** The chips already carry one each and the
 * list under a heading is right there to be looked at; three numbers saying
 * the same thing is what made the pane read as a report rather than a list.
 * What replaces it is the truncation control, which says how many are hidden
 * only when some are. */
function renderTaskGroups(sections, side, keyPrefix, { tickable = false } = {}) {
  let out = "";
  for (const section of sections) {
    const groups = section.groups.filter((g) => g[side].length);
    if (!groups.length) continue;
    /* The section's own heading, once several are on screen at a time. With
     * one selected the chip already says which, and repeating it costs a row
     * of a 360px panel. */
    if (sections.length > 1) out += tmpl`<h3 class="section">${section.label}</h3>`;
    for (const group of groups) {
      /* A single group whose name repeats the heading is a heading twice. */
      if (groups.length > 1 || group.name !== section.label) {
        const mark = group.icon
          ? rowBadge(group.icon)
          : (GROUP_ICONS[group.name] ? icon(GROUP_ICONS[group.name]).__raw + " " : "");
        out += tmpl`<h3>${raw(mark)}${group.name}</h3>`;
      }
      const key = keyPrefix + ":" + section.key + ":" + group.name + ":" + side;
      out += "<ul class='list'>" + withMore(group[side], key, TASK_ROWS, (row) => {
        /* A slot badge *replaces* the note rather than sitting beside it:
         * the glyph and the word "ring" say one thing, and a 360px row has
         * no space to say it twice. The tooltip still spells it out. */
        const slot = SLOT_ICONS[row.note];
        const badge = row.icon ? rowBadge(row.icon) : (slot ? icon(slot).__raw : ICON_GAP);
        /* The row shows the subject; the tooltip shows the whole task as the
         * export writes it, which is what `fray tasks` prints and what you
         * would search for. */
        const tip = tmpl`<b>${plain(row.name)}</b>`
          + (row.note ? tmpl`<span class="sub">${plain(row.note)}</span>` : "")
          + tmpl`<span class="hint">${plain(row.key)}</span>`;
        /* **The row is the gesture.** Ticking is what a person does with a
         * to-do list, so the list is what they click - and `data-task`/
         * `data-category` carry the payload's own key rather than the
         * panel's grouping, which is what `panels._entry` exists to say. */
        const pending = tickable && state.edits.ticked.get(row.category)?.has(row.key)
          ? " ticked" : "";
        const hooks = tickable
          ? tmpl` data-task="${row.key}" data-category="${row.category || ""}"`
          : "";
        return tmpl`<li class="task${pending}" data-tip="${tip}"${raw(hooks)}>${raw(badge)}<span class="name">${plain(row.name)}</span>
          <span class="sub">${plain(slot ? "" : row.note || "")}</span></li>`;
      }) + "</ul>";
    }
  }
  return out;
}

/* Delegated, so a re-render needs no rewiring - the same reason the tooltips
 * are. A completed row is not offered: un-ticking is not a thing this writes,
 * because `completedChallenges` is the player's own record and removing from
 * it is a claim about their past rather than about their map. */
el["tasks-body"].addEventListener("click", async (event) => {
  const row = event.target.closest("li.task[data-task]");
  if (!row || state.showDone) return;
  const category = row.dataset.category;
  if (!category) { toast("This row has no category to tick against"); return; }
  if (!(await ensureEditing())) return;
  const names = state.edits.ticked.get(category) || new Set();
  if (names.has(row.dataset.task)) names.delete(row.dataset.task);
  else names.add(row.dataset.task);
  if (names.size) state.edits.ticked.set(category, names);
  else state.edits.ticked.delete(category);
  renderRibbon();
  renderTasks();
});

el["show-done"].addEventListener("click", () => {
  state.showDone = !state.showDone;
  el["show-done"].setAttribute("aria-pressed", String(state.showDone));
  el["show-done"].title = state.showDone ? "Show what is left to do" : "Show what is already done";
  if (taskPanel) renderTasks();
});

/* ---- estimate pane ----------------------------------------------------- */

const BUCKET_COLOURS = {
  "quests": "#5abeff",
  "boss drops": "#dc3c3c",
  "activities": "#ffbe00",
  "skilling": "#3cc85a",
};

let estimatePayload = null;

async function loadEstimate() {
  el["estimate-body"].innerHTML = tmpl`<p class="empty">Pricing the outstanding work…</p>`;
  try {
    estimatePayload = await getJSON("/api/estimate?map=" + encodeURIComponent(state.map));
    clearExpansions("estimate:");
    renderEstimate(estimatePayload);
  } catch (error) {
    estimatePayload = null;
    el["estimate-total"].textContent = "";
    el["estimate-body"].innerHTML = tmpl`<p class="empty">${error.message}</p>`;
  }
}

/* A donut of stroke-dashed arcs. Four numbers whose whole meaning is their
 * proportion to each other, which is the one thing a column of figures does
 * not show - and it is SVG, so there is still no dependency.
 *
 * **The hours are on the arc, not beside it.** A legend carrying four figures
 * is a table with a picture next to it, and the picture is then decoration;
 * the proportions are what the chart is *for*, and the number behind one of
 * them is a question you ask about a single slice. `fill: none` means only the
 * stroke takes the pointer, so the ring is the hit area and the hole is not. */
function donut(ordered, total) {
  const R = 54, C = 2 * Math.PI * R;
  let offset = 0;
  let arcs = `<circle cx="70" cy="70" r="${R}" stroke="#22262f"/>`;
  for (const [name, value] of ordered) {
    const length = (value / total) * C;
    const tip = tmpl`<b>${label(name)}</b><span class="sub">${hours(value)} · ${Math.round((value / total) * 100)}% of the total</span>`;
    arcs += tmpl`<circle class="slice" cx="70" cy="70" r="${R}" stroke="${BUCKET_COLOURS[name] || "#858d9c"}"
      stroke-dasharray="${length} ${C - length}" stroke-dashoffset="${-offset}" data-tip="${tip}"/>`;
    offset += length;
  }
  return `<svg class="pie" width="140" height="140" viewBox="0 0 140 140">${arcs}</svg>`;
}

function renderEstimate(payload) {
  const total = payload.total_hours || 0;
  el["estimate-total"].textContent = hours(total) + " remaining";

  /* **One order for the chart, the key and the lists.** `_json` sorts its
   * keys, so the payload arrives alphabetical - which is an order about
   * spelling. Biggest first is the order the chart is read in, and it makes
   * the headings below say the same thing as the wedges above. Empty buckets
   * are dropped rather than drawn at zero: a swatch with no arc beside it is
   * a legend entry you go looking for and never find. */
  const ordered = Object.entries(payload.buckets)
    .filter(([, value]) => value > 0)
    .sort((a, b) => b[1] - a[1]);

  let out = '<div class="pie-row">' + donut(ordered, total || 1) + '<div class="pie-key">';
  for (const [name, value] of ordered) {
    /* The key names the slices and no more. Hovering either the swatch or the
     * arc it stands for gives the same figure, so the number is one gesture
     * away from wherever you happen to be pointing. */
    const tip = tmpl`<b>${label(name)}</b><span class="sub">${hours(value)} · ${Math.round((value / (total || 1)) * 100)}% of the total</span>`;
    out += tmpl`<span data-tip="${tip}"><i class="sw" style="background:${BUCKET_COLOURS[name] || "#858d9c"}"></i>${label(name)}</span>`;
  }
  out += "</div></div>";

  /* **Headed by the bucket, not by "Longest single items".** The pie is four
   * named slices and this was one undifferentiated list drawn from two of
   * them, so the eye had nothing to join: an item costing 40h told you
   * nothing about which wedge it was 40h of. Split by bucket, each list is
   * the inside of a slice you just looked at. Name and hours only - the
   * reasoning is real but it is the second question, so it is in the
   * tooltip. */
  const byBucket = new Map();
  const file = (bucket, row) => {
    if (!byBucket.has(bucket)) byBucket.set(bucket, []);
    byBucket.get(bucket).push(row);
  };
  /* Two shapes, one list. `items` are the unique things you go and get, which
   * is boss drops and activities; `tasks` is the quest bucket, costed per
   * quest rather than per item. `estimate.py`'s docstring is the authority on
   * why those are different units - here they are both "a thing and its
   * hours". */
  for (const item of payload.items || []) file(item.bucket, { name: item.item, ...item });
  for (const task of payload.tasks || []) file(task.bucket, { name: task.task, ...task });

  /* Ordered as the pie is, so the third heading down is the third wedge
   * round and the swatch beside it is the one you just hovered. */
  for (const [bucket] of ordered) {
    const swatch = tmpl`<i class="sw" style="background:${BUCKET_COLOURS[bucket] || "#858d9c"}"></i>`;
    if (bucket === "skilling") {
      /* The one bucket whose rows are not things but levels, so it keeps its
       * own shape: a skill, where it is going, and what that costs. */
      const skills = (payload.skills || []).slice().sort((a, b) => b.hours - a.hours);
      if (!skills.length) continue;
      out += tmpl`<h3>${raw(swatch)}${label(bucket)} <span class="num">${skills.length}</span></h3><ul class="list">`;
      out += withMore(skills, "estimate:skilling", 14, (skill) => {
        /* The same renderer the roll overlay uses - one tooltip system, and
         * this one was three lines that said much less. */
        const tip = skillTip(skill);
        return tmpl`<li data-tip="${tip}"><img class="skill-icon" src="/assets/skill/${skill.skill}.png" alt="">
          <span class="name">${skill.skill}</span>
          <span class="sub">${skill.current_level} → ${skill.target_level}</span>
          <span class="num">${hours(skill.hours)}</span></li>`;
      });
      out += "</ul>";
      continue;
    }
    const rows = (byBucket.get(bucket) || []).slice().sort((a, b) => b.hours - a.hours);
    if (!rows.length) continue;
    out += tmpl`<h3>${raw(swatch)}${label(bucket)} <span class="num">${rows.length}</span></h3><ul class="list">`;
    out += withMore(rows, "estimate:" + bucket, 12, (row) => {
      const tip = tmpl`<b>${plain(row.name)}</b><span class="sub">${plain(row.detail)}</span><span class="sub">${label(row.bucket)}</span>`;
      return tmpl`<li data-tip="${tip}"><span class="name">${plain(row.name)}</span><span class="num">${hours(row.hours)}</span></li>`;
    });
    out += "</ul>";
  }

  const unpriced = payload.unpriced || [];
  if (unpriced.length) {
    out += tmpl`<h3 data-tip="${"Reachable, but no rate exists for it in cache/wiki_rates.json, heuristics/overrides.json or a default - so none of these hours are in the total above."}">Unpriced <span class="num">${unpriced.length}</span></h3><ul class="list">`;
    out += withMore(unpriced, "estimate:unpriced", 25, (item) =>
      tmpl`<li><span class="name">${plain(typeof item === "string" ? item : item.item || "")}</span></li>`);
    out += "</ul>";
  }
  el["estimate-body"].innerHTML = out;
  ownsMore("estimate", () => renderEstimate(estimatePayload));
}

/* Provenance is not a number you act on, it is a caveat on all of them - so
 * it is one button away rather than between you and the list. */
el["estimate-why"].addEventListener("click", () => {
  const payload = estimatePayload;
  if (!payload) return;
  /* An estimate computed with the DPS bridge and one without are materially
   * different totals, so the screen has to be able to say which it showed. */
  let out = tmpl`<dl class="kv">
    <dt>Wiki rates</dt><dd>${payload.scraped_rates ? "Present" : "Missing"}</dd>`;
  out += payload.dps
    /* The denominator matters: the count is of *reachable* monsters, not of
     * the export, because pricing anything the estimate cannot ask about is
     * work thrown away. Without it the figure reads as poor coverage. */
    ? tmpl`<dt>DPS calculator</dt><dd>${payload.dps.monsters} of ${payload.dps.offered} reachable monsters</dd>
           <dt></dt><dd>${payload.dps.slayer_tasks} slayer tasks</dd>`
    : tmpl`<dt>DPS calculator</dt><dd>Not installed</dd>`;
  out += "</dl>";
  out += tmpl`<p class="sub">Every hour here comes from <code>cache/wiki_rates.json</code>,
    <code>heuristics/overrides.json</code> or a default — the export carries no durations at all.
    ${payload.dps ? "With the DPS extra installed, kill rates are recomputed from this map's own BiS gear and beat the scrape; hand overrides still win." : ""}</p>`;

  /* Every reachable master, not just the one the estimate spent, because
   * "which master" is a decision and coverage is what makes it one: a rate
   * renormalised over a third of a list flatters that master. */
  const masters = payload.slayer_masters || [];
  if (masters.length) {
    out += tmpl`<h3>Slayer masters</h3><ul class="list">`;
    for (const master of masters) {
      const chosen = payload.slayer && payload.slayer.master === master.master;
      out += tmpl`<li><span class="name">${chosen ? "▸ " : ""}${master.master}</span>
        <span class="sub">${Math.round(master.coverage * 100)}% covered · ${master.points_delta.toFixed(0)} pts</span>
        <span class="num">${Math.round(master.xp_per_hour || 0).toLocaleString()}/h</span></li>`;
    }
    out += "</ul>";
  }
  openOverlay("Where the numbers come from", out);
});

/* ---- find pane --------------------------------------------------------- */

/* A hit's placed locations. **They are objects, not strings** - `{chunk_id,
 * available}` - and the first version read them as strings, so every result
 * reported no source at all. NPCs and objects carry them at the top level;
 * an item carries them under each of its sources. A `chunk_id` may be
 * `12850-1` or a named area like `Observatory Dungeon`, and only the numeric
 * head of the former has a square. */
function chunksOf(result) {
  const found = new Set();
  const consider = (locations) => {
    for (const location of locations || []) {
      const id = String(location && location.chunk_id != null ? location.chunk_id : location);
      const chunk = id.split("-")[0];
      if (/^\d+$/.test(chunk)) found.add(chunk);
    }
  };
  consider(result.locations);
  for (const source of result.sources || []) consider(source.locations);
  return [...found];
}

function highlight(result) {
  const name = plain(result.name);
  state.found = new Set(chunksOf(result));
  renderLegend();
  invalidate();
  if (!state.found.size) { toast(name + " has no placed source"); return; }

  /* **Frame every source, not the first one.** A thing with six sources is
   * six answers to "where do I get this", and flying to one of them says the
   * other five are somewhere off screen - which is the question you asked.
   * `frameChunks` fits the rectangle holding all of them, and falls back to
   * centring when there is only one.
   *
   * It also drops the ids with no square. Plenty are underground or instanced
   * regions off the surface rectangle - an abyssal whip's first source is one
   * - and centring on one silently does nothing, which reads as a broken
   * button rather than as "that place is not on this map". */
  const placed = [...state.found].filter((id) => chunkToGrid(id));
  if (!frameChunks(placed)) {
    toast(name + ": " + state.found.size + " chunks, none on the surface map");
    return;
  }
  toast(name + ": " + state.found.size + (state.found.size === 1 ? " chunk" : " chunks"));
}

let findTimer = null;
let findRun = 0;

/* Searching on every keystroke, debounced, and every request tagged with the
 * run that asked for it - so a slow reply for "abys" cannot land on top of
 * the results for "abyssal". */
function scheduleFind() {
  clearTimeout(findTimer);
  findTimer = setTimeout(runFind, 220);
}

async function runFind() {
  const term = el["find-input"].value.trim();
  const body = el["find-body"];
  if (term.length < 2) {
    body.innerHTML = tmpl`<p class="empty">Search the whole world, unlocked or not.</p>`;
    return;
  }
  const run = ++findRun;
  body.innerHTML = tmpl`<p class="empty">Searching…</p>`;
  try {
    const payload = await getJSON(
      "/api/search?q=" + encodeURIComponent(term) +
      "&map=" + encodeURIComponent(state.map) + "&limit=40");
    if (run !== findRun) return;
    if (!payload.results.length) {
      body.innerHTML = tmpl`<p class="empty">Nothing matches ${term}.</p>`;
      return;
    }
    /* **Reachable first, then alphabetical.** The server ranks by how well a
     * name matches, which is the right order for picking the forty results
     * worth sending and the wrong one for reading them: what you can actually
     * get to is the answer, and everything else is context for it. Sorting
     * the page rather than asking the server to sort keeps that ranking doing
     * the job it is good at - deciding *which* forty. */
    const results = payload.results.slice().sort((a, b) =>
      (b.available === true) - (a.available === true) ||
      plain(a.name).localeCompare(plain(b.name), undefined, { sensitivity: "base" }));
    let out = "<ul class='list'>";
    results.forEach((result, index) => {
      const chunks = chunksOf(result);
      const note = chunks.length ? chunks.length + (chunks.length === 1 ? " chunk" : " chunks") : "—";
      const tip = tmpl`<b>${plain(result.name)}</b><span class="sub">${label(result.type)} · ${
        result.available ? "reachable on this map" : "not reachable yet"
      }</span><span class="hint">${chunks.length ? "Click to light up its " + note + " on the map" : "Nowhere on the surface map"}</span>`;
      out += tmpl`<li data-tip="${tip}">
        <span class="pill ${result.available ? "reachable" : "locked"}">${label(result.type)}</span>
        <button class="link name" data-result="${index}">${plain(result.name)}</button>
        <span class="num">${note}</span></li>`;
    });
    body.innerHTML = out + "</ul>";
    for (const button of body.querySelectorAll("button[data-result]")) {
      button.onclick = () => highlight(results[Number(button.dataset.result)]);
    }
  } catch (error) {
    if (run === findRun) body.innerHTML = tmpl`<p class="empty">${error.message}</p>`;
  }
}

el["find-input"].addEventListener("input", scheduleFind);
el["find-form"].addEventListener("submit", (e) => { e.preventDefault(); clearTimeout(findTimer); runFind(); });

/* ---- maps pane --------------------------------------------------------- */

/* What an empty "fetch a named map" box means. Must match
 * `cache.DEFAULT_MAP_ID`; `tests/test_gui_server.py` asserts it, because the
 * only symptom of drift is a placeholder that lies about what blank does. */
const DEFAULT_MAP_ID = "fray";

/* What each kind is called on screen. `fetched` is the only one worth leaving
 * unlabelled - it is the ordinary case and saying so on every row is noise. */
/* **Which kind a map is, said in colour as well as in a word.** Four kinds
 * that mean four very different things - one came from source-chunk, three
 * this project made up - and a list of names alone made them look alike. The
 * tint comes from the palette already on screen rather than from four new
 * tokens: blue is what candidates are drawn in, green is a gain, amber is the
 * accent, and a fetched map is the plain case with no tint at all. */
const KIND_LABELS = {
  fetched: "Fetched",
  simulated: "Simulated",
  edited: "Edited",
};

function mapTip(entry) {
  const rows = [
    ["Kind", KIND_LABELS[entry.kind] || label(entry.kind)],
    ["Created", when(entry.created_at)],
    ["Size", bytes(entry.size)],
    ["Chunks", entry.unlocked_chunks == null ? "—" : entry.unlocked_chunks],
  ];
  if (entry.rolls != null) rows.push(["Rolls", entry.rolls]);
  if (entry.runs != null) rows.push(["Runs", entry.runs]);
  if (entry.seed != null) rows.push(["Seed", entry.seed]);
  if (entry.base_map) rows.push(["From", entry.base_map]);
  /* Which job produced it. Runs of one batch share this; two batches from the
   * same base map and the same seed do not. */
  if (entry.batch) rows.push(["Batch", entry.batch]);
  if (entry.batch_id) rows.push(["Job", entry.batch_id.slice(0, 8)]);
  return rows.map(([k, v]) => tmpl`<span class="sub">${k}: ${v}</span>`).join("");
}

/* **The two things every number in the panel rests on**, and neither is a map:
 * the 10MB chunk export (what exists at all) and the wiki rates (what anything
 * takes). They live in the Maps tab because this is where caching is done, and
 * they are listed with their age rather than hidden behind two anonymous
 * buttons - "when did I last scrape this" is the question you actually have.
 *
 * `refresh` comes from the server rather than a lookup table here: which action
 * refreshes which blob is one fact and belongs in one place. */
async function loadReference() {
  try {
    return (await getJSON("/api/reference")).reference || [];
  } catch {
    return [];
  }
}

/* What each reference blob is and what its absence costs, keyed by the blob's
 * own name rather than by an if-ladder - three of them was one too many for
 * the ternary this replaces. The "without it" line is the important half:
 * these are the inputs whose absence changes an estimate silently. */
const REFERENCE_TIPS = {
  chunkinfo: "<b>Chunk data</b><span class='sub'>The 10MB chunk export and the tasks map. Everything derived from them is recomputed after.</span>",
  wiki_rates: "<b>Wiki rates</b><span class='sub'>Quest lengths, money-making guides, slayer assignments and the community sheet. Thirty-odd requests.</span><span class='hint'>Without it every estimate falls back to a default</span>",
  wiki_recipes: "<b>Wiki recipes</b><span class='sub'>What one action of a training method pays and costs, per skill. Thirteen requests.</span><span class='hint'>Without it Construction has no rated method at all — 13,034h rather than 191h</span>",
};

function renderReference(rows) {
  const host = document.getElementById("reference");
  if (!host) return;
  host.innerHTML = rows.map((row) => {
    const state = row.cached
      ? tmpl`<span class="sub">${when(row.fetched_at)} · ${bytes(row.size)}</span>`
      : tmpl`<span class="sub warn-text">not cached</span>`;
    const tip = REFERENCE_TIPS[row.name] || tmpl`<b>${row.label}</b>`;
    return tmpl`<li data-tip="${tip}"><span class="name">${row.label}</span>${raw(state)}
      <button class="link" data-refresh="${row.refresh}">${row.cached ? "Refresh" : "Fetch"}</button></li>`;
  }).join("");
  for (const button of host.querySelectorAll("[data-refresh]")) {
    button.onclick = () => refreshReference(button.dataset.refresh);
  }
}

const REFRESH_LABELS = {
  heuristics: "Fetch wiki rates",
  recipes: "Fetch wiki recipes",
  chunkinfo: "Refresh chunk data",
};

function refreshReference(what) {
  const label = REFRESH_LABELS[what] || "Refresh reference data";
  return runAction(label, "/api/refresh", { what }, async () => {
    renderReference(await loadReference());
  });
}

/* **The boot warm-up, which is the page's idea rather than a press.**
 * `auto` lets the server refuse it - the blob is already there, or this server
 * run has tried once and failed - and a refusal must be silent, because
 * nobody asked. When it is *not* refused there is a real scrape behind it, so
 * that gets the same progress bar the button does. */
async function autoRefresh(what) {
  let reply;
  try {
    reply = await postJSON("/api/refresh", { what, auto: true });
  } catch (error) {
    return;
  }
  if (!reply || !reply.job) return;
  await followJob(reply.job, REFRESH_LABELS[what] || "Refresh reference data", async () => {
    renderReference(await loadReference());
  });
}

async function loadMapsPane() {
  const body = el["maps-body"];
  try {
    const maps = await getJSON("/api/maps");
    /* **The box is why this is not "Fetch This Map".** Any source-chunk map
     * id is a public read, so being able to pull down a friend's map - or one
     * you have never cached and so cannot select above - is the whole point.
     * Blank means `fray`, the same default every `--map` flag carries. */
    let out = `<h3>Actions</h3><div class="row">
      <input id="fetch-name" type="text" placeholder="${DEFAULT_MAP_ID}" autocomplete="off"
        aria-label="Map id to fetch" spellcheck="false"
        data-tip="<b>Map id on source-chunk</b><span class='sub'>The <code>?fray</code> part of the app's URL. Any id works, cached or not.</span><span class='hint'>Blank fetches ${DEFAULT_MAP_ID}</span>">
      <button id="do-fetch" type="button"
        data-tip="<b>Fetch a named map</b><span class='sub'>Read it from source-chunk and write it to cache/maps/fetched/. About a second.</span>">Fetch Named Map</button>
    </div>
    <h3>Reference data</h3><ul class="list" id="reference"></ul>
    <h3>Simulate</h3><div class="row">
      <input id="sim-rolls" type="number" min="1" value="5" style="width:7ch" aria-label="Rolls"
        data-tip="Chunks to roll in each run.">
      <input id="sim-runs" type="number" min="1" value="1" style="width:7ch" aria-label="Runs"
        data-tip="How many times to repeat the whole roll, each with its own seed.">
      <button id="do-sim" type="button"
        data-tip="Roll from this map and save the result as a new simulated map, opened as the map with its timeline.">Roll</button>
    </div>`;
    /* **A batch is one entry, not one per run.** `verf-sim/run-001` through
     * `run-040` is forty rows saying one thing, and the thing they say - "I
     * rolled this" - is the batch. The runs are still selectable in the
     * picker, which is where you go to look at one; here what you do with a
     * batch is remove it, and removing means choosing which runs. */
    const batches = maps.filter((m) => !m.map_id.includes("/"));
    const runsOfBatch = (id) => maps.filter((m) => m.map_id.startsWith(id + "/"));
    out += tmpl`<h3>Cached maps <span class="num">${batches.length}</span></h3><ul class="list">`;
    for (const m of batches) {
      const runs = runsOfBatch(m.map_id);
      /* Only a real batch says how many runs. A batch of one is a map as far
       * as anyone reading this list is concerned, so it says what a map says. */
      const note = runs.length > 1
        ? runs.length + " runs"
        : (m.unlocked_chunks == null ? "" : m.unlocked_chunks + " chunks");
      /* **A fetched map is removable too, and asks a harder question.** It
       * is upstream's state rather than something recomputable from what is
       * beside it, so the only way back is the network - which is a fine
       * answer and not a reason to leave the row without the control every
       * other row has. `include_fetched` is what the API wants to hear. */
      const remove = '<button class="link danger" data-rm="'
        + m.map_id.replace(/"/g, "&quot;") + '">Remove</button>';
      out += tmpl`<li data-tip="${mapTip(m)}"><span class="tag" data-kind="${m.kind}">${KIND_LABELS[m.kind] || label(m.kind)}</span>
        <span class="name">${m.map_id}</span><span class="num">${note}</span>${raw(remove)}</li>`;
    }
    out += `</ul><div class="actions">
      <button id="rm-sims" class="danger" type="button"
        data-tip="Delete every map this project computed — simulated and unlocked alike. Fetched maps are left alone.">Remove Computed Maps</button>
      <button id="prune" type="button"
        data-tip="Empty cache/derived/. Pure recomputation, so nothing is lost - the next command is just slower.">Clear Derived Cache</button>
    </div>`;
    body.innerHTML = out;

    const fetchName = document.getElementById("fetch-name");
    const doFetch = () => {
      const wanted = fetchName.value.trim() || DEFAULT_MAP_ID;
      /* `base` is ignored by an ordinary fetch - source-chunk has never heard
       * of whatever is open here - and read by exactly one thing, which is
       * `actions.UBER_MAP_SENTINEL`. Sent always so the box stays one control
       * rather than growing a mode. */
      runAction("Fetch " + wanted, "/api/fetch", { map: wanted, base: state.map },
        async (result) => {
        /* A map that was not cached before is now, so the picker is stale -
         * and selecting what you just asked for is what asking for it meant. */
        await loadMaps();
        /* A `<select>` silently blanks when handed a value it has no option
         * for, and a blank map id is what `loadView` refuses to draw. */
        if (result.map) openMap(result.map);
        syncBreakdown();
        await loadView({ refit: true });
        loadMapsPane();
      });
    };
    document.getElementById("do-fetch").onclick = doFetch;
    /* Enter in a lone text box means "do the thing next to it". Not a form,
     * because a form in the panel submits and navigates the whole window. */
    fetchName.onkeydown = (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      doFetch();
    };
    renderReference(await loadReference());
    document.getElementById("do-sim").onclick = () => {
      const rolls = Number(document.getElementById("sim-rolls").value) || 1;
      const runs = Number(document.getElementById("sim-runs").value) || 1;
      runAction(`Simulate ${rolls} rolls`, "/api/simulate",
        { map: state.map, name: state.map + "-sim", rolls, runs },
        async (result) => {
          /* **The result becomes the map, not the comparison.** It used to go
           * into the compare slot, which is exactly the state that hides the
           * timeline - so rolling a simulation hid the one thing you rolled it
           * to see. The base map moves to `compare` instead, which keeps the
           * "what did I gain" reading and adds the progression to it. */
          const base = state.map;
          await loadMaps();
          openMap(result.open);
          syncBreakdown();
          await loadTimeline();
          await loadView({ refit: true });
          await loadCandidates();
          await loadSections();
          loadMapsPane();
          if (base !== result.open) toast("Rolled from " + base + " — drag the slider to replay it");
        });
    };
    /* Whatever was removed, the list on screen is now wrong until it is read
     * again - and so is the map, if what went was the one being drawn. */
    const afterRemoval = async () => {
      await loadMaps();
      await loadMapsPane();
      await loadView();
    };

    for (const button of body.querySelectorAll("button[data-rm]")) {
      const kind = (batches.find((m) => m.map_id === button.dataset.rm) || {}).kind;
      button.onclick = () =>
        askRemoveBatch(button.dataset.rm, runsOfBatch(button.dataset.rm), afterRemoval, kind);
    }

    document.getElementById("rm-sims").onclick = async () => {
      /* Every kind this project computed, not just the rolled ones - an
       * unlocked map is equally disposable and equally in the way. */
      const doomed = maps.filter((m) => m.kind !== "fetched" && !m.map_id.includes("/"));
      if (!doomed.length) return toast("Nothing to remove — every cached map was fetched");
      const ok = await confirmAction(
        "Remove " + doomed.length + (doomed.length === 1 ? " computed map?" : " computed maps?"),
        tmpl`<p>Deletes every batch under <code>cache/maps/simulated/</code> and
          <code>cache/maps/edited/</code>. Fetched maps are left alone.</p><ul class="list">`
          + doomed.map((m) => tmpl`<li><span class="name">${m.map_id}</span>
              <span class="sub">${KIND_LABELS[m.kind] || m.kind}</span>
              <span class="num">${m.runs == null ? "" : m.runs + (m.runs === 1 ? " run" : " runs")}</span></li>`).join("")
          + "</ul>",
        "Remove all");
      if (ok) runAction("Remove simulated maps", "/api/maps/remove", { all: true }, afterRemoval);
    };
    document.getElementById("prune").onclick = () =>
      /* Not confirmed: `cache/derived/` is pure recomputation, so the cost of
       * being wrong is 0.9 seconds rather than a map you cannot get back. */
      runAction("Clear derived cache", "/api/derived/prune", {});
  } catch (error) {
    body.innerHTML = tmpl`<p class="empty">${error.message}</p>`;
  }
}

/* **Removing a batch is choosing which runs**, once there is more than one.
 * A forty-run batch is forty worlds and the interesting ones are usually a
 * handful; "Remove verf-sim?" offered all or nothing, which meant keeping the
 * other thirty-nine to save one. Each run keeps the tooltip it has in the
 * list, so hovering says what that run holds before you tick it. */
async function askRemoveBatch(name, runs, afterRemoval, kind) {
  const fetched = kind === "fetched";
  if (runs.length < 2) {
    const ok = await confirmAction(
      "Remove " + name + "?",
      fetched
        ? tmpl`<p>Deletes <code>cache/maps/fetched/${name}.json</code>. This one
            came from source-chunk rather than from anything here, so the only
            way back is <b>Fetch Named Map</b>.</p>`
        : tmpl`<p>Deletes its directory under <code>cache/maps/</code>. A simulated
            map can be rebuilt by running its seed again; nothing else brings it back.</p>`,
      "Remove");
    if (ok) {
      runAction("Remove " + name, "/api/maps/remove",
        { names: [name], include_fetched: fetched }, afterRemoval);
    }
    return;
  }
  const body = tmpl`<p><b>${name}</b> holds ${runs.length} runs. Removing all of
      them removes the batch.</p>
    <div class="row"><button id="rm-all" class="link" type="button">Select all</button>
      <button id="rm-none" class="link" type="button">Select none</button></div>
    <ul class="list" id="rm-runs">`
    + runs.map((r) => tmpl`<li data-tip="${mapTip(r)}">
        <input type="checkbox" class="rm-run" value="${r.map_id}" aria-label="${r.map_id}">
        <span class="name">${r.map_id.split("/")[1] || r.map_id}</span>
        <span class="num">${r.unlocked_chunks == null ? "" : r.unlocked_chunks + " chunks"}</span></li>`).join("")
    + "</ul>";
  const chosen = () => [...document.querySelectorAll("#rm-runs .rm-run:checked")].map((b) => b.value);
  const answer = confirmAction("Remove runs from " + name + "?", body, "Remove selected");
  /* Wired after the overlay is on screen: `confirmAction` renders it
   * synchronously and hands back a promise, so the nodes exist now. */
  const setAll = (on) => {
    for (const box of document.querySelectorAll("#rm-runs .rm-run")) box.checked = on;
  };
  document.getElementById("rm-all").onclick = () => setAll(true);
  document.getElementById("rm-none").onclick = () => setAll(false);
  if (!(await answer)) return;
  /* Read while the overlay is still in the DOM - hidden, not replaced. */
  const names = chosen();
  if (!names.length) return toast("Nothing selected");
  /* **All of them is the batch.** Removing every run one by one leaves the
   * batch directory behind with its `batch.json`, which then lists runs that
   * are gone. */
  const doomed = names.length === runs.length ? [name] : names;
  runAction("Remove " + doomed.length + " from " + name, "/api/maps/remove",
    { names: doomed }, afterRemoval);
}

/* ---- jobs -------------------------------------------------------------- */

/* **Three of the six actions finish before they answer, and pretending
 * otherwise is what broke the Maps tab.** `fetch`, `simulate` and `refresh`
 * hand back a job id to poll; `maps/remove`, `derived/prune` and `window` do
 * the work inline and hand back the result. The old code read `{ job }` off
 * every response, then polled `/api/jobs/undefined`, got a 404, and treated
 * that as "nothing more to say" - so the completion callback never ran and the
 * map list went on showing maps that were no longer on disk.
 *
 * So the shape of the reply decides: a job id means follow it, anything else
 * *is* the answer. */
function showProgress(title, { detail = "", done = 0, total = 0, state = "", job = "" } = {}) {
  el.progress.hidden = false;
  /* **Only while it is running, and only for work that can stop.** A button
   * that does nothing is worse than none, and the reply shape already tells
   * us which actions are jobs at all. */
  el["progress-cancel"].hidden = !job;
  el["progress-cancel"].dataset.job = job;
  el.progress.className = "progress" + (state ? " " + state : "");
  el["progress-title"].textContent = title;
  el["progress-count"].textContent = total ? done + "/" + total : "";
  el["progress-detail"].textContent = detail;
  /* A bar that cannot say how far along it is says so by moving instead of by
   * filling. Inventing a percentage would be the only dishonest option. */
  el["progress-track"].classList.toggle("indeterminate", !total);
  el["progress-fill"].style.width = total ? Math.round((done / total) * 100) + "%" : "";
}

el["progress-cancel"].addEventListener("click", async () => {
  const id = el["progress-cancel"].dataset.job;
  if (!id) return;
  el["progress-cancel"].hidden = true;
  /* The work stops where it safely can, so this only *asks* - `followJob`
   * keeps polling and reports whatever was kept. */
  try {
    await postJSON("/api/cancel", { job: id });
  } catch (error) {
    toast(error.message);
  }
});

function hideProgress(after) {
  clearTimeout(hideProgress.timer);
  hideProgress.timer = setTimeout(() => { el.progress.hidden = true; }, after);
}

/* `3/40 runs - ...` is the shape `batch.run_batch` reports, and it is the only
 * thing here that can drive a real bar. Anything else stays indeterminate
 * rather than being guessed at. */
function countsIn(text) {
  const match = /(\d+)\s*\/\s*(\d+)/.exec(text || "");
  return match ? { done: +match[1], total: +match[2] } : { done: 0, total: 0 };
}

/* What an inline action actually did, in the interface's own words. */
function summariseReply(reply) {
  if (!reply || typeof reply !== "object") return "Done";
  /* **The name a save claimed is not always the name it was asked for** -
   * `claim_batch` suffixes a clash `-2`, `-3`, … - so saying which one landed
   * is the whole reason a finished job reports anything but "Finished". */
  if (reply.chunk && reply.name) {
    return "Saved " + reply.name + " — +" + reply.tasks
      + (reply.tasks === 1 ? " task" : " tasks");
  }
  if (reply.batch) {
    if (reply.cancelled) {
      return "Stopped after " + reply.rolls + " of " + reply.rolls_requested
        + " rolls — " + (reply.runs ? reply.batch + " kept" : "nothing to keep");
    }
    return "Rolled " + reply.batch + " — " + reply.runs
      + (reply.runs === 1 ? " run" : " runs");
  }
  if (typeof reply.steps === "number" && typeof reply.hours === "number") {
    return "Priced " + reply.steps + " steps — " + hours(reply.hours) + " at the end";
  }
  if (reply.map && typeof reply.unlocked_chunks === "number") {
    return reply.map + " — " + reply.unlocked_chunks + " unlocked chunks";
  }
  /* The scrape knows how much it actually found, and "18 requests, 96 of them
   * 404s" is the difference between a total worth quoting and one that is
   * mostly defaults. Say it rather than "done". */
  if (reply.refreshed) return reply.summary || "Refreshed " + reply.refreshed;
  if (Array.isArray(reply.removed)) {
    return reply.removed.length
      ? "Removed " + reply.removed.length + (reply.removed.length === 1 ? " map" : " maps")
      : "Nothing to remove";
  }
  if (typeof reply.dropped === "number") {
    return "Dropped " + reply.dropped
      + (reply.dropped === 1 ? " cached derivation" : " cached derivations")
      + (reply.freed ? ", freeing " + bytes(reply.freed) : "");
  }
  return "Done";
}

async function runAction(label, path, payload, onDone) {
  clearTimeout(hideProgress.timer);
  showProgress(label, { detail: "Starting…" });
  let reply;
  try {
    reply = await postJSON(path, payload);
  } catch (error) {
    showProgress(label, { detail: error.message, state: "failed" });
    hideProgress(6000);
    return;
  }
  if (reply && reply.job) return followJob(reply.job, label, onDone);

  showProgress(label, { detail: summariseReply(reply), done: 1, total: 1, state: "done" });
  hideProgress(3200);
  await onDone?.(reply);
}

function followJob(id, label, onDone) {
  return new Promise((resolve) => {
    const timer = setInterval(async () => {
      let job;
      try {
        job = await getJSON("/api/jobs/" + id);
      } catch (error) {
        clearInterval(timer);
        showProgress(label, { detail: error.message, state: "failed" });
        hideProgress(6000);
        return resolve();
      }
      if (job.state === "running") {
        return showProgress(label, {
          detail: job.progress || "Working…",
          job: job.stopping ? "" : id,
          ...countsIn(job.progress),
        });
      }
      clearInterval(timer);
      if (job.state === "failed") {
        showProgress(label, { detail: job.error, state: "failed" });
        hideProgress(8000);
      } else if (job.state === "cancelled") {
        /* **Stopped is not failed.** The user did this, and what it kept is
         * cached and openable - so it reads as an outcome, not a red bar. */
        showProgress(label, {
          detail: summariseReply(job.result), done: 1, total: 1, state: "stopped",
        });
        hideProgress(5000);
        await onDone?.(job.result);
      } else {
        showProgress(label, {
          detail: summariseReply(job.result), done: 1, total: 1, state: "done",
        });
        hideProgress(3200);
        await onDone?.(job.result);
      }
      resolve();
    }, 400);
  });
}

/* ---- window geometry --------------------------------------------------- */

/* Only the page can see this: the server launched a browser and has no idea
 * what the user then did to the window. Reported here, read back by
 * `browser.window_flags` on the next launch - see gui/__init__.py for why
 * Chrome will not do it for us. */
let windowTimer = null;

function windowGeometry() {
  /* "Maximised" is a guess, and has to be: there is no API for it. Filling
   * the available work area within a few pixels is what maximising looks
   * like from in here, and being wrong costs one window opened the size it
   * was rather than snapped. */
  const maximised = Math.abs(window.outerWidth - screen.availWidth) < 24
    && Math.abs(window.outerHeight - screen.availHeight) < 24;
  return {
    width: window.outerWidth,
    height: window.outerHeight,
    x: window.screenX,
    y: window.screenY,
    maximised,
  };
}

function rememberWindow() {
  clearTimeout(windowTimer);
  windowTimer = setTimeout(() => {
    postJSON("/api/window", windowGeometry()).catch(() => {});
  }, 500);
}

window.addEventListener("pagehide", () => {
  /* A closing window has no time for a fetch, and this is the one report that
   * matters most - it is the geometry you left it at. `sendBeacon` is queued
   * by the browser and survives the page going away. */
  const blob = new Blob([JSON.stringify(windowGeometry())], { type: "application/json" });
  navigator.sendBeacon("/api/window", blob);
});

/* ---- boot -------------------------------------------------------------- */

/* The query string is the app's only deep link: `?map=&compare=&candidates=1`
 * reproduces a view, which is what makes a particular question shareable and
 * a screenshot reproducible. */
const PARAMS = new URLSearchParams(location.search);
const BOOT = {
  map: PARAMS.get("map") || "",
  compare: PARAMS.get("compare") || "",
  candidates: PARAMS.get("candidates") === "1",
  sections: PARAMS.get("sections") === "1",
  plane: PARAMS.get("plane") || "",
  tab: PARAMS.get("tab") || "",
  step: PARAMS.has("step") ? Number(PARAMS.get("step")) : null,
};

async function chooseMap(id) {
  /* **Asked before anything loads.** Declining has to leave the page as it
   * was, and half a load is not that. */
  if (!(await selectMap(id))) return;
  state.selected = null;
  taskPanel = null;
  /* Cleared *before* the view loads: a step index belongs to one run, and
   * carrying it across would rewind the new map to a roll it never had.
   * `setMode` does it, and does it for every other way in as well. */
  syncBreakdown();
  await loadTimeline();
  await loadView({ refit: true });
  await loadCandidates();
  await loadSections();
}

el.compare.addEventListener("change", async () => {
  /* Only reachable from inside Diff now, so an empty choice means "leave".
   * Read before the mode changes: leaving clears the comparison, which is
   * right when you are leaving and would eat the one you just picked. */
  const chosen = el.compare.value;
  if (!chosen) return exitMode();
  setMode("diff");
  setCompare(chosen);
  renderRibbon();
  syncBreakdown();
  /* Comparing is a question about two maps and stepping is a question about
   * one map's past. Picking a comparison answers the first, so the strip goes
   * and the rewind with it. */
  await loadTimeline();
  await loadView({ refit: true });
});
el.fit.addEventListener("click", () => fitToCells());

el.candidates.addEventListener("click", async () => {
  state.showCandidates = !state.showCandidates;
  el.candidates.setAttribute("aria-pressed", String(state.showCandidates));
  await loadCandidates();
});

el.masks.addEventListener("click", async () => {
  state.showMasks = !state.showMasks;
  el.masks.setAttribute("aria-pressed", String(state.showMasks));
  renderLegend();
  await loadSections();
});

/* **Changing the floor changes only the picture.** A chunk is a region and a
 * region has every plane in it, so the unlocked set, the hull and every panel
 * are the same on floor 3 as on floor 0 - it is the tiles underneath that
 * differ. Nothing is reloaded; the tile cache is keyed on the URL, which
 * carries the plane. */
el.plane.addEventListener("change", () => {
  state.plane = Number(el.plane.value) || 0;
  /* Nothing to clear: both caches key on a URL carrying the plane, so going
   * back to a floor you have already looked at is a redraw and no more. */
  invalidate();
});

el.live.addEventListener("click", () => {
  state.live = !state.live;
  el.live.setAttribute("aria-pressed", String(state.live));
});

/* ---- timeline ---------------------------------------------------------- */

/* **A simulated run's own history, replayed off its ledger.**
 *
 * `simulate` writes every roll to `rolls.json` and, until this, nothing read
 * it back - so a simulation could say where you would end up and not what
 * each roll bought you. Stepping is a JSON read rather than a derivation
 * (`timeline.py` recovers each state by subtracting the later rolls off the
 * final set), which is what lets the slider redraw as you drag it.
 *
 * Two series, both **deltas**: what that one roll added.
 *
 * - **Tasks** comes free. `unlock.delta_from` recorded it at roll time and it
 *   is already in the ledger.
 * - **Hours** does not. It needs `estimate` over a full derivation per step,
 *   and with the `dps` extra installed that is ~1.3s a step because the kill
 *   rates are recomputed from the map's own gear. So it is a button, paid
 *   once, stored beside the run, and a file read every time after.
 *
 * **Most hour bars are empty and some point down, and that is the data.**
 * Measured on the real 106-chunk map, ten rolls moved the estimate 2815.7h ->
 * 2817.4h with eight steps at exactly 0.0; on an early map it *falls* at one
 * step, because a new chunk can open a cheaper route to something you already
 * needed. So the axis draws its zero line and every step gets a hoverable
 * slot: an empty column has to read as "this chunk added no work" rather than
 * as a graph that failed to load. `hours: null` - nobody has computed them -
 * is drawn differently again, because "not computed" and "added nothing" are
 * different answers. */

/* Where the *linear* hours axis stops. A thousand is an hour figure you can
 * still reason about - a chunk worth 300h against one worth 900h - where the
 * rolls above it are all just "enormous" and their exact heights say nothing a
 * reader is comparing. See `tlBars`. */
const HOURS_CAP = 1000;

/* Where the *log* axis stops, and the decade lines drawn across it. Four
 * decades is the range the data actually occupies: measured over a 50-roll run
 * of the real map, rolls land anywhere from 0h to a few thousand, and a linear
 * axis spends the whole strip on the largest one. Ten thousand is past every
 * roll measured, so the clamp is a guard rather than a routine event. */
const HOURS_MAX = 10000;
const HOURS_TICKS = [10, 100, 1000, 10000];

/* **`log10(1 + v)`, not `log10(v)`.** Most rolls add exactly nothing and a
 * true log has nowhere to put them: `log10(0)` is minus infinity, and flooring
 * it at some epsilon would make "added nothing" and "added six minutes" the
 * same height. Adding one before the log lands 0 on the zero line honestly and
 * costs only that the first decade is slightly compressed - 10h sits at .26 of
 * the height rather than .25. The tick lines are drawn through this same
 * function, so what they mark is where the axis really is. */
function logFrac(value) {
  return Math.log10(1 + Math.min(Math.abs(value), HOURS_MAX)) / Math.log10(1 + HOURS_MAX);
}

const TL_SERIES = [
  ["tasks", "Tasks"],
  ["hours", "Hours"],
];

const TL_SCALES = [
  ["log", "Log"],
  ["linear", "Linear"],
];

let tlSeries = "tasks";

/* **Positional, not name-derived**, because the names are the user's to change
 * and a colour must not move when a label does. The stylesheet owns the five
 * hues and the page owns only which band a bar is in - the same division
 * `renderRibbon` keeps for the mode tints. */
function bandOf(value, bands) {
  if (!bands || !bands.length) return null;
  const magnitude = Math.abs(value);
  for (let index = 0; index < bands.length; index += 1) {
    const upto = bands[index].upto;
    if (upto === null || upto === undefined || magnitude < upto) return index;
  }
  return bands.length - 1;
}

/* The settings the server holds, or `null` until they arrive. **Null means no
 * banding and the linear axis**, rather than a second copy of the defaults
 * living here: two copies is how the page and the server come to disagree
 * about what "Grind" means. */
function tlSettings() { return state.settings; }
function tlBands() { return state.settings ? state.settings.hours_bands : null; }
function tlScale() { return state.settings ? state.settings.hours_scale : "linear"; }

async function loadSettings() {
  try {
    state.settings = await getJSON("/api/settings");
  } catch {
    /* A page that cannot read its preferences still draws; it just draws the
     * older axis with no colours. This is not worth a toast. */
    state.settings = null;
  }
}

async function saveSettings(patch) {
  state.settings = await postJSON("/api/settings", patch);
  renderTimeline();
}

async function loadTimeline() {
  if (!state.map) return hideTimeline();
  let payload;
  try {
    payload = await getJSON("/api/timeline?map=" + encodeURIComponent(state.map));
  } catch {
    /* A fetched map has no ledger, which is the ordinary case rather than a
     * failure. Anything else here is equally not worth a toast: the map is
     * still on screen and the strip is an extra. */
    return hideTimeline();
  }
  if (!payload.steps || payload.steps.length < 2) return hideTimeline();
  /* **Outside Timeline mode a ledger is a caption, not a history.** A batch of
   * one - a saved unlock, an edit - has exactly one roll, and its step is
   * pinned at the end so `/api/view` can say which chunk arrived; there is
   * nothing to drag, so there is no strip and no `state.timeline` for the
   * arrow keys to move.
   *
   * This is also what replaced `comparingNotice`. Hiding the strip because a
   * comparison was up made a working feature look broken, and the notice
   * existed to apologise for it. A simulation can no longer be compared at
   * all - `renderRibbon` disables the door - so the situation is gone rather
   * than explained. */
  if (state.mode !== "timeline") {
    state.timeline = null;
    state.step = payload.steps.length - 1;
    return hideStrip();
  }
  state.timeline = payload;
  if (state.step === null) state.step = payload.steps.length - 1;
  renderTimeline();
}

/* No ledger at all: nothing to draw and nothing to remember. */
function hideTimeline() {
  state.timeline = null;
  state.step = null;
  hideStrip();
}

/* The strip goes; whatever step is pinned stays. Split from `hideTimeline`
 * because "this map has no history" and "its history is not yours to drag
 * from here" are different states and used to be the same call. */
function hideStrip() {
  el.timeline.hidden = true;
  document.documentElement.style.setProperty("--strip-h", "0px");
}

function renderTimeline() {
  const payload = state.timeline;
  if (!payload) return hideTimeline();
  const steps = payload.steps;
  const last = steps.length - 1;
  state.step = Math.max(0, Math.min(last, state.step ?? last));
  const at = steps[state.step];

  el.timeline.hidden = false;
  /* **The panels describe the map, and a rewound map is not the map.** They
   * each need a derivation, so following the slider would cost ~1s a drag and
   * lose the whole reason stepping is instant. Saying which is being shown
   * beats a screen where the world and the panel beside it quietly disagree. */
  const behind = state.step < last;
  el["tl-title"].innerHTML = tmpl`Timeline<span class="sub">${last} ${last === 1 ? "roll" : "rolls"}${
    behind ? " · panels show the finished run" : ""}</span>`;

  el["tl-chips"].innerHTML = TL_SERIES.map(([key, name]) => {
    const on = tlSeries === key;
    const provenance = !payload.has_hours ? "Not computed yet"
      : payload.enriched ? "Priced from this map's own gear"
      : "Wiki rates — often zero, most chunks add no work";
    const tip = key === "hours"
      ? tmpl`<b>Hours added</b><span class="sub">What this roll newly put in front of you, assuming everything before it is done.</span><span class="hint">${provenance}</span>`
      : tmpl`<b>Tasks added</b><span class="sub">Challenges this roll made valid.</span>`;
    return tmpl`<button class="chip ${on ? "on" : ""}" data-series="${key}" data-tip="${tip}"
      role="radio" aria-checked="${on}">${name}</button>`;
  }).join("");
  for (const chip of el["tl-chips"].querySelectorAll("[data-series]")) {
    chip.onclick = () => { tlSeries = chip.dataset.series; renderTimeline(); };
  }

  /* **Only while hours are up**, because a log axis over a task count is an
   * answer to a question nobody asked - the counts share one unit and one
   * decade. The choice is stored rather than held here: it is a way of reading
   * the graph, not a place in it, so it should survive a reload. */
  const scaling = tlSeries === "hours" && tlSettings() !== null;
  el["tl-scale"].hidden = !scaling;
  if (scaling) {
    el["tl-scale"].innerHTML = TL_SCALES.map(([key, name]) => {
      const on = tlScale() === key;
      const tip = key === "log"
        ? tmpl`<b>Logarithmic</b><span class="sub">Four decades across the strip, so a 3h roll and a 300h roll are both readable.</span><span class="hint">Lines mark 10h, 100h, 1,000h and 10,000h</span>`
        : tmpl`<b>Linear</b><span class="sub">Scaled to the tallest bar, clipped at ${hours(HOURS_CAP)}.</span><span class="hint">One enormous roll flattens the rest</span>`;
      return tmpl`<button class="chip ${on ? "on" : ""}" data-scale="${key}" data-tip="${tip}"
        role="radio" aria-checked="${on}">${name}</button>`;
    }).join("");
    for (const chip of el["tl-scale"].querySelectorAll("[data-scale]")) {
      chip.onclick = () => saveSettings({ hours_scale: chip.dataset.scale });
    }
  }

  renderBandKey();

  /* **Two different offers, and neither is "compute it again".**
   *
   * A run now prices its own rolls as it rolls them - free, because the
   * derivation is already in hand - so `has_hours` is normally true the moment
   * a simulation finishes. What the button is for is the *upgrade*: with the
   * `dps` extra installed, `enrich` reprices every kill from the map's own BiS
   * gear, which costs ~1.3s a roll and is why a simulation does not do it. So
   * it appears when there is either nothing yet or something better to be had,
   * and says which. Once the numbers are enriched there is nothing left to
   * offer and it goes. */
  const upgrade = payload.has_hours && payload.can_enrich;
  el["tl-hours"].hidden = payload.has_hours && !payload.can_enrich;
  el["tl-hours"].lastChild.textContent = upgrade ? "Reprice with gear" : "Compute hours";
  el["tl-hours"].dataset.tip = upgrade
    ? tmpl`<b>Reprice from your gear</b><span class="sub">These hours came from the wiki's rates. The <code>dps</code> extra can cost each kill from the BiS gear this map actually reaches.</span><span class="hint">Spread across every core, then stored</span>`
    : tmpl`<b>Cost every step</b><span class="sub">Prices the world after each roll, then stores the answer beside the run.</span><span class="hint">Slow once, instant after</span>`;

  el["tl-graph"].innerHTML = tlBars(steps, tlSeries, state.step);
  for (const slot of el["tl-graph"].querySelectorAll("[data-step]")) {
    slot.onclick = () => goToRoll(Number(slot.dataset.step));
  }

  /* Step 0 is where the run started; it rolled nothing, so it has nothing to
   * break down. */
  el["tl-details"].hidden = !at.chunk;

  el["tl-slider"].max = String(last);
  el["tl-slider"].value = String(state.step);
  el["tl-prev"].disabled = state.step === 0;
  el["tl-next"].disabled = state.step === last;
  el["tl-step"].textContent = at.chunk
    ? `${state.step}/${last} · ${chunkLabel(at.chunk)}`
    : `start · ${at.unlocked_chunks}`;

  document.documentElement.style.setProperty(
    "--strip-h", el.timeline.offsetHeight + "px");
}

/* Bars on a zero line, in inline SVG - the same idiom as `donut`, and for the
 * same reason: no library, no build step, and the shape is four lines of
 * arithmetic. `viewBox` does the scaling, so the strip can be any width.
 *
 * The negative half is still drawn *if* anything is negative. Nothing is,
 * under the current semantics - a bar is what a roll cost and a roll cannot
 * cost less than nothing - but the axis costs nothing to keep honest and the
 * tasks series is not the only thing that could ever be plotted here. */
function tlBars(steps, key, current) {
  const W = 1000, H = 92, TOP = 6, FOOT = 6;
  const cols = steps.length - 1;                    // step 0 is a baseline
  if (cols < 1) return "";
  const width = W / cols;
  const known = steps.slice(1)
    .map((row) => row[key])
    .filter((v) => v !== null && v !== undefined);

  /* **The negative half is only reserved when something is negative.** Tasks
   * are never negative and hours usually are not, so a permanently centred
   * axis spent half the strip on empty space and halved the resolution of the
   * bars that are actually there. */
  const down = known.some((v) => v < 0);
  const base = down ? H * 0.62 : H - FOOT;
  /* Scale to the biggest swing either way, never to zero - an all-zero series
   * must draw a flat axis rather than divide by nothing.
   *
   * **And the hours axis stops at `HOURS_CAP`.** One roll opening a
   * 2,000-hour grind sets the scale for all fifty, and every other bar
   * becomes a line one pixel tall - the graph then answers "which roll was
   * the big one", which you could already see, and nothing else. Capping
   * makes the axis about the range a reader is comparing within; the rolls
   * past it are drawn full height and marked, because a bar that is merely
   * *at* the top and one that is off the end are different facts and the
   * tooltip carries the real number either way.
   *
   * Tasks are not capped: a roll opening 239 of them is a count in the same
   * units as a roll opening 2, and nothing about that range is unreadable. */
  const cap = key === "hours" ? HOURS_CAP : Infinity;
  const peak = Math.min(cap, Math.max(1e-9, ...known.map((v) => Math.abs(v))));
  const room = base - TOP;
  /* **Log for hours, linear for everything else.** Tasks are a count in one
   * unit and nothing about their range is unreadable; hours span four decades
   * within one run, which is the whole reason the axis had a cap to begin
   * with. `logFrac` returns a fraction of `room` directly, so there is no peak
   * to divide by and one enormous roll no longer sets the scale for fifty. */
  const log = key === "hours" && tlScale() === "log";
  const ceiling = log ? HOURS_MAX : peak;
  const height = (value) => (log
    ? logFrac(value) * room
    : Math.min(1, Math.abs(value) / peak) * room);
  const bands = key === "hours" ? tlBands() : null;

  let out = tmpl`<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img"
    aria-label="${key === "hours" ? "Hours added per roll" : "Tasks added per roll"}">`;
  /* **Under the bars, so a decade line never cuts across one.** Drawn before
   * the slots too, which keeps the hit areas on top of everything and the
   * tooltip working over a gridline. */
  if (log) {
    for (const tick of HOURS_TICKS) {
      const y = base - logFrac(tick) * room;
      out += tmpl`<line class="tl-grid" x1="0" y1="${y}" x2="${W}" y2="${y}"/>`;
      /* The top line sits at `TOP`, so its label has nowhere to go above it -
       * it would render outside the viewBox and be cut in half. Only that one
       * hangs below its line; the rest sit on top, where they do not collide
       * with the line above. */
      const above = y - TOP > 10;
      out += tmpl`<text class="tl-zero-label" x="4" y="${above ? y - 2 : y + 9}">${
        tick >= 1000 ? `${tick / 1000}k` : String(tick)}h</text>`;
    }
  }
  steps.slice(1).forEach((row, index) => {
    const x = index * width;
    const value = row[key];
    const at = index + 1 === current;
    out += tmpl`<rect class="tl-slot ${at ? "at" : ""}" data-step="${index + 1}"
      x="${x}" y="0" width="${width}" height="${H}" data-tip="${tlTip(row, key)}"/>`;
    if (value !== null && value !== undefined) {
      /* A zero still gets a sliver, so the axis reads as a row of steps that
       * each happened rather than as a gap where the graph stops. */
      const over = Math.abs(value) > ceiling;
      const size = Math.max(1.5, height(value));
      const negative = value < 0;
      const band = bands === null ? null : bandOf(value, bands);
      out += tmpl`<rect class="tl-bar ${negative ? "down" : ""} ${value === 0 ? "flat" : ""} ${over ? "over" : ""}"
        data-band="${band === null ? "" : String(band)}"
        x="${x + width * 0.18}" y="${negative ? base : base - size}"
        width="${width * 0.64}" height="${size}" rx="1"/>`;
    }
    /* Where you are, as a tick under the column rather than a block over it -
     * a full-height wash competed with the bars it was meant to point at. */
    if (at) {
      out += tmpl`<rect class="tl-at-mark" x="${x + width * 0.12}" y="${H - 3}"
        width="${width * 0.76}" height="3" rx="1.5"/>`;
    }
  });
  out += tmpl`<line class="tl-zero" x1="0" y1="${base}" x2="${W}" y2="${base}"/>`;
  if (key === "hours" && !known.length) {
    out += tmpl`<text class="tl-pending" x="${W / 2}" y="${base - 14}"
      text-anchor="middle">Press Compute hours to price each roll</text>`;
  }
  return out + "</svg>";
}

/* **The key to the colours, and the way into changing them.**
 *
 * It is its own strip under the graph rather than an entry in `#legend`: that
 * one belongs to the map, is anchored to the top of the window, and
 * `test_the_bottom_edge_is_shared_rather_than_stacked` pins it there. This one
 * belongs to a graph that is only sometimes on screen.
 *
 * The swatches carry no colour of their own - each is `data-band="n"` and the
 * stylesheet fills it, which is the same division the ribbon's mode tints
 * keep. A user-editable *palette* is the thing that would break it, and is why
 * the bands are five with movable edges rather than a list you can extend. */
function renderBandKey() {
  const bands = tlBands();
  const showing = tlSeries === "hours" && bands !== null;
  el["tl-key"].hidden = !showing;
  if (!showing) return;
  el["tl-key"].innerHTML = bands.map((band, index) => tmpl`<span class="tl-band"
    data-tip="${tmpl`<b>${band.name}</b><span class="sub">${bandRange(bands, index)}</span><span class="hint">Click to change the thresholds</span>`}"
    ><i class="tl-sw" data-band="${String(index)}"></i>${band.name}</span>`).join("")
    + tmpl`<button id="tl-bands" class="tl-band-edit" type="button"
      data-tip="${tmpl`<b>Time bands</b><span class="sub">Where each colour starts and what it is called.</span>`}"
      >Edit</button>`;
  document.getElementById("tl-bands").onclick = editBands;
}

/* "10h - 100h", and the two ends said in words rather than with a dangling
 * bound: the first band has no floor to name and the last has no ceiling. */
function bandRange(bands, index) {
  const below = index === 0 ? null : bands[index - 1].upto;
  const upto = bands[index].upto;
  if (upto === null || upto === undefined) return `${hours(below)} and up`;
  if (below === null) return `Under ${hours(upto)}`;
  return `${hours(below)} to ${hours(upto)}`;
}

/* **The thresholds, edited as the ordered partition they are.** The last band
 * has no bound to edit - it is what everything above the fourth threshold
 * falls into - so it gets its name and nothing else. The server validates all
 * of this again and refuses the lot if any of it is wrong; this half exists to
 * make that refusal rare rather than to be trusted. */
function editBands() {
  const bands = tlBands();
  if (!bands) return;
  /* **`raw` because this is element content, never an attribute.** The bound
   * half is markup either way - a `<span>` or an `<input>` - and `tmpl` would
   * escape it into the visible text of the dialog. Everything user-supplied
   * inside it is still interpolated by the inner `tmpl`, which escapes it. */
  const bound = (band, index) => (band.upto === null || band.upto === undefined
    ? tmpl`<span class="band-open">and above</span>`
    : tmpl`<span class="band-under">under</span><input class="band-upto" data-index="${String(index)}"
         type="number" min="0" step="any" value="${String(band.upto)}"
         aria-label="Band ${index + 1} upper bound"><span class="band-unit">h</span>`);
  const rows = bands.map((band, index) => tmpl`<div class="band-row">
    <i class="tl-sw" data-band="${String(index)}"></i>
    <input class="band-name" data-index="${String(index)}" type="text" maxlength="24"
           value="${band.name}" aria-label="Band ${index + 1} name">
    ${raw(bound(band, index))}
  </div>`).join("");
  openOverlay("Time bands", tmpl`<p class="hint">Each band ends where the next begins, so the
    numbers must climb. The colours are fixed; the names and the edges are not.</p>`
    + `<div class="band-edit">${rows}</div>`,
    tmpl`<button id="band-reset" type="button">Reset</button>
      <button id="band-cancel" type="button">Cancel</button>
      <button id="band-save" type="button">Save</button>`);

  const read = () => bands.map((band, index) => {
    const name = document.querySelector(`.band-name[data-index="${index}"]`).value;
    const bound = document.querySelector(`.band-upto[data-index="${index}"]`);
    return { name, upto: bound === null ? null : Number(bound.value) };
  });
  document.getElementById("band-cancel").onclick = closeOverlay;
  /* **Asked for by name, not by sending an empty list.** A list `sanitise`
   * refuses leaves the stored bands exactly where they were, which is the
   * opposite of a reset - so the request has to say which key to forget. */
  document.getElementById("band-reset").onclick = () => applyBands({ reset: ["hours_bands"] });
  document.getElementById("band-save").onclick = () => applyBands({ hours_bands: read() });
}

/* **A refusal has to be visible, and the server refuses silently by design.**
 * `settings.sanitise` keeps the stored value when a new one does not validate,
 * which is right - it will not clamp what you typed into something you did not
 * ask for - but it answers 200 either way. So the reply is compared with what
 * was sent, and a patch that did not take keeps the dialog open with the
 * reason. Closing on a no-op would look exactly like success. */
async function applyBands(patch) {
  try {
    await saveSettings(patch);
    const wanted = patch.hours_bands;
    if (wanted && !sameBands(wanted, tlBands())) {
      toast("Thresholds must climb, and each band needs a name");
      return;
    }
    closeOverlay();
  } catch (error) {
    toast(String(error.message || error));
  }
}

function sameBands(a, b) {
  return Array.isArray(a) && Array.isArray(b) && a.length === b.length
    && a.every((band, index) => band.name.trim().slice(0, 24) === b[index].name
      && (band.upto ?? null) === (b[index].upto ?? null));
}

function tlTip(row, key) {
  const head = tmpl`<b>Roll ${row.step} · ${chunkLabel(row.chunk)}</b>`;
  /* **The overlay's own headings, with the overlay's own counts.** This read
   * the raw ledger per skill while the panel under it showed the filtered
   * set, so a column said `Cooking: 3` and opening it showed nothing at all.
   * After the filter a skill contributes at most one row, so per-skill would
   * be a list of ones anyway - the sections are what a reader is matching up.
   * See `routes_view.panel_counts`. */
  const groups = Object.entries(row.tasks_by_group || {});
  const breakdown = groups.length
    ? groups.map(([name, n]) => tmpl`<span class="sub">${name}: ${n}</span>`).join("")
    : tmpl`<span class="sub">Nothing new here</span>`;
  if (key !== "hours") {
    /* **The rolls, not the whole world.** `unlocked_chunks` counts the base
     * map too, so the first roll of a simulation from a 106-chunk map read
     * "106 chunks after this roll" - true, and not what the timeline is
     * about. What this roll is one *of* is the run's own progress. */
    const rolled = row.step === 1 ? "1 chunk rolled so far" : `${row.step} chunks rolled so far`;
    return head + breakdown + tmpl`<span class="hint">${rolled}</span>`;
  }
  if (row.hours === null || row.hours === undefined) {
    return head + tmpl`<span class="sub">Hours not computed yet</span>`;
  }
  /* **Never negative under this model**, so there is no minus case to word.
   * A roll that only made old work cheaper added nothing; the saving is not
   * something this roll did, because by now that work is behind you. */
  const bands = tlBands();
  const band = bands === null ? null : bands[bandOf(row.hours, bands)];
  const change = row.hours === 0
    ? tmpl`<span class="sub">Added no work</span>`
    : tmpl`<span class="sub">${hours(row.hours)} of new work${
        band ? ` \u00b7 ${band.name}` : ""}</span>`;
  /* The bar is as tall as the axis goes and the number is not - say so, or a
   * roll at exactly the cap and one at four times it look identical. */
  const ceiling = tlScale() === "log" ? HOURS_MAX : HOURS_CAP;
  const clipped = Math.abs(row.hours) > ceiling
    ? tmpl`<span class="sub">Bar clipped at ${hours(ceiling)}</span>` : "";
  /* **"Open", not "left".** This is the whole outstanding estimate for the
   * world after this roll - the Estimate tab's own number - so it *grows*
   * along a run, because unlocking a chunk adds work. Worded as "left" it read
   * as a burn-down and looked like a sign error; it is not one, and the only
   * thing that ever brings it down is a chunk opening a cheaper route to work
   * you already had. */
  const open = row.total_hours == null ? ""
    : tmpl`<span class="hint">${hours(row.total_hours)} of work open after this roll</span>`;
  return head + change + clipped + open;
}

/* Clicking a column is "take me to that roll": the slider moves, the chunk it
 * rolled is selected, and the camera flies to it. The breakdown is a separate
 * control rather than this same click, because a dialog would cover the map it
 * had just framed. */
async function goToRoll(step) {
  await setStep(step);
  const at = state.timeline && state.timeline.steps[step];
  if (at && at.chunk) {
    await selectChunk(at.chunk);
    focusChunk(at.chunk);
  }
}

/* **The names are not in `/api/timeline`.** One roll of the real export opened
 * 239 tasks, so every name for every step would be most of a megabyte spent to
 * draw a bar chart. `/api/roll` is the same ledger read, one step at a time,
 * and only when somebody asks to see it. */
async function showRoll(step) {
  const title = "Roll " + step;
  openOverlay(title, tmpl`<p class="empty">Reading the ledger…</p>`);
  let roll;
  try {
    roll = await getJSON("/api/roll?map=" + encodeURIComponent(state.map) + "&step=" + step);
  } catch (error) {
    return openOverlay(title, tmpl`<p class="empty">${error.message}</p>`);
  }
  const sections = (roll.panel || {}).sections || [];
  let out = tmpl`<dl class="kv">
    <dt>Chunk</dt><dd>${chunkLabel(roll.chunk)}</dd>
    <dt>Tasks</dt><dd>${roll.tasks}</dd>
    <dt>Sections</dt><dd>${roll.sections}</dd>
    <dt>BiS upgrades</dt><dd>${roll.bis_upgrades}</dd></dl>`;

  out += rollHours(roll.hours);

  /* **The Tasks tab's own renderer, over this roll's additions.** Same
   * envelope from `panels.py`, same `renderTaskGroups` drawing it - so a
   * Construction chunk shows the furthest build rather than all sixty, and a
   * name is spelled the way the tab spells it. Not tickable: these rows
   * record what a past state opened, so there is nothing to write. */
  const shaped = renderTaskGroups(sections, "active", "roll");
  /* **"Opened nothing" and "opened nothing better" are different answers**,
   * and on a mature map the second is the common one - the header says
   * `Tasks 12` either way, so one message for both reads as a contradiction.
   * See `panels._roll_classification` for what "better" means. */
  out += shaped || (roll.tasks
    ? tmpl`<p class="empty">Nothing this roll opened is ahead of what the run
        already had — ${roll.tasks} task${roll.tasks === 1 ? "" : "s"}, all of
        them at or below a level it has already passed.</p>`
    : tmpl`<p class="empty">This roll opened no new tasks.</p>`);
  openOverlay(
    "Roll " + step + " · " + chunkLabel(roll.chunk),
    out,
    tmpl`<button id="roll-focus" type="button">Show on map</button>`,
  );
  document.getElementById("roll-focus").onclick = () => {
    closeOverlay();
    goToRoll(step);
  };
  ownsMore("roll", () => showRoll(step));
}

/* **What this roll cost, drawn the way the Estimate tab draws the total.**
 * Same `donut`, same bucket colours, same "biggest first" ordering, because it
 * is the same estimator answering a narrower question - the buckets here are
 * `timeline.added_estimate`, this roll's own additions rather than everything
 * outstanding.
 *
 * The per-item rows are what the bar chart cannot show: a roll worth 3,050h is
 * a number until you see that 343h of it is one harpoon. Items carry the tasks
 * they answer, because the same drop usually satisfies several and charging it
 * once is the estimator's own rule.
 *
 * Absent when the server could not price it - no export, no scraped rates, or
 * step 0, which is a baseline and not a roll. The overlay then reads exactly as
 * it did before this existed. */
/* **Why a skill costs what it costs**, which is the question a four-figure
 * number always provokes. Hours are `xp to the goal / xp per hour`, so the
 * tooltip states both halves and then where the rate came from.
 *
 * A climb is priced band by band as methods unlock, so the headline rate is a
 * *blend* - Herblore's 131,080/hr is nine methods averaged and nobody trains at
 * it. The bands are therefore the tooltip's main content, each with the level
 * range it covers and where its rate came from; the band carrying the bulk of
 * the XP is the one worth arguing with. `heuristics/overrides.json` is where
 * you disagree with any of them. */
function skillTip(row) {
  const num = (value) => Math.round(Number(value) || 0).toLocaleString();
  const head = tmpl`<b>${row.skill} · ${hours(row.hours)}</b>`;
  const from = row.effective_level || row.current_level;
  const climb = tmpl`<span class="sub">Level ${from} → ${row.target_level} · ${num(row.xp)} xp to earn</span>`;
  /* Only say "starting you at X rather than Y" when the grant actually moves
   * the level - most of the time it is a few thousand XP into a high skill and
   * lands in the same band it started in. */
  const quest = !row.xp_from_quests
    ? ""
    : from !== row.current_level
      ? tmpl`<span class="sub">${num(row.xp_from_quests)} xp of it paid by quests, starting you at ${from} rather than ${row.current_level}</span>`
      : tmpl`<span class="sub">${num(row.xp_from_quests)} xp of it paid by quests this map can finish</span>`;

  /* **The bands are the answer to "why so long".** A blended rate is not a
   * rate anybody trains at - Herblore's 131,000/hr is fourteen methods
   * averaged - so the row that matters is whichever band carries the bulk of
   * the XP, and the provenance beside it says how much to trust it. */
  const bands = row.bands || [];
  if (bands.length > 1) {
    const rows = bands
      .map((b) => tmpl`<span class="sub">${b.level_from}–${b.level_to} · ${hours(b.hours)} · ${num(b.xp_per_hour)}/hr · ${b.method || "no rate known"}${b.match === "exact" ? "" : " (" + b.match + ")"}</span>`)
      .join("");
    const floored = bands.filter((b) => b.match === "default");
    const note = floored.length
      ? tmpl`<span class="hint">${num(row.floor_xp)} xp of this has no known rate and sits at the floor</span>`
      : tmpl`<span class="hint">Blended ${num(row.xp_per_hour)}/hr across ${bands.length} methods</span>`;
    return head + climb + quest + rows + note;
  }

  const rate = row.defaulted
    ? tmpl`<span class="sub">${num(row.xp_per_hour)} xp/hr — the default floor, because nothing trainable here has a known rate</span>`
    : tmpl`<span class="sub">${num(row.xp_per_hour)} xp/hr via ${row.method}</span>`;
  const options = row.options || [];
  if (!options.length) {
    return head + climb + quest + rate + tmpl`<span class="hint">No method on this map has a rate — set one in heuristics/overrides.json</span>`;
  }
  const known = options
    .map((o) => tmpl`<span class="sub">${num(o.xp_per_hour)}/hr · level ${o.level ?? "?"} · ${o.method}</span>`)
    .join("");
  const more = row.options_total > options.length
    ? tmpl`<span class="hint">${row.options_total} known in all — correct any in heuristics/overrides.json</span>`
    : tmpl`<span class="hint">Correct any of these in heuristics/overrides.json</span>`;
  return head + climb + quest + rate + tmpl`<span class="sub">Known methods for this skill:</span>` + known + more;
}


function rollHours(priced) {
  if (!hours || !priced.total_hours) return "";
  const ordered = Object.entries(priced.buckets)
    .filter(([, value]) => value > 0)
    .sort((a, b) => b[1] - a[1]);
  if (!ordered.length) return "";

  let out = tmpl`<h3>Hours this roll added <span class="num">${hours(priced.total_hours)}</span></h3>`;
  out += '<div class="pie-row">' + donut(ordered, priced.total_hours) + '<div class="pie-key">';
  for (const [name, value] of ordered) {
    const tip = tmpl`<b>${label(name)}</b><span class="sub">${hours(value)} · ${Math.round((value / priced.total_hours) * 100)}% of this roll</span>`;
    out += tmpl`<span data-tip="${tip}"><i class="sw" style="background:${BUCKET_COLOURS[name] || "#858d9c"}"></i>${label(name)}</span>`;
  }
  out += "</div></div>";

  /* **Per item, not per task**, and the difference is the estimator's: one
   * whip answers three tasks and you obtain one whip, so charging per task
   * would triple it. The tasks ride along in the tooltip, which is where "why
   * am I doing this" belongs. */
  const rows = (priced.items || []).filter((row) => row.hours > 0);
  if (rows.length) {
    out += tmpl`<h3>Longest to obtain <span class="num">${rows.length}</span></h3><ul class="list">`;
    out += withMore(rows, "roll:hours", 10, (row) => {
      const tip = tmpl`<b>${row.item}</b><span class="sub">${label(row.bucket)}${row.source ? " · from " + row.source : ""}</span><span class="hint">${row.tasks.join(", ")}</span>`;
      return tmpl`<li data-tip="${tip}"><span class="name">${row.item}</span><span class="num">${hours(row.hours)}</span></li>`;
    });
    out += "</ul>";
  }

  const quests = (priced.quests || []).filter((row) => row.hours > 0);
  if (quests.length) {
    out += tmpl`<h3>Quests <span class="num">${quests.length}</span></h3><ul class="list">`;
    out += withMore(quests, "roll:quests", 10, (row) =>
      tmpl`<li data-tip="${tmpl`<b>${row.task}</b><span class="sub">${row.detail || ""}</span>`}"><span class="name">${row.task}</span><span class="num">${hours(row.hours)}</span></li>`);
    out += "</ul>";
  }

  const skills = priced.skills || [];
  if (skills.length) {
    out += tmpl`<h3>Skilling <span class="num">${skills.length}</span></h3><ul class="list">`;
    out += withMore(skills, "roll:skills", 10, (row) =>
      tmpl`<li data-tip="${skillTip(row)}"><span class="name">${row.skill}</span><span class="num">${hours(row.hours)}</span></li>`);
    out += "</ul>";
  }
  return out;
}

async function setStep(step) {
  if (!state.timeline) return;
  const last = state.timeline.steps.length - 1;
  state.step = Math.max(0, Math.min(last, step));
  renderTimeline();
  await loadView();
}

el["tl-slider"].addEventListener("input", () => setStep(Number(el["tl-slider"].value)));
el["tl-prev"].addEventListener("click", () => setStep((state.step ?? 0) - 1));
el["tl-next"].addEventListener("click", () => setStep((state.step ?? 0) + 1));

el["tl-collapse"].addEventListener("click", () => {
  const shut = el.timeline.classList.toggle("shut");
  el["tl-collapse"].setAttribute("aria-expanded", String(!shut));
  el["tl-collapse"].querySelector("use").setAttribute("href", shut ? "#i-up" : "#i-down");
  document.documentElement.style.setProperty("--strip-h", el.timeline.offsetHeight + "px");
});

/* **A snapshot is the way out of a timeline**, so it asks for a name the way
 * every other map-making action does and opens what it claimed. Step 0 is a
 * baseline rather than a roll - it *is* the base map - so it is refused here
 * rather than writing a copy of something that already exists. */
el["tl-snapshot"].addEventListener("click", () => {
  const step = state.step ?? 0;
  if (!state.timeline || step < 1) { toast("Step 0 is the base map — drag to a roll first"); return; }
  const suggested = state.map.replace(/\//g, "-") + "-at-" + step;
  openOverlay("Snapshot roll " + step,
    tmpl`<p>Writes the world after roll ${step} of <b>${state.map}</b> as a map
      of its own, carrying that much of the run's history. It browses, edits
      and diffs like any other map; nothing existing is touched.</p>
      <div class="row"><input id="snap-name" type="text" value="${suggested}"
        aria-label="Name for the new map" spellcheck="false" autocomplete="off"
        data-tip="<b>Name for the new map</b><span class='sub'>A name already in use gains <code>-2</code>, <code>-3</code>, … rather than overwriting.</span>"></div>`,
    tmpl`<button id="snap-no" type="button">Cancel</button>
      <button id="snap-yes" type="button">Snapshot</button>`);
  const field = document.getElementById("snap-name");
  const go = () => {
    const name = field.value.trim() || suggested;
    closeOverlay();
    runAction("Snapshot " + name, "/api/snapshot", { map: state.map, step, name },
      async (result) => {
        await loadMaps();
        if (result.open) openMap(result.open);
        syncBreakdown();
        await loadTimeline();
        await loadView({ refit: true });
        await loadCandidates();
        await loadSections();
        loadMapsPane();
      });
  };
  document.getElementById("snap-no").onclick = closeOverlay;
  document.getElementById("snap-yes").onclick = go;
  field.onkeydown = (event) => { if (event.key === "Enter") { event.preventDefault(); go(); } };
  field.focus();
  field.select();
});

el["tl-details"].addEventListener("click", () => {
  if (state.timeline && state.step) showRoll(state.step);
});

el["tl-hours"].addEventListener("click", () => {
  const map = state.map;
  runAction("Cost " + map, "/api/timeline", { map }, async () => {
    await loadTimeline();
  });
});

async function poll() {
  renderBuild();
  if (!state.live || !state.view || !state.map) return;
  try {
    const { revision } = await getJSON("/api/revision?" + mapQuery());
    if (revision !== state.revision) { taskPanel = null; await loadView(); }
  } catch { /* a map deleted under us; the next load reports it */ }
}

/* Which region belongs to which named place. Static per export and map
 * independent, so it is asked for once and never invalidated - a new export
 * arrives through `fray chunkinfo`, which restarts nothing but does reset
 * `Derivations`, and a reload picks it up. */
/* **"Mount Karuulm (5179)" wherever a bare id was.** The id is what you paste
 * into `fray unlock` and what the export keys on, so it never goes away; the
 * name is what you are actually looking at. Falls back to the bare id when the
 * export names neither a `Nickname` nor a `Name`, which is most of the sea.
 *
 * Not used in the chunk panel: that shows the name as its heading and the id
 * beneath, so a combined label there would print one of them twice. */
function chunkLabel(chunkId) {
  if (!chunkId) return "";
  const name = state.labels[chunkId];
  return name ? `${name} (${chunkId})` : String(chunkId);
}

async function loadAreas() {
  try {
    const payload = await getJSON("/api/areas");
    state.areas = payload.areas || {};
    state.labels = payload.labels || {};
    invalidate();
    /* **The names arrive after the first paint**, deliberately - the map draws
     * without them and boot does not wait on a 30KB read. Anything already on
     * screen that writes a chunk id has to be told, or the strip keeps the bare
     * number until the next thing that happens to redraw it. */
    if (state.timeline) renderTimeline();
  } catch {
    /* Labels are an improvement, not a precondition: the map draws without
     * them and every id still works. */
  }
}

/* Ask the server *where* the tiles are - not for the tiles. See `drawTiles`. */
async function loadTiles() {
  try {
    const source = await getJSON("/api/tiles");
    Object.assign(tiles, source);
    if (source.error) toast(source.error);
    if (!source.version) return false;
  } catch (error) {
    tiles.error = error.message;
    toast("Could not find the map tiles: " + error.message);
    return false;
  }
  renderAttribution();
  invalidate();
  return true;
}

/* CC BY-NC-SA asks for attribution, and this is the whole of what that costs
 * when you link rather than copy. */
function renderAttribution() {
  if (!tiles.attribution) return;
  el.attribution.innerHTML = tmpl`<a href="${tiles.attribution_url || "#"}" target="_blank" rel="noreferrer">${tiles.attribution}</a>`;
  el.attribution.hidden = false;
}

(async function start() {
  resize();
  renderRibbon();
  /* Before `loadTimeline`, because the graph reads the scale and the bands out
   * of them and would otherwise draw once uncoloured and again a moment
   * later. */
  await loadSettings();
  if (!(await loadMaps())) return;
  syncBreakdown();
  await loadTimeline();
  if (BOOT.step !== null && state.timeline) {
    /* Set rather than `setStep`, which would draw the view a second time. */
    state.step = Math.max(0, Math.min(state.timeline.steps.length - 1, BOOT.step));
    renderTimeline();
  }
  await loadView();
  await loadTiles();
  fitToCells();
  loadAreas();
  if (BOOT.plane) { el.plane.value = BOOT.plane; el.plane.dispatchEvent(new Event("change")); }
  if (BOOT.candidates) el.candidates.click();
  if (BOOT.sections) el.masks.click();
  showTab(BOOT.tab || "tasks");
  setInterval(poll, 2000);
  loadBuild();
  warmReference();
})();

/* **Fetch the wiki rates once, on open, if they have never been fetched.**
 * Without them every hour in the Estimate tab falls back to a default and the
 * total is thousands of hours light - and the panel would say so in small
 * print while showing a confident-looking number. Eighteen requests is a fair
 * price for that not being the first impression.
 *
 * Only when *missing*, never on a schedule: a re-scrape is a decision, and the
 * Maps tab has the button for it. The chunk export is deliberately not fetched
 * here either - at 10MB it is `fray chunkinfo`'s to start, and the panels that
 * need it already say so when it is absent. */
/* **Which install is serving this page.** `pipx install` without `--force` is
 * a silent no-op, so the code behind this page can be older than the checkout
 * it was built from - and nothing on screen would say so. Read from the server
 * rather than baked into this file at build time, because with `--host` the
 * browser may be on a different machine from the one being edited: the answer
 * has to be the *server's*.
 *
 * Fetched once. The relative age is re-rendered from the stamp on every poll,
 * or a tab left open all afternoon would still be claiming the install
 * happened a minute ago. */
async function loadBuild() {
  try { state.build = await getJSON("/api/build"); } catch { return; }
  renderBuild();
}

function renderBuild() {
  const build = state.build;
  if (!build) return;
  const age = build.kind === "editable" ? `editable, linked ${ago(build.installed_at)}`
            : build.kind === "source" ? "uninstalled source"
            : `installed ${ago(build.installed_at)}`;
  el.watermark.textContent = `${build.version} · ${age}`;
  el.watermark.dataset.tip = tmpl`<b>This server's install</b><span class='sub'>${when(build.installed_at)} · ${build.kind}</span><span class='hint'>${build.path}</span>`;
  el.watermark.hidden = false;
}

async function warmReference() {
  const rows = await loadReference();
  renderReference(rows);
  /* **Both scrapes, and for the same reason.** Without the rates every hour
   * falls back to a default; without the recipes Construction has no rated
   * method at all and reads 13,034h. Either way the panel would put small
   * print beside a confident-looking number, which is a poor first impression
   * to buy for one fetch. The 10MB export is still deliberately not fetched
   * this way - that is `fray chunkinfo`'s to start.
   *
   * The `!row.cached` test is a courtesy, not the guard: it saves a round
   * trip, but reloading the tab mid-scrape would still ask again, so the
   * decision is the server's. See `autoRefresh` and `actions._refresh_job`. */
  for (const [name, what] of [["wiki_rates", "heuristics"], ["wiki_recipes", "recipes"]]) {
    const row = rows.find((entry) => entry.name === name);
    if (row && !row.cached) await autoRefresh(what);
  }
}
