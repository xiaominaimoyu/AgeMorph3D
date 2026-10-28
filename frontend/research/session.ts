import { FaceViewer } from "../src/viewer.ts";
import type { ModelOptions } from "../src/viewer.ts";
import {
  createResearchTimeline,
  sampleResearchTexture,
} from "../src/research-texture.ts";
import type {
  ResearchTextureFrame,
  ResearchTimeline,
  TextureAnchor,
} from "../src/research-texture.ts";
import {
  ResearchApiError,
  ResearchSessionApi,
  verifyRegisteredProvenance,
} from "../src/research-session.ts";
import type {
  LoadedCondition,
  LoadedSource,
  SessionInfo,
  StageReply,
} from "../src/research-session.ts";
import { createMaskEditorBinding } from "../src/research-mask-editor.ts";
import { MAX_MASK_DRAFT_BYTES, validateMaskDraft } from "../src/research-mask-draft.ts";

function element<T extends HTMLElement>(id: string): T {
  const found = document.getElementById(id);
  if (!found) throw new Error(`研究页面缺少组件：${id}`);
  return found as T;
}

const main = element<HTMLElement>("research-session");
const serviceUrl = element<HTMLInputElement>("service-url");
const connectButton = element<HTMLButtonElement>("connect-service");
const photoInput = element<HTMLInputElement>("source-file");
const sourceAgeInput = element<HTMLInputElement>("source-age");
const createButton = element<HTMLButtonElement>("create-session");
const existingIdInput = element<HTMLInputElement>("existing-session-id");
const existingButton = element<HTMLButtonElement>("connect-existing");
const cancelButton = element<HTMLButtonElement>("cancel-work");
const conditionInput = element<HTMLInputElement>("target-condition");
const stageButton = element<HTMLButtonElement>("stage-condition");
const loadConditionButton = element<HTMLButtonElement>("load-condition");
const reviewArea = element<HTMLElement>("review-area");
const previewImage = element<HTMLImageElement>("target-preview");
const editorBindingButton = element<HTMLButtonElement>("download-editor-binding");
const editorTargetButton = element<HTMLButtonElement>("download-editor-target");
const checkStageButton = element<HTMLButtonElement>("check-review-stage");
const stageStatus = element<HTMLElement>("review-stage-status");
const reviewFields = element<HTMLFieldSetElement>("review-fields");
const allowedInput = element<HTMLInputElement>("review-allowed");
const occludedInput = element<HTMLInputElement>("review-occluded");
const draftInput = element<HTMLInputElement>("review-draft");
const verifyDraftButton = element<HTMLButtonElement>("verify-review-draft");
const clearDraftButton = element<HTMLButtonElement>("clear-review-draft");
const draftStatus = element<HTMLElement>("review-draft-status");
const reviewerInput = element<HTMLInputElement>("review-reviewer");
const methodInput = element<HTMLTextAreaElement>("review-method");
const versionInput = element<HTMLInputElement>("review-version");
const reviewKindInput = element<HTMLSelectElement>("review-kind");
const registerButton = element<HTMLButtonElement>("register-review");
const slider = element<HTMLInputElement>("display-age");
const ageNumber = element<HTMLInputElement>("display-age-number");
const restoreButton = element<HTMLButtonElement>("restore-source");
const sourceDownloadButton = element<HTMLButtonElement>("download-source-glb");
const displayGlbButton = element<HTMLButtonElement>("export-display-glb");
const pngButton = element<HTMLButtonElement>("export-png");
const statusText = element<HTMLElement>("status");
const errorText = element<HTMLElement>("error");
const emptyState = element<HTMLElement>("empty-state");
const sourceSummary = element<HTMLElement>("source-summary");
const geometrySummary = element<HTMLElement>("geometry-summary");
const displayKind = element<HTMLElement>("display-kind");
const displayValue = element<HTMLOutputElement>("display-value");
const timelineSummary = element<HTMLElement>("timeline-summary");

let generation = 0;
let destroyed = false;
let busy = false;
let pending: AbortController | null = null;
let api: ResearchSessionApi | null = null;
let info: SessionInfo | null = null;
let source: LoadedSource | null = null;
let sourcePixels: Uint8ClampedArray | null = null;
let staged: StageReply | null = null;
let editorTargetBytes: ArrayBuffer | null = null;
let stageCheckToken: number | null = null;
let draftImportEpoch = 0;
let draftImportBusy = false;
type VerifiedDraft = {
  result: Awaited<ReturnType<typeof validateMaskDraft>>;
  draftFile: File;
  allowedFile: File;
  occludedFile: File;
  target: StageReply;
  bindingKey: string;
  epoch: number;
};
let verifiedDraft: VerifiedDraft | null = null;
let timeline: ResearchTimeline | null = null;
let frame: ResearchTextureFrame | null = null;
let selectedAge: number | null = null;
let previewUrl: string | null = null;
const conditionAnchors = new Map<number, TextureAnchor>();
const objectUrls = new Set<string>();
const downloadTimers = new Set<number>();

