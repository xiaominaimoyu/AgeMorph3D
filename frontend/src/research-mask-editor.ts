/** Native-pixel research masks. Drafts never register a target or approve quality. */
export const MASK_EDITOR_PROTOCOL = "agemorph3d-mask-editor-v1";
export interface MaskEditorStage {
  stage_id: string;
  source_fingerprint: string;
  target_condition: number;
  generated_sha256: string;
  fit_sha256: string;
}
export interface MaskEditorBinding {
  schema_version: 1;
  protocol_id: typeof MASK_EDITOR_PROTOCOL;
  stage: MaskEditorStage;
  width: 1024;
  height: 1024;
  research_only: true;
}
export interface MaskPoint { x: number; y: number }
export interface MaskPolygon { kind: "allowed" | "occluded"; points: MaskPoint[] }
export interface MaskReviewer {
  reviewer: string;
  reviewer_kind: "ai" | "human";
  method: string;
  version: string;
}
export interface RasterizedMasks {
  allowed: Uint8Array;
  occluded: Uint8Array;
  allowedCount: number;
  occludedCount: number;
  unknownCount: number;
}

const SIZE = 1024;
const MAX_PNG = 4 * 1024 ** 2;
const EPSILON = 1e-9;
const SHA = /^[0-9a-f]{64}$/;
const ID = /^[0-9a-f]{32}$/;
const encoder = new TextEncoder();
const signature = new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]);
const COORDINATE_RULE = "native-top-left-pixel-centers-even-odd-edge-cross-1e-9-occlusion-priority-v1";
const CLOSED = Object.freeze({ research_only: true, human_review_completed: false,
  identity_quality_accepted: false, age_quality_accepted: false, visual_seam_quality_accepted: false,
  years_calibrated: false, service_ready: false, production_enabled: false, g3_complete: false });

function fail(message: string): never { throw new Error(`研究遮罩编辑：${message}`); }
function exact(value: unknown, keys: string[]): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)
    || Object.keys(value).sort().join("\0") !== [...keys].sort().join("\0"))
    fail("对象字段不符合冻结协议。");
  return value as Record<string, unknown>;
}
function dimensions(width: number, height: number): void {
  if (!Number.isSafeInteger(width) || !Number.isSafeInteger(height)
    || width < 1 || height < 1 || width > SIZE || height > SIZE)
    fail("尺寸必须是1—1024之间的整数。");
}
function hash(value: unknown): string {
  if (typeof value !== "string" || !SHA.test(value)) fail("指纹必须是64位小写十六进制。");
  return value;
}
function stage(value: unknown): MaskEditorStage {
  const item = exact(value, ["stage_id", "source_fingerprint", "target_condition", "generated_sha256", "fit_sha256"]);
  if (typeof item.stage_id !== "string" || !ID.test(item.stage_id)
    || !Number.isSafeInteger(item.target_condition) || (item.target_condition as number) < 20
    || (item.target_condition as number) > 70) fail("阶段标识或整数条件无效。");
  return { stage_id: item.stage_id, source_fingerprint: hash(item.source_fingerprint),
    target_condition: item.target_condition as number, generated_sha256: hash(item.generated_sha256),
    fit_sha256: hash(item.fit_sha256) };
}
function binding(value: unknown): MaskEditorBinding {
  const item = exact(value, ["schema_version", "protocol_id", "stage", "width", "height", "research_only"]);
  if (item.schema_version !== 1 || item.protocol_id !== MASK_EDITOR_PROTOCOL
    || item.width !== SIZE || item.height !== SIZE || item.research_only !== true)
    fail("绑定版本、尺寸或研究标志无效。");
  return { schema_version: 1, protocol_id: MASK_EDITOR_PROTOCOL, stage: stage(item.stage),
    width: SIZE, height: SIZE, research_only: true };
}

export function createMaskEditorBinding(value: MaskEditorStage): MaskEditorBinding {
  return { schema_version: 1, protocol_id: MASK_EDITOR_PROTOCOL, stage: stage(value),
    width: SIZE, height: SIZE, research_only: true };
}

