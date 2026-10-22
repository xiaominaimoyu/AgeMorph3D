# BLEND 连续显示与源龄锚点研究

2026-10-22。首轮98例在Chrome、Edge中的加载、导出及再导入检查均通过，但精确源点从相邻BLEND切回原始MASK时仍有可测画面跳变，渲染连续性未签收。接续[G3后续开发计划](G3分项验收与后续开发计划.md)的隔离显示试验；开发基线为本地提交`37b99fdd9c005a78d473cc09b903c1b526145f6c`。本批复用37个已注册SAM atlas和10个原始源资产，不运行新的SAM/重建推理。几何沿用静态回退，插值只描述已有纹理的显示混合，不代表真实小数年龄生成或身份/年龄质量通过。

协议为[blend-display-v1.json](blend-display-v1.json)，补充对照为[blend-display-controls-v1.json](blend-display-controls-v1.json)。补充对照在新结果生成前由源码审查提出：MASK与BLEND的过滤/深度写入差异可能令精确源点产生跳变；仅比较源点左右两个BLEND帧会漏掉这个问题。因此分别记录左邻→原始源点、原始源点→右邻以及同原图仅切换材质的结果。

## 实现与输入边界

[离线生成工具](../tools/blend_display_probe.py)核验报告与逐资产指纹，解析原始和N4 GLB的位置、法线、有序索引及UV，要求源 canonical 数组指纹保持一致。输入PNG必须二值alpha，未知区域RGBA为零。8个已知源龄标签仅作为镜像文件名研究字段，替换同龄SAM锚点；精确源龄直接复制原始GLB/PNG字节。两个未知源龄继续没有原始绝对年龄锚点，仍可作SAM目标条件间的离线显示比较，不能因此获得绝对年龄API能力。

其余采样先将sRGB解码到线性光，对RGB预乘alpha后同时插值颜色和alpha，再量化为直通sRGB RGBA PNG；双方未知保持全零，单侧有支持的区域表示淡入/淡出，不标为新增观测。非源点主资产用glTF BLEND，并提供相同PNG/几何的MASK基线；精确源点保留原始MASK主资产，另有同图BLEND材质控制。生成资产没有形状动画或年龄morph目标，API源龄仍为unknown。

98个唯一采样包括10源的20/70边界、8个精确源点、27个原区间中点左右各0.001岁、8个源点左右各0.001岁。35组邻域比较分别保留27个区间与8个源点请求。只有一个epsilon步长，不将这些诊断写成极限连续性证明。

初始98个输入pin先冻结；实现完成后另冻结106个输入/源码pin。原始输入冻结不覆盖；补充材质对照另入实现冻结。[浏览器脚本](../frontend/tests/blend-display-research.mjs)运行前再冻结18个报告/协议/前端源码与依赖清单pin。各冻结和源码快照保存在[本批输出目录](../output/research/blend-display-20261022)。

## 浏览器测量口径

实际FaceViewer、GLTFLoader和导出器在Chrome/Edge软件WebGL中逐例加载、导出、再导入。比较几何/UV数组、材质透明模式、alpha和未知区；原始二值源点要求像素精确。半透明RGB可能经过浏览器canvas预乘/反预乘量化，因此另列直通RGB与黑/白背景合成误差，不要求所有半透明RGB字节相等。

固定前视角、viewport，关闭网格和自动旋转，显式渲染后分别采集黑/白背景帧。输出是ACES色调映射后的sRGB画面差异，与原始线性光atlas诊断分列。35组全部测量；8个源点额外测量MASK/BLEND材质控制，另测两组MASK基线。浏览器与随机端口loopback服务器由试验脚本拥有并在finally中关闭；生产界面、API及能力开关不参与试验。

## 首轮结果与证据

以下仅对应`output/research/blend-display-20261022`保存的首轮输出。浏览器报告中的`passed`表示传输、结构与脚本断言通过，不能解释为年龄质量或连续性通过。

| 证据 | 观察结果 | 可以支持的结论 |
|---|---|---|
| [离线生成报告](../output/research/blend-display-20261022/atlas-display/report.json) | 10源、37个SAM锚点输入，生成98例、35组配对，其中27组区间与8组源点邻域 | 采样请求和失败边界明确；几何保持静态 |
| [独立产物核查](../output/research/blend-display-20261022/independent-producer-audit.json) | 核对106个生成输入、18个浏览器计划及294个产物pin；98例几何/UV与N4源不变量一致；8个原始源GLB/PNG复制逐字节相同 | 输入资产与对照关系保持完整；不等于浏览器重序列化后的GLB字节不变 |
| [浏览器完整报告](../output/research/blend-display-20261022/browser/blend-display-browser.json)、[摘要](../output/research/blend-display-20261022/browser-summary.json) | Chrome、Edge各98例、35组配对及8个同原图材质对照，共196例加载/导出/再导入检查；均无页面错误或外部请求 | 首轮真实查看器传输链可运行，源龄材质跳变仍须单列 |
| [源点与材质控制摘要](../output/research/blend-display-20261022/browser-summary.json) | 两浏览器源点阶跃及同图仅换材质的RMS范围均为0.00203625—0.01997746，口径为归一化sRGB画面通道差异 | 相同图像与几何只改材质即可复现跳变，不能将该跳变归因于年龄内容变化 |
| [原始导出PNG核查](../output/research/blend-display-20261022/raw-export-png-audit.json) | 首轮只持久保存8个导出GLB，覆盖4例×2浏览器；其中4个半透明导出有RGB变化，最大1字节；全部alpha与透明未知区精确 | 浏览器canvas域相等不代表输入与导出原始PNG像素相等，其他188个内存导出没有这项原始PNG核查 |
| [资源记录](../output/research/blend-display-20261022/resource-audit.json) | 脚本退出码0，浏览器关闭记录及两个自有loopback服务清理通过，复查无剩余监听 | 本轮自有资源退出已记录；不代表生产服务或长时性能验收 |

