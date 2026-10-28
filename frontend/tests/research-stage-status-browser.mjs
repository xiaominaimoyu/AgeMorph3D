import assert from "node:assert/strict";
import { createHash, randomUUID } from "node:crypto";
import { once } from "node:events";
import { createServer } from "node:http";
import { mkdir, readFile, readdir, realpath, stat, writeFile } from "node:fs/promises";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { deflateSync } from "node:zlib";
import { chromium, expect } from "@playwright/test";
import { createServer as createViteServer } from "vite";

// Explicit synthetic UI checks. No product helper is used to make expected fixtures.
// --prepare writes fixtures, --freeze pins the completed product, --run needs that plan.
const ROOT = resolve(fileURLToPath(new URL("../../", import.meta.url)));
const RESEARCH = join(ROOT, "output/research");
const PROTOCOL = "agemorph3d-research-stage-status-browser-v1";
const EDITOR = "agemorph3d-mask-editor-v1";
const RULE = "native-top-left-pixel-centers-even-odd-edge-cross-1e-9-occlusion-priority-v1";
const SID = "a".repeat(32), FIRST_STAGE = "b".repeat(32), FP = "c".repeat(64), TOPO = "d".repeat(64);
const FLAGS = { research_only: true, human_review_completed: false, identity_quality_accepted: false,
  age_quality_accepted: false, visual_seam_quality_accepted: false, years_calibrated: false,
  service_ready: false, production_enabled: false, g3_complete: false };