const viewer = new FaceViewer(element("viewer"), {
  onStats: ({ vertices, triangles }) => {
    geometrySummary.textContent = source
      ? `${vertices.toLocaleString()} 顶点 · ${triangles.toLocaleString()} 三角形 · 固定源几何`
      : "未加载真实网格";
  },
  onError: (message) => showError(message),
  onRestore: () => setStatus("图形上下文已恢复；当前会话及显示锚点保持。"),
}, { initialDemo: false });

const knownAge = (): number | null => info?.source_age.value ?? null;
const formatAge = (value: number): string => String(value);

function setStatus(message: string): void {
  statusText.textContent = message;
}

function showError(message: string): void {
  errorText.textContent = message;
  errorText.hidden = false;
}

function clearError(): void {
  errorText.textContent = "";
  errorText.hidden = true;
}

function revokeUrl(url: string): void {
  URL.revokeObjectURL(url);
  objectUrls.delete(url);
}

function revokeAllUrls(): void {
  for (const timer of downloadTimers) window.clearTimeout(timer);
  downloadTimers.clear();
  for (const url of objectUrls) URL.revokeObjectURL(url);
  objectUrls.clear();
  previewUrl = null;
}

function clearReviewerFields(): void {
  reviewerInput.value = methodInput.value = versionInput.value = "";
  reviewKindInput.value = "ai";
}

function invalidateDraftImport(clearMetadata = false): void {
  draftImportEpoch++;
  draftImportBusy = false;
  verifiedDraft = null;
  if (clearMetadata) clearReviewerFields();
  draftStatus.dataset.state = "unverified";
  draftStatus.textContent = draftInput.files?.length
    ? "草稿尚未核对；更改文件或记录后须重新核对，或移除草稿后手动填写。"
    : "尚未导入草稿。选择三份文件后显式核对；核对不会提交或续期。";
}

function currentVerifiedDraft(): VerifiedDraft | null {
  const current = verifiedDraft;
  if (!current || current.epoch !== draftImportEpoch || current.target !== staged
    || draftInput.files?.[0] !== current.draftFile || allowedInput.files?.[0] !== current.allowedFile
    || occludedInput.files?.[0] !== current.occludedFile
    || JSON.stringify(createMaskEditorBinding(current.target.staged)) !== current.bindingKey
    || conditionInput.valueAsNumber !== current.target.staged.target_condition
    || reviewerInput.value !== current.result.review.reviewer
    || methodInput.value !== current.result.review.method || versionInput.value !== current.result.review.version
    || reviewKindInput.value !== current.result.review.reviewer_kind) return null;
  return current;
}

function clearReview(): void {
  stageCheckToken = null;
  stageStatus.dataset.state = "unchecked";
  stageStatus.textContent = "尚未检查阶段活性。离线文件不能保证阶段仍可提交。";
  draftInput.value = "";
  invalidateDraftImport(true);
  staged = null;
  editorTargetBytes = null;
  editorBindingButton.disabled = editorTargetButton.disabled = true;
  if (previewUrl) revokeUrl(previewUrl);
  previewUrl = null;
  previewImage.removeAttribute("src");
  reviewArea.hidden = true;
  allowedInput.value = "";
  occludedInput.value = "";
  for (const id of ["review-source-sha", "review-png-sha", "review-fit-sha", "target-summary"])
    element(id).textContent = "";
}

function releaseSession(): void {
  clearReview();
  revokeAllUrls();
  source = null;
  sourcePixels = null;
  info = null;
  api = null;
  conditionAnchors.clear();
  timeline = null;
  frame = null;
  selectedAge = null;
  viewer.clearModel();
  sourceSummary.textContent = "尚未建立源会话";
  geometrySummary.textContent = "未加载真实网格";
  displayKind.textContent = "未加载";
  displayValue.textContent = "—";
  slider.removeAttribute("aria-valuetext");
  ageNumber.value = "";
  timelineSummary.textContent = "尚无纹理显示锚点。不会超出已有锚点范围外推。";
  emptyState.hidden = false;
}

function refreshControls(): void {
  const bound = !!source && !!info && !destroyed;
  const hasTimelineRange = !!timeline && timeline.anchors.length > 1;
  main.dataset.busy = String(busy);
  main.setAttribute("aria-busy", String(busy));
  main.dataset.state = destroyed ? "disposed" : busy ? "loading" : staged ? "review"
    : bound ? conditionAnchors.size ? "ready" : "source" : "empty";
  connectButton.disabled = busy || destroyed;
  createButton.disabled = busy || destroyed || !photoInput.files?.length;
  existingButton.disabled = busy || destroyed || !existingIdInput.value;
  cancelButton.disabled = destroyed || (!busy && !bound && !staged);
  conditionInput.disabled = !bound || busy;
  stageButton.disabled = !bound || busy;
  loadConditionButton.disabled = !bound || busy;
  reviewFields.disabled = !staged || busy || !bound;
  editorBindingButton.disabled = editorTargetButton.disabled = !staged || !editorTargetBytes || busy || !bound;
  checkStageButton.disabled = !staged || busy || !bound;
  verifyDraftButton.disabled = !staged || !editorTargetBytes || busy || !bound
    || !draftInput.files?.length || !allowedInput.files?.length || !occludedInput.files?.length;
  clearDraftButton.disabled = busy || !draftInput.files?.length;
  registerButton.disabled = !staged || busy || !bound || !allowedInput.files?.length
    || !occludedInput.files?.length || !reviewerInput.value.trim()
    || !methodInput.value.trim() || !versionInput.value.trim()
    || !!draftInput.files?.length && !currentVerifiedDraft();
  slider.disabled = busy || !hasTimelineRange;
  ageNumber.disabled = busy || !hasTimelineRange;
  restoreButton.disabled = !bound || busy;
  sourceDownloadButton.disabled = !bound || busy;
  displayGlbButton.disabled = !bound || busy;
  pngButton.disabled = !bound || busy;
}

