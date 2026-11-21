# BP-3 G1 严格静态验收用例单（用户本机执行）

- 版本：v1.4（2026-11-21，UTC+8）；起草：Blueprint（需求架构师）；审核：Sentinel（SN-2）；状态：**v1.1 复审 PASS；v1.2 按用户答复与提交 `10f1918`（单屏工作台）修订；v1.3 按用户第二轮答复关闭 Q-3（在 `10f1918` 上执行）；v1.4 按 Sentinel MINOR 修订（切换规则标【建议】、新增 Q-9），未执行**
- 依据：仓库固定提交 `35c0cd6`（后端、启动器、接口文档、研究脚本等；这些文件在 `10f1918` 中未变，`BP-3_verify.py` 对两版都核对）；**浏览器工作台用例按 `10f1918` 编写**（`frontend/index.html`、`frontend/src/main.ts`、`frontend/tests/studio.spec.ts`，引用标 `@10f1918`；与 `35c0cd6` 的差异见 §5.3.0）。`10f1918` 只读取自独立克隆 `/workspace/bp_ref/AgeMorph3D`（GitHub `xiaominaimoyu/AgeMorph3D`，提交时间 2026-11-20 18:25 UTC+8）；BP-1 `/workspace/AgeMorph3D_tasks/BP-1_里程碑重排与验收标准.md` 的 S0-4、S0-5、S0-11
- 执行窗口：2026-11-16 → 2026-12-06（UTC+8）。G1 出口判定日 12-06 **已确认（用户 2026-11-21）**。**G1 在 `10f1918` 上执行**【用户已确认 2026-11-21，经 Atlas 转达】（§8 Q-3 已关闭）；文中 `35c0cd6` 的引用只作“两版逐字节相同”的对照依据
- 人员：A＝宋明耀（算法），B＝王晋涛（系统）（用户 2026-11-21 确认，Atlas 转述）。下文“A”“B”均按此对应
- 执行地点：用户本机 Windows，项目根目录按仓库文档示例写作 `D:\project file\AgeMorph3D`，实际路径不同就替换
- 边界：本文只写文档，不改仓库、不推送、不碰 GitHub。本文**不预填任何“通过”**。附带的 `BP-3_g1_check.py` 是只读辅助脚本，不属于仓库，运行时放在被 Git 忽略的 `output/g1/tools/` 下

## 修订记录

| 版本 | 日期（UTC+8） | 内容 |
|---|---|---|
| v1 | 2026-11-16 | 首版，送 Sentinel SN-2 审核。结论 FAIL（CRITICAL 0 / MAJOR 1 / MINOR 2） |
| v1.1 | 2026-11-16 | **MAJOR**：G1-ENV-03 第 1 步改写。`tools/local_run.py` 的命令行解析器没有 `--research-allow-unresolved` 参数，按原命令执行会由 argparse 报 `unrecognized arguments` 并以退出码 2 结束，根本走不到内部防护 `assert_spawn_allowed`（防护码 6）。期望结果改为：拒绝启动、8000/4173 没有监听、退出码 2、stderr 含 `unrecognized arguments`。`RESEARCH_BYPASS_FORBIDDEN` 改由已有单元测试 `test_spawn_rejects_install_commands_and_research_bypass` 佐证，新增运行命令和证据文件。以上均已在 35c0cd6 上用 `git show` 核对，并在 box 的 35c0cd6 只读克隆里实测：退出码 2，单元测试通过。**MINOR-1**：新增必选用例 G1-ID-07，用 35c0cd6 已有的单元测试佐证 R09“框/点/ROI 到原图的变换”中外部不可观察的部分；§9 写明“框/点/ROI 变换”和“不同点来源可追溯”不在静态接口的外部可观察范围内，以及各自怎样取证。**MINOR-2**：§0.3 补充“含人脸的截图同样不出本机、不交给任何 agent”。§6、§7 随之更新（必选用例 30 → 31） |
| v1.2 | 2026-11-21 | ① **工作台按 `10f1918` 重核**（单屏布局，标记移入 `frontend/index.html`，删除 `layout.ts`）：新增 §5.3.0 新旧界面对照；改写 G1-UI-01/02/03 的控件名、读数位置与期望（静态状态文案去掉“可以旋转查看与导出”后缀；模型名改为 `#info-source` 只显示 mesh_id；顶点/三角形读数改由 `#viewer` 的 `data-vertices`/`data-triangles` 读取；“源年龄”读数并入年龄条 `#age-output`；“¾ 侧面”改“斜侧”；“恢复源年龄/恢复至 30 岁”改“重置”；“年龄对比”改“对比”；“标准人脸模型”卡片改为“载入演示模型”按钮；导出、连接、载入演示均不再弹成功提示）；G1-NF-01、G1-MF-01、G1-BAD-02/03/04/06、G1-CAN-01、G1-EXPIRE-02、G1-ID-02 的工作台步骤同步（取消按钮“取消当前任务”→“取消”，忙碌文案→“正在重建…”，取消提示→“重建已取消”且无 toast；错误同时写在状态行和 9 秒后自动关闭的错误 toast）；§0.3 的 `#source-image` 改引 `index.html`。② 用例数、条款与覆盖不变（32 个，31 个必选）。③ A/B 对应到人；G1 判定日改为已确认。④ `BP-3_verify.py` 改为在独立克隆中核对：普通引用须同时与 `35c0cd6`、`10f1918` 一致，`@提交` 引用只核对该提交。⑤ Q-3 仍待用户决定，补充两种执行提交下的差异说明。修订前备份：`/workspace/bp_work_1121/BP-3_G1验收用例单.md` |
| v1.3 | 2026-11-21 | 按用户第二轮答复（Atlas 转述）：**Q-3 关闭，G1 在 `10f1918` 上执行**【用户已确认 2026-11-21，经 Atlas 转达】。改动：页首版本/状态/执行窗口行；§3.1 环境记录“与 35c0cd6 的差异”改为“是否为 10f1918”；§5.3.0 表头注明右列仅作对照；§8 Q-3 改为已关闭并写明 HEAD 不符时的处理。命令行条目保留双提交引用。`BP-3_verify.py` 增加 Q-3 关闭检查。修订前备份 `/workspace/bp_work_1121b/BP-3_G1验收用例单.md` |
| v1.4 | 2026-11-21 | 按 Sentinel 11-21 复审 MINOR：① 确认标记改为 【用户已确认 2026-11-21，经 Atlas 转达】，§0.1 补定义；② §3.1“是否为 10f1918”行与 §8 Q-3 的切换规则标【建议】，补“切换前 `git status --porcelain` 须为空、agent 执行须先按 RULES.md:14 确认文件清单”；③ 新增 §8 Q-9：FX-2 合入后 G1 是否仍钉 `10f1918`（待用户决定）。`BP-3_verify.py` 增加对应检查。修订前备份 `/workspace/bp_work_1121c/BP-3_G1验收用例单.md` |

## 0. 使用约定

### 0.1 标记

- 〔路径:行号「原文片段」〕：引用该文件该行的原文，该行在 `35c0cd6` 与 `10f1918` 中相同。〔@10f1918 路径:行号「原文片段」〕只对 `10f1918` 成立；〔@35c0cd6 路径:行号「原文片段」〕只对 `35c0cd6` 成立（用于 §5.3.0 对照）。`BP-3_verify.py` 会逐条核对片段是否真在那一行。
- 【推断】：根据代码或文档推出、仓库没有直接写明的结论。执行时以实际观察为准；观察不一致时照实记录，不改写成通过。
- 【建议】：比仓库原文更严，或者是仓库没有规定的做法（例如容差、人数、等待秒数、辅助脚本）。可由 A/B 决定是否采纳；不采纳时在 §7 记下决定。
- 【用户已确认 2026-11-21，经 Atlas 转达】：用户本人答复、经 Atlas 转达给 Blueprint（“已确认（用户 2026-11-21）”同义）。

### 0.2 判定与签收

1. 每个用例只填 **通过 / 未通过 / 阻塞** 三种结果之一。“阻塞”是指前置条件不满足或工具不可用，不等于通过。
2. 【建议】**必选用例中任一未通过或阻塞，G1 不通过**（沿用 BP-1 S0-5 的【建议】）。“可选”用例不影响 G1 结论，但要照实记录。
3. 签收分工按矩阵：〔docs/验收矩阵.md:46「A核模型，B联调」〕。每个用例的签收栏分 **B（王晋涛，联调）** 和 **A（宋明耀，核模型与本人结果）** 两列。**Sentinel 只审核回执，不签收。**
4. G1 签收后由用户更新矩阵，并写明证据与检查范围：〔docs/验收矩阵.md:59「后续每次签收须更新对应证据与检查范围，而非仅更新测试总数」〕。
5. 不放宽、不倒推：〔docs/验收矩阵.md:41「未指定数值质量阈值的项目保留待制定，不从已看结果倒推通过线」〕。本文里的数值容差全部标了【建议】，而且只用于判断结构是否正确（例如 R 是否正交），**不是重建质量阈值**。
6. 不得用研究链或研究开关替代严格服务：〔docs/B23真实静态链路开发记录.md:71「不得改verified来替代这一步」〕；〔docs/验收矩阵.md:57「当前严格模型清单的许可欠项不能用研究override替代」〕。
7. 浏览器用例使用生产构建：〔docs/验收矩阵.md:9「不把 Vite 开发服务当最终证明」〕。唯一的例外是 §5.5 的再导入往返，它借用仓库已有的离线研究脚本（该脚本自带 Vite），只用来证明“导出再导入”的数值不变，不当作工作台证据。

### 0.3 照片与隐私规则（必须遵守）

- 只使用**本人书面同意的成年人**照片。同意书留在本机纸面或离线文件里，回执只写同意编号，不写姓名。
- 不用网上下载的他人照片，不用合成或拼凑出来的“数据集”。唯一的公开样例是仓库 B0 已登记的 astronaut：〔docs/B23真实静态链路开发记录.md:65「本机已有样例来自B0登记的公开成年人人像astronaut」〕，SHA-256 见〔docs/B0模型验证与复现.md:71「88431cd9653ccd539741b555fb0a46b61558b301d4110412b5bc28b5e3ea6cb5」〕。
- 照片放在被 Git 忽略的 `data/g1-inputs/`，证据放在被忽略的 `output/g1/`（仓库 `.gitignore` 同时忽略 `data/` 和 `output/`）。**照片和由照片生成的 GLB 不上传 box、不提交 Git、不发给任何 agent。** 交给 box 的回执 `U-6_G1执行回执.md`【建议路径，沿用 BP-1】只含用例结果、状态码和文件哈希。
- **工作台截图同样按照片处理**：`02-ui/`、`04-errors/`、`05-cancel/`、`06-expiry/` 下的 `ui-*.png` 会拍到准备区里的本人照片（页面元素 `#source-image`），三维视口里也是本人的面部网格：〔@10f1918 frontend/index.html:43「<img id="source-image" alt="待重建的人像照片" />」〕（`35c0cd6` 中同一元素在 `frontend/src/layout.ts` 第 17 行）。单屏布局下一张截图同时拍到照片、视口和右栏，更要按照片处理。**凡含人脸或面部网格的截图、PNG 效果图、导出的 GLB，一律不出本机、不上传 box、不提交 Git、不交给任何 agent（包括 Blueprint、Sentinel、Atlas）。** Sentinel 复核回执时只看结果、状态码和哈希；需要核对画面时，由 A/B 在本机查看后写文字结论。
- 坏图和“无人脸空白图”是由本人照片或 astronaut 派生的**测试输入**（截断、改格式、放大像素等），不是数据集，用完可以删除，只保留哈希。

### 0.4 通用 PowerShell 准备（【建议】，每次开新终端时执行）

PowerShell 5.1 里的 `curl` 是 `Invoke-WebRequest` 的别名，下面一律写 `curl.exe`（Windows 10 及以上自带）。

```powershell
Set-Location -LiteralPath 'D:\project file\AgeMorph3D'
$env:AGEMORPH_NODE = 'D:\JAVA run tools\node.exe'   # Node 不在 PATH 上时才需要；按本机实际路径改
$G1  = 'output\g1\run-20261120'                     # 把日期换成实际执行日（UTC+8）
$API = 'http://127.0.0.1:8000'
$PY  = '.\backend\.venv\Scripts\python.exe'
$CHK = "$G1\tools\g1_check.py"
$DET = 'data\models\yolov5n05-face\manifest.json'
$REC = 'data\models\3ddfa-v2\manifest.json'

function G1-Reconstruct([string]$Image, [string]$Type, [string]$Out, [string]$SourceAge = '') {
  $a = @('-sS', '-D', "$Out.headers.txt", '-o', "$Out.json", '-w', '%{http_code}', '-F', "image=@$Image;type=$Type")
  if ($SourceAge) { $a += @('-F', "source_age=$SourceAge") }
  $code = & curl.exe @a "$API/api/reconstruct"
  Set-Content -LiteralPath "$Out.status.txt" -Value $code
  "$Out -> HTTP $code"
}
function G1-Fetch([string]$Json, [string]$Out) {
  $id = (Get-Content -Raw -LiteralPath $Json | ConvertFrom-Json).mesh_id
  $code = & curl.exe -sS -D "$Out.headers.txt" -o $Out -w '%{http_code}' "$API/api/assets/$id/mesh.glb"
  Set-Content -LiteralPath "$Out.status.txt" -Value $code
  "$Out ($id) -> HTTP $code"
}
```

`G1-Reconstruct` 对应接口 `POST /api/reconstruct`，表单字段是 `image` 和可选的 `source_age`：〔docs/api.md:16「`multipart/form-data`，图片字段 `image`，可选 `source_age`」〕。`G1-Fetch` 对应 `GET /api/assets/{mesh_id}/mesh.glb`：〔docs/api.md:18「`/api/assets/{mesh_id}/mesh.glb`」〕。curl 不带 Origin 头，服务允许这种本机命令行调用：〔backend/README.md:111「HTTP 无 Origin 时允许本机命令行调用」〕。

## 1. G1 条款拆分

G1 行“剩余可验证出口”的原文是：〔docs/验收矩阵.md:46「文件哈希和 CPU 自检之后的多身份/姿态、导出再导入、过期/坏图/多人/取消恢复」〕。这一行同时写明〔docs/验收矩阵.md:46「严格服务 G1 未通过」〕，并且该行对应 R03/R04/R09–R11：〔docs/验收矩阵.md:46「G1真实静态；R03/R04/R09–R11」〕。下表把这些原文拆成可以逐条检查的条款，再补上 B23 记录写明的 G1 剩余条件和 R09/R10/R11 交付列中与静态链路直接相关的部分。R03、R04 中不属于静态链路的部分见 §9。

