import assert from "node:assert/strict";
import { createHash, randomUUID } from "node:crypto";
import { createServer } from "node:http";
import { mkdir, readFile, readdir, realpath, stat, writeFile } from "node:fs/promises";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { deflateSync, inflateSync } from "node:zlib";
import { chromium, expect } from "@playwright/test";
import { preview } from "vite";

// Opt-in synthetic engineering checks; never imports the editor implementation.
// --prepare makes fixtures only. --run needs a separately frozen plan and a fresh output.
const ROOT = resolve(fileURLToPath(new URL("../../", import.meta.url)));
const RESEARCH = join(ROOT, "output/research");
const PROTOCOL = "agemorph3d-mask-editor-browser-v1";
const EDITOR_PROTOCOL = "agemorph3d-mask-editor-v1";
const SIZE = 1024;
const FLAGS = {
  research_only: true, human_review_completed: false, identity_quality_accepted: false,
  age_quality_accepted: false, visual_seam_quality_accepted: false, years_calibrated: false,
  service_ready: false, production_enabled: false, g3_complete: false,
};
const REQUIRED = [
  "docs/mask-editor-v1.json", "frontend/src/research-mask-editor.ts",
  "frontend/tests/research-mask-editor.test.ts", "frontend/tests/mask-editor-browser.mjs",
  "frontend/research/mask-editor.ts", "frontend/research/mask-editor.html",
  "frontend/research/mask-editor.css", "frontend/research/session.ts",
  "frontend/research/session.html", "frontend/vite.config.ts", "frontend/package.json",
  "frontend/package-lock.json",
];
const FIXTURE_NAMES = ["target", "binding", "other_binding", "mismatch_binding", "wrongsize_binding", "wrongsize_target"];
const args = process.argv.slice(2);
const option = key => {
  const at = args.indexOf(key);
  assert.ok(at >= 0 && args[at + 1] && !args[at + 1].startsWith("--"), `Specify ${key}.`);
  return args[at + 1];
};
const hash = bytes => createHash("sha256").update(bytes).digest("hex");
const relativePath = path => relative(ROOT, path).split(sep).join("/");
const inside = (base, path) => path !== base && !relative(base, path).startsWith("..") && !isAbsolute(relative(base, path));
const repoPath = value => {
  assert.equal(typeof value, "string");
  const path = resolve(ROOT, value);
  assert.ok(inside(ROOT, path), "Path escaped workspace.");
  return path;
};
const json = async path => JSON.parse(await readFile(path, "utf8"));
const writeJson = (path, value) => writeFile(path, JSON.stringify(value, null, 2) + "\n", { flag: "wx" });

async function freshResearchDirectory(value) {
  const path = repoPath(value);
  assert.ok(inside(RESEARCH, path));
  await mkdir(dirname(path), { recursive: true });
  assert.ok(inside(await realpath(RESEARCH), await realpath(dirname(path))));
  await mkdir(path); // EEXIST must fail; never overwrite an earlier experiment.
  return path;
}

async function pin(path) {
  const bytes = await readFile(path);
  return { path: relativePath(path), bytes: bytes.length, sha256: hash(bytes) };
}

// Independent bit-at-a-time CRC and zlib paths; no producer PNG helpers.
function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit++) crc = crc & 1 ? (crc >>> 1) ^ 0xedb88320 : crc >>> 1;
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function chunk(kind, bytes) {
  const result = Buffer.alloc(bytes.length + 12);
  result.writeUInt32BE(bytes.length, 0);
  result.write(kind, 4, 4, "ascii");
  Buffer.from(bytes).copy(result, 8);
  result.writeUInt32BE(crc32(result.subarray(4, result.length - 4)), result.length - 4);
  return result;
}

function syntheticPng(width = SIZE, height = SIZE) {
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0); header.writeUInt32BE(height, 4); header[8] = 8; header[9] = 2;
  const rows = Buffer.alloc((width * 3 + 1) * height);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const at = y * (width * 3 + 1) + 1 + 3 * x;
      rows[at] = (x + 3 * y) % 256;
      rows[at + 1] = (2 * x + y) % 256;
      rows[at + 2] = (x ^ y) % 256;
    }
  }
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", header),
    chunk("IDAT", deflateSync(rows, { level: 9 })), chunk("IEND", Buffer.alloc(0))]);
}

export async function prepareFixtures(outputDir) {
  const output = await freshResearchDirectory(outputDir);
  const target = syntheticPng(), small = syntheticPng(512, 512);
  const binding = {
    schema_version: 1, protocol_id: EDITOR_PROTOCOL,
    stage: { stage_id: "a".repeat(32), source_fingerprint: "b".repeat(64), target_condition: 45,
      generated_sha256: hash(target), fit_sha256: "c".repeat(64) },
    width: SIZE, height: SIZE, research_only: true,
  };
  const other = structuredClone(binding);
  other.stage.stage_id = "d".repeat(32); other.stage.source_fingerprint = "e".repeat(64);
  other.stage.fit_sha256 = "f".repeat(64); other.stage.target_condition = 46;
  const mismatch = structuredClone(binding); mismatch.stage.generated_sha256 = "0".repeat(64);
  const wrongsize = structuredClone(binding); wrongsize.stage.generated_sha256 = hash(small);
  const filenames = { target: "target.png", binding: "binding.json", other_binding: "other-binding.json",
    mismatch_binding: "mismatch-binding.json", wrongsize_binding: "wrongsize-binding.json",
    wrongsize_target: "wrongsize-target.png" };
  await writeFile(join(output, filenames.target), target, { flag: "wx" });
  await writeFile(join(output, filenames.wrongsize_target), small, { flag: "wx" });
  for (const [role, value] of Object.entries({ binding, other_binding: other, mismatch_binding: mismatch,
    wrongsize_binding: wrongsize })) await writeJson(join(output, filenames[role]), value);
  const fixtures = {};
  for (const [role, filename] of Object.entries(filenames)) fixtures[role] = await pin(join(output, filename));
  await writeJson(join(output, "fixtures.json"), { schema_version: 1, protocol_id: PROTOCOL,
    synthetic_only: true, no_source_or_fit_asset_truth: true, fixtures });
  return fixtures;
}

