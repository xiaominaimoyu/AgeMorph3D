// Offline, read-only review. All coordinates come from the frozen case payload.
export const PROTOCOL_ID = 'agemorph3d-mask-review-workbench-v1';
export const UV_SIZE = 256;
export const CLASS_LABELS = ['UV 外部', 'UV 重叠不唯一', '背向', '图像外', '自身遮挡', '遮罩拒绝', '已采样'];
export const REASON_LABELS = ['允许区', 'landmark 凸包外', '腐蚀环', '口部排除', '候选排除带'];
export const REGION_NAMES = ['eye_36_41', 'eye_42_47', 'nose_27_35', 'mouth_48_67'];
const REGION_LABELS = ['眼区 36–41', '眼区 42–47', '鼻区 27–35', '口区 48–67'];
const CLASS_COLORS = ['#172131', '#9952a4', '#5b6a81', '#5689c5', '#e8a04c', '#ff5d77', '#35d3c0'];
const REASON_COLORS = ['#35d3c0', '#65748b', '#e8a04c', '#d881ed', '#ff5d77'];
const REJECTION_LABELS = ['无可见遮罩拒绝', '仅候选带贡献', '仅其他不合格贡献', '候选带与其他贡献混合'];
const FALSE_FLAGS = ['age_quality_accepted', 'identity_quality_accepted', 'visual_seam_quality_accepted', 'independent_evaluation', 'causal_cause_accepted', 'masks_modified', 'unknown_regions_filled', 'real_model_inference', 'service_ready', 'production_enabled', 'g3_complete', 'historical_process_identity_proven', 'human_review_completed'];

function requireValue(condition, message) {
  if (!condition) throw new Error(message);
}

function isBase64(encoded) {
  if (typeof encoded !== 'string' || encoded.length % 4 !== 0) return false;
  const padding = encoded.endsWith('==') ? 2 : encoded.endsWith('=') ? 1 : 0;
  return !/[^A-Za-z0-9+/]/.test(encoded.slice(0, encoded.length - padding));
}

export function decodeRLE(rle, expectedLength, maxValue = 255) {
  requireValue(Number.isInteger(expectedLength) && expectedLength > 0 && expectedLength <= 16000000, 'Invalid RLE length.');
  requireValue(Number.isInteger(maxValue) && maxValue >= 0 && maxValue <= 255, 'Invalid RLE label bound.');
  requireValue(Array.isArray(rle) && rle.length > 0 && rle.length % 2 === 0 && rle.length <= expectedLength * 2, 'Invalid RLE pairs.');
  const result = new Uint8Array(expectedLength);
  let offset = 0;
  for (let i = 0; i < rle.length; i += 2) {
    const value = rle[i];
    const count = rle[i + 1];
    requireValue(Number.isInteger(value) && value >= 0 && value <= maxValue && Number.isInteger(count) && count > 0 && count <= expectedLength - offset, 'Invalid RLE value or count.');
    result.fill(value, offset, offset + count);
    offset += count;
  }
  requireValue(offset === expectedLength, 'Incomplete RLE field.');
  return result;
}

export function decodeVectorField(encoded, type, count, components = 1) {
  const kinds = { i32: [4, Int32Array, 'getInt32'], '<i4': [4, Int32Array, 'getInt32'], f64: [8, Float64Array, 'getFloat64'], '<f8': [8, Float64Array, 'getFloat64'], u8: [1, Uint8Array, 'getUint8'], '|u1': [1, Uint8Array, 'getUint8'] };
  requireValue(Object.hasOwn(kinds, type), 'Unsupported vector type.');
  requireValue(Number.isInteger(count) && count >= 0 && count <= 65536 && Number.isInteger(components) && components >= 1 && components <= 3, 'Invalid vector dimensions.');
  const [bytesPerValue, Constructor, getter] = kinds[type];
  const elements = count * components;
  const byteLength = elements * bytesPerValue;
  requireValue(typeof encoded === 'string' && encoded.length === Math.ceil(byteLength / 3) * 4 && isBase64(encoded), 'Invalid base64 vector.');
  const raw = atob(encoded);
  requireValue(raw.length === byteLength && btoa(raw) === encoded, 'Vector byte count or canonical encoding mismatch.');
  const bytes = Uint8Array.from(raw, value => value.charCodeAt(0));
  const view = new DataView(bytes.buffer);
  const result = new Constructor(elements);
  for (let i = 0; i < elements; i += 1) {
    result[i] = view[getter](i * bytesPerValue, true);
    requireValue(Number.isFinite(result[i]), 'Nonfinite vector coordinate.');
  }
  return result;
}