function invalidate(message: string, forgetInputs = false): void {
  pending?.abort();
  pending = null;
  generation++;
  busy = false;
  releaseSession();
  if (forgetInputs) {
    photoInput.value = "";
    sourceAgeInput.value = "";
    existingIdInput.value = "";
  }
  clearError();
  setStatus(message);
  refreshControls();
}

function ensureCurrent(token: number, signal?: AbortSignal): void {
  if (destroyed || token !== generation || signal?.aborted)
    throw new DOMException("研究操作已取消。", "AbortError");
}

type Operation = {
  readonly token: number;
  readonly signal: AbortSignal;
  readonly client: ResearchSessionApi;
};

async function perform(
  label: string,
  action: (operation: Operation) => Promise<void>,
  freshSource = false,
): Promise<void> {
  if (destroyed) return;
  pending?.abort();
  const token = ++generation;
  const controller = new AbortController();
  pending = controller;
  if (freshSource) releaseSession();
  busy = true;
  clearError();
  setStatus(label);
  refreshControls();
  try {
    const client = api ?? new ResearchSessionApi(serviceUrl.value.trim());
    await action({ token, signal: controller.signal, client });
    ensureCurrent(token, controller.signal);
  } catch (error) {
    const cancelled = destroyed || token !== generation || controller.signal.aborted
      || error instanceof DOMException && error.name === "AbortError";
    controller.abort(); // End unfinished sibling downloads before dropping operation ownership.
    if (cancelled) return;
    const code = error instanceof ResearchApiError ? error.code : null;
    if (code === "SESSION_EXPIRED") releaseSession();
    else if (code === "STAGE_EXPIRED") clearReview();
    const messages: Record<string, string> = {
      SESSION_EXPIRED: "源会话已过期。请重新建立或载入有效会话；本页已清除旧显示。",
      STAGE_EXPIRED: "待审核目标已过期。请重新暂存该条件，不能提交旧目标的mask。",
      SOURCE_AGE_REQUIRED: "源龄未知。请保持未知记录，或使用明确提供源龄的新会话。",
      INTEGER_AGE_REQUIRED: "生成只接受20—70的整数条件；小数只用于已有锚点之间的显示。",
      REVIEW_REQUIRED: "当前目标缺少匹配的审核记录。请核对三项指纹和两张mask。",
      RESULT_CONFLICT: "同一条件已有不同审核结果。请载入已审核条件，或新建会话后再提交。",
      BUSY: "本机模型仍在处理任务。请稍后重试；取消等待不会提前释放正在运行的模型。",
      TIMEOUT: "本机请求已超时。后台原生工作仍由服务完成清理，请稍后重试。",
    };
    showError(code && messages[code] ? messages[code]
      : error instanceof Error ? error.message : "研究操作失败，请检查本机服务。" );
    setStatus(source ? "操作未完成，已保留当前有效源会话。" : "操作未完成，尚未加载有效源会话。");
  } finally {
    if (token === generation) {
      busy = false;
      pending = null;
      refreshControls();
    }
  }
}

function pngFrame(bytes: ArrayBuffer, size: number, grayscale = false): void {
  if (bytes.byteLength < 33 || bytes.byteLength > 4 * 1024 ** 2)
    throw new Error("PNG必须是非空且不超过4MiB的有界文件。");
  const view = new DataView(bytes);
  const signature = [137, 80, 78, 71, 13, 10, 26, 10];
  if (signature.some((value, index) => view.getUint8(index) !== value)
    || view.getUint32(8) !== 13 || view.getUint32(12) !== 0x49484452
    || view.getUint32(16) !== size || view.getUint32(20) !== size
    || view.getUint8(24) !== 8 || grayscale && view.getUint8(25) !== 0)
    throw new Error(grayscale ? "审核mask必须是1024×1024、8位灰度L PNG。" : "研究图集必须使用256×256 PNG栅格。");
}

