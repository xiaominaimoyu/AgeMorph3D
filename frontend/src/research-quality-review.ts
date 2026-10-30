/** Explicit offline observation drafts. No requests, storage or quality approval. */
export const REVIEW_CRITERIA = ["eyes_glasses", "side_coverage", "seams", "identity_appearance", "age_condition_appearance"] as const;
export const REVIEW_VARIANTS = ["conservative", "observed"] as const;
export const REVIEW_RATINGS = ["pending", "issue", "no_obvious_issue", "not_assessable"] as const;
export const MAX_REVIEW_BYTES = 512 * 1024;
type Criterion = typeof REVIEW_CRITERIA[number];
type Variant = typeof REVIEW_VARIANTS[number];
type Rating = typeof REVIEW_RATINGS[number];
type JsonObject = Record<string, unknown>;
export interface ReviewObserver { kind: "human" | "ai" | null; name: string | null; recorded_at: string | null }
export interface QualityReviewRow extends JsonObject {
  sample_id: string; config_id: string; target_age_condition: number;
  assessments: Record<Variant, Record<Criterion, { rating: Rating; note: string }>>;
}
export interface QualityReviewWorksheet extends JsonObject { reviewer: ReviewObserver; records: QualityReviewRow[] }
export interface QualityReviewPackage { worksheet: QualityReviewWorksheet; images: Record<string, string>; originals: Record<string, string> }

const labels: Record<Criterion, string> = { eyes_glasses: "眼区与眼镜", side_coverage: "侧面覆盖", seams: "接缝与缺口", identity_appearance: "身份观感", age_condition_appearance: "年龄条件观感" };
const variantLabels: Record<Variant, string> = { conservative: "保守支持", observed: "额头候选" };
const ratingLabels: Record<Rating, string> = { pending: "待填写", issue: "可见问题", no_obvious_issue: "未见明显问题", not_assessable: "无法判断" };
const encoder = new TextEncoder();
function fail(message: string): never { throw new Error(message); }
function clone<T>(value: T): T { return JSON.parse(JSON.stringify(value)) as T; }
function object(value: unknown): JsonObject {
  if (!value || typeof value !== "object" || Array.isArray(value)) fail("观察草稿字段无效。");
  return value as JsonObject;
}
function keys(value: unknown, expected: readonly string[]): JsonObject {
  const result = object(value);
  if (Object.keys(result).sort().join("|") !== [...expected].sort().join("|")) fail("观察草稿字段缺失或多出。");
  return result;
}
function canonical(value: unknown): string {
  if (typeof value === "number" && !Number.isFinite(value)) fail("观察草稿含非有限数值。");
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object") return `{${Object.keys(value).sort().map(k => `${JSON.stringify(k)}:${canonical((value as JsonObject)[k])}`).join(",")}}`;
  return JSON.stringify(value);
}
function parse(text: string): unknown {
  if (typeof text !== "string" || !text.length || text.length > MAX_REVIEW_BYTES || encoder.encode(text).length > MAX_REVIEW_BYTES) fail("观察草稿必须非空且不超过512 KiB。");
  let value: unknown;
  try { value = JSON.parse(text); } catch { fail("观察草稿不是有效JSON。"); }
  const stack: (Set<string> | null)[] = [];
  for (const match of text.matchAll(/"(?:\\.|[^"\\])*"|[{}\[\]]/g)) {
    const token = match[0];
    if (token === "{" || token === "[") {
      if (stack.length >= 32) fail("观察草稿嵌套过深。");
      stack.push(token === "{" ? new Set() : null);
    } else if (token === "}" || token === "]") stack.pop();
    else {
      let at = match.index! + token.length;
      while (/[ \t\r\n]/.test(text[at] ?? "") && at < text.length) at++;
      if (text[at] !== ":") continue;
      const names = stack.at(-1), key = JSON.parse(token) as string;
      if (!names || names.has(key)) fail("观察草稿含重复字段。");
      names.add(key);
    }
  }
  canonical(value);
  return value;
}
function observer(value: unknown): ReviewObserver {
  const item = keys(value, ["kind", "name", "recorded_at"]);
  if (Object.values(item).every(v => v === null)) return item as unknown as ReviewObserver;
  if (item.kind !== "human" && item.kind !== "ai" || typeof item.name !== "string" || !item.name.trim() || item.name.length > 100 || /[\x00-\x1f\x7f]/.test(item.name)) fail("请明确观察者类型和标识。");
  const stamp = typeof item.recorded_at === "string" ? item.recorded_at : "";
  const parts = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.exec(stamp);
  if (!parts || !Number.isFinite(Date.parse(stamp))) fail("记录时间必须是带时区的有效ISO时间。");
  const [, y, m, d, h, minute, second] = parts.map(Number);
  if (y < 1 || m < 1 || m > 12 || d < 1 || d > new Date(Date.UTC(y, m, 0)).getUTCDate() || h > 23 || minute > 59 || second > 59) fail("记录时间无效。");
  return { kind: item.kind, name: item.name, recorded_at: stamp };
}
function without(value: JsonObject, omit: string[]): JsonObject { return Object.fromEntries(Object.entries(value).filter(([k]) => !omit.includes(k))); }
function closed(value: JsonObject): void {
  if (value.research_only !== true || ["human_review_completed", "service_ready", "production_enabled", "g3_complete"].some(k => value[k] !== false)) fail("观察草稿不能授予人工或质量资格。");
  if (Object.entries(value).some(([k, v]) => (k.endsWith("_accepted") || k === "independent_evaluation" || k === "years_calibrated") && v !== false)) fail("观察草稿不能授予质量资格。");
}
export function validateQualityReview(value: unknown, baseline: QualityReviewWorksheet): QualityReviewWorksheet {
  const doc = keys(value, Object.keys(baseline));
  closed(doc);
  if (canonical(without(doc, ["reviewer", "records"])) !== canonical(without(baseline, ["reviewer", "records"]))) fail("草稿不是当前这批固定证据。");
  if (!Array.isArray(doc.records) || doc.records.length !== 32 || baseline.records.length !== 32) fail("必须保留完整32组对照。");
  const by = observer(doc.reviewer);
  let needsObserver = false;
  doc.records.forEach((item, index) => {
    const expected = baseline.records[index], row = keys(item, Object.keys(expected));
    if (canonical(without(row, ["assessments"])) !== canonical(without(expected, ["assessments"]))) fail("对照顺序、图像或来源绑定发生变化。");
    const variants = keys(row.assessments, REVIEW_VARIANTS);
    for (const variant of REVIEW_VARIANTS) {
      const criteria = keys(variants[variant], REVIEW_CRITERIA);
      for (const criterion of REVIEW_CRITERIA) {
        const a = keys(criteria[criterion], ["rating", "note"]);
        if (!REVIEW_RATINGS.includes(a.rating as Rating) || typeof a.note !== "string" || a.note.length > 2000) fail("观察选项或说明无效。");
        if (a.rating !== "pending" && !a.note.trim()) fail(`请为${labels[criterion]}填写判断依据。`);
        needsObserver ||= a.rating !== "pending" || !!a.note;
      }
    }
  });
  if (needsObserver && by.kind === null) fail("已填写的观察必须注明观察者。");
  return clone(doc) as unknown as QualityReviewWorksheet;
}

