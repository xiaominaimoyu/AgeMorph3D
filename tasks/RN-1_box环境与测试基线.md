# RN-1 box 环境与测试基线

> **声明：这只是在共享 box（Linux）上的演练，不算 L02 签收。** L02 要求另一名成员在自己的全新 Windows 机器上安装、断网启动并亲自填写记录（见 `docs/干净环境与离线复现准备.md` §8）。本文不填写那张表，也不代填“通过”。`tools/repro_check.py` 本次报告同样固定为 `l02_executed=false`、`l02_signed_off=false`、`conclusion=preparation_check_only`。

- 执行人：Runner（执行运营官）
- 执行时间：2026-11-16 05:2x（UTC+1，柏林）= 12:2x（UTC+8）
- 工作副本：`/workspace/AgeMorph3D_runner`（单独 clone，未触碰主副本 `/workspace/AgeMorph3D`）
- 提交：`35c0cd61b70976393f919dfff34834bad9a67dc8`（`35c0cd6`，PR #5 合并），`git status` 干净（`output/`、`.venv*`、`node_modules`、`frontend/dist` 均在 .gitignore 内）
- 边界：未下载任何数据集；未 push；未碰 `/workspace/hf`。本任务实际下载过的只有工具链和软件包，如实列出：
  - `output/uv-cache/`（约 372 MB）：PyPI 锁内包的 uv 缓存，是**本任务上一次（被中断的那次）运行**中由 `uv sync` 下载的；本次恢复后 `uv sync` 只做核对（Resolved 39 / Checked 38），没有新下载。
  - `output/toolchain/node-v22.23.5-linux-x64.tar.xz`（约 31 MB，SHA-256 `cdeb8670a0c81f51b4dc4ac61919f9b1ad917b304bf8221eb939570663d240f8`）：Node 22 官方 Linux 二进制包，同样是上一次被中断的运行下载并解压到 `output/toolchain/node-v22.23.5-linux-x64/`（解压后共约 233 MB），**没有装进系统 PATH**。本次的 `local_run check`、`npm ci`、`npm test`、`npm run build` 和后端测试都用的是 box 自带的 Node v24.22.1；只额外用这份 Node v22.23.5 补跑了一次前端单元测试作为对照（见 §3.3）。
  - `npm ci` 的 28 个锁内 npm 包。
- 上一次被中断的半截日志已移到 `output/rn1/prev-interrupted/`，不作为结果使用

## 1. 环境与版本

| 项 | 本次实际 | 要求（锁文件/规划） | 是否满足 |
|---|---|---|---|
| 系统 | Linux 6.12.113+ x86_64，Intel Xeon，8 vCPU，15 GiB 内存 | — | 演练机，不是 L02 的 Windows |
| Python（主 venv `backend/.venv`） | 3.11.18 | `uv.lock`: `==3.11.*` | ✅ |
| Python（`backend/.venv-py31116`） | 3.11.16 | 同上；部分研究工具硬性冻结 3.11.16（见 §4） | ✅ |
| uv | 0.13.8 | 锁文件不固定 | — |
| Node | v24.22.1（box 自带；`/usr/local/bin/node` 是 sh 包装，实际二进制 `/usr/local/lib/nodejs/node`）；另有上次运行下载、未进 PATH 的 v22.23.5 仅用于前端对照 | `package-lock.json` `engines.node >=22.18.0` | ✅（README 记录的验证环境为 24.14.1） |
| npm | 11.21.1 | 随 Node | — |
| `backend/uv.lock` SHA-256 | `6433d7ba47036e2596d6e2f83e8937607f4b9a331ab9d63445ead653a32039d3` | 与 L02 准备文档 §9 记录一致 | ✅ |
| `frontend/package-lock.json` SHA-256 | `9ef259b8f8a55cd04cc2d8c79c893950eba4b9dd7d59c5f26b7d38f461130451` | 与 L02 准备文档 §9 记录一致 | ✅ |
| Python 包与锁 | 38/38 适用包一致，0 缺失 0 不符（repro_check） | — | ✅ |
| npm 包与锁 | 28/28 适用包一致，0 缺失 0 不符（repro_check） | — | ✅ |

