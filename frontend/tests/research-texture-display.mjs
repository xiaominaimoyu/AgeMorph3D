import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, readFile, realpath, writeFile } from "node:fs/promises";
import { createServer as createHttpServer } from "node:http";
import { dirname, isAbsolute, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";
import { createServer as createViteServer } from "vite";

// Opt-in research page only: actual range input -> pure sampler -> actual viewer.
// It never calls the production aging API or modifies global/result capabilities.
const root = await realpath(fileURLToPath(new URL("../../", import.meta.url)));
const inputPath = await existing(process.env.AGEMORPH_RESEARCH_DISPLAY_REPORT);
const planPath = await existing(process.env.AGEMORPH_RESEARCH_DISPLAY_PLAN);
assert.match(process.env.AGEMORPH_RESEARCH_DISPLAY_REPORT_SHA256 ?? "", /^[a-f0-9]{64}$/);
const inputBytes = await readFile(inputPath);
assert.equal(hash(inputBytes), process.env.AGEMORPH_RESEARCH_DISPLAY_REPORT_SHA256);
assert.ok(inputBytes.length < 8 * 1024 ** 2);
const producer = JSON.parse(inputBytes.toString("utf8"));
const plan = JSON.parse(await readFile(planPath, "utf8"));
const protocolId = "agemorph3d-interactive-texture-browser-v1";
assert.equal(plan.protocol_id, protocolId);
assert.ok(Array.isArray(plan.inputs));
const planned = new Map();
for (const pin of plan.inputs) {
  await verifyPin(pin); assert.equal(planned.has(pin.path), false); planned.set(pin.path, pin);
}
const requiredSources = [
  "frontend/tests/research-texture-display.mjs", "frontend/src/research-texture.ts",
  "frontend/src/viewer.ts", "frontend/src/services.ts", "frontend/src/contracts.ts",
  "frontend/src/age.ts", "frontend/src/demo-head.ts", "frontend/package.json",
  "frontend/package-lock.json", "docs/research-texture-display-v1.json",
];
for (const path of [repoRelative(inputPath), ...requiredSources]) assert.ok(planned.has(path), `Freeze ${path}.`);
const policy = JSON.parse(await readFile(await existing("docs/research-texture-display-v1.json"), "utf8"));
assert.equal(policy.protocol_id, "agemorph3d-research-texture-display-v1");
assert.equal(producer.protocol_id, "agemorph3d-blend-display-v1");
assert.equal(producer.research_only, true); assert.equal(producer.service_ready, false); assert.equal(producer.g3_complete, false);
assert.equal(producer.records.length, 98);
const registrationPath = await verifyPin(producer.inputs.registration_report);
const resetPath = await verifyPin(producer.inputs.source_reset_report);
assert.ok(planned.has(producer.inputs.registration_report.path));
assert.ok(planned.has(producer.inputs.source_reset_report.path));
const registration = JSON.parse(await readFile(registrationPath, "utf8"));
const reset = JSON.parse(await readFile(resetPath, "utf8"));
assert.equal(registration.protocol_id, "agemorph3d-target-uv-v1");
assert.equal(reset.protocol_id, "agemorph3d-source-reset-v1");
assert.equal(registration.records.length, 37); assert.equal(reset.records.length, 10);
assert.ok(registration.records.every(row => row.status === "ok"));
assert.ok(reset.records.every(row => row.status === "ok"));
const unknown = { value: null, method: "unknown", calibration_id: null };
const sources = new Map(), assetBytes = new Map(), inputPins = [];
async function bindAsset(pathname, pin) {
  const path = await verifyPin(pin); inputPins.push(pin);
  assetBytes.set(pathname, await readFile(path)); return pathname;
}
for (const source of reset.records) {
  assert.match(source.sample_id, /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,120}$/);
  assert.deepEqual(source.source_age, unknown);
  assert.equal(sources.has(source.sample_id), false);
  const id = source.sample_id;
  const glbPath = await bindAsset(`/api/assets/interactive/${id}/source.glb`, source.artifacts.glb);
  const pngPath = await bindAsset(`/api/assets/interactive/${id}/source.png`, source.artifacts.atlas);
  const document = glb(assetBytes.get(glbPath)).document;
  assert.deepEqual(document.extras.source_age, unknown); assert.equal(document.extras.asset_mode, "static");
  assert.equal(document.materials[0].alphaMode, "MASK"); assert.equal(document.materials[0].alphaCutoff, 0.5);
  const records = producer.records.filter(row => row.source_id === id);
  assert.ok(records.length > 0 && records.every(row => JSON.stringify(row.expected_geometry) === JSON.stringify(records[0].expected_geometry)));
  sources.set(id, { source_id: id, source_label: source.label_source_age,
    glb_path: glbPath, original_png_path: pngPath, original_glb: source.artifacts.glb,
    original_png: source.artifacts.atlas, topology_id: document.extras.topology_id,
    expected_geometry: records[0].expected_geometry, cases: records, anchors: [] });
}
assert.equal([...sources.values()].filter(source => source.source_label === null).length, 2);
const representativeIds = new Set([
  producer.records.find(record => record.kind === "source_exact")?.sample_id,
  [...producer.records].sort((a, b) => b.fractional_alpha_texels - a.fractional_alpha_texels)[0]?.sample_id,
  producer.records.find(record => record.target_age === 20)?.sample_id,
  producer.records.find(record => record.target_age === 70)?.sample_id,
].filter(Boolean));
for (const row of registration.records) {
  const source = sources.get(row.source_id); assert.ok(source);
  const path = await bindAsset(`/api/assets/interactive/${row.sample_id}.png`, row.artifacts.atlas);
  source.anchors.push({ age: row.target_age, path, kind: "sam_condition" });
}
for (const source of sources.values()) if (source.source_label !== null)
  source.anchors.push({ age: source.source_label, path: source.original_png_path, kind: "original_source" });
