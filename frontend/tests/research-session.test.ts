/** Synthetic API/GLB contracts only; these fixtures are not model or visual evidence. */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { deflateSync } from "node:zlib";
import { test, type TestContext } from "node:test";
import {
  ResearchApiError, ResearchSessionApi, researchSha256, verifyRegisteredProvenance,
  type SessionInfo, type StageReply,
} from "../src/research-session.ts";

const BASE = "http://127.0.0.1:18091";
const SID = "a".repeat(32), STAGE = "b".repeat(32), FP = "c".repeat(64), TOPO = "d".repeat(64);
const KNOWN = { value: 40, method: "user", calibration_id: null };
const UNKNOWN = { value: null, method: "unknown", calibration_id: null };
const FLAGS = { research_only: true, service_ready: false, production_enabled: false,
  g3_complete: false, age_quality_accepted: false, identity_quality_accepted: false,
  visual_seam_quality_accepted: false, years_calibrated: false, human_review_completed: false };
const sha = (data: Uint8Array | string) => createHash("sha256").update(data).digest("hex");
const bytes = (data: Uint8Array): ArrayBuffer => Uint8Array.from(data).buffer;
const jsonResponse = (value: unknown, status = 200) => new Response(JSON.stringify(value), {
  status, headers: { "Content-Type": "application/json" },
});

