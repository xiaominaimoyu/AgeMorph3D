import assert from "node:assert/strict";
import { test } from "node:test";
import { assertRotation, mirroredPose } from "../src/realtime.ts";

test("pose requires a pure proper rotation, rejecting reflections, scale and shear", () => {
  assert.doesNotThrow(() => assertRotation([1, 0, 0, 0, 1, 0, 0, 0, 1]));
  for (const R of [
    [-1, 0, 0, 0, 1, 0, 0, 0, 1],
    [2, 0, 0, 0, 1, 0, 0, 0, 1],
    [1, 0.1, 0, 0, 1, 0, 0, 0, 1],
    [1, 0, 0, 0, Number.NaN, 0, 0, 0, 1],
  ]) assert.throws(() => assertRotation(R), /姿态/);
});

test("mirror display reverses yaw and roll while preserving pitch and proper rotation", () => {
  const c = Math.cos(0.4), s = Math.sin(0.4);
  const cases = [
    { input: [c, 0, s, 0, 1, 0, -s, 0, c], expected: [c, 0, -s, 0, 1, 0, s, 0, c] },
    { input: [c, -s, 0, s, c, 0, 0, 0, 1], expected: [c, s, 0, -s, c, 0, 0, 0, 1] },
    { input: [1, 0, 0, 0, c, -s, 0, s, c], expected: [1, 0, 0, 0, c, -s, 0, s, c] },
  ];
  for (const { input, expected } of cases) {
    const original = { R: input, t: [2, 3, 4] };
    const actual = mirroredPose(original);
    actual.R.forEach((value, index) => assert.ok(Math.abs(value - expected[index]!) < 1e-12));
    assertRotation(actual.R);
    assert.deepEqual(actual.t, [-2, 3, 4]);
    assert.deepEqual(original.t, [2, 3, 4]);
    assert.equal(original.R, input);
  }
});
