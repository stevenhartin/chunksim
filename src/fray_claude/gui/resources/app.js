"use strict";
/* The world map canvas, and the panel beside it.
 *
 * One classic script, no modules, no build step, no CDN. The zero-dependency
 * rule is about what a user has to install, and shipping a bundler would break
 * its spirit even though npm is not pip.
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

/* Upstream clamps at 0.2, which is too high here: the whole 9216x6528 map needs
 * 0.138 to fit a 1600x900 window, so at 0.2 you could never see the world at
 * once and a sparse map would open already clipped. */
const MIN_ZOOM = 0.08;
const MAX_ZOOM = 3.5;
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

/* Section shading, and the two colours the plan asked for. Kept low-alpha
 * because the map underneath is the thing being annotated. */
const SECTION_REACHED = { fill: "rgba(60, 200, 90, 0.30)", edge: "rgba(90, 255, 130, 0.95)" };
const SECTION_LOCKED = { fill: "rgba(220, 60, 60, 0.28)", edge: "rgba(255, 110, 110, 0.9)" };

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
  selected: null,
  hovered: null,
  image: null,
  panX: 0, panY: 0, zoom: 0.5,
  needsDraw: false,
  live: true,
  showCandidates: false,
  showMasks: false,
  showDone: false,
  revision: null,
};

