# RN-4 本机执行手册（Windows PowerShell）

- 版本：v1（第一部分），2026-11-21 起草；起草：Runner（执行运营官）；状态：**第一部分待 Sentinel 审核；第二部分（LX-1—LX-3）为占位**
- 依据：规划 v2 第 140 行（RN-4）与第 182—183 行（LX 通用规则）；`BP-3_G1验收用例单.md` v1.3；`BP-3_g1_check.py`；`BP-6_E01冻结要点.md`；`RD-3_AFLW核查.md`；`RN-1_box环境与测试基线.md`；RN-3 两份下载回执；仓库 `docs/干净环境与离线复现准备.md`（均在提交 `10f1918` 读取）
- 时间：本文时间均标注时区；项目文档约定用 UTC+8，必要处同时给出 UTC+1（柏林）
- 执行地点：用户本机 Windows，项目根目录按仓库示例写作 `D:\project file\AgeMorph3D`，实际路径不同就替换
- 标记：
  - **【Linux 实测】**：Runner 在 box 的独立副本 `/workspace/AgeMorph3D_runner`（HEAD `10f19181196f1fd9b86ba9d7acf11f1c35c2515e`，工作区干净）里用等价 Linux 命令跑过，预期输出是实测原文。日志在 `/workspace/AgeMorph3D_runner/output/rn4/`。
  - **【Windows 推断】**：Windows 上没有实测，由源码、仓库文档或 Linux 结果推出。执行时以本机实际输出为准，不一致就照实记录，不改写成“通过”。
- 边界：本手册只写文档。Runner 没有改仓库、没有提交或推送，也没有在 box 上下载 AgeDB 或 3DDFA `test.data.zip`。

---

## ⚠️ 硬性规则（每一步都适用）

1. **密码**：本手册里没有、也不会出现任何密码。**任何时候都不要把密码（AgeDB 解压密码、网盘密码、账号密码等）发给任何机器人或 agent**，包括 Atlas、Runner、Sentinel、Forge、Blueprint。需要密码的步骤由你本人在本机输入，不写进任何文件、命令历史或截图。
2. **回传内容**：**只把 `summary.json` 回传给团队。** 回传前你自己打开看一眼，确认里面没有文件名、人名或照片内容。
   - LX 任务（第二部分）由 FG-8 脚本生成 `output/research/<目录>/summary.json`，只回传这个文件。
   - G1 用例单的回执按 BP-3 写作 `U-6_G1执行回执.md`，内容只限用例结果、HTTP 状态码和文件 SHA-256，**不是 `summary.json` 这个文件名**。是否把它也统一成 `summary.json`，由 Atlas / Sentinel 决定（见 §9 待决问题）。在决定之前，G1 也只回传这类“结果 + 状态码 + 哈希”的汇总，不回传其他任何文件。
