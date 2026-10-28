import assert from "node:assert/strict";
import test from "node:test";
import { createHash } from "node:crypto";
import { deflateSync } from "node:zlib";
import { createMaskEditorBinding, decodeMaskPng, exportMaskDraft,
  type MaskEditorBinding, type MaskPolygon } from "../src/research-mask-editor.ts";
import { MAX_MASK_DRAFT_BYTES, validateMaskDraft } from "../src/research-mask-draft.ts";

const SIZE = 1024, TOTAL = SIZE * SIZE;
const sha = (bytes: Uint8Array): string => createHash("sha256").update(bytes).digest("hex");
const review = { reviewer: "synthetic record", reviewer_kind: "ai" as const, method: "independent test", version: "v1" };
const polygons: MaskPolygon[] = [
  { kind: "allowed", points: [{ x: 2, y: 2 }, { x: 7, y: 2 }, { x: 7, y: 7 }, { x: 2, y: 7 }] },
  { kind: "occluded", points: [{ x: 4, y: 4 }, { x: 6, y: 4 }, { x: 6, y: 6 }, { x: 4, y: 6 }] },
];

// Deliberately independent CRC, filtering and Node zlib encoder.
function crc(bytes: Uint8Array): number {
  let n = 0xffffffff;
  for (const byte of bytes) {
    n ^= byte;
    for (let bit = 0; bit < 8; bit++) n = (n & 1) ? (n >>> 1) ^ 0xedb88320 : n >>> 1;
  }
  return (n ^ 0xffffffff) >>> 0;
}
function chunk(kind: string, data: Uint8Array): Buffer {
  const result = Buffer.alloc(data.length + 12);
  result.writeUInt32BE(data.length); result.write(kind, 4, "ascii"); result.set(data, 8);
  result.writeUInt32BE(crc(result.subarray(4, result.length - 4)), result.length - 4);
  return result;
}
function predictor(filter: number, left: number, up: number, diagonal: number): number {
  if (filter === 1) return left;
  if (filter === 2) return up;
  if (filter === 3) return (left + up) >>> 1;
  if (filter === 4) {
    const values = [left, up, diagonal], p = left + up - diagonal;
    const distances = values.map(v => Math.abs(p - v));
    return values[distances.indexOf(Math.min(...distances))];
  }
  return 0;
}
function png(pixels: Uint8Array, options: { width?: number; height?: number; color?: number;
  depth?: number; interlace?: number; filter?: number | ((row: number) => number);
  raw?: Uint8Array; extra?: Buffer; level?: 0 | 9 } = {}): Uint8Array {
  const { width = SIZE, height = SIZE, color = 0, depth = 8, interlace = 0, filter = 0, level = 9 } = options;
  const channels = color === 2 ? 3 : color === 6 ? 4 : 1;
  const stride = width * channels;
  const raw = new Uint8Array((stride + 1) * height);
  for (let row = 0; row < height; row++) {
    const kind = typeof filter === "function" ? filter(row) : filter;
    raw[row * (stride + 1)] = kind;
    for (let column = 0; column < stride; column++) {
      const at = row * stride + column;
      const l = column >= channels ? pixels[at - channels] ?? 0 : 0;
      const u = row ? pixels[at - stride] ?? 0 : 0;
      const d = row && column >= channels ? pixels[at - stride - channels] ?? 0 : 0;
      raw[row * (stride + 1) + column + 1] = ((pixels[at] ?? 0) - predictor(kind, l, u, d)) & 255;
    }
  }
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width); header.writeUInt32BE(height, 4); header.set([depth, color, 0, 0, interlace], 8);
  return new Uint8Array(Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", header),
    chunk("IDAT", deflateSync(options.raw ?? raw, { level })), ...(options.extra ? [options.extra] : []),
    chunk("IEND", new Uint8Array())]));
}
function oracle(kind: "allowed" | "occluded"): Uint8Array {
  const result = new Uint8Array(TOTAL);
  for (let y = 0; y < SIZE; y++) for (let x = 0; x < SIZE; x++) {
    const blocked = x >= 4 && x < 6 && y >= 4 && y < 6;
    const active = kind === "occluded" ? blocked : x >= 2 && x < 7 && y >= 2 && y < 7 && !blocked;
    result[y * SIZE + x] = active ? 255 : 0;
  }
  return result;
}
const target = png(new Uint8Array(SIZE * SIZE * 3), { color: 2 });
const binding = createMaskEditorBinding({ stage_id: "a".repeat(32), source_fingerprint: "b".repeat(64),
  target_condition: 45, generated_sha256: sha(target), fit_sha256: "c".repeat(64) });