function fixturePng(width = 256, height = 256, color = 6, red = 70): Buffer {
  const crc = (data: Uint8Array): number => {
    let n = 0xffffffff;
    for (const value of data) {
      n ^= value;
      for (let i = 0; i < 8; i++) n = n & 1 ? 0xedb88320 ^ (n >>> 1) : n >>> 1;
    }
    return (n ^ 0xffffffff) >>> 0;
  };
  const chunk = (kind: string, data: Buffer) => {
    const head = Buffer.alloc(4); head.writeUInt32BE(data.length);
    const body = Buffer.concat([Buffer.from(kind), data]), tail = Buffer.alloc(4);
    tail.writeUInt32BE(crc(body));
    return Buffer.concat([head, body, tail]);
  };
  const header = Buffer.alloc(13); header.writeUInt32BE(width); header.writeUInt32BE(height, 4);
  header[8] = 8; header[9] = color;
  const channels = color === 6 ? 4 : color === 2 ? 3 : 1;
  const pixels = Buffer.alloc(height * (1 + width * channels));
  // One visible pixel; all other pixels are transparent zero in RGBA fixtures.
  pixels[1] = red;
  if (color === 6) { pixels[2] = 80; pixels[3] = 90; pixels[4] = 255; }
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk("IHDR", header), chunk("IDAT", deflateSync(pixels)), chunk("IEND", Buffer.alloc(0))]);
}
function fixture(age = KNOWN) {
  const atlas = fixturePng(), targetAtlas = fixturePng(256, 256, 6, 110);
  const allowed = fixturePng(1024, 1024, 0), occluded = fixturePng(1024, 1024, 0, 0);
  const preview = fixturePng(1024, 1024, 2), fit = Buffer.from('{"synthetic_fit":true}');
  const shape = Array(40).fill(0);
  const info = { session_id: SID, source_age: age, source_fingerprint: FP, shape,
    source_glb_url: `/research/sessions/${SID}/source.glb`,
    source_texture_url: `/research/sessions/${SID}/source-texture.png`, ...FLAGS };
  const coordinates = { version: "agemorph3d-static-canonical-v1", source_coordinate_system: "bfm_model_raw",
    normalization: "source_bbox_height_to_one", source_center: [0, 0, 0], source_bbox_height: 1,
    source_to_canonical_uniform_scale: 1, axis_rotation_row_major: [1, 0, 0, 0, 1, 0, 0, 0, 1],
    vertex_order_preserved: true, face_order_preserved: true, metric_scale_verified: false,
    source_topology_sha256: TOPO, source_projection_row_major: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0],
    source_roi: [0, 0, 120, 120] };
  const generation = { pid: 1234, load_count: 1, load_seconds: 0.000001, pins: { manifest_sha256: "e".repeat(64) },
    research_only: true, service_ready: false, notes: 'synthetic string contains {"generation":1} safely' };
  const full = { version: "agemorph3d-research-registered-condition-v1", source_fingerprint: FP,
    target_condition: 45, condition_semantics: "Synthetic integer condition; no age truth",
    source_age: age, shape_route: "static_fallback", generated_sha256: sha(preview), target_fit_sha256: sha(fit),
    allowed_png_sha256: sha(allowed), occluded_png_sha256: sha(occluded),
    reviewer: "synthetic-reviewer", reviewer_kind: "ai", review_method: "explicit synthetic masks",
    review_version: "test-v1", model_bindings: { detector_manifest_sha256: "f".repeat(64),
      reconstructor_manifest_sha256: "f".repeat(64), sam_manifest_sha256: "f".repeat(64), common_uv_asset_sha256: "f".repeat(64) },
    generation, ...FLAGS };
  // Deliberately preserve Python-shaped float tokens that JS stringify changes.
  const generationRaw = JSON.stringify(generation).replace('"load_seconds":0.000001', '"load_seconds":1e-06');
  const nativeRaw = JSON.stringify(full).replace('"load_seconds":0.000001', '"load_seconds":1e-06')
    .replace('"value":40,', '"value":40.0,');
  const compact = { ...JSON.parse(nativeRaw), provenance_sha256: sha(nativeRaw), generation: {
    pid: 1234, load_count: 1, provenance_sha256: sha(generationRaw) } };
  const sourceExtras = { asset_mode: "static", source_age: age, topology_id: `tddfa-bfm-canon-v1-${TOPO}`,
    coordinate_metadata: coordinates, base_texture: { input_kind: "original_photo", original_photo_observation: true } };
  const targetExtras = { ...sourceExtras, base_texture: { kind: "sam_generated_registered_uv",
    input_kind: "sam_generated_target_image", age_generated: true, original_photo_observation: false,
    age_texture_quality_accepted: false, research_pipeline: compact } };
  const stage: StageReply & typeof FLAGS = { staged: { stage_id: STAGE, source_fingerprint: FP,
    target_condition: 45, generated_sha256: sha(preview), fit_sha256: sha(fit) },
    preview_url: `/research/sessions/${SID}/stages/${STAGE}/preview.png`,
    fit_url: `/research/sessions/${SID}/stages/${STAGE}/fit.json`, ...FLAGS };
  const registered = { session_id: SID, kind: "sam_registered_uv", condition: 45, source_age: age, shape,
    provenance: JSON.parse(nativeRaw), provenance_json_b64: Buffer.from(nativeRaw).toString("base64"),
    mesh_url: `/research/sessions/${SID}/conditions/45/mesh.glb`,
    texture_url: `/research/sessions/${SID}/conditions/45/texture.png`, ...FLAGS };
  return { info, shape, atlas, targetAtlas, allowed, occluded, preview, fit, coordinates,
    generation, nativeRaw, sourceExtras, targetExtras, stage, registered };
}
function fixtureGlb(texture: Buffer, extras: unknown, edit?: (doc: any, binary: Buffer) => void): Buffer {
  extras = structuredClone(extras);
  const positions = Buffer.alloc(36), normals = Buffer.alloc(36), triangles = Buffer.alloc(12), uv = Buffer.alloc(24);
  [0, 0, 0, 1, 0, 0, 0, 1, 0].forEach((n, i) => positions.writeFloatLE(n, i * 4));
  [0, 0, 1, 0, 0, 1, 0, 0, 1].forEach((n, i) => normals.writeFloatLE(n, i * 4));
  [0, 1, 2].forEach((n, i) => triangles.writeUInt32LE(n, i * 4));
  [0, 0, 1, 0, 0, 1].forEach((n, i) => uv.writeFloatLE(n, i * 4));
  const chunks = [positions, normals, triangles, uv, texture]; let cursor = 0;
  const views = chunks.map(data => { const view = { buffer: 0, byteOffset: cursor, byteLength: data.length }; cursor += data.length; return view; });
  const raw = Buffer.concat(chunks), binary = Buffer.concat([raw, Buffer.alloc((4 - raw.length % 4) % 4)]);
  const doc = { asset: { version: "2.0" }, scene: 0, scenes: [{ nodes: [0], extras }],
    nodes: [{ mesh: 0, name: "Synthetic_Test_Face" }], meshes: [{ primitives: [{ attributes: {
      POSITION: 0, NORMAL: 1, TEXCOORD_0: 3 }, indices: 2, material: 0, mode: 4 }] }],
    extras, buffers: [{ byteLength: binary.length }], bufferViews: views,
    accessors: [ { bufferView: 0, componentType: 5126, count: 3, type: "VEC3" },
      { bufferView: 1, componentType: 5126, count: 3, type: "VEC3" },
      { bufferView: 2, componentType: 5125, count: 3, type: "SCALAR" },
      { bufferView: 3, componentType: 5126, count: 3, type: "VEC2" } ],
    images: [{ bufferView: 4, mimeType: "image/png" }], textures: [{ sampler: 0, source: 0 }],
    samplers: [{ magFilter: 9729, minFilter: 9729, wrapS: 33071, wrapT: 33071 }],
    materials: [{ alphaMode: "MASK", alphaCutoff: 0.5, pbrMetallicRoughness: {
      baseColorFactor: [1, 1, 1, 1], baseColorTexture: { index: 0, texCoord: 0 } } }] };
  edit?.(doc, binary);
  const encoded = Buffer.from(JSON.stringify(doc)), json = Buffer.concat([encoded, Buffer.alloc((4 - encoded.length % 4) % 4, 32)]);
  const head = Buffer.alloc(20), binHead = Buffer.alloc(8);
  head.write("glTF"); head.writeUInt32LE(2, 4); head.writeUInt32LE(28 + json.length + binary.length, 8);
  head.writeUInt32LE(json.length, 12); head.write("JSON", 16);
  binHead.writeUInt32LE(binary.length); binHead.write("BIN\0", 4);
  return Buffer.concat([head, json, binHead, binary]);
}
const fetchRestores = new WeakSet<TestContext>();
function fakeFetch(t: TestContext, callback: (url: string, init: RequestInit) => Response | Promise<Response>) {
  if (!fetchRestores.has(t)) {
    const saved = globalThis.fetch;
    t.after(() => { globalThis.fetch = saved; });
    fetchRestores.add(t);
  }
  globalThis.fetch = (async (url, init) => callback(String(url), init ?? {})) as typeof fetch;
}
function routes(t: TestContext, data = fixture(), edits: { source?: (doc: any, bin: Buffer) => void; target?: (doc: any, bin: Buffer) => void; sourcePng?: Buffer; targetPng?: Buffer; info?: unknown; registered?: unknown } = {}) {
  const sourceGlb = fixtureGlb(data.atlas, data.sourceExtras, edits.source);
  const targetGlb = fixtureGlb(data.targetAtlas, data.targetExtras, edits.target);
  fakeFetch(t, (url, init) => {
    const parsed = new URL(url), path = parsed.pathname;
    assert.equal(parsed.origin, BASE);
    assert.equal(init.credentials, "omit"); assert.equal(init.redirect, "error"); assert.equal(init.cache, "no-store");
    if (path === "/research/health") return jsonResponse({ ...FLAGS, service: { closed: false }, capabilities: {
      reconstruction: false, age_morph: false, age_texture: false, realtime: false } });
    if (path === "/research/sessions" || path === `/research/sessions/${SID}`) return jsonResponse(edits.info ?? data.info);
    if (path.endsWith("/conditions")) return jsonResponse(data.stage);
    if (path.endsWith("/reviews")) return jsonResponse(edits.registered ?? data.registered);
    if (path.endsWith("/preview.png")) return new Response(bytes(data.preview), { headers: { "Content-Type": "image/png" } });
    if (path.endsWith("/fit.json")) return new Response(bytes(data.fit), { headers: { "Content-Type": "application/json" } });
    if (path.endsWith("/source.glb")) return new Response(bytes(sourceGlb), { headers: { "Content-Type": "model/gltf-binary" } });
    if (path.endsWith("/source-texture.png")) return new Response(bytes(edits.sourcePng ?? data.atlas), { headers: { "Content-Type": "image/png" } });
    if (path.endsWith("/mesh.glb")) return new Response(bytes(targetGlb), { headers: { "Content-Type": "model/gltf-binary" } });
    if (path.endsWith("/texture.png")) return new Response(bytes(edits.targetPng ?? data.targetAtlas), { headers: { "Content-Type": "image/png" } });
    throw new Error("Unexpected synthetic route " + path);
  });
  return { sourceGlb, targetGlb, data };
}
const review = (data: ReturnType<typeof fixture>) => ({
  allowed: new Blob([bytes(data.allowed)], { type: "image/png" }),
  occluded: new Blob([bytes(data.occluded)], { type: "image/png" }),
  reviewer: "synthetic-reviewer", reviewer_kind: "ai" as const, method: "explicit synthetic masks", version: "test-v1",
});

