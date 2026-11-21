# FE-1 前端更新检查（10f1918 不滚动单屏布局）

- 执行人：Runner（执行运营官）；检查时间：2026-11-21 08:25—08:50（柏林时间，UTC+1）＝ 15:25—15:50（UTC+8 / Asia/Shanghai）；审核返工：2026-11-21 08:51 起（UTC+1）＝ 15:51 起（UTC+8）
- 工作副本：`/workspace/AgeMorph3D_runner`（只做了 fetch 和 checkout，没有提交，没有 push，也没改仓库文件；`git status` 干净）
- **HEAD：`10f19181196f1fd9b86ba9d7acf11f1c35c2515e`**（detached HEAD，即 GitHub `main` 的最新提交）
- **修订（2026-11-21 08:51—09:00 UTC+1 ＝ 15:51—16:00 UTC+8，按 Sentinel FAIL 返工）**：补 MAJOR-1（限制说明/隐私声明被删；用户已决定恢复，FX-2 跟踪，经 Atlas 转达）；修 MINOR 1–6（时序脆弱的定性、命令与日志一致、日志缺文件头与 reuseExistingServer 风险、附件被覆盖、UTC+8、后端计时脚本）。原版备份在 `/tmp/FE-1.bak.075107`
- 日志都在 `/workspace/AgeMorph3D_runner/output/fe1/`（已被 Git 忽略）；截图在 `/workspace/AgeMorph3D_tasks/FE-1_screens/`

## 0. 结论

| 项 | 结果 |
|---|---|
| 前端单元测试 `npm test` | **340/340 通过**（与 RN-1 基线相同） |
| `npm run typecheck` / `npm run build` | 都通过（退出码 0） |
| lint | package.json 里没有前端 lint 脚本，无从运行 |
| 后端全量 pytest（3.11.16，AGEMORPH_NODE=真实 node） | **3008 通过、0 失败、1 跳过**，退出码 0 |
| 浏览器 e2e `studio.spec.ts`（Chrome 156，仓库配置原样） | **38 项中 37 通过、1 失败**。失败项“连接仅刷新loading状态，转为ready后…”在 HEAD 上 4 次跑失败 3 次，在旧提交 35c0cd6 上同一测试 3/3 通过。**定性（经 Sentinel 复核更正）：测试时序脆弱，被新版页面在 SwiftShader 下变慢暴露**，不是重建按钮禁用逻辑的回归（见 §3、§5） |
| 桌面单屏（≥1024 宽） | 1280×800、1920×1080、1366×768、1280×720、1024×768 下页面**都不滚动**，横向也无溢出；主要区域无重叠；关键控件全在视口内；两侧栏内容恰好放下，不需要内部滚动 |
| **主界面限制说明与隐私声明（用户已决定：恢复，在 FX-2 跟踪）** | 10f1918 删除了 35c0cd6 主界面上全部 5 处限制/隐私说明（“不用于预测个体未来相貌”“不代表模型推理或个人未来相貌”“仅记录你提供的年龄，不代表模型估计”“年龄变换不等于未来预测”“照片仅在浏览器与本机服务间处理”），新页面渲染后的 DOM 里一处不剩；`DESIGN.md:21/25` 写明是有意简化文案。对人脸年龄变换的毕设，这会影响伦理/隐私表述。**用户已决定恢复这些声明，由 Forge 在 FX-2 中修改（经 Atlas 转达）**（证据见 §5 第 1 条；初版报告漏报，由 Sentinel 指出） |
| 窄屏（<1024 宽） | 按设计改为纵向堆叠、页面可滚动（CSS `@media (max-width: 1023px)`）；**没有横向溢出**；390×844 和 768×1024 没发现重叠或裁切 |

## 1. 拉取与提交范围

```bash
cd /workspace/AgeMorph3D_runner
git fetch origin            # origin 是本机主副本 /workspace/AgeMorph3D，当时 main 还停在 35c0cd6，拿不到新提交
git fetch https://github.com/xiaominaimoyu/AgeMorph3D.git '+refs/heads/main:refs/remotes/github/main'
git checkout --detach github/main   # → 10f1918
```