## 2. 执行的命令（均在 `/workspace/AgeMorph3D_runner`）

```bash
# 后端：按锁文件同步（含 inference extra 与 dev 组），两份 venv 都同步过
uv --cache-dir output/uv-cache sync --project backend --locked --extra inference --python 3.11
UV_PROJECT_ENVIRONMENT=$PWD/backend/.venv-py31116 \
  uv --cache-dir output/uv-cache sync --project backend --locked --extra inference --python 3.11.16
# → Resolved 39 packages / Checked 38 packages（无新增下载）

# 前端：为可复现重新执行 npm ci
cd frontend && npm ci            # added 28 packages, 0 vulnerabilities, 1.7 s

# 启动器检查
backend/.venv/bin/python -B tools/local_run.py check        # 退出 0，problems=[]

# 后端完整测试（README 命令为 .venv\Scripts\python.exe -m pytest -q，在 backend/ 下运行）
cd backend
.venv/bin/python -m pytest -q -rfEsxX --junitxml=../output/rn1/backend-junit.xml -p no:cacheprovider
.venv-py31116/bin/python -m pytest -q -rfEsxX --junitxml=../output/rn1/backend-py31116-junit.xml -p no:cacheprovider

# 前端完整单元测试 + 构建
cd frontend && npm test && npm run build

# 附加：只读复现检查（不做启动烟雾）
backend/.venv-py31116/bin/python -B tools/repro_check.py --skip-smoke   # 退出 0
```

`-p no:cacheprovider` 只是不写 `.pytest_cache`，不影响用例收集。

## 3. 结果

### 3.1 `python -B tools/local_run.py check`
可核对日志：`output/rn1/local-run-check.log`（文件头记录了执行时间、目录和命令 `backend/.venv/bin/python -B tools/local_run.py check`，文件尾记录 `# exit_code: 0`；审核后于 2026-11-16 05:3x UTC+1 重跑留档）。
退出码 0，`problems: []`：Python 3.11.18、Node v24.22.1、后端导入通过、Vite 入口存在；模型清单未配置（missing），启动器不授予 ready/年龄能力。

### 3.2 后端（收集 3009 项）

| 运行 | 解释器 | passed | failed | skipped | error | 耗时 | 退出码 |
|---|---|---|---|---|---|---|---|
| A | `.venv` Python 3.11.18 | 2836 | 172 | 1 | 0 | 81.6 s | 1 |
| **B（基线）** | `.venv-py31116` Python 3.11.16 | **3007** | **1** | **1** | 0 | 78.9 s | 1 |

- 两次都有 1 条既有警告：`StarletteDeprecationWarning`（`starlette.testclient` 建议改用 `httpx2`），与 README 记录的“1 条既有弃用提示”一致。
- skipped 1 项：`tests/test_local_run.py:810`，需设置 `AGEMORPH_LOCAL_RUN_LIVE=1` 才跑真实 8000/5173 命令（设计如此）。
- 日志：`output/rn1/backend-pytest.log`、`backend-junit.xml`（A），`output/rn1/backend-py31116-pytest.log`、`backend-py31116-junit.xml`（B）。

### 3.3 前端

| 项 | 结果 |
|---|---|
| `npm test`（Node 原生 TS 转换，`tests/*.test.ts`） | **340 tests，340 pass，0 fail，0 skipped**，1.9 s，退出 0 |
| `npm run build`（`tsc --noEmit && vite build`） | 通过，退出 0 |
| 对照：用 `output/toolchain` 里的 Node v22.23.5 跑 `npm test` | **340/340 通过**，退出 0（日志 `output/rn1/frontend-test-node22.log`，记录了命令、PATH 和 node 版本；node_modules 仍是 v24 下 `npm ci` 的同一份） |
| `npm run test:e2e`（Playwright chrome/msedge 通道） | **未执行**：box 只有 Google Chrome，没有 Microsoft Edge，且 README 的 340 只指单元测试；e2e 不在本次基线范围内 |

日志：`output/rn1/frontend-test.log`、`output/rn1/frontend-build.log`。

## 4. 失败及根因

