import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { createWriteStream } from "node:fs";
import { mkdir, readFile, realpath, writeFile } from "node:fs/promises";
import { dirname, isAbsolute, join, relative, resolve } from "node:path";
import { pipeline } from "node:stream/promises";
import { fileURLToPath } from "node:url";

// Explicit offline research only. Each child owns and closes its loopback servers.
const repository = await realpath(fileURLToPath(new URL("../../", import.meta.url)));
assert.ok(process.env.AGEMORPH_RESEARCH_TARGET_REPORT,
  "Set AGEMORPH_RESEARCH_TARGET_REPORT to the registered-target UV report.");
const reportPath = await existingPath(process.env.AGEMORPH_RESEARCH_TARGET_REPORT);
const inputBytes = await readFile(reportPath);
const registrationReport = JSON.parse(inputBytes.toString("utf8"));
assert.ok(Array.isArray(registrationReport.records), "Target report needs records.");
assert.equal(registrationReport.records.length, 37,
  "The report must retain exactly the 37 frozen unique SAM requests.");
assert.ok(registrationReport.records.every((row) => row.status === "ok"),
  "Every frozen SAM request needs successful UV registration; failures cannot be filtered away.");
const records = registrationReport.records;
assert.equal(new Set(records.map((row) => row.sample_id)).size, records.length,
  "Registered target identifiers must be unique.");
for (const record of records) {
  assert.match(record.sample_id, /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,120}$/);
  assert.ok(typeof record.source_id === "string" && Number.isInteger(record.target_age));
  for (const name of ["glb", "result"]) await verifyPin(record.artifacts?.[name]);
}
const output = containedPath(process.env.AGEMORPH_RESEARCH_OUTPUT ??
  join(dirname(reportPath), "browser-roundtrip"));
await mkdir(dirname(output), { recursive: true });
assert.equal(await realpath(dirname(output)).then(isContained), true,
  "Output parent resolves outside the repository.");
await mkdir(output); // Existing evidence is never overwritten.
const childRunner = fileURLToPath(new URL("./static-mesh-research.mjs", import.meta.url));
const frontend = fileURLToPath(new URL("../", import.meta.url));
const batch = {
  schema_version: 1,
  evidenceKind: "offline-registered-target-atlas-browser-batch",
  startedAt: new Date().toISOString(),
  input: { path: relative(repository, reportPath).replaceAll("\\", "/"),
    sha256: sha256(inputBytes), bytes: inputBytes.length },
  requestedCases: records.length,
  requestedBrowserRoundtrips: records.length * 2,
  completedCases: 0,
  completedBrowserRoundtrips: 0,
  serviceInferenceVerified: false,
  g3Accepted: false,
  ageQualityAccepted: false,
  identityQualityAccepted: false,
  productionBuild: false,
  renderer: "Chromium software WebGL (SwiftShader)",
  status: "running",
  cases: [],
};
let activeChild;
let forceTimer;
let cancelled = false;
let failure;
const sourceFrames = new Map();
const commonUvPins = new Set();
const commonUvAttributes = new Set();
const requestChildStop = () => {
  if (!activeChild || activeChild.exitCode !== null || activeChild.signalCode !== null) return;
  if (activeChild.connected) activeChild.send({ type: "abort-research" }, () => {});
  if (!forceTimer) forceTimer = setTimeout(() => {
    if (!activeChild) return;
    batch.forcedChildTermination = true;
    if (process.platform === "win32") {
      spawn("taskkill", ["/pid", String(activeChild.pid), "/t", "/f"],
        { windowsHide: true, stdio: "ignore" });
    } else activeChild.kill("SIGKILL");
  }, 10_000);
};
const cancel = () => { cancelled = true; requestChildStop(); };
process.once("SIGINT", cancel);
process.once("SIGTERM", cancel);