async function decodePng(bytes: ArrayBuffer, size: number): Promise<Uint8ClampedArray> {
  pngFrame(bytes, size);
  const bitmap = await createImageBitmap(new Blob([bytes], { type: "image/png" }), {
    premultiplyAlpha: "none", colorSpaceConversion: "none",
  });
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  try {
    if (bitmap.width !== size || bitmap.height !== size)
      throw new Error("解码PNG的尺寸与声明不一致。");
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) throw new Error("浏览器无法创建研究纹理画布。");
    context.drawImage(bitmap, 0, 0);
    return context.getImageData(0, 0, size, size).data;
  } finally {
    bitmap.close();
    canvas.width = canvas.height = 0;
  }
}

function validateAtlas(rgba: Uint8ClampedArray): void {
  for (let offset = 0; offset < rgba.length; offset += 4) {
    if (rgba[offset + 3] !== 0 && rgba[offset + 3] !== 255)
      throw new Error("源和生成锚点的alpha必须为0或255。");
    if (rgba[offset + 3] === 0 && (rgba[offset] || rgba[offset + 1] || rgba[offset + 2]))
      throw new Error("未知纹理像素必须为RGBA零。");
  }
}

function modelOptions(loaded: LoadedSource): ModelOptions {
  return {
    asset_mode: "static", topology_id: loaded.topologyId,
    source_age: { ...loaded.info.source_age },
    capabilities: { age_morph: false, age_texture: false },
  };
}

function updateTimeline(): void {
  if (!source || !info || !sourcePixels) return;
  const anchors: TextureAnchor[] = [...conditionAnchors.values()];
  const sourceAge = knownAge();
  if (sourceAge !== null) anchors.push({
    age: sourceAge, kind: "original_source", width: 256, height: 256, rgba: sourcePixels,
  });
  timeline = anchors.length ? createResearchTimeline(anchors, sourceAge) : null;
  if (!timeline) {
    timelineSummary.textContent = "源龄未知；原始源仅作原图显示。先载入审核条件，再建立条件显示锚点。";
    return;
  }
  const ages = timeline.anchors.map(anchor => anchor.age);
  slider.min = ageNumber.min = String(ages[0]);
  slider.max = ageNumber.max = String(ages[ages.length - 1]);
  timelineSummary.textContent = ages.length > 1
    ? `已有锚点：${ages.map(formatAge).join("、")}。显示范围 ${formatAge(ages[0])}—${formatAge(ages[ages.length - 1])}，小数不触发生成。${sourceAge === null ? "源龄未知，不设原始源龄锚点。" : ""}`
    : `当前只有 ${formatAge(ages[0])} 一个显示锚点；再载入不同条件后可连续显示。`;
}

function restoreOriginal(): void {
  if (!source || !info || destroyed) return;
  viewer.setResearchDisplayTexture(null);
  frame = null;
  selectedAge = knownAge();
  displayKind.textContent = "原始源 · 原材质";
  displayValue.textContent = selectedAge === null ? "原始源（源龄未知）" : `原始源 ${formatAge(selectedAge)}`;
  slider.value = selectedAge === null ? slider.min : String(selectedAge);
  ageNumber.value = selectedAge === null ? "" : String(selectedAge);
  slider.setAttribute("aria-valuetext", selectedAge === null
    ? "原始源显示，源龄未知" : `原始源龄 ${formatAge(selectedAge)}`);
}

function showAge(value: number): void {
  if (!source || !timeline || destroyed) throw new Error("请先载入有效研究纹理锚点。");
  const next = sampleResearchTexture(timeline, value);
  viewer.setResearchDisplayTexture(next);
  frame = next;
  selectedAge = value;
  slider.value = ageNumber.value = String(value);
  slider.setAttribute("aria-valuetext", `${formatAge(value)}，研究显示位置`);
  displayValue.textContent = `${formatAge(value)} · 显示位置`;
  displayKind.textContent = next.exactSource ? "源龄锚点 · BLEND衍生显示" : "研究纹理 · BLEND显示";
}

async function bindSource(loaded: LoadedSource, operation: Operation): Promise<void> {
  const rgba = await decodePng(loaded.textureBytes, 256);
  ensureCurrent(operation.token, operation.signal);
  validateAtlas(rgba);
  await viewer.loadResearchModelBytes(loaded.glbBytes, modelOptions(loaded));
  ensureCurrent(operation.token, operation.signal);
  source = loaded;
  sourcePixels = rgba;
  info = loaded.info;
  api = operation.client;
  existingIdInput.value = info.session_id;
  sourceSummary.textContent = info.source_age.value === null
    ? "源龄：未知。原始模型可查看；不补默认年龄。"
    : `源龄：${formatAge(info.source_age.value)} · 来源：${info.source_age.method === "user" ? "用户明确提供" : "有记录的估计"}`;
  emptyState.hidden = true;
  updateTimeline();
  restoreOriginal();
  setStatus("源会话已载入。查看器使用真实静态网格，年龄形状能力保持关闭。");
}