test("only explicit loopback origins are accepted", () => {
  for (const url of ["http://127.0.0.1:18091", "https://localhost:1234/", "http://[::1]:9999"])
    assert.ok(new ResearchSessionApi(url).baseUrl.startsWith("http"));
  for (const url of ["http://example.test", "http://127.0.0.1:0", "http://127.1", "http://2130706433",
    "http://localhost/path", "http://localhost?", "http://localhost#", "http://u:p@localhost", " http://localhost", "file:///tmp/a"])
    assert.throws(() => new ResearchSessionApi(url));
});

test("valid native-shaped source/target keeps exact geometry and verifies native provenance bytes", async t => {
  const { data, sourceGlb } = routes(t), api = new ResearchSessionApi(BASE);
  const info = await api.sessionInfo(SID), source = await api.loadSource(info);
  assert.equal(source.kind, "original_source");
  assert.equal(source.glbBytes.byteLength, sourceGlb.length);
  assert.deepEqual(source.info.source_age, KNOWN);
  assert.equal(source.geometryHashes.POSITION, sha(Buffer.from([0, 0, 0, 1, 0, 0, 0, 1, 0].flatMap(n => {
    const data = Buffer.alloc(4); data.writeFloatLE(n); return [...data];
  }))));
  const stage = await api.stage(SID, 45);
  assert.equal(await researchSha256(await api.preview(SID, stage)), sha(data.preview));
  assert.equal(await researchSha256(await api.fit(SID, stage)), sha(data.fit));
  const registered = await api.register(SID, stage, review(data));
  const loaded = await api.loadCondition(info, 45, source);
  assert.deepEqual(loaded.geometryHashes, source.geometryHashes);
  assert.equal(new TextDecoder().decode(registered.provenanceBytes), data.nativeRaw);
  assert.notEqual(JSON.stringify(registered.provenance), data.nativeRaw, "float spelling must actually differ");
  await verifyRegisteredProvenance(registered, loaded);
});

