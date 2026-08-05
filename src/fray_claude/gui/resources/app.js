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

/* Edge bit flags. Must match gui/worldmap.py's Edge. */
const TOP = 1, BOTTOM = 2, LEFT = 4, RIGHT = 8;

const state = {
  view: null,
  cells: new Map(),        // "gx,gy" -> cell, for the locked-wash complement
  candidates: new Map(),   // chunk id -> neighbour entry
  found: new Set(),        // chunk ids highlighted by a search
  selected: null,
  image: null,
  panX: 0, panY: 0, zoom: 0.5,
  needsDraw: false,
  live: true,
  showCandidates: false,
  revision: null,
};

const el = {};
for (const id of [
  "map", "compare", "candidates", "live", "fit", "counts", "skipped", "hover",
  "toggle-panel", "panel", "tabs", "job", "toast", "legend",
  "chunk-body", "tasks-body", "estimate-body", "find-body", "find-form",
  "find-input", "maps-body",
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

/* ---- drawing ----------------------------------------------------------- */

/* An ordered list, which is the extension point: the planned roll heatmaps are
 * one more entry plus one key in view.overlays, and nothing about pan, zoom or
 * the hull has to change. */
const LAYERS = [
  drawBase, drawLockedWash, drawStates, drawFound, drawCandidates, drawHull, drawSelected,
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
  state.zoom = clamp(
    Math.min(availW / ((maxX - minX) * cell), availH / ((maxY - minY) * cell)),
    MIN_ZOOM, MAX_ZOOM,
  );
  const size = state.zoom * cell;
  state.panX = (availW - (maxX - minX) * size) / 2 + 40 - minX * size;
  state.panY = (availH - (maxY - minY) * size) / 2 + 60 - minY * size;
  invalidate();
}

function centreOn(chunkId) {
  const at = chunkToGrid(chunkId);
  if (!at) return;
  const size = cellSize();
  state.panX = (CANVAS.clientWidth - panelWidth()) / 2 - (at[0] + 0.5) * size;
  state.panY = CANVAS.clientHeight / 2 - (at[1] + 0.5) * size;
  invalidate();
}

function zoomAt(sx, sy, direction) {
  /* DEVIATION from upstream: clamp first, then derive the applied factor from
   * the clamped result. Upstream anchors on the requested step and skips the
   * update entirely at a limit, which lets the point under the cursor drift on
   * every wheel tick once you are pinned at either end. */
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
  dragging = { id: e.pointerId, x: e.clientX, y: e.clientY };
  movedWhileDown = 0;
  CANVAS.setPointerCapture(e.pointerId);
  CANVAS.classList.add("dragging");
});

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

function endDrag(e) {
  if (!dragging || dragging.id !== e.pointerId) return;
  dragging = null;
  CANVAS.releasePointerCapture(e.pointerId);
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

window.addEventListener("resize", resize);

document.addEventListener("keydown", (e) => {
  if (e.target.matches("input, select, textarea")) return;
  if (e.key === "c") el.candidates.click();
  else if (e.key === "f") el.fit.click();
  else if (e.key === "p") el["toggle-panel"].click();
  else if (e.key === "Escape") selectChunk(null);
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

/* Task and challenge names are markup-bearing keys: the raw `~|...|~` form is
 * what everything is keyed by, and stripping it is display-only. Mirrors
 * `challenges.strip_task_markup`, and applies *only* to names and details -
 * other branches of the export use `~` and `|` for real. */
function plain(text) { return String(text == null ? "" : text).replace(/~\|/g, "").replace(/\|~/g, ""); }

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

/* ---- data -------------------------------------------------------------- */

async function getJSON(path) {
  const response = await fetch(path);
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
    el.map.innerHTML = "<option value=''>no maps cached</option>";
    el.counts.textContent = "";
    el["chunk-body"].innerHTML = tmpl`<p class="empty">Nothing cached yet. Run <code>fray fetch</code> in a terminal, or press <b>fetch</b> on the maps tab.</p>`;
    showTab("maps");
    return false;
  }
  const options = maps.map((m) => tmpl`<option value="${m.map_id}">${m.map_id}${m.kind === "fetched" ? "" : "  (" + m.kind + ")"}</option>`).join("");
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
  const items = [["#6f8f5a", "unlocked"], ["#7e8288", "locked"]];
  if (state.view && state.view.compare_map_id) {
    items.push(["rgba(60,200,90,.75)", "gained"], ["rgba(220,60,60,.75)", "lost"]);
  }
  if (state.showCandidates && state.candidates.size) items.push([CANDIDATE_STROKE, "candidate"]);
  if (state.found.size) items.push(["rgba(255,190,0,.6)", "found"]);
  el.legend.innerHTML =
    items.map(([colour, label]) => tmpl`<span><i class="sw" style="background:${colour}"></i>${label}</span>`).join("") +
    tmpl`<span><i class="sw" style="background:transparent;border:2px solid ${HULL_STROKE}"></i>border</span>`;
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

/* ---- chunk pane -------------------------------------------------------- */

async function selectChunk(chunkId) {
  state.selected = chunkId;
  invalidate();
  if (!chunkId) {
    el["chunk-body"].innerHTML = tmpl`<p class="empty">Click a chunk on the map.</p>`;
    return;
  }
  showTab("chunk");
  el["chunk-body"].innerHTML = tmpl`<p class="empty">Reading ${chunkId}…</p>`;
  try {
    const detail = await getJSON(
      "/api/chunk?map=" + encodeURIComponent(el.map.value) +
      "&chunk=" + encodeURIComponent(chunkId));
    renderChunk(detail);
  } catch (error) {
    el["chunk-body"].innerHTML = tmpl`<p class="empty">${error.message}</p>`;
  }
}

function renderChunk(detail) {
  const candidate = state.candidates.get(detail.chunk_id);
  const status = detail.unlocked
    ? '<span class="pill reachable">unlocked</span>'
    : candidate
      ? '<span class="pill candidate">candidate #' + candidate.number + "</span>"
      : '<span class="pill locked">locked</span>';

  let out = tmpl`<h3>${detail.nickname || "chunk " + detail.chunk_id}</h3>
    <div class="row"><code>${detail.chunk_id}</code>${raw(status)}</div>`;

  for (const section of detail.sections) {
    const pill = section.reachable
      ? '<span class="pill reachable">reachable</span>'
      : '<span class="pill locked">unreached</span>';
    out += tmpl`<h3>section ${section.section} ${raw(pill)}</h3>`;
    const keys = Object.keys(section.contents);
    if (!keys.length) { out += tmpl`<p class="empty">Nothing recorded here.</p>`; continue; }
    out += "<ul class='list'>";
    for (const key of keys) {
      const names = section.contents[key];
      out += tmpl`<li><span class="name">${key} <span style="color:var(--dim)">${names.slice(0, 8).join(", ")}${names.length > 8 ? " …" : ""}</span></span><span class="num">${names.length}</span></li>`;
    }
    out += "</ul>";
  }

  if (!detail.unlocked) {
    out += `<div class="actions"><button id="what-if" type="button">what would this add?</button></div><div id="what-if-body"></div>`;
  }
  el["chunk-body"].innerHTML = out;

  const button = document.getElementById("what-if");
  if (button) button.addEventListener("click", () => previewUnlock(detail.chunk_id));
}

async function previewUnlock(chunkId) {
  const body = document.getElementById("what-if-body");
  body.innerHTML = tmpl`<p class="empty">Deriving both worlds…</p>`;
  try {
    const delta = await getJSON(
      "/api/unlock?map=" + encodeURIComponent(el.map.value) +
      "&chunk=" + encodeURIComponent(chunkId));
    const tasks = Object.entries(delta.new_tasks).filter(([, v]) => Object.keys(v).length);
    const taskCount = tasks.reduce((n, [, v]) => n + Object.keys(v).length, 0);
    const sectionCount = Object.values(delta.new_sections)
      .reduce((n, v) => n + Object.keys(v).length, 0);

    let out = tmpl`<h3>would add</h3><dl class="kv">
      <dt>tasks</dt><dd>${taskCount}</dd>
      <dt>sections</dt><dd>${sectionCount}</dd>
      <dt>bis upgrades</dt><dd>${Object.keys(delta.bis_upgrades).length}</dd></dl>`;
    if (tasks.length) {
      out += "<ul class='list'>";
      for (const [category, names] of tasks) {
        out += tmpl`<li><span class="name">${category}</span><span class="num">${Object.keys(names).length}</span></li>`;
      }
      out += "</ul>";
    }
    body.innerHTML = out;
  } catch (error) {
    body.innerHTML = tmpl`<p class="empty">${error.message}</p>`;
  }
}

/* ---- the other panes --------------------------------------------------- */

async function loadTasks() {
  const body = el["tasks-body"];
  body.innerHTML = tmpl`<p class="empty">Deriving…</p>`;
  try {
    const payload = await getJSON("/api/tasks?map=" + encodeURIComponent(el.map.value));
    let out = tmpl`<h3>current goal per skill</h3><ul class="list">`;
    for (const [skill, info] of Object.entries(payload.skills).sort()) {
      out += tmpl`<li><span class="name">${skill}</span><span class="num">${plain(info.active) || "—"}</span></li>`;
    }
    out += "</ul>";
    for (const [category, entries] of Object.entries(payload.other)) {
      const names = Object.keys(entries || {});
      out += tmpl`<h3>${category} <span class="num">${names.length}</span></h3><ul class="list">`;
      for (const name of names.slice(0, 40)) out += tmpl`<li><span class="name">${plain(name)}</span></li>`;
      if (names.length > 40) out += tmpl`<li><span class="name" style="color:var(--dim)">and ${names.length - 40} more</span></li>`;
      out += "</ul>";
    }
    body.innerHTML = out;
  } catch (error) {
    body.innerHTML = tmpl`<p class="empty">${error.message}</p>`;
  }
}

async function loadEstimate() {
  const body = el["estimate-body"];
  body.innerHTML = tmpl`<p class="empty">Pricing the outstanding work…</p>`;
  try {
    const payload = await getJSON("/api/estimate?map=" + encodeURIComponent(el.map.value));
    let out = tmpl`<h3>hours remaining</h3><dl class="kv">`;
    for (const [bucket, hours] of Object.entries(payload.buckets)) {
      out += tmpl`<dt>${bucket}</dt><dd>${hours.toFixed(1)}</dd>`;
    }
    out += tmpl`<dt>total</dt><dd>${payload.total_hours.toFixed(1)}</dd></dl>`;

    /* An estimate computed with the DPS bridge and one without are different
     * numbers, so the screen says which of the two it is showing. */
    out += tmpl`<h3>where the numbers come from</h3><dl class="kv">
      <dt>wiki rates</dt><dd>${payload.scraped_rates ? "present" : "missing"}</dd>`;
    out += payload.dps
      ? tmpl`<dt>dps calc</dt><dd>${payload.dps.monsters} monsters</dd><dt></dt><dd>${payload.dps.slayer_tasks} slayer tasks</dd>`
      : tmpl`<dt>dps calc</dt><dd>not installed</dd>`;
    out += "</dl>";

    /* The buckets say how long; these say *what*, which is the part you can
     * act on. Sorted by hours because the top of that list is the whole
     * question - one item is routinely a third of a bucket. */
    const items = (payload.items || []).slice().sort((a, b) => b.hours - a.hours);
    if (items.length) {
      out += tmpl`<h3>longest single items</h3><ul class="list">`;
      for (const item of items.slice(0, 12)) {
        out += tmpl`<li><span class="name">${plain(item.item)}<br><span style="color:var(--dim)">${plain(item.detail)}</span></span><span class="num">${item.hours.toFixed(0)}h</span></li>`;
      }
      out += "</ul>";
    }

    const skills = (payload.skills || []).slice().sort((a, b) => b.hours - a.hours);
    if (skills.length) {
      out += tmpl`<h3>skilling</h3><ul class="list">`;
      for (const skill of skills.slice(0, 12)) {
        out += tmpl`<li><span class="name">${skill.skill} <span style="color:var(--dim)">${skill.current_level} → ${skill.target_level}</span></span><span class="num">${skill.hours.toFixed(0)}h</span></li>`;
      }
      out += "</ul>";
    }

    /* Every reachable master, not just the one the estimate spent, because
     * "which master" is a decision and coverage is what makes it one: a rate
     * renormalised over a third of a list flatters that master. */
    const masters = payload.slayer_masters || [];
    if (masters.length) {
      out += tmpl`<h3>slayer masters</h3><ul class="list">`;
      for (const master of masters) {
        const chosen = payload.slayer && payload.slayer.master === master.master;
        out += tmpl`<li><span class="name">${chosen ? "▸ " : ""}${master.master} <span style="color:var(--dim)">${Math.round(master.coverage * 100)}% covered · ${master.points_delta.toFixed(0)} pts</span></span><span class="num">${Math.round(master.xp_per_hour || 0).toLocaleString()}/h</span></li>`;
      }
      out += "</ul>";
    }

    const unpriced = payload.unpriced || [];
    if (unpriced.length) {
      out += tmpl`<h3>unpriced <span class="num">${unpriced.length}</span></h3><ul class="list">`;
      for (const item of unpriced.slice(0, 25)) {
        out += tmpl`<li><span class="name">${plain(typeof item === "string" ? item : item.item || "")}</span></li>`;
      }
      out += "</ul>";
    }
    body.innerHTML = out;
  } catch (error) {
    body.innerHTML = tmpl`<p class="empty">${error.message}</p>`;
  }
}

/* Search results name their sources' locations as "<chunk>-<section>"; the
 * chunk half is what has a square on the map. */
function chunksOf(result) {
  const found = new Set();
  for (const source of result.sources || []) {
    for (const location of source.locations || []) {
      const chunk = String(location).split("-")[0];
      if (/^\d+$/.test(chunk)) found.add(chunk);
    }
  }
  return [...found];
}

function highlight(result) {
  state.found = new Set(chunksOf(result));
  renderLegend();
  invalidate();
  if (!state.found.size) { toast(result.name + " has no placed source"); return; }
  centreOn([...state.found][0]);
  toast(result.name + ": " + state.found.size + " chunks");
}

el["find-form"].addEventListener("submit", async (e) => {
  e.preventDefault();
  const term = el["find-input"].value.trim();
  if (!term) return;
  const body = el["find-body"];
  body.innerHTML = tmpl`<p class="empty">Searching…</p>`;
  try {
    const payload = await getJSON("/api/search?q=" + encodeURIComponent(term) + "&limit=40");
    if (!payload.results.length) {
      body.innerHTML = tmpl`<p class="empty">Nothing matches ${term}.</p>`;
      return;
    }
    let out = "<ul class='list'>";
    payload.results.forEach((result, index) => {
      const chunks = chunksOf(result);
      const note = chunks.length ? chunks.length + " chunks" : (result.available ? "reachable" : "—");
      out += tmpl`<li><button class="link" data-result="${index}">${plain(result.name)}</button><span class="num">${note}</span></li>`;
    });
    body.innerHTML = out + "</ul>";
    for (const button of body.querySelectorAll("button[data-result]")) {
      button.addEventListener("click", () => highlight(payload.results[Number(button.dataset.result)]));
    }
  } catch (error) {
    body.innerHTML = tmpl`<p class="empty">${error.message}</p>`;
  }
});

async function loadMapsPane() {
  const body = el["maps-body"];
  try {
    const maps = await getJSON("/api/maps");
    let out = `<h3>actions</h3><div class="actions">
      <button id="do-fetch" type="button">fetch this map</button>
      <button id="do-refresh" type="button">refresh chunk data</button>
    </div>
    <h3>simulate</h3><div class="row">
      <input id="sim-rolls" type="number" min="1" value="5" style="width:7ch" aria-label="rolls">
      <input id="sim-runs" type="number" min="1" value="1" style="width:7ch" aria-label="runs">
      <button id="do-sim" type="button">roll</button>
    </div>`;
    out += tmpl`<h3>cached maps <span class="num">${maps.length}</span></h3><ul class="list">`;
    for (const m of maps) {
      const note = m.unlocked_chunks == null ? m.kind : m.unlocked_chunks + " chunks";
      const remove = m.kind === "fetched" ? "" :
        '<button class="link danger" data-rm="' + m.map_id.replace(/"/g, "&quot;") + '">remove</button>';
      out += tmpl`<li><span class="name">${m.map_id}</span><span class="num">${note}</span>${raw(remove)}</li>`;
    }
    out += `</ul><div class="actions">
      <button id="rm-sims" class="danger" type="button">remove all simulated</button>
      <button id="prune" type="button">clear derived cache</button>
    </div>`;
    body.innerHTML = out;

    document.getElementById("do-fetch").onclick = () =>
      runAction("fetch " + el.map.value, "/api/fetch", { map: el.map.value }, () => loadView());
    document.getElementById("do-refresh").onclick = () =>
      runAction("refresh chunk data", "/api/refresh", { what: "chunkinfo" });
    document.getElementById("do-sim").onclick = () => {
      const rolls = Number(document.getElementById("sim-rolls").value) || 1;
      const runs = Number(document.getElementById("sim-runs").value) || 1;
      runAction(`simulate ${rolls} rolls`, "/api/simulate",
        { map: el.map.value, name: el.map.value + "-sim", rolls, runs },
        async (result) => {
          await loadMaps();
          el.compare.value = result.open;
          await loadView({ refit: true });
          loadMapsPane();
        });
    };
    for (const button of body.querySelectorAll("button[data-rm]")) {
      button.onclick = () => runAction("remove " + button.dataset.rm, "/api/maps/remove",
        { names: [button.dataset.rm] },
        async () => { await loadMaps(); loadMapsPane(); loadView(); });
    }
    document.getElementById("rm-sims").onclick = () =>
      runAction("remove simulated maps", "/api/maps/remove", { all: true },
        async () => { await loadMaps(); loadMapsPane(); loadView(); });
    document.getElementById("prune").onclick = () =>
      runAction("clear derived cache", "/api/derived/prune", {});
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

/* ---- boot -------------------------------------------------------------- */

/* The query string is the app's only deep link: `?map=&compare=&candidates=1`
 * reproduces a view, which is what makes a particular question shareable and
 * a screenshot reproducible. */
const PARAMS = new URLSearchParams(location.search);
const BOOT = {
  map: PARAMS.get("map") || "",
  compare: PARAMS.get("compare") || "",
  candidates: PARAMS.get("candidates") === "1",
  tab: PARAMS.get("tab") || "",
};

el.map.addEventListener("change", async () => {
  state.selected = null;
  await loadView({ refit: true });
  await loadCandidates();
});
el.compare.addEventListener("change", () => loadView({ refit: true }));
el.fit.addEventListener("click", () => fitToCells());

el.candidates.addEventListener("click", async () => {
  state.showCandidates = !state.showCandidates;
  el.candidates.setAttribute("aria-pressed", String(state.showCandidates));
  el.candidates.classList.toggle("on", state.showCandidates);
  await loadCandidates();
});

el.live.addEventListener("click", () => {
  state.live = !state.live;
  el.live.setAttribute("aria-pressed", String(state.live));
  el.live.classList.toggle("on", state.live);
});

async function poll() {
  if (!state.live || !state.view || !el.map.value) return;
  try {
    const { revision } = await getJSON("/api/revision?" + mapQuery());
    if (revision !== state.revision) await loadView();
  } catch { /* a map deleted under us; the next load reports it */ }
}

function loadImage() {
  return new Promise((resolve) => {
    const image = new Image();
    image.onload = () => { state.image = image; resolve(true); };
    image.onerror = () => { toast("world map image unavailable"); resolve(false); };
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
  if (BOOT.tab) showTab(BOOT.tab);
  setInterval(poll, 2000);
})();
