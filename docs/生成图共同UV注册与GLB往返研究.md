# 生成图共同 UV 注册与 GLB 往返研究（N4）

2026-10-21，完成既有 37 张 SAM 生成图的共同 UV 离线注册，覆盖 10 个原始源。每张图使用自己的完整重建、投影和 ROI 取样；同一源所有目标的输出几何、法线、有序三角形和 UV 完全相同，继续遵守 N3 的 `static_fallback`。37 个自包含 GLB 的数组、嵌入 PNG、RGBA 和透明未知区均通过离线解码检查，Chrome/Edge **74/74 次真实加载、导出和再导入通过**。

本轮是**研究版纹理注册与传输验证**。生成像素明确标为生成内容，不是原照片观测，也不是已经验收的年龄纹理。眼镜、刘海不确定区及其他未支持区域采用保守排除，保留明显透明空区；没有补全后脑、额头、眼镜下方皮肤或嘴内。正式年龄效果、身份、视觉接缝质量与许可仍未签收；`service_ready=false`、`age_texture_quality_accepted=false`、`g3_complete=false`，生产按钮和 `/api/aging` 未开放。

## 1. 范围与固定输入

规则见[共同 UV 机器协议](uv-registration-v1.json)，沿用[N0 评价协议](年龄研究评价协议.md)、[N1/N2 重建研究](同人跨龄与生成图重建研究.md)及[N3 路线结论](年龄形状路线比较与研究校准.md)。全部 37 张为 N0 已有目标和同龄条件合并去重后的集合，未挑选有利样例：31 张有源照片文件名年龄标签，6 张为 `official-866/astronaut` 的未知源龄技术样例，同龄对照共 8 张。

| 固定输入 | SHA-256 / 用途 |
|---|---|
| N0 manifest | `f511c773e8fc3d44ec007d390d1e89be93275df1e4cbf56773a14a79d9d02019`；身份用途不变 |
| N2 generated report | `e0e9432e653062261b4018416c409105106c3c9439d0da773712efc1adf40a76`；原图、目标图及各自拟合 |
| N3 selection | `50481ef306da23fde80fb5bc13a5d6e203342adf71a9cc770be9d20f4dcd905b`；静态几何回退 |
| 裁剪 BFM | `aa9e819661adec8ee97ebd82930a28f05dd64c5e61c57e52c98abb2152fb3c3b` |
| 已绑定共同 UV | `7e412e7e1f7337816db7175c2db0020854b9a77292e7582763e9d45b06e3ad7b`；38,365 顶点，原顶点顺序 |

共同 UV 复用 `output/backend/b45/combined-real/uv_bound.npz`，其拓扑为 `cc449ed7efa2860bed64be0a7e29ad8944912148c69f938ff768c8766d65e7cb`。不直接混用仅含 `uv/source_indices` 的未绑定文件。所有 NPZ 读取禁止 pickle。

原 N2 的 4 条失败仍附在新报告中：`013a21/067a23` 原图 `NO_FACE`，`012a27/082a27` 对齐图 `MULTI_FACE`。后两者各自的 SAM 目标重建成功，不能因对齐图失败删除其 8 个目标。保留组年龄结果未打开，没有新模型推理、SAM 生成、训练、下载或许可状态修改。

## 2. 注册与遮挡处理

实现由[目标图注册函数](../backend/src/agemorph3d/target_uv.py)、[投影器](../backend/src/agemorph3d/uv_texture.py)和[离线编排工具](../tools/target_uv_probe.py)组成：

1. 绑定 N0 任务、目标图、完整拟合、模型、UV 和 mask 的路径、大小、哈希及拓扑；mask-review 中的 `target_fit` 也必须对应此目标，引用另一张有效拟合仍会拒绝。
2. 使用目标**含表情的完整顶点**及其自身 projection/ROI，通过共同 UV 的三角形重心坐标投到该目标图像。源相机、源 FFHQ 逆矩阵或放大的源 valid-mask 均不能充当生成图对应关系。
3. 以原生面向和连续 max-Z 排除背面、自遮挡、画外及 UV 歧义；双线性取样前，每个非零权重贡献像素都必须通过目标局部 mask。
4. 将图集附到原始源的固定 canonical 静态网格。只改变 atlas，不累计年龄编辑，不用目标包围盒重新归一化输出几何。