async function addCondition(loaded: LoadedCondition, operation: Operation): Promise<void> {
  const rgba = await decodePng(loaded.textureBytes, 256);
  ensureCurrent(operation.token, operation.signal);
  validateAtlas(rgba);
  conditionAnchors.set(loaded.condition, {
    age: loaded.condition, kind: "sam_condition", width: 256, height: 256, rgba,
  });
  updateTimeline();
  showAge(loaded.condition);
  setStatus(knownAge() === loaded.condition
    ? "同龄条件已记录；显示以原始源锚点为准，原始文件保持不变。"
    : `已审核条件 ${loaded.condition} 已载入。连续显示只在现有锚点之间插值，不改变源网格形状。`);
}

function requestedCondition(): number {
  const text = conditionInput.value;
  if (!/^(?:[2-6][0-9]|70)$/.test(text))
    throw new Error("生成条件必须是20—70的精确整数。");
  return Number(text);
}

function selectedPhoto(): File {
  const file = photoInput.files?.[0];
  if (!file || file.size < 1 || file.size > 10 * 1024 ** 2
    || !["image/jpeg", "image/png", "image/webp"].includes(file.type))
    throw new Error("请选择不超过10MiB的JPEG、PNG或WebP照片。");
  return file;
}

async function validateMasks(allowed: File, occluded: File, operation: Operation): Promise<void> {
  const buffers = await Promise.all([allowed.arrayBuffer(), occluded.arrayBuffer()]);
  ensureCurrent(operation.token, operation.signal);
  for (const bytes of buffers) pngFrame(bytes, 1024, true);
  const [a, b] = await Promise.all(buffers.map(bytes => decodePng(bytes, 1024)));
  ensureCurrent(operation.token, operation.signal);
  for (let index = 0; index < a.length; index += 4) {
    for (const pixels of [a, b]) {
      if (pixels[index + 3] !== 255 || pixels[index] !== pixels[index + 1]
        || pixels[index] !== pixels[index + 2] || pixels[index] !== 0 && pixels[index] !== 255)
        throw new Error("审核mask的灰度像素必须全部为0或255。");
    }
    if (a[index] && b[index]) throw new Error("允许区与排除区必须互斥，不能同时覆盖同一像素。");
  }
}

function download(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  objectUrls.add(url);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  const timer = window.setTimeout(() => {
    downloadTimers.delete(timer);
    revokeUrl(url);
  }, 1000);
  downloadTimers.add(timer);
}

connectButton.addEventListener("click", () => void perform("正在检查本机研究服务…", async operation => {
  await operation.client.health(operation.signal);
  ensureCurrent(operation.token, operation.signal);
  element("connection-status").textContent = "本机研究服务可访问；生产年龄与质量资格保持关闭。";
  setStatus("研究服务连接检查通过。照片仅在你提交建立会话时发送至该本机地址。");
}));

createButton.addEventListener("click", () => {
  let file: File;
  try { file = selectedPhoto(); } catch (error) { showError((error as Error).message); return; }
  if (!sourceAgeInput.validity.valid) {
    showError("请输入20—70之间的有效源龄，或完全清空以保留未知。"); return;
  }
  const age = sourceAgeInput.value || undefined;
  void perform("正在建立源会话并加载原始网格…", async operation => {
    const created = await operation.client.createSession(file, age, operation.signal);
    ensureCurrent(operation.token, operation.signal);
    const loaded = await operation.client.loadSource(created, operation.signal);
    ensureCurrent(operation.token, operation.signal);
    await bindSource(loaded, operation);
  }, true);
});

existingButton.addEventListener("click", () => {
  const identifier = existingIdInput.value.trim();
  void perform("正在读取已有源会话…", async operation => {
    const existing = await operation.client.sessionInfo(identifier, operation.signal);
    ensureCurrent(operation.token, operation.signal);
    const loaded = await operation.client.loadSource(existing, operation.signal);
    ensureCurrent(operation.token, operation.signal);
    await bindSource(loaded, operation);
  }, true);
});

stageButton.addEventListener("click", () => {
  const current = info;
  if (!current || !source) return;
  let condition: number;
  try { condition = requestedCondition(); } catch (error) { showError((error as Error).message); return; }
  clearReview();
  void perform(`正在生成并暂存整数条件 ${condition}…`, async operation => {
    const target = await operation.client.stage(current.session_id, condition, operation.signal);
    ensureCurrent(operation.token, operation.signal);
    if (target.staged.source_fingerprint !== current.source_fingerprint)
      throw new Error("暂存目标的源指纹与当前会话不一致。");
    const [png] = await Promise.all([
      operation.client.preview(current.session_id, target, operation.signal),
      operation.client.fit(current.session_id, target, operation.signal),
    ]);
    ensureCurrent(operation.token, operation.signal);
    staged = target;
    editorTargetBytes = png.slice(0);
    previewUrl = URL.createObjectURL(new Blob([png], { type: "image/png" }));
    objectUrls.add(previewUrl);
    previewImage.src = previewUrl;
    reviewArea.hidden = false;
    element("review-source-sha").textContent = target.staged.source_fingerprint;
    element("review-png-sha").textContent = target.staged.generated_sha256;
    element("review-fit-sha").textContent = target.staged.fit_sha256;
    element("target-summary").textContent = `当前生成条件 ${condition}。PNG与目标拟合指纹已核对；尚未注册为纹理。`;
    setStatus("目标已暂存。请查看当前图像，并提供与它匹配的保守mask和审核记录。");
  });
});

