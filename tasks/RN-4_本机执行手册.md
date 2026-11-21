# RN-4 本机执行手册（Windows PowerShell）

- 版本：v2，2026-11-21；起草：Runner（执行运营官）；状态：**第一部分按 Sentinel 审核意见（FAIL：MAJOR 2 / MINOR 8，审的是 425 行版 SHA-256 `667a2a10…037020b`）修订，待复核；第二部分（LX-1—LX-3）新写，待 Sentinel 审核**
- **跟随规则**：G1 的步骤以 `BP-3_G1验收用例单.md` 为准。Blueprint 以后若修改 BP-3 的 G1 步骤，本手册第一部分要跟着改；两者不一致时，以最新通过审核的 BP-3 为准并通知 Runner。
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
2. **回传内容**：**只把 `summary.json` 回传给团队。** 回传前你自己打开看一眼，确认里面没有文件名、人名、路径或照片内容。
   - **LX 任务（第二部分）**：只回传 FG-8 脚本生成的 `output/research/<目录>/summary.json`。它由字段白名单和逐字段取值规则约束（源码 `SUMMARY_WHITELIST` 与 `project_summary()`），没有任何路径或文件名字段，见第二部分“LX 步骤 3”。
   - **G1 用例（第一部分）**：只回传按 BP-3 写的 `U-6_G1执行回执.md`。回执里只写用例结果、HTTP 状态码，以及**不带路径和文件名**的 SHA-256，文件用角色标签称呼（例如“ID01 GLB”“UI-01 Chrome 导出 GLB”“ENV-01 repro 报告”）。它的文件名不是 `summary.json`，是否统一见 §9 R4-Q1。
   - **一律不回传**：`$G1\sha256sums.txt`（BP-3 G1-SUM-01 生成它时会把 `01-identity\P01-front.glb`、`ui-identity-P01-front.png` 这类相对路径一起写进去）；`g1_check.py` 的输出 JSON（`resp`/`glb` 的 `info.file`、`angle` 的 `a`/`b`、`distinct` 的 `sha256` 和 `max_abs_position_diff` 的键里都含路径）；各类日志；照片、截图、GLB；LX 的 `local\` 文件夹。
3. **照片与截图不出本机**：照片、含人脸或面部网格的截图、PNG 效果图、导出的 GLB **一律不出本机**。它们不上传 box、不提交 Git、不发给任何 agent，也不发聊天软件或云盘。需要核对画面时，由 A（宋明耀）或 B（王晋涛）在本机查看后写文字结论。
4. 数据不进 Git：照片放 `data\g1-inputs\`，证据放 `output\g1\`（仓库 `.gitignore` 忽略 `data/` 和 `output/`）；数据集放仓库外（§7、§8）。
5. 不手改模型清单的 SHA-256、大小或 `license_status`，也不用研究开关代替严格服务（BP-3 §0.2）。
6. **BFM 2009 不从 GitHub 下载**：不要从仓库 Release `assets-bfm-2009` 或任何 GitHub 附件下载 `BaselFaceModel.tgz`；只用你本机已获授权的原始副本；不传到 box，不提交 Git（详见 §6.1）。
7. **PowerShell 执行策略**：如果运行 `.ps1` 时提示“因为在此系统上禁止运行脚本”，只用单次绕过：`powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\<脚本>.ps1 <参数>`。它只对这一次进程生效。**不要**用 `Set-ExecutionPolicy Unrestricted`（或任何作用域）永久放开策略。

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
- **换行注意**：仓库没有 `.gitattributes`，Git for Windows 默认（`core.autocrlf=true`）检出时会把换行改成 CRLF，这时文件 SHA-256 会变成 `C8A7951570160460C0E7FFD71DAF199EB995206347B2C78D6115BC067684CD8D`（Runner 按 LF→CRLF 换算得出，【Windows 推断】）。两个值都正常。与换行无关的核对方式：`git hash-object backend\uv.lock` 应输出 `97f63a5cc6862783e71745864361e1ee638ba34a`，等于 `git rev-parse HEAD:backend/uv.lock`。
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
- `package-lock.json` SHA-256：`9EF259B8F8A55CD04CC2D8C79C893950EBA4B9DD7D59C5F26B7D38F461130451`【Linux 实测】；CRLF 检出时为 `A5444474ED1B97B882F9CBF566C0E043D4809A95E5411EFD80FF27D1D476382F`【Windows 推断】；`git hash-object frontend\package-lock.json` 应为 `d3c653c02e76f81d610f4e3307a0f8327cd50e5c`。

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
- `local-run.ps1 check`：输出一段 JSON，`"problems": []`，最后的 `detail` 为 `检查完成。进程可达和模型就绪是两项不同结果；启动器不授予 ready 或年龄能力。`，`exit=0`【Linux 实测：用 3.11.16 解释器调用 `python -B tools/local_run.py check`；注意它检查的服务解释器是 box 上的 `backend/.venv`，当时为 3.11.18，见日志 `"python"` 字段。你本机的 `backend\.venv` 应为 3.11.16】。如果提示脚本被执行策略禁止，按硬性规则第 7 条改用 `powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\local-run.ps1 check`。
- `repro-check.ps1 --skip-smoke`（不传模型清单）：控制台一行 JSON，含 `"conclusion": "preparation_check_only", "exit": 0`；报告里 `problems` 为空，`gaps` 只有 `MODELS_NOT_CONFIGURED`、`UV_VERSION_NOT_IN_LOCK`、`SMOKE_SKIPPED` 三项，`python.version` 为 `3.11.16`，`git.commit` 为 `10f1918…`，`git.dirty` 为 false，`l02_executed` 与 `l02_signed_off` 都是 false【Linux 实测：`--python` 指定 3.11.16 的虚拟环境；不指定时 `repro_check` 用 `backend/.venv`，box 上那是 3.11.18】。这些 gaps 只记录，不算失败。
- 对照：box 上没有模型文件，传入模型清单时 `repro-check` 退出码 1，`problems` 为两条 `MANIFEST_UNREADABLE`；`local_run.py diagnose` 退出码 1，`status` 为 `blocked`【Linux 实测】。**在本机放好模型之后**，这两条应分别变成退出码 0 和 `preconditions_met`（见 §6 的 G1-ENV-01、G1-ENV-02）【Windows 推断】。

## 6. G1 用例执行（按 BP-3，在 `10f1918` 上）

完整的输入要求、逐步命令、期望结果、证据文件名和签收表都以 **`BP-3_G1验收用例单.md` v1.3** 为准，本节只给执行顺序、关键命令和 Runner 能在 box 上核对的部分。共 31 个必选用例和 1 个可选用例（G1-ENV-04）。**必选用例任一“未通过”或“阻塞”，G1 不通过**（BP-3 §0.2【建议】）。

**版本依赖**：G1 钉在 `10f1918`。从 §2 开始到 G1-SUM-01 结束，项目目录一直保持 `git checkout --detach 10f1918`：执行期间不要 `git pull`，不要先合入 FX-2（恢复限制说明和隐私声明的修改）或任何其他分支，也不要切到第二部分用的 LX 分支（LX 用单独的克隆，见第二部分）。每次开新终端可用 `git rev-parse HEAD` 确认仍是 `10f1918…`。是否把 G1 改钉到包含 FX-2 的提交，是待你决定的事项（§9 R4-Q6）；决定改钉后，本手册和 BP-3 都要按新提交重核。

### 6.1 前置条件

1. 已完成 §1—§5。
2. 模型文件已放进 `data\models\`，本地清单已从 `backend\model-manifests\` 重新复制（BP-3 G1-ENV-01 前置条件）。放置方法参考 `docs/model-assets.md` 与 `docs/B0模型验证与复现.md`，**但 BFM 例外**：
   - `docs/model-assets.md`（`10f1918` 第 35—37 行，“BFM 原始包分发位置”）写的是从 GitHub Release `assets-bfm-2009` 下载 `BaselFaceModel.tgz`。BFM 2009 许可 §3.3 禁止再分发，这个 Release 附件是团队尚未关闭的 CRITICAL 问题。
   - **不要从该 Release 或任何 GitHub 附件下载 BFM。** 只用你本机已经获得授权的原始副本（BFM 官方渠道取得的 `BaselFaceModel.tgz`）。
   - **不要把 BFM（`.tgz`、解出的 `.mat` 或由它转换的文件）传到 box，也不要提交到 Git。**
   - 本机原始副本的哈希可以用 `Get-FileHash -Algorithm SHA256` 自己核对并记进回执（只写哈希，不写路径）。
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
- 调用时一律写 `& $PY -B $CHK …`（`-B` 不写字节码缓存）。BP-3 正文里的调用若没有 `-B`，按这里加上，其余参数不变。
- **输出 JSON 不回传**：`resp`/`glb` 的 `info.file`、`angle` 的 `info.a`/`info.b`、`distinct` 的 `info.sha256` 和 `info.max_abs_position_diff` 的键，都含输入文件的路径（源码第 93、127、149、159、162 行）。这些输出只留在本机，回执里只抄结论（`ok`、退出码、角度数值、不带路径的哈希）。
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
& $PY -B $CHK resp "$G1\01-identity\ID01-P00-front.json" --source-age unknown | Out-File -Encoding utf8 "$G1\01-identity\check-resp-P00.json"
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

BP-3 原命令没有 `--basetemp`，也没有 `-B`。【建议】本机加上 `-B`（不写字节码缓存）和 `--basetemp`（把 pytest 临时文件放进被忽略的证据目录，避免散落到系统临时目录）：

```powershell
Push-Location backend
# G1-ENV-03 步骤 1b
.\.venv\Scripts\python.exe -B -m pytest -q "tests/test_local_run.py::test_spawn_rejects_install_commands_and_research_bypass" --basetemp "..\$G1\pytest-tmp\env03" *>&1 |
  Out-File -Encoding utf8 "..\$G1\00-env\pytest-research-bypass.txt"