export function parseMaskEditorBinding(text: string): MaskEditorBinding {
  if (typeof text !== "string" || text.length > 16384 || encoder.encode(text).length > 16384)
    fail("绑定JSON不得超过16KiB。");
  let parsed: unknown;
  try { parsed = JSON.parse(text); } catch { fail("绑定JSON无法解析。"); }
  // JSON.parse alone loses repeated keys. Tokenize only after syntax validation.
  const stack: (Set<string> | null)[] = [];
  const tokens = /"(?:\\.|[^"\\])*"|[{}\[\]]/g;
  for (const match of text.matchAll(tokens)) {
    const token = match[0];
    if (token === "{") stack.push(new Set());
    else if (token === "[") stack.push(null);
    else if (token === "}" || token === "]") stack.pop();
    else if (/^\s*:/.test(text.slice(match.index! + token.length))) {
      const keys = stack[stack.length - 1];
      const key = JSON.parse(token) as string;
      if (!keys || keys.has(key)) fail("绑定JSON含重复字段。");
      keys.add(key);
    }
  }
  return binding(parsed);
}

const crcTable = Uint32Array.from({ length: 256 }, (_, value) => {
  let crc = value;
  for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
  return crc >>> 0;
});
function crc32(bytes: Uint8Array): number {
  let crc = 0xffffffff;
  for (const byte of bytes) crc = (crc >>> 8) ^ crcTable[(crc ^ byte) & 255];
  return (crc ^ 0xffffffff) >>> 0;
}
function chunk(type: string, data: Uint8Array): Uint8Array {
  const answer = new Uint8Array(data.length + 12), view = new DataView(answer.buffer);
  view.setUint32(0, data.length); answer.set(encoder.encode(type), 4); answer.set(data, 8);
  view.setUint32(answer.length - 4, crc32(answer.subarray(4, answer.length - 4)));
  return answer;
}
function pngFrame(png: Uint8Array, width: number, height: number, grayscale: boolean): {
  compressed: Uint8Array; channels: number;
} {
  if (!(png instanceof Uint8Array) || png.length < 57 || png.length > MAX_PNG
    || !signature.every((value, index) => value === png[index])) fail("PNG为空、过大或签名无效。");
  const view = new DataView(png.buffer, png.byteOffset, png.byteLength);
  const compressed = new Uint8Array(png.length);
  let offset = 8, bytes = 0, channels = 0, ended = false, sawData = false, closedData = false;
  while (offset < png.length) {
    if (offset + 12 > png.length) fail("PNG块截断。");
    const length = view.getUint32(offset), end = offset + 12 + length;
    if (end > png.length) fail("PNG块越界。");
    const type = String.fromCharCode(...png.subarray(offset + 4, offset + 8));
    if (!/^[A-Za-z]{4}$/.test(type) || view.getUint32(end - 4) !== crc32(png.subarray(offset + 4, end - 4)))
      fail("PNG块校验失败。");
    if (type === "IHDR" && offset === 8 && length === 13) {
      const color = png[offset + 17];
      if (view.getUint32(offset + 8) !== width || view.getUint32(offset + 12) !== height
        || png[offset + 16] !== 8 || png[offset + 18] || png[offset + 19] || png[offset + 20]
        || (grayscale ? color !== 0 : color !== 2 && color !== 6)) fail("PNG原生尺寸或8位颜色格式无效。");
      channels = color === 0 ? 1 : color === 2 ? 3 : 4;
    } else if (type === "IDAT" && channels && !closedData) {
      compressed.set(png.subarray(offset + 8, end - 4), bytes); bytes += length; sawData = true;
    } else if (type === "IEND" && channels && sawData && length === 0 && end === png.length) {
      ended = true;
    } else if (!grayscale && channels && (type.charCodeAt(0) & 32) && !ended) {
      if (sawData) closedData = true;
    } else fail("PNG块类型或顺序无效。");
    offset = end;
  }
  if (!ended || !bytes) fail("PNG缺少图像数据或结束块。");
  return { compressed: compressed.subarray(0, bytes), channels };
}
async function inflate(bytes: Uint8Array, expected: number): Promise<Uint8Array> {
  const reader = new Blob([new Uint8Array(bytes)]).stream()
    .pipeThrough(new DecompressionStream("deflate")).getReader();
  const answer = new Uint8Array(expected);
  let offset = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      if (value.length > expected - offset) {
        await reader.cancel(); fail("PNG解压数据超出原生尺寸预算。");
      }
      answer.set(value, offset); offset += value.length;
    }
  } finally { reader.releaseLock(); }
  if (offset !== expected) fail("PNG解压长度不符合尺寸。");
  return answer;
}
async function sha256(bytes: Uint8Array): Promise<string> {
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new Uint8Array(bytes))),
    value => value.toString(16).padStart(2, "0")).join("");
}