test("unknown source is preserved in API and both native GLBs without a default age", async t => {
  routes(t, fixture(UNKNOWN as typeof KNOWN));
  const api = new ResearchSessionApi(BASE), info = await api.sessionInfo(SID);
  const source = await api.loadSource(info), target = await api.loadCondition(info, 45, source);
  assert.deepEqual(source.info.source_age, UNKNOWN);
  assert.deepEqual(target.info.source_age, UNKNOWN);
});

test("raw upload retains explicit decimal text and omission remains unknown", async t => {
  const data = fixture(), requests: string[] = [];
  fakeFetch(t, (url, init) => {
    requests.push(url); assert.equal(init.method, "POST"); assert.ok(init.body instanceof Blob);
    return jsonResponse({ ...data.info, source_age: new URL(url).search ? KNOWN : UNKNOWN });
  });
  const api = new ResearchSessionApi(BASE), image = new Blob(["synthetic"], { type: "image/jpeg" });
  assert.deepEqual((await api.createSession(image)).source_age, UNKNOWN);
  assert.deepEqual((await api.createSession(image, "040.0")).source_age, KNOWN);
  assert.equal(requests[1], BASE + "/research/sessions?source_age=040.0");
  for (const value of ["", "40e0", "+40", "40 ", "NaN", "19.9", "70.1"])
    await assert.rejects(api.createSession(image, value));
  assert.equal(requests.length, 2);
});

