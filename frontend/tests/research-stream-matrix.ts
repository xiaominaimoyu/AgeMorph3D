/** Synthetic transport gate only. A passed gate never grants model or quality readiness. */
export type StreamCase = { id: string; kind: string; positive: boolean; budget: number };
export type Terminal = { event: "finished" | "failed"; error?: string };
export type StreamEvidence = {
  id: string;
  application: { rejected: boolean; bytes?: number; sha256?: string;
    error?: { name: string; message: string; code?: string; status?: number };
    firstChunk?: number; aborted?: boolean };
  playwright: Terminal[];
  cdp: Terminal[];
  server: { kind: string; prefixObserved: boolean; remainderReleased: boolean };
};

export function streamCases(): StreamCase[] {
  const cases: StreamCase[] = [];
  for (const kind of ["fixed", "split"])
    for (let n = 1; n <= 4; n++) cases.push({ id: `${kind}-${n}`, kind, positive: true, budget: 262144 });
  for (const kind of ["declared-over", "actual-over", "prefix-over", "wrong-media", "empty", "truncated", "timeout", "abort", "http-error"])
    cases.push({ id: kind, kind, positive: false, budget: 1024 });
  return cases;
}

export function assessStreamEvidence(rows: StreamEvidence[], expectedSha: string) {
  const reasons: string[] = [], integrity: string[] = [];
  const cases = streamCases(), seen = new Set<string>();
  let positivesPassed = 0, negativesPassed = 0;
  for (const spec of cases) {
    const matches = rows.filter(row => row.id === spec.id);
    if (matches.length !== 1) { integrity.push(`${spec.id}: expected one row`); continue; }
    const row = matches[0]; seen.add(row.id);
    if (row.playwright.length !== 1 || row.cdp.length !== 1 ||
        !["finished", "failed"].includes(row.playwright[0].event) || row.playwright[0].event !== row.cdp[0].event ||
        row.playwright[0].event === "failed" && row.playwright[0].error !== row.cdp[0].error) {
      integrity.push(`${spec.id}: missing/duplicate/inconsistent raw terminal`); continue;
    }
    if (row.server.kind !== spec.kind) { integrity.push(`${spec.id}: server binding mismatch`); continue; }
    const app = row.application;
    if (spec.positive) {
      if (!app.rejected && app.bytes === 131072 && app.sha256 === expectedSha &&
          row.playwright[0].event === "finished" && row.cdp[0].event === "finished") positivesPassed++;
      else reasons.push(`${spec.id}: payload or original completion failed`);
    } else {
      let valid = app.rejected && !!app.error;
      if (spec.kind === "timeout") valid &&= app.error?.code === "TIMEOUT" && app.error?.status === 504;
      else if (spec.kind === "abort") valid &&= app.error?.name === "AbortError" && app.aborted === true;
      else if (spec.kind === "http-error") valid &&= app.error?.code === "STAGE_EXPIRED" && app.error?.status === 404;
      else if (spec.kind === "truncated") valid &&= app.error?.name === "TypeError";
      else {
        const message = spec.kind === "wrong-media" ? "媒体类型" : spec.kind === "empty" ? "长度不匹配" :
          spec.kind === "declared-over" ? "字节预算" : "实际字节预算";
        valid &&= app.error?.name === "Error" && app.error.message.includes(message);
      }
      if (["prefix-over", "timeout", "abort"].includes(spec.kind)) {
        valid &&= app.firstChunk === 512 && row.server.prefixObserved;
        valid &&= row.server.remainderReleased === (spec.kind === "prefix-over");
      }
      if (valid) negativesPassed++; else reasons.push(`${spec.id}: intended rejection not proved`);
    }
  }
  if (rows.length !== cases.length || rows.some(row => !seen.has(row.id))) integrity.push("unexpected/missing case rows");
  return { status: integrity.length ? "diagnostic-error" : reasons.length ? "blocked" : "passed",
    positivesPassed, positiveRequests: 8, negativesPassed, negativeRequests: 9, reasons, integrity };
}
