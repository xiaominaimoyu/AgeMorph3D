# FX-2 说明：伦理提示、A/B 分工、AI 规则、测试时序与忽略数据文件

- 执行：Forge（AI agent），2026-11-21。本文时间一律为 UTC+8（项目文档约定）
- 状态：本地完成，待 Sentinel 审查；文件清单供用户按 RULES.md:14 确认。没有改写既有提交
- 仓库：`/workspace/AgeMorph3D_fx2`（git worktree，基于已核验的本地 `origin/main` 尖端 `10f1918`，**未 fetch**），本地分支 `fix/ethics-ab-ai-rules`，当前尖端 `8dfedb4`
- 署名：作者与提交者均为 `MingYao Song <2441377859@qq.com>`，每条提交带 `Co-authored-by: Forge (AI agent) <forge-agent@agemorph3d.invalid>`
- push 地址已用 `git config --worktree` 设为 `DISABLED_NO_PUSH`（只影响本 worktree）。**未 push、未开 PR、未碰 GitHub，未 fetch。**
- 边界：没有读取 `/workspace/hf` 或真实数据/权重，没有下载，没有使用 `trust_remote_code`。主副本 `/workspace/AgeMorph3D` 未改、未运行、未导入。测试只用虚构/合成夹具。

## 1. 做了什么

### 1. 伦理提示（单屏布局）

`10f1918` 之前：第一句在页脚（自 `d00932c` 的 `layout.ts`），第二句在「拍摄时年龄」提示里（自 `e0c215c`）。单屏重构删掉了这两处。

现将两句原文合为一行，放在顶栏品牌与连接按钮之间：

> 年龄变换研究演示，不用于预测个体未来相貌。仅记录你提供的年龄，不代表模型估计。

桌面（≥1024px）顶栏仍是 48px，提示单行省略，不增加高度，不破坏 `1280×720` 不滚动约束。窄屏（≤1023px）提示改到顶栏第二行并允许换行，避免 `390px` 横向溢出（初版 `white-space: nowrap` 曾把「本地演示模式」顶出视口，已改正）。`DESIGN.md` 与 `CLAUDE.md` 的界面条文同步写明这是文案例外。

### 2. A/B 分工更正

宋明耀是 A（算法），王晋涛是 B（系统）。已改正的明确错误：

| 位置 | 原错误 | 改正 |
|---|---|---|
| `docs/model-assets.md:3` | 宋明耀（成员 B） | 成员 A |
| `docs/模型资产诊断与严格服务缺项记录.md:3` | 宋明耀（成员 B） | 成员 A |
| `backend/model-manifests/3ddfa-v2.research.json:12` | `member B, project owner` | `member A, project owner` |
| `backend/model-manifests/yolov5n05-face.research.json:12` | 同上 | 同上 |
| `backend/tests/test_model_assets.py:168` 起 | 只断言含「宋明耀」 | 同时断言含 `member A`、不含 `member B` |

只改了 `license_decided_by` / 文档中的成员字母，没有改清单其他字段或权重哈希。清单没有覆盖该字段的整体哈希或签名；`sha256` 只钉住 artifacts 里的权重文件，因此改这一字段不会使制品哈希失效。

全仓 `rg` 结果见第 4 节。

### 3. AI 规则开头

`CLAUDE.md` 与 `.github/copilot-instructions.md` 均已存在，没有新建。在标题后加入「**先读 RULES.md。**」并列出：

- RULES.md:14 的文件清单确认：未确认本次精确文件清单前不执行 Git 操作
- 本地提交授权不等于推送授权
- 论文正文、图、人工评价、签名归用户本人
- 不得抹去 AI 署名
- AgeDB 和参与者材料不进 AI

已核对 RULES.md 第 14 行原文包含「未确认本次精确文件清单前不执行Git操作」和「本地提交授权不等于推送授权」。

### 4. 10f1918 代码量口径与交接快照

在 `docs/B系统论文章节提纲.md`（文首与第 10 节「可以陈述的事实」）注明：提交 `10f1918` 的前端单屏重构由宋明耀提交，但按实际分工属于 B（王晋涛）的范围，代码量统计按此口径说明。