export function buildLookup(classification, vectors, size = UV_SIZE) {
  requireValue(Number.isInteger(size) && size > 0 && size <= UV_SIZE && classification.length === size * size, 'Invalid UV classification dimensions.');
  requireValue(Number.isInteger(vectors.count) && vectors.count >= 0 && vectors.count <= size * size && vectors.rowsColumns.length === vectors.count * 2, 'Invalid UV vector rows.');
  const lookup = new Int32Array(size * size).fill(-1);
  for (let i = 0; i < vectors.count; i += 1) {
    const row = vectors.rowsColumns[i * 2];
    const column = vectors.rowsColumns[i * 2 + 1];
    requireValue(Number.isInteger(row) && Number.isInteger(column) && row >= 0 && row < size && column >= 0 && column < size, 'UV vector outside atlas.');
    const address = row * size + column;
    requireValue(lookup[address] === -1 && classification[address] >= 2 && classification[address] <= 6, 'Duplicate or unknown UV vector.');
    lookup[address] = i;
  }
  for (let address = 0; address < classification.length; address += 1) {
    requireValue(classification[address] >= 0 && classification[address] <= 6 && (classification[address] >= 2) === (lookup[address] >= 0), 'Incomplete UV lookup or invalid classification.');
  }
  return lookup;
}

export function bilinearContributors(reasons, width, height, x, y) {
  requireValue(Number.isInteger(width) && width > 0 && Number.isInteger(height) && height > 0 && reasons.length === width * height, 'Invalid reason-map dimensions.');
  requireValue(Number.isFinite(x) && Number.isFinite(y) && x >= 0 && y >= 0 && x <= width - 1 && y <= height - 1, 'Contributor coordinate outside image.');
  const x0 = Math.floor(x);
  const y0 = Math.floor(y);
  const x1 = Math.min(x0 + 1, width - 1);
  const y1 = Math.min(y0 + 1, height - 1);
  const dx = x - x0;
  const dy = y - y0;
  return [[x0, y0, (1 - dx) * (1 - dy)], [x1, y0, dx * (1 - dy)], [x0, y1, (1 - dx) * dy], [x1, y1, dx * dy]]
    .filter(([, , weight]) => weight > 0)
    .map(([px, py, weight]) => {
      const reasonCode = reasons[py * width + px];
      requireValue(Number.isInteger(reasonCode) && reasonCode >= 0 && reasonCode <= 4, 'Invalid stage reason.');
      return { x: px, y: py, weight, reasonCode, reasonLabel: REASON_LABELS[reasonCode] };
    });
}

export function contributorReasonBits(contributors) {
  return contributors.reduce((bits, point) => bits | (point.reasonCode === 0 ? 0 : 1 << (point.reasonCode - 1)), 0);
}

export function canvasCoordinates(clientX, clientY, rect, width, height) {
  if (![clientX, clientY, rect?.left, rect?.top, rect?.width, rect?.height, width, height].every(Number.isFinite) || rect.width <= 0 || rect.height <= 0 || width <= 0 || height <= 0) return null;
  const x = (clientX - rect.left) * width / rect.width;
  const y = (clientY - rect.top) * height / rect.height;
  return x >= 0 && y >= 0 && x < width && y < height ? { x, y } : null;
}

export function uvCoordinates(clientX, clientY, rect, size = UV_SIZE) {
  const point = canvasCoordinates(clientX, clientY, rect, size, size);
  return point ? { row: Math.floor(point.y), column: Math.floor(point.x) } : null;
}