const output = contained(process.env.AGEMORPH_RESEARCH_DISPLAY_OUTPUT);
assert.ok(repoRelative(output).startsWith("output/research/"));
await mkdir(dirname(output), { recursive: true }); assert.ok(isContained(await realpath(dirname(output))));
await mkdir(output); // Existing evidence is never overwritten.
const report = {
  schema_version: 1, protocol_id: protocolId, status: "running",
  input: await filePin(inputPath), study_plan: await filePin(planPath), frozen_source_pins: plan.inputs,
  input_asset_pins: inputPins, started_at_utc: new Date().toISOString(),
  requested_browsers: ["chrome", "msedge"], cases_per_browser: 98, sources_per_browser: 10,
  epsilons_years: [0.1, 0.01, 0.001, 0.0001], views: ["front", "side"], backgrounds: ["black", "white"],
  research_only: true, service_ready: false, g3_complete: false, age_quality_accepted: false,
  identity_quality_accepted: false, rendered_continuity_accepted: false,
  production_capabilities_changed: false, real_model_inference: false, results: [],
  interpretation: "A sampled display derivative uses BLEND at every age, including the exact original source point. Original encoded MASK assets remain unchanged; their rendered appearance may differ.",
};
let frontend, assets, browser, vite, failure, interrupted = false;
const delayedResponses = new Set();
const assetRequests = [];
const server = createHttpServer((request, response) => {
  const headers = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
  const origin = request.headers.origin;
  if (origin && origin !== frontend) { response.writeHead(403, headers).end(); return; }
  if (origin) headers["Access-Control-Allow-Origin"] = frontend;
  if (!["GET", "HEAD"].includes(request.method)) { response.writeHead(405, headers).end(); return; }
  const path = new URL(request.url ?? "/", assets).pathname; assetRequests.push({ method: request.method, path });
  const delayed = path === "/api/assets/interactive/delayed.png";
  const data = delayed ? assetBytes.get([...sources.values()][0].original_png_path) : assetBytes.get(path);
  if (!data) { response.writeHead(404, headers).end(); return; }
  const send = () => {
    response.writeHead(200, { ...headers, "Content-Type": path.endsWith(".glb") ? "model/gltf-binary" : "image/png", "Content-Length": data.length });
    response.end(request.method === "HEAD" ? undefined : data);
  };
  if (delayed) {
    const timer = setTimeout(() => { delayedResponses.delete(timer); if (!response.destroyed) send(); }, 1000);
    delayedResponses.add(timer);
  } else send();
});
const interrupt = () => { interrupted = true; browser?.close().catch(() => {}); };
process.once("SIGINT", interrupt); process.once("SIGTERM", interrupt);
try {
  await new Promise((resolveListen, reject) => { server.once("error", reject); server.listen(0, "127.0.0.1", resolveListen); });
  assets = `http://127.0.0.1:${server.address().port}`;
  vite = await createViteServer({ root: fileURLToPath(new URL("../", import.meta.url)), configFile: false,
    server: { host: "127.0.0.1", port: 0, strictPort: true, open: false },
    plugins: [{ name: "interactive-research-texture-display",
      resolveId(id) { if (id === "/__interactive_modules.js") return "\0interactive-texture-modules"; },
      load(id) { if (id === "\0interactive-texture-modules") return `
        export { FaceViewer } from '/src/viewer.ts';
        export {createResearchTimeline,sampleResearchTexture} from '/src/research-texture.ts';
        export { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
        export * as THREE from 'three';`; },
      configureServer(instance) {
        instance.middlewares.use((request, response, next) => {
          if (request.url?.split("?")[0] !== "/__interactive_display") return next();
          response.setHeader("Content-Type", "text/html; charset=utf-8");
          response.end(`<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>隔离连续纹理显示研究</title>
            <style>body{margin:0;background:#111827;color:#e1edf5;font:15px system-ui}header{padding:10px 20px}
            #viewer{height:600px}input{width:65%}</style><header><h1>连续纹理显示研究 · 非年龄预测 / 非 G3</h1>
            <label>研究显示条件 <input id="display-age" type="range" min="20" max="70" step="any"></label>
            <output id="display-value"></output><p id="state">仅对本机已注册 atlas 进行插值</p></header><div id="viewer"></div></html>`);
        });
      },
    }],
  });
  await vite.listen(); frontend = `http://127.0.0.1:${vite.httpServer.address().port}`;
  report.owned_servers = { frontend, assets };
  for (const channel of report.requested_browsers) {
    assert.equal(interrupted, false);
    const errors = [], externalRequests = [];
    browser = await chromium.launch({ channel, headless: true, timeout: 30_000,
      args: ["--enable-unsafe-swiftshader", "--use-angle=swiftshader"] });
    const page = await browser.newPage({ viewport: { width: 1000, height: 780 }, locale: "zh-CN" });
    page.on("pageerror", error => errors.push(error.message));
    page.on("request", request => { const url = new URL(request.url());
      if (["http:", "https:"].includes(url.protocol) && ![frontend, assets].includes(url.origin)) externalRequests.push(request.url()); });
    await page.goto(`${frontend}/__interactive_display`, { waitUntil: "networkidle", timeout: 30_000 });
    await page.evaluate(installTools);
    const result = { channel, version: browser.version(), sources: [], lifecycle: [], errors,
      external_requests: externalRequests, status: "running" };
    report.results.push(result);
    let count = 0;
    for (const source of sources.values()) {
      assert.equal(interrupted, false);
      const browserSource = { ...source, glb_url: assets + source.glb_path,
        anchors: source.anchors.map(anchor => ({ ...anchor, url: assets + anchor.path })) };
      const initialized = await bounded(page.evaluate(source => window.researchTools.loadSource(source), browserSource), 45_000, "Source load");
      const sourceResult = { source_id: source.source_id, source_label: source.source_label,
        initialized, cases: [], neighborhoods: [], status: "running" };
      result.sources.push(sourceResult);
      for (const record of source.cases) {
        const saveGlb = representativeIds.has(record.sample_id);
        const observed = await bounded(page.evaluate(({ record, save }) => window.researchTools.exportCase(record, save),
          { record, save: saveGlb }), 45_000, `Display ${record.sample_id}`);
        const pngPath = resolve(output, `${record.sample_id}-${channel}-raw-export.png`);
        await writeFile(pngPath, Buffer.from(observed.png_base64, "base64"), { flag: "wx" });
        observed.raw_export_png = await filePin(pngPath); delete observed.png_base64;
        if (observed.glb_base64) {
          const glbPath = resolve(output, `${record.sample_id}-${channel}.glb`);
          await writeFile(glbPath, Buffer.from(observed.glb_base64, "base64"), { flag: "wx" });
          observed.exported_glb = await filePin(glbPath); delete observed.glb_base64;
        }
        sourceResult.cases.push(observed); count++;
        if (count % 10 === 0 || count === 98) console.log(JSON.stringify({ channel, cases: count, requested: 98 }));
      }
      if (source.source_label !== null) {
        sourceResult.neighborhoods = await bounded(page.evaluate(epsilons => window.researchTools.neighborhoods(epsilons),
          report.epsilons_years), 60_000, `Source neighborhoods ${source.source_id}`);
        sourceResult.original_mask_control = await bounded(page.evaluate(() => window.researchTools.originalMaskControl()), 30_000, "Original MASK control");
      } else sourceResult.source_point_status = "SOURCE_AGE_UNKNOWN";
      if (result.sources.length <= 2) {
        const screenshot = resolve(output, `${source.source_id}-${channel}-interactive.png`);
        await page.screenshot({ path: screenshot, timeout: 20_000 }); sourceResult.screenshot = await filePin(screenshot);
      }
      sourceResult.status = "passed";
    }
    assert.equal(count, 98);
    // Explicit lifecycle checks run after the 98 slider updates, separately from
    // per-source loading, so ordinary updates never reload a mesh.
    const first = [...sources.values()][0];
    await page.evaluate(source => window.researchTools.loadSource(source), { ...first, glb_url: assets + first.glb_path,
      anchors: first.anchors.map(anchor => ({ ...anchor, url: assets + anchor.path })) });
    const delayedRequest = page.waitForRequest(request => request.url().endsWith("/api/assets/interactive/delayed.png"), { timeout: 10_000 });
    await page.evaluate(url => window.researchTools.beginOrdinaryPending(url), assets + "/api/assets/interactive/delayed.png");
    await delayedRequest;
    result.lifecycle.push(await bounded(page.evaluate(() => window.researchTools.cancelOrdinaryWithResearch()), 10_000, "Ordinary texture cancellation"));
    result.lifecycle.push(await bounded(page.evaluate(url => window.researchTools.lifecycle(url), assets + first.original_png_path), 45_000, "Display lifecycle"));
    await page.evaluate(() => window.researchTools.close());
    assert.deepEqual(errors, []); assert.deepEqual(externalRequests, []); result.status = "passed";
    await bounded(browser.close(), 15_000, "Browser close"); browser = undefined;
  }
  for (const pin of [...plan.inputs, ...inputPins]) await verifyPin(pin);
  report.status = "passed";
} catch (error) {
  failure = error; report.status = "failed"; report.error = error instanceof Error ? error.stack : String(error);
} finally {
  for (const timer of delayedResponses) clearTimeout(timer); delayedResponses.clear();
  const cleanup = await Promise.allSettled([
    browser ? bounded(browser.close(), 15_000, "Final browser close") : undefined,
    vite ? bounded(vite.close(), 10_000, "Vite close") : undefined,
    server.listening ? bounded(new Promise((done, reject) => {
      server.close(error => error ? reject(error) : done()); server.closeAllConnections();
    }), 10_000, "Asset server close") : undefined,
  ]);
  report.owned_servers_closed = cleanup.every(value => value.status === "fulfilled") && !server.listening && !vite?.httpServer?.listening;
  report.cleanup = cleanup.map((value, index) => ({ resource: ["browser", "vite", "assets"][index], status: value.status,
    ...(value.status === "rejected" ? { error: String(value.reason) } : {}) }));
  report.asset_requests = assetRequests; report.interrupted = interrupted; report.finished_at_utc = new Date().toISOString();
  if (!report.owned_servers_closed) { failure ??= new Error("Owned resources did not close."); report.status = "failed"; }
  await writeFile(resolve(output, "research-texture-browser.json"), `${JSON.stringify(report, null, 2)}\n`, { flag: "wx" });
  process.removeListener("SIGINT", interrupt); process.removeListener("SIGTERM", interrupt);
}
if (failure) throw failure;
console.log(JSON.stringify({ status: report.status, browsers: report.results.length, cases: 196,
  raw_export_pngs: 196, owned_servers_closed: report.owned_servers_closed, g3_complete: false, output }));