"exit=$LASTEXITCODE" | Add-Content "..\$G1\00-env\pytest-research-bypass.txt"
# G1-ID-07
.\.venv\Scripts\python.exe -B -m pytest -q `
  "tests/test_detector.py::test_box_and_points_share_letterbox_inverse_without_mirroring" `
  "tests/test_tddfa.py::test_roi_uses_xywh_center_shift_integer_expansion_and_rounded_crop" `
  "tests/test_inputs.py::test_exif_orientation_is_applied_and_removed" --basetemp "..\$G1\pytest-tmp\id07" *>&1 |
  Out-File -Encoding utf8 "..\$G1\01-identity\pytest-geometry-transforms.txt"
"exit=$LASTEXITCODE" | Add-Content "..\$G1\01-identity\pytest-geometry-transforms.txt"
# G1-CAN-03
.\.venv\Scripts\python.exe -B -m pytest -q tests/test_static_api.py tests/test_asset_cache.py tests/test_runtime.py --basetemp "..\$G1\pytest-tmp\can03" *>&1 |
  Out-File -Encoding utf8 "..\$G1\05-cancel\pytest-static.txt"
"exit=$LASTEXITCODE" | Add-Content "..\$G1\05-cancel\pytest-static.txt"
Pop-Location
```

【Linux 实测】（10f1918，Python 3.11.16，`--basetemp` 在 `output/rn4/` 下；box 上运行时没有加 `-B`，`-B` 只影响是否写 `.pyc`，不影响测试结果【推断】）：
- ENV-03 1b：`1 passed`，exit 0。
- ID-07：`3 passed`，exit 0。
- CAN-03：`108 passed`，exit 0（BP-3 只要求“退出码 0、无失败”，没有写数量）。

### 6.6 回执

执行完把 BP-3 §7 结果汇总填好（存为 `$G1\G1-results.md`，留在本机），再按它写 `U-6_G1执行回执.md`。**G1 只回传这一份回执**，内容只限：
- 每个用例的结果（通过 / 未通过 / 阻塞 / 不适用）；
- HTTP 状态码和错误码（如 `422 NO_FACE`）；
- SHA-256 哈希，**不带路径和文件名**，用角色标签标注，例如“ID01 GLB：`<64 位哈希>`”“ENV-01 repro 报告：`<64 位哈希>`”；
- 同意编号（如 `C-P01`），不写姓名。

**一律不回传**：`$G1\sha256sums.txt`（含 `01-identity\P01-front.glb`、`ui-identity-P01-front.png` 这类相对路径，见 BP-3 G1-SUM-01）、`g1_check.py` 输出 JSON（含路径，见 §6.3）、`G1-results.md` 原件、各类日志与 `.txt` 证据、照片、截图、GLB。需要哈希时，从 `sha256sums.txt` 里手抄哈希值、换成角色标签写进回执。

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
- **NME 按全部 68 点计算（含不可见点）**【经 Atlas 转达的用户确认，2026-11-21，BP-6 N-2】。其余口径以 BP-6 为准：2D、原图像素坐标（裁剪图上的预测须用官方 `roi_box` 映射回原图）、归一化距离为真值 68 点外接矩形的 `sqrt(宽×高)`、按偏航角三箱求均值再取平均。
- 不能代替官方 `AFLW2000-3D.zip`（完整评测用的是 RN-3 已下载的官方包）。
- **许可**：`test.data.zip` 本身是 AFLW 裁剪图的再分发，受 TU Graz AFLW 条款约束——**仅限非商业研究，不得复制、发布或分发任何部分**（同组织单一站点内部使用除外）（RD-3）。所以它**不进 Git、不上云、不传 box、不发给任何人**。

## 8. WIDER FACE 放到 D 盘

box 上已经有一份官方 WIDER FACE（RN-3，路径 `/workspace/datasets/wider_face/`）。如果你要在本机也放一份，请自己从官方渠道下载，然后按下面的目录和哈希核对。不要从 box 往外拷贝。

### 8.1 官方来源（与 RN-3 一致）

