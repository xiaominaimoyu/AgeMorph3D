# AgeMorph3D 会话交接：2026-10-30

本文件供新会话首读。工作区为 **`D:\project file\AgeMorph3D`**，Windows/PowerShell，日期口径为Asia/Shanghai。最新25文件已发布到`github/main`：**`dc2604e00002294e6b55a431bf530ad3be80cf96`**。工程底座、K2网格与K4填写工具已有证据；严格真实服务、年龄/身份质量、正式数据/训练和最终毕设交付仍未完成。

**最新用户决定：K4真实人工评审“尚未完成，先推进其他计划项”。保留待办，继续独立工作，不反复索取同一份人工材料。** 用户明确项目仅用于毕业设计；具体用途材料待补不扩大为整体开发停工。

本轮任务仅编写交接文档。旧持续目标已被用户清除，没有自动恢复；下一会话按新的用户指令开发。旧[10月26日交接](2026-10-26_会话交接-AgeMorph3D-report.md)保留历史，不覆盖本文件的最新状态。

## 1. 新会话前五分钟

1. 读本文件、[RULES](../RULES.md)与[验收矩阵](验收矩阵.md)。随后按需读[具体计划](剩余关键工作开发计划.md)的最新接续和K0—K8表、[47项清单](后续任务清单.md)，避免重新实施已完成工具。
2. 核对[发布收据](../output/research/git-publication-20261030-quality-and-mesh/publication-result.json)、[本轮关键指纹](../output/research/session-handoff-20261030/handoff-pins-v1.json)与当前源码。这里的发布状态来自上次实际Git结果；交接轮没有重新查询Git或远端。
3. 本机版本刚核对为Python3.11.16、Node24.14.1；解释器用`backend/.venv/Scripts/python.exe`，Node用`D:/JAVA run tools/node.exe`。不要使用系统默认Python替代项目环境。
4. 本文件第6节给出下一开发批次的独立范围：建议从L01统一启动/停止/诊断入口着手。它目前是建议与待实现范围，不是已完成能力，也没有替代K3/K5主线。

只读准备命令，在项目根执行：

```powershell
Set-Location -LiteralPath 'D:\project file\AgeMorph3D'
Get-Content -LiteralPath 'RULES.md' -Encoding UTF8
Get-Content -LiteralPath 'docs/验收矩阵.md' -Encoding UTF8
& 'backend/.venv/Scripts/python.exe' --version
& 'D:/JAVA run tools/node.exe' --version
```

本机[完整交接核对](../output/research/session-handoff-20261030/verification-v1.json)记录链接、关键指纹及受控文件范围。本轮只核对当前文件与保存证据，没有重新运行模型、训练、浏览器捕获或完整测试。`output/`和`data/`不在源码仓库，切换聊天继续使用当前工作区即可；新克隆还需按来源恢复受限资产和研究证据。

## 2. 最新发布与工作区边界

| 项目 | 已核实的保存状态 |
|---|---|
| 最新提交 | `dc2604e00002294e6b55a431bf530ad3be80cf96`；父提交`7542d34aa2b03f012f187d6201f5a406296eecf2` |
| 内容 | `research: add offline quality editor and neutral mesh validation`；25文件，2186行新增、14行删除，含K4与K2及说明更新 |
| 远端 | `github`，`https://github.com/xiaominaimoyu/AgeMorph3D`，分支`main`；发布时本地、跟踪分支和实际远端main相同 |
| 文件与日志 | [25文件清单](../output/research/git-publication-20261030-quality-and-mesh/submitted-files.md)、[最终收据](../output/research/git-publication-20261030-quality-and-mesh/publication-result.json) |
| 上次最终Git状态 | 仅旧`docs/2026-10-26_会话交接-AgeMorph3D-report.md`未跟踪；旧文件未纳入25文件。本轮新增本交接文档，未提交或推送 |
| 当前文件核对 | 写交接前，K2末检保存的400个受控文件指纹全部匹配；不以此代替新的Git状态查询 |

本次写交接不修改原源码、规划、`.gitignore`、模型登记、旧交接或旧研究结果。Git操作需针对新范围另列文件清单并获确认；上次25文件的确认不能用于自动提交本交接文档。禁止全量暂存、强制推送或把`data/output/环境/模型/日志`加入仓库。

