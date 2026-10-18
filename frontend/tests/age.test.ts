import assert from "node:assert/strict";
import test from "node:test";
import { getAgeWeights } from "../src/age.ts";

const sum = (values: number[]) =>
  values.reduce((total, value) => total + value, 0);

test("each age anchor selects exactly its own target", () => {
  assert.deepEqual(getAgeWeights(20), [1, 0, 0]);
  assert.deepEqual(getAgeWeights(45), [0, 1, 0]);
  assert.deepEqual(getAgeWeights(70), [0, 0, 1]);
});

test("intermediate ages interpolate between adjacent anchors only", () => {
  assert.deepEqual(getAgeWeights(30), [0.6, 0.4, 0]);
  assert.deepEqual(getAgeWeights(57.5), [0, 0.5, 0.5]);
});

test("finite ages outside the supported interval clamp to the nearest anchor", () => {
  assert.deepEqual(getAgeWeights(-100), [1, 0, 0]);
  assert.deepEqual(getAgeWeights(1000), [0, 0, 1]);
});

test("weights are normalized, nonnegative and continuous across the middle anchor", () => {
  for (let age = 19; age <= 71; age += 0.25) {
    const weights = getAgeWeights(age);
    assert.ok(weights.every((weight) => weight >= 0 && weight <= 1));
    assert.ok(Math.abs(sum(weights) - 1) < 1e-12);
    assert.ok(weights.filter((weight) => weight > 0).length <= 2);
  }
  const left = getAgeWeights(45 - 1e-7);
  const right = getAgeWeights(45 + 1e-7);
  left.forEach((weight, index) =>
    assert.ok(Math.abs(weight - right[index]) < 1e-7),
  );
});

test("custom uneven age anchors use age distance instead of index distance", () => {
  assert.deepEqual(getAgeWeights(25, [10, 20, 40, 80]), [0, 0.75, 0.25, 0]);
  assert.deepEqual(getAgeWeights(50, [10, 20, 40, 80]), [0, 0, 0.75, 0.25]);
  assert.deepEqual(getAgeWeights(999, [42]), [1]);
});

test("invalid ages fail instead of propagating NaN through the renderer", () => {
  for (const age of [NaN, Infinity, -Infinity])
    assert.throws(() => getAgeWeights(age), /有限数值/);
});

test("age anchors must be nonempty, finite and strictly increasing", () => {
  for (const stops of [
    [],
    [45, 20, 70],
    [20, 20, 70],
    [20, NaN, 70],
    [20, Infinity],
    [-Infinity, 20],
  ]) {
    assert.throws(() => getAgeWeights(30, stops), /严格递增/);
  }
});

test("age calculation does not mutate a caller-owned anchor array", () => {
  const anchors = Object.freeze([20, 45, 70]);
  assert.deepEqual(getAgeWeights(30, anchors), [0.6, 0.4, 0]);
  assert.deepEqual(anchors, [20, 45, 70]);
});
