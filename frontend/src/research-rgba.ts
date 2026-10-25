/** Preserve canonical straight RGBA bytes: Canvas2D's premultiplication is lossy. */
const MAX_PIXELS = 16_000_000;
const MAX_SCANLINE_BYTES = 80 * 1024 * 1024;
const MAX_GLB_BYTES = 64 * 1024 * 1024;
const MAX_JSON_BYTES = 1024 * 1024;
const PNG_SIGNATURE = new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]);
const encoder = new TextEncoder();
const decoder = new TextDecoder("utf-8", { fatal: true });
const align4 = (value: number): number => Math.ceil(value / 4) * 4;

function fail(message: string): never {
  throw new Error(`研究RGBA导出：${message}`);
}

function integer(value: unknown, minimum = 0): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= minimum;
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

function pngChunk(type: string, data: Uint8Array): Uint8Array {
  const chunk = new Uint8Array(data.length + 12);
  const view = new DataView(chunk.buffer);
  view.setUint32(0, data.length);
  chunk.set(encoder.encode(type), 4);
  chunk.set(data, 8);
  view.setUint32(chunk.length - 4, crc32(chunk.subarray(4, chunk.length - 4)));
  return chunk;
}

/** Encode noninterlaced 8-bit RGBA PNG without a canvas or color conversion. */
export async function encodeResearchRgbaPng(
  rgba: Uint8Array | Uint8ClampedArray,
  width: number,
  height: number,
): Promise<Uint8Array> {
  const pixels = width * height;
  const scanlineBytes = (width * 4 + 1) * height;
  if (!integer(width, 1) || !integer(height, 1) || !integer(pixels, 1) || pixels > MAX_PIXELS
    || scanlineBytes > MAX_SCANLINE_BYTES
    || (!(rgba instanceof Uint8Array) && !(rgba instanceof Uint8ClampedArray))
    || rgba.length !== pixels * 4) fail("需要尺寸匹配且不超过1600万像素的RGBA字节数组。");
  for (let offset = 0; offset < rgba.length; offset += 4) {
    if (rgba[offset + 3] === 0 && (rgba[offset] || rgba[offset + 1] || rgba[offset + 2]))
      fail("未知区域必须为RGBA零。");
  }
  const scanlines = new Uint8Array(scanlineBytes);
  const stride = width * 4;
  for (let row = 0; row < height; row++)
    scanlines.set(rgba.subarray(row * stride, (row + 1) * stride), row * (stride + 1) + 1);
  const compression = new CompressionStream("deflate");
  const compressed = new Response(compression.readable).arrayBuffer();
  const writer = compression.writable.getWriter();
  await writer.write(scanlines);
  await writer.close();
  const header = new Uint8Array(13);
  const headerView = new DataView(header.buffer);
  headerView.setUint32(0, width);
  headerView.setUint32(4, height);
  header.set([8, 6, 0, 0, 0], 8);
  const chunks = [pngChunk("IHDR", header), pngChunk("IDAT", new Uint8Array(await compressed)), pngChunk("IEND", new Uint8Array())];
  const result = new Uint8Array(8 + chunks.reduce((size, chunk) => size + chunk.length, 0));
  result.set(PNG_SIGNATURE);
  let offset = 8;
  for (const chunk of chunks) { result.set(chunk, offset); offset += chunk.length; }
  return result;
}

type Json = Record<string, unknown>;

function record(value: unknown): Json {
  if (!value || typeof value !== "object" || Array.isArray(value)) fail("GLB对象无效。");
  return value as Json;
}

function array(value: unknown, required = false): Json[] {
  if (value === undefined && !required) return [];
  if (!Array.isArray(value) || value.length > 100_000) fail("GLB数组无效或过大。");
  return value.map(record);
}

function reference(value: unknown, values: Json[]): number {
  if (!integer(value) || value >= values.length) fail("GLB索引越界。");
  return value;
}