上次发布两次校验器误报均保留：先把G3计划文档的CRLF→LF正常规范化判成字节漂移；随后把需保留的旧未跟踪交接文档纳入已暂存状态校验。最终修正只在忽略目录的发布校验器，实际Git命令均成功，25文件范围未变。[换行诊断](../output/research/git-publication-20261030-quality-and-mesh/index-line-ending-diagnostic-v1.json)与[状态校验修正](../output/research/git-publication-20261030-quality-and-mesh/resume-validator-v2.json)可复核。

当前`core.autocrlf=true`。G3计划文档工作区43076字节、256处CRLF；Git blob为42820字节/LF，正文相同。对该文档跨克隆核对时注意换行差异；源码、权重、图片和冻结协议的SHA约束仍按各自协议严格执行，不通用放宽指纹。

## 3. 当前真实开发进度

| 模块 | 已实现/已有证据 | 尚未完成 |
|---|---|---|
| 前端与三维 | TypeScript/Vite/Three.js工作台、程序化演示、静态GLB、PNG/GLB导出、相机和实时客户端 | 严格真实成功服务的最终联调；演示头模不是本人年龄重建 |
| 后端 | v1.2、HTTP/WS、生命周期、有界准入、缓存TTL、取消、资源释放及传输反馈 | 完整G0、严格照片G1、正式实体相机G2与长时/普通设备签收 |
| 检测/重建 | 真实YOLO/3DDFA CPU、canonical/UV/GLB、研究相机及实际查看器已有 | 多身份/姿态质量、具体用途登记及严格服务出口；当前两模型登记仍unresolved |
| K1/K2形状 | K1保存特征接口、嵌套身份验证、原始源恢复；最新实际中性GLB与固定渲染工程已完成 | 年份尺度、20—70覆盖、真实年龄/身份及独立质量；生产仍static_fallback |
| K4纹理 | 真SAM→目标拟合→共同UV/研究会话已运行，离线填写/回收和AI观察已完成 | 眼区/侧面/接缝质量、真实人工复核；重点32帧仍NO_FACE，G3未通过 |
| D/P数据工具 | 资源取得/校验、归档/解码、坐标叠加、重复候选、冻结预检、保存特征对接、质检工程已有 | 正式取得/身份审查/冻结/批量特征和真实预算，独立/高龄样本未齐 |
| 训练/评价 | E01工程稿/指标核心、T01四候选草案和只读入口预检 | 预检blocked/23缺项；没有正式训练执行器、正式训练和最终锁定测试完成证据 |
| 交付 | 过程文档、学校要求清单、源码发布和手动启动方式 | 统一运行入口、另一成员干净环境复现、完整论文/PPT/视频及正式主观评价 |

当前[生产年龄接口](../backend/src/agemorph3d/app.py)中的`/api/aging`仍直接返回`MODEL_NOT_READY`；[Runtime](../backend/src/agemorph3d/runtime.py)只在检测/重建均ready且未关闭时开放重建/实时能力，年龄能力仍false。不要通过改manifest为verified、开放布尔值或静态伪年龄目标绕过这些出口。

数据保持FG-NET研究子集292图/55身份：85/70/137条分别用于开发、校准、研究保留，身份数10/15/30。正式train/validation/test均0；精确研究标签20—69，70岁样本0。K2只消费70张校准原图、标签20—55，55岁仅一张；这些资料已曝光，不能转称独立测试或盲评。API源龄与文件名研究标签分开，unknown/null不填默认年龄。

## 4. 最近两批成果与证据入口

### 4.1 K2实际网格与渲染

先读[开发记录](年龄形状实际网格与渲染复核.md)、[原首轮记录](年龄形状新基线开发记录.md)和[冻结协议](age-shape-mesh-v1.json)，再按需读实现[age_shape_mesh_probe.py](../tools/age_shape_mesh_probe.py)及[浏览器脚本](../frontend/tests/age-shape-mesh-browser.mjs)。