editorBindingButton.addEventListener("click", () => {
  if (!staged || !editorTargetBytes || busy || destroyed) return;
  const binding = createMaskEditorBinding(staged.staged);
  download(new Blob([JSON.stringify(binding, null, 2) + "\n"], { type: "application/json" }),
    `mask-editor-${staged.staged.stage_id.slice(0, 8)}-binding.json`);
});
editorTargetButton.addEventListener("click", () => {
  if (!staged || !editorTargetBytes || busy || destroyed) return;
  download(new Blob([editorTargetBytes.slice(0)], { type: "image/png" }),
    `mask-editor-${staged.staged.stage_id.slice(0, 8)}-target.png`);
});

loadConditionButton.addEventListener("click", () => {
  const current = info, original = source;
  if (!current || !original) return;
  let condition: number;
  try { condition = requestedCondition(); } catch (error) { showError((error as Error).message); return; }
  void perform(`正在读取已审核条件 ${condition}…`, async operation => {
    const loaded = await operation.client.loadCondition(current, condition, original, operation.signal);
    ensureCurrent(operation.token, operation.signal);
    await addCondition(loaded, operation);
  });
});

checkStageButton.addEventListener("click", () => {
  const current = info, target = staged;
  if (busy || destroyed || !current || !target || !source) return;
  void perform("正在检查当前待审核阶段…", async operation => {
    stageCheckToken = operation.token;
    stageStatus.dataset.state = "checking";
    stageStatus.textContent = "正在查询阶段状态，不续期或保留提交名额…";
    try {
      await operation.client.checkStage(current.session_id, target, operation.signal);
      ensureCurrent(operation.token, operation.signal);
      if (info !== current || staged !== target || conditionInput.valueAsNumber !== target.staged.target_condition)
        throw new DOMException("检查期间审核阶段已改变。", "AbortError");
      stageStatus.dataset.state = "available";
      stageStatus.textContent = "上次检查时阶段可用。本次检查不续期、不保留提交名额，提交时服务仍会再次核验。";
      setStatus("已检查待审核阶段；没有下载目标图、生成或提交审核记录。");
    } catch (value) {
      if (operation.token === generation && !operation.signal.aborted) {
        stageStatus.dataset.state = "unknown";
        stageStatus.textContent = "未核实阶段可用性，请查看错误提示或重新检查。";
      }
      if (value instanceof ResearchApiError && value.code === "TIMEOUT")
        throw new Error("待审核阶段检查超时，可用性尚未核实。本次检查没有续期或保留提交名额，请稍后重新检查。");
      throw value;
    } finally {
      if (stageCheckToken === operation.token) stageCheckToken = null;
    }
  });
});

verifyDraftButton.addEventListener("click", () => {
  if (busy || destroyed) return;
  const target = staged, targetBytes = editorTargetBytes;
  const draft = draftInput.files?.[0], allowed = allowedInput.files?.[0], occluded = occludedInput.files?.[0];
  invalidateDraftImport(true);
  clearError();
  if (!target || !targetBytes || !draft || !allowed || !occluded) {
    showError("需要当前待审核目标、草稿JSON和两张配套遮罩。"); refreshControls(); return;
  }
  if (draft.size < 1 || draft.size > MAX_MASK_DRAFT_BYTES
    || [allowed, occluded].some(file => file.size < 1 || file.size > 4 * 1024 ** 2)) {
    showError("草稿必须非空且不超过512KiB；每张遮罩必须非空且不超过4MiB。");
    refreshControls(); return;
  }
  const epoch = draftImportEpoch;
  const binding = createMaskEditorBinding(target.staged);
  const bindingKey = JSON.stringify(binding);
  void perform("正在本地核对草稿、当前目标和两张遮罩…", async operation => {
    draftImportBusy = true;
    try {
      const [draftBytes, allowedBytes, occludedBytes] = await Promise.all([
        draft.arrayBuffer(), allowed.arrayBuffer(), occluded.arrayBuffer(),
      ]);
      ensureCurrent(operation.token, operation.signal);
      if (draftBytes.byteLength !== draft.size || allowedBytes.byteLength !== allowed.size
        || occludedBytes.byteLength !== occluded.size) throw new Error("本地文件读取长度发生变化，请重新选择。");
      const result = await validateMaskDraft(binding, new Uint8Array(targetBytes),
        new TextDecoder("utf-8", { fatal: true }).decode(draftBytes),
        new Uint8Array(allowedBytes), new Uint8Array(occludedBytes));
      ensureCurrent(operation.token, operation.signal);
      if (epoch !== draftImportEpoch || staged !== target || editorTargetBytes !== targetBytes
        || draftInput.files?.[0] !== draft || allowedInput.files?.[0] !== allowed
        || occludedInput.files?.[0] !== occluded
        || JSON.stringify(createMaskEditorBinding(target.staged)) !== bindingKey
        || conditionInput.valueAsNumber !== target.staged.target_condition)
        throw new DOMException("草稿核对期间输入已改变。", "AbortError");
      reviewerInput.value = result.review.reviewer;
      methodInput.value = result.review.method;
      versionInput.value = result.review.version;
      reviewKindInput.value = result.review.reviewer_kind;
      verifiedDraft = { result, draftFile: draft, allowedFile: allowed, occludedFile: occluded,
        target, bindingKey, epoch };
      draftStatus.dataset.state = "verified";
      draftStatus.textContent = `本地文件核对通过：允许 ${result.pixelCounts.allowed}、遮挡 ${result.pixelCounts.occluded}、未知 ${result.pixelCounts.unknown} 像素。尚未提交，阶段有效性由服务核验。`;
      setStatus("草稿及两张遮罩已在本地核对；请检查记录后显式提交，核对不代表人工质量签收。");
    } finally {
      if (epoch === draftImportEpoch) draftImportBusy = false;
    }
  });
});

