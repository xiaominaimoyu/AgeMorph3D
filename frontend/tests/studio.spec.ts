import { test, expect } from "@playwright/test";
import type { Page, TestInfo, WebSocketRoute } from "@playwright/test";
import { readFile } from "node:fs/promises";

const API = "http://127.0.0.1:8000";
const IDENTITY = { R: [1, 0, 0, 0, 1, 0, 0, 0, 1], t: [0, 0, 0] };
const failures = new WeakMap<Page, string[]>();
const ageResultFields = {
  topology_id: "test_topology",
  asset_mode: "age_morph",
  capabilities: { age_morph: true, age_texture: true },
  source_age: { value: 30, method: "user", calibration_id: null },
};

/** Synthetic triangle used only to verify the static API/viewer contract, not real G1. */
function staticGlb(normalMorphOnly = false): Buffer {
  const bin = Buffer.alloc(68);
  [-0.8, -1, 0, 0.8, -1, 0, 0, 1, 0].forEach((value, index) => bin.writeFloatLE(value, index * 4));
  [0, 1, 2].forEach((value, index) => bin.writeUInt16LE(value, 36 + index * 2));
  [0, 0, 1, 0, 0.5, 1].forEach((value, index) => bin.writeFloatLE(value, 44 + index * 4));
  const json = Buffer.from(JSON.stringify({
    asset: { version: "2.0", generator: "AgeMorph3D synthetic static test fixture" },
    scene: 0, scenes: [{ nodes: [0] }],
    nodes: [{ mesh: 0, name: "Synthetic_Static_Triangle", extras: { synthetic: true } }],
    meshes: [{ primitives: [{ attributes: { POSITION: 0, TEXCOORD_0: 2, ...(normalMorphOnly ? { NORMAL: 0 } : {}) }, indices: 1, material: 0, ...(normalMorphOnly ? { targets: [{ NORMAL: 0 }] } : {}) }] }],
    materials: [{ doubleSided: true, pbrMetallicRoughness: { metallicFactor: 0, roughnessFactor: 1 } }],
    buffers: [{ byteLength: bin.length }],
    bufferViews: [{ buffer: 0, byteOffset: 0, byteLength: 36, target: 34962 }, { buffer: 0, byteOffset: 36, byteLength: 6, target: 34963 }, { buffer: 0, byteOffset: 44, byteLength: 24, target: 34962 }],
    accessors: [{ bufferView: 0, componentType: 5126, count: 3, type: "VEC3", min: [-0.8, -1, 0], max: [0.8, 1, 0] }, { bufferView: 1, componentType: 5123, count: 3, type: "SCALAR" }, { bufferView: 2, componentType: 5126, count: 3, type: "VEC2" }],
  }));
  const padded = Buffer.alloc(Math.ceil(json.length / 4) * 4, 32);
  json.copy(padded);
  const glb = Buffer.alloc(12 + 8 + padded.length + 8 + bin.length);
  glb.write("glTF"); glb.writeUInt32LE(2, 4); glb.writeUInt32LE(glb.length, 8);
  glb.writeUInt32LE(padded.length, 12); glb.writeUInt32LE(0x4e4f534a, 16); padded.copy(glb, 20);
  glb.writeUInt32LE(bin.length, 20 + padded.length); glb.writeUInt32LE(0x004e4942, 24 + padded.length); bin.copy(glb, 28 + padded.length);
  return glb;
}

function serviceHealth(capabilities = { reconstruction: true, age_morph: true, age_texture: true, realtime: true }) {
  const model = (ready: boolean) => ({
    state: ready ? "ready" : "missing",
    backend: ready ? "test-backend" : null,
    provider: ready ? "CPUExecutionProvider" : null,
    detail: ready ? "Test model ready." : "Model is not installed.",
  });
  return {
    api_version: "1.2",
    models: {
      detector: model(capabilities.realtime || capabilities.reconstruction),
      reconstructor: model(capabilities.reconstruction),
      age_shape: model(capabilities.age_morph),
      age_texture: model(capabilities.age_texture),
    },
    capabilities,
    device: "cpu",
    version: "test-v1",
  };
}

test.beforeEach(async ({ page }) => {
  const errors: string[] = [];
  failures.set(page, errors);
  page.on("pageerror", (error) => errors.push(error.message));
});

test.afterEach(async ({ page }) => {
  expect(failures.get(page), "页面不应出现未捕获异常").toEqual([]);
});

async function openStudio(page: Page): Promise<void> {
  await page.goto("/");
  await expect(page.locator("#viewer canvas")).toBeVisible();
  await expect(page.locator("#vertex-readout")).not.toHaveText("—");
  await expect(page.locator("#viewer-fallback")).toBeHidden();
}

async function uploadTinyPng(page: Page): Promise<void> {
  const data = await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    canvas.width = 8;
    canvas.height = 8;
    const context = canvas.getContext("2d")!;
    context.fillStyle = "#b3d8d5";
    context.fillRect(0, 0, 8, 8);
    return canvas.toDataURL("image/png").split(",")[1]!;
  });
  await page.locator("#photo-input").setInputFiles({
    name: "tiny-portrait.png",
    mimeType: "image/png",
    buffer: Buffer.from(data, "base64"),
  });
  await expect(page.locator("#photo-preview")).toBeVisible();
  await expect(page.locator("#source-image")).toHaveJSProperty(
    "naturalWidth",
    8,
  );
}

async function connectLocalApi(page: Page): Promise<void> {
  await page.locator("#settings-open").click();
  await page.locator("#api-url").fill(API);
  await page.locator("#connect-api").click();
  await expect(page.locator("#connection-label")).toHaveText("本地服务已连接");
  if (await page.locator("#settings-dialog").isVisible())
    await page.keyboard.press("Escape");
}

async function fakeCamera(page: Page): Promise<void> {
  await page.addInitScript(() => {
    Object.defineProperty(navigator.mediaDevices, "getUserMedia", {
      configurable: true,
      value: async () => {
        const canvas = document.createElement("canvas");
        canvas.width = 32;
        canvas.height = 32;
        canvas.getContext("2d")!.fillRect(0, 0, 32, 32);
        return canvas.captureStream(10);
      },
    });
  });
}

async function downloadBytes(
  page: Page,
  selector: string,
  testInfo?: TestInfo,
  name?: string,
): Promise<Buffer> {
  const downloadEvent = page.waitForEvent("download");
  await page.locator(selector).click();
  const download = await downloadEvent;
  expect(await download.failure()).toBeNull();
  const temporaryPath = await download.path();
  expect(temporaryPath).not.toBeNull();
  if (testInfo && name) await download.saveAs(testInfo.outputPath(name));
  return readFile(temporaryPath!);
}