- 22项输入先冻，复用保存的13个外层模型，没有重新拟合或选择模型。完整三路线942条请求中922成功、20条超覆盖失败保留。
- 13个可配对身份按最小/最大研究年龄、字典序打破同龄并列、双向固定26对照；78路线请求中74成功、4失败。047的20↔55在两条变化路线中超覆盖，未生成替代网格；2个仅单龄身份保留原因。
- 导出100份GLB：26源、26同源框架目标重建参考、48变化路线；78次同龄请求返回原系数对象及精确原GLB。目标参考是拟合代理，不是实测三维真值。
- Chrome156.0.8078.48及Edge156.0.4314.50各100资产、200帧、100次导出/GLTFLoader重导入；共400PNG、200导出，位置/索引精确、法线实际差0。源的显示变换固定，避免目标独立归一化干扰比较。
- 实际renderer均SwiftShader，资产经浏览器控制通道交给原FaceViewer字节入口；这不是正式HTTP资产流或普通GPU资格。七拼图/四原始帧仅作AI观察：形状变化较小，不能签收年龄或身份。

| 入口 | 用途 |
|---|---|
| [run-v1/report.json](../output/research/age-shape-mesh-20261030/run-v1/report.json) | 全分母、失败、实际GLB及source frame |
| [mesh-audit-v1.json](../output/research/age-shape-mesh-20261030/mesh-audit-v1.json) | 不导入项目代码的数组/GLB复算；端点与旧Gram最大差2.0816681711721685e-17 |
| [capture-report.json](../output/research/age-shape-mesh-20261030/capture-v1/capture-report.json) | 双浏览器版本、400帧、200实际导出和关闭状态 |
| [capture-audit-v1.json](../output/research/age-shape-mesh-20261030/capture-audit-v1.json) | 保存字节、同源显示变换、固定相机及尺寸 |
| [AI观察](../output/research/age-shape-mesh-20261030/ai-visual-observations-v1.json) | 7拼图/4原始帧的观察范围与局限；不是人工评审 |
| [final-audit-v1.json](../output/research/age-shape-mesh-20261030/final-audit-v1.json) | 400受控文件、13保护项、22输入和522本地链接 |

完整后端[2956项通过](../output/research/age-shape-mesh-20261030/full-v1.stdout.log)，30项新增；Ruff/格式通过，保留1条既有Starlette/httpx弃用提示。独立审计v1写报告时发生变量遮蔽，[失败](../output/research/age-shape-mesh-20261030/audit-failure-v1.json)和原脚本保留，v2只改审计输出变量名后通过。当前原0.1137%几何代理改善是旧结果，没有本轮新的模型收益。

### 4.2 K4离线填写及AI观察

先读[开发记录](纹理质量离线填写与导出开发记录.md)。本机[editor-v2填写页](../output/research/quality-review-editor-20261030/editor-v2/index.html)含72张原字节PNG、32组/320项，支持原尺寸查看、来源锁定、部分草稿、导入/导出；页面需要自行导出保存。

- 原37目标/两版共752保存帧、每版376帧/296对及全部失败保留；重点32对照两版仍全NO_FACE。
- AI[320项记录](../output/research/quality-observations-20261030/ai-worksheet-v1.json)为160项issue、160项not_assessable，0项no_obvious_issue。五拼图/三原尺寸样例的范围披露；不是320项质量通过或真实人工评审。
- 原[空worksheet](../output/research/texture-quality-review-20261029/prepared-v1/worksheet.json)不改。用户已明确尚未人工评审，先推进其他项；不要自动填human或反复请求。
- [双浏览器各20项](../output/research/quality-review-editor-20261030/browser-v3/report.json)通过，0网络/页面错误；[四份实际导出被原CLI接收、两份篡改拒绝](../output/research/quality-review-editor-20261030/export-integration-v1.json)，765唯一输入保持。
- 该批[前端340项](../output/research/quality-review-editor-20261030/frontend-full-v3.stdout.log)、类型/构建及新增Python静态检查通过；K2后续没有修改这些前端生产源码。browser-v1/v2的fieldset查询和异步File.text观察时机失败保留，最终v3通过。

后续改纹理需有明确观察依据、另冻单因素候选，同源同视角比较。目标未知区不回填源颜色来掩盖缺损；记录完整和AI观察均不授予纹理/身份/年龄或G3资格。

## 5. 原有关键缺口及切换条件