try {
  for (const record of records) {
    assert.equal(cancelled, false, "Browser batch was interrupted.");
    const caseOutput = join(output, record.sample_id);
    await mkdir(caseOutput);
    const attempt = {
      sample_id: record.sample_id, source_id: record.source_id,
      target_age: record.target_age, status: "running", artifacts: [],
    };
    batch.cases.push(attempt);
    let childResult;
    try {
      childResult = await runChild(record, caseOutput);
      attempt.child = childResult;
      const childReportPath = join(caseOutput, "static-mesh-research.json");
      const childReport = JSON.parse(await readFile(childReportPath, "utf8"));
      attempt.report = await filePin(childReportPath);
      const completed = childReport.results.filter((result) => result.status === "passed");
      batch.completedBrowserRoundtrips += completed.length;
      attempt.completedBrowserRoundtrips = completed.length;
      for (const result of completed)
        for (const artifact of [result.exported.path, ...Object.values(result.screenshots)])
          attempt.artifacts.push(await filePin(await existingPath(artifact)));
      assert.equal(childResult.code, 0, "Browser child failed; inspect its preserved logs.");
      assert.equal(childResult.timedOut, false, "Browser child exceeded its research deadline.");
      assert.equal(childReport.status, "passed");
      assert.equal(childReport.ownedServersClosed, true);
      assert.equal(childReport.interrupted, false);
      assert.equal(childReport.generatedTargetAtlasVerification, true);
      assert.equal(childReport.ageTextureVerified, false);
      assert.equal(childReport.g3Accepted, false);
      assert.equal(childReport.input.sha256, record.artifacts.glb.sha256);
      const registration = childReport.input.registered_target_texture;
      assert.equal(registration.target_sample_id, record.sample_id);
      assert.equal(registration.source_id, record.source_id);
      assert.equal(registration.target_age_condition, record.target_age);
      assert.equal(registration.kind, "sam_generated_registered_uv");
      assert.equal(registration.age_quality_accepted, false);
      assert.equal(registration.identity_quality_accepted, false);
      commonUvPins.add(registration.common_uv_sha256);
      const coordinates = childReport.input.sourceCoordinateMetadata;
      const frame = { source_center: coordinates.source_center,
        source_to_canonical_uniform_scale: coordinates.source_to_canonical_uniform_scale };
      if (sourceFrames.has(record.source_id))
        assert.deepEqual(frame, sourceFrames.get(record.source_id),
          "Targets of one source must share its unchanged canonical frame.");
      else sourceFrames.set(record.source_id, frame);
      assert.deepEqual(completed.map((result) => result.channel), ["chrome", "msedge"]);
      for (const result of completed) {
        assert.deepEqual(result.errors, []);
        assert.deepEqual(result.externalRequests, []);
        for (const comparison of result.roundtrip.comparisons) {
          for (const name of ["position", "normal", "uv"]) {
            const attribute = comparison.attributes[name];
            assert.ok(attribute?.originalSha256 && attribute?.exportedSha256);
            assert.equal(attribute.originalSha256, attribute.exportedSha256,
              `Roundtrip changed local canonical ${name} bytes.`);
          }
          commonUvAttributes.add(comparison.attributes.uv.originalSha256);
          for (let index = 0; index < comparison.textures.original.length; index++) {
            const original = comparison.textures.original[index];
            const exported = comparison.textures.exported[index];
            assert.ok(original?.unknownMaskSha256 && original?.alphaSha256);
            assert.equal(original.unknownMaskSha256, exported.unknownMaskSha256);
            assert.equal(original.alphaSha256, exported.alphaSha256);
            assert.equal(original.partialAlphaTexels, 0, "Registration masks must use binary alpha.");
          }
        }
      }
      assert.equal(commonUvPins.size, 1, "Target assets do not share the registered common UV pin.");
      assert.equal(commonUvAttributes.size, 1, "Target assets do not share identical UV attributes.");
      for (const name of ["glb", "result"]) await verifyPin(record.artifacts[name]);
      attempt.status = "passed";
      batch.completedCases++;
    } catch (error) {
      attempt.status = "failed";
      attempt.error = error instanceof Error ? error.message : String(error);
      throw error;
    } finally {
      for (const name of ["runner.stdout.log", "runner.stderr.log"])
        attempt.artifacts.push(await filePin(join(caseOutput, name)).catch(() => null));
      attempt.artifacts = attempt.artifacts.filter(Boolean);
    }
    console.log(JSON.stringify({ completedCases: batch.completedCases,
      completedBrowserRoundtrips: batch.completedBrowserRoundtrips,
      requestedCases: batch.requestedCases, sample_id: record.sample_id }));
  }
  assert.equal(cancelled, false, "Browser batch was interrupted.");
  assert.equal(batch.completedBrowserRoundtrips, 74);
  batch.status = "passed";
} catch (error) {
  failure = error;
  batch.status = "failed";
  batch.error = error instanceof Error ? error.message : String(error);
} finally {
  process.removeListener("SIGINT", cancel);
  process.removeListener("SIGTERM", cancel);
  batch.finishedAt = new Date().toISOString();
  batch.interrupted = cancelled;
  batch.unattemptedCases = batch.requestedCases - batch.cases.length;
  batch.commonUvPins = [...commonUvPins];
  batch.commonUvAttributeSha256 = [...commonUvAttributes];
  batch.sourceFrames = Object.fromEntries(sourceFrames);
  await writeFile(join(output, "target-uv-browser.json"), JSON.stringify(batch, null, 2), { flag: "wx" });
}
if (failure) throw failure;
console.log(JSON.stringify({ status: batch.status, completedCases: batch.completedCases,
  completedBrowserRoundtrips: batch.completedBrowserRoundtrips, output }));

