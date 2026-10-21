import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createServer as createHttpServer } from "node:http";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium, expect } from "@playwright/test";
import { createServer as createViteServer } from "vite";

// Explicit offline research only. This runner never provides health/reconstruct responses.
const meshPath = requiredPath("AGEMORPH_RESEARCH_MESH");
const resultPath = requiredPath("AGEMORPH_RESEARCH_RESULT");
const output = resolve(process.env.AGEMORPH_RESEARCH_OUTPUT ??
  fileURLToPath(new URL("../../output/backend/b23/browser/", import.meta.url)));
const frontendPort = port("AGEMORPH_RESEARCH_VITE_PORT", 5175);
const assetPort = port("AGEMORPH_RESEARCH_ASSET_PORT", 18003);
const requireTexture = process.env.AGEMORPH_RESEARCH_REQUIRE_TEXTURE === "1";
const textureKind = process.env.AGEMORPH_RESEARCH_TEXTURE_KIND ?? "observed_photo";
assert.ok(["observed_photo", "generated_target"].includes(textureKind), "Unknown texture research kind.");
const generatedTarget = textureKind === "generated_target";
if (generatedTarget) assert.equal(requireTexture, true, "Generated-target research needs texture checks.");
assert.notEqual(frontendPort, assetPort, "The owned servers need separate ports.");
const frontend = `http://127.0.0.1:${frontendPort}`;
const assets = `http://127.0.0.1:${assetPort}`;
const originalUrl = `${assets}/api/assets/research/mesh.glb`;
const exportedUrl = `${assets}/api/assets/research/exported.glb`;
const original = await readFile(meshPath);
const metadata = JSON.parse(await readFile(resultPath, "utf8"));
const originalJson = standaloneGlb(original);
if (generatedTarget) {
  assert.match(metadata.source_frame?.source_topology_sha256, /^[a-f0-9]{64}$/);
  assert.equal(originalJson.extras?.topology_id,
    `tddfa-bfm-canon-v1-${metadata.source_frame.source_topology_sha256}`,
    "Generated target topology must match the source frame fingerprint.");
  if (metadata.topology_id !== undefined)
    assert.equal(metadata.topology_id, originalJson.extras.topology_id);
}
const options = {
  asset_mode: "static",
  topology_id: generatedTarget ? originalJson.extras.topology_id : metadata.topology_id,
  source_age: metadata.source_age,
  ...(metadata.capabilities ? { capabilities: metadata.capabilities } : {}),
};
validateOptions(options);
if (metadata.asset_mode !== undefined) assert.equal(metadata.asset_mode, "static");
const registration = generatedTarget ? registeredTarget(originalJson) : undefined;
const sourceCoordinateMetadata = generatedTarget
  ? extraValues(originalJson, "coordinate_metadata")[0] : undefined;
if (generatedTarget) {
  assert.equal(registration.kind, "sam_generated_registered_uv");
  assert.equal(registration.age_quality_accepted, false);
  assert.equal(registration.identity_quality_accepted, false);
  assert.equal(metadata.source_age.method, "unknown");
  assert.equal(metadata.source_age.value, null);
  assert.ok(sourceCoordinateMetadata?.source_center &&
    Number.isFinite(sourceCoordinateMetadata.source_to_canonical_uniform_scale),
  "Generated target must retain its original source canonical frame.");
}
if (requireTexture) {
  assert.ok(originalJson.images?.length, "Texture verification needs an embedded image.");
  assert.equal(metadata.capabilities?.age_morph, false, "Photo UV evidence cannot enable age shape.");
  assert.equal(metadata.capabilities?.age_texture, false, "Photo UV evidence cannot enable age texture.");
  for (const mesh of originalJson.meshes ?? []) for (const primitive of mesh.primitives) {
    assert.notEqual(primitive.attributes?.TEXCOORD_0, undefined, "Textured mesh needs atlas UV.");
    assert.notEqual(originalJson.materials?.[primitive.material]?.pbrMetallicRoughness?.baseColorTexture?.index,
      undefined, "Textured mesh needs an embedded base color map.");
  }
}
await mkdir(output, { recursive: true });