const GRAPHICS = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"];
const args = process.argv.slice(2);
const option = key => {
  const i = args.indexOf(key);
  assert.ok(i >= 0 && args[i + 1] && !args[i + 1].startsWith("--"), `Specify ${key}.`);
  return args[i + 1];
};
const sha = data => createHash("sha256").update(data).digest("hex");
const rel = path => relative(ROOT, path).split(sep).join("/");
const repoPath = path => {
  const result = resolve(ROOT, path);
  assert.ok(!isAbsolute(relative(ROOT, result)) && !relative(ROOT, result).startsWith(".."));
  return result;
};
const json = async path => JSON.parse(await readFile(path, "utf8"));
const writeJson = (path, value) => writeFile(path, JSON.stringify(value, null, 2) + "\n", { flag: "wx" });
async function pin(path) { const bytes = await readFile(path); return { path: rel(path), bytes: bytes.length, sha256: sha(bytes) }; }
async function verify(pinValue) { assert.deepEqual(await pin(repoPath(pinValue.path)), pinValue, `Input drift: ${pinValue.path}`); }
async function fresh(value) {
  const path = repoPath(value);
  assert.ok(path !== RESEARCH && relative(RESEARCH, path) && !relative(RESEARCH, path).startsWith(".."));
  await mkdir(dirname(path), { recursive: true });
  const parent = await realpath(dirname(path));
  assert.ok(!relative(await realpath(RESEARCH), parent).startsWith(".."));
  await mkdir(path);
  return path;
}
function crc(bytes) {
  let n = 0xffffffff;
  for (const value of bytes) {
    n ^= value;
    for (let bit = 0; bit < 8; bit++) n = n & 1 ? 0xedb88320 ^ (n >>> 1) : n >>> 1;
  }
  return (n ^ 0xffffffff) >>> 0;
}
function chunk(type, data) {
  const result = Buffer.alloc(data.length + 12);
  result.writeUInt32BE(data.length); result.write(type, 4, "ascii"); result.set(data, 8);
  result.writeUInt32BE(crc(result.subarray(4, result.length - 4)), result.length - 4);
  return result;
}
function png(width, height, color, pixels) {
  const channels = color === 0 ? 1 : color === 2 ? 3 : 4;
  assert.equal(pixels.length, width * height * channels);
  const rows = Buffer.alloc((width * channels + 1) * height);
  for (let y = 0; y < height; y++) rows.set(pixels.subarray(y * width * channels, (y + 1) * width * channels), y * (width * channels + 1) + 1);
  const header = Buffer.alloc(13); header.writeUInt32BE(width); header.writeUInt32BE(height, 4); header[8] = 8; header[9] = color;
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", header),
    chunk("IDAT", deflateSync(rows, { level: 9 })), chunk("IEND", Buffer.alloc(0))]);
}
function triangleGlb(texture, extras) {
  const positions = Buffer.alloc(36), normals = Buffer.alloc(36), indices = Buffer.alloc(12), uv = Buffer.alloc(24);
  [0, 0, 0, 1, 0, 0, 0, 1, 0].forEach((n, i) => positions.writeFloatLE(n, i * 4));
  [0, 0, 1, 0, 0, 1, 0, 0, 1].forEach((n, i) => normals.writeFloatLE(n, i * 4));
  [0, 1, 2].forEach((n, i) => indices.writeUInt32LE(n, i * 4));
  [0, 0, 1, 0, 0, 1].forEach((n, i) => uv.writeFloatLE(n, i * 4));
  let offset = 0;
  const parts = [positions, normals, indices, uv, texture];
  const bufferViews = parts.map(bytes => { const view = { buffer: 0, byteOffset: offset, byteLength: bytes.length }; offset += bytes.length; return view; });
  const raw = Buffer.concat(parts), binary = Buffer.concat([raw, Buffer.alloc((4 - raw.length % 4) % 4)]);
  const doc = { asset: { version: "2.0" }, scene: 0, scenes: [{ nodes: [0], extras }],
    nodes: [{ mesh: 0, name: "Synthetic_Draft_Import_Triangle" }],
    meshes: [{ primitives: [{ attributes: { POSITION: 0, NORMAL: 1, TEXCOORD_0: 3 }, indices: 2, material: 0, mode: 4 }] }],
    extras, buffers: [{ byteLength: binary.length }], bufferViews,
    accessors: [{ bufferView: 0, componentType: 5126, count: 3, type: "VEC3", min: [0, 0, 0], max: [1, 1, 0] },
      { bufferView: 1, componentType: 5126, count: 3, type: "VEC3" },
      { bufferView: 2, componentType: 5125, count: 3, type: "SCALAR" },
      { bufferView: 3, componentType: 5126, count: 3, type: "VEC2" }],
    images: [{ bufferView: 4, mimeType: "image/png" }], textures: [{ sampler: 0, source: 0 }],
    samplers: [{ magFilter: 9729, minFilter: 9729, wrapS: 33071, wrapT: 33071 }],
    materials: [{ alphaMode: "MASK", alphaCutoff: 0.5, pbrMetallicRoughness: { baseColorFactor: [1, 1, 1, 1], baseColorTexture: { index: 0, texCoord: 0 } } }] };
  const encoded = Buffer.from(JSON.stringify(doc)), text = Buffer.concat([encoded, Buffer.alloc((4 - encoded.length % 4) % 4, 32)]);
  const header = Buffer.alloc(20), binHeader = Buffer.alloc(8);
  header.write("glTF"); header.writeUInt32LE(2, 4); header.writeUInt32LE(28 + text.length + binary.length, 8);
  header.writeUInt32LE(text.length, 12); header.write("JSON", 16);
  binHeader.writeUInt32LE(binary.length); binHeader.write("BIN\0", 4);
  return Buffer.concat([header, text, binHeader, binary]);
}