const el = {};
for (const id of [
  "map", "compare", "candidates", "masks", "live", "fit", "counts", "skipped",
  "hover", "toggle-panel", "panel", "tabs", "job", "toast", "legend", "tip",
  "overlay", "overlay-title", "overlay-body", "overlay-close",
  "chunk-head", "chunk-chips", "chunk-body", "task-chips", "tasks-body",
  "show-done", "estimate-total", "estimate-why", "estimate-body",
  "find-body", "find-form", "find-input", "maps-body",
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
function gridToChunk(gx, gy) { return String((gx + 15) * 256 + (65 - gy)); }

function chunkToGrid(chunkId) {
  const id = Number(chunkId);
  if (!Number.isFinite(id)) return null;
  const gx = (id >> 8) - 15, gy = 65 - (id & 0xff);
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
 * scale gets a plain decelerating curve. */
const GLIDE_MS = 420;
const BACK = 1.7;

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
  for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) r.drawImage(image, dx, dy);
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

/* Which squares are worth shading: the one you selected, always, plus every
 * split chunk on screen once a chunk is big enough for its sections to be
 * legible. */
function maskTargets() {
  const size = cellSize();
  const wanted = [];
  if (state.selected && state.sections[state.selected]) wanted.push(state.selected);
  if (size >= MASK_MIN_CELL) {
    for (const chunkId of Object.keys(state.sections)) {
      if (chunkId === state.selected) continue;
      const at = chunkToGrid(chunkId);
      if (!at) continue;
      const [x, y] = toScreen(at[0], at[1]);
      if (onScreen(x, y, size)) wanted.push(chunkId);
      if (wanted.length >= MASK_MAX_CHUNKS) break;
    }
  }
  return wanted;
}

/* ---- drawing ----------------------------------------------------------- */

/* An ordered list, which is the extension point: the planned roll heatmaps are
 * one more entry plus one key in view.overlays, and nothing about pan, zoom or
 * the hull has to change. */
const LAYERS = [
  drawBase, drawLockedWash, drawGrid, drawStates, drawMasks, drawFound,
  drawCandidates, drawHull, drawHovered, drawSelected,
];

function drawBase() {
  if (!state.image) return;
  const { image_width: w, image_height: h } = state.view.geometry;
  CTX.drawImage(state.image, state.panX, state.panY, state.zoom * w, state.zoom * h);
}

function onScreen(x, y, size) {
  return !(x > CANVAS.clientWidth || y > CANVAS.clientHeight || x + size < 0 || y + size < 0);
}

function drawLockedWash() {
  const { grid_columns: cols, grid_rows: rows } = state.view.geometry;
  const size = cellSize();
  CTX.fillStyle = LOCKED_WASH;
  for (let gx = 0; gx < cols; gx++) {
    for (let gy = 0; gy < rows; gy++) {
      if (state.cells.has(gx + "," + gy)) continue;
      const [x, y] = toScreen(gx, gy);
      if (onScreen(x, y, size)) CTX.fillRect(x, y, size, size);
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
  for (const chunkId of maskTargets()) {
    const at = chunkToGrid(chunkId);
    if (!at) continue;
    const [x, y] = toScreen(at[0], at[1]);
    for (const [section, reachable] of Object.entries(state.sections[chunkId])) {
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
  /* The map is pixel art at 3px per game tile; smoothing turns it to mush. */
  CTX.imageSmoothingEnabled = false;
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

function fitBox(minX, minY, maxX, maxY, cell) {
  /* Leave room for the bar and the panel, so a fit never puts part of the
   * shape underneath either of them. */
  const availW = CANVAS.clientWidth - panelWidth() - 80;
  const availH = CANVAS.clientHeight - 100;
  stopGlide();
  state.zoom = clamp(
    Math.min(availW / ((maxX - minX) * cell), availH / ((maxY - minY) * cell)),
    MIN_ZOOM, MAX_ZOOM,
  );
  const size = state.zoom * cell;
  state.panX = (availW - (maxX - minX) * size) / 2 + 40 - minX * size;
  state.panY = (availH - (maxY - minY) * size) / 2 + 60 - minY * size;
  invalidate();
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
  if (cell) bits.push(cell.state);
  if (candidate) bits.push("#" + candidate.number);
  el.hover.textContent = bits.join("  ");
}

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
  el.panel.classList.toggle("hidden");
  el.job.style.right = el.panel.classList.contains("hidden") ? "0" : "";
});

function toast(message) {
  el.toast.textContent = message;
  el.toast.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { el.toast.hidden = true; }, 2400);
}

/* One dialog, reused. An answer you asked a question to get needs somewhere
 * to live that is not "instead of the thing you were reading". */
function openOverlay(title, html) {
  el["overlay-title"].textContent = title;
  el["overlay-body"].innerHTML = html;
  el.overlay.hidden = false;
}

function closeOverlay() { el.overlay.hidden = true; }

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
  if (el.compare.value) params.set("compare", el.compare.value);
  return params.toString();
}

async function loadMaps() {
  const maps = await getJSON("/api/maps");
  if (!maps.length) {
    /* An empty screen is an invitation to act. The first build showed a blank
     * dropdown and "missing required parameter 'map'", which is a dead end. */
    el.map.innerHTML = "<option value=''>No maps cached</option>";
    el.counts.textContent = "";
    el["chunk-body"].innerHTML = tmpl`<p class="empty">Nothing cached yet. Run <code>fray fetch</code> in a terminal, or press <b>Fetch This Map</b> on the Maps tab.</p>`;
    showTab("maps");
    return false;
  }
  const options = maps.map((m) => tmpl`<option value="${m.map_id}">${m.map_id}${m.kind === "fetched" ? "" : "  (" + label(m.kind) + ")"}</option>`).join("");
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
  if (state.view && state.view.compare_map_id) {
    items.push(["rgba(60,200,90,.75)", "Gained"], ["rgba(220,60,60,.75)", "Lost"]);
  }
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

let chunkDetail = null;
let chunkCategory = null;

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

  el["chunk-head"].innerHTML = tmpl`<h3>${detail.nickname || "Chunk " + detail.chunk_id}</h3>
    <div class="row"><code>${detail.chunk_id}</code>${raw(status)}
      <span class="spacer"></span>
      <button id="chunk-focus" type="button" title="Centre this chunk (F)">Focus</button>
      ${raw(detail.unlocked ? "" : '<button id="what-if" type="button">What would this add?</button>')}
    </div>`;
  document.getElementById("chunk-focus").onclick = () => focusChunk(detail.chunk_id);
  const whatIf = document.getElementById("what-if");
  if (whatIf) whatIf.onclick = () => previewUnlock(detail.chunk_id);

  /* Categories as chips rather than as eight headings in one column: at 360px
   * a chunk with monsters, NPCs, objects and shops was four short lists you
   * had to scroll past each other to compare. */
  const categories = Object.keys(detail.contents);
  if (!categories.includes(chunkCategory)) chunkCategory = categories[0] || "sections";

  let chips = categories.map((key) => tmpl`<button class="chip ${key === chunkCategory ? "on" : ""}" data-cat="${key}" title="${key}">
      ${icon(CATEGORY_ICONS[key] || "dot")}<span class="count">${detail.contents[key].length}</span></button>`).join("");
  chips += tmpl`<button class="chip ${chunkCategory === "sections" ? "on" : ""}" data-cat="sections" title="Sections">
      ${icon("sections")}<span class="count">${detail.sections.length}</span></button>`;
  el["chunk-chips"].innerHTML = chips;
  for (const chip of el["chunk-chips"].querySelectorAll("[data-cat]")) {
    chip.onclick = () => { chunkCategory = chip.dataset.cat; renderChunk(); };
  }

  el["chunk-body"].innerHTML = chunkCategory === "sections"
    ? renderSections(detail)
    : renderCategory(detail, chunkCategory);
}

function renderSections(detail) {
  if (!detail.sections.length) return tmpl`<p class="empty">This chunk is not split.</p>`;
  let out = "<ul class='list'>";
  for (const section of detail.sections) {
    out += tmpl`<li><span class="name">Section ${section.section}</span>
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
    out += tmpl`<li class="${row.reachable ? "" : "unreached"}">
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
      for (const [category, names] of tasks.sort((a, b) => Object.keys(b[1]).length - Object.keys(a[1]).length)) {
        const sample = Object.keys(names).slice(0, 6).map(plain).join("<br>");
        out += tmpl`<li data-tip="${sample}"><span class="name">${category}</span><span class="num">${Object.keys(names).length}</span></li>`;
      }
      out += "</ul>";
    }
    openOverlay("If you unlocked " + chunkId, out);
  } catch (error) {
    openOverlay("If you unlocked " + chunkId, tmpl`<p class="empty">${error.message}</p>`);
  }
}

/* ---- tasks pane -------------------------------------------------------- */

const GROUP_ICONS = {
  "Collection Log": "log",
  "Permanent Unlockables": "unlock",
  "Untracked Uniques": "star",
  "Ungrouped": "dot",
};

let taskPanel = null;
let taskSection = null;

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
  if (!sections.some((s) => s.key === taskSection)) taskSection = sections[0].key;

  el["task-chips"].innerHTML = sections.map((s) => tmpl`<button class="chip ${s.key === taskSection ? "on" : ""}" data-section="${s.key}">
      ${s.label}<span class="count">${state.showDone ? s.completed_total : s.active_total}</span></button>`).join("");
  for (const chip of el["task-chips"].querySelectorAll("[data-section]")) {
    chip.onclick = () => { taskSection = chip.dataset.section; renderTasks(); };
  }

  const section = sections.find((s) => s.key === taskSection);
  const side = state.showDone ? "completed" : "active";
  const groups = section.groups.filter((g) => g[side].length);
  if (!groups.length) {
    el["tasks-body"].innerHTML = tmpl`<p class="empty">Nothing ${state.showDone ? "completed" : "outstanding"} under ${section.label}.</p>`;
    return;
  }

  let out = "";
  for (const group of groups) {
    /* A single group whose name repeats the heading is a heading twice. */
    if (groups.length > 1 || group.name !== section.label) {
      out += tmpl`<h3>${raw(GROUP_ICONS[group.name] ? icon(GROUP_ICONS[group.name]).__raw + " " : "")}${group.name} <span class="num">${group[side].length}</span></h3>`;
    }
    out += "<ul class='list'>";
    for (const row of group[side]) {
      const badge = row.icon
        ? tmpl`<img class="skill-icon" src="/assets/skill/${row.icon}.png" alt="${row.icon}" title="${row.icon}">`
        : "";
      out += tmpl`<li>${raw(badge)}<span class="name">${plain(row.name)}</span>
        <span class="sub">${plain(row.note || "")}</span></li>`;
    }
    out += "</ul>";
  }
  el["tasks-body"].innerHTML = out;
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
    renderEstimate(estimatePayload);
  } catch (error) {
    estimatePayload = null;
    el["estimate-total"].textContent = "";
    el["estimate-body"].innerHTML = tmpl`<p class="empty">${error.message}</p>`;
  }
}

