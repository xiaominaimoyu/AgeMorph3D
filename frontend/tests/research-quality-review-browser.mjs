/** Opt-in installed-browser contract checks on a fresh offline editor artifact. */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { resolve, relative, isAbsolute } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "@playwright/test";

const ROOT = resolve(fileURLToPath(new URL("../..", import.meta.url)));
const args = process.argv.slice(2);
const option = name => { const i = args.indexOf(name); assert.ok(i >= 0 && args[i + 1], `Specify ${name}`); return args[i + 1]; };
function local(name) { const p = resolve(ROOT, name), tail = relative(ROOT, p); assert.ok(tail && !isAbsolute(tail) && !tail.startsWith("..")); return p; }
const htmlPath = local(option("--editor")), aiPath = local(option("--ai-worksheet"));
const outputName = option("--output-dir"); assert.ok(outputName.startsWith("output/research/"));
const OUT = local(outputName); await mkdir(OUT);
const sha = b => createHash("sha256").update(b).digest("hex");
const html = await readFile(htmlPath), aiBody = await readFile(aiPath), ai = JSON.parse(aiBody);
const harness = await readFile(fileURLToPath(import.meta.url)); await writeFile(resolve(OUT, "harness.frozen.mjs"), harness, { flag: "wx" });
const pkg = JSON.parse(html.toString("utf8").match(/<script id="review-package" type="application\/json">(.*?)<\/script>/s)[1]);
const baseline = pkg.worksheet;
const result = { status: "running", research_only: true, human_review_completed: false, g3_complete: false,
  node: process.version, harness_sha256: sha(harness),
  html: { path: relative(ROOT, htmlPath), bytes: html.length, sha256: sha(html) },
  ai_worksheet: { path: relative(ROOT, aiPath), bytes: aiBody.length, sha256: sha(aiBody) },
  browsers: [], network_requests: [], errors: [] };
