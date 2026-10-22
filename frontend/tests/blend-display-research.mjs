import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, readFile, realpath, writeFile } from "node:fs/promises";
import { createServer as createHttpServer } from "node:http";
import { dirname, isAbsolute, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";
import { createServer as createViteServer } from "vite";

// Isolated offline display transport. No production API, age controls, inference,
// quality threshold, identity score or future-face claim is supplied here.
const repository = await realpath(fileURLToPath(new URL("../../", import.meta.url)));
const frontendRoot = fileURLToPath(new URL("../", import.meta.url));
const inputPath = await existing(process.env.AGEMORPH_BLEND_REPORT);
const planPath = await existing(process.env.AGEMORPH_BLEND_PLAN);
assert.match(process.env.AGEMORPH_BLEND_REPORT_SHA256 ?? "", /^[a-f0-9]{64}$/,
  "Set AGEMORPH_BLEND_REPORT_SHA256 to the frozen producer report SHA-256.");
const inputBytes = await readFile(inputPath);
assert.ok(inputBytes.length <= 8 * 1024 ** 2, "Producer JSON exceeds the research bound.");
assert.equal(hash(inputBytes), process.env.AGEMORPH_BLEND_REPORT_SHA256, "Producer report changed.");
const producer = JSON.parse(inputBytes.toString("utf8"));
const plan = JSON.parse(await readFile(planPath, "utf8"));
assert.equal(plan.protocol_id, "agemorph3d-blend-display-browser-v1");
assert.ok(Array.isArray(plan.inputs) && plan.inputs.length > 0, "Freeze browser input/source pins.");
const planned = new Map();
for (const pin of plan.inputs) {
  await verifyPin(pin);
  assert.equal(planned.has(pin.path), false, "Frozen input paths must be unique.");
  planned.set(pin.path, pin);
}
for (const path of [repoRelative(inputPath), "frontend/tests/blend-display-research.mjs",
  "frontend/src/viewer.ts", "frontend/src/services.ts", "frontend/src/contracts.ts",
  "frontend/src/age.ts", "frontend/src/demo-head.ts", "frontend/package.json", "frontend/package-lock.json"])
  assert.ok(planned.has(path), `Browser plan must bind ${path}.`);
assert.equal(producer.protocol_id, "agemorph3d-blend-display-v1");
assert.equal(producer.research_only, true);
assert.equal(producer.service_ready, false);
assert.equal(producer.g3_complete, false);
assert.ok(Array.isArray(producer.records) && producer.records.length === 98,
  "Retain all 98 cases from the frozen ten-source display schedule.");
assert.ok(Array.isArray(producer.pair_probes) && producer.pair_probes.length === 35);
assert.equal(producer.pair_probes.filter(pair => pair.kind === "interval_midpoint").length, 27);
assert.equal(producer.pair_probes.filter(pair => pair.kind === "source_neighborhood").length, 8);
assert.ok(Array.isArray(producer.source_anchors) && producer.source_anchors.length === 10);
const anchors = new Map(producer.source_anchors.map(anchor => [anchor.source_id, anchor]));
assert.equal(anchors.size, 10);
assert.equal(producer.source_anchors.filter(anchor => anchor.research_label === null).length, 2);
const records = new Map();
for (const record of producer.records) {
  assert.match(record.sample_id, /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,140}$/);
  assert.equal(records.has(record.sample_id), false, "Display case IDs must be unique.");
  assert.ok(["source_exact", "blend_display", "sam_anchor"].includes(record.kind));
  assert.ok(Number.isFinite(record.target_age) && record.target_age >= 20 && record.target_age <= 70);
  assert.ok(record.source_id && record.expected_geometry);
  assert.equal(record.status, "ok");
  assert.deepEqual(record.source_age, { value: null, method: "unknown", calibration_id: null });
  const sourceAnchor = anchors.get(record.source_id); assert.ok(sourceAnchor);
  if (record.kind === "source_exact") {
    assert.ok(sourceAnchor.research_label !== null && record.target_age === sourceAnchor.research_label);
    assert.equal(record.original_source_bytes_exact, true);
    for (const name of ["glb", "atlas"])
      assert.equal(record.artifacts[name].sha256, sourceAnchor.original_artifacts[name].sha256,
        "Exact source case must retain the original encoded GLB/PNG bytes.");
  }
  assert.equal(record.material_alpha_mode, record.kind === "source_exact" ? "MASK" : "BLEND");
  for (const pin of Object.values(record.artifacts)) await verifyPin(pin);
  const bytes = await readFile(await existing(record.artifacts.glb.path));
  const parsed = standaloneGlb(bytes);
  validateDocument(parsed.document, record.material_alpha_mode);
  assert.match(parsed.document.extras.topology_id, /^tddfa-bfm-canon-v1-[a-f0-9]{64}$/);
  if (record.topology_id !== undefined) assert.equal(record.topology_id, parsed.document.extras.topology_id);
  assert.deepEqual(embeddedPng(parsed), await readFile(await existing(record.artifacts.atlas.path)),
    "Input GLB must embed the exact frozen atlas PNG.");
  records.set(record.sample_id, { ...record, topology_id: parsed.document.extras.topology_id });
}
const sourceIds = new Set(producer.records.map(record => record.source_id));
assert.equal(sourceIds.size, 10, "Keep all ten development sources.");
assert.equal(producer.records.filter(record => record.kind === "source_exact").length, 8);
for (const sourceId of sourceIds) for (const age of [20, 70])
  assert.ok(producer.records.some(record => record.source_id === sourceId && record.target_age === age),
    "Every source requires both display boundaries.");
