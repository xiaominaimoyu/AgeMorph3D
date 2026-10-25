/** Explicit local research API and fixed-source asset validation.
 * No production capability is granted and unknown source ages remain unknown.
 */
import type { SourceAge } from "./contracts";

type JsonObject = Record<string, unknown>;
export type GeometryKey = "POSITION" | "NORMAL" | "TEXCOORD_0" | "indices";
export interface ResearchFlags {
  research_only: true;
  service_ready: false;
  production_enabled: false;
  g3_complete: false;
  age_quality_accepted: false;
  identity_quality_accepted: false;
  visual_seam_quality_accepted: false;
  years_calibrated: false;
  human_review_completed: false;
}
export interface SessionInfo extends ResearchFlags {
  session_id: string;
  source_age: SourceAge;
  source_fingerprint: string;
  shape: number[];
  source_glb_url: string;
  source_texture_url: string;
}
export interface StagedTarget {
  stage_id: string;
  source_fingerprint: string;
  target_condition: number;
  generated_sha256: string;
  fit_sha256: string;
}
export interface StageReply {
  staged: StagedTarget;
  preview_url: string;
  fit_url: string;
}
export interface ReviewInput {
  allowed: Blob;
  occluded: Blob;
  reviewer: string;
  reviewer_kind: "ai" | "human";
  method: string;
  version: string;
}
export interface RegisteredReply {
  session_id: string;
  condition: number;
  kind: "sam_registered_uv";
  source_age: SourceAge;
  shape: number[];
  provenance: JsonObject;
  provenance_json_b64: string;
  provenanceBytes: ArrayBuffer;
  mesh_url: string;
  texture_url: string;
}
export interface ResearchHealth {
  research_only: true;
  service_ready: false;
  production_enabled: false;
  g3_complete: false;
  service: JsonObject;
  capabilities: { reconstruction: false; age_morph: false; age_texture: false; realtime: false };
}
interface LoadedAsset {
  info: SessionInfo;
  glbBytes: ArrayBuffer;
  textureBytes: ArrayBuffer;
  topologyId: string;
  geometryHashes: Readonly<Record<GeometryKey, string>>;
  coordinateMetadata: JsonObject;
}
export interface LoadedSource extends LoadedAsset { kind: "original_source" }
export interface LoadedCondition extends LoadedAsset { kind: "sam_condition"; condition: number; provenance: JsonObject }

const ID = /^[0-9a-f]{32}$/;
const SHA = /^[0-9a-f]{64}$/;
const TOPOLOGY = /^tddfa-bfm-canon-v1-[0-9a-f]{64}$/;
const JSON_LIMIT = 16 * 1024;
const REGISTER_LIMIT = 256 * 1024;
const GLB_LIMIT = 64 * 1024 ** 2;
const PNG_LIMIT = 4 * 1024 ** 2;
const FIT_LIMIT = 16 * 1024 ** 2;
const IMAGE_LIMIT = 10 * 1024 ** 2;
const KEYS: readonly GeometryKey[] = ["POSITION", "NORMAL", "TEXCOORD_0", "indices"];
const CLOSED: ResearchFlags = Object.freeze({ research_only: true, service_ready: false,
  production_enabled: false, g3_complete: false, age_quality_accepted: false,
  identity_quality_accepted: false, visual_seam_quality_accepted: false,
  years_calibrated: false, human_review_completed: false });
const utf8 = new TextDecoder("utf-8", { fatal: true });

function invalid(message = "研究服务返回的数据或资产不符合本机会话协议。"): never {
  throw new Error(message);
}
function object(value: unknown): JsonObject {
  if (value === null || typeof value !== "object" || Array.isArray(value)) invalid();
  return value as JsonObject;
}
function list(value: unknown, length?: number): unknown[] {
  if (!Array.isArray(value) || length !== undefined && value.length !== length) invalid();
  return value;
}
function integer(value: unknown, minimum: number, maximum: number): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < minimum || value > maximum) invalid();
  return value;
}
function age(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 20 || value > 70) invalid("年龄必须是20—70之间的有限数值。");
  return value;
}
function condition(value: unknown): number { return integer(value, 20, 70); }
function text(value: unknown, maximum = 256): string {
  if (typeof value !== "string" || !value.trim() || value.length > maximum) invalid();
  return value;
}
function identifier(value: unknown): string {
  const id = text(value, 32);
  if (!ID.test(id)) invalid("研究会话或阶段标识格式无效。");
  return id;
}
function digest(value: unknown): string {
  const result = text(value, 64);
  if (!SHA.test(result)) invalid();
  return result;
}
function coefficients(value: unknown): number[] {
  const values = list(value, 40);
  return values.map(item => {
    if (typeof item !== "number" || !Number.isFinite(item) || Math.abs(item) > 1e6) invalid();
    return item;
  });
}
function sourceAge(value: unknown): SourceAge {
  const data = object(value);
  if (Object.keys(data).sort().join() !== "calibration_id,method,value") invalid();
  if (data.method === "unknown") {
    if (data.value !== null || data.calibration_id !== null) invalid();
    return { value: null, method: "unknown", calibration_id: null };
  }
  if (data.method !== "user" && data.method !== "estimated") invalid();
  const result = age(data.value);
  const calibration = data.method === "estimated" ? text(data.calibration_id, 100) : null;
  if (data.method === "user" && data.calibration_id !== null) invalid();
  if (calibration !== null && !/^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$/.test(calibration)) invalid();
  return { value: result, method: data.method, calibration_id: calibration };
}
function equal(a: unknown, b: unknown): boolean { return canonical(a) === canonical(b); }
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object")
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical((value as JsonObject)[key])}`).join(",")}}`;
  return JSON.stringify(value);
}
function flags(value: JsonObject, required = true): void {
  if (required && Object.entries(CLOSED).some(([key, expected]) => value[key] !== expected)) invalid("本客户端只接受关闭生产资格的研究会话。");
  for (const [key, item] of Object.entries(value)) {
    if ((key.endsWith("_accepted") || key === "years_calibrated" || key === "human_review_completed" || key === "production_enabled" || key === "service_ready" || key === "g3_complete") && item !== false) invalid("研究响应不能授予生产或质量资格。");
  }
}

