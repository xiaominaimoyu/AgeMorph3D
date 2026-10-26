import {
  exportMaskDraft,
  parseMaskEditorBinding,
  rasterizeMaskPolygons,
  validateMaskEditorTarget,
} from "../src/research-mask-editor.ts";
import type {
  MaskEditorBinding,
  MaskPoint,
  MaskPolygon,
  MaskReviewer,
} from "../src/research-mask-editor.ts";

function element<T extends HTMLElement>(id: string): T {
  const value = document.getElementById(id);
  if (!value) throw new Error(`遮罩页面缺少组件：${id}`);
  return value as T;
}

const main = element("mask-editor");
const bindingInput = element<HTMLInputElement>("editor-binding");
const targetInput = element<HTMLInputElement>("editor-target");
const loadButton = element<HTMLButtonElement>("load-editor");
const clearButton = element<HTMLButtonElement>("clear-editor");
const canvas = element<HTMLCanvasElement>("mask-canvas");
const context = canvas.getContext("2d");
if (!context) throw new Error("本机浏览器不能建立二维标注画布。");
const overlay = document.createElement("canvas");
overlay.width = overlay.height = 1024;
const overlayContext = overlay.getContext("2d");
if (!overlayContext) throw new Error("本机浏览器不能建立标注预览。");
const kindInput = element<HTMLSelectElement>("polygon-kind");
const finishButton = element<HTMLButtonElement>("finish-polygon");
const cancelButton = element<HTMLButtonElement>("cancel-polygon");
const undoButton = element<HTMLButtonElement>("undo-polygon");
const clearPolygonsButton = element<HTMLButtonElement>("clear-polygons");
const zoomInput = element<HTMLInputElement>("editor-zoom");
const showOverlay = element<HTMLInputElement>("show-overlay");
const reviewerInput = element<HTMLInputElement>("editor-reviewer");
const reviewerKindInput = element<HTMLSelectElement>("editor-review-kind");
const methodInput = element<HTMLTextAreaElement>("editor-method");
const versionInput = element<HTMLInputElement>("editor-version");
const prepareButton = element<HTMLButtonElement>("prepare-export");
const allowedButton = element<HTMLButtonElement>("download-allowed");
const occludedButton = element<HTMLButtonElement>("download-occluded");
const draftButton = element<HTMLButtonElement>("download-draft");
const statusText = element("editor-status");
const errorText = element("editor-error");
const metadataFields = [reviewerInput, reviewerKindInput, methodInput, versionInput];
const urls = new Set<string>();
const timers = new Set<number>();
let epoch = 0;
let disposed = false;
let loadInFlight = false;
let activeLoadEpoch: number | null = null;
let exportInFlight = false;
let binding: MaskEditorBinding | null = null;
let targetBytes: Uint8Array | null = null;
let bitmap: ImageBitmap | null = null;
let polygons: MaskPolygon[] = [];
let points: MaskPoint[] = [];
let masks: ReturnType<typeof rasterizeMaskPolygons> | null = null;
let prepared: Awaited<ReturnType<typeof exportMaskDraft>> | null = null;