| 主线 | 当前状态 | 什么时候继续实际执行 |
|---|---|---|
| K3严格服务 | [资产诊断](模型资产诊断与严格服务缺项记录.md)已有，文件完整性不等于用途/算子/ready；两登记仍unresolved | A收口具体用途与来源，B走严格loader/实际HTTP、正式WS、真实身份/相机与长时恢复；不伪造登记 |
| 稳定浏览器资产流 | [原入口](稳定浏览器流重验入口记录.md)最近保存Chrome正向3/8、Edge1/8完成，正确payload不能豁免ERR_ABORTED | 浏览器版本变化或出现新的可证伪假设后，重新准备/冻结到新目录再验；无变化不重复旧矩阵 |
| K5正式数据 | [资源方案](数据资源清单.md)、D/P工具已有；独立/高龄、用途、身份/近重复和实际冻结仍缺 | 按原入口评审推进真实资源与特征，不把研究保留组改名为test或以合成工具授予资格 |
| T01及训练 | [草案/入口记录](基线注册草案与训练入口预检.md)已有；[当前报告](../output/research/training-preflight-20261030/probe-v1/current-research/report.json)blocked/23项 | 补模型/数据用途、R11/R12、R13/R14可行性与欠项、实际P04/P05/P06和E01材料后再短跑；不要求G3提前成功 |
| E01与最终评价 | [实验协议](实验协议.md)工程稿、指标核心及研究诊断已有 | 正式点集/归一化、阈值依据、独立性和真实团队签认后冻结执行；最终test不参与选择 |

固定Canary+SwiftShader+软件合成曾有12帧工程闭环；这与稳定版/普通图形及本轮离线中性网格是不同证据。不要缩小整体验收范围来解释失败，也不要用许可/人工待补阻止所有独立工程。

## 6. 下一开发批次：建议先补L01统一运行入口

这是一项**尚未实现的交接建议**，对应[L01](后续任务清单.md)和总体本机交付要求；B主责、A复核。已检查当前受控目录：有手动启动、锁文件和独立模型诊断，没有统一的PowerShell/cmd启动器。不是重做FastAPI或界面，也不等待K4人工评审才能编码。

1. 先读[backend启动说明](../backend/README.md)、[后端入口](../backend/src/agemorph3d/__main__.py)、[Settings](../backend/src/agemorph3d/config.py)、[独立诊断](../backend/src/agemorph3d/model_diagnostics.py)、[前端脚本](../frontend/package.json)及六份根说明；重新定义可验证出口再编码。`opencode-md/SKILL.md`当前缺失，已在RULES说明，继续使用用户给出的编码原则。
2. 最小入口支持检查/状态、启动、停止，正确处理含空格路径、缺解释器/依赖、端口占用、重复启动和部分启动失败。默认使用现有环境和锁定依赖，不静默安装或修改系统配置；日志/进程状态只进忽略目录。
3. 后端沿用现有单进程127.0.0.1:8000，前端固定loopback及明确端口；保持Host/Origin限制。状态区分“进程/HTTP可达”和“模型/能力ready”。未配置模型应missing，当前研究清单应准确报告error/unresolved，不能让启动器授予ready或年龄能力。
4. 停止仅作用于本次入口拥有且身份核对一致的进程；保留其他人的8000/5173监听者。验证子进程/worker/端口释放、失败回滚和重开，Windows后台辅助进程按用户规则使用隐藏窗口。不能把强制结束未知PID当资源验收。
5. 先做有意义的路径/状态/生命周期边界验证，再做真实本机启动—健康/前端响应—停止—重开。保留失败和环境/源码pin；结束核查拥有的PID与监听。按变更决定必要回归，已通过且源码未变的2956/340测试不要无故重复。
6. 完成后更新L01、当前验收及总规划，给出可运行命令和真实局限；这仍不是严格模型成功链、L02干净环境复现或毕设整体完成。若用户指定回到K3/K5主线，按第5节依赖执行。

拟定实现可以落在`tools/`下，但具体脚本及参数尚未创建；不要把计划文件名写成已存在入口。开始前确认当前源码，保留最新两个研究工具及原生产行为。

## 7. 已存在的手动启动与按需检查

以下是当前已有入口，本交接轮没有启动它们。环境和依赖已经在本机时，不需要先重装。分开打开两个终端，退出后检查自己拥有的进程和端口。

后端终端：

```powershell
Set-Location -LiteralPath 'D:\project file\AgeMorph3D\backend'
& '.\.venv\Scripts\python.exe' -B -m agemorph3d
```

前端终端：

```powershell
Set-Location -LiteralPath 'D:\project file\AgeMorph3D\frontend'
& 'D:/JAVA run tools/node.exe' '.\node_modules\vite\bin\vite.js' `
  --host 127.0.0.1 --port 5173 --strictPort