| 条款 | 内容 | 来源 |
|---|---|---|
| G1-C01 | 严格加载：清单点名文件的哈希核验和 CPU 自检全部通过后，检测与重建才为 ready，`reconstruction=true` | 〔docs/验收矩阵.md:46「文件哈希和 CPU 自检之后」〕〔docs/后续任务清单.md:59「仅真实加载及自检成功才 ready」〕〔docs/B23真实静态链路开发记录.md:9「检测/重建均严格加载、自检成功且服务未关闭时，健康能力 `reconstruction=true`」〕 |
| G1-C02 | 必须是严格服务，不是研究链；不得使用研究开关，不得手改 verified 或哈希 | 〔docs/验收矩阵.md:46「研究链成立」〕〔docs/干净环境与离线复现准备.md:83「启动器仍拒绝 `--research-allow-unresolved`」〕〔docs/B23真实静态链路开发记录.md:71「不得改verified来替代这一步」〕 |
| G1-C03 | 多身份：不同真实身份的照片各自得到自己的输出 | 〔docs/验收矩阵.md:46「多身份/姿态」〕〔docs/后续任务清单.md:61「不同照片得到各自输出」〕〔docs/B23真实静态链路开发记录.md:73「本轮真实模型证据仍只有一个身份及其变体」〕 |
| G1-C04 | 多姿态：正面和侧面都能重建 | 〔docs/验收矩阵.md:46「多身份/姿态」〕〔docs/后续任务清单.md:56「正面/侧面真实身份/表情/网格/UV」〕〔docs/B23真实静态链路开发记录.md:71「补充不同真实身份、侧脸、错误恢复及Chrome/Edge正式工作台往返证据」〕 |
| G1-C05 | 图像方向：真实解码并纠正 EXIF；镜像图不复用原图输出 | 〔docs/B23真实静态链路开发记录.md:7「真实解码并纠正EXIF」〕〔docs/后续任务清单.md:61「图像方向和框/点/ROI 到原图的变换明确」〕 |
| G1-C06 | 静态结果契约：static、两项年龄能力 false、`texture_url=null`；身份 40 维和表情 10 维已应用；源年龄为 unknown 或用户值 | 〔docs/B23真实静态链路开发记录.md:11「成功结果为static、年龄能力均false、texture_url=null」〕〔docs/B23真实静态链路开发记录.md:11「身份40维与表情10维已经应用到网格」〕〔docs/api.md:51「`unknown` 必须两个值都为 null」〕〔docs/api.md:30「提供时必须是最长32字符的ASCII普通十进制文本，20—70之间」〕 |
| G1-C07 | 网格与姿态：拓扑固定（38365 顶点、76073 面、拓扑哈希）；`RᵀR≈I`、`det(R)≈1`；`t` 为三个 0；不双重旋转、无外链、无非法维度；GLB 标明非米制 | 〔docs/后续任务清单.md:62「`RᵀR≈I`、`det(R)≈1`」〕〔docs/后续任务清单.md:62「身份/表情已应用，无双重旋转、外链或非法维度」〕〔docs/B23真实静态链路开发记录.md:15「保留原始38365个顶点的顺序与76073个面的顺序」〕〔docs/B23真实静态链路开发记录.md:19「API的t为三个0」〕〔docs/B23真实静态链路开发记录.md:17「dimensionless、source_units=unverified和metric_scale_verified=false」〕 |
| G1-C08 | Chrome 与 Edge 的正式工作台（生产构建）完成上传、重建、查看、导出 | 〔docs/后续任务清单.md:63「真实照片在 Chrome/Edge 加载导出再导入」〕〔docs/B23真实静态链路开发记录.md:71「补充不同真实身份、侧脸、错误恢复及Chrome/Edge正式工作台往返证据」〕 |
| G1-C09 | 导出再导入：导出的 GLB 再导入后几何、法线、索引不变 | 〔docs/验收矩阵.md:46「导出再导入」〕〔docs/后续任务清单.md:63「真实照片在 Chrome/Edge 加载导出再导入」〕 |
| G1-C10 | 无人脸：真实失败（422/NO_FACE），之后能恢复 | 〔docs/后续任务清单.md:61「无人脸/多人脸真实失败」〕〔docs/B23真实静态链路开发记录.md:7「零人脸为422/NO_FACE，多人为422/MULTI_FACE」〕 |
| G1-C11 | 多人脸：真实失败（422/MULTI_FACE），之后能恢复 | 〔docs/验收矩阵.md:46「过期/坏图/多人/取消恢复」〕〔docs/B23真实静态链路开发记录.md:7「零人脸为422/NO_FACE，多人为422/MULTI_FACE」〕 |
| G1-C12 | 坏图：损坏、空文件、格式不支持、声明不一致、超字节、超像素、动画图都被拒绝，之后能恢复 | 〔docs/验收矩阵.md:46「过期/坏图/多人/取消恢复」〕〔docs/api.md:55「图片仅接受非空 JPG、PNG、WebP，最大 10 MiB、1600 万像素」〕〔backend/README.md:115「真正可解码的 JPEG、PNG、WebP」〕 |
| G1-C13 | 取消：取消后能恢复，不发布、不显示迟到结果 | 〔docs/验收矩阵.md:46「过期/坏图/多人/取消恢复」〕〔docs/后续任务清单.md:60「取消不发迟到结果」〕〔docs/B23真实静态链路开发记录.md:29「取消、断连、超时和关闭不会发布迟到网格」〕 |
| G1-C14 | 过期：TTL 从发布时起算、访问不续期；过期、未知或重启后的 ID 返回 404；重新重建可以恢复 | 〔docs/验收矩阵.md:46「过期/坏图/多人/取消恢复」〕〔docs/B23真实静态链路开发记录.md:25「TTL从发布时开始，访问不续期」〕〔docs/B23真实静态链路开发记录.md:25「过期/未知/淘汰/重启后的ID为404」〕 |
| G1-C15 | 坏资产可恢复 | 〔docs/后续任务清单.md:63「过期/取消/坏资产可恢复」〕 |
| G1-C16 | 静态 UI 语义：显式静态 GLB、不造零 morph、不显示虚构 30 岁、导出名含 original、不写年龄字段 | 〔docs/后续任务清单.md:63「不造零 morph、不显示虚构30岁」〕〔docs/后续任务清单.md:58「静态控件/对照/导出语义明确」〕〔docs/api.md:87「静态导出名含 `original`」〕〔docs/api.md:87「不写 `age/ageAnchors/displayAge`」〕 |
| G1-C17 | 演示回归 | 〔docs/后续任务清单.md:63「演示回归」〕 |
| G1-C18 | 年龄接口仍关闭：`/api/aging` 返回 503 `MODEL_NOT_READY`，两项年龄能力 false | 〔docs/验收矩阵.md:57「生产 `/api/aging` 继续返回 `503 MODEL_NOT_READY`」〕〔docs/干净环境与离线复现准备.md:122「`/api/aging` 仍是 `MODEL_NOT_READY`」〕 |
| G1-C19 | 证据可追溯：记录执行环境、提交、锁文件和模型文件哈希、浏览器版本，签收时写明检查范围 | 〔docs/验收矩阵.md:59「后续每次签收须更新对应证据与检查范围」〕〔docs/B23真实静态链路开发记录.md:45「真实研究脚本使用本机Chrome155.0.8059.84、Edge155.0.4283.62和软件WebGL」〕 |

**不属于 G1 的事项**：干净环境与断网复现属于 L02，由另一名成员在他自己的机器上执行：〔docs/干净环境与离线复现准备.md:3「L02 的执行人是另一名成员」〕。本文只加一个可选的断网记录用例（G1-ENV-04【建议】），不代替 L02。

## 2. 环境记录（执行人填写）

复制本表到 `$G1\00-env\env-record.md` 后填写。版本要求只转述锁文件：〔docs/干净环境与离线复现准备.md:25「`requires-python = "==3.11.*"`」〕〔docs/干净环境与离线复现准备.md:26「`engines.node` 为 `>=22.18.0`」〕。

| 项 | 记录 | 来源/命令 |
|---|---|---|
| 执行人（A/B 代号） | | |
| 执行起止时间（UTC+8） | | |
| 机器、Windows 版本、CPU 型号 | | 系统信息 |
| GPU（只记录，G1 不验 GPU） | | 设备管理器 |
| git commit / 工作区是否干净 | | `git rev-parse HEAD`；`git status --porcelain`（repro-check 报告也会记录） |
| 是否为 10f1918 | 是 / 否（否则按 §8 Q-3 的【建议】处理：先确认 `git status --porcelain` 为空，再切回 `10f1918`；不能切回则停止并报告） | `git rev-parse --short HEAD`；`git log --oneline 10f1918..HEAD` |
| Python（须满足 `==3.11.*`） | | `& $PY --version` |
| Node（须满足 `>=22.18.0`） | | `node --version` 或 `& $env:AGEMORPH_NODE --version` |
| uv（锁文件不固定版本） | | `uv --version` |
| `backend/uv.lock` SHA-256 | | repro-check 报告 |
| `frontend/package-lock.json` SHA-256 | | repro-check 报告 |
| Python 包、npm 包与锁是否一致 | | repro-check 报告 |
| 检测清单与其 1 个文件的 SHA-256 是否一致 | | repro-check / model_diagnostics |
| 重建清单与其 3 个文件（regressor、bfm、param_stats）的 SHA-256 是否一致 | | 同上 |
| 本地清单是否从 `backend/model-manifests/` 新复制（`license_status`） | | 文件比较 |
| Chrome 版本 | | `chrome://version` |
| Edge 版本 | | `edge://version` |
| 网络状态（联网 / 断网及方式） | | G1-ENV-04（可选） |
| 偏差 | | |

## 3. 证据目录布局

全部位于项目内被忽略的 `output/g1/run-<YYYYMMDD>/`（下称 `$G1`）。照片输入位于 `data/g1-inputs/`，也被忽略。

```text
data/g1-inputs/                     # 照片与派生测试输入，不出本机
  P00-front.png                     # astronaut（B0 登记），复制自 data/samples/astronaut.png
  P01-front.jpg  P01-yawL.jpg  P01-yawR.jpg  P01-profile.jpg  P01-exif.jpg  P01-mirror.png
  P02-front.jpg  P02-yawL.jpg  P02-yawR.jpg  P02-profile.jpg
  P03-front.jpg  P03-yawL.jpg  P03-yawR.jpg  P03-profile.jpg
  P01-large.jpg                     # 取消用例：原尺寸大图（≤10 MiB、≤1600 万像素）
  NF-scene.jpg  NF-blank.png        # 无人脸
  MF-two.jpg                        # 多人脸（P01 与 P02 同框）
  BAD-*.*                           # 坏图（§4.3 生成）
output/g1/run-<YYYYMMDD>/
  tools/g1_check.py                 # 附录 A 的辅助脚本
  00-env/   env-record.md, repro-check-skip-smoke.json, model-diagnostics.json, model-diagnostics.exit.txt,
            research-flag.txt, research-flag-ports.txt, pytest-research-bypass.txt, health-ready.json, aging-503.json, aging-503.status.txt, inputs-sha256.csv,
            network.txt（可选）
  01-identity/ <用例>-<输入>.json/.headers.txt/.status.txt, <输入>.glb, check-*.json, pytest-geometry-transforms.txt
  02-ui/    chrome/  edge/          # 截图 ui-*.png，浏览器下载的 AgeMorph3D-*.glb/png，notes.md
  03-export/ roundtrip-<名称>/static-mesh-research.json 及截图、exported-*.glb
  04-errors/ NF-*, MF-*, BAD-*, recover-* 的 json/headers/status
  05-cancel/ cancel-*.txt, retry-*.json, ui-*.png, pytest-static.txt
  06-expiry/ ttl-*.json/.status.txt, restart-*.status.txt, ui-*.png
  local-run-backend.log             # 用例结束后从 output/local-run/backend.log 复制
  sha256sums.txt                    # 本目录所有文件的 SHA-256（G1-SUM 生成）
  G1-results.md                     # §7 结果汇总
```

启动器的状态和日志默认写在〔tools/local_run.py:211「path = (root / "output" / "local-run").resolve()」〕，每个角色一个日志文件：〔tools/local_run.py:1499「log_path = plan.state_dir / f"{role}.log"」〕。【推断】后端日志文件名是 `output/local-run/backend.log`，以本机实际文件为准。

## 4. 输入数据准备

### 4.1 身份与姿态照片

| 代号 | 身份 | 来源 | 必需姿态 |
|---|---|---|---|
| P00 | astronaut 公开样例 | 仓库 B0 已登记，`data/samples/astronaut.png` | 正面（基线） |
| P01 | 成年志愿者 1（例如用户本人） | 本人用手机或相机拍摄，书面同意 | front、yawL、yawR、profile；另外 exif、mirror、large |
| P02 | 成年志愿者 2（例如另一名组员） | 同上 | front、yawL、yawR、profile |
| P03 | 成年志愿者 3 | 同上 | front、yawL、yawR、profile |

- 人数：G1 原文没有规定身份数。【建议】除 P00 外**至少 3 名**真实成年人（P01–P03）。只能找到 2 人时，记为偏差交 A/B 决定（§8 Q-1）。
- 姿态：front 为正对镜头；yawL、yawR 为头向左、向右各转约 30°；profile 为约 60°–90° 的大侧脸。角度是【建议】拍摄指引，不是验收阈值。光线均匀、单人、无遮挡；每张不超过 10 MiB、1600 万像素。
- P01-exif：用手机**竖拍**一张正面照，原样导出（保留 EXIF Orientation 标签）。用下面的命令确认标签值不等于 1。
- P01-mirror：由 P01-front 左右镜像生成（§4.3）。
- P01-large：原尺寸正面大图（例如 1200 万像素、小于 10 MiB），用于让推理时间长一点，方便取消。

```powershell
& $PY -c "from PIL import Image; im=Image.open(r'data\g1-inputs\P01-exif.jpg'); print('EXIF Orientation =', im.getexif().get(274))"
```

### 4.2 无人脸与多人脸

- NF-scene.jpg：本人拍摄、画面中没有任何人的场景照（例如桌面或墙面）。
- NF-blank.png：640×480 纯灰图，按 §4.3 生成。
- MF-two.jpg：P01 与 P02 同框、两张脸都清晰（两人均已书面同意）。

### 4.3 派生测试输入生成（【建议】命令；只生成测试输入，不改仓库）

```powershell
@'
from pathlib import Path
from PIL import Image, ImageOps
d = Path("data/g1-inputs")
front = d / "P01-front.jpg"
# 镜像（PNG 无损保存）
ImageOps.mirror(ImageOps.exif_transpose(Image.open(front))).convert("RGB").save(d / "P01-mirror.png")
# 无人脸空白图
Image.new("RGB", (640, 480), (128, 128, 128)).save(d / "NF-blank.png")
raw = front.read_bytes()
(d / "BAD-truncated.jpg").write_bytes(raw[: len(raw) // 2])          # 损坏：截断一半
(d / "BAD-empty.jpg").write_bytes(b"")                                 # 空文件
src = Image.open("data/samples/astronaut.png").convert("RGB")
src.save(d / "BAD-format.gif")                                         # 不支持的格式
src.save(d / "BAD-mismatch.png")                                       # 实为 PNG，上传时声明成 JPEG
(d / "BAD-oversize.jpg").write_bytes(raw + b"\0" * (11 * 1024 * 1024))  # 超过 10 MiB + 64 KiB
Image.new("RGB", (4200, 4100), (120, 120, 120)).save(d / "BAD-pixels.png")   # 1722 万像素 > 1600 万
frames = [src, ImageOps.mirror(src)]
frames[0].save(d / "BAD-anim.webp", save_all=True, append_images=frames[1:], duration=200, loop=0)
print("ok")
'@ | & $PY -
Copy-Item data\samples\astronaut.png data\g1-inputs\P00-front.png
Get-ChildItem data\g1-inputs | Get-FileHash -Algorithm SHA256 |
  ForEach-Object { "$($_.Hash.ToLower()),$(Split-Path -Leaf $_.Path)" } |
  Set-Content -Encoding utf8 "$G1\00-env\inputs-sha256.csv"
```

`inputs-sha256.csv` 只含文件名和哈希。【建议】在同一文件里再补一列同意编号（例如 `C-P01`），不写姓名。

## 5. 用例

每个用例都有以下字段：编号、类别、必选、对应验收条款、前置条件、输入数据、逐步操作、期望结果、证据文件名、判定/签收。“对应验收条款”里的 G1-Cxx 见 §1。

### 5.1 环境、严格加载与年龄接口

### G1-ENV-01 环境与锁文件记录

