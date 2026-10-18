# 岁月镜 AgeMorph3D：毕业设计可行性分析与参考资料

> 整理日期：2026-10-15
> GitHub 星数是当天通过 GitHub API 查到的；论文都在 arXiv、OpenAlex 和期刊官网逐篇核对过。

## 项目名称与论文题目

**项目名称：岁月镜（英文名 AgeMorph3D）**

用户对着摄像头，像照镜子一样看到自己在不同年龄的三维头像，所以中文名叫"岁月镜"，用于答辩和演示。英文名里的 Morph 有两层意思：一是系统的技术核心"三维形变模型"（3D Morphable Model），二是 three.js 里实现年龄滑块的 morph target。英文名用作代码仓库名，GitHub 上目前没有同名项目。

**论文题目（推荐）：《基于YOLO与三维形变模型的跨年龄三维人脸重建及可视化系统》**

英文题目：A Cross-Age 3D Face Reconstruction and Visualization System Based on YOLO and 3D Morphable Models

- 如果学校模板要求"设计与实现"的格式，就在中文题目末尾加上"设计与实现"，英文题目前加 Design and Implementation of。
- 如果学校限制题目字数，可以用备选题目：《基于三维形变模型的跨年龄三维人脸重建与可视化》（22 字）。
- 题目用"三维人脸"而不是"三维头部"，是因为保底方案（BFM）只有面部区域。主线方案（FLAME 全头）做成后，可以改成"三维头部"。

## 一、结论

能做，而且演示效果会很好。前提是把"预测还原各年龄段"改成"基于统计模型的年龄变换和三维可视化"，论文的工作重心放在把现成模型集成起来，不去自己发明重建或老化算法。

三个模块的难度差别很大：

| 模块 | 难度 | 现状 |
|---|---|---|
| 摄像头 + YOLO 人脸检测 | 低 | 有现成的人脸检测权重，一两周能跑通 |
| 单张照片生成三维头模 | 中 | 有成熟的预训练模型可直接集成，难点在配环境和模型许可 |
| 预测各年龄段的三维头部 | 高 | 学术前沿。三维的老化方法 2023–2026 年才陆续发表，基本没有可用代码 |

## 二、题目里要先想清楚的三点

**YOLO 只负责找到脸在哪。** 它输出人脸框，人脸专用权重会多给 5 个关键点，但不含任何深度信息。真正从二维恢复三维的是另一类模型：三维形变模型（3DMM）回归网络。所以 YOLO 在系统里是前端的检测模块，比如把 3DDFA_V2 自带的 FaceBoxes 检测器换成 YOLO26n-face。如果导师要求体现 YOLO 的工作量，可以在 WIDER FACE 数据集上微调一个人脸检测模型，报告 mAP 和 FPS，正好撑起论文的"模型训练与实验"一章。

**做"头部"比做"人脸"难得多。** BFM 系列模型只有面部区域。FLAME 包含完整的颅形、脖子和眼球，但同样没有头发。后脑勺和头发在正脸照片里根本看不到，只能靠统计先验去猜。建议把目标定为"完整颅形的光头头模 + 面部纹理"。

**"预测"没有标准答案。** 没人知道一个具体的人 60 岁长什么样，结果只能是统计上合理的年龄变换，答辩时要准备好替代的评价指标（见第五节）。另外，FLAME 和 BFM 主要用成年人的扫描数据训练，表达不了儿童的头部比例。好在有现成的统计资源可以用：