```

健康检查返回模型实际状态，不表示年龄功能已验收：

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/api/health' | ConvertTo-Json -Depth 6
```

算法/数据工具的复现命令分别在K2/K4开发记录及T01记录中，不在这里批量启动。现有`run-v1`、`capture-v1`、`editor-v2`、`browser-v3`、`prepared-v1`等目录都是已保存证据；**fresh-only脚本不能在原路径重跑**。先选新目录、冻结源码/输入/环境再运行；旧wrapper的日志或状态文件不能代替实际活进程句柄，不因观察超时重复启动。

## 8. 本机知识图谱和文件布局

- 生产前端在`frontend/src/`，独立研究界面在`frontend/research/`，显式研究浏览器脚本在`frontend/tests/`。后端在`backend/src/agemorph3d/`；K1/K5及D/P工具在`preprocessing/`；`training/`目前只有草案和只读预检。
- 协议/总规划/验收记录在`docs/`；模型/数据/独立环境及研究输出在被忽略的`data/`、`output/`。本人照片、确切源龄、派生图及私密路径只留原忽略证据，不复制进源码或交接正文。
- [graph.json](../output/research/project-knowledge-20261023/graphify-out/graph.json)与[图谱报告](../output/research/project-knowledge-20261023/graphify-out/GRAPH_REPORT.md)为6104节点/15680边/245社区，11条自环、无缺失端点。只是代码AST导航，文档语义未重新提取；截断查询和推断边不能替代源码。
- 解释器为`C:/Users/ASUS/AppData/Roaming/uv/tools/graphifyy/Scripts/python.exe`；用v3守卫`output/research/mask-replay-20261023/graphify_local.py`调用本机图谱，禁止Git/外部进程及网络。先按图谱词表展开查询，代码改变后才更新；大于5000节点生成图前告知并使用聚合视图。交接轮只查询，没有重建。

本轮核过的词表包含`runtime diagnostics main preflight neutral mesh review`。按需查询已有图：

```powershell
Set-Location -LiteralPath 'D:\project file\AgeMorph3D'
& 'C:/Users/ASUS/AppData/Roaming/uv/tools/graphifyy/Scripts/python.exe' -B `
  output/research/mask-replay-20261023/graphify_local.py `
  query 'runtime diagnostics main' --budget 1500
```

## 9. 毕业设计范围与长期节点

两人项目，A负责算法/数据实验，B负责系统/可视化及集成；真实姓名未绑定。项目和论文2027年6月交付，内部完整交付目标2027-05-31。任务书的论文/答辩阶段至2027-06-10，实际学校通知另留依据；旧审核文档2022—2024年份示例不覆盖当前日程。

[任务书原件](【任务书】基于YOLO与三维形变模型的跨年龄三维人脸重建及可视化系统.doc)、[审核要求原件](审核评估-毕业设计要求.docx)已只读核过，映射见[交付清单](毕业设计要求与交付清单.md)：1500行/人、4500行/项目，10—20人主观评价，3—5分钟视频，每人11类学校材料及真实签认。物理行数不证明个人原创贡献；内部A/B评审不替代正式10—20人评价。

原内部节点：11/30严格静态、12/20实时、12/31年龄原型阶段结论；2027-01-17资源、02/07划分、03/21训练选择、04/18最终评价、05/10初稿/冻结、05/31内部交付。日期是目标，按依赖和实际投入重估，不能压缩验收或凭工具完成数给整体百分比。

## 10. 可直接复制的新会话开场

```text
读取 D:\project file\AgeMorph3D\docs\2026-10-30_会话交接-AgeMorph3D-report.md。
以当前真实源码和保存证据为准，先执行第1节只读核对，再按第6节推进L01本机统一启动、停止与诊断入口。
K4真实人工评审尚未完成，先推进其他计划项，不代填或反复索取；模型、数据和质量门槛继续分别保留。
保留已有研究成果、失败分母、unknown源龄及生产关闭状态；不自动训练、重跑旧fresh-only目录或执行Git。
需要Git时先给本次精确文件清单，等我确认。
```

证据→判断→行动：25文件已发布、K2/K4工程与指纹可复核；核心质量/正式数据/严格服务仍欠。新会话可从独立运行入口开始交付具体代码，同时维护完整主线和失败边界。