- **编号**：G1-ENV-01
- **类别**：环境记录
- **必选**：是
- **对应验收条款**：G1-C19；〔docs/干净环境与离线复现准备.md:103「报告写到被忽略的 `output/repro-check/report.json`」〕〔docs/干净环境与离线复现准备.md:141「`l02_executed` 和 `l02_signed_off` 固定为 false」〕
- **前置条件**：已按锁文件安装依赖（`uv ... sync --locked --extra inference`、`npm ci`）；模型文件已按台账放进 `data/models/`；本地清单已从 `backend/model-manifests/` 重新复制：〔docs/干净环境与离线复现准备.md:83「本地 `data\models\...\manifest.json` 如果是旧副本，重新从 `backend\model-manifests\` 复制后再启动」〕。8000、4173 端口空闲
- **输入数据**：无照片
- **逐步操作**：
  1. 新建证据目录，并把附录 A 的脚本存成 `$G1\tools\g1_check.py`。
  2. 只读环境检查（不启动服务）：
     ```powershell
     New-Item -ItemType Directory -Force "$G1\tools","$G1\00-env","$G1\01-identity","$G1\02-ui\chrome","$G1\02-ui\edge","$G1\03-export","$G1\04-errors","$G1\05-cancel","$G1\06-expiry" | Out-Null
     .\tools\repro-check.ps1 --skip-smoke --detector-manifest $DET --reconstructor-manifest $REC --output "$G1\00-env\repro-check-skip-smoke.json"
     "exit=$LASTEXITCODE" | Set-Content "$G1\00-env\repro-check.exit.txt"
     ```
  3. 按 §2 填写 `env-record.md`。
- **期望结果**：退出码 0；报告中的 Python 包、npm 包与锁一致；两份清单点名的 4 个文件（检测 1 个、重建 3 个）都存在，且 SHA-256 与清单一致；`git commit` 已记录；报告保持 `l02_executed=false`（这不是 L02）。退出码 1 或 2 即未通过，原因照抄报告里的 `problems`。`gaps` 中的条目（例如 uv 版本不在锁里）只记录，不影响本例
- **证据文件名**：`$G1\00-env\repro-check-skip-smoke.json`、`$G1\00-env\repro-check.exit.txt`、`$G1\00-env\env-record.md`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛） | 签收 A（宋明耀） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G1-ENV-02 模型文件哈希只读诊断

- **编号**：G1-ENV-02
- **类别**：严格加载
- **必选**：是
- **对应验收条款**：G1-C01、G1-C02；〔backend/model-manifests/3ddfa-v2.research.json:10「"license_status": "verified"」〕〔backend/model-manifests/yolov5n05-face.research.json:10「"license_status": "verified"」〕
- **前置条件**：G1-ENV-01 通过
- **输入数据**：两份本地清单及其点名的权重文件
- **逐步操作**：
  ```powershell
  .\tools\local-run.ps1 diagnose --detector-manifest $DET --reconstructor-manifest $REC |
    Out-File -Encoding utf8 "$G1\00-env\model-diagnostics.json"
  "exit=$LASTEXITCODE" | Set-Content "$G1\00-env\model-diagnostics.exit.txt"
  ```
- **期望结果**：退出码 0，报告 `status` 为 `preconditions_met`（诊断程序退出 0 的条件见 `backend/src/agemorph3d/model_diagnostics.py`）。诊断只说明满足加载前置条件，不授予 ready：〔backend/README.md:47「退出0仅表示满足加载前置条件」〕。退出码 1 即未通过，并照抄报告中的阻塞项。**禁止**为通过本例手改清单的 SHA-256、大小或 `license_status`
- **证据文件名**：`$G1\00-env\model-diagnostics.json`、`$G1\00-env\model-diagnostics.exit.txt`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛） | 签收 A（宋明耀） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G1-ENV-03 严格服务启动、CPU 自检就绪与年龄接口关闭

- **编号**：G1-ENV-03
- **类别**：严格加载
- **必选**：是
- **对应验收条款**：G1-C01、G1-C02、G1-C18；〔docs/干净环境与离线复现准备.md:122「检测和重建可以变为 `ready`，`reconstruction` 与 `realtime` 可以为 true」〕〔tools/local_run.py:1853「def build_parser() -> argparse.ArgumentParser:」〕〔backend/tests/test_local_run.py:799「def test_spawn_rejects_install_commands_and_research_bypass():」〕
- **前置条件**：G1-ENV-02 通过；8000、4173 端口空闲，否则启动器会退出：〔docs/干净环境与离线复现准备.md:116「端口已被其他程序占用时，脚本退出 3」〕
- **输入数据**：无照片
- **逐步操作**：
  1. 研究开关负例（命令行层）。启动器的参数解析器只接受下列参数，没有 `--research-allow-unresolved`：〔tools/local_run.py:1858「parser.add_argument("command", choices=("check", "status", "start", "stop", "diagnose"))」〕；解析在 `main()` 里进行，argparse 遇到未知参数会直接退出：〔tools/local_run.py:1918「try:」〕（其后一行即 `parser.parse_args`，只捕获 `LocalRunError`，不捕获 argparse 的退出）。
     ```powershell
     .\tools\local-run.ps1 start --research-allow-unresolved *>&1 | Out-File -Encoding utf8 "$G1\00-env\research-flag.txt"
     "exit=$LASTEXITCODE" | Add-Content "$G1\00-env\research-flag.txt"
     Get-NetTCPConnection -LocalPort 8000,4173 -State Listen -ErrorAction SilentlyContinue |
       Out-File -Encoding utf8 "$G1\00-env\research-flag-ports.txt"
     "listen_count=$((Get-NetTCPConnection -LocalPort 8000,4173 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count)" |
       Add-Content "$G1\00-env\research-flag-ports.txt"
     ```
  1b. 研究开关负例（启动器内部防护）。内部防护 `assert_spawn_allowed` 遇到含 `--research-allow-unresolved` 的子进程命令行时抛出 `RESEARCH_BYPASS_FORBIDDEN`：〔tools/local_run.py:239「"RESEARCH_BYPASS_FORBIDDEN",」〕。这条路径从命令行走不到，用仓库已有的单元测试佐证（测试传入的是 `agemorph3d.static_probe` 的命令行）：〔backend/tests/test_local_run.py:807「assert bypass.value.code == "RESEARCH_BYPASS_FORBIDDEN"」〕
     ```powershell
     Push-Location backend
     .\.venv\Scripts\python.exe -m pytest -q "tests/test_local_run.py::test_spawn_rejects_install_commands_and_research_bypass" *>&1 |
       Out-File -Encoding utf8 "..\$G1\00-env\pytest-research-bypass.txt"
     "exit=$LASTEXITCODE" | Add-Content "..\$G1\00-env\pytest-research-bypass.txt"
     Pop-Location
     ```
  2. 用真实清单启动生产模式：
     ```powershell
     .\tools\local-run.ps1 start --production --detector-manifest $DET --reconstructor-manifest $REC
     .\tools\local-run.ps1 status
     ```
  3. 反复读取健康检查，直到两个模型都不再是 `loading`（【建议】最多等 120 秒），保存最终结果：
     ```powershell
     curl.exe -sS -o "$G1\00-env\health-ready.json" "$API/api/health"
     ```
  4. 年龄接口（PowerShell 5.1 会吃掉命令行参数里的双引号，所以请求体先写进文件）：
     ```powershell
     Set-Content -Encoding ascii "$G1\00-env\aging-body.json" '{"mesh_id":"abc","age":30}'
     curl.exe -sS -o "$G1\00-env\aging-503.json" -w '%{http_code}' -H 'Content-Type: application/json' --data-binary "@$G1\00-env\aging-body.json" "$API/api/aging" | Set-Content "$G1\00-env\aging-503.status.txt"
     ```
- **期望结果**：
  - 步骤 1：启动器拒绝启动；`research-flag.txt` 含 argparse 的 `unrecognized arguments: --research-allow-unresolved`（输出到 stderr，已用 `*>&1` 一并写入），末行 `exit=2`；`research-flag-ports.txt` 末行 `listen_count=0`，即 8000、4173 都没有被拉起。退出码不是 2 但非 0 时照实记录并由 B（王晋涛） 说明原因；退出码为 0 或端口有监听即未通过。（box 上的 35c0cd6 只读克隆在 Linux 实测：同一参数退出码 2，输出 `local_run.py: error: unrecognized arguments: --research-allow-unresolved`；Windows 上经 `local-run.ps1` 的 `exit $LASTEXITCODE` 传出，【推断】同为 2。）
  - 步骤 1b：退出码 0，输出 `1 passed`。这是合成单元测试，只证明内部防护存在，不是真实服务证据。
  - 步骤 3：`models.detector.state` 和 `models.reconstructor.state` 都是 `ready`；`capabilities.reconstruction=true`、`capabilities.realtime=true`、`age_morph=false`、`age_texture=false`；`age_shape`、`age_texture` 两个模型为 `missing`；`api_version` 为 `1.2`，`device` 为 `cpu`。任何一个是 `error` 即未通过，并照抄 `detail`。
  - 步骤 4：HTTP 503，JSON 中 `code` 为 `MODEL_NOT_READY`。
- **证据文件名**：`$G1\00-env\research-flag.txt`、`$G1\00-env\research-flag-ports.txt`、`$G1\00-env\pytest-research-bypass.txt`、`$G1\00-env\health-ready.json`、`$G1\00-env\aging-503.json`、`$G1\00-env\aging-503.status.txt`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛） | 签收 A（宋明耀） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G1-ENV-04 断网执行记录（可选）【建议】

- **编号**：G1-ENV-04
- **类别**：离线
- **必选**：否（可选；G1 原文没有要求断网，L02 另行执行）
- **对应验收条款**：G1-C19（补充）；照片不出本机：〔docs/api.md:9「用户照片、摄像头帧和推理输出不发送到云端」〕；Windows 上没有网络命名空间隔离：〔docs/干净环境与离线复现准备.md:139「Windows 没有这个调用，报告写 `not_applicable`」〕
- **前置条件**：依赖和模型文件已就位
- **输入数据**：无
- **逐步操作**：在 G1-ENV-03 之前禁用网络适配器（或拔网线），整个 G1 期间保持断网；把断网方式和时间写进 `network.txt`；最后执行 `Test-NetConnection 1.1.1.1 -Port 443`，把结果追加进同一文件。
- **期望结果**：断网状态下 G1-ENV-03 到 G1-EXPIRE-03 的结果与联网时一致；`Test-NetConnection` 显示外网不通。本例只是补充记录，不代替 L02
- **证据文件名**：`$G1\00-env\network.txt`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛） | 签收 A（宋明耀） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### 5.2 多身份、多姿态与图像方向（命令行，严格服务）

### G1-ID-01 公开样例基线（P00）

- **编号**：G1-ID-01
- **类别**：多身份
- **必选**：是
- **对应验收条款**：G1-C06、G1-C07；〔docs/B23真实静态链路开发记录.md:15「cc449ed7efa2860bed64be0a7e29ad8944912148c69f938ff768c8766d65e7cb」〕
- **前置条件**：G1-ENV-03 通过，服务保持运行
- **输入数据**：`P00-front.png`（SHA-256 应为 `88431cd9…cb5`，与 B0 台账一致）
- **逐步操作**：
  ```powershell
  G1-Reconstruct 'data/g1-inputs/P00-front.png' 'image/png' "$G1\01-identity\ID01-P00-front"
  G1-Fetch "$G1\01-identity\ID01-P00-front.json" "$G1\01-identity\P00-front.glb"
  & $PY $CHK resp "$G1\01-identity\ID01-P00-front.json" --source-age unknown | Set-Content "$G1\01-identity\check-resp-P00-front.json"
  & $PY $CHK glb "$G1\01-identity\P00-front.glb" --response "$G1\01-identity\ID01-P00-front.json" | Set-Content "$G1\01-identity\check-glb-P00-front.json"
  ```
- **期望结果**：重建 HTTP 200；两份 check 输出都是 `"ok": true`，具体包括：`mesh_id` 是 32 位小写十六进制；`topology_id` 为 `tddfa-bfm-canon-v1-cc449ed7…e7cb`；`asset_mode=static`；结果 capabilities 两项都是 false；`texture_url` 为 null；`shape` 40 维、`expr` 10 维；`t=[0,0,0]`；`RᵀR` 与 I 的最大偏差 ≤ 1e-4 且 `|det(R)−1|` ≤ 1e-4（容差为【建议】）；`source_age` 为 unknown（值和校准标识都为 null）。GLB 读取 HTTP 200，响应头 `Content-Type: model/gltf-binary`，并带 `Cache-Control: no-store`：〔docs/api.md:65「Content-Type为 `model/gltf-binary`，设置Content-Length和no-store」〕；38365 个顶点、76073 个三角形；单一内嵌 buffer，无外链 uri；无 morph target；场景 extras 中 `coordinate_metadata` 为 dimensionless、unverified、`metric_scale_verified=false`；extras 不含 age、ageAnchors、displayAge、texture_age
- **证据文件名**：`$G1\01-identity\ID01-P00-front.json/.headers.txt/.status.txt`、`$G1\01-identity\P00-front.glb/.headers.txt/.status.txt`、`$G1\01-identity\check-resp-P00-front.json`、`$G1\01-identity\check-glb-P00-front.json`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛） | 签收 A（宋明耀） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G1-ID-02 多身份正面重建（P01–P03）

- **编号**：G1-ID-02
- **类别**：多身份
- **必选**：是
- **对应验收条款**：G1-C03、G1-C06、G1-C07；〔docs/后续任务清单.md:61「不同照片得到各自输出」〕
- **前置条件**：G1-ID-01 通过
- **输入数据**：`P01-front.jpg`、`P02-front.jpg`、`P03-front.jpg`（同意编号写进 inputs-sha256.csv）
- **逐步操作**：
  ```powershell
  foreach ($p in 'P01','P02','P03') {
    G1-Reconstruct "data/g1-inputs/$p-front.jpg" 'image/jpeg' "$G1\01-identity\ID02-$p-front"
    G1-Fetch "$G1\01-identity\ID02-$p-front.json" "$G1\01-identity\$p-front.glb"
    & $PY $CHK resp "$G1\01-identity\ID02-$p-front.json" --source-age unknown | Set-Content "$G1\01-identity\check-resp-$p-front.json"
    & $PY $CHK glb "$G1\01-identity\$p-front.glb" --response "$G1\01-identity\ID02-$p-front.json" | Set-Content "$G1\01-identity\check-glb-$p-front.json"
  }
  & $PY $CHK distinct "$G1\01-identity\P00-front.glb" "$G1\01-identity\P01-front.glb" "$G1\01-identity\P02-front.glb" "$G1\01-identity\P03-front.glb" | Set-Content "$G1\01-identity\check-distinct-front.json"
  ```
  然后用 A（宋明耀） 的判断做一次目视检查：工作台没有 GLB 导入控件，所以在 G1-UI-01 的工作台里依次选择 P00—P03 的正面照重建，用视角按钮“正面”“侧面”各看一次，每人截一张图。
- **期望结果**：3 次重建都是 HTTP 200，每份 check 都是 `"ok": true`（逐项与 G1-ID-01 相同）；`check-distinct-front.json` 中 4 个 GLB 的 SHA-256 两两不同，任意两者的顶点坐标最大差都大于 0；4 个 `shape` 向量两两不同。这里只证明“各自输出”，**不评价重建精度**，也不设相似度阈值。A（宋明耀） 目视确认每个网格是开放面部、没有明显翻转或塌陷；看到异常就照实写进备注，不改判为通过
- **证据文件名**：`$G1\01-identity\ID02-P0{1,2,3}-front.*`、`$G1\01-identity\P0{1,2,3}-front.glb`、`$G1\01-identity\check-*-P0{1,2,3}-front.json`、`$G1\01-identity\check-distinct-front.json`、`$G1\02-ui\chrome\ui-identity-P0{0..3}-{front,side}.png`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛） | 签收 A（宋明耀） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G1-ID-03 多姿态：左右约 30° 侧转

- **编号**：G1-ID-03
- **类别**：多姿态
- **必选**：是
- **对应验收条款**：G1-C04、G1-C07；〔docs/后续任务清单.md:56「正面/侧面真实身份/表情/网格/UV」〕〔docs/B23真实静态链路开发记录.md:19「R未烘入canonical网格」〕
- **前置条件**：G1-ID-02 通过
- **输入数据**：P01–P03 的 `yawL.jpg`、`yawR.jpg`
- **逐步操作**：
  ```powershell
  foreach ($p in 'P01','P02','P03') { foreach ($v in 'yawL','yawR') {
    G1-Reconstruct "data/g1-inputs/$p-$v.jpg" 'image/jpeg' "$G1\01-identity\ID03-$p-$v"
    G1-Fetch "$G1\01-identity\ID03-$p-$v.json" "$G1\01-identity\$p-$v.glb"
    & $PY $CHK resp "$G1\01-identity\ID03-$p-$v.json" --source-age unknown | Set-Content "$G1\01-identity\check-resp-$p-$v.json"
    & $PY $CHK glb "$G1\01-identity\$p-$v.glb" --response "$G1\01-identity\ID03-$p-$v.json" | Set-Content "$G1\01-identity\check-glb-$p-$v.json"
    & $PY $CHK angle "$G1\01-identity\ID02-$p-front.json" "$G1\01-identity\ID03-$p-$v.json" | Set-Content "$G1\01-identity\check-angle-$p-front-$v.json"
  }
  & $PY $CHK angle "$G1\01-identity\ID03-$p-yawL.json" "$G1\01-identity\ID03-$p-yawR.json" | Set-Content "$G1\01-identity\check-angle-$p-yawL-yawR.json" }
  ```
- **期望结果**：6 次重建都是 HTTP 200，每份 resp 和 glb 检查都是 `"ok": true`。姿态检查与旋转矩阵的分解约定无关，只比较两个 R 之间的相对旋转角：【建议】每人 front 与 yawL、front 与 yawR 的相对角都 ≥ 10°，而且 yawL 与 yawR 之间的相对角大于其中任何一个，说明两张图在正面的两侧。这些角度是拍摄角度的结构性检查，不是精度阈值。GLB 拓扑与正面一致（顶点数、三角形数相同），因为 R 不烘进 canonical 网格；不同姿态的 GLB 哈希允许不同
- **证据文件名**：`$G1\01-identity\ID03-*.json/.headers.txt/.status.txt`、`$G1\01-identity\P0{1,2,3}-yaw{L,R}.glb`、`$G1\01-identity\check-resp-*`、`check-glb-*`、`check-angle-*.json`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛） | 签收 A（宋明耀） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G1-ID-04 多姿态：大侧脸（约 60°–90°）

- **编号**：G1-ID-04
- **类别**：多姿态
- **必选**：是（要求有明确结果，不要求一定成功，见期望结果）
- **对应验收条款**：G1-C04、G1-C10；失败必须是固定的脱敏错误，不得用演示网格补成功：〔docs/B23真实静态链路开发记录.md:7「没有用演示网格补成功」〕
- **前置条件**：G1-ID-03 通过
- **输入数据**：P01–P03 的 `profile.jpg`
- **逐步操作**：
  ```powershell
  foreach ($p in 'P01','P02','P03') {
    G1-Reconstruct "data/g1-inputs/$p-profile.jpg" 'image/jpeg' "$G1\01-identity\ID04-$p-profile"
    if ((Get-Content "$G1\01-identity\ID04-$p-profile.status.txt") -eq '200') {
      G1-Fetch "$G1\01-identity\ID04-$p-profile.json" "$G1\01-identity\$p-profile.glb"
      & $PY $CHK resp "$G1\01-identity\ID04-$p-profile.json" --source-age unknown | Set-Content "$G1\01-identity\check-resp-$p-profile.json"
      & $PY $CHK glb "$G1\01-identity\$p-profile.glb" --response "$G1\01-identity\ID04-$p-profile.json" | Set-Content "$G1\01-identity\check-glb-$p-profile.json"
    }
  }
  G1-Reconstruct 'data/g1-inputs/P01-front.jpg' 'image/jpeg' "$G1\01-identity\ID04-recover"
  ```
- **期望结果**：每张图都只能是以下两种结果之一：(a) HTTP 200，且 resp、glb 检查都是 `"ok": true`；(b) 应用层 JSON 错误，`code` 为 `NO_FACE`（422）或 `RECONSTRUCTION_FAILED`（500，〔backend/src/agemorph3d/reconstruction.py:55「500, "RECONSTRUCTION_FAILED", "人脸重建失败，请更换清晰照片后重试。"」〕），响应头带 `Cache-Control: no-store`。不允许出现无 JSON 的崩溃、`INTERNAL_ERROR` 或服务退出。最后的恢复请求 `ID04-recover` 为 HTTP 200。结果分布（几张成功、几张失败）照实写进备注，用来说明侧脸能力的边界，**不倒推通过线**。【建议】三张大侧脸全部失败时，A（宋明耀） 需要在备注中说明这是否满足 R04 的“侧面”要求（§8 Q-2）
- **证据文件名**：`$G1\01-identity\ID04-*.json/.headers.txt/.status.txt`、成功时的 `$G1\01-identity\P0x-profile.glb` 和 `check-*-P0x-profile.json`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛） | 签收 A（宋明耀） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G1-ID-05 图像方向：EXIF 旋转与镜像

- **编号**：G1-ID-05
- **类别**：图像方向
- **必选**：是
- **对应验收条款**：G1-C05、G1-C03；〔docs/B23真实静态链路开发记录.md:40「6类预期结果通过：空白NO_FACE、双人MULTI_FACE、镜像成功、EXIF旋转成功、坏图BAD_INPUT、无研究开关严格拒绝」〕（那是研究探针的历史证据，本例在严格服务上重做）
- **前置条件**：G1-ID-02 通过
- **输入数据**：`P01-exif.jpg`（EXIF Orientation ≠ 1）、`P01-mirror.png`
- **逐步操作**：
  ```powershell
  G1-Reconstruct 'data/g1-inputs/P01-exif.jpg' 'image/jpeg' "$G1\01-identity\ID05-P01-exif"
  G1-Fetch "$G1\01-identity\ID05-P01-exif.json" "$G1\01-identity\P01-exif.glb"
  G1-Reconstruct 'data/g1-inputs/P01-mirror.png' 'image/png' "$G1\01-identity\ID05-P01-mirror"
  G1-Fetch "$G1\01-identity\ID05-P01-mirror.json" "$G1\01-identity\P01-mirror.glb"
  foreach ($v in 'exif','mirror') {
    & $PY $CHK resp "$G1\01-identity\ID05-P01-$v.json" --source-age unknown | Set-Content "$G1\01-identity\check-resp-P01-$v.json"
    & $PY $CHK angle "$G1\01-identity\ID02-P01-front.json" "$G1\01-identity\ID05-P01-$v.json" | Set-Content "$G1\01-identity\check-angle-P01-front-$v.json"
  }
  & $PY $CHK distinct "$G1\01-identity\P01-front.glb" "$G1\01-identity\P01-mirror.glb" | Set-Content "$G1\01-identity\check-distinct-mirror.json"
  ```
- **期望结果**：两次都是 HTTP 200，resp 检查 `"ok": true`。EXIF：服务先按 EXIF 纠正方向再推理，所以 exif 结果的 R 不应带约 90° 的整体滚转；【建议】`check-angle-P01-front-exif` 的相对角 < 45°（拍摄时头部姿态本来就有小差别）。镜像：`check-distinct-mirror.json` 为 `"ok": true`（哈希不同，顶点有差异），证明没有复用原图输出
- **证据文件名**：`$G1\01-identity\ID05-*.json/.headers.txt/.status.txt`、`P01-exif.glb`、`P01-mirror.glb`、`check-resp-P01-{exif,mirror}.json`、`check-angle-P01-front-{exif,mirror}.json`、`check-distinct-mirror.json`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛） | 签收 A（宋明耀） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G1-ID-06 源年龄输入语义

- **编号**：G1-ID-06
- **类别**：多身份
- **必选**：是
- **对应验收条款**：G1-C06、G1-C16；〔docs/api.md:30「提供时必须是最长32字符的ASCII普通十进制文本，20—70之间」〕
- **前置条件**：G1-ID-02 通过
- **输入数据**：`P02-front.jpg`
- **逐步操作**：
  ```powershell
  G1-Reconstruct 'data/g1-inputs/P02-front.jpg' 'image/jpeg' "$G1\01-identity\ID06-age35" '35'
  & $PY $CHK resp "$G1\01-identity\ID06-age35.json" --source-age 35 | Set-Content "$G1\01-identity\check-resp-age35.json"
  foreach ($bad in '19','71','abc','1e2') { G1-Reconstruct 'data/g1-inputs/P02-front.jpg' 'image/jpeg' "$G1\01-identity\ID06-age-$bad" $bad }
  ```
- **期望结果**：`age35` 为 HTTP 200，`source_age` 为 `{value:35, method:"user", calibration_id:null}`，`asset_mode` 仍是 static，年龄能力仍是 false。`19`、`71`、`abc`、`1e2` 都是 HTTP 422，`code` 为 `BAD_INPUT`。服务端源码中对应的错误信息是“源年龄必须为 20—70 岁的十进制数值。”
- **证据文件名**：`$G1\01-identity\ID06-*.json/.headers.txt/.status.txt`、`$G1\01-identity\check-resp-age35.json`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛） | 签收 A（宋明耀） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G1-ID-07 框/点/ROI 变换与 EXIF 纠正的单元测试佐证

- **编号**：G1-ID-07
- **类别**：图像方向
- **必选**：是
- **对应验收条款**：G1-C05；〔docs/后续任务清单.md:61「图像方向和框/点/ROI 到原图的变换明确」〕。静态重建的成功响应只有 `{mesh_id, topology_id, asset_mode, capabilities, source_age, shape, expr, pose, texture_url?}`，不含检测框和五点：〔docs/api.md:16「`{mesh_id, topology_id, asset_mode, capabilities, source_age, shape, expr, pose, texture_url?}`」〕，所以这部分从静态接口外部看不到，只能用仓库已有的单元测试佐证
- **前置条件**：开发依赖已安装（`uv ... sync --locked` 默认包含开发组）
- **输入数据**：无（测试在测试目录中自行构造图片，不用真实照片：〔backend/README.md:141「测试只在测试目录中构造图片，不使用真实人物照片或权重」〕）
- **逐步操作**：
  ```powershell
  Push-Location backend
  .\.venv\Scripts\python.exe -m pytest -q `
    "tests/test_detector.py::test_box_and_points_share_letterbox_inverse_without_mirroring" `
    "tests/test_tddfa.py::test_roi_uses_xywh_center_shift_integer_expansion_and_rounded_crop" `
    "tests/test_inputs.py::test_exif_orientation_is_applied_and_removed" *>&1 |
    Out-File -Encoding utf8 "..\$G1\01-identity\pytest-geometry-transforms.txt"
  "exit=$LASTEXITCODE" | Add-Content "..\$G1\01-identity\pytest-geometry-transforms.txt"
  Pop-Location
  ```
  三个测试在 35c0cd6 中的位置：〔backend/tests/test_detector.py:68「def test_box_and_points_share_letterbox_inverse_without_mirroring():」〕〔backend/tests/test_tddfa.py:119「def test_roi_uses_xywh_center_shift_integer_expansion_and_rounded_crop() -> None:」〕〔backend/tests/test_inputs.py:117「def test_exif_orientation_is_applied_and_removed() -> None:」〕
