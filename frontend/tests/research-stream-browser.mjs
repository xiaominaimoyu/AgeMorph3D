import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { createServer } from "node:http";
import { mkdir, readFile, readdir, realpath, stat, writeFile } from "node:fs/promises";
import { dirname, isAbsolute, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";
import { createServer as createViteServer } from "vite";
import { assessStreamEvidence, streamCases } from "./research-stream-matrix.ts";

// Opt-in synthetic gate. Never imported by the product or ordinary test command.
const ROOT = resolve(fileURLToPath(new URL("../../", import.meta.url)));
const RESEARCH = resolve(ROOT, "output/research");
const ID = "agemorph3d-research-stream-recheck-v1";
const FLAGS = { research_only: true, human_review_completed: false, identity_quality_accepted: false,
  age_quality_accepted: false, visual_seam_quality_accepted: false, years_calibrated: false,
  service_ready: false, production_enabled: false, g3_complete: false };
const args = process.argv.slice(2);
const sha = value => createHash("sha256").update(value).digest("hex");
const rel = value => relative(ROOT, value).split(sep).join("/");
const json = async path => JSON.parse(await readFile(path, "utf8"));
const writeJson = (path, value) => writeFile(path, JSON.stringify(value, null, 2) + "\n", { flag: "wx" });
const option = (name, required = true) => {
  const at = args.indexOf(name);
  if (at < 0 && !required) return undefined;
  assert.ok(at >= 0 && args[at + 1] && !args[at + 1].startsWith("--"), `Specify ${name}`);
  return args[at + 1];
};
function repoPath(value) {
  const path = resolve(ROOT, value), tail = relative(ROOT, path);
  assert.ok(!isAbsolute(tail) && tail !== ".." && !tail.startsWith(".." + sep), "Path must stay within the repository");
  return path;
}
async function outputPath(value, directory) {
  const path = repoPath(value), tail = relative(RESEARCH, path);
  assert.ok(tail && tail !== ".." && !tail.startsWith(".." + sep) && !isAbsolute(tail), "Output must be under output/research");
  await mkdir(dirname(path), { recursive: true });
  const parent = await realpath(dirname(path)), boundary = await realpath(RESEARCH);
  const realTail = relative(boundary, parent);
  assert.ok(!isAbsolute(realTail) && realTail !== ".." && !realTail.startsWith(".." + sep), "Output parent escapes research directory");
  if (directory) await mkdir(path);
  return path;
}
async function pin(path) {
  const data = await readFile(path);
  return { path: rel(path), bytes: data.length, sha256: sha(data) };
}
async function verify(value) { assert.deepEqual(await pin(repoPath(value.path)), value, `Input drift: ${value.path}`); }
async function executable(path) { const data = await readFile(path); return { path, bytes: data.length, sha256: sha(data) }; }
async function verifyExecutable(value) { assert.deepEqual(await executable(value.path), value, "Executable drift"); }

async function prepare() {
  const dir = await outputPath(option("--output-dir"), true);
  const body = Buffer.alloc(131072);
  for (let i = 0; i < body.length; i++) body[i] = (i * 31 + 7) & 255;
  const path = resolve(dir, "synthetic.bin");
  await writeFile(path, body, { flag: "wx" });
  await writeJson(resolve(dir, "fixtures.json"), { protocol_id: ID, synthetic_only: true, body: await pin(path) });
  console.log(JSON.stringify({ status: "prepared", manifest: rel(resolve(dir, "fixtures.json")) }));
}
async function browserPin(channel) {
  const supplied = option(channel === "chrome" ? "--chrome-executable" : "--edge-executable", false);
  const candidates = supplied ? [resolve(supplied)] : channel === "chrome" ? [
    resolve(process.env.PROGRAMFILES || "C:/Program Files", "Google/Chrome/Application/chrome.exe"),
    "/opt/google/chrome/chrome", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ] : [resolve(process.env["PROGRAMFILES(X86)"] || "C:/Program Files (x86)", "Microsoft/Edge/Application/msedge.exe"),
    "/opt/microsoft/msedge/msedge", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"];
  for (const path of candidates) {
    try { if ((await stat(path)).isFile()) return { channel, ...await executable(path) }; } catch (error) {
      if (error.code !== "ENOENT" && error.code !== "ENOTDIR") throw error;
    }
  }
  throw new Error(`Installed ${channel} unavailable; supply its executable path. No browser is installed automatically.`);
}
async function sourcePaths() {
  const files = new Set([".gitignore", "docs/research-stream-recheck-v1.json", "frontend/package.json", "frontend/package-lock.json",
    "frontend/tsconfig.json", "frontend/vite.config.ts", "frontend/tests/research-stream-browser.mjs",
    "frontend/tests/research-stream-matrix.ts", "frontend/tests/research-stream-matrix.test.ts",
    "frontend/node_modules/@playwright/test/package.json", "frontend/node_modules/playwright/package.json",
    "frontend/node_modules/playwright-core/package.json", "frontend/node_modules/vite/package.json"]);
  for (const entry of await readdir(resolve(ROOT, "frontend/src"), { withFileTypes: true }))
    if (entry.isFile() && entry.name.endsWith(".ts")) files.add("frontend/src/" + entry.name);
  return [...files].sort();
}
async function freeze() {
  const fixturePath = repoPath(option("--fixtures")), fixtures = await json(fixturePath);
  assert.equal(fixtures.protocol_id, ID); assert.equal(fixtures.synthetic_only, true); await verify(fixtures.body);
  const protocol = await json(resolve(ROOT, "docs/research-stream-recheck-v1.json"));
  assert.equal(protocol.protocol_id, ID);
  assert.deepEqual(protocol.flags, FLAGS);
  assert.deepEqual(protocol.positive, { fixed_repeats: 4, split_repeats: 4, body_bytes: 131072, budget_bytes: 262144 });
  assert.deepEqual(streamCases().filter(x => !x.positive).map(x => x.id), protocol.negative_cases);
  const path = await outputPath(option("--plan"), false);
  const plan = { protocol_id: ID, synthetic_only: true, fixtures: await pin(fixturePath),
    sources: await Promise.all((await sourcePaths()).map(name => pin(repoPath(name)))),
    browsers: await Promise.all(["chrome", "msedge"].map(browserPin)),
    runtime: { node: process.version, platform: process.platform, arch: process.arch, ...await executable(process.execPath) },
    cases: streamCases(), flags: protocol.flags };
  await writeJson(path, plan);
  console.log(JSON.stringify({ status: "frozen_before_run", sources: plan.sources.length, cases_per_browser: plan.cases.length, plan: rel(path) }));
}

const pageModule = `
import { ResearchSessionApi } from '/src/research-session.ts';
window.runStreamCase = async (base, spec, id) => {
  const controller = new AbortController(), result = { rejected: false };
  const observePrefix = ['prefix-over','timeout','abort'].includes(spec.kind);
  const original = ReadableStreamDefaultReader.prototype.read;
  if (observePrefix) ReadableStreamDefaultReader.prototype.read = function(...args) {
    return original.apply(this,args).then(async part => {
      if (!part.done && result.firstChunk === undefined) {
        result.firstChunk = part.value.byteLength;
        await window.observedStreamPrefix(id);
        if (spec.kind === 'abort') controller.abort();
      }
      return part;
    });
  };
  try {
    const api = new ResearchSessionApi(base);
    const bytes = await api.bytes(base + '/bytes/' + id, {}, spec.budget, 'application/octet-stream', controller.signal, spec.kind === 'timeout' ? 1000 : 5000);
    result.bytes = bytes.byteLength;
    result.sha256 = [...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(x=>x.toString(16).padStart(2,'0')).join('');
  } catch (error) { result.rejected = true; result.error = { name:error.name, message:error.message, code:error.code, status:error.status }; }
  finally { if (observePrefix) ReadableStreamDefaultReader.prototype.read = original; }
  result.aborted = controller.signal.aborted;
  return result;
};
window.streamProbeReady = true;
`;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function deadline(promise, ms) {
  let timer;
  try { return await Promise.race([promise, new Promise((_resolve, reject) => { timer = setTimeout(() => reject(new Error("Host observation deadline exceeded")), ms); })]); }
  finally { clearTimeout(timer); }
}
async function waitUntil(predicate, ms) {
  const deadline = Date.now() + ms;
  while (!predicate() && Date.now() < deadline) await sleep(10);
  return predicate();
}

async function run() {
  const planPath = repoPath(option("--plan")), plan = await json(planPath);
  assert.equal(plan.protocol_id, ID); assert.equal(plan.synthetic_only, true);
  assert.deepEqual(plan.cases, streamCases());
  assert.deepEqual(plan.sources.map(row => row.path), await sourcePaths(), "Incomplete or reordered source freeze");
  assert.deepEqual(plan.browsers.map(x => x.channel), ["chrome", "msedge"]);
  for (const source of plan.sources) await verify(source);
  await verify(plan.fixtures);
  const fixtures = await json(repoPath(plan.fixtures.path)); await verify(fixtures.body);
  assert.equal(fixtures.protocol_id, ID); assert.equal(fixtures.synthetic_only, true);
  assert.equal(fixtures.body.bytes, 131072);
  assert.equal(plan.runtime.node, process.version); assert.equal(plan.runtime.path, process.execPath);
  await verifyExecutable({ path: plan.runtime.path, bytes: plan.runtime.bytes, sha256: plan.runtime.sha256 });
  for (const { channel, ...binary } of plan.browsers) await verifyExecutable(binary);
  const protocol = await json(resolve(ROOT, "docs/research-stream-recheck-v1.json"));
  assert.deepEqual(plan.flags, protocol.flags); assert.deepEqual(plan.flags, FLAGS);
  const dir = await outputPath(option("--output-dir"), true);
  await writeJson(resolve(dir, "plan-frozen.json"), plan);
  await mkdir(resolve(dir, "snapshots"));
  for (let i = 0; i < plan.sources.length; i++)
    await writeFile(resolve(dir, "snapshots", `${i}-${plan.sources[i].path.split("/").at(-1)}`), await readFile(repoPath(plan.sources[i].path)), { flag: "wx" });
  await writeFile(resolve(dir, "page.frozen.js"), pageModule, { flag: "wx" });
  const body = await readFile(repoPath(fixtures.body.path));
  const report = { protocol_id: ID, status: "running", synthetic_only: true, plan: await pin(planPath),
    model_execution: false, real_service_acceptance: false, ...plan.flags,
    browsers: [], server_requests: [], errors: [], cleanup: {}, inputs_unchanged: false };
  const pending = new Map(), timers = new Set();
  let vite, server, browser, context;
  try {
    vite = await createViteServer({ root: resolve(ROOT, "frontend"), configFile: false,
      server: { host: "127.0.0.1", port: 0 }, plugins: [{ name: "stream-recheck", configureServer(instance) {
        instance.middlewares.use((req, res, next) => {
          const path = new URL(req.url, "http://127.0.0.1").pathname;
          if (!["/stream-probe", "/stream-probe.js"].includes(path)) return next();
          res.setHeader("Cache-Control", "no-store");
          res.setHeader("Content-Type", path.endsWith(".js") ? "application/javascript" : "text/html");
          res.end(path.endsWith(".js") ? pageModule : '<html><link rel="icon" href="data:,"><title>Synthetic stream gate</title><script type="module" src="/stream-probe.js"></script></html>');
        });
      } }] });
    await vite.listen();
    report.page_origin = `http://127.0.0.1:${vite.httpServer.address().port}`;
    const specs = new Map(plan.browsers.flatMap(browser => streamCases().map(spec => [`${browser.channel}-${spec.id}`, spec])));
    server = createServer((req, res) => {
      const id = new URL(req.url, "http://127.0.0.1").pathname.slice("/bytes/".length), spec = specs.get(id);
      if (!req.url.startsWith("/bytes/") || !spec || req.method !== "GET") { res.writeHead(404); res.end(); return; }
      const row = { id, kind: spec.kind, method: req.method, requestBodyBytes: 0, bodyWrites: [], prefixObserved: false,
        remainderReleased: false, finished: false, closed: false, errors: [] };
      report.server_requests.push(row);
      req.on("data", chunk => { row.requestBodyBytes += chunk.length; });
      res.on("finish", () => { row.finished = true; });
      res.on("close", () => { row.closed = true; pending.delete(id); });
      res.on("error", error => { row.errors.push(error.message); });
      res.setHeader("Cache-Control", "no-store");
      res.setHeader("Access-Control-Allow-Origin", report.page_origin);
      res.setHeader("Access-Control-Expose-Headers", "Content-Type, Content-Length");
      res.setHeader("Content-Type", spec.kind === "wrong-media" ? "text/plain" : "application/octet-stream");
      const write = (value, end = false) => { row.bodyWrites.push(value.length); if (end) res.end(value); else res.write(value); };
      if (spec.kind === "http-error") {
        const bytes = Buffer.from('{"code":"STAGE_EXPIRED"}');
        res.statusCode = 404; res.setHeader("Content-Type", "application/json"); res.setHeader("Content-Length", bytes.length); write(bytes, true);
      } else if (spec.kind === "empty") { res.setHeader("Content-Length", 0); write(Buffer.alloc(0), true); }
      else if (spec.kind === "truncated") {
        res.setHeader("Content-Length", 513); row.bodyWrites.push(512);
        res.write(body.subarray(0, 512), () => { row.socketFinRequested = true; res.socket?.end(); });
      } else if (["prefix-over", "timeout", "abort"].includes(spec.kind)) {
        pending.set(id, () => {
          row.prefixObserved = true;
          if (spec.kind === "prefix-over") { row.remainderReleased = true; write(body.subarray(512), true); }
        });
        write(body.subarray(0, 512));
      } else if (spec.kind === "split") {
        res.setHeader("Content-Length", body.length); write(body.subarray(0, 65536));
        const timer = setTimeout(() => { timers.delete(timer); if (!res.destroyed) write(body.subarray(65536), true); }, 20);
        timers.add(timer);
      } else {
        if (spec.kind !== "actual-over") res.setHeader("Content-Length", body.length);
        else res.flushHeaders(); // Prevent Node end(body) from synthesizing a Content-Length.
        write(body, true);
      }
    });
    await new Promise((resolve, reject) => { server.once("error", reject); server.listen(0, "127.0.0.1", resolve); });
    report.service_origin = `http://127.0.0.1:${server.address().port}`;
    for (const installed of plan.browsers) {
      const { channel, ...binary } = installed;
      await verifyExecutable(binary);
      const result = { channel, status: "running", version: null, rows: [], page_errors: [], raw_cdp: [], raw_playwright: [], context_closed: false, browser_closed: false };
      report.browsers.push(result);
      browser = await chromium.launch({ executablePath: binary.path, headless: true });
      result.version = browser.version();
      const browserCdp = await browser.newBrowserCDPSession();
      result.browser_version = await browserCdp.send("Browser.getVersion");
      result.launch = { requested: { executablePath: binary.path, headless: true } };
      try { result.launch.cdp = await browserCdp.send("Browser.getBrowserCommandLine"); }
      catch (error) {
        if (!error.message.includes("--enable-automation not set")) throw error;
        result.launch.cdp_unavailable = error.message;
      }
      context = await browser.newContext({ serviceWorkers: "block" });
      const pw = new Map(), cd = new Map(), requestIds = new Map();
      const dataId = url => url.startsWith(report.service_origin + "/bytes/") ? new URL(url).pathname.slice("/bytes/".length) : null;
      const append = (map, id, value) => { if (!map.has(id)) map.set(id, []); map.get(id).push(value); };
      for (const [event, kind] of [["requestfinished", "finished"], ["requestfailed", "failed"]])
        context.on(event, req => { const id = dataId(req.url()); if (id) {
          const terminal = { event: kind, ...(req.failure()?.errorText ? { error: req.failure().errorText } : {}) };
          append(pw, id, terminal); result.raw_playwright.push({ id, url: req.url(), method: req.method(), terminal });
        } });
      const page = await context.newPage();
      page.on("pageerror", error => result.page_errors.push(error.message));
      await page.exposeBinding("observedStreamPrefix", (_source, id) => {
        assert.ok(pending.has(id), "Unexpected prefix notification"); pending.get(id)();
      });
      const cdp = await context.newCDPSession(page);
      await cdp.send("Network.enable");
      cdp.on("Network.requestWillBeSent", event => { const id = dataId(event.request.url); if (id) {
        requestIds.set(event.requestId, id); result.raw_cdp.push({ kind: "request", id, requestId: event.requestId, url: event.request.url });
      } });
      cdp.on("Network.responseReceived", event => { const id = requestIds.get(event.requestId); if (id)
        result.raw_cdp.push({ kind: "response", id, requestId: event.requestId, response: event.response }); });
      for (const [event, kind] of [["Network.loadingFinished", "finished"], ["Network.loadingFailed", "failed"]])
        cdp.on(event, value => { const id = requestIds.get(value.requestId); if (id) {
          const terminal = { event: kind, ...(value.errorText ? { error: value.errorText } : {}) };
          append(cd, id, terminal); result.raw_cdp.push({ kind: "terminal", id, terminal, raw: value });
        } });
      await page.goto(report.page_origin + "/stream-probe");
      await page.waitForFunction(() => window.streamProbeReady === true);
      for (const spec of streamCases()) {
        const id = `${channel}-${spec.id}`;
        const application = await deadline(page.evaluate(({ base, spec, id }) => window.runStreamCase(base, spec, id),
          { base: report.service_origin, spec, id }), 10000);
        const observed = await waitUntil(() => pw.has(id) && cd.has(id) && report.server_requests.some(row => row.id === id && (row.finished || row.closed)), 5000);
        const serverRow = report.server_requests.find(row => row.id === id);
        const responses = result.raw_cdp.filter(row => row.kind === "response" && row.id === id);
        const headers = Object.fromEntries(Object.entries(responses[0]?.response.headers || {}).map(([key, value]) => [key.toLowerCase(), value]));
        const framing = responses.length === 1 && responses[0].response.protocol === "http/1.1" && headers["cache-control"] === "no-store" &&
          (!["actual-over", "prefix-over"].includes(spec.kind) || headers["content-length"] === undefined) &&
          (spec.kind !== "declared-over" || Number(headers["content-length"]) > spec.budget) &&
          (spec.kind !== "truncated" || headers["content-length"] === "513");
        result.rows.push({ id: spec.id, request_id: id, application, playwright: pw.get(id) || [], cdp: cd.get(id) || [],
          server: serverRow || { kind: "missing", prefixObserved: false, remainderReleased: false },
          observations_complete: observed, framing_valid: framing });
      }
      result.assessment = assessStreamEvidence(result.rows, fixtures.body.sha256);
      result.observations_complete = result.rows.every(row => row.observations_complete && row.framing_valid) &&
        result.raw_cdp.filter(row => row.kind === "request").length === streamCases().length &&
        result.raw_cdp.filter(row => row.kind === "response").length === streamCases().length &&
        result.raw_playwright.length === streamCases().length;
      result.status = result.page_errors.length || !result.observations_complete ? "diagnostic-error" : result.assessment.status;
      await context.close(); context = undefined; result.context_closed = true;
      await browser.close(); result.browser_closed = !browser.isConnected(); browser = undefined;
    }
  } catch (error) { report.errors.push({ name: error.name, message: error.message, stack: error.stack }); }
  finally {
    if (context) await context.close().catch(error => report.errors.push({ cleanup: error.message }));
    if (browser) await browser.close().catch(error => report.errors.push({ cleanup: error.message }));
    for (const timer of timers) clearTimeout(timer);
    timers.clear(); pending.clear();
    if (server) { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
    if (vite) await vite.close();
    report.cleanup = { browser_closed: !browser?.isConnected(), context_closed: !context || context.pages().length === 0,
      service_closed: !server?.listening, vite_closed: !vite?.httpServer?.listening, timers: timers.size, pending_prefixes: pending.size };
    try {
      for (const source of plan.sources) await verify(source);
      await verify(plan.fixtures); await verify(fixtures.body);
      for (const { channel, ...binary } of plan.browsers) await verifyExecutable(binary);
      await verifyExecutable({ path: plan.runtime.path, bytes: plan.runtime.bytes, sha256: plan.runtime.sha256 });
      report.inputs_unchanged = true;
    } catch (error) { report.errors.push({ input_drift: error.message }); }
  }
  const integrityError = report.errors.length || report.browsers.length !== 2 || !report.inputs_unchanged ||
    report.server_requests.length !== streamCases().length * 2 ||
    new Set(report.server_requests.map(row => row.id)).size !== streamCases().length * 2 ||
    report.server_requests.some(row => row.method !== "GET" || row.requestBodyBytes !== 0 || row.errors.length) ||
    report.browsers.some(row => row.status === "diagnostic-error") ||
    !report.cleanup.browser_closed || !report.cleanup.context_closed || !report.cleanup.service_closed || !report.cleanup.vite_closed;
  report.status = integrityError ? "diagnostic-error" : report.browsers.every(row => row.status === "passed") ? "passed" : "blocked";
  await writeJson(resolve(dir, "report.json"), report);
  console.log(JSON.stringify({ status: report.status, report: rel(resolve(dir, "report.json")),
    browsers: report.browsers.map(row => ({ channel: row.channel, version: row.version, ...row.assessment })) }));
  process.exitCode = report.status === "passed" ? 0 : report.status === "blocked" ? 1 : 2;
}

try {
  assert.equal(args.filter(value => ["--prepare", "--freeze", "--run"].includes(value)).length, 1, "Choose exactly one mode");
  if (args.includes("--prepare")) await prepare();
  else if (args.includes("--freeze")) await freeze();
  else await run();
} catch (error) {
  console.error(JSON.stringify({ status: "diagnostic-error", error: { name: error.name, message: error.message } }));
  process.exitCode = 2;
}