export function selectUVPoint(model, row, column) {
  const size = model.size ?? UV_SIZE;
  if (!Number.isInteger(row) || !Number.isInteger(column) || row < 0 || column < 0 || row >= size || column >= size) return null;
  const address = row * size + column;
  const classificationCode = model.classification[address];
  const index = model.lookup[address];
  const selection = { uv: { row, column }, classificationCode, classificationLabel: CLASS_LABELS[classificationCode], vectorIndex: null, faceOwner: null, barycentric: null, targetXYZ: null, sourceCanonicalXYZ: null, regionBits: null, regions: null, rejectionPartition: null, contributors: null, contributorReasonBits: null, approximate: false, selectionDistance: null };
  if (index < 0) return selection;
  const vectors = model.vectors;
  selection.vectorIndex = index;
  selection.faceOwner = vectors.faceOwner[index];
  selection.barycentric = Array.from(vectors.barycentric.slice(index * 3, index * 3 + 3));
  selection.targetXYZ = Array.from(vectors.targetXYZ.slice(index * 3, index * 3 + 3));
  selection.sourceCanonicalXYZ = Array.from(vectors.sourceCanonicalXYZ.slice(index * 3, index * 3 + 3));
  selection.regionBits = vectors.regionBits[index];
  selection.regions = REGION_NAMES.filter((_, bit) => selection.regionBits & (1 << bit));
  selection.rejectionPartition = vectors.rejectionPartition[index];
  if (classificationCode === 5 || classificationCode === 6) {
    selection.contributors = bilinearContributors(model.reasons, model.width, model.height, selection.targetXYZ[0], selection.targetXYZ[1]);
    selection.contributorReasonBits = contributorReasonBits(selection.contributors);
    const bits = selection.contributorReasonBits;
    const partition = (bits & 8 ? 1 : 0) + (bits & 7 ? 2 : 0);
    requireValue(partition === selection.rejectionPartition && (classificationCode === 5) === (partition > 0), 'Saved rejection partition disagrees with positive contributors.');
  }
  return selection;
}

export function nearestVisiblePoint(model, x, y, maxDistance = 3) {
  if (![x, y, maxDistance].every(Number.isFinite) || maxDistance < 0) return null;
  const vectors = model.vectors;
  const size = model.size ?? UV_SIZE;
  let nearest = null;
  let bestDistanceSquared = maxDistance * maxDistance;
  for (let index = 0; index < vectors.count; index += 1) {
    const code = model.classification[vectors.rowsColumns[index * 2] * size + vectors.rowsColumns[index * 2 + 1]];
    if (code !== 5 && code !== 6) continue;
    const offset = index * 3;
    const distanceSquared = (vectors.targetXYZ[offset] - x) ** 2 + (vectors.targetXYZ[offset + 1] - y) ** 2;
    const betterTie = nearest !== null && distanceSquared === bestDistanceSquared && (vectors.targetXYZ[offset + 2] > vectors.targetXYZ[nearest * 3 + 2] || (vectors.targetXYZ[offset + 2] === vectors.targetXYZ[nearest * 3 + 2] && index < nearest));
    if (distanceSquared < bestDistanceSquared || (distanceSquared === bestDistanceSquared && (nearest === null || betterTie))) {
      nearest = index;
      bestDistanceSquared = distanceSquared;
    }
  }
  return nearest === null ? null : { index: nearest, distance: Math.sqrt(bestDistanceSquared) };
}

export function selectTargetPoint(model, x, y) {
  const point = nearestVisiblePoint(model, x, y);
  if (!point) return null;
  const selection = selectUVPoint(model, model.vectors.rowsColumns[point.index * 2], model.vectors.rowsColumns[point.index * 2 + 1]);
  selection.approximate = true;
  selection.selectionDistance = point.distance;
  return selection;
}

