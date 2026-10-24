import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, open, realpath, stat, unlink, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, isAbsolute, relative, resolve, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { chromium } from '@playwright/test';

// Explicit offline engineering verification. Never imports the application's helpers.
const PROTOCOL = 'agemorph3d-mask-workbench-browser-v1';
const UNKNOWN = { value: null, method: 'unknown', calibration_id: null };
const MAX_METADATA = 32 * 1024 ** 2;
const REQUIRED = ['frontend/tests/mask-review-workbench.mjs', 'frontend/research/mask-review.mjs', 'frontend/research/mask-review.html', 'frontend/package.json', 'frontend/package-lock.json'];
const FLAGS = ['age_quality_accepted', 'identity_quality_accepted', 'visual_seam_quality_accepted', 'independent_evaluation', 'causal_cause_accepted', 'masks_modified', 'unknown_regions_filled', 'real_model_inference', 'service_ready', 'production_enabled', 'g3_complete', 'historical_process_identity_proven', 'human_review_completed'];
const REGIONS = ['eye_36_41', 'eye_42_47', 'nose_27_35', 'mouth_48_67'];
const STAGES = [[53, 211, 192, 255], [101, 116, 139, 255], [232, 160, 76, 255], [216, 129, 237, 255], [255, 93, 119, 255]];
const CLASSES = [[23, 33, 49, 255], [153, 82, 164, 255], [91, 106, 129, 255], [86, 137, 197, 255], [232, 160, 76, 255], [255, 93, 119, 255], [53, 211, 192, 255]];
const root = await realpath(fileURLToPath(new URL('../../', import.meta.url)));
const frontendRequire = createRequire(resolve(root, 'frontend/package.json'));
const planned = new Map();
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const textError = error => error instanceof Error ? `${error.name}: ${error.message}\n${error.stack ?? ''}` : String(error);

function withinRoot(path) {
  const remainder = relative(root, path);
  return remainder !== '' && !isAbsolute(remainder) && remainder !== '..' && !remainder.startsWith(`..${sep}`);
}

function inputPath(name) {
  assert.equal(typeof name, 'string');
  assert.ok(name.length > 0 && !name.includes('\\') && !isAbsolute(name));
  const path = resolve(root, name);
  assert.ok(withinRoot(path) && relative(root, path).split(sep).join('/') === name, `Unsafe project path: ${name}`);
  return path;
}

async function existing(name) {
  assert.equal(typeof name, 'string', 'An explicit plan/output environment variable is required.');
  const path = isAbsolute(name) ? resolve(name) : inputPath(name);
  assert.ok(withinRoot(path));
  assert.equal(await realpath(path), path, 'Input cannot resolve through a symlink.');
  return path;
}

async function readBounded(path, limit = MAX_METADATA) {
  const handle = await open(path, 'r');
  try {
    const info = await handle.stat();
    assert.ok(info.isFile() && info.size >= 0 && info.size <= limit, `Input size limit: ${path}`);
    const bytes = await handle.readFile();
    assert.equal(bytes.length, info.size);
    return bytes;
  } finally { await handle.close(); }
}

async function hashFile(path) {
  const handle = await open(path, 'r');
  const hash = createHash('sha256');
  let bytes = 0;
  try {
    const before = await handle.stat();
    assert.ok(before.isFile());
    for await (const block of handle.createReadStream({ autoClose: false })) { hash.update(block); bytes += block.length; }
    const after = await handle.stat();
    assert.equal(bytes, before.size);
    assert.equal(after.size, before.size);
    assert.equal(after.mtimeMs, before.mtimeMs, 'File changed while hashing.');
  } finally { await handle.close(); }
  return { bytes, sha256: hash.digest('hex') };
}

function pinShape(pin) {
  assert.ok(pin && typeof pin === 'object' && typeof pin.path === 'string');
  assert.ok(Number.isSafeInteger(pin.bytes) && pin.bytes >= 0 && /^[a-f0-9]{64}$/.test(pin.sha256));
  return { path: pin.path, bytes: pin.bytes, sha256: pin.sha256 };
}

async function verifyPin(pin) {
  pinShape(pin);
  const path = await existing(inputPath(pin.path));
  const actual = await hashFile(path);
  assert.equal(actual.bytes, pin.bytes, `Byte count drift: ${pin.path}`);
  assert.equal(actual.sha256, pin.sha256, `SHA256 drift: ${pin.path}`);
  return path;
}

function requirePlanned(pin) {
  assert.deepEqual(pinShape(planned.get(pin.path)), pinShape(pin), `Missing/conflicting frozen pin: ${pin.path}`);
}

async function pinnedJSON(pin) {
  requirePlanned(pin);
  const path = await verifyPin(pin);
  return JSON.parse((await readBounded(path)).toString('utf8'));
}

function sameNumbers(actual, expected, label = 'value') {
  if (typeof expected === 'number') {
    assert.ok(Number.isFinite(actual) && actual === expected, `${label}: ${actual} !== ${expected}`); // +0 and -0 have equal numeric meaning.
  } else if (Array.isArray(expected)) {
    assert.ok(Array.isArray(actual), `${label}: expected array`);
    assert.equal(actual.length, expected.length, `${label}: array length`);
    expected.forEach((value, index) => sameNumbers(actual[index], value, `${label}[${index}]`));
  } else if (expected !== null && typeof expected === 'object') {
    assert.ok(actual && typeof actual === 'object', `${label}: expected object`);
    for (const [key, value] of Object.entries(expected)) sameNumbers(actual[key], value, `${label}.${key}`);
  } else assert.equal(actual, expected, label);
}