因为 runner 副本的 `origin` 指向本机主副本，而主副本在 fetch 时还没有新提交，所以改为直接从 GitHub 公开地址只读拉取 `main`，存进本地引用 `refs/remotes/github/main`。没有改 remote 配置，push 地址仍是 `DISABLED_NO_PUSH`。

`35c0cd6..10f1918` 共 2 个提交，都在 GitHub `main` 上：

| 提交 | 时间（柏林 UTC+1 / UTC+8） | 说明 | 改动文件 |
|---|---|---|---|
| `4c3432c` | 2026-11-19 15:31:59 UTC+1 ＝ 22:31:59 UTC+8 | docs: add project guidance and session handoff | `.github/copilot-instructions.md`（+102）、`CLAUDE.md`（+9）、`docs/2026-10-26_会话交接-AgeMorph3D-report.md`（+177） |
| `10f1918` | 2026-11-20 11:25:20 UTC+1 ＝ 18:25:20 UTC+8 | refactor(frontend): 主工作台改为不滚动单屏布局 | 12 个文件，+747/−1979：`frontend/index.html`、`src/main.ts`、`src/style.css`（−1,600 余行）、删除 `src/icons.ts`、`src/layout.ts`、`src/responsive.css`；`tests/studio.spec.ts`；文档 `CLAUDE.md`、`DESIGN.md`、`PROGRESS.md`、`README.md`、`docs/B系统论文章节提纲.md` |

两个提交都没改 `frontend/package*.json`、`backend/uv.lock`，也没改 `backend/` 下任何文件（`git diff --stat 35c0cd6 HEAD -- backend` 为空）。

附注：检查过程中发现主副本 `/workspace/AgeMorph3D` 也已经到了 `10f1918`。它的 `FETCH_HEAD` 修改时间是 2026-11-21 08:25:57（柏林时间，UTC+1）＝ 15:25:57（UTC+8），是别的 Agent 或用户更新的，不是 Runner 操作的。Runner 对主副本只执行过 `git log`、`git rev-parse`、`git status` 这类只读命令。

## 2. 测试与构建（命令、数量、耗时、退出码）

| 项 | 命令（在 `frontend/` 或 `backend/` 下） | 结果 | 耗时 | 退出码 | 日志 |
|---|---|---|---|---|---|
| 依赖 | `npm ci` | 28 个包，0 个漏洞 | 1.6 s | 0 | `npm-ci.log` |
| 单元测试 | `npm test`（Node 原生 `--test`，不是 vitest） | tests 340 / pass 340 / fail 0 / skipped 0 | 2.0 s | 0 | `frontend-test.log` |
| 类型检查 | `npm run typecheck`（`tsc --noEmit`） | 无输出 | 0.25 s | 0 | `typecheck.log` |
| 构建 | `npm run build` | `✓ built in 246ms` | 0.7 s | 0 | `build.log` |
| lint | — | package.json 没有 lint 脚本，未运行 | — | — | — |
| 后端 | `AGEMORPH_NODE=/usr/local/lib/nodejs/node .venv-py31116/bin/python -m pytest -q -rfEsxX --junitxml=../output/fe1/backend-junit.xml -p no:cacheprovider` | 3008 passed, 1 skipped, 1 warning | 77.9 s（pytest 自报） | 0 | `backend-pytest.log`、`backend-junit.xml`；修正计时后的重跑见下方注 |
| e2e | `npx playwright test --project=Chrome` | 37 passed, 1 failed | 5.2 min | 1 | `e2e-chrome.log` |

> **注（Sentinel MINOR-6 返工）：** 原 `backend-pytest.log` 末尾是 `bc: command not found`，`wall_seconds` 为空。原因是 box 上没有 `bc`。该日志保留未改。新脚本 `output/fe1/run-backend-pytest.sh` 用 python 计算墙钟时间，在日志头写入 date（UTC / UTC+1 / UTC+8）、HEAD 和完整命令，并按新规定加了 `--basetemp=../output/fe1/pytest-tmp`。
> 重跑在 10f1918 上，2026-11-21 08:53:41—08:54:55 UTC+1（15:53:41—15:54:55 UTC+8）：**3008 passed, 1 skipped**，exit 0，pytest 自报 73.50 s，**wall_seconds 74.1**。日志为 `backend-pytest-rerun.log`、`backend-junit-rerun.xml`。
> 另有一次不带 `--basetemp` 的重跑，在规定下达后被主动中止，日志改名为 `backend-pytest-rerun-aborted-no-basetemp.log` 保留，不计入结果。

