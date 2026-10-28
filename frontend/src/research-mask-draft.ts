/** Explicit local draft checking only; no request, registration or quality approval. */
import {
  MASK_EDITOR_PROTOCOL,
  decodeMaskPng,
  parseMaskEditorBinding,
  rasterizeMaskPolygons,
  validateMaskEditorTarget,
} from "./research-mask-editor.ts";
import type { MaskEditorBinding, MaskPolygon, MaskReviewer } from "./research-mask-editor.ts";

export const MAX_MASK_DRAFT_BYTES = 512 * 1024;
const MAX_PNG = 4 * 1024 ** 2;
const SIZE = 1024;
const SHA = /^[0-9a-f]{64}$/;
const encoder = new TextEncoder();
const COORDINATE_RULE = "native-top-left-pixel-centers-even-odd-edge-cross-1e-9-occlusion-priority-v1";
const FLAGS = Object.freeze({ research_only: true, human_review_completed: false,
  identity_quality_accepted: false, age_quality_accepted: false, visual_seam_quality_accepted: false,
  years_calibrated: false, service_ready: false, production_enabled: false, g3_complete: false });
const STAGE_KEYS = ["stage_id", "source_fingerprint", "target_condition", "generated_sha256", "fit_sha256"];

export interface VerifiedMaskDraft {
  review: MaskReviewer;
  polygons: MaskPolygon[];
  allowedPng: Uint8Array;
  occludedPng: Uint8Array;
  pixelCounts: { allowed: number; occluded: number; unknown: number };
}

function fail(message: string): never { throw new Error(`研究遮罩草稿：${message}`); }
function exact(value: unknown, keys: readonly string[]): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)
    || Object.keys(value).sort().join("\0") !== [...keys].sort().join("\0"))
    fail("对象字段不符合草稿协议。");
  return value as Record<string, unknown>;
}
function binding(value: unknown): MaskEditorBinding {
  const item = exact(value, ["schema_version", "protocol_id", "stage", "width", "height", "research_only"]);
  const stage = exact(item.stage, STAGE_KEYS);
  // Check bounded primitive shape before serializing a caller-owned object.
  if (item.schema_version !== 1 || item.protocol_id !== MASK_EDITOR_PROTOCOL
    || item.width !== SIZE || item.height !== SIZE || item.research_only !== true
    || STAGE_KEYS.some(key => key === "target_condition" ? !Number.isSafeInteger(stage[key])
      : typeof stage[key] !== "string" || (stage[key] as string).length > 64))
    fail("当前绑定无效。");
  return parseMaskEditorBinding(JSON.stringify(item));
}
function parse(text: string): Record<string, unknown> {
  if (typeof text !== "string" || !text.length || text.length > MAX_MASK_DRAFT_BYTES
    || encoder.encode(text).length > MAX_MASK_DRAFT_BYTES) fail("草稿JSON必须非空且不超过512KiB。");
  let value: unknown;
  try { value = JSON.parse(text); } catch { fail("草稿JSON无法解析。"); }
  const stack: (Set<string> | null)[] = [];
  for (const match of text.matchAll(/"(?:\\.|[^"\\])*"|[{}\[\]]/g)) {
    const token = match[0];
    if (token === "{" || token === "[") {
      if (stack.length >= 32) fail("草稿JSON嵌套过深。");
      stack.push(token === "{" ? new Set() : null);
    } else if (token === "}" || token === "]") stack.pop();
    else {
      let index = match.index! + token.length;
      while (index < text.length && /[ \t\r\n]/.test(text[index])) index++;
      if (text[index] !== ":") continue;
      const keys = stack[stack.length - 1], key = JSON.parse(token) as string;
      if (!keys || keys.has(key)) fail("草稿JSON含重复字段。");
      keys.add(key);
    }
  }
  return exact(value, ["schema_version", "protocol_id", "status", "binding", "coordinate_rule",
    "polygons", "review", "masks", "pixel_counts", ...Object.keys(FLAGS)]);
}
function review(value: unknown): MaskReviewer {
  const item = exact(value, ["reviewer", "reviewer_kind", "method", "version"]);
  if (item.reviewer_kind !== "ai" && item.reviewer_kind !== "human") fail("记录来源无效。");
  function field(key: string, maximum: number): string {
    const text = item[key];
    if (typeof text !== "string" || !text.trim() || text.length > maximum || /[\x00-\x1f\x7f]/.test(text))
      fail("记录者、方法或版本无效。");
    return text.trim();
  }
  return { reviewer: field("reviewer", 128), reviewer_kind: item.reviewer_kind,
    method: field("method", 256), version: field("version", 64) };
}
function integer(value: unknown, maximum: number): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0 || (value as number) > maximum)
    fail("草稿计数或字节数无效。");
  return value as number;
}
function manifest(value: unknown): { sha256: string; bytes: number; pixels: number } {
  const item = exact(value, ["sha256", "bytes", "pixels"]);
  if (typeof item.sha256 !== "string" || !SHA.test(item.sha256)) fail("遮罩指纹无效。");
  const bytes = integer(item.bytes, MAX_PNG);
  if (bytes < 57) fail("遮罩字节数无效。");
  return { sha256: item.sha256, bytes, pixels: integer(item.pixels, SIZE * SIZE) };
}
async function sha256(bytes: Uint8Array): Promise<string> {
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new Uint8Array(bytes))),
    value => value.toString(16).padStart(2, "0")).join("");
}