- **期望结果**：退出码 0，输出 `3 passed`（box 上的 35c0cd6 只读克隆在 Linux 实测为 3 passed）。这只证明“框和五点共用同一个 letterbox 逆变换、不镜像”“ROI 按 xywh 中心与整数扩展裁剪”“解码时应用并移除 EXIF 方向”这三项代码行为；是合成测试，**不代替** G1-ID-05 的真实照片观察，也不评价检测精度
- **证据文件名**：`$G1\01-identity\pytest-geometry-transforms.txt`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛） | 签收 A（宋明耀） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### 5.3 正式工作台（生产构建，Chrome 与 Edge）

### 5.3.0 工作台版本说明（`10f1918` 单屏布局与 `35c0cd6` 对照）

本节以下所有工作台步骤按 `10f1918` 编写。`10f1918` 只改主工作台：标记从 `layout.ts` 移到 `frontend/index.html`，研究页、三维查看器、后端未改（`frontend/src/viewer.ts`、`services.ts`、`tests/static-mesh-research.mjs`、`backend/`、`tools/`、`docs/api.md` 在两版间逐字节相同）。桌面布局：〔@10f1918 DESIGN.md:23「布局。桌面（≥1024px）是不滚动的单屏」〕；仓库自带的 e2e 用 1280×720 检查视口、年龄滑块、重建与导出按钮无需滚动：〔@10f1918 frontend/tests/studio.spec.ts:485「笔记本单屏工作台：视口、年龄滑块与主要操作无需滚动」〕。【建议】浏览器窗口不小于 1280×720，截图时不需要滚动；窗口尺寸记进 `notes.md`。

| 项 | `10f1918`（本文步骤，执行提交） | `35c0cd6`（仅作对照，v1.3 起不在此提交执行） |
|---|---|---|
| 打开连接对话框 | 顶栏右侧胶囊按钮“本地演示模式”〔@10f1918 frontend/index.html:26「<span id="connection-label">本地演示模式</span>」〕；对话框“连接本地服务”，按钮“检查并连接”〔@10f1918 frontend/index.html:171「<button id="connect-api" class="button primary">检查并连接</button>」〕；连接成功后无提示 toast | 同一按钮与对话框；连接后另有 toast |
| 选择照片 | 左栏“人像来源”的“选择或拖入照片”〔@10f1918 frontend/index.html:39「选择或拖入照片」〕；选图后才出现“拍摄时年龄”〔@10f1918 frontend/index.html:65「<label for="source-age">拍摄时年龄</label>」〕 | “将人像照片拖放至此”；“照片拍摄时年龄” |
| 授权与重建 | “我已获得该人像的使用授权”〔@10f1918 frontend/index.html:69「我已获得该人像的使用授权」〕；“开始三维重建”〔@10f1918 frontend/index.html:70「开始三维重建」〕；忙碌时按钮文字〔@10f1918 frontend/src/main.ts:191「"正在重建…"」〕，旁边出现“取消”〔@10f1918 frontend/index.html:71「<button id="cancel-reconstruct" class="button quiet" hidden>取消</button>」〕 | “我已获得所选人像的使用授权”；忙碌“正在生成三维模型…”；“取消当前任务” |
| 静态结果状态行 `#source-status` | 〔@10f1918 frontend/src/main.ts:605「"原始重建，年龄变换不可用"」〕（无后缀） | “原始重建，年龄变换不可用。可以旋转查看与导出。” |
| 模型名 | 视口左上 `#info-source` 只显示 mesh_id〔@10f1918 frontend/src/main.ts:588「el("info-source").textContent = meshId;」〕 | `LOCAL MODEL / <mesh_id>`、`STANDARD HEAD / PROCEDURAL` |
| 顶点/三角形数 | 界面不再显示，由 `#viewer` 的属性提供〔@10f1918 frontend/src/main.ts:265「el("viewer").dataset.vertices = String(stats.vertices);」〕；在 F12 控制台读取 | 视口底部 `VERTICES` 读数与右栏“三角面数” |
| 源年龄/目标年龄读数 | 年龄条读数 `#age-output`，未知时显示“未知”、隐藏“岁”〔@10f1918 frontend/src/main.ts:102「el<HTMLOutputElement>("age-output").value = displayAge == null ? "未知" : String(displayAge);」〕；年龄说明 `#age-description` 为“年龄变换不可用”〔@10f1918 frontend/src/main.ts:114「"年龄变换不可用"」〕 | 年龄读数“—”，另有“源年龄 未知”信息栏 |
| 视角按钮 | “正面”“斜侧”“侧面”〔@10f1918 frontend/index.html:96「<button data-view="three-quarter" aria-pressed="false">斜侧</button>」〕；“重置视角”已删 | “正面”“¾ 侧面”“侧面”，另有“重置视角” |
| 年龄控件 | “重置”〔@10f1918 frontend/index.html:120「<button id="age-reset" class="button quiet">重置</button>」〕、“对比”〔@10f1918 frontend/index.html:99「<button id="compare-toggle" class="button push" aria-pressed="false">对比</button>」〕 | “恢复源年龄/恢复至 30 岁”、“年龄对比” |
| 导出 | 右栏“导出 GLB”“导出 PNG”〔@10f1918 frontend/index.html:144「<button id="export-glb" class="button">导出 GLB</button>」〕；文件名规则不变〔@10f1918 frontend/src/main.ts:688「anchor.download = `AgeMorph3D-${provenance}-${suffix}.${format}`;」〕；成功时无提示 | “导出三维模型 GLB”“保存效果图 PNG”；成功提示“静态重建模型已导出，包含来源信息。”〔@35c0cd6 frontend/src/main.ts:754「? "静态重建模型已导出，包含来源信息。"」〕 |
| 回到演示模型 | 左栏底部“载入演示模型”，只在已有本地重建且不忙时出现〔@10f1918 frontend/index.html:73「<button id="load-demo" class="button quiet foot" hidden>载入演示模型</button>」〕；无提示 | “标准人脸模型”卡片；提示“已载入程序化示例，年龄已恢复至 30 岁。” |
| 取消 | 状态行〔@10f1918 frontend/src/main.ts:623「el("source-status").textContent = "重建已取消";」〕，无 toast | “重建已取消，可调整输入后重试。”+ toast“已取消当前重建任务。” |
| 错误显示 | 重建失败时状态行与错误 toast 同文〔@10f1918 frontend/src/main.ts:610「el("source-status").textContent = message(error);」〕〔@10f1918 frontend/src/main.ts:611「notify(message(error), true);」〕；错误 toast 9 秒后自动关闭〔@10f1918 frontend/src/main.ts:57「error ? 9000 : 5500,」〕，前端拒绝（格式、大小、像素、损坏）只有 toast，须在 9 秒内截图 | 状态行与 toast 同样存在 |

