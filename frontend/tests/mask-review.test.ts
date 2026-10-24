import assert from "node:assert/strict";
import test from "node:test";
import {
  bilinearContributors,
  buildLookup,
  canvasCoordinates,
  createReviewNotes,
  decodeCase,
  decodeRLE,
  decodeVectorField,
  nearestVisiblePoint,
  selectTargetPoint,
  selectUVPoint,
  uvCoordinates,
} from "../research/mask-review.mjs";

const qualityFlags = {
  research_only: true,
  age_quality_accepted: false,
  identity_quality_accepted: false,
  visual_seam_quality_accepted: false,
  independent_evaluation: false,
  causal_cause_accepted: false,
  masks_modified: false,
  unknown_regions_filled: false,
  real_model_inference: false,
  service_ready: false,
  production_enabled: false,
  g3_complete: false,
  historical_process_identity_proven: false,
  human_review_completed: false,
};

function littleEndian(values: number[], type: "i32" | "f64" | "u8"): string {
  const bytes = Buffer.alloc(values.length * (type === "u8" ? 1 : type === "i32" ? 4 : 8));
  values.forEach((value, index) => {
    if (type === "i32") bytes.writeInt32LE(value, index * 4);
    else if (type === "f64") bytes.writeDoubleLE(value, index * 8);
    else bytes[index] = value;
  });
  return bytes.toString("base64");
}

function caseData(): any {
  const landmark = Array.from({ length: 68 }, (_, index) => [index % 4, Math.floor(index / 4) % 4]);
  const pin = { path: "output/research/synthetic.json", bytes: 1, sha256: "a".repeat(64) };
  return {
    schemaVersion: 1,
    protocolId: "agemorph3d-mask-review-workbench-v1",
    sampleId: "fgnet-004a63--sam-020",
    sourceId: "fgnet-004a63",
    targetAgeCondition: 20,
    sourceAgeApi: { value: null, method: "unknown", calibration_id: null },
    sourceAgeLabel: 63,
    width: 4,
    height: 4,
    landmarksXY: landmark,
    roundedLandmarksXY: landmark.map((point) => [...point]),
    regionBoxes: {
      eye_36_41: [0, 0, 3, 3], eye_42_47: [0, 0, 3, 3],
      nose_27_35: [0, 0, 3, 3], mouth_48_67: [0, 0, 3, 3],
    },
    classificationRLE: [6, 1, 5, 2, 2, 1, 0, 65532],
    reasonRLE: [0, 1, 1, 1, 2, 1, 4, 1, 0, 1, 1, 1, 2, 1, 4, 1, 3, 1, 0, 2, 4, 1, 0, 4],
    images: Object.fromEntries(["target", "allowed", "occluded", "atlas"].map((name) =>
      [name, "data:image/png;base64,iVBORw0KGgo="])),
    vectors: {
      count: 4,
      rows_columns_i32: littleEndian([0, 0, 0, 1, 0, 2, 0, 3], "i32"),
      face_owner_i32: littleEndian([12, 13, 14, 15], "i32"),
      barycentric_f64: littleEndian([0.25, 0.25, 0.5, 0, 1, 0, 0.125, 0.625, 0.25, 1, 0, 0], "f64"),
      target_xyz_f64: littleEndian([0, 0, 10, 1.5, 0, 20, 2.5, 0, 30, -10, -10, 99], "f64"),
      source_canonical_xyz_f64: littleEndian([2 ** -45, -0, 0.0123456789012345, 1, 2, 3, 4, 5, 6, 7, 8, 9], "f64"),
      region_bits_u8: littleEndian([15, 15, 15, 0], "u8"),
      rejection_partition_u8: littleEndian([0, 2, 3, 0], "u8"),
    },
    provenance: { maskReport: pin, maskAudit: pin, uvReport: pin, protocol: pin, input: pin },
    flags: { ...qualityFlags },
  };
}

test("RLE reconstructs exact row-major labels without changing its input", () => {
  const input = [0, 2, 4, 3, 2, 1];
  assert.deepEqual([...decodeRLE(input, 6, 4)], [0, 0, 4, 4, 4, 2]);
  assert.deepEqual(input, [0, 2, 4, 3, 2, 1]);
});