- 作者主页：http://shuoyang1213.me/WIDERFACE/ 的 Download 栏。
- train：Google Drive https://drive.google.com/file/d/15hGDLhsx8bLgLcIRD5DhYt5iBxnjNF1M/view?usp=sharing
- val：Google Drive https://drive.google.com/file/d/1GUCogbp16PMGa39thoMMeWxp7Rp5oM8Q/view?usp=sharing
- train（约 1.46 GB）和 val（约 363 MB）都大于 100 MB，Google Drive 会提示“无法扫描此文件是否含有病毒”，这和 §7 的 `test.data.zip` 情况相同。点“仍然下载”即可，不要取消；下载后以 §8.3 的哈希校验为准。
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
- `Expand-Archive` 会拒绝把文件写到目标目录之外。但它不是 FG-4 那套完整的安全检查，所以**一定要先通过 §8.3 的哈希校验再解压**。哈希和官方值一致，才是真正的防线【Windows 推断】。
- **风险**：用 `Expand-Archive` 解 1.46 GB、12,880 个文件的 `WIDER_train.zip`，没有在 Windows 上实测过。Windows PowerShell 5.1 自带的版本在大包上可能很慢，或者中途报错。遇到这种情况，先删掉不完整的 `extracted\WIDER_train\` 再换下面任一工具重解，目标目录不变：
  - Windows 10 1803 及以后自带的 `tar.exe`：`New-Item -ItemType Directory -Force "$W\extracted\WIDER_train\files" | Out-Null; tar.exe -xf "$W\archives\WIDER_train.zip" -C "$W\extracted\WIDER_train\files"`；
  - 7-Zip：`& 'C:\Program Files\7-Zip\7z.exe' x "$W\archives\WIDER_train.zip" "-o$W\extracted\WIDER_train\files"`。
  换工具后照样做上面的计数核对。
- **不要**对下载的 WIDER zip 运行 FG-4 或 FG-8（`lx-local.ps1`）的 ZIP 检查。它们的严格布局规则还没有在真实官方包上验证过，结论不可靠；这里以 §8.3 的哈希校验为准。
- 计数一致后，【建议】把 `extracted` 设为只读（`attrib +R /S /D "$W\extracted\*"`）。核对完成后是否删除 `archives\` 下的 zip 由你决定（box 上已按经 Atlas 转达的你的决定删除）。
- 本节命令【Windows 推断】：box 上验证的是期望值本身（哈希、计数，见 RN-3 回执），PowerShell 命令没有在 Windows 上跑过。

---

# 第二部分：AgeDB 本机处理（LX-1—LX-3）

> ## ⚠️ LX 硬性规则（第二部分每一步都适用）
>
> 1. **没有任何密码出现在本手册、命令、文件或聊天里。** AgeDB 的解压密码只在你本人手里。**不要把它发给任何机器人或 agent**（Atlas、Runner、Sentinel、Forge、Blueprint、Metric 都不例外），也不要写进命令行参数、环境变量、脚本、`.txt`、截图或聊天记录。任何人（包括机器人）向你要密码，一律拒绝。
> 2. **AgeDB 只在你自己的 Windows 电脑上处理。** box 上不下载、不存放 AgeDB，也不放它的任何转存。官方包和解压出的图片都不进 Git，不上云，不发给任何人。
> 3. **只把 `summary.json` 回传给团队。** 它只含汇总数字、固定代码和文件 SHA-256。`local\` 文件夹下的所有报告都含文件名和人名，标了 `local_only`，**一律不出本机**。回传前你自己打开 `summary.json` 看一眼，确认里面没有文件名或人名。
> 4. **照片和含人脸的截图不出本机。** 出问题时只报告退出码、`error_code` 和 `summary.json`，不要截图 AgeDB 图片或文件夹。
> 5. **严格 ZIP 布局检查拒收官方包时，停下来汇报，不要自己放宽。** 不改脚本、不换解压方式绕过、不手动改 `summary.json`。是否放宽由你和团队另行决定。
> 6. **这套脚本还没有在 Windows 上实际运行过**（开发者只做了静态检查；Runner 在 box 上用合成数据跑了 Linux 等价命令）。本部分所有 Windows 命令都是【Windows 推断】，实际输出不一致时照实记录。

## LX-0 脚本来源与版本（先核对再用）

| 项 | 值 |
|---|---|
| 分支 | `feat/lx-local-scripts`（Forge，FG-8） |
| **本手册对应的代码版本** | **以 Git 树对象 `3118275dec80bea8b1c43249e3cea7dc60e2ddf7` 为准**（提交说明“文档：严格 ZIP 布局的误拒类别与未经真实归档验证，group_id 哈希口径”，提交时间 2026-11-21 16:10:45 UTC+8 ＝ 09:10:45 UTC+1） |
| 对应的提交号 | Runner 起草期间这条分支被**改写过一次**（内容不变、提交号全部变了）：先是 `b4ac53eb8d68a41d43d707d5fc9c9f7c9a2943a8`，2026-11-21 约 09:12 UTC+1 起是 **`01d439237aa37fe1316aeb6dac71f6e63bda224f`**，两者的树对象相同（都是 `3118275d…`）。推送前提交号可能还会变，所以下面用树对象和文件 blob 核对，不只看提交号 |
| 它的上一提交 | “FG-8 复审 PASS 后 MINOR：内嵌 stored zip 不再误拒，ps1 三路共用 3.11 探测”（改写前 `6ac40e1`，改写后 `a8a75d5`） |
| SN-6 第二轮审到的版本 | 提交说明“文档：FG-8 第二轮返工说明……”，改写前 `f3fbe7a972bd…`，改写后 `5c51a06c8eb6…`，树对象都是 `7d50429ec7992241afca27df2cddf293c3632c47`（按下一条提交的说明，复审 PASS 在它之后）。之后两条 MINOR 提交是否已经过 Sentinel 复核，Runner 无法从仓库判断，见 §9 R4-Q4 |
| FG-4 `42e634b`（`feat/safe-loading`） | **不在** LX 分支里，LX 脚本也不调用它。LX-1 的 ZIP 检查是 `preprocessing/lx_local.py` 里**重新实现**的、与 FG-4 “部分等价”的规则（开发记录 §5）。42e634b 与本手册的命令无关，只作背景 |
| 与 `10f1918` 的差别 | `tools/`、`preprocessing/`、`backend/uv.lock` 里只差 3 个文件：`tools/lx-local.ps1`、`preprocessing/lx_local.py`、`preprocessing/agedb_filenames.py`。`backend/uv.lock` 完全相同（SHA-256 `6433d7ba…39d3`），所以 §3 的装法照用 |
| GitHub 上是否有 | **据 box 上的记录还没有。** Runner 副本最后一次 fetch（2026-11-21 08:25:25 UTC+1）时，`origin/feat/lx-local-scripts` 还是第一轮的 `515dcb0`；FG-8 说明写明第二轮起“未 push”。**这版推到 GitHub 之前，你的电脑拿不到它**，这一步需要你另行批准推送（见 §9 R4-Q5）。Runner 没有推送，也没有做任何 GitHub 操作 |

**本手册引用的文件（树 `3118275d…`；改写前后 blob 相同）**——Windows 上 Git 默认会把换行改成 CRLF（仓库没有 `.gitattributes`），所以同一文件在你电脑上的 SHA-256 可能是“CRLF”那一列。**最稳的核对方式是 Git 对象号（blob），它与换行无关**：

| 文件 | Git blob | SHA-256（LF，box 上） | SHA-256（CRLF，Windows 默认检出时） |
|---|---|---|---|
| `tools/lx-local.ps1` | `3a444a3dc2578bf5045c1f5d197dde2ba6ae66d8` | `7341f84e5be744244fd1cb0fd05e12e9449068c22700f26cfff4cb391b7a596a` | `453103f3cac38389581a508a5bd192d45f8cce69ceb201c4aaad3e48c84fe5f3` |
| `preprocessing/lx_local.py` | `78b30dbe7dab0686955c614ef1bb2239be2f2d16` | `6363fae2a8694b14d62e9d22a86c3eeb7ad76c1f17b90f971d75d3a703c0ab91` | `558bc4964368ce5c0fedd67823eaeff97713e101fceca2ae8c7dd9d5452193c8` |
| `preprocessing/agedb_filenames.py`（FG-2） | `d6f3dbc705f884ba2136f9ad2366a82376c0b854` | `006f179f2747c8da3cb141dc39a0aaa0cc6e25550c69d0d063e4692e87bf75de` | `e9eb0c92c11968943ad8face92719d7d14d2e2207e37c49e8f6dd87f2b1aa3a0` |
| `docs/LX本机脚本包开发记录.md` | `e73773c0f5728a9fa322fc7a9624b20ab34aa01a` | `fd77c7b19eaf4112ada8ecc3d64b52ebe54bd4cff656167a62fab579c4ecd7e2` | — |
| `docs/lx-summary-sample.json`（合成样例） | `2a41b7387882ed13354d43b16a299c691622df09` | `af48ffaa385bc098f231b8f6cdd8c96d1c9e9698fdca03f08e69b32e667c2303` | — |
| `backend/tests/test_lx_local.py` | `68707c43425fa98e1adee88a4d6d1e02215c9c33` | `a7c58cb5afec7d3d9e93c12abcab8f3eb84d272eb8a14760dac087edf8f044c4` | — |

`summary.json` 里的 `producer_sha256` 是**运行时 `lx_local.py` 文件字节**的 SHA-256，所以它会等于上表 LF 或 CRLF 两列之一，这两种都算对。【Linux 实测】box 上合成运行得到的 `producer_sha256` 是 `6363fae2…ab91`（LF 列）。

## LX 步骤 1：预检

### 1a. 单独准备一份 LX 用的克隆（不动 G1 用的 `10f1918`）

前提：这版已推到 GitHub（见上表），推送后由团队告诉你最终的提交号；如果给了提交号，把下面的 `origin/feat/lx-local-scripts` 换成它。

```powershell
Set-Location -LiteralPath 'D:\project file'
git clone https://github.com/xiaominaimoyu/AgeMorph3D.git AgeMorph3D-lx
Set-Location -LiteralPath 'D:\project file\AgeMorph3D-lx'
git fetch origin feat/lx-local-scripts
git checkout --detach origin/feat/lx-local-scripts
git rev-parse HEAD
git rev-parse 'HEAD^{tree}'
git status --porcelain
git rev-parse HEAD:tools/lx-local.ps1 HEAD:preprocessing/lx_local.py HEAD:preprocessing/agedb_filenames.py
git hash-object tools/lx-local.ps1 preprocessing/lx_local.py preprocessing/agedb_filenames.py
```

预期：
- `git rev-parse HEAD` 记下来（应等于团队给你的提交号）；`git rev-parse 'HEAD^{tree}'` **必须**是 `3118275dec80bea8b1c43249e3cea7dc60e2ddf7`，不是就停下、问团队；`git status --porcelain` 无输出。
- 后两条命令各输出 3 行，**都等于**上表 blob 列：`3a444a3d…`、`78b30dbe…`、`d6f3dbc7…`。`git hash-object` 会按 Git 的规则先还原换行再计算，所以 CRLF 检出也应一致。不一致就停下，不要运行。

AgeDB 会放进这个克隆的 `data\datasets\`（脚本要求，见 1c），它被 `.gitignore` 的 `data/` 忽略，不会进 Git。

### 1b. 装环境（与 §3 相同，Python 必须 3.11.16）

```powershell
Set-Location -LiteralPath 'D:\project file\AgeMorph3D-lx'
uv --cache-dir output\uv-cache sync --project backend --locked --extra inference --python 3.11.16
backend\.venv\Scripts\python.exe --version
backend\.venv\Scripts\python.exe -c "import PIL; print(PIL.__version__)"
```

预期：`Python 3.11.16`、`13.0.0`。

为什么要用这个虚拟环境：
- `lx-local.ps1` 按顺序找 Python：`backend\.venv\Scripts\python.exe` → `py -3.11` → PATH 上的 `python`（跳过 WindowsApps 占位程序），每个候选都要先通过 `Test-Python311` 探测（只看主次版本 3.11）。后两者通常**没有装 Pillow 等依赖**，脚本会在导入阶段崩溃（见“风险 1”）。所以一定先装好 `backend\.venv`。
- LX-3 在满足特定条件时会调用 P03 工具，它把环境钉在 Python 3.11.16 + Pillow 13.0.0（RN-1 发现）。【Linux 实测】同一套测试在 3.11.18 下有 1 项因 `FINGERPRINT_ENVIRONMENT_MISMATCH` 失败，换 3.11.16 全部通过。

### 1c. 放置官方包与条款快照（不需要密码）

1. AgeDB 官方包按 U-1 申请流程从官方页面链接（Dropbox）下载。**box 上不下载，也不要让任何机器人代你下载。**
2. 把 zip 原样放到：`D:\project file\AgeMorph3D-lx\data\datasets\AgeDB.zip`。
3. 用浏览器把 AgeDB 官方页面“另存为”`D:\project file\AgeMorph3D-lx\data\datasets\agedb-terms.html`，作为条款快照。脚本只记录它的大小和 SHA-256。
4. 记录官方包的哈希（自己留底；`summary.json` 里也会有）：

```powershell
Set-Location -LiteralPath 'D:\project file\AgeMorph3D-lx'
Get-Item -LiteralPath data\datasets\AgeDB.zip | Select-Object Name, Length, LastWriteTime
(Get-FileHash -Algorithm SHA256 -LiteralPath data\datasets\AgeDB.zip).Hash.ToLower()
```

**路径规则（来自源码，不满足就以固定代码拒绝）**：
- 传给脚本的路径都**相对于项目根**，用**正斜杠** `/`，不能是 `D:\...` 这样的绝对路径，不能含 `\`、`..`、`:` 等字符，也不能经过符号链接或目录联接。【Linux 实测】传 `data\datasets\AgeDB.zip` → `INVALID_PATH`，exit 2。
- `--images-dir` 必须正好是 `data/datasets/<以 agedb 开头的名字>`，例如 `data/datasets/agedb`；更深一层或放到 `D:\datasets\` 都会被拒。【Linux 实测】传 `D:/datasets/agedb` → `IMAGES_DIR_SCOPE`，exit 2。
- `--output-dir` 必须以 `output/research/` 开头。【Linux 实测】传 `output/other` → `OUTPUT_MUST_BE_RESEARCH_DIRECTORY`，exit 2，且什么文件都不写。
- 项目根不能经过 `subst` 映射盘或联接，否则 `INVALID_ROOT`【Windows 推断】。

### 1d. 脚本自检

```powershell
Set-Location -LiteralPath 'D:\project file\AgeMorph3D-lx'
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\lx-local.ps1 --help
"exit=$LASTEXITCODE"
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\lx-local.ps1 --output-dir output/research/lx-agedb-v1
"exit=$LASTEXITCODE"
```

（`-ExecutionPolicy Bypass` 只对这一次进程生效，不改系统设置；如果你的电脑能直接运行本地 `.ps1`，可以去掉。）

预期：
- `--help`：打印 `usage: lx_local.py [-h] [--root ROOT] [--archive ARCHIVE] [--images-dir IMAGES_DIR] [--terms-snapshot TERMS_SNAPSHOT] --output-dir OUTPUT_DIR [--stages STAGES] [--split-seed SPLIT_SEED] [--local-only-ack] [--suppress-small-cells]`，`exit=0`【Linux 实测，直接调用 Python】。
- 不带 `--local-only-ack`：stderr 为“拒绝执行：未传入 --local-only-ack。……本工具不接收、不保存解压密码。”，stdout 一行 `{"status": "rejected", "error_code": "LOCAL_ONLY_ACK_REQUIRED", ...}`，`exit=2`，不写任何文件【Linux 实测】。
- 若打印 `{"status": "rejected", "error_code": "LAUNCHER_PYTHON_311_REQUIRED"}`：没找到 3.11，回到 1b【Windows 推断，来自 ps1 源码】。

**参数一览（来自 `lx_local.py` 的 `main()`）**：

| 参数 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `--local-only-ack` | 是 | — | 不传就拒绝运行（exit 2，不写文件）。传入表示你确认含文件名的输出只留在本机 |
| `--output-dir` | 是 | — | `output/research/...`，例如 `output/research/lx-agedb-v1` |
| `--archive` | 否 | 无 | 官方 zip 的相对路径。**建议总是传**：脚本会用它的中央目录核对解压结果（文件名、大小、CRC32），`identity_group_origin` 才可能记为 `official` |
| `--images-dir` | 实际必填 | 无 | 解压目录，`data/datasets/agedb`。不传报 `IMAGES_DIR_REQUIRED` |
| `--terms-snapshot` | 否 | 无 | 条款快照相对路径，只记大小和 SHA-256 |
| `--stages` | 否 | `lx1,lx2,lx3` | 逗号分隔的子集，例如 `lx1` |
| `--split-seed` | 否 | `agemorph3d-lx3-identity-split-v1` | 临时划分规则的种子，不要改 |
| `--suppress-small-cells` | 否 | 关 | 保留开关。**不要传**：规则未定，传了会以 `SMALL_CELL_SUPPRESSION_POLICY_UNSETTLED` 拒绝【Linux 实测】 |
| `--root` | 否 | `.` | ps1 已切到项目根，不用传 |

脚本**没有任何密码参数，也没有交互式密码提示**。传入不认识的参数（例如任何形如 `--password` 的东西）会以 `ARGUMENT_REJECTED` 拒绝，而且**不回显参数值**【Linux 实测】。

### 1e. 严格 ZIP 布局预检（解压之前）

开发记录明确：严格布局“**从未在真实归档上跑过**，官方 AgeDB 包是否符合未经验证；用户应先在本机只跑 LX-1 预检（`--stages lx1`），被拒时报告错误码”。在**还没有** `data\datasets\agedb\` 文件夹时运行：

```powershell
Set-Location -LiteralPath 'D:\project file\AgeMorph3D-lx'
New-Item -ItemType Directory -Force output\lx-logs | Out-Null
$env:PYTHONIOENCODING = 'utf-8'
$p = Start-Process -FilePath powershell.exe -NoNewWindow -Wait -PassThru `
  -RedirectStandardOutput output\lx-logs\preflight-stdout.txt -RedirectStandardError output\lx-logs\preflight-stderr.txt `
  -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','.\tools\lx-local.ps1','--local-only-ack',
    '--archive','data/datasets/AgeDB.zip','--images-dir','data/datasets/agedb',
    '--terms-snapshot','data/datasets/agedb-terms.html','--output-dir','output/research/lx-preflight','--stages','lx1'