export async function validateMaskEditorTarget(value: MaskEditorBinding, png: Uint8Array): Promise<void> {
  if (!(png instanceof Uint8Array) || png.length < 57 || png.length > MAX_PNG)
    fail("PNG为空、过大或存储类型无效。");
  const current = binding(value), snapshot = new Uint8Array(png);
  const frame = pngFrame(snapshot, SIZE, SIZE, false);
  const raw = await inflate(frame.compressed, (SIZE * frame.channels + 1) * SIZE);
  for (let row = 0; row < SIZE; row++)
    if (raw[row * (SIZE * frame.channels + 1)] > 4) fail("PNG扫描线过滤器无效。");
  if (await sha256(snapshot) !== current.stage.generated_sha256) fail("目标PNG指纹与当前阶段不匹配。");
}

function cross(a: MaskPoint, b: MaskPoint, p: MaskPoint): number {
  return (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x);
}
function onEdge(a: MaskPoint, b: MaskPoint, p: MaskPoint): boolean {
  return Math.abs(cross(a, b, p)) <= EPSILON
    && p.x >= Math.min(a.x, b.x) && p.x <= Math.max(a.x, b.x)
    && p.y >= Math.min(a.y, b.y) && p.y <= Math.max(a.y, b.y);
}
function intersects(a: MaskPoint, b: MaskPoint, c: MaskPoint, d: MaskPoint): boolean {
  const abC = cross(a, b, c), abD = cross(a, b, d), cdA = cross(c, d, a), cdB = cross(c, d, b);
  const contains = (left: MaskPoint, right: MaskPoint, p: MaskPoint): boolean =>
    cross(left, right, p) === 0 && p.x >= Math.min(left.x, right.x) && p.x <= Math.max(left.x, right.x)
      && p.y >= Math.min(left.y, right.y) && p.y <= Math.max(left.y, right.y);
  return (abC > 0 && abD < 0 || abC < 0 && abD > 0) && (cdA > 0 && cdB < 0 || cdA < 0 && cdB > 0)
    || contains(a, b, c) || contains(a, b, d) || contains(c, d, a) || contains(c, d, b);
}
function polygons(value: readonly MaskPolygon[], width: number, height: number): MaskPolygon[] {
  if (!Array.isArray(value) || value.length > 64) fail("最多允许64个多边形。");
  let total = 0;
  return value.map(raw => {
    const item = exact(raw, ["kind", "points"]);
    if (item.kind !== "allowed" && item.kind !== "occluded" || !Array.isArray(item.points)
      || item.points.length < 3 || item.points.length > 128) fail("多边形类别或顶点数无效。");
    total += item.points.length;
    if (total > 4096) fail("多边形总顶点数超过4096。");
    const points = item.points.map(rawPoint => {
      const point = exact(rawPoint, ["x", "y"]);
      const { x, y } = point;
      if (typeof x !== "number" || typeof y !== "number" || !Number.isFinite(x) || !Number.isFinite(y)
        || x < 0 || y < 0 || x > width || y > height) fail("多边形顶点必须是原生图像范围内的有限坐标。");
      return { x, y };
    });
    const n = points.length;
    if (new Set(points.map(p => `${p.x},${p.y}`)).size !== n) fail("多边形不能包含重复顶点。");
    let area = 0;
    for (let i = 0; i < n; i++) {
      const a = points[i], b = points[(i + 1) % n], c = points[(i + 2) % n];
      // Translate before multiplying: absolute shoelace products can erase a
      // valid subpixel triangle near the image's lower-right corner.
      area += cross(points[0], a, b);
      if (cross(a, b, c) === 0
        && (b.x - a.x) * (c.x - b.x) + (b.y - a.y) * (c.y - b.y) < 0)
        fail("多边形相邻边不能折返重叠。");
      for (let j = i + 1; j < n; j++) {
        if (j === i + 1 || i === 0 && j === n - 1) continue;
        if (intersects(a, b, points[j], points[(j + 1) % n])) fail("多边形不能自交或自接触。");
      }
    }
    if (area === 0) fail("多边形面积不能为零。");
    return { kind: item.kind, points };
  });
}

