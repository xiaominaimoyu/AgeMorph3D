import assert from "node:assert/strict";
import test from "node:test";
import { createHash } from "node:crypto";
import { deflateSync, inflateSync } from "node:zlib";
import { MASK_EDITOR_PROTOCOL, createMaskEditorBinding, parseMaskEditorBinding,
  validateMaskEditorTarget, rasterizeMaskPolygons, encodeMaskPng, exportMaskDraft,
  type MaskPoint, type MaskPolygon, type MaskEditorBinding, type MaskReviewer,
} from "../src/research-mask-editor.ts";

const textEncoder = new TextEncoder();
const sha = (bytes: Uint8Array): string => createHash("sha256").update(bytes).digest("hex");
const reviewer: MaskReviewer = { reviewer: "synthetic automation", reviewer_kind: "ai", method: "synthetic test", version: "v1" };

// Independent bit-at-a-time CRC and Node zlib: never call a project PNG helper.
function crc(bytes: Uint8Array): number {
  let value = 0xffffffff;
  for (const byte of bytes) {
    value ^= byte;
    for (let i = 0; i < 8; i++) value = (value & 1) ? (value >>> 1) ^ 0xedb88320 : value >>> 1;
  }
  return (value ^ 0xffffffff) >>> 0;
}
function makeChunk(name: string, bytes: Uint8Array): Buffer {
  const answer = Buffer.alloc(bytes.length + 12);
  answer.writeUInt32BE(bytes.length); answer.write(name, 4, "ascii"); answer.set(bytes, 8);
  answer.writeUInt32BE(crc(answer.subarray(4, answer.length - 4)), answer.length - 4);
  return answer;
}
function targetPng(options: { width?: number; height?: number; color?: number; raw?: Uint8Array;
  compressed?: Uint8Array; depth?: number; interlace?: number; extra?: Buffer } = {}): Uint8Array {
  const { width = 1024, height = 1024, color = 2, depth = 8, interlace = 0 } = options;
  const header = Buffer.alloc(13); header.writeUInt32BE(width); header.writeUInt32BE(height, 4);
  header.set([depth, color, 0, 0, interlace], 8);
  const channels = color === 6 ? 4 : color === 2 ? 3 : 1;
  const raw = options.raw ?? new Uint8Array((width * channels + 1) * height);
  return new Uint8Array(Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), makeChunk("IHDR", header),
    makeChunk("IDAT", options.compressed ?? deflateSync(raw)), ...(options.extra ? [options.extra] : []),
    makeChunk("IEND", new Uint8Array())]));
}
function decodeMask(bytes: Uint8Array): { pixels: Uint8Array; width: number; height: number } {
  const data = Buffer.from(bytes), types: string[] = [], payloads: Buffer[] = [];
  assert.deepEqual([...data.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
  let width = 0, height = 0, at = 8;
  while (at < data.length) {
    const size = data.readUInt32BE(at), end = at + size + 12, type = data.toString("ascii", at + 4, at + 8);
    assert.ok(end <= data.length); types.push(type);
    assert.equal(crc(data.subarray(at + 4, end - 4)), data.readUInt32BE(end - 4));
    if (type === "IHDR") {
      width = data.readUInt32BE(at + 8); height = data.readUInt32BE(at + 12);
      assert.deepEqual([...data.subarray(at + 16, at + 21)], [8, 0, 0, 0, 0]);
    } else if (type === "IDAT") payloads.push(data.subarray(at + 8, end - 4));
    at = end;
  }
  assert.deepEqual(types, ["IHDR", "IDAT", "IEND"]);
  assert.equal(at, data.length);
  const rows = inflateSync(Buffer.concat(payloads));
  assert.equal(rows.length, (width + 1) * height);
  const pixels = new Uint8Array(width * height);
  for (let row = 0; row < height; row++) {
    assert.equal(rows[row * (width + 1)], 0);
    pixels.set(rows.subarray(row * (width + 1) + 1, (row + 1) * (width + 1)), row * width);
  }
  assert.ok(pixels.every(value => value === 0 || value === 255));
  return { pixels, width, height };
}

const target = targetPng();
function binding(png = target): MaskEditorBinding {
  return createMaskEditorBinding({ stage_id: "a".repeat(32), source_fingerprint: "b".repeat(64),
    target_condition: 45, generated_sha256: sha(png), fit_sha256: "c".repeat(64) });
}
function polygon(points: number[][], kind: "allowed" | "occluded" = "allowed"): MaskPolygon {
  return { kind, points: points.map(([x, y]) => ({ x, y })) };
}
const square = polygon([[0, 0], [4, 0], [4, 4], [0, 4]]);

// Winding-number oracle, independent from the scanline producer.
function oracleContains(points: MaskPoint[], x: number, y: number): boolean {
  let winding = 0;
  for (let i = 0; i < points.length; i++) {
    const a = points[i], b = points[(i + 1) % points.length];
    const side = (b.x - a.x) * (y - a.y) - (b.y - a.y) * (x - a.x);
    if (Math.abs(side) <= 1e-9 && x >= Math.min(a.x, b.x) && x <= Math.max(a.x, b.x)
      && y >= Math.min(a.y, b.y) && y <= Math.max(a.y, b.y)) return true;
    if (a.y <= y && b.y > y && side > 0) winding++;
    else if (a.y > y && b.y <= y && side < 0) winding--;
  }
  return winding !== 0;
}
function assertOracle(polygons: MaskPolygon[], width: number, height: number): void {
  const actual = rasterizeMaskPolygons(polygons, width, height);
  let aCount = 0, oCount = 0;
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const o = polygons.some(p => p.kind === "occluded" && oracleContains(p.points, x + 0.5, y + 0.5));
    const a = !o && polygons.some(p => p.kind === "allowed" && oracleContains(p.points, x + 0.5, y + 0.5));
    const at = y * width + x;
    assert.equal(actual.allowed[at], a ? 255 : 0, `allowed ${x},${y}`);
    assert.equal(actual.occluded[at], o ? 255 : 0, `occluded ${x},${y}`);
    aCount += Number(a); oCount += Number(o);
  }
  assert.equal(actual.allowedCount, aCount); assert.equal(actual.occludedCount, oCount);
  assert.equal(actual.unknownCount, width * height - aCount - oCount);
}

test("binding roundtrip keeps exact three hashes and stage but owns a copy", () => {
  const original = binding(), roundtrip = parseMaskEditorBinding(JSON.stringify(original));
  assert.deepEqual(roundtrip, original); assert.equal(roundtrip.protocol_id, MASK_EDITOR_PROTOCOL);
  original.stage.source_fingerprint = "d".repeat(64);
  assert.equal(roundtrip.stage.source_fingerprint, "b".repeat(64));
});
test("binding rejects extra/missing fields, raised flags and invalid identifiers", () => {
  for (const edit of [
    (v: any) => { v.g3_complete = true; }, (v: any) => { delete v.width; },
    (v: any) => { v.stage.session_id = "a".repeat(32); }, (v: any) => { v.research_only = false; },
    (v: any) => { v.width = 512; }, (v: any) => { v.protocol_id = "other"; },
    (v: any) => { v.stage.stage_id = "A".repeat(32); },
    (v: any) => { v.stage.generated_sha256 = "g".repeat(64); },
    (v: any) => { v.stage.source_fingerprint = "B".repeat(64); },
    (v: any) => { v.stage.fit_sha256 = "f".repeat(63); },
    (v: any) => { v.stage.target_condition = 42.5; }, (v: any) => { v.stage.target_condition = 71; },
  ]) {
    const value = binding(); edit(value);
    assert.throws(() => parseMaskEditorBinding(JSON.stringify(value)));
  }
});
test("binding rejects duplicate decoded keys and byte budget including multibyte text", () => {
  const valid = JSON.stringify(binding());
  assert.throws(() => parseMaskEditorBinding(valid.replace('"width":1024', '"width":1024,"width":1024')), /重复/);
  assert.throws(() => parseMaskEditorBinding(valid.replace('"width":1024', '"width":1024,"\\u0077idth":1024')), /重复/);
  assert.throws(() => parseMaskEditorBinding(" ".repeat(16385) + valid), /16KiB/);
  assert.throws(() => parseMaskEditorBinding(JSON.stringify({ extra: "中".repeat(6000) })), /16KiB/);
  for (const value of ["", "{", "null", "[]", "123"])
    assert.throws(() => parseMaskEditorBinding(value));
});
test("target verifies independently made RGB and RGBA PNG and native SHA", async () => {
  await validateMaskEditorTarget(binding(), target);
  const rgba = targetPng({ color: 6 });
  await validateMaskEditorTarget(binding(rgba), rgba);
  const view = Buffer.concat([Buffer.from([11]), Buffer.from(target), Buffer.from([22])]);
  await validateMaskEditorTarget(binding(), view.subarray(1, -1));
  await assert.rejects(validateMaskEditorTarget({ ...binding(), stage: { ...binding().stage, generated_sha256: "d".repeat(64) } }, target), /指纹/);
});
test("target rejects CRC, trailing bytes, IHDR format and missing compressed data", async () => {
  const corrupt = target.slice(); corrupt[29] ^= 1;
  const cases = [corrupt, Buffer.concat([target, Buffer.from([1])]), target.subarray(0, -1),
    targetPng({ width: 512 }), targetPng({ height: 512 }), targetPng({ color: 0 }),
    targetPng({ color: 3 }), targetPng({ depth: 16 }), targetPng({ interlace: 1 }),
    targetPng({ compressed: new Uint8Array() }), new Uint8Array(4 * 1024 ** 2 + 1)];
  for (const png of cases) await assert.rejects(validateMaskEditorTarget(binding(png), png));
});
test("target bounds actual inflation and checks exact scanline length and filters", async () => {
  const wrongFilter = new Uint8Array((1024 * 3 + 1) * 1024); wrongFilter[0] = 5;
  for (const raw of [new Uint8Array(1), new Uint8Array((1024 * 3 + 1) * 1024 + 1), wrongFilter]) {
    const png = targetPng({ raw }); await assert.rejects(validateMaskEditorTarget(binding(png), png));
  }
  const invalidDeflate = targetPng({ compressed: new Uint8Array([1, 2, 3, 4]) });
  await assert.rejects(validateMaskEditorTarget(binding(invalidDeflate), invalidDeflate));
});
test("target rejects unknown critical chunks but permits CRC-valid ancillary metadata", async () => {
  const withText = targetPng({ extra: makeChunk("tEXt", textEncoder.encode("synthetic\0test")) });
  await validateMaskEditorTarget(binding(withText), withText);
  const withCritical = targetPng({ extra: makeChunk("ABCD", new Uint8Array()) });
  await assert.rejects(validateMaskEditorTarget(binding(withCritical), withCritical));
});
test("target validation snapshots Node Buffer inputs before asynchronous inflation", async () => {
  const buffer = Buffer.from(target), current = binding(buffer);
  const pending = validateMaskEditorTarget(current, buffer);
  buffer.fill(0);
  await pending;
});
test("empty editor has two zero masks and no implicit allowed region", () => {
  const actual = rasterizeMaskPolygons([], 8, 7);
  assert.equal(actual.allowedCount, 0); assert.equal(actual.occludedCount, 0); assert.equal(actual.unknownCount, 56);
  assert.ok(actual.allowed.every(x => x === 0) && actual.occluded.every(x => x === 0));
});
test("native centers cover rectangle interior independent of winding", () => {
  assertOracle([square], 7, 6);
  assertOracle([{ ...square, points: [...square.points].reverse() }], 7, 6);
  assert.equal(rasterizeMaskPolygons([square], 7, 6).allowedCount, 16);
});
test("pixel centers on horizontal, diagonal, vertical edges and vertices are included", () => {
  for (const p of [polygon([[0.5, 0.5], [5.5, 0.5], [5.5, 5.5], [0.5, 5.5]]),
    polygon([[0.5, 0.5], [5.5, 5.5], [0.5, 5.5]]),
    polygon([[1.5, 0.5], [4.5, 3.5], [1.5, 6.5]])]) assertOracle([p], 7, 7);
});
test("concave simple polygon agrees with independent winding oracle", () => {
  assertOracle([polygon([[0, 0], [6, 0], [6, 2], [2, 2], [2, 6], [0, 6]])], 8, 8);
});
test("allowed union subtracts occlusion irrespective of polygon draw order", () => {
  const second = polygon([[2, 1], [7, 1], [7, 6], [2, 6]]);
  const excluded = polygon([[3, 0], [5, 0], [5, 7], [3, 7]], "occluded");
  const first = rasterizeMaskPolygons([square, second, excluded], 8, 8);
  const last = rasterizeMaskPolygons([excluded, second, square], 8, 8);
  assert.deepEqual(first, last); assertOracle([square, second, excluded], 8, 8);
});
test("64 deterministic fractional radial polygons agree per pixel with independent oracle", () => {
  for (let seed = 1; seed <= 64; seed++) {
    const count = 3 + seed % 8;
    const points = Array.from({ length: count }, (_, i) => {
      const angle = i * Math.PI * 2 / count + seed * 0.017;
      const radius = 3 + ((seed * 17 + i * 13) % 11) / 5;
      return { x: 8 + Math.cos(angle) * radius, y: 8 + Math.sin(angle) * radius };
    });
    assertOracle([{ kind: seed % 2 ? "allowed" : "occluded", points }], 16, 16);
  }
});
test("edge tolerance at pixel centers follows absolute cross product contract", () => {
  for (const displacement of [-1e-10, 0, 1e-10, 2e-9]) {
    const p = polygon([[0.5 + displacement, 0], [0.5 + displacement, 4], [4, 4], [4, 0]]);
    assertOracle([p], 5, 5);
  }
});
test("pixel edge tolerance is not an implicit minimum polygon area", () => {
  const tiny = polygon([[1, 1], [1.000001, 1], [1, 1.000001]]);
  assertOracle([tiny], 2, 2);
  assert.equal(rasterizeMaskPolygons([tiny], 2, 2).allowedCount, 0);
  assertOracle([polygon([[0.5, 0.5], [0.500001, 0.5], [0.5, 0.500001]])], 2, 2);
});
test("nonzero subpixel triangles remain valid near either native image corner", () => {
  for (const offset of [1, 1023]) {
    const tiny = polygon([[offset, offset], [offset + 0.000001, offset], [offset, offset + 0.000001]]);
    assertOracle([tiny], 1024, 1024);
    const raster = rasterizeMaskPolygons([tiny]);
    assert.equal(raster.allowedCount, 0); assert.equal(raster.occludedCount, 0);
    assert.equal(raster.unknownCount, 1024 ** 2);
  }
});
test("coordinates never use implicit clipping or accept nonfinite values", () => {
  for (const point of [{ x: -0.001, y: 1 }, { x: 8.001, y: 1 }, { x: 1, y: -1 },
    { x: 1, y: NaN }, { x: Infinity, y: 1 }]) {
    assert.throws(() => rasterizeMaskPolygons([{ kind: "allowed", points: [point, { x: 4, y: 0 }, { x: 4, y: 4 }] }], 8, 8));
  }
  for (const size of [0, -1, 0.5, NaN, Infinity, 1025]) assert.throws(() => rasterizeMaskPolygons([], size, 4));
});
test("non-simple, repeated, zero area and retraced adjacent edges are refused", () => {
  for (const points of [
    [[0, 0], [4, 4], [0, 4], [4, 0]],
    [[0, 0], [4, 4], [0, 4], [4, 0], [5, 2]],
    [[0, 0], [4, 0], [4, 4], [0, 0]], [[0, 0], [1, 1], [2, 2]],
    [[0, 0], [4, 0], [2, 0], [4, 4], [0, 4]],
    [[0, 0], [4, 0], [4, 4], [2, 0], [0, 4]],
  ]) assert.throws(() => rasterizeMaskPolygons([polygon(points)], 8, 8));
});
test("polygon and vertex budgets are enforced before raster allocation", () => {
  assert.throws(() => rasterizeMaskPolygons(Array.from({ length: 65 }, () => square), 8, 8));
  assert.throws(() => rasterizeMaskPolygons([polygon([[0, 0], [1, 1]])], 8, 8));
  const radial = (n: number): MaskPolygon => ({ kind: "allowed", points: Array.from({ length: n }, (_, i) => ({
    x: 4 + Math.cos(i * 2 * Math.PI / n) * 3, y: 4 + Math.sin(i * 2 * Math.PI / n) * 3,
  })) });
  assert.throws(() => rasterizeMaskPolygons([radial(129)], 8, 8));
  assert.throws(() => rasterizeMaskPolygons(Array.from({ length: 33 }, () => radial(128)), 8, 8), /4096/);
});
test("raster outputs and geometry do not alias each other or caller inputs", () => {
  const p = structuredClone(square), raster = rasterizeMaskPolygons([p], 8, 8);
  p.points[0].x = 100; raster.allowed[0] = 0;
  assert.equal(raster.occluded[0], 0);
  assert.equal(rasterizeMaskPolygons([square], 8, 8).allowed[0], 255);
});
test("L8 encoder independently decodes binary rows including full zeros and ones", async () => {
  for (const pixels of [new Uint8Array(15), new Uint8Array(15).fill(255),
    Uint8Array.from({ length: 15 }, (_, i) => i % 3 ? 255 : 0)]) {
    const before = pixels.slice(), png = await encodeMaskPng(pixels, 5, 3), decoded = decodeMask(png);
    assert.deepEqual(decoded.pixels, before); assert.equal(decoded.width, 5); assert.equal(decoded.height, 3);
    assert.deepEqual(pixels, before);
  }
});
test("L8 encoder honors Uint8Array subviews and owns pre-await scanlines", async () => {
  const storage = new Uint8Array([17, 0, 255, 255, 0, 18]);
  const pending = encodeMaskPng(storage.subarray(1, 5), 2, 2);
  storage.fill(91);
  assert.deepEqual([...decodeMask(await pending).pixels], [0, 255, 255, 0]);
});
test("L8 encoder rejects nonbinary bytes, unsupported storage, shape and dimensions", async () => {
  for (const pixels of [new Uint8Array([0, 1, 255, 0]), new Uint8Array(3),
    new Uint8ClampedArray(4) as unknown as Uint8Array, new Float32Array(4) as unknown as Uint8Array])
    await assert.rejects(encodeMaskPng(pixels, 2, 2));
  for (const size of [0, -1, 1.5, NaN, Infinity, 1025])
    await assert.rejects(encodeMaskPng(new Uint8Array(1), size, 1));
});
test("draft exports two disjoint native L8 masks with exact hashes and closed flags", async () => {
  const polygons = [polygon([[0, 0], [12, 0], [12, 12], [0, 12]]), polygon([[4, 4], [8, 4], [8, 8], [4, 8]], "occluded")];
  const exported = await exportMaskDraft(binding(), target, polygons, reviewer);
  const a = decodeMask(exported.allowedPng), o = decodeMask(exported.occludedPng), d = exported.draft as any;
  assert.equal(a.width, 1024); assert.equal(a.height, 1024); assert.equal(o.width, 1024); assert.equal(o.height, 1024);
  assert.equal(d.status, "draft_unsubmitted"); assert.deepEqual(d.binding, binding());
  assert.deepEqual(d.polygons, polygons); assert.deepEqual(d.review, reviewer);
  assert.equal(d.masks.allowed.sha256, sha(exported.allowedPng)); assert.equal(d.masks.occluded.sha256, sha(exported.occludedPng));
  assert.equal(d.masks.allowed.bytes, exported.allowedPng.length); assert.equal(d.masks.occluded.bytes, exported.occludedPng.length);
  assert.equal(d.pixel_counts.allowed, 128); assert.equal(d.pixel_counts.occluded, 16);
  assert.equal(d.pixel_counts.unknown, 1024 ** 2 - 144);
  for (let i = 0; i < a.pixels.length; i++) assert.ok(!(a.pixels[i] && o.pixels[i]));
  for (const flag of ["human_review_completed", "identity_quality_accepted", "age_quality_accepted", "visual_seam_quality_accepted",
    "years_calibrated", "service_ready", "production_enabled", "g3_complete"]) assert.equal(d[flag], false);
  assert.equal(d.research_only, true);
});
test("draft owns all caller state before its first await", async () => {
  const current = binding(), png = target.slice(), polys = [structuredClone(square)], person = { ...reviewer };
  const pending = exportMaskDraft(current, png, polys, person);
  current.stage.fit_sha256 = "f".repeat(64); polys[0].points[0].x = 3000; person.reviewer = "changed"; png.fill(0);
  const d = (await pending).draft as any;
  assert.equal(d.binding.stage.fit_sha256, "c".repeat(64)); assert.deepEqual(d.polygons, [square]);
  assert.equal(d.review.reviewer, reviewer.reviewer);
});
test("draft refuses zero allowed pixels including complete occlusion", async () => {
  await assert.rejects(exportMaskDraft(binding(), target, [], reviewer), /允许/);
  await assert.rejects(exportMaskDraft(binding(), target, [square, { ...square, kind: "occluded" }], reviewer), /允许/);
});
test("draft refuses explicit all-allowed image instead of silently changing annotation", async () => {
  const full = polygon([[0, 0], [1024, 0], [1024, 1024], [0, 1024]]);
  await assert.rejects(exportMaskDraft(binding(), target, [full], reviewer), /全部放行/);
  assert.equal(rasterizeMaskPolygons([full]).allowedCount, 1024 ** 2);
});
test("draft requires explicit bounded reviewer metadata and cannot claim approval", async () => {
  for (const value of [ { ...reviewer, reviewer: " " }, { ...reviewer, reviewer: "x".repeat(129) },
    { ...reviewer, method: "" }, { ...reviewer, version: "a\nb" }, { ...reviewer, version: "x".repeat(65) },
    { ...reviewer, reviewer_kind: "" }, { ...reviewer, human_review_completed: true }])
    await assert.rejects(exportMaskDraft(binding(), target, [square], value as MaskReviewer));
  const human = (await exportMaskDraft(binding(), target, [square], { ...reviewer, reviewer_kind: "human" })).draft as any;
  assert.equal(human.review.reviewer_kind, "human"); assert.equal(human.human_review_completed, false);
});
