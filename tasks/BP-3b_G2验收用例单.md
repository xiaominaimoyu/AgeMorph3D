# BP-3b G2 实时姿态验收用例单（S1-2 / R12 / E05 实时部分）

- 版本：v1.2（2026-11-21，UTC+8）；起草：Blueprint（需求架构师）；审核：Sentinel（只审核，不签收）；状态：**v1.1 按用户第二轮答复关闭 Q-3；v1.2 按 Sentinel MINOR 修订（切换规则标【建议】、新增 Q-8），未执行**
- **固定提交（pinned）：`10f1918`，G2 在此提交上执行**【用户已确认 2026-11-21，经 Atlas 转达】（§8 Q-3 已关闭）（GitHub `xiaominaimoyu/AgeMorph3D`，2026-11-20 18:25 UTC+8，“refactor(frontend): 主工作台改为不滚动单屏布局”）。本文所有仓库引用都按 `git show 10f1918:<路径>` 核对，读自独立只读克隆 `/workspace/bp_ref/AgeMorph3D`；`BP-3b_verify.py` 逐条复核。`backend/`、`docs/api.md`、`frontend/src/services.ts` 在 `35c0cd6` 与 `10f1918` 之间没有改动，界面文字只在 `10f1918` 成立
- 依据：BP-1 `/workspace/AgeMorph3D_tasks/BP-1_里程碑重排与验收标准.md` S1-2 行〔@tasks BP-1_里程碑重排与验收标准.md:141「S1-2 R12 / G2」〕，以及 §10 Q-5 的用户答复〔@tasks BP-1_里程碑重排与验收标准.md:462「S1-2 的证据文件名以 BP-3b 为准」〕；格式沿用 BP-3 v1.2（`BP-3_G1验收用例单.md`）
- 执行窗口：G1 签收后 → **2026-12-27 G2 出口（已确认，用户 2026-11-21）**。所有时间为 UTC+8
- 人员：A＝宋明耀（算法），B＝王晋涛（系统）（用户 2026-11-21 确认）。G2 由 **B（王晋涛）联调主责，A（宋明耀）核对**：〔docs/验收矩阵.md:47「B，A复核」〕
- 前置：R12 依赖 R08—R11：〔docs/后续任务清单.md:64「R08—R11；不等 R13/R14」〕。因此本单的必选用例以 **G1 已签收（至少 BP-3 的 G1-ENV-03 严格服务就绪已通过）** 为前提；严格服务未就绪时，本单全部记为“阻塞”，不得改用研究端点或研究开关

## 修订记录

| 版本 | 日期（UTC+8） | 内容 |
|---|---|---|
| v1.0 | 2026-11-21 | 初稿：22 个条款（G2-C01—C22），26 个用例（25 个必选，1 个可选），附录 A 协议辅助客户端 `BP-3b_g2_ws.py`、附录 B 控制台记录脚本 `BP-3b_g2_console.js`；固定提交 `10f1918` |
| v1.1 | 2026-11-21 | 按用户第二轮答复（Atlas 转述）：**Q-3 关闭，G2 在 `10f1918` 上执行**【用户已确认 2026-11-21，经 Atlas 转达】；页首与 §8 同步。Q-1 仍按【建议】30 分钟，尚未询问用户，保持待决；Q-2、Q-4—Q-7 未答，保持待决。条款与用例数不变（仍为 22 个条款、26 个用例）。`BP-3b_verify.py` 增加 Q 状态检查。修订前备份 `/workspace/bp_work_1121b/BP-3b_G2验收用例单.md` |
| v1.2 | 2026-11-21 | 按 Sentinel 11-21 复审 MINOR：① 确认标记改为 【用户已确认 2026-11-21，经 Atlas 转达】，§0.1 补定义；② G2-ENV-01 期望结果与 §8 Q-3 的切换规则标【建议】，补“切换前 `git status --porcelain` 须为空、agent 执行须先按 RULES.md:14 确认文件清单”；③ 新增 §8 Q-8：FX-2 合入后 G2 是否仍钉 `10f1918`（待用户决定）。条款与用例数不变（仍为 22 个条款、26 个用例）。`BP-3b_verify.py` 增加对应检查。修订前备份 `/workspace/bp_work_1121c/BP-3b_G2验收用例单.md` |

## 0. 约定

### 0.1 标记

- 〔路径:行号「原文片段」〕：引用 `10f1918` 中该文件该行的原文，`BP-3b_verify.py` 会核对片段是否真在那一行。
- 〔@tasks 文件名:行号「原文片段」〕：引用 `/workspace/AgeMorph3D_tasks/` 下的任务文档（BP-1 等），同样由 `BP-3b_verify.py` 核对。
- 【推断】：根据代码或文档推出、仓库没有直接写明的结论。执行时以实际观察为准；不一致时照实记录，不改写成通过。
- 【建议】：比仓库原文更严，或仓库没有规定的做法（时长、容差、辅助脚本）。A（宋明耀）/B（王晋涛）可决定是否采纳；不采纳时在 §7 记下决定。
- 【用户已确认 2026-11-21，经 Atlas 转达】：用户本人答复、经 Atlas 转达给 Blueprint（“已确认（用户 2026-11-21）”同义）。

### 0.2 判定与签收

1. 每个用例只填 **通过 / 未通过 / 阻塞**。“阻塞”指前置条件不满足或工具不可用，不等于通过。
2. 【建议】必选用例中任一未通过或阻塞，G2 不通过（与 BP-3 §0.2 同口径）。可选用例照实记录，不影响结论。
3. 每个用例的签收栏分 **B（王晋涛，联调）** 和 **A（宋明耀，核对）** 两列：〔docs/验收矩阵.md:47「B，A复核」〕。**Sentinel 只审核回执，不签收。**
4. 签收后由用户更新矩阵 G2 行，写明证据与检查范围：〔docs/验收矩阵.md:59「后续每次签收须更新对应证据与检查范围」〕。
5. 不放宽、不倒推：〔docs/验收矩阵.md:41「未指定数值质量阈值的项目保留待制定，不从已看结果倒推通过线」〕。本文的容差（R 正交 1e-4）、时长（30 分钟）、恢复等待（15 秒）都标【建议】，**不是姿态精度或性能阈值**；资源曲线只记录，不设通过线。
6. 不得用研究链替代正式服务。B6 的实体相机证据用的是独立研究端点，不是正式 G2：〔docs/B6实时姿态开发记录.md:55「`/research/ws`隔离工具，不修改正式app/加载器/健康响应」〕；正式 G2 要求〔docs/B6实时姿态开发记录.md:94「以真正严格ready的模型完成正式服务G1与`/ws/frame`真实浏览器路径」〕。
7. 浏览器用例使用生产构建（`local-run.ps1 start --production`，前端 `http://127.0.0.1:4173`）：〔docs/验收矩阵.md:9「不把 Vite 开发服务当最终证明」〕。
8. 合成单元测试（`pytest`）只作辅助证据，不能替代真实服务或实体相机：〔docs/B6实时姿态开发记录.md:48「合成摄像头和模拟WS，覆盖镜像像素、恢复、单飞及停止/切换/pagehide；不是实体G2」〕。

### 0.3 摄像头、帧与隐私规则（必须遵守）

- 只拍**本人书面同意的成年人**（执行人本人或签了同意书的同学）。同意书留在本机，回执只写同意编号。第二人入镜（多人脸用例）也需要书面同意。
- 接口约定帧和推理输出不出本机：〔docs/api.md:9「用户照片、摄像头帧和推理输出不发送到云端，不写入前端持久存储」〕。本单沿用 B6 的做法，**不保存照片、视频、录屏或逐帧完整参数**：〔docs/B6实时姿态开发记录.md:42「真实相机没有保存照片、视频、截图、跟踪录像或逐帧参数」〕。
- 【建议】例外只有两类，而且都按照片处理、只留在被忽略的 `output/g2/`（`.gitignore` 第 28 行忽略 `output/`）：① 需要人工判断方向时的少量截图 `cam-*.png`（会拍到人脸）；② 附录 B 的记录文件 `wslog-*.json`（只有大小、序号、错误码、置信度、朝向向量和框中心 x，没有图像、关键点或完整 R）。**截图、记录文件、照片都不上传 box、不提交 Git、不发给任何 agent。** 交给 box 的回执 `U-6_G2执行回执.md`【建议路径，沿用 BP-1 S1-2】只含结果、计数、哈希前 12 位和 §7 汇总，不含图像。
- 协议用例（§5.2）用的输入图片沿用 BP-3 的 `data/g1-inputs/`（astronaut、本人照片、无人脸图、多人图），由附录 A 在内存中编码，不另存帧。
- 不得使用研究开关 `--research-allow-unresolved` 或研究端点；不得手改清单 verified 或哈希。

### 0.4 通用 PowerShell 准备（【建议】，每次开新终端时执行）

```powershell
Set-Location -LiteralPath 'D:\project file\AgeMorph3D'
$env:AGEMORPH_NODE = 'D:\JAVA run tools\node.exe'   # Node 不在 PATH 上时才需要；按本机实际路径改
$G2  = 'output\g2\run-20261220'                     # 把日期换成实际执行日（UTC+8）
$G1IN = 'data\g1-inputs'                            # BP-3 的输入目录
$API = 'http://127.0.0.1:8000'
$PY  = '.\backend\.venv\Scripts\python.exe'
$WS  = "$G2\tools\g2_ws.py"                         # 附录 A 复制到这里
$DET = 'data\models\yolov5n05-face\manifest.json'
$REC = 'data\models\3ddfa-v2\manifest.json'
New-Item -ItemType Directory -Force "$G2\00-env","$G2\01-protocol","$G2\02-camera\chrome","$G2\02-camera\edge","$G2\03-longrun","$G2\04-recovery","$G2\05-summary","$G2\tools" | Out-Null
```

正式端点只有一个：〔docs/api.md:105「端点：`ws://127.0.0.1:8000/ws/frame`」〕，代码入口〔backend/src/agemorph3d/app.py:216「@app.websocket("/ws/frame")」〕。前端由 `LocalApi.websocketUrl()` 拼出同一地址：〔frontend/src/services.ts:203「const url = new URL("/ws/frame", this.baseUrl);」〕。健康检查 `GET /api/health`：〔docs/api.md:15「`/api/health`」〕。

## 1. G2 条款拆分