环境：Node v24.22.1、npm 11.21.1、Python 3.11.16（`backend/.venv-py31116`，锁文件未变，所以沿用 RN-1 的环境）、Google Chrome 156.0.8078.47。

### 与 RN-1 基线对比

| 项 | RN-1 基线（35c0cd6） | 本次（10f1918） | 差异与解释 |
|---|---|---|---|
| 前端单元测试 | 340 | 340 | 0。`frontend/tests/*.test.ts` 共 11 个文件，这两个提交都没改；唯一改动的测试文件 `studio.spec.ts` 属于 Playwright e2e，不计入 `npm test` |
| 后端 | 3009 收集：3007 通过 / 1 失败 / 1 跳过 | 3009 收集：3008 通过 / 0 失败 / 1 跳过 | 用例数不变（后端没有改动）。RN-1 中唯一的失败是 box 的 node 包装脚本导致的身份校验失败（`test_real_stack_start_stop_restart`）；这次按 RN-1 的结论设置了 `AGEMORPH_NODE=/usr/local/lib/nodejs/node`，所以通过。跳过的那 1 项仍需 `AGEMORPH_LOCAL_RUN_LIVE=1` |
| e2e（Chrome） | RN-1 未跑 | 38 项 | 用 `--list` 数：35c0cd6 是 36 项，10f1918 是 38 项。+2 是新增的“笔记本单屏工作台：视口、年龄滑块与主要操作无需滚动”（1280×720）和“可见控件都有可访问名称”；另外“弹窗关闭后归还焦点”改为只测设置弹窗（指南、关于弹窗已从页面移除），多处 `#info-age` 断言改为 `#age-output`，删掉了 `#view-reset` 的断言 |

## 3. e2e（`frontend/tests/studio.spec.ts`）

- 仓库的 `playwright.config.ts` 定义了 `Chrome`（channel=chrome）和 `Edge`（channel=msedge）两个项目。box 装有 Google Chrome，所以 **Chrome 项目按原配置直接运行**，不需要改配置；**Edge 项目没跑**，因为 box 上没有 msedge。
- 结果：**37 通过、1 失败**。新增和改动的布局相关用例都通过了：390px 窄屏（#14）、笔记本单屏（#15）、可访问名称（#16）、弹窗焦点（#17）。
- 失败项：`tests/studio.spec.ts:982` “连接仅刷新loading状态，转为ready后更新能力并停止轮询”，第 999 行 `expect(#reconstruct).toBeDisabled()`，10 秒内一直是 enabled。失败截图、trace 和 error-context 在 `output/frontend-verification/studio-连接仅刷新loading状态，转为ready后更新能力并停止轮询-Chrome/`。**注意：** 全量运行那次的失败附件已被随后的 rerun 覆盖（目录修改时间 08:32:39 与 08:33:16，UTC+1），现存的 `-Chrome/` 与 `-Chrome-repeat2/` 两个目录、以及 `output/frontend-verification/.last-run.json` 里的 2 个失败 id（`…-e87b2a665372e900e18a`、`…-95493da2b8fcc299f08f`）都来自 rerun，不是全量运行那次的。全量那次的失败只剩 `e2e-chrome.log` 中的文字记录。
- 复现对照：