function parseGlb(bytes: Buffer): Record<string, any> {
  expect(bytes.subarray(0, 4).toString("ascii")).toBe("glTF");
  expect(bytes.readUInt32LE(4)).toBe(2);
  expect(bytes.readUInt32LE(8)).toBe(bytes.length);
  expect(bytes.readUInt32LE(16)).toBe(0x4e4f534a);
  const length = bytes.readUInt32LE(12);
  return JSON.parse(
    bytes
      .subarray(20, 20 + length)
      .toString("utf8")
      .trim(),
  );
}

async function mockReconstruction(page: Page, result: Record<string, unknown>, fixture: Buffer): Promise<void> {
  await page.route(`${API}/**`, async (route) => {
    const headers = { "Access-Control-Allow-Origin": "*" };
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/health") await route.fulfill({ headers, json: serviceHealth() });
    else if (path === "/api/reconstruct") await route.fulfill({ headers, json: result });
    else if (path.endsWith("/mesh.glb")) await route.fulfill({ headers, contentType: "model/gltf-binary", body: fixture });
    else await route.abort();
  });
  await connectLocalApi(page);
  await uploadTinyPng(page);
  await page.locator("#photo-consent").check();
  await page.locator("#reconstruct").click();
}

test("静态契约模拟资产保留未知源年龄，禁用年龄动作且导出不伪造年龄", async ({ page }) => {
  await openStudio(page);
  await mockReconstruction(page, {
    mesh_id: "static_unknown", topology_id: "triangle_fixture", asset_mode: "static",
    capabilities: { age_morph: false, age_texture: false },
    source_age: { value: null, method: "unknown", calibration_id: null },
    shape: [0], expr: [0], pose: IDENTITY,
  }, staticGlb());
  await expect(page.locator("#model-badge")).toHaveText("本地重建");
  await expect(page.locator("#source-status")).toContainText("原始重建，年龄变换不可用");
  await expect(page.locator("#age-output")).toHaveText("—");
  await expect(page.locator("#info-age")).toHaveText("未知");
  for (const selector of ["#age-slider", "#age-reset", "[data-age=\"60\"]", "#compare-toggle", "#apply-texture"])
    await expect(page.locator(selector)).toBeDisabled();
  await page.evaluate(() => {
    for (const id of ["age-reset", "compare-toggle"]) {
      const control = document.getElementById(id) as HTMLButtonElement;
      control.disabled = false; control.click();
    }
    const slider = document.getElementById("age-slider") as HTMLInputElement;
    slider.disabled = false; slider.value = "60"; slider.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await expect(page.locator("#info-age")).toHaveText("未知");
  await expect(page.locator("#comparison-labels")).toBeHidden();
  const pending = page.waitForEvent("download");
  await page.locator("#export-glb").click();
  const download = await pending;
  expect(download.suggestedFilename()).toBe("AgeMorph3D-local-original.glb");
  const exported = parseGlb(await readFile((await download.path())!));
  const root = exported.nodes.find((node: any) => node.name === "AgeMorph3D_Loaded_Model");
  expect(root.extras.asset_mode).toBe("static");
  expect(root.extras.topology_id).toBe("triangle_fixture");
  expect(root.extras.source_age).toEqual({ value: null, method: "unknown", calibration_id: null });
  for (const field of ["age", "ageAnchors", "displayAge"])
    expect(root.extras[field]).toBeUndefined();
  expect(exported.meshes.every((mesh: any) => mesh.primitives.every((primitive: any) => primitive.targets === undefined))).toBe(true);
  await page.locator("#photo-remove").click();
  await expect(page.locator("#model-badge")).toHaveText("演示模型");
  await expect(page.locator("#age-output")).toHaveText("30");
  await expect(page.locator("#age-slider")).toBeEnabled();
});

test("年龄资产以真实声明的源年龄重置和对照，不沿用演示的30岁", async ({ page }) => {
  await openStudio(page);
  const fixture = await downloadBytes(page, "#export-glb");
  await mockReconstruction(page, {
    ...ageResultFields, mesh_id: "calibrated", shape: [0], expr: [0], pose: IDENTITY,
    capabilities: { age_morph: true, age_texture: false },
    source_age: { value: 42.5, method: "estimated", calibration_id: "calibration_fixture" },
  }, fixture);
  await expect(page.locator("#model-badge")).toHaveText("本地重建");
  await expect(page.locator("#info-age")).toHaveText("42.5");
  await expect(page.locator("#age-slider")).toHaveValue("42.5");
  await page.locator('[data-age="60"]').click();
  await page.locator("#compare-toggle").click();
  await expect(page.locator("#compare-source-age")).toHaveText("42.5");
  await page.locator("#age-reset").click();
  await expect(page.locator("#age-output")).toHaveText("42.5");
  await expect(page.locator("#age-slider")).toHaveValue("42.5");
  const exported = parseGlb(await downloadBytes(page, "#export-glb"));
  const root = exported.nodes.find((node: any) => node.name === "AgeMorph3D_Loaded_Model");
  expect(root.extras.age).toBe(42.5);
  expect(root.extras.source_age.value).toBe(42.5);
  await page.locator("#load-demo").click();
  await expect(page.locator("#age-slider")).toHaveValue("30");
  await expect(page.locator("#age-slider")).toHaveAttribute("step", "1");
});

for (const mode of ["static", "age_morph"] as const) {
  test(`显式${mode}模式拒绝不匹配资产，损坏年龄资产不降级`, async ({ page }) => {
    await openStudio(page);
    const fixture = mode === "static" ? await downloadBytes(page, "#export-glb") : staticGlb();
    await mockReconstruction(page, {
      ...ageResultFields, mesh_id: "mismatched", shape: [0], expr: [0], pose: IDENTITY,
      asset_mode: mode, capabilities: { age_morph: mode === "age_morph", age_texture: false },
    }, fixture);
    await expect(page.locator("#source-status")).toContainText(mode === "static" ? "静态重建资产不能包含形变目标" : "未找到带 age_20");
    await expect(page.locator("#viewer")).toHaveAttribute("data-source", "demo");
    await expect(page.locator("#model-badge")).toHaveText("演示模型");
  });
}

test("静态模式拒绝仅含法线的形变目标，不能用缺少position目标绕过契约", async ({ page }) => {
  await openStudio(page);
  await mockReconstruction(page, {
    mesh_id: "normal_morph", topology_id: "triangle_fixture", asset_mode: "static",
    capabilities: { age_morph: false, age_texture: false }, source_age: { value: null, method: "unknown", calibration_id: null },
    shape: [0], expr: [0], pose: IDENTITY,
  }, staticGlb(true));
  await expect(page.locator("#source-status")).toContainText("静态重建资产不能包含形变目标");
  await expect(page.locator("#viewer")).toHaveAttribute("data-source", "demo");
});

test("离线演示启动，无外部请求，年龄滑块支持键盘并保持读数一致", async ({
  page,
}, testInfo) => {
  const requested: string[] = [];
  page.on("request", (request) => {
    if (/^https?:/.test(request.url())) requested.push(request.url());
  });
  await openStudio(page);
  await expect(page.locator("#model-badge")).toContainText("演示");
  await expect(page.locator("#age-output")).toHaveText("30");
  await expect(page.locator("#reconstruct")).toBeDisabled();
  const slider = page.getByRole("slider", { name: "目标年龄" });
  await slider.focus();
  await slider.press("End");
  await expect(page.locator("#age-output")).toHaveText("70");
  await expect(page.locator("#info-age")).toHaveText("70");
  await expect(slider).toHaveAttribute("aria-valuetext", "70 岁");
  await slider.press("Home");
  await expect(page.locator("#age-output")).toHaveText("20");
  await slider.press("ArrowRight");
  await expect(page.locator("#age-output")).toHaveText("21");
  await page.locator("#age-reset").click();
  await expect(slider).toHaveValue("30");
  expect(
    requested.every((url) => new URL(url).origin === new URL(page.url()).origin),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("studio-desktop.png"),
    fullPage: true,
  });
});

test("材质、视角、光照与年龄对照可切换，画布确实更新", async ({ page }) => {
  await openStudio(page);
  const canvas = page.locator("#viewer canvas");
  const initial = await canvas.screenshot();
  await page.locator('[data-mode="wireframe"]').click();
  await expect(page.locator('[data-mode="wireframe"]')).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect((await canvas.screenshot()).equals(initial)).toBe(false);
  await page.locator('[data-mode="points"]').click();
  await expect(page.locator('[data-mode="solid"]')).toHaveAttribute(
    "aria-pressed",
    "false",
  );
  await page.locator('[data-mode="solid"]').click();
  await page.locator('[data-view="side"]').click();
  await expect(page.locator('[data-view="side"]')).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await page.locator("#lighting").selectOption("dramatic");
  await page.locator('[data-age="60"]').click();
  await page.locator("#compare-toggle").click();
  await expect(page.locator("#comparison-labels")).toBeVisible();
  await expect(page.locator("#compare-age")).toHaveText("60");
  await expect(page.locator("#comparison-labels")).toContainText(
    "基准 · 30 岁",
  );
  await page.locator("#compare-toggle").click();
  await expect(page.locator("#comparison-labels")).toBeHidden();
  await page.locator("#view-reset").click();
  await expect(page.locator('[data-view="front"]')).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

test("390px 窄屏无横向溢出，核心操作与弹窗可达", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openStudio(page);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.locator('[data-age="70"]').click();
  await expect(page.locator("#age-output")).toHaveText("70");
  await page.locator("#settings-open").click();
  await expect(page.locator("#settings-dialog")).toBeVisible();
  const box = await page.locator("#settings-dialog").boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(391);
  await page.keyboard.press("Escape");
  await expect(page.locator("#settings-open")).toBeFocused();
  await page.screenshot({
    path: testInfo.outputPath("studio-mobile.png"),
    fullPage: true,
  });
});

test("弹窗关闭后归还焦点，远程服务地址在发起请求前被拒绝", async ({ page }) => {
  await openStudio(page);
  for (const [button, dialog] of [
    ["guide-open", "guide-dialog"],
    ["about-open", "about-dialog"],
    ["settings-open", "settings-dialog"],
  ]) {
    await page.locator(`#${button}`).click();
    await expect(page.locator(`#${dialog}`)).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.locator(`#${dialog}`)).toBeHidden();
    await expect(page.locator(`#${button}`)).toBeFocused();
  }
  const remoteRequests: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("example.com"))
      remoteRequests.push(request.url());
  });
  await page.locator("#settings-open").click();
  await page.locator("#api-url").fill("https://example.com");
  await page.locator("#connect-api").click();
  await expect(page.locator("#health-status")).toContainText(/本机|localhost/);
  expect(remoteRequests).toEqual([]);
  await expect(page.locator("#connection-label")).toHaveText("本地演示模式");
});