/** Bounded JSON with duplicate-key and nonfinite-number rejection. */
function parseJson(data: ArrayBuffer, rootValues?: Map<string, ArrayBuffer>): unknown {
  const input = utf8.decode(data);
  let cursor = 0;
  const white = () => { while (/[ \t\r\n]/.test(input[cursor] ?? "") && cursor < input.length) cursor++; };
  const string = (): string => {
    if (input[cursor] !== '"') invalid();
    const start = cursor++;
    while (cursor < input.length) {
      const c = input[cursor++];
      if (c === '"') return JSON.parse(input.slice(start, cursor)) as string;
      if (c === "\\") cursor++;
    }
    return invalid();
  };
  const value = (depth: number): unknown => {
    if (depth > 64) invalid();
    white();
    const c = input[cursor];
    if (c === '"') return string();
    if (c === "{") {
      cursor++; white();
      const result: JsonObject = Object.create(null);
      if (input[cursor] === "}") { cursor++; return result; }
      while (true) {
        white(); const key = string(); white();
        if (Object.hasOwn(result, key) || input[cursor++] !== ":") invalid("JSON包含重复或无效字段。");
        const begin = cursor;
        result[key] = value(depth + 1);
        if (depth === 0 && rootValues) rootValues.set(key, new TextEncoder().encode(input.slice(begin, cursor).trimStart()).buffer);
        white();
        if (input[cursor] === "}") { cursor++; return result; }
        if (input[cursor++] !== ",") invalid();
      }
    }
    if (c === "[") {
      cursor++; white(); const result: unknown[] = [];
      if (input[cursor] === "]") { cursor++; return result; }
      while (true) {
        result.push(value(depth + 1)); white();
        if (input[cursor] === "]") { cursor++; return result; }
        if (input[cursor++] !== ",") invalid();
      }
    }
    for (const [token, result] of [["true", true], ["false", false], ["null", null]] as const) {
      if (input.startsWith(token, cursor)) { cursor += token.length; return result; }
    }
    const match = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/.exec(input.slice(cursor));
    if (!match) invalid();
    cursor += match[0].length;
    const number = Number(match[0]);
    if (!Number.isFinite(number)) invalid();
    return number;
  };
  const result = value(0); white();
  if (cursor !== input.length) invalid();
  return result;
}

export async function researchSha256(data: ArrayBuffer | Uint8Array): Promise<string> {
  const bytes = data instanceof Uint8Array ? new Uint8Array(data) : data.slice(0);
  return [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map(v => v.toString(16).padStart(2, "0")).join("");
}
function sameBytes(a: Uint8Array, b: Uint8Array): boolean {
  return a.length === b.length && a.every((value, index) => value === b[index]);
}
const crcTable = Array.from({ length: 256 }, (_, n) => {
  for (let i = 0; i < 8; i++) n = n & 1 ? 0xedb88320 ^ (n >>> 1) : n >>> 1;
  return n >>> 0;
});
function png(bytes: ArrayBuffer, width: number, height: number, color: number): void {
  const data = new Uint8Array(bytes), view = new DataView(bytes);
  if (bytes.byteLength < 57 || bytes.byteLength > PNG_LIMIT || !sameBytes(data.subarray(0, 8), new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]))) invalid("纹理不是有界PNG。");
  let offset = 8, seenData = false, ended = false;
  while (offset < data.length) {
    if (offset + 12 > data.length) invalid();
    const length = view.getUint32(offset), end = offset + 12 + length;
    if (end > data.length) invalid();
    const kind = String.fromCharCode(...data.subarray(offset + 4, offset + 8));
    let crc = 0xffffffff;
    for (let i = offset + 4; i < offset + 8 + length; i++) crc = crcTable[(crc ^ data[i]) & 255] ^ (crc >>> 8);
    if (((crc ^ 0xffffffff) >>> 0) !== view.getUint32(offset + 8 + length)) invalid("PNG校验失败。");
    if (offset === 8) {
      if (kind !== "IHDR" || length !== 13 || view.getUint32(16) !== width || view.getUint32(20) !== height || data[24] !== 8 || data[25] !== color || data[26] || data[27] || data[28]) invalid("PNG像素尺寸或编码与研究协议不符。");
    } else if (kind === "IDAT") seenData = true;
    else if (kind === "IEND") {
      if (length !== 0 || !seenData || end !== data.length) invalid();
      ended = true;
    } else invalid("研究PNG包含不支持的附加数据。");
    offset = end;
  }
  if (!ended) invalid();
}

