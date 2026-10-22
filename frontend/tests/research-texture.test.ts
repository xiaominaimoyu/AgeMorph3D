import assert from "node:assert/strict";
import test from "node:test";
import {
  createResearchTimeline,
  sampleResearchTexture,
} from "../src/research-texture.ts";
import type { TextureAnchor } from "../src/research-texture.ts";

const anchor = (
  age: number,
  rgba: number[],
  kind: TextureAnchor["kind"] = "sam_condition",
): TextureAnchor => ({ age, rgba: new Uint8ClampedArray(rgba), width: rgba.length / 4, height: 1, kind });

test("opaque black/white midpoint uses linear light, giving sRGB188 rather than128", () => {
  const timeline = createResearchTimeline([
    anchor(20, [0, 0, 0, 255]), anchor(70, [255, 255, 255, 255]),
  ], null);
  assert.deepEqual([...sampleResearchTexture(timeline, 45).rgba], [188, 188, 188, 255]);
});

test("premultiplied interpolation fades supported color without dark fringes or unknown fill", () => {
  const left = anchor(20, [255, 32, 0, 255, 0, 0, 0, 0]);
  const right = anchor(70, [0, 0, 0, 0, 0, 0, 0, 0]);
  const timeline = createResearchTimeline([left, right], null);
  assert.deepEqual([...sampleResearchTexture(timeline, 45).rgba], [255, 32, 0, 128, 0, 0, 0, 0]);
  assert.deepEqual([...sampleResearchTexture(timeline, 69.99999).rgba], new Array(8).fill(0));
  assert.deepEqual([...left.rgba], [255, 32, 0, 255, 0, 0, 0, 0]);
  assert.deepEqual([...right.rgba], new Array(8).fill(0));
});

test("alpha half-integer quantization matches NumPy ties-to-even", () => {
  const timeline = createResearchTimeline([
    anchor(20, [0, 0, 0, 0]), anchor(70, [255, 0, 0, 255]),
  ], null);
  // 0.3 * 255 = 76.5; Math.round would return77, NumPy rint returns76.
  assert.deepEqual([...sampleResearchTexture(timeline, 35).rgba], [255, 0, 0, 76]);
  assert.deepEqual([...sampleResearchTexture(timeline, 45).rgba], [255, 0, 0, 128]);
});

for (const originalFirst of [true, false]) {
  test(`original source overrides same-age SAM in either order (${originalFirst})`, () => {
    const original = anchor(42, [0, 255, 0, 255], "original_source");
    const sam = anchor(42, [255, 0, 0, 255]);
    const pair = originalFirst ? [original, sam] : [sam, original];
    const inputs = [anchor(20, [0, 0, 255, 255]), ...pair, anchor(70, [255, 255, 255, 255])];
    const timeline = createResearchTimeline(inputs, 42);
    assert.deepEqual(timeline.anchors.map((a) => a.age), [20, 42, 70]);
    const exact = sampleResearchTexture(timeline, 42);
    assert.equal(exact.rgba, original.rgba);
    assert.equal(exact.targetAge, 42);
    assert.equal(exact.sourceLabel, 42);
    assert.equal(exact.exactSource, true);
    assert.equal(exact.kind, "research-display-only");
    assert.equal(sampleResearchTexture(timeline, 41.999).exactSource, false);
    assert.equal(sampleResearchTexture(timeline, 42.001).exactSource, false);
    assert.deepEqual([...sam.rgba], [255, 0, 0, 255]);
    assert.deepEqual(inputs.map((a) => a.age), [20, 42, 42, 70]);
  });
}

test("fractional original source keeps exact42.5 reference while SAM conditions reject fractions", () => {
  const original = anchor(42.5, [0, 255, 0, 255], "original_source");
  const timeline = createResearchTimeline([
    anchor(20, [255, 0, 0, 255]), original, anchor(70, [0, 0, 255, 255]),
  ], 42.5);
  assert.equal(sampleResearchTexture(timeline, 42.5).rgba, original.rgba);
  assert.equal(sampleResearchTexture(timeline, 42.5).exactSource, true);
  for (const target of [42.499, 42.501]) {
    const frame = sampleResearchTexture(timeline, target);
    assert.equal(frame.targetAge, target);
    assert.equal(frame.exactSource, false);
  }
  assert.throws(() => createResearchTimeline([
    anchor(20, [0, 0, 0, 255]), anchor(42.5, [255, 0, 0, 255]),
  ], null), /SAM条件.*整数/);
  assert.throws(() => createResearchTimeline([
    original, anchor(42.5, [255, 0, 0, 255]),
  ], 42.5), /SAM条件.*整数/);
});

test("uneven anchors use actual year distances and do not round fractional requests", () => {
  const timeline = createResearchTimeline([
    anchor(20, [255, 0, 0, 255]), anchor(30, [0, 0, 0, 0]), anchor(70, [0, 0, 255, 255]),
  ], null);
  assert.deepEqual([...sampleResearchTexture(timeline, 25).rgba], [255, 0, 0, 128]);
  assert.deepEqual([...sampleResearchTexture(timeline, 50).rgba], [0, 0, 255, 128]);
  assert.equal(sampleResearchTexture(timeline, 30.125).targetAge, 30.125);
});

