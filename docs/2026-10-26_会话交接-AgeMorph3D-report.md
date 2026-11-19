# AgeMorph3D 新会话交接

2026-10-26，Asia/Shanghai。本文件供新会话接续开发，按本次读取的源码、已保存研究结果和较晚的Git发布收据整理。当前任务只准备交接，没有继续开发、模型推理、浏览器批次、训练或Git操作。

## 1. 先读这一页

项目目录为`D:\project file\AgeMorph3D`，Windows/PowerShell，前端TypeScript/Vite/Three.js，后端Python3.11/FastAPI。两人项目以2027年6月交付为计划目标，计划日期不是能力验收。

最近一次已核验发布提交为[`184ffbfd317eefb1e3cfdbabe4e836b8b019be88`](https://github.com/xiaominaimoyu/AgeMorph3D/commit/184ffbfd317eefb1e3cfdbabe4e836b8b019be88)，父提交`0590e439de8806aff89ef6526ff4a4d16d65dfd2`。10个确认文件已正常推送到GitHub `github/main`，当次本地、远端和跟踪引用一致，工作区干净；依据是[发布收据](../output/research/git-publication-20261026-observed-skin/publication-result.json)。本次交接没有重新检查远端或Git状态；本文是发布后新增、尚未提交的文件。

最新研究结论是：**真实额头候选的注册与质量复核已完成；额头支持增加，候选质量未通过。**37目标注册、752帧对照和Chrome/Edge共74次GLB往返通过，完整后端2058项测试通过；重点32帧仍全部`NO_FACE`，眼区和侧面缺口明显。年龄形状、纹理、连续性、身份、许可和独立评价继续分别判断，G3与生产年龄能力保持关闭。

新会话不要重做已完成额头批。先恢复证据与源码基线，再分别处理需要真实人工记录的候选质量和可自主推进的稳定浏览器工程缺口。

## 2. 最短阅读顺序

| 顺序 | 入口 | 解决的问题 |
| --- | --- | --- |
| 1 | [真实额头候选注册与质量复核](真实额头候选注册与质量复核.md) | 最新开发范围、表格、结论及失败边界 |
| 2 | [较晚的Git发布收据](../output/research/git-publication-20261026-observed-skin/publication-result.json) | 最新已核验提交和精确10文件清单 |
| 3 | [研究批交接JSON](../output/research/real-candidate-20261026/final-handoff.json)、[封口验证](../output/research/real-candidate-20261026/verification.json)、[最终独立审查](../output/research/real-candidate-20261026/final-review-v1.json) | 2706文件指纹、14快照、148链接和关闭标志 |
| 4 | [TASKS](../TASKS.md)、[G3分项计划](G3分项验收与后续开发计划.md)、[FFHQ后续计划](FFHQ桥接后的后续实施计划.md) | 未完成出口与依赖；按批次区分历史状态 |
| 5 | [PRD](../PRD.md)、[ARCHITECTURE](../ARCHITECTURE.md)、[DESIGN](../DESIGN.md)、[RULES](../RULES.md)、[PROGRESS](../PROGRESS.md) | 产品、结构、约束和历史执行记录；连同TASKS组成六份根说明 |
| 6 | [真实会话显示记录](真实研究会话连续显示与导出记录.md)、[定长响应候选审查](固定长度响应兼容候选审查.md) | 下一条可独立推进的稳定浏览器工程线 |

`final-handoff.json`里的`git_operations_this_task=false`、PROGRESS里的“本轮无Git”和“0590e上轮”，指先完成的研究批；随后才执行184ffbfd发布。不要据较早字段断言成果尚未提交，也不要为了更新Git状态重写冻结研究报告。

真实输入、权重、环境、日志、图片与GLB均在本机忽略目录。克隆仓库只有源码和说明，不自动具备真实复现资产。用户本人照片及明确源龄已用于本机工程正向验证，私密路径和确切个人记录继续留在本机受控证据中，本文不复制。

## 3. 已完成到哪里

| 工作线 | 当前已完成 | 不能据此宣称完成 |
| --- | --- | --- |
| 协议与年龄语义 | 身份划分、开发/校准/保留、同龄研究标签、未知API源龄语义已建立 | 允许用途的独立/高龄评价、训练重叠排除仍有欠项 |
| 真实研究和年龄形状比较 | SAM目标逐图重检/完整拟合、同龄漂移研究及BFM/SAM路线比较已做 | 合格年龄形状仍未通过；静态回退不等于真实年龄几何 |
| 共同UV | 各目标自己的投影/ROI，统一源canonical/拓扑/UV，未知RGBA0，完整37注册和往返 | 纹理完整、自然、身份保持和接缝质量未签收 |
| worker/会话/缓存 | 独立研究处理器、服务、HTTP所有权、缓存、明确源龄恢复、取消/TTL/释放已有真实验证 | 不能把研究app接线直接称为生产年龄API |
| 连续显示与导出 | 独立研究页、BLEND、小数显示、DataTexture和无损PNG/GLB；固定Canary软件配置12帧闭环 | 稳定Chrome/Edge真实服务和普通图形配置出口仍未通过 |
| 身份评价与遮罩工具 | 原照片域校准、原生像素mask编辑器和三指纹草稿导出已实现 | 原照片参考值不能直接成为稀疏渲染域阈值；编辑器不是人工质量批准 |

生产入口`backend/src/agemorph3d/app.py`中的`/api/aging`当前仍直接抛`model_not_ready()`。新会话必须继续保留能力门禁。

## 4. 最新额头候选的准确结论

固定10源/37真实生成目标，重点为`fgnet-004a63--sam-020/045/063/070`。没有新SAM生成或拟合；只改四张图的明确额头皮肤，其余33条review完整继承。63是文件名研究标签的同龄条件，API源龄仍为`unknown/null`，生成条件不当真实年龄。

四目标新增原图允许像素79,432/77,777/75,228/73,345；保护区新增放行0，旧allowed移除0。继承镜片/镜框/鼻梁架保护及12原生像素方形边界，不放行镜片内可见眼睛；使用已有离线OpenCV LINE8规则，不声称等同交互编辑器的像素中心规则。

四目标新增有效UV点5,329/5,143/5,151/5,125，分类变化仅为目标mask拒绝5→采样6。旧sampled RGBA、源几何、目标投影与其他33图集保持；当前重点只覆盖UV面部域约33.15%—33.49%。未知区没有填色、源回退、镜像或补画。

| 检查 | 实际结果 | 关键证据 |
| --- | --- | --- |
| 新mask/注册 | 33输入先冻结；四组独立像素一致；完整37注册，1221输入/23注册源码 | [mask审计](../output/research/real-candidate-20261026/mask-audit.json)、[注册收据](../output/research/real-candidate-20261026/registration-receipt.json) |
| 当前渲染成对比较 | 同一当前viewer下两版各376帧、296配对；合计752帧 | [独立渲染差分](../output/research/real-candidate-20261026/render-delta-audit-v1.json) |
| 保存PNG/GLB | 952指纹前后不变，94个GLB独立解析；32重点画面改变，344非重点画面RGBA完全一致 | 同上；旧截图viewer版本不同，不能直接当本轮唯一基线 |
| 身份与年龄 | 两版分别重新评分，各376帧中218成功/158 NO_FACE，各296配对中145有效/151失败 | [共同有效集合比较](../output/research/real-candidate-20261026/paired-quality-delta-v1.json) |
| 指标差值 | 有效集合进入/退出0，共同9源不含重点004；可评分配对指标delta0，无有效源配置保留null | [独立算术审计](../output/research/real-candidate-20261026/independent-quality-audit-v1.json)：5459次数值比较、0差异、最大误差2.22e-16 |
| 真实浏览器往返 | Chrome/Edge37×2=74次通过，407份子报告/导出/截图指纹 | [浏览器收据](../output/research/real-candidate-20261026/browser-roundtrip-verification.json) |
| AI视觉复核 | 全部四图×八配置已查看；额头增加，眼区/侧面大缺口及硬边仍存在，32重点帧仍全部NO_FACE | [AI观察](../output/research/real-candidate-20261026/render-visual-review-v1.json)、[对照板索引](../output/research/real-candidate-20261026/visual-plates.json) |
| 资源 | 四次评价models_closed，捕获/浏览器服务关闭；当次六端口无监听 | [Windows快照](../output/research/real-candidate-20261026/network-resources.json) |

原照片域身份参考值`0.30832315136297866`没有迁移成渲染阈值，`quality_threshold=null`。共同有效集合不含重点004，因此零差值不能解释为重点样本改善；缺失现象也不能证明`NO_FACE`的唯一原因。独立保存数值复算不是独立模型重跑或独立人群评价。

历史上游拟合分母为59请求、55成功、4失败：2个aligned-source多脸、2个原图负控无人脸。37生成目标自身拟合全部成功，不能写成41个生成目标。

## 5. 下一阶段怎么接

| 顺序与负责人 | 先做什么 | 验收出口与依赖 |
| --- | --- | --- |
| 1，接手助手 | 执行第7节只读指纹检查，读取上述证据、规则和当前源码 | 区分最新发布与历史批次；不自动重跑现有实验或改质量标志 |
| 2，模型/评价负责人A与真实人工审核者 | 基于已有32组重点对照明确mask、眼区、侧面、未知边界与外观问题；保存可追踪审核记录 | 人工身份和审核范围必须真实；没有人工记录不能把human_review_completed置真。新候选另立观察依据、版本、冻结和全量对照，不在旧批调参 |
| 3，前后端负责人B；可在等待人工时独立推进 | 先从现有固定源码的无模型ASGI最小复现查稳定浏览器消费/完成标记问题 | 保持no-store、实际chunk预算、EOF/长度、超时、取消和失败；提出新候选前给出针对性反例与可证伪条件 |
| 4，B与A交叉复核 | 最小候选成立后，再按原协议新建计划，运行稳定Chrome/Edge真实HTTP显示/导出/原始恢复 | 原始/目标/中间显示、RGBA/几何/源龄/provenance及资源均需实际通过；不能用静态74往返、Canary12帧或replay替代 |
| 5，A与B | 持续补齐允许用途独立/高龄数据、训练重叠、年龄本域校准、身份渲染域适用性、合格年龄形状和许可 | 逐项达到G3出口后才开放对应能力；按现有总计划管理，不因本轮注册通过放开生产 |

A/B沿用既有两人计划的职责划分，未指定真实姓名；这里是接续顺序，不是新增完成承诺。只处理当前用户授权任务，不因本文自动启动训练、下载模型、申请数据或新批推理。

稳定浏览器这条线已有反例：`arrayBuffer`原生预算候选因SW/H2超预算反例撤回，`pipeTo`/BYOB也未修复完成标记。研究后端`_LeasedResponse.__call__`已经单次发送ASGI body，不能再次包装成新修复。实际客户端仍是`ResearchSessionApi.bytes()`的有界流读取。完整前瞻条件见[显示协议](research-session-display-v1.json)和[响应审查协议](research-framed-response-v1.json)。

## 6. 代码入口，不要从零重写

| 入口 | 职责 |
| --- | --- |
| [observed_skin_candidate_probe.py](../tools/observed_skin_candidate_probe.py) | `extend_masks`、`build_review`、`run`；新额头mask，四角色闭合指纹与原子输出 |
| [target_uv_probe.py](../tools/target_uv_probe.py) | 完整目标自有投影注册、共同UV、分类/GLB |
| [research_aging_pipeline.py](../backend/src/agemorph3d/research_aging_pipeline.py) | `ResearchAgingProcessor.stage_condition/register_reviewed/__call__/close`；真实stage与审核注册分离 |
| [research_aging_service.py](../backend/src/agemorph3d/research_aging_service.py) | `ResearchAgingService.create/stage/register/absolute/asset/close`；会话和资产所有权 |
| [research_aging_app.py](../backend/src/agemorph3d/research_aging_app.py) | 独立研究HTTP app、`_LeasedResponse`、审核和绝对年龄入口 |
| [aging_sessions.py](../backend/src/agemorph3d/aging_sessions.py) | `AgingCoordinator.generate`、worker/会话/缓存；unknown绝对年龄拒绝与明确源龄恢复 |
| [research-session.ts](../frontend/src/research-session.ts)、[研究页](../frontend/research/session.ts) | 研究HTTP客户端、实际字节读取及连续显示页面 |
| [research-session-live.mjs](../frontend/tests/research-session-live.mjs) | 真实live显示harness，要求显式AGEMORPH_SESSION_BROWSER_PLAN |
| [research-mask-editor.ts](../frontend/src/research-mask-editor.ts)、[编辑页](../frontend/research/mask-editor.ts) | 原生像素标注、遮挡优先、两张L8 PNG及三指纹未提交草稿 |
| [viewer.ts](../frontend/src/viewer.ts)、[research-rgba.ts](../frontend/src/research-rgba.ts) | 查看器研究bytes入口、DataTexture与无损RGBA导出；本轮未改这些文件 |
| [render_evaluator_probe.py](../tools/render_evaluator_probe.py) | 新画面身份/年龄评价、源均权与固定bootstrap；年龄复用本版新identity框/失败 |

## 7. 本机环境与可直接用的起步命令

以下路径在准备交接时已检查存在；版本来自本批冻结记录，切换机器后需重新核对。

| 用途 | 路径或版本 |
| --- | --- |
| 后端/身份/测试 | `backend/.venv/Scripts/python.exe`，Python3.11.16；身份环境38包 |
| 年龄评价 | `data/research-envs/mivolo-cpu/Scripts/python.exe`，冻结35包；与后端/SAM环境隔离 |
| Node/npm | `D:/JAVA run tools/node.exe` v24.14.1；`D:/JAVA run tools/npm.cmd` |
| 前端依赖 | 冻结Playwright1.64.1、Vite8.3.4、Three0.186.1；以package-lock和运行冻结为准 |
| 实际静态往返浏览器 | 当次Chrome156.0.8078.48、Edge156.0.4314.42；未来运行重新冻结可执行文件和版本 |
| graphify解释器 | `C:/Users/ASUS/AppData/Roaming/uv/tools/graphifyy/Scripts/python.exe` |
| graphify封装与输出 | `output/research/mask-replay-20261023/graphify_local.py`；`output/research/project-knowledge-20261023/graphify-out/` |

后端使用项目3.11解释器，约束见`backend/pyproject.toml`。以下第一段仅用标准库读取12个已发布/交接指纹，不使用Git、项目推理模块或模型；它已在准备交接时实际执行通过。

```powershell
Set-Location -LiteralPath 'D:\project file\AgeMorph3D'
@'
import hashlib, json
from pathlib import Path
root = Path.cwd()
pub = json.loads((root / 'output/research/git-publication-20261026-observed-skin/publication-result.json').read_bytes())
study = json.loads((root / 'output/research/real-candidate-20261026/final-handoff.json').read_bytes())
for pin in [*pub['files'], study['verification'], study['independent_final_review']]:
    raw = (root / pin['path']).read_bytes()
    assert len(raw) == pin['bytes'], pin['path']
    assert hashlib.sha256(raw).hexdigest() == pin['sha256'], pin['path']
print(pub['status'], pub['commit'])
print(study['status'], study['summary'])
'@ | & 'backend/.venv/Scripts/python.exe' -
```

需要定位代码时，使用现有受限graphify封装查询后再读源码：

```powershell
& 'C:/Users/ASUS/AppData/Roaming/uv/tools/graphifyy/Scripts/python.exe' `
  output/research/mask-replay-20261023/graphify_local.py `
  query 'ResearchSessionApi bytes' --budget 1500
```

只使用v3 guard封装：阻止Git、其他外部进程及网络，只允许Python AST worker。现有图4684节点/11679边/190社区，0悬空、9自调用、312个无source_location的AST节点；它不是完整语义图谱或运行验收证据。代码修改后按已提供的全局规则更新本地图谱；本次只是文档整理，仅执行了查询。

修改相关源码后可运行针对性检查；没有新变更或未解决疑问时，不为交接重新执行已通过大批次：

```powershell
& 'backend/.venv/Scripts/python.exe' -m pytest backend/tests/test_observed_skin_candidate_probe.py -q
& 'backend/.venv/Scripts/python.exe' -m ruff check --config backend/pyproject.toml tools/observed_skin_candidate_probe.py backend/tests/test_observed_skin_candidate_probe.py
& 'backend/.venv/Scripts/python.exe' -m ruff format --check --config backend/pyproject.toml tools/observed_skin_candidate_probe.py backend/tests/test_observed_skin_candidate_probe.py
```

最新候选批实际记录为33项新增/完整2058后端通过，1条既有Starlette弃用警告，Ruff/格式通过。前端203项及构建属于此前mask-editor批的通过记录，本轮没有前端源码变更，不应改写为本轮重跑结果。

## 8. 复现与操作中容易踩的坑

本机研究包装器是单次批次编排，不是幂等只读命令：`registration_driver.py`固定HERE，要求旧plan/freeze/log不存在；`quality_driver.py`固定两个variant目录且要求fresh；`evaluation_driver.py`的freeze/verify都创建新文件；`final_verify.py`要求`verification.json`不存在。它们位于`output/research/real-candidate-20261026/`。不要为了确认保存结果直接重跑，也不要删除旧输出让其通过。新实验需新版本目录、计划、源码/输入/环境冻结及明确观察上下文。

旧conservative捕获viewer与当前不同，本轮因此重捕两版。今后若renderer改变，也要明确控制其影响。每个capture-plan的直接JSON输入只能有一份target-uv报告，重复协议ID会导致findDocument歧义。

真实评价的`completed_with_failures`退出码1与完整性失败分开：本轮四次评分均保留158失败帧，`integrity_status=passed`且`models_closed=true`。年龄必须用同一新variant的检测记录，不能复用旧框或删失败名单。

本批留存失败包括finite-JSON修复前日志、绝对输出路径拒绝、旧stage6保护清单误用、比较器混淆外部可执行路径/历史漂移与当前依赖。见[最新复核记录的失败段落](真实额头候选注册与质量复核.md#保留的问题与失败)；v1/v2脚本、日志及修正收据保留。两份旧保护清单中的README/忽略规则差异在本批开始前就存在，本批保持的是当前起点，不要还原为旧hash。

Git发布曾被检查器误要求URL带`.git`后缀阻断；用户确认后修正等价URL校验，原远端未改，最终184ffbfd发布成功。日志在`output/research/git-publication-20261026-observed-skin/`。`https://github.com/xiaominaimoyu/AgeMorph3D`与其`.git`形式须按同一批准仓库核验。

## 9. 必须传给新会话的操作约束

用户提供的《AGENTS.md》第三节要求：任何Git相关操作前先确认本次精确文件清单；先读取`.gitignore`，扫描全部待提交文件，发现敏感/违规项或Git错误后停止并按规则等待人工干预。只暂存获准清单，不用`git add .`、`git add -A`或`--all`，不擅自强推；完成后给文件清单和hash。旧10文件授权已执行结束，不覆盖本文或下一批新变更。

`.gitignore`不能修改或删除，模型、数据集、环境、日志、output产物、私密照片和本地AI缓存不进入源码仓库。工程检查、AI观察、人工质量、独立评价和生产资格分开陈述；未知源龄不填默认值，用户源龄不附estimated-only calibration_id，未知RGBA不填补。生产服务和能力门禁继续保留，研究服务只绑定loopback。

每项实现先检查编码规则及六份根说明，最小改动，保留原资产和失败。`~/.config/opencode/skills/opencode-md/SKILL.md`在本会话检查时仍不存在，采用用户已完整提供的内联原则。项目根AGENTS文件此前未找到；不要伪造已读取的本地文件，优先遵守实际用户指令和可读规则。

本次交接只新增本文，并在忽略研究目录保存检查证据；没有修改已发布10文件、历史封口或全局记忆，也没有提交推送交接文档。

## 10. 新会话可直接粘贴

```text
项目在 D:\project file\AgeMorph3D。请先读取 docs/2026-10-26_会话交接-AgeMorph3D-report.md，按其中阅读顺序和非Git只读指纹检查恢复上下文。最新已核验发布为184ffbfd317eefb1e3cfdbabe4e836b8b019be88；额头候选37注册/752帧/74往返工程完成，但重点32帧仍NO_FACE，质量及G3关闭。

在我要求继续开发时，先核对当前源码和保存证据，再按交接第5节推进最小可验收任务。需要人工复核的质量项不能代签；等待人工期间可先推进稳定Chrome/Edge真实研究会话的无模型最小诊断。不要重复已完成额头批、重提已撤回arrayBuffer预算候选或把既有单次ASGI body发送当新修复。任何新模型/浏览器批次先明确冻结与出口，保留未知和失败分母。执行Git前仍需确认本次精确清单；本文尚未提交。
```