export function decodeCase(data) {
  requireValue(data?.schemaVersion === 1 && data.protocolId === PROTOCOL_ID, 'Unsupported workbench protocol.');
  requireValue(typeof data.sampleId === 'string' && data.sampleId.length > 0 && typeof data.sourceId === 'string', 'Missing case identity.');
  requireValue(Number.isInteger(data.width) && data.width > 0 && Number.isInteger(data.height) && data.height > 0 && data.width * data.height <= 16000000, 'Invalid target dimensions.');
  requireValue(data.sourceAgeApi?.value === null && data.sourceAgeApi?.method === 'unknown' && data.sourceAgeApi?.calibration_id === null, 'Source API age must remain unknown.');
  requireValue(data.flags?.research_only === true && FALSE_FLAGS.every(flag => data.flags[flag] === false), 'Research flags must remain closed.');
  requireValue(data.provenance && typeof data.provenance === 'object' && !Array.isArray(data.provenance), 'Missing case provenance.');
  for (const points of [data.landmarksXY, data.roundedLandmarksXY]) {
    requireValue(Array.isArray(points) && points.length === 68 && points.every(point => Array.isArray(point) && point.length === 2 && point.every(Number.isFinite)), 'Expected 68 finite XY landmarks.');
  }
  requireValue(data.roundedLandmarksXY.every(point => point.every(Number.isInteger)), 'Rounded landmarks must be integers.');
  requireValue(data.regionBoxes && REGION_NAMES.every(name => Array.isArray(data.regionBoxes[name]) && data.regionBoxes[name].length === 4 && data.regionBoxes[name].every(Number.isFinite) && data.regionBoxes[name][0] < data.regionBoxes[name][2] && data.regionBoxes[name][1] < data.regionBoxes[name][3]), 'Invalid region boxes.');
  requireValue(data.images && ['target', 'allowed', 'occluded', 'atlas'].every(name => typeof data.images[name] === 'string' && data.images[name].startsWith('data:image/png;base64,') && data.images[name].length > 22 && isBase64(data.images[name].slice(22))), 'Expected embedded PNG images.');
  const source = data.vectors;
  requireValue(source && Number.isInteger(source.count) && source.count >= 0 && source.count <= 65536, 'Invalid correspondence count.');
  const count = source.count;
  const vectors = {
    count,
    rowsColumns: decodeVectorField(source.rows_columns_i32, 'i32', count, 2),
    faceOwner: decodeVectorField(source.face_owner_i32, 'i32', count),
    barycentric: decodeVectorField(source.barycentric_f64, 'f64', count, 3),
    targetXYZ: decodeVectorField(source.target_xyz_f64, 'f64', count, 3),
    sourceCanonicalXYZ: decodeVectorField(source.source_canonical_xyz_f64, 'f64', count, 3),
    regionBits: decodeVectorField(source.region_bits_u8, 'u8', count),
    rejectionPartition: decodeVectorField(source.rejection_partition_u8, 'u8', count),
  };
  const classification = decodeRLE(data.classificationRLE, UV_SIZE * UV_SIZE, 6);
  const reasons = decodeRLE(data.reasonRLE, data.width * data.height, 4);
  const lookup = buildLookup(classification, vectors);
  const model = { data, width: data.width, height: data.height, size: UV_SIZE, classification, reasons, vectors, lookup };
  for (let index = 0; index < count; index += 1) {
    requireValue(vectors.faceOwner[index] >= 0 && vectors.regionBits[index] <= 15 && vectors.rejectionPartition[index] <= 3, 'Invalid owner, region or rejection code.');
    const bary = vectors.barycentric.slice(index * 3, index * 3 + 3);
    requireValue(bary.every(value => value >= -1e-8 && value <= 1 + 1e-8) && Math.abs(bary[0] + bary[1] + bary[2] - 1) <= 1e-8, 'Invalid saved barycentric coordinates.');
    const row = vectors.rowsColumns[index * 2];
    const column = vectors.rowsColumns[index * 2 + 1];
    const code = classification[row * UV_SIZE + column];
    requireValue((code === 5) === (vectors.rejectionPartition[index] > 0), 'Classification and saved rejection disagree.');
    if (code === 5 || code === 6) selectUVPoint(model, row, column);
  }
  return model;
}

