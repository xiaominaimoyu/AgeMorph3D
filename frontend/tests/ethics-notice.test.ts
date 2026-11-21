import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const frontendRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const SENTENCE_DEMO = "年龄变换研究演示，不用于预测个体未来相貌";
const SENTENCE_AGE = "仅记录你提供的年龄，不代表模型估计";

test("主工作台顶栏伦理提示包含两句原文", () => {
  const html = readFileSync(join(frontendRoot, "index.html"), "utf8");
  const match = html.match(/<p id="ethics-notice" class="ethics-notice">([^<]*)<\/p>/);
  assert.ok(match, "index.html 缺少 #ethics-notice");
  assert.equal(
    match[1],
    `${SENTENCE_DEMO}。${SENTENCE_AGE}。`,
  );
  assert.ok(html.includes(SENTENCE_DEMO));
  assert.ok(html.includes(SENTENCE_AGE));
});

test("桌面单屏壳层约束仍在，伦理提示单行不撑高顶栏", () => {
  const css = readFileSync(join(frontendRoot, "src/style.css"), "utf8");
  assert.match(css, /\.topbar\s*\{[^}]*height:\s*48px/s);
  assert.match(css, /height:\s*100vh;/);
  assert.match(css, /height:\s*100dvh;/);
  assert.match(
    css,
    /\.ethics-notice\s*\{[^}]*white-space:\s*nowrap[^}]*overflow:\s*hidden[^}]*text-overflow:\s*ellipsis/s,
  );
});
