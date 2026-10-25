import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { createReadStream, createWriteStream } from "node:fs";
import { mkdir, readFile, realpath, stat, writeFile } from "node:fs/promises";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium, expect } from "@playwright/test";
import { createServer as createViteServer } from "vite";

// Explicit live research only: every research response comes from the owned real service.
// Run only after independently freezing the plan and its input fingerprints.
const ROOT = resolve(fileURLToPath(new URL("../../", import.meta.url)));
const PROTOCOL = "agemorph3d-live-session-display-v1";
const TIMEOUT = 180_000;
const SHA = /^[0-9a-f]{64}$/;
const geometryNames = ["POSITION", "NORMAL", "TEXCOORD_0", "indices"];
assert.ok(process.env.AGEMORPH_SESSION_BROWSER_PLAN, "Set AGEMORPH_SESSION_BROWSER_PLAN explicitly.");
const planPath = resolve(process.env.AGEMORPH_SESSION_BROWSER_PLAN);
const planBytes = await readFile(planPath);
const plan = JSON.parse(planBytes.toString("utf8"));
assert.equal(plan.protocol_id, PROTOCOL);
assert.ok(plan.software_compositing === undefined || typeof plan.software_compositing === "boolean");
assert.ok(Number.isFinite(plan.source_age) && plan.source_age >= 20 && plan.source_age <= 70);
assert.ok(Number.isInteger(plan.target_condition) && plan.target_condition >= 20 && plan.target_condition <= 70);
assert.notEqual(plan.source_age, plan.target_condition, "Continuous display needs two distinct anchors.");
assert.ok(Array.isArray(plan.display_ages) && plan.display_ages.length === 6);
assert.equal(new Set(plan.display_ages).size, 6, "Specify six distinct display ages.");
for (const age of plan.display_ages)
  assert.ok(Number.isFinite(age) && age >= Math.min(plan.source_age, plan.target_condition)
    && age <= Math.max(plan.source_age, plan.target_condition), "Display ages must stay inside the frozen anchors.");
assert.ok(plan.display_ages.includes(plan.source_age), "Include the exact source anchor.");
assert.ok(plan.display_ages.includes(plan.target_condition), "Include the target anchor.");
assert.ok(plan.display_ages.some(age => !Number.isInteger(age)), "Include a decimal display position.");
assert.ok(plan.display_ages.some(age => age > Math.min(plan.source_age, plan.target_condition)
  && age < Math.max(plan.source_age, plan.target_condition)), "Include an interpolated display position.");
assert.ok(Array.isArray(plan.inputs) && plan.inputs.length > 0);
assert.ok(isAbsolute(plan.image.path), "The image path must be explicit and absolute.");
assert.ok(Number.isSafeInteger(plan.image.bytes) && plan.image.bytes > 0
  && plan.image.bytes <= 10 * 1024 ** 2, "The photo must use the bounded nonempty image budget.");
const output = repoPath(plan.output_dir);
assert.ok(inside(resolve(ROOT, "output/research"), output), "Output must be under output/research.");
const reviewPath = repoPath(plan.approved_review.path);
const inputs = new Map();
for (const input of plan.inputs) {
  const path = repoPath(input.path);
  assert.ok(!inputs.has(path.toLowerCase()), "Duplicate frozen input path.");
  inputs.set(path.toLowerCase(), { ...input, absolute: path });
}
assert.ok(inputs.has(reviewPath.toLowerCase()), "The approved review must also be in inputs.");
const allPins = [...inputs.values(), { ...plan.image, absolute: resolve(plan.image.path) }];
await checkPins(allPins);
await checkPin(reviewPath, plan.approved_review);
const customBrowserCases = plan.browser_cases !== undefined;
const browserCases = customBrowserCases ? plan.browser_cases : [
  { label: "chrome", channel: "chrome" }, { label: "msedge", channel: "msedge" },
];
assert.ok(Array.isArray(browserCases) && browserCases.length === 2,
  "The browser cohort requires two independent cases.");
assert.equal(new Set(browserCases.map(spec => spec.label)).size, browserCases.length);
if (customBrowserCases) {
  const researchRoot = await realpath(join(ROOT, "output/research"));
  for (const spec of browserCases) {
    assert.match(spec.label, /^[a-z0-9][a-z0-9_-]{0,79}$/);
    assert.ok(spec.executable && typeof spec.executable.path === "string");
    const executablePath = isAbsolute(spec.executable.path)
      ? resolve(spec.executable.path) : repoPath(spec.executable.path);
    assert.ok(inside(join(ROOT, "output/research"), executablePath)
      && inside(researchRoot, await realpath(executablePath)),
    "Custom browser executables must resolve inside output/research.");
    const frozen = inputs.get(executablePath.toLowerCase());
    assert.ok(frozen, "Each custom browser executable must be pinned in plan.inputs.");
    assert.equal(frozen.bytes, spec.executable.bytes);
    assert.equal(frozen.sha256, spec.executable.sha256);
    assert.ok(spec.executable.bytes > 0);
    await checkPin(executablePath, spec.executable);
    spec.executable = { path: relativePath(executablePath), bytes: spec.executable.bytes,
      sha256: spec.executable.sha256 };
  }
  assert.equal(new Set(browserCases.map(spec => spec.executable.sha256)).size, 1,
    "The custom cohort is limited to the same pinned browser executable.");
}
const review = JSON.parse(await readFile(reviewPath, "utf8"));
for (const key of ["source_fingerprint", "generated_sha256", "fit_sha256"]) assert.match(review[key], SHA);
for (const key of ["reviewer", "method", "version"]) {
  assert.equal(typeof review[key], "string");
  assert.ok(review[key].trim() && review[key].length <= 256);
}
assert.equal(review.reviewer_kind, "ai", "This frozen AI review cannot be relabelled as human acceptance.");
const maskPaths = {};
for (const key of ["allowed", "occluded"]) {
  assert.equal(typeof review[key], "string");
  assert.ok(!isAbsolute(review[key]) && !review[key].includes(":"));
  maskPaths[key] = resolve(dirname(reviewPath), review[key]);
  assert.ok(inside(dirname(reviewPath), maskPaths[key]), "Mask references must stay inside their review directory.");
  assert.ok(inputs.has(maskPaths[key].toLowerCase()), "Every mask must be independently pinned in inputs.");
}
await mkdir(dirname(output), { recursive: true });
const resolvedResearch = await realpath(join(ROOT, "output/research"));
const resolvedOutputParent = await realpath(dirname(output));
assert.ok(resolvedResearch.toLowerCase() === resolvedOutputParent.toLowerCase()
  || inside(resolvedResearch, resolvedOutputParent),
  "Resolved output parent escaped output/research.");
await mkdir(output); // Refuse to overwrite or reuse evidence from an earlier attempt.
await mkdir(join(output, "assets"));

const report = {
  protocol_id: PROTOCOL, status: "running", started_at_utc: new Date().toISOString(),
  research_only: true, service_ready: false, production_enabled: false, g3_complete: false,
  quality_accepted: false, human_review_completed: false, route_mocks: false,
  requested_render_configuration: { angle: "swiftshader", software_compositing: plan.software_compositing === true },
  browser_cohort: customBrowserCases ? "same-executable-independent-contexts" : "chrome-and-edge-channels",
  same_engine: customBrowserCases,
  browser_cases: browserCases,
  input_plan: { path: relativePath(planPath), bytes: planBytes.length, sha256: hash(planBytes) },
  frozen_inputs: [...inputs.values()].map(({ absolute, bytes, sha256 }) => ({ path: relativePath(absolute), bytes, sha256 })),
  private_input: { path: plan.image.path, bytes: plan.image.bytes, sha256: plan.image.sha256 },
  source: null, target: null, records: [], browsers: [], rpc: [], health_samples: [], cleanup: {},
};
let vite, browser, activePage, child, childExit, serviceBase, failed, interrupted = false;
let serverPid = null, childExitResult = null;
const childLogs = [];
const interrupt = () => {
  interrupted = true;
  void browser?.close().catch(() => {});
};
const parentMessage = value => { if (value?.type === "abort") interrupt(); };
process.on("SIGINT", interrupt);
process.on("SIGTERM", interrupt);
process.on("message", parentMessage);