### G1-UI-01 Chrome 正式工作台：上传、重建、查看、导出

- **编号**：G1-UI-01
- **类别**：浏览器工作台
- **必选**：是
- **对应验收条款**：G1-C08、G1-C16、G1-C06；〔docs/api.md:87「纯静态结果显示“原始重建，年龄变换不可用”」〕〔@10f1918 frontend/src/main.ts:688「anchor.download = `AgeMorph3D-${provenance}-${suffix}.${format}`;」〕
- **前置条件**：G1-ENV-03 通过，服务以 `--production` 运行（前端 `http://127.0.0.1:4173`）；Chrome 使用访客窗口或无扩展的配置文件（【建议】）；窗口不小于 1280×720（【建议】，见 §5.3.0）；下载目录设为 `$G1\02-ui\chrome\`
- **输入数据**：`P01-front.jpg`；第二轮用 `P03-yawL.jpg` 并填写拍摄时年龄 `42.5`
- **逐步操作**：
  1. 打开 `http://127.0.0.1:4173/`。点击顶栏右侧胶囊按钮“本地演示模式”，在“连接本地服务”对话框中确认“服务地址”为 `http://127.0.0.1:8000`，点击“检查并连接”。截图 `ui-health.png`，按 Esc 关闭对话框。
  2. 在左栏点击“选择或拖入照片”，选择 `P01-front.jpg`；出现的“拍摄时年龄”留空；勾选“我已获得该人像的使用授权”；点击“开始三维重建”。
  3. 完成后截图 `ui-P01-front.png`（单屏，一张即含左栏、视口、年龄条和右栏）；依次点击视口底部的视角按钮“正面”“斜侧”“侧面”，各截一张图（`ui-P01-view-{front,34,side}.png`）。然后按 F12 在控制台执行下面一行，把输出抄进 `notes.md`：
     ```javascript
     [document.getElementById('viewer').dataset.source, document.getElementById('viewer').dataset.vertices, document.getElementById('viewer').dataset.triangles, document.documentElement.scrollHeight <= innerHeight]
     ```
  4. 点击右栏“导出 GLB”和“导出 PNG”，确认下载文件名。
  5. 点击照片右上角“移除照片”（×），选择 `P03-yawL.jpg`，“拍摄时年龄”填 `42.5`，勾选授权后重建，截图 `ui-P03-yawL-age.png`，再导出 GLB。
  6. 在 `notes.md` 中记录：窗口尺寸、各处显示的文字、步骤 3 控制台输出、下载文件名、浏览器控制台是否有错误（F12）。
- **期望结果**：
  - 步骤 1：对话框的状态区显示 `reconstruction=可用`、`age_morph=不可用`、`age_texture=不可用`、`realtime=可用`，detector 和 reconstructor 都是 `state=ready`；顶栏胶囊变为“本地服务已连接”。
  - 步骤 2–3：左栏状态行为“原始重建，年龄变换不可用”；徽标为“本地重建”；徽标旁 `#info-source` 显示本次 mesh_id（32 位十六进制）；控制台输出为 `["reconstruction", "38365", "76073", true/false]`（最后一项只记录单屏是否无需滚动，不影响判定）；年龄条读数为“未知”且不显示“岁”；年龄滑块、年龄刻度按钮 20—70、“重置”和“对比”都不可点；右栏“生成年龄纹理”不可点；年龄说明为“年龄变换不可用”；页面上任何地方都不出现把这个真实模型标成 30 岁的文字（R11“不显示虚构30岁”）。三个视角都能看到开放的面部网格。
  - 步骤 4：下载文件名为 `AgeMorph3D-local-original.glb` 和 `AgeMorph3D-local-original.png`；`10f1918` 导出成功时不弹提示，不得出现错误 toast。
  - 步骤 5：年龄条读数为 `42.5` 且显示“岁”，仍不能调节年龄；导出文件名仍含 `original`。
  - 控制台没有未捕获的错误。
- **证据文件名**：`$G1\02-ui\chrome\ui-health.png`、`ui-P01-front.png`、`ui-P01-view-{front,34,side}.png`、`ui-P03-yawL-age.png`、`AgeMorph3D-local-original.glb`（第二个导出改名为 `AgeMorph3D-local-original-P03-yawL.glb`）、`AgeMorph3D-local-original.png`、`notes.md`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛） | 签收 A（宋明耀） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G1-UI-02 Edge 正式工作台：上传、重建、查看、导出

- **编号**：G1-UI-02
- **类别**：浏览器工作台
- **必选**：是
- **对应验收条款**：G1-C08、G1-C16、G1-C06；〔docs/后续任务清单.md:63「真实照片在 Chrome/Edge 加载导出再导入」〕
- **前置条件**：同 G1-UI-01，浏览器换成 Edge，下载目录设为 `$G1\02-ui\edge\`
- **输入数据**：`P02-front.jpg`；第二轮用 `P01-yawR.jpg`，年龄 `42.5`
- **逐步操作**：与 G1-UI-01 的步骤 1–6 相同，证据存进 `edge\`。
- **期望结果**：与 G1-UI-01 的全部期望相同。
- **证据文件名**：`$G1\02-ui\edge\ui-health.png`、`ui-P02-front.png`、`ui-P02-view-{front,34,side}.png`、`ui-P01-yawR-age.png`、`AgeMorph3D-local-original.glb`、`AgeMorph3D-local-original-P01-yawR.glb`、`AgeMorph3D-local-original.png`、`notes.md`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛） | 签收 A（宋明耀） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G1-UI-03 演示回归

- **编号**：G1-UI-03
- **类别**：演示回归
- **必选**：是
- **对应验收条款**：G1-C17；加载失败时不能把演示网格当作真实结果：〔docs/api.md:85「不能将演示网格当作本次真实重建结果」〕
- **前置条件**：G1-UI-01 或 G1-UI-02 已完成，页面保持打开
- **输入数据**：无
- **逐步操作**：（Chrome 和 Edge 各做一次）
  1. 点击左栏底部“载入演示模型”（只在已有本地重建时出现）。
  2. 拖动年龄滑块到 50，再点“重置”；点击右栏“导出 GLB”。
  3. 照片仍是 `P01-front.jpg`（`10f1918` 载入演示模型不清除照片；如已移除则重新选择），确认已勾选授权，点击“开始三维重建”，确认能回到真实结果。
- **期望结果**：步骤 1 后徽标变回“演示模型”，`#info-source` 为空，年龄条读数为 `30` 并显示“岁”，“载入演示模型”按钮消失（`10f1918` 不弹提示）；步骤 2 中年龄滑块可用，“重置”后读数回到 `30`（演示模型没有源年龄，重置值为 30：〔@10f1918 frontend/src/main.ts:314「on("age-reset", "click", () => changeAge(reconstruction?.source_age.value ?? 30));」〕），导出文件名为 `AgeMorph3D-demo-age30.glb`（【推断】由 `main.ts` 的命名规则推出：演示来源为 `demo`，非静态时后缀为 `age<年龄>`）；步骤 3 重新得到“本地重建”结果，表现与 G1-UI-01 相同
- **证据文件名**：`$G1\02-ui\{chrome,edge}\ui-demo.png`、`AgeMorph3D-demo-age30.glb`、`ui-demo-back-to-real.png`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛） | 签收 A（宋明耀） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### 5.4 无人脸、多人脸与坏图

所有错误都应是应用层 JSON `{"detail": …, "code": …}`：〔docs/api.md:141「应用层HTTP错误响应为`{"detail":"可读说明","code":"稳定错误码"}`」〕。状态码与错误码的对应关系见〔docs/api.md:141「400坏图/坏multipart、403来源或Host拒绝、404资产不存在、413超限、415格式不支持、422字段无效或无人/多人、429忙、503模型未就绪、504超时」〕。工作台把服务端错误显示成“本地服务请求失败（HTTP 状态码）：detail”：〔frontend/src/services.ts:369「`本地服务请求失败（HTTP ${response.status}）${explanation}`,」〕。每次失败之后都要做一次恢复请求，以 HTTP 200 证明服务不用重启就能继续：〔docs/B23真实静态链路开发记录.md:7「失败后可以重新提交」〕。

### G1-NF-01 无人脸（命令行与工作台）

- **编号**：G1-NF-01
- **类别**：无人脸
- **必选**：是
- **对应验收条款**：G1-C10；〔backend/src/agemorph3d/reconstruction.py:26「raise ApiError(422, "NO_FACE", "未检测到人脸，请使用清晰的单人照片。")」〕
- **前置条件**：G1-ENV-03 通过
- **输入数据**：`NF-scene.jpg`（本人拍摄的无人场景）、`NF-blank.png`（纯灰图）
- **逐步操作**：
  ```powershell
  G1-Reconstruct 'data/g1-inputs/NF-scene.jpg' 'image/jpeg' "$G1\04-errors\NF-scene"
  G1-Reconstruct 'data/g1-inputs/NF-blank.png' 'image/png' "$G1\04-errors\NF-blank"
  G1-Reconstruct 'data/g1-inputs/P01-front.jpg' 'image/jpeg' "$G1\04-errors\recover-NF"
  ```
  然后在 Chrome 工作台选择 `NF-scene.jpg`、勾选授权并重建，在 9 秒内截图（错误 toast 9 秒后自动关闭，状态行文字保留）；接着点“移除照片”，换成 `P01-front.jpg` 重建，截图。
- **期望结果**：两次都是 HTTP 422，`code` 为 `NO_FACE`，响应头带 `Cache-Control: no-store`；`recover-NF` 为 HTTP 200。工作台左栏状态行和错误 toast 都是“本地服务请求失败（HTTP 422）：未检测到人脸，请使用清晰的单人照片。”（前端把服务端 detail 拼在 HTTP 状态码后面），徽标保持“演示模型”、不切换成“本地重建”，也不把演示模型当结果；随后的 P01 重建成功
- **证据文件名**：`$G1\04-errors\NF-scene.*`、`NF-blank.*`、`recover-NF.*`、`$G1\02-ui\chrome\ui-NF.png`、`ui-NF-recover.png`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛） | 签收 A（宋明耀） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G1-MF-01 多人脸（命令行与工作台）

- **编号**：G1-MF-01
- **类别**：多人脸
- **必选**：是
- **对应验收条款**：G1-C11；〔backend/src/agemorph3d/reconstruction.py:28「raise ApiError(422, "MULTI_FACE", "检测到多张人脸，请上传只有一人的照片。")」〕
- **前置条件**：G1-ENV-03 通过
- **输入数据**：`MF-two.jpg`（P01 与 P02 同框，两人均已同意）
- **逐步操作**：
  ```powershell
  G1-Reconstruct 'data/g1-inputs/MF-two.jpg' 'image/jpeg' "$G1\04-errors\MF-two"
  G1-Reconstruct 'data/g1-inputs/P02-front.jpg' 'image/jpeg' "$G1\04-errors\recover-MF"
  ```
  在 Edge 工作台选择 `MF-two.jpg`、勾选授权并重建，9 秒内截图；再点“移除照片”换成 `P02-front.jpg` 重建并截图。
- **期望结果**：HTTP 422，`code` 为 `MULTI_FACE`；`recover-MF` 为 HTTP 200；工作台左栏状态行和错误 toast 都是“本地服务请求失败（HTTP 422）：检测到多张人脸，请上传只有一人的照片。”，徽标保持“演示模型”，随后的重建成功
- **证据文件名**：`$G1\04-errors\MF-two.*`、`recover-MF.*`、`$G1\02-ui\edge\ui-MF.png`、`ui-MF-recover.png`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛） | 签收 A（宋明耀） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G1-BAD-01 损坏文件与空文件

- **编号**：G1-BAD-01
- **类别**：坏图
- **必选**：是
- **对应验收条款**：G1-C12；〔backend/src/agemorph3d/images.py:61「raise ApiError(400, "BAD_INPUT", "图片已损坏或无法解码。") from error」〕〔backend/src/agemorph3d/images.py:23「raise ApiError(400, "BAD_INPUT", "图片内容不能为空。")」〕
- **前置条件**：G1-ENV-03 通过
- **输入数据**：`BAD-truncated.jpg`、`BAD-empty.jpg`
- **逐步操作**：
  ```powershell
  G1-Reconstruct 'data/g1-inputs/BAD-truncated.jpg' 'image/jpeg' "$G1\04-errors\BAD-truncated"
  G1-Reconstruct 'data/g1-inputs/BAD-empty.jpg' 'image/jpeg' "$G1\04-errors\BAD-empty"
  G1-Reconstruct 'data/g1-inputs/P01-front.jpg' 'image/jpeg' "$G1\04-errors\recover-BAD01"
  ```
- **期望结果**：两次都是 HTTP 400，`code` 为 `BAD_INPUT`（截断文件【推断】走“图片已损坏或无法解码。”这条路径；空文件为“图片内容不能为空。”，如果 multipart 解析层先拒绝，也是 400 `BAD_INPUT`，照实记录 detail）；`recover-BAD01` 为 HTTP 200
- **证据文件名**：`$G1\04-errors\BAD-truncated.*`、`BAD-empty.*`、`recover-BAD01.*`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛） | 签收 A（宋明耀） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G1-BAD-02 不支持的格式与声明不一致

- **编号**：G1-BAD-02
- **类别**：坏图
- **必选**：是
- **对应验收条款**：G1-C12；〔backend/src/agemorph3d/images.py:42「415, "UNSUPPORTED_MEDIA_TYPE", "图片实际格式与声明的媒体类型不一致。"」〕
- **前置条件**：G1-ENV-03 通过
- **输入数据**：`BAD-format.gif`、`BAD-mismatch.png`
- **逐步操作**：
  ```powershell
  G1-Reconstruct 'data/g1-inputs/BAD-format.gif' 'image/gif' "$G1\04-errors\BAD-gif"
  G1-Reconstruct 'data/g1-inputs/BAD-mismatch.png' 'image/jpeg' "$G1\04-errors\BAD-mismatch"
  G1-Reconstruct 'data/g1-inputs/P01-front.jpg' 'image/jpeg' "$G1\04-errors\recover-BAD02"
  ```
  再在 Chrome 工作台点“选择或拖入照片”，尝试选择 `BAD-format.gif`（文件对话框里切到“所有文件”），9 秒内截图。
- **期望结果**：`BAD-gif` 为 HTTP 415，`code` 为 `UNSUPPORTED_MEDIA_TYPE`，信息为“仅支持 JPEG、PNG 或 WebP 图片。”；`BAD-mismatch` 为 HTTP 415，`code` 为 `UNSUPPORTED_MEDIA_TYPE`，信息为“图片实际格式与声明的媒体类型不一致。”；恢复请求为 HTTP 200。工作台在前端就拒绝 GIF，错误 toast 为“请选择不超过 10 MB 的 JPG、PNG 或 WebP 图片。”〔@10f1918 frontend/src/main.ts:387「notify("请选择不超过 10 MB 的 JPG、PNG 或 WebP 图片。", true);」〕，照片区保持原状
- **证据文件名**：`$G1\04-errors\BAD-gif.*`、`BAD-mismatch.*`、`recover-BAD02.*`、`$G1\02-ui\chrome\ui-BAD-gif.png`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛） | 签收 A（宋明耀） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G1-BAD-03 超过字节上限

