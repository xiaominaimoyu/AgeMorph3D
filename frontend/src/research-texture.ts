/** Offline display sampling only; this does not authorize production aging.
 * Anchor buffers belong to the caller and must stay unchanged while in use.
 * Exact source sampling retains that original buffer reference.
 */
export interface TextureAnchor {
  readonly age: number;
  readonly rgba: Uint8ClampedArray;
  readonly width: number;
  readonly height: number;
  readonly kind: "sam_condition" | "original_source";
}

export interface ResearchTimeline {
  readonly kind: "research-display-timeline";
  readonly anchors: readonly TextureAnchor[];
  readonly sourceLabel: number | null;
  readonly width: number;
  readonly height: number;
}

export interface ResearchTextureFrame {
  readonly kind: "research-display-only";
  readonly width: number;
  readonly height: number;
  readonly rgba: Uint8ClampedArray;
  readonly targetAge: number;
  readonly sourceLabel: number | null;
  readonly exactSource: boolean;
}

const MAX_PIXELS = 16_000_000;
const MAX_ANCHORS = 64;

function age(value: unknown): asserts value is number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 20 || value > 70)
    throw new Error("研究年龄必须是20—70内的有限数值，不取整或外推。");
}

function validateAnchor(anchor: TextureAnchor): void {
  if (!anchor || (anchor.kind !== "sam_condition" && anchor.kind !== "original_source"))
    throw new Error("研究纹理锚点必须明确像素来源。");
  age(anchor.age);
  if (anchor.kind === "sam_condition" && !Number.isInteger(anchor.age))
    throw new Error("SAM条件锚点必须为精确整数，小数仅用于原始源或显示插值。");
  const pixels = anchor.width * anchor.height;
  if (
    !Number.isSafeInteger(anchor.width) || !Number.isSafeInteger(anchor.height)
    || anchor.width < 1 || anchor.height < 1 || !Number.isSafeInteger(pixels)
    || pixels > MAX_PIXELS || !(anchor.rgba instanceof Uint8ClampedArray)
    || anchor.rgba.length !== pixels * 4
  ) throw new Error("研究纹理必须是尺寸匹配且有界的RGBA字节数组。");
  for (let offset = 0; offset < anchor.rgba.length; offset += 4) {
    const alpha = anchor.rgba[offset + 3];
    if (alpha !== 0 && alpha !== 255)
      throw new Error("原始锚点alpha必须为0或255。");
    if (alpha === 0 && (anchor.rgba[offset] || anchor.rgba[offset + 1] || anchor.rgba[offset + 2]))
      throw new Error("未知纹理区域必须为RGBA零。");
  }
}

export function createResearchTimeline(
  anchors: readonly TextureAnchor[],
  sourceLabel: number | null,
): ResearchTimeline {
  if (sourceLabel !== null) age(sourceLabel);
  if (!Array.isArray(anchors) || !anchors.length || anchors.length > MAX_ANCHORS)
    throw new Error("研究纹理锚点数量必须为1—64。");
  const selected = new Map<number, TextureAnchor>();
  const seen = new Set<string>();
  let pixels = 0, originalCount = 0;
  for (const anchor of anchors) {
    if (anchor && pixels + anchor.width * anchor.height > MAX_PIXELS)
      throw new Error("锚点总像素超过1600万预算。");
    validateAnchor(anchor);
    pixels += anchor.width * anchor.height;
    if (anchor.width !== anchors[0].width || anchor.height !== anchors[0].height)
      throw new Error("所有研究纹理必须使用相同UV栅格尺寸。");
    if (anchor.kind === "original_source") {
      if (sourceLabel === null || anchor.age !== sourceLabel)
        throw new Error("原始源锚点必须匹配已知研究源龄，未知源龄不能补默认值。");
      originalCount++;
    }
    const key = `${anchor.age}:${anchor.kind}`;
    if (seen.has(key)) throw new Error("同龄重复锚点仅允许原始源覆盖SAM条件图。");
    seen.add(key);
    const previous = selected.get(anchor.age);
    if (!previous || anchor.kind === "original_source")
      selected.set(anchor.age, Object.freeze({ ...anchor }));
  }
  if (sourceLabel !== null && originalCount !== 1)
    throw new Error("已知研究源龄必须具有唯一原始源纹理锚点。");
  return Object.freeze({
    kind: "research-display-timeline",
    anchors: Object.freeze([...selected.values()].sort((a, b) => a.age - b.age)),
    sourceLabel,
    width: anchors[0].width,
    height: anchors[0].height,
  });
}

const linear = (value: number): number =>
  value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;

const srgb = (value: number): number =>
  value <= 0.0031308 ? value * 12.92 : 1.055 * value ** (1 / 2.4) - 0.055;

/** Match NumPy rint: ties go to the even integer, unlike Math.round. */
function byte(value: number): number {
  const scaled = Math.max(0, Math.min(1, value)) * 255;
  const floor = Math.floor(scaled), fraction = scaled - floor;
  return fraction === 0.5 ? floor + (floor % 2) : Math.floor(scaled + 0.5);
}

export function sampleResearchTexture(
  timeline: ResearchTimeline,
  targetAge: number,
): ResearchTextureFrame {
  age(targetAge);
  if (!timeline || timeline.kind !== "research-display-timeline" || !timeline.anchors.length)
    throw new Error("必须先建立研究纹理时间线。");
  const anchors = timeline.anchors;
  if (targetAge < anchors[0].age || targetAge > anchors[anchors.length - 1].age)
    throw new Error("研究显示不能超出已有年龄锚点外推。");
  const right = anchors.findIndex((anchor) => anchor.age >= targetAge);
  const upper = anchors[right];
  const lower = upper.age === targetAge ? upper : anchors[right - 1];
  validateAnchor(lower);
  if (upper !== lower) validateAnchor(upper);
  const exactSource = upper.age === targetAge && upper.kind === "original_source";
  let rgba: Uint8ClampedArray;
  if (exactSource) rgba = upper.rgba;
  else if (upper === lower) rgba = new Uint8ClampedArray(upper.rgba);
  else {
    rgba = new Uint8ClampedArray(lower.rgba.length);
    const weight = (targetAge - lower.age) / (upper.age - lower.age);
    for (let offset = 0; offset < rgba.length; offset += 4) {
      const a = lower.rgba[offset + 3] / 255, b = upper.rgba[offset + 3] / 255;
      const alpha = (1 - weight) * a + weight * b;
      const encodedAlpha = byte(alpha);
      if (encodedAlpha === 0) continue;
      rgba[offset + 3] = encodedAlpha;
      for (let channel = 0; channel < 3; channel++) {
        const premultiplied = (1 - weight) * a * linear(lower.rgba[offset + channel] / 255)
          + weight * b * linear(upper.rgba[offset + channel] / 255);
        rgba[offset + channel] = byte(srgb(Math.max(0, Math.min(1, premultiplied / alpha))));
      }
    }
  }
  return {
    kind: "research-display-only", width: timeline.width, height: timeline.height,
    rgba, targetAge, sourceLabel: timeline.sourceLabel, exactSource,
  };
}
