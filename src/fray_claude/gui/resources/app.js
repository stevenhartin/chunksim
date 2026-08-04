"use strict";
/* The world map canvas: pan, zoom, and a layered draw.
 *
 * One classic script, no modules, no build step, no CDN. The zero-dependency
 * rule is about what a user has to install, and shipping a bundler would break
 * its spirit even though npm is not pip.
 *
 * Pan and zoom are manual affine arithmetic rather than ctx.transform, matching
 * upstream's renderer so the two can be compared line by line: the map is one
 * drawImage at (panX, panY) scaled by zoom, and every chunk rect is
 * pan + zoom * grid * PIXELS_PER_CHUNK. Two deliberate departures from upstream
 * are marked DEVIATION below.
 */

const CANVAS = document.getElementById("canvas");
const CTX = CANVAS.getContext("2d");

const MIN_ZOOM = 0.2;
const MAX_ZOOM = 3.5;
const ZOOM_STEP = 0.15;

/* Upstream's colours, so a screenshot of either is recognisably the same map. */
const LOCKED_WASH = "rgba(150, 150, 150, 0.6)";
const ADDED_FILL = "rgba(60, 200, 90, 0.45)";
const REMOVED_FILL = "rgba(220, 60, 60, 0.45)";
const HULL_STROKE = "#ffbe00";

/* Edge bit flags. Must match gui/worldmap.py's Edge. */
const TOP = 1, BOTTOM = 2, LEFT = 4, RIGHT = 8;

const state = {
  view: null,
  cells: new Map(),      // "gx,gy" -> cell, for the locked-wash complement
  image: null,
  panX: 0,
  panY: 0,
  zoom: 0.5,
  needsDraw: false,
  live: true,
  revision: null,
};

const el = {
  map: document.getElementById("map"),
  compare: document.getElementById("compare"),
  reset: document.getElementById("reset"),
  live: document.getElementById("live"),
  counts: document.getElementById("counts"),
  skipped: document.getElementById("skipped"),
  status: document.getElementById("status"),
  toast: document.getElementById("toast"),
  fetch: document.getElementById("fetch"),
  simulate: document.getElementById("simulate"),
  rolls: document.getElementById("rolls"),
  runs: document.getElementById("runs"),
  job: document.getElementById("job"),
};

/* ---- geometry ---------------------------------------------------------- */

function cellSize() {
  return state.zoom * state.view.geometry.pixels_per_chunk;
}

function toScreen(gridX, gridY) {
  const size = cellSize();
  return [state.panX + gridX * size, state.panY + gridY * size];
}

function toGrid(screenX, screenY) {
  const size = cellSize();
  return [
    Math.floor((screenX - state.panX) / size),
    Math.floor((screenY - state.panY) / size),
  ];
}

/* ---- drawing ----------------------------------------------------------- */

/* An ordered list, which is the extension point: a heatmap is one more entry
 * here plus one key in view.overlays, and nothing about pan, zoom or the hull
 * has to change. */
const LAYERS = [drawBase, drawLockedWash, drawStates, drawHull, drawOverlays];

function drawBase() {
  if (!state.image) return;
  const { image_width: w, image_height: h } = state.view.geometry;
  CTX.drawImage(state.image, state.panX, state.panY, state.zoom * w, state.zoom * h);
}

function drawLockedWash() {
  /* Every grid cell we were not given a cell for. ~1,500 fillRects is well
   * under a millisecond; if that ever stops being true the alternative is one
   * wash over the whole map plus a source-rect drawImage per unlocked cell. */
  const { grid_columns: cols, grid_rows: rows } = state.view.geometry;
  const size = cellSize();
  CTX.fillStyle = LOCKED_WASH;
  for (let gx = 0; gx < cols; gx++) {
    for (let gy = 0; gy < rows; gy++) {
      if (state.cells.has(gx + "," + gy)) continue;
      const [x, y] = toScreen(gx, gy);
      if (x > CANVAS.clientWidth || y > CANVAS.clientHeight || x + size < 0 || y + size < 0) {
        continue;
      }
      CTX.fillRect(x, y, size, size);
    }
  }
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
  /* Upstream's fixed 3 disappears at zoom 0.2 and looks thin at 3.5. */
  CTX.lineWidth = Math.max(2, 2.5 * state.zoom);
  CTX.lineCap = "square";
  CTX.stroke();
}

function drawOverlays() {
  /* Reserved for the roll heatmaps. Nothing populates view.overlays yet. */
}

function draw() {
  state.needsDraw = false;
  CTX.clearRect(0, 0, CANVAS.clientWidth, CANVAS.clientHeight);
  if (!state.view) return;
  /* The map is pixel art at 3px per game tile; smoothing turns it to mush
   * above zoom 1. */
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
   * scale the context once, so every coordinate below stays in CSS pixels and
   * the map is not blurry on a HiDPI screen. */
  const dpr = window.devicePixelRatio || 1;
  CANVAS.width = Math.round(CANVAS.clientWidth * dpr);
  CANVAS.height = Math.round(CANVAS.clientHeight * dpr);
  CTX.setTransform(dpr, 0, 0, dpr, 0, 0);
  invalidate();
}