function comparePoint(actual, expected, approximate = false) {
  assert.ok(actual, 'A point selection is required.');
  for (const key of ['uv', 'classificationCode', 'vectorIndex', 'faceOwner', 'barycentric', 'targetXYZ', 'sourceCanonicalXYZ', 'regionBits', 'regions', 'rejectionPartition', 'contributors', 'contributorReasonBits']) {
    assert.ok(Object.hasOwn(expected, key), `Oracle lacks ${key}.`);
    sameNumbers(actual[key], expected[key], key);
  }
  assert.equal(actual.approximate, approximate);
  if (expected.classificationCode < 2) {
    for (const key of ['vectorIndex', 'faceOwner', 'barycentric', 'targetXYZ', 'sourceCanonicalXYZ', 'regionBits', 'regions', 'rejectionPartition', 'contributors', 'contributorReasonBits']) assert.equal(actual[key], null, `Unknown retains ${key}.`);
  } else if (expected.classificationCode !== 5 && expected.classificationCode !== 6) assert.equal(actual.contributors, null);
}

function parsePayload(bytes) {
  const html = bytes.toString('utf8');
  const marker = '<script id="case-data" type="application/json">';
  const start = html.indexOf(marker);
  assert.ok(start >= 0 && html.indexOf(marker, start + marker.length) === -1);
  const end = html.indexOf('</script>', start + marker.length);
  assert.ok(end >= 0);
  return JSON.parse(html.slice(start + marker.length, end));
}

function decodeOracle(payload) {
  const labels = new Uint8Array(65536);
  let offset = 0;
  for (let pair = 0; pair < payload.classificationRLE.length; pair += 2) {
    const [value, count] = payload.classificationRLE.slice(pair, pair + 2);
    assert.ok(Number.isInteger(value) && value >= 0 && value <= 6 && Number.isInteger(count) && count > 0 && offset + count <= labels.length);
    labels.fill(value, offset, offset + count); offset += count;
  }
  assert.equal(offset, labels.length);
  const vector = payload.vectors;
  return { payload, labels, count: vector.count, rows: Buffer.from(vector.rows_columns_i32, 'base64'), target: Buffer.from(vector.target_xyz_f64, 'base64'), owner: Buffer.from(vector.face_owner_i32, 'base64'), bary: Buffer.from(vector.barycentric_f64, 'base64'), source: Buffer.from(vector.source_canonical_xyz_f64, 'base64'), regions: Buffer.from(vector.region_bits_u8, 'base64'), rejection: Buffer.from(vector.rejection_partition_u8, 'base64') };
}

function nearestOracle(oracle, captured) {
  const x = (captured.clientX - captured.rect.left) * captured.width / captured.rect.width;
  const y = (captured.clientY - captured.rect.top) * captured.height / captured.rect.height;
  let found = null;
  let best = 9;
  for (let index = 0; index < oracle.count; index += 1) {
    const row = oracle.rows.readInt32LE(index * 8);
    const column = oracle.rows.readInt32LE(index * 8 + 4);
    const code = oracle.labels[row * 256 + column];
    if (code !== 5 && code !== 6) continue;
    const px = oracle.target.readDoubleLE(index * 24);
    const py = oracle.target.readDoubleLE(index * 24 + 8);
    const z = oracle.target.readDoubleLE(index * 24 + 16);
    const distance = (px - x) ** 2 + (py - y) ** 2;
    if (distance < best || (distance === best && (found === null || z > found.z || (z === found.z && index < found.index)))) {
      best = distance; found = { index, row, column, z };
    }
  }
  return found ? { ...found, distance: Math.sqrt(best), clickedTargetXY: [x, y] } : null;
}

function pointFromOracle(oracle, index) {
  const row = oracle.rows.readInt32LE(index * 8), column = oracle.rows.readInt32LE(index * 8 + 4);
  const triple = buffer => [0, 8, 16].map(offset => buffer.readDoubleLE(index * 24 + offset));
  const regionBits = oracle.regions[index];
  return { uv: { row, column }, classificationCode: oracle.labels[row * 256 + column], vectorIndex: index, faceOwner: oracle.owner.readInt32LE(index * 4), barycentric: triple(oracle.bary), targetXYZ: triple(oracle.target), sourceCanonicalXYZ: triple(oracle.source), regionBits, regions: REGIONS.filter((_, bit) => regionBits & (1 << bit)), rejectionPartition: oracle.rejection[index] };
}

async function canvasPixels(page, id, points) {
  return page.evaluate(({ id, points }) => {
    const canvas = document.getElementById(id), context = canvas.getContext('2d');
    return points.map(({ x, y }) => Array.from(context.getImageData(x, y, 1, 1).data));
  }, { id, points });
}

function comparePixels(actual, expected, tolerance = 0) {
  assert.equal(actual.length, expected.length);
  actual.forEach((pixel, index) => pixel.forEach((channel, component) => assert.ok(Math.abs(channel - expected[index][component]) <= tolerance, `Pixel ${index} channel ${component}: ${channel} / ${expected[index][component]} (tolerance ${tolerance})`)));
}

async function selected(page) {
  return page.locator('#point-details').evaluate(element => JSON.parse(element.dataset.selection ?? 'null'));
}