test("unknown source remains unknown and exact SAM anchors do not become source resets", () => {
  const left = anchor(20, [12, 34, 56, 255]);
  const timeline = createResearchTimeline([left, anchor(70, [0, 0, 0, 0])], null);
  const frame = sampleResearchTexture(timeline, 20);
  assert.equal(frame.sourceLabel, null);
  assert.equal(frame.exactSource, false);
  assert.deepEqual(frame.rgba, left.rgba);
  assert.notEqual(frame.rgba, left.rgba);
  assert.throws(() => createResearchTimeline([anchor(20, [0, 0, 0, 255], "original_source")], null));
  assert.throws(() => createResearchTimeline([left], 20), /唯一原始源/);
  assert.throws(() => createResearchTimeline([anchor(42, [0, 0, 0, 255], "original_source")], 42.5));
});

test("uncovered ages are rejected instead of clamped or extrapolated", () => {
  const timeline = createResearchTimeline([anchor(30, [0, 0, 0, 255]), anchor(50, [255, 255, 255, 255])], null);
  for (const age of [20, 29.999, 50.001, 70])
    assert.throws(() => sampleResearchTexture(timeline, age), /外推/);
});

test("nonfinite, boolean and out-of-range ages are rejected at both inputs", () => {
  const good = [anchor(20, [0, 0, 0, 255]), anchor(70, [0, 0, 0, 255])];
  const timeline = createResearchTimeline(good, null);
  for (const value of [NaN, Infinity, -Infinity, 19, 71, true, "45", undefined]) {
    assert.throws(() => sampleResearchTexture(timeline, value as number));
    assert.throws(() => createResearchTimeline([anchor(value as number, [0, 0, 0, 255])], null));
    assert.throws(() => createResearchTimeline(good, value as number));
  }
});

test("duplicate condition/source ages cannot silently choose a favorable input", () => {
  assert.throws(() => createResearchTimeline([anchor(20, [0, 0, 0, 255]), anchor(20, [255, 255, 255, 255])], null), /重复/);
  assert.throws(() => createResearchTimeline([anchor(42, [0, 0, 0, 255], "original_source"), anchor(42, [255, 255, 255, 255], "original_source")], 42), /重复/);
  for (const pair of [
    [anchor(42, [0, 255, 0, 255], "original_source"), anchor(42, [255, 0, 0, 255])],
    [anchor(42, [255, 0, 0, 255]), anchor(42, [0, 255, 0, 255], "original_source")],
  ]) assert.throws(() => createResearchTimeline([...pair, anchor(42, [0, 0, 255, 255])], 42), /重复/);
  assert.throws(() => createResearchTimeline([], null), /数量/);
});

test("malformed dimensions, storage, support and unknown RGB are rejected", () => {
  const good = anchor(20, [0, 0, 0, 255]);
  const invalid = [
    { ...good, width: 0 }, { ...good, width: 1.5 }, { ...good, height: Infinity },
    { ...good, width: 2 }, { ...good, rgba: new Uint8Array([0, 0, 0, 255]) },
    { ...good, rgba: new Uint8ClampedArray([0, 0, 0]) },
    anchor(20, [0, 0, 0, 128]), anchor(20, [12, 0, 0, 0]),
    { ...good, kind: "generated" },
  ];
  for (const value of invalid)
    assert.throws(() => createResearchTimeline([value as TextureAnchor], null));
  assert.throws(() => createResearchTimeline([good, anchor(70, [0, 0, 0, 255, 0, 0, 0, 255])], null), /相同UV/);
  // Discarded same-age SAM inputs are still validated.
  assert.throws(() => createResearchTimeline([anchor(20, [0, 0, 0, 255], "original_source"), anchor(20, [255, 0, 0, 0])], 20));
});

test("metadata is copied/frozen while caller buffers and source order remain untouched", () => {
  const a = anchor(70, [255, 0, 0, 255]), b = anchor(20, [0, 0, 255, 255]);
  const inputs = Object.freeze([a, b]);
  const timeline = createResearchTimeline(inputs, null);
  assert.deepEqual(inputs.map((item) => item.age), [70, 20]);
  assert.ok(Object.isFrozen(timeline) && Object.isFrozen(timeline.anchors));
  assert.ok(Object.isFrozen(timeline.anchors[0]));
  assert.notEqual(timeline.anchors[0], b);
  sampleResearchTexture(timeline, 45);
  assert.deepEqual([...a.rgba], [255, 0, 0, 255]);
  assert.deepEqual([...b.rgba], [0, 0, 255, 255]);
  // A caller violating the buffer contract cannot introduce hidden unknown RGB.
  b.rgba.set([255, 0, 0, 0]);
  assert.throws(() => sampleResearchTexture(timeline, 45), /RGBA零/);
});

test("anchor count and total pixel budget bound validation work", () => {
  const a = anchor(20, [0, 0, 0, 255]);
  assert.throws(() => createResearchTimeline(new Array(65).fill(a), null), /数量/);
  // Storage is shared so this checks the total budget with one 32MB allocation.
  const pixels = 8_000_001;
  const rgba = new Uint8ClampedArray(pixels * 4);
  assert.throws(() => createResearchTimeline([
    { age: 20, width: pixels, height: 1, rgba, kind: "sam_condition" },
    { age: 70, width: pixels, height: 1, rgba, kind: "sam_condition" },
  ], null), /预算/);
});