function fitToCells() {
  if (!state.view || !state.view.cells.length) return resetToWholeMap();
  const cell = state.view.geometry.pixels_per_chunk;
  const xs = state.view.cells.map((c) => c.grid_x);
  const ys = state.view.cells.map((c) => c.grid_y);
  const minX = Math.min(...xs), maxX = Math.max(...xs) + 1;
  const minY = Math.min(...ys), maxY = Math.max(...ys) + 1;
  const pad = 40;
  const zoomX = (CANVAS.clientWidth - pad * 2) / ((maxX - minX) * cell);
  const zoomY = (CANVAS.clientHeight - pad * 2) / ((maxY - minY) * cell);
  state.zoom = clamp(Math.min(zoomX, zoomY), MIN_ZOOM, MAX_ZOOM);
  const size = state.zoom * cell;
  state.panX = (CANVAS.clientWidth - (maxX - minX) * size) / 2 - minX * size;
  state.panY = (CANVAS.clientHeight - (maxY - minY) * size) / 2 - minY * size;
  invalidate();
}

function resetToWholeMap() {
  const { image_width: w, image_height: h } = state.view.geometry;
  state.zoom = clamp(Math.min(CANVAS.clientWidth / w, CANVAS.clientHeight / h), MIN_ZOOM, MAX_ZOOM);
  state.panX = (CANVAS.clientWidth - state.zoom * w) / 2;
  state.panY = (CANVAS.clientHeight - state.zoom * h) / 2;
  invalidate();
}

function clamp(value, low, high) {
  return Math.min(high, Math.max(low, value));
}

function zoomAt(screenX, screenY, direction) {
  /* DEVIATION from upstream: clamp first, then derive the applied factor from
   * the clamped result. Upstream anchors on the requested step and skips the
   * whole update when it would exceed a limit, which lets the point under the
   * cursor drift on every wheel tick once you are pinned at either end. */
  const next = clamp(state.zoom * (1 + direction * ZOOM_STEP), MIN_ZOOM, MAX_ZOOM);
  const applied = next / state.zoom - 1;
  state.panX -= (screenX - state.panX) * applied;
  state.panY -= (screenY - state.panY) * applied;
  state.zoom = next;
  invalidate();
}

/* ---- input ------------------------------------------------------------- */

let dragging = null;

CANVAS.addEventListener("pointerdown", (event) => {
  /* DEVIATION from upstream: Pointer Events plus capture, so trackpads and
   * touch work and a drag released outside the canvas still ends. */
  dragging = { id: event.pointerId, x: event.clientX, y: event.clientY };
  CANVAS.setPointerCapture(event.pointerId);
  CANVAS.classList.add("dragging");
});

CANVAS.addEventListener("pointermove", (event) => {
  if (dragging && dragging.id === event.pointerId) {
    state.panX += event.clientX - dragging.x;
    state.panY += event.clientY - dragging.y;
    dragging.x = event.clientX;
    dragging.y = event.clientY;
    invalidate();
  }
  showHovered(event.clientX, event.clientY);
});

function endDrag(event) {
  if (!dragging || dragging.id !== event.pointerId) return;
  dragging = null;
  CANVAS.releasePointerCapture(event.pointerId);
  CANVAS.classList.remove("dragging");
}

CANVAS.addEventListener("pointerup", endDrag);
CANVAS.addEventListener("pointercancel", endDrag);

CANVAS.addEventListener("wheel", (event) => {
  event.preventDefault();
  zoomAt(event.clientX, event.clientY, event.deltaY < 0 ? 1 : -1);
}, { passive: false });

CANVAS.addEventListener("click", () => {
  const id = el.status.dataset.chunk;
  if (!id) return;
  navigator.clipboard?.writeText(id).then(() => toast("copied " + id), () => {});
});

window.addEventListener("resize", resize);

function showHovered(screenX, screenY) {
  if (!state.view) return;
  const [gx, gy] = toGrid(screenX, screenY);
  const { grid_columns: cols, grid_rows: rows } = state.view.geometry;
  if (gx < 0 || gy < 0 || gx >= cols || gy >= rows) {
    el.status.textContent = "";
    delete el.status.dataset.chunk;
    return;
  }
  const cell = state.cells.get(gx + "," + gy);
  /* Invert the projection rather than asking the server: the id is a function
   * of the square, so a round trip per mousemove would be absurd. */
  const regionX = gx + 15;
  const regionY = 65 - gy;
  const chunkId = String(regionX * 256 + regionY);
  el.status.dataset.chunk = chunkId;
  el.status.textContent =
    chunkId + "  (" + regionX + ", " + regionY + ")" + (cell ? "  " + cell.state : "");
}

function toast(message) {
  el.toast.textContent = message;
  el.toast.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { el.toast.hidden = true; }, 1600);
}

/* ---- data -------------------------------------------------------------- */

async function getJSON(path) {
  const response = await fetch(path);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || response.statusText);
  return payload;
}

function viewURL(path) {
  const params = new URLSearchParams({ map: el.map.value });
  if (el.compare.value) params.set("compare", el.compare.value);
  return path + "?" + params.toString();
}

