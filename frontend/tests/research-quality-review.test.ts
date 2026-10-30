/** Synthetic draft interactions; no real reviewer or quality sign-off. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { QualityReviewDraft, validateQualityReview, REVIEW_CRITERIA, REVIEW_VARIANTS, MAX_REVIEW_BYTES, type QualityReviewWorksheet } from "../src/research-quality-review.ts";

function baseline(): QualityReviewWorksheet {
  return {
    schema_version: 1, protocol_id: "agemorph3d-texture-quality-review-v1", scope: "synthetic",
    research_only: true, human_review_completed: false, age_quality_accepted: false,
    identity_quality_accepted: false, visual_seam_quality_accepted: false,
    independent_evaluation: false, service_ready: false, production_enabled: false, g3_complete: false,
    reviewer: { kind: null, name: null, recorded_at: null },
    plan: { path: "output/research/synthetic/plan.json", bytes: 20, sha256: "a".repeat(64) },
    cohort_targets: [{ id: "entire-cohort-retained" }],
    denominators: { targets: 37, focus_pairs: 32, frames_per_variant: 376, pairs_per_variant: 296 },
    records: Array.from({ length: 32 }, (_, i) => ({
      sample_id: `sample-${Math.floor(i / 8)}`, config_id: `config-${i % 8}`,
      target_age_condition: [20, 45, 63, 70][Math.floor(i / 8)],
      source_age_api: { value: null, method: "unknown", calibration_id: null },
      evidence: { conservative: { frame_id: `frame-${i}`, saved_identity_status: "NO_FACE" }, observed: { frame_id: `frame-${i}`, saved_identity_status: "NO_FACE" } },
      assessments: Object.fromEntries(REVIEW_VARIANTS.map(v => [v, Object.fromEntries(REVIEW_CRITERIA.map(c => [c, { rating: "pending", note: "" }]))])) as QualityReviewWorksheet["records"][number]["assessments"],
    })),
  };
}
const stamp = "2026-10-30T10:00:00+08:00";
function answered(): QualityReviewDraft { const d = new QualityReviewDraft(baseline()); d.start("ai", "synthetic-ai", stamp); d.set(0, "observed", "eyes_glasses", "issue", "Synthetic visible gap"); return d; }

test("blank package stays pending with no default human identity", () => {
  const b = baseline(), d = new QualityReviewDraft(b);
  assert.deepEqual(d.summary(), { answered: 0, missingNotes: 0, total: 320 });
  assert.deepEqual(JSON.parse(d.exportText()), b);
  assert.throws(() => d.set(0, "observed", "eyes_glasses", "issue", "reason"), /观察者/);
});
test("partial draft preserves all fixed evidence, null source age and failure denominators", () => {
  const b = baseline(), d = new QualityReviewDraft(b); d.start("ai", "synthetic-ai", stamp);
  d.set(31, "observed", "seams", "not_assessable", "Unobservable region");
  const v = JSON.parse(d.exportText());
  assert.equal(v.records.length, 32); assert.deepEqual(v.denominators, b.denominators);
  assert.deepEqual(v.cohort_targets, b.cohort_targets); assert.deepEqual(v.records[0].source_age_api, b.records[0].source_age_api);
  assert.equal(v.records[31].evidence.observed.saved_identity_status, "NO_FACE");
  assert.equal(v.records[0].assessments.observed.seams.rating, "pending");
  for (const k of ["human_review_completed", "production_enabled", "g3_complete"]) assert.equal(v[k], false);
});
test("editing is incomplete until every selected rating has an explanation", () => {
  const d = new QualityReviewDraft(baseline()); d.start("ai", "test", stamp);
  d.set(2, "conservative", "seams", "issue", " ");
  assert.deepEqual(d.summary(), { answered: 1, missingNotes: 1, total: 320 });
  assert.throws(() => d.exportText(), /判断依据/);
  d.set(2, "conservative", "seams", "issue", "Visible edge"); assert.doesNotThrow(() => d.exportText());
});
test("loaded AI draft cannot be relabelled human without clearing its observations", () => {
  const d = new QualityReviewDraft(baseline()); d.importText(answered().exportText());
  assert.equal(d.preview().reviewer.kind, "ai");
  assert.throws(() => d.start("human", "another-user", stamp), /清空/);
  d.reset(); assert.deepEqual(d.summary(), { answered: 0, missingNotes: 0, total: 320 });
  d.start("human", "synthetic-human-declaration", stamp);
  assert.equal(d.preview().reviewer.kind, "human"); assert.equal(d.preview().human_review_completed, false);
});
test("preview, caller baseline and failed imports never mutate the live draft", () => {
  const b = baseline(), d = new QualityReviewDraft(b); b.records[0].target_age_condition = 99;
  d.start("ai", "test", stamp); const preview = d.preview(); preview.records[0].target_age_condition = 99;
  assert.equal(d.preview().records[0].target_age_condition, 20);
  const before = d.exportText(), tampered = JSON.parse(before); tampered.records.pop();
  assert.throws(() => d.importText(JSON.stringify(tampered))); assert.equal(d.exportText(), before);
});
for (const [name, edit] of [
  ["plan pin", (v: any) => { v.plan.sha256 = "b".repeat(64); }],
  ["cohort", (v: any) => { v.cohort_targets = []; }],
  ["denominator", (v: any) => { v.denominators.frames_per_variant = 32; }],
  ["source age", (v: any) => { v.records[0].source_age_api.value = 63; }],
  ["saved failure", (v: any) => { v.records[0].evidence.observed.saved_identity_status = "ok"; }],
  ["row order", (v: any) => { v.records.reverse(); }],
  ["extra row", (v: any) => { v.records.push(v.records[0]); }],
  ["missing criterion", (v: any) => { delete v.records[0].assessments.observed.seams; }],
  ["extra assessment field", (v: any) => { v.records[0].assessments.observed.seams.approved = true; }],
  ["human approval", (v: any) => { v.human_review_completed = true; }],
  ["production", (v: any) => { v.production_enabled = true; }],
  ["quality", (v: any) => { v.age_quality_accepted = true; }],
  ["reviewer type", (v: any) => { v.reviewer.kind = "verified-human"; }],
  ["missing reviewer", (v: any) => { v.reviewer = { kind: null, name: null, recorded_at: null }; }],
  ["rating", (v: any) => { v.records[0].assessments.observed.eyes_glasses.rating = "passed"; }],
  ["long note", (v: any) => { v.records[0].assessments.observed.eyes_glasses.note = "x".repeat(2001); }],
] as const) test(`imports reject ${name} while preserving the current draft`, () => {
  const d = answered(), before = d.exportText(), v = JSON.parse(before); edit(v);
  assert.throws(() => d.importText(JSON.stringify(v))); assert.equal(d.exportText(), before);
});
for (const time of ["2026-10-30T10:00:00", "2026-02-30T10:00:00Z", "0000-01-01T00:00:00Z", "2026-13-01T00:00:00Z"]) test(`reject invalid observer time ${time}`, () => {
  const d = new QualityReviewDraft(baseline()); assert.throws(() => d.start("ai", "test", time));
});
test("duplicate and escaped duplicate keys, nonfinite values and excessive depth are rejected", () => {
  const d = answered(), text = d.exportText();
  assert.throws(() => d.importText(text.replace('"research_only": true,', '"research_only": false,"research_only":true,')), /重复/);
  assert.throws(() => d.importText(text.replace('"research_only": true,', '"research_only": false,"research_\\u006fnly":true,')), /重复/);
  assert.throws(() => d.importText('{"x":1e999}'), /非有限/);
  assert.throws(() => d.importText('['.repeat(33) + '0' + ']'.repeat(33)), /嵌套/);
});
test("UTF8 size is bounded independently from JavaScript string length", () => {
  const d = answered(); assert.throws(() => d.importText('"' + '中'.repeat(Math.ceil(MAX_REVIEW_BYTES / 3)) + '"'), /512/);
});
test("complete self-reported observation set stays closed and round trips", () => {
  const d = new QualityReviewDraft(baseline()); d.start("ai", "synthetic-ai", stamp);
  for (let i = 0; i < 32; i++) for (const v of REVIEW_VARIANTS) for (const c of REVIEW_CRITERIA) d.set(i, v, c, "not_assessable", "Synthetic unobservable criterion");
  assert.deepEqual(d.summary(), { answered: 320, missingNotes: 0, total: 320 });
  const copy = new QualityReviewDraft(baseline()); copy.importText(d.exportText());
  assert.equal(copy.exportText(), d.exportText()); assert.equal(copy.preview().g3_complete, false);
});
test("baseline cannot preload completed AI observations as a blank human worksheet", () => {
  assert.throws(() => new QualityReviewDraft(answered().preview()), /待填表/);
  assert.throws(() => validateQualityReview({ ...baseline(), g3_complete: true }, baseline()));
});