/* A donut of stroke-dashed arcs. Four numbers whose whole meaning is their
 * proportion to each other, which is the one thing a column of figures does
 * not show - and it is SVG, so there is still no dependency. */
function donut(buckets, total) {
  const R = 54, C = 2 * Math.PI * R;
  let offset = 0;
  let arcs = `<circle cx="70" cy="70" r="${R}" stroke="#22262f"/>`;
  for (const [name, value] of Object.entries(buckets)) {
    if (!value) continue;
    const length = (value / total) * C;
    arcs += `<circle cx="70" cy="70" r="${R}" stroke="${BUCKET_COLOURS[name] || "#858d9c"}"
      stroke-dasharray="${length} ${C - length}" stroke-dashoffset="${-offset}"/>`;
    offset += length;
  }
  return `<svg class="pie" width="140" height="140" viewBox="0 0 140 140">${arcs}</svg>`;
}

function renderEstimate(payload) {
  const total = payload.total_hours || 0;
  el["estimate-total"].textContent = hours(total) + " remaining";

  let out = '<div class="pie-row">' + donut(payload.buckets, total || 1) + '<div class="pie-key">';
  for (const [name, value] of Object.entries(payload.buckets)) {
    out += tmpl`<span><i class="sw" style="background:${BUCKET_COLOURS[name] || "#858d9c"}"></i>${label(name)}<b>${hours(value)}</b></span>`;
  }
  out += "</div></div>";

  /* The buckets say how long; these say *what*, which is the part you can
   * act on. Name and hours only - the reasoning is real but it is the second
   * question, so it lives in the tooltip. */
  const items = (payload.items || []).slice().sort((a, b) => b.hours - a.hours);
  if (items.length) {
    out += tmpl`<h3>Longest single items</h3><ul class="list">`;
    for (const item of items.slice(0, 14)) {
      const tip = tmpl`<b>${plain(item.item)}</b><span class="sub">${plain(item.detail)}</span><span class="sub">${label(item.bucket)}</span>`;
      out += tmpl`<li data-tip="${tip}"><span class="name">${plain(item.item)}</span><span class="num">${hours(item.hours)}</span></li>`;
    }
    out += "</ul>";
  }

  const skills = (payload.skills || []).slice().sort((a, b) => b.hours - a.hours);
  if (skills.length) {
    out += tmpl`<h3>Skilling</h3><ul class="list">`;
    for (const skill of skills.slice(0, 14)) {
      out += tmpl`<li><img class="skill-icon" src="/assets/skill/${skill.skill}.png" alt="">
        <span class="name">${skill.skill}</span>
        <span class="sub">${skill.current_level} → ${skill.target_level}</span>
        <span class="num">${hours(skill.hours)}</span></li>`;
    }
    out += "</ul>";
  }

  const unpriced = payload.unpriced || [];
  if (unpriced.length) {
    out += tmpl`<h3>Unpriced <span class="num">${unpriced.length}</span></h3><ul class="list">`;
    for (const item of unpriced.slice(0, 25)) {
      out += tmpl`<li><span class="name">${plain(typeof item === "string" ? item : item.item || "")}</span></li>`;
    }
    out += "</ul>";
  }
  el["estimate-body"].innerHTML = out;
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
    ? tmpl`<dt>DPS calculator</dt><dd>${payload.dps.monsters} monsters</dd>
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

  /* **Fly to a chunk that has a square.** Plenty of ids are underground or
   * instanced regions off the surface rectangle - an abyssal whip's first
   * source is one - and centring on one silently does nothing, which reads
   * as a broken button rather than as "that place is not on this map". */
  const placed = [...state.found].filter((id) => chunkToGrid(id));
  if (!placed.length) {
    toast(name + ": " + state.found.size + " chunks, none on the surface map");
    return;
  }
  focusChunk(placed[0]);
  toast(name + ": " + state.found.size + " chunks");
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
    let out = "<ul class='list'>";
    payload.results.forEach((result, index) => {
      const chunks = chunksOf(result);
      const note = chunks.length ? chunks.length + (chunks.length === 1 ? " chunk" : " chunks") : "—";
      out += tmpl`<li>
        <span class="pill ${result.available ? "reachable" : "locked"}">${label(result.type)}</span>
        <button class="link name" data-result="${index}">${plain(result.name)}</button>
        <span class="num">${note}</span></li>`;
    });
    body.innerHTML = out + "</ul>";
    for (const button of body.querySelectorAll("button[data-result]")) {
      button.onclick = () => highlight(payload.results[Number(button.dataset.result)]);
    }
  } catch (error) {
    if (run === findRun) body.innerHTML = tmpl`<p class="empty">${error.message}</p>`;
  }
}

el["find-input"].addEventListener("input", scheduleFind);
el["find-form"].addEventListener("submit", (e) => { e.preventDefault(); clearTimeout(findTimer); runFind(); });

/* ---- maps pane --------------------------------------------------------- */

function mapTip(entry) {
  const rows = [
    ["Kind", label(entry.kind)],
    ["Created", when(entry.created_at)],
    ["Size", bytes(entry.size)],
    ["Chunks", entry.unlocked_chunks == null ? "—" : entry.unlocked_chunks],
  ];
  if (entry.rolls != null) rows.push(["Rolls", entry.rolls]);
  if (entry.runs != null) rows.push(["Runs", entry.runs]);
  if (entry.seed != null) rows.push(["Seed", entry.seed]);
  if (entry.base_map) rows.push(["From", entry.base_map]);
  return rows.map(([k, v]) => tmpl`<span class="sub">${k}: ${v}</span>`).join("");
}

async function loadMapsPane() {
  const body = el["maps-body"];
  try {
    const maps = await getJSON("/api/maps");
    let out = `<h3>Actions</h3><div class="actions">
      <button id="do-fetch" type="button">Fetch This Map</button>
      <button id="do-refresh" type="button">Refresh Chunk Data</button>
    </div>
    <h3>Simulate</h3><div class="row">
      <input id="sim-rolls" type="number" min="1" value="5" style="width:7ch" aria-label="Rolls">
      <input id="sim-runs" type="number" min="1" value="1" style="width:7ch" aria-label="Runs">
      <button id="do-sim" type="button">Roll</button>
    </div>`;
    out += tmpl`<h3>Cached maps <span class="num">${maps.length}</span></h3><ul class="list">`;
    for (const m of maps) {
      const note = m.unlocked_chunks == null ? label(m.kind) : m.unlocked_chunks + " chunks";
      const remove = m.kind === "fetched" ? "" :
        '<button class="link danger" data-rm="' + m.map_id.replace(/"/g, "&quot;") + '">Remove</button>';
      out += tmpl`<li data-tip="${mapTip(m)}"><span class="name">${m.map_id}</span><span class="num">${note}</span>${raw(remove)}</li>`;
    }
    out += `</ul><div class="actions">
      <button id="rm-sims" class="danger" type="button">Remove All Simulated</button>
      <button id="prune" type="button">Clear Derived Cache</button>
    </div>`;
    body.innerHTML = out;

    document.getElementById("do-fetch").onclick = () =>
      runAction("Fetch " + el.map.value, "/api/fetch", { map: el.map.value }, () => loadView());
    document.getElementById("do-refresh").onclick = () =>
      runAction("Refresh chunk data", "/api/refresh", { what: "chunkinfo" });
    document.getElementById("do-sim").onclick = () => {
      const rolls = Number(document.getElementById("sim-rolls").value) || 1;
      const runs = Number(document.getElementById("sim-runs").value) || 1;
      runAction(`Simulate ${rolls} rolls`, "/api/simulate",
        { map: el.map.value, name: el.map.value + "-sim", rolls, runs },
        async (result) => {
          await loadMaps();
          el.compare.value = result.open;
          await loadView({ refit: true });
          loadMapsPane();
        });
    };
    for (const button of body.querySelectorAll("button[data-rm]")) {
      button.onclick = () => runAction("Remove " + button.dataset.rm, "/api/maps/remove",
        { names: [button.dataset.rm] },
        async () => { await loadMaps(); loadMapsPane(); loadView(); });
    }
    document.getElementById("rm-sims").onclick = () =>
      runAction("Remove simulated maps", "/api/maps/remove", { all: true },
        async () => { await loadMaps(); loadMapsPane(); loadView(); });
    document.getElementById("prune").onclick = () =>
      runAction("Clear derived cache", "/api/derived/prune", {});
  } catch (error) {
    body.innerHTML = tmpl`<p class="empty">${error.message}</p>`;
  }
}

/* ---- jobs -------------------------------------------------------------- */

function showJob(text, cls) {
  el.job.hidden = false;
  el.job.textContent = text;
  el.job.className = "job" + (cls ? " " + cls : "");
}

async function runAction(label, path, payload, onDone) {
  try {
    const { job } = await postJSON(path, payload);
    showJob(label + " starting…");
    await followJob(job, label, onDone);
  } catch (error) {
    showJob(label + " failed: " + error.message, "failed");
  }
}

function followJob(id, label, onDone) {
  return new Promise((resolve) => {
    const timer = setInterval(async () => {
      let job;
      try { job = await getJSON("/api/jobs/" + id); }
      catch { clearInterval(timer); return resolve(); }
      if (job.state === "running") return showJob(label + ": " + (job.progress || "working…"));
      clearInterval(timer);
      if (job.state === "failed") showJob(label + " failed: " + job.error, "failed");
      else {
        showJob(label + " done", "done");
        setTimeout(() => { el.job.hidden = true; }, 4000);
        onDone?.(job.result);
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
  tab: PARAMS.get("tab") || "",
};

el.map.addEventListener("change", async () => {
  state.selected = null;
  taskPanel = null;
  await loadView({ refit: true });
  await loadCandidates();
  await loadSections();
});
el.compare.addEventListener("change", () => loadView({ refit: true }));
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

el.live.addEventListener("click", () => {
  state.live = !state.live;
  el.live.setAttribute("aria-pressed", String(state.live));
});

async function poll() {
  if (!state.live || !state.view || !el.map.value) return;
  try {
    const { revision } = await getJSON("/api/revision?" + mapQuery());
    if (revision !== state.revision) { taskPanel = null; await loadView(); }
  } catch { /* a map deleted under us; the next load reports it */ }
}

function loadImage() {
  return new Promise((resolve) => {
    const image = new Image();
    image.onload = () => { state.image = image; resolve(true); };
    image.onerror = () => { toast("World map image unavailable"); resolve(false); };
    image.src = "/world_map.png";
  });
}

(async function start() {
  resize();
  if (!(await loadMaps())) return;
  await loadView();
  await loadImage();
  fitToCells();
  if (BOOT.candidates) el.candidates.click();
  if (BOOT.sections) el.masks.click();
  showTab(BOOT.tab || "tasks");
  setInterval(poll, 2000);
})();