async function ready(page) {
  await page.waitForFunction(() => document.getElementById('status')?.dataset.ready === 'true' || document.getElementById('workbench-error')?.hidden === false, null, { timeout: 30000 });
  assert.equal(await page.locator('#status').getAttribute('data-ready'), 'true', await page.locator('#workbench-error').textContent());
  assert.equal(await page.locator('#workbench-error').isVisible(), false);
}

async function clickUV(page, uv) {
  const canvas = page.locator('#uv-canvas');
  await canvas.scrollIntoViewIfNeeded();
  const box = await canvas.boundingBox(); assert.ok(box);
  // Chrome exposes integer MouseEvent client coordinates. Dispatch an integer
  // strictly inside this texel's half-open CSS interval, retaining the UV oracle.
  const integerCoordinate = (start, extent, texel) => {
    const lo = start + texel * extent / 256;
    const hi = start + (texel + 1) * extent / 256;
    const minimum = Math.ceil(lo);
    const maximum = Math.ceil(hi) - 1;
    assert.ok(minimum <= maximum, 'UV texel has no representable integer CSS click coordinate.');
    const coordinate = Math.min(maximum, Math.max(minimum, Math.round((lo + hi) / 2)));
    assert.ok(Number.isInteger(coordinate) && coordinate >= lo && coordinate < hi);
    return coordinate;
  };
  await page.mouse.click(integerCoordinate(box.x, box.width, uv.column), integerCoordinate(box.y, box.height, uv.row));
  return selected(page);
}

async function clickTarget(page, xy) {
  await page.locator('#target-viewport').scrollIntoViewIfNeeded();
  await page.evaluate(([x, y]) => {
    const viewport = document.getElementById('target-viewport'), canvas = document.getElementById('target-canvas');
    const box = canvas.getBoundingClientRect(), container = viewport.getBoundingClientRect();
    viewport.scrollLeft += box.left + x * box.width / canvas.width - container.left - container.width / 2;
    viewport.scrollTop += box.top + y * box.height / canvas.height - container.top - container.height / 2;
  }, xy);
  const box = await page.locator('#target-canvas').boundingBox(); assert.ok(box);
  const native = await page.locator('#target-canvas').evaluate(canvas => [canvas.width, canvas.height]);
  const previousClicks = await page.evaluate(() => window.__maskWorkbenchEvidence.targetClicks.length);
  await page.mouse.click(box.x + xy[0] * box.width / native[0], box.y + xy[1] * box.height / native[1]);
  assert.equal(await page.evaluate(() => window.__maskWorkbenchEvidence.targetClicks.length), previousClicks + 1, 'The native click must reach the target canvas.');
  const captured = await page.evaluate(() => window.__maskWorkbenchEvidence.targetClicks.at(-1));
  assert.ok(captured, 'Native target click was not observed.');
  return { captured, selection: await selected(page) };
}

async function cleanControls(page, unknown) {
  if (unknown) { const result = await clickUV(page, unknown.uv); assert.ok(result && result.vectorIndex === null); }
  await page.locator('#overlay-layer').selectOption('none');
  await page.locator('#landmark-mode').selectOption('off');
  await page.locator('#show-regions').uncheck();
}

async function canvasDifference(page, baseline) {
  return page.evaluate(reference => {
    const canvas = document.getElementById('target-canvas');
    const current = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
    let changed = 0;
    for (let index = 0; index < current.length; index += 4) if (current[index] !== reference[index] || current[index + 1] !== reference[index + 1] || current[index + 2] !== reference[index + 2] || current[index + 3] !== reference[index + 3]) changed += 1;
    return changed;
  }, baseline);
}

function installObservers() {
  const evidence = { created: [], revoked: [], active: new Set(), targetClicks: [], pagehide: 0 };
  window.__maskWorkbenchEvidence = evidence;
  const nativeCreate = URL.createObjectURL, nativeRevoke = URL.revokeObjectURL;
  URL.createObjectURL = function (...args) {
    const url = nativeCreate.apply(this, args); evidence.created.push(url); evidence.active.add(url); return url;
  };
  URL.revokeObjectURL = function (url) {
    evidence.revoked.push(url); evidence.active.delete(url); return nativeRevoke.call(this, url);
  };
  document.addEventListener('click', event => {
    if (event.target?.id !== 'target-canvas') return;
    const canvas = event.target, box = canvas.getBoundingClientRect();
    evidence.targetClicks.push({ clientX: event.clientX, clientY: event.clientY, width: canvas.width, height: canvas.height, rect: { left: box.left, top: box.top, width: box.width, height: box.height } });
  }, true);
  window.addEventListener('pagehide', () => { evidence.pagehide += 1; });
}