const report = {
  evidenceKind: generatedTarget ? "offline-generated-target-atlas-browser-roundtrip"
    : "offline-real-model-asset-browser-roundtrip",
  serviceInferenceVerified: false,
  g1Accepted: false,
  g3Accepted: false,
  photoTextureVerification: requireTexture && !generatedTarget,
  generatedTargetAtlasVerification: generatedTarget,
  textureResearchKind: textureKind,
  ageTextureVerified: false,
  routeMocks: false,
  productionBuild: false,
  renderer: "Chromium software WebGL (SwiftShader)",
  startedAt: new Date().toISOString(),
  input: { meshPath, resultPath, bytes: original.length, sha256: sha256(original),
    mesh_id: metadata.mesh_id ?? null, ...options,
    ...(generatedTarget ? { registered_target_texture: registration,
      sourceCoordinateMetadata } : {}) },
  frontend, assetServer: assets, results: [], status: "running",
};
let exported;
const requests = [];
const assetServer = createHttpServer((request, response) => {
  const origin = request.headers.origin;
  if (origin && origin !== frontend) {
    response.writeHead(403).end();
    return;
  }
  const headers = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
  if (origin) headers["Access-Control-Allow-Origin"] = frontend;
  const pathname = new URL(request.url ?? "/", assets).pathname;
  requests.push({ method: request.method, pathname });
  if (request.method !== "GET" && request.method !== "HEAD") {
    response.writeHead(405, headers).end();
    return;
  }
  const bytes = pathname === "/api/assets/research/mesh.glb" ? original
    : pathname === "/api/assets/research/exported.glb" ? exported : undefined;
  if (!bytes) {
    response.writeHead(404, headers).end();
    return;
  }
  response.writeHead(200, { ...headers, "Content-Type": "model/gltf-binary",
    "Content-Length": bytes.length });
  response.end(request.method === "HEAD" ? undefined : bytes);
});
let vite;
let browser;
let failure;
let abortRequested = false;
const abortResearch = () => {
  abortRequested = true;
  browser?.close().catch(() => {});
};
const onParentMessage = (message) => {
  if (message?.type === "abort-research") abortResearch();
};
process.on("message", onParentMessage);
process.once("SIGINT", abortResearch);
process.once("SIGTERM", abortResearch);
try {
  await new Promise((resolveListen, reject) => {
    assetServer.once("error", reject);
    assetServer.listen(assetPort, "127.0.0.1", resolveListen);
  });
  vite = await createViteServer({
    root: fileURLToPath(new URL("../", import.meta.url)),
    configFile: false,
    server: { host: "127.0.0.1", port: frontendPort, strictPort: true, open: false },
    plugins: [{
      name: "agemorph-offline-research-harness",
      resolveId(id) {
        if (id === "/__research_modules.js") return "\0agemorph-research-modules";
      },
      load(id) {
        if (id === "\0agemorph-research-modules") return `
          export { FaceViewer } from '/src/viewer.ts';
          export * as THREE from 'three';
          export { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';`;
      },
      configureServer(server) {
        server.middlewares.use((request, response, next) => {
          if (request.url?.split("?")[0] !== "/__research_static_mesh") return next();
          response.setHeader("Content-Type", "text/html; charset=utf-8");
          response.end(`<!doctype html><html lang="zh-CN"><meta charset="utf-8">
            <title>AgeMorph3D offline real-mesh research verification</title>
            <style>body{margin:0;background:#0a0e1a;color:#d9eeee;font:16px sans-serif}
            header{padding:18px 24px}h1{font-size:20px;margin:0 0 8px}
            p{margin:5px 0;color:#a4bcc8}#research-viewer{height:760px;margin:0 20px}
            #research-state{color:#70dfcb}</style><header>
            <h1>${generatedTarget ? "SAM 目标图集 · 共同 UV 离线研究" : "真实 CPU 网格 · 离线研究验证"}</h1>
            <p>使用实际 FaceViewer 查看、导出和再导入；未连接模型服务，G1 尚未签收。</p>
            ${requireTexture ? generatedTarget
              ? "<p>SAM 目标图已注册共同 UV；年龄与身份质量未签收，G3 未通过。</p>"
              : "<p>照片 UV 贴图验证，未生成年龄纹理，G3 尚未签收。</p>" : ""}
            <p id="research-state">正在加载真实静态资产</p></header>
            <div id="research-viewer"></div></html>`);
        });
      },
    }],
  });
  await vite.listen();
  for (const channel of ["chrome", "msedge"]) {
    assert.equal(abortRequested, false, "Research run was interrupted.");
    exported = undefined;
    browser = await chromium.launch({ channel, headless: true,
      args: ["--enable-unsafe-swiftshader", "--use-angle=swiftshader"] });
    assert.equal(abortRequested, false, "Research run was interrupted.");
    const page = await browser.newPage({ viewport: { width: 1280, height: 920 },
      locale: "zh-CN", acceptDownloads: true, reducedMotion: "reduce" });
    page.setDefaultTimeout(30_000);
    const errors = [];
    const externalRequests = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("request", (request) => {
      const url = new URL(request.url());
      if (["http:", "https:"].includes(url.protocol) &&
        url.origin !== frontend && url.origin !== assets) externalRequests.push(request.url());
    });
    await page.goto(`${frontend}/__research_static_mesh`);
    const initial = await page.evaluate(async ({ url, options }) => {
      const { FaceViewer, GLTFLoader, THREE } = await import("/__research_modules.js");
      window.researchErrors = [];
      window.researchStats = null;
      window.researchViewer = new FaceViewer(document.getElementById("research-viewer"), {
        onError: (message) => window.researchErrors.push(message),
        onStats: (stats) => { window.researchStats = stats; },
      });
      window.researchViewer.setAutoRotate(false);
      window.researchViewer.setBackground(false);
      await window.researchViewer.loadModel(url, options);
      window.researchViewer.setView("front");
      const bytes = await (await fetch(url, { cache: "no-store" })).arrayBuffer();
      const parsed = await new GLTFLoader().parseAsync(bytes, "");
      window.researchOriginal = parsed;
      const bounds = new THREE.Box3().setFromObject(parsed.scene);
      const primitives = [];
      parsed.scene.traverse((node) => {
        if (!node.isMesh) return;
        primitives.push({ vertices: node.geometry.getAttribute("position").count,
          triangles: (node.geometry.index?.count ?? node.geometry.getAttribute("position").count) / 3 });
      });
      document.getElementById("research-state").textContent =
        `${options.topology_id} · 原始静态网格 · 正面`;
      return { bounds: { min: bounds.min.toArray(), max: bounds.max.toArray() }, primitives };
    }, { url: originalUrl, options });
    const vertices = initial.primitives.reduce((sum, mesh) => sum + mesh.vertices, 0);
    const triangles = initial.primitives.reduce((sum, mesh) => sum + mesh.triangles, 0);
    assert.ok(vertices >= 3 && triangles >= 1);
    await page.waitForFunction(({ vertices, triangles }) =>
      window.researchStats?.vertices === vertices && window.researchStats?.triangles === triangles,
    { vertices, triangles });
    await expect(page.locator("#research-viewer canvas")).toBeVisible();
    const frontPath = join(output, `original-front-${channel}.png`);
    await page.screenshot({ path: frontPath });
    await page.evaluate(() => {
      window.researchViewer.setView("side");
      document.getElementById("research-state").textContent += " · 侧面";
    });
    await rendered(page);
    const sidePath = join(output, `original-side-${channel}.png`);
    await page.screenshot({ path: sidePath });

    const downloadEvent = page.waitForEvent("download");
    await page.evaluate(async () => {
      const blob = await window.researchViewer.exportGLB();
      const anchor = document.createElement("a");
      const url = URL.createObjectURL(blob);
      anchor.href = url;
      anchor.download = "AgeMorph3D-research-original.glb";
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
    });
    const download = await downloadEvent;
    assert.equal(await download.failure(), null);
    const exportedPath = join(output, `exported-${channel}.glb`);
    await download.saveAs(exportedPath);
    exported = await readFile(exportedPath);
    const exportJson = standaloneGlb(exported);
    if (generatedTarget)
      assert.deepEqual(registeredTarget(exportJson, registration.target_sample_id), registration,
        "Viewer export must preserve the complete generated-texture registration provenance.");
    if (generatedTarget)
      assert.ok(extraValues(exportJson, "coordinate_metadata").some((value) =>
        stableJSON(value) === stableJSON(sourceCoordinateMetadata)),
      "Viewer export must retain the unchanged source canonical frame metadata.");
    const root = exportJson.nodes?.find((node) => node.name === "AgeMorph3D_Loaded_Model");
    assert.ok(root, "Actual viewer export must preserve its model root.");
    assert.equal(root.extras.asset_mode, "static");
    assert.equal(root.extras.topology_id, options.topology_id);
    assert.deepEqual(root.extras.source_age, options.source_age);
    for (const key of ["age", "ageAnchors", "displayAge", "texture_age"])
      assert.equal(root.extras[key], undefined, `Static research export cannot invent ${key}.`);
    const roundtrip = await page.evaluate(async ({ url, options, requireTexture, generatedTarget, registration }) => {
      const { FaceViewer, GLTFLoader, THREE } = await import("/__research_modules.js");
      const bytes = await (await fetch(url, { cache: "no-store" })).arrayBuffer();
      const parsed = await new GLTFLoader().parseAsync(bytes, "");
      const meshes = (scene) => {
        const found = [];
        scene.traverse((node) => { if (node.isMesh) found.push(node); });
        return found;
      };
      const before = meshes(window.researchOriginal.scene);
      const after = meshes(parsed.scene);
      if (before.length !== after.length) throw new Error("Roundtrip changed mesh count.");
      if (generatedTarget) {
        const stable = (value) => Array.isArray(value) ? value.map(stable)
          : value && typeof value === "object" ? Object.fromEntries(
            Object.keys(value).sort().map((key) => [key, stable(value[key])])) : value;
        const signature = (value) => JSON.stringify(stable(value));
        const registrations = [];
        for (const scene of [window.researchOriginal.scene, parsed.scene]) {
          const found = [];
          scene.traverse((node) => {
            const value = node.userData?.registered_target_texture;
            if (value?.target_sample_id === registration.target_sample_id) found.push(value);
          });
          if (!found.length || found.some((value) => signature(value) !== signature(registration)))
            throw new Error("Loaded scene lost generated-texture registration provenance.");
          registrations.push(found[0]);
        }
        if (signature(registrations[0]) !== signature(registrations[1]))
          throw new Error("Roundtrip changed generated-texture registration provenance.");
      }
      const comparisons = [];
      const textureSummary = async (mesh) => {
        const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
        const textures = [];
        for (const material of materials) {
          const texture = material.map;
          if (!texture) {
            if (requireTexture) throw new Error("Photo UV mesh is missing its base color texture.");
            textures.push(null);
            continue;
          }
          const image = texture.image;
          const width = image?.width;
          const height = image?.height;
          if (!Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1 || width * height > 16_000_000)
            throw new Error("Invalid decoded photo texture dimensions.");
          const canvas = document.createElement("canvas");
          canvas.width = width;
          canvas.height = height;
          const context = canvas.getContext("2d");
          if (!context) throw new Error("Cannot inspect decoded texture pixels.");
          context.drawImage(image, 0, 0);
          const pixels = context.getImageData(0, 0, width, height).data;
          const digest = await crypto.subtle.digest("SHA-256", pixels);
          const rgbaSha256 = [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, "0")).join("");
          let generatedSummary = {};
          if (generatedTarget) {
            const alpha = new Uint8Array(width * height);
            const unknownMask = new Uint8Array(width * height);
            let unknownTexels = 0;
            let opaqueTexels = 0;
            for (let index = 0; index < alpha.length; index++) {
              alpha[index] = pixels[index * 4 + 3];
              unknownMask[index] = alpha[index] === 0 ? 1 : 0;
              unknownTexels += unknownMask[index];
              opaqueTexels += alpha[index] === 255 ? 1 : 0;
            }
            const hex = async (data) => [...new Uint8Array(await crypto.subtle.digest("SHA-256", data))]
              .map((value) => value.toString(16).padStart(2, "0")).join("");
            generatedSummary = { alphaSha256: await hex(alpha), unknownMaskSha256: await hex(unknownMask),
              unknownTexels, opaqueTexels, partialAlphaTexels: alpha.length - unknownTexels - opaqueTexels,
              pbrMaterial: { color: material.color?.toArray(), metalness: material.metalness,
                roughness: material.roughness } };
          }
          textures.push({ width, height, rgbaSha256, flipY: texture.flipY,
            colorSpace: texture.colorSpace, uvChannel: texture.channel,
            offset: texture.offset.toArray(), repeat: texture.repeat.toArray(),
            rotation: texture.rotation, wrapS: texture.wrapS, wrapT: texture.wrapT,
            magFilter: texture.magFilter, minFilter: texture.minFilter,
            material: { opacity: material.opacity, transparent: material.transparent,
              alphaTest: material.alphaTest, side: material.side }, ...generatedSummary });
        }
        return textures;
      };
      for (let index = 0; index < before.length; index++) {
        const a = before[index].geometry;
        const b = after[index].geometry;
        const normals = a.getAttribute("normal");
        if (!normals || normals.count !== a.getAttribute("position").count)
          throw new Error("Original real mesh needs one normal per vertex.");
        let normalLengthError = 0;
        for (let vertex = 0; vertex < normals.count; vertex++) {
          const length = Math.hypot(normals.getX(vertex), normals.getY(vertex), normals.getZ(vertex));
          if (!Number.isFinite(length)) throw new Error("Original mesh has non-finite normals.");
          normalLengthError = Math.max(normalLengthError, Math.abs(length - 1));
        }
        if (normalLengthError > 1e-5) throw new Error("Original mesh normals are not unit length.");
        const attributes = {};
        for (const name of ["position", "normal", "uv"]) {
          const first = a.getAttribute(name);
          const second = b.getAttribute(name);
          if (!!first !== !!second) throw new Error(`Roundtrip changed ${name} availability.`);
          if (!first) continue;
          if (first.count !== second.count || first.itemSize !== second.itemSize)
            throw new Error(`Roundtrip changed ${name} dimensions.`);
          let maximumDifference = 0;
          for (let value = 0; value < first.array.length; value++) {
            if (!Number.isFinite(first.array[value]) || !Number.isFinite(second.array[value]))
              throw new Error(`Non-finite ${name}.`);
            maximumDifference = Math.max(maximumDifference, Math.abs(first.array[value] - second.array[value]));
          }
          if (maximumDifference > 1e-6) throw new Error(`Roundtrip changed ${name} values.`);
          attributes[name] = { count: first.count, itemSize: first.itemSize, maximumDifference };
          if (generatedTarget) {
            const digest = async (array) => [...new Uint8Array(await crypto.subtle.digest("SHA-256",
              new Uint8Array(array.buffer, array.byteOffset, array.byteLength)))]
              .map((value) => value.toString(16).padStart(2, "0")).join("");
            attributes[name].originalSha256 = await digest(first.array);
            attributes[name].exportedSha256 = await digest(second.array);
          }
        }
        if (!!a.index !== !!b.index || a.index?.count !== b.index?.count)
          throw new Error("Roundtrip changed index dimensions.");
        for (let value = 0; value < (a.index?.count ?? 0); value++) {
          const vertex = a.index.getX(value);
          if (!Number.isInteger(vertex) || vertex < 0 || vertex >= a.getAttribute("position").count)
            throw new Error("Original mesh triangle index is out of range.");
          if (vertex !== b.index.getX(value)) throw new Error("Roundtrip changed triangle indices.");
        }
        if (Object.values(b.morphAttributes).some((targets) => targets.length))
          throw new Error("Static roundtrip unexpectedly contains morph targets.");
        if (requireTexture && !attributes.uv) throw new Error("Photo UV mesh has no atlas coordinates.");
        const originalTextures = await textureSummary(before[index]);
        const exportedTextures = await textureSummary(after[index]);
        if (JSON.stringify(originalTextures) !== JSON.stringify(exportedTextures))
          throw new Error("Roundtrip changed decoded texture pixels or UV orientation metadata.");
        comparisons.push({ attributes, indexCount: a.index?.count ?? null, normalLengthError,
          textures: { original: originalTextures, exported: exportedTextures } });
      }
      const originalBounds = new THREE.Box3().setFromObject(window.researchOriginal.scene);
      const originalSize = originalBounds.getSize(new THREE.Vector3());
      const scale = 2.8 / Math.max(...originalSize.toArray());
      const expectedSize = originalSize.multiplyScalar(scale).toArray();
      const bounds = new THREE.Box3().setFromObject(parsed.scene);
      const actualSize = bounds.getSize(new THREE.Vector3()).toArray();
      const center = bounds.getCenter(new THREE.Vector3()).toArray();
      if (expectedSize.some((value, index) => Math.abs(value - actualSize[index]) > 1e-5) ||
        center.some((value) => Math.abs(value) > 1e-5))
        throw new Error("Roundtrip world bounds differ from the viewer normalization.");
      window.researchViewer.dispose();
      window.researchStats = null;
      window.researchViewer = new FaceViewer(document.getElementById("research-viewer"), {
        onError: (message) => window.researchErrors.push(message),
        onStats: (stats) => { window.researchStats = stats; },
      });
      window.researchViewer.setAutoRotate(false);
      window.researchViewer.setBackground(false);
      await window.researchViewer.loadModel(url, options);
      window.researchViewer.setView("front");
      document.getElementById("research-state").textContent =
        `${options.topology_id} · 浏览器导出文件已再导入 · 正面`;
      return { comparisons, expectedSize, actualSize, center };
    }, { url: exportedUrl, options, requireTexture, generatedTarget, registration });
    await page.waitForFunction(({ vertices, triangles }) =>
      window.researchStats?.vertices === vertices && window.researchStats?.triangles === triangles,
    { vertices, triangles });
    await rendered(page);
    const reimportPath = join(output, `reimport-front-${channel}.png`);
    await page.screenshot({ path: reimportPath });
    assert.deepEqual(await page.evaluate(() => window.researchErrors), []);
    assert.deepEqual(errors, []);
    assert.deepEqual(externalRequests, []);
    await page.evaluate(() => {
      window.researchViewer.dispose();
      for (const asset of [window.researchOriginal]) asset.scene.traverse((node) => {
        if (!node.isMesh) return;
        node.geometry.dispose();
        for (const material of Array.isArray(node.material) ? node.material : [node.material])
          material.dispose();
      });
    });
    report.results.push({ channel, version: browser.version(), vertices, triangles,
      initial, roundtrip, rootExtras: root.extras,
      exported: { path: exportedPath, bytes: exported.length, sha256: sha256(exported) },
      screenshots: { front: frontPath, side: sidePath, reimport: reimportPath },
      errors, externalRequests, status: "passed" });
    await browser.close();
    browser = undefined;
  }
  report.status = "passed";
} catch (error) {
  failure = error;
  report.status = "failed";
  report.error = error instanceof Error ? error.stack : String(error);
} finally {
  const cleanup = await Promise.allSettled([
    browser?.close(),
    vite?.close(),
    assetServer.listening ? new Promise((resolveClose, reject) => {
      assetServer.close((error) => error ? reject(error) : resolveClose());
      assetServer.closeAllConnections();
    }) : undefined,
  ]);
  report.ownedServersClosed = cleanup.every((result) => result.status === "fulfilled");
  report.interrupted = abortRequested;
  report.assetRequests = requests;
  report.finishedAt = new Date().toISOString();
  report.input.glbGenerator = originalJson.asset.generator ?? null;
  try {
    await writeFile(join(output, "static-mesh-research.json"), JSON.stringify(report, null, 2));
  } finally {
    process.removeListener("message", onParentMessage);
    process.removeListener("SIGINT", abortResearch);
    process.removeListener("SIGTERM", abortResearch);
    if (process.connected) process.disconnect();
  }
}
if (failure) throw failure;
assert.equal(report.ownedServersClosed, true);
console.log(JSON.stringify({ passed: report.results.length, output, evidenceKind: report.evidenceKind,
  serviceInferenceVerified: false, g1Accepted: false, g3Accepted: false,
  photoTextureVerification: requireTexture && !generatedTarget,
  generatedTargetAtlasVerification: generatedTarget, ownedServersClosed: report.ownedServersClosed }));