const snapshot = value => JSON.parse(JSON.stringify(value));

export function createReviewNotes(data, reviewer, observations, recordedAt = new Date().toISOString()) {
  requireValue(typeof reviewer === 'string' && reviewer.trim().length > 0 && reviewer.length <= 200 && Array.isArray(observations), 'Invalid review notes.');
  return {
    protocol_id: 'agemorph3d-mask-review-notes-v1',
    reviewer,
    recorded_at: recordedAt,
    sample_id: data.sampleId,
    source_id: data.sourceId,
    target_age_condition: data.targetAgeCondition,
    source_age_api: snapshot(data.sourceAgeApi),
    provenance: snapshot(data.provenance),
    observations: snapshot(observations),
    research_only: true,
    review_complete: false,
    ...Object.fromEntries(FALSE_FLAGS.map(flag => [flag, false])),
  };
}

function colorPixels(canvas, labels, colors, selectedOnly = null) {
  const context = canvas.getContext('2d');
  const pixels = context.createImageData(canvas.width, canvas.height);
  const rgb = colors.map(color => [1, 3, 5].map(offset => Number.parseInt(color.slice(offset, offset + 2), 16)));
  for (let index = 0; index < labels.length; index += 1) {
    const code = labels[index];
    const offset = index * 4;
    pixels.data.set(rgb[code], offset);
    pixels.data[offset + 3] = selectedOnly === null || code === selectedOnly ? 255 : 0;
  }
  context.putImageData(pixels, 0, 0);
  return canvas;
}

function makeCanvas(width, height) {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  return canvas;
}

function loadImage(uri) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => { image.onload = null; image.onerror = null; resolve(image); };
    image.onerror = () => { image.onload = null; image.onerror = null; reject(new Error('Embedded PNG could not be decoded.')); };
    image.src = uri;
  });
}

function maskOverlay(image, width, height, color) {
  const canvas = makeCanvas(width, height);
  const context = canvas.getContext('2d');
  context.drawImage(image, 0, 0);
  const pixels = context.getImageData(0, 0, width, height);
  const channels = [1, 3, 5].map(offset => Number.parseInt(color.slice(offset, offset + 2), 16));
  for (let offset = 0; offset < pixels.data.length; offset += 4) {
    const active = pixels.data[offset] !== 0;
    pixels.data.set(channels, offset);
    pixels.data[offset + 3] = active ? 255 : 0;
  }
  context.putImageData(pixels, 0, 0);
  return canvas;
}

function textElement(tag, value, className) {
  const element = document.createElement(tag);
  element.textContent = value;
  if (className) element.className = className;
  return element;
}

function legend(container, labels, colors) {
  labels.forEach((label, index) => {
    const item = textElement('span', '');
    const swatch = textElement('i', '', 'swatch');
    swatch.style.backgroundColor = colors[index];
    item.append(swatch, document.createTextNode(label));
    container.append(item);
  });
}