代表性区间`fgnet-004a63`的66.499→66.501比较中，黑背景BLEND画面RMS为0.00114748，MASK基线为0.20675724；白背景分别为0.00132204和0.26260812。这是两组所选MASK基线之一，不能扩展为所有区间、视角或设备的质量结论。源点邻域中，左右两个BLEND帧可以相同，但它们与正中的原始MASK帧不同；只看左右之差会漏掉精确源点问题。

查看首轮结果后，又用已经采集的帧哈希作事后解释：每个浏览器的8源×左右邻域×黑白背景共32次比较，全部与同源、同图的BLEND控制帧一致，没有新增浏览器运行。这个单步长现象支持继续试验“全程统一BLEND”的显示策略，不能视作预先冻结的独立连续性验证。

## 误差口径与剩余限制

首轮196次往返在浏览器canvas解码域报告alpha变化为0、RGB误差为0；两端都先经过canvas时，第一次PNG预乘/反预乘产生的变化可能已被共同吸收。因此另用Pillow直接解码输入atlas和已保存GLB内的PNG，得出上述8份原始导出的结果：2份精确源点导出的原始RGBA相同，6份显示混合导出中4份有RGB变化，最大黑/白线性合成通道误差均为0.00362924，最大黑背景RMS为0.00085845。原始PNG核查并未覆盖全部196份导出，也不要求重新编码后的PNG压缩字节相同。

glTF MASK与BLEND会改变alpha阈值、深度写入和渲染队列；即使源PNG只有0/255 alpha，GPU线性过滤仍能在边缘产生中间alpha。BLEND又不对单个网格内部的三角形逐个排序，源点切换可包含过滤与遮挡顺序两类影响。本轮同图材质对照测到的是它们的合并效果，没有分别定量归因。固定前视角、软件WebGL及单个0.001岁步长不能证明任意视角连续、收敛极限或硬件性能，也没有制定视觉质量阈值。

8个文件名研究源龄仍未成为API用户填龄或模型估龄，两个未知源没有获得默认年龄；所有原始和派生GLB的API源龄保持unknown。纹理支持区、外部遮挡、接缝、年龄效果、身份保持、许可和真实服务出口继续未签收；静态几何与已有纹理混合均不构成G3通过。

## 后续修正的边界

首轮保留“精确源点原始MASK、邻域BLEND”的历史结果。后续交互修正采用统一BLEND显示，并把显示衍生资产与原始GLB/PNG恢复分别记录，过程单独登记于[交互式研究纹理显示与源龄恢复](交互式研究纹理显示与源龄恢复.md)。截至2026-10-23整理时，该批修正已完成本机工程验证，新结果只在独立报告中记录，不据此提升首轮连续性、年龄、身份或生产验收状态。

## 复现

在项目根目录运行。依赖本机已有的被忽略研究资产和冻结清单；请选择新的输出目录。浏览器命令核验原冻结生成报告，不自动转用上一步的复算结果。首轮源码快照分别保存在[生成工具快照](../output/research/blend-display-20261022/source-snapshot-producer)与[浏览器快照](../output/research/blend-display-20261022/source-snapshot-browser)。首轮18个浏览器pin在该轮运行前通过核验；当前`viewer.ts`已进入后续交互修正，直接执行下方首轮浏览器命令会因源码pin变化而拒绝。

重跑首轮时，应在独立副本中恢复匹配`source-snapshot-browser`的冻结前端源码，不能覆盖当前工作树或改写原计划来冒充首轮重跑。若评估当前实现，应另冻结新方案并保存为新的开发实验；交互修正有单独的21个pin计划与复现说明，见上一节链接。

```powershell
.\backend\.venv\Scripts\python.exe tools/blend_display_probe.py `
  --study-plan output/research/blend-display-20261022/study-plan.json `
  --output-dir output/research/blend-display-reproduction/atlas-display

$env:AGEMORPH_BLEND_REPORT=Join-Path (Get-Location) 'output/research/blend-display-20261022/atlas-display/report.json'
$env:AGEMORPH_BLEND_REPORT_SHA256=(Get-FileHash -LiteralPath $env:AGEMORPH_BLEND_REPORT -Algorithm SHA256).Hash.ToLowerInvariant()
$env:AGEMORPH_BLEND_PLAN=Join-Path (Get-Location) 'output/research/blend-display-20261022/browser-plan.json'
$env:AGEMORPH_BLEND_OUTPUT=Join-Path (Get-Location) 'output/research/blend-display-reproduction/browser'
node frontend/tests/blend-display-research.mjs

.\backend\.venv\Scripts\python.exe -m pytest -q backend/tests
```