function validatePng(png: Uint8Array): void {
  if (!(png instanceof Uint8Array) || png.length < 57 || png.length > MAX_GLB_BYTES
    || !PNG_SIGNATURE.every((byte, index) => byte === png[index])) fail("PNG无效或过大。");
  const view = new DataView(png.buffer, png.byteOffset, png.byteLength);
  let offset = 8, sawHeader = false, sawData = false, sawEnd = false;
  while (offset < png.length) {
    if (offset + 12 > png.length) fail("PNG块截断。");
    const length = view.getUint32(offset);
    const end = offset + 12 + length;
    if (end > png.length) fail("PNG块越界。");
    const type = decoder.decode(png.subarray(offset + 4, offset + 8));
    if (view.getUint32(end - 4) !== crc32(png.subarray(offset + 4, end - 4))) fail("PNG校验失败。");
    if (type === "IHDR" && !sawHeader && offset === 8 && length === 13) {
      const width = view.getUint32(offset + 8), height = view.getUint32(offset + 12);
      if (!width || !height || width * height > MAX_PIXELS
        || png[offset + 16] !== 8 || png[offset + 17] !== 6
        || png[offset + 18] || png[offset + 19] || png[offset + 20]) fail("PNG必须是有界8位RGBA栅格。");
      sawHeader = true;
    } else if (type === "IDAT" && sawHeader && !sawEnd) sawData = true;
    else if (type === "IEND" && sawData && length === 0 && end === png.length) sawEnd = true;
    else fail("PNG含不支持的块或顺序。");
    offset = end;
  }
  if (!sawEnd) fail("PNG缺少结束块。");
}

function validateAccessors(accessors: Json[], views: Json[]): void {
  const components: Record<string, number> = { SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4, MAT2: 4, MAT3: 9, MAT4: 16 };
  const bytes: Record<number, number> = { 5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4 };
  for (const accessor of accessors) {
    if (accessor.sparse !== undefined) fail("不支持稀疏accessor。");
    const view = views[reference(accessor.bufferView, views)];
    const count = accessor.count, offset = accessor.byteOffset ?? 0;
    const component = accessor.componentType, type = accessor.type;
    if (!integer(count, 1) || !integer(offset) || typeof component !== "number" || !bytes[component]
      || typeof type !== "string" || !Object.hasOwn(components, type)) fail("GLB accessor格式无效。");
    const size = bytes[component];
    // Matrix columns use 4-byte alignment even for 8-/16-bit components.
    const dimension = type.startsWith("MAT") ? Number(type.slice(3)) : 0;
    const elementBytes = dimension ? align4(dimension * size) * dimension : components[type] * size;
    const stride = view.byteStride ?? elementBytes;
    if (!integer(stride, elementBytes) || (view.byteStride !== undefined && (stride > 252 || stride % 4))
      || offset % size || (Number(view.byteOffset ?? 0) + offset) % size
      || offset + (count - 1) * stride + elementBytes > Number(view.byteLength)) fail("GLB accessor超出bufferView。");
  }
}