"exit=$($p.ExitCode)"
Get-Content output\lx-logs\preflight-stdout.txt
```

为什么用 `Start-Process` 重定向到文件：脚本会往 stderr 写提示。在 Windows PowerShell 5.1 里，如果在同一会话里用 `2>` / `2>&1` 重定向，原生程序的 stderr 会变成错误记录，而 `lx-local.ps1` 设置了 `$ErrorActionPreference = 'Stop'`，可能把正常运行误报成 `LAUNCHER_START_FAILED`（ps1 自己的注释也提到了这个 5.1 行为）。`Start-Process` 在进程层面重定向，避开这个问题【Windows 推断】。日志放在 `output\lx-logs\`（被 Git 忽略），**不外传**。

结果判读：

| 结果 | 含义 | 下一步 |
|---|---|---|
| exit 2，`"error_code": "SYSTEM_EXTRACTOR_REQUIRED"` | **预期结果（加密的官方包）**：脚本已读完中央目录并通过严格布局检查，发现包有密码，所以不替你解压 | 去 LX 步骤 2 |
| exit 0，`"status": "passed"` | 包没加密，脚本已按安全规则解压到 `data\datasets\agedb\` 并设为只读 | 去 LX 步骤 2（跳过手动解压） |
| exit 2，`error_code` 是 `ARCHIVE_NOT_ZIP`、`ZIP_` 开头的任一代码（如 `ZIP_END_INVALID`、`ZIP_END_AMBIGUOUS`、`ZIP_ENTRY_GAP`、`ZIP_ENTRY_OVERLAP`、`ZIP_DIRECTORY_NOT_ADJACENT`、`ZIP_PREFIX_UNSUPPORTED`、`ZIP_LAYOUT_UNSUPPORTED`、`ZIP_LOCAL_HEADER_MISMATCH`、`ZIP_DIRECTORY_LIMIT`），或 `ARCHIVE_CORRUPT_OR_NOT_ZIP`、`ARCHIVE_TRUNCATED`、`FILE_SIZE_EXCEEDED` | **严格 ZIP 布局（或大小上限）拒收了这个包** | **停下来，不要继续，不要放宽，不要换工具绕过。** 只把退出码、`error_code` 和 `output/research/lx-preflight/summary.json` 报给团队 |
| 其他 exit 2 代码（`INVALID_PATH`、`IMAGES_DIR_SCOPE`、`OUTPUT_MUST_BE_RESEARCH_DIRECTORY` 等） | 路径写法不对 | 按 1c 的路径规则改，再跑 |

【Linux 实测，合成包】加密标记的 zip、目标文件夹不存在 → `SYSTEM_EXTRACTOR_REQUIRED`，exit 2；前面多出 64 字节 → `ARCHIVE_NOT_ZIP`；末尾多出 8 字节 → `ZIP_END_INVALID`；三者都写了拒收的 `summary.json`。

## LX 步骤 2：运行

### 2a. 用系统工具自己解压（仅加密包需要；密码只在 7-Zip 的窗口里输入）

脚本**从不接收、不保存密码**（源码文档：“encrypted official zips must be extracted with a system tool (Explorer / 7-Zip) by the user”）。所以：

1. 在资源管理器里右键 `data\datasets\AgeDB.zip` → 7-Zip → “提取文件…”，目标填 `D:\project file\AgeMorph3D-lx\data\datasets\agedb\`。
2. 7-Zip 弹出密码框时，**只在这个弹窗里**亲手输入密码。不要复制到别处，不要截图，不要写进任何文件或聊天。（Windows 自带解压只支持传统 ZipCrypto；包若用 AES 加密，需要 7-Zip。）
3. 解压后不要往 `data\datasets\agedb\` 里放任何别的文件，也不要改名、删除。脚本会逐个核对文件，多一个或少一个都会拒绝。【Linux 实测】多一个 `Thumbs.db` → `EXTRACTED_ARCHIVE_COUNT_MISMATCH`，exit 2。zip 里如果所有文件都在同一个顶层文件夹下（例如 `AgeDB/…`），解压后多出这一层也可以，脚本会自动去掉这一层公共前缀再比对。

### 2b. 完整运行 LX-1 → LX-2 → LX-3

```powershell
Set-Location -LiteralPath 'D:\project file\AgeMorph3D-lx'
$env:PYTHONIOENCODING = 'utf-8'
$p = Start-Process -FilePath powershell.exe -NoNewWindow -Wait -PassThru `
  -RedirectStandardOutput output\lx-logs\run-stdout.txt -RedirectStandardError output\lx-logs\run-stderr.txt `
  -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','.\tools\lx-local.ps1','--local-only-ack',
    '--archive','data/datasets/AgeDB.zip','--images-dir','data/datasets/agedb',
    '--terms-snapshot','data/datasets/agedb-terms.html','--output-dir','output/research/lx-agedb-v1'