3. **照片与截图不出本机**：照片、含人脸或面部网格的截图、PNG 效果图、导出的 GLB **一律不出本机**。它们不上传 box、不提交 Git、不发给任何 agent，也不发聊天软件或云盘。需要核对画面时，由 A（宋明耀）或 B（王晋涛）在本机查看后写文字结论。
4. 数据不进 Git：照片放 `data\g1-inputs\`，证据放 `output\g1\`（仓库 `.gitignore` 忽略 `data/` 和 `output/`）；数据集放仓库外（§7、§8）。
5. 不手改模型清单的 SHA-256、大小或 `license_status`，也不用研究开关代替严格服务（BP-3 §0.2）。

---

# 第一部分

## 1. 一次性准备：安装工具

| 工具 | 要求 | 为什么 |
|---|---|---|
| Git for Windows | 任意新版 | 克隆、检出 `10f1918` |
| uv | 官方安装方式（版本不在锁文件里） | 按锁文件装 Python 依赖 |
| **Python 3.11.16（64 位）** | **必须正好 3.11.16** | 见下方说明 |
| Node.js | `>=22.18.0`（`frontend/package-lock.json` 的 `engines.node`） | `npm ci`、前端构建 |
| Google Chrome、Microsoft Edge | 当前版本 | G1-UI 与 G1-EXP 两个浏览器用例 |

**为什么必须是 3.11.16（RN-1 发现）**：仓库文档 `docs/干净环境与离线复现准备.md` §2 写“任意 3.11 补丁都可以”，但研究工具 `tools/near_duplicate_probe.py:32` 把环境指纹冻结在 Python 3.11.16 + Pillow 13.0.0。RN-1 在 box 上用 3.11.18 跑后端测试，有 171 项因此失败（166 项直接报 `FINGERPRINT_ENVIRONMENT_MISMATCH`，5 项是间接表现）；换成 3.11.16 后全部通过。所以本机也请用 3.11.16，避免同样的问题。

【Windows 推断】用 uv 安装指定补丁版本：

```powershell
uv python install 3.11.16
uv python list --only-installed
```

预期：列表里有 `cpython-3.11.16-windows-x86_64-none`（名称以本机输出为准）。

## 2. 克隆并检出 `10f1918`

```powershell
New-Item -ItemType Directory -Force 'D:\project file' | Out-Null
Set-Location -LiteralPath 'D:\project file'
git clone https://github.com/xiaominaimoyu/AgeMorph3D.git AgeMorph3D   # 已有克隆就跳过这一行，改为 git fetch origin
Set-Location -LiteralPath 'D:\project file\AgeMorph3D'
git checkout --detach 10f19181196f1fd9b86ba9d7acf11f1c35c2515e
git rev-parse HEAD
git status --porcelain
```

预期：
- `git rev-parse HEAD` 输出 `10f19181196f1fd9b86ba9d7acf11f1c35c2515e`【Linux 实测】。
- `git status --porcelain` 没有输出（工作区干净）【Linux 实测：0 项改动】。

已有克隆、而且本地有未提交改动时，先停下来问 B（王晋涛），不要 `reset`。

## 3. 按锁文件安装后端（Python 3.11.16）

```powershell
Set-Location -LiteralPath 'D:\project file\AgeMorph3D'
uv --cache-dir output\uv-cache sync --project backend --locked --extra inference --python 3.11.16
backend\.venv\Scripts\python.exe --version
Get-FileHash -Algorithm SHA256 backend\uv.lock
```

预期：
- `uv sync` 正常结束，没有 “lockfile needs to be updated” 一类错误（`--locked` 遇到锁不一致会直接报错退出）。
- `python --version` 输出 `Python 3.11.16`【Linux 实测】。
- `backend\uv.lock` 的 SHA-256 为 `6433D7BA47036E2596D6E2F83E8937607F4B9A331AB9D63445EAD653A32039D3`（PowerShell 显示大写；与 box 小写值 `6433d7ba…39d3` 是同一个）【Linux 实测】。
- Linux 等价命令 `uv sync --project backend --locked --extra inference --python 3.11.16 --offline --dry-run` 在已装好的环境上输出 `Resolved 39 packages`、`Checked 38 packages`、`Would make no changes`【Linux 实测】。Windows 上包数可能差 1—2 个：锁文件里有平台标记，Windows 会装 `colorama`、不装 `uvloop`（仓库文档 §2）【Windows 推断】。

注意：
- 虚拟环境必须在 `backend\.venv`。`tools\local-run.ps1` 固定用 `backend\.venv\Scripts\python.exe` 启动服务，BP-3 的 `$PY` 也指向这里。
- 不要用 `pip install`，也不要去掉 `--locked`。
- 已经有一个不是 3.11.16 的 `backend\.venv` 时，先把它改名备份（例如 `backend\.venv-old`），再重新执行上面的 `uv sync`。

## 4. 按锁文件安装前端（Node 22.18+）

```powershell
node --version
Set-Location -LiteralPath 'D:\project file\AgeMorph3D\frontend'
npm ci
npm test
npm run typecheck
npm run build
Set-Location -LiteralPath 'D:\project file\AgeMorph3D'
Get-FileHash -Algorithm SHA256 frontend\package-lock.json
```

预期：
- `node --version` 不低于 `v22.18.0`。box 用的是 v24.22.1，同样满足。
- `npm ci`：`added 28 packages, and audited 29 packages`，`found 0 vulnerabilities`【Linux 实测（FE-1）】；Windows 上包数可能因平台可选二进制略有不同【Windows 推断】。
- `npm test`：`tests 340`、`pass 340`、`fail 0`【Linux 实测（FE-1，10f1918）】。
- `npm run typecheck`：无输出，退出码 0【Linux 实测】。
- `npm run build`：最后一行类似 `✓ built in 246ms`【Linux 实测】。
- `package-lock.json` SHA-256：`9EF259B8F8A55CD04CC2D8C79C893950EBA4B9DD7D59C5F26B7D38F461130451`【Linux 实测】。

**关于 `AGEMORPH_NODE`（RN-1 发现）**：启动器会核对它拉起的 Node 进程身份。box 上的 `node` 是一个 sh 包装脚本，真正运行的程序和命令行不一致，导致 1 项测试失败；把 `AGEMORPH_NODE` 指向真正的 Node 程序后通过。
- Windows 上 Node 不在 PATH 时，按仓库文档设置 `$env:AGEMORPH_NODE = 'D:\JAVA run tools\node.exe'`（换成本机实际路径）。
- 如果你的 `node` 是 nvm-windows、Volta、fnm 等版本管理器的“垫片”（shim），也请把 `AGEMORPH_NODE` 直接指向真实的 `node.exe`，例如用 `(Get-Command node).Source` 找到后再确认它不是 `.cmd`/`.ps1` 垫片【Windows 推断】。

## 5. 启动前的只读检查（不需要模型）

```powershell
Set-Location -LiteralPath 'D:\project file\AgeMorph3D'
.\tools\local-run.ps1 check
"exit=$LASTEXITCODE"
.\tools\repro-check.ps1 --skip-smoke --output output\repro-check\pre-models.json
"exit=$LASTEXITCODE"
```

预期：
- `local-run.ps1 check`：输出一段 JSON，`"problems": []`，最后的 `detail` 为 `检查完成。进程可达和模型就绪是两项不同结果；启动器不授予 ready 或年龄能力。`，`exit=0`【Linux 实测：`python -B tools/local_run.py check`】。
- `repro-check.ps1 --skip-smoke`（不传模型清单）：控制台一行 JSON，含 `"conclusion": "preparation_check_only", "exit": 0`；报告里 `problems` 为空，`gaps` 只有 `MODELS_NOT_CONFIGURED`、`UV_VERSION_NOT_IN_LOCK`、`SMOKE_SKIPPED` 三项，`python.version` 为 `3.11.16`，`git.commit` 为 `10f1918…`，`git.dirty` 为 false，`l02_executed` 与 `l02_signed_off` 都是 false【Linux 实测】。这些 gaps 只记录，不算失败。
- 对照：box 上没有模型文件，传入模型清单时 `repro-check` 退出码 1，`problems` 为两条 `MANIFEST_UNREADABLE`；`local_run.py diagnose` 退出码 1，`status` 为 `blocked`【Linux 实测】。**在本机放好模型之后**，这两条应分别变成退出码 0 和 `preconditions_met`（见 §6 的 G1-ENV-01、G1-ENV-02）【Windows 推断】。

## 6. G1 用例执行（按 BP-3，在 `10f1918` 上）

完整的输入要求、逐步命令、期望结果、证据文件名和签收表都以 **`BP-3_G1验收用例单.md` v1.3** 为准，本节只给执行顺序、关键命令和 Runner 能在 box 上核对的部分。共 31 个必选用例和 1 个可选用例（G1-ENV-04）。**必选用例任一“未通过”或“阻塞”，G1 不通过**（BP-3 §0.2【建议】）。

### 6.1 前置条件

1. 已完成 §1—§5。
2. 模型文件已按 `docs/model-assets.md` 与 `docs/B0模型验证与复现.md` 放进 `data\models\`。本地清单已从 `backend\model-manifests\` 重新复制（BP-3 G1-ENV-01 前置条件）。
3. 照片已按 BP-3 §4 准备好，放在 `data\g1-inputs\`。只用**本人书面同意的成年人**照片；同意书留在本机，回执只写同意编号（例如 `C-P01`），不写姓名。
4. 8000、4173 端口空闲：

```powershell
Get-NetTCPConnection -LocalPort 8000,4173 -State Listen -ErrorAction SilentlyContinue
```

预期：没有输出。

### 6.2 每次开新终端先执行（BP-3 §0.4，原样照抄）

把 BP-3 §0.4 的整段代码粘进 PowerShell。它设置 `$G1`、`$API`、`$PY`、`$CHK`、`$DET`、`$REC`，并定义 `G1-Reconstruct`、`G1-Fetch` 两个函数。注意：
- `$G1 = 'output\g1\run-20261120'` 里的日期改成实际执行日（UTC+8）。
- `$env:AGEMORPH_NODE` 只在 Node 不在 PATH 或是垫片时需要（§4）。
- PowerShell 5.1 里 `curl` 是 `Invoke-WebRequest` 的别名，一律用 `curl.exe`。

### 6.3 放置辅助脚本 `g1_check.py`

`BP-3_g1_check.py` 与 BP-3 附录 A 的内容逐字相同（Runner 已核对）。文件 SHA-256：`c79cd915fe08c55bdf8cfc807e35f74fd4e01159aaa320cc196add99befcffbc`【Linux 实测】。

```powershell
New-Item -ItemType Directory -Force "$G1\tools" | Out-Null
# 把 BP-3 附录 A 的脚本（或团队给你的 BP-3_g1_check.py）存为 $G1\tools\g1_check.py，然后核对哈希：
(Get-FileHash -Algorithm SHA256 "$G1\tools\g1_check.py").Hash.ToLower()
```

预期：输出 `c79cd915fe08c55bdf8cfc807e35f74fd4e01159aaa320cc196add99befcffbc`。不一致就不要用，先问 B。

**用法**（只读、只用标准库；在项目根目录执行）：

| 子命令 | 参数 | 检查内容 | 用在哪些用例 |
|---|---|---|---|
| `resp <响应.json> [--source-age unknown\|<数值>]` | `/api/reconstruct` 的响应 JSON | 键齐全；`mesh_id` 为 32 位小写十六进制；`topology_id` 为 `tddfa-bfm-canon-v1-cc449ed7…e7cb`；`asset_mode=static`；`capabilities` 两项为 false；`texture_url` 为 null；`shape` 40 维、`expr` 10 维；`t=[0,0,0]`；R 正交且行列式为 1（容差 1e-4【建议】）；给了 `--source-age` 时再核对 `source_age` | G1-ID-01—06 等 |
| `glb <文件.glb> [--kind service\|viewer] [--response <响应.json>]` | 服务导出（service，默认）或工作台导出（viewer）的 GLB | 单个内嵌 buffer、无外部图片、无 morph target；顶点 38,365、三角形 76,073；service 还查 generator 和坐标元数据；viewer 查 `AgeMorph3D_Loaded_Model` 根节点；extras 为 static 且不含年龄键；给了 `--response` 时核对 topology 与 source_age 和响应一致 | G1-ID、G1-EXP、G1-EXPIRE-04 |
| `angle <响应A.json> <响应B.json>` | 两份响应 | 只**报告**两个 R 之间的相对旋转角 `relative_rotation_deg`，`checks` 为空，所以 `ok` 恒为 true；是否满足 ≥10° 等【建议】判断由执行人看数值 | G1-ID-03、G1-ID-05 |
| `distinct <a.glb> <b.glb> [...]` | 至少两个 GLB | SHA-256 两两不同、顶点坐标最大差都大于 0 | G1-ID-02、G1-ID-05 |

- 输出：一行 JSON，`{"command": …, "ok": true/false, "checks": {…}, "info": {…}}`；出错时为 `{"command": …, "error": "…"}`。
- 退出码：**0** = 本项检查全部满足；**1** = 有不满足项（看 `checks` 里哪项是 false）；**2** = 用法或文件错误（不带参数时打印用法说明）。
- 【Linux 实测】（用 Runner 构造的合成 JSON，不含任何照片或真实结果，日志 `output/rn4/g1_check-usage.log`）：
  - 不带参数：打印用法，退出码 2。
  - `resp` 合格样例加 `--source-age unknown`：`"ok": true`，12 项 checks 全为 true，退出码 0。
  - `resp` 中 `asset_mode` 改成非 static：`"ok": false`，`asset_mode_static: false`，退出码 1。
  - `angle` 单位阵与绕 y 轴 30°：`relative_rotation_deg` 为 `29.99999999999998`，退出码 0。
  - `glb` 传入非 GLB 文件：`{"command": "glb", "error": "不是 GLB（缺少 glTF 魔数）"}`，退出码 2。
  - 文件不存在：`error` 为 `[Errno 2] No such file or directory…`，退出码 2。
- 真实模型输出的 `resp`/`glb` 结果 box 上无法实测（box 没有模型权重，也不能有照片）【Windows 推断，以 BP-3 期望结果为准】。

Windows 调用示例：

```powershell
& $PY $CHK resp "$G1\01-identity\ID01-P00-front.json" --source-age unknown | Out-File -Encoding utf8 "$G1\01-identity\check-resp-P00.json"
"exit=$LASTEXITCODE"
```

### 6.4 执行顺序与关键预期

下表的“关键预期”是摘要，判定以 BP-3 各用例的“期望结果”全文为准。“box 核对”一列说明 Runner 在 box 上能验证到什么程度。

| 顺序 | 用例 | 必选 | 做什么（详见 BP-3） | 关键预期 | box 核对 |
|---|---|---|---|---|---|
| 1 | G1-ENV-04 | 可选 | 如要断网，在 ENV-03 之前断开并记录 | 断网下结果与联网一致 | — |
| 2 | G1-ENV-01 | 是 | 建证据目录；`.\tools\repro-check.ps1 --skip-smoke --detector-manifest $DET --reconstructor-manifest $REC --output "$G1\00-env\repro-check-skip-smoke.json"`；填 §2 环境表 | 退出码 0；包与锁一致；4 个模型文件哈希与清单一致；`l02_executed=false` | 不带模型的同一命令实测 exit 0；带清单实测 exit 1（box 无模型，属预期）|
| 3 | G1-ENV-02 | 是 | `.\tools\local-run.ps1 diagnose --detector-manifest $DET --reconstructor-manifest $REC` | 退出码 0，`status` 为 `preconditions_met` | box 无模型：实测 exit 1、`blocked`（预期）|
| 4 | G1-ENV-03 | 是 | ① `start --research-allow-unresolved` 负例；①b 单元测试；② `start --production`；③ 读 `/api/health`；④ `/api/aging` | ① 退出码 2，含 `unrecognized arguments: --research-allow-unresolved`，8000/4173 无监听；①b `1 passed`；③ 两个模型 `ready`，`age_morph`/`age_texture` 为 false，`api_version` 1.2，`device` cpu；④ HTTP 503 `MODEL_NOT_READY` | ① 实测 exit 2、同样报错、端口无监听；①b 实测 `1 passed`；②—④ 需要模型，无法实测 |
| 5 | G1-ID-01 | 是 | P00（astronaut）重建并取 GLB，跑 `resp`、`glb` | HTTP 200；两份 check 都 `"ok": true` | — |
| 6 | G1-ID-02 | 是 | P01—P03 正面重建；`distinct` | 3 次 HTTP 200；4 个 GLB 两两不同 | — |
| 7 | G1-ID-03 | 是 | 左右约 30° 侧转；`angle` | 6 次 HTTP 200；相对角 ≥10°【建议】 | — |
| 8 | G1-ID-04 | 是 | 大侧脸 | 每张只能是 200 + ok，或 422 `NO_FACE` / 500 `RECONSTRUCTION_FAILED` | — |
| 9 | G1-ID-05 | 是 | EXIF 竖拍与镜像 | 两次 HTTP 200；EXIF 相对角 <45°【建议】 | — |
| 10 | G1-ID-06 | 是 | `source_age` 35 / 19 / 71 / abc / 1e2 | 35 → 200、`method:"user"`；其余 422 | — |
| 11 | G1-ID-07 | 是 | 3 项几何变换单元测试 | 退出码 0，`3 passed` | 实测 `3 passed` |
| 12 | G1-UI-01 / UI-02 | 是 | Chrome / Edge 生产构建工作台：上传、重建、查看、导出 | 见 BP-3 | box 无 Edge、无模型，未实测 |
| 13 | G1-UI-03 | 是 | 演示回归 | 徽标变回“演示模型”、读数 30 等 | — |
| 14 | G1-NF-01、MF-01 | 是 | 无人脸、多人脸 | 422 `NO_FACE` / `MULTI_FACE`，随后恢复 200 | — |
| 15 | G1-BAD-01—06 | 是 | 坏图、格式、超字节、超像素、动画、工作台坏图 | 400 `BAD_INPUT` / 415 `UNSUPPORTED_MEDIA_TYPE` / 413 `PAYLOAD_TOO_LARGE`、`INPUT_TOO_LARGE` 等，随后恢复 200 | — |
| 16 | G1-EXP-01、EXP-02 | 是 | 严格服务 GLB 双浏览器往返；工作台导出再导入 | `static-mesh-research.json` 为 `passed`，38,365 顶点 / 76,073 三角形 | — |
| 17 | G1-CAN-01、CAN-02 | 是 | 工作台取消；命令行中途断开 | “重建已取消”；curl 退出 28；之后恢复 200 | — |
| 18 | G1-CAN-03 | 是 | 合成测试佐证不发布迟到结果 | 退出码 0、无失败 | 实测 `108 passed` |
| 19 | G1-EXPIRE-01—04 | 是 | TTL、坏资产、重启后旧 ID、坏 GLB | 见 BP-3 | — |
| 20 | G1-SUM-01 | 是 | 停服务、扫日志、生成 `sha256sums.txt` | 8000/4173 不再监听；`log-scan.txt` 为空 | — |

### 6.5 box 上实测过的三条单元测试命令（Windows 写法）

BP-3 原命令没有 `--basetemp`。【建议】本机也加上 `--basetemp`，把 pytest 临时文件放进被忽略的证据目录，避免散落到系统临时目录：

```powershell
Push-Location backend
# G1-ENV-03 步骤 1b
.\.venv\Scripts\python.exe -m pytest -q "tests/test_local_run.py::test_spawn_rejects_install_commands_and_research_bypass" --basetemp "..\$G1\pytest-tmp\env03" *>&1 |
  Out-File -Encoding utf8 "..\$G1\00-env\pytest-research-bypass.txt"
