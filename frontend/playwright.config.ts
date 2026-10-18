import { defineConfig } from "@playwright/test";
import path from "node:path";

const production = process.env.AGEMORPH_E2E_PRODUCTION === "1";
const baseURL = `http://127.0.0.1:${production ? 4173 : 5173}`;

export default defineConfig({
  testDir: "./tests",
  testMatch: "**/*.spec.ts",
  outputDir: path.resolve(
    process.env.TEST_ARTIFACT_DIR ?? "../output/frontend-verification",
  ),
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  reporter: [["list"], ["json", { outputFile: "../output/frontend-browser-tests.json" }]],
  use: {
    baseURL,
    browserName: "chromium",
    viewport: { width: 1440, height: 1040 },
    locale: "zh-CN",
    reducedMotion: "reduce",
    acceptDownloads: true,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    launchOptions: { args: ["--enable-unsafe-swiftshader"] },
  },
  projects: [
    { name: "Chrome", use: { channel: "chrome" } },
    { name: "Edge", use: { channel: "msedge" } },
  ],
  webServer: {
    command: production ? "npm run preview -- --port 4173 --strictPort" : "npm run dev -- --port 5173 --strictPort",
    url: baseURL,
    reuseExistingServer: true,
    timeout: 30_000,
  },
});
