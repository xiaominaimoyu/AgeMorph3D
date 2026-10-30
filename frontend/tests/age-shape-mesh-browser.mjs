import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { dirname, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";
import { createServer } from "vite";

// Explicit, isolated research capture. Never starts an inference or production API.
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const args = Object.fromEntries(process.argv.slice(2).map(value => value.split("=", 2)));
const INPUT = args["--report"], OUTPUT = args["--output-dir"];
assert.ok(INPUT?.startsWith("output/research/") && OUTPUT?.startsWith("output/research/"));
const inside = name => { const path = resolve(ROOT, name); assert.ok(relative(ROOT, path) && !relative(ROOT, path).startsWith("..")); return path; };
const sha = bytes => createHash("sha256").update(bytes).digest("hex");
const inputBody = await readFile(inside(INPUT)); assert.ok(inputBody.length <= 24 * 1024 ** 2);
const study = JSON.parse(inputBody);
assert.equal(study.protocol_id, "agemorph3d-age-shape-mesh-v1");
assert.equal(study.research_only, true); assert.equal(study.g3_complete, false);
assert.equal(study.mesh_count, 100); assert.equal(study.assets.length, 100);
const payloads = new Map(), expected = new Map();
for (const asset of study.assets) {
  const bytes = await readFile(inside(asset.artifact.path));
  assert.equal(bytes.length, asset.artifact.bytes); assert.equal(sha(bytes), asset.artifact.sha256);
  payloads.set(asset.asset_id, bytes); expected.set(asset.asset_id, inspect(bytes));
}
const sourceNames = [INPUT, relative(ROOT, fileURLToPath(import.meta.url)).replaceAll("\\", "/"),
  "frontend/package.json", "frontend/package-lock.json", "frontend/node_modules/three/package.json",
  "frontend/node_modules/three/build/three.module.js", "frontend/node_modules/three/build/three.core.js",
  "frontend/node_modules/three/examples/jsm/loaders/GLTFLoader.js",
  "frontend/node_modules/three/examples/jsm/exporters/GLTFExporter.js",
  "frontend/node_modules/three/examples/jsm/controls/OrbitControls.js"];
for (const entry of await readdir(resolve(ROOT, "frontend/src"), { withFileTypes: true })) if (entry.isFile()) sourceNames.push(`frontend/src/${entry.name}`);
const frozen = [];
for (const name of sourceNames) { const bytes = await readFile(inside(name)); frozen.push({ path: name, bytes: bytes.length, sha256: sha(bytes) }); }
const out = inside(OUTPUT); await mkdir(out); // fresh only
await writeFile(resolve(out, "harness.frozen.mjs"), await readFile(fileURLToPath(import.meta.url)), { flag: "wx" });
const plan = { scope: "Frozen neutral GLBs through unchanged FaceViewer; shared source display transform; no live-service qualification",
  sources: frozen, mesh_inputs: study.assets.map(a => a.artifact), channels: ["chrome", "msedge"],
  viewport: [768, 768], device_scale_factor: 1, views: ["front", "side"], material: "solid native neutral",
  background: "#101624", lighting: "studio", node: process.version,
  args: ["--enable-unsafe-swiftshader", "--use-angle=swiftshader"],
  roundtrip: "Unchanged FaceViewer exportGLB then actual GLTFLoader reimport; local positions/index exact, normals absolute tolerance 2e-7; not a second viewer raster acceptance",
  research_only: true, human_review_completed: false, g3_complete: false };
await writeFile(resolve(out, "capture-plan.json"), JSON.stringify(plan, null, 2) + "\n", { flag: "wx" });
const result = { status: "running", research_only: true, human_review_completed: false, quality_accepted: false,
  g3_complete: false, plan, browsers: [], external_requests: [], errors: [], output_bytes: 0 };
const save = () => writeFile(resolve(out, "capture-report.json"), JSON.stringify(result, null, 2) + "\n");
let server, browser, page;
const bounded = async (promise, ms, label) => { let timer; try { return await Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`${label} timed out`)), ms); })]); } finally { clearTimeout(timer); } };
const store = async (name, bytes) => {
  assert.ok(name === name.split(/[\\/]/).at(-1)); result.output_bytes += bytes.length;
  assert.ok(result.output_bytes <= 512 * 1024 ** 2, "Capture output byte budget");
  await writeFile(resolve(out, name), bytes, { flag: "wx" }); return { path: `${OUTPUT}/${name}`, bytes: bytes.length, sha256: sha(bytes) };
};
try {
  server = await createServer({ root: resolve(ROOT, "frontend"), configFile: false,
    server: { host: "127.0.0.1", port: 0, strictPort: true, open: false, hmr: false },
    plugins: [{ name: "age-shape-mesh-research",
      resolveId(id) { if (id === "/__shape_modules.js") return "\0shape-modules"; },
      load(id) { if (id === "\0shape-modules") return "export {FaceViewer} from '/src/viewer.ts'; export * as THREE from 'three'; export {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';"; },
      configureServer(instance) { instance.middlewares.use((req, res, next) => {
        if (req.url?.split("?")[0] !== "/__shape") return next();
        res.setHeader("Content-Type", "text/html; charset=utf-8");
        res.end('<!doctype html><html><meta charset="utf-8"><link rel="icon" href="data:,"><style>html,body{margin:0;width:768px;height:768px;overflow:hidden}#viewer{width:768px;height:768px}</style><div id="viewer"></div></html>');
      }); },
    }],
  });
  await bounded(server.listen(), 20_000, "Vite listen");
  const origin = `http://127.0.0.1:${server.httpServer.address().port}`; result.origin = origin;
  const order = { neutral_source: 0, reconstructed_neutral_target_reference: 1, bfm_direction_refit: 2, identity_centered_ridge: 3 };
  const assets = [...study.assets].sort((a, b) => `${a.source_id}/${a.target_id}`.localeCompare(`${b.source_id}/${b.target_id}`) || order[a.role] - order[b.role]);
  for (const channel of plan.channels) {
    browser = await chromium.launch({ channel, headless: true, args: plan.args, timeout: 30_000 });
    const context = await browser.newContext({ viewport: { width: 768, height: 768 }, deviceScaleFactor: 1, locale: "zh-CN", serviceWorkers: "block" });
    await context.route("**/*", route => { const url = new URL(route.request().url());
      if (["http:", "https:"].includes(url.protocol) && url.origin !== origin) { result.external_requests.push(url.href); return route.abort(); }
      return route.continue(); });
    page = await context.newPage();
    const entry = { channel, version: browser.version(), assets: [], errors: [], failed_requests: [], viewer_disposed: false, browser_closed: false };
    result.browsers.push(entry);
    page.on("pageerror", error => entry.errors.push(String(error)));
    page.on("console", message => { if (message.type() === "error") entry.errors.push(message.text()); });
    page.on("requestfailed", request => entry.failed_requests.push({ url: request.url(), error: request.failure()?.errorText }));
    await page.goto(origin + "/__shape");
    entry.runtime = await bounded(page.evaluate(install), 30_000, "Viewer initialization");
    for (const asset of assets) {
      const response = await bounded(page.evaluate(async ({ asset, base64 }) => window.shapeStudy.capture(asset, base64),
        { asset, base64: payloads.get(asset.asset_id).toString("base64") }), 60_000, asset.asset_id);
      assert.deepEqual(response.loaded, expected.get(asset.asset_id));
      const frames = [];
      for (const frame of response.frames) {
        const bytes = Buffer.from(frame.base64, "base64");
        assert.equal(bytes.readUInt32BE(16), 768); assert.equal(bytes.readUInt32BE(20), 768);
        frames.push({ view: frame.view, image: await store(`${channel}--${asset.asset_id}--${frame.view}.png`, bytes), camera: frame.camera });
      }
      const exported = Buffer.from(response.glb_base64, "base64");
      const roundtrip = inspect(exported);
      assert.equal(roundtrip.position, response.loaded.position); assert.equal(roundtrip.index, response.loaded.index);
      entry.assets.push({ asset_id: asset.asset_id, source_id: asset.source_id, target_id: asset.target_id, role: asset.role,
        frames, loaded: response.loaded, transform: response.transform,
        exported: await store(`${channel}--${asset.asset_id}--export.glb`, exported),
        reimport: response.reimport, exported_geometry: roundtrip });
      if (entry.assets.length % 20 === 0) { console.log(JSON.stringify({ channel, captured_assets: entry.assets.length })); await save(); }
    }
    assert.equal(entry.assets.length, 100); assert.deepEqual(entry.errors, []); assert.deepEqual(entry.failed_requests, []);
    await page.evaluate(() => window.shapeStudy.close()); entry.viewer_disposed = true;
    await context.close(); await browser.close(); browser = null; page = null; entry.browser_closed = true; await save();
  }
  for (const p of frozen) { const bytes = await readFile(inside(p.path)); assert.equal(bytes.length, p.bytes); assert.equal(sha(bytes), p.sha256); }
  for (const asset of study.assets) assert.equal(sha(await readFile(inside(asset.artifact.path))), asset.artifact.sha256);
  assert.deepEqual(result.external_requests, []); result.inputs_unchanged = true; result.status = "passed";
} catch (error) { result.status = "failed"; result.errors.push(String(error.stack ?? error)); }
finally {
  if (page && !page.isClosed()) await bounded(page.evaluate(() => window.shapeStudy?.close()), 5000, "Final viewer cleanup").catch(error => result.errors.push(String(error)));
  if (browser) await bounded(browser.close(), 15_000, "Browser close").catch(error => result.errors.push(String(error)));
  if (server) await bounded(server.close(), 10_000, "Vite close").catch(error => result.errors.push(String(error)));
  result.server_closed = !server?.httpServer?.listening; result.browser_closed = !browser?.isConnected();
  if (!result.server_closed || !result.browser_closed || result.errors.length) result.status = "failed";
  await save();
}
console.log(JSON.stringify({ status: result.status, browsers: result.browsers.map(b => ({ channel: b.channel, assets: b.assets.length })), server_closed: result.server_closed }));
if (result.status !== "passed") throw new Error(result.errors.join("\n"));