const planPath = await existing(process.env.AGEMORPH_MASK_REVIEW_BROWSER_PLAN);
assert.ok(relative(root, planPath).split(sep).join('/').startsWith('output/research/'));
const planBytes = await readBounded(planPath), plan = JSON.parse(planBytes.toString('utf8'));
assert.equal(plan.schema_version, 1); assert.equal(plan.protocol_id, PROTOCOL);
assert.ok(Array.isArray(plan.inputs) && plan.inputs.length > 0 && plan.inputs.length <= 1024);
for (const input of plan.inputs) {
  pinShape(input); assert.equal(planned.has(input.path), false, 'Duplicate planned pin.');
  planned.set(input.path, input); await verifyPin(input);
}
for (const source of REQUIRED) assert.ok(planned.has(source), `Freeze ${source}.`);
for (const key of ['export_report', 'artifact_audit', 'expectations', 'browser_runtime']) requirePlanned(plan[key]);
const exported = await pinnedJSON(plan.export_report), audit = await pinnedJSON(plan.artifact_audit), expectations = await pinnedJSON(plan.expectations), runtime = await pinnedJSON(plan.browser_runtime);
assert.equal(exported.protocol_id, 'agemorph3d-mask-review-workbench-v1'); assert.equal(exported.summary?.all_requested_verified, true);
assert.equal(exported.records.length, 12); assert.ok(exported.records.every(row => row.status === 'ok'));
for (const pin of [...exported.inputs, exported.study_plan, exported.artifacts.index, ...exported.records.map(row => row.artifacts.page)]) requirePlanned(pin);
assert.equal(audit.status, 'passed'); assert.deepEqual(pinShape(audit.export_report), pinShape(plan.export_report));
assert.deepEqual(pinShape(audit.browser_expectations), pinShape(plan.expectations));
assert.equal(audit.summary.targets, 12); assert.equal(audit.summary.pages, 13); assert.equal(audit.summary.original_pngs_exact, 48); assert.equal(audit.summary.saved_vector_arrays_exact, 84);
assert.equal(expectations.schema_version, 1); assert.deepEqual(pinShape(expectations.export_report), pinShape(plan.export_report)); assert.equal(expectations.cases.length, 12);
assert.equal(runtime.status, 'passed'); assert.equal(runtime.offline_file_csp_module, true); assert.equal(runtime.node, process.version);
assert.equal(runtime.playwright_version, frontendRequire('@playwright/test/package.json').version);
assert.deepEqual(runtime.errors, []); assert.equal(runtime.external_network_requests, 0);
const exportRows = new Map(exported.records.map(row => [row.sample_id, row]));
const oracles = new Map();
for (const item of expectations.cases) {
  assert.ok(/^[a-zA-Z0-9_-]+$/.test(item.sample_id) && !oracles.has(item.sample_id));
  const row = exportRows.get(item.sample_id); assert.ok(row); assert.deepEqual(pinShape(item.page), pinShape(row.artifacts.page));
  requirePlanned(item.page); assert.equal(item.source_id, row.source_id); assert.equal(item.target_age_condition, row.target_age_condition);
  assert.ok(Array.isArray(item.points) && item.points.some(point => point.classificationCode < 2) && item.points.some(point => point.classificationCode === 5) && item.points.some(point => point.classificationCode === 6));
  assert.ok(item.visible_point && [5, 6].includes(item.visible_point.classificationCode));
  const payload = parsePayload(await readBounded(await verifyPin(item.page), 16 * 1024 ** 2));
  assert.equal(payload.sampleId, item.sample_id); assert.equal(payload.sourceId, item.source_id); assert.equal(payload.width, item.width); assert.equal(payload.height, item.height);
  assert.deepEqual(payload.sourceAgeApi, UNKNOWN); assert.equal(payload.flags.research_only, true); for (const flag of FLAGS) assert.equal(payload.flags[flag], false);
  oracles.set(item.sample_id, { item, payload, numeric: decodeOracle(payload) });
}

const outputSetting = process.env.AGEMORPH_MASK_REVIEW_BROWSER_OUTPUT;
assert.equal(typeof outputSetting, 'string');
const output = isAbsolute(outputSetting) ? resolve(outputSetting) : inputPath(outputSetting);
assert.ok(withinRoot(output) && relative(root, output).split(sep).join('/').startsWith('output/research/'));
await mkdir(dirname(output), { recursive: true }); assert.equal(await realpath(dirname(output)), dirname(output));
await mkdir(output); // Every invocation owns a new evidence directory; old failures remain untouched.
await mkdir(resolve(output, 'downloads')); await mkdir(resolve(output, 'screenshots'));
const planPin = { path: relative(root, planPath).split(sep).join('/'), bytes: planBytes.length, sha256: digest(planBytes) };
const report = { schema_version: 1, protocol_id: PROTOCOL, status: 'running', started_at_utc: new Date().toISOString(), study_plan: planPin, inputs: [planPin, ...plan.inputs], export_report: plan.export_report, artifact_audit: plan.artifact_audit, expectations: plan.expectations, browser_runtime: plan.browser_runtime, research_only: true, review_complete: false, ...Object.fromEntries(FLAGS.map(flag => [flag, false])), browser: { channel: 'chrome', headless: true, args: ['--disable-gpu'], viewport: { width: 1440, height: 1000 }, device_scale_factor: 1 }, records: expectations.cases.map(item => ({ sample_id: item.sample_id, source_id: item.source_id, target_age_condition: item.target_age_condition, page: item.page, status: 'pending', checks: [], artifacts: [] })), external_requests: [], errors: [], integrity: { before: false, after_browser: false, after_report: false }, resources: { context_closed: false, browser_closed: false, pages_closed: 0 }, interpretation: 'Automated offline UI engineering checks only. No human mask review, true-occlusion finding, quality acceptance, registration or production capability.' };
let browser, context, fatalError, interrupted = false;
const interrupt = () => { interrupted = true; void browser?.close().catch(() => {}); };
process.once('SIGINT', interrupt); process.once('SIGTERM', interrupt);

async function verifyRuntime() {
  assert.equal(await realpath(process.execPath), await realpath(runtime.node_executable));
  assert.equal((await hashFile(process.execPath)).sha256, runtime.node_executable_sha256, 'Node executable drift.');
  assert.equal((await hashFile(runtime.browser_executable)).sha256, runtime.browser_executable_sha256, 'Chrome executable drift.');
  assert.equal(process.version, runtime.node); assert.equal(frontendRequire('@playwright/test/package.json').version, runtime.playwright_version);
}