### mask 的证据边界

[逐图审查记录](../output/research/age-stage4-20261021/mask-review.json)绑定全部 37 张目标及各自 mask。先实际查看原图和 overlay，再计算图集。保守区域来自每张目标自己的 68 点：0—26 点凸包、9×9 侵蚀；60—67 点嘴内凸包膨胀 7×7 后排除。4 张 `004` 的眼镜候选带完整排除；10 张 `astronaut/062/005` 的刘海附近不确定带排除。具体边界和复现参数均写入机器协议及逐图记录。

独立预审发现首版眼镜带漏掉了下镜框，已在任何 atlas 结果之前将这 4 张的排除带延长至图像行 650，并重新查看原尺寸图和 overlay。旧 review JSON 作为已废弃草稿保留；其 mask 路径已指向修正版本，不能拿旧 hash 当可复现的最终输入。冻结只绑定修正后的 review 和 mask。

这是模型辅助的开发用途可见问题审查，**不是人工独立分割真值或自动遮挡检测**。较宽的排除带也会舍弃可见皮肤；`mask_rejected` 同时包含保守支持区之外和疑似外遮挡，不能全部算作外遮挡量。`006/057` 的胡须仍作为生成外观保留，不能据此声称获得皮肤层或排除了全部毛发。

源 FFHQ valid-mask 只描述源裁剪的重采样支持，没有迁移到生成图。生成图所有 37 张均为 1024² PNG，EXIF 方向为恒等，与其 N2 投影像素坐标一致。

### 分类与透明未知区

256² 图集使用互斥的 7 类状态，按 UV 外→重叠→背面→画外→自遮挡→目标 mask 拒绝→生成取样的覆盖顺序分类。37 张共 2,424,832 个 texel：

| 类别 / 代码 | texel 数 |
|---|---:|
| UV 外 / 0 | 746,697 |
| UV 重叠歧义 / 1 | 0 |
| 背面 / 2 | 182,657 |
| 画外 / 3 | 232 |
| 自遮挡 / 4 | 10,377 |
| 目标 mask 拒绝 / 5 | 801,243 |
| 已取样生成像素 / 6 | 683,626 |

原始 `classification.png` 保留 L 模式数值 0—6；`coverage.png` 才是二值 0/255，另有着色预览。全部未取样 texel 的 RGBA **逐值为零**，alpha 仅 0/255；不镜像、不扩张颜色、不修复、不跨未知区融合。生成 metadata 移除了 `observed_*` 原照片字段，单列 PNG 文件 pin 与 `uint8_0_1_row_major` mask 数组 hash，避免混淆。

## 3. 实际覆盖与接缝

各目标相对于共同 UV 面部区域的有效生成取样比例如下；分母是固定的 45,355 个 UV 面部 texel，不是整张 65,536 texel 图集。

| 原始源 | 目标数 | 面部取样比例范围 |
|---|---:|---:|
| official-866 | 3 | 44.69%—45.61% |
| astronaut | 3 | 42.57%—43.00% |
| 012a27 | 4 | 43.22%—44.78% |
| 082a27 | 4 | 36.68%—37.43% |
| 004a63 | 4 | 18.77%—19.57% |
| 006a55 | 4 | 46.39%—46.71% |
| 062a45 | 3 | 40.70%—41.24% |
| 005a35 | 4 | 42.47%—42.93% |
| 057a25 | 4 | 45.44%—46.00% |
| 003a38 | 4 | 45.12%—45.62% |

相对于整张 atlas 的覆盖仅 12.99%—32.32%。`004` 的低覆盖主要是主动舍弃整条眼镜区域；透明额头、眼区和嘴内不是完整脸部纹理。不会把这些空区填成“已观测”。