async function prepare() {
  const out = await fresh(option("--output-dir"));
  const targetPixels = Buffer.alloc(1024 * 1024 * 3);
  for (let y = 0; y < 1024; y++) for (let x = 0; x < 1024; x++) {
    const at = (y * 1024 + x) * 3; targetPixels[at] = x % 256; targetPixels[at + 1] = y % 256; targetPixels[at + 2] = (x + y) % 256;
  }
  const target = png(1024, 1024, 2, targetPixels), fit = Buffer.from('{"synthetic_fit":true,"model_execution":false}\n');
  const allowed = Buffer.alloc(1024 ** 2), occluded = Buffer.alloc(1024 ** 2);
  // Independent axis-aligned pixel-center oracle, not the implementation rasterizer.
  for (let y = 100; y < 180; y++) for (let x = 100; x < 220; x++) allowed[y * 1024 + x] = 255;
  for (let y = 120; y < 160; y++) for (let x = 140; x < 160; x++) { allowed[y * 1024 + x] = 0; occluded[y * 1024 + x] = 255; }
  const a = png(1024, 1024, 0, allowed), o = png(1024, 1024, 0, occluded);
  const altered = Buffer.from(allowed); altered[0] = 255;
  const alteredPng = png(1024, 1024, 0, altered);
  const binding = { schema_version: 1, protocol_id: EDITOR,
    stage: { stage_id: FIRST_STAGE, source_fingerprint: FP, target_condition: 45, generated_sha256: sha(target), fit_sha256: sha(fit) },
    width: 1024, height: 1024, research_only: true };
  const rect = (kind, x0, y0, x1, y1) => ({ kind, points: [{ x: x0, y: y0 }, { x: x1, y: y0 }, { x: x1, y: y1 }, { x: x0, y: y1 }] });
  const draft = { schema_version: 1, protocol_id: EDITOR, status: "draft_unsubmitted", binding,
    coordinate_rule: RULE, polygons: [rect("allowed", 100, 100, 220, 180), rect("occluded", 140, 120, 160, 160)],
    review: { reviewer: "synthetic-browser-record", reviewer_kind: "ai", method: "Synthetic rectangles only; no actual human review", version: "browser-v1" },
    masks: { allowed: { sha256: sha(a), bytes: a.length, pixels: 8800 }, occluded: { sha256: sha(o), bytes: o.length, pixels: 800 } },
    pixel_counts: { allowed: 8800, occluded: 800, unknown: 1024 ** 2 - 9600 }, ...FLAGS };
  const human = structuredClone(draft); human.review.reviewer_kind = "human"; human.review.reviewer = "synthetic-human-provenance-only";
  const badStage = structuredClone(draft); badStage.binding.stage.stage_id = "f".repeat(32);
  const badCount = structuredClone(draft); badCount.pixel_counts.allowed++;
  const badHash = structuredClone(draft); badHash.masks.allowed.sha256 = "0".repeat(64);
  const badPixels = structuredClone(draft); badPixels.masks.allowed = { sha256: sha(alteredPng), bytes: alteredPng.length, pixels: 8801 };
  badPixels.pixel_counts.allowed++; badPixels.pixel_counts.unknown--;
  const badFlag = structuredClone(draft); badFlag.human_review_completed = true;
  const age = { value: 40, method: "user", calibration_id: null };
  const atlasPixels = Buffer.alloc(256 * 256 * 4); atlasPixels.set([70, 80, 90, 255]);
  const atlas = png(256, 256, 6, atlasPixels);
  const coordinates = { version: "agemorph3d-static-canonical-v1", source_coordinate_system: "bfm_model_raw",
    normalization: "source_bbox_height_to_one", source_center: [0, 0, 0], source_bbox_height: 1,
    source_to_canonical_uniform_scale: 1, axis_rotation_row_major: [1, 0, 0, 0, 1, 0, 0, 0, 1],
    vertex_order_preserved: true, face_order_preserved: true, metric_scale_verified: false, source_topology_sha256: TOPO,
    source_projection_row_major: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0], source_roi: [0, 0, 120, 120] };
  const info = { session_id: SID, source_age: age, source_fingerprint: FP, shape: Array(40).fill(0),
    source_glb_url: `/research/sessions/${SID}/source.glb`, source_texture_url: `/research/sessions/${SID}/source-texture.png`, ...FLAGS };
  const extras = { asset_mode: "static", source_age: age, topology_id: `tddfa-bfm-canon-v1-${TOPO}`,
    coordinate_metadata: coordinates, base_texture: { input_kind: "original_photo", original_photo_observation: true } };
  const objects = { target: ["target.png", target], fit: ["fit.json", fit], allowed: ["allowed.png", a],
    other_allowed: ["other-allowed.png", a], occluded: ["occluded.png", o], altered_allowed: ["altered-allowed.png", alteredPng],
    atlas: ["atlas.png", atlas], source_glb: ["source.glb", triangleGlb(atlas, extras)] };
  const fixtures = {};
  for (const [role, [name, bytes]] of Object.entries(objects)) {
    const path = join(out, "browser-" + name); await writeFile(path, bytes, { flag: "wx" }); fixtures[role] = await pin(path);
  }
  for (const [role, value] of Object.entries({ draft, human, badStage, badCount, badHash, badPixels, badFlag, binding, info })) {
    const path = join(out, "browser-" + role + ".json"); await writeJson(path, value); fixtures[role] = await pin(path);
  }
  const receipt = { schema_version: 1, protocol_id: PROTOCOL, synthetic_only: true,
    independent_pixel_oracle: "axis-aligned pixel centers; allowed rectangle minus occluded rectangle", fixtures };
  await writeJson(join(out, "browser-fixtures.json"), receipt);
  console.log(JSON.stringify({ status: "prepared", manifest: rel(join(out, "browser-fixtures.json")), fixture_count: Object.keys(fixtures).length }));
}