- **编号**：G1-BAD-03
- **类别**：坏图
- **必选**：是
- **对应验收条款**：G1-C12；〔backend/src/agemorph3d/middleware.py:149「code = {413: "PAYLOAD_TOO_LARGE", 504: "TIMEOUT"}.get(status, "BAD_INPUT")」〕
- **前置条件**：G1-ENV-03 通过
- **输入数据**：`BAD-oversize.jpg`（约 11 MiB 以上，超过“图片上限 + 64 KiB”的请求上限）
- **逐步操作**：
  ```powershell
  G1-Reconstruct 'data/g1-inputs/BAD-oversize.jpg' 'image/jpeg' "$G1\04-errors\BAD-oversize"
  G1-Reconstruct 'data/g1-inputs/P01-front.jpg' 'image/jpeg' "$G1\04-errors\recover-BAD03"
  ```
  再在 Edge 工作台选择 `BAD-oversize.jpg`，9 秒内截图。
- **期望结果**：HTTP 413，`code` 为 `PAYLOAD_TOO_LARGE`，信息为“请求内容超过大小限制。”；恢复请求为 HTTP 200；工作台在前端拒绝，错误 toast 为“请选择不超过 10 MB 的 JPG、PNG 或 WebP 图片。”，照片区保持原状
- **证据文件名**：`$G1\04-errors\BAD-oversize.*`、`recover-BAD03.*`、`$G1\02-ui\edge\ui-BAD-oversize.png`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛） | 签收 A（宋明耀） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G1-BAD-04 超过像素上限

- **编号**：G1-BAD-04
- **类别**：坏图
- **必选**：是
- **对应验收条款**：G1-C12；〔backend/src/agemorph3d/images.py:48「raise ApiError(413, "INPUT_TOO_LARGE", "图片像素总量超过限制。")」〕〔@10f1918 frontend/src/main.ts:398「throw new Error("图片像素过大，请缩小到 1600 万像素以内再上传。");」〕
- **前置条件**：G1-ENV-03 通过
- **输入数据**：`BAD-pixels.png`（4200×4100，约 1722 万像素，文件很小）
- **逐步操作**：
  ```powershell
  G1-Reconstruct 'data/g1-inputs/BAD-pixels.png' 'image/png' "$G1\04-errors\BAD-pixels"
  G1-Reconstruct 'data/g1-inputs/P01-front.jpg' 'image/jpeg' "$G1\04-errors\recover-BAD04"
  ```
  再在 Chrome 工作台选择 `BAD-pixels.png`，9 秒内截图。
- **期望结果**：HTTP 413，`code` 为 `INPUT_TOO_LARGE`，信息为“图片像素总量超过限制。”；恢复请求为 HTTP 200；工作台错误 toast 为“图片像素过大，请缩小到 1600 万像素以内再上传。”，照片区保持原状
- **证据文件名**：`$G1\04-errors\BAD-pixels.*`、`recover-BAD04.*`、`$G1\02-ui\chrome\ui-BAD-pixels.png`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛） | 签收 A（宋明耀） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G1-BAD-05 动画图片

- **编号**：G1-BAD-05
- **类别**：坏图
- **必选**：是
- **对应验收条款**：G1-C12；〔backend/src/agemorph3d/images.py:52「raise ApiError(400, "BAD_INPUT", "不支持动画图片。")」〕
- **前置条件**：G1-ENV-03 通过
- **输入数据**：`BAD-anim.webp`（两帧动画 WebP）
- **逐步操作**：
  ```powershell
  G1-Reconstruct 'data/g1-inputs/BAD-anim.webp' 'image/webp' "$G1\04-errors\BAD-anim"
  G1-Reconstruct 'data/g1-inputs/P01-front.jpg' 'image/jpeg' "$G1\04-errors\recover-BAD05"
  ```
- **期望结果**：HTTP 400，`code` 为 `BAD_INPUT`，信息为“不支持动画图片。”；恢复请求为 HTTP 200
- **证据文件名**：`$G1\04-errors\BAD-anim.*`、`recover-BAD05.*`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛） | 签收 A（宋明耀） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G1-BAD-06 工作台损坏文件

- **编号**：G1-BAD-06
- **类别**：坏图
- **必选**：是
- **对应验收条款**：G1-C12；〔@10f1918 frontend/src/main.ts:417「? "无法读取这张图片，请检查文件是否损坏。"」〕
- **前置条件**：工作台已连接服务
- **输入数据**：`BAD-truncated.jpg`
- **逐步操作**：（Chrome、Edge 各一次）点“选择或拖入照片”，选择 `BAD-truncated.jpg`，9 秒内截图；然后选择 `P01-front.jpg` 并重建。
- **期望结果**：前端错误 toast 为“无法读取这张图片，请检查文件是否损坏。”（【推断】浏览器如果能部分解码截断的 JPEG，这张图会进入准备区；这时重建应得到服务端 400 `BAD_INPUT`，左栏状态行与错误 toast 为“本地服务请求失败（HTTP 400）：图片已损坏或无法解码。”。两种结果都算正确拒绝，照实记录是哪一种）；随后 P01 重建成功
- **证据文件名**：`$G1\02-ui\{chrome,edge}\ui-BAD-truncated.png`、`ui-BAD-truncated-recover.png`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛） | 签收 A（宋明耀） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### 5.5 导出再导入