async function recheck() {
  assert.equal(digest(await readBounded(planPath)), planPin.sha256, 'Browser plan drift.');
  for (const pin of planned.values()) await verifyPin(pin);
  await verifyRuntime();
}

function outputPin(path, bytes) { return { path: relative(root, path).split(sep).join('/'), bytes: bytes.length, sha256: digest(bytes) }; }

async function saveDownload(page, row, kind, expectedSelections) {
  const pending = page.waitForEvent('download', { timeout: 10000 });
  await page.locator('#export-note').click();
  const download = await pending; assert.equal(await download.failure(), null);
  const path = resolve(output, 'downloads', `${row.sample_id}--${kind}.json`);
  await assert.rejects(stat(path), { code: 'ENOENT' });
  await download.saveAs(path);
  const bytes = await readBounded(path), notes = JSON.parse(bytes.toString('utf8'));
  const { payload } = oracles.get(row.sample_id);
  assert.equal(notes.protocol_id, 'agemorph3d-mask-review-notes-v1'); assert.equal(notes.reviewer, 'automated-ui-check');
  assert.equal(notes.sample_id, row.sample_id); assert.equal(notes.source_id, row.source_id); assert.equal(notes.target_age_condition, row.target_age_condition);
  assert.deepEqual(notes.source_age_api, UNKNOWN); sameNumbers(notes.provenance, payload.provenance);
  assert.equal(notes.research_only, true); assert.equal(notes.review_complete, false); for (const flag of FLAGS) assert.equal(notes[flag], false);
  assert.equal(notes.observations.length, expectedSelections.length);
  notes.observations.forEach((observation, index) => { comparePoint(observation.selection, expectedSelections[index]); assert.ok(observation.text.includes('UI 工程验证')); assert.ok(Number.isFinite(Date.parse(observation.recorded_at))); });
  assert.ok(Number.isFinite(Date.parse(notes.recorded_at)));
  row.artifacts.push({ role: `notes_${kind}`, ...outputPin(path, bytes) });
  await page.waitForFunction(() => window.__maskWorkbenchEvidence.active.size === 0, null, { timeout: 5000 });
  const urls = await page.evaluate(() => ({ created: window.__maskWorkbenchEvidence.created.length, revoked: window.__maskWorkbenchEvidence.revoked.length, active: window.__maskWorkbenchEvidence.active.size }));
  assert.ok(urls.created > 0 && urls.revoked >= urls.created && urls.active === 0);
  assert.equal(await page.locator('a[download]').count(), 0);
  return { observations: notes.observations.length, urls, artifact: outputPin(path, bytes) };
}