async function browserPin(channel) {
  const roots = [process.env.PROGRAMFILES, process.env["PROGRAMFILES(X86)"], process.env.LOCALAPPDATA].filter(Boolean);
  const suffix = channel === "chrome" ? "Google/Chrome/Application/chrome.exe" : "Microsoft/Edge/Application/msedge.exe";
  for (const base of roots) {
    const path = join(base, suffix);
    try { const info = await stat(path); if (info.isFile()) { const bytes = await readFile(path); return { channel, path, bytes: bytes.length, sha256: sha(bytes) }; } } catch {}
  }
  throw new Error("Installed browser executable unavailable: " + channel);
}
async function freeze() {
  const fixturePath = repoPath(option("--fixtures")), manifest = await json(fixturePath);
  assert.equal(manifest.protocol_id, PROTOCOL); assert.equal(manifest.synthetic_only, true);
  for (const value of Object.values(manifest.fixtures)) await verify(value);
  const files = new Set(["docs/research-stage-availability-v1.json", "docs/mask-draft-import-v1.json", "docs/mask-editor-v1.json", "frontend/package.json",
    "frontend/package-lock.json", "frontend/vite.config.ts", "frontend/tsconfig.json", "frontend/tests/research-stage-status-browser.mjs",
    "frontend/research/session.ts", "frontend/research/session.html", "frontend/research/session.css",
    "frontend/tests/research-mask-draft.test.ts", "frontend/tests/research-mask-editor.test.ts", "frontend/tests/research-session.test.ts",
    "backend/src/agemorph3d/asset_cache.py", "backend/src/agemorph3d/research_aging_pipeline.py",
    "backend/src/agemorph3d/research_aging_service.py", "backend/src/agemorph3d/research_aging_app.py",
    "backend/tests/test_asset_cache.py", "backend/tests/test_research_aging_pipeline.py",
    "backend/tests/test_research_aging_service.py", "backend/tests/test_research_aging_app.py",
    "frontend/node_modules/@playwright/test/package.json", "frontend/node_modules/playwright/package.json",
    "frontend/node_modules/playwright-core/package.json", "frontend/node_modules/vite/package.json",
    "frontend/node_modules/three/package.json", "frontend/node_modules/typescript/package.json"]);
  for (const item of await readdir(join(ROOT, "frontend/src"), { withFileTypes: true })) if (item.isFile() && item.name.endsWith(".ts")) files.add("frontend/src/" + item.name);
  assert.ok(files.has("frontend/src/research-mask-draft.ts"), "Completed import module must exist before freezing.");
  const sources = await Promise.all([...files].sort().map(path => pin(repoPath(path))));
  const browsers = await Promise.all(["chrome", "msedge"].map(browserPin));
  const plan = { schema_version: 1, protocol_id: PROTOCOL, synthetic_only: true,
    fixtures: await pin(fixturePath), sources, browsers, graphics_args: GRAPHICS,
    runtime: { node: process.version, executable: process.execPath, executable_sha256: sha(await readFile(process.execPath)), platform: process.platform, arch: process.arch },
    ...FLAGS };
  const path = repoPath(option("--plan")); assert.ok(path.startsWith(RESEARCH + sep));
  await writeJson(path, plan);
  console.log(JSON.stringify({ status: "frozen_before_browser", path: rel(path), sources: sources.length, fixtures: Object.keys(manifest.fixtures).length, browsers: browsers.map(x => x.channel) }));
}