async function loadMaps() {
  const maps = await getJSON("/api/maps");
  const options = maps.map((m) => {
    const label = m.kind === "fetched" ? m.map_id : m.map_id + "  (" + m.kind + ")";
    return '<option value="' + m.map_id + '">' + label + "</option>";
  }).join("");
  el.map.innerHTML = options;
  el.compare.innerHTML = '<option value="">none</option>' + options;
  if (BOOT.map) el.map.value = BOOT.map;
  if (BOOT.compare) el.compare.value = BOOT.compare;
}

async function loadView({ refit = false } = {}) {
  try {
    const view = await getJSON(viewURL("/api/view"));
    state.view = view;
    state.revision = view.revision;
    state.cells = new Map(view.cells.map((c) => [c.grid_x + "," + c.grid_y, c]));
    renderCounts(view);
    if (refit) fitToCells(); else invalidate();
  } catch (error) {
    el.counts.textContent = "";
    el.status.textContent = error.message;
  }
}

function renderCounts(view) {
  const parts = [view.counts.unlocked + " unlocked"];
  if (view.counts.added) parts.push("+" + view.counts.added);
  if (view.counts.removed) parts.push("−" + view.counts.removed);
  el.counts.textContent = parts.join("  ·  ");

  /* Without this the canvas simply shows fewer chunks than `fray show` counts,
   * which reads as a rendering bug rather than as "these have no square". */
  if (view.counts.skipped) {
    el.skipped.hidden = false;
    el.skipped.textContent = view.counts.skipped + " not on the map";
    el.skipped.onclick = () => toast(view.skipped.join(", "));
  } else {
    el.skipped.hidden = true;
  }
}

async function poll() {
  if (!state.live || !state.view) return;
  try {
    const { revision } = await getJSON(viewURL("/api/revision"));
    if (revision !== state.revision) await loadView();
  } catch { /* a map deleted under us; the next view load reports it */ }
}

function loadImage() {
  return new Promise((resolve) => {
    const image = new Image();
    image.onload = () => { state.image = image; resolve(true); };
    image.onerror = () => { toast("world map image unavailable"); resolve(false); };
    image.src = "/world_map.png";
  });
}

/* ---- actions ----------------------------------------------------------- */

/* A POST answers with a job id, not a result: a simulate of fifty runs takes
 * minutes. Everything below is polling that job and showing its progress. */

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

function showJob(text, cls) {
  el.job.hidden = false;
  el.job.textContent = text;
  el.job.className = "job" + (cls ? " " + cls : "");
}

async function runAction(label, path, payload, onDone) {
  setBusy(true);
  try {
    const { job } = await postJSON(path, payload);
    showJob(label + " starting...");
    await followJob(job, label, onDone);
  } catch (error) {
    showJob(label + " failed: " + error.message, "failed");
  } finally {
    setBusy(false);
  }
}

function followJob(id, label, onDone) {
  return new Promise((resolve) => {
    const timer = setInterval(async () => {
      let job;
      try {
        job = await getJSON("/api/jobs/" + id);
      } catch {
        clearInterval(timer);
        return resolve();
      }
      if (job.state === "running") {
        showJob(label + ": " + (job.progress || "working..."));
        return;
      }
      clearInterval(timer);
      if (job.state === "failed") {
        showJob(label + " failed: " + job.error, "failed");
      } else {
        showJob(label + " done", "done");
        setTimeout(() => { el.job.hidden = true; }, 4000);
        onDone?.(job.result);
      }
      resolve();
    }, 400);
  });
}

function setBusy(busy) {
  el.fetch.disabled = busy;
  el.simulate.disabled = busy;
}

el.fetch.addEventListener("click", () => {
  const map = el.map.value;
  runAction("fetch " + map, "/api/fetch", { map }, () => loadView());
});

el.simulate.addEventListener("click", () => {
  const map = el.map.value;
  const rolls = Number(el.rolls.value) || 1;
  const runs = Number(el.runs.value) || 1;
  /* A name the user did not have to invent. The server appends -2, -3 if it
   * is taken, and tells us what it actually used. */
  const name = map + "-sim";
  runAction(
    "simulate " + rolls + " rolls",
    "/api/simulate",
    { map, name, rolls, runs },
    async (result) => {
      await loadMaps();
      /* Jump straight to the result and show it against where you started,
       * which is the question you were asking by simulating. */
      el.map.value = map;
      el.compare.value = result.open;
      await loadView({ refit: true });
    },
  );
});

/* ---- boot -------------------------------------------------------------- */

const BOOT = {
  map: new URLSearchParams(location.search).get("map") || "",
  compare: new URLSearchParams(location.search).get("compare") || "",
};

el.map.addEventListener("change", () => loadView({ refit: true }));
el.compare.addEventListener("change", () => loadView({ refit: true }));
el.reset.addEventListener("click", () => fitToCells());
el.live.addEventListener("change", () => { state.live = el.live.checked; });

(async function start() {
  resize();
  await loadMaps();
  await loadView();
  await loadImage();
  fitToCells();
  setInterval(poll, 2000);
})();