interface ParsedGlb {
  topologyId: string;
  coordinates: JsonObject;
  extras: JsonObject;
  geometryHashes: Record<GeometryKey, string>;
}
async function inspectGlb(bytes: ArrayBuffer, texture: ArrayBuffer, info: SessionInfo): Promise<ParsedGlb> {
  const data = new Uint8Array(bytes), view = new DataView(bytes);
  if (bytes.byteLength < 28 || bytes.byteLength > GLB_LIMIT || view.getUint32(0, true) !== 0x46546c67 || view.getUint32(4, true) !== 2 || view.getUint32(8, true) !== data.length) invalid("GLB头或长度无效。");
  const jsonLength = view.getUint32(12, true), binaryHeader = 20 + jsonLength;
  if (jsonLength > JSON_LIMIT || jsonLength % 4 || binaryHeader + 8 > data.length || view.getUint32(16, true) !== 0x4e4f534a || view.getUint32(binaryHeader + 4, true) !== 0x004e4942) invalid();
  const binaryLength = view.getUint32(binaryHeader, true), start = binaryHeader + 8;
  if (binaryLength % 4 || start + binaryLength !== data.length) invalid();
  const doc = object(parseJson(bytes.slice(20, binaryHeader))), bin = data.subarray(start);
  if (object(doc.asset).version !== "2.0" || doc.extensionsRequired !== undefined || doc.extensionsUsed !== undefined || doc.skins !== undefined || doc.animations !== undefined) invalid();
  if (integer(doc.scene, 0, 0) !== 0) invalid();
  const scene = object(list(doc.scenes, 1)[0]), node = object(list(doc.nodes, 1)[0]);
  if (!equal(scene.nodes, [0]) || node.mesh !== 0 || ["matrix", "translation", "rotation", "scale", "skin", "children"].some(key => key in node)) invalid("研究资产必须保留共同的原始源坐标。");
  const extras = object(doc.extras);
  if (!equal(scene.extras, extras) || extras.asset_mode !== "static" || !equal(sourceAge(extras.source_age), info.source_age)) invalid("GLB源龄或资产模式与会话不符。");
  const topologyId = text(extras.topology_id, 100);
  if (!TOPOLOGY.test(topologyId)) invalid();
  const coordinates = object(extras.coordinate_metadata);
  if (coordinates.version !== "agemorph3d-static-canonical-v1" || coordinates.source_coordinate_system !== "bfm_model_raw" || coordinates.normalization !== "source_bbox_height_to_one" || coordinates.vertex_order_preserved !== true || coordinates.face_order_preserved !== true || coordinates.metric_scale_verified !== false || coordinates.source_topology_sha256 !== topologyId.slice("tddfa-bfm-canon-v1-".length)) invalid("原始源框或有序拓扑声明无效。");
  const finiteArray = (value: unknown, count: number): number[] => list(value, count).map(item => {
    if (typeof item !== "number" || !Number.isFinite(item)) invalid();
    return item;
  });
  finiteArray(coordinates.source_center, 3);
  finiteArray(coordinates.source_projection_row_major, 12);
  const roi = finiteArray(coordinates.source_roi, 4);
  if (roi[2] <= roi[0] || roi[3] <= roi[1] || !equal(coordinates.axis_rotation_row_major, [1, 0, 0, 0, 1, 0, 0, 0, 1]) || typeof coordinates.source_bbox_height !== "number" || !Number.isFinite(coordinates.source_bbox_height) || coordinates.source_bbox_height <= 0 || typeof coordinates.source_to_canonical_uniform_scale !== "number" || !Number.isFinite(coordinates.source_to_canonical_uniform_scale) || coordinates.source_to_canonical_uniform_scale <= 0) invalid();
  const buffer = object(list(doc.buffers, 1)[0]);
  if ("uri" in buffer || integer(buffer.byteLength, 1, GLB_LIMIT) !== bin.length) invalid();
  const mesh = object(list(doc.meshes, 1)[0]), primitive = object(list(mesh.primitives, 1)[0]);
  if (primitive.mode !== 4 || primitive.material !== 0 || primitive.targets !== undefined || mesh.weights !== undefined) invalid();
  const attributes = object(primitive.attributes);
  if (Object.keys(attributes).sort().join() !== "NORMAL,POSITION,TEXCOORD_0") invalid();
  const accessors = list(doc.accessors, 4), views = list(doc.bufferViews, 5);
  let contiguous = 0;
  for (const item of views) {
    const buffer = object(item);
    if (buffer.buffer !== 0 || (buffer.byteOffset ?? 0) !== contiguous) invalid();
    contiguous += integer(buffer.byteLength, 1, bin.length);
  }
  if (contiguous > bin.length || bin.length - contiguous > 3 || bin.subarray(contiguous).some(value => value !== 0)) invalid();
  const bufferView = (index: unknown): Uint8Array => {
    const item = object(views[integer(index, 0, views.length - 1)]);
    if (item.buffer !== 0 || item.byteStride !== undefined || item.extensions !== undefined) invalid();
    const begin = item.byteOffset === undefined ? 0 : integer(item.byteOffset, 0, bin.length);
    const length = integer(item.byteLength, 1, bin.length);
    if (begin + length > bin.length) invalid();
    return bin.subarray(begin, begin + length);
  };
  const geometryHashes = {} as Record<GeometryKey, string>;
  let vertices = 0;
  const geometryBytes = new Map<GeometryKey, Uint8Array>();
  for (const key of KEYS) {
    const accessor = object(accessors[integer(key === "indices" ? primitive.indices : attributes[key], 0, 3)]);
    if (accessor.bufferView !== ({ POSITION: 0, NORMAL: 1, indices: 2, TEXCOORD_0: 3 }[key]) || (accessor.byteOffset ?? 0) !== 0) invalid();
    const parts = key === "indices" ? 1 : key === "TEXCOORD_0" ? 2 : 3;
    if (accessor.componentType !== (key === "indices" ? 5125 : 5126) || accessor.type !== (parts === 1 ? "SCALAR" : `VEC${parts}`) || accessor.sparse !== undefined || accessor.normalized === true || accessor.extensions !== undefined) invalid();
    const count = integer(accessor.count, key === "indices" ? 3 : 3, key === "indices" ? 900_000 : 200_000);
    if (key === "POSITION") vertices = count;
    if (key !== "indices" && count !== vertices || key === "indices" && count % 3) invalid();
    const content = bufferView(accessor.bufferView);
    const offset = accessor.byteOffset === undefined ? 0 : integer(accessor.byteOffset, 0, content.length);
    if (offset % 4 || offset + count * parts * 4 !== content.length) invalid();
    const raw = content.subarray(offset, offset + count * parts * 4), numbers = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
    for (let at = 0; at < raw.length; at += 4) {
      const number = key === "indices" ? numbers.getUint32(at, true) : numbers.getFloat32(at, true);
      if (!Number.isFinite(number) || key === "indices" && number >= vertices || key === "TEXCOORD_0" && (number < 0 || number > 1)) invalid("GLB几何数组包含无效数值。");
    }
    geometryHashes[key] = await researchSha256(raw);
    geometryBytes.set(key, raw);
  }
  const indices = geometryBytes.get("indices")!;
  const triangles = new DataView(indices.buffer, indices.byteOffset, indices.byteLength);
  for (let at = 0; at < indices.length; at += 12) {
    const a = triangles.getUint32(at, true), b = triangles.getUint32(at + 4, true), c = triangles.getUint32(at + 8, true);
    if (a === b || a === c || b === c) invalid();
  }
  const image = object(list(doc.images, 1)[0]);
  if ("uri" in image || image.mimeType !== "image/png" || image.bufferView !== 4) invalid();
  if (!sameBytes(bufferView(image.bufferView), new Uint8Array(texture))) invalid("GLB内嵌图集与会话PNG不一致。");
  png(texture, 256, 256, 6);
  const tex = object(list(doc.textures, 1)[0]), material = object(list(doc.materials, 1)[0]);
  if (tex.source !== 0 || tex.sampler !== 0 || material.alphaMode !== "MASK" || material.alphaCutoff !== 0.5) invalid();
  const pbr = object(material.pbrMetallicRoughness), base = object(pbr.baseColorTexture);
  if (base.index !== 0 || base.texCoord !== 0 || !equal(pbr.baseColorFactor, [1, 1, 1, 1])) invalid();
  const sampler = object(list(doc.samplers, 1)[0]);
  if (sampler.magFilter !== 9729 || sampler.minFilter !== 9729 || sampler.wrapS !== 33071 || sampler.wrapT !== 33071) invalid();
  return { topologyId, coordinates, extras, geometryHashes };
}