async function syntheticService(fixtures) {
  const content = {};
  for (const [key, value] of Object.entries(fixtures)) content[key] = await readFile(repoPath(value.path));
  const info = JSON.parse(content.info), baseStage = JSON.parse(content.binding).stage;
  const requests = [], submissions = [], beacons = [];
  let stageNumber = 0, checkMode = "available", pendingCheck = null;
  const server = createServer(async (request, response) => {
    response.setHeader("Access-Control-Allow-Origin", "*");
    response.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
    response.setHeader("Access-Control-Allow-Headers", "Content-Type");
    response.setHeader("Access-Control-Expose-Headers", "Content-Length, Content-Type");
    response.setHeader("Cache-Control", "no-store");
    let parts = [], total = 0;
    for await (const part of request) { total += part.length; if (total > 8 * 1024 ** 2) { response.writeHead(413); response.end(); return; } parts.push(part); }
    const body = Buffer.concat(parts), path = new URL(request.url, "http://127.0.0.1").pathname;
    requests.push({ method: request.method, path, bytes: body.length });
    const send = (value, media = "application/json", status = 200) => {
      const bytes = Buffer.isBuffer(value) ? value : Buffer.from(JSON.stringify(value));
      response.writeHead(status, { "Content-Type": media, "Content-Length": bytes.length }); response.end(bytes);
    };
    try {
      if (request.method === "OPTIONS") { response.writeHead(204); response.end(); return; }
      if (path === "/__browser_probe/pagehide") { beacons.push(JSON.parse(body.toString("utf8"))); send({ recorded: true }); return; }
      if (path === "/research/health") { send({ ...FLAGS, service: { closed: false }, capabilities: { reconstruction: false, age_morph: false, age_texture: false, realtime: false } }); return; }
      if (path === `/research/sessions/${SID}` && request.method === "GET") { stageNumber = 0; send(info); return; }
      if (path === `/research/sessions/${SID}/source.glb`) { send(content.source_glb, "model/gltf-binary"); return; }
      if (path === `/research/sessions/${SID}/source-texture.png`) { send(content.atlas, "image/png"); return; }
      if (path === `/research/sessions/${SID}/conditions` && request.method === "POST") {
        assert.equal(JSON.parse(body).condition, 45);
        const stage_id = stageNumber++ === 0 ? FIRST_STAGE : "e".repeat(32);
        send({ staged: { ...baseStage, stage_id }, preview_url: `/research/sessions/${SID}/stages/${stage_id}/preview.png`,
          fit_url: `/research/sessions/${SID}/stages/${stage_id}/fit.json`, ...FLAGS }); return;
      }
      if (new RegExp(`^/research/sessions/${SID}/stages/[0-9a-f]{32}/status$`).test(path) && request.method === "GET") {
        const mode = checkMode, id = path.split("/")[5];
        const value = { staged: { ...baseStage, stage_id: id }, ...FLAGS, status: "available",
          ttl_extended: false, reservation_held: false,
          preview_url: `/research/sessions/${SID}/stages/${id}/preview.png`,
          fit_url: `/research/sessions/${SID}/stages/${id}/fit.json` };
        if (mode === "wrong_binding") value.staged.fit_sha256 = "f".repeat(64);
        if (mode === "claimed_renewal") value.ttl_extended = true;
        if (mode === "delayed") await new Promise(resolve => { pendingCheck = { release: resolve }; });
        if (response.destroyed) return;
        if (mode === "check_timeout") { send({ code: "TIMEOUT" }, "application/json", 504); return; }
        if (mode === "stage_expired" || mode === "session_expired") {
          send({ code: mode === "stage_expired" ? "STAGE_EXPIRED" : "SESSION_EXPIRED" }, "application/json", 404); return;
        }
        send(value); return;
      }
      if (new RegExp(`^/research/sessions/${SID}/stages/[0-9a-f]{32}/preview\\.png$`).test(path)) { send(content.target, "image/png"); return; }
      if (new RegExp(`^/research/sessions/${SID}/stages/[0-9a-f]{32}/fit\\.json$`).test(path)) { send(content.fit); return; }
      if (new RegExp(`^/research/sessions/${SID}/stages/[0-9a-f]{32}/reviews$`).test(path) && request.method === "POST") {
        submissions.push({ path, payload: JSON.parse(body.toString("utf8")) });
        send({ code: "STAGE_EXPIRED", message: "Synthetic rejection; no model or registration executed" }, "application/json", 410); return;
      }
      send({ code: "NOT_FOUND", path }, "application/json", 404);
    } catch (error) { send({ code: "SYNTHETIC_FIXTURE_ERROR", message: String(error) }, "application/json", 500); }
  });
  server.listen(0, "127.0.0.1"); await once(server, "listening");
  const base = `http://127.0.0.1:${server.address().port}`;
  return { base, requests, submissions, beacons, content, setCheckMode: value => { checkMode = value; }, get checkPending() { return !!pendingCheck; }, releaseCheck: () => { const pending = pendingCheck; pendingCheck = null; pending?.release(); }, close: async () => { pendingCheck?.release(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); } };
}