async function runChild(record, caseOutput) {
  const child = spawn(process.execPath, [childRunner], {
    cwd: frontend, windowsHide: true,
    env: { ...process.env,
      AGEMORPH_RESEARCH_MESH: await existingPath(record.artifacts.glb.path),
      AGEMORPH_RESEARCH_RESULT: await existingPath(record.artifacts.result.path),
      AGEMORPH_RESEARCH_OUTPUT: caseOutput,
      AGEMORPH_RESEARCH_REQUIRE_TEXTURE: "1",
      AGEMORPH_RESEARCH_TEXTURE_KIND: "generated_target" },
    stdio: ["ignore", "pipe", "pipe", "ipc"],
  });
  activeChild = child;
  const stdout = pipeline(child.stdout, createWriteStream(join(caseOutput, "runner.stdout.log"), { flags: "wx" }));
  const stderr = pipeline(child.stderr, createWriteStream(join(caseOutput, "runner.stderr.log"), { flags: "wx" }));
  const streamsDone = Promise.allSettled([stdout, stderr]);
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; requestChildStop(); }, 180_000);
  try {
    const result = await new Promise((resolveClose, reject) => {
      child.once("error", reject);
      child.once("close", (code, signal) => resolveClose({ code, signal }));
    });
    const streams = await streamsDone;
    for (const stream of streams) if (stream.status === "rejected") throw stream.reason;
    return { ...result, timedOut };
  } finally {
    await streamsDone;
    clearTimeout(timer);
    clearTimeout(forceTimer);
    forceTimer = undefined;
    activeChild = undefined;
  }
}

function isContained(path) {
  const value = relative(repository, path);
  return value === "" || (!isAbsolute(value) && value !== ".." && !value.startsWith(`..${process.platform === "win32" ? "\\" : "/"}`));
}

function containedPath(value) {
  const path = resolve(repository, value);
  assert.ok(isContained(path), "Research paths must remain inside this repository.");
  return path;
}

async function existingPath(value) {
  assert.ok(typeof value === "string" && value, "Expected an explicit local evidence path.");
  const path = await realpath(containedPath(value));
  assert.ok(isContained(path), "Evidence path resolves outside this repository.");
  return path;
}

async function verifyPin(value) {
  assert.ok(value && !isAbsolute(value.path), "Input artifact pins must use repository-relative paths.");
  const path = await existingPath(value.path);
  const actual = await filePin(path);
  assert.equal(actual.sha256, value.sha256, `Input hash mismatch: ${value.path}`);
  assert.equal(actual.bytes, value.bytes, `Input size mismatch: ${value.path}`);
}

async function filePin(path) {
  const bytes = await readFile(containedPath(path));
  return { path: relative(repository, path).replaceAll("\\", "/"),
    sha256: sha256(bytes), bytes: bytes.length };
}

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}