const initial = await exportMaskDraft(binding, target, polygons, review);
function draft(): any { return structuredClone(initial.draft); }
function validate(value = draft(), allowed = initial.allowedPng, occluded = initial.occludedPng,
  current = binding, image = target) {
  return validateMaskDraft(current, image, typeof value === "string" ? value : JSON.stringify(value), allowed, occluded);
}
function manifest(value: any, kind: "allowed" | "occluded", bytes: Uint8Array): void {
  value.masks[kind].sha256 = sha(bytes); value.masks[kind].bytes = bytes.length;
}

test("existing editor export roundtrip owns matching review and PNG bytes without accepting quality", async () => {
  const result = await validate();
  assert.deepEqual(result.review, review);
  assert.deepEqual(result.pixelCounts, { allowed: 21, occluded: 4, unknown: TOTAL - 25 });
  assert.deepEqual(result.allowedPng, initial.allowedPng); assert.notEqual(result.allowedPng, initial.allowedPng);
  assert.deepEqual(result.occludedPng, initial.occludedPng); assert.notEqual(result.occludedPng, initial.occludedPng);
  assert.deepEqual(Object.keys(result).sort(), ["review", "allowedPng", "occludedPng", "pixelCounts"].sort());
});
test("human source remains a record value with no approval or registration return", async () => {
  const value = draft(); value.review.reviewer_kind = "human";
  const result = await validate(value);
  assert.equal(result.review.reviewer_kind, "human"); assert.equal("human_review_completed" in result, false);
});
test("independent alternate zlib streams and all filters validate by pixels rather than recompressed bytes", async () => {
  const a = png(oracle("allowed"), { filter: row => row % 5, level: 0 });
  const o = png(oracle("occluded"), { filter: row => (row + 3) % 5 });
  assert.notEqual(sha(a), sha(initial.allowedPng));
  const value = draft(); manifest(value, "allowed", a); manifest(value, "occluded", o);
  const result = await validate(value, a, o);
  assert.deepEqual(result.pixelCounts, { allowed: 21, occluded: 4, unknown: TOTAL - 25 });
});
for (let filter = 0; filter <= 4; filter++) test(`L8 decoder independently reconstructs PNG filter ${filter}`, async () => {
  const width = 17, height = 9;
  const pixels = Uint8Array.from({ length: width * height }, (_, i) => ((i * 13 + (i >> 2)) % 7) < 3 ? 255 : 0);
  assert.deepEqual(await decodeMaskPng(png(pixels, { width, height, filter }), width, height), pixels);
});
for (const key of ["stage_id", "source_fingerprint", "generated_sha256", "fit_sha256", "target_condition"])
  test(`rejects mismatching current stage field ${key}`, async () => {
    const value = draft(); value.binding.stage[key] = key === "target_condition" ? 46 : "d".repeat(key === "stage_id" ? 32 : 64);
    await assert.rejects(validate(value), /当前待审核阶段/);
  });
for (const key of ["human_review_completed", "identity_quality_accepted", "age_quality_accepted",
  "visual_seam_quality_accepted", "years_calibrated", "service_ready", "production_enabled", "g3_complete", "research_only"])
  test(`rejects altered closed flag ${key}`, async () => {
    const value = draft(); value[key] = key === "research_only" ? false : true;
    await assert.rejects(validate(value), /关闭标志/);
  });