try {
  vite = await createViteServer({ root: join(ROOT, "frontend"),
    configFile: join(ROOT, "frontend/vite.config.ts"), logLevel: "error",
    server: { host: "127.0.0.1", port: 0, strictPort: true, open: false } });
  await vite.listen();
  const address = vite.httpServer.address();
  assert.ok(address && typeof address === "object");
  const origin = `http://127.0.0.1:${address.port}`;
  report.frontend_origin = origin;
  const control = join(output, "server-control");
  const stdout = createWriteStream(join(output, "server.stdout.log"), { flags: "wx" });
  const stderr = createWriteStream(join(output, "server.stderr.log"), { flags: "wx" });
  childLogs.push(stdout, stderr);
  child = spawn(join(ROOT, "backend/.venv/Scripts/python.exe"),
    [join(ROOT, "tools/research_aging_server.py"), "--control-dir", control,
      "--allowed-origin", origin, "--research-allow-unresolved"],
    { cwd: ROOT, windowsHide: true, shell: false, stdio: ["ignore", "pipe", "pipe"] });
  child.stdout.pipe(stdout);
  child.stderr.pipe(stderr);
  childExit = new Promise(resolveExit => {
    child.once("error", error => resolveExit(childExitResult = { error: error.stack, code: null, signal: null }));
    child.once("exit", (code, signal) => resolveExit(childExitResult = { code, signal }));
  });
  const ready = await poll(async () => {
    if (childExitResult) throw new Error(`Owned service exited before ready: ${JSON.stringify(childExitResult)}`);
    try { return JSON.parse(await readFile(join(control, "ready.json"), "utf8")); }
    catch (error) { if (error.code === "ENOENT") return null; throw error; }
  }, TIMEOUT, "real service ready.json");
  assert.ok(Number.isSafeInteger(ready.pid) && ready.pid > 0);
  serverPid = ready.pid; // Windows venv redirectors have a separate launcher PID.
  assert.equal(ready.status, "serving");
  assert.equal(ready.research_only, true);
  assert.equal(ready.g3_complete, false);
  serviceBase = new URL(ready.base_url).origin;
  assert.equal(new URL(serviceBase).hostname, "127.0.0.1");
  assert.deepEqual(ready.allowed_origins, [origin]);
  report.server = { pid: serverPid, launcher_pid: child.pid, base_url: serviceBase,
    ready: relativePath(join(control, "ready.json")) };
  await health("initial");

  for (const [caseIndex, browserCase] of browserCases.entries()) {
    const browserLabel = browserCase.label;
    const entry = { browser: browserLabel, case_index: caseIndex, same_engine: customBrowserCases,
      ...(customBrowserCases ? { executable: browserCase.executable } : { channel: browserCase.channel }),
      status: "running", page_errors: [], request_failures: [],
      unexpected_http_failures: [], external_requests: [], expected_cancel_requests: [],
      actions: [], network: [] };
    report.browsers.push(entry);
    browser = await chromium.launch({ ...(customBrowserCases
      ? { executablePath: repoPath(browserCase.executable.path) } : { channel: browserCase.channel }), headless: true,
      args: ["--enable-unsafe-swiftshader", "--use-angle=swiftshader",
        ...(plan.software_compositing ? ["--disable-gpu-compositing"] : [])] });
    entry.version = browser.version();
    const context = await browser.newContext({ viewport: { width: 1600, height: 1100 }, acceptDownloads: true });
    const page = await context.newPage();
    activePage = page;
    page.setDefaultTimeout(30_000);
    await page.addInitScript(() => {
      const telemetry = { raf_ticks: 0, timer_ticks: 0, last_raf_ms: 0, last_timer_ms: 0 };
      window.__liveFrameTelemetry = telemetry;
      let frame;
      const tick = () => {
        telemetry.raf_ticks++;
        telemetry.last_raf_ms = performance.now();
        frame = requestAnimationFrame(tick);
      };
      frame = requestAnimationFrame(tick);
      const timer = setInterval(() => {
        telemetry.timer_ticks++;
        telemetry.last_timer_ms = performance.now();
      }, 250);
      addEventListener("pagehide", () => { cancelAnimationFrame(frame); clearInterval(timer); }, { once: true });
    });
    let action = "browser-initialization", requestSequence = 0;
    const requestRecords = new WeakMap();
    page.__liveSetAction = label => {
      action = label;
      entry.actions.push({ action: label, at_utc: new Date().toISOString() });
    };
    const cancelRequests = new WeakSet();
    let cancelWindow = false;
    page.on("pageerror", error => entry.page_errors.push(error.stack ?? String(error)));
    page.on("request", request => {
      const url = new URL(request.url());
      if (!["http:", "https:"].includes(url.protocol)) return;
      const headers = request.headers();
      const trace = { request_id: `${browserLabel}-${++requestSequence}`, browser: browserLabel,
        action, started_at_utc: new Date().toISOString(), method: request.method(), url: request.url(),
        resource_type: request.resourceType(), navigation_request: request.isNavigationRequest(),
        request_headers: Object.fromEntries(["origin", "referer", "content-type", "content-length"]
          .filter(key => headers[key] !== undefined).map(key => [key, headers[key]])),
        redirected_from: request.redirectedFrom()?.url() ?? null,
        response: null, finished_at_utc: null, failed_at_utc: null };
      requestRecords.set(request, trace);
      entry.network.push(trace);
      if (![origin, serviceBase].includes(url.origin)) entry.external_requests.push(request.url());
      if (url.origin === serviceBase) {
        const record = { browser: browserLabel, method: request.method(), path: url.pathname,
          query: url.search, request_id: trace.request_id, action,
          started_at_utc: trace.started_at_utc, status: null };
        report.rpc.push(record);
        request.__liveRecord = record;
        if (cancelWindow && request.method() === "POST" && /\/conditions$/.test(url.pathname))
          cancelRequests.add(request);
      }
    });
    page.on("response", response => {
      const request = response.request();
      const trace = requestRecords.get(request);
      if (trace) {
        const headers = response.headers();
        trace.response = { received_at_utc: new Date().toISOString(), action,
          url: response.url(), status: response.status(), status_text: response.statusText(),
          from_service_worker: response.fromServiceWorker(),
          headers: Object.fromEntries(["content-type", "content-length", "connection", "access-control-allow-origin"]
            .filter(key => headers[key] !== undefined).map(key => [key, headers[key]])) };
      }
      if (request.__liveRecord) request.__liveRecord.status = response.status();
      if (response.status() >= 400) entry.unexpected_http_failures.push({ request_id: trace?.request_id,
        action, at_utc: new Date().toISOString(), url: response.url(), status: response.status() });
    });
    page.on("requestfinished", request => {
      const trace = requestRecords.get(request);
      if (!trace) return;
      trace.finished_at_utc = new Date().toISOString();
      trace.finished_action = action;
      trace.timing = request.timing();
      if (request.__liveRecord) request.__liveRecord.finished_at_utc = trace.finished_at_utc;
    });
    page.on("requestfailed", request => {
      const trace = requestRecords.get(request);
      const at = new Date().toISOString();
      if (trace) {
        trace.failed_at_utc = at;
        trace.failed_action = action;
        trace.failure = request.failure();
        trace.timing = request.timing();
      }
      const item = { request_id: trace?.request_id, request_action: trace?.action, failed_action: action,
        started_at_utc: trace?.started_at_utc, failed_at_utc: at,
        method: request.method(), url: request.url(), resource_type: request.resourceType(),
        response_seen: trace?.response !== null && trace?.response !== undefined,
        response: trace?.response ?? null, request_finished_seen: !!trace?.finished_at_utc,
        timing: request.timing(), error: request.failure()?.errorText ?? "unknown" };
      if (cancelRequests.has(request) && /(?:ERR_ABORTED|NS_BINDING_ABORTED|cancel)/i.test(item.error))
        entry.expected_cancel_requests.push(item);
      else entry.request_failures.push(item);
    });
    markAction(page, "open-research-page");
    await page.goto(`${origin}/research/session.html`, { waitUntil: "networkidle" });
    await page.waitForFunction(() => !!window.__researchSessionTools);
    const gpuSession = await browser.newBrowserCDPSession();
    try {
      const { gpu } = await deadline(gpuSession.send("SystemInfo.getInfo"), 5000, "browser GPU information");
      entry.browser_gpu_features = gpu.featureStatus;
      entry.browser_gpu_devices = gpu.devices.map(({ vendorId, deviceId, vendorString, deviceString, driverVendor, driverVersion }) =>
        ({ vendorId, deviceId, vendorString, deviceString, driverVendor, driverVersion }));
    } finally { await gpuSession.detach(); }
    assert.equal(await page.getByTestId("source-age").inputValue(), "");
    assert.equal(await page.evaluate(() => window.__researchSessionTools.viewer().model), null);
    await page.getByTestId("service-url").fill(serviceBase);
    markAction(page, "connect-real-service");
    await page.getByTestId("connect-service").click();
    await idle(page);
    await noUiError(page);

    if (caseIndex === 0) {
      markAction(page, "upload-source-and-create-session");
      await page.getByTestId("source-file").setInputFiles(plan.image.path);
      assert.equal(await page.getByTestId("source-age").inputValue(), "");
      await page.getByTestId("source-age").fill(String(plan.source_age));
      await page.getByTestId("create-session").click();
      await bound(page);
      const initial = await state(page);
      assert.deepEqual(initial.sourceAge, sourceAge());
      assert.deepEqual(initial.conditionAges, []);
      const sourceDigest = await page.evaluate(() => window.__researchSessionTools.sourceDigest());
      const sid = initial.sessionId;
      assert.match(sid, /^[0-9a-f]{32}$/);
      const info = await jsonGet(`/research/sessions/${sid}`);
      assert.deepEqual(info.source_age, sourceAge());
      assert.equal(info.source_fingerprint, review.source_fingerprint);
      const glb = await getAsset(info.source_glb_url, "assets/source.glb");
      const texture = await getAsset(info.source_texture_url, "assets/source-texture.png");
      assert.equal(glb.sha256, sourceDigest);
      const sourceGlb = glbDocument(await readFile(repoPath(glb.path)));
      assert.deepEqual(embeddedPng(sourceGlb), await readFile(repoPath(texture.path)));
      assert.equal(sourceGlb.json.materials[0].alphaMode, "MASK");
      assert.equal(sourceGlb.json.materials[0].alphaCutoff, 0.5);
      report.source = { session_id: sid, source_age: info.source_age, shape: info.shape,
        source_fingerprint: info.source_fingerprint, topology_id: sourceGlb.json.extras.topology_id,
        glb, texture, geometry_hashes: geometryHashes(sourceGlb) };
      assert.deepEqual(initial.geometryHashes, report.source.geometry_hashes);
      entry.graphics_before_native = await deadline(graphicsState(page), 5000, "initial graphics observation");
      await page.getByTestId("target-condition").fill(String(plan.target_condition));
      cancelWindow = true;
      markAction(page, "stage-for-native-cancellation");
      await page.getByTestId("stage-condition").click();
      const nativeBefore = await poll(async () => {
        const value = await health("waiting-for-native-sam");
        return value.service.active && value.service.processor.active
          && !value.service.processor.native_cpu_active ? value : null;
      }, TIMEOUT, "real native SAM job admission");
      assert.ok(nativeBefore.service.cache.pins > 0);
      markAction(page, "cancel-native-wait-and-clear-page");
      await page.getByTestId("cancel-work").click();
      cancelWindow = false;
      await assertEmpty(page);
      const nativeAfter = await health("after-ui-cancel");
      assert.equal(nativeAfter.service.active, true, "UI abort must not release active native ownership early.");
      assert.equal(nativeAfter.service.processor.active, true);
      assert.ok(nativeAfter.service.cache.pins > 0);
      await poll(async () => {
        const value = await health("draining-cancelled-native");
        return !value.service.active && !value.service.processor.active
          && !value.service.native_cpu_active && !value.service.processor.native_cpu_active ? value : null;
      }, TIMEOUT, "cancelled native SAM drain");
      await connectExisting(page, sid);
      assert.equal(await page.evaluate(() => window.__researchSessionTools.sourceDigest()), sourceDigest);
      await captureOriginalState(page);
      await page.getByTestId("target-condition").fill(String(plan.target_condition));
      markAction(page, "stage-for-reviewed-target");
      await page.getByTestId("stage-condition").click();
      await page.waitForFunction(() => {
        const s = window.__researchSessionTools.state();
        return s.pendingStage && !s.busy;
      }, undefined, { timeout: TIMEOUT });
      await noUiError(page);
      await expect(page.locator("#review-area")).toBeVisible();
      const staged = (await state(page)).pendingStage;
      for (const key of ["source_fingerprint", "generated_sha256", "fit_sha256"])
        assert.equal(staged[key], review[key], `The inspected review cannot be reused for a different ${key}.`);
      const prefix = `/research/sessions/${sid}/stages/${staged.stage_id}`;
      const preview = await getAsset(`${prefix}/preview.png`, "assets/staged-preview.png");
      const fit = await getAsset(`${prefix}/fit.json`, "assets/staged-fit.json");
      assert.equal(preview.sha256, review.generated_sha256);
      assert.equal(fit.sha256, review.fit_sha256);
      report.review_binding = { staged, preview, fit, approved_review: plan.approved_review,
        reviewer_kind: review.reviewer_kind, exact_three_sha: true };
      await page.getByTestId("review-allowed").setInputFiles(maskPaths.allowed);
      await page.getByTestId("review-occluded").setInputFiles(maskPaths.occluded);
      for (const key of ["reviewer", "method", "version"])
        await page.getByTestId(`review-${key}`).fill(review[key]);
      await page.getByTestId("review-kind").selectOption(review.reviewer_kind);
      markAction(page, "register-frozen-ai-review");
      const registrationUrl = `${serviceBase}${prefix}/reviews`;
      const registrationResponsePromise = page.waitForResponse(response =>
        response.url() === registrationUrl && response.request().method() === "POST",
      { timeout: TIMEOUT });
      const [registrationResponse] = await Promise.all([registrationResponsePromise, (async () => {
        await page.getByTestId("register-review").click();
        await conditionBound(page);
      })()]);
      assert.equal(registrationResponse.url(), registrationUrl);
      assert.equal(new URL(registrationResponse.url()).origin, serviceBase);
      assert.equal(new URL(registrationResponse.url()).pathname, `${prefix}/reviews`);
      assert.equal(new URL(registrationResponse.url()).search, "");
      assert.equal(registrationResponse.request().method(), "POST");
      assert.equal(registrationResponse.request().redirectedFrom(), null);
      assert.equal(registrationResponse.fromServiceWorker(), false);
      assert.equal(registrationResponse.status(), 200);
      assert.equal(registrationResponse.headers()["content-type"]?.split(";", 1)[0], "application/json");
      const registrationBytes = await registrationResponse.body();
      assert.ok(registrationBytes.length > 0 && registrationBytes.length <= 256 * 1024);
      report.review_binding.register_response = await save("assets/register-response.json", registrationBytes);
      report.review_binding.register_request = { method: "POST", url: registrationUrl, status: 200 };
      const registration = JSON.parse(registrationBytes.toString("utf8"));
      assert.equal(registration.session_id, sid);
      assert.equal(registration.condition, plan.target_condition);
      assert.equal(registration.kind, "sam_registered_uv");
      assert.deepEqual(registration.source_age, sourceAge());
      assert.equal(typeof registration.provenance_json_b64, "string");
      const nativeProvenance = Buffer.from(registration.provenance_json_b64, "base64");
      assert.ok(nativeProvenance.length > 0 && nativeProvenance.length <= 256 * 1024);
      assert.equal(nativeProvenance.toString("base64"), registration.provenance_json_b64);
      // Archive the exact decoded native bytes; never reconstruct them with JSON.stringify.
      report.review_binding.native_provenance = await save("assets/native-provenance.json", nativeProvenance);
      const provenance = JSON.parse(nativeProvenance.toString("utf8"));
      assert.deepEqual(provenance, registration.provenance);
      assert.equal(provenance.source_fingerprint, staged.source_fingerprint);
      assert.equal(provenance.generated_sha256, staged.generated_sha256);
      assert.equal(provenance.target_fit_sha256, staged.fit_sha256);
      assert.equal(provenance.target_condition, plan.target_condition);
      const targetPrefix = `/research/sessions/${sid}/conditions/${plan.target_condition}`;
      report.target = { condition: plan.target_condition,
        glb: await getAsset(`${targetPrefix}/mesh.glb`, "assets/target.glb"),
        texture: await getAsset(`${targetPrefix}/texture.png`, "assets/target-texture.png") };
      const targetGlb = glbDocument(await readFile(repoPath(report.target.glb.path)));
      assert.deepEqual(geometryHashes(targetGlb), report.source.geometry_hashes);
      assert.deepEqual(embeddedPng(targetGlb), await readFile(repoPath(report.target.texture.path)));
      entry.cancel_native_lease_verified = true;
    } else {
      const rpcBefore = report.rpc.length;
      await connectExisting(page, report.source.session_id);
      await captureOriginalState(page);
      await page.getByTestId("target-condition").fill(String(plan.target_condition));
      markAction(page, "load-registered-condition-from-cache");
      await page.getByTestId("load-condition").click();
      await conditionBound(page);
      assert.ok(report.rpc.slice(rpcBefore).every(item => item.method === "GET"),
        `${browserLabel} must reuse the registered assets without upload, generation, or registration.`);
      entry.cached_condition_get_only = true;
    }

    markAction(page, "restore-source-before-display-cases");
    await idle(page);
    await expect(page.getByTestId("restore-source")).toBeEnabled();
    entry.graphics_before_restore = await deadline(graphicsState(page), 5000, "pre-restore graphics observation");
    await trackDisplayImage(page);
    await page.getByTestId("restore-source").click();
    await assertRestored(page);
    const originalSnapshot = await snapshot(page);
    assert.deepEqual(originalSnapshot.geometry_hashes, report.source.geometry_hashes);
    for (const material of originalSnapshot.materials) {
      assert.equal(material.transparent, false);
      assert.equal(material.alphaTest, 0.5);
      assert.equal(material.depthWrite, true);
      assert.equal(material.premultipliedAlpha, false);
    }
    entry.original_materials = originalSnapshot.materials;
    const rpcStart = report.rpc.length;
    for (let index = 0; index < plan.display_ages.length; index++) {
      const age = plan.display_ages[index];
      markAction(page, `display-range-${index + 1}-${age}`);
      // Exercise the actual range input handler. Never call sampler/showAge directly.
      await page.getByTestId("display-age").evaluate((input, value) => {
        input.value = String(value);
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }, age);
      await rendered(page);
      await noUiError(page);
      const current = await state(page);
      assert.equal(current.selectedAge, age);
      assert.equal(current.displayMode, "research-blend");
      assert.equal(current.exactSourceDisplay, age === plan.source_age);
      assert.deepEqual(current.sourceAge, sourceAge());
      assert.deepEqual(current.geometryHashes, report.source.geometry_hashes);
      assert.deepEqual(current.anchorAges, [plan.source_age, plan.target_condition].sort((a, b) => a - b));
      const actual = await snapshot(page);
      assert.deepEqual(actual.geometry_hashes, report.source.geometry_hashes);
      assert.equal(actual.model_unchanged, true);
      assert.equal(actual.geometry_objects_unchanged, true);
      assert.deepEqual(actual.source_age, sourceAge());
      assert.equal(actual.research_display.target_condition, age);
      assert.equal(actual.research_display.source_research_label, plan.source_age);
      assert.equal(actual.research_display.exact_source, age === plan.source_age);
      assert.equal(actual.research_display.rendered_derivative, true);
      for (const material of actual.materials) assertBlend(material);
      const frame = await page.evaluate(() => window.__researchSessionTools.frameDigest());
      assert.match(frame, SHA);
      const stem = `${browserLabel}-${String(index + 1).padStart(2, "0")}-${String(age).replace(".", "_")}`;
      const display = await download(page, "export-display-glb", `${stem}.glb`);
      assert.notEqual(display.sha256, report.source.glb.sha256, "Display derivatives must not masquerade as original source bytes.");
      const document = glbDocument(await readFile(repoPath(display.path)));
      assert.deepEqual(geometryHashes(document), report.source.geometry_hashes);
      const displayMetadata = extras(document.json, "research_display");
      assert.ok(displayMetadata.length > 0);
      for (const metadata of displayMetadata) assert.deepEqual(metadata, actual.research_display);
      const sourceAges = extras(document.json, "source_age");
      assert.ok(sourceAges.length > 0);
      for (const value of sourceAges) assert.deepEqual(value, sourceAge());
      for (const material of document.json.materials) assert.equal(material.alphaMode, "BLEND");
      const png = embeddedPng(document);
      const pngPin = await save(`${stem}-embedded.png`, png);
      const viewPng = await download(page, "export-png", `${stem}-view.png`);
      const screenshot = `${stem}-page.png`;
      await page.screenshot({ path: join(output, screenshot), fullPage: true });
      report.records.push({ browser: browserLabel, age, frame_rgba_sha256: frame,
        exported_glb: display, embedded_png: pngPin, view_png: viewPng,
        page_screenshot: relativePath(join(output, screenshot)),
        geometry_hashes: actual.geometry_hashes, materials: actual.materials,
        display_metadata: actual.research_display });
    }
    assert.equal(report.rpc.length, rpcStart, "Local display and export must send no research API request.");
    const decimal = plan.display_ages.find(age => !Number.isInteger(age));
    markAction(page, `display-decimal-number-${decimal}`);
    await page.getByTestId("display-age-number").fill(String(decimal));
    await page.getByTestId("display-age-number").dispatchEvent("change");
    await trackDisplayImage(page);
    assert.equal((await state(page)).selectedAge, decimal);
    await noUiError(page);
    entry.decimal_number_input = decimal;
    const intermediate = report.records.find(record => record.browser === browserLabel
      && record.age > Math.min(plan.source_age, plan.target_condition)
      && record.age < Math.max(plan.source_age, plan.target_condition));
    markAction(page, "reimport-display-derivative-and-render");
    entry.roundtrip = await reimport(page, await readFile(repoPath(intermediate.exported_glb.path)));
    assert.deepEqual(entry.roundtrip.geometry_hashes, report.source.geometry_hashes);
    assert.deepEqual(entry.roundtrip.source_age, sourceAge());
    assert.equal(entry.roundtrip.source_viewer_unchanged, true);
    for (const material of entry.roundtrip.materials) {
      assert.equal(material.transparent, true);
      assert.equal(material.alphaTest, 0);
      assert.equal(material.flipY, false);
      assert.equal(material.colorSpace, "srgb");
    }
    markAction(page, "restore-source-after-display-and-reimport");
    await trackDisplayImage(page);
    await page.getByTestId("restore-source").click();
    entry.restored = await assertRestored(page);
    const restoredDownload = await download(page, "download-source-glb", `${browserLabel}-original-restored.glb`);
    assert.equal(restoredDownload.sha256, report.source.glb.sha256);
    entry.original_download = restoredDownload;
    assert.deepEqual((await jsonGet(`/research/sessions/${report.source.session_id}`)).source_age, sourceAge());
    // Exercise invalidation while a real DataTexture is active, without submitting the replacement.
    markAction(page, "activate-display-before-file-replacement");
    await page.getByTestId("display-age-number").fill(String(decimal));
    await page.getByTestId("display-age-number").dispatchEvent("change");
    await trackDisplayImage(page);
    markAction(page, "replace-local-photo-without-upload");
    await page.getByTestId("source-file").evaluate(async input => {
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = 1;
      const blob = await new Promise(resolveBlob => canvas.toBlob(resolveBlob, "image/png"));
      const transfer = new DataTransfer();
      transfer.items.add(new File([blob], "local-state-reset-only.png", { type: "image/png" }));
      input.files = transfer.files;
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await assertEmpty(page);
    entry.file_replacement_released_images = await assertTrackedImagesReleased(page);
    assert.equal(await page.getByTestId("source-age").inputValue(), "");
    entry.file_replacement_cleared = true;
    // Reload existing cached assets so pagehide releases a currently owned texture as well.
    await connectExisting(page, report.source.session_id);
    await page.getByTestId("target-condition").fill(String(plan.target_condition));
    markAction(page, "load-cached-condition-before-pagehide");
    await page.getByTestId("load-condition").click();
    await conditionBound(page);
    await trackDisplayImage(page);
    markAction(page, "dispatch-pagehide-with-active-display");
    await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent("pagehide")));
    const disposed = await state(page);
    assert.equal(disposed.destroyed, true);
    assert.equal(disposed.objectUrls, 0);
    entry.pagehide = await page.evaluate(() => {
      const viewer = window.__researchSessionTools.viewer();
      return { model: viewer.model === null, disposed: viewer.disposed,
        research_texture: viewer.researchTexture === null,
        material_states: viewer.researchMaterialStates.size, canvas_count: document.querySelectorAll("#viewer canvas").length };
    });
    assert.deepEqual(entry.pagehide, { model: true, disposed: true, research_texture: true,
      material_states: 0, canvas_count: 0 });
    entry.pagehide_released_images = await assertTrackedImagesReleased(page);
    markAction(page, "close-owned-page-context-and-browser");
    await page.close();
    activePage = undefined;
    await context.close();
    await browser.close();
    browser = undefined;
    assert.deepEqual(entry.page_errors, []);
    assert.deepEqual(entry.request_failures, []);
    assert.deepEqual(entry.unexpected_http_failures, []);
    assert.deepEqual(entry.external_requests, []);
    if (caseIndex === 0) assert.equal(entry.expected_cancel_requests.length, 1);
    else assert.deepEqual(entry.expected_cancel_requests, []);
    entry.status = "passed";
  }
  assert.equal(report.records.length, plan.display_ages.length * browserCases.length);
  await health("before-owned-close");
} catch (error) {
  failed = error;
  report.error = error instanceof Error ? error.stack : String(error);
  if (activePage && !activePage.isClosed()) {
    try {
      report.failure_page_state = await deadline(activePage.evaluate(() => {
        const button = document.querySelector('[data-testid="restore-source"]');
        const bounds = button?.getBoundingClientRect();
        const style = button && getComputedStyle(button);
        return {
          state: window.__researchSessionTools?.state(),
          restore: button && { html: button.outerHTML, bounds: bounds?.toJSON(),
            disabled: button.matches(":disabled"), display: style.display,
            visibility: style.visibility, opacity: style.opacity },
          scroll: { x: scrollX, y: scrollY, height: document.documentElement.scrollHeight,
            width: innerWidth, viewport_height: innerHeight },
          error: document.querySelector("#error")?.textContent,
          status: document.querySelector("#status")?.textContent,
          frame_telemetry: { ...window.__liveFrameTelemetry, now_ms: performance.now(), visibility: document.visibilityState },
        };
      }), 5000, "failure page observation");
      report.failure_graphics_state = await deadline(graphicsState(activePage), 5000, "failure graphics observation");
      const failureScreenshot = join(output, "failure-page.png");
      await activePage.screenshot({ path: failureScreenshot, fullPage: true, timeout: 5000 });
      const screenshotBytes = await readFile(failureScreenshot);
      report.failure_page_screenshot = { path: relativePath(failureScreenshot),
        bytes: screenshotBytes.length, sha256: hash(screenshotBytes) };
    } catch (observationError) {
      report.failure_observation_error = String(observationError);
    }
  }
} finally {
  const cleanupError = error => {
    failed ??= error;
    (report.cleanup.errors ??= []).push(error instanceof Error ? error.stack : String(error));
  };
  for (const [name, action] of [["browser_closed", () => browser?.close()], ["vite_closed", () => vite?.close()]]) {
    try { await action(); report.cleanup[name] = true; }
    catch (error) { report.cleanup[name] = false; cleanupError(error); }
  }
  if (child) {
    try {
      const control = join(output, "server-control");
      let closed = null;
      try { closed = JSON.parse(await readFile(join(control, "closed.json"), "utf8")); }
      catch (error) { if (error.code !== "ENOENT") throw error; }
      if (serverPid === null) {
        for (const name of ["ready.json", "closed.json"]) {
          try {
            const receipt = JSON.parse(await readFile(join(control, name), "utf8"));
            if (Number.isSafeInteger(receipt.pid) && receipt.pid > 0) { serverPid = receipt.pid; break; }
          } catch (error) { if (error.code !== "ENOENT") throw error; }
        }
      }
      report.cleanup.server_pid = serverPid;
      report.cleanup.launcher_pid = child.pid;
      if (closed) report.cleanup.server_receipt = closed;
      // A failed startup can close without ever publishing ready. Do not send a launcher PID.
      if (!childExitResult && !closed) {
        assert.ok(serverPid !== null, "Service has no ready/closed actual PID; cannot issue an owned stop request.");
        await writeFile(join(control, "stop.json"), JSON.stringify({ pid: serverPid, stop: true }), { flag: "wx" });
      }
      const exit = await deadline(childExit, TIMEOUT, "owned research service graceful shutdown");
      report.cleanup.child_exit = exit;
      closed ??= JSON.parse(await readFile(join(control, "closed.json"), "utf8"));
      report.cleanup.server_closed = relativePath(join(control, "closed.json"));
      report.cleanup.server_receipt = closed;
      assert.deepEqual(exit, { code: 0, signal: null });
      assert.equal(closed.status, "closed");
      assert.equal(closed.pid, serverPid);
      assert.equal(closed.environment_unchanged, true);
      assert.deepEqual(closed.cleanup_errors, []);
      assert.equal(closed.service_after_close.closed, true);
      assert.equal(closed.service_after_close.active, false);
      assert.equal(closed.service_after_close.native_cpu_active, false);
      assert.equal(closed.service_after_close.processor.closed, true);
      assert.equal(closed.service_after_close.processor.active, false);
      assert.equal(closed.service_after_close.processor.native_cpu_active, false);
      assert.equal(closed.service_after_close.cache.pins, 0);
      assert.equal(closed.service_after_close.cache.entries, 0);
      assert.equal(closed.service_after_close.downloads, 0);
      assert.equal(closed.worker_after_close.closed, true);
      assert.equal(closed.worker_after_close.busy, false);
      assert.equal(closed.worker_after_close.forced_termination, false);
      assert.equal(closed.worker_after_close.returncode, 0);
      assert.equal(closed.worker_after_close.worker_exitcode, 0);
      assert.equal(closed.counts.source_builds, 1);
      assert.ok(closed.counts.sam_generate_calls >= 1);
      assert.ok(closed.counts.target_refits >= 1);
      report.cleanup.owned_server_closed = true;
    } catch (error) { report.cleanup.owned_server_closed = false; cleanupError(error); }
  }
  for (const stream of childLogs) {
    try { await new Promise((resolveEnd, rejectEnd) => { stream.once("error", rejectEnd); stream.end(resolveEnd); }); }
    catch (error) { cleanupError(error); }
  }
  try {
    await checkPins(allPins);
    await checkPin(reviewPath, plan.approved_review);
    assert.equal(hash(await readFile(planPath)), hash(planBytes));
    report.cleanup.inputs_unchanged = true;
  } catch (error) { report.cleanup.inputs_unchanged = false; cleanupError(error); }
  report.interrupted = interrupted;
  if (interrupted && !failed) cleanupError(new Error("Live research interrupted by its owner."));
  report.status = failed ? "failed" : "passed";
  report.finished_at_utc = new Date().toISOString();
  await writeFile(join(output, "report.json"), JSON.stringify(report, null, 2), { flag: "wx" });
  process.removeListener("SIGINT", interrupt);
  process.removeListener("SIGTERM", interrupt);
  process.removeListener("message", parentMessage);
  if (process.connected) process.disconnect();
}
if (failed) throw failed;
console.log(JSON.stringify({ status: report.status, report: relativePath(join(output, "report.json")),
  browser_count: report.browsers.length, display_records: report.records.length,
  route_mocks: false, service_ready: false, g3_complete: false, owned_server_closed: report.cleanup.owned_server_closed }));