const save = async () => writeFile(resolve(OUT, "report.json"), JSON.stringify(result, null, 2) + "\n");
let currentBrowser;
try {
  for (const channel of ["chrome", "msedge"]) {
    const browser = await chromium.launch({ channel, headless: true }); currentBrowser = browser;
    const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, acceptDownloads: true });
    const page = await context.newPage(), checks = [], pageErrors = [], consoleErrors = [], downloads = [];
    page.on("pageerror", e => pageErrors.push(e.message));
    page.on("console", e => { if (e.type() === "error") consoleErrors.push(e.text()); });
    page.on("request", req => { if (/^https?:/.test(req.url())) result.network_requests.push({ channel, url: req.url() }); });
    page.on("download", d => downloads.push(d.suggestedFilename()));
    const check = (name, value) => { assert.ok(value, name); checks.push(name); };
    await page.goto(pathToFileURL(htmlPath).href, { waitUntil: "load" });
    await page.locator("#record-select option").last().waitFor({ state: "attached" });
    check("32 complete evidence rows", await page.locator("#record-select option").count() === 32);
    check("no default human and edits initially disabled", await page.locator("#observer-kind").inputValue() === "" && await page.locator("#criteria").evaluate(e => e.disabled) && await page.locator(".criterion select").first().isDisabled());
    const decoded = await page.evaluate(async () => {
      const p = JSON.parse(document.getElementById("review-package").textContent);
      let count = 0;
      for (const uri of [...Object.values(p.images), ...Object.values(p.originals)]) {
        const image = new Image(); image.src = uri; await image.decode();
        if (image.naturalWidth !== 1024 || image.naturalHeight !== 1024) throw new Error("Image size mismatch");
        image.src = ""; count++;
      }
      return count;
    });
    check("72 saved PNGs decode at native dimensions", decoded === 72);
    for (let i = 0; i < 32; i++) for (const v of ["conservative", "observed"]) {
      const bytes = Buffer.from(pkg.images[`${i}/${v}`].split(",", 2)[1], "base64");
      assert.equal(sha(bytes), baseline.records[i].evidence[v].image.sha256);
    }
    checks.push("64 target PNG bytes match exact original pins");
    await page.locator("#begin").click();
    check("missing observer rejected", (await page.locator("#message").textContent()).includes("观察者"));
    await page.locator("#observer-kind").selectOption("ai");
    await page.locator("#observer-name").fill("browser-contract-only-not-quality");
    await page.locator("#begin").click();
    check("observer locked after starting", await page.locator("#observer-kind").isDisabled() && !(await page.locator(".criterion select").first().isDisabled()));
    const rating = page.locator('select[data-criterion="eyes_glasses"][data-variant="observed"]');
    await rating.selectOption("issue"); await page.locator("#export").click();
    check("unexplained selection cannot export", (await page.locator("#message").textContent()).includes("判断依据") && downloads.length === 0);
    const note = page.getByLabel("说明 · 眼区与眼镜 · 额头候选", { exact: true });
    await note.fill('Synthetic browser contract note <img src="https://example.test/not-a-request">');
    const downloadFile = async name => {
      const promise = page.waitForEvent("download"); await page.locator("#export").click();
      const downloaded = await promise, path = resolve(OUT, `${channel}-${name}.json`); await downloaded.saveAs(path);
      return JSON.parse(await readFile(path, "utf8"));
    };
    const partial = await downloadFile("partial");
    check("partial export retains entire worksheet and unknown age", partial.records.length === 32 && partial.records[0].source_age_api.value === null && partial.reviewer.kind === "ai");
    assert.deepEqual(partial.denominators, baseline.denominators); assert.deepEqual(partial.cohort_targets, baseline.cohort_targets);
    assert.equal(partial.records[0].evidence.observed.saved_identity_status, "NO_FACE");
    assert.equal(partial.g3_complete, false); assert.equal(partial.human_review_completed, false);
    checks.push("full cohort, failures and closed flags preserved");
    await page.locator("#next").click(); await page.locator("#previous").click();
    check("observations survive navigation and text stays literal", (await note.inputValue()).includes("<img") && await page.locator(".pictures img").count() === 3);
    await page.locator("#record-select").selectOption("31");
    await page.locator('select[data-criterion="seams"][data-variant="conservative"]').selectOption("not_assessable");
    await page.getByLabel("说明 · 接缝与缺口 · 保守支持", { exact: true }).fill("Synthetic last-row note");
    check("last row is independently editable", (await page.locator("#progress").textContent()).includes("2/320"));
    await page.locator("#import-file").setInputFiles(resolve(OUT, `${channel}-partial.json`));
    await page.waitForFunction(() => document.getElementById("import-file").value === "");
    check("import explicitly replaces full draft", (await page.locator("#progress").textContent()).includes("1/320"));
    const tampered = structuredClone(partial); tampered.g3_complete = true;
    const badPath = resolve(OUT, `${channel}-tampered.json`); await writeFile(badPath, JSON.stringify(tampered));
    await page.locator("#import-file").setInputFiles(badPath);
    await page.waitForFunction(() => document.getElementById("import-file").value === "");
    check("tampered quality flags rejected without losing edits", (await page.locator("#message").textContent()).includes("不能") && (await page.locator("#progress").textContent()).includes("1/320"));
    await page.locator("#import-file").setInputFiles(aiPath);
    await page.waitForFunction(() => document.getElementById("import-file").value === "");
    check("real AI observations import with original attribution", (await page.locator("#progress").textContent()).includes("320/320") && await page.locator("#observer-name").inputValue() === ai.reviewer.name && await page.locator("#observer-kind").inputValue() === "ai");
    const full = await downloadFile("full-ai"); assert.deepEqual(full, ai);
    checks.push("complete AI draft round-trips unchanged without human promotion");
    await page.locator(".zoom-button").first().click();
    check("native size image view", await page.locator("#zoom").isVisible() && await page.locator("#zoom-image").evaluate(e => e.naturalWidth === 1024 && e.clientWidth === 1024));
    await page.locator("#zoom-close").click();
    await page.setViewportSize({ width: 390, height: 900 });
    await page.screenshot({ path: resolve(OUT, `${channel}-mobile.png`) });
    check("390px page has no horizontal overflow", await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.locator(".criterion").first().screenshot({ path: resolve(OUT, `${channel}-mobile-criterion.png`) });
    await page.setViewportSize({ width: 1440, height: 1100 }); await page.evaluate(() => scrollTo(0, 0));
    await page.screenshot({ path: resolve(OUT, `${channel}-desktop.png`) });
    await page.locator("#reset").click();
    check("clear resets observations and observer", await page.locator("#observer-kind").inputValue() === "" && (await page.locator("#progress").textContent()).includes("0/320"));
    await page.locator("#observer-kind").selectOption("ai"); await page.locator("#observer-name").fill("newer-edit"); await page.locator("#begin").click();
    await page.evaluate(() => {
      const original = File.prototype.text; window.__originalReviewFileText = original;
      File.prototype.text = function () { return new Promise(resolve => { window.__releaseReviewFile = () => original.call(this).then(resolve); }); };
    });
    await page.locator("#import-file").setInputFiles(aiPath);
    await page.waitForFunction(() => typeof window.__releaseReviewFile === "function");
    await page.locator('select[data-criterion="eyes_glasses"][data-variant="observed"]').selectOption("issue");
    await note.fill("Synthetic newer edit must not be overwritten");
    await page.evaluate(async () => { await window.__releaseReviewFile(); File.prototype.text = window.__originalReviewFileText; });
    await page.waitForFunction(() => document.getElementById("import-file").value === "");
    check("late file read cannot overwrite newer edits or block file retry", await page.locator("#observer-name").inputValue() === "newer-edit" && (await page.locator("#progress").textContent()).includes("1/320"));
    check("no unexpected browser errors", !pageErrors.length && !consoleErrors.length);
    result.browsers.push({ channel, version: browser.version(), checks, page_errors: pageErrors, console_errors: consoleErrors, downloads, browser_closed: false });
    await context.close(); await browser.close(); currentBrowser = null;
    result.browsers.at(-1).browser_closed = true; await save();
  }
  assert.deepEqual(await readFile(htmlPath), html); assert.deepEqual(await readFile(aiPath), aiBody);
  assert.equal(result.network_requests.length, 0);
  result.status = "passed"; result.inputs_unchanged = true; await save();
  console.log(JSON.stringify({ status: result.status, browsers: result.browsers.map(b => ({ channel: b.channel, checks: b.checks.length })), network_requests: 0 }));
} catch (error) {
  result.status = "failed"; result.errors.push(String(error.stack || error)); await save(); throw error;
} finally { if (currentBrowser) await currentBrowser.close(); }