/** Append a canonical PNG, preserving original binary geometry and its descriptors. */
export async function replaceResearchPng(
  glb: ArrayBuffer,
  png: Uint8Array,
  textureName: string,
): Promise<ArrayBuffer> {
  if (!(glb instanceof ArrayBuffer) || glb.byteLength < 32 || glb.byteLength > MAX_GLB_BYTES)
    fail("GLB大小无效或超过64MiB。");
  if (typeof textureName !== "string" || !textureName.length || textureName.length > 256)
    fail("必须指定研究base-color纹理名称。");
  validatePng(png);
  const input = new Uint8Array(glb), header = new DataView(glb);
  if (header.getUint32(0, true) !== 0x46546c67 || header.getUint32(4, true) !== 2
    || header.getUint32(8, true) !== glb.byteLength) fail("需要长度精确的GLB v2。");
  const jsonLength = header.getUint32(12, true);
  const binHeader = 20 + jsonLength;
  if (!jsonLength || jsonLength % 4 || jsonLength > MAX_JSON_BYTES || binHeader + 8 > glb.byteLength
    || header.getUint32(16, true) !== 0x4e4f534a || header.getUint32(binHeader + 4, true) !== 0x004e4942)
    fail("需要有界JSON和单个BIN块。");
  const binLength = header.getUint32(binHeader, true);
  if (binLength % 4 || binHeader + 8 + binLength !== glb.byteLength) fail("BIN块截断或存在未知块。");
  let parsed: unknown;
  try { parsed = JSON.parse(decoder.decode(input.subarray(20, binHeader))); }
  catch { fail("GLB JSON无效。"); }
  const document = record(parsed), asset = record(document.asset);
  if (asset.version !== "2.0") fail("需要glTF 2.0资产。");
  const buffers = array(document.buffers, true), views = array(document.bufferViews, true);
  const images = array(document.images, true), textures = array(document.textures, true);
  const materials = array(document.materials, true);
  if (buffers.length !== 1 || buffers[0].uri !== undefined || !integer(buffers[0].byteLength, 1)
    || buffers[0].byteLength > binLength || binLength - buffers[0].byteLength > 3)
    fail("需要单个自包含且长度匹配的buffer。");
  const binaryLength = buffers[0].byteLength;
  for (let offset = binaryLength; offset < binLength; offset++)
    if (input[binHeader + 8 + offset] !== 0) fail("BIN填充必须为零。");
  for (const view of views) {
    const offset = view.byteOffset ?? 0;
    if (view.buffer !== 0 || !integer(offset) || !integer(view.byteLength, 1)
      || offset + view.byteLength > binaryLength) fail("GLB bufferView越界或使用外部buffer。");
  }
  validateAccessors(array(document.accessors), views);
  for (const image of images) {
    if (image.uri !== undefined) fail("GLB不能包含外部或data URI图像。");
    reference(image.bufferView, views);
  }
  const usedBaseTextures = new Set<number>();
  for (const material of materials) {
    if (material.pbrMetallicRoughness === undefined) continue;
    const pbr = record(material.pbrMetallicRoughness);
    if (pbr.baseColorTexture !== undefined)
      usedBaseTextures.add(reference(record(pbr.baseColorTexture).index, textures));
  }
  const selectedImages = new Set<number>();
  for (const index of usedBaseTextures) {
    const texture = textures[index];
    if (texture.name === textureName) {
      const imageIndex = reference(texture.source, images);
      if (images[imageIndex].mimeType !== "image/png") fail("研究base-color必须是内置PNG。");
      selectedImages.add(imageIndex);
    }
  }
  if (!selectedImages.size) fail("未找到命名研究base-color纹理。");
  const pngOffset = align4(binaryLength), nextBinaryLength = pngOffset + png.length;
  const newView = views.length;
  // All JSON objects are private to this parse; caller buffers remain untouched.
  (document.bufferViews as Json[]).push({ buffer: 0, byteOffset: pngOffset, byteLength: png.length });
  for (const index of selectedImages) images[index].bufferView = newView;
  buffers[0].byteLength = nextBinaryLength;
  const json = encoder.encode(JSON.stringify(document));
  const paddedJsonLength = align4(json.length), paddedBinaryLength = align4(nextBinaryLength);
  const totalLength = 12 + 8 + paddedJsonLength + 8 + paddedBinaryLength;
  if (paddedJsonLength > MAX_JSON_BYTES || totalLength > MAX_GLB_BYTES) fail("替换后GLB超过导出预算。");
  const result = new Uint8Array(totalLength), resultHeader = new DataView(result.buffer);
  resultHeader.setUint32(0, 0x46546c67, true);
  resultHeader.setUint32(4, 2, true);
  resultHeader.setUint32(8, totalLength, true);
  resultHeader.setUint32(12, paddedJsonLength, true);
  resultHeader.setUint32(16, 0x4e4f534a, true);
  result.fill(32, 20, 20 + paddedJsonLength);
  result.set(json, 20);
  const resultBinHeader = 20 + paddedJsonLength;
  resultHeader.setUint32(resultBinHeader, paddedBinaryLength, true);
  resultHeader.setUint32(resultBinHeader + 4, 0x004e4942, true);
  result.set(input.subarray(binHeader + 8, binHeader + 8 + binaryLength), resultBinHeader + 8);
  result.set(png, resultBinHeader + 8 + pngOffset);
  return result.buffer;
}