### 4.1 运行 A 的 172 项失败：解释器补丁号与研究工具冻结环境不一致（环境原因，不是代码回归）
分布：`test_split_freeze.py` 62、`test_feature_join.py` 45、`test_duplicate_screening.py` 31、`test_data_quality.py` 17、`test_near_duplicate_probe.py` 12、`test_training_preflight.py` 4、`test_local_run.py` 1（即 4.2 那一项）。

根因：`tools/near_duplicate_probe.py:32` 把运行环境冻结为 `{"python_version": "3.11.16", "pillow_version": "13.0.0"}`；`preprocessing/duplicate_screening.py:274` 和 near_duplicate_probe 在运行时比较 `sys.version`，不一致就抛 `FINGERPRINT_ENVIRONMENT_MISMATCH` / “Running Python/Pillow environment differs from the frozen environment.”。下游 split_freeze、feature_join、data_quality、training_preflight 的测试夹具都经过 duplicate_screening，所以连锁失败。

按 `output/rn1/backend-junit.xml` 逐条核对这 171 项（不含 4.2 那一项）：
- **166 项直接证据**：失败信息里就是 `FINGERPRINT_ENVIRONMENT_MISMATCH` 或 “Running Python/Pillow environment differs from the frozen environment.”；
- **5 项间接证据**：失败信息里没有这句话，表现为 CLI 返回码 2 而测试期望 0/1（`test_duplicate_screening.py::test_cli_success_failure_and_input_rejection` 的 `[False-False-0]`、`[True-False-1]`），near_duplicate_probe CLI 返回 1 而期望 0（`test_cli_json_only_rejects_existing_output_and_keeps_false_flags`），或者 report.json 没有生成（`test_image_change_during_candidate_analysis_is_caught_after_analysis`、`test_cli_failed_image_retains_report_and_returns_one`）。它们走的是同一条环境检查路径，所以根因判断不变。

（初稿里写的“该错误出现 151 次”是按日志文本粗略计数，无法按用例复现，已改为上面按用例的 166 + 5。）

换成 Python 3.11.16（运行 B）后这 171 项全部通过，证实只是补丁号问题。

> 值得注意的不一致：`docs/干净环境与离线复现准备.md` §2 说“任意 3.11 补丁都可以”，PROGRESS 里 L01 也是在 3.11.18 上记录的；但完整后端测试实际需要 **3.11.16**。按文档用 `uv sync --python 3.11` 可能解析到别的补丁（本 box 解析到 3.11.18），就会出现这 171 项失败。建议 L02 执行人用 `--python 3.11.16`，或由开发者在文档里说明这一点（是否修改由用户/Forge 决定，本任务未改任何仓库文件）。

### 4.2 两次都失败的 1 项：`tests/test_local_run.py::test_real_stack_start_stop_restart`（box 环境原因）
报错：`LocalRunError(IDENTITY_MISMATCH)`：“frontend 的实际命令行与请求不一致，已结束本次创建的进程。”

根因：box 上的 `/usr/local/bin/node` 不是二进制，而是一个 sh 包装脚本（`exec /usr/local/lib/nodejs/node "$@"`）。启动器以 `node` 作为 argv[0] 启动 Vite，再从 `/proc` 读到实际命令行 argv[0] 为 `/usr/local/lib/nodejs/node`；`tools/local_run.py` 的 `argv_matches` 在非 Windows 上要求逐项完全相等，于是判为身份不符并主动结束进程（这正是它的安全设计）。

验证（日志 `output/rn1/backend-local-run-realnode.log`，审核后重跑留档，文件里记录了执行时间、目录、环境变量和完整命令及退出码）：
- 在 `backend/` 下执行 `AGEMORPH_NODE=/usr/local/lib/nodejs/node .venv-py31116/bin/python -m pytest -q -rfEs -p no:cacheprovider tests/test_local_run.py`：**27 passed，1 skipped，0 failed**，退出 0；
- 对照：`env -u AGEMORPH_NODE .venv-py31116/bin/python -m pytest -q -rfEs -p no:cacheprovider tests/test_local_run.py::test_real_stack_start_stop_restart`：1 failed，同样是 `LocalRunError: frontend 的实际命令行与请求不一致`，退出 1。端口 8000/5173/4173 测试前后都无人监听。所以这是本 box 的 Node 安装方式造成的，不是项目代码缺陷；Windows 上直接用 `node.exe` 不会遇到。

