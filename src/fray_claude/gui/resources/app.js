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

/* Upstream's own wash, so a screenshot of either is recognisably the same map. */
const LOCKED_WASH = "rgba(150, 150, 150, 0.6)";
const ADDED_FILL = "rgba(60, 200, 90, 0.45)";
const REMOVED_FILL = "rgba(220, 60, 60, 0.45)";
const CANDIDATE_FILL = "rgba(90, 190, 255, 0.34)";
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
  view: null,
  cells: new Map(),        // "gx,gy" -> cell, for the locked-wash complement
  candidates: new Map(),   // chunk id -> neighbour entry
  found: new Set(),        // chunk ids highlighted by a search
  sections: {},            // chunk id -> {section: reachable}, for the masks
  areas: {},               // chunk id -> named area, for labels and the readout
  selected: null,
  hovered: null,
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
};

const el = {};
for (const id of [
  "map", "compare", "breakdown", "plane", "candidates", "masks", "live", "fit", "counts", "skipped",
  "hover", "toggle-panel", "panel", "tabs", "toast", "legend", "tip",
  "progress", "progress-title", "progress-count", "progress-detail",
  "progress-track", "progress-fill",
  "overlay", "overlay-title", "overlay-body", "overlay-close", "overlay-actions",
  "chunk-head", "chunk-chips", "chunk-body", "task-chips", "tasks-body",
  "show-done", "estimate-total", "estimate-why", "estimate-body",
  "find-body", "find-form", "find-input", "maps-body", "attribution",
  "timeline", "tl-title", "tl-chips", "tl-hours", "tl-collapse", "tl-graph",
  "tl-prev", "tl-slider", "tl-next", "tl-step",
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
  const pan = easeOutBack(t), scale = easeOutCubic(t);
  const { from, to } = glide;
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
  const target = centredOn(chunkId, clamp(zoom || state.zoom, MIN_ZOOM, MAX_ZOOM));
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
  drawTiles, drawLockedWash, drawGrid, drawStates, drawMasks, drawFound,
  drawCandidates, drawHull, drawAreas, drawHovered, drawSelected,
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

function panelWidth() {
  return el.panel.classList.contains("hidden") ? 0 : el.panel.offsetWidth;
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
  else if (e.key === "p") el["toggle-panel"].click();
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
  const bits = [chunkId];
  /* The name first among the words, because "Kurask Lair" is what you are
   * looking for and the id is what you paste into `fray unlock`. */
  if (state.areas[chunkId]) bits.push(state.areas[chunkId]);
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

function when(iso) {
  if (!iso) return "unknown";
  const at = new Date(iso);
  return Number.isNaN(at.valueOf()) ? iso : at.toLocaleString();
}

function showTab(name) {
  for (const b of el.tabs.querySelectorAll("button")) {
    b.classList.toggle("on", b.dataset.tab === name);
  }
  for (const p of document.querySelectorAll(".pane")) {
    p.classList.toggle("on", p.dataset.pane === name);
  }
  el.panel.classList.remove("hidden");
  if (name === "tasks") loadTasks();
  if (name === "estimate") loadEstimate();
  if (name === "maps") loadMapsPane();
}

el.tabs.addEventListener("click", (e) => {
  const button = e.target.closest("button[data-tab]");
  if (button) showTab(button.dataset.tab);
});

el["toggle-panel"].addEventListener("click", () => {
  const hidden = el.panel.classList.toggle("hidden");
  /* Everything anchored to the right of the *map* reads `--rail`, so the
   * progress card and the attribution slide out with the panel instead of
   * hanging over the gap it left. */
  document.body.classList.toggle("no-panel", hidden);
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
function confirmAction(title, body, verb) {
  return new Promise((resolve) => {
    openOverlay(title, body, tmpl`<button id="confirm-no" type="button">Cancel</button>
      <button id="confirm-yes" class="danger" type="button">${verb}</button>`);
    closeOverlay.pending = resolve;
    const answer = (value) => { closeOverlay.pending = null; el.overlay.hidden = true; resolve(value); };
    document.getElementById("confirm-no").onclick = () => answer(false);
    const yes = document.getElementById("confirm-yes");
    yes.onclick = () => answer(true);
    yes.focus();
  });
}

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

function mapQuery() {
  const params = new URLSearchParams({ map: el.map.value });
  /* **A step and a comparison are exclusive**, and the step wins because it
   * is the thing you just dragged. Two maps and a rewind would need a third
   * colour for "gained by this roll but lost against the other side", which
   * is a question nobody asked. `renderTimeline` hides the strip while a
   * comparison is up, so this branch is belt and braces. */
  if (state.step !== null) params.set("step", String(state.step));
  else if (el.compare.value) params.set("compare", el.compare.value);
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

async function loadMaps() {
  const maps = await getJSON("/api/maps");
  if (!maps.length) {
    /* An empty screen is an invitation to act. The first build showed a blank
     * dropdown and "missing required parameter 'map'", which is a dead end. */
    el.map.innerHTML = "<option value=''>No maps cached</option>";
    el.counts.textContent = "";
    el["chunk-body"].innerHTML = tmpl`<p class="empty">Nothing cached yet. Run <code>fray fetch</code> in a terminal, or press <b>Fetch Named Map</b> on the Maps tab.</p>`;
    showTab("maps");
    return false;
  }
  const options = mapOptions(maps);
  const keepMap = el.map.value, keepCompare = el.compare.value;
  el.map.innerHTML = options;
  el.compare.innerHTML = "<option value=''>—</option>" + options;
  el.map.value = BOOT.map || keepMap || maps[0].map_id;
  if (!el.map.value) el.map.value = maps[0].map_id;
  el.compare.value = BOOT.compare || keepCompare || "";
  BOOT.map = BOOT.compare = "";
  return true;
}

async function loadView({ refit = false } = {}) {
  if (!el.map.value) return;
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
      const payload = await getJSON("/api/neighbours?map=" + encodeURIComponent(el.map.value));
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
  if (!state.showMasks || !el.map.value) { state.sections = {}; return; }
  try {
    const payload = await getJSON("/api/sections?map=" + encodeURIComponent(el.map.value));
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
  el["chunk-body"].innerHTML = tmpl`<p class="empty">Reading ${chunkId}…</p>`;
  try {
    chunkDetail = await getJSON(
      "/api/chunk?map=" + encodeURIComponent(el.map.value) +
      "&chunk=" + encodeURIComponent(chunkId));
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
  const offer = detail.unlocked ? "" : tmpl`
      <button id="what-if" type="button"
        data-tip="<b>What would this add?</b><span class='sub'>Sections, tasks and BiS upgrades this chunk would bring, without saving anything.</span>">What would this add?</button>
      <button id="do-unlock" type="button"
        data-tip="<b>Unlock this chunk</b><span class='sub'>Save a new map with this chunk added by hand, the way <code>fray unlock --cache-map</code> does.</span>">Unlock</button>`;

  el["chunk-head"].innerHTML = tmpl`<h3>${detail.nickname || "Chunk " + detail.chunk_id}</h3>
    <div class="row"><code>${detail.chunk_id}</code>${raw(status)}
      <span class="spacer"></span>
      <button id="chunk-focus" type="button"
        data-tip="<b>Focus</b><span class='sub'>Centre the map on this chunk.</span><span class='hint'>F</span>">Focus</button>
      ${raw(offer)}
    </div>`;
  document.getElementById("chunk-focus").onclick = () => focusChunk(detail.chunk_id);
  const whatIf = document.getElementById("what-if");
  if (whatIf) whatIf.onclick = () => previewUnlock(detail.chunk_id);
  const unlockNow = document.getElementById("do-unlock");
  if (unlockNow) unlockNow.onclick = () => askUnlock(detail.chunk_id);

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
    /* One category selected is a list; several need saying which is which. */
    if (showing.length === 1) return body;
    const count = key === SECTIONS_CHIP ? detail.sections.length : detail.contents[key].length;
    return tmpl`<h3>${categoryLabel(key)} <span class="num">${count}</span></h3>` + body;
  }).join("");
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
 * take eight clicks. */
function applyChipGesture(off, key, keys, event) {
  if (event.shiftKey) return off.delete(key);
  if (event.ctrlKey || event.metaKey) return off.add(key);
  off.clear();
  for (const other of keys) if (other !== key) off.add(other);
}

const CHIP_HINT = "Click for only this · shift adds · ctrl removes";

function renderSections(detail) {
  if (!detail.sections.length) return tmpl`<p class="empty">This chunk is not split.</p>`;
  let out = "<ul class='list'>";
  for (const section of detail.sections) {
    const tip = section.section === "0"
      ? "Section 0 opens with the chunk itself."
      : (section.reachable
          ? "Opened by a link from a section you already reach."
          : "Needs a link from somewhere you have not unlocked yet.");
    out += tmpl`<li data-tip="${tip}"><span class="name">Section ${section.section}</span>
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
  let out = "<ul class='list'>";
  for (const row of rows) {
    const where = row.sections.length > 1 || row.sections[0] !== "0"
      ? row.sections.join(", ") : "";
    const tip = tmpl`<b>${plain(row.name)}</b><span class="sub">${
      row.sections.length === 1 ? "Section " + row.sections[0] : "Sections " + row.sections.join(", ")
    }</span><span class="sub">${row.reachable
      ? "You can reach this"
      : "Behind a section you have not opened"}</span>`;
    out += tmpl`<li class="${row.reachable ? "" : "unreached"}" data-tip="${tip}">
      <span class="name">${plain(row.name)}</span>
      <span class="num">${where}</span></li>`;
  }
  return out + "</ul>";
}

async function previewUnlock(chunkId) {
  openOverlay("If you unlocked " + chunkId, tmpl`<p class="empty">Deriving both worlds…</p>`);
  try {
    const delta = await getJSON(
      "/api/unlock?map=" + encodeURIComponent(el.map.value) +
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
  const suggested = (el.map.value || DEFAULT_MAP_ID).replace(/\//g, "-") + "-" + chunkId;
  openOverlay("Unlock " + chunkId,
    tmpl`<p>Writes a new map under <code>cache/maps/unlocked/</code> holding
      everything <b>${el.map.value}</b> holds plus this chunk. Nothing existing
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
    runAction("Unlock " + chunkId, "/api/unlock",
      { map: el.map.value, chunk: chunkId, name },
      async (result) => {
        /* Compare rather than select: what you want to see next is what the
         * chunk *changed*, and that is the delta against where you started. */
        await loadMaps();
        if (result.open) el.compare.value = result.open;
        syncBreakdown();
        await loadView();
        loadMapsPane();
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
  const from = el.map.value, to = el.compare.value;
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
  el.breakdown.disabled = !el.map.value || !el.compare.value;
}

/* ---- tasks pane -------------------------------------------------------- */

const GROUP_ICONS = {
  "Collection Log": "log",
  "Permanent Unlockables": "unlock",
  "Untracked Uniques": "star",
  "Ungrouped": "dot",
};

let taskPanel = null;
/* Which task categories are switched *off*. The five answer one question
 * between them - "what is left" - so they all show until you say otherwise. */
const taskOff = new Set();

async function loadTasks() {
  if (taskPanel && taskPanel.map_id === el.map.value) return renderTasks();
  el["tasks-body"].innerHTML = tmpl`<p class="empty">Deriving…</p>`;
  try {
    taskPanel = await getJSON("/api/tasks?map=" + encodeURIComponent(el.map.value));
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

  let out = "";
  for (const section of showing) {
    const groups = section.groups.filter((g) => g[side].length);
    if (!groups.length) continue;
    /* The section's own heading, once several are on screen at a time. With
     * one selected the chip already says which, and repeating it costs a row
     * of a 360px panel. */
    if (showing.length > 1) {
      const total = groups.reduce((n, g) => n + g[side].length, 0);
      out += tmpl`<h3 class="section">${section.label} <span class="num">${total}</span></h3>`;
    }
    for (const group of groups) {
      /* A single group whose name repeats the heading is a heading twice. */
      if (groups.length > 1 || group.name !== section.label) {
        out += tmpl`<h3>${raw(GROUP_ICONS[group.name] ? icon(GROUP_ICONS[group.name]).__raw + " " : "")}${group.name} <span class="num">${group[side].length}</span></h3>`;
      }
      out += "<ul class='list'>";
      for (const row of group[side]) {
        const badge = row.icon
          ? tmpl`<img class="skill-icon" src="/assets/skill/${row.icon}.png" alt="${row.icon}">`
          : "";
        /* The row shows the subject; the tooltip shows the whole task as the
         * export writes it, which is what `fray tasks` prints and what you
         * would search for. */
        const tip = tmpl`<b>${plain(row.name)}</b>`
          + (row.note ? tmpl`<span class="sub">${plain(row.note)}</span>` : "")
          + tmpl`<span class="hint">${plain(row.key)}</span>`;
        out += tmpl`<li data-tip="${tip}">${raw(badge)}<span class="name">${plain(row.name)}</span>
          <span class="sub">${plain(row.note || "")}</span></li>`;
      }
      out += "</ul>";
    }
  }
  el["tasks-body"].innerHTML = out ||
    tmpl`<p class="empty">Nothing ${state.showDone ? "completed" : "outstanding"} here.</p>`;
}

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
    estimatePayload = await getJSON("/api/estimate?map=" + encodeURIComponent(el.map.value));
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
        const tip = tmpl`<b>${skill.skill}</b><span class="sub">Level ${skill.current_level} to ${skill.target_level}</span><span class="sub">${hours(skill.hours)} at the rate this map can reach</span>`;
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
      "&map=" + encodeURIComponent(el.map.value) + "&limit=40");
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
const KIND_LABELS = {
  fetched: "Fetched",
  simulated: "Simulated",
  unlocked: "Unlocked",
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

function renderReference(rows) {
  const host = document.getElementById("reference");
  if (!host) return;
  host.innerHTML = rows.map((row) => {
    const state = row.cached
      ? tmpl`<span class="sub">${when(row.fetched_at)} · ${bytes(row.size)}</span>`
      : tmpl`<span class="sub warn-text">not cached</span>`;
    const tip = row.name === "wiki_rates"
      ? tmpl`<b>Wiki rates</b><span class="sub">Quest lengths, money-making guides, slayer assignments and the community sheet. About eighteen requests.</span><span class="hint">Without it every estimate falls back to a default</span>`
      : tmpl`<b>Chunk data</b><span class="sub">The 10MB chunk export and the tasks map. Everything derived from them is recomputed after.</span>`;
    return tmpl`<li data-tip="${tip}"><span class="name">${row.label}</span>${raw(state)}
      <button class="link" data-refresh="${row.refresh}">${row.cached ? "Refresh" : "Fetch"}</button></li>`;
  }).join("");
  for (const button of host.querySelectorAll("[data-refresh]")) {
    button.onclick = () => refreshReference(button.dataset.refresh);
  }
}

function refreshReference(what) {
  const label = what === "heuristics" ? "Fetch wiki rates" : "Refresh chunk data";
  return runAction(label, "/api/refresh", { what }, async () => {
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
        data-tip="Roll from this map and save the result as a new simulated map, opened as a comparison.">Roll</button>
    </div>`;
    out += tmpl`<h3>Cached maps <span class="num">${maps.length}</span></h3><ul class="list">`;
    for (const m of maps) {
      const note = m.unlocked_chunks == null ? (KIND_LABELS[m.kind] || label(m.kind)) : m.unlocked_chunks + " chunks";
      const remove = m.kind === "fetched" ? "" :
        '<button class="link danger" data-rm="' + m.map_id.replace(/"/g, "&quot;") + '">Remove</button>';
      out += tmpl`<li data-tip="${mapTip(m)}"><span class="name">${m.map_id}</span><span class="num">${note}</span>${raw(remove)}</li>`;
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
      runAction("Fetch " + wanted, "/api/fetch", { map: wanted }, async (result) => {
        /* A map that was not cached before is now, so the picker is stale -
         * and selecting what you just asked for is what asking for it meant. */
        await loadMaps();
        /* A `<select>` silently blanks when handed a value it has no option
         * for, and a blank map id is what `loadView` refuses to draw. */
        if (result.map) el.map.value = result.map;
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
        { map: el.map.value, name: el.map.value + "-sim", rolls, runs },
        async (result) => {
          /* **The result becomes the map, not the comparison.** It used to go
           * into the compare slot, which is exactly the state that hides the
           * timeline - so rolling a simulation hid the one thing you rolled it
           * to see. The base map moves to `compare` instead, which keeps the
           * "what did I gain" reading and adds the progression to it. */
          const base = el.map.value;
          await loadMaps();
          el.map.value = result.open;
          el.compare.value = "";
          state.step = null;
          state.timeline = null;
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
      button.onclick = async () => {
        const name = button.dataset.rm;
        const ok = await confirmAction(
          "Remove " + name + "?",
          tmpl`<p>Deletes its directory under <code>cache/sims/</code>. A simulated
            map can be rebuilt by running its seed again; nothing else brings it back.</p>`,
          "Remove");
        if (ok) runAction("Remove " + name, "/api/maps/remove", { names: [name] }, afterRemoval);
      };
    }

    document.getElementById("rm-sims").onclick = async () => {
      /* Every kind this project computed, not just the rolled ones - an
       * unlocked map is equally disposable and equally in the way. */
      const doomed = maps.filter((m) => m.kind !== "fetched" && !m.map_id.includes("/"));
      if (!doomed.length) return toast("Nothing to remove — every cached map was fetched");
      const ok = await confirmAction(
        "Remove " + doomed.length + (doomed.length === 1 ? " computed map?" : " computed maps?"),
        tmpl`<p>Deletes every batch under <code>cache/maps/simulated/</code> and
          <code>cache/maps/unlocked/</code>. Fetched maps are left alone.</p><ul class="list">`
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
function showProgress(title, { detail = "", done = 0, total = 0, state = "" } = {}) {
  el.progress.hidden = false;
  el.progress.className = "progress" + (state ? " " + state : "");
  el["progress-title"].textContent = title;
  el["progress-count"].textContent = total ? done + "/" + total : "";
  el["progress-detail"].textContent = detail;
  /* A bar that cannot say how far along it is says so by moving instead of by
   * filling. Inventing a percentage would be the only dishonest option. */
  el["progress-track"].classList.toggle("indeterminate", !total);
  el["progress-fill"].style.width = total ? Math.round((done / total) * 100) + "%" : "";
}

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
          ...countsIn(job.progress),
        });
      }
      clearInterval(timer);
      if (job.state === "failed") {
        showProgress(label, { detail: job.error, state: "failed" });
        hideProgress(8000);
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

el.map.addEventListener("change", async () => {
  state.selected = null;
  taskPanel = null;
  /* Cleared *before* the view loads: a step index belongs to one run, and
   * carrying it across would rewind the new map to a roll it never had. */
  state.step = null;
  state.timeline = null;
  syncBreakdown();
  await loadTimeline();
  await loadView({ refit: true });
  await loadCandidates();
  await loadSections();
});
el.compare.addEventListener("change", async () => {
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

const TL_SERIES = [
  ["tasks", "Tasks"],
  ["hours", "Hours"],
];

let tlSeries = "tasks";

async function loadTimeline() {
  /* A comparison and a rewind are exclusive - see `mapQuery`. */
  if (!el.map.value || el.compare.value) return hideTimeline();
  try {
    state.timeline = await getJSON("/api/timeline?map=" + encodeURIComponent(el.map.value));
  } catch {
    /* A fetched map has no ledger, which is the ordinary case rather than a
     * failure. Anything else here is equally not worth a toast: the map is
     * still on screen and the strip is an extra. */
    return hideTimeline();
  }
  if (!state.timeline.steps || state.timeline.steps.length < 2) return hideTimeline();
  if (state.step === null) state.step = state.timeline.steps.length - 1;
  renderTimeline();
}

function hideTimeline() {
  state.timeline = null;
  state.step = null;
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
    slot.onclick = () => setStep(Number(slot.dataset.step));
  }

  el["tl-slider"].max = String(last);
  el["tl-slider"].value = String(state.step);
  el["tl-prev"].disabled = state.step === 0;
  el["tl-next"].disabled = state.step === last;
  el["tl-step"].textContent = at.chunk
    ? `${state.step}/${last} · ${at.chunk}`
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
   * must draw a flat axis rather than divide by nothing. */
  const peak = Math.max(1e-9, ...known.map((v) => Math.abs(v)));
  const room = base - TOP;

  let out = tmpl`<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img"
    aria-label="${key === "hours" ? "Hours added per roll" : "Tasks added per roll"}">`;
  steps.slice(1).forEach((row, index) => {
    const x = index * width;
    const value = row[key];
    const at = index + 1 === current;
    out += tmpl`<rect class="tl-slot ${at ? "at" : ""}" data-step="${index + 1}"
      x="${x}" y="0" width="${width}" height="${H}" data-tip="${tlTip(row, key)}"/>`;
    if (value !== null && value !== undefined) {
      /* A zero still gets a sliver, so the axis reads as a row of steps that
       * each happened rather than as a gap where the graph stops. */
      const size = Math.max(1.5, (Math.abs(value) / peak) * room);
      const negative = value < 0;
      out += tmpl`<rect class="tl-bar ${negative ? "down" : ""} ${value === 0 ? "flat" : ""}"
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

function tlTip(row, key) {
  const head = tmpl`<b>Roll ${row.step} · ${row.chunk}</b>`;
  const skills = Object.entries(row.tasks_by_skill || {});
  const breakdown = skills.length
    ? skills.map(([skill, n]) => tmpl`<span class="sub">${skill}: ${n}</span>`).join("")
    : tmpl`<span class="sub">No new tasks</span>`;
  if (key !== "hours") {
    return head + breakdown + tmpl`<span class="hint">${row.unlocked_chunks} chunks after this roll</span>`;
  }
  if (row.hours === null || row.hours === undefined) {
    return head + tmpl`<span class="sub">Hours not computed yet</span>`;
  }
  /* **Never negative under this model**, so there is no minus case to word.
   * A roll that only made old work cheaper added nothing; the saving is not
   * something this roll did, because by now that work is behind you. */
  const change = row.hours === 0
    ? tmpl`<span class="sub">Added no work</span>`
    : tmpl`<span class="sub">${hours(row.hours)} of new work</span>`;
  const left = row.total_hours == null ? ""
    : tmpl`<span class="hint">${hours(row.total_hours)} left after this roll</span>`;
  return head + change + left;
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

el["tl-hours"].addEventListener("click", () => {
  const map = el.map.value;
  runAction("Cost " + map, "/api/timeline", { map }, async () => {
    await loadTimeline();
  });
});

async function poll() {
  if (!state.live || !state.view || !el.map.value) return;
  try {
    const { revision } = await getJSON("/api/revision?" + mapQuery());
    if (revision !== state.revision) { taskPanel = null; await loadView(); }
  } catch { /* a map deleted under us; the next load reports it */ }
}

/* Which region belongs to which named place. Static per export and map
 * independent, so it is asked for once and never invalidated - a new export
 * arrives through `fray chunkinfo`, which restarts nothing but does reset
 * `Derivations`, and a reload picks it up. */
async function loadAreas() {
  try {
    const payload = await getJSON("/api/areas");
    state.areas = payload.areas || {};
    invalidate();
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
async function warmReference() {
  const rows = await loadReference();
  renderReference(rows);
  const rates = rows.find((row) => row.name === "wiki_rates");
  if (rates && !rates.cached) await refreshReference("heuristics");
}