clearDraftButton.addEventListener("click", () => {
  if (busy || destroyed) return;
  draftInput.value = "";
  invalidateDraftImport(true);
  clearError();
  setStatus("已移除草稿及其审核字段。可以保留当前两张mask，手动填写研究审核记录。");
  refreshControls();
});

registerButton.addEventListener("click", () => {
  if (busy || destroyed) return;
  const current = info, original = source, target = staged;
  const allowed = allowedInput.files?.[0], occluded = occludedInput.files?.[0];
  if (!current || !original || !target || !allowed || !occluded) return;
  const imported = currentVerifiedDraft();
  if (draftInput.files?.length && !imported) {
    showError("所选草稿尚未核对或输入已改变，请重新核对，或移除草稿后手动填写。"); return;
  }
  // Verified imports submit owned snapshots rather than rereading selected disk files.
  const submittedAllowed = imported ? new File([new Uint8Array(imported.result.allowedPng)],
    allowed.name, { type: "image/png" }) : allowed;
  const submittedOccluded = imported ? new File([new Uint8Array(imported.result.occludedPng)],
    occluded.name, { type: "image/png" }) : occluded;
  const reviewer = reviewerInput.value.trim(), method = methodInput.value.trim(), version = versionInput.value.trim();
  const kind = reviewKindInput.value;
  if (!reviewer || !method || !version || kind !== "ai" && kind !== "human") {
    showError("请完整填写审核者、方法、版本与记录来源。"); return;
  }
  if ([allowed, occluded].some(file => file.size < 1 || file.size > 4 * 1024 ** 2)) {
    showError("每张审核mask必须非空且不超过4MiB。"); return;
  }
  void perform("正在核对二值mask并注册当前目标…", async operation => {
    await validateMasks(submittedAllowed, submittedOccluded, operation);
    ensureCurrent(operation.token, operation.signal);
    if (imported && currentVerifiedDraft() !== imported)
      throw new DOMException("注册前草稿或审核输入已改变。", "AbortError");
    const registered = await operation.client.register(current.session_id, target, {
      allowed: submittedAllowed, occluded: submittedOccluded, reviewer, reviewer_kind: kind, method, version,
    }, operation.signal);
    ensureCurrent(operation.token, operation.signal);
    const loaded = await operation.client.loadCondition(current, target.staged.target_condition,
      original, operation.signal);
    ensureCurrent(operation.token, operation.signal);
    await verifyRegisteredProvenance(registered, loaded);
    ensureCurrent(operation.token, operation.signal);
    await addCondition(loaded, operation);
    ensureCurrent(operation.token, operation.signal);
    clearReview();
  });
});

function displayInput(raw: string): void {
  clearError();
  try {
    if (!raw.trim()) throw new Error("请输入已有锚点范围内的显示位置。");
    showAge(Number(raw));
    setStatus("已更新本地显示插值，没有发送新的生成请求。");
  } catch (error) {
    showError(error instanceof Error ? error.message : "显示位置无效。");
  }
}
slider.addEventListener("input", () => {
  if (!timeline) return;
  const lower = timeline.anchors[0].age;
  const upper = timeline.anchors[timeline.anchors.length - 1].age;
  const nativeValue = slider.valueAsNumber;
  // Native range serialization can lose the last bits of a decimal endpoint.
  // A physical endpoint selects that exact anchor; typed numbers are never clamped.
  const endpoint = slider.cloneNode() as HTMLInputElement;
  endpoint.value = slider.min;
  const nativeLower = endpoint.valueAsNumber;
  endpoint.value = slider.max;
  const nativeUpper = endpoint.valueAsNumber;
  const position = nativeValue <= nativeLower ? lower : nativeValue >= nativeUpper ? upper : nativeValue;
  displayInput(String(position));
});
ageNumber.addEventListener("change", () => displayInput(ageNumber.value));
restoreButton.addEventListener("click", () => {
  clearError(); restoreOriginal();
  setStatus("已恢复原始源地图与原材质；原始文件下载仍返回未改变的源GLB字节。");
});
sourceDownloadButton.addEventListener("click", () => {
  if (!source) return;
  download(new Blob([source.glbBytes], { type: "model/gltf-binary" }), "research-original-source.glb");
  setStatus("已下载原始源GLB字节，不是连续显示导出的衍生物。");
});
displayGlbButton.addEventListener("click", () => void perform("正在导出当前显示GLB…", async operation => {
  const blob = await viewer.exportGLB();
  ensureCurrent(operation.token, operation.signal);
  download(blob, "research-current-display.glb");
  setStatus("当前显示GLB已导出；研究显示信息与原始源文件分别保留。");
}));
pngButton.addEventListener("click", () => void perform("正在导出当前视图PNG…", async operation => {
  const blob = await viewer.exportPNG();
  ensureCurrent(operation.token, operation.signal);
  download(blob, "research-current-view.png");
  setStatus("当前视图PNG已导出，图像不代表年龄或身份质量验收。");
}));