const pairIds = new Set();
const pairs = producer.pair_probes.map((pair, index) => {
  const id = pair.sample_id ?? pair.pair_id ?? `pair-${String(index).padStart(3, "0")}`;
  assert.equal(pairIds.has(id), false); pairIds.add(id);
  const before = records.get(pair.before_id), after = records.get(pair.after_id);
  assert.ok(before && after && before.source_id === pair.source_id && after.source_id === pair.source_id);
  assert.ok(before.target_age < after.target_age);
  assert.deepEqual(before.expected_geometry, after.expected_geometry, "A display pair must keep geometry/UV.");
  if (pair.source_exact_id) {
    const exact = records.get(pair.source_exact_id);
    assert.ok(exact?.kind === "source_exact" && exact.source_id === pair.source_id);
    assert.ok(before.target_age < exact.target_age && exact.target_age < after.target_age);
    assert.deepEqual(exact.expected_geometry, before.expected_geometry);
  }
  return { ...pair, pair_id: id };
});
// Keep paired frames adjacent so large raw canvas buffers can be released promptly.
const orderedIds = [...new Set([...pairs.flatMap(pair =>
  [pair.before_id, ...(pair.source_exact_id ? [pair.source_exact_id] : []), pair.after_id]), ...records.keys()])];
const baselinePairs = [
  [...pairs].filter(pair => pair.kind === "interval_midpoint")
    .sort((a, b) => (b.support_xor_texels ?? 0) - (a.support_xor_texels ?? 0) || a.pair_id.localeCompare(b.pair_id))[0],
  pairs.find(pair => pair.kind === "source_neighborhood"),
].filter(Boolean).filter(pair => records.get(pair.before_id).artifacts.mask_glb && records.get(pair.after_id).artifacts.mask_glb);
assert.equal(baselinePairs.length, 2, "Supply MASK counterparts for an interval and a source-neighborhood pair.");
const representativeIds = new Set([
  producer.records.find(record => record.kind === "source_exact")?.sample_id,
  baselinePairs[0].before_id, baselinePairs[0].after_id,
  baselinePairs[1].before_id,
].filter(Boolean));
const output = contained(process.env.AGEMORPH_BLEND_OUTPUT);
assert.ok(repoRelative(output).startsWith("output/research/"), "Use a new ignored research output directory.");
await mkdir(dirname(output), { recursive: true });
assert.ok(isContained(await realpath(dirname(output))), "Output parent must resolve within the workspace.");
await mkdir(output); // Never overwrite evidence.
const report = {
  schema_version: 1, protocol_id: "agemorph3d-blend-display-browser-v1",
  evidenceKind: "offline-blend-display-browser-transport-and-frame-differences",
  research_only: true, service_ready: false, g3_complete: false,
  age_quality_accepted: false, identity_quality_accepted: false,
  rendered_continuity_accepted: false, production_capabilities_changed: false,
  real_model_inference: false, route_mocks: false,
  renderer: "Chromium software WebGL (SwiftShader)",
  input: await filePin(inputPath), study_plan: await filePin(planPath),
  frozen_source_pins: plan.inputs,
  requested_cases: orderedIds.length, requested_browsers: ["chrome", "msedge"],
  requested_pair_probes: pairs.length, baseline_pair_ids: baselinePairs.map(pair => pair.pair_id),
  started_at_utc: new Date().toISOString(), results: [], status: "running",
  interpretation: "Frame differences and transport metrics are observations, not visual-quality thresholds or proof of real fractional-age generation.",
};
const buffers = new Map();
const baselineIds = new Set(baselinePairs.flatMap(pair => [pair.before_id, pair.after_id]));
for (const id of orderedIds) {
  const record = records.get(id);
  buffers.set(`/api/assets/blend/${id}.glb`, await readFile(await existing(record.artifacts.glb.path)));
  if (record.artifacts.mask_glb && baselineIds.has(id)) {
    const bytes = await readFile(await existing(record.artifacts.mask_glb.path));
    validateDocument(standaloneGlb(bytes).document, "MASK");
    buffers.set(`/api/assets/blend/${id}-mask.glb`, bytes);
  }
  if (record.kind === "source_exact") {
    assert.ok(record.artifacts.blend_control_glb, "Original source requires a same-PNG BLEND material control.");
    const bytes = await readFile(await existing(record.artifacts.blend_control_glb.path));
    const control = standaloneGlb(bytes), original = standaloneGlb(buffers.get(`/api/assets/blend/${id}.glb`));
    validateDocument(control.document, "BLEND");
    assert.deepEqual(control.binary, original.binary, "Same-image material control must preserve every geometry/PNG byte.");
    buffers.set(`/api/assets/blend/${id}-source-blend.glb`, bytes);
  }
}
let frontend, assets, vite, browser, failure, interrupted = false;
const requests = [];
const assetServer = createHttpServer((request, response) => {
  const headers = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
  const origin = request.headers.origin;
  if (origin && origin !== frontend) { response.writeHead(403, headers).end(); return; }
  if (origin) headers["Access-Control-Allow-Origin"] = frontend;
  if (!["GET", "HEAD"].includes(request.method)) { response.writeHead(405, headers).end(); return; }
  const pathname = new URL(request.url ?? "/", assets).pathname;
  requests.push({ method: request.method, pathname });
  const bytes = buffers.get(pathname);
  if (!bytes) { response.writeHead(404, headers).end(); return; }
  response.writeHead(200, { ...headers, "Content-Type": "model/gltf-binary", "Content-Length": bytes.length });
  response.end(request.method === "HEAD" ? undefined : bytes);
});
const interrupt = () => { interrupted = true; browser?.close().catch(() => {}); };
process.once("SIGINT", interrupt); process.once("SIGTERM", interrupt);
try {
  await new Promise((resolveListen, reject) => {
    assetServer.once("error", reject); assetServer.listen(0, "127.0.0.1", resolveListen);
  });
  assets = `http://127.0.0.1:${assetServer.address().port}`;
  vite = await createViteServer({ root: frontendRoot, configFile: false,
    server: { host: "127.0.0.1", port: 0, strictPort: true, open: false },
    plugins: [{ name: "isolated-blend-display-research",
      resolveId(id) { if (id === "/__blend_modules.js") return "\0blend-display-modules"; },
      load(id) { if (id === "\0blend-display-modules") return `
        export { FaceViewer } from '/src/viewer.ts';
        export { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
        export * as THREE from 'three';`; },
      configureServer(server) {
        server.middlewares.use((request, response, next) => {
          if (request.url?.split("?")[0] !== "/__blend_display") return next();
          response.setHeader("Content-Type", "text/html; charset=utf-8");
          response.end(`<!doctype html><html lang="zh-CN"><meta charset="utf-8">
            <title>共同UV连续显示研究</title><style>body{margin:0;background:#111827;
            color:#e4edf5;font:16px system-ui}header{padding:12px 20px}#viewer{height:640px}</style>
            <header><h1>BLEND 显示研究 · 非真实小数年龄生成 / 非 G3</h1><p id="state">离线资产传输</p></header>
            <div id="viewer"></div></html>`);
        });
      },
    }],
  });
  await vite.listen(); frontend = `http://127.0.0.1:${vite.httpServer.address().port}`;
  report.owned_servers = { frontend, assets };
  for (const channel of report.requested_browsers) {
    assert.equal(interrupted, false, "Browser research was interrupted.");
    const errors = [], externalRequests = [];
    browser = await chromium.launch({ channel, headless: true, timeout: 30_000,
      args: ["--enable-unsafe-swiftshader", "--use-angle=swiftshader"] });
    const page = await browser.newPage({ viewport: { width: 1000, height: 770 }, locale: "zh-CN" });
    page.setDefaultTimeout(30_000);
    page.on("pageerror", error => errors.push(error.message));
    page.on("request", request => {
      const url = new URL(request.url());
      if (["http:", "https:"].includes(url.protocol) && ![frontend, assets].includes(url.origin)) externalRequests.push(request.url());
    });
    await page.goto(`${frontend}/__blend_display`, { waitUntil: "networkidle", timeout: 30_000 });
    await page.evaluate(installBrowserTools);
    const result = { channel, version: browser.version(), cases: [], rendered_pairs: [], mask_baselines: [], errors, external_requests: externalRequests, status: "running" };
    report.results.push(result);
    const pairContext = pairs.map(pair => ({ pair_id: pair.pair_id, before_id: pair.before_id,
      after_id: pair.after_id, ...(pair.source_exact_id ? { source_exact_id: pair.source_exact_id } : {}) }));
    for (const id of orderedIds) {
      assert.equal(interrupted, false, "Browser research was interrupted.");
      const record = records.get(id);
      const observed = await bounded(page.evaluate(async ({ url, record, pairs, save, controlUrl }) =>
        window.blendTools.runCase(url, record, pairs, save, controlUrl),
      { url: `${assets}/api/assets/blend/${id}.glb`, record, pairs: pairContext,
        save: representativeIds.has(id),
        ...(record.kind === "source_exact" ? { controlUrl: `${assets}/api/assets/blend/${id}-source-blend.glb` } : {}),
      }), 45_000, `Case ${id}`);
      if (observed.export_base64) {
        const exportPath = join(output, `${id}-${channel}.glb`);
        await writeFile(exportPath, Buffer.from(observed.export_base64, "base64"), { flag: "wx" });
        observed.exported_artifact = await filePin(exportPath); delete observed.export_base64;
        const shotPath = join(output, `${id}-${channel}.png`);
        await page.screenshot({ path: shotPath, timeout: 20_000 });
        observed.screenshot = await filePin(shotPath);
      }
      result.rendered_pairs.push(...observed.completed_pairs); delete observed.completed_pairs;
      result.cases.push(observed);
      if (result.cases.length % 10 === 0 || result.cases.length === orderedIds.length)
        console.log(JSON.stringify({ channel, completed_cases: result.cases.length,
          requested_cases: orderedIds.length, completed_pairs: result.rendered_pairs.length }));
    }
    assert.equal(result.rendered_pairs.length, pairs.length, "Retain every requested rendered pair.");
    for (const pair of baselinePairs) {
      const before = records.get(pair.before_id), after = records.get(pair.after_id);
      const observation = await bounded(page.evaluate(async ({ beforeUrl, afterUrl, before, after, pairId, exactUrl, exact }) =>
        window.blendTools.maskBaseline(beforeUrl, afterUrl, before, after, pairId, exactUrl, exact), {
        beforeUrl: `${assets}/api/assets/blend/${before.sample_id}-mask.glb`,
        afterUrl: `${assets}/api/assets/blend/${after.sample_id}-mask.glb`,
        before, after, pairId: pair.pair_id,
        ...(pair.source_exact_id ? {
          exactUrl: `${assets}/api/assets/blend/${pair.source_exact_id}.glb`,
          exact: records.get(pair.source_exact_id),
        } : {}),
      }), 45_000, `MASK baseline ${pair.pair_id}`);
      result.mask_baselines.push(observation);
    }
    await page.evaluate(() => window.blendTools.close());
    assert.deepEqual(errors, []); assert.deepEqual(externalRequests, []);
    result.status = "passed";
    await bounded(browser.close(), 15_000, "Browser close"); browser = undefined;
  }
  // Repeat integrity checks after the browser run so changed evidence is retained
  // as a failed run rather than silently associated with the initial freeze.
  for (const pin of plan.inputs) await verifyPin(pin);
  for (const record of producer.records) for (const pin of Object.values(record.artifacts)) await verifyPin(pin);
  report.status = "passed";
} catch (error) {
  failure = error; report.status = "failed";
  report.error = error instanceof Error ? error.stack : String(error);
} finally {
  const cleanup = await Promise.allSettled([
    browser ? bounded(browser.close(), 15_000, "Final browser close") : undefined,
    vite ? bounded(vite.close(), 10_000, "Vite close") : undefined,
    assetServer.listening ? bounded(new Promise((resolveClose, reject) => {
      assetServer.close(error => error ? reject(error) : resolveClose()); assetServer.closeAllConnections();
    }), 10_000, "Asset server close") : undefined,
  ]);
  report.owned_servers_closed = cleanup.every(value => value.status === "fulfilled") && !assetServer.listening && !vite?.httpServer?.listening;
  report.cleanup = cleanup.map((value, index) => ({ resource: ["browser", "vite", "asset_server"][index], status: value.status,
    ...(value.status === "rejected" ? { error: String(value.reason) } : {}) }));
  report.interrupted = interrupted; report.asset_requests = requests;
  report.finished_at_utc = new Date().toISOString();
  if (!report.owned_servers_closed) { report.status = "failed"; failure ??= new Error("Owned browser/server cleanup failed."); }
  await writeFile(join(output, "blend-display-browser.json"), `${JSON.stringify(report, null, 2)}\n`, { flag: "wx" });
  process.removeListener("SIGINT", interrupt); process.removeListener("SIGTERM", interrupt);
}
if (failure) throw failure;
console.log(JSON.stringify({ status: report.status, cases_per_browser: orderedIds.length,
  browsers: report.results.length, pairs_per_browser: pairs.length,
  owned_servers_closed: report.owned_servers_closed, g3_complete: false, output }));