test("图片输入拒绝类型错误和损坏文件，合法图片可预览移除且不会自动上传", async ({
  page,
}) => {
  await openStudio(page);
  const apiRequests: string[] = [];
  page.on("request", (request) => {
    if (request.url().startsWith(API)) apiRequests.push(request.url());
  });
  await page
    .locator("#photo-input")
    .setInputFiles({
      name: "invalid.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("invalid"),
    });
  await expect(page.locator("#toast")).toBeVisible();
  await expect(page.locator("#toast-text")).toContainText(/JPG|PNG|WebP|图片/);
  await expect(page.locator("#photo-preview")).toBeHidden();
  await page
    .locator("#photo-input")
    .setInputFiles({
      name: "broken.png",
      mimeType: "image/png",
      buffer: Buffer.from("not a png"),
    });
  await expect(page.locator("#toast-text")).toContainText(
    /损坏|解码|读取|有效/,
  );
  await uploadTinyPng(page);
  await page.locator("#photo-consent").check();
  await expect(page.locator("#reconstruct")).toBeDisabled();
  expect(apiRequests).toEqual([]);
  await page.locator("#photo-remove").click();
  await expect(page.locator("#photo-preview")).toBeHidden();
  await expect(page.locator("#upload-trigger")).toBeVisible();
});

test("摄像头仅在点击后请求，拒绝权限有反馈且拍照不可用", async ({ page }) => {
  await page.addInitScript(() => {
    const state = window as Window & { __cameraCalls: number };
    state.__cameraCalls = 0;
    const getUserMedia = async () => {
      state.__cameraCalls++;
      throw new DOMException("Permission denied by test", "NotAllowedError");
    };
    if (navigator.mediaDevices)
      Object.defineProperty(navigator.mediaDevices, "getUserMedia", {
        configurable: true,
        value: getUserMedia,
      });
    else
      Object.defineProperty(navigator, "mediaDevices", {
        configurable: true,
        value: { getUserMedia },
      });
  });
  await openStudio(page);
  expect(
    await page.evaluate(
      () => (window as Window & { __cameraCalls: number }).__cameraCalls,
    ),
  ).toBe(0);
  await page.locator("#camera-tab").click();
  await page.locator("#camera-toggle").click();
  await expect(page.locator("#toast-text")).toContainText(/权限|拒绝|允许/);
  await expect(page.locator("#camera-capture")).toBeDisabled();
  expect(
    await page.evaluate(
      () => (window as Window & { __cameraCalls: number }).__cameraCalls,
    ),
  ).toBe(1);
  await page.locator("#photo-tab").click();
  await expect(page.locator("#camera-area")).toBeHidden();
});