| 提交 | 命令 | 结果 | 日志 |
|---|---|---|---|
| 10f1918 | `npx playwright test --project=Chrome -g 'loading状态' --repeat-each=3`（与日志第 1 行一致） | ready 变体 **3 次失败 2 次**；error 变体 3/3 通过 | `e2e-chrome-loading-rerun.log` |
| 35c0cd6（临时 worktree `/tmp/fe1_base_35c0cd6`，node_modules 链接到 runner，用后已删除） | `TEST_ARTIFACT_DIR=/tmp/fe1_base_art npx playwright test --project=Chrome -g '连接仅刷新loading状态' --repeat-each=3 --reporter=line`（与日志第 2 行一致） | **6/6 全部通过** | `e2e-chrome-loading-baseline-35c0cd6.log` |

  合计：HEAD 上 ready 变体 4 次跑失败 3 次，基线 3/3 通过。两个版本的健康轮询间隔都是 500 ms，没有变化。

  **定性（按 Sentinel 复核更正，原文“疑似回归”撤回）：测试时序脆弱，被新版页面在 SwiftShader 下变慢暴露。** 重建按钮的禁用逻辑本身没有问题。以下证据来自 Sentinel 的独立复核，Runner 未重做：
  - 把第 2 次 health 响应延迟 2.5 s 后，10f1918 上该测试 3/3 通过，说明 loading 期间按钮确实会被禁用；
  - trace 显示 ready 响应在 +1330 ms 到达，而 `toBeDisabled` 断言到 +1377 ms 才开始，断言开始时状态已经转为 ready，按钮自然是可用的；
  - 单个 Playwright 动作的中位耗时：10f1918 约 45 ms，35c0cd6 约 2 ms（新页面在 box 的 SwiftShader 软件渲染下明显变慢）。

  根因跟进由 Sentinel 转给 Forge（例如让测试控制 health 响应时机，而不依赖 500 ms 轮询窗口）。我没有修改任何代码。

  **日志可核对性的局限：**
  - `e2e-chrome-loading-rerun.log` 和 `e2e-chrome-loading-baseline-35c0cd6.log` 只记了命令，**没有记 date 和 HEAD 文件头**；baseline 的临时 worktree 用后已删除，无法事后复查。
  - `playwright.config.ts:37` 设置了 `reuseExistingServer: true`：如果 5173 端口上已有服务在跑，Playwright 会直接复用它，而不是从 worktree 启动 35c0cd6 的 dev 服务。baseline 运行时没有记录端口占用情况，因此**无法证明 baseline 那 6 次确实打在 35c0cd6 的服务上**。“基线 6/6 通过”只能作为参考，不能作为严格对照。
  - 补充（Sentinel 复审提供）：Sentinel 在独立副本上对 35c0cd6 另跑 ready 变体，5/5 通过，可作为基线一侧的独立佐证。

## 4. 视觉检查（不滚动 / 裁切 / 重叠）

方法：自己启动 Vite dev 服务（`npx vite --host 127.0.0.1 --port 5173 --strictPort`，演示模式，不需要后端），用前端依赖里自带的 Playwright 以 headless 方式驱动本机 Chrome。脚本是 `output/fe1/visual-check.mjs` 和 `visual-check-states.mjs`，原始数据在同目录的 `visual-check*.json` / `.log`。每个视口检查以下几项：
- `document.scrollingElement` 的 scrollHeight/clientHeight、scrollWidth/clientWidth；
- 四大区域（`.topbar`、左栏 `.sidebar.source`、`.stage`、右栏 `.sidebar.inspector`）两两求包围盒交集；
- 9 个关键控件（画布、年龄滑块、重建、导出 GLB、设置、授权勾选、拍摄年龄、对比、应用纹理）是否在视口内；
- 所有可见的交互元素是否超出视口，或被设了 overflow 的父容器裁掉；
- 侧栏是否需要内部滚动；
- 文本是否被省略号截断；
- 页面 JS 错误。

截图都是视口大小；页面需要滚动时另存一张整页图。