async function installTools() {
  const { FaceViewer, GLTFLoader, THREE, createResearchTimeline, sampleResearchTexture } = await import("/__interactive_modules.js");
  let viewer = new FaceViewer(document.getElementById("viewer")), source, timeline, current, originals, originalRgba;
  let pending, inputEvents = 0, meshLoads = 0;
  const slider = document.getElementById("display-age");
  const hex = async data => [...new Uint8Array(await crypto.subtle.digest("SHA-256", data))].map(value => value.toString(16).padStart(2, "0")).join("");
  const typedHash = array => hex(new Uint8Array(array.buffer, array.byteOffset, array.byteLength));
  const materials = () => viewer.bindings.flatMap(binding => Array.isArray(binding.material) ? binding.material : [binding.material]);
  const options = () => ({ asset_mode: "static", topology_id: source.topology_id,
    source_age: { value: null, method: "unknown", calibration_id: null }, capabilities: { age_morph: false, age_texture: false } });
  const freezeOriginals = () => materials().map(material => ({ material, map: material.map,
    transparent: material.transparent, alphaTest: material.alphaTest, depthWrite: material.depthWrite,
    premultipliedAlpha: material.premultipliedAlpha, opacity: material.opacity }));
  const restored = () => originals.every(state => state.material.map === state.map &&
    ["transparent", "alphaTest", "depthWrite", "premultipliedAlpha", "opacity"].every(key => state.material[key] === state[key]));
  const assertRestored = () => { if (!restored()) throw new Error("Original material/map state was not restored."); };
  const assertResearchReleased = () => {
    if (viewer.researchTexture !== null || viewer.researchCanvas !== null || viewer.researchMaterialStates.size !== 0)
      throw new Error("Viewer retained owned research texture/canvas/material snapshots.");
  };
  const assertDisplay = () => {
    for (const material of materials()) {
      if (!material.transparent || material.alphaTest !== 0 || material.depthWrite || material.premultipliedAlpha || material.opacity !== 1)
        throw new Error("Research frame did not use consistent straight-alpha BLEND flags.");
      if (material.map?.colorSpace !== "srgb" || material.map.flipY !== false) throw new Error("Research map orientation/color space changed.");
    }
    if (viewer.model.userData.source_age.value !== null) throw new Error("Research source label entered API provenance.");
  };
  slider.addEventListener("input", () => {
    current = sampleResearchTexture(timeline, Number(slider.value));
    viewer.setResearchDisplayTexture(current); inputEvents++;
    document.getElementById("display-value").textContent = slider.value;
    document.getElementById("state").textContent = `${source.source_id} · 研究条件${slider.value} · 原始API源龄unknown`;
    assertDisplay();
  });
  const show = age => {
    slider.value = String(age); slider.dispatchEvent(new Event("input", { bubbles: true }));
    if (!current || current.targetAge !== age) throw new Error("Range input rounded or omitted the requested condition.");
    return current;
  };
  const pngRgba = async url => {
    const response = await fetch(url, { signal: AbortSignal.timeout(20_000), cache: "no-store" });
    if (!response.ok) throw new Error(`Anchor HTTP ${response.status}.`);
    const image = await createImageBitmap(await response.blob(), { premultiplyAlpha: "none", colorSpaceConversion: "none" });
    const canvas = document.createElement("canvas"); canvas.width = image.width; canvas.height = image.height;
    const context = canvas.getContext("2d", { willReadFrequently: true }); context.drawImage(image, 0, 0); image.close();
    const rgba = context.getImageData(0, 0, canvas.width, canvas.height).data;
    return { width: canvas.width, height: canvas.height, rgba };
  };
  const arrayInfo = async geometry => {
    const result = {};
    for (const key of ["position", "normal", "uv"]) {
      const attribute = geometry.getAttribute(key); if (!attribute) throw new Error(`Missing ${key}.`);
      result[key] = await typedHash(attribute.array);
    }
    if (!geometry.index) throw new Error("Source index required."); result.index = await typedHash(geometry.index.array); return result;
  };
  const capture = async () => {
    const result = {};
    for (const view of ["front", "side"]) {
      viewer.setView(view);
      await new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done)));
      const size = viewer.renderer.getDrawingBufferSize(new THREE.Vector2()), gl = viewer.renderer.getContext();
      for (const background of ["black", "white"]) {
        viewer.scene.background = new THREE.Color(background); viewer.renderer.render(viewer.scene, viewer.camera);
        const pixels = new Uint8Array(size.x * size.y * 4); gl.readPixels(0, 0, size.x, size.y, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
        if (gl.getError() !== gl.NO_ERROR) throw new Error("WebGL readPixels failed.");
        result[`${view}_${background}`] = { width: size.x, height: size.y, rgba: pixels, sha256: await hex(pixels) };
      }
    }
    viewer.scene.background = new THREE.Color("#0a0e1a"); viewer.setView("front");
    viewer.renderer.render(viewer.scene, viewer.camera); return result;
  };
  const difference = (a, b) => Object.fromEntries(Object.keys(a).map(key => {
    const before = a[key], after = b[key];
    if (before.width !== after.width || before.height !== after.height) throw new Error("Rendered raster changed.");
    let changed = 0, squared = 0, maximum = 0;
    for (let index = 0; index < before.rgba.length; index += 4) {
      let differs = false;
      for (let channel = 0; channel < 3; channel++) {
        const delta = Math.abs(after.rgba[index + channel] - before.rgba[index + channel]) / 255;
        differs ||= delta > 0; squared += delta * delta; maximum = Math.max(maximum, delta);
      }
      changed += differs;
    }
    return [key, { before_sha256: before.sha256, after_sha256: after.sha256,
      changed_pixels: changed, max_channel_difference: maximum,
      rms_channel_difference: Math.sqrt(squared / (before.width * before.height * 3)) }];
  }));
  const renderFront = async () => {
    viewer.setView("front");
    await new Promise(done => requestAnimationFrame(done));
    viewer.renderer.render(viewer.scene, viewer.camera);
    const size = viewer.renderer.getDrawingBufferSize(new THREE.Vector2()), gl = viewer.renderer.getContext();
    const pixels = new Uint8Array(size.x * size.y * 4);
    gl.readPixels(0, 0, size.x, size.y, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
    if (gl.getError() !== gl.NO_ERROR) throw new Error("Interactive frame could not be read.");
    let variedPixels = 0;
    for (let index = 0; index < pixels.length; index += 4)
      variedPixels += pixels[index] !== pixels[0] || pixels[index + 1] !== pixels[1] || pixels[index + 2] !== pixels[2];
    if (variedPixels === 0) throw new Error("Interactive range update rendered a uniform/empty viewport.");
    return { width: size.x, height: size.y, rgba_sha256: await hex(pixels), pixels_different_from_corner: variedPixels };
  };
  const disposeScene = scene => {
    const geometries = new Set(), maps = new Set(), entries = new Set();
    scene.traverse(node => { if (!node.isMesh) return; geometries.add(node.geometry);
      for (const material of Array.isArray(node.material) ? node.material : [node.material]) entries.add(material); });
    for (const material of entries) { for (const value of Object.values(material)) if (value?.isTexture) maps.add(value); material.dispose(); }
    for (const geometry of geometries) geometry.dispose();
    for (const map of maps) { map.dispose(); if (typeof ImageBitmap !== "undefined" && map.image instanceof ImageBitmap) map.image.close(); }
  };
  const base64 = bytes => { let value = ""; for (let index = 0; index < bytes.length; index += 32768)
    value += String.fromCharCode(...bytes.subarray(index, index + 32768)); return btoa(value); };
  window.researchTools = {
    async loadSource(next) {
      source = next;
      const anchors = [];
      for (const anchor of source.anchors) anchors.push({ age: anchor.age, kind: anchor.kind, ...await pngRgba(anchor.url) });
      originalRgba = anchors.find(anchor => anchor.kind === "original_source")?.rgba;
      timeline = createResearchTimeline(anchors, source.source_label);
      await viewer.loadModel(source.glb_url, options()); meshLoads++;
      viewer.setAutoRotate(false); viewer.setBackground(false); viewer.setView("front"); originals = freezeOriginals();
      const actual = await arrayInfo(viewer.bindings[0].mesh.geometry);
      for (const [key, expected] of [["position", "source_positions_sha256"], ["normal", "source_normals_sha256"], ["index", "source_indices_sha256"], ["uv", "gltf_uv_sha256"]])
        if (actual[key] !== source.expected_geometry[expected]) throw new Error("Source geometry/UV differs from the frozen frame.");
      return { source_api_age: viewer.model.userData.source_age, geometry: actual, model_load_count: meshLoads,
        original_material_flags: originals.map(({ map, material, ...flags }) => flags), input_events_before: inputEvents };
    },
    async exportCase(record, save) {
      const loadsBefore = meshLoads, eventsBefore = inputEvents;
      const frame = show(record.target_age); const frameHash = await hex(frame.rgba);
      if (frameHash !== record.rgba_sha256) throw new Error(`Sampler parity differs from frozen raw atlas: ${record.sample_id}.`);
      const exactAnchor = source.anchors.find(anchor => anchor.kind === "original_source");
      if (record.kind === "source_exact" && (!frame.exactSource || exactAnchor?.age !== record.target_age || frame.rgba !== originalRgba)) throw new Error("Exact original source anchor lost.");
      const renderedFront = await renderFront();
      const bytes = await (await viewer.exportGLB()).arrayBuffer();
      const reimport = await new GLTFLoader().parseAsync(bytes, "");
      try {
        const meshes = []; reimport.scene.traverse(node => { if (node.isMesh) meshes.push(node); });
        if (meshes.length !== 1) throw new Error("Export changed source mesh count.");
        const geometry = await arrayInfo(meshes[0].geometry), originalGeometry = await arrayInfo(viewer.bindings[0].mesh.geometry);
        if (JSON.stringify(geometry) !== JSON.stringify(originalGeometry)) throw new Error("Export changed geometry/UV/index.");
        const material = meshes[0].material;
        if (!material.transparent || material.alphaTest !== 0 || material.depthWrite) throw new Error("Export lost consistent BLEND mode.");
        if (material.map.colorSpace !== "srgb" || material.map.flipY !== false) throw new Error("Export changed texture semantics.");
        const displayMetadata = [];
        reimport.scene.traverse(node => { if (node.userData.research_display) displayMetadata.push(node.userData); });
        if (!displayMetadata.length || displayMetadata.some(data => data.research_display.target_condition !== record.target_age || data.texture_age !== undefined))
          throw new Error("Export lost research condition metadata or retained a stale ordinary age.");
        const data = new Uint8Array(bytes), view = new DataView(bytes), jsonLength = view.getUint32(12, true);
        const document = JSON.parse(new TextDecoder().decode(data.subarray(20, 20 + jsonLength)));
        if (document.images.length !== 1 || document.images[0].mimeType !== "image/png") throw new Error("One embedded raw PNG required.");
        const image = document.bufferViews[document.images[0].bufferView], binaryStart = 28 + jsonLength;
        const png = data.subarray(binaryStart + (image.byteOffset ?? 0), binaryStart + (image.byteOffset ?? 0) + image.byteLength);
        if (meshLoads !== loadsBefore || inputEvents !== eventsBefore + 1) throw new Error("Slider update reloaded the mesh or missed its input event.");
        return { sample_id: record.sample_id, target_age: record.target_age, kind: record.kind,
          sampler_rgba_sha256: frameHash, producer_rgba_sha256: record.rgba_sha256, sampler_exact_source: frame.exactSource,
          displayed_derivative_alpha_mode: "BLEND", geometry, model_load_count: meshLoads,
          rendered_front: renderedFront,
          slider_input_events: inputEvents, exported_bytes: bytes.byteLength, exported_sha256: await hex(bytes),
          png_base64: base64(png), raw_embedded_png_sha256: await hex(png),
          ...(save ? { glb_base64: base64(data) } : {}), status: "passed" };
      } finally { disposeScene(reimport.scene); }
    },
    async neighborhoods(epsilons) {
      const age = source.source_label; if (age === null) throw new Error("Unknown source has no absolute source point.");
      const exactFrame = show(age), exactHash = await hex(exactFrame.rgba), exact = await capture();
      const output = [];
      for (const epsilon of epsilons) {
        const beforeFrame = show(age - epsilon), beforeHash = await hex(beforeFrame.rgba), before = await capture();
        const afterFrame = show(age + epsilon), afterHash = await hex(afterFrame.rgba), after = await capture();
        output.push({ epsilon_years: epsilon, source_label: age, before_age: age - epsilon, after_age: age + epsilon,
          sampler_before_rgba_sha256: beforeHash, sampler_exact_rgba_sha256: exactHash, sampler_after_rgba_sha256: afterHash,
          consistent_material_alpha_mode: "BLEND", before_to_exact: difference(before, exact),
          exact_to_after: difference(exact, after), before_to_after: difference(before, after) });
      }
      show(age); return output;
    },
    async originalMaskControl() {
      const age = source.source_label; show(age); const blend = await capture();
      viewer.setResearchDisplayTexture(null); assertRestored(); assertResearchReleased(); const mask = await capture();
      show(age);
      return { original_encoded_assets_unchanged: true, original_material_restored: true,
        interpretation: "Same source pixels: original MASK versus consistent BLEND derivative; not age interpolation error.",
        mask_to_blend: difference(mask, blend) };
    },
    beginOrdinaryPending(url) { pending = viewer.setTexture(url).then(() => ({ status: "fulfilled" }), error => ({ status: "rejected", name: error.name })); },
    async cancelOrdinaryWithResearch() {
      show(45); const map = materials()[0].map, outcome = await pending;
      if (outcome.status !== "rejected" || outcome.name !== "AbortError" || materials()[0].map !== map) throw new Error("Pending ordinary texture overwrote research frame.");
      assertDisplay(); return { case: "research_frame_aborts_pending_ordinary_texture", outcome, research_map_retained: true };
    },
    async lifecycle(basePngUrl) {
      show(45);
      const oldTexture = viewer.researchTexture, oldCanvas = viewer.researchCanvas;
      let textureDisposed = false; oldTexture.addEventListener("dispose", () => { textureDisposed = true; });
      viewer.setResearchDisplayTexture(null); assertRestored(); assertResearchReleased();
      if (!textureDisposed || oldCanvas.width !== 0 || oldCanvas.height !== 0) throw new Error("Research resource backing store was not released.");
      show(45); await viewer.setTexture(basePngUrl, false, 45); // Valid ordinary API clears research state first.
      if (materials().some(material => material.transparent || material.alphaTest !== 0.5 || !material.depthWrite)) throw new Error("Ordinary texture inherited research BLEND flags.");
      assertResearchReleased();
      const ordinaryMap = materials()[0].map;
      show(30);
      if (viewer.model.userData.texture_age !== undefined || viewer.model.userData.research_display.target_condition !== 30)
        throw new Error("Research display retained stale ordinary texture age.");
      const derivative = await new GLTFLoader().parseAsync(await (await viewer.exportGLB()).arrayBuffer(), "");
      try {
        const marked = []; derivative.scene.traverse(node => { if (node.userData.research_display) marked.push(node.userData); });
        if (!marked.length || marked.some(data => data.research_display.target_condition !== 30 || data.texture_age !== undefined))
          throw new Error("Export retained stale ordinary texture age metadata.");
      } finally { disposeScene(derivative.scene); }
      viewer.setResearchDisplayTexture(null); assertResearchReleased();
      if (materials()[0].map !== ordinaryMap || viewer.model.userData.texture_age !== 45 || viewer.model.userData.research_display !== undefined)
        throw new Error("Clearing research did not restore ordinary texture/map/age45.");
      await viewer.setTexture(null); assertRestored();
      show(45); await viewer.loadModel(source.glb_url, options()); meshLoads++; originals = freezeOriginals();
      if (viewer.model.userData.research_display !== undefined || materials().some(material => material.transparent || material.alphaTest !== 0.5)) throw new Error("Model replacement retained research state.");
      show(45); viewer.loadDemo();
      if (viewer.model.userData.research_display !== undefined) throw new Error("Demo replacement retained research metadata.");
      await viewer.loadModel(source.glb_url, options()); meshLoads++; originals = freezeOriginals(); show(45);
      viewer.dispose(); viewer.dispose();
      assertResearchReleased();
      if (document.querySelectorAll("#viewer canvas").length !== 0) throw new Error("Disposed viewer retained its canvas.");
      return { case: "clear_ordinary_model_demo_dispose", clear_restored_original: true,
        ordinary_texture_restored_mask: true, model_replacement_cleared: true, demo_cleared: true,
        ordinary_age_45_hidden_during_research_30_and_restored: true,
        research_export_without_stale_texture_age: true, owned_texture_disposed: textureDisposed,
        research_canvas_backing_store_released: true, dispose_idempotent: true, canvases_remaining: 0 };
    },
    close() { viewer.dispose(); timeline = undefined; current = undefined; originals = undefined; },
  };
}

