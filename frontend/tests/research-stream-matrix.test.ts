import assert from "node:assert/strict";
import test from "node:test";
import { assessStreamEvidence, streamCases } from "./research-stream-matrix.ts";
import type { StreamEvidence } from "./research-stream-matrix.ts";

const HASH = "a".repeat(64);
function evidence(): StreamEvidence[] {
  return streamCases().map(spec => {
    const error = spec.kind === "timeout" ? { name: "ResearchApiError", message: "timeout", code: "TIMEOUT", status: 504 } :
      spec.kind === "abort" ? { name: "AbortError", message: "abort" } :
      spec.kind === "http-error" ? { name: "ResearchApiError", message: "expired", code: "STAGE_EXPIRED", status: 404 } :
      spec.kind === "truncated" ? { name: "TypeError", message: "Failed to fetch" } :
      { name: "Error", message: "媒体类型 长度不匹配 实际字节预算" };
    return { id: spec.id, application: spec.positive ? { rejected: false, bytes: 131072, sha256: HASH } :
      { rejected: true, error, firstChunk: 512, aborted: spec.kind === "abort" },
    playwright: [{ event: "finished" }], cdp: [{ event: "finished" }],
    server: { kind: spec.kind, prefixObserved: true, remainderReleased: spec.kind === "prefix-over" } };
  });
}

test("complete raw completions, correct payload and intended negative controls pass only the synthetic gate", () => {
  const result = assessStreamEvidence(evidence().reverse(), HASH);
  assert.equal(result.status, "passed"); assert.equal(result.positivesPassed, 8); assert.equal(result.negativesPassed, 9);
});
test("correct bytes never excuse original aborted requests", () => {
  const rows = evidence(); rows[0].playwright = rows[0].cdp = [{ event: "failed", error: "net::ERR_ABORTED" }];
  const result = assessStreamEvidence(rows, HASH);
  assert.equal(result.status, "blocked"); assert.equal(result.positivesPassed, 7); assert.equal(result.integrity.length, 0);
});
test("failure in either body bytes or digest blocks a positive", () => {
  for (const key of ["bytes", "sha256"] as const) {
    const rows = evidence(); Object.assign(rows[0].application, { [key]: key === "bytes" ? 1 : "b".repeat(64) });
    assert.equal(assessStreamEvidence(rows, HASH).status, "blocked");
  }
});
test("missing, duplicate, inconsistent and unexpected raw evidence are diagnostic errors", () => {
  const mutations = [
    (rows: StreamEvidence[]) => { rows[0].cdp = []; },
    (rows: StreamEvidence[]) => { rows[0].playwright.push({ event: "finished" }); },
    (rows: StreamEvidence[]) => { rows[0].cdp = [{ event: "failed" }]; },
    (rows: StreamEvidence[]) => { rows[0].cdp = [{ event: "failed", error: "a" }]; rows[0].playwright = [{ event: "failed", error: "b" }]; },
    (rows: StreamEvidence[]) => { rows.push(structuredClone(rows[0])); },
    (rows: StreamEvidence[]) => { rows.pop(); },
    (rows: StreamEvidence[]) => { rows[0].id = "unexpected"; },
    (rows: StreamEvidence[]) => { rows[0].server.kind = "split"; },
  ];
  for (const mutate of mutations) { const rows = evidence(); mutate(rows); assert.equal(assessStreamEvidence(rows, HASH).status, "diagnostic-error"); }
});
test("timeout is not accepted as truncation or a budget rejection", () => {
  for (const kind of ["truncated", "actual-over", "declared-over", "prefix-over"]) {
    const rows = evidence(); rows.find(row => row.id === kind)!.application.error = { name: "ResearchApiError", message: "timeout", code: "TIMEOUT", status: 504 };
    assert.equal(assessStreamEvidence(rows, HASH).status, "blocked");
  }
});
test("prefix controls require observation before remainder and explicit caller abort", () => {
  for (const kind of ["prefix-over", "timeout", "abort"]) {
    const rows = evidence(); rows.find(row => row.id === kind)!.server.prefixObserved = false;
    assert.equal(assessStreamEvidence(rows, HASH).status, "blocked");
  }
  const rows = evidence(); rows.find(row => row.id === "abort")!.application.aborted = false;
  assert.equal(assessStreamEvidence(rows, HASH).status, "blocked");
});
test("wrong timeout or HTTP status and an unrequested remainder cannot pass", () => {
  for (const kind of ["timeout", "http-error"]) {
    const rows = evidence(); rows.find(row => row.id === kind)!.application.error!.status = 500;
    assert.equal(assessStreamEvidence(rows, HASH).status, "blocked");
  }
  const rows = evidence(); rows.find(row => row.id === "timeout")!.server.remainderReleased = true;
  assert.equal(assessStreamEvidence(rows, HASH).status, "blocked");
});