async function browserRun(spec, base, fixtures, service, out, probe) {
  let browser, context, page, currentCase = "setup";
  const started = new WeakMap();
  const record = { channel: spec.channel, cases: [], request_failures: [], page_errors: [],
    actual_product_modules: true, synthetic_service: true, model_execution: false, ...FLAGS };
  const state = () => page.evaluate(() => window.__researchSessionTools.state());
  const idle = () => expect.poll(async () => (await state()).busy).toBe(false);
  const check = async (name, action) => { currentCase = name; await action(); record.cases.push({ name, passed: true }); };
  try {
    assert.deepEqual(await browserPin(spec.channel), spec);
    browser = await chromium.launch({ channel: spec.channel, headless: true, args: GRAPHICS });
    record.version = browser.version();
    context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, deviceScaleFactor: 1 });
    page = await context.newPage(); page.setDefaultTimeout(15000);
    page.on("pageerror", error => record.page_errors.push(String(error)));
    page.on("request", req => started.set(req, currentCase));
    page.on("requestfailed", req => record.request_failures.push({ url: req.url(), method: req.method(),
      case: started.get(req), error: req.failure()?.errorText }));
    const bind = async (reload = false) => {
      service.setCheckMode("available");
      if (reload) { await page.goto(base + "/research/session.html"); await page.waitForFunction(() => !!window.__researchSessionTools); await page.locator("#service-url").fill(service.base); }
      if (!await page.locator("details.existing-session").evaluate(node => node.open)) await page.locator("details.existing-session > summary").click();
      await page.locator("#existing-session-id").fill(SID); await page.locator("#connect-existing").click();
      await expect.poll(async () => { const s = await state(); return s.hasSourceBytes && !s.busy; }).toBe(true);
      await page.locator("#target-condition").fill("45"); await page.locator("#stage-condition").click(); await idle();
      assert.ok((await state()).pendingStage);
    };
    const importDraft = async () => {
      for (const [id, role] of [["review-allowed", "allowed"], ["review-occluded", "occluded"], ["review-draft", "draft"]])
        await page.locator("#" + id).setInputFiles(repoPath(fixtures[role].path));
      await page.locator("#verify-review-draft").click(); await idle(); assert.equal((await state()).draftVerified, true);
    };
    const press = async mode => { service.setCheckMode(mode); await page.locator("#check-review-stage").click(); await idle(); };
    const delay = async () => {
      service.setCheckMode("delayed"); await page.locator("#check-review-stage").click();
      await expect.poll(() => service.checkPending).toBe(true); assert.equal((await state()).stageCheckPending, true);
    };
    const clearedReview = async () => {
      const s = await state(); assert.equal(s.pendingStage, null); assert.equal(s.draftVerified, false);
      await expect(page.locator("#review-draft")).toHaveValue("");
      await expect(page.locator("#register-review")).toBeDisabled();
      await expect(page.locator("#review-stage-status")).toHaveAttribute("data-state", "unchecked");
    };
    await page.goto(base + "/research/session.html"); await page.waitForFunction(() => !!window.__researchSessionTools);
    await check("no-stage-check-before-current-review", async () => { await expect(page.locator("#check-review-stage")).toBeDisabled(); });
    await bind(true);
    await check("draft-import-does-not-automatically-query-stage", async () => {
      const before = service.requests.filter(r => r.path.endsWith("/status")).length;
      await importDraft(); assert.equal(service.requests.filter(r => r.path.endsWith("/status")).length, before);
    });
    await check("available-snapshot-is-one-get-with-no-assets-post-or-review-loss", async () => {
      const before = service.requests.length; await press("available");
      const requests = service.requests.slice(before);
      assert.deepEqual(requests.map(r => [r.method, r.path, r.bytes]), [["GET", `/research/sessions/${SID}/stages/${FIRST_STAGE}/status`, 0]]);
      assert.equal((await state()).draftVerified, true); assert.equal(service.submissions.length, 0);
      await expect(page.locator("#register-review")).toBeEnabled();
      await expect(page.locator("#review-stage-status")).toHaveAttribute("data-state", "available");
      await expect(page.locator("#review-stage-status")).toContainText("不续期");
      await page.screenshot({ path: join(out, `browser-${spec.channel}-available.png`), fullPage: true });
    });
    for (const mode of ["wrong_binding", "claimed_renewal"]) await check("reject-" + mode + "-without-claiming-active", async () => {
      await press(mode); await expect(page.locator("#review-stage-status")).toHaveAttribute("data-state", "unknown");
      await expect(page.locator("#error")).toBeVisible(); assert.ok((await state()).pendingStage);
      assert.equal(service.submissions.length, 0);
    });
    await check("check-timeout-keeps-source-and-does-not-claim-native-work", async () => {
      await press("check_timeout");
      await expect(page.locator("#error")).toContainText("检查超时");
      await expect(page.locator("#error")).not.toContainText("后台原生工作");
      await expect(page.locator("#review-stage-status")).toHaveAttribute("data-state", "unknown");
      assert.ok((await state()).pendingStage); assert.equal((await state()).hasSourceBytes, true);
    });
    await check("stage-expiry-clears-review-but-keeps-current-source", async () => {
      await press("stage_expired"); await clearedReview(); assert.equal((await state()).hasSourceBytes, true);
      await expect(page.locator("#error")).toContainText("过期");
    });
    await bind();
    await check("session-expiry-clears-source-and-review", async () => {
      await press("session_expired"); await clearedReview(); assert.equal((await state()).hasSourceBytes, false);
    });
    await bind();
    await check("cancelled-old-check-cannot-replace-a-new-available-snapshot", async () => {
      await delay(); await page.locator("#cancel-work").click(); await clearedReview();
      await bind(); await press("available"); service.releaseCheck(); await page.waitForTimeout(150); await idle();
      await expect(page.locator("#review-stage-status")).toHaveAttribute("data-state", "available");
      assert.equal((await state()).stageCheckPending, false);
    });
    await check("late-condition-input-invalidates-pending-check", async () => {
      await delay();
      await page.locator("#target-condition").evaluate(node => { node.value = "46"; node.dispatchEvent(new Event("input", { bubbles: true })); });
      service.releaseCheck(); await idle(); await clearedReview(); assert.equal((await state()).hasSourceBytes, true);
    });
    await bind();
    await check("new-source-selection-invalidates-pending-check", async () => {
      await delay(); await page.locator("#source-file").setInputFiles(repoPath(fixtures.target.path));
      service.releaseCheck(); await idle(); await clearedReview(); assert.equal((await state()).hasSourceBytes, false);
    });
    await bind();
    await check("pagehide-aborts-check-and-releases-page-state", async () => {
      await delay(); const nonce = randomUUID();
      await page.evaluate(({ endpoint, nonce }) => {
        window.addEventListener("pagehide", () => navigator.sendBeacon(endpoint, JSON.stringify({ nonce, state: window.__researchSessionTools.state() })), { once: true });
      }, { endpoint: probe.base, nonce });
      await page.goto("about:blank"); service.releaseCheck();
      await expect.poll(() => probe.receipts.some(x => x.nonce === nonce)).toBe(true);
      record.pagehide = probe.receipts.find(x => x.nonce === nonce);
      const s = record.pagehide.state;
      assert.equal(s.destroyed, true); assert.equal(s.stageCheckPending, false); assert.equal(s.pendingStage, null);
      assert.equal(s.objectUrls, 0); assert.equal(s.hasSourceBytes, false);
    });
    assert.deepEqual(record.page_errors, []); assert.equal(service.submissions.length, 0);
    assert.deepEqual(await browserPin(spec.channel), spec); record.status = "passed";
  } catch (error) { record.status = "failed"; record.error = error.stack || String(error); }
  finally {
    service.releaseCheck();
    if (context) { await context.close(); record.context_closed = true; }
    if (browser) { await browser.close(); record.browser_closed = true; }
    await writeJson(join(out, `browser-${spec.channel}-report.json`), record);
  }
  return record;
}