"exit=$LASTEXITCODE" | Add-Content "..\$G1\00-env\pytest-research-bypass.txt"
# G1-ID-07
.\.venv\Scripts\python.exe -m pytest -q `
  "tests/test_detector.py::test_box_and_points_share_letterbox_inverse_without_mirroring" `
  "tests/test_tddfa.py::test_roi_uses_xywh_center_shift_integer_expansion_and_rounded_crop" `
  "tests/test_inputs.py::test_exif_orientation_is_applied_and_removed" --basetemp "..\$G1\pytest-tmp\id07" *>&1 |
  Out-File -Encoding utf8 "..\$G1\01-identity\pytest-geometry-transforms.txt"
"exit=$LASTEXITCODE" | Add-Content "..\$G1\01-identity\pytest-geometry-transforms.txt"
# G1-CAN-03
.\.venv\Scripts\python.exe -m pytest -q tests/test_static_api.py tests/test_asset_cache.py tests/test_runtime.py --basetemp "..\$G1\pytest-tmp\can03" *>&1 |
  Out-File -Encoding utf8 "..\$G1\05-cancel\pytest-static.txt"
"exit=$LASTEXITCODE" | Add-Content "..\$G1\05-cancel\pytest-static.txt"
Pop-Location
```

【Linux 实测】（10f1918，Python 3.11.16，`--basetemp` 在 `output/rn4/` 下）：
- ENV-03 1b：`1 passed`，exit 0。
- ID-07：`3 passed`，exit 0。
- CAN-03：`108 passed`，exit 0（BP-3 只要求“退出码 0、无失败”，没有写数量）。