function fillRange(target: Uint8Array, row: number, width: number, left: number, right: number): void {
  const start = Math.max(0, Math.ceil(left - 0.5)), end = Math.min(width - 1, Math.floor(right - 0.5));
  if (start <= end) target.fill(255, row * width + start, row * width + end + 1);
}
function rasterPolygon(target: Uint8Array, points: MaskPoint[], width: number, height: number): void {
  const first = Math.max(0, Math.ceil(Math.min(...points.map(p => p.y)) - 0.5));
  const last = Math.min(height - 1, Math.floor(Math.max(...points.map(p => p.y)) - 0.5));
  for (let row = first; row <= last; row++) {
    const y = row + 0.5, crossings: number[] = [];
    for (let i = 0; i < points.length; i++) {
      const a = points[i], b = points[(i + 1) % points.length], dy = b.y - a.y;
      if ((a.y > y) !== (b.y > y)) crossings.push(a.x + (y - a.y) * (b.x - a.x) / dy);
      if (y < Math.min(a.y, b.y) || y > Math.max(a.y, b.y)) continue;
      if (!dy) {
        if (Math.abs((b.x - a.x) * (y - a.y)) <= EPSILON)
          fillRange(target, row, width, Math.min(a.x, b.x), Math.max(a.x, b.x));
      } else {
        const x = a.x + (y - a.y) * (b.x - a.x) / dy, margin = EPSILON / Math.abs(dy);
        // Candidate scanline centers are checked against the exact edge predicate.
        const left = Math.max(0, Math.ceil(Math.max(Math.min(a.x, b.x), x - margin) - 0.5) - 1);
        const right = Math.min(width - 1, Math.floor(Math.min(Math.max(a.x, b.x), x + margin) - 0.5) + 1);
        for (let column = left; column <= right; column++)
          if (onEdge(a, b, { x: column + 0.5, y })) target[row * width + column] = 255;
      }
    }
    crossings.sort((a, b) => a - b);
    for (let i = 0; i + 1 < crossings.length; i += 2)
      fillRange(target, row, width, crossings[i], crossings[i + 1]);
  }
}

export function rasterizeMaskPolygons(value: readonly MaskPolygon[], width = SIZE, height = SIZE): RasterizedMasks {
  dimensions(width, height);
  const snapshot = polygons(value, width, height);
  const allowed = new Uint8Array(width * height), occluded = new Uint8Array(width * height);
  for (const polygon of snapshot)
    rasterPolygon(polygon.kind === "allowed" ? allowed : occluded, polygon.points, width, height);
  let allowedCount = 0, occludedCount = 0;
  for (let i = 0; i < allowed.length; i++) {
    if (occluded[i]) { allowed[i] = 0; occludedCount++; }
    else if (allowed[i]) allowedCount++;
  }
  return { allowed, occluded, allowedCount, occludedCount,
    unknownCount: width * height - allowedCount - occludedCount };
}

/** Decode only bounded binary L8 masks; never use Canvas color conversion. */
export async function decodeMaskPng(png: Uint8Array, width = SIZE, height = SIZE): Promise<Uint8Array> {
  dimensions(width, height);
  if (!(png instanceof Uint8Array) || png.length < 57 || png.length > MAX_PNG)
    fail("遮罩PNG为空、过大或存储类型无效。");
  const frame = pngFrame(new Uint8Array(png), width, height, true);
  const rows = await inflate(frame.compressed, (width + 1) * height);
  const pixels = new Uint8Array(width * height);
  for (let row = 0; row < height; row++) {
    const filter = rows[row * (width + 1)];
    if (filter > 4) fail("遮罩PNG扫描线过滤器无效。");
    for (let column = 0; column < width; column++) {
      const index = row * width + column;
      const left = column ? pixels[index - 1] : 0;
      const up = row ? pixels[index - width] : 0;
      const corner = row && column ? pixels[index - width - 1] : 0;
      const prediction = left + up - corner;
      const dl = Math.abs(prediction - left), du = Math.abs(prediction - up), dc = Math.abs(prediction - corner);
      const paeth = dl <= du && dl <= dc ? left : du <= dc ? up : corner;
      const value = (rows[row * (width + 1) + column + 1]
        + (filter === 1 ? left : filter === 2 ? up : filter === 3 ? Math.floor((left + up) / 2)
          : filter === 4 ? paeth : 0)) & 255;
      if (value !== 0 && value !== 255) fail("遮罩PNG像素必须为0或255。");
      pixels[index] = value;
    }
  }
  return pixels;
}

