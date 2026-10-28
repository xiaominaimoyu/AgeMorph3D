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
const PROTOCOL = "agemorph3d-mask-draft-import-browser-v1";
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
  const files = new Set(["docs/mask-draft-import-v1.json", "docs/mask-editor-v1.json", "frontend/package.json",
    "frontend/package-lock.json", "frontend/vite.config.ts", "frontend/tsconfig.json", "frontend/tests/mask-draft-import-browser.mjs",
    "frontend/research/session.ts", "frontend/research/session.html", "frontend/research/session.css",
    "frontend/tests/research-mask-draft.test.ts", "frontend/tests/research-mask-editor.test.ts",
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
  let stageNumber = 0;
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
  return { base, requests, submissions, beacons, content, close: async () => { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); } };
}

async function browserRun(spec, base, fixtures, service, out) {
  let browser, context, page;
  const initialSubmissions = service.submissions.length;
  const record = { channel: spec.channel, cases: [], page_errors: [], request_failures: [], graphics_args: GRAPHICS,
    actual_product_modules: true, synthetic_loopback_service: true, mocked_product_modules: false,
    model_execution: false, ordinary_gpu_or_real_service_qualification: false };
  const state = () => page.evaluate(() => window.__researchSessionTools.state());
  const file = key => repoPath(fixtures[key].path);
  const check = async (name, action) => { await action(); record.cases.push({ name, passed: true }); };
  try {
    assert.deepEqual(await browserPin(spec.channel), spec);
    browser = await chromium.launch({ channel: spec.channel, headless: true, args: GRAPHICS });
    record.version = browser.version();
    context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, deviceScaleFactor: 1 });
    page = await context.newPage(); page.setDefaultTimeout(15000);
    page.on("pageerror", error => record.page_errors.push(String(error)));
    page.on("requestfailed", request => record.request_failures.push({ url: request.url(), method: request.method(), error: request.failure()?.errorText }));
    const bound = async () => {
      await expect.poll(async () => { const s = await state(); return s.hasSourceBytes && !s.busy; }).toBe(true);
    };
    const idle = () => expect.poll(async () => (await state()).busy).toBe(false);
    const bindStage = async (reload = true) => {
      if (reload) { await page.goto(base + "/research/session.html"); await page.waitForFunction(() => !!window.__researchSessionTools); await page.locator("#service-url").fill(service.base); }
      if (!await page.locator("details.existing-session").evaluate(node => node.open))
        await page.locator("details.existing-session > summary").click();
      await page.locator("#existing-session-id").fill(SID);
      await page.locator("#connect-existing").click(); await bound();
      await page.locator("#target-condition").fill("45"); await page.locator("#stage-condition").click();
      await expect.poll(async () => { const s = await state(); return s.pendingStage?.stage_id === FIRST_STAGE && !s.busy; }).toBe(true);
      await expect(page.locator("#review-area")).toBeVisible();
    };
    const select = async (draft = "draft", allowed = "allowed") => {
      await page.locator("#review-allowed").setInputFiles(file(allowed));
      await page.locator("#review-occluded").setInputFiles(file("occluded"));
      await page.locator("#review-draft").setInputFiles(file(draft));
    };
    const verify = async () => { await page.locator("#verify-review-draft").click(); await idle(); };
    const assertEmptyRecord = async () => {
      for (const selector of ["#review-reviewer", "#review-method", "#review-version"]) await expect(page.locator(selector)).toHaveValue("");
      assert.equal((await state()).draftVerified, false); await expect(page.locator("#register-review")).toBeDisabled();
    };
    const verified = async draft => {
      await select(draft); await verify(); assert.equal((await state()).draftVerified, true);
      await expect(page.locator("#register-review")).toBeEnabled();
      await expect(page.locator("#review-draft-status")).toHaveAttribute("data-state", "verified");
    };
    await bindStage();
    await check("empty-stage-needs-three-explicit-inputs", async () => {
      await expect(page.locator("#verify-review-draft")).toBeDisabled(); await assertEmptyRecord();
    });
    await check("valid-import-is-local-and-atomic", async () => {
      await select(); const requests = service.requests.length; await verify();
      assert.equal(service.requests.length, requests, "Verification sent a service request.");
      assert.equal((await state()).draftVerified, true);
      await expect(page.locator("#review-reviewer")).toHaveValue("synthetic-browser-record");
      await expect(page.locator("#review-kind")).toHaveValue("ai");
      await expect(page.locator("#register-review")).toBeEnabled();
    });
    await check("mask-selection-replacement-invalidates-metadata", async () => {
      await page.locator("#review-allowed").setInputFiles(file("other_allowed")); await assertEmptyRecord();
    });
    await check("reviewer-edit-invalidates-selected-draft", async () => {
      await verified("draft"); await page.locator("#review-reviewer").fill("edited synthetic record");
      assert.equal((await state()).draftVerified, false); await expect(page.locator("#register-review")).toBeDisabled();
    });
    await check("explicit-draft-removal-restores-manual-path", async () => {
      await page.locator("#clear-review-draft").click(); await expect(page.locator("#review-draft")).toHaveValue("");
      await assertEmptyRecord();
      await page.locator("#review-reviewer").fill("manual synthetic record"); await page.locator("#review-method").fill("manual synthetic test");
      await page.locator("#review-version").fill("manual-v1"); await expect(page.locator("#register-review")).toBeEnabled();
      assert.equal(service.submissions.length, initialSubmissions);
    });
    for (const [draft, allowed] of [["badStage", "allowed"], ["badCount", "allowed"], ["badHash", "allowed"],
      ["badPixels", "altered_allowed"], ["badFlag", "allowed"]]) {
      await check("reject-" + draft + "-without-half-record-or-post", async () => {
        await select(draft, allowed); const before = service.requests.length; await verify(); await assertEmptyRecord();
        await expect(page.locator("#error")).toBeVisible(); assert.equal(service.requests.length, before);
      });
    }
    await check("late-review-change-during-register-validation-sends-no-post", async () => {
      await verified("draft");
      await page.evaluate(() => {
        const native = window.createImageBitmap;
        window.__registerHeld = { entered: false, release: null, used: false };
        window.createImageBitmap = function (...args) {
          const result = native.apply(this, args);
          if (window.__registerHeld.used) return result;
          window.__registerHeld.used = true;
          return result.then(bitmap => new Promise(resolve => {
            window.__registerHeld.entered = true; window.__registerHeld.release = () => resolve(bitmap);
          }));
        };
      });
      const before = service.submissions.length;
      await page.locator("#register-review").click();
      await page.waitForFunction(() => window.__registerHeld.entered);
      // Simulate a delayed change already queued before the fieldset became disabled.
      await page.evaluate(() => {
        const input = document.querySelector("#review-reviewer"); input.value = "late synthetic change";
        input.dispatchEvent(new Event("change", { bubbles: true })); window.__registerHeld.release();
      });
      await idle(); assert.equal(service.submissions.length, before);
      assert.equal((await state()).draftVerified, false); assert.ok((await state()).pendingStage);
      await expect(page.locator("#register-review")).toBeDisabled();
    });
    await check("human-provenance-keeps-qualification-closed", async () => {
      await verified("human"); await expect(page.locator("#review-kind")).toHaveValue("human");
      const s = await state(); assert.equal(s.research_only, true); assert.equal(s.service_ready, false); assert.equal(s.g3_complete, false);
      await page.screenshot({ path: join(out, "browser-" + spec.channel + "-verified.png"), fullPage: true });
    });
    await check("explicit-submit-uses-verified-snapshots-and-server-expiry", async () => {
      await page.evaluate(() => {
        const originals = [document.querySelector("#review-allowed").files[0], document.querySelector("#review-occluded").files[0]];
        const native = File.prototype.arrayBuffer;
        File.prototype.arrayBuffer = function () { if (originals.includes(this)) throw new Error("Selected original File reread after verification"); return native.call(this); };
      });
      const before = service.submissions.length; await page.locator("#register-review").click();
      await expect.poll(() => service.submissions.length).toBe(before + 1); await idle();
      const payload = service.submissions.at(-1).payload;
      assert.equal(payload.reviewer, "synthetic-human-provenance-only"); assert.equal(payload.reviewer_kind, "human");
      assert.equal(payload.source_fingerprint, FP);
      assert.equal(sha(Buffer.from(payload.allowed_png_b64, "base64")), fixtures.allowed.sha256);
      assert.equal(sha(Buffer.from(payload.occluded_png_b64, "base64")), fixtures.occluded.sha256);
      assert.equal((await state()).pendingStage, null); assert.equal((await state()).draftVerified, false);
      await expect(page.locator("#error")).toContainText("过期");
    });
    await bindStage();
    await check("new-stage-clears-previous-import", async () => {
      await verified("draft"); await page.locator("#stage-condition").click(); await idle();
      assert.equal((await state()).pendingStage.stage_id, "e".repeat(32));
      await assertEmptyRecord(); await expect(page.locator("#review-draft")).toHaveValue("");
    });
    await bindStage();
    await check("cancelled-old-read-cannot-overwrite-new-import", async () => {
      await select();
      await page.evaluate(() => {
        const held = document.querySelector("#review-draft").files[0], native = File.prototype.arrayBuffer;
        window.__draftHeld = { entered: false, release: null };
        File.prototype.arrayBuffer = function () {
          const result = native.call(this);
          return this === held ? result.then(bytes => new Promise(resolve => {
            window.__draftHeld.entered = true; window.__draftHeld.release = () => resolve(bytes);
          })) : result;
        };
      });
      await page.locator("#verify-review-draft").click();
      await page.waitForFunction(() => window.__draftHeld.entered);
      await page.locator("#cancel-work").click(); await assertEmptyRecord();
      assert.equal((await state()).hasSourceBytes, false);
      await bindStage(false); await verified("human");
      await page.evaluate(() => window.__draftHeld.release());
      await page.waitForTimeout(200);
      assert.equal((await state()).draftVerified, true); assert.equal((await state()).draftImportBusy, false);
      await expect(page.locator("#review-reviewer")).toHaveValue("synthetic-human-provenance-only");
    });
    await check("condition-change-clears-import", async () => {
      await page.locator("#target-condition").fill("46"); await assertEmptyRecord();
      assert.equal((await state()).pendingStage, null); await expect(page.locator("#review-draft")).toHaveValue("");
    });
    await bindStage(); await verified("draft");
    await check("real-pagehide-releases-import-and-source-state", async () => {
      const nonce = randomUUID();
      await page.evaluate(({ endpoint, nonce }) => {
        window.addEventListener("pagehide", () => {
          navigator.sendBeacon(endpoint, JSON.stringify({ nonce, state: window.__researchSessionTools.state() }));
        }, { once: true });
      }, { endpoint: service.base + "/__browser_probe/pagehide", nonce });
      await page.goto("about:blank");
      await expect.poll(() => service.beacons.some(x => x.nonce === nonce)).toBe(true);
      const s = service.beacons.find(x => x.nonce === nonce).state;
      assert.equal(s.destroyed, true); assert.equal(s.draftVerified, false); assert.equal(s.draftImportBusy, false);
      assert.equal(s.pendingStage, null); assert.equal(s.hasSourceBytes, false); assert.equal(s.objectUrls, 0);
      record.pagehide = { nonce, state: s, receiver_observed: true };
    });
    assert.deepEqual(record.page_errors, []);
    assert.deepEqual(await browserPin(spec.channel), spec);
    record.status = "passed";
  } catch (error) {
    record.status = "failed"; record.error = error.stack || String(error);
    if (page && !page.isClosed()) { record.last_url = page.url(); record.last_state = await state().catch(() => null); record.last_error_text = await page.locator("#error").textContent().catch(() => null); }
  } finally {
    if (context) await context.close(); if (browser) await browser.close();
    record.context_closed = true; record.browser_closed = true;
    await writeJson(join(out, "browser-" + spec.channel + "-report.json"), record);
  }
  return record;
}