for (const value of [true, 20.5, NaN, Infinity, "45", 19, 71]) test(`invalid condition ${String(value)} never reaches fetch`, async t => {
  fakeFetch(t, () => { assert.fail("invalid condition fetched"); });
  await assert.rejects(new ResearchSessionApi(BASE).stage(SID, value as number));
});

for (const change of [
  { service_ready: true }, { production_enabled: true }, { g3_complete: true },
  { age_quality_accepted: true }, { research_only: false }, { source_age: { ...UNKNOWN, value: 40 } },
  { source_age: { ...KNOWN, calibration_id: "invented" } }, { shape: [0] },
]) test(`invalid session metadata ${Object.keys(change).join()} is rejected`, async t => {
  const data = fixture(); routes(t, data, { info: { ...data.info, ...change } });
  await assert.rejects(new ResearchSessionApi(BASE).sessionInfo(SID));
});

for (const url of [
  `http://evil.invalid/research/sessions/${SID}/source.glb`,
  `/research/sessions/${STAGE}/source.glb`, `/research/sessions/${SID}/source.glb?x=1`,
  `/research/sessions/${SID}/source.glb#`, `/research/sessions/${SID}/../${SID}/source.glb`,
  `/research/sessions/${SID}/%73ource.glb`, `//127.0.0.1:18091/research/sessions/${SID}/source.glb`,
]) test(`source URL escape ${url} is rejected`, async t => {
  const data = fixture(); routes(t, data, { info: { ...data.info, source_glb_url: url } });
  await assert.rejects(new ResearchSessionApi(BASE).sessionInfo(SID));
});

test("duplicate response keys and nonfinite JSON never grant research state", async t => {
  fakeFetch(t, () => new Response('{"research_only":true,"service_ready":true,"service_ready":false}', { headers: { "Content-Type": "application/json" } }));
  await assert.rejects(new ResearchSessionApi(BASE).health(), /重复/);
  fakeFetch(t, () => new Response('{"value":1e999}', { headers: { "Content-Type": "application/json" } }));
  await assert.rejects(new ResearchSessionApi(BASE).health());
});

test("HTTP safe codes discard server private details and retain hash-bound staged metadata", async t => {
  const data = fixture();
  fakeFetch(t, () => jsonResponse({ code: "REVIEW_REQUIRED", detail: "secret local photo path", ...data.stage }, 409));
  await assert.rejects(new ResearchSessionApi(BASE).stage(SID, 45), error => {
    assert.ok(error instanceof ResearchApiError); assert.equal(error.code, "REVIEW_REQUIRED");
    assert.ok(error.stage); assert.equal(error.stage.staged.generated_sha256, sha(data.preview));
    assert.doesNotMatch(error.message, /secret/); return true;
  });
});

