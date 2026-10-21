import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import { createWriteStream } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { connect } from "node:net";
import { delimiter, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium, expect } from "@playwright/test";
import { createServer } from "vite";

// Real browsers and real LocalApi/FaceViewer, backed exclusively by a test factory.
// No SAM, user portraits, production capability switches or G3 acceptance occur.
const repository = fileURLToPath(new URL("../../", import.meta.url));
const frontendPort = port("AGEMORPH_CONTRACT_VITE_PORT", 5177);
const backendPort = port("AGEMORPH_CONTRACT_API_PORT", 18007);
assert.notEqual(frontendPort, backendPort);
const frontend = `http://127.0.0.1:${frontendPort}`;
const backend = `http://127.0.0.1:${backendPort}`;
const nonce = randomBytes(24).toString("hex");
const output = resolve(process.env.AGEMORPH_CONTRACT_OUTPUT ??
  join(repository, "output/research/age-stage5-20261021/synthetic-browser"));
const rel = relative(repository, output);
assert.ok(rel && !rel.startsWith("..") && !/^[A-Za-z]:/.test(rel), "Output must stay in the repository.");
await mkdir(resolve(output, ".."), { recursive: true });
await mkdir(output); // Preserve existing evidence.
const python = process.env.AGEMORPH_CONTRACT_PYTHON ?? join(repository, "backend/.venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const report = {
  schema_version: 1, evidenceKind: "synthetic-aging-session-browser-contract",
  syntheticOnly: true, samInference: false, realModelInference: false,
  ageQualityAccepted: false, identityQualityAccepted: false, g3Accepted: false,
  productionCapabilityChanged: false, routeMocks: false,
  renderer: "Chromium software WebGL (SwiftShader)", startedAt: new Date().toISOString(),
  requestedBrowsers: ["chrome", "msedge"], results: [], status: "running", inputs: [],
};
for (const name of ["backend/src/agemorph3d/aging_sessions.py",
  "backend/tests/fixtures/aging_contract_app.py", "frontend/tests/aging-session-contract.mjs",
  "frontend/src/services.ts", "frontend/src/viewer.ts"]) {
  const data = await readFile(join(repository, name));
  report.inputs.push({ path: name, sha256: hash(data), bytes: data.length });
}
let child, vite, browser, failure, actualFixturePid, childClosed = false, interrupted = false;
const interrupt = () => {
  interrupted = true;
  browser?.close().catch(() => {});
};
process.once("SIGINT", interrupt);
process.once("SIGTERM", interrupt);
const stdout = createWriteStream(join(output, "fixture.stdout.log"), { flags: "wx" });
const stderr = createWriteStream(join(output, "fixture.stderr.log"), { flags: "wx" });
try {
  child = spawn(python, ["-m", "uvicorn", "backend.tests.fixtures.aging_contract_app:create_app",
    "--factory", "--host", "127.0.0.1", "--port", String(backendPort), "--workers", "1",
    "--no-access-log", "--log-level", "warning"], {
    cwd: repository, windowsHide: true, stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env, PYTHONPATH: [join(repository, "backend/src"), process.env.PYTHONPATH]
      .filter(Boolean).join(delimiter), AGEMORPH_SYNTHETIC_AGING_CONTRACT: "1",
      AGEMORPH_SYNTHETIC_FRONTEND: frontend, AGEMORPH_SYNTHETIC_NONCE: nonce,
      AGEMORPH_SYNTHETIC_PARENT_MONITOR: "1" },
  });
  child.once("close", () => { childClosed = true; });
  child.stdout.pipe(stdout);
  child.stderr.pipe(stderr);
  const spawnError = new Promise((_, reject) => child.once("error", reject));
  await Promise.race([waitFor(async () => {
    assert.equal(interrupted, false, "Synthetic contract run was interrupted.");
    if (child.exitCode !== null) throw new Error(`Synthetic fixture exited ${child.exitCode}.`);
    try { await state(); return true; }
    catch (error) { if (error.name === "AssertionError") throw error; return false; }
  }, 20_000), spawnError]);
  const setup = await control("setup", {});
  assert.equal(setup.synthetic_only, true);
  assert.equal(setup.sam_inference, false);
  assert.equal(setup.source_age.value, 42.5);
  report.productionBoundary = await (await boundedFetch(`${backend}/_contract/production-probe`)).json();
  assert.deepEqual({ status: report.productionBoundary.aging_status,
    code: report.productionBoundary.aging_code, shape: report.productionBoundary.age_morph,
    texture: report.productionBoundary.age_texture },
  { status: 503, code: "MODEL_NOT_READY", shape: false, texture: false });
  vite = await createServer({ root: fileURLToPath(new URL("../", import.meta.url)), configFile: false,
    server: { host: "127.0.0.1", port: frontendPort, strictPort: true, open: false },
    plugins: [{ name: "synthetic-aging-contract",
      resolveId(id) { if (id === "/__aging_modules.js") return "\0aging-contract-modules"; },
      load(id) { if (id === "\0aging-contract-modules") return `
        export { LocalApi } from '/src/services.ts';
        export { FaceViewer } from '/src/viewer.ts';
        export { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';`; },
      configureServer(server) {
        server.middlewares.use((request, response, next) => {
          if (request.url?.split("?")[0] !== "/__aging_contract") return next();
          response.setHeader("Content-Type", "text/html; charset=utf-8");
          response.end(`<!doctype html><html lang="zh-CN"><meta charset="utf-8">
            <title>合成年龄会话契约检查</title><style>body{margin:0;background:#111827;
            color:#dce9ef;font:16px system-ui}header{padding:20px}#viewer{height:680px}</style>
            <header><h1>合成会话 · 非 SAM / 非 G3</h1><p id="state">测试静态源与纹理传输</p></header>
            <div id="viewer"></div></html>`);
        });
      },
    }],
  });
  await vite.listen();
  for (const channel of report.requestedBrowsers) {
    assert.equal(interrupted, false, "Synthetic contract run was interrupted.");
    const errors = [], externalRequests = [];
    const before = await state();
    browser = await chromium.launch({ channel, headless: true,
      args: ["--enable-unsafe-swiftshader", "--use-angle=swiftshader"] });
    const page = await browser.newPage({ viewport: { width: 1200, height: 880 }, locale: "zh-CN" });
    page.setDefaultTimeout(30_000);
    page.on("pageerror", error => errors.push(error.message));
    page.on("request", request => {
      const url = new URL(request.url());
      if (["http:", "https:"].includes(url.protocol) && ![frontend, backend].includes(url.origin))
        externalRequests.push(request.url());
    });
    await page.goto(`${frontend}/__aging_contract`);
    const initial = await page.evaluate(async apiUrl => {
      const { LocalApi, FaceViewer } = await import("/__aging_modules.js");
      window.contractFetch = (url, init = {}) => fetch(url,
        { ...init, signal: AbortSignal.timeout(5000) });
      window.client = new LocalApi(apiUrl);
      const photo = await (await window.contractFetch(`${apiUrl}/_contract/input.png`)).blob();
      window.photo = photo;
      window.metadata = await window.client.reconstruct(photo, undefined, 42.5);
      window.viewer = new FaceViewer(document.getElementById("viewer"));
      window.viewer.setAutoRotate(false);
      await window.viewer.loadModel(window.client.assetUrl(window.metadata.mesh_id), window.metadata);
      window.viewer.setView("front");
      return window.metadata;
    }, backend);
    assert.equal(initial.source_age.value, 42.5);
    assert.deepEqual(initial.capabilities, { age_morph: false, age_texture: true });
    await expect(page.locator("#viewer canvas")).toBeVisible();
    const originalGlb = await (await boundedFetch(`${backend}/api/assets/${initial.mesh_id}/mesh.glb`)).arrayBuffer();
    const generated = await page.evaluate(async () => {
      const first = await window.client.aging(window.metadata.mesh_id, 20);
      const again = await window.client.aging(window.metadata.mesh_id, 20.0);
      await window.viewer.setTexture(first.texture_url, false, 20);
      document.getElementById("state").textContent = "合成 20 整数条件；非真实年龄生成";
      return { first, again };
    });
    assert.deepEqual(generated.first, generated.again);
    assert.equal((await state()).calls.length - before.calls.length, 1, "Cache hit reran the processor.");
    const front = join(output, `synthetic-integer-${channel}.png`);
    await page.screenshot({ path: front });
    const exported = await page.evaluate(async () => {
      const { GLTFLoader } = await import("/__aging_modules.js");
      const blob = await window.viewer.exportGLB();
      const bytes = await blob.arrayBuffer();
      const scene = (await new GLTFLoader().parseAsync(bytes, "")).scene;
      const meshes = [];
      scene.traverse(node => { if (node.isMesh) meshes.push(node); });
      const map = meshes[0].material.map;
      const canvas = document.createElement("canvas");
      canvas.width = map.image.width; canvas.height = map.image.height;
      const context = canvas.getContext("2d", { willReadFrequently: true });
      context.drawImage(map.image, 0, 0);
      const rgba = context.getImageData(0, 0, canvas.width, canvas.height).data;
      const digest = async data => [...new Uint8Array(await crypto.subtle.digest("SHA-256", data))]
        .map(v => v.toString(16).padStart(2, "0")).join("");
      const target = await window.client.aging(window.metadata.mesh_id, 20);
      const image = await createImageBitmap(await (await window.contractFetch(target.texture_url)).blob());
      context.clearRect(0, 0, canvas.width, canvas.height);
      context.drawImage(image, 0, 0); image.close();
      return { bytes: [...new Uint8Array(bytes)], embeddedRgbaSha256: await digest(rgba),
        endpointRgbaSha256: await digest(context.getImageData(0, 0, canvas.width, canvas.height).data),
        vertices: meshes[0].geometry.getAttribute("position").count, flipY: map.flipY,
        colorSpace: map.colorSpace, alphaTest: meshes[0].material.alphaTest };
    });
    assert.equal(exported.embeddedRgbaSha256, exported.endpointRgbaSha256);
    assert.equal(exported.vertices, 3); assert.equal(exported.flipY, false);
    assert.equal(exported.colorSpace, "srgb"); assert.equal(exported.alphaTest, 0.5);
    const exportedPath = join(output, `synthetic-export-${channel}.glb`);
    await writeFile(exportedPath, Buffer.from(exported.bytes), { flag: "wx" });
    delete exported.bytes;
    const reset = await page.evaluate(async () => {
      const result = await window.client.aging(window.metadata.mesh_id, 42.5);
      await window.viewer.setTexture(null);
      const digest = async bytes => [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))]
        .map(v => v.toString(16).padStart(2, "0")).join("");
      return { original: await digest(await (await window.contractFetch(window.metadata.texture_url)).arrayBuffer()),
        reset: await digest(await (await window.contractFetch(result.texture_url)).arrayBuffer()) };
    });
    assert.equal(reset.original, reset.reset);
    assert.equal(hash(Buffer.from(originalGlb)), hash(Buffer.from(await (await boundedFetch(
      `${backend}/api/assets/${initial.mesh_id}/mesh.glb`)).arrayBuffer())));
    const fractional = await boundedFetch(`${backend}/api/aging`, { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mesh_id: initial.mesh_id, age: 42.6 }) });
    assert.equal(fractional.status, 422);
    assert.equal((await fractional.json()).code, "INTEGER_AGE_REQUIRED");
    await control("block", {});
    await page.evaluate(() => {
      window.aborter = new AbortController();
      window.abandoned = null;
      window.pending = window.client.aging(window.metadata.mesh_id, 45, window.aborter.signal)
        .then(() => { window.abandoned = "unexpected_success"; }, () => { window.abandoned = "cancelled"; });
    });
    await waitFor(async () => (await state()).processing === 1);
    await page.evaluate(() => window.aborter.abort());
    await page.waitForFunction(() => window.abandoned === "cancelled");
    const busy = await boundedFetch(`${backend}/api/aging`, { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mesh_id: initial.mesh_id, age: 70 }) });
    assert.equal(busy.status, 429); assert.equal((await busy.json()).code, "BUSY");
    assert.equal((await state()).cache.pins, 1, "Client abort freed an in-use source context.");
    await control("release", {});
    await waitFor(async () => { const value = await state(); return value.processing === 0 && value.cache.pins === 0; });
    assert.equal((await state()).cache.results, 1, "Abandoned result was cached.");
    await control("advance", { seconds: 300 });
    const expired = await boundedFetch(`${backend}/api/assets/${initial.mesh_id}/mesh.glb`);
    assert.equal(expired.status, 404); assert.equal((await expired.json()).code, "SESSION_EXPIRED");
    const expiredTexture = await boundedFetch(generated.first.texture_url);
    assert.equal(expiredTexture.status, 404);
    const replacement = await page.evaluate(async () => {
      const next = await window.client.reconstruct(window.photo, undefined, 42.5);
      await window.viewer.loadModel(window.client.assetUrl(next.mesh_id), next);
      window.metadata = next;
      document.getElementById("state").textContent = "过期后已重新建立合成会话；生产年龄接口仍关闭";
      return next;
    });
    assert.notEqual(replacement.mesh_id, initial.mesh_id);
    const recovered = join(output, `synthetic-recovered-${channel}.png`);
    await page.screenshot({ path: recovered });
    assert.deepEqual(errors, []); assert.deepEqual(externalRequests, []);
    report.results.push({ channel, version: browser.version(), status: "passed", errors,
      externalRequests, integerCacheHit: true, exactFractionalSourceReset: true,
      unsupportedFractionalConditionRejected: true, cancelledWorkRetainsPinAndAdmission: true,
      abandonedResultNotCached: true, expiredGlbAndTextureRejected: true, newSessionRecovered: true,
      exportedTexture: exported, screenshots: [front, recovered], exportedGlb: exportedPath });
    await page.evaluate(() => window.viewer.dispose());
    await browser.close(); browser = undefined;
  }
  report.status = "passed";
} catch (error) {
  failure = error;
  report.status = "failed";
  report.failure = { name: error.name, message: error.message, stack: error.stack };
} finally {
  await deadline(browser?.close(), 5000).catch(() => {});
  // HTTP availability is never a prerequisite for stopping the owned launcher.
  if (actualFixturePid !== undefined) await control("release", {}).catch(() => {});
  try {
    await stopLauncher();
    await waitFor(async () => await closed(backendPort), 5000);
  } catch (error) {
    failure ??= error; report.shutdownError = error.message; report.status = "failed";
  }
  await deadline(vite?.close(), 5000).catch(error => {
    failure ??= error; report.frontendShutdownError = error.message; report.status = "failed";
  });
  stdout.end(); stderr.end();
  process.removeListener("SIGINT", interrupt);
  process.removeListener("SIGTERM", interrupt);
  report.interrupted = interrupted;
  if (interrupted) { report.status = "failed"; failure ??= new Error("Synthetic contract run was interrupted."); }
  report.ownedServersClosed = await closed(frontendPort) && await closed(backendPort);
  if (!report.ownedServersClosed) { report.status = "failed"; failure ??= new Error("Owned loopback port remains open."); }
  report.finishedAt = new Date().toISOString();
  await writeFile(join(output, "aging-session-contract.json"), JSON.stringify(report, null, 2) + "\n", { flag: "wx" });
}
if (failure) throw failure;
console.log(`Synthetic aging contract: ${report.results.length}/2 real browser runs passed; no SAM/G3.`);