export async function mountWorkbench() {
  const byId = id => document.getElementById(id);
  const abort = new AbortController();
  const urls = new Set();
  let active = true;
  let selection = null;
  const observations = [];
  const listen = (target, type, listener) => target.addEventListener(type, listener, { signal: abort.signal });
  listen(window, 'pagehide', () => {
    active = false;
    selection = null;
    observations.length = 0;
    for (const url of urls) URL.revokeObjectURL(url);
    urls.clear();
    abort.abort();
    byId('point-details').replaceChildren();
    byId('point-details').dataset.selection = 'null';
    byId('add-observation').disabled = true;
    byId('reviewer').value = '';
    byId('review-notes').value = '';
    byId('observations-list').replaceChildren();
    byId('export-note').disabled = true;
    byId('note-count').textContent = '0 条';
  });
  try {
    const data = JSON.parse(byId('case-data').textContent);
    const model = decodeCase(data);
    const imageEntries = await Promise.all(Object.entries(data.images).filter(([name]) => ['target', 'allowed', 'occluded', 'atlas'].includes(name)).map(async ([name, uri]) => [name, await loadImage(uri)]));
    if (!active) return;
    const images = Object.fromEntries(imageEntries);
    for (const name of ['target', 'allowed', 'occluded']) requireValue(images[name].naturalWidth === model.width && images[name].naturalHeight === model.height, 'Embedded target/mask dimensions disagree.');
    requireValue(images.atlas.naturalWidth === UV_SIZE && images.atlas.naturalHeight === UV_SIZE, 'Embedded atlas dimensions disagree.');
    const targetCanvas = byId('target-canvas');
    const uvCanvas = byId('uv-canvas');
    targetCanvas.width = model.width;
    targetCanvas.height = model.height;
    const stageLayer = colorPixels(makeCanvas(model.width, model.height), model.reasons, REASON_COLORS);
    const overlays = { allowed: maskOverlay(images.allowed, model.width, model.height, REASON_COLORS[0]), occluded: maskOverlay(images.occluded, model.width, model.height, REASON_COLORS[4]), stages: stageLayer };
    const classLayer = colorPixels(makeCanvas(UV_SIZE, UV_SIZE), model.classification, CLASS_COLORS);
    byId('case-title').textContent = `${data.sampleId} · 遮罩审查`;
    document.title = `${data.sampleId} · AgeMorph3D 遮罩审查`;
    byId('case-subtitle').textContent = `开发组 ${data.sourceId} · 目标年龄条件 ${data.targetAgeCondition} · API 源龄未知 · 原图 ${model.width} × ${model.height}`;
    byId('provenance').textContent = JSON.stringify({ protocol_id: data.protocolId, source_age_api: data.sourceAgeApi, source_age_label: data.sourceAgeLabel, provenance: data.provenance, flags: { research_only: true, ...Object.fromEntries(FALSE_FLAGS.map(flag => [flag, false])) } }, null, 2);
    legend(byId('class-legend'), CLASS_LABELS, CLASS_COLORS);
    const navigation = byId('case-navigation');
    if (data.indexHref === '../index.html') {
      const link = textElement('a', '全部目标');
      link.href = data.indexHref;
      navigation.append(link);
    }
    for (const item of data.navLinks ?? []) {
      requireValue(typeof item.sampleId === 'string' && typeof item.href === 'string' && /^(?:\.\/)?[a-zA-Z0-9_-]+\.html$/.test(item.href), 'Unsafe case navigation link.');
      const link = textElement('a', item.label ?? item.sampleId);
      link.href = item.href;
      if (item.sampleId === data.sampleId) link.setAttribute('aria-current', 'page');
      navigation.append(link);
    }
    const regionToggles = REGION_NAMES.map((name, index) => {
      const label = textElement('label', '');
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.checked = true;
      checkbox.dataset.region = name;
      label.append(checkbox, document.createTextNode(REGION_LABELS[index]));
      byId('region-toggles').append(label);
      return checkbox;
    });

    function drawTarget() {
      const context = targetCanvas.getContext('2d');
      context.clearRect(0, 0, model.width, model.height);
      context.drawImage(images.target, 0, 0);
      const layer = byId('overlay-layer').value;
      if (Object.hasOwn(overlays, layer)) {
        context.globalAlpha = Number(byId('overlay-opacity').value);
        context.drawImage(overlays[layer], 0, 0);
        context.globalAlpha = 1;
      }
      const scale = Math.max(1, model.width / 700);
      if (byId('show-regions').checked) REGION_NAMES.forEach((name, index) => {
        if (!regionToggles[index].checked) return;
        const [x0, y0, x1, y1] = data.regionBoxes[name];
        context.strokeStyle = ['#35d3c0', '#78aaff', '#e8a04c', '#d881ed'][index];
        context.lineWidth = 1.3 * scale;
        context.strokeRect(x0, y0, x1 - x0, y1 - y0);
      });
      const mode = byId('landmark-mode').value;
      function points(values, rounded) {
        context.fillStyle = rounded ? '#e8a04c' : '#35d3c0';
        context.strokeStyle = '#0a0e1a';
        context.lineWidth = scale;
        values.forEach(([x, y]) => {
          context.beginPath();
          if (rounded) context.rect(x - 2.2 * scale, y - 2.2 * scale, 4.4 * scale, 4.4 * scale);
          else context.arc(x, y, 2 * scale, 0, Math.PI * 2);
          context.fill();
          context.stroke();
        });
      }
      if (mode === 'continuous' || mode === 'both') points(data.landmarksXY, false);
      if (mode === 'rounded' || mode === 'both') points(data.roundedLandmarksXY, true);
      if (selection?.targetXYZ && (selection.classificationCode === 5 || selection.classificationCode === 6)) {
        const [x, y] = selection.targetXYZ;
        context.strokeStyle = '#ffffff';
        context.lineWidth = 1.5 * scale;
        context.beginPath();
        context.arc(x, y, 7 * scale, 0, Math.PI * 2);
        context.moveTo(x - 11 * scale, y);
        context.lineTo(x + 11 * scale, y);
        context.moveTo(x, y - 11 * scale);
        context.lineTo(x, y + 11 * scale);
        context.stroke();
      }
    }

    function drawUV() {
      const context = uvCanvas.getContext('2d');
      context.clearRect(0, 0, UV_SIZE, UV_SIZE);
      context.drawImage(byId('uv-mode').value === 'atlas' ? images.atlas : classLayer, 0, 0);
      if (selection) {
        const { row, column } = selection.uv;
        context.strokeStyle = '#000';
        context.lineWidth = 3;
        context.strokeRect(column - 2, row - 2, 5, 5);
        context.strokeStyle = '#fff';
        context.lineWidth = 1;
        context.strokeRect(column - 2, row - 2, 5, 5);
      }
    }

    function showSelection(next, message) {
      selection = next;
      const details = byId('point-details');
      details.replaceChildren();
      details.dataset.selection = JSON.stringify(selection);
      byId('selection-message').textContent = message;
      byId('add-observation').disabled = !selection;
      if (selection) {
        const grid = textElement('dl', '', 'point-grid');
        function row(label, value) {
          grid.append(textElement('dt', label), textElement('dd', value === null ? 'null' : typeof value === 'string' ? value : JSON.stringify(value)));
        }
        row('UV 行 / 列', [selection.uv.row, selection.uv.column]);
        row('原始分类', `${selection.classificationCode} · ${selection.classificationLabel}`);
        row('原生 face owner', selection.faceOwner);
        row('a / b / c 权重', selection.barycentric);
        row('目标投影 XYZ', selection.targetXYZ);
        row('原源 canonical XYZ', selection.sourceCanonicalXYZ);
        row('重叠区域', selection.regions);
        row('区域位', selection.regionBits);
        row('原拒绝分区', selection.rejectionPartition === null ? null : `${selection.rejectionPartition} · ${REJECTION_LABELS[selection.rejectionPartition]}`);
        row('正权原因位', selection.contributorReasonBits);
        if (selection.approximate) row('近似选择距离 / px', selection.selectionDistance);
        details.append(grid);
        if (selection.vectorIndex === null) details.append(textElement('p', '此 texel 没有唯一对应；owner、目标及原源坐标均为 null。', 'small'));
        else if (!selection.contributors) details.append(textElement('p', '该分类未进入可见遮罩查询阶段，不赋予遮罩贡献原因。', 'small'));
        else selection.contributors.forEach(point => details.append(textElement('div', `像素 (${point.x}, ${point.y}) · 权重 ${point.weight}\n${point.reasonCode} · ${point.reasonLabel}`, 'contributor')));
      }
      drawTarget();
      drawUV();
    }

    for (const id of ['overlay-layer', 'landmark-mode', 'show-regions']) listen(byId(id), 'change', drawTarget);
    listen(byId('overlay-opacity'), 'input', () => {
      byId('opacity-value').textContent = `${Math.round(Number(byId('overlay-opacity').value) * 100)}%`;
      drawTarget();
    });
    regionToggles.forEach(checkbox => listen(checkbox, 'change', drawTarget));
    listen(byId('uv-mode'), 'change', drawUV);
    listen(byId('target-zoom'), 'change', () => {
      const zoom = byId('target-zoom').value;
      targetCanvas.style.width = zoom === 'fit' ? '100%' : `${model.width * Number(zoom)}px`;
      targetCanvas.style.maxWidth = zoom === 'fit' ? '100%' : 'none';
    });
    listen(uvCanvas, 'click', event => {
      const point = uvCoordinates(event.clientX, event.clientY, uvCanvas.getBoundingClientRect());
      showSelection(point ? selectUVPoint(model, point.row, point.column) : null, point ? '直接选择 UV texel。' : 'UV 外部：已清除上次选择。');
    });
    listen(targetCanvas, 'click', event => {
      const point = canvasCoordinates(event.clientX, event.clientY, targetCanvas.getBoundingClientRect(), model.width, model.height);
      const next = point ? selectTargetPoint(model, point.x, point.y) : null;
      showSelection(next, next ? `近似最近中心选择 · ${next.selectionDistance} 原图像素` : '3 像素内无可见中心：已清除上次选择。');
    });
    listen(byId('add-observation'), 'click', () => {
      const text = byId('review-notes').value.trim();
      if (!selection || !text) { byId('status').textContent = '选择一个点并填写观察后再添加。'; return; }
      const observation = { recorded_at: new Date().toISOString(), selection: snapshot(selection), text };
      observations.push(observation);
      const item = textElement('li', `UV (${selection.uv.row}, ${selection.uv.column}) · ${text}`);
      byId('observations-list').append(item);
      byId('review-notes').value = '';
      byId('note-count').textContent = `${observations.length} 条`;
      byId('export-note').disabled = false;
      byId('status').textContent = '已添加观察快照；尚未下载。';
    });
    listen(byId('export-note'), 'click', () => {
      const reviewer = byId('reviewer').value.trim();
      if (!reviewer) {
        byId('status').textContent = '填写审查者后再下载观察草稿。';
        byId('reviewer').focus();
        return;
      }
      let url = null;
      let link = null;
      try {
        const notes = createReviewNotes(data, reviewer, observations);
        const blob = new Blob([JSON.stringify(notes, null, 2) + '\n'], { type: 'application/json' });
        url = URL.createObjectURL(blob);
        urls.add(url);
        link = document.createElement('a');
        link.href = url;
        link.download = `${data.sampleId}-mask-review-notes.json`;
        document.body.append(link);
        link.click();
        link.remove();
        const downloadUrl = url;
        setTimeout(() => { URL.revokeObjectURL(downloadUrl); urls.delete(downloadUrl); }, 1000);
        byId('status').textContent = `已请求下载 ${observations.length} 条观察草稿；审查完成与质量标志均为 false。`;
      } catch (error) {
        link?.remove();
        if (url) { URL.revokeObjectURL(url); urls.delete(url); }
        byId('status').textContent = `导出失败：${error instanceof Error ? error.message : String(error)}`;
      }
    });
    showSelection(null, '请选择 UV texel 或目标图中的可见中心。');
    byId('status').textContent = '冻结数据已加载 · 只读研究 · 0 条观察';
    byId('status').dataset.ready = 'true';
    document.documentElement.dataset.workbenchReady = 'true';
  } catch (error) {
    if (!active) return;
    const panel = byId('workbench-error');
    panel.hidden = false;
    panel.textContent = `页面校验失败：${error instanceof Error ? error.message : String(error)}`;
    byId('status').textContent = '未加载可审查数据。';
    byId('status').dataset.ready = 'false';
    document.documentElement.dataset.workbenchReady = 'false';
    abort.abort();
    for (const url of urls) URL.revokeObjectURL(url);
    urls.clear();
  }
}

if (typeof document !== 'undefined') void mountWorkbench();