"exit=$($p.ExitCode)"
Get-Content output\lx-logs\run-stdout.txt
```

做了什么（开发记录 §2）：
- **LX-1**：记录官方包的大小、SHA-256、修改时间；记录条款快照的大小和 SHA-256；用中央目录核对解压目录（文件名、大小、CRC32），通过后把目录设为只读。
- **LX-2**：调用 FG-2 的 `agedb_filenames.export()`，按官方文件名 `<id>_<name>_<age>_<gender>.jpg` 重新统计。
- **LX-3**：给出按身份的 train/validation/test **临时建议账本**（70/15/15 无出处、未按年龄分层，待你决定），并统计精确 SHA-256 重复。**不冻结、不做 P01 质检和官方规模近重复**，`summary.json` 里有固定字段如实标注。

**退出码（`lx-local.ps1` 与 `lx_local.py` 源码）**：

| 退出码 | stdout 最后一行 | 含义 |
|---|---|---|
| 0 | `{"status": "passed", "output_dir": "output/research/lx-agedb-v1", "stages_completed": ["lx1", "lx2", "lx3"], ...}` | 通过 |
| 1 | `{"status": "needs_review", "output_dir": ..., "stages_completed": [...], ...}` | 需要复核：LX-2 有被拒文件（例如文件名不符合官方格式）。**也可能是 Python 崩溃，见风险 1** |
| 2 | `{"status": "rejected", "error_code": "<固定代码>", ...}` | 拒绝。stdout 不含文件名、路径或 traceback |
| 2 | `{"status": "rejected", "error_code": "LAUNCHER_PYTHON_311_REQUIRED"}` 或 `LAUNCHER_START_FAILED` | ps1 找不到 3.11，或 Python 没能启动/返回了 0、1、2 以外的码 |

【Linux 实测，合成数据，直接调用 Python】
- 6 张合法文件名 → exit 0，`passed`，`extraction_method: safe_unencrypted_zip`，`extracted_readonly: true`，`extracted_archive_consistent: true`。
- 同一命令再跑一次 → exit 0，`extraction_method: already_extracted`，`lx2_resumed: true`；旧 `summary.json` 被移到 `local/summary.stale.json`。
- 加密标记包 + 预先放好的解压目录 → exit 0，`already_extracted`，`extracted_archive_consistent: true`。
- 多 1 个非官方格式文件名 → exit 1，`needs_review`，`lx2_status: needs_review`，`rejected: 1`，`rejected_by_reason: {"ID_INVALID": 1}`。

**断点续跑**：中途中断或改了输入后，用同一条命令重跑即可。LX-1 每次都重算归档哈希并重新核对；LX-2 只在输入清单哈希和四个产物哈希都对得上时才复用；LX-3 每次都重算（开发记录 §4）。`state.json` 损坏时报 `STATE_CORRUPT`，原文件不动；这时换一个新的 `--output-dir`（例如 `output/research/lx-agedb-v2`）重跑，不要手改 `state.json`。

## LX 步骤 3：生成并回传 `summary.json`

`summary.json` 在每次运行结束时由脚本自动写出，不需要另外的命令：

| 位置 | 内容 | 能否外传 |
|---|---|---|
| `output\research\lx-agedb-v1\summary.json` | 汇总数字、固定代码、文件 SHA-256（字段白名单约 89 个键，样例见 `docs/lx-summary-sample.json`） | **能，且只有它能** |
| `output\research\lx-agedb-v1\local\`（`lx1-report.json`、`agedb-stats\stats.json`/`manifest.json`/`audit.json`/`rejected.json`、`assignment-ledger.json`、`exact-duplicates.json`、`lx3-tools.json`、`state.json`、`summary.stale.json` 等） | 含文件名、人名、身份分组 | **不能，只留本机** |
| `output\lx-logs\*.txt` | 本手册建议的运行日志 | **不能，只留本机** |
| `output\research\lx-preflight\` | 预检的拒收或通过 summary | 预检被拒时，只回传其中的 `summary.json` |

**`summary.json` 本身不含路径和文件名（按源码核对）**：
- 写出前一律经过 `project_summary()`：只保留 `SUMMARY_WHITELIST` 里的键（多一个键报 `SUMMARY_EXTRA_FIELDS`），并且**每个键都有取值规则**：SHA-256 必须是 64 位小写十六进制，时间必须是 ISO 格式，错误码必须是大写代码，计数必须是非负整数，计数表的键只能是年龄段、性别、固定代码等受限格式；不认识的键直接报 `SUMMARY_FIELD_TYPE`。白名单里**没有**路径、目录或文件名字段（唯一带 `file` 字样的是计数 `extracted_file_count`）。
- 屏幕上最后一行状态 JSON 里有 `output_dir`（例如 `output/research/lx-agedb-v1`），但它**不写进** `summary.json`。
- 【Linux 实测】box 上 11 份合成 `summary.json`（含拒收、needs_review 和通过三类）里都找不到夹具的虚构人名、`.jpg` 文件名或路径。
- 所以 LX 和 G1 的规则一致：回传物里只有结果、代码、计数和不带路径的哈希；带路径或文件名的东西一律留在本机。

注意：`group_id` 是对姓名做两次**未加盐**哈希得到的，按公开名单可以反查，**不是匿名化**（开发记录 §5）；它只在 `local\` 里，不进 `summary.json`。

回传前自查：

```powershell
Set-Location -LiteralPath 'D:\project file\AgeMorph3D-lx'
$S = 'output\research\lx-agedb-v1\summary.json'
$j = Get-Content -Raw -Encoding UTF8 $S | ConvertFrom-Json
$j.status; $j.error_code; $j.contains_file_names_or_person_names; $j.password_accepted_or_stored; $j.producer_sha256; $j.python_runtime
(Get-FileHash -Algorithm SHA256 -LiteralPath $S).Hash.ToLower()
Select-String -LiteralPath $S -Pattern '\.jpg|\.png|_m\b|_f\b' | Measure-Object | Select-Object -ExpandProperty Count
```

预期：
- `status` 为 `passed` 或 `needs_review`（被拒时为 `rejected`，并有 `error_code`）。
- `contains_file_names_or_person_names` 和 `password_accepted_or_stored` 都是 `False`。
- `producer_sha256` 等于 LX-0 表里 `lx_local.py` 的 LF 或 CRLF 值；`python_runtime` 为 `3.11.16`。
- 最后一行计数为 `0`。不是 0 就**不要回传**，先报告团队。
- 再用记事本打开通读一遍，确认没有任何人名或文件名。【Linux 实测】box 上所有合成场景的 `summary.json` 都不含夹具里的虚构人名和文件名。

然后**只把这一个 `summary.json` 文件**（和你算出的它的 SHA-256）交给团队。不要附带 `local\`、日志、截图或图片。

## 已知风险（必须读）

### 风险 1：exit 1 可能是 needs_review，也可能是 Python 崩溃

`lx-local.ps1` 把 Python 的 0/1/2 原样传出。Python 在 CLI 的异常处理**之外**崩溃（典型是导入失败：用了没装依赖的 Python、文件缺失或损坏），Python 自己也以 1 退出，ps1 无法区分（开发记录 §1 原文：“Python 进程若在 CLI 之外崩溃并以 1 退出，ps1 无法和 needs_review 区分”）。CLI 内部的普通异常会被转成固定代码、以 exit 2 拒绝，不会是 1。按下面三处区分：

| 看哪里 | needs_review | Python 崩溃 |
|---|---|---|
| `run-stdout.txt` 最后一行 | `{"status": "needs_review", "output_dir": "output/research/lx-agedb-v1", "stages_completed": [...], ...}` | **没有**这样的 JSON 行（通常为空） |
| `run-stderr.txt` | 只有提示横幅：`==========`、`含文件名的输出仅限用户本机`、`==========` | 含 `Traceback (most recent call last):`，最后一行是异常名，如 `ModuleNotFoundError: No module named 'PIL'` 或 `ImportError: ...` |
| `summary.json` | 本次新写的：`"status": "needs_review"`、`"lx2_status": "needs_review"`，`recorded_at_utc` 是本次运行时间（UTC），`rejected` > 0 | 没有新写：文件不存在，或 `recorded_at_utc` 是旧时间；中途崩溃时旧文件可能已被移到 `local\summary.stale.json` |

```powershell
Select-String -LiteralPath output\lx-logs\run-stderr.txt -Pattern 'Traceback \(most recent call last\)' -Quiet
Get-Content output\lx-logs\run-stdout.txt | Select-Object -Last 1
(Get-Content -Raw -Encoding UTF8 output\research\lx-agedb-v1\summary.json | ConvertFrom-Json) | Select-Object status, lx2_status, rejected, recorded_at_utc
```

- 第一条输出 `True` → 崩溃。**traceback 里可能出现本机路径，不要外传**；只告诉团队“exit 1 + Traceback，最后一行异常类型是 X”（只报异常类型名，不贴全文），通常是没用 `backend\.venv`（回到 1b）。
- 第一条 `False`、最后一行是 `needs_review` JSON、summary 的 `recorded_at_utc` 是刚才 → needs_review。被拒原因按代码汇总在 `summary.json` 的 `rejected_by_reason` 里，可以回传；逐文件明细在 `local\agedb-stats\rejected.json`，**只在本机看**。

【Linux 实测】
- needs_review：exit 1，stdout 为 `{"status": "needs_review", ...}`，stderr 只有横幅，summary `lx2_status: needs_review`、`rejected_by_reason: {"ID_INVALID": 1}`。
- 模拟崩溃（删掉一个依赖模块）：exit 1，stdout 为空，stderr 以 `Traceback (most recent call last):` 开头、以 `ImportError: cannot import name 'split_freeze' from 'preprocessing' (...)` 结尾，没有写出 `summary.json`。
- Runner 第一次在 box 上导出脚本时少拷了 `tools/` 目录，14 个场景全部以 `ModuleNotFoundError: No module named 'tools'` + exit 1 结束（日志 `lx-cli-scenarios-f3fbe7a-incomplete-tree.log`）。这正是“exit 1 不一定是 needs_review”的真实例子。

### 风险 2：严格 ZIP 布局可能拒收官方包

- 规则（开发记录 §5）：第一个本地头必须在偏移 0，条目之间无空隙，中央目录紧跟最后一个条目，结束记录紧跟中央目录并结束文件；不支持 ZIP64、多卷、前置数据（自解压包）、尾随数据。开发者写明的“偏向拒绝”代价：带空隙或前置数据的少见合法 zip、末尾补零的包、强制 ZIP64 的包、注释里含结束签名的包都会被拒。
- 这些规则**只在合成包上测过，从未在真实归档上跑过**。官方 AgeDB 包是否符合，未经验证。
- **被拒就停下来汇报**：只报退出码、`error_code` 和预检的 `summary.json`。**不要自己放宽**：不改脚本，不加参数绕过，不重新打包后再喂给脚本，不手改 `summary.json`（改过的 summary 会因白名单校验报 `SUMMARY_DISCLOSURE_ALTERED` 等代码）。是否放宽、怎样放宽由你和团队另行决定，并由 Forge 改代码、Sentinel 审核。

### 风险 3：脚本还没有在 Windows 上运行过

- `lx-local.ps1` 源码第 12 行：`NOTE: never run on Windows by the developer; only statically tested.`
- Runner 在 box 上能验证的只有 Linux 等价命令（直接 `python -B -m preprocessing.lx_local`）和 Python 测试；box 上没有 PowerShell，ps1 本身没有运行过。
- 以下是 Windows 特有、未经验证的点：ps1 的 Python 探测与退出码传递；PowerShell 5.1 的 stderr 行为；`os.chmod` 在 Windows 上的只读效果（`extracted_readonly`）；目录联接检测；CRLF 检出后的文件哈希；中文用户名或含空格路径下的行为。任何一项和本手册不一致，都照实记录，不要改写成“通过”。

## 第二部分范围外

LX-4 到 LX-6 依赖尚未合并的 FG-6/FG-7，不在本次 RN-4 范围内，留待后续。

---

## 9. 待决问题

| 编号 | 问题 | 建议 |
|---|---|---|
| R4-Q1 | G1 的回传物是 BP-3 的 `U-6_G1执行回执.md`，与“只回传 `summary.json`”在文件名上不一致 | 按 Sentinel 审核意见，本版已写明：G1 只回传 U-6 回执，内容只限结果、状态码和不带路径的哈希（硬性规则第 2 条、§6.6）。是否改名为 `summary.json` 由 Atlas 决定 |
| R4-Q2 | WIDER 在本机放 `D:\datasets\wider_face\`（仓库外，与 box 对应）还是仓库内被忽略的 `data\datasets\wider_face\` | 本手册默认前者；由 A/B 决定（Sentinel 意见已转 Atlas） |
| R4-Q3 | BP-3 的 pytest 命令没有 `--basetemp` 和 `-B` | 本手册按【建议】加上；是否回写 BP-3 由 Blueprint / Sentinel 决定 |
| R4-Q4 | 第二部分对应树 `3118275d…`（提交 `b4ac53e`，分支改写后为 `01d4392`）；SN-6 第二轮审到的是树 `7d50429e…`（`f3fbe7a` / 改写后 `5c51a06`）。之后两条 MINOR 提交（ps1 探测、内嵌 stored zip 误拒、文档）是否已复核，Runner 无法从仓库判断；分支为什么整体改写（含 FG-2 提交）也不清楚 | 请 Atlas / Sentinel 确认；若要求按第二轮审到的版本，LX-0 的树号和哈希表要换（Runner 已在 box 上对 `f3fbe7a` 跑过同样检查，日志见 §10） |
| R4-Q5 | LX 分支这一版还没推到 GitHub，用户电脑拿不到；推送前提交号还可能变 | 推送需要用户逐次批准（FG-8 说明 §6）；Runner 没有推送 |
| R4-Q6 | G1 是否改钉到包含 FX-2（恢复限制说明和隐私声明）的提交 | 待用户决定；在决定前保持 `10f1918`（§6 版本依赖） |

## 10. 核对记录（Runner，box）

| 项 | 方法 | 结果 | 日志（`/workspace/AgeMorph3D_runner/output/rn4/`） |
|---|---|---|---|
| HEAD、工作区 | `git rev-parse HEAD`、`git status --porcelain` | `10f1918…`，0 项改动 | `verify-env.log` |
| Python / Node / uv / 锁文件哈希 | 版本命令、`sha256sum` | 3.11.16 / v24.22.1 / uv 0.13.8；uv.lock `6433d7ba…39d3`，package-lock `9ef259b8…0451` | `verify-env.log` |
| 锁一致 | `uv sync --locked --extra inference --python 3.11.16 --offline --dry-run` | `Would make no changes` | `verify-env.log` |
| 启动器 check | 用 `.venv-py31116`（3.11.16）调用 `local_run.py check` | exit 0，`problems: []`；**它检查的服务解释器是 `backend/.venv`，当时为 3.11.18**（日志 `"python"` 字段） | `local-run-check.log` |
| 研究开关负例 | `local_run.py start --research-allow-unresolved` | exit 2，`unrecognized arguments`，8000/4173 无监听 | `research-flag.log` |
| 诊断（无模型） | `local_run.py diagnose` 带清单 | exit 1，`blocked`（box 无模型，预期） | `diagnose-missing.log` |
| repro-check | `repro_check.py --skip-smoke`：不带清单时 `--python` 指定 3.11.16；带清单那次没指定，用的是 `backend/.venv` 的 **3.11.18** | 不带清单：exit 0，`python.version` 3.11.16（`repro-check-nomanifest.json`）；带清单：exit 1（`MANIFEST_UNREADABLE`），`python.version` 3.11.18（`repro-check-skip-smoke.json`） | `repro-check*.log/json` |
| 三条单元测试 | pytest（均带 `--basetemp`） | 1 / 3 / 108 passed | `pytest-*.log` |
| g1_check.py | 合成 JSON 与非 GLB 文件 | 退出码 0 / 1 / 2 行为与源码一致 | `g1_check-usage.log` |
| 前端 | `npm ci`、`npm test`、typecheck、build（FE-1） | 28 包 / 340 pass / exit 0 / built | `output/fe1/` |
| 3DDFA README | curl 抓取 raw README | 链接与 151M 自述；无官方校验值 | `/workspace/AgeMorph3D_tasks/RN-4_refs/` |
| 换行与哈希 | `git show HEAD:<文件>` 按 LF 与 LF→CRLF 分别计算 SHA-256，记录 blob | 见 §3、§4 与 LX-0 表 | `fg8-source-pins.log` |
| LX 脚本来源 | 在 `/workspace/AgeMorph3D_fg8` 只读执行 `git rev-parse` / `git show` / `git archive`（不检出、不写入） | 分支 `feat/lx-local-scripts` 起草时 = `b4ac53e…`，09:12 UTC+1 前后改写为 `01d4392…`，树对象相同（`3118275d…`）；42e634b 不在该分支；Runner 副本的 `origin/feat/lx-local-scripts` 为 `515dcb0` | `fg8-source-pins.log`（`b4ac53e`）、`fg8-source-pins-f3fbe7a.log` |
| LX 单元测试 | `git archive b4ac53e` 导出后，3.11.16 跑 `tests/test_lx_local.py`，带 `--basetemp` | 68 passed，exit 0；`f3fbe7a`：3.11.16 下 63 passed，3.11.18 下 1 项 `FINGERPRINT_ENVIRONMENT_MISMATCH` 失败 | `pytest-lx-local.log`、`pytest-lx-local-f3fbe7a*.log` |
| LX CLI 场景 | 合成虚构人名小图，直接 `python -B -m preprocessing.lx_local`，共 18 个场景 | 0 / 1（needs_review）/ 2 各码与手册一致；模拟崩溃 exit 1 带 Traceback、无 summary；summary 无人名、无文件名 | `lx-cli-scenarios.log`、脚本 `lx_cli_scenarios.py` |
| PowerShell | box 上没有 `pwsh` / `powershell` | `lx-local.ps1`、`Start-Process` 写法都未运行 | — |

未在 box 上做的：任何需要模型权重、照片、Edge 或 Windows 的步骤；任何 `.ps1` 的实际运行；AgeDB 与 3DDFA `test.data.zip` 的下载（按规定不在 box 上下载）。没有改动任何仓库或工作区，没有推送，没有 GitHub 操作。