export class QualityReviewDraft {
  private readonly baseline: QualityReviewWorksheet;
  private data: QualityReviewWorksheet;
  constructor(baseline: QualityReviewWorksheet) {
    if (baseline.protocol_id !== "agemorph3d-texture-quality-review-v1") fail("观察协议不匹配。");
    this.baseline = validateQualityReview(baseline, baseline);
    if (this.baseline.reviewer.kind !== null || this.baseline.records.some(r => REVIEW_VARIANTS.some(v => REVIEW_CRITERIA.some(c => r.assessments[v][c].rating !== "pending" || !!r.assessments[v][c].note)))) fail("编辑入口必须从原始待填表开始。");
    this.data = clone(this.baseline);
  }
  preview(): QualityReviewWorksheet { return clone(this.data); }
  start(kind: "human" | "ai", name: string, stamp = new Date().toISOString()): void {
    if (this.data.reviewer.kind !== null) fail("请先清空观察，才能更换观察者。");
    this.data.reviewer = observer({ kind, name, recorded_at: stamp });
  }
  set(index: number, variant: Variant, criterion: Criterion, rating: Rating, note: string): void {
    if (this.data.reviewer.kind === null) fail("请先选择观察者并开始记录。");
    if (!Number.isInteger(index) || index < 0 || index >= 32 || !REVIEW_VARIANTS.includes(variant) || !REVIEW_CRITERIA.includes(criterion) || !REVIEW_RATINGS.includes(rating) || typeof note !== "string" || note.length > 2000) fail("观察项无效。");
    this.data.records[index].assessments[variant][criterion] = { rating, note };
  }
  importText(text: string): void { this.data = validateQualityReview(parse(text), this.baseline); }
  reset(): void { this.data = clone(this.baseline); }
  summary(): { answered: number; missingNotes: number; total: number } {
    let answered = 0, missingNotes = 0;
    for (const row of this.data.records) for (const v of REVIEW_VARIANTS) for (const c of REVIEW_CRITERIA) {
      const a = row.assessments[v][c];
      if (a.rating !== "pending") { answered++; if (!a.note.trim()) missingNotes++; }
    }
    return { answered, missingNotes, total: 320 };
  }
  exportText(): string {
    const text = JSON.stringify(validateQualityReview(this.data, this.baseline), null, 2) + "\n";
    if (encoder.encode(text).length > MAX_REVIEW_BYTES) fail("草稿超过512 KiB，请精简观察说明。");
    return text;
  }
}

