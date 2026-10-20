# B4/B5 年龄方向与 UV 开发记录

更新日期：2026-10-20。用户确认没有额外年龄权重或获准校准样例，本批按“先用现有BFM资产推进”完成可独立验证的开发：原生年龄属性方向、精确顶点映射、源年龄输入、真实基础照片UV及GLB往返。**完整第5阶段/G3尚未完成**：没有年尺度校准、绝对目标年龄形变、实际年龄纹理生成或身份质量验收。正式两项年龄能力保持false，`/api/aging`仍503；现有检测/重建清单仍unresolved，G1/G2欠项保留。

本批未提交或推送Git，未修改`.gitignore`、项目依赖/锁文件、原BFM或现有模型清单；B4/B5实现期间也没有下载训练集或SAM权重。2026-10-20 后续已单独获取官方SAM checkpoint与FG-NET研究镜像，来源、哈希和许可边界见 [年龄模型与校准样例获取记录](年龄模型与校准样例获取记录.md)，G3状态不变。前阶段见 [B6记录](B6实时姿态开发记录.md)，当前契约见 [api.md](api.md)。

## 1. G3 分项状态

| 项目 | 已完成证据 | 未通过范围 |
|---|---|---|
| 年龄方向来源/拓扑 | 用户授权BFM原TGZ、逐成员哈希、199维PC/EV/属性公式；53,490→38,365顶点一一对应，全部40PCA逐项零误差 | 不能把属性单位直接解释成年 |
| 源年龄 | UI选填20—70，留空未知、换图清空、重建时快照；user与estimated/unknown语义保留 | 用户填写不是模型估计，也不是方向年尺度校准；没有校准集或估计器 |
| 形状数值 | 原生强度−50—50、零精确不变、连续性、往返及固定源canonical坐标检查 | 未交付20/45/70绝对年龄morph或真实年龄质量 |
| UV/基础照片纹理 | 单图集、原照片双线性采样、自遮挡与背面排除、未知透明、自包含GLB，双浏览器像素往返 | 不是年龄纹理生成；外部遮挡和光照未分离 |
| 年龄纹理候选 | SAM官方源码/环境/输入输出可行性核查；官方checkpoint已下载并做zip/键结构检查；已在独立环境跑通batch=1二维推理 | 实际GPU算子用原生shim替代（自检误差≤1.4e-6）、显存约2.7 GB、稳定前向约0.12 s；FFHQ对齐桥接、连续年龄、逐目标重对齐/UV均未验 |
| 身份保持 | 40身份/10表情系数保持及PNG像素保持有证据 | 不能由此证明人的身份保持；无独立识别模型/阈值/多身份评估 |

## 2. 实现与实际资产

### 原生属性方向

新增`prepare_bfm_age.py`、`age_shape.py`及对应测试。转换器在解压/解析前核对原TGZ和目标BFM的大小/SHA-256，只通过`tarfile.extractfile`读取指定普通成员，不展开归档路径；MAT先检查声明类型/维度/预算，NPZ禁止pickle。通过全部40PCA的完整字节签名证明顶点唯一对应，发现不一致或歧义即拒绝，不用最近点猜测。