G2 行“剩余可验证出口”的原文：〔docs/验收矩阵.md:47「正式`/ws/frame`、人工有意转头/镜像方向、长时/断开/重新打开及资源释放」〕，当前结论〔docs/验收矩阵.md:47「正式G2未通过」〕，对应〔docs/验收矩阵.md:47「G2实时姿态；R12/E05」〕。R12 验收要点在〔docs/后续任务清单.md:64「原 JPEG 像素与镜像对齐；进入应用的 ≤2 MiB 帧每帧一个终结回复」〕，E05 的实时相关部分在〔docs/后续任务清单.md:119「冷/热/纹理/WS/渲染分测；deadline、TTL、拒绝、重启/缺模型/断开」〕。BP-1 S1-2 把两者合写为 G2 出口〔@tasks BP-1_里程碑重排与验收标准.md:141「单飞/deadline；NO_FACE/MULTI_FACE 后继续；断线释放」〕。

| 条款 | 内容 | 来源 |
|---|---|---|
| G2-C01 | 正式 `/ws/frame`：严格就绪的模型、生产构建、真实浏览器与实体相机路径；`realtime=true` | 〔docs/验收矩阵.md:47「正式`/ws/frame`」〕〔docs/B6实时姿态开发记录.md:94「以真正严格ready的模型完成正式服务G1与`/ws/frame`真实浏览器路径」〕 |
| G2-C02 | 人工有意转头（左右、上下、平移）的人工检查 | 〔docs/验收矩阵.md:47「人工有意转头/镜像方向」〕〔docs/B6实时姿态开发记录.md:95「对有意左右/上下转头、平移、镜像方向、遮挡/无人/多人后恢复做人工质量检查」〕 |
| G2-C03 | 镜像方向：预览、叠加与三维展示方向一致（`S R S`） | 〔docs/验收矩阵.md:47「人工有意转头/镜像方向」〕〔docs/api.md:121「镜像预览的三维展示使用 `S R S`」〕 |
| G2-C04 | 长时运行 | 〔docs/验收矩阵.md:47「长时/断开/重新打开及资源释放」〕〔docs/B6实时姿态开发记录.md:96「补长时间运行、设备占用/拔出、恢复与实际资源曲线」〕 |
| G2-C05 | 断开（客户端停止、换来源、相机断开、服务端断开）后状态正确 | 〔docs/验收矩阵.md:47「长时/断开/重新打开及资源释放」〕〔docs/B6实时姿态开发记录.md:36「前端停止、来源切换、相机轨道ended和pagehide停止WS、计时器和轨道」〕 |
| G2-C06 | 重新打开（相机、连接）后恢复 | 〔docs/验收矩阵.md:47「长时/断开/重新打开及资源释放」〕 |
| G2-C07 | 资源释放（相机轨道、连接、服务端工作槽位、内存） | 〔docs/验收矩阵.md:47「长时/断开/重新打开及资源释放」〕〔docs/B6实时姿态开发记录.md:36「断开/取消/超时丢弃迟到结果，但原生线程实际结束前仍占用槽位」〕 |
| G2-C08 | 签收分工：B 联调主责，A 复核 | 〔docs/验收矩阵.md:47「B，A复核」〕 |
| G2-C09 | 原 JPEG 像素与镜像对齐：发出的 JPEG 不镜像，视频与叠加同时镜像，框按实际编码尺寸绘制 | 〔docs/后续任务清单.md:64「原 JPEG 像素与镜像对齐」〕〔docs/api.md:121「视频与叠加画布同时做水平镜像；发出的 JPEG 不镜像」〕 |
| G2-C10 | 进入应用的 ≤2 MiB 帧每帧恰好一个终结回复（`face_state` 或 `error`），`status` 不算确认 | 〔docs/后续任务清单.md:64「进入应用的 ≤2 MiB 帧每帧一个终结回复」〕〔docs/api.md:127「状态消息不能替代帧回复」〕 |
| G2-C11 | 每条服务端文本消息 UTF-8 ≤1024 字节 | 〔docs/后续任务清单.md:64「UTF-8 ≤1024 B」〕〔backend/src/agemorph3d/frame_socket.py:42「if len(text.encode("utf-8")) > 1024:」〕 |
| G2-C12 | 超过 2 MiB 的帧在协议层关闭（1009，无应用 JSON），另行验证 | 〔docs/后续任务清单.md:64「超限协议关闭另验」〕〔docs/api.md:143「WS协议层超过2 MiB仍1009且无应用终结JSON」〕 |
| G2-C13 | 单飞：客户端只有一帧在等；服务端不排队，流水违规两帧各 BUSY 后 1013 | 〔docs/后续任务清单.md:64「单飞/deadline」〕〔docs/api.md:131「服务器不排队推理」〕 |
| G2-C14 | deadline：工作与成功发送共享 6 秒绝对预算；客户端 8 秒无回复停止 | 〔docs/后续任务清单.md:64「单飞/deadline」〕〔docs/api.md:131「工作与成功发送共享6秒绝对预算」〕 |
| G2-C15 | NO_FACE / MULTI_FACE 后同一连接继续 | 〔docs/后续任务清单.md:64「NO_FACE/MULTI_FACE 后继续」〕〔backend/src/agemorph3d/frame_socket.py:12「_RECOVERABLE = {"NO_FACE", "MULTI_FACE", "BUSY"}」〕 |
| G2-C16 | 断线释放：断开后丢弃迟到结果，槽位在原生任务结束后释放，新连接可恢复 | 〔docs/后续任务清单.md:64「断线释放」〕〔docs/api.md:129「连接已断开时丢弃结果」〕 |
| G2-C17 | 不声称表情几何：回复不含 shape/expr，不逐帧生成或更新网格身份/年龄 | 〔docs/后续任务清单.md:64「不声称表情几何」〕〔docs/api.md:121「实时帧不生成/缓存GLB，不传完整shape/expr，也不更新网格身份或年龄」〕 |
| G2-C18 | WS 分测：实时帧耗时单独记录（首帧与后续帧分开），不与 HTTP 重建、纹理、渲染混算 | 〔docs/后续任务清单.md:119「冷/热/纹理/WS/渲染分测」〕〔docs/B6实时姿态开发记录.md:96「分别报告模型延迟、传帧率、渲染FPS及内存」〕 |
| G2-C19 | 拒绝：非白名单 Origin、非 JPEG、文本帧、边长超限都被拒绝，错误先回复再关闭 | 〔docs/后续任务清单.md:119「deadline、TTL、拒绝、重启/缺模型/断开」〕〔docs/api.md:129「WS校验白名单Origin和回环Host」〕〔docs/api.md:129「致命错误均先回复再关闭」〕 |
| G2-C20 | 重启 / 缺模型 / 断开：服务重启后手动重连可恢复；缺模型时实时能力关闭、帧返回 MODEL_NOT_READY | 〔docs/后续任务清单.md:119「deadline、TTL、拒绝、重启/缺模型/断开」〕〔docs/api.md:129「模型未就绪→MODEL_NOT_READY/1013」〕 |
| G2-C21 | 硬件 WebGL 与软件 WebGL 分开记录 | 〔docs/后续任务清单.md:119「硬件与软件 WebGL 分开记录」〕 |
| G2-C22 | 证据可追溯：提交、模型哈希、浏览器与相机型号、执行时间；签收时写明检查范围 | 〔docs/验收矩阵.md:59「后续每次签收须更新对应证据与检查范围」〕 |

**不属于 G2 的事项**：E05 中的 HTTP 重建冷/热耗时、TTL、纹理与渲染性能（分属 G1、G3 显示与资源、E05 正式性能），见 §9。

## 2. 环境记录（执行人填写）

复制本表到 `$G2\00-env\env-record.md` 后填写。

| 项 | 记录 | 来源/命令 |
|---|---|---|
| 执行人（A（宋明耀）/B（王晋涛）） | | |
| 执行起止时间（UTC+8） | | |
| 机器、Windows 版本、CPU 型号 | | 系统信息 |
| GPU 型号（只记录，G2 不验 GPU） | | 设备管理器 |
| 摄像头型号、接口（内置/USB）、实际分辨率 | | 设备管理器；G2-CAM-01 记录 |
| git commit / 工作区是否干净 | | `git rev-parse HEAD`；`git status --porcelain` |
| 与 `10f1918` 的差异 | 相同 / 不同（写明提交和原因） | `git log --oneline 10f1918..HEAD`；不同则先重跑 `BP-3b_verify.py`（改 `COMMIT`） |
| 对应 G1 回执与签收日期 | | `U-6_G1执行回执.md` |
| Python 版本；websockets 版本 | | `& $PY --version`；`& $PY -c "import websockets; print(websockets.__version__)"` |
| 检测与重建清单文件 SHA-256（与 G1 相同） | | G1 环境记录 |
| Chrome 版本；WebGL 渲染器（硬件/软件） | | `chrome://version`；`chrome://gpu` 的 “WebGL” 与 “GL_RENDERER” |
| Edge 版本；WebGL 渲染器（硬件/软件） | | `edge://version`；`edge://gpu` |
| 浏览器窗口尺寸 | | 【建议】≥1280×720 |
| 偏差 | | |

## 3. 证据目录布局

全部位于项目内被忽略的 `output/g2/run-<YYYYMMDD>/`（下称 `$G2`）。

```text
$G2/
  tools/g2_ws.py                    # 附录 A；g2_console.js 为附录 B
  00-env/   env-record.md  health-ready.json  health-nomodel.json  pytest-launcher.txt  pytest-realtime.txt
  01-protocol/                      # 附录 A 输出，每个文件 ok=true 才算该步通过
    ws-01-face.json  ws-02-repeat30.json  ws-03-noface.json  ws-04-multi.json  ws-05-pipeline.json
    ws-06-text.json  ws-06-png.json  ws-06-side.json  ws-07-oversize.json  ws-08-origin.json
    ws-09-drop.json  ws-10-nomodel.json  ws-11-latency.json
  02-camera/chrome/  02-camera/edge/
    wslog-<场景>.json  wssum-<场景>.json   # 附录 B 输出（按照片处理）
    cam-<场景>.png                        # 少量方向截图（按照片处理）
    notes.md                              # 人工观察、时间点（UTC+8）
  03-longrun/  wssum-longrun.json  resources.csv  notes.md
  04-recovery/ wssum-*.json  notes.md  health-*.json
  05-summary/  log-scan.txt  U-6_G2执行回执.md（草稿，交给 box 的只有它）
```

## 4. 输入准备

| 输入 | 来源 | 用途 |
|---|---|---|
| `$G1IN\P00-front.png` | astronaut，B0 登记的公开样例（BP-3 §4） | 协议单帧成功 |
| `$G1IN\P01-front.jpg` | 本人同意照片（BP-3 §4） | 协议成功、断线恢复 |
| `$G1IN\NF-scene.jpg` | 无人脸图（BP-3 §4） | NO_FACE |
| `$G1IN\MF-two.jpg` | 两名同意成年人合照（BP-3 §4） | MULTI_FACE |
| 实体摄像头 | 本机内置或 USB 摄像头 | §5.3 全部 |
| 第二名同意的成年人 | 现场入镜 | G2-CAM-04 多人脸 |