function inspect(bytes) {
  assert.equal(bytes.toString("ascii", 0, 4), "glTF"); assert.equal(bytes.readUInt32LE(4), 2); assert.equal(bytes.readUInt32LE(8), bytes.length);
  const length = bytes.readUInt32LE(12), doc = JSON.parse(bytes.subarray(20, 20 + length)), binary = bytes.subarray(28 + length);
  assert.equal(bytes.toString("ascii", 16, 20), "JSON"); assert.equal(bytes.toString("ascii", 24 + length, 28 + length), "BIN\0");
  assert.ok(doc.buffers.every(b => b.uri === undefined)); assert.equal(doc.images?.length ?? 0, 0);
  assert.equal(doc.animations?.length ?? 0, 0); assert.equal(doc.meshes.length, 1);
  const primitive = doc.meshes[0].primitives[0]; assert.equal(primitive.targets, undefined);
  const output = {};
  for (const [name, i] of [["position", primitive.attributes.POSITION], ["normal", primitive.attributes.NORMAL], ["index", primitive.indices]]) {
    const accessor = doc.accessors[i], view = doc.bufferViews[accessor.bufferView];
    assert.equal(accessor.componentType, name === "index" ? 5125 : 5126);
    assert.equal(view.byteStride ?? (name === "index" ? 4 : 12), name === "index" ? 4 : 12);
    const start = (view.byteOffset ?? 0) + (accessor.byteOffset ?? 0), size = accessor.count * (name === "index" ? 1 : 3) * 4;
    assert.ok(start >= 0 && start + size <= binary.length); output[name] = sha(binary.subarray(start, start + size));
  }
  return output;
}