cancelButton.addEventListener("click", () => invalidate(
  "已清除本页会话和显示；后台原生任务由本机服务继续完成清理。", true,
));
photoInput.addEventListener("change", () => {
  sourceAgeInput.value = "";
  existingIdInput.value = "";
  invalidate("已更换照片并清除旧会话。请重新填写这张照片的明确源龄，或保持未知。");
});
sourceAgeInput.addEventListener("input", () => {
  existingIdInput.value = "";
  invalidate("源龄输入已改变。请以当前照片和源龄重新建立会话。");
});
serviceUrl.addEventListener("input", () => {
  existingIdInput.value = "";
  invalidate("服务地址已改变，已清除旧连接下的会话显示。");
  element("connection-status").textContent = "请检查新的本机研究服务地址。";
});
existingIdInput.addEventListener("input", () => {
  photoInput.value = "";
  sourceAgeInput.value = "";
  invalidate("会话标识已改变，载入前不会显示上一会话的网格。");
});
conditionInput.addEventListener("input", () => {
  const importing = draftImportBusy;
  const checkingStage = stageCheckToken === generation;
  if (importing || checkingStage) pending?.abort();
  if (!busy || importing || checkingStage) clearReview();
  clearError();
  refreshControls();
});
for (const input of [draftInput, allowedInput, occludedInput]) {
  input.addEventListener("change", () => {
    const hadDraft = !!draftInput.files?.length || !!verifiedDraft;
    if (draftImportBusy) pending?.abort();
    invalidateDraftImport(hadDraft);
    clearError();
    refreshControls();
  });
}
for (const input of [reviewerInput, methodInput, versionInput, reviewKindInput]) {
  const changed = (): void => {
    if (draftImportBusy) pending?.abort();
    invalidateDraftImport();
    refreshControls();
  };
  input.addEventListener("input", changed);
  input.addEventListener("change", changed);
}

function destroy(): void {
  if (destroyed) return;
  destroyed = true;
  pending?.abort();
  pending = null;
  generation++;
  busy = false;
  releaseSession();
  photoInput.value = sourceAgeInput.value = existingIdInput.value = "";
  viewer.dispose();
  clearError();
  setStatus("本页会话与显示资源已释放。请刷新页面后重新连接研究服务。");
  element("connection-status").textContent = "本页资源已释放。";
  refreshControls();
}
window.addEventListener("pagehide", destroy, { once: true });

async function bytesDigest(bytes: ArrayBuffer | Uint8ClampedArray): Promise<string> {
  const owned = bytes instanceof ArrayBuffer ? bytes.slice(0) : new Uint8Array(bytes).buffer;
  const hash = new Uint8Array(await crypto.subtle.digest("SHA-256", owned));
  return [...hash].map(value => value.toString(16).padStart(2, "0")).join("");
}

/** Dev harness only: hashes/state are available without putting raw pixels into page controls. */
if (import.meta.env.DEV) {
  const tools = Object.freeze({
    state: () => Object.freeze({
      generation, destroyed, busy, sessionId: info?.session_id ?? null,
      sourceAge: info ? { ...info.source_age } : null,
      geometryHashes: source ? { ...source.geometryHashes } : null,
      anchorAges: timeline?.anchors.map(anchor => anchor.age) ?? [],
      conditionAges: [...conditionAnchors.keys()], selectedAge,
      exactSourceDisplay: frame?.exactSource ?? false,
      displayMode: frame ? "research-blend" : source ? "original" : "empty",
      pendingStage: staged ? { ...staged.staged } : null,
      stageCheckPending: stageCheckToken === generation,
      draftVerified: !!currentVerifiedDraft(), draftImportBusy,
      objectUrls: objectUrls.size, hasSourceBytes: source !== null,
      research_only: true, service_ready: false, g3_complete: false,
    }),
    frameDigest: async () => frame ? bytesDigest(frame.rgba) : null,
    sourceDigest: async () => source ? bytesDigest(source.glbBytes) : null,
    viewer: () => viewer,
  });
  (window as Window & { __researchSessionTools?: typeof tools }).__researchSessionTools = tools;
}

refreshControls();