test("PNG 与 GLB 下载有效，GLB 保留年龄目标、当前权重和演示来源", async ({
  page,
}, testInfo) => {
  await openStudio(page);
  await page.locator('[data-age="70"]').click();
  const png = await downloadBytes(
    page,
    "#export-png",
    testInfo,
    "demo-age-70.png",
  );
  expect([...png.subarray(0, 8)]).toEqual([137, 80, 78, 71, 13, 10, 26, 10]);
  expect(png.readUInt32BE(16)).toBeGreaterThan(100);
  expect(png.readUInt32BE(20)).toBeGreaterThan(100);
  const glb = parseGlb(
    await downloadBytes(page, "#export-glb", testInfo, "demo-age-70.glb"),
  );
  const morphing = glb.meshes.filter(
    (mesh: any) => mesh.extras?.targetNames?.length,
  );
  expect(morphing.length).toBeGreaterThan(0);
  for (const mesh of morphing) {
    expect(mesh.extras.targetNames).toEqual(["age_20", "age_45", "age_70"]);
    expect(mesh.weights).toEqual([0, 0, 1]);
    expect(mesh.primitives[0].targets).toHaveLength(3);
  }
  expect(JSON.stringify(glb)).toContain("procedural-demo");
});

test("本地服务连接和授权门槛生效，重建错误可恢复且不冒充成功", async ({
  page,
}) => {
  let uploads = 0;
  await page.route(`${API}/**`, async (route) => {
    const headers = { "Access-Control-Allow-Origin": "*" };
    if (route.request().url().endsWith("/api/health")) {
      await route.fulfill({
        headers,
        json: serviceHealth(),
      });
    } else if (route.request().url().endsWith("/api/reconstruct")) {
      uploads++;
      expect(route.request().postDataBuffer()?.toString("utf8")).toContain(
        'name="image"',
      );
      await route.fulfill({
        status: 422,
        headers,
        json: { detail: "未检测到人脸，请使用清晰的正面照片。" },
      });
    } else
      await route.fulfill({
        status: 404,
        headers,
        json: { detail: "Unexpected test request" },
      });
  });
  await openStudio(page);
  await connectLocalApi(page);
  await uploadTinyPng(page);
  await expect(page.locator("#reconstruct")).toBeDisabled();
  await page.locator("#photo-consent").check();
  await expect(page.locator("#reconstruct")).toBeEnabled();
  await page.locator("#reconstruct").click();
  await expect(page.locator("#toast-text")).toContainText("未检测到人脸");
  await expect(page.locator("#reconstruct")).toBeEnabled();
  await expect(page.locator("#model-badge")).toContainText("演示");
  expect(uploads).toBe(1);
});

test("符合约定的 GLB 可加载，纹理失败可恢复，移除照片清理个人结果", async ({
  page,
}) => {
  await openStudio(page);
  const fixture = await downloadBytes(page, "#export-glb");
  const ages: number[] = [];
  await page.route(`${API}/**`, async (route) => {
    const headers = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Headers": "content-type",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    };
    const request = route.request();
    if (request.method() === "OPTIONS")
      await route.fulfill({ status: 204, headers });
    else if (request.url().endsWith("/api/health"))
      await route.fulfill({
        headers,
        json: serviceHealth(),
      });
    else if (request.url().endsWith("/api/reconstruct"))
      await route.fulfill({
        headers,
        json: {
          mesh_id: "test_subject",
          ...ageResultFields,
          shape: [0],
          expr: [0],
          pose: IDENTITY,
          texture_url: "/api/assets/test_subject/base.png",
        },
      });
    else if (request.url().endsWith("/api/assets/test_subject/mesh.glb"))
      await route.fulfill({
        headers,
        contentType: "model/gltf-binary",
        body: fixture,
      });
    else if (request.url().endsWith("/api/aging")) {
      ages.push(request.postDataJSON().age);
      await route.fulfill({
        status: 503,
        headers,
        json: { detail: "纹理模型尚未就绪。" },
      });
    } else
      await route.fulfill({
        status: 404,
        headers,
        json: { detail: "Unexpected test request" },
      });
  });
  await connectLocalApi(page);
  await uploadTinyPng(page);
  await page.locator("#photo-consent").check();
  await page.locator("#reconstruct").click();
  await expect(page.locator("#apply-texture")).toBeEnabled();
  await expect(page.locator("#model-badge")).not.toContainText("演示");
  await page.locator('[data-age="60"]').click();
  await page.locator("#apply-texture").click();
  await expect(page.locator("#toast-text")).toContainText("纹理模型尚未就绪");
  await expect(page.locator("#apply-texture")).toBeEnabled();
  expect(ages).toEqual([60]);
  await page.locator("#photo-remove").click();
  await expect(page.locator("#model-badge")).toContainText("演示");
  await expect(page.locator("#apply-texture")).toBeDisabled();
});

test("WebGL 不可用时显示恢复入口，禁用三维导出并保留照片输入", async ({
  page,
}) => {
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (
      contextId: string,
      ...args: any[]
    ): any {
      if (contextId.includes("webgl")) return null;
      return original.apply(this, [contextId, ...args] as any);
    } as typeof original;
  });
  await page.goto("/");
  await expect(page.locator("#viewer-fallback")).toBeVisible();
  await expect(page.locator("#viewer-retry")).toBeVisible();
  await expect(page.locator("#export-glb")).toBeDisabled();
  await expect(page.locator("#export-png")).toBeDisabled();
  await uploadTinyPng(page);
});