export async function validateMaskDraft(
  currentBinding: MaskEditorBinding, targetPng: Uint8Array, draftText: string,
  allowedPng: Uint8Array, occludedPng: Uint8Array,
): Promise<VerifiedMaskDraft> {
  // Validate every input budget before any PNG copy or asynchronous operation.
  for (const png of [targetPng, allowedPng, occludedPng])
    if (!(png instanceof Uint8Array) || png.length < 57 || png.length > MAX_PNG)
      fail("每张PNG必须非空且不超过4MiB。");
  const draft = parse(draftText), current = binding(currentBinding), declared = binding(draft.binding);
  if (draft.schema_version !== 1 || draft.protocol_id !== MASK_EDITOR_PROTOCOL
    || draft.status !== "draft_unsubmitted" || draft.coordinate_rule !== COORDINATE_RULE
    || Object.entries(FLAGS).some(([key, value]) => draft[key] !== value)) fail("版本、坐标规则、状态或关闭标志无效。");
  if (STAGE_KEYS.some(key => current.stage[key as keyof typeof current.stage]
    !== declared.stage[key as keyof typeof declared.stage])) fail("草稿不属于当前待审核阶段。");
  const reviewer = review(draft.review);
  const masks = exact(draft.masks, ["allowed", "occluded"]);
  const allowedManifest = manifest(masks.allowed), occludedManifest = manifest(masks.occluded);
  const counts = exact(draft.pixel_counts, ["allowed", "occluded", "unknown"]);
  const expected = rasterizeMaskPolygons(draft.polygons as MaskPolygon[]);
  const restoredPolygons = (draft.polygons as MaskPolygon[]).map(polygon => ({
    kind: polygon.kind, points: polygon.points.map(point => ({ x: point.x, y: point.y })),
  }));
  if (!expected.allowedCount || expected.allowedCount === SIZE * SIZE) fail("允许区不得为空或整图全部放行。");
  const pixelCounts = { allowed: expected.allowedCount, occluded: expected.occludedCount, unknown: expected.unknownCount };
  if (Object.entries(pixelCounts).some(([key, value]) => integer(counts[key], SIZE * SIZE) !== value)
    || allowedManifest.pixels !== expected.allowedCount || occludedManifest.pixels !== expected.occludedCount)
    fail("草稿像素计数与多边形不一致。");
  if (allowedManifest.bytes !== allowedPng.length || occludedManifest.bytes !== occludedPng.length)
    fail("遮罩原字节长度与草稿不一致。");
  // All data which survives the first await is owned by this invocation.
  const target = new Uint8Array(targetPng), allowed = new Uint8Array(allowedPng), occluded = new Uint8Array(occludedPng);
  const [allowedSha, occludedSha] = await Promise.all([sha256(allowed), sha256(occluded)]);
  if (allowedSha !== allowedManifest.sha256 || occludedSha !== occludedManifest.sha256)
    fail("遮罩原字节指纹与草稿不一致。");
  await validateMaskEditorTarget(current, target);
  const [allowedPixels, occludedPixels] = await Promise.all([decodeMaskPng(allowed), decodeMaskPng(occluded)]);
  if (allowedPixels.some((value, index) => value !== expected.allowed[index])
    || occludedPixels.some((value, index) => value !== expected.occluded[index])) fail("遮罩像素与草稿多边形不一致。");
  return { review: reviewer, polygons: restoredPolygons, allowedPng: allowed, occludedPng: occluded, pixelCounts };
}