export async function encodeMaskPng(pixels: Uint8Array, width: number, height: number): Promise<Uint8Array> {
  dimensions(width, height);
  if (!(pixels instanceof Uint8Array) || pixels.length !== width * height
    || pixels.some(value => value !== 0 && value !== 255)) fail("遮罩必须是尺寸匹配的0/255字节栅格。");
  const scanlines = new Uint8Array((width + 1) * height);
  for (let row = 0; row < height; row++)
    scanlines.set(pixels.subarray(row * width, (row + 1) * width), row * (width + 1) + 1);
  const stream = new CompressionStream("deflate");
  const compressed = new Response(stream.readable).arrayBuffer(), writer = stream.writable.getWriter();
  await writer.write(scanlines); await writer.close();
  const header = new Uint8Array(13), view = new DataView(header.buffer);
  view.setUint32(0, width); view.setUint32(4, height); header.set([8, 0, 0, 0, 0], 8);
  const parts = [chunk("IHDR", header), chunk("IDAT", new Uint8Array(await compressed)), chunk("IEND", new Uint8Array())];
  const answer = new Uint8Array(8 + parts.reduce((sum, part) => sum + part.length, 0));
  answer.set(signature); let offset = 8;
  for (const part of parts) { answer.set(part, offset); offset += part.length; }
  const frame = pngFrame(answer, width, height, true);
  const readback = await inflate(frame.compressed, scanlines.length);
  if (readback.some((value, index) => value !== scanlines[index])) fail("遮罩PNG回读与原始栅格不一致。");
  return answer;
}

function reviewer(value: MaskReviewer): MaskReviewer {
  const item = exact(value, ["reviewer", "reviewer_kind", "method", "version"]);
  if (item.reviewer_kind !== "ai" && item.reviewer_kind !== "human") fail("必须明确选择记录来源。");
  function field(name: string, maximum: number): string {
    const text = item[name];
    if (typeof text !== "string" || !text.trim() || text.length > maximum || /[\x00-\x1f\x7f]/.test(text))
      fail("审核者、方法和版本必须是有界非空文字。");
    return text.trim();
  }
  return { reviewer: field("reviewer", 128), reviewer_kind: item.reviewer_kind,
    method: field("method", 256), version: field("version", 64) };
}

export async function exportMaskDraft(
  value: MaskEditorBinding, png: Uint8Array, valuePolygons: readonly MaskPolygon[], valueReviewer: MaskReviewer,
): Promise<{ allowedPng: Uint8Array; occludedPng: Uint8Array; draft: Record<string, unknown> }> {
  // Snapshot all caller-owned data before the first await.
  const current = binding(value), snapshot = polygons(valuePolygons, SIZE, SIZE), review = reviewer(valueReviewer);
  if (!(png instanceof Uint8Array) || png.length > MAX_PNG) fail("目标PNG超出预算。");
  const target = new Uint8Array(png), masks = rasterizeMaskPolygons(snapshot);
  if (!masks.allowedCount) fail("至少需要一个明确允许的像素，不能导出空允许区。");
  if (masks.allowedCount === SIZE * SIZE) fail("不能导出整张图全部放行的遮罩。");
  await validateMaskEditorTarget(current, target);
  const [allowedPng, occludedPng] = await Promise.all([
    encodeMaskPng(masks.allowed, SIZE, SIZE), encodeMaskPng(masks.occluded, SIZE, SIZE),
  ]);
  const [allowedSha, occludedSha] = await Promise.all([sha256(allowedPng), sha256(occludedPng)]);
  return { allowedPng, occludedPng, draft: { schema_version: 1, protocol_id: MASK_EDITOR_PROTOCOL,
    status: "draft_unsubmitted", binding: current, coordinate_rule: COORDINATE_RULE,
    polygons: snapshot, review,
    masks: { allowed: { sha256: allowedSha, bytes: allowedPng.length, pixels: masks.allowedCount },
      occluded: { sha256: occludedSha, bytes: occludedPng.length, pixels: masks.occludedCount } },
    pixel_counts: { allowed: masks.allowedCount, occluded: masks.occludedCount, unknown: masks.unknownCount },
    ...CLOSED } };
}