共同拓扑具有 113,781 条共享索引边、657 条开放边界边，非流形边为 0；全部目标 UV 歧义 texel 为 0。每个顶点只存一个 UV，共享索引边连续；独立复核没有重复 UV 坐标，开放边界顶点度数为 2。合成线性 RGB 平面的共享边测试检查无错误裂口和颜色跳变。

真实图集同时保存有效区相邻 RGB 跳变和 alpha 边界数。照片自身的眼睛、嘴唇、阴影也会产生较大跳变，因此不把邻接色差直接当接缝误差或自定质量阈值；没有做色彩均衡、光照分离或接缝美化。未知区边界仍可能影响外观，结构检查和像素传输检查不等于视觉质量签收。

## 4. GLB 与浏览器检查

全部 GLB 均为原始源静态几何，内嵌 PNG、`TEXCOORD_0`、MASK alpha（0.5）和 CLAMP_TO_EDGE，没有外部 URI、年龄 morph 或动画。API 形式的 `source_age` 保持 unknown；原照片文件名标签仅放在独立研究 provenance 中，不冒充用户填写或年龄估计。材质名称明确为 `Registered_Generated_Surface`。

Python 对全部 37 个 GLB 重新解码，逐数组比较位置、法线、有序索引、共同 UV，以及原 PNG 字节、解码 RGBA、透明和注册来源；同一源的四类几何/UV hash 固定。查看器自身的归一化包装不能证明共同坐标，验证使用局部 position 属性与源 canonical 元数据。

浏览器入口为[批量研究脚本](../frontend/tests/target-uv-research.mjs)，调用实际 FaceViewer/GLTFLoader 的加载、GLB 导出和再导入，固定全部 37 个目标、Chrome/Edge 各一次。比较局部几何、UV、RGBA、alpha/未知区 hash、flipY、sRGB、UV 通道、采样、材质与注册 provenance；保存正面、侧面和再导入截图，禁止外网素材及模拟模型服务。汇总见[浏览器记录](../output/research/age-stage4-20261021/browser-all/target-uv-browser.json)。

实际 **74/74 通过**，position/normal/UV 的最大往返差均为 0，解码 RGBA、alpha 与未知区 hash 相同；没有页面错误或外网请求，37 个子任务均关闭所属服务器，最终 loopback 端口已释放。原始截图共 222 张。已查看 37 张 Chrome 正面，以及按固定顺序每源首目标的 10 张 Edge 侧面和 10 张再导入正面；[正面总览](../output/research/age-stage4-20261021/browser-front-contact-1.jpg)、[侧面总览](../output/research/age-stage4-20261021/browser-side-sources-contact.jpg)保留原截图的裁切拼图，原图不覆盖。

复看未见 UV 上下翻转或导出造成的数据偏移，但透明额头、嘴内、鼻孔及侧脸未支持缺口明显，眼镜样例只剩下半脸，256² 二值 mask 边缘可见阶梯。原图阴影与查看器光照也仍影响外观。故浏览器传输通过，**视觉接缝和完整纹理质量继续未签收**；没有为了截图填洞或改变 mask。

## 5. 数值复核、版本与复现

独立[数值审查](../output/research/age-stage4-20261021/independent-numeric-audit.json)核对 432 个唯一文件 pin，直接从原源拟合重算 canonical 顶点、法线和有序面，并独立解析 GLB。每张抽 24 个取样点，共 **888 个**：独立寻找 UV 三角形、计算重心坐标、使用目标投影手算 RGB 双线性及 mask 支持，全部逐值一致；另有 **756 个分类点**通过独立三角形/max-Z 复核。没有重跑完整 projector 或模型推理。

反例中，若错误使用原源 projection，888/888 个抽样 RGB 均改变；若去除目标表情，795/888 改变。这证明该输入链不能由源相机或中性几何替代，不构成年龄或身份真实性证明。