function requiredPath(name) {
  assert.ok(process.env[name], `Set ${name} to an explicit local file.`);
  return resolve(process.env[name]);
}

function port(name, fallback) {
  const value = Number(process.env[name] ?? fallback);
  assert.ok(Number.isInteger(value) && value >= 1024 && value <= 65535, `Invalid ${name}.`);
  return value;
}

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function registeredTarget(document, targetId) {
  const registrations = extraValues(document, "registered_target_texture")
    .filter((value) => !targetId || value.target_sample_id === targetId);
  assert.ok(registrations.length, "GLB is missing generated-target registration provenance.");
  for (const registration of registrations) assert.deepEqual(registration, registrations[0]);
  return registrations[0];
}

function extraValues(document, key) {
  const values = [];
  const visit = (value) => {
    if (!value || typeof value !== "object") return;
    if (value[key]) values.push(value[key]);
    for (const child of Object.values(value)) visit(child);
  };
  visit(document);
  return values;
}

function stableJSON(value) {
  const stable = (item) => Array.isArray(item) ? item.map(stable)
    : item && typeof item === "object" ? Object.fromEntries(
      Object.keys(item).sort().map((key) => [key, stable(item[key])])) : item;
  return JSON.stringify(stable(value));
}

function validateOptions(value) {
  assert.match(value.topology_id, /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}$/);
  const age = value.source_age;
  assert.ok(age && ["unknown", "user", "estimated"].includes(age.method));
  if (age.method === "unknown") {
    assert.equal(age.value, null);
    assert.equal(age.calibration_id, null);
  } else {
    assert.ok(Number.isFinite(age.value) && age.value >= 20 && age.value <= 70);
    if (age.method === "user") assert.equal(age.calibration_id, null);
    else assert.match(age.calibration_id, /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}$/);
  }
}