for (const malformed of [[0], [0, 0], [0, -1], [5, 6], [0, 1.5], [0, 7], [NaN, 6], [true, 6]]) {
  test(`RLE rejects invalid runs or labels ${JSON.stringify(malformed)}`, () => {
    assert.throws(() => decodeRLE(malformed, 6, 4));
  });
}

test("RLE rejects oversized expected allocation before constructing an output buffer", () => {
  assert.throws(() => decodeRLE([0, 16000001], 16000001, 4));
  assert.throws(() => decodeRLE([0, 6], -1, 4));
});

test("vector decoding keeps exact LE float64 precision and negative zero", () => {
  const values = [2 ** -45, -0, 0.0123456789012345, -123456789.25, 2 ** 40, 1];
  const decoded = decodeVectorField(littleEndian(values, "f64"), "f64", 2, 3);
  assert.ok(decoded instanceof Float64Array);
  assert.deepEqual([...decoded], values);
  assert.ok(Object.is(decoded[1], -0));
  assert.deepEqual([...decodeVectorField(littleEndian([-2147483648, 2147483647], "i32"), "i32", 2)],
    [-2147483648, 2147483647]);
  assert.deepEqual([...decodeVectorField(littleEndian([0, 255], "u8"), "u8", 2)], [0, 255]);
});

test("maximum-size synthetic f64 field validates without regex stack overflow", () => {
  const bytes = Buffer.alloc(65536 * 3 * 8);
  bytes.writeDoubleLE(0.0123456789012345, 0);
  bytes.writeDoubleLE(-(2 ** -45), bytes.length - 8);
  const decoded = decodeVectorField(bytes.toString("base64"), "f64", 65536, 3);
  assert.equal(decoded.length, 196608);
  assert.equal(decoded[0], 0.0123456789012345);
  assert.equal(decoded[decoded.length - 1], -(2 ** -45));
});

for (const [name, base64, type, count, components] of [
  ["invalid base64", "%%%", "f64", 1, 1],
  ["truncated", littleEndian([1], "i32"), "f64", 1, 1],
  ["trailing", littleEndian([1, 2], "f64"), "f64", 1, 1],
  ["nonfinite", littleEndian([Infinity], "f64"), "f64", 1, 1],
  ["negative rows", "", "u8", -1, 1],
  ["excess rows", "", "u8", 65537, 1],
  ["unknown type", "", "u16", 1, 1],
  ["noncanonical padding bits", "AB==", "u8", 1, 1],
] as const) {
  test(`vector decoding refuses ${name}`, () => {
    assert.throws(() => decodeVectorField(base64, type, count, components));
  });
}

test("case schema retains unknown API age separately from the filename research label", () => {
  const data = caseData();
  const before = JSON.stringify(data);
  const model = decodeCase(data);
  assert.equal(model.classification.length, 65536);
  assert.equal(model.reasons.length, 16);
  assert.equal(model.vectors.count, 4);
  assert.equal(model.data.sourceAgeApi.value, null);
  assert.equal(model.data.sourceAgeLabel, 63);
  assert.equal(JSON.stringify(data), before);
});

for (const [name, mutate] of [
  ["wrong protocol", (d: any) => { d.protocolId = "other"; }],
  ["oversized image", (d: any) => { d.width = 16000001; }],
  ["default source age", (d: any) => { d.sourceAgeApi.value = 30; }],
  ["missing API age", (d: any) => { delete d.sourceAgeApi; }],
  ["quality promotion", (d: any) => { d.flags.age_quality_accepted = true; }],
  ["missing flags", (d: any) => { delete d.flags; }],
  ["missing closed gate", (d: any) => { delete d.flags.g3_complete; }],
  ["production promotion", (d: any) => { d.flags.production_enabled = true; }],
  ["nonfinite landmark", (d: any) => { d.landmarksXY[0][0] = NaN; }],
  ["unknown reason", (d: any) => { d.reasonRLE = [5, 16]; }],
  ["class count mismatch", (d: any) => { d.classificationRLE = [0, 65536]; }],
  ["wrong partition", (d: any) => { d.vectors.rejection_partition_u8 = littleEndian([0, 1, 3, 0], "u8"); }],
] as const) {
  test(`case schema rejects ${name}`, () => {
    const data = caseData();
    mutate(data);
    assert.throws(() => decodeCase(data));
  });
}