test("摄像头拍照生成本地照片并释放轨道，设备意外断开后恢复按钮", async ({
  page,
}) => {
  await page.addInitScript(() => {
    const state = window as Window & { __cameraStream?: MediaStream };
    const getUserMedia = async () => {
      const canvas = document.createElement("canvas");
      canvas.width = 640;
      canvas.height = 480;
      const context = canvas.getContext("2d")!;
      context.fillStyle = "#789caa";
      context.fillRect(0, 0, 640, 480);
      state.__cameraStream = canvas.captureStream(10);
      return state.__cameraStream;
    };
    Object.defineProperty(navigator.mediaDevices, "getUserMedia", {
      configurable: true,
      value: getUserMedia,
    });
  });
  await openStudio(page);
  await page.locator("#camera-tab").click();
  await page.locator("#camera-toggle").click();
  await expect(page.locator("#camera-toggle")).toHaveText("关闭摄像头");
  await page.waitForFunction(
    () =>
      document.querySelector<HTMLVideoElement>("#camera-video")!.readyState >=
      2,
  );
  await page.locator("#camera-capture").click();
  await expect(page.locator("#photo-preview")).toBeVisible();
  await expect(page.locator("#source-image")).toHaveJSProperty(
    "naturalWidth",
    640,
  );
  expect(
    await page.evaluate(() =>
      (window as Window & { __cameraStream: MediaStream }).__cameraStream
        .getTracks()
        .every((track) => track.readyState === "ended"),
    ),
  ).toBe(true);
  await page.locator("#camera-tab").click();
  await page.locator("#camera-toggle").click();
  await expect(page.locator("#camera-toggle")).toHaveText("关闭摄像头");
  await page.evaluate(() => {
    const track = (
      window as Window & { __cameraStream: MediaStream }
    ).__cameraStream.getVideoTracks()[0]!;
    track.stop();
    track.dispatchEvent(new Event("ended"));
  });
  await expect(page.locator("#camera-toggle")).toHaveText("开启摄像头");
  await expect(page.locator("#camera-capture")).toBeDisabled();
  await expect(page.locator("#toast-text")).toContainText("摄像头已断开");
});

test("取消重建后，迟到的响应不能替换演示模型", async ({ page }) => {
  let requested = false;
  let assets = 0;
  await page.route(`${API}/**`, async (route) => {
    const headers = { "Access-Control-Allow-Origin": "*" };
    if (route.request().url().endsWith("/api/health"))
      await route.fulfill({
        headers,
        json: serviceHealth(),
      });
    else if (route.request().url().endsWith("/api/reconstruct")) {
      requested = true;
      await new Promise((resolve) => setTimeout(resolve, 750));
      await route.fulfill({
        headers,
        json: {
          mesh_id: "late_subject",
          ...ageResultFields,
          shape: [0],
          expr: [0],
          pose: IDENTITY,
        },
      });
    } else {
      assets++;
      await route.abort();
    }
  });
  await openStudio(page);
  await connectLocalApi(page);
  await uploadTinyPng(page);
  await page.locator("#photo-consent").check();
  await page.locator("#reconstruct").click();
  await expect.poll(() => requested).toBe(true);
  await page.locator("#cancel-reconstruct").click();
  await expect(page.locator("#source-status")).toContainText("已取消");
  await page.waitForTimeout(850);
  await expect(page.locator("#viewer")).toHaveAttribute("data-source", "demo");
  await expect(page.locator("#reconstruct")).toBeEnabled();
  expect(assets).toBe(0);
});

for (const assetMode of ["static", "age_morph"] as const) {
  test(`${assetMode}资产年龄纹理应用后，改变年龄恢复基础纹理，导出保留实际纹理与目标`, async ({
    page,
  }) => {
    await openStudio(page);
    const fixture = assetMode === "static" ? staticGlb() : await downloadBytes(page, "#export-glb");
    const png = async (color: string): Promise<Buffer> =>
      Buffer.from(
        await page.evaluate((fill) => {
          const canvas = document.createElement("canvas");
          canvas.width = 4;
          canvas.height = 4;
          const ctx = canvas.getContext("2d")!;
          ctx.fillStyle = fill;
          ctx.fillRect(0, 0, 4, 4);
          return canvas.toDataURL("image/png").split(",")[1]!;
        }, color),
        "base64",
      );
    const base = await png("#28c864");
    const aged = await png("#dc643c");
    await page.route(`${API}/**`, async (route) => {
      const headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "content-type",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      };
      const request = route.request();
      const path = new URL(request.url()).pathname;
      if (request.method() === "OPTIONS")
        await route.fulfill({ status: 204, headers });
      else if (path === "/api/health")
        await route.fulfill({
          headers,
          json: serviceHealth(),
        });
      else if (path === "/api/reconstruct")
        await route.fulfill({
          headers,
          json: {
            mesh_id: "texture_subject",
            ...ageResultFields,
            asset_mode: assetMode,
            capabilities: { age_morph: assetMode === "age_morph", age_texture: true },
            shape: [0],
            expr: [0],
            pose: IDENTITY,
            texture_url: "/api/assets/texture_subject/base.png",
          },
        });
      else if (path.endsWith("/mesh.glb"))
        await route.fulfill({
          headers,
          contentType: "model/gltf-binary",
          body: fixture,
        });
      else if (path.endsWith("/base.png"))
        await route.fulfill({ headers, contentType: "image/png", body: base });
      else if (path.endsWith("/aged.png"))
        await route.fulfill({ headers, contentType: "image/png", body: aged });
      else if (path === "/api/aging")
        await route.fulfill({
          headers,
          json: {
            shape_aged: [0],
            texture_url: "/api/assets/texture_subject/aged.png",
          },
        });
      else await route.abort();
    });
    const firstTextureColor = async (bytes: Buffer): Promise<number[]> => {
      const glb = parseGlb(bytes);
      expect(glb.images.length).toBeGreaterThan(0);
      const view = glb.bufferViews[glb.images[0].bufferView];
      const binOffset = 20 + bytes.readUInt32LE(12) + 8;
      const image = bytes.subarray(
        binOffset + (view.byteOffset ?? 0),
        binOffset + (view.byteOffset ?? 0) + view.byteLength,
      );
      return page.evaluate(
        async (data) => {
          const bitmap = await createImageBitmap(
            new Blob([new Uint8Array(data)], { type: "image/png" }),
          );
          const canvas = document.createElement("canvas");
          canvas.width = 4;
          canvas.height = 4;
          const ctx = canvas.getContext("2d")!;
          ctx.drawImage(bitmap, 0, 0);
          bitmap.close();
          return [...ctx.getImageData(0, 0, 1, 1).data].slice(0, 3);
        },
        [...image],
      );
    };
    await connectLocalApi(page);
    await uploadTinyPng(page);
    await page.locator("#photo-consent").check();
    await page.locator("#reconstruct").click();
    await expect(page.locator("#apply-texture")).toBeEnabled();
    await page.locator('[data-age="60"]').click();
    await page.locator("#apply-texture").click();
    await expect(page.locator("#texture-hint")).toContainText("已应用 60 岁");
    const agedExport = await downloadBytes(page, "#export-glb");
    expect(await firstTextureColor(agedExport)).toEqual([220, 100, 60]);
    const exportedRoot = parseGlb(agedExport).nodes.find((node: any) => node.name === "AgeMorph3D_Loaded_Model");
    expect(exportedRoot.extras.texture_age).toBe(60);
    if (assetMode === "static") {
      expect(exportedRoot.extras.age).toBeUndefined();
      expect(exportedRoot.extras.displayAge).toBeUndefined();
      await expect(page.locator("#compare-toggle")).toBeDisabled();
      await expect(page.locator("#age-description")).toContainText("三维形状保持原始重建");
    }
    await page.locator('[data-age="50"]').click();
    expect(
      await firstTextureColor(await downloadBytes(page, "#export-glb")),
    ).toEqual([40, 200, 100]);
  });
}