function decodeMaskPng(png) {
  assert.ok(png.length > 57 && png.length <= 4 * 1024 ** 2);
  assert.deepEqual([...png.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
  const names = [], data = [];
  let offset = 8, width, height;
  while (offset < png.length) {
    assert.ok(offset + 12 <= png.length);
    const length = png.readUInt32BE(offset), end = offset + 12 + length;
    assert.ok(end <= png.length);
    assert.equal(png.readUInt32BE(end - 4), crc32(png.subarray(offset + 4, end - 4)));
    const type = png.toString("ascii", offset + 4, offset + 8); names.push(type);
    if (type === "IHDR") {
      assert.equal(length, 13); width = png.readUInt32BE(offset + 8); height = png.readUInt32BE(offset + 12);
      assert.deepEqual([...png.subarray(offset + 16, offset + 21)], [8, 0, 0, 0, 0]);
    } else if (type === "IDAT") data.push(png.subarray(offset + 8, end - 4));
    offset = end;
  }
  assert.deepEqual(names, ["IHDR", "IDAT", "IEND"]);
  assert.equal(offset, png.length); assert.equal(width, SIZE); assert.equal(height, SIZE);
  const scanlines = inflateSync(Buffer.concat(data), { maxOutputLength: (SIZE + 1) * SIZE });
  assert.equal(scanlines.length, (SIZE + 1) * SIZE);
  const pixels = Buffer.alloc(SIZE * SIZE);
  for (let row = 0; row < SIZE; row++) {
    assert.equal(scanlines[row * (SIZE + 1)], 0);
    scanlines.copy(pixels, row * SIZE, row * (SIZE + 1) + 1, (row + 1) * (SIZE + 1));
  }
  assert.ok(pixels.every(value => value === 0 || value === 255));
  return pixels;
}

// Straight ray-casting oracle, intentionally not the scanline producer algorithm.
function insidePolygon(x, y, points) {
  let inside = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    const a = points[j], b = points[i];
    const cross = (x - a.x) * (b.y - a.y) - (y - a.y) * (b.x - a.x);
    if (Math.abs(cross) <= 1e-9 && x >= Math.min(a.x, b.x) && x <= Math.max(a.x, b.x)
      && y >= Math.min(a.y, b.y) && y <= Math.max(a.y, b.y)) return true;
    if ((a.y > y) !== (b.y > y) && x < (b.x - a.x) * (y - a.y) / (b.y - a.y) + a.x) inside = !inside;
  }
  return inside;
}

function independentMasks(polygons) {
  const allowed = Buffer.alloc(SIZE * SIZE), occluded = Buffer.alloc(SIZE * SIZE);
  let a = 0, o = 0;
  for (let y = 0; y < SIZE; y++) for (let x = 0; x < SIZE; x++) {
    let yes = false, no = false;
    for (const polygon of polygons) if (insidePolygon(x + 0.5, y + 0.5, polygon.points)) {
      if (polygon.kind === "allowed") yes = true; else no = true;
    }
    const index = y * SIZE + x;
    if (no) { occluded[index] = 255; o++; }
    else if (yes) { allowed[index] = 255; a++; }
  }
  return { allowed, occluded, counts: { allowed: a, occluded: o, unknown: SIZE * SIZE - a - o } };
}

async function verifyPin(item) {
  assert.ok(item && typeof item.path === "string" && Number.isSafeInteger(item.bytes) && item.bytes >= 0);
  assert.match(item.sha256, /^[a-f0-9]{64}$/);
  const path = repoPath(item.path), info = await stat(path);
  assert.equal(info.size, item.bytes, item.path);
  const bytes = await readFile(path); assert.equal(hash(bytes), item.sha256, item.path);
  return path;
}

async function detectBrowserExecutable(channel) {
  const candidates = channel === "chrome"
    ? [join(process.env.PROGRAMFILES || "C:/Program Files", "Google/Chrome/Application/chrome.exe"),
      join(process.env["PROGRAMFILES(X86)"] || "C:/Program Files (x86)", "Google/Chrome/Application/chrome.exe"),
      join(process.env.LOCALAPPDATA || "C:/Users/ASUS/AppData/Local", "Google/Chrome/Application/chrome.exe")]
    : [join(process.env["PROGRAMFILES(X86)"] || "C:/Program Files (x86)", "Microsoft/Edge/Application/msedge.exe"),
      join(process.env.PROGRAMFILES || "C:/Program Files", "Microsoft/Edge/Application/msedge.exe")];
  for (const path of candidates) {
    try { const bytes = await readFile(path); return { path, bytes: bytes.length, sha256: hash(bytes) }; }
    catch (error) { if (error.code !== "ENOENT") throw error; }
  }
  throw new Error(`Installed ${channel} executable not found; do not substitute a browser.`);
}

async function buildFiles(path) {
  const result = [];
  for (const entry of await readdir(path, { withFileTypes: true })) {
    const child = join(path, entry.name);
    assert.ok(!entry.isSymbolicLink(), "Do not serve a symlink build entry.");
    if (entry.isDirectory()) result.push(...await buildFiles(child));
    else { assert.ok(entry.isFile()); result.push(child); }
  }
  return result;
}

async function telemetryReceiver(base) {
  const runToken = randomUUID(), received = [], rejected = [], consumers = new Set();
  const endpointPath = `/__mask_observer/${runToken}`;
  const kinds = ["create", "revoke", "bitmap-create", "bitmap-close", "pagehide-start", "pagehide-tail"];
  const id = value => Number.isSafeInteger(value) && value >= 1 && value <= 10_000;
  const nonce = value => typeof value === "string" && /^[0-9a-f-]{36}$/.test(value);
  const url = value => typeof value === "string" && value.startsWith(`blob:${base}/`) && value.length <= 256;
  const sameKeys = (value, keys) => value && typeof value === "object" && !Array.isArray(value)
    && Object.keys(value).sort().join("\0") === [...keys].sort().join("\0");
  function validate(value) {
    const keys = ["run_token", "document_nonce", "initial_url", "sequence", "kind"];
    if (value?.kind === "create" || value?.kind === "revoke") keys.push("url");
    else if (value?.kind === "bitmap-create" || value?.kind === "bitmap-close") keys.push("id");
    else if (value?.kind === "pagehide-start") keys.push("persisted");
    else if (value?.kind === "pagehide-tail") keys.push("persisted", "urls", "bitmaps", "previous_acceptance");
    assert.ok(sameKeys(value, keys)); assert.equal(value.run_token, runToken);
    assert.ok(nonce(value.document_nonce) && id(value.sequence) && kinds.includes(value.kind));
    assert.equal(value.initial_url, base + "/research/mask-editor.html");
    if ("url" in value) assert.ok(url(value.url));
    if ("id" in value) assert.ok(id(value.id));
    if ("persisted" in value) assert.equal(typeof value.persisted, "boolean");
    if (value.kind === "pagehide-tail") {
      assert.ok(Array.isArray(value.urls) && value.urls.length <= 128 && value.urls.every(url));
      assert.ok(Array.isArray(value.bitmaps) && value.bitmaps.length <= 128 && value.bitmaps.every(id));
      assert.ok(Array.isArray(value.previous_acceptance) && value.previous_acceptance.length <= 8);
      for (const item of value.previous_acceptance) {
        assert.ok(sameKeys(item, ["sequence", "kind", "accepted"]) && id(item.sequence)
          && kinds.includes(item.kind) && typeof item.accepted === "boolean");
      }
    }
    return value;
  }
  const server = createServer((request, response) => {
    if (request.method !== "POST" || request.url !== endpointPath) { response.writeHead(404).end(); return; }
    let size = 0; const pieces = [];
    request.on("data", chunk => {
      size += chunk.length;
      if (size > 4096) { rejected.push({ reason: "byte-budget", size }); request.destroy(); }
      else pieces.push(chunk);
    });
    request.on("error", error => rejected.push({ reason: "request-error", message: error.message }));
    request.on("end", () => {
      try {
        assert.ok(size > 0 && size <= 4096);
        const event = validate(JSON.parse(Buffer.concat(pieces).toString("utf8")));
        const item = { received_at_utc: new Date().toISOString(), bytes: size, event };
        assert.ok(!received.some(other => other.event.document_nonce === event.document_nonce
          && other.event.sequence === event.sequence), "Duplicate observer sequence.");
        received.push(item);
        for (const consumer of consumers) consumer(item);
        response.writeHead(204, { "Access-Control-Allow-Origin": "*" }).end();
      } catch (error) { rejected.push({ reason: "event-schema", message: error.message }); response.writeHead(400).end(); }
    });
  });
  await new Promise((accept, reject) => { server.once("error", reject); server.listen(0, "127.0.0.1", accept); });
  assert.equal(server.address().address, "127.0.0.1");
  return { endpoint: `http://127.0.0.1:${server.address().port}${endpointPath}`, runToken,
    received, rejected, consumers, validate,
    close: () => new Promise((accept, reject) => server.close(error => error ? reject(error) : accept())) };
}

function instrumentation({ endpoint, runToken, editorUrl }) {
  if (location.href !== editorUrl) return;
  const state = { clicks: [], live: new Set(), created: 0, revoked: 0,
    bitmapCreated: 0, bitmapClosed: 0, bitmapLive: new Set(), delayNextDecode: false,
    decodeHeld: false, releaseDecode: null, documentNonce: crypto.randomUUID(),
    initialUrl: location.href, sequence: 0, acceptance: [] };
  Object.defineProperty(window, "__maskHarness", { value: state });
  state.emit = value => {
    if (state.initialUrl !== editorUrl) return;
    const event = { run_token: runToken, document_nonce: state.documentNonce,
      initial_url: state.initialUrl, sequence: ++state.sequence, ...value };
    const accepted = navigator.sendBeacon(endpoint, JSON.stringify(event));
    state.acceptance.push({ sequence: event.sequence, kind: event.kind, accepted });
  };
  const create = URL.createObjectURL.bind(URL), revoke = URL.revokeObjectURL.bind(URL);
  URL.createObjectURL = (...args) => {
    const url = create(...args); state.live.add(url); state.created++;
    state.emit({ kind: "create", url });
    console.debug("__MASK_URL__" + JSON.stringify({ kind: "create", url })); return url;
  };
  URL.revokeObjectURL = url => {
    const answer = revoke(url);
    state.live.delete(url); state.revoked++;
    state.emit({ kind: "revoke", url });
    console.debug("__MASK_URL__" + JSON.stringify({ kind: "revoke", url })); return answer;
  };
  const createBitmap = window.createImageBitmap.bind(window);
  window.createImageBitmap = async (...args) => {
    const bitmap = await createBitmap(...args), id = ++state.bitmapCreated;
    state.bitmapLive.add(id);
    state.emit({ kind: "bitmap-create", id });
    console.debug("__MASK_BITMAP__" + JSON.stringify({ kind: "create", id }));
    const close = bitmap.close.bind(bitmap);
    bitmap.close = () => {
      const answer = close(); state.bitmapLive.delete(id); state.bitmapClosed++;
      state.emit({ kind: "bitmap-close", id });
      console.debug("__MASK_BITMAP__" + JSON.stringify({ kind: "close", id }));
      return answer;
    };
    if (state.delayNextDecode) {
      state.delayNextDecode = false; state.decodeHeld = true;
      await new Promise(accept => { state.releaseDecode = () => {
        state.decodeHeld = false; state.releaseDecode = null; accept();
      }; });
    }
    return bitmap;
  };
  addEventListener("pagehide", event => state.emit({ kind: "pagehide-start", persisted: event.persisted }));
  addEventListener("click", event => {
    if (!(event.target instanceof HTMLCanvasElement) || event.target.id !== "mask-canvas") return;
    const rect = event.target.getBoundingClientRect(), style = getComputedStyle(event.target);
    const left = rect.left + parseFloat(style.borderLeftWidth) + parseFloat(style.paddingLeft);
    const top = rect.top + parseFloat(style.borderTopWidth) + parseFloat(style.paddingTop);
    const width = rect.width - parseFloat(style.borderLeftWidth) - parseFloat(style.borderRightWidth)
      - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
    const height = rect.height - parseFloat(style.borderTopWidth) - parseFloat(style.borderBottomWidth)
      - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
    state.clicks.push({ clientX: event.clientX, clientY: event.clientY,
      x: (event.clientX - left) / width * 1024, y: (event.clientY - top) / height * 1024,
      content_rect: { left, top, width, height } });
  }, true);
}

async function runBrowser(spec, base, fixtures, output) {
  const browserOutput = join(output, spec.channel); await mkdir(browserOutput);
  const checks = [], pageErrors = [], requests = [], urlEvents = [], urlLive = new Set();
  const bitmapEvents = [], bitmapLive = new Set();
  const legacyConsoleUrls = new Set(), legacyConsoleBitmaps = new Set(), legacyConsoleEvents = [];
  const controlledRequests = [], documents = new Set();
  let telemetry, browser, context, page, currentStep = "launch";
  const record = { channel: spec.channel, synthetic_only: true, checks, page_errors: pageErrors,
    requests, url_events: urlEvents, bitmap_events: bitmapEvents,
    controlled_telemetry_requests: controlledRequests, legacy_console_events: legacyConsoleEvents,
    status: "running", executed_model_or_service_requests: false };
  const rebuildResources = () => {
    // The receiver is authoritative. Sort document sequence to tolerate beacon delivery order.
    const events = telemetry.received.map(item => item.event).filter(event => documents.has(event.document_nonce))
      .sort((a, b) => a.document_nonce.localeCompare(b.document_nonce) || a.sequence - b.sequence);
    urlEvents.splice(0, urlEvents.length, ...events.filter(event => event.kind === "create" || event.kind === "revoke"));
    bitmapEvents.splice(0, bitmapEvents.length, ...events.filter(event => event.kind === "bitmap-create" || event.kind === "bitmap-close"));
    urlLive.clear(); bitmapLive.clear();
    for (const event of events) {
      const key = event.document_nonce + ":" + (event.url ?? event.id);
      if (event.kind === "create") urlLive.add(key);
      else if (event.kind === "revoke") urlLive.delete(key);
      else if (event.kind === "bitmap-create") bitmapLive.add(key);
      else if (event.kind === "bitmap-close") bitmapLive.delete(key);
    }
  };
  const check = async (name, task) => {
    currentStep = name; await task(); checks.push({ name, status: "passed" });
    await writeFile(join(browserOutput, "progress.json"), JSON.stringify({ currentStep, checks }, null, 2));
  };
  const state = () => page.locator("#mask-editor").getAttribute("data-state");
  const count = async id => Number((await page.locator(id).textContent()).replace(/[^0-9]/g, ""));
  const downloadButtons = ["#download-allowed", "#download-occluded", "#download-draft"];
  const assertExportsDisabled = async () => {
    for (const id of downloadButtons) await expect(page.locator(id)).toBeDisabled();
  };
  const assertEmpty = async expectedState => {
    if (expectedState) await expect.poll(state).toBe(expectedState);
    assert.equal(await count("#allowed-count"), 0); assert.equal(await count("#occluded-count"), 0);
    assert.equal(await count("#unknown-count"), SIZE * SIZE);
    assert.equal(await count("#polygon-count"), 0); assert.equal(await count("#pending-count"), 0);
    for (const id of ["#editor-reviewer", "#editor-review-kind", "#editor-method", "#editor-version"])
      assert.equal(await page.locator(id).inputValue(), "");
    await assertExportsDisabled();
  };
  const load = async (bindingRole = "binding", targetRole = "target") => {
    await page.locator("#editor-binding").setInputFiles(fixtures[bindingRole]);
    await page.locator("#editor-target").setInputFiles(fixtures[targetRole]);
    await page.locator("#load-editor").click();
    await expect.poll(state).toBe("ready");
  };
  const clickNative = async (x, y) => {
    await page.locator("#mask-canvas").scrollIntoViewIfNeeded();
    const rect = await page.locator("#mask-canvas").evaluate(canvas => {
      const r = canvas.getBoundingClientRect(), s = getComputedStyle(canvas);
      return { left: r.left + parseFloat(s.borderLeftWidth) + parseFloat(s.paddingLeft),
        top: r.top + parseFloat(s.borderTopWidth) + parseFloat(s.paddingTop),
        width: r.width - parseFloat(s.borderLeftWidth) - parseFloat(s.borderRightWidth)
          - parseFloat(s.paddingLeft) - parseFloat(s.paddingRight),
        height: r.height - parseFloat(s.borderTopWidth) - parseFloat(s.borderBottomWidth)
          - parseFloat(s.paddingTop) - parseFloat(s.paddingBottom) };
    });
    const before = await page.evaluate(() => window.__maskHarness.clicks.length);
    const client = { x: Math.round(rect.left + x / SIZE * rect.width),
      y: Math.round(rect.top + y / SIZE * rect.height) };
    await page.mouse.click(client.x, client.y);
    const events = await page.evaluate(() => window.__maskHarness.clicks);
    assert.equal(events.length, before + 1);
    const event = events.at(-1);
    assert.equal(event.clientX, client.x); assert.equal(event.clientY, client.y);
    return { x: event.x, y: event.y };
  };
  const polygon = async (kind, points, viaKeyboard = true) => {
    await page.locator("#polygon-kind").selectOption(kind);
    const native = [];
    for (const [x, y] of points) native.push(await clickNative(x, y));
    if (viaKeyboard) await page.locator("#mask-canvas").press("Enter");
    else await page.locator("#finish-polygon").click();
    return { kind, points: native };
  };
  const reviewer = async () => {
    await page.locator("#editor-reviewer").fill("synthetic-browser-automation");
    await page.locator("#editor-review-kind").selectOption("ai");
    await page.locator("#editor-method").fill("synthetic-rectangle-contract-check");
    await page.locator("#editor-version").fill("mask-editor-browser-v1");
  };
  const prepareExport = async () => {
    await page.locator("#prepare-export").click();
    await expect.poll(state, { timeout: 20_000 }).toBe("prepared");
    for (const id of downloadButtons) await expect(page.locator(id)).toBeEnabled();
  };
  const setZoom = async value => {
    const slider = page.locator("#editor-zoom");
    await slider.press("Home");
    for (let current = 25; current < value; current += 25) await slider.press("ArrowRight");
    assert.equal(await slider.inputValue(), String(value));
  };
  const download = async (id, filename) => {
    const pending = page.waitForEvent("download"); await page.locator(id).click();
    const file = await pending; assert.equal(await file.failure(), null);
    const path = join(browserOutput, filename); await file.saveAs(path);
    return await readFile(path);
  };
  let actualPolygons = [], expectedMasks, downloadedDraft;
  try {
    telemetry = await telemetryReceiver(base);
    telemetry.consumers.add(rebuildResources);
    record.observer = { mechanism: "loopback-http-beacon-after-native-api-return",
      endpoint: telemetry.endpoint, byte_limit: 4096,
      scope: "Synthetic resource metadata only; no PNG, photo, draft or service upload" };
    record.executable_before = await detectBrowserExecutable(spec.channel);
    if (spec.executable) assert.deepEqual(record.executable_before, spec.executable, "Browser executable drifted from the frozen plan.");
    browser = await chromium.launch({ channel: spec.channel, headless: true });
    record.version = browser.version();
    context = await browser.newContext({ viewport: { width: 1600, height: 1400 }, deviceScaleFactor: 1,
      acceptDownloads: true });
    await context.addInitScript(instrumentation, { endpoint: telemetry.endpoint,
      runToken: telemetry.runToken, editorUrl: base + "/research/mask-editor.html" });
    page = await context.newPage(); page.setDefaultTimeout(10_000);
    page.on("pageerror", error => pageErrors.push(String(error)));
    page.on("request", request => {
      const item = { url: request.url(), method: request.method(), resource: request.resourceType() };
      if (request.url() === telemetry.endpoint) {
        controlledRequests.push({ ...item, bytes: request.postDataBuffer()?.byteLength ?? 0 });
      } else requests.push(item);
    });
    page.on("console", message => {
      const text = message.text();
      if (text.startsWith("__MASK_BITMAP__")) {
        const event = JSON.parse(text.slice("__MASK_BITMAP__".length));
        legacyConsoleEvents.push({ resource: "bitmap", ...event });
        if (event.kind === "create") legacyConsoleBitmaps.add(event.id); else legacyConsoleBitmaps.delete(event.id);
        return;
      }
      if (!text.startsWith("__MASK_URL__")) return;
      const event = JSON.parse(text.slice("__MASK_URL__".length));
      legacyConsoleEvents.push({ resource: "url", ...event });
      if (event.kind === "create") legacyConsoleUrls.add(event.url); else legacyConsoleUrls.delete(event.url);
    });
    await page.goto(base + "/research/mask-editor.html", { waitUntil: "networkidle" });
    documents.add(await page.evaluate(() => window.__maskHarness.documentNonce));
    rebuildResources();
    await check("initial-empty-no-human-default", async () => {
      await assertEmpty("empty");
      assert.equal(await page.locator("#polygon-kind").inputValue(), "");
    });
    await check("valid-native-input-and-explicit-binding", async () => {
      await load(); await assertEmpty("ready");
      assert.equal(await page.locator("#mask-canvas").getAttribute("width"), "1024");
      assert.equal(await page.locator("#mask-canvas").getAttribute("height"), "1024");
      const b = await json(fixtures.binding);
      for (const [key, id] of [["source_fingerprint", "#editor-source-sha"],
        ["generated_sha256", "#editor-generated-sha"], ["fit_sha256", "#editor-fit-sha"]])
        assert.equal(await page.locator(id).textContent(), b.stage[key]);
    });
    await check("real-keyboard-cancel-and-undo", async () => {
      await page.locator("#polygon-kind").selectOption("allowed");
      await clickNative(80, 80); await clickNative(160, 80);
      assert.equal(await count("#pending-count"), 2);
      await page.locator("#mask-canvas").press("Escape");
      assert.equal(await count("#pending-count"), 0);
      await polygon("allowed", [[40, 40], [80, 40], [80, 80], [40, 80]]);
      assert.equal(await count("#polygon-count"), 1);
      await page.locator("#undo-polygon").click();
      assert.equal(await count("#polygon-count"), 0);
      assert.equal(await count("#allowed-count"), 0);
    });
    await check("reject-collinear-and-self-crossing-without-crash", async () => {
      await polygon("allowed", [[100, 100], [200, 100], [300, 100]]);
      await expect(page.locator("#editor-error")).not.toHaveText("");
      assert.equal(await count("#polygon-count"), 0);
      await page.locator("#mask-canvas").press("Escape");
      await polygon("allowed", [[100, 100], [300, 300], [300, 100], [100, 300]], false);
      await expect(page.locator("#editor-error")).not.toHaveText("");
      assert.equal(await count("#polygon-count"), 0);
      await page.locator("#mask-canvas").press("Escape");
    });
    await check("native-allowed-and-occlusion-priority", async () => {
      await setZoom(50);
      actualPolygons.push(await polygon("allowed", [[100, 100], [300, 100], [300, 300], [100, 300]]));
      actualPolygons.push(await polygon("occluded", [[200, 200], [350, 200], [350, 350], [200, 350]], false));
      expectedMasks = independentMasks(actualPolygons);
      assert.equal(await count("#allowed-count"), expectedMasks.counts.allowed);
      assert.equal(await count("#occluded-count"), expectedMasks.counts.occluded);
      assert.equal(await count("#unknown-count"), expectedMasks.counts.unknown);
      assert.equal(await count("#polygon-count"), 2);
      await writeJson(join(browserOutput, "pointer-oracle.json"), { polygons: actualPolygons,
        counts: expectedMasks.counts, events: await page.evaluate(() => window.__maskHarness.clicks) });
      await page.screenshot({ path: join(browserOutput, "edited-synthetic.png"), fullPage: true });
    });
    await check("no-review-kind-default-and-three-real-downloads", async () => {
      assert.equal(await page.locator("#editor-review-kind").inputValue(), "");
      await reviewer(); await prepareExport();
      const allowed = await download("#download-allowed", "allowed.png");
      const occluded = await download("#download-occluded", "occluded.png");
      const draftBytes = await download("#download-draft", "draft.json");
      downloadedDraft = JSON.parse(draftBytes.toString("utf8"));
      assert.deepEqual(decodeMaskPng(allowed), expectedMasks.allowed);
      assert.deepEqual(decodeMaskPng(occluded), expectedMasks.occluded);
      assert.deepEqual(downloadedDraft.binding, await json(fixtures.binding));
      assert.equal(downloadedDraft.polygons.length, actualPolygons.length);
      for (let polygon = 0; polygon < actualPolygons.length; polygon++) {
        assert.equal(downloadedDraft.polygons[polygon].kind, actualPolygons[polygon].kind);
        assert.equal(downloadedDraft.polygons[polygon].points.length, actualPolygons[polygon].points.length);
        for (let point = 0; point < actualPolygons[polygon].points.length; point++)
          for (const axis of ["x", "y"]) assert.ok(Math.abs(downloadedDraft.polygons[polygon].points[point][axis]
            - actualPolygons[polygon].points[point][axis]) <= 1e-9, "Native pointer mapping changed beyond floating algebra tolerance.");
      }
      assert.equal(downloadedDraft.status, "draft_unsubmitted");
      assert.equal(downloadedDraft.schema_version, 1); assert.equal(downloadedDraft.protocol_id, EDITOR_PROTOCOL);
      for (const [key, value] of Object.entries(FLAGS)) assert.equal(downloadedDraft[key], value, key);
      assert.deepEqual(downloadedDraft.pixel_counts, expectedMasks.counts);
      for (const [kind, png] of [["allowed", allowed], ["occluded", occluded]]) {
        assert.equal(downloadedDraft.masks[kind].sha256, hash(png));
        assert.equal(downloadedDraft.masks[kind].bytes, png.length);
        assert.equal(downloadedDraft.masks[kind].pixels, expectedMasks.counts[kind]);
      }
      assert.equal(downloadedDraft.review.reviewer_kind, "ai");
      assert.equal(downloadedDraft.review.reviewer, "synthetic-browser-automation");
      record.exported_masks = { allowed: await pin(join(browserOutput, "allowed.png")),
        occluded: await pin(join(browserOutput, "occluded.png")), draft: await pin(join(browserOutput, "draft.json")) };
    });
    await check("css-zoom-does-not-change-native-mask", async () => {
      for (const zoom of [25, 100]) {
        await setZoom(zoom);
        await prepareExport();
        const allowed = await download("#download-allowed", `allowed-zoom-${zoom}.png`);
        const occluded = await download("#download-occluded", `occluded-zoom-${zoom}.png`);
        assert.deepEqual(decodeMaskPng(allowed), expectedMasks.allowed);
        assert.deepEqual(decodeMaskPng(occluded), expectedMasks.occluded);
      }
    });
    await check("metadata-and-edits-invalidate-export-snapshot", async () => {
      await page.locator("#editor-reviewer").fill("changed-synthetic-reviewer");
      await assertExportsDisabled();
      await reviewer(); await prepareExport();
      await page.locator("#polygon-kind").selectOption("allowed"); await clickNative(500, 500);
      await assertExportsDisabled();
      await page.locator("#mask-canvas").press("Escape");
      await page.locator("#clear-polygons").click();
      assert.equal(await count("#allowed-count"), 0); assert.equal(await count("#occluded-count"), 0);
      await assertExportsDisabled();
    });
    await check("changing-binding-clears-old-person-and-reviewer", async () => {
      await page.locator("#editor-binding").setInputFiles(fixtures.other_binding);
      await assertEmpty("empty");
      await page.locator("#load-editor").click(); await expect.poll(state).toBe("ready");
      await assertEmpty("ready");
      const b = await json(fixtures.other_binding);
      assert.equal(await page.locator("#editor-source-sha").textContent(), b.stage.source_fingerprint);
      await polygon("allowed", [[100, 100], [300, 100], [300, 300], [100, 300]]);
      await reviewer();
      await page.locator("#editor-target").setInputFiles(fixtures.wrongsize_target);
      await assertEmpty("empty");
    });
    await check("hash-mismatch-and-wrong-dimensions-fail-closed", async () => {
      for (const [bindingRole, targetRole] of [["mismatch_binding", "target"], ["wrongsize_binding", "wrongsize_target"]]) {
        await page.locator("#editor-binding").setInputFiles(fixtures[bindingRole]);
        await page.locator("#editor-target").setInputFiles(fixtures[targetRole]);
        await page.locator("#load-editor").click();
        await expect(page.locator("#editor-error")).not.toHaveText("");
        await assertEmpty("empty");
      }
    });
    await check("explicit-clear-releases-all-editor-state", async () => {
      await load();
      await polygon("allowed", [[100, 100], [300, 100], [300, 300], [100, 300]]);
      await reviewer(); await prepareExport();
      await download("#download-draft", "before-clear-draft.json");
      await page.locator("#clear-editor").click(); await assertEmpty("empty");
      await expect.poll(() => urlLive.size).toBe(0);
      await expect.poll(() => bitmapLive.size).toBe(0);
    });
    await check("late-native-decode-after-clear-or-replacement-is-closed", async () => {
      record.controlled_fault_scope = "Delay only the next completed native createImageBitmap result; no UI state, PNG bytes, hash or network stub.";
      for (const action of ["clear", "replace-target"]) {
        await page.locator("#editor-binding").setInputFiles(fixtures.binding);
        await page.locator("#editor-target").setInputFiles(fixtures.target);
        await page.evaluate(() => { window.__maskHarness.delayNextDecode = true; });
        await page.locator("#load-editor").click();
        await expect.poll(() => page.evaluate(() => window.__maskHarness.decodeHeld)).toBe(true);
        assert.equal(await state(), "loading");
        await expect.poll(() => bitmapLive.size).toBe(1);
        if (action === "clear") await page.locator("#clear-editor").click();
        else await page.locator("#editor-target").setInputFiles(fixtures.wrongsize_target);
        await assertEmpty("empty");
        await page.evaluate(() => window.__maskHarness.releaseDecode());
        await expect.poll(() => bitmapLive.size).toBe(0);
        await assertEmpty("empty");
      }
    });
    await check("pagehide-does-not-persist-draft-or-leak-urls", async () => {
      await load();
      await polygon("allowed", [[100, 100], [300, 100], [300, 300], [100, 300]]);
      await reviewer(); await prepareExport();
      await download("#download-draft", "before-pagehide-draft.json");
      await expect.poll(() => urlLive.size).toBe(1);
      await expect.poll(() => bitmapLive.size).toBe(1);
      record.live_urls_before_pagehide = urlLive.size;
      record.pagehide_before = await page.evaluate(() => ({ document_nonce: window.__maskHarness.documentNonce,
        urls: [...window.__maskHarness.live], bitmaps: [...window.__maskHarness.bitmapLive],
        send_beacon_acceptance: window.__maskHarness.acceptance }));
      assert.equal(record.pagehide_before.urls.length, 1);
      assert.equal(record.pagehide_before.bitmaps.length, 1);
      await page.evaluate(() => addEventListener("pagehide", event => {
        const state = window.__maskHarness;
        state.emit({ kind: "pagehide-tail", persisted: event.persisted,
          urls: [...state.live], bitmaps: [...state.bitmapLive], previous_acceptance: state.acceptance.slice(-8) });
      }));
      await page.goto("about:blank");
      const oldEvents = () => telemetry.received.map(item => item.event)
        .filter(event => event.document_nonce === record.pagehide_before.document_nonce);
      await expect.poll(() => oldEvents().filter(event => event.kind === "pagehide-tail").length).toBe(1);
      await expect.poll(() => urlLive.size).toBe(0);
      await expect.poll(() => bitmapLive.size).toBe(0);
      const received = oldEvents(), tail = received.find(event => event.kind === "pagehide-tail");
      assert.deepEqual(received.map(event => event.sequence).sort((a, b) => a - b),
        Array.from({ length: tail.sequence }, (_, index) => index + 1),
        "Every old-document resource event must actually reach the receiver.");
      assert.deepEqual(tail.urls, []); assert.deepEqual(tail.bitmaps, []);
      for (const url of record.pagehide_before.urls)
        assert.ok(received.some(event => event.kind === "revoke" && event.url === url));
      for (const id of record.pagehide_before.bitmaps)
        assert.ok(received.some(event => event.kind === "bitmap-close" && event.id === id));
      assert.ok(tail.previous_acceptance.every(item => item.accepted));
      record.pagehide_cleanup = { navigation: "about:blank", old_document_nonce: tail.document_nonce,
        actual_received_old_document_events: received, tail_empty: true,
        native_revoke_and_close_received: true, accepted_and_delivered_are_separate: true,
        legacy_console_only_counts_after_navigation: { urls: legacyConsoleUrls.size, bitmaps: legacyConsoleBitmaps.size } };
      await page.goto(base + "/research/mask-editor.html", { waitUntil: "networkidle" });
      documents.add(await page.evaluate(() => window.__maskHarness.documentNonce));
      rebuildResources();
      await assertEmpty("empty");
      const storage = await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length }));
      assert.deepEqual(storage, { local: 0, session: 0 });
      assert.equal((await context.cookies()).length, 0);
    });
    await check("no-page-errors-or-service-upload-requests", async () => {
      assert.deepEqual(pageErrors, []);
      assert.ok(requests.length > 0);
      for (const request of requests) {
        assert.ok(request.url.startsWith(base + "/") || request.url.startsWith("blob:"), request.url);
        assert.equal(request.method, "GET");
        assert.ok(!new URL(request.url).pathname.startsWith("/api/"));
      }
      assert.ok(controlledRequests.length > 0);
      for (const request of controlledRequests) {
        assert.equal(request.url, telemetry.endpoint); assert.equal(request.method, "POST");
        // Browser request metadata may omit an unloading document's POST body.
        // The separate HTTP receiver validates the actual bytes and closed schema.
        assert.ok(request.bytes >= 0 && request.bytes <= 4096);
      }
      assert.ok(telemetry.received.length > 0);
      for (const item of telemetry.received) assert.ok(item.bytes > 0 && item.bytes <= 4096);
      assert.deepEqual(telemetry.rejected, []);
      assert.ok(urlEvents.filter(item => item.kind === "create").length >= 3);
      assert.equal(urlLive.size, 0);
      assert.equal(bitmapLive.size, 0);
    });
    record.executable_after = await detectBrowserExecutable(spec.channel);
    assert.deepEqual(record.executable_after, record.executable_before);
    record.status = "passed";
  } catch (error) {
    record.status = "failed"; record.failed_step = currentStep;
    record.error = { name: error.name, message: error.message, stack: error.stack };
    if (page && !page.isClosed()) await page.screenshot({ path: join(browserOutput, "failure.png"), fullPage: true }).catch(() => {});
  } finally {
    if (page && !page.isClosed()) await page.close();
    if (context) await context.close();
    if (browser) await browser.close();
    if (telemetry) {
      await telemetry.close();
      record.observer_closed = true;
      record.actual_received_telemetry = telemetry.received;
      record.rejected_telemetry = telemetry.rejected;
    }
    record.resources_closed = true;
    record.live_urls_after_close = urlLive.size;
    record.live_bitmaps_after_close = bitmapLive.size;
    await writeJson(join(browserOutput, "report.json"), record);
  }
  return record;
}