附录 A 把图片缩到最长边 640、质量 70 的 JPEG，与前端编码一致：〔docs/api.md:105「客户端发送 JPEG 二进制帧（最长边 640 像素，质量 0.7）」〕。服务端限制：〔backend/src/agemorph3d/config.py:56「max_frame_bytes: int = 2 * 1024**2」〕〔backend/src/agemorph3d/config.py:57「max_frame_side: int = 640」〕。

## 5. 用例

### 5.1 环境

### G2-ENV-01 环境记录与提交核对

- **编号**：G2-ENV-01
- **类别**：环境记录
- **必选**：是
- **对应验收条款**：G2-C22、G2-C21
- **前置条件**：G1 已签收，或至少 BP-3 G1-ENV-03 已通过（记录日期）
- **输入数据**：无
- **逐步操作**：
  1. 按 §2 填写 `$G2\00-env\env-record.md`。
  2. 在 Chrome、Edge 分别打开 `chrome://gpu`、`edge://gpu`，把 WebGL 一栏和 `GL_RENDERER` 抄进表中，注明是硬件还是软件（SwiftShader 等为软件）。
  3. 把附录 A、附录 B 复制到 `$G2\tools\`（`g2_ws.py`、`g2_console.js`），记录两者的 SHA-256。
- **期望结果**：§2 每行都有记录；两种浏览器的 WebGL 类型分别写明；提交为 `10f1918`（§8 Q-3 已关闭；不是时按 Q-3 的【建议】处理：先确认 `git status --porcelain` 为空再切回，不能切回则记“阻塞”并停止）。
- **证据文件名**：`$G2\00-env\env-record.md`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛，联调） | 签收 A（宋明耀，核对） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G2-ENV-02 严格服务就绪，实时能力开放

- **编号**：G2-ENV-02
- **类别**：严格加载
- **必选**：是
- **对应验收条款**：G2-C01
- **前置条件**：G2-ENV-01 通过；8000、4173 端口空闲
- **输入数据**：无
- **逐步操作**：
  1. 用真实清单以生产模式启动（与 BP-3 G1-ENV-03 相同命令）：
     ```powershell
     .\tools\local-run.ps1 start --production --detector-manifest $DET --reconstructor-manifest $REC
     .\tools\local-run.ps1 status
     ```
  2. 等两个模型都不再是 `loading`（【建议】最多 120 秒），保存健康检查：
     ```powershell
     curl.exe -sS -o "$G2\00-env\health-ready.json" "$API/api/health"
     ```
- **期望结果**：`models.detector.state` 和 `models.reconstructor.state` 都是 `ready`，`capabilities.realtime=true`，`device` 为 `cpu`。若仍是严格拒绝（清单 unresolved），本用例“阻塞”，G2 其余必选用例一并阻塞，**不得**改用研究开关。
- **证据文件名**：`$G2\00-env\health-ready.json`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛，联调） | 签收 A（宋明耀，核对） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G2-ENV-03 启动器 WS 参数与实时传输回归（辅助）

- **编号**：G2-ENV-03
- **类别**：传输参数
- **必选**：是
- **对应验收条款**：G2-C12、G2-C13、G2-C14；〔backend/src/agemorph3d/__main__.py:15「ws_max_size=2 * 1024 * 1024,」〕〔backend/src/agemorph3d/__main__.py:16「ws_max_queue=1,」〕〔backend/src/agemorph3d/__main__.py:17「ws_per_message_deflate=False,」〕
- **前置条件**：后端虚拟环境已装 dev 依赖（`pytest`）
- **输入数据**：无（合成测试）
- **逐步操作**：
  ```powershell
  Push-Location backend
  .\.venv\Scripts\python.exe -m pytest -q "tests/test_realtime_api.py::test_launcher_bounds_ws_queue_and_disables_compression" *>&1 |
    Out-File -Encoding utf8 "..\$G2\00-env\pytest-launcher.txt"
  .\.venv\Scripts\python.exe -m pytest -q tests/test_realtime_api.py *>&1 | Out-File -Encoding utf8 "..\$G2\00-env\pytest-realtime.txt"
  "exit=$LASTEXITCODE" | Add-Content "..\$G2\00-env\pytest-realtime.txt"
  Pop-Location
  ```
- **期望结果**：两次都全部通过、`exit=0`。其中 `test_timeout_never_releases_native_slot_early` 覆盖 deadline，〔backend/tests/test_realtime_api.py:229「async def test_timeout_never_releases_native_slot_early(models):」〕。**这些是合成测试，只证明机制存在，不是正式 G2 证据**（§0.2 第 8 条）。
- **证据文件名**：`$G2\00-env\pytest-launcher.txt`、`$G2\00-env\pytest-realtime.txt`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛，联调） | 签收 A（宋明耀，核对） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### 5.2 正式端点协议（附录 A，无摄像头）

本节用附录 A 直接连接正式端点。附录 A 带 `Origin: http://127.0.0.1:4173`（默认白名单之一：〔backend/src/agemorph3d/config.py:13「"http://127.0.0.1:4173",」〕），禁用压缩，与浏览器路径的协议一致；它只作协议探针，**浏览器真实路径在 §5.3 另验**。附录 A 依赖 websockets 的同步客户端（【推断】随 `uvicorn[standard]` 安装；缺少时退出码 3，用例记“阻塞”，是否安装由用户决定，见 §8 Q-4）。

### G2-WS-01 正式端点单帧成功与回复结构

- **编号**：G2-WS-01
- **类别**：协议
- **必选**：是
- **对应验收条款**：G2-C01、G2-C10、G2-C11、G2-C17；〔backend/src/agemorph3d/frame_socket.py:71「await _send(socket, {"type": "status", "device": "cpu"})」〕〔backend/src/agemorph3d/frame_socket.py:21「"""No coefficients, images or asset identifiers belong in a frame reply."""」〕
- **前置条件**：G2-ENV-02 通过
- **输入数据**：`P00-front.png`、`P01-front.jpg`
- **逐步操作**：
  ```powershell
  & $PY $WS probe "$G1IN\P00-front.png" "$G1IN\P01-front.jpg" --expect face_state,face_state --out "$G2\01-protocol\ws-01-face.json"
  ```
- **期望结果**：退出码 0，`ok=true`。具体：连上后第一条是 `{"type":"status","device":"cpu"}`；两帧各收到一条 `face_state`，`seq` 为 1、2；每条回复 ≤1024 字节；`checks` 全为 true：键集合恰为 `type/seq/ts/bbox/landmarks/pose/conf`（**没有 shape/expr**）、框在帧内、5 个有限关键点、`RᵀR≈I` 与 `det(R)≈1`（【建议】容差 1e-4）、`t=[0,0,0]`、`conf` 在 0—1。【推断】`P00` 为 PNG，附录 A 先转成 JPEG 再发送。
- **证据文件名**：`$G2\01-protocol\ws-01-face.json`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛，联调） | 签收 A（宋明耀，核对） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G2-WS-02 连续 30 帧：每帧一个终结回复，序号连续

- **编号**：G2-WS-02
- **类别**：协议
- **必选**：是
- **对应验收条款**：G2-C10、G2-C11、G2-C18；〔docs/api.md:129「每个已消费输入至多一条终结回复」〕
- **前置条件**：G2-WS-01 通过
- **输入数据**：`P01-front.jpg`（重复 30 次）
- **逐步操作**：
  ```powershell
  & $PY $WS probe "$G1IN\P01-front.jpg" --repeat 30 --out "$G2\01-protocol\ws-02-repeat30.json"
  ```
- **期望结果**：`ok=true`；30 条 `face_state`，`seq` 为 1—30 连续，没有多余或缺失的终结回复；`latency_ms.first`、`rest_p50`、`max` 照实记录（实时帧耗时单独记，不与 HTTP 重建混算，不设阈值）。
- **证据文件名**：`$G2\01-protocol\ws-02-repeat30.json`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛，联调） | 签收 A（宋明耀，核对） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G2-WS-03 NO_FACE 后同一连接继续

- **编号**：G2-WS-03
- **类别**：无人脸
- **必选**：是
- **对应验收条款**：G2-C15、G2-C10；〔docs/api.md:129「这三项清除前端旧框/姿态，并允许同一连接继续」〕
- **前置条件**：G2-WS-01 通过
- **输入数据**：`NF-scene.jpg`、`P01-front.jpg`
- **逐步操作**：
  ```powershell
  & $PY $WS probe "$G1IN\NF-scene.jpg" "$G1IN\P01-front.jpg" --expect NO_FACE,face_state --out "$G2\01-protocol\ws-03-noface.json"
  ```
- **期望结果**：`ok=true`；第 1 帧为 `error`、`code=NO_FACE`、`seq=1`，连接不关闭；第 2 帧在同一连接上得到 `face_state`、`seq=2`。
- **证据文件名**：`$G2\01-protocol\ws-03-noface.json`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛，联调） | 签收 A（宋明耀，核对） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G2-WS-04 MULTI_FACE 后同一连接继续

- **编号**：G2-WS-04
- **类别**：多人脸
- **必选**：是
- **对应验收条款**：G2-C15、G2-C10
- **前置条件**：G2-WS-01 通过
- **输入数据**：`MF-two.jpg`、`P01-front.jpg`
- **逐步操作**：
  ```powershell
  & $PY $WS probe "$G1IN\MF-two.jpg" "$G1IN\P01-front.jpg" --expect MULTI_FACE,face_state --out "$G2\01-protocol\ws-04-multi.json"
  ```
- **期望结果**：`ok=true`；第 1 帧 `code=MULTI_FACE`、`seq=1`，连接不关闭；第 2 帧 `face_state`、`seq=2`。
- **证据文件名**：`$G2\01-protocol\ws-04-multi.json`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛，联调） | 签收 A（宋明耀，核对） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G2-WS-05 流水违规：服务端不排队

- **编号**：G2-WS-05
- **类别**：单飞
- **必选**：是
- **对应验收条款**：G2-C13、G2-C19；〔docs/api.md:131「两个已消费序号各收到BUSY并以1013关闭」〕〔backend/src/agemorph3d/frame_socket.py:86「error = ApiError(429, "BUSY", "请等待当前帧回复后再发送下一帧。")」〕〔backend/src/agemorph3d/frame_socket.py:91「await _close(socket, 1013)」〕
- **前置条件**：G2-WS-01 通过
- **输入数据**：`P01-front.jpg`（不等回复连发两帧）
- **逐步操作**：
  ```powershell
  & $PY $WS pipeline "$G1IN\P01-front.jpg" --out "$G2\01-protocol\ws-05-pipeline.json"
  ```