交接文档选用 `docs/2026-10-26_会话交接-AgeMorph3D-report.md`：任务要求的句子是「2026-10-26 快照」，与该文件日期和「新会话交接」用途一致。已在标题下加入「2026-10-26 快照，状态以 TASKS/PROGRESS 为准」。未改另外两份候选（`docs/2026-10-24提交与推送交接记录.md` 是当次 Git 操作记录；`docs/2026-10-30_会话交接-AgeMorph3D-report.md` 是更晚的会话交接，日期不符）。

### 5. 修复 studio.spec.ts:982 时序脆弱（10f1918 行号）

Sentinel / FE-1 定性：不是功能回归，`refreshActions()` 两边相同。测试必须在第一次 health（loading）与第二次（ready）之间约 500 ms 窗口内完成连接后的若干步（等待「已连接」、处理设置弹窗、Escape、断言 `state=loading` / 重建按钮禁用）。box 上 SwiftShader 软件渲染时，10f1918 动作中位约 45 ms、Escape 约 258 ms，ready 变体曾 5/5 失败；35c0cd6 上约 2 ms，同一测试可通过。

修复（仅测试）：路由拦截暂扣第二次 `/api/health`，先用状态断言确认 loading 且重建按钮禁用，再用 `expect.poll(() => checks).toBe(2)` 等到第二次请求已发出但仍被暂扣，然后放行，再等待终态文案。去掉 `waitForTimeout(750)`。终态出现后 `expect(checks).toBe(2)` 即可：应用在非 loading 时会 `stopHealthRefresh()`，不会再调度第三次请求。

**Sentinel 附带风险（此处未修）：** 新主工作台在没有 GPU、走软件渲染的机器上可能明显变慢。

复跑：`npx playwright test --project=Chrome -g "连接仅刷新loading状态" --repeat-each=8`（独立 5273 端口，避免占用其他代理的 5173），**16/16 通过**（ready 8/8，error 8/8）。

### 6. .gitignore 增加 zip / jpeg 规则

用户经 Atlas 批准，在本分支给 `.gitignore` 补规则，防止数据误入库。这与 RULES.md:13「不修改或删除原有 `.gitignore`」字面冲突，但以用户本次明确批准为准；只追加规则，没有删除既有条目。

先列出已跟踪文件：

```
git ls-files '*.zip' '*.jpg' '*.ZIP' '*.JPG' '*.jpeg' '*.JPEG' '*.jpe' '*.JPE'
```

结果为空；再用 `git ls-files | rg -i '\.(zip|jpg|jpeg|jpe|jfif)$'` 仍为空。仓库里没有已跟踪的 zip/jpg/jpeg，因此**不加例外规则**。

已添加的规则（写在「模型与数据」段、`*.tgz` 之后）：

- `*.zip`
- `*.ZIP`
- `*.jpg`
- `*.JPG`
- `*.jpeg`
- `*.JPEG`

同时加入 `*.jpeg` / 大写后缀的理由：与 `*.zip`/`*.jpg` 同属照片和压缩包数据；Linux 上 Git 区分大小写，只写 `*.jpg` 挡不住 `Photo.JPG`；本仓库工具与 AgeDB 文件名也把 `.jpeg` 与 `.jpg` 同等对待。未加 `*.jpe` / `*.jfif`（仓库与工具链里没有这类用法，不属于本次明确要求的范围）。

`git check-ignore -v` 抽样：

| 路径 | 结果 |
|---|---|
| `data/datasets/x.zip` | 被忽略（先命中已有 `data/`，仍会被挡） |
| `data/foo.jpg` | 被忽略（`data/`） |
| `datasets/a.ZIP` | 被忽略（已有 `datasets/`） |
| `output/b.jpeg` | 被忽略（已有 `output/`） |
| `some/random/archive.zip` | 被忽略（新规则 `*.zip`） |
| `SOME/RANDOM/ARCHIVE.ZIP` | 被忽略（新规则 `*.ZIP`） |
| `backend/tests/tmp.jpg` | 被忽略（`*.jpg`） |
| `frontend/src/photo.JPG` | 被忽略（`*.JPG`） |
| `docs/shot.jpeg` | 被忽略（`*.jpeg`） |
| `frontend/public/favicon.svg`、`frontend/index.html` | 不被忽略 |