export async function runFrozenPlan(studyPlan) {
  const planPath = repoPath(studyPlan), originalPlan = await readFile(planPath);
  assert.ok(originalPlan.length > 0 && originalPlan.length <= 1024 * 1024);
  const plan = JSON.parse(originalPlan.toString("utf8"));
  assert.equal(plan.protocol_id, PROTOCOL); assert.equal(plan.schema_version, 1);
  assert.ok(Array.isArray(plan.inputs) && plan.inputs.length > 0 && plan.inputs.length < 1000);
  const planned = new Map();
  for (const item of plan.inputs) {
    const path = await verifyPin(item); assert.ok(!planned.has(relativePath(path)));
    planned.set(relativePath(path), item);
  }
  for (const path of REQUIRED) assert.ok(planned.has(path), `Freeze ${path}.`);
  const fixtures = {};
  assert.deepEqual(Object.keys(plan.fixtures).sort(), [...FIXTURE_NAMES].sort());
  for (const name of FIXTURE_NAMES) {
    const item = plan.fixtures[name];
    assert.deepEqual(planned.get(item.path), item, "Every fixture must be in exact input pins.");
    fixtures[name] = await verifyPin(item);
  }
  const distFiles = await buildFiles(join(ROOT, "frontend/dist"));
  assert.ok(distFiles.length > 0 && distFiles.length < 1000);
  for (const path of distFiles) assert.ok(planned.has(relativePath(path)), `Freeze built file ${relativePath(path)}.`);
  assert.deepEqual([...planned.keys()].filter(path => path.startsWith("frontend/dist/")).sort(),
    distFiles.map(relativePath).sort(), "Freeze the exact production build file set.");
  if (plan.runtime) {
    assert.equal(plan.runtime.node, process.version);
    const nodeBytes = await readFile(process.execPath);
    assert.deepEqual(plan.runtime.executable, { path: process.execPath, bytes: nodeBytes.length, sha256: hash(nodeBytes) });
  }
  const output = await freshResearchDirectory(plan.output_dir);
  const policy = await json(repoPath("docs/mask-editor-v1.json"));
  assert.equal(policy.protocol_id, EDITOR_PROTOCOL);
  const results = [];
  let server, serverClosed = false;
  try {
    server = await preview({ root: join(ROOT, "frontend"), preview: { host: "127.0.0.1", port: 0, strictPort: true, open: false } });
    const address = server.httpServer.address();
    assert.ok(address && typeof address !== "string" && address.address === "127.0.0.1");
    const base = `http://127.0.0.1:${address.port}`;
    for (const channel of ["chrome", "msedge"]) results.push(await runBrowser({ channel,
      executable: plan.browser_executables?.[channel] }, base, fixtures, output));
  } finally {
    if (server) await new Promise((accept, reject) => server.httpServer.close(error => error ? reject(error) : accept()));
    serverClosed = true;
  }
  for (const item of plan.inputs) await verifyPin(item);
  assert.deepEqual((await buildFiles(join(ROOT, "frontend/dist"))).map(relativePath).sort(),
    distFiles.map(relativePath).sort());
  if (plan.runtime) {
    const nodeBytes = await readFile(process.execPath);
    assert.deepEqual(plan.runtime.executable, { path: process.execPath, bytes: nodeBytes.length, sha256: hash(nodeBytes) });
  }
  assert.deepEqual(await readFile(planPath), originalPlan);
  const status = results.length === 2 && results.every(record => record.status === "passed") ? "passed" : "failed";
  const report = { schema_version: 1, protocol_id: PROTOCOL, recorded_at_utc: new Date().toISOString(), status,
    scope: "Synthetic offline mask-editor engineering only; no live SAM, human review or stable-browser research-service qualification",
    plan: { path: relativePath(planPath), bytes: originalPlan.length, sha256: hash(originalPlan) },
    inputs: plan.inputs, input_pins_unchanged: true, plan_unchanged: true,
    runtime: { node: process.version, executable: process.execPath },
    browser_cases: results.map(record => ({ channel: record.channel, status: record.status, checks: record.checks.length,
      failed_step: record.failed_step ?? null, report: relativePath(join(output, record.channel, "report.json")),
      version: record.version ?? null })),
    server_closed: serverClosed, synthetic_only: true, new_model_inference: false,
    research_only: true, human_review_completed: false, independent_evaluation: false,
    identity_quality_accepted: false, production_enabled: false, g3_complete: false };
  await writeJson(join(output, "report.json"), report);
  console.log(JSON.stringify({ status, browsers: report.browser_cases, output: relativePath(output) }));
  assert.equal(status, "passed", "One or more actual browser cases failed; retain original evidence.");
  return report;
}

if (args.includes("--prepare")) {
  const fixtures = await prepareFixtures(option("--output-dir"));
  console.log(JSON.stringify({ status: "fixtures-prepared-no-browser-run", fixtures }));
} else if (args.includes("--run")) {
  await runFrozenPlan(option("--study-plan"));
} else {
  throw new Error("Use --prepare --output-dir <fresh research dir> or --run --study-plan <frozen plan>.");
}