已知限制：〔docs/B23真实静态链路开发记录.md:75「UI当前没有独立GLB文件导入控件」〕。因此再导入使用仓库已有的研究脚本 `frontend/tests/static-mesh-research.mjs`。它用实际的 FaceViewer 和 GLTFLoader，在 Chrome 和 Edge 中依次完成加载、导出、再导入：〔frontend/tests/static-mesh-research.mjs:173「for (const channel of ["chrome", "msedge"]) {」〕；位置、法线、UV 的差异超过 1e-6 即失败：〔frontend/tests/static-mesh-research.mjs:378「if (maximumDifference > 1e-6) throw new Error(`Roundtrip changed ${name} values.`);」〕；导出文件不得出现年龄字段：〔frontend/tests/static-mesh-research.mjs:264「for (const key of ["age", "ageAnchors", "displayAge", "texture_age"])」〕。输出目录由环境变量指定：〔frontend/tests/static-mesh-research.mjs:13「const output = resolve(process.env.AGEMORPH_RESEARCH_OUTPUT ??」〕。脚本占用 5175 和 18003 端口，报告固定写 `serviceInferenceVerified=false` 和 `g1Accepted=false`；这两个值说的是脚本本身不连接模型服务，**输入 GLB 来自严格服务这一点由本节用例的前置步骤保证**。

### G1-EXP-01 严格服务 GLB 双浏览器往返

- **编号**：G1-EXP-01
- **类别**：导出再导入
- **必选**：是
- **对应验收条款**：G1-C09、G1-C07；〔docs/验收矩阵.md:46「导出再导入」〕
- **前置条件**：G1-ID-02 已产出 `P01-front.glb` 和 `ID02-P01-front.json`（都来自严格服务）；本机已安装 Chrome 和 Edge；`frontend/node_modules` 已由 `npm ci` 安装；5175、18003 端口空闲
- **输入数据**：`$G1\01-identity\P01-front.glb`、`$G1\01-identity\ID02-P01-front.json`；另取一个侧脸结果 `P02-yawL.glb` 和 `ID03-P02-yawL.json`
- **逐步操作**：
  ```powershell
  foreach ($x in @(@('P01-front','ID02-P01-front'), @('P02-yawL','ID03-P02-yawL'))) {
    $env:AGEMORPH_RESEARCH_MESH   = (Resolve-Path "$G1\01-identity\$($x[0]).glb").Path
    $env:AGEMORPH_RESEARCH_RESULT = (Resolve-Path "$G1\01-identity\$($x[1]).json").Path
    $env:AGEMORPH_RESEARCH_OUTPUT = (New-Item -ItemType Directory -Force "$G1\03-export\roundtrip-$($x[0])").FullName
    Push-Location frontend; & node tests/static-mesh-research.mjs *>&1 | Out-File -Encoding utf8 "$env:AGEMORPH_RESEARCH_OUTPUT\console.txt"; "exit=$LASTEXITCODE" | Add-Content "$env:AGEMORPH_RESEARCH_OUTPUT\console.txt"; Pop-Location
  }
  Remove-Item Env:AGEMORPH_RESEARCH_MESH, Env:AGEMORPH_RESEARCH_RESULT, Env:AGEMORPH_RESEARCH_OUTPUT
  ```
  （Node 不在 PATH 时，把 `node` 换成 `& $env:AGEMORPH_NODE`。）
- **期望结果**：两次退出码都是 0；每个 `static-mesh-research.json` 中 `status` 为 `passed`，`results` 有 chrome 和 msedge 两项，各自 `status` 为 `passed`，`vertices=38365`、`triangles=76073`，位置和法线的 `maximumDifference` ≤ 1e-6（脚本内置）；`rootExtras.asset_mode=static`，不含年龄字段；`externalRequests` 为空；`ownedServersClosed=true`；`input.sha256` 等于 `G1-ID-02`/`G1-ID-03` 中对应 GLB 的 SHA-256；每个浏览器都有正面、侧面和再导入截图
- **证据文件名**：`$G1\03-export\roundtrip-P01-front\static-mesh-research.json`、`console.txt`、`exported-chrome.glb`、`exported-msedge.glb`、`original-front-*.png`、`original-side-*.png`、`reimport-front-*.png`；`roundtrip-P02-yawL\` 下的同名文件
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛） | 签收 A（宋明耀） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G1-EXP-02 工作台导出文件的再导入

- **编号**：G1-EXP-02
- **类别**：导出再导入
- **必选**：是
- **对应验收条款**：G1-C09、G1-C16；〔docs/后续任务清单.md:63「真实照片在 Chrome/Edge 加载导出再导入」〕
- **前置条件**：G1-UI-01 和 G1-UI-02 已下载 `AgeMorph3D-local-original.glb`
- **输入数据**：`$G1\02-ui\chrome\AgeMorph3D-local-original.glb`（来自 P01-front）、`$G1\02-ui\edge\AgeMorph3D-local-original.glb`（来自 P02-front），以及各自的重建响应 `ID02-P01-front.json`、`ID02-P02-front.json` 作为元数据【推断：工作台中这两次重建的 topology_id 和 source_age 与命令行的同一张照片一致；mesh_id 不同不影响脚本】
- **逐步操作**：
  1. 结构检查：
     ```powershell
     & $PY $CHK glb "$G1\02-ui\chrome\AgeMorph3D-local-original.glb" --kind viewer --response "$G1\01-identity\ID02-P01-front.json" | Set-Content "$G1\03-export\check-viewer-chrome.json"
     & $PY $CHK glb "$G1\02-ui\edge\AgeMorph3D-local-original.glb" --kind viewer --response "$G1\01-identity\ID02-P02-front.json" | Set-Content "$G1\03-export\check-viewer-edge.json"
     ```
  2. 再导入往返：照 G1-EXP-01 的命令执行，把 `AGEMORPH_RESEARCH_MESH` 换成上述两个工作台导出文件，输出目录分别为 `roundtrip-ui-chrome`、`roundtrip-ui-edge`。
- **期望结果**：步骤 1 两份检查都是 `"ok": true`：存在名为 `AgeMorph3D_Loaded_Model` 的根节点（脚本以同名节点判断工作台导出：〔frontend/tests/static-mesh-research.mjs:259「const root = exportJson.nodes?.find((node) => node.name === "AgeMorph3D_Loaded_Model");」〕），其 extras 中 `asset_mode=static`，`topology_id` 和 `source_age` 与响应一致，不含年龄字段；38365 个顶点、76073 个三角形；无 morph target；单一内嵌 buffer。步骤 2 的期望与 G1-EXP-01 相同。【推断】研究脚本此前只用服务端 GLB 跑过，没有用工作台导出件跑过；如果脚本因输入格式拒绝（不是因为数值不一致），本例记为“阻塞”并交 §8 Q-4，**不改脚本、不当作通过**
- **证据文件名**：`$G1\03-export\check-viewer-chrome.json`、`check-viewer-edge.json`、`roundtrip-ui-chrome\`、`roundtrip-ui-edge\`（文件同 G1-EXP-01）
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛） | 签收 A（宋明耀） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### 5.6 取消

关于取消的实际语义：〔docs/B23真实静态链路开发记录.md:29「已观测到的断开以499/CANCELLED终结」〕；原生算子会一直运行到结束，期间工作槽保持忙：〔docs/B23真实静态链路开发记录.md:29「工作槽在此之前保持忙状态」〕。因此取消后立刻再提交，可能先得到 429 `BUSY`（带 `Retry-After: 1`），这是合同规定的行为，**不算失败**：〔docs/api.md:141「忙时带`Retry-After: 1`」〕。

### G1-CAN-01 工作台取消并恢复

- **编号**：G1-CAN-01
- **类别**：取消
- **必选**：是
- **对应验收条款**：G1-C13；〔@10f1918 frontend/src/main.ts:623「el("source-status").textContent = "重建已取消";」〕
- **前置条件**：G1-UI-01 通过；Chrome 开发者工具 → Network → 节流选 “Slow 3G”（【建议】，用来拉长上传时间，方便点击取消）
- **输入数据**：`P01-large.jpg`
- **逐步操作**：（Chrome 做一次；Edge 【建议】再做一次）
  1. 选择 `P01-large.jpg`，勾选授权，点击“开始三维重建”；按钮变成“正在重建…”、下方出现“取消”时，点击“取消”。
  2. 立即截图；然后等 15 秒（【建议】，超过一次正常重建的耗时），再截图。
  3. 关闭节流，用 `P01-front.jpg` 重新重建；如果提示资源忙，按提示等待后重试。
  4. 记下 `output/local-run/backend.log` 末尾与这次请求有关的行（只记状态码，不复制其他内容）。
- **期望结果**：步骤 1–2：左栏状态行为“重建已取消”（`10f1918` 取消时不弹 toast），“取消”按钮消失；视口为演示模型（徽标“演示模型”，`#info-source` 为空）；等待 15 秒后**仍然是演示模型**，不会被迟到的结果替换。步骤 3：重建成功（中间允许出现一次资源忙的错误提示）。步骤 4 为辅助记录：【推断】如果请求体已经上传完，日志中会出现 499；如果上传中途取消，可能看不到 499。两种情况都不影响判定
- **证据文件名**：`$G1\05-cancel\ui-cancel-chrome.png`、`ui-cancel-chrome-15s.png`、`ui-cancel-recover-chrome.png`（Edge 同名改 `edge`）、`$G1\05-cancel\backend-log-cancel.txt`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛） | 签收 A（宋明耀） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G1-CAN-02 推理中途断开连接（命令行）

- **编号**：G1-CAN-02
- **类别**：取消
- **必选**：是
- **对应验收条款**：G1-C13；〔backend/src/agemorph3d/app.py:195「raise ApiError(499, "CANCELLED", "请求连接已断开，请重新提交。")」〕
- **前置条件**：G1-ENV-03 通过；已知本机正常重建一次的耗时（看 G1-ID-02 的执行时间，或先 `Measure-Command { G1-Reconstruct ... }`）
- **输入数据**：`P01-large.jpg`
- **逐步操作**：
  ```powershell
  $t = 0.3   # 取本机正常耗时的一半左右；如果 curl 在超时前拿到了 200，就缩短后重做
  curl.exe -sS -o "$G1\05-cancel\cancel-cli.json" -w '%{http_code}' --max-time $t -F "image=@data/g1-inputs/P01-large.jpg;type=image/jpeg" "$API/api/reconstruct" *>&1 | Out-File -Encoding utf8 "$G1\05-cancel\cancel-cli.txt"
  "curl_exit=$LASTEXITCODE" | Add-Content "$G1\05-cancel\cancel-cli.txt"
  curl.exe -sS -o "$G1\05-cancel\health-after-cancel.json" "$API/api/health"
  for ($i = 1; $i -le 30; $i++) {
    G1-Reconstruct 'data/g1-inputs/P01-front.jpg' 'image/jpeg' "$G1\05-cancel\retry-$i"
    if ((Get-Content "$G1\05-cancel\retry-$i.status.txt") -eq '200') { break }
    Start-Sleep -Seconds 1
  }
  ```
- **期望结果**：`cancel-cli.txt` 中 curl 退出码为 28（超时），没有得到 200 和 mesh_id；`health-after-cancel.json` 中两个模型仍为 `ready`；重试序列最终得到 HTTP 200，【建议】在 30 次（约 30 秒）以内；中间只允许出现 429 `BUSY`（响应头带 `Retry-After: 1`），不允许 5xx。如果 curl 在超时前就拿到了 200，说明这次没有测到取消，缩短 `$t` 重做，不能记为通过
- **证据文件名**：`$G1\05-cancel\cancel-cli.txt`、`health-after-cancel.json`、`retry-*.json/.headers.txt/.status.txt`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛） | 签收 A（宋明耀） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G1-CAN-03 “不发布迟到结果”的自动化佐证

- **编号**：G1-CAN-03
- **类别**：取消
- **必选**：是
- **对应验收条款**：G1-C13、G1-C14；〔backend/README.md:145「`test_static_mesh.py`、`test_asset_cache.py`、`test_static_api.py`、`test_static_probe.py` 覆盖本轮几何、GLB、TTL/LRU/租约、成功接口、断开/取消/超时/关闭及独立研究路径」〕
- **前置条件**：开发依赖已安装
- **输入数据**：无（测试用合成夹具，不用照片）
- **逐步操作**：
  ```powershell
  Push-Location backend
  .\.venv\Scripts\python.exe -m pytest -q tests/test_static_api.py tests/test_asset_cache.py tests/test_runtime.py *>&1 | Out-File -Encoding utf8 "..\$G1\05-cancel\pytest-static.txt"
  "exit=$LASTEXITCODE" | Add-Content "..\$G1\05-cancel\pytest-static.txt"
  Pop-Location
  ```
- **期望结果**：退出码 0，没有失败项。说明：服务端没有接口可以列出缓存里的资产，所以“取消后没有发布迟到网格”无法从外部直接观察。本例只用合成测试佐证服务端行为，**不代替** G1-CAN-01/02 的真实观察，也不算真实模型证据
- **证据文件名**：`$G1\05-cancel\pytest-static.txt`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛） | 签收 A（宋明耀） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### 5.7 过期与坏资产

缓存 TTL 由环境变量设置：〔backend/README.md:123「缓存配置为 `AGEMORPH_ASSET_TTL_SECONDS`、`AGEMORPH_ASSET_MAX_BYTES` 和 `AGEMORPH_ASSET_MAX_ENTRIES`」〕；代码中读取该变量：〔backend/src/agemorph3d/config.py:109「("asset_ttl_seconds", "AGEMORPH_ASSET_TTL_SECONDS", float),」〕。启动器把当前环境原样传给后端子进程：〔tools/local_run.py:912「env = {key: value for key, value in os.environ.items() if "\0" not in key and "\0" not in value}」〕。过期资产返回〔backend/src/agemorph3d/runtime.py:122「raise ApiError(404, "ASSET_NOT_FOUND", "模型资产不存在或已过期，请重新重建。") from None」〕。**本节用完后必须删除该环境变量并重启服务，恢复默认 1800 秒**。

### G1-EXPIRE-01 TTL 过期、访问不续期、重新重建恢复

- **编号**：G1-EXPIRE-01
- **类别**：过期
- **必选**：是
- **对应验收条款**：G1-C14；〔docs/B23真实静态链路开发记录.md:25「TTL从发布时开始，访问不续期」〕
- **前置条件**：G1-ID-02 通过
- **输入数据**：`P01-front.jpg`
- **逐步操作**：
  ```powershell
  .\tools\local-run.ps1 stop
  $env:AGEMORPH_ASSET_TTL_SECONDS = '30'
  .\tools\local-run.ps1 start --production --detector-manifest $DET --reconstructor-manifest $REC
  # 等健康检查显示两个模型 ready 后：
  G1-Reconstruct 'data/g1-inputs/P01-front.jpg' 'image/jpeg' "$G1\06-expiry\ttl-src"; $t0 = Get-Date
  Start-Sleep 10; G1-Fetch "$G1\06-expiry\ttl-src.json" "$G1\06-expiry\ttl-10s.glb"
  Start-Sleep 15; G1-Fetch "$G1\06-expiry\ttl-src.json" "$G1\06-expiry\ttl-25s.glb"
  Start-Sleep 12; G1-Fetch "$G1\06-expiry\ttl-src.json" "$G1\06-expiry\ttl-37s.glb"
  "elapsed_s=$(((Get-Date) - $t0).TotalSeconds)" | Set-Content "$G1\06-expiry\ttl-timing.txt"
  G1-Reconstruct 'data/g1-inputs/P01-front.jpg' 'image/jpeg' "$G1\06-expiry\ttl-recover"
  G1-Fetch "$G1\06-expiry\ttl-recover.json" "$G1\06-expiry\ttl-recover.glb"
  ```
- **期望结果**：`ttl-10s`、`ttl-25s` 为 HTTP 200；`ttl-37s` 为 HTTP 404，`code` 为 `ASSET_NOT_FOUND`。第 25 秒的读取没有把有效期延长到第 55 秒，这就证明“访问不续期”。`ttl-recover` 得到新的 mesh_id（与 `ttl-src` 不同），读取为 HTTP 200。各次读取的实际时间以 `ttl-timing.txt` 和 `.headers.txt` 中的 `date` 头为准；如果因为机器慢导致时间点偏离超过 2 秒，照实记录并重做
- **证据文件名**：`$G1\06-expiry\ttl-src.*`、`ttl-10s.glb.*`、`ttl-25s.glb.*`、`ttl-37s.glb.*`、`ttl-timing.txt`、`ttl-recover.*`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛） | 签收 A（宋明耀） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G1-EXPIRE-02 工作台中资产过期（坏资产）可恢复

- **编号**：G1-EXPIRE-02
- **类别**：坏资产
- **必选**：是
- **对应验收条款**：G1-C14、G1-C15；〔docs/后续任务清单.md:63「过期/取消/坏资产可恢复」〕
- **前置条件**：G1-EXPIRE-01 完成
- **输入数据**：`P02-front.jpg`
- **逐步操作**：
  1. 用极短的 TTL 重启，让资产几乎在发布的同时过期，工作台随后读取 GLB 时就会拿到 404：
     ```powershell
     .\tools\local-run.ps1 stop
     $env:AGEMORPH_ASSET_TTL_SECONDS = '0.001'
     .\tools\local-run.ps1 start --production --detector-manifest $DET --reconstructor-manifest $REC
     ```
  2. Chrome 工作台重新连接（顶栏胶囊 →“检查并连接”），选择 `P02-front.jpg`、勾选授权并重建，9 秒内截图。
  3. 恢复默认 TTL 并重启：
     ```powershell
     .\tools\local-run.ps1 stop
     Remove-Item Env:AGEMORPH_ASSET_TTL_SECONDS
     .\tools\local-run.ps1 start --production --detector-manifest $DET --reconstructor-manifest $REC
     ```
  4. 工作台重新连接后再重建 `P02-front.jpg`，截图。
- **期望结果**：步骤 2：工作台明确显示加载失败（左栏状态行与错误 toast，照实记录提示文字），徽标**不变成**“本地重建”，也不把演示模型当成这次的结果。按接口文档，加载失败应明确显示错误：〔docs/api.md:85「加载失败应明确显示错误」〕。【推断】TTL 为 0.001 秒时资产会在浏览器读取前过期；如果仍然加载成功，说明这个时机没触发，记为“阻塞”并交 §8 Q-5，不算通过。步骤 4：重建成功，表现与 G1-UI-01 相同
- **证据文件名**：`$G1\06-expiry\ui-expired-chrome.png`、`ui-expired-recover-chrome.png`、`notes-expiry.md`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛） | 签收 A（宋明耀） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G1-EXPIRE-03 重启后旧 ID 失效与未知 ID

- **编号**：G1-EXPIRE-03
- **类别**：过期
- **必选**：是
- **对应验收条款**：G1-C14、G1-C15；〔docs/B23真实静态链路开发记录.md:25「过期/未知/淘汰/重启后的ID为404」〕
- **前置条件**：服务以默认 TTL 运行（G1-EXPIRE-02 步骤 3 之后）
- **输入数据**：`P03-front.jpg`
- **逐步操作**：
  ```powershell
  G1-Reconstruct 'data/g1-inputs/P03-front.jpg' 'image/jpeg' "$G1\06-expiry\restart-src"
  G1-Fetch "$G1\06-expiry\restart-src.json" "$G1\06-expiry\restart-before.glb"
  .\tools\local-run.ps1 stop
  .\tools\local-run.ps1 start --production --detector-manifest $DET --reconstructor-manifest $REC
  # 等两个模型 ready 后：
  G1-Fetch "$G1\06-expiry\restart-src.json" "$G1\06-expiry\restart-after.glb"
  $u = & curl.exe -sS -o "$G1\06-expiry\unknown-id.json" -w '%{http_code}' "$API/api/assets/00000000000000000000000000000000/mesh.glb"; Set-Content "$G1\06-expiry\unknown-id.status.txt" $u
  G1-Reconstruct 'data/g1-inputs/P03-front.jpg' 'image/jpeg' "$G1\06-expiry\restart-recover"
  ```
- **期望结果**：`restart-before` 为 HTTP 200；重启后 `restart-after` 为 HTTP 404 `ASSET_NOT_FOUND`；全零的未知 ID 为 HTTP 404 `ASSET_NOT_FOUND`；`restart-recover` 为 HTTP 200。服务停止时 8000 和 4173 被释放（看 `local-run stop` 的输出）
- **证据文件名**：`$G1\06-expiry\restart-src.*`、`restart-before.glb.*`、`restart-after.glb.*`、`unknown-id.*`、`restart-recover.*`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛） | 签收 A（宋明耀） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G1-EXPIRE-04 坏 GLB 不得被判为往返通过

- **编号**：G1-EXPIRE-04
- **类别**：坏资产
- **必选**：是
- **对应验收条款**：G1-C15、G1-C09
- **前置条件**：G1-EXP-01 已经能正常运行
- **输入数据**：把 `P01-front.glb` 截掉末尾 1000 字节，存成 `$G1\03-export\BAD-truncated.glb`（【建议】）
- **逐步操作**：
  ```powershell
  $b = [IO.File]::ReadAllBytes((Resolve-Path "$G1\01-identity\P01-front.glb")); [IO.File]::WriteAllBytes("$PWD\$G1\03-export\BAD-truncated.glb", $b[0..($b.Length-1001)])
  & $PY $CHK glb "$G1\03-export\BAD-truncated.glb" | Set-Content "$G1\03-export\check-bad-glb.json"
  ```
  然后照 G1-EXP-01 的命令，把 `AGEMORPH_RESEARCH_MESH` 换成这个坏文件，输出目录为 `roundtrip-bad`。
- **期望结果**：辅助检查输出错误（退出码 2，“GLB 头不合法”）；研究脚本退出码不为 0，**不会**输出 `passed`（【推断】脚本在读取 GLB 头时就断言失败，可能不写报告文件）。之后再跑一次 G1-EXP-01 的正常输入，仍然通过，证明坏文件不影响后续使用
- **证据文件名**：`$G1\03-export\BAD-truncated.glb`、`check-bad-glb.json`、`roundtrip-bad\console.txt`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛） | 签收 A（宋明耀） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### 5.8 收尾

### G1-SUM-01 停止服务、日志和证据哈希

- **编号**：G1-SUM-01
- **类别**：环境记录
- **必选**：是
- **对应验收条款**：G1-C19；日志不得含照片、帧或完整参数：〔docs/后续任务清单.md:60「日志无照片/帧/完整参数」〕（这一条属于 R08，在 S1 签收；本例只顺带检查 G1 期间的日志）
- **前置条件**：前面各用例都已执行
- **输入数据**：无
- **逐步操作**：
  ```powershell
  .\tools\local-run.ps1 stop *>&1 | Out-File -Encoding utf8 "$G1\00-env\stop.txt"
  Copy-Item output\local-run\backend.log "$G1\local-run-backend.log"
  Select-String -Path "$G1\local-run-backend.log" -Pattern 'P0[0-3]-|NF-|MF-|BAD-|"shape"' | Out-File -Encoding utf8 "$G1\00-env\log-scan.txt"
  Get-ChildItem -Recurse -File $G1 | Get-FileHash -Algorithm SHA256 |
    ForEach-Object { "$($_.Hash.ToLower())  $(Resolve-Path -Relative $_.Path)" } | Set-Content -Encoding utf8 "$G1\sha256sums.txt"
  ```
- **期望结果**：停止输出显示后端和前端都已停止，8000、4173 不再接受连接；`log-scan.txt` 为空（日志里没有输入文件名，也没有完整参数数组）。这是【建议】的检查，扫到内容时照实记录并交 R08 处理，G1 判定由 A/B 决定；`sha256sums.txt` 已生成
- **证据文件名**：`$G1\00-env\stop.txt`、`$G1\local-run-backend.log`、`$G1\00-env\log-scan.txt`、`$G1\sha256sums.txt`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛） | 签收 A（宋明耀） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

## 6. 覆盖矩阵（G1 条款 → 用例）

| 条款 | 覆盖用例 |
|---|---|
| G1-C01 | G1-ENV-02、G1-ENV-03 |
| G1-C02 | G1-ENV-02、G1-ENV-03 |
| G1-C03 | G1-ID-02、G1-ID-05 |
| G1-C04 | G1-ID-03、G1-ID-04 |
| G1-C05 | G1-ID-05、G1-ID-07 |
| G1-C06 | G1-ID-01、G1-ID-02、G1-ID-06、G1-UI-01、G1-UI-02 |
| G1-C07 | G1-ID-01、G1-ID-02、G1-ID-03、G1-EXP-01 |
| G1-C08 | G1-UI-01、G1-UI-02 |
| G1-C09 | G1-EXP-01、G1-EXP-02、G1-EXPIRE-04 |
| G1-C10 | G1-NF-01、G1-ID-04 |
| G1-C11 | G1-MF-01 |
| G1-C12 | G1-BAD-01、G1-BAD-02、G1-BAD-03、G1-BAD-04、G1-BAD-05、G1-BAD-06 |
| G1-C13 | G1-CAN-01、G1-CAN-02、G1-CAN-03 |
| G1-C14 | G1-EXPIRE-01、G1-EXPIRE-02、G1-EXPIRE-03、G1-CAN-03 |
| G1-C15 | G1-EXPIRE-02、G1-EXPIRE-03、G1-EXPIRE-04 |
| G1-C16 | G1-UI-01、G1-UI-02、G1-ID-06、G1-EXP-02 |
| G1-C17 | G1-UI-03 |
| G1-C18 | G1-ENV-03 |
| G1-C19 | G1-ENV-01、G1-ENV-04、G1-SUM-01 |

## 7. 结果汇总模板（执行人填写，存为 `$G1\G1-results.md`）

| 编号 | 类别 | 必选 | 结果（通过/未通过/阻塞） | 关键观察（状态码、哈希前 12 位） | 签收 B（王晋涛） | 签收 A（宋明耀） |
|---|---|---|---|---|---|---|
| G1-ENV-01 | 环境记录 | 是 | | | | |
| G1-ENV-02 | 严格加载 | 是 | | | | |
| G1-ENV-03 | 严格加载 | 是 | | | | |
| G1-ENV-04 | 离线 | 否 | | | | |
| G1-ID-01 | 多身份 | 是 | | | | |
| G1-ID-02 | 多身份 | 是 | | | | |
| G1-ID-03 | 多姿态 | 是 | | | | |
| G1-ID-04 | 多姿态 | 是 | | | | |
| G1-ID-05 | 图像方向 | 是 | | | | |
| G1-ID-06 | 多身份 | 是 | | | | |
| G1-ID-07 | 图像方向 | 是 | | | | |
| G1-UI-01 | 浏览器工作台 | 是 | | | | |
| G1-UI-02 | 浏览器工作台 | 是 | | | | |
| G1-UI-03 | 演示回归 | 是 | | | | |
| G1-NF-01 | 无人脸 | 是 | | | | |
| G1-MF-01 | 多人脸 | 是 | | | | |
| G1-BAD-01 | 坏图 | 是 | | | | |
| G1-BAD-02 | 坏图 | 是 | | | | |
| G1-BAD-03 | 坏图 | 是 | | | | |
| G1-BAD-04 | 坏图 | 是 | | | | |
| G1-BAD-05 | 坏图 | 是 | | | | |
| G1-BAD-06 | 坏图 | 是 | | | | |
| G1-EXP-01 | 导出再导入 | 是 | | | | |
| G1-EXP-02 | 导出再导入 | 是 | | | | |
| G1-CAN-01 | 取消 | 是 | | | | |
| G1-CAN-02 | 取消 | 是 | | | | |
| G1-CAN-03 | 取消 | 是 | | | | |
| G1-EXPIRE-01 | 过期 | 是 | | | | |
| G1-EXPIRE-02 | 坏资产 | 是 | | | | |
| G1-EXPIRE-03 | 过期 | 是 | | | | |
| G1-EXPIRE-04 | 坏资产 | 是 | | | | |
| G1-SUM-01 | 环境记录 | 是 | | | | |

**G1 总结论**（只能写“通过”或“未通过”，由 B（王晋涛） 联调、A（宋明耀） 核模型与本人结果后共同签认；不得由起草人或审核方代填）：

| 项 | 内容 |
|---|---|
| 必选用例数 / 通过数 / 未通过数 / 阻塞数 | 31 / ___ / ___ / ___ |
| 可选用例结果 | G1-ENV-04：___ |
| 未采纳的【建议】及决定人 | |
| 偏差（照片人数、姿态、提交号等） | |
| 结论 | 未填写 |
| 签收 B（王晋涛）（日期，UTC+8） | 未签 |
| 签收 A（宋明耀）（日期，UTC+8） | 未签 |
| 矩阵 G1 行更新（由用户写证据与检查范围） | 未更新 |
| 回执 `U-6_G1执行回执.md` 已交 Sentinel 审核 | 否 |

## 8. 未决问题（需要用户或 A/B 决定）

- **Q-1 身份人数**：G1 原文没有规定身份数量。本文【建议】除 astronaut 外至少 3 名同意的成年人。能找到几个人？如果只有 2 人，A/B 是否接受？
- **Q-2 大侧脸的通过口径**：R04 写“正面/侧面”，但没有给角度。本文把约 30° 作为必须成功，约 60°–90° 只要求“成功或明确的脱敏错误”。A（宋明耀） 是否同意这个口径？三张大侧脸全部失败时是否仍算满足 R04？
- **Q-3 执行提交号（v1.3 已关闭）**：**G1 在 `10f1918` 上执行**【用户已确认 2026-11-21，经 Atlas 转达】。后端、启动器、接口、研究脚本在 `35c0cd6` 与 `10f1918` 间逐字节相同，文中这些条目保留双提交引用（@10f1918 / @35c0cd6）作依据；工作台步骤本就按 `10f1918` 编写，§5.3.0 右列只作对照。【建议】执行当天若 HEAD 不是 `10f1918`：先确认 `git status --porcelain` 输出为空（有任何改动就停止并报告，不切换）；若由 agent 执行切换，须先按〔RULES.md:14「未确认本次精确文件清单前不执行Git操作」〕向用户确认本次文件清单；然后 `git switch --detach 10f1918`，执行完再切回原分支；不能切回时停止执行并报告，不在其他提交上判定 G1。
- **Q-4 工作台导出件的再导入**：前端没有 GLB 导入控件（B23 第 75 行）。本文借用研究脚本完成再导入。如果研究脚本不接受工作台导出件（G1-EXP-02 阻塞），是否接受只用服务端 GLB 的往返（G1-EXP-01）加工作台导出件的结构检查？还是要先在前端补一个导入控件（这属于开发任务，需另行派发）？
- **Q-5 工作台中的过期场景**：G1-EXPIRE-02 依靠 0.001 秒 TTL 触发 404，这个时机是【推断】。如果没触发，是否接受用 G1-EXPIRE-01/03 的命令行证据加 R11 的前端自动化测试作为替代？
- **Q-6 “不发布迟到结果”的外部证据**：服务端没有列出缓存资产的接口，外部只能看到“前端没有显示迟到结果”和“没有拿到 mesh_id”。服务端行为只能由合成测试（G1-CAN-03）佐证。A/B 是否接受？
- **Q-7 日志检查**：G1-SUM-01 的日志扫描是【建议】，正式条款属于 R08（S1 签收）。如果扫到问题，是否影响 G1 结论？
- **Q-8 GPU**：R04 要求“CPU 与实际可用 GPU 分别验证”。G1 原文只写 CPU 自检，本文不含 GPU 用例。GPU 验证排在哪里，由 BP-1 和 A（宋明耀） 决定。
- **Q-9 FX-2 合入后的执行提交（v1.4 新增，待用户决定）**：据 Sentinel 转述，Forge 的 FX-2 将恢复 `10f1918` 删掉的免责文案（顶栏一行，见 `/workspace/AgeMorph3D_tasks/FX-2_说明.md` 第 16—18 行；FX-2 待 Sentinel 审查、尚未合入）。FX-2 合入后，G1 是仍钉 `10f1918`，还是改在含 FX-2 的提交上执行？本文不替用户决定；在答复前仍按 `10f1918` 执行（Q-3）。若改提交，须先重跑本文校验脚本（改提交常量）并更新变化处（至少工作台文案与免责提示相关步骤）。

## 9. 不在本用例单范围内

- R03 的检测框和五点叠加、阈值、点定义与耗时（`docs/后续任务清单.md` 第 55 行），以及 R04 的 GPU 验证（第 56 行）：属于 R03/R04 的其他出口，见 BP-1 S0-6、S0-7。
- R08 的容量与 LRU 淘汰、读取保护、长时负载、日志全面检查（第 60 行）：在 S1 签收（BP-1 S1-1）。
- R09 中两项不在静态接口的外部可观察范围内（清单第 61 行）：
  - **“框/点/ROI 到原图的变换明确”**：`/api/reconstruct` 成功响应不含框和点（`docs/api.md` 第 16 行），本用例单从外部只能看到它的结果（EXIF 照片和镜像照片能各自正确重建，G1-ID-05）。变换本身由 G1-ID-07 的三个已有单元测试佐证。实时帧 `/ws/frame` 会返回原图坐标下的框和五点（`docs/api.md` 第 119 行），属于 G2 用例，在那里做真实观察。
  - **“不同点来源可追溯”**：静态链路只有 YOLO 一种点来源，响应里也没有点来源字段，本用例单无法从外部检查。它的取证留给 R03/R09 的签收材料（模型台账 `docs/model-assets.md` 与 `docs/B0模型验证与复现.md` 中的来源记录），由 A（宋明耀） 负责，见 BP-1 S0-6、S0-10。G1 签收时须在矩阵检查范围中写明“此项未由 G1 用例覆盖”。
- 实时 `/ws/frame` 和实体摄像头：属于 G2。
- L02 干净环境与断网复现：由另一名成员在他自己的机器上执行。
- 年龄形状、年龄纹理和 G3：本文只确认 `/api/aging` 仍为 503。

## 附录 A：辅助检查脚本 `g1_check.py`

与 box 上的 `/workspace/AgeMorph3D_tasks/BP-3_g1_check.py` 内容相同（`BP-3_verify.py` 会核对两者一致）。只用 Python 标准库，可用 `backend\.venv\Scripts\python.exe` 运行。它是【建议】工具，不属于仓库；它的结论不能代替人工判定和签收。

```python
#!/usr/bin/env python3
r"""BP-3 G1 本机辅助检查（只读，仅标准库）。不属于仓库；放在被忽略的 output/g1/tools/ 下运行。

用法（项目根目录，Windows PowerShell）：
  backend\.venv\Scripts\python.exe output\g1\tools\g1_check.py resp  <reconstruct响应.json> [--source-age unknown|<数值>]
  backend\.venv\Scripts\python.exe output\g1\tools\g1_check.py glb   <文件.glb> [--kind service|viewer] [--response <响应.json>]
  backend\.venv\Scripts\python.exe output\g1\tools\g1_check.py angle <响应A.json> <响应B.json>
  backend\.venv\Scripts\python.exe output\g1\tools\g1_check.py distinct <a.glb> <b.glb> [...]
输出一行 JSON；退出码 0 = 本项检查全部满足，1 = 有不满足项，2 = 用法或文件错误。
数值容差 1e-4 为【建议】值，仓库没有规定；它只用于判定 R 是否正交，不是质量阈值。
"""
import hashlib, json, math, re, struct, sys

TOPOLOGY_ID = "tddfa-bfm-canon-v1-cc449ed7efa2860bed64be0a7e29ad8944912148c69f938ff768c8766d65e7cb"
VERTICES, FACES = 38365, 76073
AGE_KEYS = ("age", "ageAnchors", "displayAge", "texture_age")
TOL = 1e-4


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def load_glb(path):
    data = open(path, "rb").read()
    if len(data) < 28 or data[:4] != b"glTF":
        raise ValueError("不是 GLB（缺少 glTF 魔数）")
    version, length = struct.unpack_from("<II", data, 4)
    jlen, jtype = struct.unpack_from("<II", data, 12)
    if version != 2 or length != len(data) or jtype != 0x4E4F534A:
        raise ValueError("GLB 头不合法")
    doc = json.loads(data[20:20 + jlen].decode("utf-8"))
    off = 20 + jlen
    binary = b""
    if off + 8 <= len(data):
        blen, btype = struct.unpack_from("<II", data, off)
        if btype == 0x004E4942:
            binary = data[off + 8: off + 8 + blen]
    return data, doc, binary


def positions(doc, binary):
    out = []
    for mesh in doc.get("meshes", []):
        for prim in mesh.get("primitives", []):
            acc = doc["accessors"][prim["attributes"]["POSITION"]]
            view = doc["bufferViews"][acc["bufferView"]]
            start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
            stride = view.get("byteStride", 12)
            for i in range(acc["count"]):
                out.append(struct.unpack_from("<fff", binary, start + i * stride))
    return out


def rot(resp):
    R = resp["pose"]["R"]
    return [R[0:3], R[3:6], R[6:9]]


def det3(m):
    return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
            - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
            + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))


def check_resp(path, source_age):
    r = json.load(open(path, encoding="utf-8"))
    c = {}
    c["keys"] = {"mesh_id", "topology_id", "asset_mode", "capabilities", "source_age",
                 "shape", "expr", "pose"} <= set(r)
    c["mesh_id_32hex"] = bool(re.fullmatch(r"[0-9a-f]{32}", str(r.get("mesh_id", ""))))
    c["topology_id"] = r.get("topology_id") == TOPOLOGY_ID
    c["asset_mode_static"] = r.get("asset_mode") == "static"
    c["capabilities_false"] = r.get("capabilities") == {"age_morph": False, "age_texture": False}
    c["texture_url_null"] = r.get("texture_url") is None
    c["shape_40"] = len(r.get("shape", [])) == 40
    c["expr_10"] = len(r.get("expr", [])) == 10
    c["t_zero"] = r.get("pose", {}).get("t") == [0, 0, 0]
    R = rot(r)
    rtr = [[sum(R[k][i] * R[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    orth = max(abs(rtr[i][j] - (1 if i == j else 0)) for i in range(3) for j in range(3))
    d = det3(R)
    c["RtR_eq_I"] = orth <= TOL
    c["det_eq_1"] = abs(d - 1) <= TOL
    sa = r.get("source_age", {})
    if source_age == "unknown":
        c["source_age"] = sa == {"value": None, "method": "unknown", "calibration_id": None}
    elif source_age is not None:
        c["source_age"] = (sa.get("method") == "user" and sa.get("calibration_id") is None
                           and abs(float(sa.get("value")) - float(source_age)) < 1e-9)
    angle = math.degrees(math.acos(max(-1, min(1, (R[0][0] + R[1][1] + R[2][2] - 1) / 2))))
    return c, {"file": path, "sha256": sha256(path), "mesh_id": r.get("mesh_id"),
               "RtR_max_abs_error": orth, "det_R": d, "angle_from_identity_deg": angle}


def check_glb(path, kind, response):
    data, doc, binary = load_glb(path)
    c = {}
    c["single_embedded_buffer"] = len(doc.get("buffers", [])) == 1 and "uri" not in doc["buffers"][0]
    c["no_external_images"] = all("uri" not in im for im in doc.get("images", []))
    prims = [p for m in doc.get("meshes", []) for p in m.get("primitives", [])]
    c["no_morph_targets"] = all(not p.get("targets") for p in prims)
    nverts = sum(doc["accessors"][p["attributes"]["POSITION"]]["count"] for p in prims)
    nidx = sum(doc["accessors"][p["indices"]]["count"] for p in prims if "indices" in p)
    c["vertices_38365"] = nverts == VERTICES
    c["faces_76073"] = nidx == FACES * 3
    if kind == "service":
        extras = (doc.get("scenes") or [{}])[0].get("extras", {})
        cm = extras.get("coordinate_metadata", {})
        c["generator"] = doc.get("asset", {}).get("generator") == "AgeMorph3D static canonical v1"
        c["coordinate_metadata"] = (cm.get("canonical_unit") == "dimensionless"
                                    and cm.get("source_units") == "unverified"
                                    and cm.get("metric_scale_verified") is False)
    else:
        root = next((n for n in doc.get("nodes", []) if n.get("name") == "AgeMorph3D_Loaded_Model"), None)
        extras = (root or {}).get("extras", {})
        c["viewer_root_node"] = root is not None
    c["extras_asset_mode_static"] = extras.get("asset_mode") == "static"
    c["extras_no_age_keys"] = all(k not in extras for k in AGE_KEYS)
    if response:
        r = json.load(open(response, encoding="utf-8"))
        c["extras_topology_matches_response"] = extras.get("topology_id") == r.get("topology_id")
        c["extras_source_age_matches_response"] = extras.get("source_age") == r.get("source_age")
    else:
        c["extras_topology_id"] = extras.get("topology_id") == TOPOLOGY_ID
    return c, {"file": path, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
               "vertices": nverts, "triangles": nidx // 3, "kind": kind}


def main(argv):
    if len(argv) < 2:
        print(__doc__); return 2
    cmd, args = argv[1], argv[2:]
    def opt(name, default=None):
        if name in args:
            i = args.index(name); v = args[i + 1]; del args[i:i + 2]; return v
        return default
    try:
        if cmd == "resp":
            sa = opt("--source-age"); checks, info = check_resp(args[0], sa)
        elif cmd == "glb":
            kind = opt("--kind", "service"); resp = opt("--response")
            checks, info = check_glb(args[0], kind, resp)
        elif cmd == "angle":
            a, b = rot(json.load(open(args[0], encoding="utf-8"))), rot(json.load(open(args[1], encoding="utf-8")))
            tr = sum(a[k][i] * b[k][i] for i in range(3) for k in range(3))
            ang = math.degrees(math.acos(max(-1, min(1, (tr - 1) / 2))))
            checks, info = {}, {"a": args[0], "b": args[1], "relative_rotation_deg": ang}
        elif cmd == "distinct":
            if len(args) < 2: raise ValueError("至少两个 GLB")
            hashes = [sha256(p) for p in args]
            pos = [positions(*load_glb(p)[1:]) for p in args]
            pairs = {}
            for i in range(len(args)):
                for j in range(i + 1, len(args)):
                    diff = (max(abs(x - y) for u, v in zip(pos[i], pos[j]) for x, y in zip(u, v))
                            if len(pos[i]) == len(pos[j]) else None)
                    pairs[f"{args[i]} | {args[j]}"] = diff
            checks = {"sha256_all_distinct": len(set(hashes)) == len(hashes),
                      "positions_all_differ": all(v is None or v > 0 for v in pairs.values())}
            info = {"sha256": dict(zip(args, hashes)), "max_abs_position_diff": pairs}
        else:
            print(__doc__); return 2
    except (OSError, ValueError, KeyError, IndexError, json.JSONDecodeError) as e:
        print(json.dumps({"command": cmd, "error": str(e)}, ensure_ascii=False)); return 2
    ok = all(checks.values())
    print(json.dumps({"command": cmd, "ok": ok, "checks": checks, "info": info}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

## 附录 B：本文自检

`/workspace/AgeMorph3D_tasks/BP-3_verify.py` 用 `git show 35c0cd6:<路径>` 只读核对以下内容：每个 G1 条款至少对应一个用例，覆盖矩阵与用例里写的条款一致；九类必需场景（环境记录、多身份、多姿态、无人脸、多人脸、坏图、取消、过期、导出再导入）都有用例；每个用例的 10 个字段齐全；全文每一处〔路径:行号「原文」〕的原文都出现在 35c0cd6 该文件的该行；附录 A 与 box 上的脚本一致。
