/** Explicit K3 transport checks. Run with --output-dir output/research/<fresh-dir>. */
import assert from "node:assert/strict";
import { spawn, execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { createServer, request } from "node:http";
import { createConnection } from "node:net";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { resolve, relative, dirname, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";
import { createServer as createViteServer } from "vite";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const API = "http://127.0.0.1:8000", PAGE = "http://127.0.0.1:5173";
const INDEX = process.argv.indexOf("--output-dir");
assert.ok(INDEX >= 0 && process.argv[INDEX + 1], "Provide a fresh --output-dir under output/");
const output = resolve(ROOT, process.argv[INDEX + 1]);
assert.ok(output.startsWith(resolve(ROOT, "output") + sep));
const sleep = ms => new Promise(r => setTimeout(r, ms));
const pin = async path => { const b = await readFile(path); return { path: relative(ROOT, path).replaceAll("\\", "/"), bytes: b.length, sha256: createHash("sha256").update(b).digest("hex") }; };
const json = (path, value) => writeFile(path, JSON.stringify(value, null, 2) + "\n", { flag: "wx" });
const HEALTH = { api_version: "1.2", models: {}, capabilities: { reconstruction: false, age_morph: false, age_texture: false, realtime: false }, device: "cpu", version: "synthetic-transport" };
const SOURCES = ["frontend/src/services.ts", "frontend/src/contracts.ts", "frontend/src/realtime.ts", "frontend/tests/services.test.ts", "frontend/tests/transport-recovery-browser.mjs", "frontend/package-lock.json", "docs/transport-recovery-v1.json", "backend/src/agemorph3d/__main__.py", "backend/src/agemorph3d/app.py", "backend/src/agemorph3d/config.py", "backend/src/agemorph3d/middleware.py", "backend/src/agemorph3d/runtime.py", "backend/src/agemorph3d/frame_socket.py", "backend/src/agemorph3d/model_lifecycle.py", "backend/src/agemorph3d/model_assets.py", "data/models/yolov5n05-face/manifest.json", "data/models/3ddfa-v2/manifest.json"];

const moduleSource = `
import {LocalApi,FrameStream} from '/src/services.ts';
const canvas=document.createElement('canvas');canvas.width=canvas.height=48;
canvas.getContext('2d').fillRect(0,0,48,48);
const video=document.createElement('video');video.muted=true;video.srcObject=canvas.captureStream(10);
document.body.append(video);await video.play();
await new Promise(r=>video.readyState>=2?r():video.addEventListener('loadeddata',r,{once:true}));
const nativeEncode=HTMLCanvasElement.prototype.toBlob;
window.state={errors:[],frames:0,statuses:[],mode:'normal'};
HTMLCanvasElement.prototype.toBlob=function(callback,...args){
 if(window.state.mode==='oversized')callback(new Blob([new Uint8Array(2097153)],{type:'image/jpeg'}));
 else nativeEncode.call(this,callback,...args);
};
window.stream=new FrameStream({websocketUrl:()=> 'ws://127.0.0.1:8000/synthetic/frame'},video,{
 onError:m=>{window.state.errors.push(m);document.querySelector('#status').textContent=m},
 onStatus:m=>window.state.statuses.push(m),onState:()=>{window.state.frames++;window.stream.stop()}
});
document.querySelector('#start').onclick=()=>window.stream.start();
window.LocalApi=LocalApi;
window.released=()=>window.stream.timer===null&&window.stream.responseTimer===null&&!window.stream.pending&&window.stream.socket===null;
window.dispose=()=>{window.stream.stop();video.srcObject.getTracks().forEach(t=>t.stop());video.srcObject=null};
window.ready=true;
`;

async function listeningPorts() {
  const command = "$transportRows = @(Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object { $_.LocalPort -in @(8000,5173) } | Select-Object LocalAddress,LocalPort,OwningProcess); ConvertTo-Json -InputObject $transportRows -Compress";
  const stdout = await new Promise((ok, bad) => execFile("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", command], { windowsHide: true }, (error, text) => error ? bad(error) : ok(text)));
  return JSON.parse(stdout);
}
function rawHealth() {
  return new Promise((ok, bad) => {
    const req = request(API + "/api/health", { agent: false, headers: { Connection: "close", Origin: PAGE } }, res => {
      const chunks = []; let size = 0;
      res.on("data", b => { size += b.length; if (size > 128 * 1024) req.destroy(new Error("Raw health budget")); else chunks.push(b); });
      res.on("end", () => ok({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks).toString("utf8") }));
    });
    req.setTimeout(3000, () => req.destroy(new Error("Raw health timeout")));
    req.on("error", bad); req.end();
  });
}
async function untilHealth(child) {
  for (let i = 0; i < 100; i++) {
    assert.equal(child.exitCode, null, "Owned backend exited before readiness");
    try { const r = await rawHealth(); if (r.status === 200) return r; } catch {}
    await sleep(50);
  }
  throw new Error("Production no-model app not ready");
}