### 6.6 回执

执行完把 BP-3 §7 结果汇总填好（存为 `$G1\G1-results.md`），回执只写用例结果、HTTP 状态码和文件 SHA-256，按硬性规则第 2、3 条回传。`$G1\sha256sums.txt` 可以回传哈希，但对应的照片、截图、GLB 本身不回传。

## 7. 3DDFA `test.data.zip`（只在本机获取，不进 box）

依据：经 Atlas 转达的用户决定（2026-11-21）——在用户本机获取 3DDFA 的 `test.data.zip`，box 上不下载；BP-6 Q-11 已关闭。

### 7.1 官方来源

- 官方仓库：**cleardusk/3DDFA** — https://github.com/cleardusk/3DDFA 。README 的训练/评测资源表（`readme.md` 第 201 行）原文：

  > `| test.data.zip | [BaiduYun](https://pan.baidu.com/s/1DTVGCG5k0jjjhOc8GcSLOw) or [Google Drive](https://drive.google.com/file/d/1r_ciJ1M0BSRTwndIBt42GlPFRv6CvvEP/view?usp=sharing), 151M | The cropped images of AFLW and ALFW-2000-3D testset |`

- 官方下载链接（二选一）：
  - Google Drive：https://drive.google.com/file/d/1r_ciJ1M0BSRTwndIBt42GlPFRv6CvvEP/view?usp=sharing
  - 百度网盘：https://pan.baidu.com/s/1DTVGCG5k0jjjhOc8GcSLOw