### 4.3 附带观察（不计入测试数量）
- `ruff format --check src tests`：124 个文件已格式化，通过。
- `ruff check src tests`（锁内 ruff 0.17.1，在 `backend/` 下）：17 处 I001（import 排序），如 `import pytest` 与 `from agemorph3d...` 之间要求空一行。Sentinel 在干净的 `git archive 35c0cd6` 上用锁定的 ruff 0.17.1 也复现了这 17 处，所以这是提交 35c0cd6 本身的问题，不是本机环境造成的。它和仓库里“Ruff 通过”的记录对不上，这些记录在 `PROGRESS.md` 第 9 行（L01）、第 11 行（K2），以及 `docs/干净环境与离线复现准备.md` §9（第 201 行）；README 第 11、13 行并没有提 Ruff。本任务未修改代码。

## 5. 与 README 记录的对比

| 记录 | 记录值 | 本次 | 差异 | 解释 |
|---|---|---|---|---|
| K4 批后端 | 2926 | 3009 收集（B：3007 通过） | +83 | K4 与 K2 同在提交 `dc2604e`（2026-10-30）。K4 先记 2926；随后 K2 新增 `test_age_shape_mesh_probe.py` 30 项 → 2956（README/TASKS 写明“30 新增/完整 2956”，本次在 `dc2604e` 上收集该文件确为 30 项） |
| K2 批后端 | 2956 | 3009 收集 | +53 | 在 `dc2604e` 检出的临时 worktree 中 `pytest --collect-only` 实测 **2956**，与记录完全一致。之后到 `35c0cd6` 的 L01/L02/L03 提交新增：`test_local_run.py` +28、`test_repro_check.py` +14、`test_code_stats.py` +9、`test_model_assets.py` +2（25→27），合计 **+53** = 3009 ✔ |
| 新增项结果 | — | 3009 = 3007 通过 + 1 失败 + 1 跳过 | — | 失败、跳过都在新增的 `test_local_run.py` 里，原 2956 项在 3.11.16 下全部通过 |
| K4 批前端 | 340 | 340 收集 / 340 通过 | 0 | `dc2604e` 之后 `frontend/tests` 没有任何改动（`git diff --stat dc2604e 35c0cd6 -- frontend/tests` 为空） |

补充：PROGRESS 中 L02 准备记录提到 `test_repro_check.py` 为 13 项通过；当前提交收集为 14 项（之后的 UTF-8 修复提交 `20aae7e`/`34c5b60` 一带新增），不影响上述合计。

临时 worktree（`/tmp/am3d_wt_dc2604e`）只用于收集计数，已删除并 `git worktree prune`。

## 6. 结论（演练层面）

- 锁文件哈希、38 个 Python 包、28 个 npm 包与锁一致；启动器 check 无问题。
- **后端基线（Python 3.11.16）：3009 项中 3007 通过、1 失败（box 的 node 包装脚本导致）、1 跳过（设计如此）**；在 3.11.18 下另有 171 项因研究工具冻结了 Python 补丁号而失败。
- **前端基线：340/340 通过**（Node v24.22.1；用 Node v22.23.5 对照也是 340/340），构建通过；e2e 未跑（缺 Edge）。
- 与 README 的差异全部可以按提交逐项对上，没有不明来源的增减。
- **再次声明：这是 box 上的演练，不算 L02 签收。** L02 仍需另一名成员在干净的 Windows 机器上执行并亲自填写记录。

## 7. 产物位置（都在被忽略的 `output/` 下，未提交）

`/workspace/AgeMorph3D_runner/output/rn1/`：`backend-pytest.log`、`backend-junit.xml`、`backend-start.txt`、`backend-py31116-pytest.log`、`backend-py31116-junit.xml`、`backend-py31116-start.txt`、`backend-local-run-realnode.log`、`local-run-check.log`、`frontend-test.log`、`frontend-test-node22.log`、`frontend-build.log`、`repro-check-skip-smoke.log`、`prev-interrupted/`（上次中断的半截日志）；`output/repro-check/report.json`（repro_check 报告）。