function status(message: string): void { statusText.textContent = message; }
function clearError(): void { errorText.textContent = ""; errorText.hidden = true; }
function error(value: unknown): void {
  errorText.textContent = value instanceof Error ? value.message : "当前操作失败。";
  errorText.hidden = false;
}
function releaseDownloads(): void {
  for (const timer of timers) window.clearTimeout(timer);
  timers.clear();
  for (const url of urls) URL.revokeObjectURL(url);
  urls.clear();
}
function clearMetadata(): void {
  for (const field of metadataFields) field.value = "";
}
function counts(): void {
  element("allowed-count").textContent = String(masks?.allowedCount ?? 0);
  element("occluded-count").textContent = String(masks?.occludedCount ?? 0);
  element("unknown-count").textContent = String(masks?.unknownCount ?? 1024 ** 2);
  element("polygon-count").textContent = String(polygons.length);
  element("pending-count").textContent = String(points.length);
}
function metadataReady(): boolean {
  return !!reviewerInput.value.trim() && !!methodInput.value.trim() && !!versionInput.value.trim()
    && (reviewerKindInput.value === "ai" || reviewerKindInput.value === "human");
}
function refresh(): void {
  const loaded = !!binding && !!bitmap && !!targetBytes && !disposed;
  const loading = loadInFlight && activeLoadEpoch === epoch;
  main.dataset.state = disposed ? "disposed" : loading ? "loading" : !loaded ? "empty"
    : exportInFlight ? "exporting" : prepared ? "prepared" : "ready";
  main.setAttribute("aria-busy", String(loading || exportInFlight));
  loadButton.disabled = disposed || loadInFlight || !bindingInput.files?.length || !targetInput.files?.length;
  clearButton.disabled = disposed;
  kindInput.disabled = !loaded;
  finishButton.disabled = !loaded || points.length < 3;
  cancelButton.disabled = !loaded || !points.length;
  undoButton.disabled = !loaded || !polygons.length;
  clearPolygonsButton.disabled = !loaded || !polygons.length && !points.length;
  for (const field of metadataFields) field.disabled = !loaded;
  prepareButton.disabled = !loaded || exportInFlight || !!points.length || !masks?.allowedCount || !metadataReady();
  allowedButton.disabled = occludedButton.disabled = draftButton.disabled = !loaded || !prepared;
  counts();
}
function invalidateExport(): void {
  epoch++;
  prepared = null;
  releaseDownloads();
  clearError();
}
function reset(forgetFiles: boolean, message: string): void {
  invalidateExport();
  activeLoadEpoch = null;
  bitmap?.close();
  bitmap = null;
  binding = null;
  targetBytes = null;
  polygons = [];
  points = [];
  masks = null;
  kindInput.value = "";
  clearMetadata();
  if (forgetFiles) bindingInput.value = targetInput.value = "";
  for (const id of ["editor-source-sha", "editor-generated-sha", "editor-fit-sha"])
    element(id).textContent = "";
  element("editor-stage").textContent = "尚未载入目标";
  context!.clearRect(0, 0, 1024, 1024);
  overlayContext!.clearRect(0, 0, 1024, 1024);
  status(message);
  refresh();
}
function current(token: number): boolean { return !disposed && token === epoch; }

function draw(): void {
  context!.clearRect(0, 0, 1024, 1024);
  if (!bitmap) return;
  context!.drawImage(bitmap, 0, 0);
  if (showOverlay.checked) {
    context!.drawImage(overlay, 0, 0);
    for (const polygon of polygons) outline(polygon.points, polygon.kind, true);
  }
  if (points.length) outline(points, kindInput.value === "occluded" ? "occluded" : "allowed", false);
}
function outline(vertices: readonly MaskPoint[], kind: string, closed: boolean): void {
  const color = kind === "occluded" ? "#e8a04c" : "#35d3c0";
  context!.strokeStyle = context!.fillStyle = color;
  context!.lineWidth = 2;
  context!.beginPath();
  vertices.forEach((point, index) => index ? context!.lineTo(point.x, point.y) : context!.moveTo(point.x, point.y));
  if (closed) context!.closePath();
  context!.stroke();
  for (const point of vertices) {
    context!.beginPath(); context!.arc(point.x, point.y, 4, 0, Math.PI * 2); context!.fill();
  }
}
function updateMasks(next: MaskPolygon[]): void {
  const result = rasterizeMaskPolygons(next);
  invalidateExport();
  polygons = next;
  masks = result;
  const pixels = new Uint8ClampedArray(1024 ** 2 * 4);
  for (let index = 0; index < result.allowed.length; index++) {
    if (result.occluded[index]) pixels.set([232, 160, 76, 105], index * 4);
    else if (result.allowed[index]) pixels.set([53, 211, 192, 90], index * 4);
  }
  overlayContext!.putImageData(new ImageData(pixels, 1024, 1024), 0, 0);
  draw(); refresh();
}
function finishPolygon(): void {
  if (!binding || disposed || points.length < 3) return;
  const kind = kindInput.value;
  if (kind !== "allowed" && kind !== "occluded") return;
  try {
    updateMasks([...polygons, { kind, points: points.map(point => ({ ...point })) }]);
    points = [];
    draw(); refresh();
    status("区域已封闭。遮挡优先，未标注像素仍为未知。");
  } catch (value) { error(value); }
}
function copyBuffer(bytes: Uint8Array): ArrayBuffer {
  const copy = new Uint8Array(bytes.length);
  copy.set(bytes);
  return copy.buffer;
}