for (const finalState of ["ready", "error"] as const) {
  test(`连接仅刷新loading状态，转为${finalState}后更新能力并停止轮询`, async ({ page }) => {
    let checks = 0;
    const loading = serviceHealth({ reconstruction: false, age_morph: false, age_texture: false, realtime: false });
    loading.models.reconstructor.state = "loading";
    loading.models.reconstructor.detail = "Fixture model loading.";
    const terminal = serviceHealth({ reconstruction: finalState === "ready", age_morph: false, age_texture: false, realtime: false });
    terminal.models.reconstructor.state = finalState;
    terminal.models.reconstructor.detail = `Fixture model ${finalState}.`;
    await page.route(`${API}/api/health`, async (route) => {
      checks++;
      await route.fulfill({ headers: { "Access-Control-Allow-Origin": "*" }, json: checks === 1 ? loading : terminal });
    });
    await openStudio(page);
    await uploadTinyPng(page);
    await page.locator("#photo-consent").check();
    await connectLocalApi(page);
    await expect(page.locator("#health-status")).toContainText("state=loading");
    await expect(page.locator("#reconstruct")).toBeDisabled();
    await expect(page.locator("#health-status")).toContainText(`Fixture model ${finalState}.`);
    if (finalState === "ready") await expect(page.locator("#reconstruct")).toBeEnabled();
    else await expect(page.locator("#reconstruct")).toBeDisabled();
    await page.waitForTimeout(750);
    expect(checks).toBe(2);
  });
}

test("断开loading连接取消状态刷新，迟到ready响应不能恢复能力或覆盖演示", async ({ page }) => {
  let checks = 0;
  let delivered = false;
  let release!: () => void;
  const waiting = new Promise<void>((resolve) => { release = resolve; });
  const loading = serviceHealth({ reconstruction: false, age_morph: false, age_texture: false, realtime: false });
  loading.models.reconstructor.state = "loading";
  await page.route(`${API}/api/health`, async (route) => {
    checks++;
    if (checks > 1) await waiting;
    await route.fulfill({ headers: { "Access-Control-Allow-Origin": "*" }, json: checks === 1 ? loading : serviceHealth() });
    if (checks > 1) delivered = true;
  });
  await openStudio(page);
  await uploadTinyPng(page);
  await page.locator("#photo-consent").check();
  await connectLocalApi(page);
  await expect.poll(() => checks).toBe(2);
  await page.locator("#settings-open").click();
  await page.locator("#disconnect").click();
  release();
  await expect.poll(() => delivered).toBe(true);
  await page.waitForTimeout(750);
  expect(checks).toBe(2);
  await expect(page.locator("#health-status")).toHaveText("当前使用程序化演示模型。");
  await expect(page.locator("#connection-label")).toHaveText("本地演示模式");
  await expect(page.locator("#reconstruct")).toBeDisabled();
  await expect(page.locator("#viewer")).toHaveAttribute("data-source", "demo");
});

test("loading健康刷新结束时保留已载入的静态个人模型", async ({ page }) => {
  let checks = 0;
  let release!: () => void;
  const waiting = new Promise<void>((resolve) => { release = resolve; });
  const loading = serviceHealth({ reconstruction: true, age_morph: false, age_texture: false, realtime: false });
  loading.models.age_shape.state = "loading";
  const ready = serviceHealth({ reconstruction: true, age_morph: false, age_texture: false, realtime: false });
  ready.models.age_shape.detail = "Fixture loading completed.";
  await page.route(`${API}/**`, async (route) => {
    const headers = { "Access-Control-Allow-Origin": "*" };
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/health") {
      checks++;
      if (checks > 1) await waiting;
      await route.fulfill({ headers, json: checks === 1 ? loading : ready });
    } else if (path === "/api/reconstruct") await route.fulfill({ headers, json: {
      mesh_id: "static_during_loading", topology_id: "triangle_fixture", asset_mode: "static",
      capabilities: { age_morph: false, age_texture: false }, source_age: { value: null, method: "unknown", calibration_id: null },
      shape: [0], expr: [0], pose: IDENTITY,
    } });
    else if (path.endsWith("/mesh.glb")) await route.fulfill({ headers, contentType: "model/gltf-binary", body: staticGlb() });
    else await route.abort();
  });
  await openStudio(page);
  await connectLocalApi(page);
  await uploadTinyPng(page);
  await page.locator("#photo-consent").check();
  await page.locator("#reconstruct").click();
  await expect(page.locator("#model-badge")).toHaveText("本地重建");
  release();
  await expect(page.locator("#health-status")).toContainText("Fixture loading completed.");
  await expect(page.locator("#viewer")).toHaveAttribute("data-source", "reconstruction");
  await expect(page.locator("#info-source")).toHaveText("static_during_loading");
  await expect(page.locator("#info-age")).toHaveText("未知");
  await expect(page.locator("#source-status")).toContainText("原始重建，年龄变换不可用");
});

test("loading自动刷新到30秒预算后停止，不对稳定未就绪服务持续轮询", async ({ page }) => {
  let checks = 0;
  const loading = serviceHealth({ reconstruction: false, age_morph: false, age_texture: false, realtime: false });
  loading.models.reconstructor.state = "loading";
  await page.route(`${API}/api/health`, async (route) => {
    checks++;
    await route.fulfill({ headers: { "Access-Control-Allow-Origin": "*" }, json: loading });
  });
  await openStudio(page);
  await page.clock.install();
  await connectLocalApi(page);
  await page.clock.fastForward(30_001);
  await expect(page.locator("#health-status")).toContainText("自动刷新已结束");
  const stoppedAt = checks;
  await page.clock.fastForward(10_000);
  expect(checks).toBe(stoppedAt);
  await expect(page.locator("#reconstruct")).toBeDisabled();
});