- **期望结果**：`ok=true`；收到 `(seq=1, BUSY)`、`(seq=2, BUSY)` 两条错误，随后关闭码 1013；没有 `face_state`。【推断】若第 1 帧在第 2 帧到达前已处理完，会先收到 `face_state`，此时 `ok=false`，照实记录并重跑一次；两次都如此时记“未通过”并交 B 分析。
- **证据文件名**：`$G2\01-protocol\ws-05-pipeline.json`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛，联调） | 签收 A（宋明耀，核对） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G2-WS-06 拒绝：文本帧、非 JPEG、边长超限

- **编号**：G2-WS-06
- **类别**：拒绝
- **必选**：是
- **对应验收条款**：G2-C19、G2-C10；〔backend/src/agemorph3d/frame_socket.py:98「seq, ApiError(400, "BAD_INPUT", "实时帧必须为 JPEG 二进制数据。")」〕〔backend/src/agemorph3d/images.py:39「raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE", "不支持此图片格式。")」〕〔backend/src/agemorph3d/images.py:50「raise ApiError(413, "INPUT_TOO_LARGE", "实时帧边长超过限制。")」〕
- **前置条件**：G2-WS-01 通过
- **输入数据**：文本 `not a jpeg frame`；`P01-front.jpg` 转 PNG；`P01-front.jpg` 放大到最长边 800 的 JPEG
- **逐步操作**：
  ```powershell
  & $PY $WS text --out "$G2\01-protocol\ws-06-text.json"
  & $PY $WS png "$G1IN\P01-front.jpg" --out "$G2\01-protocol\ws-06-png.json"
  & $PY $WS side "$G1IN\P01-front.jpg" --out "$G2\01-protocol\ws-06-side.json"
  ```
- **期望结果**：三个文件都 `ok=true`：文本帧 → `(seq=1, BAD_INPUT)` 后关闭码 1003；PNG → `(seq=1, UNSUPPORTED_MEDIA_TYPE)` 后 1003；最长边 800 → `(seq=1, INPUT_TOO_LARGE)` 后 1003。错误都先回复再关闭：〔backend/src/agemorph3d/frame_socket.py:140「else 1003,」〕。
- **证据文件名**：`$G2\01-protocol\ws-06-text.json`、`$G2\01-protocol\ws-06-png.json`、`$G2\01-protocol\ws-06-side.json`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛，联调） | 签收 A（宋明耀，核对） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G2-WS-07 超过 2 MiB：协议层关闭（另验）

- **编号**：G2-WS-07
- **类别**：超限
- **必选**：是
- **对应验收条款**：G2-C12；〔docs/严格服务传输反馈与恢复记录.md:11「WebSocket关闭码1009提示大小限制」〕
- **前置条件**：G2-WS-01 通过
- **输入数据**：附录 A 生成的 2 MiB + 1 字节随机数据（以 JPEG 起始标记开头，不含图像）
- **逐步操作**：
  ```powershell
  & $PY $WS oversize --out "$G2\01-protocol\ws-07-oversize.json"
  ```
- **期望结果**：`ok=true`；关闭码 1009，没有任何应用层 `error` 或 `face_state`（只可能有连接开始时的 `status`）。这是传输例外，不计入“每帧一个终结回复”。
- **证据文件名**：`$G2\01-protocol\ws-07-oversize.json`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛，联调） | 签收 A（宋明耀，核对） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G2-WS-08 非白名单 Origin 被拒

- **编号**：G2-WS-08
- **类别**：拒绝
- **必选**：是
- **对应验收条款**：G2-C19；〔backend/src/agemorph3d/middleware.py:62「await send({"type": "websocket.close", "code": 1008})」〕
- **前置条件**：G2-ENV-02 通过
- **输入数据**：无
- **逐步操作**：
  ```powershell
  & $PY $WS origin --origin http://example.invalid --out "$G2\01-protocol\ws-08-origin.json"
  ```
- **期望结果**：`ok=true`：没有收到 `status`。【推断】中间件在接受连接前关闭，Uvicorn 会把它变成握手拒绝（`handshake_error` 中出现 HTTP 403）；若表现为连接后 1008 关闭，也算通过，照实记录。
- **证据文件名**：`$G2\01-protocol\ws-08-origin.json`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛，联调） | 签收 A（宋明耀，核对） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G2-WS-09 发帧后立即断开：结果丢弃，槽位释放后新连接恢复

- **编号**：G2-WS-09
- **类别**：断线释放
- **必选**：是
- **对应验收条款**：G2-C16、G2-C07、G2-C05；〔backend/src/agemorph3d/frame_socket.py:79「# A disconnect or an unsolicited next input wins over a late CPU result.」〕
- **前置条件**：G2-WS-01 通过
- **输入数据**：`P01-front.jpg`
- **逐步操作**：
  ```powershell
  & $PY $WS drop "$G1IN\P01-front.jpg" --recover-seconds 15 --out "$G2\01-protocol\ws-09-drop.json"
  curl.exe -sS -o "$G2\04-recovery\health-after-drop.json" "$API/api/health"
  ```
- **期望结果**：`ok=true`：断开后【建议】15 秒内，新连接得到通过全部检查的 `face_state`。`attempts` 中可以先出现 `BUSY`（原生任务仍占槽位，属预期：〔docs/api.md:131「断开/取消/超时不会提前释放原生CPU任务槽位」〕），但不得出现非 BUSY 的致命错误；之后健康检查仍为 `ready`、`realtime=true`。
- **证据文件名**：`$G2\01-protocol\ws-09-drop.json`、`$G2\04-recovery\health-after-drop.json`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛，联调） | 签收 A（宋明耀，核对） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G2-WS-10 缺模型：实时能力关闭，帧返回 MODEL_NOT_READY

- **编号**：G2-WS-10
- **类别**：缺模型
- **必选**：是
- **对应验收条款**：G2-C20、G2-C19；〔backend/src/agemorph3d/runtime.py:169「return ApiError(503, "MODEL_NOT_READY", "所需模型尚未就绪，请先完成模型与资产接入。")」〕〔frontend/src/main.ts:225「"实时检测能力不可用"」〕
- **前置条件**：§5.2 其余用例已完成（本用例要重启服务）
- **输入数据**：`P01-front.jpg`
- **逐步操作**：
  1. 停止服务，不带清单启动生产模式：
     ```powershell
     .\tools\local-run.ps1 stop
     .\tools\local-run.ps1 start --production
     curl.exe -sS -o "$G2\00-env\health-nomodel.json" "$API/api/health"
     & $PY $WS probe "$G1IN\P01-front.jpg" --expect MODEL_NOT_READY --expect-close 1013 --out "$G2\01-protocol\ws-10-nomodel.json"
     ```
  2. 在 Chrome 打开 `http://127.0.0.1:4173/`，连接本地服务，切到“摄像头”，开启摄像头并勾选授权，记录“连接实时检测”按钮是否可点和 `#stream-status` 文字（不截图）。
  3. 停止服务，按 G2-ENV-02 步骤 1 用真实清单重新启动，确认 `realtime=true` 后再继续。
- **期望结果**：`health-nomodel.json` 中 `capabilities.realtime=false`；附录 A `ok=true`：`(seq=1, MODEL_NOT_READY)` 后关闭码 1013；工作台“连接实时检测”不可点：〔frontend/src/main.ts:205「!camera.active || !supports("realtime") || !input("photo-consent").checked || busy;」〕，状态文字为“实时检测能力不可用”。
- **证据文件名**：`$G2\00-env\health-nomodel.json`、`$G2\01-protocol\ws-10-nomodel.json`、`$G2\04-recovery\notes.md`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛，联调） | 签收 A（宋明耀，核对） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G2-WS-11 deadline 与实时耗时记录

- **编号**：G2-WS-11
- **类别**：deadline
- **必选**：是
- **对应验收条款**：G2-C14、G2-C18；〔backend/src/agemorph3d/config.py:60「frame_timeout_seconds: float = 6」〕〔frontend/src/services.ts:720「this.fail("实时服务 8 秒未返回检测结果，连接已停止，请手动重试。"),」〕
- **前置条件**：G2-ENV-02、G2-ENV-03 通过
- **输入数据**：`P00-front.png`、`P01-front.jpg`（各重复 30 次）
- **逐步操作**：
  ```powershell
  & $PY $WS probe "$G1IN\P00-front.png" "$G1IN\P01-front.jpg" --repeat 30 --out "$G2\01-protocol\ws-11-latency.json"
  ```
- **期望结果**：`ok=true`；60 帧没有 `TIMEOUT`，每帧耗时都低于 6 秒预算；`latency_ms` 照实记录。【推断】正式服务的 6 秒预算不能通过环境变量调小（`Settings.from_env` 不读这一项），所以 TIMEOUT 分支只能由 G2-ENV-03 的合成测试证明；正式服务这里只证明“正常负载下不触发超时”。是否接受这一组合由用户决定（§8 Q-2）。
- **证据文件名**：`$G2\01-protocol\ws-11-latency.json`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛，联调） | 签收 A（宋明耀，核对） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### 5.3 实体相机与正式工作台（Chrome、Edge）

通用做法：打开 `http://127.0.0.1:4173/`，F12 → Console 粘贴附录 B（必须在点“连接实时检测”之前）；点击顶栏“本地演示模式”→“检查并连接”；左栏切到“摄像头”〔frontend/index.html:34「<button id="camera-tab" aria-pressed="false">摄像头</button>」〕，点“开启摄像头”并在浏览器中允许；勾选“我已获得该人像的使用授权”；点“连接实时检测”〔frontend/index.html:60「<button id="stream-toggle" class="button" disabled hidden>连接实时检测</button>」〕。成功时状态行显示〔frontend/src/main.ts:538「`实时检测 · 置信度 ${(state.conf * 100).toFixed(1)}% · 帧 ${state.seq}`;」〕。每个场景结束后在控制台执行 `copy(JSON.stringify(__g2summary(), null, 2))` 存为 `wssum-<场景>.json`，再执行 `copy(JSON.stringify(__g2))` 存为 `wslog-<场景>.json`，然后刷新页面并重新粘贴附录 B（每个场景单独一份记录）。附录 B 记录的时间为相对毫秒，`started` 为 UTC，换算成 UTC+8 写进 `notes.md`。

### G2-CAM-01 Chrome 实体相机经正式端点：框点叠加与镜像对齐