- README 快照：`/workspace/AgeMorph3D_tasks/RN-4_refs/3DDFA_readme.md`。抓取地址为 https://raw.githubusercontent.com/cleardusk/3DDFA/master/readme.md ，时间 2026-11-21 09:00:54 UTC+1 ＝ 16:00:54 UTC+8；快照 SHA-256 `4cca6b63…f192`；同目录 `.meta` 记录抓取信息。
- 3DDFA_V2（https://github.com/cleardusk/3DDFA_V2 ）的 README 没有列出 `test.data.zip`，不作为来源。
- **不要**用 Kaggle、Hugging Face、TFDS 或其他转存。

### 7.2 下载与校验步骤

1. 用浏览器打开上面的 Google Drive 链接，点“下载”。文件大于 100 MB，Google 会提示“无法扫描病毒”，点“仍然下载”。（百度网盘按网页提示下载即可。如果网盘要求登录或提取码，**自己在网页里输入，不要发给任何机器人**。）
2. 把文件放到**仓库外**的目录，例如 `D:\datasets\3ddfa_test_data\archives\test.data.zip`。**不要放进 `D:\project file\AgeMorph3D\` 下的任何位置。**
3. 计算哈希并记录：

```powershell
New-Item -ItemType Directory -Force 'D:\datasets\3ddfa_test_data\archives' | Out-Null
# 把下载好的文件移动到上面的目录后：
$f = 'D:\datasets\3ddfa_test_data\archives\test.data.zip'
Get-Item -LiteralPath $f | Select-Object Name, Length, LastWriteTime
(Get-FileHash -Algorithm SHA256 -LiteralPath $f).Hash.ToLower()
```

预期与比对：
- **官方没有公布 SHA-256 或其他校验值**（README 只写了大约 “151M”）。因此没有可比对的期望哈希，**请把你算出的 SHA-256、字节数（`Length`）、下载日期（UTC+8）和所用链接（Drive 或百度）记下来，作为团队今后的基准**，写进 LX/summary 类汇总回传（只回传这几项数字，不回传文件本身）。
- `Length` 应在 151 MB 左右（约 1.5—1.6 亿字节）。这只是 README 自述的大小，RD-3 和 Runner 都没有实测过。明显偏小（例如只有几 KB）通常说明下载到的是网页而不是 zip，请重新下载。
- 这一步【Windows 推断】：box 上按规定没有下载，所以没有实测。

4. 解压到同样在仓库外的目录（先校验、后解压）：

```powershell
Expand-Archive -LiteralPath $f -DestinationPath 'D:\datasets\3ddfa_test_data\extracted'
(Get-ChildItem -LiteralPath 'D:\datasets\3ddfa_test_data\extracted' -Recurse -File | Measure-Object).Count
```

   把文件数也记下来。解压后的目录结构以实际为准，本手册不预设。【建议】解压完把 `extracted` 目录设为只读：右键 → 属性 → 只读，或 `attrib +R /S /D 'D:\datasets\3ddfa_test_data\extracted\*'`。

### 7.3 使用限制（必须遵守）

- **只能用来计算 NME**。它是 120×120 的裁剪图，不含 `.mat` 三维参数（v3 §2-F），不能算 WIDER AP，不能评端到端重建或三维重建误差，也不能评年龄或身份（BP-6 第 17 行）。
- **NME 按全部 68 点计算（含不可见点）**【用户已确认 2026-11-21，BP-6 N-2】。其余口径以 BP-6 为准：2D、原图像素坐标（裁剪图上的预测须用官方 `roi_box` 映射回原图）、归一化距离为真值 68 点外接矩形的 `sqrt(宽×高)`、按偏航角三箱求均值再取平均。
- 不能代替官方 `AFLW2000-3D.zip`（完整评测用的是 RN-3 已下载的官方包）。
- **许可**：`test.data.zip` 本身是 AFLW 裁剪图的再分发，受 TU Graz AFLW 条款约束——**仅限非商业研究，不得复制、发布或分发任何部分**（同组织单一站点内部使用除外）（RD-3）。所以它**不进 Git、不上云、不传 box、不发给任何人**。

## 8. WIDER FACE 放到 D 盘

box 上已经有一份官方 WIDER FACE（RN-3，路径 `/workspace/datasets/wider_face/`）。如果你要在本机也放一份，请自己从官方渠道下载，然后按下面的目录和哈希核对。不要从 box 往外拷贝。

### 8.1 官方来源（与 RN-3 一致）

- 作者主页：http://shuoyang1213.me/WIDERFACE/ 的 Download 栏。
- train：Google Drive https://drive.google.com/file/d/15hGDLhsx8bLgLcIRD5DhYt5iBxnjNF1M/view?usp=sharing
- val：Google Drive https://drive.google.com/file/d/1GUCogbp16PMGa39thoMMeWxp7Rp5oM8Q/view?usp=sharing
- split：https://mmlab.ie.cuhk.edu.hk/projects/WIDERFace/support/bbx_annotation/wider_face_split.zip （CUHK 历史官方入口）
- 不需要 `WIDER_test.zip`（RN-3 没有下载）。
- 许可：Creative Commons BY-NC-ND（主页未写版本，HF 卡片写 4.0）：非商业、署名、禁止演绎；不再分发图片或标注；引用 Yang et al., CVPR 2016。

### 8.2 目录布局（与 box 的 `/workspace/datasets/wider_face` 相同）

【建议】放在仓库外的 `D:\datasets\wider_face\`。这和 box 上的 `/workspace/datasets/` 一一对应，脚本只要换根目录就能用。

```text
D:\datasets\wider_face\
  archives\                          # 下载的 3 个 zip；校验并解压后可以删除（v3 §3）
    WIDER_train.zip  WIDER_val.zip  wider_face_split.zip
  extracted\
    WIDER_train\files\WIDER_train\images\<61 个事件目录>\*.jpg     # 12,880 张
    WIDER_val\files\WIDER_val\images\<61 个事件目录>\*.jpg         # 3,226 张
    wider_face_split\files\wider_face_split\                      # 7 个文件