const ERRORS: Record<string, string> = {
  REVIEW_REQUIRED: "生成目标需要匹配新图和拟合指纹的审核遮罩。",
  SESSION_EXPIRED: "研究会话已过期，请重新建立会话。",
  STAGE_EXPIRED: "生成阶段已过期，请重新请求。",
  RESULT_NOT_FOUND: "该条件尚无已审核注册的资产。",
  RESULT_CONFLICT: "相同条件已有不同审核结果，请新建研究会话。",
  SOURCE_AGE_REQUIRED: "源龄未知，不能请求绝对年龄。",
  INTEGER_AGE_REQUIRED: "直接生成仅接受20—70的整数条件。",
  BUSY: "本机研究资源正忙，请稍后重试。",
  TIMEOUT: "研究请求超时，后台原生工作可能仍在结束。",
  NO_FACE: "没有检测到人脸，请使用清晰的单人照片。",
  MULTI_FACE: "照片中检测到多张人脸，请更换单人照片。",
};
export class ResearchApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly stage?: StageReply;
  constructor(status: number, code: string, stage?: StageReply) {
    super(ERRORS[code] ?? "本机研究请求失败，请检查服务状态和输入。");
    this.name = "ResearchApiError";
    this.status = status; this.code = code; this.stage = stage;
  }
}