try {
  await recheck(); report.integrity.before = true;
  browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--disable-gpu'], timeout: 30000 });
  report.browser.version = browser.version(); assert.equal(browser.version(), runtime.browser_version, 'Chrome version changed after freeze.');
  context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1, locale: 'zh-CN', acceptDownloads: true, serviceWorkers: 'block' });
  await context.addInitScript(installObservers);
  await context.route('**/*', route => {
    const url = route.request().url();
    if (/^(?:https?|wss?):/i.test(url)) { report.external_requests.push({ url, method: route.request().method() }); return route.abort('blockedbyclient'); }
    return route.continue();
  });
  report.index = { page: exported.artifacts.index, status: 'running' };
  const indexPage = await context.newPage(), indexErrors = [], indexNetwork = [];
  indexPage.on('pageerror', error => indexErrors.push(textError(error)));
  indexPage.on('console', message => { if (message.type() === 'error') indexErrors.push(message.text()); });
  indexPage.on('request', request => { if (/^(?:https?|wss?):/i.test(request.url())) indexNetwork.push(request.url()); });
  indexPage.on('websocket', socket => indexNetwork.push(socket.url()));
  try {
    await indexPage.goto(pathToFileURL(inputPath(exported.artifacts.index.path)).href, { waitUntil: 'load', timeout: 30000 });
    const links = await indexPage.locator('a').evaluateAll(items => items.map(item => ({ href: item.getAttribute('href'), label: item.textContent })));
    assert.equal(links.length, 12);
    assert.deepEqual(links.map(link => link.href).sort(), expectations.cases.map(item => `cases/${item.sample_id}.html`).sort());
    const first = expectations.cases[0];
    await Promise.all([indexPage.waitForURL(pathToFileURL(inputPath(first.page.path)).href), indexPage.locator(`a[href="cases/${first.sample_id}.html"]`).click()]);
    await ready(indexPage); assert.equal(await selected(indexPage), null); assert.equal(await indexPage.locator('#observations-list li').count(), 0);
    assert.deepEqual(indexErrors, []); assert.deepEqual(indexNetwork, []);
    report.index = { page: exported.artifacts.index, status: 'passed', links: 12, actual_anchor_navigation: true, no_selection: true, external_requests: 0, errors: [] };
  } catch (error) { report.index.status = 'failed'; report.index.error = textError(error); report.errors.push(textError(error)); }
  finally { await indexPage.close().then(() => { report.resources.pages_closed += 1; }).catch(error => report.errors.push(textError(error))); }
  for (const row of report.records) {
    if (interrupted) { row.status = 'failed'; row.error = 'Interrupted before case execution.'; continue; }
    const { item, payload, numeric } = oracles.get(row.sample_id);
    const unknown = item.points.find(point => point.classificationCode < 2);
    const page = await context.newPage();
    const consoleErrors = [], consoleMessages = [], pageErrors = [], network = [], downloads = [];
    page.setDefaultTimeout(10000);
    page.on('console', message => { const entry = { type: message.type(), text: message.text() }; consoleMessages.push(entry); if (message.type() === 'error') consoleErrors.push(entry); });
    page.on('pageerror', error => pageErrors.push(textError(error)));
    page.on('request', request => { if (/^(?:https?|wss?):/i.test(request.url())) network.push(request.url()); });
    page.on('websocket', socket => network.push(socket.url()));
    page.on('download', download => downloads.push(download.suggestedFilename()));
    const check = async (name, action) => {
      const entry = { name, status: 'running' }; row.checks.push(entry);
      try { entry.observed = await action(); entry.status = 'passed'; }
      catch (error) { entry.status = 'failed'; entry.error = textError(error); }
    };
    try {
      await check('load_and_initial_state', async () => {
        await page.goto(pathToFileURL(inputPath(item.page.path)).href, { waitUntil: 'load', timeout: 30000 }); await ready(page);
        assert.equal(await page.locator('#overlay-layer').inputValue(), 'none'); assert.equal(await page.locator('#landmark-mode').inputValue(), 'off'); assert.equal(await page.locator('#show-regions').isChecked(), false);
        assert.equal(await selected(page), null); assert.equal(await page.locator('#add-observation').isDisabled(), true); assert.equal(await page.locator('#export-note').isDisabled(), true);
        assert.deepEqual(await page.locator('#target-canvas').evaluate(canvas => [canvas.width, canvas.height]), [item.width, item.height]);
        assert.deepEqual(await page.locator('#uv-canvas').evaluate(canvas => [canvas.width, canvas.height]), [256, 256]);
        return { page_url: page.url(), ready: true, no_selection: true };
      });
      if (row.checks[0].status !== 'passed') throw new Error('Page did not initialize; remaining controls cannot be exercised.');

      await check('original_masks_stages_and_opacity_pixels', async () => {
        const samples = item.target_pixel_samples; assert.ok(samples.length > 0);
        comparePixels(await canvasPixels(page, 'target-canvas', samples), samples.map(pixel => pixel.rgba));
        const observations = [];
        for (const layer of ['allowed', 'occluded', 'stages']) {
          await page.locator('#overlay-layer').selectOption(layer);
          const expected = samples.map(sample => {
            const active = layer === 'stages' || Boolean(sample[layer]);
            const color = layer === 'allowed' ? STAGES[0] : layer === 'occluded' ? STAGES[4] : STAGES[sample.reasonCode];
            return active ? sample.rgba.map((channel, index) => index === 3 ? 255 : Math.round(channel * 0.55 + color[index] * 0.45)) : sample.rgba;
          });
          const pixels = await canvasPixels(page, 'target-canvas', samples); comparePixels(pixels, expected, 2);
          observations.push({ layer, opacity: 0.45, sampled_pixels: pixels.length, tolerance: 2 });
        }
        await page.locator('#overlay-opacity').focus(); await page.locator('#overlay-opacity').press('Home');
        comparePixels(await canvasPixels(page, 'target-canvas', samples), samples.map(pixel => pixel.rgba));
        await page.locator('#overlay-opacity').press('End');
        comparePixels(await canvasPixels(page, 'target-canvas', samples), samples.map(pixel => STAGES[pixel.reasonCode]));
        await page.locator('#overlay-opacity').press('Home'); for (let index = 0; index < 9; index += 1) await page.locator('#overlay-opacity').press('ArrowRight');
        assert.equal(await page.locator('#overlay-opacity').inputValue(), '0.45');
        await page.locator('#overlay-layer').selectOption('none'); return observations;
      });

      await check('landmark_and_independent_region_drawings', async () => {
        await cleanControls(page);
        const baseline = await page.evaluateHandle(() => { const canvas = document.getElementById('target-canvas'); return canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data; });
        const observed = { landmarks: [], regions: [] };
        try {
          for (const mode of ['continuous', 'rounded', 'both', 'off']) {
            await page.locator('#landmark-mode').selectOption(mode); const changed = await canvasDifference(page, baseline);
            assert.ok(mode === 'off' ? changed === 0 : changed > 0, `Landmark mode ${mode} did not produce expected drawing.`); observed.landmarks.push({ mode, changed_pixels: changed });
          }
          const toggles = page.locator('#region-toggles input'); assert.equal(await toggles.count(), 4);
          for (let index = 0; index < 4; index += 1) await toggles.nth(index).uncheck();
          await page.locator('#show-regions').check(); assert.equal(await canvasDifference(page, baseline), 0);
          for (let index = 0; index < 4; index += 1) {
            await toggles.nth(index).check(); const changed = await canvasDifference(page, baseline); assert.ok(changed > 0, `Region ${index} did not draw.`);
            observed.regions.push({ region: REGIONS[index], changed_pixels: changed }); await toggles.nth(index).uncheck(); assert.equal(await canvasDifference(page, baseline), 0);
          }
          for (let index = 0; index < 4; index += 1) await toggles.nth(index).check();
          assert.ok(await canvasDifference(page, baseline) > 0); await page.locator('#show-regions').uncheck(); assert.equal(await canvasDifference(page, baseline), 0);
        } finally { await baseline.dispose(); }
        return observed;
      });

      await check('uv_classification_and_original_atlas_pixels', async () => {
        await page.locator('#uv-mode').selectOption('classification');
        comparePixels(await canvasPixels(page, 'uv-canvas', item.points.map(point => ({ x: point.uv.column, y: point.uv.row }))), item.points.map(point => CLASSES[point.classificationCode]));
        await page.locator('#uv-mode').selectOption('atlas'); comparePixels(await canvasPixels(page, 'uv-canvas', item.atlas_pixel_samples), item.atlas_pixel_samples.map(pixel => pixel.rgba));
        assert.ok(item.atlas_pixel_samples.some(pixel => pixel.rgba[3] === 0));
        await page.locator('#uv-mode').selectOption('classification'); return { class_samples: item.points.length, atlas_samples: item.atlas_pixel_samples.length, tolerance: 0 };
      });

      await check('actual_uv_clicks_original_correspondence_and_unknown_clear', async () => {
        const observed = [];
        for (const point of [...item.points.filter(point => point.classificationCode >= 2), ...item.points.filter(point => point.classificationCode < 2)]) {
          const actual = await clickUV(page, point.uv); comparePoint(actual, point); observed.push({ uv: point.uv, classification: point.classificationCode, exact_saved_numbers: true });
        }
        return observed;
      });

      await check('target_nearest_after_zoom_and_no_hit_clear', async () => {
        await cleanControls(page, unknown);
        const observations = [];
        for (const zoom of ['1', '2', 'fit']) {
          await page.locator('#target-zoom').selectOption(zoom); assert.deepEqual(await page.locator('#target-canvas').evaluate(canvas => [canvas.width, canvas.height]), [item.width, item.height]);
          const click = await clickTarget(page, item.visible_point.targetXYZ.slice(0, 2)); const expected = nearestOracle(numeric, click.captured); assert.ok(expected && expected.distance <= 3);
          const original = pointFromOracle(numeric, expected.index); sameNumbers(click.selection, original); assert.equal(click.selection.approximate, true); sameNumbers(click.selection.selectionDistance, expected.distance);
          observations.push({ zoom, captured: click.captured, expected_uv: original.uv, distance: expected.distance });
        }
        const miss = await clickTarget(page, [0, 0]); assert.equal(nearestOracle(numeric, miss.captured), null, 'Frozen (0,0) must be a genuine no-hit query.');
        assert.equal(miss.selection, null); assert.equal(await page.locator('#add-observation').isDisabled(), true); return { selections: observations, no_hit_cleared: true };
      });

      await check('review_draft_download_exact_snapshots_and_blob_disposal', async () => {
        const current = await clickUV(page, item.visible_point.uv); comparePoint(current, item.visible_point);
        await page.locator('#review-notes').fill('UI 工程验证：自动化点位与下载检查，不是人工遮罩质量审查。'); await page.locator('#add-observation').click();
        assert.equal(await page.locator('#observations-list li').count(), 1);
        await page.locator('#reviewer').fill(''); const previous = downloads.length; await page.locator('#export-note').click(); await page.waitForTimeout(200);
        assert.equal(downloads.length, previous); assert.ok((await page.locator('#status').textContent()).includes('填写审查者')); assert.equal(await page.locator('#reviewer').evaluate(element => element === document.activeElement), true);
        await page.locator('#reviewer').fill('automated-ui-check'); const visible = await saveDownload(page, row, 'visible', [item.visible_point]);
        const unknownSelection = await clickUV(page, unknown.uv); comparePoint(unknownSelection, unknown);
        await page.locator('#review-notes').fill('UI 工程验证：未知 texel 的对应字段必须保留 null。'); await page.locator('#add-observation').click();
        const withUnknown = await saveDownload(page, row, 'with-unknown', [item.visible_point, unknown]);
        return { empty_reviewer_blocked: true, visible, with_unknown: withUnknown };
      });

      if (row === report.records[0]) await check('cross_source_anchor_navigation_back_and_fresh_interaction', async () => {
        const other = expectations.cases.find(candidate => candidate.source_id !== row.source_id), otherOracle = oracles.get(other.sample_id);
        const link = page.locator(`#case-navigation a[href="${other.sample_id}.html"]`); assert.equal(await link.count(), 1);
        await Promise.all([page.waitForURL(pathToFileURL(inputPath(other.page.path)).href), link.click()]); await ready(page);
        assert.equal(await selected(page), null); assert.equal(await page.locator('#observations-list li').count(), 0); assert.equal(await page.locator('#reviewer').inputValue(), '');
        comparePoint(await clickUV(page, otherOracle.item.visible_point.uv), otherOracle.item.visible_point);
        await page.goBack({ waitUntil: 'load' }); await ready(page);
        assert.equal(page.url(), pathToFileURL(inputPath(item.page.path)).href); assert.equal(await selected(page), null); assert.equal(await page.locator('#observations-list li').count(), 0); assert.equal(await page.locator('#reviewer').inputValue(), '');
        comparePoint(await clickUV(page, item.visible_point.uv), item.visible_point); // Detects restored documents with disposed listeners.
        await page.locator('#review-notes').fill('UI 工程验证：返回导航后交互仍可用。'); await page.locator('#add-observation').click(); assert.equal(await page.locator('#observations-list li').count(), 1);
        return { full_document_navigation: true, destination_source: other.source_id, back_cleared: true, interaction_after_back: true };
      });

      if (row === report.records[0]) await check('responsive_900px_true_uv_click', async () => {
        await page.setViewportSize({ width: 900, height: 1000 }); comparePoint(await clickUV(page, unknown.uv), unknown); comparePoint(await clickUV(page, item.visible_point.uv), item.visible_point);
        await page.setViewportSize({ width: 1440, height: 1000 }); return { viewport_width: 900, actual_uv_click: true };
      });

      if ((row.source_id === 'fgnet-004a63' && row.target_age_condition === 20) || (row.source_id === 'fgnet-006a55' && row.target_age_condition === 55)) await check('review_overview_screenshot', async () => {
        await page.locator('#target-zoom').selectOption('fit'); await page.locator('#overlay-layer').selectOption('stages'); await page.locator('#landmark-mode').selectOption('both'); await page.locator('#show-regions').check();
        await page.evaluate(() => { const viewport = document.getElementById('target-viewport'); viewport.scrollTop = 0; viewport.scrollLeft = 0; window.scrollTo(0, 0); });
        const path = resolve(output, 'screenshots', `${row.sample_id}--overview.png`); await assert.rejects(stat(path), { code: 'ENOENT' });
        const bytes = await page.screenshot({ path, fullPage: true, timeout: 15000 }); const pin = outputPin(path, bytes); row.artifacts.push({ role: 'overview', ...pin }); return pin;
      });

      await check('console_network_and_runtime_state', async () => {
        assert.deepEqual(consoleErrors, []); assert.deepEqual(pageErrors, []); assert.deepEqual(network, []);
        const resource = await page.evaluate(() => ({ active_blob_urls: window.__maskWorkbenchEvidence.active.size, document_url: document.URL, csp: document.querySelector('meta[http-equiv="Content-Security-Policy"]').content }));
        assert.equal(resource.active_blob_urls, 0); assert.ok(resource.document_url.startsWith('file:')); assert.ok(resource.csp.includes("connect-src 'none'"));
        return { console_errors: 0, page_errors: 0, external_http_ws_requests: 0, downloads: downloads.length, ...resource };
      });
    } catch (error) { row.error = textError(error); }
    finally {
      row.console = consoleMessages; row.page_errors = pageErrors; row.external_requests = network;
      await page.close().then(() => { report.resources.pages_closed += 1; }).catch(error => { row.close_error = textError(error); });
      row.status = !row.error && !row.close_error && row.checks.length > 0 && row.checks.every(entry => entry.status === 'passed') ? 'passed' : 'failed';
      console.log(JSON.stringify({ sample_id: row.sample_id, status: row.status, passed_checks: row.checks.filter(entry => entry.status === 'passed').length, failed_checks: row.checks.filter(entry => entry.status === 'failed').length }));
    }
  }
} catch (error) { fatalError = error; report.errors.push(textError(error)); }
finally {
  if (context) await context.close().then(() => { report.resources.context_closed = true; }).catch(error => report.errors.push(textError(error)));
  if (browser) await browser.close().then(() => { report.resources.browser_closed = true; }).catch(error => report.errors.push(textError(error)));
  process.removeListener('SIGINT', interrupt); process.removeListener('SIGTERM', interrupt);
  for (const row of report.records) if (row.status === 'pending') { row.status = 'failed'; row.error = 'Browser initialization failed or interrupted; case retained in denominator.'; }
}