for (const scenario of ["missing", "legacy", "invalid"] as const) {
  test(`健康检查 ${scenario} 不授予推理能力，已授权照片和已开启摄像头也不可绕过`, async ({ page }) => {
    await fakeCamera(page);
    const disabled = serviceHealth({ reconstruction: false, age_morph: false, age_texture: false, realtime: false });
    const payload = scenario === "missing"
      ? disabled
      : scenario === "legacy"
        ? { models: { detector: "ready", reconstructor: "ready" }, device: "cpu", version: "legacy" }
        : { ...serviceHealth(), capabilities: { ...serviceHealth().capabilities, realtime: "true" } };
    const inference: string[] = [];
    const sockets: string[] = [];
    page.on("websocket", (socket) => {
      if (new URL(socket.url()).origin === API.replace("http:", "ws:"))
        sockets.push(socket.url());
    });
    await page.route(`${API}/**`, async (route) => {
      if (!route.request().url().endsWith("/api/health")) inference.push(route.request().url());
      await route.fulfill({ headers: { "Access-Control-Allow-Origin": "*" }, json: payload });
    });
    await openStudio(page);
    await connectLocalApi(page);
    await uploadTinyPng(page);
    await page.locator("#photo-consent").check();
    await expect(page.locator("#reconstruct")).toBeDisabled();
    await expect(page.locator("#apply-texture")).toBeDisabled();
    await page.locator("#settings-open").click();
    if (scenario === "missing") {
      await expect(page.locator("#health-status")).toContainText("reconstruction=不可用");
      await expect(page.locator("#health-status")).toContainText("reconstructor: state=missing");
      await expect(page.locator("#health-status")).toContainText("backend=未配置");
      await expect(page.locator("#health-status")).toContainText("Model is not installed.");
    } else {
      await expect(page.locator("#health-status")).toContainText("能力状态未知");
      await expect(page.locator("#health-status")).toContainText("检查 API 版本");
      await expect(page.locator("#source-status")).toContainText("重建能力未知");
    }
    await page.keyboard.press("Escape");
    await page.locator("#camera-tab").click();
    await page.locator("#camera-toggle").click();
    await expect(page.locator("#camera-toggle")).toHaveText("关闭摄像头");
    await expect(page.locator("#stream-toggle")).toBeDisabled();
    await page.evaluate(() => {
      for (const id of ["reconstruct", "apply-texture", "stream-toggle"]) {
        const target = document.getElementById(id) as HTMLButtonElement;
        target.disabled = false;
        target.click();
      }
    });
    expect(inference).toEqual([]);
    expect(sockets).toEqual([]);
    await expect(page.locator("#viewer")).toHaveAttribute("data-source", "demo");
    await expect(page.locator("#camera-capture")).toBeEnabled();
  });
}

test("部分能力就绪时按能力启禁，已有重建模型也不能调用未就绪纹理", async ({ page }) => {
  await fakeCamera(page);
  await openStudio(page);
  const fixture = await downloadBytes(page, "#export-glb");
  let agingRequests = 0;
  await page.route(`${API}/**`, async (route) => {
    const headers = { "Access-Control-Allow-Origin": "*" };
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/health")
      await route.fulfill({ headers, json: serviceHealth({ reconstruction: true, age_morph: true, age_texture: false, realtime: true }) });
    else if (path === "/api/reconstruct")
      await route.fulfill({ headers, json: { ...ageResultFields, capabilities: { age_morph: true, age_texture: false }, mesh_id: "partial", shape: [0], expr: [0], pose: IDENTITY } });
    else if (path.endsWith("mesh.glb"))
      await route.fulfill({ headers, contentType: "model/gltf-binary", body: fixture });
    else {
      agingRequests++;
      await route.abort();
    }
  });
  await connectLocalApi(page);
  await uploadTinyPng(page);
  await page.locator("#photo-consent").check();
  await expect(page.locator("#reconstruct")).toBeEnabled();
  await page.locator("#reconstruct").click();
  await expect(page.locator("#model-badge")).toHaveText("本地重建");
  await expect(page.locator("#apply-texture")).toBeDisabled();
  await expect(page.locator("#texture-hint")).toContainText("年龄纹理能力不可用");
  await page.evaluate(() => {
    const target = document.getElementById("apply-texture") as HTMLButtonElement;
    target.disabled = false;
    target.click();
  });
  expect(agingRequests).toBe(0);
  await page.locator("#camera-tab").click();
  await page.locator("#camera-toggle").click();
  await expect(page.locator("#stream-toggle")).toBeEnabled();
});

test("切换服务立即撤销旧能力，断开后的迟到健康响应和新服务失败不恢复能力", async ({ page }) => {
  const secondApi = "http://127.0.0.1:8001";
  let firstChecks = 0;
  let secondChecks = 0;
  let release!: () => void;
  let delivered = false;
  const waiting = new Promise<void>((resolve) => { release = resolve; });
  const headers = { "Access-Control-Allow-Origin": "*" };
  await page.route(`${API}/api/health`, async (route) => {
    firstChecks++;
    await route.fulfill({ headers, json: firstChecks === 1 ? serviceHealth() : serviceHealth({ reconstruction: false, age_morph: false, age_texture: false, realtime: false }) });
  });
  await page.route(`${secondApi}/api/health`, async (route) => {
    secondChecks++;
    if (secondChecks === 1) {
      await waiting;
      await route.fulfill({ headers, json: serviceHealth() });
      delivered = true;
    } else await route.fulfill({ headers, status: 503, json: { detail: "Second service unavailable." } });
  });
  await openStudio(page);
  await connectLocalApi(page);
  await uploadTinyPng(page);
  await page.locator("#photo-consent").check();
  await expect(page.locator("#reconstruct")).toBeEnabled();
  await page.locator("#settings-open").click();
  await page.locator("#api-url").fill(secondApi);
  await page.locator("#connect-api").click();
  await expect.poll(() => secondChecks).toBe(1);
  await expect(page.locator("#reconstruct")).toBeDisabled();
  await expect(page.locator("#connection-label")).toHaveText("正在检查本地服务");
  await page.locator("#disconnect").click();
  await connectLocalApi(page);
  await expect(page.locator("#reconstruct")).toBeDisabled();
  release();
  await expect.poll(() => delivered).toBe(true);
  await page.locator("#settings-open").click();
  await expect(page.locator("#api-url")).toHaveValue(API);
  await expect(page.locator("#health-status")).toContainText("reconstruction=不可用");
  await expect(page.locator("#reconstruct")).toBeDisabled();
  await page.locator("#api-url").fill(secondApi);
  await page.locator("#connect-api").click();
  await expect(page.locator("#health-status")).toContainText("Second service unavailable.");
  await expect(page.locator("#connection-label")).toHaveText("本地演示模式");
  await expect(page.locator("#reconstruct")).toBeDisabled();
  await expect(page.locator("#apply-texture")).toBeDisabled();
});