loadButton.addEventListener("click", () => {
  if (disposed || loadInFlight) return;
  const jsonFile = bindingInput.files?.[0], pngFile = targetInput.files?.[0];
  reset(false, "正在核对本地阶段绑定与目标 PNG…");
  if (!jsonFile || !pngFile || jsonFile.size < 1 || jsonFile.size > 16 * 1024
    || pngFile.size < 1 || pngFile.size > 4 * 1024 ** 2) {
    error(new Error("请选择非空的绑定 JSON（≤16KiB）与目标 PNG（≤4MiB）。"));
    return;
  }
  const token = epoch;
  activeLoadEpoch = token;
  loadInFlight = true;
  refresh();
  void (async () => {
    let decoded: ImageBitmap | null = null;
    try {
      const [jsonBytes, pngBytes] = await Promise.all([jsonFile.arrayBuffer(), pngFile.arrayBuffer()]);
      if (!current(token)) return;
      const next = parseMaskEditorBinding(new TextDecoder("utf-8", { fatal: true }).decode(jsonBytes));
      const png = new Uint8Array(pngBytes);
      await validateMaskEditorTarget(next, png);
      if (!current(token)) return;
      decoded = await createImageBitmap(new Blob([copyBuffer(png)], { type: "image/png" }),
        { imageOrientation: "none", premultiplyAlpha: "none", colorSpaceConversion: "none" });
      if (!current(token)) return;
      if (decoded.width !== 1024 || decoded.height !== 1024)
        throw new Error("浏览器解码后的目标尺寸必须为1024×1024。");
      binding = next;
      targetBytes = png;
      bitmap = decoded;
      decoded = null;
      masks = rasterizeMaskPolygons([]);
      element("editor-source-sha").textContent = next.stage.source_fingerprint;
      element("editor-generated-sha").textContent = next.stage.generated_sha256;
      element("editor-fit-sha").textContent = next.stage.fit_sha256;
      element("editor-stage").textContent = `当前条件 ${next.stage.target_condition} · 阶段 ${next.stage.stage_id}`;
      draw();
      status("PNG 指纹和原生尺寸已核对。请选择区域类型，再逐点标注；初始没有允许像素。");
    } catch (value) {
      if (current(token)) { reset(false, "输入未通过核对，已清除本次编辑状态。"); error(value); }
    } finally {
      decoded?.close();
      loadInFlight = false;
      activeLoadEpoch = null;
      refresh();
    }
  })();
});
for (const input of [bindingInput, targetInput]) input.addEventListener("change", () => {
  reset(false, "输入已更换，旧标注和记录已清空。请重新核对两份当前文件。");
});
clearButton.addEventListener("click", () => reset(true, "本页输入、图像、标注、记录和下载资源已清除。"));
canvas.addEventListener("click", event => {
  if (!binding || disposed) return;
  const kind = kindInput.value;
  if (kind !== "allowed" && kind !== "occluded") {
    error(new Error("请先选择本次区域为允许区或遮挡区。")); return;
  }
  if (points.length >= 128 || polygons.reduce((sum, polygon) => sum + polygon.points.length, 0) + points.length >= 4096) {
    error(new Error("已达到当前区域或总顶点上限，请先封闭或撤销。")); return;
  }
  const rect = canvas.getBoundingClientRect();
  const point = { x: (event.clientX - rect.left) * 1024 / rect.width,
    y: (event.clientY - rect.top) * 1024 / rect.height };
  if (!Number.isFinite(point.x) || !Number.isFinite(point.y)
    || point.x < 0 || point.y < 0 || point.x > 1024 || point.y > 1024) return;
  invalidateExport(); points.push(point); canvas.focus(); draw(); refresh();
});
canvas.addEventListener("keydown", event => {
  if (event.key === "Enter") { event.preventDefault(); finishPolygon(); }
  if (event.key === "Escape") { event.preventDefault(); cancelButton.click(); }
});
finishButton.addEventListener("click", finishPolygon);
cancelButton.addEventListener("click", () => {
  invalidateExport(); points = []; draw(); refresh(); status("当前点列已取消，已封闭区域保持。");
});
kindInput.addEventListener("change", () => {
  invalidateExport(); points = []; draw(); refresh(); status("已切换区域类型，未封闭点列已清除。");
});
undoButton.addEventListener("click", () => {
  if (!polygons.length) return;
  points = []; updateMasks(polygons.slice(0, -1)); status("已撤销最后一个区域。");
});
clearPolygonsButton.addEventListener("click", () => {
  points = []; clearMetadata(); updateMasks([]); status("画区和记录已清空，当前目标仍可查看。");
});
zoomInput.addEventListener("input", () => {
  const percent = Number(zoomInput.value);
  if (![25, 50, 75, 100, 125, 150].includes(percent)) return;
  canvas.style.width = canvas.style.height = `${1024 * percent / 100}px`;
  element("zoom-value").textContent = `${percent}%`;
});
showOverlay.addEventListener("change", draw);
for (const field of metadataFields) field.addEventListener("input", () => {
  invalidateExport(); refresh(); status("记录已修改，请重新准备导出快照。");
});
reviewerKindInput.addEventListener("change", () => { invalidateExport(); refresh(); });
prepareButton.addEventListener("click", () => {
  if (disposed || exportInFlight || !binding || !targetBytes || points.length) return;
  const kind = reviewerKindInput.value;
  if (kind !== "ai" && kind !== "human") return;
  const reviewer: MaskReviewer = { reviewer: reviewerInput.value.trim(), reviewer_kind: kind,
    method: methodInput.value.trim(), version: versionInput.value.trim() };
  const token = epoch;
  exportInFlight = true;
  prepared = null;
  clearError(); refresh(); status("正在编码并核对不可变的遮罩导出快照…");
  void exportMaskDraft(binding, targetBytes, polygons, reviewer).then(result => {
    if (!current(token)) return;
    prepared = result;
    status("同一快照的三份文件已准备。请分别下载；草稿尚未提交，不代表质量批准。");
  }).catch(value => { if (current(token)) error(value); }).finally(() => {
    exportInFlight = false;
    refresh();
  });
});
function download(bytes: Uint8Array, type: string, suffix: string): void {
  if (!prepared || !binding || disposed) return;
  const blob = new Blob([copyBuffer(bytes)], { type });
  const url = URL.createObjectURL(blob);
  urls.add(url);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `mask-editor-${binding.stage.stage_id.slice(0, 8)}-${suffix}`;
  document.body.append(anchor); anchor.click(); anchor.remove();
  const timer = window.setTimeout(() => {
    timers.delete(timer); URL.revokeObjectURL(url); urls.delete(url);
  }, 1000);
  timers.add(timer);
}
allowedButton.addEventListener("click", () => {
  if (prepared) download(prepared.allowedPng, "image/png", "allowed.png");
});
occludedButton.addEventListener("click", () => {
  if (prepared) download(prepared.occludedPng, "image/png", "occluded.png");
});
draftButton.addEventListener("click", () => {
  if (prepared) download(new TextEncoder().encode(JSON.stringify(prepared.draft, null, 2) + "\n"),
    "application/json", "draft.json");
});
window.addEventListener("pagehide", () => {
  disposed = true;
  reset(true, "页面已释放。");
});
refresh();
