import assert from "node:assert/strict";
import test from "node:test";
import { inflateSync } from "node:zlib";
import { encodeResearchRgbaPng, replaceResearchPng } from "../src/research-rgba.ts";

const NAME = "AgeMorph3D_Research_Display_RGBA";
const encoder = new TextEncoder();
const align4 = (size: number): number => Math.ceil(size / 4) * 4;

// Independent bit-at-a-time CRC and zlib decoder, without the production codec.
function decodePng(png: Uint8Array): { rgba: Uint8Array; width: number; height: number } {
  assert.deepEqual([...png.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
  const view = new DataView(png.buffer, png.byteOffset, png.byteLength);
  const types: string[] = [], compressed: Uint8Array[] = [];
  let width = 0, height = 0, offset = 8;
  while (offset < png.length) {
    const size = view.getUint32(offset), end = offset + 12 + size;
    assert.ok(end <= png.length);
    const type = new TextDecoder().decode(png.subarray(offset + 4, offset + 8));
    types.push(type);
    let crc = 0xffffffff;
    for (const byte of png.subarray(offset + 4, end - 4)) {
      crc ^= byte;
      for (let bit = 0; bit < 8; bit++) crc = (crc & 1) ? (crc >>> 1) ^ 0xedb88320 : crc >>> 1;
    }
    assert.equal(view.getUint32(end - 4), (crc ^ 0xffffffff) >>> 0);
    if (type === "IHDR") {
      assert.equal(size, 13);
      width = view.getUint32(offset + 8); height = view.getUint32(offset + 12);
      assert.deepEqual([...png.subarray(offset + 16, offset + 21)], [8, 6, 0, 0, 0]);
    }
    if (type === "IDAT") compressed.push(png.subarray(offset + 8, end - 4));
    offset = end;
  }
  assert.deepEqual(types, ["IHDR", "IDAT", "IEND"]);
  assert.equal(offset, png.length);
  const rows = inflateSync(Buffer.concat(compressed));
  assert.equal(rows.length, (width * 4 + 1) * height);
  const rgba = new Uint8Array(width * height * 4);
  for (let row = 0; row < height; row++) {
    const start = row * (width * 4 + 1);
    assert.equal(rows[start], 0);
    rgba.set(rows.subarray(start + 1, start + 1 + width * 4), row * width * 4);
  }
  return { rgba, width, height };
}

test("PNG preserves every straight RGB byte at all 256 alpha levels and multiple rows", async () => {
  const rgba = new Uint8ClampedArray(256 * 2 * 4);
  for (let row = 0; row < 2; row++) {
    for (let alpha = 1; alpha < 256; alpha++) {
      const index = (row * 256 + alpha) * 4;
      rgba.set([150 - row, 100 + row, 80, alpha], index);
    }
  }
  const snapshot = rgba.slice();
  const decoded = decodePng(await encodeResearchRgbaPng(rgba, 256, 2));
  assert.equal(decoded.width, 256); assert.equal(decoded.height, 2);
  assert.deepEqual([...decoded.rgba], [...rgba]);
  assert.deepEqual([...decoded.rgba.subarray(4, 8)], [150, 100, 80, 1]);
  assert.deepEqual(rgba, snapshot);
});

test("PNG accepts bounded Uint8Array subviews without reading unrelated backing bytes", async () => {
  const backing = new Uint8Array([99, 150, 100, 80, 2, 98]);
  const png = await encodeResearchRgbaPng(backing.subarray(1, 5), 1, 1);
  assert.deepEqual([...decodePng(png).rgba], [150, 100, 80, 2]);
  assert.deepEqual([...backing], [99, 150, 100, 80, 2, 98]);
});

test("PNG rejects hidden RGB in unknown pixels and malformed dimensions or storage", async () => {
  await assert.rejects(encodeResearchRgbaPng(new Uint8Array([1, 0, 0, 0]), 1, 1), /RGBA零/);
  const rgba = new Uint8Array([0, 0, 0, 0]);
  for (const dimension of [0, -1, 1.5, NaN, Infinity, 16_000_001, Number.MAX_SAFE_INTEGER]) {
    await assert.rejects(encodeResearchRgbaPng(rgba, dimension, 1));
    await assert.rejects(encodeResearchRgbaPng(rgba, 1, dimension));
  }
  await assert.rejects(encodeResearchRgbaPng(new Uint8Array(3), 1, 1));
  await assert.rejects(encodeResearchRgbaPng(new Float32Array(4) as unknown as Uint8Array, 1, 1));
  await assert.rejects(encodeResearchRgbaPng(rgba, 4001, 4000));
});

type Document = Record<string, any>;

function fixtureDocument(): Document {
  return {
    asset: { version: "2.0", generator: "synthetic-rgba-test" },
    buffers: [{ byteLength: 45 }],
    bufferViews: [
      { buffer: 0, byteOffset: 0, byteLength: 36, target: 34962 },
      { buffer: 0, byteOffset: 36, byteLength: 5 },
      { buffer: 0, byteOffset: 41, byteLength: 4 },
    ],
    accessors: [{ bufferView: 0, byteOffset: 0, componentType: 5126, count: 3, type: "VEC3", min: [0, 0, 0], max: [1, 1, 0] }],
    images: [{ bufferView: 1, mimeType: "image/png", name: "base" }, { bufferView: 2, mimeType: "image/png", name: "normal" }],
    textures: [{ name: NAME, source: 0, sampler: 0 }, { name: "normal", source: 1, sampler: 0 }],
    samplers: [{ magFilter: 9729, minFilter: 9729 }],
    materials: [{ pbrMetallicRoughness: { baseColorTexture: { index: 0 } }, normalTexture: { index: 1 }, alphaMode: "BLEND" }],
    meshes: [{ primitives: [{ attributes: { POSITION: 0 }, material: 0 }] }],
    nodes: [{ mesh: 0, name: "synthetic geometry" }], scenes: [{ nodes: [0] }], scene: 0,
    extras: { researchOnly: true, targetAge: 42.25 },
  };
}

function buildGlb(document = fixtureDocument(), binary = Uint8Array.from({ length: 45 }, (_, i) => (i * 17) % 256)): ArrayBuffer {
  const json = encoder.encode(JSON.stringify(document)), jsonSize = align4(json.length), binarySize = align4(binary.length);
  const output = new Uint8Array(28 + jsonSize + binarySize), view = new DataView(output.buffer);
  view.setUint32(0, 0x46546c67, true); view.setUint32(4, 2, true); view.setUint32(8, output.length, true);
  view.setUint32(12, jsonSize, true); view.setUint32(16, 0x4e4f534a, true);
  output.fill(32, 20, 20 + jsonSize); output.set(json, 20);
  view.setUint32(20 + jsonSize, binarySize, true); view.setUint32(24 + jsonSize, 0x004e4942, true);
  output.set(binary, 28 + jsonSize);
  return output.buffer;
}

function readGlb(glb: ArrayBuffer): { document: Document; binary: Uint8Array; jsonSize: number } {
  const header = new DataView(glb), jsonSize = header.getUint32(12, true);
  assert.equal(header.getUint32(8, true), glb.byteLength);
  assert.equal(header.getUint32(20 + jsonSize, true), glb.byteLength - 28 - jsonSize);
  return {
    document: JSON.parse(new TextDecoder().decode(new Uint8Array(glb, 20, jsonSize))),
    binary: new Uint8Array(glb, 28 + jsonSize), jsonSize,
  };
}

const tinyPng = (): Promise<Uint8Array> => encodeResearchRgbaPng(new Uint8Array([150, 100, 80, 1]), 1, 1);

test("GLB appends one aligned PNG and preserves original geometry, descriptors, metadata and caller inputs", async () => {
  const input = buildGlb(), snapshot = input.slice(0), png = await tinyPng(), pngSnapshot = png.slice();
  const before = readGlb(input), output = await replaceResearchPng(input, png, NAME), after = readGlb(output);
  const pngView = after.document.bufferViews.at(-1);
  assert.deepEqual(pngView, { buffer: 0, byteOffset: 48, byteLength: png.length });
  assert.equal(after.document.images[0].bufferView, 3);
  assert.equal(after.document.buffers[0].byteLength, 48 + png.length);
  assert.deepEqual(after.binary.subarray(0, 45), before.binary.subarray(0, 45));
  assert.deepEqual([...after.binary.subarray(45, 48)], [0, 0, 0]);
  assert.deepEqual(after.binary.subarray(48, 48 + png.length), png);
  assert.ok([...after.binary.subarray(48 + png.length)].every((value) => value === 0));
  assert.deepEqual([...decodePng(after.binary.subarray(48, 48 + png.length)).rgba], [150, 100, 80, 1]);
  const expected = structuredClone(before.document);
  expected.bufferViews.push(pngView); expected.images[0].bufferView = 3; expected.buffers[0].byteLength = 48 + png.length;
  assert.deepEqual(after.document, expected);
  assert.deepEqual(input, snapshot); assert.deepEqual(png, pngSnapshot);
  const jsonStart = encoder.encode(JSON.stringify(after.document)).length;
  assert.ok([...new Uint8Array(output, 20 + jsonStart, after.jsonSize - jsonStart)].every((value) => value === 32));
});

test("GLB routes only named base-color textures and appends PNG once for multiple selected images", async () => {
  const document = fixtureDocument();
  document.textures[1].name = NAME;
  const output = readGlb(await replaceResearchPng(buildGlb(document), await tinyPng(), NAME));
  assert.equal(output.document.images[1].bufferView, 2); // Same marker on a normal map is insufficient.
  document.materials.push({ pbrMetallicRoughness: { baseColorTexture: { index: 1 } } });
  const both = readGlb(await replaceResearchPng(buildGlb(document), await tinyPng(), NAME));
  assert.equal(both.document.bufferViews.length, 4);
  assert.equal(both.document.images[0].bufferView, 3); assert.equal(both.document.images[1].bufferView, 3);
  delete document.materials[0].pbrMetallicRoughness;
  document.materials.pop();
  await assert.rejects(replaceResearchPng(buildGlb(document), await tinyPng(), NAME), /base-color/);
  await assert.rejects(replaceResearchPng(buildGlb(), await tinyPng(), "unmarked"), /base-color/);
});

test("GLB rejects external assets, invalid references and geometry ranges", async () => {
  const mutations: ((document: Document) => void)[] = [
    (d) => { d.buffers[0].uri = "geometry.bin"; },
    (d) => { d.buffers.push({ byteLength: 4 }); },
    (d) => { d.images[1].uri = "data:image/png;base64,ignored"; },
    (d) => { d.buffers[0].byteLength = 49; },
    (d) => { d.buffers[0].byteLength = 40; },
    (d) => { d.bufferViews[0].buffer = 1; },
    (d) => { d.bufferViews[0].byteOffset = -1; },
    (d) => { d.bufferViews[0].byteLength = 46; },
    (d) => { d.accessors[0].count = 4; },
    (d) => { d.accessors[0].bufferView = 4; },
    (d) => { d.accessors[0].byteOffset = 1; },
    (d) => { d.accessors[0].componentType = 999; },
    (d) => { d.accessors[0].type = "__proto__"; },
    (d) => { d.accessors[0].sparse = {}; },
    (d) => { d.images[0].bufferView = 100; },
    (d) => { d.images[0].mimeType = "image/jpeg"; },
    (d) => { d.textures[0].source = 100; },
    (d) => { d.materials[0].pbrMetallicRoughness.baseColorTexture.index = 100; },
    (d) => { d.asset.version = "1.0"; },
  ];
  const png = await tinyPng();
  for (const mutate of mutations) {
    const document = fixtureDocument(); mutate(document);
    await assert.rejects(replaceResearchPng(buildGlb(document), png, NAME));
  }
});

test("GLB rejects truncated/unknown chunks, invalid PNGs, invalid headers and exceeded budgets", async () => {
  const png = await tinyPng(), good = buildGlb();
  for (const length of [0, 12, 31, good.byteLength - 1])
    await assert.rejects(replaceResearchPng(good.slice(0, length), png, NAME));
  for (const [offset, value] of [[0, 0], [4, 1], [8, good.byteLength + 4], [12, 2_000_000], [16, 0], [20 + new DataView(good).getUint32(12, true) + 4, 0]]) {
    const invalid = good.slice(0); new DataView(invalid).setUint32(offset, value, true);
    await assert.rejects(replaceResearchPng(invalid, png, NAME));
  }
  const unknownChunk = new Uint8Array(good.byteLength + 8); unknownChunk.set(new Uint8Array(good));
  new DataView(unknownChunk.buffer).setUint32(8, unknownChunk.length, true);
  await assert.rejects(replaceResearchPng(unknownChunk.buffer, png, NAME), /未知块/);
  const badPadding = good.slice(0);
  new Uint8Array(badPadding)[badPadding.byteLength - 1] = 1;
  await assert.rejects(replaceResearchPng(badPadding, png, NAME), /填充/);
  const invalidPng = png.slice(); invalidPng[29] ^= 1;
  await assert.rejects(replaceResearchPng(good, invalidPng, NAME), /校验/);
  await assert.rejects(replaceResearchPng(good, png.subarray(0, png.length - 1), NAME));
  await assert.rejects(replaceResearchPng(new ArrayBuffer(64 * 1024 * 1024 + 1), png, NAME), /64MiB/);
  const largeJson = fixtureDocument(); largeJson.extras.padding = "x".repeat(1024 * 1024);
  await assert.rejects(replaceResearchPng(buildGlb(largeJson), png, NAME), /JSON/);
});