async function run() {
  const planPath = repoPath(option("--plan")), planPin = await pin(planPath), plan = await json(planPath);
  assert.equal(plan.protocol_id, PROTOCOL); assert.equal(plan.synthetic_only, true);
  assert.equal(plan.runtime.node, process.version); assert.deepEqual(plan.graphics_args, GRAPHICS);
  assert.equal(plan.runtime.executable_sha256, sha(await readFile(process.execPath)));
  for (const p of plan.sources) await verify(p);
  await verify(plan.fixtures); const fixtures = (await json(repoPath(plan.fixtures.path))).fixtures;
  for (const p of Object.values(fixtures)) await verify(p);
  const out = await fresh(option("--output-dir"));
  const report = { protocol_id: PROTOCOL, plan: planPin, synthetic_only: true, ...FLAGS,
    real_service_or_model_acceptance: false, graphics_args: GRAPHICS, browsers: [] };
  let vite, server, service; const probe = { receipts: [] };
  try {
    const snapshots = join(out, "snapshots"); await mkdir(snapshots);
    for (let i = 0; i < plan.sources.length; i++) {
      const p = plan.sources[i]; await writeFile(join(snapshots, `${i}-${p.path.split("/").at(-1)}`), await readFile(repoPath(p.path)), { flag: "wx" });
    }
    await writeJson(join(out, "plan-frozen.json"), plan);
    service = await syntheticService(fixtures); report.service_origin = service.base;
    server = createServer(async (request, response) => {
      let body = ""; for await (const p of request) { body += p; if (Buffer.byteLength(body) > 4096) { response.writeHead(413); response.end(); return; } }
      probe.receipts.push(JSON.parse(body)); response.writeHead(204); response.end();
    });
    server.listen(0, "127.0.0.1"); await once(server, "listening"); probe.base = `http://127.0.0.1:${server.address().port}/pagehide`;
    report.probe_endpoint = probe.base;
    vite = await createViteServer({ root: join(ROOT, "frontend"), configFile: join(ROOT, "frontend/vite.config.ts"),
      server: { host: "127.0.0.1", port: 0, strictPort: false, open: false }, logLevel: "error" });
    await vite.listen(); const base = `http://127.0.0.1:${vite.httpServer.address().port}`; report.page_origin = base;
    for (const spec of plan.browsers) {
      const record = await browserRun(spec, base, fixtures, service, out, probe); report.browsers.push(record);
      assert.equal(record.status, "passed", record.error);
    }
    for (const p of plan.sources) await verify(p);
    for (const p of Object.values(fixtures)) await verify(p);
    await verify(planPin); report.inputs_unchanged = true; report.status = "passed";
  } catch (error) { report.status = "failed"; report.error = error.stack || String(error); }
  finally {
    if (service) { report.service_requests = service.requests; report.explicit_submissions = service.submissions; await service.close(); }
    if (vite) await vite.close();
    if (server) { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
    report.pagehide_receipts = probe.receipts;
    report.cleanup = { service_closed: !!service, vite_closed: !!vite, probe_closed: !!server,
      contexts_closed: report.browsers.every(b => b.context_closed && b.browser_closed) };
    await writeJson(join(out, "browser-report.json"), report);
    console.log(JSON.stringify({ status: report.status, output: rel(out),
      browsers: report.browsers.map(b => ({ channel: b.channel, status: b.status, cases: b.cases.length, request_failures: b.request_failures.length })), error: report.error }));
  }
  if (report.status !== "passed") process.exitCode = 1;
}

if (args.includes("--prepare")) await prepare();
else if (args.includes("--freeze")) await freeze();
else if (args.includes("--run")) await run();
else throw new Error("Use --prepare, --freeze or --run explicitly.");