[BFM官方说明](https://www.faces.dmi.unibas.ch/bfm/index.php?id=details&nav=1-1-0)提供199个形状主成分及年龄属性方向。原授权TGZ内`apply_attributes.m`仅取前199项并在正负50示例中标注Older/Younger；`coef2object.m`按EV缩放系数。因此派生公式为：

```text
direction = (PC @ (EV * age_attribute[:199])).reshape(-1,3)[vertex_map]
vertices_at_strength = original_vertices + strength * direction
```

原属性有200项，第200项的额外语义尚未证明，严格按示例忽略；不宣称它是偏置或第200个人。原模型与3DDFA修改均值不是同一均值，本批只证明方向所依赖的形状基/顶点对应，不混用均值或UV索引。原生纹理方向也派生以保留来源，但未直接加在照片RGB上。

| 资产 | SHA-256 |
|---|---|
| 用户`BaselFaceModel.tgz` | `d6cf2dffb74404f4f7ee2cd56f611e6fdcb22081ebf993f8b01edf6207f6cce9` |
| 当前裁剪`bfm.npz` | `aa9e819661adec8ee97ebd82930a28f05dd64c5e61c57e52c98abb2152fb3c3b` |
| 派生`prepared-age/age_direction.npz` | `e94e8f294a2a36264a6751eaffdcd4854f7587800de1ccde31d4969424850b5b` |
| 原始`uv.npz` | `d191871a33467b3b6c0565b62469b17e16241efd1683c681ea9550dc9c741228` |

成员哈希、匹配方式和全部绑定见 [provenance.json](../output/backend/b45/prepared-age/provenance.json)。`load_age_direction`再核验派生NPZ pin、目标BFM pin、拓扑、单位及有限数组；`apply_age_strength`只接受−50—50的原生强度，并保留原始40/10系数、投影、ROI、拓扑及输入所有权。零直接返回原对象。

新增`age_research_probe.py`组合真实CPU照片重建、原生方向和可选UV。各强度共用源模型的canonical中心/尺度，避免每次重新归一化掩盖形状变化；纹理始终使用原照片投影，不生成年龄纹理。输出仍static，不含age_20/age_45/age_70，元数据明确`bfm_attribute_strength`、`years_calibrated=false`、`identity_quality_accepted=false`。源年龄可保留unknown，绝不默填30/45。

### 基础照片 UV 与正式静态链路

新增`uv_texture.py`和测试；使用原始BFM底部原点UV，转为glTF顶部原点`(u,1-v)`。UV texel中心通过三角形重心坐标投到原照片，以连续max-Z及原生面朝向排除自遮挡/背面，排除画外与有歧义的重叠内部；RGB双线性取样。未观测区RGBA为0，不做镜像填补、生成或修复。该几何可见性不能识别头发/手/眼镜等网格外遮挡，不能去除源光照。

`static_mesh.py`可写TEXCOORD_0、内嵌PNG、CLAMP_TO_EDGE采样与MASK材质。PNG和UV无外部URI；原顶点、法线及有序三角形保持。`TddfaOnnx`接受可选严格uv资产角色，其安全NPZ必须绑定完整有序topology_sha256并有N×2有限UV；生命周期自检也执行基础纹理投影/编码。`reconstruction.py`使用该UV时在同一工作线程生成带基础纹理的静态GLB，仍保留年龄能力false、texture_url=null及原缓存/取消语义。

实际模型清单没有改写，当前仍严格拒绝未收口许可。研究CLI额外给定的UV必须有显式SHA并使用研究开关，产出的`uv_bound.npz`只是拓扑绑定产物，不自动获得许可或服务readiness。

前端新增拍摄时年龄控件；验证提交快照、换图清空和未知值。内嵌图像、声明年龄纹理的资产及外部贴图请求均检查UV，拒绝缺失/不匹配/非有限数据；基础贴图失败提示不会被成功消息覆盖。无纹理静态资产保持可加载。浏览器往返脚本增加可选纹理模式，比较解码RGBA、方向、色彩空间、UV通道和采样，不只比较几何。

### SAM 候选限制（2026-10-20 补充）

本轮已下载官方 checkpoint，并在独立环境 `data/envs/sam` 用纯 PyTorch 算子替代跑通 batch=1 推理，详见 [SAM 独立环境配置](SAM独立环境配置.md)。但官方 [README](https://github.com/yuval-alaluf/SAM/blob/master/README.md) 的发布环境、整数目标年龄转换和二维 RGB 输出这些限制仍在：二维输出不是 UV，生成图也可能改变姿态/几何，不能不经重对齐/重建就沿用原图投影。本机环境、算子自检和显存/延迟记录见 [本机来源核查](../output/backend/b45/age-texture-sam-feasibility.json) 与独立配置文档。

## 3. 复现

从项目根目录执行。转换需要用户授权的本机原TGZ；SciPy仅用于临时离线环境，不改服务依赖。以下命令已实际运行通过，换用新的输出目录：

```powershell
uv --cache-dir output/backend/b45/uv-cache run --no-project --python 3.11 --with numpy --with scipy python backend/src/agemorph3d/prepare_bfm_age.py --bfm-archive 'BFM 非商业研究授权与模型资产/BaselFaceModel.tgz' --bfm-archive-sha256 d6cf2dffb74404f4f7ee2cd56f611e6fdcb22081ebf993f8b01edf6207f6cce9 --target-bfm data/models/3ddfa-v2/bfm.npz --target-bfm-sha256 aa9e819661adec8ee97ebd82930a28f05dd64c5e61c57e52c98abb2152fb3c3b --output-dir output/backend/b45/repro-direction
```

用转换得到的NPZ及其pin运行公开成年astronaut照片的原生强度/基础UV样例，输出目录必须不存在：

```powershell
.\backend\.venv\Scripts\python.exe -m agemorph3d.age_research_probe --detector-manifest data/models/yolov5n05-face/manifest.json --reconstructor-manifest data/models/3ddfa-v2/manifest.json --image data/samples/astronaut.png --direction output/backend/b45/repro-direction/age_direction.npz --direction-sha256 e94e8f294a2a36264a6751eaffdcd4854f7587800de1ccde31d4969424850b5b --uv data/models/3ddfa-v2/uv.npz --uv-sha256 d191871a33467b3b6c0565b62469b17e16241efd1683c681ea9550dc9c741228 --strengths=-50,0,50 --output-dir output/backend/b45/repro-combined --research-allow-unresolved
```

`mesh.glb/result.json`为零强度原始结果，`strength-00/01/02.glb`的实际强度写入report与GLB元数据；名称不标成年龄。还输出base-atlas.png、uv_bound.npz、report.json。源年龄可显式`--source-age 42.5`，只代表调用者提供的年龄，未知时省略。默认无研究开关则严格许可；独立UV需显式研究，非零强度需pin方向，已有结果目录拒绝，失败只清理本次创建的文件。

真实纹理浏览器复验：

```powershell
$env:AGEMORPH_RESEARCH_MESH = (Resolve-Path output/backend/b45/repro-combined/mesh.glb).Path
$env:AGEMORPH_RESEARCH_RESULT = (Resolve-Path output/backend/b45/repro-combined/result.json).Path
$env:AGEMORPH_RESEARCH_OUTPUT = (Join-Path (Get-Location) 'output/backend/b45/repro-browser')
$env:AGEMORPH_RESEARCH_REQUIRE_TEXTURE = '1'
Set-Location frontend
node tests/static-mesh-research.mjs
```

该脚本独占回环5175/18003，使用实际FaceViewer/GLTFLoader并自动关闭，不提供模型健康/推理接口，不伪造正式ready；使用软件WebGL。当前原照片来源/许可/哈希继承B0记录，未引入其他身份或批量数据。

## 4. 本次检查与证据

| 检查 | 本次结果 | 限定范围 |
|---|---|---|
| 后端全量 | **766 passed**；Ruff检查通过，51个Python文件格式通过；一条上游Starlette/httpx弃用提示 | 合成数值/契约/资源测试，与实际模型证据分列 |
| 前端 | **47单元**、TS/Vite构建通过；Chrome/Edge完整浏览器 **72/72** | [完整报告](../output/backend/b45/frontend-browser-full.json) |
| 原始资产转换 | 53,490→38,365唯一对应，40PCA零误差，199维方向；独立复现产物hash相同 | [派生来源](../output/backend/b45/prepared-age/provenance.json)、`verified-converter-command/provenance.json` |
| 实际方向连续性 | 7个强度均有限，零精确不变；往返最大0.0078125原始单位 | [native-direction-check.json](../output/backend/b45/native-direction-check.json)，不是年尺度/身份验收 |
| 实际组合样例 | −50/0/50三个静态GLB；往返canonical最大约4.30×10⁻⁸，固定源坐标、原PNG、40/10系数保持 | [combined-real/report.json](../output/backend/b45/combined-real/report.json) |
| 独立组合复核 | 三GLB逐字节复现，固定坐标最大误差6.29×10⁻⁸；重复输出拒绝且8文件hash不变 | [combined-output-review.json](../output/backend/b45/combined-output-review.json) |
| 实际照片UV | 256图集，45,355面部texel、40,916可观测，约**90.2128%**面部覆盖；排除280个自遮挡texel | [uv-real/report.json](../output/backend/b45/uv-real/report.json)，不代表外部遮挡/身份质量 |
| 实际UV浏览器往返 | Chrome/Edge **2/2**；位置/法线/UV最大差0、索引相同，256²解码RGBA精确一致，flipY=false、sRGB/UV0/采样及透明遮罩保持 | [uv-browser报告](../output/backend/b45/uv-browser/static-mesh-research.json)，G1/G3/service=false |
| 严格拒绝 | 当前实际清单默认MODEL_ASSET_ERROR、exit1，仅失败报告 | [strict-rejected/report.json](../output/backend/b45/strict-rejected/report.json) |

独立UV样例GLB为2,217,416B、SHA`29d595b112634572e0e9e0fe388dcf46ff93af258b179d67807583601d9c66d8`；其内PNG69,346B、SHA`c029393d67f126b473cc854038ece3b6d9a743f85f3e1c68151d11cad7d6f45c`。浏览器导出后各2,235,816B，解码RGBA SHA`d7f6074838c7931f1f4425f48648d3548eb490c3442176c9d043d54881539eeb`相同。已实际查看正面、侧面与再导入图，五官方向对齐；未知侧部透明和开放后脑均保留。

组合样例UV投影约3.98秒，独立UV样例约4.48秒；包含实际单图算法但不包括完整服务/浏览器耗时，不是吞吐、GPU、身份或性能验收。原始物理单位仍未证明，误差的原始单位不解释成毫米。

## 5. 剩余工作

需要获准的年龄校准样例/有证据的年尺度，建立源年龄与绝对目标年龄关系，并逐项验收形状、纹理、连续性和身份保持。年龄纹理还需在后续取得的checkpoint及兼容独立运行栈基础上完成生成后重对齐/重建/UV、外部遮挡/接缝与身份评估。现有属性强度、用户填龄、相邻图像插值或基础UV均不能代替这些证据。

2026-10-20 已获取的 SAM checkpoint 和 FG-NET 20—70 子集只解决了“文件缺失”，没有解决“许可收口”和“年尺度证据”：FG-NET 是研究镜像且许可未定；SAM 已在独立环境跑通 batch=1 二维推理，但仍是许可未收口、未做 UV 注册和身份/年尺度评价。FG-NET 已跑完解码/检测/68 点一致性检查：292 张全部解码，290 张单人脸并重建成功（99.3%），瞳距归一的点集最近邻偏差均值约 0.082；这只说明旧照片能被现有链路读入，不构成身份或年尺度证据。下一步做同人跨龄检查，并向 iBUG 申请 AgeDB 密码（已发信，等待回复）；在完成身份分组、校准协议和独立评价前，不把年龄能力改为可用。详见 [获取记录](年龄模型与校准样例获取记录.md)。

原资产和原未提交文档的保持情况、源码及产物哈希见 [verification-summary.json](../output/backend/b45/verification-summary.json)。本批没有自动开放年龄滑杆或生成年龄纹理按钮，没有改许可状态、没有开始训练或推送Git。

2026-10-20 后续另完成[3DDFA → FFHQ / SAM 桥接](FFHQ对齐桥接实验.md)：从原照片68点重采样并保留有效区和逆变换，10个预期成功样例生成30张二维SAM输出，2个预期失败样例保持NO_FACE；后端当前全量820项通过。此后续证据替代上表“FFHQ桥接未验”的输入链路欠项，未收口的仍是许可、年尺度、同人真实跨龄/身份质量和逐目标重建/UV；原批次的哈希和测试记录保持历史含义。