| 视口 | 页面滚动（scrollH/clientH，scrollW/clientW） | 区域重叠 | 关键控件出视口 | 被容器裁切 / 截断 | 侧栏内部滚动 | 截图 |
|---|---|---|---|---|---|---|
| 1920×1080 | 1080/1080，1920/1920 **不滚动** | 无 | 无 | 0 / 0 | 无（1032/1032） | `fe1_1920x1080.png` |
| 1366×768 | 768/768，1366/1366 **不滚动** | 无 | 无 | 0 / 0 | 无（720/720） | `fe1_1366x768.png` |
| 1280×800 | 800/800，1280/1280 **不滚动** | 无 | 无 | 0 / 0 | 无（752/752） | `fe1_1280x800.png` |
| 1280×720 | 720/720，1280/1280 **不滚动** | 无 | 无 | 0 / 0 | 无（672/672） | `fe1_1280x720.png` |
| 1024×768 | 768/768，1024/1024 **不滚动** | 无 | 无 | 0 / 0 | 无 | `fe1_1024x768.png` |
| 768×1024 | 1080/1024 纵向滚动 56 px；**无横向溢出** | 无 | `#reconstruct` 在 y=1032（视口下方） | 0 / 0 | 无 | `fe1_768x1024.png`、`fe1_768x1024_fullpage.png` |
| 390×844 | 1301/844 纵向滚动；**无横向溢出** | 无 | 重建、导出 GLB、授权勾选等 11 个元素在首屏下方 | 0 / 0 | 无 | `fe1_390x844.png`、`fe1_390x844_fullpage.png` |

- 窄屏需要滚动是**设计如此**：`style.css` 的 `@media (max-width: 1023px)` 把 body 改成 `height:auto; min-height:100dvh`，画布在上，两个面板在下（≤640 宽时单列）。提交说明和新增 e2e 也只要求笔记本、桌面尺寸单屏，窄屏只要求无横向溢出（e2e #14 通过）。768×1024 只差 56 px，重建按钮在首屏之外，属于可以考虑优化的小点，不算缺陷。
- 状态变化后的复测（1280×720、1366×768、1280×800、1920×1080）：上传一张 8×8 PNG、切到摄像头页、打开设置弹窗，三种情况下页面都不滚动，侧栏不需要内部滚动，侧栏里没有元素被裁掉；设置弹窗完整在视口内（440×251，内部无滚动）。截图是 `fe1_<视口>_photo-uploaded.png`、`_camera-tab.png`、`_settings-dialog.png`，共 12 张。
- 人工看过截图（1280×720、1024×768、768×1024 整页、390×844 整页）：没看到文字重叠、按钮被遮挡或错位。各视口都没有页面 JS 错误。
- 局限：只覆盖演示模式和上面几种状态；没连真实后端，没测重建成功后的纹理组、对比标签展开等较高的状态；也没测 Edge 和 Windows 字体渲染。

## 5. 发现的问题