assert.deepEqual(await listeningPorts(), [], "Do not replace an existing listener on 8000/5173");
await mkdir(output, { recursive: false });
const sources = await Promise.all(SOURCES.map(p => pin(resolve(ROOT, p))));
await json(resolve(output, "source-freeze.json"), { protocol_id: "agemorph3d-transport-recovery-v1", sources, node: process.version, before_browser_cases: true, production_model_execution: false });
const report = { status: "running", protocol_id: "agemorph3d-transport-recovery-v1", browser_results: [], server_log: "", original_network_failures: [], page_errors: [], cleanup: {}, production_g0_g1_g2_g3_accepted: false };
let child, vite, fixture, browser, holds = [];
try {
  const env = { ...process.env, PYTHONPATH: resolve(ROOT, "backend/src") };
  delete env.AGEMORPH_DETECTOR_MANIFEST; delete env.AGEMORPH_RECONSTRUCTOR_MANIFEST;
  delete env.AGEMORPH_ALLOWED_ORIGINS;
  child = spawn(resolve(ROOT, "backend/.venv/Scripts/python.exe"), ["-B", "-m", "agemorph3d"], { cwd: ROOT, env, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
  child.on("error", error => { report.backend_spawn_error = error.message; });
  child.stdout.on("data", b => { report.server_log += b.toString(); });
  child.stderr.on("data", b => { report.server_log += b.toString(); });
  report.backend_pid = child.pid;
  report.backend_scope = "Unmodified production entry/config; child manifest env unset; no-model app; fixed 16 connections, 2 MiB WS limit";
  report.initial_health = await untilHealth(child);
  assert.ok(Object.values(JSON.parse(report.initial_health.body).capabilities).every(v => v === false));
  let fixtureMode = "plain-503";
  fixture = createServer((req, res) => {
    res.setHeader("Access-Control-Allow-Origin", PAGE); res.setHeader("Cache-Control", "no-store");
    if (fixtureMode === "plain-503") { res.writeHead(503, { "Content-Type": "text/plain" }); res.end("do-not-echo-raw-503"); }
    else if (fixtureMode === "model-503") { res.writeHead(503, { "Content-Type": "application/json" }); res.end(JSON.stringify({ code: "MODEL_NOT_READY", detail: "模型权重许可尚未完成核验。" })); }
    else { res.writeHead(200, { "Content-Type": "application/json" }); res.end(JSON.stringify(HEALTH)); }
  });
  await new Promise(ok => fixture.listen(0, "127.0.0.1", ok));
  const fixtureUrl = `http://127.0.0.1:${fixture.address().port}`;
  report.fixture_origin = fixtureUrl;
  vite = await createViteServer({ root: resolve(ROOT, "frontend"), configFile: false, server: { host: "127.0.0.1", port: 5173, strictPort: true }, plugins: [{ name: "transport-feedback-test", configureServer(server) {
    server.middlewares.use((req, res, next) => {
      if (!["/transport-test", "/transport-test.js"].includes(req.url)) return next();
      res.setHeader("Content-Type", req.url.endsWith(".js") ? "application/javascript" : "text/html");
      res.end(req.url.endsWith(".js") ? moduleSource : '<html><link rel="icon" href="data:,"><button id="start">连接</button><p id="status"></p><script type="module" src="/transport-test.js"></script></html>');
    });
  } }] });
  await vite.listen();
  for (const channel of ["chrome", "msedge"]) {
    browser = await chromium.launch({ channel, headless: true });
    const context = await browser.newContext();
    const page = await context.newPage();
    page.on("pageerror", error => report.page_errors.push({ channel, message: error.message }));
    page.on("requestfailed", req => report.original_network_failures.push({ channel, url: req.url(), method: req.method(), error: req.failure()?.errorText }));
    let syntheticMode = "close1009", connections = 0, sends = 0;
    await page.routeWebSocket("ws://127.0.0.1:8000/synthetic/frame", socket => {
      connections++;
      socket.onMessage(() => {
        sends++;
        if (syntheticMode.startsWith("close")) socket.close({ code: Number(syntheticMode.slice(5)), reason: "do-not-echo-reason" });
        else socket.send(JSON.stringify({ type: "face_state", seq: 1, ts: 1, bbox: [1, 1, 20, 20], landmarks: [[3,3],[10,3],[6,6],[3,10],[10,10]], pose: { R: [1,0,0,0,1,0,0,0,1], t: [0,0,0] }, conf: .9 }));
      });
    });
    await page.goto(PAGE + "/transport-test"); await page.waitForFunction(() => window.ready === true);
    const cases = [];
    const clientError = async origin => page.evaluate(async origin => { try { await new window.LocalApi(origin).health(); return null; } catch (e) { return e.message; } }, origin);
    fixtureMode = "plain-503";
    const plain = await clientError(fixtureUrl); assert.match(plain, /HTTP 503.*可能连接繁忙/); assert.doesNotMatch(plain, /do-not-echo/);
    cases.push({ id: "readable-unstructured-503", status: "passed", message: plain, synthetic: true });
    fixtureMode = "model-503";
    const model = await clientError(fixtureUrl); assert.match(model, /模型权重许可尚未完成核验/); assert.doesNotMatch(model, /连接繁忙/);
    cases.push({ id: "structured-model-error", status: "passed", message: model, synthetic: true });
    // Real production Uvicorn overload: these are idle TCP connections, not fake 503 responses.
    holds = await Promise.all(Array.from({ length: 16 }, () => new Promise((ok, bad) => {
      const socket = createConnection({ host: "127.0.0.1", port: 8000 }); socket.once("connect", () => ok(socket)); socket.once("error", bad);
    })));
    const overloaded = await rawHealth(); assert.equal(overloaded.status, 503); assert.equal(overloaded.headers["access-control-allow-origin"], undefined);
    const opaque = await clientError(API); assert.match(opaque, /关闭其他连接后手动重试/); assert.doesNotMatch(opaque, /HTTP 503/);
    cases.push({ id: "production-overload-opaque", status: "passed", raw_response: overloaded, message: opaque, idle_connections: holds.length, synthetic: false });
    holds.forEach(s => s.destroy()); holds = [];
    await untilHealth(child);
    const recovered = await page.evaluate(async origin => new window.LocalApi(origin).health(), API);
    assert.ok(Object.values(recovered.capabilities).every(v => v === false));
    cases.push({ id: "production-health-recovery", status: "passed", health: recovered, synthetic: false });
    const rawWs = await page.evaluate(async url => new Promise((ok, bad) => {
      const socket = new WebSocket(url); const messages = []; const timer = setTimeout(() => { socket.close(); bad(new Error("Raw WS deadline")); }, 8000);
      socket.onopen = () => socket.send(new Uint8Array(2097153));
      socket.onmessage = e => messages.push(e.data);
      socket.onclose = e => { clearTimeout(timer); ok({ code: e.code, messages }); };
    }), "ws://127.0.0.1:8000/ws/frame");
    assert.equal(rawWs.code, 1009); assert.ok(rawWs.messages.every(text => JSON.parse(text).type === "status"));
    cases.push({ id: "production-raw-ws-oversize", status: "passed", ...rawWs, synthetic: false });
    // The browser closes below are explicit synthetic controls for the unchanged production client.
    for (const code of [1009, 1013]) {
      syntheticMode = "close" + code;
      const before = await page.evaluate(() => window.state.errors.length);
      await page.locator("#start").click();
      await page.waitForFunction(n => window.state.errors.length > n, before);
      const state = await page.evaluate(() => ({ message: window.state.errors.at(-1), released: window.released() }));
      assert.match(state.message, code === 1009 ? /服务大小限制/ : /暂时不可用/); assert.equal(state.released, true); assert.doesNotMatch(state.message, /do-not-echo/);
      const stable = connections; await sleep(150); assert.equal(connections, stable);
      cases.push({ id: "client-close-" + code, status: "passed", ...state, auto_reconnect: false, synthetic: true });
      syntheticMode = "frame";
      const frames = await page.evaluate(() => window.state.frames);
      await page.locator("#start").click(); await page.waitForFunction(n => window.state.frames > n, frames);
      assert.equal(await page.evaluate(() => window.released()), true);
      cases.push({ id: "client-manual-recovery-" + code, status: "passed", synthetic: true });
    }
    syntheticMode = "frame";
    await page.evaluate(() => { window.state.mode = "oversized"; });
    const beforeErrors = await page.evaluate(() => window.state.errors.length), beforeSends = sends;
    await page.locator("#start").click(); await page.waitForFunction(n => window.state.errors.length > n, beforeErrors);
    assert.equal(sends, beforeSends); assert.equal(await page.evaluate(() => window.released()), true);
    cases.push({ id: "client-local-size-rejection", status: "passed", sent_frames: 0, synthetic: true });
    await page.evaluate(() => { window.state.mode = "normal"; });
    const beforeFrames = await page.evaluate(() => window.state.frames);
    await page.locator("#start").click(); await page.waitForFunction(n => window.state.frames > n, beforeFrames);
    assert.equal(await page.evaluate(() => window.released()), true);
    cases.push({ id: "client-manual-recovery-local-size", status: "passed", synthetic: true });
    await page.evaluate(() => window.dispose());
    assert.equal(await page.evaluate(() => window.released()), true);
    cases.push({ id: "client-dispose", status: "passed", synthetic: true });
    report.browser_results.push({ channel, version: browser.version(), cases });
    await context.close(); await browser.close(); browser = null;
  }
  assert.equal(report.page_errors.length, 0);
  report.status = "passed";
} catch (error) {
  report.status = "failed"; report.failure = error.stack ?? String(error); process.exitCode = 1;
} finally {
  holds.forEach(s => s.destroy());
  if (browser) await browser.close();
  if (vite) await vite.close();
  if (fixture) { fixture.closeAllConnections(); await new Promise(ok => fixture.close(ok)); }
  if (child && child.exitCode === null) { child.kill(); await new Promise(ok => child.once("exit", ok)); }
  report.cleanup.backend_exit_code = child?.exitCode;
  report.cleanup.backend_signal = child?.signalCode;
  try {
    report.cleanup.listening_ports = await listeningPorts();
    assert.deepEqual(report.cleanup.listening_ports, []);
    report.cleanup.owned_backend_exited = !child || child.exitCode !== null || child.signalCode !== null;
    assert.equal(report.cleanup.owned_backend_exited, true);
    report.cleanup.ports_free = true;
    assert.deepEqual(await Promise.all(SOURCES.map(p => pin(resolve(ROOT, p)))), sources);
    report.inputs_unchanged = true;
  } catch (error) { report.status = "failed"; report.cleanup.failure = String(error); process.exitCode = 1; }
  await json(resolve(output, "report.json"), report);
  console.log(JSON.stringify({ status: report.status, browsers: report.browser_results.map(r => ({ channel: r.channel, version: r.version, passed: r.cases.length })), failure: report.failure, cleanup: report.cleanup, network_failures: report.original_network_failures.length }));
}