首轮 `registration/` 保留。最终 `registration-final/` 在按仓库配置归一化注释、导入及格式后复跑；CLI 的 AST 完全一致。37 个目标的 atlas、分类、coverage、着色预览、NPZ 与 GLB 共 **222 个二进制产物逐字节一致**，数值、源坐标和诊断也一致，见[复跑核验](../output/research/age-stage4-20261021/reproduction-check.json)。各运行的结果 JSON 含不同输出路径，不要求文件 hash 相同。

版本边界明确保留：初始[运行计划](../output/research/age-stage4-20261021/study-plan.json)在 atlas 结果之前冻结；[最终投影运行计划](../output/research/age-stage4-20261021/study-plan-final.json)在首轮结果之后、复跑之前冻结。浏览器首个输入检查发现研究 result 缺少顶层 `topology_id`，在启动浏览器前拒绝；随后仅生成模式改为读取并核对 GLB 已验证的 topology 与源框架，默认照片契约不变。修正后单样例双浏览器 smoke 通过，完整批处理之前另存[浏览器冻结](../output/research/age-stage4-20261021/browser-freeze.json)。这些修订未改变目标、mask、取样算法或选择规则；最终全链源码不是在首次 atlas 结果之前冻结。

当前[复现计划](../output/research/age-stage4-20261021/reproduction-plan.json)绑定更新后的浏览器适配及相同投影源码；其 209 项输入已重新校验，实际 `load_inputs` 预检通过。它是结果之后派生的可运行快照，不能冒充事前计划。保留源快照和各阶段日志，完整汇总见[核验记录](../output/research/age-stage4-20261021/verification.json)。

在仓库根目录，使用已有本地固定输入，输出目录必须不存在：

```powershell
.\backend\.venv\Scripts\python.exe tools/target_uv_probe.py `
  --study-plan output/research/age-stage4-20261021/reproduction-plan.json `
  --output-dir output/research/age-stage4-reproduction/registration

$env:AGEMORPH_RESEARCH_TARGET_REPORT = (Resolve-Path output/research/age-stage4-reproduction/registration/report.json).Path
$env:AGEMORPH_RESEARCH_OUTPUT = Join-Path (Get-Location) 'output/research/age-stage4-reproduction/browser'
Set-Location frontend
node tests/target-uv-research.mjs
```

这些命令依赖未入库的本地研究输入和已审查 mask；新照片必须重新建立目标自身重建、局部 mask 审查及冻结，不能移用本轮 mask 或 pin。脚本仅绑定 loopback，进程和服务器在结束/失败时关闭；本轮不包含独立 SAM worker、服务会话、GPU 准入或缓存实现。

后端新增 57 项测试，最终全量 **1047 项通过**（1 条既有 Starlette/httpx 弃用提示）；前端 **47 项通过**，TypeScript/Vite 构建通过。5 个涉及的 Python 文件按 `backend/pyproject.toml` 通过 Ruff 检查与格式检查，两个研究浏览器脚本通过语法检查。测试与真实图像、浏览器证据分列，不把数量当质量验收。

## 6. 证据对应的结论与后续

| 证据 | 可确认的结论 | 对后续工作的影响 |
|---|---|---|
| 37 个目标自身投影、888 点数值反例 | 共同 UV 注册使用目标像素坐标及完整表情几何 | 后续纹理不得改回源 FFHQ 逆矩阵 |
| 逐图 mask、7 类分区、RGBA0 | 研究排除区与未知区可追踪，取样不会越过支持 mask | 更完整覆盖需要新的遮挡/有效区证据；不擅自填补 |
| 共享边、UV/PNG/GLB 数组核验及真实浏览器往返 | 拓扑、方向、材质与透明数据的传输可检查 | 视觉接缝、光照及身份仍在 G3 分项评价中单独签收 |

N4 技术链完成后，下一项是 N5 的连续年龄与小数策略，再按计划做独立 SAM worker、会话、缓存和资源释放。N3 仍没有可正式采用的年龄形状路线；本轮注册不会改变这一结论，也没有开放正式年龄能力。数据、权重、mask 和输出均留在被忽略目录，本轮未提交或推送 Git。