function hash(bytes) { return createHash("sha256").update(bytes).digest("hex"); }
function inside(parent, childPath) {
  const path = relative(parent, childPath);
  return path !== "" && !isAbsolute(path) && path !== ".." && !path.startsWith(`..${sep}`);
}
function repoPath(path) {
  assert.equal(typeof path, "string");
  assert.ok(path && !isAbsolute(path) && !path.includes(":"), "Expected a repository-relative path.");
  const absolute = resolve(ROOT, path);
  assert.ok(inside(ROOT, absolute), "Path escaped the repository.");
  return absolute;
}
function relativePath(path) { return relative(ROOT, path).split(sep).join("/"); }
function sourceAge() { return { value: plan.source_age, method: "user", calibration_id: null }; }
async function checkPin(path, expected) {
  assert.ok(Number.isSafeInteger(expected.bytes) && expected.bytes >= 0);
  assert.match(expected.sha256, SHA);
  const actual = await stat(path);
  assert.equal(actual.isFile(), true);
  assert.equal(actual.size, expected.bytes, `Frozen byte size changed: ${relativePath(path)}`);
  assert.equal(await fileHash(path), expected.sha256, `Frozen SHA changed: ${relativePath(path)}`);
}
async function fileHash(path) {
  const digest = createHash("sha256");
  for await (const chunk of createReadStream(path)) digest.update(chunk);
  return digest.digest("hex");
}
async function checkPins(values) { for (const value of values) await checkPin(value.absolute, value); }
async function save(path, bytes) {
  const absolute = resolve(output, path);
  assert.ok(inside(output, absolute));
  await writeFile(absolute, bytes, { flag: "wx" });
  return { path: relativePath(absolute), bytes: bytes.length, sha256: hash(bytes) };
}
async function deadline(promise, timeout, label) {
  let timer;
  try { return await Promise.race([promise, new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`Timed out: ${label}`)), timeout);
  })]); } finally { clearTimeout(timer); }
}
async function poll(action, timeout, label) {
  const until = Date.now() + timeout;
  while (Date.now() < until) {
    assert.equal(interrupted, false, "Live research interrupted.");
    const value = await action();
    if (value) return value;
    await new Promise(resolveDelay => setTimeout(resolveDelay, 100));
  }
  throw new Error(`Timed out: ${label}`);
}
async function fetchReal(path) {
  const url = new URL(path, serviceBase);
  assert.equal(url.origin, serviceBase);
  const record = { browser: "node-owner", method: "GET", path: url.pathname,
    action: "owner-read-real-service", status: null, started_at_utc: new Date().toISOString() };
  report.rpc.push(record);
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(30_000), cache: "no-store" });
    record.status = response.status;
    record.response_at_utc = new Date().toISOString();
    assert.equal(response.status, 200, `Real service GET failed: ${url.pathname}`);
    const bytes = Buffer.from(await response.arrayBuffer());
    record.finished_at_utc = new Date().toISOString();
    record.response_bytes = bytes.length;
    return bytes;
  } catch (error) {
    record.failed_at_utc = new Date().toISOString();
    record.failure = error instanceof Error ? error.stack : String(error);
    throw error;
  }
}
async function jsonGet(path) { return JSON.parse((await fetchReal(path)).toString("utf8")); }
async function getAsset(path, outputPath) { return save(outputPath, await fetchReal(path)); }
async function health(label) {
  const value = await jsonGet("/research/health");
  assert.equal(value.research_only, true);
  for (const key of ["service_ready", "production_enabled", "g3_complete"]) assert.equal(value[key], false);
  assert.deepEqual(value.capabilities, { reconstruction: false, age_morph: false, age_texture: false, realtime: false });
  report.health_samples.push({ label, at_utc: new Date().toISOString(), ...value });
  return value;
}
async function state(page) { return page.evaluate(() => window.__researchSessionTools.state()); }
function markAction(page, action) { page.__liveSetAction?.(action); }
async function graphicsState(page) {
  return page.evaluate(() => {
    const viewer = window.__researchSessionTools.viewer();
    const gl = viewer.renderer.getContext();
    const debug = gl.getExtension("WEBGL_debug_renderer_info");
    return {
      visibility: document.visibilityState,
      context_lost: gl.isContextLost(), viewer_context_lost: viewer.lostContext,
      vendor: gl.getParameter(gl.VENDOR), renderer: gl.getParameter(gl.RENDERER),
      version: gl.getParameter(gl.VERSION),
      unmasked_vendor: debug ? gl.getParameter(debug.UNMASKED_VENDOR_WEBGL) : null,
      unmasked_renderer: debug ? gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) : null,
      heartbeat: { ...window.__liveFrameTelemetry, now_ms: performance.now() },
    };
  });
}
async function noUiError(page) {
  assert.equal(await page.getByTestId("error").isVisible(), false,
    await page.getByTestId("error").textContent());
}
async function idle(page) {
  await page.waitForFunction(() => !window.__researchSessionTools.state().busy, undefined, { timeout: TIMEOUT });
  await noUiError(page);
}
async function bound(page) {
  await page.waitForFunction(() => {
    const value = window.__researchSessionTools.state();
    return value.hasSourceBytes && !value.busy;
  }, undefined, { timeout: TIMEOUT });
  await noUiError(page);
}
async function conditionBound(page) {
  await page.waitForFunction(condition => {
    const value = window.__researchSessionTools.state();
    return value.conditionAges.includes(condition) && !value.busy;
  }, plan.target_condition, { timeout: TIMEOUT });
  await noUiError(page);
}
async function connectExisting(page, sid) {
  markAction(page, "connect-existing-source-session");
  await page.locator("details.existing-session").evaluate(details => { details.open = true; });
  await page.getByTestId("existing-session-id").fill(sid);
  await page.getByTestId("connect-existing").click();
  await bound(page);
  assert.equal((await state(page)).sessionId, sid);
}
async function assertEmpty(page) {
  const value = await state(page);
  assert.equal(value.hasSourceBytes, false);
  assert.equal(value.sessionId, null);
  assert.equal(value.sourceAge, null);
  assert.equal(value.geometryHashes, null);
  assert.equal(value.pendingStage, null);
  assert.deepEqual(value.anchorAges, []);
  assert.deepEqual(value.conditionAges, []);
  assert.equal(value.objectUrls, 0);
  assert.equal(await page.evaluate(() => window.__researchSessionTools.viewer().model), null);
  for (const id of ["restore-source", "download-source-glb", "export-display-glb", "export-png", "display-age"])
    assert.equal(await page.getByTestId(id).isDisabled(), true);
  await expect(page.locator("#review-area")).toBeHidden();
}
async function rendered(page) {
  await page.evaluate(() => new Promise(resolveFrame => requestAnimationFrame(() => requestAnimationFrame(resolveFrame))));
}
async function captureOriginalState(page) {
  await page.evaluate(() => {
    const viewer = window.__researchSessionTools.viewer();
    const meshes = [];
    viewer.model.traverse(node => { if (node.isMesh) meshes.push(node); });
    window.__liveOriginal = { model: viewer.model, meshes,
      geometry: meshes.map(mesh => mesh.geometry), materials: meshes.flatMap(mesh =>
        (Array.isArray(mesh.material) ? mesh.material : [mesh.material]).map(material => ({ material,
          map: material.map, transparent: material.transparent, alphaTest: material.alphaTest,
          depthWrite: material.depthWrite, premultipliedAlpha: material.premultipliedAlpha, opacity: material.opacity }))) };
  });
}
async function trackDisplayImage(page) {
  return page.evaluate(() => {
    const texture = window.__researchSessionTools.viewer().researchTexture;
    if (!texture) return null;
    if (texture.isDataTexture !== true || !ArrayBuffer.isView(texture.image?.data)
      || texture.image.width !== 256 || texture.image.height !== 256
      || texture.image.data.byteLength !== 256 * 256 * 4)
      throw new Error("Expected an owned 256x256 RGBA DataTexture before clearing display.");
    const images = window.__liveResearchImages ??= [];
    if (!images.includes(texture.image)) images.push(texture.image);
    return { tracked_images: images.length, width: texture.image.width,
      height: texture.image.height, byte_length: texture.image.data.byteLength };
  });
}
async function assertTrackedImagesReleased(page) {
  const result = await page.evaluate(() => {
    const images = window.__liveResearchImages ?? [];
    return { tracked_images: images.length, every_image_released: images.every(image =>
      image.data.byteLength === 0 && image.width === 0 && image.height === 0) };
  });
  assert.ok(result.tracked_images > 0, "Capture a real DataTexture image before checking disposal.");
  assert.equal(result.every_image_released, true);
  return result;
}
async function snapshot(page) {
  await trackDisplayImage(page);
  return page.evaluate(async () => {
    const viewer = window.__researchSessionTools.viewer();
    const meshes = [];
    viewer.model.traverse(node => { if (node.isMesh) meshes.push(node); });
    if (meshes.length !== 1) throw new Error("Expected one frozen source mesh.");
    const geometry = meshes[0].geometry;
    const digest = async array => [...new Uint8Array(await crypto.subtle.digest("SHA-256",
      new Uint8Array(array.buffer, array.byteOffset, array.byteLength)))].map(value => value.toString(16).padStart(2, "0")).join("");
    const hashes = {};
    for (const [name, attribute] of [["POSITION", "position"], ["NORMAL", "normal"], ["TEXCOORD_0", "uv"]])
      hashes[name] = await digest(geometry.getAttribute(attribute).array);
    hashes.indices = await digest(geometry.index.array);
    const materials = meshes.flatMap(mesh => (Array.isArray(mesh.material) ? mesh.material : [mesh.material])
      .map(material => ({ transparent: material.transparent, alphaTest: material.alphaTest,
        depthWrite: material.depthWrite, premultipliedAlpha: material.premultipliedAlpha,
        opacity: material.opacity, colorSpace: material.map?.colorSpace, flipY: material.map?.flipY,
        is_data_texture: material.map?.isDataTexture === true })));
    return { geometry_hashes: hashes, model_unchanged: viewer.model === window.__liveOriginal.model,
      geometry_objects_unchanged: meshes.every((mesh, index) => mesh === window.__liveOriginal.meshes[index]
        && mesh.geometry === window.__liveOriginal.geometry[index]),
      source_age: viewer.model.userData.source_age, research_display: viewer.model.userData.research_display ?? null,
      materials };
  });
}
function assertBlend(material) {
  assert.equal(material.is_data_texture, true);
  assert.equal(material.transparent, true);
  assert.equal(material.alphaTest, 0);
  assert.equal(material.depthWrite, false);
  assert.equal(material.premultipliedAlpha, false);
  assert.equal(material.opacity, 1);
  assert.equal(material.colorSpace, "srgb");
  assert.equal(material.flipY, false);
}
async function assertRestored(page) {
  const result = await page.evaluate(() => {
    const viewer = window.__researchSessionTools.viewer();
    const states = window.__liveOriginal.materials;
    return { original_maps_and_flags: states.every(({ material, ...expected }) =>
      Object.entries(expected).every(([key, value]) => material[key] === value)),
      same_model: viewer.model === window.__liveOriginal.model,
      research_display_removed: !Object.hasOwn(viewer.model.userData, "research_display"),
      texture_released: viewer.researchTexture === null,
      material_states: viewer.researchMaterialStates.size };
  });
  assert.deepEqual(result, { original_maps_and_flags: true, same_model: true,
    research_display_removed: true, texture_released: true, material_states: 0 });
  assert.equal((await state(page)).displayMode, "original");
  assert.equal(await page.evaluate(() => window.__researchSessionTools.frameDigest()), null);
  return { ...result, released_images: await assertTrackedImagesReleased(page) };
}
async function download(page, id, name) {
  markAction(page, `download-${id}-${name}`);
  const event = page.waitForEvent("download");
  await page.getByTestId(id).click();
  const file = await event;
  assert.equal(await file.failure(), null);
  const path = join(output, name);
  await file.saveAs(path);
  await idle(page);
  const bytes = await readFile(path);
  return { path: relativePath(path), bytes: bytes.length, sha256: hash(bytes) };
}
function glbDocument(bytes) {
  assert.equal(bytes.toString("ascii", 0, 4), "glTF");
  assert.equal(bytes.readUInt32LE(4), 2);
  assert.equal(bytes.readUInt32LE(8), bytes.length);
  const chunks = [];
  for (let offset = 12; offset < bytes.length;) {
    const length = bytes.readUInt32LE(offset), type = bytes.readUInt32LE(offset + 4);
    assert.ok(length % 4 === 0 && offset + 8 + length <= bytes.length);
    chunks.push({ type, bytes: bytes.subarray(offset + 8, offset + 8 + length) });
    offset += 8 + length;
  }
  assert.equal(chunks.length, 2);
  assert.equal(chunks[0].type, 0x4e4f534a);
  assert.equal(chunks[1].type, 0x004e4942);
  const json = JSON.parse(chunks[0].bytes.toString("utf8"));
  assert.equal(json.asset.version, "2.0");
  assert.equal(json.buffers.length, 1);
  assert.equal(json.buffers[0].uri, undefined);
  assert.equal(json.meshes.length, 1);
  assert.equal(json.meshes[0].primitives.length, 1);
  const primitive = json.meshes[0].primitives[0];
  assert.ok(!primitive.targets?.length);
  assert.ok(primitive.mode === undefined || primitive.mode === 4);
  return { json, bin: chunks[1].bytes, primitive };
}
function accessorBytes(document, index) {
  const accessor = document.json.accessors[index];
  assert.ok(accessor && !accessor.sparse && accessor.normalized !== true);
  const view = document.json.bufferViews[accessor.bufferView];
  assert.equal(view.buffer, 0);
  const component = { 5121: 1, 5123: 2, 5125: 4, 5126: 4 }[accessor.componentType];
  const count = { SCALAR: 1, VEC2: 2, VEC3: 3 }[accessor.type];
  assert.ok(component && count && Number.isSafeInteger(accessor.count));
  const size = component * count;
  assert.ok(view.byteStride === undefined || view.byteStride === size, "Packed frozen geometry is required.");
  const start = (view.byteOffset ?? 0) + (accessor.byteOffset ?? 0);
  const end = start + size * accessor.count;
  assert.ok(end <= document.bin.length && end <= (view.byteOffset ?? 0) + view.byteLength);
  return document.bin.subarray(start, end);
}
function geometryHashes(document) {
  return Object.fromEntries(geometryNames.map(key => [key, hash(accessorBytes(document,
    key === "indices" ? document.primitive.indices : document.primitive.attributes[key]))]));
}
function embeddedPng(document) {
  const material = document.json.materials[document.primitive.material];
  const texture = document.json.textures[material.pbrMetallicRoughness.baseColorTexture.index];
  const image = document.json.images[texture.source];
  assert.equal(image.mimeType, "image/png");
  assert.equal(image.uri, undefined);
  const view = document.json.bufferViews[image.bufferView];
  assert.equal(view.buffer, 0);
  const result = document.bin.subarray(view.byteOffset ?? 0, (view.byteOffset ?? 0) + view.byteLength);
  assert.equal(result.subarray(0, 8).toString("hex"), "89504e470d0a1a0a");
  return result;
}
function extras(document, key) {
  const values = [];
  const visit = object => {
    if (!object || typeof object !== "object") return;
    if (Object.hasOwn(object, key)) values.push(object[key]);
    for (const value of Object.values(object)) visit(value);
  };
  visit(document);
  return values;
}
async function reimport(page, bytes) {
  return page.evaluate(async ({ encoded, options }) => {
    const { FaceViewer } = await import("/src/viewer.ts");
    const container = document.createElement("div");
    Object.assign(container.style, { width: "256px", height: "256px", position: "fixed", left: "-1000px" });
    document.body.append(container);
    const errors = [];
    const viewer = new FaceViewer(container, { onError: message => errors.push(message) }, { initialDemo: false });
    try {
      const data = Uint8Array.from(atob(encoded), value => value.charCodeAt(0));
      await viewer.loadResearchModelBytes(data.buffer, options);
      viewer.setAutoRotate(false);
      viewer.setView("front");
      await new Promise(resolveFrame => requestAnimationFrame(() => requestAnimationFrame(resolveFrame)));
      const gl = viewer.renderer.getContext();
      if (gl.isContextLost() || gl.getError() !== gl.NO_ERROR)
        throw new Error("Reimport WebGL context is lost or reports an error before rendering.");
      const width = gl.drawingBufferWidth, height = gl.drawingBufferHeight;
      if (width < 1 || height < 1) throw new Error("Reimport has an empty drawing buffer.");
      const gridVisible = viewer.grid.visible, modelVisible = viewer.model.visible;
      const rendered = {};
      try {
        viewer.grid.visible = false;
        const pixels = visible => {
          viewer.model.visible = visible;
          viewer.renderer.setRenderTarget(null);
          viewer.renderer.render(viewer.scene, viewer.camera);
          const rgba = new Uint8Array(width * height * 4);
          gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, rgba);
          if (gl.isContextLost() || gl.getError() !== gl.NO_ERROR)
            throw new Error("Reimport rendering/readPixels reports a WebGL error or context loss.");
          return rgba;
        };
        const visible = pixels(true), hidden = pixels(false);
        let changedPixels = 0;
        for (let offset = 0; offset < visible.length; offset += 4)
          if (visible[offset] !== hidden[offset] || visible[offset + 1] !== hidden[offset + 1]
            || visible[offset + 2] !== hidden[offset + 2]) changedPixels++;
        if (changedPixels === 0) throw new Error("Reimport rendered no RGB contribution from its actual model.");
        const rgbaHash = async values => [...new Uint8Array(await crypto.subtle.digest("SHA-256", values))]
          .map(value => value.toString(16).padStart(2, "0")).join("");
        Object.assign(rendered, { width, height, changed_rgb_pixels: changedPixels,
          visible_rgba_sha256: await rgbaHash(visible), hidden_rgba_sha256: await rgbaHash(hidden),
          webgl_error: gl.NO_ERROR, context_lost: false, grid_hidden_for_comparison: true });
      } finally {
        viewer.grid.visible = gridVisible;
        viewer.model.visible = modelVisible;
      }
      const meshes = [];
      viewer.model.traverse(node => { if (node.isMesh) meshes.push(node); });
      if (meshes.length !== 1) throw new Error("Reimport changed the static mesh count.");
      const geometry = meshes[0].geometry;
      const digest = async array => [...new Uint8Array(await crypto.subtle.digest("SHA-256",
        new Uint8Array(array.buffer, array.byteOffset, array.byteLength)))].map(value => value.toString(16).padStart(2, "0")).join("");
      const geometryHashes = {};
      for (const [name, attribute] of [["POSITION", "position"], ["NORMAL", "normal"], ["TEXCOORD_0", "uv"]])
        geometryHashes[name] = await digest(geometry.getAttribute(attribute).array);
      geometryHashes.indices = await digest(geometry.index.array);
      if (errors.length) throw new Error(errors.join("\n"));
      const materials = meshes.flatMap(mesh => (Array.isArray(mesh.material) ? mesh.material : [mesh.material])
        .map(material => ({ transparent: material.transparent, alphaTest: material.alphaTest,
          flipY: material.map?.flipY, colorSpace: material.map?.colorSpace })));
      return { geometry_hashes: geometryHashes, source_age: viewer.model.userData.source_age,
        materials, rendered, initial_demo: false,
        source_viewer_unchanged: window.__researchSessionTools.viewer().model === window.__liveOriginal.model };
    } finally { viewer.dispose(); container.remove(); }
  }, { encoded: bytes.toString("base64"), options: { asset_mode: "static",
    topology_id: report.source.topology_id, source_age: sourceAge(),
    capabilities: { age_morph: false, age_texture: false } } });
}
