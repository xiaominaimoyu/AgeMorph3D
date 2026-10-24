import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, open, realpath, writeFile } from "node:fs/promises";
import { createServer as createHttpServer } from "node:http";
import { dirname, isAbsolute, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";
import { createServer as createViteServer } from "vite";

// Explicitly invoked, isolated research harness. No production page or age API.
// Private viewer inspection is frozen with its source, not a public API promise.
const PROTOCOL = "agemorph3d-render-domain-v1";
const MAX_METADATA = 20 * 1024 ** 2;
const MAX_GLB = 64 * 1024 ** 2;
const MAX_PNG = 16 * 1024 ** 2;
const UNKNOWN = { value: null, method: "unknown", calibration_id: null };
const GEOMETRY = {
  position: "source_positions_sha256", normal: "source_normals_sha256",
  index: "source_indices_sha256", uv: "gltf_uv_sha256",
};
const REQUIRED_SOURCES = [
  "frontend/tests/render-domain-capture.mjs", "frontend/src/viewer.ts",
  "frontend/src/services.ts", "frontend/src/contracts.ts", "frontend/src/realtime.ts",
  "frontend/src/age.ts", "frontend/src/demo-head.ts", "frontend/src/research-texture.ts",
  "frontend/package.json", "frontend/package-lock.json", "docs/render-domain-v1.json",
];
const root = await realpath(fileURLToPath(new URL("../../", import.meta.url)));
const planPath = await existing(process.env.AGEMORPH_RENDER_PLAN);
const planRaw = await boundedRead(planPath, MAX_METADATA);
const plan = json(planRaw);
assert.equal(plan.protocol_id, PROTOCOL);
assert.ok(Array.isArray(plan.inputs) && plan.inputs.length <= 128);
const planned = new Map(), documents = [];
for (const pin of plan.inputs) {
  assert.equal(planned.has(pin.path), false, "Duplicate study-plan input.");
  const raw = await readPinned(pin, MAX_METADATA);
  planned.set(pin.path, pin);
  if (pin.path.endsWith(".json")) documents.push({ pin, value: json(raw) });
}
for (const name of REQUIRED_SOURCES) assert.ok(planned.has(name), `Freeze ${name}.`);
const policy = findDocument(PROTOCOL, "protocol");
const registration = findDocument("agemorph3d-target-uv-v1", "registration_report");
const reset = findDocument("agemorph3d-source-reset-v1", "source_reset_report");
const n0 = documents.filter(row => row.value.protocol_id === "agemorph3d-age-research-v1" && Array.isArray(row.value.bridge_cases));
assert.equal(n0.length, 1, "Freeze exactly one N0 manifest.");
const n0Document = n0[0];
assert.deepEqual(registration.value.inputs.protocol_manifest, n0Document.pin);
assert.deepEqual(reset.value.inputs.protocol_manifest, n0Document.pin);
assert.equal(policy.pin.path, "docs/render-domain-v1.json");
validatePolicy(policy.value);
for (const document of [registration.value, reset.value, n0Document.value]) {
  assert.equal(document.research_only, true);
  assert.equal(document.service_ready, false);
  assert.equal(document.g3_complete, false);
}
assert.equal(registration.value.holdout_age_results_opened, false);
assert.equal(reset.value.holdout_age_results_opened, false);
assert.equal(registration.value.records.length, 37);
assert.equal(reset.value.records.length, 10);
const cases = new Map(n0Document.value.bridge_cases.filter(row => row.source_status === "passed").map(row => [row.sample_id, row]));
assert.equal(cases.size, 10);
const originalRows = new Map(), assets = [], payloads = new Map(), assetPins = new Map();
const outputKeys = new Set();
for (const row of reset.value.records) {
  identifier(row.sample_id);
  assert.equal(row.status, "ok"); assert.equal(row.group, "development");
  assert.deepEqual(row.source_age, UNKNOWN);
  const source = cases.get(row.sample_id); assert.ok(source);
  assert.equal(source.group, "development"); assert.equal(source.subject_id, row.subject_id);
  assert.deepEqual(source.source, row.input);
  assert.equal(source.source_age.value, row.label_source_age);
  label(row.label_source_age);
  assert.equal(originalRows.has(row.sample_id), false);
  originalRows.set(row.sample_id, row);
  await addAsset(row, {
    asset_id: `${row.sample_id}--original`, source_id: row.sample_id, sample_id: null,
    role: "original_static_3d", source_age_label: row.label_source_age,
    target_age: null, category: "baseline",
  });
}
const seenConditions = new Set();
for (const row of registration.value.records) {
  identifier(row.sample_id); identifier(row.source_id);
  const source = cases.get(row.source_id), original = originalRows.get(row.source_id);
  assert.ok(source && original); assert.equal(row.status, "ok");
  assert.equal(row.subject_id, source.subject_id);
  assert.equal(row.source_age_label, source.source_age.value);
  assert.deepEqual(row.source_age, UNKNOWN);
  assert.deepEqual(row.capabilities, { age_morph: false, age_texture: false });
  assert.deepEqual(row.source_frame, original.source_frame);
  assert.ok(Number.isInteger(row.target_age) && row.target_age >= 20 && row.target_age <= 70);
  const candidates = [...source.target_runs];
  if (["generated", "reused_existing"].includes(source.same_age_control.status))
    candidates.push({ ...source.same_age_control.output, target_age: source.same_age_control.target_age });
  const expected = candidates.filter(item => item.target_age === row.target_age);
  assert.ok(expected.length >= 1);
  for (const item of expected) assert.deepEqual(pinOnly(item), row.input);
  const key = `${row.source_id}/${row.target_age}`;
  assert.equal(seenConditions.has(key), false); seenConditions.add(key);
  const invariants = registration.value.source_geometry_invariants[row.source_id];
  for (const name of Object.values(GEOMETRY)) assert.equal(row[name], invariants[name]);
  await addAsset(row, {
    asset_id: row.sample_id, source_id: row.source_id, sample_id: row.sample_id,
    role: "sam_texture_static_3d", source_age_label: row.source_age_label,
    target_age: row.target_age,
    category: row.source_age_label === null ? "unknown_source_age"
      : row.source_age_label === row.target_age ? "same_age_control" : "other_condition",
  });
}
const expectedConditions = new Set();
for (const source of cases.values()) {
  for (const target of source.target_runs) expectedConditions.add(`${source.sample_id}/${target.target_age}`);
  if (["generated", "reused_existing"].includes(source.same_age_control.status))
    expectedConditions.add(`${source.sample_id}/${source.same_age_control.target_age}`);
}
assert.deepEqual(seenConditions, expectedConditions);
assert.equal(assets.length, 47); assert.equal(assetPins.size, 94);
assert.equal(assets.filter(row => row.category === "same_age_control").length, 8);
assert.equal(assets.filter(row => row.category === "other_condition").length, 23);
assert.equal(assets.filter(row => row.category === "unknown_source_age").length, 6);
assert.equal(assets.filter(row => row.role === "original_static_3d" && row.source_age_label === null).length, 2);
const configurations = policy.value.capture.material_modes.flatMap(material_mode =>
  policy.value.capture.views.flatMap(view => policy.value.capture.backgrounds.map(background => ({ material_mode, view, background }))));
const frames = assets.flatMap(asset => configurations.map(configuration => ({
  ...descriptive(asset), frame_id: `${asset.asset_id}::${configId(configuration)}`,
  config_id: configId(configuration), configuration, status: "pending", image: null,
})));
assert.equal(frames.length, 376);
const frameIndex = new Map(frames.map(frame => [frame.frame_id, frame]));
const pairs = frames.filter(frame => frame.role === "sam_texture_static_3d").map(frame => ({
  source_id: frame.source_id, sample_id: frame.sample_id, config_id: frame.config_id,
  source_frame_id: `${frame.source_id}--original::${frame.config_id}`, target_frame_id: frame.frame_id,
}));
assert.equal(pairs.length, 296);
for (const pair of pairs) assert.ok(frameIndex.has(pair.source_frame_id));
const output = contained(process.env.AGEMORPH_RENDER_OUTPUT);
assert.ok(repoRelative(output).startsWith("output/research/"));
await mkdir(dirname(output), { recursive: true });
assert.ok(isContained(await realpath(dirname(output))));
await mkdir(output); // Existing evidence is never overwritten.
const studyPlanPin = pinBytes(planPath, planRaw);
const report = {
  schema_version: 1, protocol_id: PROTOCOL, status: "running",
  research_only: true, ...Object.fromEntries(Object.keys(policy.value.flags).filter(key => key !== "research_only").map(key => [key, false])),
  real_model_inference: false, production_capabilities_changed: false,
  input_geometry_is_static: true, quality_threshold: null,
  started_at_utc: new Date().toISOString(), study_plan: studyPlanPin,
  inputs: [studyPlanPin, ...plan.inputs],
  source_pins: REQUIRED_SOURCES.map(name => planned.get(name)), asset_pins: [...assetPins.values()],
  assets, frames, pairs, requested_frames: 376, requested_pairs: 296,
  requested_configuration: policy.value.capture, png_orientation: "top-left; native canvas.toBlob via actual FaceViewer.exportPNG",
  material_control_scope: "Only the five alpha/depth flags change. Original GLB maps and filtering remain; this is not the CanvasTexture sampling path.",
  limitations: "Development-only static geometry. Coverage, pose, lighting, alpha and rendering-domain confounds remain; no age/identity quality or G3 acceptance.",
};
let frontendOrigin, assetOrigin, vite, browser, context, page, failure, interrupted = false;
const browserErrors = [], externalRequests = [], assetRequests = [], baselineStates = new Map();
const server = createHttpServer((request, response) => {
  const headers = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
  if (request.headers.origin && request.headers.origin !== frontendOrigin) { response.writeHead(403, headers).end(); return; }
  if (request.headers.origin) headers["Access-Control-Allow-Origin"] = frontendOrigin;
  if (!["GET", "HEAD"].includes(request.method)) { response.writeHead(405, headers).end(); return; }
  const url = new URL(request.url ?? "/", assetOrigin);
  assetRequests.push({ method: request.method, path: url.pathname });
  const data = url.search ? undefined : payloads.get(url.pathname);
  if (!data) { response.writeHead(404, headers).end(); return; }
  response.writeHead(200, { ...headers, "Content-Type": "model/gltf-binary", "Content-Length": data.length });
  response.end(request.method === "HEAD" ? undefined : data);
});
const interrupt = () => { interrupted = true; browser?.close().catch(() => {}); };
process.once("SIGINT", interrupt); process.once("SIGTERM", interrupt);
try {
  await bounded(new Promise((done, reject) => { server.once("error", reject); server.listen(0, "127.0.0.1", done); }), 10_000, "Asset server listen");
  assetOrigin = `http://127.0.0.1:${server.address().port}`;
  vite = await createViteServer({ root: fileURLToPath(new URL("../", import.meta.url)), configFile: false,
    server: { host: "127.0.0.1", port: 0, strictPort: true, open: false },
    plugins: [{ name: "isolated-render-domain-capture",
      resolveId(id) { if (id === "/__render_domain_modules.js") return "\0render-domain-modules"; },
      load(id) { if (id === "\0render-domain-modules") return "export {FaceViewer} from '/src/viewer.ts'; export * as THREE from 'three';"; },
      configureServer(instance) { instance.middlewares.use((request, response, next) => {
        if (request.url?.split("?")[0] !== "/__render_domain") return next();
        response.setHeader("Content-Type", "text/html; charset=utf-8");
        response.end('<!doctype html><html><meta charset="utf-8"><title>Isolated render-domain research</title><style>html,body{margin:0;padding:0;width:1024px;height:1024px;overflow:hidden}#viewer{width:1024px;height:1024px}</style><div id="viewer"></div></html>');
      }); },
    }],
  });
  await bounded(vite.listen(), 20_000, "Vite listen");
  frontendOrigin = `http://127.0.0.1:${vite.httpServer.address().port}`;
  report.owned_servers = { frontend: frontendOrigin, assets: assetOrigin };
  browser = await chromium.launch({ channel: policy.value.capture.browser_channel,
    headless: policy.value.capture.headless, args: policy.value.capture.browser_args, timeout: 30_000 });
  report.browser = { channel: policy.value.capture.browser_channel, version: browser.version() };
  context = await browser.newContext({ viewport: { width: 1024, height: 1024 }, deviceScaleFactor: 1, locale: "zh-CN", serviceWorkers: "block" });
  await context.route("**/*", route => {
    const url = new URL(route.request().url());
    if (["http:", "https:"].includes(url.protocol) && ![frontendOrigin, assetOrigin].includes(url.origin)) {
      externalRequests.push(url.href); return route.abort("blockedbyclient");
    }
    return route.continue();
  });
  page = await context.newPage();
  page.on("pageerror", error => browserErrors.push(error.message));
  page.on("websocket", socket => {
    const url = new URL(socket.url());
    if (url.origin.replace(/^ws/, "http") !== frontendOrigin) externalRequests.push(url.href);
  });
  await page.goto(`${frontendOrigin}/__render_domain`, { waitUntil: "networkidle", timeout: 30_000 });
  report.renderer = await bounded(page.evaluate(installCapture), 30_000, "Actual viewer initialization");
  let attemptedFrames = 0;
  for (const asset of assets) {
    assert.equal(interrupted, false, "Capture was interrupted.");
    const requested = frames.filter(frame => frame.asset_id === asset.asset_id);
    try {
      asset.loaded = await bounded(page.evaluate(value => window.renderDomain.load(value), { ...asset, url: assetOrigin + asset.asset_url }), 45_000, `Load ${asset.asset_id}`);
      asset.status = "loaded";
      for (const frame of requested) {
        assert.equal(interrupted, false, "Capture was interrupted.");
        try {
          const result = await bounded(page.evaluate(configuration => window.renderDomain.capture(configuration), frame.configuration), 30_000, `Frame ${frame.frame_id}`);
          const baselineKey = `${asset.source_id}/${frame.config_id}`;
          if (asset.role === "original_static_3d") baselineStates.set(baselineKey, result.invariants);
          else assertPairedInvariants(result.invariants, baselineStates.get(baselineKey));
          const png = Buffer.from(result.png_base64, "base64"); delete result.png_base64;
          assert.ok(png.length > 0 && png.length <= MAX_PNG); assert.deepEqual(pngDimensions(png), [1024, 1024]);
          assert.equal(result.png_sha256, hash(png), "Browser/Node PNG transport hash differs.");
          const filename = `${asset.asset_id}--${frame.config_id.replaceAll("/", "--")}.png`;
          assert.equal(outputKeys.has(filename), false); outputKeys.add(filename);
          const path = resolve(output, filename);
          await writeFile(path, png, { flag: "wx" });
          frame.image = pinBytes(path, png); frame.status = "ok"; frame.observed = result;
        } catch (error) { frame.status = "failed"; frame.error = errorText(error); }
        attemptedFrames++;
        if (attemptedFrames % 40 === 0) console.log(JSON.stringify({ attempted_frames: attemptedFrames, requested: 376 }));
      }
      asset.status = requested.every(frame => frame.status === "ok") ? "captured" : "capture_failed";
    } catch (error) {
      asset.status = "load_failed"; asset.error = errorText(error);
      for (const frame of requested) if (frame.status === "pending") { frame.status = "failed"; frame.error = asset.error; attemptedFrames++; }
    }
    console.log(JSON.stringify({ asset: asset.asset_id, status: asset.status, attempted_frames: attemptedFrames, requested: 376 }));
  }
  await bounded(page.evaluate(() => window.renderDomain.close()), 10_000, "Viewer dispose");
  for (const pin of [studyPlanPin, ...plan.inputs]) await readPinned(pin, MAX_METADATA);
  for (const pin of assetPins.values()) await readPinned(pin, pin.path.endsWith(".glb") ? MAX_GLB : MAX_PNG);
  report.input_integrity = "passed";
  assert.equal(interrupted, false); assert.deepEqual(externalRequests, []); assert.deepEqual(browserErrors, []);
  assert.equal(frames.filter(frame => frame.status === "ok").length, 376, "All requested captures must succeed.");
  report.status = "passed";
} catch (error) {
  failure = error; report.status = "failed"; report.error = errorText(error);
} finally {
  if (page && !page.isClosed()) await bounded(page.evaluate(() => window.renderDomain?.close()), 5_000, "Final viewer dispose").catch(error => { report.viewer_cleanup_error = errorText(error); });
  const cleanup = await Promise.allSettled([
    browser ? bounded(browser.close(), 15_000, "Browser close") : undefined,
    vite ? bounded(vite.close(), 10_000, "Vite close") : undefined,
    server.listening ? bounded(new Promise((done, reject) => { server.close(error => error ? reject(error) : done()); server.closeAllConnections(); }), 10_000, "Asset server close") : undefined,
  ]);
  report.cleanup = cleanup.map((value, index) => ({ resource: ["browser", "vite", "assets"][index], status: value.status,
    ...(value.status === "rejected" ? { error: errorText(value.reason) } : {}) }));
  report.owned_servers_closed = cleanup.every(value => value.status === "fulfilled") && !server.listening && !vite?.httpServer?.listening;
  report.browser_closed = !browser?.isConnected();
  if (!report.owned_servers_closed || !report.browser_closed || report.viewer_cleanup_error) {
    failure ??= new Error("Owned resource cleanup did not complete."); report.status = "failed";
  }
  for (const frame of frames) if (frame.status === "pending") { frame.status = "not_captured"; frame.error = "Capture terminated before this request."; }
  report.frame_counts = { requested: 376, captured: frames.filter(frame => frame.status === "ok").length, failed: frames.filter(frame => frame.status !== "ok").length };
  report.external_requests = externalRequests; report.browser_errors = browserErrors;
  report.asset_requests = assetRequests; report.interrupted = interrupted; report.finished_at_utc = new Date().toISOString();
  await writeFile(resolve(output, "render-capture.json"), `${JSON.stringify(report, null, 2)}\n`, { flag: "wx" });
  process.removeListener("SIGINT", interrupt); process.removeListener("SIGTERM", interrupt);
}
if (failure) throw failure;
console.log(JSON.stringify({ status: report.status, ...report.frame_counts, paired_requests: 296, owned_servers_closed: report.owned_servers_closed, output }));

async function addAsset(row, description) {
  identifier(description.asset_id); assert.equal(assets.some(asset => asset.asset_id === description.asset_id), false);
  const glbPin = row.artifacts.glb, atlasPin = row.artifacts.atlas;
  for (const pin of [glbPin, atlasPin]) { assert.equal(assetPins.has(pin.path), false); assetPins.set(pin.path, pin); }
  const bytes = await readPinned(glbPin, MAX_GLB), atlas = await readPinned(atlasPin, MAX_PNG);
  const document = inspectGlb(bytes, atlas, row.source_frame);
  const invariants = registration.value.source_geometry_invariants[description.source_id];
  assert.deepEqual(document.geometry, invariants);
  const asset_url = `/api/assets/render-domain/${description.asset_id}.glb`;
  assert.equal(payloads.has(asset_url), false); payloads.set(asset_url, bytes);
  assets.push({ ...description, status: "pending", asset_url, glb: glbPin, atlas: atlasPin,
    topology_id: document.topology_id, expected_geometry: invariants,
    source_frame: row.source_frame, atlas_dimensions: pngDimensions(atlas),
    texture_coverage_metadata: row.texture_metadata ?? null });
}

function inspectGlb(bytes, atlas, sourceFrame) {
  assert.equal(bytes.toString("ascii", 0, 4), "glTF"); assert.equal(bytes.readUInt32LE(4), 2); assert.equal(bytes.readUInt32LE(8), bytes.length);
  const length = bytes.readUInt32LE(12); assert.equal(bytes.toString("ascii", 16, 20), "JSON");
  const binaryStart = 28 + length;
  assert.equal(bytes.toString("ascii", 24 + length, 28 + length), "BIN\0");
  const binary = bytes.subarray(binaryStart); assert.equal(bytes.readUInt32LE(20 + length), binary.length);
  const document = json(bytes.subarray(20, 20 + length));
  assert.deepEqual(document.extras.source_age, UNKNOWN); assert.equal(document.extras.asset_mode, "static");
  assert.deepEqual(document.extras.coordinate_metadata, sourceFrame);
  assert.equal(document.meshes.length, 1); assert.equal(document.meshes[0].primitives.length, 1);
  assert.equal(document.animations?.length ?? 0, 0); assert.equal(document.skins?.length ?? 0, 0);
  assert.ok([...document.images, ...document.buffers].every(row => row.uri === undefined));
  const primitive = document.meshes[0].primitives[0]; assert.equal(primitive.targets, undefined);
  const material = document.materials[primitive.material];
  assert.equal(material.alphaMode, "MASK"); assert.equal(material.alphaCutoff, 0.5);
  const geometry = {};
  for (const [name, accessorIndex] of Object.entries({ position: primitive.attributes.POSITION, normal: primitive.attributes.NORMAL, uv: primitive.attributes.TEXCOORD_0, index: primitive.indices })) {
    const accessor = document.accessors[accessorIndex], view = document.bufferViews[accessor.bufferView];
    const components = name === "uv" ? 2 : name === "index" ? 1 : 3;
    assert.equal(accessor.componentType, name === "index" ? 5125 : 5126);
    assert.equal(accessor.type, name === "index" ? "SCALAR" : name === "uv" ? "VEC2" : "VEC3");
    assert.equal(accessor.sparse, undefined); assert.ok(!view.byteStride || view.byteStride === components * 4);
    const start = (view.byteOffset ?? 0) + (accessor.byteOffset ?? 0), size = accessor.count * components * 4;
    assert.ok(Number.isSafeInteger(size) && size > 0 && start >= 0 && start + size <= binary.length);
    geometry[GEOMETRY[name]] = hash(binary.subarray(start, start + size));
  }
  assert.equal(document.images.length, 1); assert.equal(document.images[0].mimeType, "image/png");
  const imageView = document.bufferViews[document.images[0].bufferView];
  assert.deepEqual(binary.subarray(imageView.byteOffset ?? 0, (imageView.byteOffset ?? 0) + imageView.byteLength), atlas);
  return { geometry, topology_id: document.extras.topology_id };
}

async function installCapture() {
  const { FaceViewer, THREE } = await import("/__render_domain_modules.js");
  const viewer = new FaceViewer(document.getElementById("viewer"));
  let asset, initialMaps, disposed = false;
  const digest = async bytes => [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map(value => value.toString(16).padStart(2, "0")).join("");
  const hashArray = array => digest(new Uint8Array(array.buffer, array.byteOffset, array.byteLength));
  const materials = () => viewer.bindings.flatMap(binding => Array.isArray(binding.material) ? binding.material : [binding.material]);
  const flags = mode => ({ transparent: mode === "BLEND", alphaTest: mode === "MASK" ? 0.5 : 0, depthWrite: mode === "MASK", premultipliedAlpha: false, opacity: 1 });
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  const fail = message => { throw new Error(message); };
  const geometry = async () => {
    if (viewer.bindings.length !== 1) fail("Expected one source-static mesh.");
    const mesh = viewer.bindings[0].mesh, result = {};
    for (const [attribute, key] of [["position", "source_positions_sha256"], ["normal", "source_normals_sha256"], ["uv", "gltf_uv_sha256"]]) {
      const entry = mesh.geometry.getAttribute(attribute); if (!entry) fail(`Missing ${attribute}.`);
      result[key] = await hashArray(entry.array);
    }
    if (!mesh.geometry.index) fail("Missing ordered source indices.");
    result.source_indices_sha256 = await hashArray(mesh.geometry.index.array);
    if (!same(result, asset.expected_geometry)) {
      // Compare names explicitly because JSON property insertion order is irrelevant.
      for (const [key, expected] of Object.entries(asset.expected_geometry)) if (result[key] !== expected) fail(`Changed ${key}.`);
    }
    return result;
  };
  const invariantState = () => {
    viewer.scene.updateMatrixWorld(true); viewer.camera.updateMatrixWorld(true);
    return {
      camera: { position: viewer.camera.position.toArray(), quaternion: viewer.camera.quaternion.toArray(), target: viewer.controls.target.toArray(),
        fov: viewer.camera.fov, aspect: viewer.camera.aspect, near: viewer.camera.near, far: viewer.camera.far, projection: viewer.camera.projectionMatrix.toArray() },
      transforms: viewer.bindings.map(binding => ({ local: binding.mesh.matrix.toArray(), world: binding.mesh.matrixWorld.toArray() })),
      materials: materials().map(material => ({ type: material.type, side: material.side, roughness: material.roughness ?? null, metalness: material.metalness ?? null,
        color: material.color?.toArray() ?? null, transparent: material.transparent, alphaTest: material.alphaTest,
        depthWrite: material.depthWrite, premultipliedAlpha: material.premultipliedAlpha, opacity: material.opacity,
        map: material.map && { colorSpace: material.map.colorSpace, channel: material.map.channel, magFilter: material.map.magFilter,
          minFilter: material.map.minFilter, wrapS: material.map.wrapS, wrapT: material.map.wrapT, flipY: material.map.flipY,
          anisotropy: material.map.anisotropy, generateMipmaps: material.map.generateMipmaps, offset: material.map.offset.toArray(),
          repeat: material.map.repeat.toArray(), center: material.map.center.toArray(), rotation: material.map.rotation,
          matrix: material.map.matrix.toArray() } })),
      renderer: { colorSpace: viewer.renderer.outputColorSpace, toneMapping: viewer.renderer.toneMapping, exposure: viewer.renderer.toneMappingExposure,
        drawing_size: viewer.renderer.getDrawingBufferSize(new THREE.Vector2()).toArray(), pixel_ratio: viewer.renderer.getPixelRatio() },
      lighting: [viewer.key, viewer.fill, viewer.rim, viewer.ambient].map(light => ({ type: light.type, intensity: light.intensity, color: light.color.toArray(),
        groundColor: light.groundColor?.toArray() ?? null, position: light.position.toArray() })),
      fog: { color: viewer.scene.fog.color.toArray(), near: viewer.scene.fog.near, far: viewer.scene.fog.far },
      background: viewer.scene.background.toArray(),
      grid: viewer.grid.visible, compare: viewer.compare, auto_rotate: viewer.controls.autoRotate, damping: viewer.controls.enableDamping,
    };
  };
  window.renderDomain = {
    async load(next) {
      asset = next;
      await viewer.loadModel(asset.url, { asset_mode: "static", topology_id: asset.topology_id,
        source_age: { value: null, method: "unknown", calibration_id: null }, capabilities: { age_morph: false, age_texture: false } });
      viewer.setAutoRotate(false); viewer.controls.enableDamping = false; viewer.controls.update();
      viewer.setLighting("studio"); viewer.setMode("solid"); viewer.setCompare(false); viewer.setBackground(false); viewer.setView("front");
      await new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done)));
      if (!same(viewer.model.userData.source_age, { value: null, method: "unknown", calibration_id: null })) fail("An invented source age entered the viewer.");
      initialMaps = materials().map(material => material.map);
      for (const material of materials()) {
        if (!(material instanceof THREE.MeshStandardMaterial)) fail("Unexpected source material type.");
        for (const [key, value] of Object.entries(flags("MASK"))) if (material[key] !== value) fail(`Native MASK ${key} differs.`);
        if (!material.map || material.map.image.width !== asset.atlas_dimensions[0] || material.map.image.height !== asset.atlas_dimensions[1]) fail("Loaded atlas dimensions differ.");
      }
      return { geometry: await geometry(), invariants: invariantState(), api_source_age: viewer.model.userData.source_age };
    },
    async capture(configuration) {
      if (!asset || disposed) fail("No active research asset.");
      for (const [index, material] of materials().entries()) {
        if (material.map !== initialMaps[index]) fail("Capture replaced the original GLB map.");
        Object.assign(material, flags(configuration.material_mode)); material.needsUpdate = true;
      }
      viewer.controls.enableDamping = false; viewer.controls.update(); viewer.setView(configuration.view);
      viewer.scene.background = new THREE.Color(configuration.background);
      await new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done)));
      const expectedPosition = configuration.view === "front" ? [0, 0.03, 4.9] : [4.9, 0.03, 0];
      if (viewer.camera.position.toArray().some((value, index) => Math.abs(value - expectedPosition[index]) > 1e-9)) fail("Capture camera position differs.");
      if (viewer.controls.target.toArray().some((value, index) => Math.abs(value - [0, -0.05, 0][index]) > 1e-9)) fail("Capture camera target differs.");
      const geometryBefore = await geometry();
      const blob = await viewer.exportPNG();
      const bytes = new Uint8Array(await blob.arrayBuffer());
      const geometryAfter = await geometry();
      if (!same(geometryBefore, geometryAfter)) fail("Geometry changed during PNG capture.");
      const invariants = invariantState();
      if (!same(invariants.renderer.drawing_size, [1024, 1024]) || invariants.renderer.pixel_ratio !== 1 || invariants.camera.aspect !== 1) fail("Capture raster changed.");
      let binary = ""; for (let offset = 0; offset < bytes.length; offset += 32768) binary += String.fromCharCode(...bytes.subarray(offset, offset + 32768));
      return { png_base64: btoa(binary), png_sha256: await digest(bytes), geometry: geometryAfter, invariants };
    },
    close() { if (!disposed) { viewer.dispose(); disposed = true; } if (document.querySelectorAll("#viewer canvas").length) fail("Viewer canvas was not released."); },
  };
  const gl = viewer.renderer.getContext();
  const debug = gl.getExtension("WEBGL_debug_renderer_info");
  return { three_revision: THREE.REVISION, renderer: gl.getParameter(gl.RENDERER), vendor: gl.getParameter(gl.VENDOR), version: gl.getParameter(gl.VERSION),
    unmasked_renderer: debug ? gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) : null,
    unmasked_vendor: debug ? gl.getParameter(debug.UNMASKED_VENDOR_WEBGL) : null,
    device_pixel_ratio: window.devicePixelRatio, drawing_size: viewer.renderer.getDrawingBufferSize(new THREE.Vector2()).toArray() };
}