function hash(bytes) { return createHash("sha256").update(bytes).digest("hex"); }
function repoRelative(path) { return relative(root, path).replaceAll("\\", "/"); }
function isContained(path) { const name = relative(root, path); return name && !name.startsWith("..") && !isAbsolute(name); }
function contained(value) { assert.ok(value, "Supply an explicit workspace path."); const path = resolve(root, value); assert.ok(isContained(path)); return path; }
async function existing(value) { const path = await realpath(contained(value)); assert.ok(isContained(path)); return path; }
async function filePin(path) { const bytes = await readFile(path); return { path: repoRelative(path), sha256: hash(bytes), bytes: bytes.length }; }
async function verifyPin(pin) {
  assert.ok(pin && Object.keys(pin).sort().join() === "bytes,path,sha256"); assert.match(pin.sha256, /^[a-f0-9]{64}$/);
  assert.ok(Number.isInteger(pin.bytes) && pin.bytes > 0); const path = await existing(pin.path);
  assert.equal(repoRelative(path), pin.path); assert.deepEqual(await filePin(path), pin); return path;
}
function glb(bytes) {
  assert.equal(bytes.toString("ascii", 0, 4), "glTF"); assert.equal(bytes.readUInt32LE(4), 2); assert.equal(bytes.readUInt32LE(8), bytes.length);
  const length = bytes.readUInt32LE(12); assert.equal(bytes.toString("ascii", 16, 20), "JSON");
  const start = 20 + length; assert.equal(bytes.toString("ascii", start + 4, start + 8), "BIN\0");
  const binary = bytes.subarray(start + 8); assert.equal(bytes.readUInt32LE(start), binary.length);
  return { document: JSON.parse(bytes.toString("utf8", 20, start)), binary };
}
async function bounded(promise, milliseconds, name) {
  let timer;
  try { return await Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`${name} exceeded ${milliseconds} ms.`)), milliseconds); })]); }
  finally { clearTimeout(timer); }
}