function port(name, fallback) {
  const value = Number(process.env[name] ?? fallback);
  assert.ok(Number.isInteger(value) && value > 1024 && value <= 65535, `Invalid ${name}.`);
  return value;
}
function hash(data) { return createHash("sha256").update(data).digest("hex"); }
async function control(name, payload) {
  const response = await boundedFetch(`${backend}/_contract/${name}`, { method: "POST",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  assert.equal(response.ok, true, `Synthetic ${name} failed: ${response.status}.`);
  return response.json();
}
async function state() {
  const response = await fetch(`${backend}/_contract/state`, { signal: AbortSignal.timeout(1000) });
  assert.equal(response.ok, true);
  const value = await response.json();
  assert.equal(value.synthetic_only, true);
  assert.equal(value.fixture_nonce, nonce, "The loopback server is not the owned synthetic fixture.");
  assert.ok(Number.isInteger(value.fixture_pid) && value.fixture_pid > 0);
  assert.ok(Number.isInteger(value.fixture_ppid) && value.fixture_ppid > 0);
  assert.ok(value.fixture_pid === child.pid || value.fixture_ppid === child.pid,
    "The fixture must be the spawned Python process or its direct launcher child.");
  if (process.platform === "win32") assert.equal(value.parent_monitor_enabled, true);
  if (actualFixturePid !== undefined) assert.equal(value.fixture_pid, actualFixturePid);
  actualFixturePid = value.fixture_pid;
  report.fixtureOwnership = { launcherPid: child.pid, actualPid: value.fixture_pid,
    actualParentPid: value.fixture_ppid, nonceMatched: true,
    parentMonitorEnabled: value.parent_monitor_enabled };
  return value;
}
async function stopLauncher() {
  if (!child || childClosed) return;
  const finished = new Promise(resolveClose => child.once("close", resolveClose));
  if (child.exitCode === null && child.signalCode === null) child.kill("SIGTERM");
  try { await deadline(finished, 3000); }
  catch {
    if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
    await deadline(finished, 3000);
  }
  report.stoppedOwnedLauncherPid = child.pid;
}
function boundedFetch(url, init = {}) {
  return fetch(url, { ...init, signal: AbortSignal.timeout(3000) });
}
async function deadline(promise, milliseconds) {
  let timer;
  try {
    return await Promise.race([promise, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error("Owned resource operation exceeded its deadline.")), milliseconds);
    })]);
  } finally { clearTimeout(timer); }
}
async function waitFor(predicate, timeout = 5000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await predicate()) return;
    await new Promise(resolveWait => setTimeout(resolveWait, 30));
  }
  throw new Error("Synthetic contract condition timed out.");
}
async function closed(number) {
  return new Promise(resolveClosed => {
    const socket = connect({ host: "127.0.0.1", port: number });
    socket.once("connect", () => { socket.destroy(); resolveClosed(false); });
    socket.once("error", () => resolveClosed(true));
    socket.setTimeout(1000, () => { socket.destroy(); resolveClosed(false); });
  });
}