test("UV lookup maps only exact saved integer texels and rejects duplicate ownership", () => {
  const model = decodeCase(caseData());
  const lookup = buildLookup(model.classification, model.vectors);
  assert.deepEqual([...lookup.slice(0, 5)], [0, 1, 2, 3, -1]);
  assert.equal(lookup[65535], -1);
  const vectors = { ...model.vectors, rowsColumns: new Int32Array([0, 0, 0, 0, 0, 2, 0, 3]) };
  assert.throws(() => buildLookup(model.classification, vectors));
});

test("unknown and ambiguous UV choices clear owner, correspondence and contributor state", () => {
  const model = decodeCase(caseData());
  const known = selectUVPoint(model, 0, 0);
  assert.equal(known.faceOwner, 12);
  assert.equal(known.targetXYZ[2], 10);
  for (const code of [0, 1]) {
    model.classification[65535] = code;
    const unknown = selectUVPoint(model, 255, 255);
    assert.equal(unknown.classificationCode, code);
    for (const field of ["vectorIndex", "faceOwner", "barycentric", "targetXYZ", "sourceCanonicalXYZ", "regionBits", "rejectionPartition"])
      assert.equal(unknown[field], null, field);
    assert.equal(unknown.contributors, null);
    assert.equal(unknown.contributorReasonBits, null);
  }
  assert.equal(known.faceOwner, 12);
});

test("selection preserves saved owner/barycentric/f64 source coordinates without reprojecting", () => {
  const selection = selectUVPoint(decodeCase(caseData()), 0, 0);
  assert.deepEqual(selection.barycentric, [0.25, 0.25, 0.5]);
  assert.equal(selection.sourceCanonicalXYZ[0], 2 ** -45);
  assert.ok(Object.is(selection.sourceCanonicalXYZ[1], -0));
  assert.equal(selection.sourceCanonicalXYZ[2], 0.0123456789012345);
  assert.equal(selection.regions.length, 4);
});

test("original class5 bitsets agree with frozen other-only and mixed partitions", () => {
  const model = decodeCase(caseData());
  assert.equal(selectUVPoint(model, 0, 1).contributorReasonBits, 3);
  assert.equal(selectUVPoint(model, 0, 1).rejectionPartition, 2);
  assert.equal(selectUVPoint(model, 0, 2).contributorReasonBits, 10);
  assert.equal(selectUVPoint(model, 0, 2).rejectionPartition, 3);
  const back = selectUVPoint(model, 0, 3);
  assert.equal(back.classificationCode, 2);
  assert.equal(back.contributors, null);
  assert.equal(back.contributorReasonBits, null);
  for (const code of [3, 4]) {
    model.classification[3] = code;
    const hidden = selectUVPoint(model, 0, 3);
    assert.equal(hidden.classificationCode, code);
    assert.equal(hidden.contributors, null);
    assert.equal(hidden.contributorReasonBits, null);
  }
});

test("positive-weight bilinear contributors exclude zero neighbors and clamp the image edge", () => {
  const reasons = new Uint8Array([0, 1, 2, 4, 3, 0, 0, 4, 0, 0, 0, 0, 0, 0, 0, 3]);
  const integer = bilinearContributors(reasons, 4, 4, 0, 0);
  assert.deepEqual(integer.map(({ x, y, weight, reasonCode }: any) => [x, y, weight, reasonCode]), [[0, 0, 1, 0]]);
  const edge = bilinearContributors(reasons, 4, 4, 3, 3);
  assert.deepEqual(edge.map(({ x, y, weight, reasonCode }: any) => [x, y, weight, reasonCode]), [[3, 3, 1, 3]]);
  const fraction = bilinearContributors(reasons, 4, 4, 0.25, 0.5);
  assert.deepEqual(fraction.map(({ weight }: any) => weight), [0.375, 0.125, 0.375, 0.125]);
  assert.equal(fraction.reduce((sum: number, point: any) => sum + point.weight, 0), 1);
  assert.equal(bilinearContributors(reasons, 4, 4, 2 ** -40, 0).length, 2);
});

