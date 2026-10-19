import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { chromium, expect } from "@playwright/test";

// Explicit opt-in smoke: start the backend and a production preview before running this file.
const frontend = process.env.AGEMORPH_SMOKE_FRONTEND ?? "http://127.0.0.1:4173";
const api = "http://127.0.0.1:8000";
const output = fileURLToPath(new URL("../../output/backend-verification/", import.meta.url));
await mkdir(output, { recursive: true });
const results = [];

for (const channel of ["chrome", "msedge"]) {
  const browser = await chromium.launch({
    channel,
    headless: true,
    args: [
      "--enable-unsafe-swiftshader",
      "--use-fake-ui-for-media-stream",
      "--use-fake-device-for-media-stream",
    ],
  });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1040 }, locale: "zh-CN" });
    const requests = [];
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("request", (request) => {
      if (new URL(request.url()).origin === api)
        requests.push({ method: request.method(), url: request.url() });
    });
    await page.goto(frontend);
    await expect(page.locator("#viewer canvas")).toBeVisible();
    const image = await page.evaluate(() => {
      const canvas = document.createElement("canvas");
      canvas.width = 8;
      canvas.height = 8;
      canvas.getContext("2d").fillRect(0, 0, 8, 8);
      return canvas.toDataURL("image/png").split(",")[1];
    });
    await page.locator("#photo-input").setInputFiles({
      name: "synthetic-smoke.png", mimeType: "image/png", buffer: Buffer.from(image, "base64"),
    });
    await expect(page.locator("#photo-preview")).toBeVisible();
    await page.locator("#photo-consent").check();
    await page.locator("#settings-open").click();
    const response = page.waitForResponse(`${api}/api/health`);
    await page.locator("#connect-api").click();
    const healthResponse = await response;
    assert.equal(healthResponse.status(), 200);
    const health = await healthResponse.json();
    assert.equal(health.api_version, "1.1");
    assert.deepEqual(health.capabilities, {
      reconstruction: false, age_morph: false, age_texture: false, realtime: false,
    });
    for (const name of ["detector", "reconstructor", "age_shape", "age_texture"]) {
      assert.equal(health.models[name].state, "missing");
      await expect(page.locator("#health-status")).toContainText(`${name}: state=missing`);
    }
    await expect(page.locator("#connection-label")).toHaveText("本地服务已连接");
    await page.locator("#health-status").screenshot({ path: `${output}health-${channel}.png` });
    await page.keyboard.press("Escape");
    await expect(page.locator("#reconstruct")).toBeDisabled();
    await expect(page.locator("#apply-texture")).toBeDisabled();
    await expect(page.locator("#source-status")).toContainText("三维重建能力不可用");
    await page.locator("#camera-tab").click();
    await page.locator("#camera-toggle").click();
    await expect(page.locator("#camera-toggle")).toHaveText("关闭摄像头");
    await expect(page.locator("#camera-capture")).toBeEnabled();
    await expect(page.locator("#stream-toggle")).toBeDisabled();
    await expect(page.locator("#stream-status")).toContainText("实时检测能力不可用");
    await expect(page.locator("#texture-hint")).toContainText("年龄纹理能力不可用");
    await page.screenshot({ path: `${output}disabled-${channel}.png`, fullPage: true });
    assert.deepEqual(requests, [{ method: "GET", url: `${api}/api/health` }]);
    assert.deepEqual(errors, []);
    await page.locator("#camera-toggle").click();
    results.push({
      channel, version: browser.version(), health, requests, errors,
      reconstructionDisabled: true, ageTextureDisabled: true, realtimeDisabledWithActiveCamera: true,
    });
  } finally {
    await browser.close();
  }
}
await writeFile(`${output}live-browser-smoke.json`, JSON.stringify({
  frontend, backend: api, media: "Chromium synthetic camera device", routeMocks: false, results,
}, null, 2));
console.log(JSON.stringify({ browsers: results.map(({ channel, version }) => ({ channel, version })), passed: results.length, output }));