测试与工具里的 zip/jpg 写到 `tmp_path`、已忽略的 `data/` 或 `output/`，或只作为请求体/路径字符串出现；`backend/tests/fixtures/` 里只有两个 `.py`，没有图片或压缩包。忽略这些后缀不会让现有测试找不到未跟踪夹具。若将来要入库测试夹具或文档图片，再为具体路径加 `!` 例外。

## 2. 提交与精确文件清单（RULES.md:14）

分支 `fix/ethics-ab-ai-rules`，基于 `10f19181196f1fd9b86ba9d7acf11f1c35c2515e`。六条新提交，全部在其之上追加，没有 rebase、没有改写历史。

1. `de602e53625baf3439eb0c010bdecf4e4b6c1f9c`  
   `fix(frontend): 在不滚动单屏顶栏恢复两句伦理提示`  
   - `DESIGN.md`  
   - `frontend/index.html`  
   - `frontend/src/style.css`  
   - `frontend/tests/ethics-notice.test.ts`（新建）  
   - `frontend/tests/studio.spec.ts`

2. `db9159a71d8a4b19d037d35ae8211096d2b66712`  
   `fix(docs): 将宋明耀的成员登记从 B 更正为 A（算法）`  
   - `backend/model-manifests/3ddfa-v2.research.json`  
   - `backend/model-manifests/yolov5n05-face.research.json`  
   - `backend/tests/test_model_assets.py`  
   - `docs/model-assets.md`  
   - `docs/模型资产诊断与严格服务缺项记录.md`

3. `0bced3513d66c706603acc5f4f30541d2b50f259`  
   `docs: 在 CLAUDE 与 Copilot 指令开头加入先读 RULES.md`  
   - `.github/copilot-instructions.md`  
   - `CLAUDE.md`

4. `c377706f2eb4b6c8fb20e93f7eec93f4be7ba87a`  
   `docs: 注明 10f1918 属 B 范围并标明 2026-10-26 交接快照`  
   - `docs/2026-10-26_会话交接-AgeMorph3D-report.md`  
   - `docs/B系统论文章节提纲.md`

5. `cd69fbffa434dd58b221aa38974edce0599cdade`  
   `fix(frontend): 让 loading 健康刷新测试自行控制第二次响应`  
   - `frontend/tests/studio.spec.ts`

6. `8dfedb4321f12702fcea70665a08891e3c0ef6d9`  
   `chore: 在 .gitignore 中忽略 zip 与 jpeg 数据文件`  
   - `.gitignore`

相对 `10f1918` 合计 15 个路径、115 插入、9 删除。

## 3. 测试

环境：box Linux，Python 3.11.16 + Pillow 13.0.0 + ruff 0.17.1，venv 在仓库外 `/workspace/.venvs/agemorph-fx2-31116`（`uv sync --project backend --frozen --offline --extra inference --python 3.11.16`，只用本机缓存）。前端 `npm ci --offline`（28 个包，与 runner 的 lock 一致）。命令在本 worktree 内，`PYTHONDONTWRITEBYTECODE=1` / `-B`，`QT_QPA_PLATFORM=offscreen`，pytest 使用 `--basetemp=/tmp/fx2-pytest/<run>`（父目录需先存在；未使用、也未清理 `/tmp/pytest-of-box`）。