function element<T extends HTMLElement>(id: string): T {
  const value = document.getElementById(id);
  if (!value) fail("离线页面缺少控件。");
  return value as T;
}
function node(tag: string, text?: string): HTMLElement { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; return n; }
export function mountQualityReview(pkg: QualityReviewPackage): void {
  const draft = new QualityReviewDraft(pkg.worksheet);
  const host = element("quality-review");
  host.innerHTML = `<header><p class="eyebrow">AgeMorph3D · 保存画面观察</p><h1>纹理质量观察</h1><p>逐组对照原始画面、保守支持和额头候选，记录可见问题。草稿只在本页内编辑，须自行导出保存。</p></header>
<section class="observer"><label>观察者类型（自述）<select id="observer-kind"><option value="">请选择</option><option value="human">人类观察者</option><option value="ai">AI观察者</option></select></label><label>观察者标识<input id="observer-name" maxlength="100" autocomplete="off"></label><button id="begin">开始记录</button><button id="reset" class="secondary">清空观察重新开始</button></section>
<p id="observer-note" class="muted">每位观察者单独保存。载入已填草稿后沿用其观察者身份；清空全部观察后才可更换。</p>
<nav><button id="previous" class="secondary">上一组</button><label>对照组<select id="record-select"></select></label><button id="next" class="secondary">下一组</button><span id="progress" aria-live="polite"></span></nav>
<p id="source-note" class="muted"></p><div id="pictures" class="pictures"></div><dialog id="zoom"><div class="zoom-header"><span id="zoom-caption"></span><button id="zoom-close">关闭原尺寸图</button></div><div class="zoom-scroll"><img id="zoom-image" alt=""></div></dialog><fieldset id="criteria"><legend>当前组观察</legend><div id="assessments"></div></fieldset>
<section class="files"><label>载入并替换观察草稿<input id="import-file" type="file" accept=".json,application/json"></label><button id="export">导出观察草稿</button></section><p id="message" role="status" aria-live="polite"></p>
<footer>这是已曝光开发样例的观察记录。生成条件不是年龄真值；无法判断请明确记录。填写或导出不会认证人工身份，也不代表年龄、身份或纹理质量通过。</footer>`;
  const select = element<HTMLSelectElement>("record-select");
  pkg.worksheet.records.forEach((r, i) => {
    const opt = document.createElement("option"); opt.value = String(i); opt.textContent = `${i + 1}/32 · 条件${r.target_age_condition} · ${r.config_id}`; select.append(opt);
  });
  let current = 0, revision = 0, importSequence = 0;
  const message = (text: string, error = false) => { const p = element("message"); p.textContent = text; p.classList.toggle("error", error); };
  const safe = (action: () => void) => { try { action(); } catch (e) { message(e instanceof Error ? e.message : "观察草稿操作失败。", true); } };
  const progress = () => { const s = draft.summary(); element("progress").textContent = `已选 ${s.answered}/${s.total} 项${s.missingNotes ? `，${s.missingNotes}项待补说明` : ""}`; };
  const syncObserver = () => {
    const r = draft.preview().reviewer, active = r.kind !== null;
    element<HTMLSelectElement>("observer-kind").value = r.kind ?? "";
    element<HTMLInputElement>("observer-name").value = r.name ?? "";
    for (const id of ["observer-kind", "observer-name", "begin"]) (element(id) as HTMLInputElement).disabled = active;
    element<HTMLFieldSetElement>("criteria").disabled = !active;
    element("observer-note").textContent = active ? `当前记录来源：${r.kind === "ai" ? "AI" : "人类"}（自述） · ${r.name}。不会自动认定为人工签收。` : "每位观察者单独保存；选择身份后开始记录。清空全部观察后才可更换身份。";
  };
  const render = () => {
    const row = draft.preview().records[current]; select.value = String(current);
    element<HTMLButtonElement>("previous").disabled = current === 0;
    element<HTMLButtonElement>("next").disabled = current === 31;
    element("source-note").textContent = `生成条件 ${row.target_age_condition} · API源龄未确认；63仅为文件名研究标签 · 保存检测结果NO_FACE仍保留。`;
    const pictures = element("pictures"); pictures.replaceChildren();
    const images = [["原始静态参考（非照片真值）", pkg.originals[row.config_id]], ...REVIEW_VARIANTS.map(v => [variantLabels[v], pkg.images[`${current}/${v}`]])];
    for (const [caption, src] of images) {
      if (typeof src !== "string" || !/^data:image\/png;base64,[A-Za-z0-9+/]+=*$/.test(src)) fail("保存画面缺失或无效。");
      const figure = node("figure"), img = document.createElement("img"); img.src = src; img.alt = caption; img.width = img.height = 1024;
      const zoom = node("button", "原尺寸查看"); zoom.className = "zoom-button secondary";
      zoom.addEventListener("click", () => {
        const image = element<HTMLImageElement>("zoom-image"); image.src = src; image.alt = caption;
        element("zoom-caption").textContent = caption; element<HTMLDialogElement>("zoom").showModal();
      });
      figure.append(node("figcaption", caption), img, zoom); pictures.append(figure);
    }
    const assessments = element("assessments"); assessments.replaceChildren();
    for (const c of REVIEW_CRITERIA) {
      const section = node("section"); section.className = "criterion"; section.append(node("h2", labels[c]));
      for (const v of REVIEW_VARIANTS) {
        const cell = node("div"), label = node("label", variantLabels[v]), options = document.createElement("select"), note = document.createElement("textarea");
        options.setAttribute("aria-label", `${labels[c]} · ${variantLabels[v]}`); options.dataset.criterion = c; options.dataset.variant = v;
        for (const rating of REVIEW_RATINGS) { const opt = document.createElement("option"); opt.value = rating; opt.textContent = ratingLabels[rating]; options.append(opt); }
        options.value = row.assessments[v][c].rating;
        note.value = row.assessments[v][c].note; note.maxLength = 2000; note.rows = 3; note.placeholder = "写明可见依据；无法判断也需说明原因";
        note.setAttribute("aria-label", `说明 · ${labels[c]} · ${variantLabels[v]}`);
        const update = () => safe(() => { draft.set(current, v, c, options.value as Rating, note.value); revision++; progress(); message("草稿已修改，请导出保存。"); });
        options.addEventListener("change", update); note.addEventListener("input", update);
        label.append(options); cell.append(label, note); section.append(cell);
      }
      assessments.append(section);
    }
    syncObserver(); progress();
  };
  select.addEventListener("change", () => safe(() => { current = Number(select.value); render(); }));
  element("previous").addEventListener("click", () => safe(() => { if (current > 0) current--; render(); }));
  element("next").addEventListener("click", () => safe(() => { if (current < 31) current++; render(); }));
  element("zoom-close").addEventListener("click", () => element<HTMLDialogElement>("zoom").close());
  element("begin").addEventListener("click", () => safe(() => { draft.start(element<HTMLSelectElement>("observer-kind").value as "human" | "ai", element<HTMLInputElement>("observer-name").value); revision++; syncObserver(); message("已开始记录；内容仅在当前页面内，离开前请导出。"); }));
  element("reset").addEventListener("click", () => safe(() => { draft.reset(); revision++; render(); message("全部观察已清空，原始证据未改变。"); }));
  element<HTMLInputElement>("import-file").addEventListener("change", async event => {
    const input = event.target as HTMLInputElement, file = input.files?.[0], ticket = ++importSequence, expectedRevision = revision;
    try {
      if (!file || !file.size || file.size > MAX_REVIEW_BYTES) fail("请选择不超过512 KiB的观察JSON。");
      const text = await file.text();
      if (ticket !== importSequence || expectedRevision !== revision) return;
      draft.importText(text); revision++; render(); message("已载入并替换草稿，原始证据与观察者身份已核对。");
    } catch (e) { if (ticket === importSequence && expectedRevision === revision) message(e instanceof Error ? e.message : "载入失败。", true); }
    finally { if (ticket === importSequence) input.value = ""; }
  });
  element("export").addEventListener("click", () => safe(() => {
    const text = draft.exportText(), url = URL.createObjectURL(new Blob([text], { type: "application/json" })), a = document.createElement("a");
    a.href = url; a.download = "texture-quality-observations.json"; document.body.append(a); a.click(); a.remove();
    globalThis.setTimeout(() => URL.revokeObjectURL(url), 1000); message("已导出观察草稿；请保留文件，之后仍须使用原校验入口核对。");
  }));
  render();
}
