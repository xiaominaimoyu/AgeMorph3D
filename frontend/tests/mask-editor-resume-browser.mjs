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
const PROTOCOL = "agemorph3d-mask-editor-resume-browser-v1";
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
  for (const [role, value] of Object.entries({ draft, human, badStage, badCount, badHash, badPixels, badFlag, binding, otherBinding: { ...binding, stage: { ...binding.stage, stage_id: "e".repeat(32) } }, info })) {
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
  const files = new Set(["docs/mask-editor-resume-v1.json", "docs/mask-draft-import-v1.json", "docs/mask-editor-v1.json", "frontend/package.json",
    "frontend/package-lock.json", "frontend/vite.config.ts", "frontend/tsconfig.json", "frontend/tests/mask-editor-resume-browser.mjs",
    "frontend/research/session.ts", "frontend/research/session.html", "frontend/research/session.css",
    "frontend/research/mask-editor.ts", "frontend/research/mask-editor.html", "frontend/research/mask-editor.css",
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

async function browserRun(spec, base, fixtures, out, probe) {
  let browser, context, page;
  const record = { channel: spec.channel, cases: [], page_errors: [], request_failures: [], requests: [],
    downloads: [], actual_editor: true, product_modules_mocked: false, ...FLAGS };
  const input = key => repoPath(fixtures[key].path);
  const check = async (name, action) => { await action(); record.cases.push({ name, passed: true }); };
  try {
    assert.deepEqual(await browserPin(spec.channel), spec);
    browser = await chromium.launch({ channel: spec.channel, headless: true, args: GRAPHICS });
    record.version = browser.version();
    context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, deviceScaleFactor: 1 });
    await context.addInitScript(() => {
      const bitmaps = new Set(), urls = new Set();
      const bitmap = window.createImageBitmap, create = URL.createObjectURL, revoke = URL.revokeObjectURL;
      window.createImageBitmap = async (...args) => {
        const answer = await bitmap(...args), close = answer.close.bind(answer);
        bitmaps.add(answer); answer.close = () => { close(); bitmaps.delete(answer); };
        return answer;
      };
      URL.createObjectURL = blob => { const url = create.call(URL, blob); urls.add(url); return url; };
      URL.revokeObjectURL = url => { revoke.call(URL, url); urls.delete(url); };
      window.__resumeResources = () => ({ bitmaps: bitmaps.size, urls: urls.size });
    });
    page = await context.newPage(); page.setDefaultTimeout(15000);
    page.on("pageerror", error => record.page_errors.push(String(error)));
    page.on("requestfailed", request => record.request_failures.push({ url: request.url(), error: request.failure()?.errorText }));
    page.on("request", request => record.requests.push({ url: request.url(), method: request.method() }));
    await page.goto(base + "/research/mask-editor.html");
    const state = () => page.locator("#mask-editor").getAttribute("data-state");
    const ready = () => expect.poll(state).toBe("ready");
    const count = async (name, value) => expect(page.locator("#" + name + "-count")).toHaveText(String(value));
    const noRecord = async () => {
      await count("polygon", 0); await count("allowed", 0); await count("occluded", 0); await count("unknown", 1024 ** 2);
      for (const key of ["reviewer", "method", "version", "review-kind"]) await expect(page.locator("#editor-" + key)).toHaveValue("");
      await expect(page.locator("#download-draft")).toBeDisabled();
    };
    const load = async (binding = "binding") => {
      await page.locator("#editor-binding").setInputFiles(input(binding));
      await page.locator("#editor-target").setInputFiles(input("target"));
      await page.locator("#load-editor").click(); await ready();
    };
    const select = async (draft = "draft", allowed = "allowed") => {
      await page.locator("#resume-allowed").setInputFiles(input(allowed));
      await page.locator("#resume-occluded").setInputFiles(input("occluded"));
      await page.locator("#resume-draft").setInputFiles(input(draft));
    };
    const resume = async (draft = "draft") => {
      await select(draft); await page.locator("#resume-editor").click(); await ready();
      await count("polygon", 2); await count("allowed", 8800); await count("occluded", 800); await count("unknown", 1038976);
    };
    await check("empty-editor-does-not-auto-resume", async () => {
      await expect(page.locator("#resume-editor")).toBeDisabled(); await noRecord();
    });
    await load();
    await page.locator("details.resume-draft > summary").click();
    await check("file-selection-alone-does-not-apply-annotations", async () => {
      await select(); await noRecord(); await expect(page.locator("#resume-editor")).toBeEnabled();
    });
    await check("explicit-restore-is-local-and-not-prepared", async () => {
      const before = record.requests.length;
      await page.locator("#resume-editor").click(); await ready();
      await count("polygon", 2); await count("allowed", 8800); await count("occluded", 800);
      await expect(page.locator("#editor-reviewer")).toHaveValue("synthetic-browser-record");
      await expect(page.locator("#download-draft")).toBeDisabled();
      assert.equal(record.requests.length, before);
    });
    await check("human-source-is-restored-as-declaration-only", async () => {
      await resume("human"); await expect(page.locator("#editor-review-kind")).toHaveValue("human");
      await expect(page.locator("#editor-method")).toHaveValue("Synthetic rectangles only; no actual human review");
      await page.screenshot({ path: join(out, `browser-${spec.channel}-restored.png`), fullPage: true });
    });
    await check("restored-polygon-can-be-edited", async () => {
      await page.locator("#undo-polygon").click(); await count("polygon", 1); await count("allowed", 9600); await count("occluded", 0);
    });
    await check("fresh-export-after-edit-has-new-polygons-and-closed-flags", async () => {
      await page.locator("#prepare-export").click();
      await expect.poll(state).toBe("prepared");
      for (const [selector, suffix] of [["#download-allowed", "allowed.png"], ["#download-occluded", "occluded.png"], ["#download-draft", "draft.json"]]) {
        const event = page.waitForEvent("download"); await page.locator(selector).click();
        const download = await event, path = join(out, `browser-${spec.channel}-edited-${suffix}`);
        await download.saveAs(path); record.downloads.push(await pin(path));
        if (suffix === "draft.json") {
          const draft = await json(path);
          assert.equal(draft.status, "draft_unsubmitted"); assert.equal(draft.polygons.length, 1);
          assert.deepEqual(draft.pixel_counts, { allowed: 9600, occluded: 0, unknown: 1038976 });
          for (const [key, value] of Object.entries(FLAGS)) assert.equal(draft[key], value);
        }
      }
    });
    await check("changed-restore-selection-revokes-download-without-auto-replacing", async () => {
      await page.locator("#resume-draft").setInputFiles(input("badStage"));
      await expect(page.locator("#download-draft")).toBeDisabled(); await count("polygon", 1); await count("allowed", 9600);
    });
    for (const [draft, allowed] of [["badStage", "allowed"], ["badCount", "allowed"], ["badFlag", "allowed"], ["badPixels", "altered_allowed"]]) {
      await check("reject-" + draft + "-without-partial-annotations", async () => {
        await select(draft, allowed); await page.locator("#resume-editor").click(); await ready(); await noRecord();
        await expect(page.locator("#editor-error")).toBeVisible();
      });
    }
    const holdRead = async () => {
      await select();
      await page.evaluate(() => {
        const file = document.querySelector("#resume-draft").files[0], native = File.prototype.arrayBuffer;
        window.__resumeHeld = { entered: false, release: null };
        File.prototype.arrayBuffer = function () {
          const result = native.call(this);
          return this === file ? result.then(bytes => new Promise(resolve => {
            window.__resumeHeld.entered = true; window.__resumeHeld.release = () => resolve(bytes);
          })) : result;
        };
      });
      await page.locator("#resume-editor").click(); await page.waitForFunction(() => window.__resumeHeld.entered);
      await expect.poll(state).toBe("resuming");
    };
    await check("clear-old-read-then-new-success-cannot-be-overwritten", async () => {
      await holdRead(); await expect(page.locator("#polygon-kind")).toBeDisabled();
      await expect(page.locator("#editor-reviewer")).toBeDisabled();
      await page.locator("#mask-canvas").click({ position: { x: 30, y: 30 } }); await count("pending", 0);
      await expect(page.locator("#editor-error")).toBeHidden();
      await page.locator("#clear-editor").click(); await expect.poll(state).toBe("empty"); await noRecord();
      await load(); await resume("human"); await page.evaluate(() => window.__resumeHeld.release());
      await page.waitForTimeout(150); await ready();
      await expect(page.locator("#editor-reviewer")).toHaveValue("synthetic-human-provenance-only"); await count("polygon", 2);
    });
    await check("changed-file-invalidates-old-read-and-allows-new-restore", async () => {
      await holdRead();
      await page.locator("#resume-draft").setInputFiles(input("human"));
      await page.locator("#resume-editor").click(); await ready();
      await page.evaluate(() => window.__resumeHeld.release()); await page.waitForTimeout(150);
      await expect(page.locator("#editor-reviewer")).toHaveValue("synthetic-human-provenance-only"); await count("polygon", 2);
    });
    await check("new-stage-target-rejects-old-completion", async () => {
      await holdRead();
      await page.locator("#editor-binding").setInputFiles(input("otherBinding"));
      await page.locator("#load-editor").click(); await ready(); await noRecord();
      await page.evaluate(() => window.__resumeHeld.release()); await page.waitForTimeout(150); await noRecord();
      await expect(page.locator("#editor-stage")).toContainText("e".repeat(32));
    });
    await load(); await resume();
    await check("pagehide-explicitly-clears-bitmap-and-download-resources", async () => {
      const nonce = randomUUID();
      await page.evaluate(({ endpoint, nonce }) => {
        window.addEventListener("pagehide", () => {
          navigator.sendBeacon(endpoint, JSON.stringify({ nonce, ...window.__resumeResources(),
            state: document.querySelector("#mask-editor").dataset.state,
            polygonCount: document.querySelector("#polygon-count").textContent,
            reviewer: document.querySelector("#editor-reviewer").value }));
        }, { once: true });
      }, { endpoint: probe.base, nonce });
      await page.goto("about:blank");
      await expect.poll(() => probe.receipts.some(x => x.nonce === nonce)).toBe(true);
      const receipt = probe.receipts.find(x => x.nonce === nonce);
      assert.equal(receipt.state, "disposed"); assert.equal(receipt.bitmaps, 0); assert.equal(receipt.urls, 0);
      assert.equal(receipt.polygonCount, "0"); assert.equal(receipt.reviewer, ""); record.pagehide = receipt;
    });
    assert.deepEqual(record.page_errors, []);
    assert.ok(record.requests.every(r => r.method === "GET" && r.url.startsWith(base + "/") || r.method === "POST" && r.url === probe.base));
    assert.deepEqual(await browserPin(spec.channel), spec); record.status = "passed";
  } catch (error) { record.status = "failed"; record.error = error.stack || String(error); }
  finally {
    if (context) { await context.close(); record.context_closed = true; }
    if (browser) { await browser.close(); record.browser_closed = true; }
    await writeJson(join(out, `browser-${spec.channel}-report.json`), record);
  }
  return record;
}

async function run() {
  const planPath = repoPath(option("--plan")), planPin = await pin(planPath), plan = await json(planPath);
  assert.equal(plan.protocol_id, PROTOCOL); assert.equal(plan.synthetic_only, true);
  for (const source of plan.sources) await verify(source);
  await verify(plan.fixtures); const fixtures = (await json(repoPath(plan.fixtures.path))).fixtures;
  for (const fixture of Object.values(fixtures)) await verify(fixture);
  assert.equal(plan.runtime.executable_sha256, sha(await readFile(process.execPath)));
  const out = await fresh(option("--output-dir"));
  const report = { protocol_id: PROTOCOL, plan: planPin, synthetic_only: true, graphics_args: GRAPHICS,
    ...FLAGS, real_service_or_model_acceptance: false, browsers: [] };
  let vite, server;
  const probe = { receipts: [] };
  try {
    const snapshots = join(out, "snapshots"); await mkdir(snapshots);
    for (let i = 0; i < plan.sources.length; i++) {
      const p = plan.sources[i]; await writeFile(join(snapshots, `${i}-${p.path.split("/").at(-1)}`), await readFile(repoPath(p.path)), { flag: "wx" });
    }
    await writeJson(join(out, "plan-frozen.json"), plan);
    server = createServer(async (request, response) => {
      let body = ""; for await (const chunk of request) { body += chunk; if (Buffer.byteLength(body) > 4096) { response.writeHead(413); response.end(); return; } }
      probe.receipts.push(JSON.parse(body)); response.writeHead(204); response.end();
    });
    server.listen(0, "127.0.0.1"); await once(server, "listening"); probe.base = `http://127.0.0.1:${server.address().port}/pagehide`;
    vite = await createViteServer({ root: join(ROOT, "frontend"), configFile: join(ROOT, "frontend/vite.config.ts"),
      server: { host: "127.0.0.1", port: 0, strictPort: false, open: false }, logLevel: "error" });
    await vite.listen(); const base = `http://127.0.0.1:${vite.httpServer.address().port}`;
    report.page_origin = base; report.probe_endpoint = probe.base;
    for (const spec of plan.browsers) {
      const result = await browserRun(spec, base, fixtures, out, probe); report.browsers.push(result);
      assert.equal(result.status, "passed", result.error);
    }
    for (const source of plan.sources) await verify(source);
    for (const fixture of Object.values(fixtures)) await verify(fixture);
    await verify(planPin); report.inputs_unchanged = true; report.status = "passed";
  } catch (error) { report.status = "failed"; report.error = error.stack || String(error); }
  finally {
    if (vite) await vite.close();
    if (server) { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
    report.pagehide_receipts = probe.receipts;
    report.cleanup = { vite_closed: !!vite, probe_closed: !!server,
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