test("B6 合成摄像头与模拟 WS 验证镜像、单飞、错误恢复和释放（不代表实体 G2）", async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    const state = window as Window & { __b6Streams: MediaStream[] };
    state.__b6Streams = [];
    Object.defineProperty(navigator.mediaDevices, "getUserMedia", {
      configurable: true,
      value: async () => {
        const canvas = document.createElement("canvas");
        canvas.width = 640;
        canvas.height = 360;
        const context = canvas.getContext("2d")!;
        context.fillStyle = "red";
        context.fillRect(0, 0, 320, 360);
        context.fillStyle = "blue";
        context.fillRect(320, 0, 320, 360);
        const stream = canvas.captureStream(10);
        state.__b6Streams.push(stream);
        return stream;
      },
    });
  });
  await page.route(`${API}/api/health`, (route) => route.fulfill({
    headers: { "Access-Control-Allow-Origin": "*" },
    json: serviceHealth({ reconstruction: false, age_morph: false, age_texture: false, realtime: true }),
  }));
  const sessions: { socket: WebSocketRoute; frames: Buffer[] }[] = [];
  let closes = 0;
  await page.routeWebSocket("ws://127.0.0.1:8000/ws/frame", (socket) => {
    const session = { socket, frames: [] as Buffer[] };
    sessions.push(session);
    socket.onMessage((message) => {
      if (Buffer.isBuffer(message)) session.frames.push(message);
    });
    socket.onClose(() => { closes++; });
    socket.send(JSON.stringify({ type: "status", device: "synthetic-test" }));
  });
  const overlayInk = () => page.evaluate(() => {
    const canvas = document.querySelector<HTMLCanvasElement>("#camera-overlay")!;
    return canvas.getContext("2d")!.getImageData(0, 0, canvas.width, canvas.height)
      .data.some((value, index) => index % 4 === 3 && value !== 0);
  });
  const send = (session: number, value: unknown) => sessions[session]!.socket.send(JSON.stringify(value));
  const face = (seq: number) => {
    const c = Math.cos(0.4), s = Math.sin(0.4);
    return { type: "face_state", seq, ts: 1, bbox: [32, 25, 80, 90],
      landmarks: [[42, 45], [92, 45], [67, 65], [47, 85], [87, 85]],
      pose: { R: [c, 0, s, 0, 1, 0, -s, 0, c], t: [0, 0, 0] }, conf: 0.95 };
  };
  await openStudio(page);
  await connectLocalApi(page);
  await page.locator("#photo-consent").check();
  await page.locator("#camera-tab").click();
  await page.locator("#camera-toggle").click();
  await expect(page.locator("#camera-toggle")).toHaveText("关闭摄像头");
  await page.locator("#stream-toggle").click();
  await expect.poll(() => sessions[0]?.frames.length).toBe(1);
  await page.waitForTimeout(250);
  expect(sessions[0]!.frames).toHaveLength(1);
  const capture = await page.evaluate(async (bytes) => {
    const image = await createImageBitmap(new Blob([new Uint8Array(bytes)], { type: "image/jpeg" }));
    const canvas = document.createElement("canvas");
    canvas.width = image.width; canvas.height = image.height;
    const context = canvas.getContext("2d")!;
    context.drawImage(image, 0, 0);
    image.close();
    return { width: canvas.width, height: canvas.height,
      left: Array.from(context.getImageData(100, 100, 1, 1).data),
      right: Array.from(context.getImageData(500, 100, 1, 1).data),
      mirror: ["camera-video", "camera-overlay"].map((id) =>
        new DOMMatrix(getComputedStyle(document.getElementById(id)!).transform).a),
    };
  }, Array.from(sessions[0]!.frames[0]!));
  expect([capture.width, capture.height]).toEqual([640, 360]);
  expect(capture.left[0]).toBeGreaterThan(230);
  expect(capture.left[2]).toBeLessThan(30);
  expect(capture.right[2]).toBeGreaterThan(230);
  expect(capture.mirror).toEqual([-1, -1]);
  send(0, face(1));
  await expect(page.locator("#stream-status")).toContainText("帧 1");
  expect(await overlayInk()).toBe(true);
  const glb = parseGlb(await downloadBytes(page, "#export-glb"));
  const root = glb.nodes.find((node: { name?: string }) => node.name === "AgeMorph3D_Demo");
  expect(root.matrix[2]).toBeCloseTo(Math.sin(0.4), 5);
  expect(root.matrix[8]).toBeCloseTo(-Math.sin(0.4), 5);
  await page.screenshot({ path: testInfo.outputPath("synthetic-mirrored-frame.png") });
  for (const [index, code] of ["NO_FACE", "MULTI_FACE", "BUSY"].entries()) {
    await expect.poll(() => sessions[0]!.frames.length).toBe(index + 2);
    send(0, { type: "error", seq: index + 2, code, msg: `合成夹具 ${code}` });
    await expect(page.locator("#stream-status")).toHaveText(`合成夹具 ${code}`);
    expect(await overlayInk()).toBe(false);
    await expect(page.locator("#stream-toggle")).toContainText("停止实时检测");
  }
  await expect.poll(() => sessions[0]!.frames.length).toBe(5);
  send(0, { type: "error", seq: 2, code: "NO_FACE", msg: "过期错误" });
  send(0, face(3));
  await page.waitForTimeout(250);
  expect(sessions[0]!.frames).toHaveLength(5);
  await expect(page.locator("#stream-status")).toHaveText("合成夹具 BUSY");
  send(0, face(5));
  await expect(page.locator("#stream-status")).toContainText("帧 5");
  expect(await overlayInk()).toBe(true);
  await page.locator("#stream-toggle").click();
  await expect.poll(() => closes).toBe(1);
  expect(await overlayInk()).toBe(false);
  await expect(page.locator("#camera-toggle")).toHaveText("关闭摄像头");
  await page.locator("#stream-toggle").click();
  await expect.poll(() => sessions[1]?.frames.length).toBe(1);
  send(1, { type: "error", seq: 1, code: "POSE_FAILED", msg: "合成致命错误" });
  await expect(page.locator("#stream-toggle")).toContainText("连接实时检测");
  await expect(page.locator("#stream-status")).toHaveText("合成致命错误");
  await expect.poll(() => closes).toBe(2);
  await page.locator("#stream-toggle").click();
  await expect.poll(() => sessions[2]?.frames.length).toBe(1);
  await page.locator("#photo-tab").click();
  await expect.poll(() => closes).toBe(3);
  expect(await page.evaluate(() => (window as Window & { __b6Streams: MediaStream[] }).__b6Streams
    .every((stream) => stream.getTracks().every((track) => track.readyState === "ended")))).toBe(true);
  await page.locator("#camera-tab").click();
  await page.locator("#camera-toggle").click();
  await page.locator("#stream-toggle").click();
  await expect.poll(() => sessions[3]?.frames.length).toBe(1);
  await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent("pagehide")));
  await expect.poll(() => closes).toBe(4);
  expect(await page.evaluate(() => (window as Window & { __b6Streams: MediaStream[] }).__b6Streams
    .every((stream) => stream.getTracks().every((track) => track.readyState === "ended")))).toBe(true);
});