```

`files\` 这一层是 box 上安全解压工具（FG-4）固定的输出目录。本机照样建这一层，两边路径就能对得上。

如果更想放在仓库内被忽略的 `D:\project file\AgeMorph3D\data\datasets\wider_face\`（仓库已有 FG-NET 用 `data/datasets/fgnet/` 的先例，`data/` 被 `.gitignore` 忽略），也可以，但要确认 `git status` 里看不到它。是否统一放在哪里，由 A/B 决定。

### 8.3 校验压缩包（解压前）

```powershell
$W = 'D:\datasets\wider_face'
New-Item -ItemType Directory -Force "$W\archives","$W\extracted" | Out-Null
# 把下载好的 3 个 zip 放进 $W\archives 后：
$expected = @{
  'WIDER_train.zip'      = @{ Size = 1465602149; Sha = 'e23b76129c825cafae8be944f65310b2e1ba1c76885afe732f179c41e5ed6d59' }
  'WIDER_val.zip'        = @{ Size = 362752168;  Sha = 'f9efbd09f28c5d2d884be8c0eaef3967158c866a593fc36ab0413e4b2a58a17a' }
  'wider_face_split.zip' = @{ Size = 3591642;    Sha = 'c7561e4f5e7a118c249e0a5c5c902b0de90bbf120d7da9fa28d99041f68a8a5c' }
}
foreach ($n in $expected.Keys) {
  $p = Join-Path "$W\archives" $n
  $len = (Get-Item -LiteralPath $p).Length
  $sha = (Get-FileHash -Algorithm SHA256 -LiteralPath $p).Hash.ToLower()
  "{0}  size={1} ({2})  sha256={3} ({4})" -f $n, $len, ($len -eq $expected[$n].Size), $sha, ($sha -eq $expected[$n].Sha)
}
```

预期：三行都是 `(True)` 和 `(True)`。期望值来自 RN-3 回执：box 上从同一官方链接下载，并与 Hugging Face `CUHK-CSE/wider_face` 的 LFS 元数据互证一致。任何一项 `False` 都不要解压，重新下载。

| 文件 | 字节数 | SHA-256 |
|---|---|---|
| `WIDER_train.zip` | 1,465,602,149 | `e23b76129c825cafae8be944f65310b2e1ba1c76885afe732f179c41e5ed6d59` |
| `WIDER_val.zip` | 362,752,168 | `f9efbd09f28c5d2d884be8c0eaef3967158c866a593fc36ab0413e4b2a58a17a` |
| `wider_face_split.zip` | 3,591,642 | `c7561e4f5e7a118c249e0a5c5c902b0de90bbf120d7da9fa28d99041f68a8a5c` |

### 8.4 解压与计数

```powershell
Expand-Archive -LiteralPath "$W\archives\WIDER_train.zip"      -DestinationPath "$W\extracted\WIDER_train\files"
Expand-Archive -LiteralPath "$W\archives\WIDER_val.zip"        -DestinationPath "$W\extracted\WIDER_val\files"
Expand-Archive -LiteralPath "$W\archives\wider_face_split.zip" -DestinationPath "$W\extracted\wider_face_split\files"
(Get-ChildItem "$W\extracted\WIDER_train\files\WIDER_train\images" -Recurse -File -Filter *.jpg | Measure-Object).Count
(Get-ChildItem "$W\extracted\WIDER_val\files\WIDER_val\images" -Recurse -File -Filter *.jpg | Measure-Object).Count
(Get-ChildItem "$W\extracted\wider_face_split\files\wider_face_split" -File | Measure-Object).Count
(Get-ChildItem "$W\extracted\WIDER_train\files\WIDER_train\images" -Directory | Measure-Object).Count
```

预期（来自 box 实测，RN-3 回执）：`12880`、`3226`、`7`、`61`。split 的 7 个文件是：`readme.txt`、`wider_face_train_bbx_gt.txt`、`wider_face_val_bbx_gt.txt`、`wider_face_train.mat`、`wider_face_val.mat`、`wider_face_test.mat`、`wider_face_test_filelist.txt`。

- 解压后约 1.72 GiB；解压期间压缩包和解压文件同时存在，约 3.43 GiB，请先确认 D 盘空间足够（`Get-PSDrive D`）。
- `Expand-Archive` 会拒绝把文件写到目标目录之外。但它不是 FG-4 那套完整的安全检查，所以**一定要先通过 §8.3 的哈希校验再解压**【Windows 推断】。
- 计数一致后，【建议】把 `extracted` 设为只读（`attrib +R /S /D "$W\extracted\*"`）。核对完成后是否删除 `archives\` 下的 zip 由你决定（box 上已按你的决定删除）。
- 本节命令【Windows 推断】：box 上验证的是期望值本身（哈希、计数，见 RN-3 回执），PowerShell 命令没有在 Windows 上跑过。

---

# 第二部分（占位）

> **待 FG-8 通过 SN-6 后补充。** 本部分的脚本来自 FG-8，需要 SN-6 审核通过才能写具体命令和预期输出。通用规则（规划 v2 第 183 行）：在 Windows 本机 `D:\project file\AgeMorph3D` 运行；回传到 box 的只有 `summary.json`（汇总数字 + 文件 SHA-256），回传前自己看一眼，确认没有文件名或人名；AgeDB 只在本机处理，box 上不下载 AgeDB；密码只在你手里，不写进任何文件，不发给任何机器人。

## LX-1 AgeDB 官方包下载与校验（D03）

待 FG-8 通过 SN-6 后补充。

## LX-2 AgeDB 重新统计（v3 §4.4）

待 FG-8 通过 SN-6 后补充。

## LX-3 质检、去重、按身份划分并冻结（P01—P04）

待 FG-8 通过 SN-6 后补充。

（LX-4 到 LX-6 不在本次 RN-4 范围内，留待后续。）

---

## 9. 待决问题

| 编号 | 问题 | 建议 |
|---|---|---|
| R4-Q1 | G1 的回传物是 BP-3 的 `U-6_G1执行回执.md`（结果、状态码、哈希），与“只回传 `summary.json`”的说法在文件名上不一致 | 由 Atlas / Sentinel 决定是否统一成 `summary.json`；在决定之前，内容范围按硬性规则第 2 条执行 |
| R4-Q2 | WIDER 在本机放 `D:\datasets\wider_face\`（仓库外，与 box 对应）还是仓库内被忽略的 `data\datasets\wider_face\` | 本手册默认前者；由 A/B 决定 |
| R4-Q3 | BP-3 的 pytest 命令没有 `--basetemp` | 本手册按【建议】加上；是否回写 BP-3 由 Blueprint / Sentinel 决定 |

## 10. 核对记录（Runner，box）

| 项 | 方法 | 结果 | 日志（`/workspace/AgeMorph3D_runner/output/rn4/`） |
|---|---|---|---|
| HEAD、工作区 | `git rev-parse HEAD`、`git status --porcelain` | `10f1918…`，0 项改动 | `verify-env.log` |
| Python / Node / uv / 锁文件哈希 | 版本命令、`sha256sum` | 3.11.16 / v24.22.1 / uv 0.13.8；uv.lock `6433d7ba…39d3`，package-lock `9ef259b8…0451` | `verify-env.log` |
| 锁一致 | `uv sync --locked --extra inference --python 3.11.16 --offline --dry-run` | `Would make no changes` | `verify-env.log` |
| 启动器 check | `local_run.py check` | exit 0，`problems: []` | `local-run-check.log` |
| 研究开关负例 | `local_run.py start --research-allow-unresolved` | exit 2，`unrecognized arguments`，8000/4173 无监听 | `research-flag.log` |
| 诊断（无模型） | `local_run.py diagnose` 带清单 | exit 1，`blocked`（box 无模型，预期） | `diagnose-missing.log` |
| repro-check | `repro_check.py --skip-smoke`（不带 / 带清单） | exit 0 / exit 1（`MANIFEST_UNREADABLE`） | `repro-check*.log/json` |
| 三条单元测试 | pytest（均带 `--basetemp`） | 1 / 3 / 108 passed | `pytest-*.log` |
| g1_check.py | 合成 JSON 与非 GLB 文件 | 退出码 0 / 1 / 2 行为与源码一致 | `g1_check-usage.log` |
| 前端 | `npm ci`、`npm test`、typecheck、build（FE-1） | 28 包 / 340 pass / exit 0 / built | `output/fe1/` |
| 3DDFA README | curl 抓取 raw README | 链接与 151M 自述；无官方校验值 | `/workspace/AgeMorph3D_tasks/RN-4_refs/` |

未在 box 上做的：任何需要模型权重、照片、Edge 或 Windows 的步骤；AgeDB 与 3DDFA `test.data.zip` 的下载（按规定不在 box 上下载）。