function validatePolicy(value) {
  assert.equal(value.schema_version, 1); assert.equal(value.protocol_id, PROTOCOL);
  assert.equal(value.observations.render_domain_model_scores_seen_before_freeze, false);
  assert.equal(value.flags.research_only, true);
  for (const [key, flag] of Object.entries(value.flags)) if (key !== "research_only") assert.equal(flag, false);
  const capture = value.capture;
  assert.equal(capture.browser_channel, "chrome"); assert.equal(capture.headless, true);
  assert.deepEqual(capture.browser_args, ["--enable-unsafe-swiftshader", "--use-angle=swiftshader"]);
  assert.equal(capture.width, 1024); assert.equal(capture.height, 1024); assert.equal(capture.device_scale_factor, 1);
  assert.deepEqual(capture.views, ["front", "side"]); assert.deepEqual(capture.backgrounds, ["black", "white"]);
  assert.deepEqual(capture.material_modes, ["MASK", "BLEND"]);
  assert.equal(value.cohort.original_assets, 10); assert.equal(value.cohort.sam_assets, 37);
  assert.equal(value.cohort.unique_frames, 376); assert.equal(value.cohort.paired_comparisons, 296);
  assert.equal(value.cohort.held_out_inference, false); assert.equal(value.cohort.baseline_target_age, null);
}
function findDocument(id, role) {
  const matches = documents.filter(row => row.value.protocol_id === id);
  assert.equal(matches.length, 1, `Freeze exactly one ${role}.`);
  if (plan[role]) assert.deepEqual(plan[role], matches[0].pin);
  return matches[0];
}
function descriptive(asset) { return Object.fromEntries(["asset_id", "source_id", "sample_id", "role", "source_age_label", "target_age", "category"].map(key => [key, asset[key]])); }
function assertPairedInvariants(actual, expected) {
  assert.ok(expected, "The paired original-source configuration was not captured.");
  const { camera: actualCamera, ...actualState } = actual;
  const { camera: expectedCamera, ...expectedState } = expected;
  assert.deepEqual(actualState, expectedState, "Paired source/target world transforms, material, map, lighting or background differ.");
  const compare = (left, right) => {
    if (typeof left === "number" && typeof right === "number") {
      assert.ok(Number.isFinite(left) && Number.isFinite(right) && Math.abs(left - right) <= 1e-9, "Paired camera values differ.");
    } else if (Array.isArray(left) && Array.isArray(right)) {
      assert.equal(left.length, right.length); left.forEach((value, index) => compare(value, right[index]));
    } else if (left && right && typeof left === "object" && typeof right === "object") {
      assert.deepEqual(Object.keys(left).sort(), Object.keys(right).sort());
      for (const key of Object.keys(left)) compare(left[key], right[key]);
    } else assert.deepEqual(left, right);
  };
  compare(actualCamera, expectedCamera);
}
function configId(configuration) { return `${configuration.material_mode}/${configuration.view}/${configuration.background}`; }
function identifier(value) { assert.match(value, /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,180}$/); }
function label(value) { assert.ok(value === null || Number.isInteger(value) && value >= 20 && value <= 70); }
function pinOnly(value) { return Object.fromEntries(["path", "bytes", "sha256"].map(key => [key, value[key]])); }
function pngDimensions(bytes) {
  assert.ok(bytes.length >= 33); assert.equal(bytes.subarray(0, 8).toString("hex"), "89504e470d0a1a0a"); assert.equal(bytes.toString("ascii", 12, 16), "IHDR");
  const dimensions = [bytes.readUInt32BE(16), bytes.readUInt32BE(20)];
  assert.ok(dimensions.every(value => value > 0) && dimensions[0] * dimensions[1] <= 16_000_000); return dimensions;
}
function json(raw) { const value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw)); assert.ok(value && typeof value === "object" && !Array.isArray(value)); return value; }
function hash(bytes) { return createHash("sha256").update(bytes).digest("hex"); }
function pinBytes(path, bytes) { return { path: repoRelative(path), bytes: bytes.length, sha256: hash(bytes) }; }
function repoRelative(path) { return relative(root, path).replaceAll("\\", "/"); }
function isContained(path) { const name = relative(root, path); return !!name && !name.startsWith("..") && !isAbsolute(name); }
function contained(value) { assert.ok(typeof value === "string" && value.length > 0); const path = resolve(root, value); assert.ok(isContained(path)); return path; }
async function existing(value) { const path = await realpath(contained(value)); assert.ok(isContained(path)); return path; }
async function boundedRead(path, maximum) {
  const file = await open(path, "r"), chunks = []; let count = 0;
  try {
    for (;;) {
      const buffer = Buffer.alloc(Math.min(65536, maximum + 1 - count));
      const result = await file.read(buffer, 0, buffer.length, null);
      if (!result.bytesRead) break;
      count += result.bytesRead; assert.ok(count <= maximum, "Input exceeds its resource bound."); chunks.push(buffer.subarray(0, result.bytesRead));
    }
  } finally { await file.close(); }
  assert.ok(count > 0); return Buffer.concat(chunks, count);
}
async function readPinned(pin, maximum) {
  assert.ok(pin && Object.keys(pin).sort().join() === "bytes,path,sha256"); assert.match(pin.sha256, /^[a-f0-9]{64}$/);
  assert.ok(Number.isInteger(pin.bytes) && pin.bytes > 0 && pin.bytes <= maximum);
  assert.equal(typeof pin.path, "string"); assert.ok(!pin.path.includes("\\") && !pin.path.includes(":") && !pin.path.split("/").some(part => !part || part === "." || part === ".."));
  const path = await existing(pin.path); assert.equal(repoRelative(path), pin.path);
  const raw = await boundedRead(path, pin.bytes); assert.deepEqual(pinBytes(path, raw), pin); return raw;
}
function errorText(error) { return error instanceof Error ? error.stack ?? error.message : String(error); }
async function bounded(promise, milliseconds, name) {
  let timer;
  try { return await Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`${name} exceeded ${milliseconds} ms.`)), milliseconds); })]); }
  finally { clearTimeout(timer); }
}