async function installBrowserTools() {
  const { FaceViewer, GLTFLoader, THREE } = await import("/__blend_modules.js");
  const viewer = new FaceViewer(document.getElementById("viewer"));
  viewer.setAutoRotate(false); viewer.setBackground(false); viewer.setCompare(false);
  const frameCache = new Map();
  const completedPairIds = new Set();
  const hex = async bytes => [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map(value => value.toString(16).padStart(2, "0")).join("");
  const typedHash = value => hex(new Uint8Array(value.buffer, value.byteOffset, value.byteLength));
  const linear = value => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  const meshes = scene => { const found = []; scene.traverse(node => { if (node.isMesh) found.push(node); }); return found; };
  const dispose = scene => {
    const geometries = new Set(), materials = new Set(), textures = new Set();
    scene.traverse(node => {
      if (!node.isMesh) return; geometries.add(node.geometry);
      for (const material of Array.isArray(node.material) ? node.material : [node.material]) materials.add(material);
    });
    for (const material of materials) { for (const value of Object.values(material)) if (value?.isTexture) textures.add(value); material.dispose(); }
    for (const geometry of geometries) geometry.dispose();
    for (const texture of textures) { texture.dispose(); if (typeof ImageBitmap !== "undefined" && texture.image instanceof ImageBitmap) texture.image.close(); }
  };
  const imagePixels = texture => {
    const image = texture.image;
    if (!image || image.width * image.height > 16_000_000) throw new Error("Invalid atlas image size.");
    const canvas = document.createElement("canvas"); canvas.width = image.width; canvas.height = image.height;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    context.drawImage(image, 0, 0);
    return { width: canvas.width, height: canvas.height, pixels: context.getImageData(0, 0, canvas.width, canvas.height).data };
  };
  const materialInfo = async mesh => {
    const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    if (materials.length !== 1 || !materials[0].map) throw new Error("One embedded base-color atlas required.");
    const material = materials[0], texture = material.map;
    if (texture.colorSpace !== "srgb" || texture.flipY !== false) throw new Error("Atlas color space/orientation changed.");
    const decoded = imagePixels(texture), alpha = new Uint8Array(decoded.width * decoded.height);
    let unknown = 0, partial = 0, hiddenRgb = 0;
    for (let index = 0; index < alpha.length; index++) {
      alpha[index] = decoded.pixels[index * 4 + 3];
      unknown += alpha[index] === 0; partial += alpha[index] > 0 && alpha[index] < 255;
      if (alpha[index] === 0 && decoded.pixels.subarray(index * 4, index * 4 + 3).some(value => value !== 0)) hiddenRgb++;
    }
    return { material: { transparent: material.transparent, alphaTest: material.alphaTest, depthWrite: material.depthWrite,
      opacity: material.opacity, side: material.side }, color_space: texture.colorSpace, flip_y: texture.flipY,
      width: decoded.width, height: decoded.height, rgba_sha256: await hex(decoded.pixels), alpha_sha256: await hex(alpha),
      unknown_texels: unknown, partial_alpha_texels: partial, unknown_nonzero_rgb_texels: hiddenRgb, pixels: decoded.pixels };
  };
  const geometryInfo = async mesh => {
    const result = {};
    for (const name of ["position", "normal", "uv"]) {
      const attribute = mesh.geometry.getAttribute(name); if (!attribute) throw new Error(`Missing ${name}.`);
      result[name] = { count: attribute.count, item_size: attribute.itemSize, sha256: await typedHash(attribute.array) };
    }
    if (!mesh.geometry.index) throw new Error("Indexed source mesh required.");
    result.index = { count: mesh.geometry.index.count, sha256: await typedHash(mesh.geometry.index.array) };
    return result;
  };
  const comparePixels = (before, after) => {
    if (before.length !== after.length) throw new Error("Texture raster changed.");
    let alphaChanged = 0, rgbChanged = 0, maximumRgb = 0, blackMax = 0, whiteMax = 0, blackSq = 0, whiteSq = 0;
    for (let index = 0; index < before.length; index += 4) {
      const a = before[index + 3] / 255, b = after[index + 3] / 255;
      alphaChanged += before[index + 3] !== after[index + 3];
      for (let channel = 0; channel < 3; channel++) {
        const byteDelta = Math.abs(before[index + channel] - after[index + channel]);
        rgbChanged += byteDelta !== 0; maximumRgb = Math.max(maximumRgb, byteDelta);
        const delta = linear(after[index + channel] / 255) * b - linear(before[index + channel] / 255) * a;
        const whiteDelta = delta - (b - a);
        blackMax = Math.max(blackMax, Math.abs(delta)); whiteMax = Math.max(whiteMax, Math.abs(whiteDelta));
        blackSq += delta * delta; whiteSq += whiteDelta * whiteDelta;
      }
    }
    const channels = before.length / 4 * 3;
    return { alpha_changed_texels: alphaChanged, rgb_changed_channels: rgbChanged, max_rgb_byte_error: maximumRgb,
      black_linear_composite_max_channel_error: blackMax, white_linear_composite_max_channel_error: whiteMax,
      black_linear_composite_rms_channel_error: Math.sqrt(blackSq / channels), white_linear_composite_rms_channel_error: Math.sqrt(whiteSq / channels) };
  };
  const assertMaterial = (info, mode) => {
    const expected = mode === "BLEND" ? [true, 0, false] : [false, 0.5, true];
    const actual = [info.material.transparent, info.material.alphaTest, info.material.depthWrite];
    if (JSON.stringify(actual) !== JSON.stringify(expected)) throw new Error(`Incorrect ${mode} material flags: ${actual}.`);
    if (info.unknown_nonzero_rgb_texels !== 0) throw new Error("Unknown atlas pixels acquired color.");
  };
  const renderFrames = async () => {
    viewer.setView("front");
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const result = {}, gl = viewer.renderer.getContext(), size = viewer.renderer.getDrawingBufferSize(new THREE.Vector2());
    for (const background of ["black", "white"]) {
      viewer.scene.background = new THREE.Color(background); viewer.renderer.render(viewer.scene, viewer.camera);
      const pixels = new Uint8Array(size.x * size.y * 4);
      gl.readPixels(0, 0, size.x, size.y, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
      if (gl.getError() !== gl.NO_ERROR) throw new Error("Cannot read the rendered WebGL frame.");
      result[background] = { width: size.x, height: size.y, pixels, sha256: await hex(pixels) };
    }
    viewer.scene.background = new THREE.Color("#0a0e1a"); viewer.renderer.render(viewer.scene, viewer.camera);
    return result;
  };
  const frameDifference = (before, after) => {
    const result = {};
    for (const background of ["black", "white"]) {
      const a = before[background], b = after[background];
      if (a.width !== b.width || a.height !== b.height) throw new Error("Rendered frame size changed.");
      let changed = 0, squared = 0, maximum = 0, absolute = 0;
      for (let index = 0; index < a.pixels.length; index += 4) {
        let differs = false;
        for (let channel = 0; channel < 3; channel++) {
          const delta = Math.abs(b.pixels[index + channel] - a.pixels[index + channel]);
          differs ||= delta !== 0; squared += (delta / 255) ** 2; absolute += delta / 255; maximum = Math.max(maximum, delta / 255);
        }
        changed += differs;
      }
      const channels = a.width * a.height * 3;
      result[background] = { width: a.width, height: a.height, before_sha256: a.sha256, after_sha256: b.sha256,
        changed_pixels: changed, rms_channel_difference: Math.sqrt(squared / channels), mean_abs_channel_difference: absolute / channels,
        max_channel_difference: maximum };
    }
    return result;
  };
  const load = async url => {
    const response = await fetch(url, { cache: "no-store", signal: AbortSignal.timeout(20_000) });
    if (!response.ok) throw new Error(`Asset HTTP ${response.status}.`);
    const bytes = await response.arrayBuffer();
    return { bytes, gltf: await new GLTFLoader().parseAsync(bytes, "") };
  };
  const options = record => ({ asset_mode: "static", topology_id: record.topology_id ?? "offline-blend-display",
    source_age: { value: null, method: "unknown", calibration_id: null }, capabilities: { age_morph: false, age_texture: false } });
  const compareGeometry = (actual, expected) => {
    if (JSON.stringify(actual) !== JSON.stringify(expected)) throw new Error("Export changed source geometry or common UV arrays.");
  };
  window.blendTools = {
    async runCase(url, record, pairs, save, controlUrl) {
      const original = await load(url); let reimport;
      try {
        const sourceMeshes = meshes(original.gltf.scene);
        if (sourceMeshes.length !== 1) throw new Error("Display research requires one source mesh.");
        const beforeGeometry = await geometryInfo(sourceMeshes[0]);
        for (const [attribute, field] of [["position", "source_positions_sha256"], ["normal", "source_normals_sha256"], ["index", "source_indices_sha256"], ["uv", "gltf_uv_sha256"]])
          if (beforeGeometry[attribute].sha256 !== record.expected_geometry[field]) throw new Error(`Frozen ${attribute} differs from source geometry.`);
        const before = await materialInfo(sourceMeshes[0]); assertMaterial(before, record.material_alpha_mode);
        if (record.alpha_sha256 && before.alpha_sha256 !== record.alpha_sha256) throw new Error("Decoded input alpha differs from the frozen PNG alpha.");
        if (record.kind === "source_exact" && record.rgba_sha256 && before.rgba_sha256 !== record.rgba_sha256) throw new Error("Original source RGBA differs from frozen source.");
        await viewer.loadModel(url, options(record)); viewer.setAutoRotate(false); viewer.setBackground(false); viewer.setView("front");
        document.getElementById("state").textContent = `${record.source_id} · ${record.target_age} · ${record.kind} · 研究显示`;
        const pairRecords = pair => [pair.before_id, ...(pair.source_exact_id ? [pair.source_exact_id] : []), pair.after_id];
        const related = pairs.filter(pair => pairRecords(pair).includes(record.sample_id));
        const completedPairs = [];
        let currentFrames;
        if (related.length) {
          currentFrames = await renderFrames();
          frameCache.set(record.sample_id, currentFrames);
          for (const pair of related) {
            if (completedPairIds.has(pair.pair_id) || !pairRecords(pair).every(id => frameCache.has(id))) continue;
            completedPairs.push({ pair_id: pair.pair_id, before_id: pair.before_id, after_id: pair.after_id,
              rendered_difference: frameDifference(frameCache.get(pair.before_id), frameCache.get(pair.after_id)),
              ...(pair.source_exact_id ? { source_exact_id: pair.source_exact_id,
                before_to_source_exact: frameDifference(frameCache.get(pair.before_id), frameCache.get(pair.source_exact_id)),
                source_exact_to_after: frameDifference(frameCache.get(pair.source_exact_id), frameCache.get(pair.after_id)),
              } : {}),
            });
            completedPairIds.add(pair.pair_id);
          }
          for (const id of frameCache.keys())
            if (!pairs.some(pair => !completedPairIds.has(pair.pair_id) && pairRecords(pair).includes(id))) frameCache.delete(id);
        }
        let materialControl;
        if (controlUrl) {
          currentFrames ??= await renderFrames();
          await viewer.loadModel(controlUrl, options(record));
          const controlMaterials = viewer.bindings.flatMap(binding =>
            Array.isArray(binding.material) ? binding.material : [binding.material]);
          if (controlMaterials.some(material => !material.transparent || material.alphaTest !== 0 || material.depthWrite !== false))
            throw new Error("Same-image control did not load BLEND material flags.");
          const controlFrames = await renderFrames();
          materialControl = { kind: "same_source_geometry_and_png_material_only",
            mask_to_blend_rendered_difference: frameDifference(currentFrames, controlFrames) };
          // The exact-source export must retain the original MASK material.
          await viewer.loadModel(url, options(record)); viewer.setView("front");
        }
        const exportBytes = await (await viewer.exportGLB()).arrayBuffer();
        reimport = await new GLTFLoader().parseAsync(exportBytes, "");
        const exportedMeshes = meshes(reimport.scene);
        if (exportedMeshes.length !== 1) throw new Error("Export changed mesh count.");
        const afterGeometry = await geometryInfo(exportedMeshes[0]); compareGeometry(afterGeometry, beforeGeometry);
        const after = await materialInfo(exportedMeshes[0]); assertMaterial(after, record.material_alpha_mode);
        const drift = comparePixels(before.pixels, after.pixels);
        if (drift.alpha_changed_texels !== 0) throw new Error("Export changed atlas alpha bytes.");
        if (record.kind === "source_exact" && before.rgba_sha256 !== after.rgba_sha256) throw new Error("Export changed original binary-alpha source RGBA.");
        delete before.pixels; delete after.pixels;
        let exportBase64;
        if (save) {
          const array = new Uint8Array(exportBytes); let binary = "";
          for (let index = 0; index < array.length; index += 32768) binary += String.fromCharCode(...array.subarray(index, index + 32768));
          exportBase64 = btoa(binary);
        }
        return { sample_id: record.sample_id, source_id: record.source_id, target_age: record.target_age, kind: record.kind,
          geometry: beforeGeometry, original: before, reimported: after, quantized_export_drift: drift,
          export_bytes: exportBytes.byteLength, export_sha256: await hex(exportBytes),
          ...(materialControl ? { material_only_control: materialControl } : {}),
          ...(exportBase64 ? { export_base64: exportBase64 } : {}), completed_pairs: completedPairs, status: "passed" };
      } finally { dispose(original.gltf.scene); if (reimport) dispose(reimport.scene); }
    },
    async maskBaseline(beforeUrl, afterUrl, before, after, pairId, exactUrl, exact) {
      const frames = [];
      const entries = [[beforeUrl, before], ...(exactUrl ? [[exactUrl, exact]] : []), [afterUrl, after]];
      for (const [url, record] of entries) {
        await viewer.loadModel(url, options(record)); viewer.setAutoRotate(false); viewer.setBackground(false);
        frames.push(await renderFrames());
      }
      return { pair_id: pairId, before_id: before.sample_id, after_id: after.sample_id,
        material_alpha_mode: "MASK", rendered_difference: frameDifference(frames[0], frames.at(-1)),
        ...(exactUrl ? { before_to_source_exact: frameDifference(frames[0], frames[1]),
          source_exact_to_after: frameDifference(frames[1], frames[2]) } : {}),
      };
    },
    close() { frameCache.clear(); viewer.dispose(); },
  };
}

function hash(data) { return createHash("sha256").update(data).digest("hex"); }
function repoRelative(path) { return relative(repository, path).replaceAll("\\", "/"); }
function isContained(path) { const name = relative(repository, path); return name && !name.startsWith("..") && !isAbsolute(name); }
function contained(value) { assert.ok(value, "Supply an explicit workspace path."); const path = resolve(repository, value); assert.ok(isContained(path), "Path must stay within the workspace."); return path; }
async function existing(value) { const path = await realpath(contained(value)); assert.ok(isContained(path), "Evidence symlink resolves outside the workspace."); return path; }
async function filePin(path) { const bytes = await readFile(path); return { path: repoRelative(path), sha256: hash(bytes), bytes: bytes.length }; }
async function verifyPin(pin) {
  assert.ok(pin && typeof pin === "object" && Object.keys(pin).sort().join() === "bytes,path,sha256", "Invalid evidence pin.");
  assert.match(pin.sha256, /^[a-f0-9]{64}$/); assert.ok(Number.isInteger(pin.bytes) && pin.bytes > 0);
  const path = await existing(pin.path); assert.equal(repoRelative(path), pin.path, "Pins must use canonical relative paths.");
  const actual = await filePin(path); assert.deepEqual(actual, pin, `Frozen evidence changed: ${pin.path}`); return actual;
}
function standaloneGlb(bytes) {
  assert.equal(bytes.toString("ascii", 0, 4), "glTF"); assert.equal(bytes.readUInt32LE(4), 2); assert.equal(bytes.readUInt32LE(8), bytes.length);
  const jsonLength = bytes.readUInt32LE(12); assert.equal(bytes.toString("ascii", 16, 20), "JSON");
  const offset = 20 + jsonLength; assert.equal(bytes.toString("ascii", offset + 4, offset + 8), "BIN\0");
  const binary = bytes.subarray(offset + 8); assert.equal(bytes.readUInt32LE(offset), binary.length);
  return { document: JSON.parse(bytes.toString("utf8", 20, offset)), binary };
}
function embeddedPng({ document, binary }) {
  assert.equal(document.images.length, 1); const view = document.bufferViews[document.images[0].bufferView];
  return binary.subarray(view.byteOffset ?? 0, (view.byteOffset ?? 0) + view.byteLength);
}
function validateDocument(document, mode) {
  assert.deepEqual(document.extras.source_age, { value: null, method: "unknown", calibration_id: null });
  assert.equal(document.extras.asset_mode, "static");
  assert.equal(document.materials.length, 1); assert.equal(document.materials[0].alphaMode, mode);
  assert.equal(document.materials[0].alphaCutoff, mode === "MASK" ? 0.5 : undefined);
  assert.ok(document.buffers.every(row => row.uri === undefined) && document.images.every(row => row.uri === undefined));
  assert.equal(document.animations, undefined);
  for (const mesh of document.meshes) for (const primitive of mesh.primitives) assert.equal(primitive.targets, undefined);
}
async function bounded(promise, milliseconds, operation) {
  let timer;
  try { return await Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`${operation} exceeded ${milliseconds} ms.`)), milliseconds); })]); }
  finally { clearTimeout(timer); }
}