- **编号**：G2-CAM-01
- **类别**：实体相机
- **必选**：是
- **对应验收条款**：G2-C01、G2-C09、G2-C10、G2-C11、G2-C17
- **前置条件**：G2-ENV-02 通过；Chrome；摄像头未被其他程序占用
- **输入数据**：执行人本人正对摄像头
- **逐步操作**：
  1. 按 §5.3 通用做法连接，持续约 60 秒，正对镜头不动。
  2. 抬起右手放在脸的右侧（本人的右），观察预览中手出现在屏幕哪一侧，以及框是否框住脸、五个点是否落在双眼、鼻尖、两嘴角附近；截图一张 `cam-align.png`。
  3. 在控制台执行 `document.getElementById('viewer').dataset.vertices`，记录数值；点“停止实时检测”，保存 `wssum-align.json`、`wslog-align.json`。
- **期望结果**：
  - 预览是镜像（本人右手出现在屏幕右侧，像照镜子），框与五点叠在镜像画面中的脸上，没有左右错位：〔docs/api.md:121「前端以该帧实际编码尺寸绘制，视频与叠加画布同时做水平镜像」〕。
  - `wssum`：`url` 为 `ws://127.0.0.1:8000/ws/frame`；`terminal_replies` 等于 `sends`（停止时最多差 1 帧在途）；`seq_continuous_from_1=true`；`max_reply_bytes`≤1024；`face_keys` 只有 `bbox,conf,landmarks,pose,seq,ts,type`；`other_msgs=0`；`max_send_bytes`≤2097152。
  - 三维视口仍是原来的模型（顶点数与连接前相同），只随姿态转动，不出现表情或身份变化：〔docs/B6实时姿态开发记录.md:18「相机姿态驱动演示模型不表示已重建相机中人物身份」〕。
- **证据文件名**：`$G2\02-camera\chrome\wssum-align.json`、`$G2\02-camera\chrome\wslog-align.json`、`$G2\02-camera\chrome\cam-align.png`、`$G2\02-camera\chrome\notes.md`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛，联调） | 签收 A（宋明耀，核对） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G2-CAM-02 Edge 实体相机经正式端点：框点叠加与镜像对齐

- **编号**：G2-CAM-02
- **类别**：实体相机
- **必选**：是
- **对应验收条款**：G2-C01、G2-C09、G2-C10、G2-C11、G2-C17
- **前置条件**：G2-CAM-01 已执行；Chrome 已关闭摄像头（避免设备占用）；Edge
- **输入数据**：执行人本人正对摄像头
- **逐步操作**：与 G2-CAM-01 步骤 1–3 相同，证据存进 `edge\`。
- **期望结果**：与 G2-CAM-01 全部相同。
- **证据文件名**：`$G2\02-camera\edge\wssum-align.json`、`$G2\02-camera\edge\wslog-align.json`、`$G2\02-camera\edge\cam-align.png`、`$G2\02-camera\edge\notes.md`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛，联调） | 签收 A（宋明耀，核对） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G2-CAM-03 人工有意转头与镜像方向

- **编号**：G2-CAM-03
- **类别**：转头方向
- **必选**：是
- **对应验收条款**：G2-C02、G2-C03、G2-C09
- **前置条件**：G2-CAM-01 通过；Chrome（Edge 可选重复）
- **输入数据**：执行人本人；A（宋明耀）在旁观察或事后核对记录
- **逐步操作**：连接后按下表顺序做动作，每个动作保持约 3 秒、回正约 3 秒，B（王晋涛）在 `notes.md` 记下每个动作的开始时刻（UTC+8）和观察；每个方向截一张图 `cam-turn-<动作>.png`（共 6 张）。
  | 动作 | 记录 |
  |---|---|
  | 向本人左侧转头约 30° | 预览中脸转向屏幕哪侧；三维模型转向哪侧；`wslog` 中 `fwd[0]` 符号 |
  | 向本人右侧转头约 30° | 同上 |
  | 抬头、低头 | 三维模型上下方向；`fwd[1]` 符号 |
  | 身体向本人左、右平移约 20 cm | 叠加框随脸移动的屏幕方向；`cx` 变化方向 |
- **期望结果**：
  - 每个动作中，叠加框和三维模型的转动方向都与镜像预览中的脸一致（像照镜子），左右不颠倒、上下不颠倒：〔docs/api.md:121「不把镜像反射直接作为 R」〕。
  - `wslog` 中：左转与右转时 `fwd[0]` 符号相反，抬头与低头时 `fwd[1]` 符号相反；平移时 `cx`（未镜像 JPEG 坐标）的变化方向与镜像预览中的屏幕移动方向**相反**（【推断】因为发出的 JPEG 不镜像）。哪一侧对应正号由 A（宋明耀）对照坐标约定核对，本文不预设。
  - 这是人工方向检查，**不是有真值的姿态精度验收**：〔docs/B6实时姿态开发记录.md:57「这些是模型输出变化，不是有标定真值的实际转头角或人工视觉验收」〕；不设角度误差阈值。
- **证据文件名**：`$G2\02-camera\chrome\wssum-turn.json`、`$G2\02-camera\chrome\wslog-turn.json`、`$G2\02-camera\chrome\cam-turn-*.png`、`$G2\02-camera\chrome\notes.md`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛，联调） | 签收 A（宋明耀，核对） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G2-CAM-04 遮挡/离开画面与第二人入镜后继续

- **编号**：G2-CAM-04
- **类别**：无人脸/多人脸恢复
- **必选**：是
- **对应验收条款**：G2-C15、G2-C10；〔frontend/src/services.ts:763「if (code === "NO_FACE" || code === "MULTI_FACE" || code === "BUSY") {」〕
- **前置条件**：G2-CAM-01 通过；第二名同意的成年人在场
- **输入数据**：执行人；第二人
- **逐步操作**：连接后依次：① 用手完全遮住镜头约 5 秒，再移开；② 离开画面约 5 秒，再回来；③ 第二人进入画面并排约 5 秒，再离开。每步记下时刻和 `#stream-status` 文字；不截第二人的图。结束后保存 `wssum-recover.json`、`wslog-recover.json`。
- **期望结果**：遮挡和离开时 `#stream-status` 显示无人脸提示，叠加框消失；第二人入镜时显示多人提示；三种情况都**不断开**，恢复后继续出现 `face_state`。`wssum`：`error_codes` 含 `NO_FACE` 和 `MULTI_FACE`，`close_codes` 只有停止时的 1000（或为空），`seq_continuous_from_1=true`。
- **证据文件名**：`$G2\02-camera\chrome\wssum-recover.json`、`$G2\02-camera\chrome\wslog-recover.json`、`$G2\02-camera\chrome\notes.md`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛，联调） | 签收 A（宋明耀，核对） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G2-CAM-05 客户端单飞与传帧上限

- **编号**：G2-CAM-05
- **类别**：单飞
- **必选**：是
- **对应验收条款**：G2-C13、G2-C10；〔docs/api.md:125「客户端单飞，成功和错误均需匹配当前等待的序号」〕〔frontend/src/services.ts:652「}, 100);」〕
- **前置条件**：G2-CAM-01、G2-CAM-02 已保存 `wssum-align.json`
- **输入数据**：G2-CAM-01/02/03/04 的 `wssum-*.json`
- **逐步操作**：逐个查看各 `wssum-*.json` 中的 `max_outstanding`、`mean_send_rate`、`max_sends_in_1s`，填入 `notes.md`。
- **期望结果**：所有连接 `max_outstanding`≤1（任何时刻最多一帧在等回复）；`mean_send_rate`≤10；`max_sends_in_1s` 照实记录（【建议】≤10；定时器抖动导致 11 时照实记录并说明，不改写结论）。10 FPS 是传帧上限，不是吞吐目标：〔docs/api.md:125「10 FPS是传帧上限，不是模型吞吐或画布帧率」〕。
- **证据文件名**：`$G2\02-camera\chrome\notes.md`、`$G2\02-camera\edge\notes.md`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛，联调） | 签收 A（宋明耀，核对） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G2-CAM-06 长时运行与资源曲线

- **编号**：G2-CAM-06
- **类别**：长时
- **必选**：是
- **对应验收条款**：G2-C04、G2-C07、G2-C18
- **前置条件**：G2-CAM-01 通过；电脑接电源、关闭睡眠
- **输入数据**：执行人本人在镜头前（允许正常活动、短暂离开）
- **逐步操作**：
  1. Chrome 连接实时检测，【建议】连续运行 **30 分钟**（仓库没有规定时长，见 §8 Q-1）。
  2. 在第 0、10、20、30 分钟各记一行 `resources.csv`：时刻（UTC+8）、`#stream-status` 中的帧号、Chrome 任务管理器（Shift+Esc）中该标签页内存、后端进程内存：
     ```powershell
     Get-Process python -ErrorAction SilentlyContinue | Select-Object Id, @{n='WS_MB';e={[math]::Round($_.WorkingSet64/1MB,1)}}, CPU |
       Format-Table -AutoSize | Out-String | Add-Content "$G2\03-longrun\notes.md"
     ```
  3. 结束时点“停止实时检测”，保存 `wssum-longrun.json`（不保存 `wslog`，文件太大时可省略）。
- **期望结果**：整个过程连接不断（没有 1009/1011/1013 或“实时服务已断开”），`seq_continuous_from_1=true`、`max_outstanding`≤1；内存与帧号照实记录，**不设内存或 FPS 通过线**（§0.2 第 5 条），由 B（王晋涛）判断是否有持续增长并写明理由。
- **证据文件名**：`$G2\03-longrun\wssum-longrun.json`、`$G2\03-longrun\resources.csv`、`$G2\03-longrun\notes.md`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛，联调） | 签收 A（宋明耀，核对） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G2-CAM-07 停止、换来源、切标签页、关闭后重新打开