async function run() {
  const planPath = repoPath(option("--plan")), frozenPlan = await pin(planPath), plan = await json(planPath);
  assert.equal(plan.protocol_id, PROTOCOL); assert.equal(plan.synthetic_only, true);
  assert.deepEqual(plan.graphics_args, GRAPHICS);
  assert.equal(plan.runtime.node, process.version); assert.equal(plan.runtime.executable_sha256, sha(await readFile(process.execPath)));
  for (const p of plan.sources) await verify(p);
  await verify(plan.fixtures); const manifest = await json(repoPath(plan.fixtures.path));
  for (const p of Object.values(manifest.fixtures)) await verify(p);
  const out = await fresh(option("--output-dir"));
  let vite, service;
  const report = { protocol_id: PROTOCOL, plan: frozenPlan, synthetic_only: true, ...FLAGS,
    real_service_or_model_acceptance: false, graphics_scope: "Installed Chrome/Edge using fixed SwiftShader solely for synthetic UI checks", browsers: [] };
  try {
    const snapshots = join(out, "browser-snapshots"); await mkdir(snapshots);
    for (let i = 0; i < plan.sources.length; i++) {
      const p = plan.sources[i]; await writeFile(join(snapshots, "browser-" + String(i).padStart(3, "0") + "-" + p.path.split("/").at(-1)), await readFile(repoPath(p.path)), { flag: "wx" });
    }
    await writeJson(join(out, "browser-plan-frozen.json"), plan);
    service = await syntheticService(manifest.fixtures);
    vite = await createViteServer({ root: join(ROOT, "frontend"), configFile: join(ROOT, "frontend/vite.config.ts"),
      server: { host: "127.0.0.1", port: 0, strictPort: false, open: false }, logLevel: "error" });
    await vite.listen(); const address = vite.httpServer.address(); const base = `http://127.0.0.1:${address.port}`;
    report.service_origin = service.base; report.page_origin = base;
    for (const spec of plan.browsers) {
      const record = await browserRun(spec, base, manifest.fixtures, service, out); report.browsers.push(record);
      assert.equal(record.status, "passed", record.error);
    }
    for (const p of plan.sources) await verify(p);
    for (const p of Object.values(manifest.fixtures)) await verify(p);
    await verify(frozenPlan);
    report.input_fingerprints_unchanged = true; report.status = "passed";
  } catch (error) { report.status = "failed"; report.error = error.stack || String(error); }
  finally {
    if (service) { report.service_requests = service.requests; report.explicit_submissions = service.submissions; report.pagehide_receipts = service.beacons; await service.close(); }
    if (vite) await vite.close();
    report.cleanup = { synthetic_service_closed: !!service, vite_closed: !!vite, browser_contexts_closed: report.browsers.every(x => x.context_closed && x.browser_closed) };
    await writeJson(join(out, "browser-report.json"), report);
    console.log(JSON.stringify({ status: report.status, output: rel(out), browsers: report.browsers.map(x => ({ channel: x.channel, version: x.version, status: x.status, cases: x.cases.length, request_failures: x.request_failures.length })), error: report.error }));
  }
  if (report.status !== "passed") process.exitCode = 1;
}

if (args.includes("--prepare")) await prepare();
else if (args.includes("--freeze")) await freeze();
else if (args.includes("--run")) await run();
else throw new Error("Use --prepare, --freeze, or --run explicitly.");