- BFM 2009 发布包里的 `04_attributes.mat` 自带年龄、性别、身高、体重的形状变化方向（[官网说明](https://faces.dmi.unibas.ch/bfm/index.php?nav=1-1-0&id=details)），拿来就能做年龄滑块。
- LYHM（全头，1200 多人）和 LSFM（9663 人）都按年龄组单独建过子模型，但要签协议申请。

## 三、推荐的技术路线

```
摄像头 → YOLO26n-face 检测 → 裁剪对齐 → 3DMM 回归（3DDFA_V2 / MICA）
      → 形状参数 β、表情、姿态、UV 纹理
      → 年龄变换：β' = β + w(age)·Δβ_age；纹理用 SAM 生成目标年龄的照片再展开
      → 导出 glTF（年龄方向作为 morph target）→ three.js 渲染 + 年龄滑块
```

**保底版（约 6–8 周，确保能毕业）。** 用 YOLO + 3DDFA_V2 + BFM 年龄方向 + three.js。3DDFA_V2 仓库自带检测器、处理好的 BFM 文件、摄像头 demo（`demo_webcam_smooth.py`）和 ONNX 推理，在 CPU 上就能实时跑。把 BFM 的年龄方向换算成每个顶点的位移，对齐两套网格的顶点编号后，直接作为 three.js 的一个 morph target，用滑块控制它的权重。

**主线版（推荐）。** 换成 MICA，得到 FLAME 全头模型，再做一个本课题自己的小创新：用数据统计出"年龄方向"。具体做法是用带年龄标签的数据集（UTKFace、FFHQ-Aging）批量重建，得到大量 FLAME 形状参数，再按年龄做回归，得到 FLAME 空间里的年龄方向。形状负责脸型、下颌、软组织下垂；皱纹和肤色这类纹理变化交给 SAM 生成。这个思路和 ICME 2024 的 3D-STD 论文一致，可以作为核心参考文献。

**加分版（可选）。** LAM、FaceLift、混元 Hunyuan3D-2.1 能从单张照片直接生成三维头像或模型，效果惊艳。但它们不是参数化模型，做不了年龄滑块，适合放在对比或扩展展示部分。

three.js 这边有三个设计要点：

- 实时和离线分开。检测、重建、姿态驱动可以逐帧实时做；年龄变换做成"拍照 → 生成 → 查看"的离线流程。
- 前后端之间传参数，不传网格。前端一次性加载模板网格和形状基，后端每帧只发几十个浮点数。FLAME 只有 5023 个顶点，很适合在浏览器里算。
- 前端可以直接参考 three.js 官方示例 `webgl_morphtargets_webcam`，它演示了用 MediaPipe 读摄像头、驱动头模的表情和头部姿态。

## 四、开发环境注意事项

开发笔记本是 RTX 5060 Laptop（8GB 显存）、31GB 内存、Windows 11，已经装了 WSL2 Ubuntu。用来推理够用，但有两个坑：

- **50 系显卡的兼容性。** 这代显卡需要 CUDA 12.8 和 PyTorch 2.7 以上。DECA、SAM、LATS 这些 2020–2021 年的仓库锁定 PyTorch 1.x，照 README 安装会报 `no kernel image is available`，需要升级 PyTorch 并重新编译 CUDA 扩展。建议先跑通依赖最少的 3DDFA_V2。
- **在 WSL2 里配环境。** PyTorch3D 在 Windows 上原生编译很痛苦。扩散类老化模型（FADING、Cradle2Cane）在 8GB 显存上偏紧，需要开半精度或租云 GPU；不要在笔记本上重新训练 SAM。

## 五、风险、评价指标和合规

| 风险 | 应对 |
|---|---|
| FLAME 要在官网注册，BFM、LYHM、LSFM 要申请，可能等一到几周 | 开题第一周就提交申请。3DDFA_V2 自带的 BFM 文件可以先用；Google 2026 年 7 月发布的 [GNM Head](https://github.com/google/GNM) 用 Apache-2.0 协议，不用申请 |
| 表达不了儿童头型 | 主体范围限定在 20–70 岁，儿童放进"局限与展望" |
| 三维老化没有现成代码 | 3D-STD 和 DiffAge3D 在 GitHub 上没搜到官方代码，所以主线用 3DMM 年龄方向自己实现 |

**评价指标**，用来应对"准确率多少"这类提问：

- 检测：WIDER FACE 的 mAP 和 FPS。
- 重建：AFLW2000-3D 上的关键点误差（NME）；有余力可以再用 NoW 或 REALY 评测基准。
- 年龄变换：用 MiVOLO 估计生成结果的年龄，看和目标年龄差多少；用 ArcFace 算和原图的身份相似度；FG-NET 数据集里有同一个人不同年龄的真实照片，可以做直观对比。
- 系统：端到端延迟、渲染帧率，外加 10–20 人的主观打分。

**合规。** 人脸属于《个人信息保护法》规定的敏感个人信息，处理需要本人单独同意。《人脸识别技术应用安全管理办法》（国家网信办、公安部令第 19 号）已于 2025 年 6 月 1 日施行。采集同学照片要签知情同意书，数据只在本地处理，不采集未满 14 岁的人。论文里单独写一节"数据合规"会加分。

## 六、时间安排（约 16 周）

| 周次 | 任务 |
|---|---|
| 1–2 | 读综述，申请模型许可，在 WSL2 配好环境 |
| 3–4 | 跑通 YOLO 人脸检测，在 WIDER FACE 上微调 |
| 5–7 | 跑通 3DDFA_V2，在 three.js 里加载模型、贴纹理 |
| 8–10 | 先做 BFM 年龄滑块，再做 MICA + 年龄回归 + SAM 纹理 |
| 11–12 | 前后端联调（FastAPI + WebSocket） |
| 13–16 | 实验评价、写论文、录演示视频 |

近期待办：

1. 和导师确认题目和范围，尤其是把"预测"改为"年龄变换与可视化"。
2. 提交 FLAME 注册和 BFM 2009 下载申请。
3. 在 WSL2 里跑通 3DDFA_V2 的摄像头 demo（`demo_webcam_smooth.py`）。

## 七、GitHub 可参考项目

没有找到完整实现"摄像头 → 三维头模 → 跨年龄"整套流程的仓库。这说明题目有一定新意，但集成工作要自己做。

| 类别 | 项目 | ⭐ | 用途 |
|---|---|---|---|
| 检测 | [ultralytics/ultralytics](https://github.com/ultralytics/ultralytics) | 62.5k | YOLO 官方框架。YOLO26 是目前最新的正式版，YOLO27 官方标注"即将推出"，还没发布；AGPL-3.0 |
| 检测 | [akanametov/yolo-face](https://github.com/akanametov/yolo-face) | 964 | 现成的人脸检测权重，含 yolo26n/s-face、YOLO11/12-face |
| 检测 | [deepcam-cn/yolov5-face](https://github.com/deepcam-cn/yolov5-face) | 2.4k | YOLO5Face 论文官方代码，带 5 个关键点 |
| 检测 | [WildChlamydia/MiVOLO](https://github.com/WildChlamydia/MiVOLO) | 541 | 年龄、性别估计，可用来评估老化效果 |
| 检测 | [dinglizhong/BYSJ](https://github.com/dinglizhong/BYSJ) | 3 | 一份国内本科毕设：人脸检测 + 年龄估计 + SAM 老化 + 摄像头界面，可参考毕设的工作量 |
| 重建 | [cleardusk/3DDFA_V2](https://github.com/cleardusk/3DDFA_V2) | 3.2k | 保底首选，轻量，自带摄像头 demo（MIT） |
| 重建 | [Zielon/MICA](https://github.com/Zielon/MICA) | 659 | 主线推荐，FLAME 全头，脸型估计准 |
| 重建 | [yfeng95/DECA](https://github.com/yfeng95/DECA) | 2.5k | FLAME 全头 + 皮肤细节 |
| 重建 | [sicxu/Deep3DFaceRecon_pytorch](https://github.com/sicxu/Deep3DFaceRecon_pytorch) | 1.9k | 微软亚洲研究院，BFM（MIT） |
| 重建 | [youngLBW/HRN](https://github.com/youngLBW/HRN) | 546 | 阿里达摩院 CVPR 2023，细节更丰富 |
| 重建 | [LizhenWangT/FaceVerse](https://github.com/LizhenWangT/FaceVerse) | 536 | 清华，用东亚人脸数据建的三维人脸模型 |
| 重建 | [SimonGiebenhain/pixel3dmm](https://github.com/SimonGiebenhain/pixel3dmm) | 532 | 2025 年新方法，单图拟合 FLAME 精度高 |
| 重建 | [yfeng95/face3d](https://github.com/yfeng95/face3d) | 2.8k | 3DMM 原理的 Python 教学代码 |
| 重建 | [patrikhuber/eos](https://github.com/patrikhuber/eos) | 2.0k | 轻量的 3DMM 拟合库（C++/Python） |
| 重建 | [TimoBolkart/FLAME-Universe](https://github.com/TimoBolkart/FLAME-Universe) | 709 | FLAME 相关资源总目录 |
| 重建 | [google/GNM](https://github.com/google/GNM) | 1.6k | Google 2026 年 7 月发布的全头参数模型（含眼球、牙齿、舌头），Apache-2.0 免申请；采样器只支持按性别和族裔，不支持年龄 |
| 重建 | [aigc3d/LAM](https://github.com/aigc3d/LAM) | 1.1k | 阿里，单图生成高斯头像，配套 [LAM_WebRender](https://github.com/aigc3d/LAM_WebRender) 网页渲染器 |
| 重建 | [weijielyu/FaceLift](https://github.com/weijielyu/FaceLift) | 567 | ICCV 2025，单图生成三维高斯头部 |
| 重建 | [Tencent-Hunyuan/Hunyuan3D-2.1](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1) | 4.2k | 腾讯混元，单图生成带 PBR 材质的三维模型 |
| 老化 | [yuval-alaluf/SAM](https://github.com/yuval-alaluf/SAM) | 729 | 连续年龄控制，最成熟（MIT） |
| 老化 | [royorel/Lifespan_Age_Transformation_Synthesis](https://github.com/royorel/Lifespan_Age_Transformation_Synthesis) | 598 | 覆盖 0–70 岁，会改变头型，附 FFHQ-Aging 数据集 |
| 老化 | [byliutao/Cradle2Cane](https://github.com/byliutao/Cradle2Cane) | 11 | NeurIPS 2025，最新的扩散模型方案 |
| 老化 | [MunchkinChen/FADING](https://github.com/MunchkinChen/FADING) | 56 | BMVC 2023，扩散模型老化 |
| 老化 | [ZZUTK/Face-Aging-CAAE](https://github.com/ZZUTK/Face-Aging-CAAE) | 659 | CVPR 2017 经典，适合理解原理 |
| 前端 | [mrdoob/three.js](https://github.com/mrdoob/three.js) | 116k | 看官方示例 `webgl_morphtargets_webcam` 和 `webgl_morphtargets_face` |
| 前端 | [google-ai-edge/mediapipe](https://github.com/google-ai-edge/mediapipe) | 37k | 478 个三维人脸关键点，浏览器里能跑 |
| 前端 | [spite/FaceMeshFaceGeometry](https://github.com/spite/FaceMeshFaceGeometry) | 423 | 把人脸关键点直接转成 three.js 几何体 |
| 前端 | [google/xrblocks](https://github.com/google/xrblocks) | 485 | 基于 three.js，`demos/gnm` 是头模的网页调参 demo |
| 前端 | [jeeliz/jeelizFaceFilter](https://github.com/jeeliz/jeelizFaceFilter) | 2.9k | WebGL 人脸跟踪 + three.js AR 示例 |
| 前端 | [Hyuto/yolov8-onnxruntime-web](https://github.com/Hyuto/yolov8-onnxruntime-web) | 193 | YOLO 在浏览器里运行的示例 |
| 清单 | [winterbloooom/awesome-3d-face](https://github.com/winterbloooom/awesome-3d-face) | 41 | 三维人脸论文、数据集、评测基准清单 |

## 八、论文

### 国外论文（建议按顺序读）

**1. 入门综述**

| 论文 | 出处 | 链接 | 说明 |
|---|---|---|---|
| 3D Morphable Face Models—Past, Present and Future（Egger 等） | ACM TOG 2020 | [arXiv:1909.01815](https://arxiv.org/abs/1909.01815) | 3DMM 必读综述 |
| State of the Art on Monocular 3D Face Reconstruction, Tracking, and Applications（Zollhöfer 等） | CGF 2018 | [DOI](https://doi.org/10.1111/cgf.13382) | 单目重建综述 |
| Survey on 3D face reconstruction from uncalibrated images（Morales 等） | — | [arXiv:2011.05740](https://arxiv.org/abs/2011.05740) | 较新的重建综述 |
| Age Synthesis and Estimation via Faces: A Survey（Fu、Guo、Huang） | TPAMI 2010 | [DOI](https://doi.org/10.1109/tpami.2010.36) | 年龄合成经典综述 |
| Deep Face Age Progression: A Survey（Grimmer 等） | IEEE Access 2021 | [DOI](https://doi.org/10.1109/access.2021.3085835) | 深度学习老化综述 |

**2. 基础形状模型**

| 论文 | 出处 | 链接 | 说明 |
|---|---|---|---|
| A Morphable Model for the Synthesis of 3D Faces（Blanz、Vetter） | SIGGRAPH 1999 | [DOI](https://doi.org/10.1145/311535.311556) | 3DMM 开山之作 |
| A 3D Face Model for Pose and Illumination Invariant Face Recognition（Paysan 等，BFM 2009） | AVSS 2009 | [DOI](https://doi.org/10.1109/avss.2009.58) | 自带年龄等属性方向 |
| Learning a model of facial shape and expression from 4D scans（Li 等，FLAME） | ACM TOG 2017 | [DOI](https://doi.org/10.1145/3130800.3130813) | 全头参数模型 |
| Large Scale 3D Morphable Models（Booth 等，LSFM） | IJCV 2018 | [DOI](https://doi.org/10.1007/s11263-017-1009-7) | 9663 人，按年龄、性别、族裔分组建模 |
| Statistical Modeling of Craniofacial Shape and Texture（Dai 等，LYHM） | IJCV 2020 | [DOI](https://doi.org/10.1007/s11263-019-01260-7) | 全头，按年龄组建子模型 |
| Towards a complete 3D morphable model of the human head（Ploumpis 等，UHM） | — | [arXiv:1911.08008](https://arxiv.org/abs/1911.08008) | 面部与全头合并的模型 |
| GNM Head: A Generative aNthropometric Model of the human head（Ploumpis 等） | 2026 | [arXiv:2607.23687](https://arxiv.org/abs/2607.23687) | Google 新发布的全头模型 |

**3. 单图三维重建**

| 论文 | 出处 | 链接 | 说明 |
|---|---|---|---|
| Towards Fast, Accurate and Stable 3D Dense Face Alignment（Guo 等，3DDFA_V2） | ECCV 2020 | [arXiv:2009.09960](https://arxiv.org/abs/2009.09960) | 保底方案 |
| Accurate 3D Face Reconstruction with Weakly-Supervised Learning（Deng 等） | CVPRW 2019 | [arXiv:1903.08527](https://arxiv.org/abs/1903.08527) | 弱监督重建经典 |
| Joint 3D Face Reconstruction and Dense Alignment with Position Map Regression Network（Feng 等，PRNet） | ECCV 2018 | [arXiv:1803.07835](https://arxiv.org/abs/1803.07835) | 位置图回归 |
| Learning an Animatable Detailed 3D Face Model from In-The-Wild Images（Feng 等，DECA） | SIGGRAPH 2021 | [arXiv:2012.04012](https://arxiv.org/abs/2012.04012) | FLAME + 细节 |
| Towards Metrical Reconstruction of Human Faces（Zielonka 等，MICA） | ECCV 2022 | [arXiv:2204.06607](https://arxiv.org/abs/2204.06607) | 主线方案 |
| A Hierarchical Representation Network for Accurate and Detailed Face Reconstruction from In-The-Wild Images（Lei 等，HRN） | CVPR 2023 | [arXiv:2302.14434](https://arxiv.org/abs/2302.14434) | 国内团队，细节重建 |
| Pixel3DMM: Versatile Screen-Space Priors for Single-Image 3D Face Reconstruction（Giebenhain 等） | 2025 | [arXiv:2505.00615](https://arxiv.org/abs/2505.00615) | 新方法 |
| REALY: Rethinking the Evaluation of 3D Face Reconstruction（Chai 等） | ECCV 2022 | [arXiv:2203.09729](https://arxiv.org/abs/2203.09729) | 重建评测基准 |
| Learning to Regress 3D Face Shape and Expression from an Image without 3D Supervision（Sanyal 等） | CVPR 2019 | [arXiv:1905.06817](https://arxiv.org/abs/1905.06817) | 提出 NoW 评测基准 |

**4. 二维年龄变换**

| 论文 | 出处 | 链接 | 说明 |
|---|---|---|---|
| Age Progression/Regression by Conditional Adversarial Autoencoder（Zhang 等，CAAE） | CVPR 2017 | [arXiv:1702.08423](https://arxiv.org/abs/1702.08423) | 入门 |
| Learning Face Age Progression: A Pyramid Architecture of GANs（Yang 等） | CVPR 2018 | [arXiv:1711.10352](https://arxiv.org/abs/1711.10352) | 北航 |
| Face Aging with Identity-Preserved Conditional Generative Adversarial Networks（IPCGAN） | CVPR 2018 | [DOI](https://doi.org/10.1109/cvpr.2018.00828) | 上海科技大学 |
| Lifespan Age Transformation Synthesis（Or-El 等，LATS） | ECCV 2020 | [arXiv:2003.09764](https://arxiv.org/abs/2003.09764) | 0–70 岁，含头型变化 |
| Only a Matter of Style: Age Transformation Using a Style-Based Regression Model（Alaluf 等，SAM） | SIGGRAPH 2021 | [arXiv:2102.02754](https://arxiv.org/abs/2102.02754) | 主线纹理方案 |
| Disentangled Lifespan Face Synthesis（He 等） | ICCV 2021 | [arXiv:2108.02874](https://arxiv.org/abs/2108.02874) | 形状、纹理解耦 |
| Face Aging via Diffusion-based Editing（Chen、Lathuilière，FADING） | BMVC 2023 | [arXiv:2309.11321](https://arxiv.org/abs/2309.11321) | 扩散模型 |
| From Cradle to Cane: A Two-Pass Framework for High-Fidelity Lifespan Face Aging（Liu 等） | NeurIPS 2025 | [arXiv:2506.20977](https://arxiv.org/abs/2506.20977) | 最新扩散方案 |

**5. 三维年龄变换（和本题最接近）**

| 论文 | 出处 | 链接 | 说明 |
|---|---|---|---|
| Prediction of Individual Non-Linear Aging Trajectories of Faces（Scherbaum 等） | CGF 2007 | [DOI](https://doi.org/10.1111/j.1467-8659.2007.01050.x) | 用 3DMM 预测个体老化轨迹 |
| Age-Invariant Face Recognition（Park、Tong、Jain） | TPAMI 2010 | [DOI](https://doi.org/10.1109/tpami.2010.14) | 提出 3D 老化模型 |
| Adversarial UV-Transformation Texture Estimation for 3D Face Aging（Wu 等） | IEEE TCSVT 2021 | [DOI](https://doi.org/10.1109/tcsvt.2021.3133313) | 三维老化的纹理估计 |
| Exploring 3D-aware Lifespan Face Aging via Disentangled Shape-Texture Representations（Teng 等，3D-STD） | ICME 2024 | [arXiv:2312.16881](https://arxiv.org/abs/2312.16881) | **核心参考**，用三维重建把老化拆成形状和纹理 |
| DiffAge3D: Diffusion-based 3D-aware Face Aging（Wahid 等） | 2024 | [arXiv:2408.15922](https://arxiv.org/abs/2408.15922) | 三维感知的扩散老化 |
| ReAge3D: Re-Aging 3D Faces with View Consistency（Zeng 等） | 2026 | [arXiv:2606.18156](https://arxiv.org/abs/2606.18156) | 最新进展 |

**6. 其他（检测、评估、生成式头像）**

| 论文 | 出处 | 链接 | 说明 |
|---|---|---|---|
| YOLO5Face: Why Reinventing a Face Detector（Qi 等） | ECCV Workshops 2022 | [arXiv:2105.12931](https://arxiv.org/abs/2105.12931) | YOLO 人脸检测 |
| MiVOLO: Multi-input Transformer for Age and Gender Estimation（Kuprashevich 等） | 2023 | [arXiv:2307.04616](https://arxiv.org/abs/2307.04616) | 年龄估计，用于评估 |
| PanoHead: Geometry-Aware 3D Full-Head Synthesis in 360°（An 等） | CVPR 2023 | [arXiv:2303.13071](https://arxiv.org/abs/2303.13071) | 360° 全头生成 |
| LAM: Large Avatar Model for One-shot Animatable Gaussian Head（He 等） | SIGGRAPH 2025 | [arXiv:2502.17796](https://arxiv.org/abs/2502.17796) | 单图生成高斯头像 |
| FaceLift: Learning Generalizable Single Image 3D Face Reconstruction from Synthetic Heads（Lyu 等） | ICCV 2025 | [arXiv:2412.17812](https://arxiv.org/abs/2412.17812) | 单图生成三维高斯头部 |

### 国内论文

1. 刘菲, 张堃博, 杨青, 周树波, 王云龙, 孙哲南. 三维人脸成像及重建技术综述[J]. 中国图象图形学报, 2024, 29(9): 2441-2470. [DOI: 10.11834/jig.230697](https://doi.org/10.11834/jig.230697)
   中科院自动化所团队写的，可免费下载，是中文入门首选。按单目、多目、视频、语音四类梳理了近五年的深度学习重建方法。该刊还有"数字人建模、生成与渲染技术"专栏，可以顺着看。
2. 张珂, 于婷婷, 石超君, 娄文硕, 刘阳. 融合通道位置注意力机制和并行空洞卷积的人脸年龄合成[J]. 中国图象图形学报, 2023, 28(12): 3870-3883. [DOI: 10.11834/jig.230007](https://doi.org/10.11834/jig.230007)
3. 张珂 等. Survey of deep learning methods for face age estimation[J]. 中国图象图形学报, 2019. [DOI: 10.11834/jig.180653](https://doi.org/10.11834/jig.180653)
   年龄估计综述，评价"生成结果像不像目标年龄"时用得上。
4. Zhong Yicheng, Pei Yuru, Li Peixin（北京大学）. Single-View 3D Face Reconstruction via Cross-View Consistency Constraints[J]. 计算机辅助设计与图形学学报, 2024, 36(4): 543-551. [DOI: 10.3724/sp.j.1089.2024.19772](https://doi.org/10.3724/sp.j.1089.2024.19772)
   可免费阅读。
5. Bao Yongtang 等. Realistic 3D Face Reconstruction Method for Single Image[J]. 计算机辅助设计与图形学学报, 2022. [DOI: 10.3724/sp.j.1089.2022.19485](https://doi.org/10.3724/sp.j.1089.2022.19485)
6. Shen Chengxiao 等. Large-View 3D Color Face Reconstruction from Single Image via UV Location Map and CGAN[J]. 计算机辅助设计与图形学学报, 2022. [DOI: 10.3724/sp.j.1089.2022.18959](https://doi.org/10.3724/sp.j.1089.2022.18959)

国内团队在国际会议上的代表作，中文解读资料多，读起来门槛低：3DDFA_V2（中科院自动化所）、Deep3DFaceRecon（微软亚洲研究院）、HRN（阿里达摩院）、FaceVerse（清华，[arXiv:2203.14057](https://arxiv.org/abs/2203.14057)）、FaceScape（南京大学，[arXiv:2003.13989](https://arxiv.org/abs/2003.13989)）、金字塔 GAN 老化（北航）、IPCGAN（上海科技大学）、3D-STD（北邮）。

### 检索建议

整理时百度学术和万方都弹出了人机验证，上面的中文论文是通过期刊官网和 OpenAlex 找到的，覆盖不全。建议从学校图书馆进知网，搜"三维人脸重建""三维形变模型""人脸年龄合成""人脸老化""跨年龄"，重点看硕士学位论文。它们的篇幅和深度跟本科毕设最接近，系统设计和实验章节的写法可以直接借鉴。

国外论文用 arXiv 和 CVF Open Access（CVPR、ICCV 论文全文免费）基本就够了，再用 Google Scholar 顺着引用关系找相关工作。