function rawProvenance(value: unknown): { encoded: string; bytes: ArrayBuffer; parsed: JsonObject } {
  const encoded = text(value, 4 * Math.ceil(64 * 1024 / 3));
  let decoded: string;
  try { decoded = atob(encoded); } catch { return invalid("原始来源记录base64无效。"); }
  if (decoded.length === 0 || decoded.length > 64 * 1024 || btoa(decoded) !== encoded) invalid();
  const bytes = Uint8Array.from(decoded, ch => ch.charCodeAt(0)).buffer;
  return { encoded, bytes, parsed: object(parseJson(bytes)) };
}

/** Hash the exact native bytes, never a JS reserialization of Python floats. */
export async function verifyRegisteredProvenance(registered: RegisteredReply, loaded: LoadedCondition): Promise<void> {
  if (registered.session_id !== loaded.info.session_id || registered.condition !== loaded.condition || !equal(registered.source_age, loaded.info.source_age) || !equal(registered.shape, loaded.info.shape)) invalid();
  const raw = rawProvenance(registered.provenance_json_b64);
  if (!sameBytes(new Uint8Array(raw.bytes), new Uint8Array(registered.provenanceBytes)) || !equal(raw.parsed, registered.provenance)) invalid();
  const compact = loaded.provenance;
  if (await researchSha256(raw.bytes) !== compact.provenance_sha256) invalid("完整来源记录与GLB指纹不一致。");
  const values = new Map<string, ArrayBuffer>();
  parseJson(raw.bytes, values);
  const generation = values.get("generation");
  if (!generation || await researchSha256(generation) !== object(compact.generation).provenance_sha256) invalid("worker原始来源记录与GLB指纹不一致。");
  const fullGeneration = object(raw.parsed.generation), compactGeneration = object(compact.generation);
  if (fullGeneration.pid !== compactGeneration.pid || fullGeneration.load_count !== compactGeneration.load_count) invalid();
  for (const [key, value] of Object.entries(raw.parsed))
    if (key !== "generation" && !equal(value, compact[key])) invalid("完整与嵌入来源记录字段不一致。");
}