for (const [name, change] of [
  ["unknown root field", (v: any) => { v.extra = true; }],
  ["missing root field", (v: any) => { delete v.status; }],
  ["wrong version", (v: any) => { v.schema_version = 2; }],
  ["wrong protocol", (v: any) => { v.protocol_id = "other"; }],
  ["non-draft status", (v: any) => { v.status = "approved"; }],
  ["wrong coordinate rule", (v: any) => { v.coordinate_rule = "rounded"; }],
  ["extra binding field", (v: any) => { v.binding.extra = true; }],
  ["extra stage field", (v: any) => { v.binding.stage.extra = true; }],
  ["wrong binding dimensions", (v: any) => { v.binding.width = 512; }],
  ["extra review field", (v: any) => { v.review.accepted = true; }],
  ["empty reviewer", (v: any) => { v.review.reviewer = " "; }],
  ["overlong reviewer", (v: any) => { v.review.reviewer = "x".repeat(129); }],
  ["overlong method", (v: any) => { v.review.method = "x".repeat(257); }],
  ["overlong version", (v: any) => { v.review.version = "x".repeat(65); }],
  ["control character", (v: any) => { v.review.method = "line\nline"; }],
  ["unknown record source", (v: any) => { v.review.reviewer_kind = "approved"; }],
  ["extra manifest field", (v: any) => { v.masks.allowed.extra = 1; }],
  ["invalid hash", (v: any) => { v.masks.allowed.sha256 = "F".repeat(64); }],
  ["wrong byte length", (v: any) => { v.masks.allowed.bytes++; }],
  ["wrong manifest pixels", (v: any) => { v.masks.occluded.pixels++; }],
  ["fractional pixels", (v: any) => { v.pixel_counts.allowed = 21.5; }],
  ["negative pixels", (v: any) => { v.pixel_counts.occluded = -1; }],
  ["unknown count mismatch", (v: any) => { v.pixel_counts.unknown--; }],
  ["invalid vertex", (v: any) => { v.polygons[0].points[0].x = -1; }],
  ["self-intersecting polygon", (v: any) => { v.polygons[0].points = [
    { x: 2, y: 2 }, { x: 7, y: 7 }, { x: 2, y: 7 }, { x: 7, y: 2 }]; }],
  ["excess polygons", (v: any) => { v.polygons = Array.from({ length: 65 }, () => v.polygons[0]); }],
] as const) test(`rejects ${name}`, async () => {
  const value = draft(); change(value); await assert.rejects(validate(value));
});
test("rejects duplicate root, nested and escaped-key aliases before losing values", async () => {
  const text = JSON.stringify(draft());
  for (const changed of [text.replace('"schema_version":1', '"schema_version":2,"schema_version":1'),
    text.replace('"reviewer":"synthetic record"', '"reviewer":"other","reviewer":"synthetic record"'),
    text.replace('"reviewer":"synthetic record"', '"reviewer":"other","revi\\u0065wer":"synthetic record"')])
    await assert.rejects(validate(changed), /重复字段/);
});
test("rejects malformed, nonfinite, deeply nested, empty and over-budget JSON", async () => {
  const text = JSON.stringify(draft());
  for (const invalid of ["", "{", "null", "[]", " ".repeat(MAX_MASK_DRAFT_BYTES + 1),
    JSON.stringify("中".repeat(Math.floor(MAX_MASK_DRAFT_BYTES / 3) + 1)),
    text.replace('"x":2', '"x":1e999'), "[".repeat(33) + "0" + "]".repeat(33)])
    await assert.rejects(validate(invalid));
});
test("accepts the exact UTF8 text size budget and rejects a single extra byte", async () => {
  const text = JSON.stringify(draft());
  const maximum = " ".repeat(MAX_MASK_DRAFT_BYTES - Buffer.byteLength(text)) + text;
  await validate(maximum); await assert.rejects(validate(" " + maximum), /512KiB/);
});
test("rejects malformed current binding before serializing caller-owned values", async () => {
  for (const change of [(v: any) => { v.extra = true; }, (v: any) => { v.stage.fit_sha256 = {}; },
    (v: any) => { v.stage.target_condition = Infinity; }]) {
    const current = structuredClone(binding); change(current); await assert.rejects(validate(draft(), undefined, undefined, current));
  }
});
test("rejects all PNG size/type limits before copies or digest work", async () => {
  const original = crypto.subtle.digest;
  let calls = 0;
  crypto.subtle.digest = ((...args: Parameters<typeof original>) => { calls++; return original.apply(crypto.subtle, args); }) as typeof original;
  try {
    for (const bad of [new Uint8Array(), new Uint8Array(57 - 1), new Uint8Array(4 * 1024 ** 2 + 1), null]) {
      for (const index of [0, 1, 2]) {
        const inputs = [target, initial.allowedPng, initial.occludedPng]; inputs[index] = bad as Uint8Array;
        await assert.rejects(validateMaskDraft(binding, inputs[0], JSON.stringify(draft()), inputs[1], inputs[2]));
      }
    }
    await assert.rejects(validate(" ".repeat(MAX_MASK_DRAFT_BYTES + 1)));
    assert.equal(calls, 0);
  } finally { crypto.subtle.digest = original; }
});
test("rejects changed raw bytes even when the altered PNG remains valid", async () => {
  const different = png(oracle("allowed"), { level: 0 });
  const value = draft(); value.masks.allowed.bytes = different.length;
  await assert.rejects(validate(value, different), /原字节指纹/);
});
test("rejects a different valid target PNG with the same native dimensions", async () => {
  const pixels = new Uint8Array(TOTAL * 3); pixels[0] = 255;
  await assert.rejects(validate(draft(), undefined, undefined, undefined, png(pixels, { color: 2 })), /目标PNG指纹/);
});
test("rejects incorrect pixels despite repaired PNG hash, bytes and equal pixel counts", async () => {
  const pixels = oracle("allowed"); pixels[2 * SIZE + 2] = 0; pixels[0] = 255;
  const wrong = png(pixels), value = draft(); manifest(value, "allowed", wrong);
  await assert.rejects(validate(value, wrong), /像素与草稿多边形/);
});
test("rejects overlap despite repaired hashes and equal individual counts", async () => {
  const pixels = oracle("allowed"); pixels[2 * SIZE + 2] = 0; pixels[4 * SIZE + 4] = 255;
  const wrong = png(pixels), value = draft(); manifest(value, "allowed", wrong);
  await assert.rejects(validate(value, wrong), /像素与草稿多边形/);
});
for (const [name, bytes] of [
  ["RGB", () => png(new Uint8Array(TOTAL * 3), { color: 2 })],
  ["RGBA", () => png(new Uint8Array(TOTAL * 4), { color: 6 })],
  ["16bit", () => png(oracle("allowed"), { depth: 16 })],
  ["interlaced", () => png(oracle("allowed"), { interlace: 1 })],
  ["wrong dimensions", () => png(new Uint8Array(512 * 512), { width: 512, height: 512 })],
  ["invalid filter", () => png(oracle("allowed"), { filter: 5 })],
  ["nonbinary pixels", () => { const p = oracle("allowed"); p[0] = 127; return png(p); }],
  ["bad CRC", () => { const p = initial.allowedPng.slice(); p[p.length - 1] ^= 1; return p; }],
  ["extra ancillary chunk", () => png(oracle("allowed"), { extra: chunk("tEXt", new Uint8Array([1])) })],
  ["trailing bytes", () => new Uint8Array([...initial.allowedPng, 0])],
  ["truncated scanlines", () => png(oracle("allowed"), { raw: new Uint8Array((SIZE + 1) * SIZE - 1) })],
  ["oversized inflated payload", () => png(oracle("allowed"), { raw: new Uint8Array((SIZE + 1) * SIZE + 1) })],
] as const) test(`rejects ${name} even when the draft pins that exact PNG`, async () => {
  const wrong = bytes(), value = draft(); manifest(value, "allowed", wrong);
  await assert.rejects(validate(value, wrong));
});
test("rejects empty and all-allowed polygon candidates without silently fixing pixels", async () => {
  for (const ps of [[], [{ kind: "allowed", points: [{ x: 0, y: 0 }, { x: SIZE, y: 0 },
    { x: SIZE, y: SIZE }, { x: 0, y: SIZE }] }]]) {
    const value = draft(); value.polygons = ps; await assert.rejects(validate(value), /允许区不得/);
  }
});
test("snapshots current binding and every PNG before the first asynchronous digest", async () => {
  const current: MaskEditorBinding = structuredClone(binding);
  const image = target.slice(), a = initial.allowedPng.slice(), o = initial.occludedPng.slice();
  const value = draft();
  const pending = validate(value, a, o, current, image);
  current.stage.stage_id = "d".repeat(32); image.fill(0); a.fill(0); o.fill(0);
  value.review.reviewer = "late edit"; value.polygons[0].points[0].x = 100;
  const result = await pending;
  assert.deepEqual(result.review, review);
  assert.deepEqual(result.allowedPng, initial.allowedPng); assert.deepEqual(result.occludedPng, initial.occludedPng);
});
test("direct decoder checks dimensions, CRC, binary values and detached caller snapshot", async () => {
  const pixels = new Uint8Array([0, 255, 255, 0]);
  const bytes = png(pixels, { width: 2, height: 2, filter: 4 });
  const pending = decodeMaskPng(bytes, 2, 2); bytes.fill(0);
  assert.deepEqual(await pending, pixels);
  for (const dimensions of [[0, 2], [2.5, 2], [1025, 2]])
    await assert.rejects(decodeMaskPng(initial.allowedPng, dimensions[0], dimensions[1]));
});