1. **【MAJOR，用户已决定：恢复，在 FX-2 跟踪】主界面全部限制说明与隐私声明被删除（初版漏报，由 Sentinel 指出，Runner 已逐条复核）。**
   - 35c0cd6 中的 5 处原文（`git grep 35c0cd6`）：
     - `frontend/src/layout.ts:43` 页脚：“年龄变换研究演示，不用于预测个体未来相貌。”
     - `frontend/src/layout.ts:27` 示例说明：“示例用于体验三维形变，不代表模型推理或个人未来相貌。”
     - `frontend/src/layout.ts:21`（初始 HTML）与 `frontend/src/main.ts:96`（校验后重设）拍摄年龄提示：“填写 20–70 岁；仅记录你提供的年龄，不代表模型估计。修改后需重新重建。”
     - `frontend/src/layout.ts:48` 关于弹窗脚注：“年龄范围：20–70 岁 · 本地处理 · 年龄变换不等于未来预测”
     - `frontend/src/layout.ts:10` 页首：“本地运行 · 隐私优先 / 照片仅在浏览器与本机服务间处理”
   - 10f1918：`layout.ts` 整个文件被删除；`git grep` 在 `frontend/src`、`frontend/index.html` 中对上述 5 句及“研究演示”“未来预测”“本机服务”“隐私”“仅在浏览器”均**零命中**（`source-age-hint` 元素还在，但 `main.ts` 不再写入那句提示）。
   - 渲染后 DOM：用 headless Chrome 打开 10f1918 的 Vite dev 页面（1280×800，演示模式），检查 `document.documentElement.textContent`（含关闭状态的弹窗）与 aria-label/title/placeholder/aria-valuetext 属性，上述 5 句以及“未来”“预测”“隐私”“研究演示”“不代表”**全部不存在**。脚本与结果：`output/fe1/dom-disclaimer-check.mjs`、`dom-disclaimer-check.log`。
   - 唯一残留：`frontend/src/demo-head.ts:117` 的数据字段 `description: "原创程序化示意模型；年龄形变不代表真实预测。"` 会打进 `dist/assets/viewer-*.js`，但不在主界面显示（上述 DOM 检查未命中“不代表”）。研究子页 `research-quality-review.ts` 不属于主工作台。
   - 是否有意：`DESIGN.md:21` “2026-11-20 改版：……界面靠布局说明自己，不靠文字解释。”；`DESIGN.md:25` “文案。不放标语、使用说明和英文副标签；可见文字只有控件名、读数与状态。……”。即删除是设计决定，不是误删。
   - 影响：本项目是人脸年龄变换毕设，原页面明确声明“不是未来相貌预测”“不代表模型估计”“照片只在本机处理”。删除后，用户/答辩评审在主界面上看不到这些限制与隐私说明，可能被理解为预测工具，也与论文中的伦理与隐私表述不一致。
   - **处理结果：用户已决定恢复这些限制说明与隐私声明，由 Forge 在 FX-2 中实施（经 Atlas 转达，2026-11-21）。** 建议 FX-2 验收时用 `output/fe1/dom-disclaimer-check.mjs` 同样的方法复查渲染后 DOM，并同步修改 `DESIGN.md:25` 的“不放标语、使用说明”表述。Runner 未改任何代码。
2. **e2e 时序脆弱（需要跟进，非回归）**：见 §3。“连接仅刷新loading状态，转为ready后…”在 10f1918 上 4 次跑失败 3 次。按 Sentinel 复核，定性为**测试时序脆弱，被新版页面在 SwiftShader 下变慢暴露**，禁用逻辑正确（延迟第 2 次 health 响应 2.5 s 后 3/3 通过；ready 响应 +1330 ms 先于断言开始 +1377 ms；动作中位耗时约 45 ms 对 2 ms）。10f1918 新增的 PROGRESS.md 记录写“Chrome/Edge 共 76 项……”（76 = 38 × 2 个浏览器，Sentinel 确认），但在 box 的 Chrome 上这一项不能稳定通过；根因已由 Sentinel 转 Forge。另：baseline 对照受 `reuseExistingServer: true` 与日志缺文件头所限，不能严格证明（见 §3）。
3. **e2e 只跑了 Chrome**：Edge 项目因为 box 没有 msedge 未运行。
4. 小优化点（不是缺陷）：768×1024 竖屏平板上，“开始三维重建”按钮在首屏下方 8 px 处，要滚动 56 px 才能看到。

## 6. 产物

- 截图（21 张）：`/workspace/AgeMorph3D_tasks/FE-1_screens/`
- 日志和数据：`/workspace/AgeMorph3D_runner/output/fe1/`，包括 `npm-ci.log`、`frontend-test.log`、`typecheck.log`、`build.log`、`backend-pytest.log`、`backend-junit.xml`、`e2e-chrome.log`、`e2e-chrome-loading-rerun.log`、`e2e-chrome-loading-baseline-35c0cd6.log`、`visual-check*.mjs/json/log`、`vite-dev.log`
- 返工新增：`dom-disclaimer-check.mjs/.log`（MAJOR-1 的 DOM 检查）、`run-backend-pytest.sh`、`backend-pytest-rerun.log`、`backend-junit-rerun.xml`、`backend-pytest-rerun-aborted-no-basetemp.log`、`vite-dev-major1.log`、`pytest-tmp/`
- e2e 失败附件：`/workspace/AgeMorph3D_runner/output/frontend-verification/`，以及 `output/frontend-browser-tests.json`
- 结束时已停掉 Vite 服务，5173、4173、8000 端口都没有残留监听；临时 worktree `/tmp/fe1_base_35c0cd6` 已删除。