const changes: [string, (doc: any, bin: Buffer) => void][] = [
  ["external buffer", d => { d.buffers[0].uri = "https://evil.invalid/x.bin"; }],
  ["external image", d => { d.images[0].uri = "https://evil.invalid/x.png"; }],
  ["node transform", d => { d.nodes[0].translation = [1, 0, 0]; }],
  ["morph target", d => { d.meshes[0].primitives[0].targets = [{ POSITION: 0 }]; }],
  ["sparse accessor", d => { d.accessors[0].sparse = {}; }],
  ["oversized accessor", d => { d.accessors[0].count = 2 ** 31; }],
  ["view bounds", d => { d.bufferViews[0].byteLength += 1000; }],
  ["UV range", (_d, b) => { b.writeFloatLE(2, 84); }],
  ["nonfinite position", (_d, b) => { b.writeFloatLE(NaN, 0); }],
  ["invalid triangle", (_d, b) => { b.writeUInt32LE(9, 72); }],
  ["source age mismatch", d => { d.extras.source_age.value = 41; }],
  ["wrong source frame", d => { d.extras.coordinate_metadata.normalization = "target_bbox_height_to_one"; }],
  ["wrong MASK state", d => { d.materials[0].alphaMode = "BLEND"; }],
];
for (const [name, edit] of changes) test(`native source rejects ${name}`, async t => {
  routes(t, fixture(), { source: edit }); const api = new ResearchSessionApi(BASE), info = await api.sessionInfo(SID);
  await assert.rejects(api.loadSource(info));
});

for (const [name, edit] of [
  ["position drift", (_d: any, b: Buffer) => { b.writeFloatLE(0.25, 0); }],
  ["UV reorder", (_d: any, b: Buffer) => { b.writeFloatLE(0.5, 84); }],
  ["source fingerprint", (d: any) => { d.extras.base_texture.research_pipeline.source_fingerprint = "f".repeat(64); }],
  ["condition", (d: any) => { d.extras.base_texture.research_pipeline.target_condition = 46; }],
  ["quality elevation", (d: any) => { d.extras.base_texture.research_pipeline.identity_quality_accepted = true; }],
] as const) test(`condition cannot change ${name}`, async t => {
  routes(t, fixture(), { target: edit }); const api = new ResearchSessionApi(BASE), info = await api.sessionInfo(SID), source = await api.loadSource(info);
  await assert.rejects(api.loadCondition(info, 45, source));
});

test("separate source PNG must equal the exact embedded bytes", async t => {
  routes(t, fixture(), { sourcePng: fixturePng(256, 256, 6, 111) });
  const api = new ResearchSessionApi(BASE), info = await api.sessionInfo(SID);
  await assert.rejects(api.loadSource(info), /内嵌/);
});

test("PNG CRC is checked even when external and embedded corrupt bytes match", async t => {
  const data = fixture(); data.atlas[data.atlas.length - 1] ^= 1;
  routes(t, data); const api = new ResearchSessionApi(BASE), info = await api.sessionInfo(SID);
  await assert.rejects(api.loadSource(info), /PNG校验/);
});

test("register checks mask bounds, frame and original native provenance object equality", async t => {
  const data = fixture(); routes(t, data, { registered: { ...data.registered, provenance_json_b64: Buffer.from('{}').toString('base64') } });
  const api = new ResearchSessionApi(BASE), stage = await api.stage(SID, 45);
  await assert.rejects(api.register(SID, stage, { ...review(data), allowed: new Blob(["not a mask"], { type: "image/png" }) }));
  await assert.rejects(api.register(SID, stage, review(data)), /原始来源/);
});

test("native provenance hashes fail after byte changes without JS canonicalization", async t => {
  const data = fixture(); routes(t, data); const api = new ResearchSessionApi(BASE), info = await api.sessionInfo(SID), source = await api.loadSource(info);
  const registered = await api.register(SID, await api.stage(SID, 45), review(data));
  const loaded = await api.loadCondition(info, 45, source);
  const changed = JSON.stringify(registered.provenance);
  await assert.rejects(verifyRegisteredProvenance({ ...registered, provenance_json_b64: Buffer.from(changed).toString("base64"), provenanceBytes: bytes(Buffer.from(changed)) }, loaded), /GLB指纹/);
});