| 套件 | 命令 / 范围 | 结果 |
|---|---|---|
| Ruff | `ruff check --config backend/pyproject.toml backend/tests/test_model_assets.py` | 通过，无新 I001 |
| 后端全量 | `python -B -m pytest -q -rfEsxX -p no:cacheprovider --basetemp=/tmp/fx2-pytest/full` | **3006 passed, 3 skipped, 1 warning**（Starlette/httpx 弃用警告，原有） |
| 前端单元 | `npm test`（`tests/*.test.ts`，含新增 2 项伦理提示断言） | **342 passed, 0 failed** |
| 前端 e2e Chrome（开发中） | 因 5173 当时被 Sentinel FE-1 占用，用临时配置在 5273 跑唯一 e2e 文件 `frontend/tests/studio.spec.ts`（38 项；仓库无其他 `*.spec.ts`），不改已提交文件 | 初跑 38 项中 **36 passed, 2 failed**：窄屏溢出（当时伦理提示 nowrap，随后已修）；ready 变体时序（第 5 项，随后已修） |
| 布局回归 | 窄屏 CSS 修正后重跑「390px 窄屏…」和「笔记本单屏…」 | **2/2 passed**（含两句原文与不滚动/无横向溢出断言） |
| loading 时序复跑 | 第 5 项修复后 `--repeat-each=8` | **16/16 passed**（ready 8/8，error 8/8） |
| 送审前全量 Chrome e2e（HEAD `8dfedb4`） | 同一临时 5273 配置（`reuseExistingServer: false`，不占用/不复用 5173），连续两轮完整 38 项。第 1 轮 2026-11-21 15:59:36–16:04:57 UTC+8；第 2 轮 16:04:59–16:10:17 UTC+8。日志与 JSON 在 `/tmp/fx2-e2e/full-run1/`、`full-run2/`（不入库） | **第 1 轮 38 passed / 0 failed / 0 skipped / 0 flaky（5.3 min）**；**第 2 轮 38 passed / 0 failed / 0 skipped / 0 flaky（5.3 min）**。JSON `expected=38, unexpected=0` |

3 个后端跳过与既有原因相同：`AGEMORPH_LOCAL_RUN_LIVE` 未设；项目内没有 `backend/.venv`（本任务 venv 在仓库外）；Vite 入口检查按仓库约定跳过。

未跑 Edge e2e：box 没有 `msedge`，与 FE-1 相同。临时 Playwright 配置仅用于跑测，跑完已删除，工作区干净，没有新提交。

## 4. A/B 全仓检索

检索：`宋明耀`、`王晋涛`、`成员 A/B`、`member A/B`、`A（` / `B（`、`算法线` / `系统线`、`MingYao` / `Song` / `Wang` / `Jintao`。

已改正的错误见第 1.2 节。其余未见张冠李戴，说明如下（未改）：

- `docs/AgeMorph3D_技术框架与模块行动计划.md:5` 已是「宋明耀（A，组长，算法线）｜王晋涛（B，组员，系统线）」，正确。
- `docs/B系统论文章节提纲.md`、`docs/干净环境与离线复现准备.md`、`README.md` 中的「成员 B」指系统分工角色，没有把宋明耀写成 B。
- `docs/纹理质量离线填写与导出开发记录.md`「算法成员A填写、系统成员B交叉复核」角色正确，未绑定错名。
- 「路线 A / 路线 B」是技术路线，不是成员分工。
- `LICENSE` 的 `Copyright (c) 2026 MingYao Song` 是版权行，不是 A/B 登记。
- `tools/code_stats.py` / `tools/author-members.template.json` 的作者到 A/B 对照表仍为空（README 也写明留空），不是错误登记。
- `backend/tests/test_code_stats.py` 里「MingYao not in text」是夹具断言，与成员字母无关。

## 5. 待用户确认或未决事项

- 本分支 15 个路径的精确文件清单，供按 RULES.md:14 确认。本地提交授权不等于推送授权。
- 未 push、未开 PR；是否推送或开 PR 需用户逐次批准。
- 未把本分支 rebase 到 `10f1918` 之后的提交上。
- 新主工作台在无 GPU / 软件渲染机器上可能变慢（Sentinel 附带观察），本次未修。
- Edge e2e 未跑。
- 若日后要把 zip/jpg 测试夹具或文档图片入库，需要再加 `!` 例外。

## 6. 环境与工作树

- worktree 由已有 worktree `/workspace/AgeMorph3D_fg4` 添加，没有对主副本执行 git 写操作。
- 本 worktree 配置：`remote.origin.pushurl=DISABLED_NO_PUSH`，`user.name=MingYao Song`，`user.email=2441377859@qq.com`。