export class ResearchSessionApi {
  readonly baseUrl: string;
  constructor(baseUrl: string) {
    if (typeof baseUrl !== "string" || !/^https?:\/\/(?:localhost|127\.0\.0\.1|\[::1\])(?::[0-9]{1,5})?\/?$/i.test(baseUrl)) invalid("研究服务必须是明确的本机HTTP(S)地址。");
    const url = new URL(baseUrl);
    if (url.port && Number(url.port) < 1) invalid();
    this.baseUrl = url.origin;
  }
  private url(value: unknown, expected: string): string {
    const path = text(value, 2048);
    if (/[\\%?#]/.test(path) || path.startsWith("//") || path.split("/").includes("..")) invalid("研究资产地址不可离开当前会话。");
    const url = new URL(path, this.baseUrl);
    if (url.origin !== this.baseUrl || url.username || url.password || url.pathname !== expected || url.search || url.hash) invalid("研究资产地址不可离开当前会话。");
    return url.href;
  }
  private parseInfo(value: unknown, sid?: string): SessionInfo {
    const data = object(value); flags(data);
    const id = identifier(data.session_id);
    if (sid !== undefined && id !== sid) invalid();
    return { ...CLOSED, session_id: id, source_age: sourceAge(data.source_age), source_fingerprint: digest(data.source_fingerprint),
      shape: coefficients(data.shape), source_glb_url: this.url(data.source_glb_url, `/research/sessions/${id}/source.glb`),
      source_texture_url: this.url(data.source_texture_url, `/research/sessions/${id}/source-texture.png`) };
  }
  private parseStage(value: unknown, sid: string, expected?: number): StageReply {
    const data = object(value), raw = object(data.staged);
    if (data.research_only !== undefined) flags(data);
    const staged: StagedTarget = { stage_id: identifier(raw.stage_id), source_fingerprint: digest(raw.source_fingerprint),
      target_condition: condition(raw.target_condition), generated_sha256: digest(raw.generated_sha256), fit_sha256: digest(raw.fit_sha256) };
    if (expected !== undefined && staged.target_condition !== expected) invalid();
    return { staged, preview_url: this.url(data.preview_url, `/research/sessions/${sid}/stages/${staged.stage_id}/preview.png`),
      fit_url: this.url(data.fit_url, `/research/sessions/${sid}/stages/${staged.stage_id}/fit.json`) };
  }
  private async bytes(url: string, init: RequestInit, limit: number, media: string, signal?: AbortSignal, timeout = 190_000): Promise<ArrayBuffer> {
    const controller = new AbortController();
    let timedOut = false;
    const abort = () => controller.abort();
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) controller.abort();
    const timer = globalThis.setTimeout(() => { timedOut = true; controller.abort(); }, timeout);
    let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
    let fetched: Response | undefined;
    let bodyDone = false;
    try {
      if (controller.signal.aborted) throw new DOMException("请求已取消。", "AbortError");
      const response = await fetch(url, { ...init, signal: controller.signal, credentials: "omit", redirect: "error", cache: "no-store" });
      fetched = response;
      if (response.redirected || response.type === "opaque" || response.url && response.url !== url) invalid("研究请求不能重定向。");
      const responseMedia = response.headers.get("content-type")?.split(";", 1)[0].trim().toLowerCase();
      const budget = response.ok ? limit : JSON_LIMIT;
      if (responseMedia !== (response.ok ? media : "application/json")) invalid("研究响应媒体类型错误。");
      const length = response.headers.get("content-length");
      if (length !== null && (!/^[0-9]+$/.test(length) || Number(length) > budget)) invalid("研究响应超过字节预算。");
      reader = response.body?.getReader();
      if (!reader) invalid("研究响应为空。");
      const chunks: Uint8Array[] = []; let size = 0;
      while (true) {
        const activeReader = reader;
        const part = await new Promise<ReadableStreamReadResult<Uint8Array>>((resolve, reject) => {
          const cancel = () => { void activeReader.cancel().catch(() => {}); reject(new DOMException("请求已取消。", "AbortError")); };
          controller.signal.addEventListener("abort", cancel, { once: true });
          if (controller.signal.aborted) cancel();
          activeReader.read().then(resolve, reject).finally(() => controller.signal.removeEventListener("abort", cancel));
        });
        if (part.done) { bodyDone = true; break; }
        size += part.value.byteLength;
        if (size > budget) invalid("研究响应超过实际字节预算。");
        chunks.push(part.value.slice());
      }
      if (length !== null && Number(length) !== size || size === 0) invalid("研究响应长度不匹配。");
      const joined = new Uint8Array(size); let at = 0;
      for (const chunk of chunks) { joined.set(chunk, at); at += chunk.length; }
      if (!response.ok) {
        const error = object(parseJson(joined.buffer));
        const code = typeof error.code === "string" && /^[A-Z][A-Z0-9_]{0,39}$/.test(error.code) ? error.code : "INTERNAL_ERROR";
        let stage: StageReply | undefined;
        if (code === "REVIEW_REQUIRED" && error.staged !== undefined) {
          const sid = new URL(url).pathname.split("/")[3];
          stage = this.parseStage(error, identifier(sid));
        }
        throw new ResearchApiError(response.status, code, stage);
      }
      return joined.buffer;
    } catch (error) {
      if (timedOut) throw new ResearchApiError(504, "TIMEOUT");
      if (signal?.aborted) throw new DOMException("请求已取消。", "AbortError");
      throw error;
    } finally {
      if (reader) {
        if (!bodyDone) await reader.cancel().catch(() => {});
        reader.releaseLock();
      }
      else if (fetched?.body) await fetched.body.cancel().catch(() => {});
      globalThis.clearTimeout(timer); signal?.removeEventListener("abort", abort);
    }
  }
  private async json(path: string, init: RequestInit = {}, signal?: AbortSignal, limit = JSON_LIMIT): Promise<unknown> {
    return parseJson(await this.bytes(this.url(path, path), init, limit, "application/json", signal));
  }
  async health(signal?: AbortSignal): Promise<ResearchHealth> {
    const data = object(await this.json("/research/health", {}, signal)); flags(data);
    const capabilities = object(data.capabilities);
    if (["reconstruction", "age_morph", "age_texture", "realtime"].some(key => capabilities[key] !== false)) invalid();
    return { research_only: true, service_ready: false, production_enabled: false, g3_complete: false,
      service: object(data.service), capabilities: { reconstruction: false, age_morph: false, age_texture: false, realtime: false } };
  }
  async createSession(image: Blob, sourceAgeText?: string, signal?: AbortSignal): Promise<SessionInfo> {
    if (!(image instanceof Blob) || !image.size || image.size > IMAGE_LIMIT || !["image/jpeg", "image/png", "image/webp"].includes(image.type)) invalid("请提供有界JPEG/PNG/WebP照片。");
    let path = "/research/sessions";
    if (sourceAgeText !== undefined) {
      if (typeof sourceAgeText !== "string" || sourceAgeText.length > 32 || !/^[0-9]+(?:\.[0-9]+)?$/.test(sourceAgeText)) invalid("源龄必须是明确的20—70十进制数值；未知请留空。");
      age(Number(sourceAgeText)); path += `?source_age=${sourceAgeText}`;
    }
    // This is the sole query accepted by the raw-photo endpoint.
    const url = this.baseUrl + path;
    const data = parseJson(await this.bytes(url, { method: "POST", headers: { "Content-Type": image.type }, body: image }, JSON_LIMIT, "application/json", signal));
    const info = this.parseInfo(data);
    if (sourceAgeText === undefined ? info.source_age.method !== "unknown" : info.source_age.method !== "user" || info.source_age.value !== Number(sourceAgeText)) invalid("服务改变了明确输入的源龄来源。");
    return info;
  }
  async sessionInfo(sid: string, signal?: AbortSignal): Promise<SessionInfo> {
    identifier(sid); return this.parseInfo(await this.json(`/research/sessions/${sid}`, {}, signal), sid);
  }
  async stage(sid: string, target: number, signal?: AbortSignal): Promise<StageReply> {
    identifier(sid); condition(target);
    const data = object(await this.json(`/research/sessions/${sid}/conditions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ condition: target }) }, signal));
    flags(data);
    return this.parseStage(data, sid, target);
  }
  async preview(sid: string, stage: StageReply, signal?: AbortSignal): Promise<ArrayBuffer> {
    identifier(sid); const checked = this.parseStage(stage, sid);
    const bytes = await this.bytes(checked.preview_url, {}, PNG_LIMIT, "image/png", signal, 30_000);
    png(bytes, 1024, 1024, 2);
    if (await researchSha256(bytes) !== checked.staged.generated_sha256) invalid("生成PNG与审核阶段指纹不一致。");
    return bytes;
  }
  async fit(sid: string, stage: StageReply, signal?: AbortSignal): Promise<ArrayBuffer> {
    identifier(sid); const checked = this.parseStage(stage, sid);
    const bytes = await this.bytes(checked.fit_url, {}, FIT_LIMIT, "application/json", signal, 30_000);
    if (await researchSha256(bytes) !== checked.staged.fit_sha256) invalid("拟合与审核阶段指纹不一致。");
    return bytes;
  }
  async register(sid: string, stage: StageReply, review: ReviewInput, signal?: AbortSignal): Promise<RegisteredReply> {
    identifier(sid); const checked = this.parseStage(stage, sid);
    if (review.reviewer_kind !== "ai" && review.reviewer_kind !== "human") invalid();
    const encode = async (blob: Blob): Promise<string> => {
      if (!(blob instanceof Blob) || !blob.size || blob.size > PNG_LIMIT || blob.type !== "image/png") invalid("审核遮罩必须为不超过4MiB的PNG。");
      const bytes = new Uint8Array(await blob.arrayBuffer());
      png(bytes.buffer, 1024, 1024, 0);
      let result = "";
      for (let at = 0; at < bytes.length; at += 0x8000) result += String.fromCharCode(...bytes.subarray(at, at + 0x8000));
      return btoa(result);
    };
    const payload = { source_fingerprint: checked.staged.source_fingerprint,
      generated_sha256: checked.staged.generated_sha256, fit_sha256: checked.staged.fit_sha256,
      allowed_png_b64: await encode(review.allowed), occluded_png_b64: await encode(review.occluded),
      reviewer: text(review.reviewer), reviewer_kind: review.reviewer_kind, method: text(review.method), version: text(review.version) };
    const data = object(await this.json(`/research/sessions/${sid}/stages/${checked.staged.stage_id}/reviews`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }, signal, REGISTER_LIMIT));
    flags(data);
    if (data.session_id !== sid || data.kind !== "sam_registered_uv" || data.condition !== checked.staged.target_condition) invalid();
    const provenance = object(data.provenance); flags(provenance);
    const native = rawProvenance(data.provenance_json_b64);
    if (!equal(native.parsed, provenance)) invalid("原始来源记录与响应对象不一致。");
    if (provenance.source_fingerprint !== payload.source_fingerprint || provenance.generated_sha256 !== payload.generated_sha256 || provenance.target_fit_sha256 !== payload.fit_sha256 || provenance.target_condition !== data.condition || provenance.shape_route !== "static_fallback" || provenance.allowed_png_sha256 !== await researchSha256(await review.allowed.arrayBuffer()) || provenance.occluded_png_sha256 !== await researchSha256(await review.occluded.arrayBuffer())) invalid("审核注册来源与当前目标不一致。");
    const source_age = sourceAge(data.source_age);
    if (!equal(source_age, sourceAge(provenance.source_age))) invalid();
    return { session_id: sid, condition: condition(data.condition), kind: "sam_registered_uv", source_age,
      shape: coefficients(data.shape), provenance, provenance_json_b64: native.encoded, provenanceBytes: native.bytes,
      mesh_url: this.url(data.mesh_url, `/research/sessions/${sid}/conditions/${data.condition}/mesh.glb`),
      texture_url: this.url(data.texture_url, `/research/sessions/${sid}/conditions/${data.condition}/texture.png`) };
  }
  private async assetPair(glbUrl: string, textureUrl: string, signal?: AbortSignal): Promise<[ArrayBuffer, ArrayBuffer]> {
    const controller = new AbortController();
    const abort = () => controller.abort();
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) controller.abort();
    try {
      return await Promise.all([
        this.bytes(glbUrl, {}, GLB_LIMIT, "model/gltf-binary", controller.signal, 30_000),
        this.bytes(textureUrl, {}, PNG_LIMIT, "image/png", controller.signal, 30_000),
      ]);
    } catch (error) {
      controller.abort();
      throw error;
    } finally {
      signal?.removeEventListener("abort", abort);
    }
  }
  async loadSource(info: SessionInfo, signal?: AbortSignal): Promise<LoadedSource> {
    const sid = identifier(info.session_id);
    // Revalidate externally retained metadata instead of trusting a mutable object.
    const verified = this.parseInfo(info, sid);
    const [glbBytes, textureBytes] = await this.assetPair(
      this.url(verified.source_glb_url, `/research/sessions/${sid}/source.glb`),
      this.url(verified.source_texture_url, `/research/sessions/${sid}/source-texture.png`), signal);
    const parsed = await inspectGlb(glbBytes, textureBytes, verified);
    const base = object(parsed.extras.base_texture);
    if (base.age_generated === true || base.input_kind === "sam_generated_target_image") invalid("原始源不能被替换为生成目标。");
    return { kind: "original_source", info: verified, glbBytes, textureBytes, topologyId: parsed.topologyId,
      geometryHashes: Object.freeze(parsed.geometryHashes), coordinateMetadata: parsed.coordinates };
  }
  async loadCondition(info: SessionInfo, target: number, source: LoadedSource, signal?: AbortSignal): Promise<LoadedCondition> {
    const sid = identifier(info.session_id); condition(target);
    if (source.kind !== "original_source" || !equal(source.info, info)) invalid("条件资产必须绑定当前源会话。");
    const [glbBytes, textureBytes] = await this.assetPair(
      this.baseUrl + `/research/sessions/${sid}/conditions/${target}/mesh.glb`,
      this.baseUrl + `/research/sessions/${sid}/conditions/${target}/texture.png`, signal);
    const parsed = await inspectGlb(glbBytes, textureBytes, info);
    if (parsed.topologyId !== source.topologyId || !equal(parsed.coordinates, source.coordinateMetadata) || !equal(parsed.geometryHashes, source.geometryHashes)) invalid("条件资产改变了原始源几何或共同UV。");
    const base = object(parsed.extras.base_texture), provenance = object(base.research_pipeline);
    flags(provenance); flags(base, false);
    if (base.kind !== "sam_generated_registered_uv" || base.age_generated !== true || base.input_kind !== "sam_generated_target_image" || base.original_photo_observation !== false || provenance.source_fingerprint !== info.source_fingerprint || provenance.target_condition !== target || provenance.shape_route !== "static_fallback" || !equal(sourceAge(provenance.source_age), info.source_age)) invalid("条件资产的生成/源龄语义与会话不一致。");
    for (const key of ["generated_sha256", "target_fit_sha256", "allowed_png_sha256", "occluded_png_sha256", "provenance_sha256"]) digest(provenance[key]);
    const bindings = object(provenance.model_bindings);
    for (const key of ["detector_manifest_sha256", "reconstructor_manifest_sha256", "sam_manifest_sha256", "common_uv_asset_sha256"]) digest(bindings[key]);
    const generation = object(provenance.generation);
    integer(generation.pid, 1, Number.MAX_SAFE_INTEGER);
    if (generation.load_count !== 1) invalid();
    digest(generation.provenance_sha256);
    return { kind: "sam_condition", condition: target, info, glbBytes, textureBytes, topologyId: parsed.topologyId, provenance,
      geometryHashes: Object.freeze(parsed.geometryHashes), coordinateMetadata: parsed.coordinates };
  }
}