try { await recheck(); report.integrity.after_browser = true; }
catch (error) { report.errors.push(textError(error)); for (const row of report.records) row.status = 'invalidated_input_drift'; }
if (report.external_requests.length) report.errors.push('Unexpected external network requests were blocked.');
report.finished_at_utc = new Date().toISOString();
report.summary = { requested_targets: 12, requested_sources: 3, statuses: Object.fromEntries([...new Set(report.records.map(row => row.status))].map(status => [status, report.records.filter(row => row.status === status).length])), all_requested_verified: report.records.every(row => row.status === 'passed') && report.errors.length === 0 && report.integrity.before && report.integrity.after_browser };
report.status = report.summary.all_requested_verified ? 'passed' : 'failed';
const reportPath = resolve(output, 'report.json');
// A success is published together with a hash-bound verification receipt below.
// If the final post-write recheck fails, only this invocation's report is invalidated.
report.integrity.after_report = true;
await writeFile(reportPath, JSON.stringify(report, null, 2) + '\n', { flag: 'wx' });
try {
  await recheck(); report.integrity.after_report = true;
  // This report belongs only to this invocation. Preserve a separate final verification receipt.
  const reportBytes = await readBounded(reportPath);
  await writeFile(resolve(output, 'verification.json'), JSON.stringify({ schema_version: 1, protocol_id: PROTOCOL, recorded_at_utc: new Date().toISOString(), report: outputPin(reportPath, reportBytes), all_inputs_unchanged_after_report: true, runtime_unchanged_after_report: true, report_integrity_after_report: true, research_only: true, human_review_completed: false, g3_complete: false }, null, 2) + '\n', { flag: 'wx' });
} catch (error) {
  report.integrity.after_report = false; report.errors.push(textError(error)); report.status = 'invalidated_input_drift'; report.summary.all_requested_verified = false;
  for (const row of report.records) row.status = 'invalidated_input_drift';
  report.summary.statuses = { invalidated_input_drift: 12 };
  await unlink(reportPath); // Delete only the just-created report, never any inherited evidence.
  await writeFile(reportPath, JSON.stringify(report, null, 2) + '\n', { flag: 'wx' });
}
console.log(JSON.stringify({ report: relative(root, reportPath).split(sep).join('/'), status: report.status, ...report.summary, resources: report.resources, integrity: report.integrity }));
if (fatalError || report.status !== 'passed') process.exitCode = 1;