- **编号**：G2-CAM-07
- **类别**：断开与重开
- **必选**：是
- **对应验收条款**：G2-C05、G2-C06、G2-C07；〔frontend/src/services.ts:816「socket.close(1000, "client stopped");」〕〔frontend/src/main.ts:801「if (document.hidden) stopCamera();」〕〔frontend/src/main.ts:782「window.addEventListener("pagehide", () => {」〕
- **前置条件**：G2-CAM-01 通过；Chrome
- **输入数据**：执行人本人
- **逐步操作**：每一步之后看摄像头指示灯和 `#stream-status`，并在 PowerShell 执行 `Get-NetTCPConnection -RemotePort 8000 -State Established -ErrorAction SilentlyContinue | Measure-Object` 记录连接数。
  1. 连接实时检测约 20 秒 → 点“停止实时检测” → 再点“连接实时检测”。
  2. 点“关闭摄像头” → “开启摄像头” → “连接实时检测”。
  3. 连接中切到左栏“照片”（换来源）→ 再切回“摄像头”，开启并连接。
  4. 连接中切到另一个浏览器标签页约 10 秒 → 切回，开启并连接。
  5. 连接中直接关闭该标签页，30 秒后新开工作台并连接。
  保存每一步的 `wssum-reopen.json`（第 5 步关闭标签页前的记录无法导出，只记连接数和指示灯）。
- **期望结果**：第 1—4 步每次断开后：叠加框清除、`#stream-status` 清空或显示停止信息、`close_codes` 出现 1000（客户端主动关闭）；第 2—5 步摄像头指示灯熄灭（轨道已释放）；后端 8000 端口上的已建立连接数回到 0（【建议】30 秒内，浏览器保活连接照实记录）；每次重新连接后 `seq` 从 1 重新开始，并正常得到 `face_state`。
- **证据文件名**：`$G2\04-recovery\wssum-reopen.json`、`$G2\04-recovery\notes.md`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛，联调） | 签收 A（宋明耀，核对） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G2-CAM-08 服务重启中断与手动重连

- **编号**：G2-CAM-08
- **类别**：重启
- **必选**：是
- **对应验收条款**：G2-C20、G2-C05、G2-C06；〔frontend/src/services.ts:673「: "实时服务已断开，点击连接可手动重试。";」〕
- **前置条件**：G2-CAM-01 通过；Chrome
- **输入数据**：执行人本人
- **逐步操作**：
  1. 连接实时检测约 20 秒后，在 PowerShell 执行 `.\tools\local-run.ps1 stop`，记录工作台的 toast 和 `#stream-status` 文字。
  2. 按 G2-ENV-02 步骤 1 用真实清单重新启动，等健康检查 `ready`，保存 `health-after-restart.json`。
  3. 工作台点“本地演示模式/本地服务已连接”胶囊 →“检查并连接”，再点“连接实时检测”。保存 `wssum-restart.json`。
- **期望结果**：步骤 1：实时检测停止，提示为“实时服务已断开，点击连接可手动重试。”或 1013 的“实时服务暂时不可用…”（照实记录），不自动重连，不显示旧框；步骤 3：手动重连后新连接 `seq` 从 1 开始并正常得到 `face_state`。
- **证据文件名**：`$G2\04-recovery\health-after-restart.json`、`$G2\04-recovery\wssum-restart.json`、`$G2\04-recovery\notes.md`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛，联调） | 签收 A（宋明耀，核对） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G2-CAM-09 摄像头被占用或拔出

- **编号**：G2-CAM-09
- **类别**：设备故障
- **必选**：否（只有 USB 摄像头才能做“拔出”；内置摄像头只做“占用”）
- **对应验收条款**：G2-C05、G2-C20；〔frontend/src/services.ts:540「throw new Error("摄像头无法打开，可能被其他应用占用。");」〕〔frontend/src/main.ts:17「notify("摄像头已断开，请重新连接设备。", true);」〕
- **前置条件**：G2-CAM-01 通过
- **输入数据**：另一个占用摄像头的程序（例如 Windows“相机”应用）；USB 摄像头（如有）
- **逐步操作**：① 先用“相机”应用打开摄像头，再在工作台点“开启摄像头”，记录提示；关闭“相机”应用后重试。② （USB）连接实时检测中拔出摄像头，记录提示；插回后重新开启并连接。
- **期望结果**：① 提示“摄像头无法打开，可能被其他应用占用。”，释放后能开启；② 提示“摄像头已断开，请重新连接设备。”，实时检测停止，插回后能重新开启并连接。【推断】部分驱动在占用时仍允许共享打开，此时照实记录。
- **证据文件名**：`$G2\04-recovery\notes.md`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛，联调） | 签收 A（宋明耀，核对） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G2-CAM-10 不声称表情几何（界面与回复）

- **编号**：G2-CAM-10
- **类别**：语义
- **必选**：是
- **对应验收条款**：G2-C17；〔docs/api.md:123「`shape/expr` 不用于逐帧生成新几何」〕
- **前置条件**：G2-CAM-03 已完成
- **输入数据**：G2-CAM-01/03 的记录
- **逐步操作**：
  1. 检查 `wssum-align.json`、`wssum-turn.json` 的 `face_keys`。
  2. 实时检测中做张嘴、皱眉等表情约 10 秒，观察三维模型；控制台再读一次 `document.getElementById('viewer').dataset.vertices`。
  3. 通读工作台界面文字，记录是否有“表情”“身份”“年龄”随实时检测变化的说法。
- **期望结果**：`face_keys` 中没有 `shape`、`expr`；三维模型只整体转动，不随表情变形，顶点数不变；界面没有声称实时生成表情几何、重建身份或估计年龄的文字。
- **证据文件名**：`$G2\02-camera\chrome\notes.md`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛，联调） | 签收 A（宋明耀，核对） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### G2-CAM-11 Edge 断开与重开（简化）

- **编号**：G2-CAM-11
- **类别**：断开与重开
- **必选**：是
- **对应验收条款**：G2-C05、G2-C06、G2-C07
- **前置条件**：G2-CAM-02 通过；Edge
- **输入数据**：执行人本人
- **逐步操作**：在 Edge 中重复 G2-CAM-07 的步骤 1、2、4。
- **期望结果**：与 G2-CAM-07 对应步骤相同。
- **证据文件名**：`$G2\02-camera\edge\wssum-reopen.json`、`$G2\02-camera\edge\notes.md`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛，联调） | 签收 A（宋明耀，核对） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

### 5.4 汇总

### G2-SUM-01 日志隐私扫描、证据清点与回执

- **编号**：G2-SUM-01
- **类别**：环境记录
- **必选**：是
- **对应验收条款**：G2-C08、G2-C22、G2-C07
- **前置条件**：其余必选用例已执行
- **输入数据**：后端日志（`local-run.ps1 status` 输出的 `log_path`，文件名为 `<角色>.log`：〔tools/local_run.py:1499「log_path = plan.state_dir / f"{role}.log"」〕）、`$G2` 全部文件
- **逐步操作**：
  1. 【建议】扫描后端日志，确认没有帧字节、base64 图像或完整姿态参数：
     ```powershell
     .\tools\local-run.ps1 status
     # 把 status 输出中 backend 一项的 log_path（启动器状态目录下的 backend.log）填到 $LOG
     Select-String -Path $LOG -Pattern 'base64|/9j/|"R":|landmarks' | Out-File -Encoding utf8 "$G2\05-summary\log-scan.txt"
     ```
  2. 清点 §3 的文件是否齐全；把含图像的文件（`cam-*.png`）与 `wslog-*.json` 列入“不出本机”清单。
  3. 起草 `U-6_G2执行回执.md`：只写 §7 汇总表、各 JSON 的 `ok`、计数和 SHA-256 前 12 位，不附任何图像或逐帧记录。
- **期望结果**：`log-scan.txt` 为空（或只有与帧无关的命中，逐条说明）；证据齐全；回执不含图像、帧或逐帧参数。
- **证据文件名**：`$G2\05-summary\log-scan.txt`、`$G2\05-summary\U-6_G2执行回执.md`
- **判定/签收**：

| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛，联调） | 签收 A（宋明耀，核对） | 备注 |
|---|---|---|---|---|---|
| | | | | | |

## 6. 覆盖矩阵（条款 → 用例）

| 条款 | 用例 |
|---|---|
| G2-C01 | G2-ENV-02、G2-WS-01、G2-CAM-01、G2-CAM-02 |
| G2-C02 | G2-CAM-03 |
| G2-C03 | G2-CAM-03 |
| G2-C04 | G2-CAM-06 |
| G2-C05 | G2-WS-09、G2-CAM-07、G2-CAM-08、G2-CAM-09、G2-CAM-11 |
| G2-C06 | G2-CAM-07、G2-CAM-08、G2-CAM-11 |
| G2-C07 | G2-WS-09、G2-CAM-06、G2-CAM-07、G2-CAM-11、G2-SUM-01 |
| G2-C08 | G2-SUM-01 |
| G2-C09 | G2-CAM-01、G2-CAM-02、G2-CAM-03 |
| G2-C10 | G2-WS-01、G2-WS-02、G2-WS-03、G2-WS-04、G2-WS-06、G2-CAM-01、G2-CAM-02、G2-CAM-04、G2-CAM-05 |
| G2-C11 | G2-WS-01、G2-WS-02、G2-CAM-01、G2-CAM-02 |
| G2-C12 | G2-ENV-03、G2-WS-07 |
| G2-C13 | G2-ENV-03、G2-WS-05、G2-CAM-05 |
| G2-C14 | G2-ENV-03、G2-WS-11 |
| G2-C15 | G2-WS-03、G2-WS-04、G2-CAM-04 |
| G2-C16 | G2-WS-09 |
| G2-C17 | G2-WS-01、G2-CAM-01、G2-CAM-02、G2-CAM-10 |
| G2-C18 | G2-WS-02、G2-WS-11、G2-CAM-06 |
| G2-C19 | G2-WS-05、G2-WS-06、G2-WS-08、G2-WS-10 |
| G2-C20 | G2-WS-10、G2-CAM-08、G2-CAM-09 |
| G2-C21 | G2-ENV-01 |
| G2-C22 | G2-ENV-01、G2-SUM-01 |

## 7. 执行汇总（执行人填写）

| 编号 | 类别 | 必选 | 结果（通过/未通过/阻塞） | 关键观察（ok、关闭码、计数） | 签收 B（王晋涛，联调） | 签收 A（宋明耀，核对） |
|---|---|---|---|---|---|---|
| G2-ENV-01 | 环境记录 | 是 | | | | |
| G2-ENV-02 | 严格加载 | 是 | | | | |
| G2-ENV-03 | 传输参数 | 是 | | | | |
| G2-WS-01 | 协议 | 是 | | | | |
| G2-WS-02 | 协议 | 是 | | | | |
| G2-WS-03 | 无人脸 | 是 | | | | |
| G2-WS-04 | 多人脸 | 是 | | | | |
| G2-WS-05 | 单飞 | 是 | | | | |
| G2-WS-06 | 拒绝 | 是 | | | | |
| G2-WS-07 | 超限 | 是 | | | | |
| G2-WS-08 | 拒绝 | 是 | | | | |
| G2-WS-09 | 断线释放 | 是 | | | | |
| G2-WS-10 | 缺模型 | 是 | | | | |
| G2-WS-11 | deadline | 是 | | | | |
| G2-CAM-01 | 实体相机 | 是 | | | | |
| G2-CAM-02 | 实体相机 | 是 | | | | |
| G2-CAM-03 | 转头方向 | 是 | | | | |
| G2-CAM-04 | 无人脸/多人脸恢复 | 是 | | | | |
| G2-CAM-05 | 单飞 | 是 | | | | |
| G2-CAM-06 | 长时 | 是 | | | | |
| G2-CAM-07 | 断开与重开 | 是 | | | | |
| G2-CAM-08 | 重启 | 是 | | | | |
| G2-CAM-09 | 设备故障 | 否 | | | | |
| G2-CAM-10 | 语义 | 是 | | | | |
| G2-CAM-11 | 断开与重开 | 是 | | | | |
| G2-SUM-01 | 环境记录 | 是 | | | | |

**G2 总结论**（只能写“通过”或“未通过”，由 B（王晋涛）联调、A（宋明耀）核对后共同签认；不得由起草人或审核方代填）：

| 项 | 内容 |
|---|---|
| 必选用例数 / 通过数 / 未通过数 / 阻塞数 | 25 / ___ / ___ / ___ |
| 可选用例结果 | G2-CAM-09：___ |
| 未采纳的【建议】及决定人 | |
| 偏差（提交号、浏览器、摄像头、时长等） | |
| 结论 | 未填写 |
| 签收 B（王晋涛）（日期，UTC+8） | 未签 |
| 签收 A（宋明耀）（日期，UTC+8） | 未签 |
| 矩阵 G2 行更新（由用户写证据与检查范围） | 未更新 |
| 回执 `U-6_G2执行回执.md` 已交 Sentinel 审核 | 否 |

## 8. 未决问题（需要用户或 A（宋明耀）/B（王晋涛）决定）

- **Q-1 长时时长（仍待决）**：矩阵只写“长时”，没有时长。本文【建议】30 分钟连续运行（v1.1：尚未询问用户，仍按【建议】执行文本）。是否接受？若论文需要更长（如 2 小时），请定。
- **Q-2 deadline 的正式服务证据**：正式服务的 6 秒预算不能从外部调小，TIMEOUT 分支只有合成测试（G2-ENV-03）证明，正式服务只证明正常负载下不超时（G2-WS-11）。是否接受这一组合？若不接受，需要 B（王晋涛）在仓库里加一个只用于测试的配置项（改仓库，属于用户/B 的决定，本文不做）。
- **Q-3 执行提交号（v1.1 已关闭）**：**G2 在 `10f1918` 上执行**【用户已确认 2026-11-21，经 Atlas 转达】。【建议】执行当天若 HEAD 不是 `10f1918`：先确认 `git status --porcelain` 输出为空（有任何改动就停止并报告，不切换）；若由 agent 执行切换，须先按〔RULES.md:14「未确认本次精确文件清单前不执行Git操作」〕向用户确认本次文件清单；然后 `git switch --detach 10f1918`，执行完再切回原分支；不能切回时停止执行并报告，不在其他提交上判定 G2。（与 BP-3 Q-3 一致）
- **Q-4 辅助客户端依赖**：附录 A 需要后端虚拟环境里的 websockets 同步客户端（【推断】`uvicorn[standard]` 已带）。若没有，是否允许在本机虚拟环境安装？（安装属于用户决定；本文不安装、不下载。）
- **Q-5 方向截图与逐帧记录**：本文【建议】保留 6 张方向截图和不含图像的逐帧记录（只在本机）。B6 当时一张都没保存。是否接受？不接受时改为只写 `notes.md` 文字观察和 `wssum` 汇总。
- **Q-6 第二人入镜**：G2-CAM-04 需要第二名同意的成年人。若找不到，是否接受只用 G2-WS-04（多人照片）证明 MULTI_FACE 后继续？
- **Q-7 资源“释放”的判定口径**：本文用摄像头指示灯、8000 端口已建立连接数和进程内存曲线判断，不设数值阈值。是否需要更细的资源指标（如 Windows 性能监视器）？
- **Q-8 FX-2 合入后的执行提交（v1.2 新增，待用户决定）**：据 Sentinel 转述，Forge 的 FX-2 将恢复 `10f1918` 删掉的免责文案（顶栏一行，见 `/workspace/AgeMorph3D_tasks/FX-2_说明.md` 第 16—18 行；FX-2 待 Sentinel 审查、尚未合入）。FX-2 合入后，G2 是仍钉 `10f1918`，还是改在含 FX-2 的提交上执行？本文不替用户决定；在答复前仍按 `10f1918` 执行（Q-3）。若改提交，须先重跑本文校验脚本（改提交常量）并更新变化处（至少工作台文案与免责提示相关步骤）。

## 9. 不在本用例单范围内

- HTTP 重建冷/热耗时、资产 TTL、取消（属于 G1/R08，见 BP-3 与 BP-1 S1-1）。
- 年龄纹理、年龄形状、渲染 FPS 与稳定浏览器流（属于 G3 与 E06）。
- GPU 验证（BP-3 Q-8 同样未排）。
- 姿态精度（有真值的角度误差）：仓库没有真值数据与阈值，本文只做人工方向检查（G2-C02/C03）。
- 研究端点 `/research/ws` 与研究工具：只作历史证据，不重跑、不替代。

## 附录 A `BP-3b_g2_ws.py`（协议辅助客户端，【建议】工具）

```python
#!/usr/bin/env python3
"""G2 /ws/frame 协议辅助客户端（BP-3b 附录 A，【建议】工具，不是仓库代码）。

只连接本机正式端点 ws://127.0.0.1:8000/ws/frame，按前端同样方式把图片编码为
最长边 640、质量 70 的 JPEG（与 services.ts 的 videoBlob(video, 640, 0.7) 对应）。
不保存任何图片字节、关键点坐标或旋转矩阵；输出只含计数、尺寸、哈希前 12 位、
结构检查结果、朝向向量与耗时。输出文件仍按照片派生物处理，不出本机。
数值容差 1e-4 为【建议】值，只判定 R 是否正交，不是姿态质量阈值。

依赖：backend 虚拟环境中的 Pillow 与 websockets（uvicorn[standard] 的依赖，
需要 websockets>=11 的同步客户端）。缺少时退出码 3，用例记为“阻塞”。
用法见 BP-3b §5 各用例；退出码 0 = 本子命令的 ok 为 true，1 = false，2 = 参数错误。
"""
import argparse, hashlib, io, json, math, os, sys, time

TOL = 1e-4
URL = "ws://127.0.0.1:8000/ws/frame"
ORIGIN = "http://127.0.0.1:4173"
FACE_KEYS = {"type", "seq", "ts", "bbox", "landmarks", "pose", "conf"}

try:
    from PIL import Image, ImageOps
    from websockets.sync.client import connect
    import websockets
except Exception as exc:  # noqa: BLE001
    print(json.dumps({"ok": False, "blocked": f"缺少依赖：{exc!r}"}, ensure_ascii=False))
    sys.exit(3)


def jpeg(path, side=640, quality=70):
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((side, side)) if max(im.size) > side else None
        if side > 640 and max(im.size) <= 640:  # 边长超限用例：放大到 side
            scale = side / max(im.size)
            im = im.resize((round(im.width * scale), round(im.height * scale)))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=quality)
        return buf.getvalue(), im.size


def png(path):
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((640, 640))
        buf = io.BytesIO()
        im.save(buf, "PNG")
        return buf.getvalue(), im.size


def close_code(ws, exc=None):
    for obj in (exc, ws):
        for attr in ("rcvd", "close_rcvd"):
            frame = getattr(obj, attr, None) if obj is not None else None
            if frame is not None and getattr(frame, "code", None) is not None:
                return frame.code
    return getattr(ws, "close_code", None) if ws is not None else None


def check_face(msg, size):
    c = {}
    c["keys_exact"] = set(msg) == FACE_KEYS
    c["no_shape_expr"] = "shape" not in msg and "expr" not in msg
    b = msg.get("bbox", [])
    c["bbox_in_frame"] = (len(b) == 4 and all(isinstance(v, (int, float)) for v in b) and b[0] >= 0 and b[1] >= 0
                          and b[2] > 0 and b[3] > 0 and b[0] + b[2] <= size[0] + 1e-3 and b[1] + b[3] <= size[1] + 1e-3)
    lm = msg.get("landmarks", [])
    c["landmarks_5_finite"] = len(lm) == 5 and all(len(p) == 2 and all(math.isfinite(v) and abs(v) <= 16384 for v in p) for p in lm)
    R = msg.get("pose", {}).get("R", [])
    t = msg.get("pose", {}).get("t", [])
    ok_r = len(R) == 9 and all(math.isfinite(v) for v in R)
    if ok_r:
        m = [R[0:3], R[3:6], R[6:9]]
        orth = max(abs(sum(m[k][i] * m[k][j] for k in range(3)) - (1.0 if i == j else 0.0)) for i in range(3) for j in range(3))
        det = (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
               + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
        c["RtR_eq_I"] = orth <= TOL
        c["det_eq_1"] = abs(det - 1) <= TOL
        forward = [round(R[2], 4), round(R[5], 4), round(R[8], 4)]  # R·(0,0,1)，行优先
    else:
        c["RtR_eq_I"] = c["det_eq_1"] = False
        forward = None
    c["t_zero"] = t == [0, 0, 0]
    conf = msg.get("conf")
    c["conf_0_1"] = isinstance(conf, (int, float)) and 0 <= conf <= 1
    return c, forward


def session(frames, origin, wait=8.0):
    """frames: [(label, bytes, size)]；逐帧发送并等待终结回复，遇关闭停止。"""
    rec = {"url": URL, "origin": origin, "websockets": websockets.__version__, "replies": [], "status": None,
           "close_code": None, "handshake_error": None}
    try:
        ws = connect(URL, origin=origin, compression=None, max_size=None, open_timeout=wait)
    except Exception as exc:  # noqa: BLE001
        rec["handshake_error"] = f"{type(exc).__name__}: {exc}"[:200]
        return rec
    with ws:
        try:
            first = ws.recv(timeout=wait)
            rec["status"] = json.loads(first)
            rec["status_bytes"] = len(first.encode("utf-8"))
            for label, data, size in frames:
                t0 = time.perf_counter()
                ws.send(data)
                while True:
                    raw = ws.recv(timeout=wait)
                    msg = json.loads(raw)
                    if msg.get("type") != "status":
                        break
                item = {"input": label, "sent_bytes": len(data), "sha12": hashlib.sha256(data).hexdigest()[:12],
                        "size": list(size) if size else None, "type": msg.get("type"), "seq": msg.get("seq"),
                        "code": msg.get("code"), "reply_bytes": len(raw.encode("utf-8")),
                        "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
                if msg.get("type") == "face_state":
                    item["checks"], item["forward"] = check_face(msg, size)
                rec["replies"].append(item)
                if msg.get("type") == "error" and msg.get("code") not in {"NO_FACE", "MULTI_FACE", "BUSY"}:
                    break
            ws.close()
        except Exception as exc:  # noqa: BLE001
            rec["end"] = type(exc).__name__
        rec["close_code"] = close_code(ws)
    return rec


def burst(payloads, origin, text=False, wait=8.0):
    """不等回复连续发送，收集到关闭为止（流水违规、文本帧、超大帧）。"""
    rec = {"url": URL, "origin": origin, "messages": [], "close_code": None}
    ws = connect(URL, origin=origin, compression=None, max_size=None, open_timeout=wait)
    with ws:
        rec["status"] = json.loads(ws.recv(timeout=wait))
        for p in payloads:
            ws.send(p)
        try:
            while True:
                raw = ws.recv(timeout=wait)
                msg = json.loads(raw)
                rec["messages"].append({"type": msg.get("type"), "seq": msg.get("seq"), "code": msg.get("code"),
                                        "reply_bytes": len(raw.encode("utf-8"))})
        except Exception as exc:  # noqa: BLE001
            rec["end"] = type(exc).__name__
        rec["close_code"] = close_code(ws)
    return rec


def all_checks(rec):
    return all(all(r["checks"].values()) for r in rec["replies"] if "checks" in r)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mode", choices=("probe", "pipeline", "text", "png", "side", "oversize", "origin", "drop"))
    ap.add_argument("images", nargs="*")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--origin", default=ORIGIN)
    ap.add_argument("--expect", default="", help="probe：逗号分隔的期望类型/错误码序列，如 face_state,NO_FACE,face_state")
    ap.add_argument("--expect-close", type=int, default=None)
    ap.add_argument("--recover-seconds", type=float, default=15.0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if os.path.exists(a.out):
        print("输出文件已存在，不覆盖", file=sys.stderr); sys.exit(2)
    started = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    if a.mode == "probe":
        frames = [(os.path.basename(p), *jpeg(p)) for _ in range(a.repeat) for p in a.images]
        rec = session(frames, a.origin)
        got = [r["type"] if r["type"] == "face_state" else r["code"] for r in rec["replies"]]
        seqs = [r["seq"] for r in rec["replies"]]
        rec["observed"] = got
        rec["seq_continuous_from_1"] = seqs == list(range(1, len(seqs) + 1))
        rec["all_replies_le_1024"] = all(r["reply_bytes"] <= 1024 for r in rec["replies"])
        rec["face_checks_ok"] = all_checks(rec)
        ok = rec["handshake_error"] is None and rec["seq_continuous_from_1"] and rec["all_replies_le_1024"] and rec["face_checks_ok"]
        if a.expect:
            ok = ok and got == a.expect.split(",")
        if a.expect_close is not None:
            ok = ok and rec["close_code"] == a.expect_close
        lat = [r["latency_ms"] for r in rec["replies"]]
        rec["latency_ms"] = {"first": lat[0] if lat else None, "rest_p50": sorted(lat[1:])[len(lat[1:]) // 2] if len(lat) > 1 else None,
                             "max": max(lat) if lat else None}
    elif a.mode == "pipeline":
        data, _ = jpeg(a.images[0])
        rec = burst([data, data], a.origin)
        got = [(m["seq"], m["code"]) for m in rec["messages"] if m["type"] != "status"]
        ok = got == [(1, "BUSY"), (2, "BUSY")] and rec["close_code"] == 1013
    elif a.mode == "text":
        rec = burst(["not a jpeg frame"], a.origin)
        got = [(m["seq"], m["code"]) for m in rec["messages"] if m["type"] != "status"]
        ok = got == [(1, "BAD_INPUT")] and rec["close_code"] == 1003
    elif a.mode == "png":
        data, _ = png(a.images[0])
        rec = burst([data], a.origin)
        got = [(m["seq"], m["code"]) for m in rec["messages"] if m["type"] != "status"]
        ok = got == [(1, "UNSUPPORTED_MEDIA_TYPE")] and rec["close_code"] == 1003
    elif a.mode == "side":
        data, size = jpeg(a.images[0], side=800)
        rec = burst([data], a.origin)
        rec["frame_size"] = list(size)
        got = [(m["seq"], m["code"]) for m in rec["messages"] if m["type"] != "status"]
        ok = max(size) > 640 and got == [(1, "INPUT_TOO_LARGE")] and rec["close_code"] == 1003
    elif a.mode == "oversize":
        data = b"\xff\xd8" + os.urandom(2 * 1024 * 1024 - 1)  # 2 MiB + 1 字节
        rec = burst([data], a.origin)
        rec["sent_bytes"] = len(data)
        ok = rec["close_code"] == 1009 and not [m for m in rec["messages"] if m["type"] != "status"]
    elif a.mode == "origin":
        rec = session([], a.origin)
        ok = rec["status"] is None  # 握手被拒或连接被 1008 关闭，均不得收到 status
    else:  # drop
        data, size = jpeg(a.images[0])
        ws = connect(URL, origin=a.origin, compression=None, max_size=None, open_timeout=8)
        ws.recv(timeout=8); ws.send(data); ws.close()
        rec = {"dropped_after_send": True, "attempts": []}
        t0 = time.monotonic()
        ok = False
        while time.monotonic() - t0 < a.recover_seconds:
            r = session([("recover", data, size)], a.origin)
            kind = r["replies"][0]["type"] if r["replies"] else r.get("handshake_error") or "none"
            code = r["replies"][0]["code"] if r["replies"] else None
            rec["attempts"].append({"t_s": round(time.monotonic() - t0, 2), "type": kind, "code": code})
            if kind == "face_state" and all_checks(r):
                ok = True; break
            time.sleep(0.5)
    rec.update({"mode": a.mode, "started": started, "ok": bool(ok)})
    with open(a.out, "x", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    print(json.dumps({"mode": a.mode, "ok": bool(ok), "out": a.out}, ensure_ascii=False))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
```

## 附录 B `BP-3b_g2_console.js`（浏览器控制台记录脚本，【建议】工具）

```javascript
// BP-3b 附录 B：G2 实时帧记录（【建议】工具，不是仓库代码）。
// 在工作台页面按 F12 → Console 粘贴执行；必须在点击“连接实时检测”之前执行，刷新页面后要重新粘贴。
// 只记录消息大小、类型、序号、错误码、置信度、朝向向量 R·(0,0,1) 和框中心 x；不记录图像、关键点或完整 R。
(() => {
  if (window.__g2) { console.log("G2 记录已安装"); return; }
  const T0 = performance.now();
  const now = () => Math.round(performance.now() - T0);
  const log = { started: new Date().toISOString(), ua: navigator.userAgent, events: [] };
  window.__g2 = log;
  let conns = 0;
  const Native = window.WebSocket;
  class LoggedSocket extends Native {
    constructor(url, protocols) {
      super(url, protocols);
      const conn = ++conns;
      this.__conn = conn;
      log.events.push({ k: "new", conn, t: now(), url: String(url) });
      this.addEventListener("open", () => log.events.push({ k: "open", conn, t: now() }));
      this.addEventListener("message", (ev) => {
        const e = { k: "recv", conn, t: now() };
        if (typeof ev.data === "string") {
          e.bytes = new TextEncoder().encode(ev.data).byteLength;
          try {
            const m = JSON.parse(ev.data);
            e.type = m.type; e.seq = m.seq; e.code = m.code;
            e.keys = Object.keys(m).sort().join(",");
            if (m.type === "face_state") {
              const R = m.pose.R;
              e.conf = m.conf;
              e.fwd = [R[2], R[5], R[8]].map((v) => Math.round(v * 1000) / 1000);
              e.cx = Math.round(m.bbox[0] + m.bbox[2] / 2);
            }
          } catch { e.type = "invalid-json"; }
        } else e.type = "binary";
        log.events.push(e);
      });
      this.addEventListener("close", (ev) => log.events.push({ k: "close", conn, t: now(), code: ev.code }));
      this.addEventListener("error", () => log.events.push({ k: "error", conn, t: now() }));
    }
    send(data) {
      log.events.push({ k: "send", conn: this.__conn, t: now(), bytes: data.size ?? data.byteLength ?? data.length });
      return super.send(data);
    }
  }
  window.WebSocket = LoggedSocket;
  window.__g2summary = () => {
    const out = [];
    for (let c = 1; c <= conns; c++) {
      const ev = log.events.filter((e) => e.conn === c);
      const sends = ev.filter((e) => e.k === "send");
      const terms = ev.filter((e) => e.k === "recv" && (e.type === "face_state" || e.type === "error"));
      let outstanding = 0, maxOutstanding = 0;
      for (const e of ev) {
        if (e.k === "send") maxOutstanding = Math.max(maxOutstanding, ++outstanding);
        if (e.k === "recv" && (e.type === "face_state" || e.type === "error")) outstanding--;
      }
      let maxPerSecond = 0;
      for (let i = 0, j = 0; i < sends.length; i++) {
        while (sends[i].t - sends[j].t >= 1000) j++;
        maxPerSecond = Math.max(maxPerSecond, i - j + 1);
      }
      const faces = terms.filter((e) => e.type === "face_state");
      const seqs = terms.map((e) => e.seq);
      const codes = {};
      terms.filter((e) => e.type === "error").forEach((e) => { codes[e.code] = (codes[e.code] || 0) + 1; });
      const span = sends.length > 1 ? (sends[sends.length - 1].t - sends[0].t) / 1000 : 0;
      out.push({
        conn: c,
        url: (ev.find((e) => e.k === "new") || {}).url,
        duration_s: ev.length ? (ev[ev.length - 1].t - ev[0].t) / 1000 : 0,
        sends: sends.length,
        max_send_bytes: Math.max(0, ...sends.map((e) => e.bytes || 0)),
        terminal_replies: terms.length,
        face_state: faces.length,
        error_codes: codes,
        status_msgs: ev.filter((e) => e.k === "recv" && e.type === "status").length,
        other_msgs: ev.filter((e) => e.k === "recv" && !["face_state", "error", "status"].includes(e.type)).length,
        seq_continuous_from_1: seqs.every((s, i) => s === i + 1),
        max_reply_bytes: Math.max(0, ...ev.filter((e) => e.k === "recv").map((e) => e.bytes || 0)),
        face_keys: [...new Set(faces.map((e) => e.keys))],
        max_outstanding: maxOutstanding,
        mean_send_rate: span ? Math.round((sends.length - 1) / span * 100) / 100 : null,
        max_sends_in_1s: maxPerSecond,
        fwd_x_range: faces.length ? [Math.min(...faces.map((e) => e.fwd[0])), Math.max(...faces.map((e) => e.fwd[0]))] : null,
        fwd_y_range: faces.length ? [Math.min(...faces.map((e) => e.fwd[1])), Math.max(...faces.map((e) => e.fwd[1]))] : null,
        close_codes: ev.filter((e) => e.k === "close").map((e) => e.code),
      });
    }
    return { started: log.started, ua: log.ua, connections: out };
  };
  console.log("G2 记录已安装。结束后执行：copy(JSON.stringify(__g2summary(), null, 2)) 和 copy(JSON.stringify(__g2))");
})();
```