for (const [x, y] of [[-0.001, 0], [0, -1], [3.001, 0], [0, 4], [NaN, 0], [Infinity, 0]]) {
  test(`bilinear query rejects outside/nonfinite coordinates (${x},${y})`, () => {
    assert.throws(() => bilinearContributors(new Uint8Array(16), 4, 4, x, y));
  });
}

test("canvas scaling preserves continuous image coordinates and rejects clicks outside the frame", () => {
  const rect = { left: 10, top: 20, width: 200, height: 100 };
  assert.deepEqual(canvasCoordinates(60, 45, rect, 1000, 500), { x: 250, y: 125 });
  assert.equal(canvasCoordinates(210, 45, rect, 1000, 500), null);
  assert.equal(canvasCoordinates(9.9, 45, rect, 1000, 500), null);
  assert.equal(canvasCoordinates(60, 120, rect, 1000, 500), null);
  assert.deepEqual(uvCoordinates(60, 45, rect), { row: 64, column: 64 });
});

test("nearest target center includes only class5/6 within the inclusive three-pixel radius", () => {
  const model = decodeCase(caseData());
  const hit = nearestVisiblePoint(model, 1.6, 0);
  assert.equal(hit.index, 1);
  assert.ok(Math.abs(hit.distance - 0.1) < 1e-14);
  assert.equal(nearestVisiblePoint(model, -10, -10), null);
  assert.equal(nearestVisiblePoint(model, 0, 3).index, 0);
  assert.equal(nearestVisiblePoint(model, 0, 3.00001), null);
  assert.equal(selectTargetPoint(model, -10, -10), null);
  const selected = selectTargetPoint(model, 1.6, 0);
  assert.equal(selected.vectorIndex, 1);
  assert.equal(selected.approximate, true);
});

test("equal-distance target picks larger projected Z and then lower saved vector row", () => {
  const model = decodeCase(caseData());
  model.vectors.targetXYZ.set([1, 1, 4, 3, 1, 8, 3, 1, 8, -10, -10, 99]);
  assert.equal(nearestVisiblePoint(model, 2, 1).index, 1);
  model.vectors.targetXYZ[2] = 8;
  assert.equal(nearestVisiblePoint(model, 2, 1).index, 0);
});

test("note export snapshots untrusted observations with unknown API age and every quality gate closed", () => {
  const data = caseData();
  const selection = selectUVPoint(decodeCase(data), 0, 0);
  const observation = { text: '</script><img src=x> observed only', selection };
  const notes = createReviewNotes(data, "synthetic reviewer", [observation], "2026-10-24T00:00:00Z");
  assert.equal(notes.protocol_id, "agemorph3d-mask-review-notes-v1");
  assert.equal(notes.reviewer, "synthetic reviewer");
  assert.equal(notes.sample_id, data.sampleId);
  assert.deepEqual(notes.source_age_api, { value: null, method: "unknown", calibration_id: null });
  assert.deepEqual(notes.provenance, data.provenance);
  assert.equal(notes.review_complete, false);
  for (const [name, value] of Object.entries(qualityFlags)) assert.equal(notes[name], value, name);
  assert.equal(notes.observations[0].text, observation.text);
  observation.text = "changed later";
  selection.targetXYZ[0] = 99;
  assert.equal(notes.observations[0].text, '</script><img src=x> observed only');
  assert.equal(notes.observations[0].selection.targetXYZ[0], 0);
  assert.equal(data.sourceAgeApi.value, null);
  assert.equal(data.flags.g3_complete, false);
});

test("unknown review observation keeps correspondence null without inventing a nearest texel", () => {
  const data = caseData();
  const selection = selectUVPoint(decodeCase(data), 255, 255);
  const notes = createReviewNotes(data, "reviewer", [{ text: "unknown surface", selection }]);
  assert.equal(notes.observations[0].selection.faceOwner, null);
  assert.equal(notes.observations[0].selection.targetXYZ, null);
  assert.equal(notes.observations[0].selection.sourceCanonicalXYZ, null);
  assert.equal(notes.observations[0].selection.vectorIndex, null);
  assert.equal(notes.review_complete, false);
});

for (const reviewer of ["", "   ", "\t\n"]) {
  test(`review notes require an explicit nonblank reviewer ${JSON.stringify(reviewer)}`, () => {
    assert.throws(() => createReviewNotes(caseData(), reviewer, []));
  });
}