async function install() {
  const { FaceViewer, THREE, GLTFLoader } = await import("/__shape_modules.js");
  const viewer = new FaceViewer(document.getElementById("viewer"), {}, { initialDemo: false });
  viewer.setAutoRotate(false); viewer.setCompare(false); viewer.setMode("solid"); viewer.setLighting("studio"); viewer.setBackground(false);
  viewer.controls.enableDamping = false; viewer.scene.background = new THREE.Color("#101624");
  const transforms = new Map(); let disposed = false;
  const unknown = { value: null, method: "unknown", calibration_id: null };
  const digest = async array => [...new Uint8Array(await crypto.subtle.digest("SHA-256", new Uint8Array(array.buffer, array.byteOffset, array.byteLength)))].map(b => b.toString(16).padStart(2, "0")).join("");
  const encode = bytes => { let value = ""; for (let i = 0; i < bytes.length; i += 32768) value += String.fromCharCode(...bytes.subarray(i, i + 32768)); return btoa(value); };
  const fingerprint = async mesh => ({ position: await digest(mesh.geometry.getAttribute("position").array), normal: await digest(mesh.geometry.getAttribute("normal").array), index: await digest(mesh.geometry.index.array) });
  const fail = text => { throw new Error(text); };
  window.shapeStudy = {
    async capture(asset, base64) {
      const bytes = Uint8Array.from(atob(base64), c => c.charCodeAt(0));
      await viewer.loadResearchModelBytes(bytes.buffer, { asset_mode: "static", source_age: unknown, topology_id: asset.topology_id, capabilities: { age_morph: false, age_texture: false } });
      if (viewer.bindings.length !== 1 || JSON.stringify(viewer.model.userData.source_age) !== JSON.stringify(unknown)) fail("Mesh/source age contract changed.");
      const mesh = viewer.bindings[0].mesh, loaded = await fingerprint(mesh), pair = `${asset.source_id}/${asset.target_id}`;
      const normalization = viewer.model.getObjectByName("Asset_Normalization"), scene = normalization.children[0];
      if (asset.role === "neutral_source") transforms.set(pair, { scale: normalization.scale.toArray(), position: scene.position.toArray() });
      const transform = transforms.get(pair); if (!transform) fail("Missing original source display frame.");
      normalization.scale.fromArray(transform.scale); scene.position.fromArray(transform.position); viewer.scene.updateMatrixWorld(true);
      const frames = [];
      for (const view of ["front", "side"]) {
        viewer.setView(view); viewer.controls.update();
        const wanted = view === "front" ? [0, .03, 4.9] : [4.9, .03, 0];
        if (viewer.camera.position.toArray().some((x, i) => Math.abs(x - wanted[i]) > 1e-9)) fail("Camera changed.");
        const blob = await viewer.exportPNG(); frames.push({ view, base64: encode(new Uint8Array(await blob.arrayBuffer())),
          camera: { position: viewer.camera.position.toArray(), target: viewer.controls.target.toArray(), projection: viewer.camera.projectionMatrix.toArray() } });
      }
      const blob = await viewer.exportGLB(), exported = await blob.arrayBuffer();
      const roundtrip = await new GLTFLoader().parseAsync(exported, "");
      const meshes = []; roundtrip.scene.traverse(n => { if (n.isMesh) meshes.push(n); });
      if (meshes.length !== 1) fail("Roundtrip mesh count changed.");
      const reimport = await fingerprint(meshes[0]);
      if (reimport.position !== loaded.position || reimport.index !== loaded.index) fail("Roundtrip positions or index changed.");
      const a = mesh.geometry.getAttribute("normal").array, b = meshes[0].geometry.getAttribute("normal").array;
      if (a.length !== b.length) fail("Roundtrip normal dimension changed.");
      let maxNormalDelta = 0; for (let i = 0; i < a.length; i++) maxNormalDelta = Math.max(maxNormalDelta, Math.abs(a[i] - b[i]));
      if (maxNormalDelta > 2e-7) fail("Roundtrip normals changed beyond numeric tolerance.");
      roundtrip.scene.traverse(n => { if (n.isMesh) { n.geometry.dispose(); for (const m of Array.isArray(n.material) ? n.material : [n.material]) m.dispose(); } });
      if (JSON.stringify(await fingerprint(mesh)) !== JSON.stringify(loaded)) fail("Capture/export changed source geometry.");
      return { loaded, frames, transform, glb_base64: encode(new Uint8Array(exported)), reimport: { ...reimport, max_normal_delta: maxNormalDelta } };
    },
    close() { if (!disposed) { viewer.dispose(); disposed = true; } if (document.querySelector("#viewer canvas")) fail("Viewer canvas retained."); },
  };
  const gl = viewer.renderer.getContext(), ext = gl.getExtension("WEBGL_debug_renderer_info");
  return { three_revision: THREE.REVISION, renderer: gl.getParameter(gl.RENDERER), unmasked_renderer: ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : null, pixel_ratio: viewer.renderer.getPixelRatio() };
}