function standaloneGlb(bytes) {
  assert.ok(bytes.length >= 28 && bytes.length <= 64 * 1024 * 1024);
  assert.equal(bytes.toString("ascii", 0, 4), "glTF");
  assert.equal(bytes.readUInt32LE(4), 2);
  assert.equal(bytes.readUInt32LE(8), bytes.length);
  assert.equal(bytes.readUInt32LE(16), 0x4e4f534a);
  const length = bytes.readUInt32LE(12);
  assert.ok(20 + length <= bytes.length);
  const json = JSON.parse(bytes.toString("utf8", 20, 20 + length));
  assert.equal(json.asset.version, "2.0");
  assert.ok(json.buffers?.length === 1 && json.buffers[0].uri === undefined);
  for (const image of json.images ?? []) assert.equal(image.uri, undefined);
  for (const mesh of json.meshes ?? []) for (const primitive of mesh.primitives) {
    assert.ok(!primitive.targets?.length, "Research static asset contains morph targets.");
    assert.ok(primitive.mode === undefined || primitive.mode === 4, "Expected triangle primitives.");
  }
  return json;
}

async function rendered(page) {
  await page.evaluate(() => new Promise((resolveFrame) =>
    requestAnimationFrame(() => requestAnimationFrame(resolveFrame))));
}