test("fully drained success and HTTP error bodies release without cancellation", async t => {
  const successful = { ...FLAGS, service: { closed: false }, capabilities: {
    reconstruction: false, age_morph: false, age_texture: false, realtime: false } };
  for (const status of [200, 409]) {
    let cancelled = 0, released = 0;
    const response = jsonResponse(status === 200 ? successful : { code: "BUSY" }, status);
    const stream = response.body!, originalGetReader = stream.getReader.bind(stream);
    Object.defineProperty(stream, "getReader", { value: () => {
      const reader = originalGetReader(), originalCancel = reader.cancel.bind(reader), originalRelease = reader.releaseLock.bind(reader);
      reader.cancel = reason => { cancelled++; return originalCancel(reason); };
      reader.releaseLock = () => { released++; originalRelease(); };
      return reader;
    } });
    fakeFetch(t, () => response);
    const request = new ResearchSessionApi(BASE).health();
    if (status === 200) assert.equal((await request).service.closed, false);
    else await assert.rejects(request, error => error instanceof ResearchApiError && error.code === "BUSY");
    assert.equal(cancelled, 0, `drained ${status} response must not be cancelled`);
    assert.equal(released, 1, `drained ${status} response must release its lock`);
    assert.equal(stream.locked, false);
  }
});

test("declared and measured response budgets cancel the body", async t => {
  let cancelled = 0;
  fakeFetch(t, () => new Response(new ReadableStream({ cancel() { cancelled++; } }), {
    headers: { "Content-Type": "application/json", "Content-Length": "16385" },
  }));
  await assert.rejects(new ResearchSessionApi(BASE).health(), /预算/);
  assert.equal(cancelled, 1);
  fakeFetch(t, () => new Response(new ReadableStream({ start(c) { c.enqueue(new Uint8Array(10_000)); c.enqueue(new Uint8Array(10_000)); }, cancel() { cancelled++; } }), {
    headers: { "Content-Type": "application/json" },
  }));
  await assert.rejects(new ResearchSessionApi(BASE).health(), /实际字节预算/);
  assert.equal(cancelled, 2);
});

test("abort before fetch and during a streamed body closes its reader", async t => {
  let fetches = 0, cancelled = false;
  fakeFetch(t, () => { fetches++; return new Response(new ReadableStream({ start(c) { c.enqueue(new Uint8Array([32])); }, cancel() { cancelled = true; } }), { headers: { "Content-Type": "application/json" } }); });
  const api = new ResearchSessionApi(BASE), before = new AbortController(); before.abort();
  await assert.rejects(api.health(before.signal), { name: "AbortError" }); assert.equal(fetches, 0);
  const during = new AbortController(), work = api.health(during.signal);
  await new Promise(resolve => setTimeout(resolve, 0)); during.abort();
  await assert.rejects(work, { name: "AbortError" }); assert.ok(cancelled);
});

test("a failed asset cancels the concurrent peer request", async t => {
  const data = fixture(); let peerAborted = false;
  fakeFetch(t, (url, init) => {
    if (url.endsWith(`/research/sessions/${SID}`)) return jsonResponse(data.info);
    if (url.endsWith("source.glb")) return jsonResponse({ code: "SESSION_EXPIRED" }, 404);
    return new Promise((_resolve, reject) => {
      init.signal!.addEventListener("abort", () => { peerAborted = true; reject(new DOMException("cancelled", "AbortError")); });
    });
  });
  const api = new ResearchSessionApi(BASE), info = await api.sessionInfo(SID);
  await assert.rejects(api.loadSource(info), error => error instanceof ResearchApiError && error.code === "SESSION_EXPIRED");
  assert.ok(peerAborted);
});
