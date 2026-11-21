# RD-1 选型核查：YOLO26n-face / YOLO5Face / MICA+FLAME / BFM

- 任务：Atlas 规划 v2 的 RD-1（任务书选型核查）。用户经 Atlas 恢复后要求完成可由 AI 独立完成的部分。
- 范围：只做公开资料与本地仓库只读核对。**本次未下载任何权重、数据集或大文件**。
- 本地仓库副本：`/workspace/AgeMorph3D`，commit `35c0cd61b70976393f919dfff34834bad9a67dc8`（`35c0cd6`）。
- 查阅日期：2026-11-16（Europe/Berlin，UTC+1）。下文 URL 均在该日访问。
- 原则：每条结论附一手来源；查不到的写「未核实」。给出可选方案与给导师的事实摘要，**不替代用户或导师做最终决定**。本文不是法律意见。
- 范围补充：SAM、pSp/e4e 等纹理或潜空间模型的许可与获取**不在 RD-1 范围内**，由其他任务另行核查；本文只在资产台账中见到 SAM 被提及，不对其条款下结论。
- 修订（2026-11-16，Europe/Berlin）：按 Sentinel SN-2 初审 FAIL（1 CRITICAL、2 MINOR）修订。已用公开 GitHub API / 网页核验 Release 元数据，并对下载链接做了**不跟随、不下载正文**的 HEAD；未下载 `BaselFaceModel.tgz` 或任何权重。改写了 §2.2 的 GPL 边界、§3.3 给导师摘要、§4.3 与 C13。是否删除或将 Release 附件改为私有，**由用户本人决定**；本文不写成已处理。
- 修订 2（2026-11-16，Europe/Berlin，RD-1 复审通过后的小整理）：在本地副本核验并补列另外三处「仓库不转分发」表述；将 §3.3 第 5 条标为时点性陈述，MU-5 起草前须重查附件状态，是否及如何告知导师由用户决定；为 §4.3 所引 Release 说明「不随源码仓库分发」补上已有的 GitHub Releases API `body` 出处。本次未再访问该项目的 GitHub，也未下载附件。

---

## 0. 结论先行（供 Sentinel / 导师快速阅读）

1. **YOLO26 是 Ultralytics 官方正式版**（2026-01-14 发布，文档与新闻稿一致）。官方预训练只有通用检测 / 分割 / 分类 / **人体姿态** / OBB 等，**没有官方「YOLO26n-face」权重**。
2. **名为 `yolo26n-face.pt` 的第三人权重确实存在**，主要来源是 GitHub 仓库 [akanametov/yolo-face](https://github.com/akanametov/yolo-face) 的 release `1.0.0`，README 写明在 WIDER FACE 上训练、用法是 `yolo task=detect`。这是较常见的第三方人脸检测微调，**不是 Ultralytics 官方发布**。另有 Hugging Face、Ultralytics Platform 上的同名社区模型，训练过程与指标口径不同，不能和 akanametov 权重混用。
3. **`yolo26n-face` 只出人脸框，不出 5 个面部关键点。** 官方 `yolo26n-pose.pt` 是 COCO 17 点人体关键点，不是人脸 5 点。任务书「框 + 5 点」不能靠现成的 YOLO26n-face 权重直接满足。
4. 技术框架里把官方 YOLO26n 的 COCO 指标（mAP50-95 = 40.9、2.4 M 参数、5.5 GFLOPs、T4 1.7 ms）写成人脸检测能力，**这是口径错误**：那些数字属于 80 类 COCO 检测模型 `yolo26n.pt`，不是 `yolo26n-face`。akanametov 未在 README 中公布 YOLO26-face 的 WIDER FACE Easy/Medium/Hard AP 数字（**未核实**）。
5. 本仓库**实际在用** YOLO5Face（deepcam-cn/yolov5-face）经 clibdev 导出的 ONNX：`yolov5n-0.5-face.onnx`。代码接受 `[1,N,16]`（框 + 目标分数 + **5 个 xy 点** + 人脸分数）。3DDFA_V2 的 `reconstruct()` **只需要人脸框**，5 点用于前端/实时显示，不是重建输入的硬依赖。
6. YOLO5Face 代码为 **GPL-3.0**；官方与论文公布的 yolov5n-0.5 在 WIDER FACE **验证集**上为 Easy 90.76 / Medium 88.12 / Hard 73.82。清单指向的 ONNX 与 clibdev README 的 SHA-256 一致，但 **上游没有单独的权重许可文件**；训练数据 WIDER FACE 为 CC BY-NC-ND。清单已记录项目所有者 2026-11-01 的学术非商业、不转分发决定，并写明「这不是上游授权」。
7. **MICA + FLAME 可以合法用于本科非商业科研，但必须先注册并接受非商业条款**；MICA 预训练与 FLAME 2020（MICA 安装脚本实际下载的版本）都禁止再分发和商业使用。MICA demo 保存的是 **FLAME 身份形状码**（`identity.npy` / `pred_shape_code`）和规范形状网格，**不是**与 3DDFA_V2 同接口的「shape40 + expr10 + 姿态」完整参数。改用 FLAME 会使已在 **BFM 裁剪拓扑、shape40 空间**里学习的年龄方向全部作废，并打断现有网格、UV、GLB 导出。
8. **（CRITICAL，已核实）公开仓库确实在转分发原始 BFM 数据包。** 清单、README 第 43 行和 `docs/model-assets.md` 第 3 行仍写「仓库不转分发」，但同一份 README 第 47 行和 `docs/model-assets.md` 第 37 行写明原始 `BaselFaceModel.tgz`「改以 GitHub Release 附件分发」。公开仓库 [xiaominaimoyu/AgeMorph3D](https://github.com/xiaominaimoyu/AgeMorph3D) 的 Release [`assets-bfm-2009`](https://github.com/xiaominaimoyu/AgeMorph3D/releases/tag/assets-bfm-2009) 挂有 `BaselFaceModel.tgz`（240,287,841 字节，`draft=false`，`prerelease=false`，`published_at=2026-10-24T11:23:38Z`，即 2026-10-24 13:23 Europe/Berlin，当时为 UTC+2）。未认证 HEAD 该下载地址返回 302，可匿名获取。这与 BFM 非商业许可 **§3.3**（禁止将 DATA 全部或部分分发给任何第三方）相冲突。是否删除或改为私有附件，须由**用户本人**决定；本文不写成已处理。
9. **给导师的建议（推荐，非决定）**：开题与正文以**现用代码**为准——检测写 YOLO5Face，重建写 3DDFA_V2 + BFM；把 YOLO26n-face、MICA+FLAME 明确标为任务书原计划 / 对照路线，不要改名宣称已经换成 YOLO26 或 MICA。若学期内仍要做对比实验，可在许可允许的前提下用 YOLO26n-face 做「只出框」对照，5 点仍走现有 YOLO5Face 或另行训练 pose，不建议现在切换主线。

---

## 1. YOLO26 与「YOLO26n-face」是否真实存在

### 1.1 YOLO26 是不是官方正式版

**是。** Ultralytics 于 **2026-01-14** 正式发布 YOLO26。

- 官方文档 [Ultralytics YOLO26](https://docs.ultralytics.com/models/yolo26) 开篇写：「Newest SOTA Ultralytics models, released January 2026。」并给出统一模型族：检测 `yolo26n.pt` … `yolo26x.pt`，以及 seg / sem / depth / cls / **pose** / obb。使用方式为 `pip install ultralytics` 后 `YOLO("yolo26n.pt")`。社区公告要求 `ultralytics>=8.4.0`（[YOLO26 Available Now](https://community.ultralytics.com/t/yolo26-available-now/1746)，2026-01-14）。
- 官方新闻稿 [Ultralytics redefines state-of-the-art vision AI with YOLO26](https://www.ultralytics.com/news/ultralytics-redefines-state-of-the-art-vision-ai-with-yolo26)（标注 January 14, 2026）写：「Today, we’re officially launching Ultralytics YOLO26」。此前在 YOLO Vision 2025 上预告。
- 论文条目见文档引用：Jocher 等，*Ultralytics YOLO26: Unified Real-Time End-to-End Vision Models*，arXiv:[2606.03748](https://arxiv.org/abs/2606.03748)。
- 官方检测表（同一文档，COCO val，640 输入）中 YOLO26n：mAP50-95 = **40.9**，参数 **2.4 M**，FLOPs **5.5 B**，T4 TensorRT10 **1.7 ms**。这些是 **80 类 COCO 通用检测**指标。

仓库文档 `docs/AgeMorph3D_技术框架与模块行动计划.md`（约第 85 行）把上述 40.9 / 2.4 M / 5.5 GFLOPs / 1.7 ms 作为选用 YOLO26n-face 的依据。**这些数字不能代表人脸检测精度**，只说明官方 nano 检测模型的规模与 COCO 速度。该文件提到的 `ultralytics` 8.4.178 是否为查阅当日最新补丁版，**本次未核实**；官方门槛是 `>=8.4.0`。

### 1.2 有没有官方或可信的 YOLO26 人脸检测权重（n 规格）

**没有 Ultralytics 官方人脸权重。** 官方模型表与 [ultralytics/yolo26](https://github.com/ultralytics/yolo26) 均未列出 `yolo26n-face.pt` 或任何 face 任务检查点。官方预训练检测是 COCO 80 类，不是单类人脸。

**存在较可信的第三方权重**：

| 来源 | 文件 | 说明 | 是否官方 |
|---|---|---|---|
| [akanametov/yolo-face](https://github.com/akanametov/yolo-face) README（dev 分支）与 [release 1.0.0](https://github.com/akanametov/yolo-face/releases/tag/1.0.0) | `yolo26n-face.pt`（约 5.64 MB）、`yolo26s-face.pt` | README「Update」写：「YOLO26-n/s (face) trained on WIDERFace [09.2025]」。权重托管在该 release 的 GitHub Assets。推理示例一律是 `yolo task=detect mode=predict`。 | 否，第三方 |
| [Shubham12864/YOLO26n-face](https://huggingface.co/Shubham12864/YOLO26n-face) | 卡片写单类人脸检测、WIDER FACE、license: agpl-3.0 | 另一社区微调，文件名也不是 akanametov 的 `yolo26n-face.pt`。 | 否 |
| Ultralytics Platform 社区项目，如 [c-h-impala/…/yolo26n-face](https://platform.ultralytics.com/c-h-impala/intelligent-osprey/yolo26n-face) | 平台记录 mAP50 68.7%、mAP50-95 36.5% 等 | 这是平台自己的 val 指标，**不是** WIDER FACE 官方 Easy/Medium/Hard 协议，也不能用来评价 akanametov 权重。 | 否 |

任务书与技术框架指定的具体文件，是 akanametov release `1.0.0` 的 `yolo26n-face.pt`（见技术框架约第 18、86 行）。该 release 标签首次发布时间为 **2023-01-28T18:30:08Z**（GitHub 页面 “Published”），此后不断追加资产；本次见到 `yolo26n-face.pt` 的资产时间戳为 2026-01-21，`yolo26s-face.pt` 为 2026-09-27。README 写「09.2025」与资产时间戳不完全一致，**训练完成的确切日期未核实**。

### 1.3 许可、训练数据、是否输出 5 个关键点

**许可（多层，需分开写）：**

- **Ultralytics 官方代码与官方训练模型**：双许可。文档页写「YOLO26 code, models, and documentation … under AGPL-3.0 and Enterprise licenses。」官方许可页 [ultralytics.com/license](https://www.ultralytics.com/license) 写明：使用 Ultralytics YOLO 的代码、模型、架构、训练管线或「trained/fine-tuned models」，要么把**整个派生项目**按 AGPL-3.0 开源（含应用、脚本、配置，以及适用时的权重），要么购买 Enterprise License。FAQ 还写：「All Ultralytics YOLO trained models fall under the AGPL-3.0 License by default。」本科非商业、且仓库已开源的场景，官方文本把 Academic research 列为 AGPL-3.0 适用情形；若以后做闭源或商业产品，则需要企业许可。本文不判断具体合规细节。
- **akanametov/yolo-face 仓库代码**：仓库根目录 [LICENSE](https://github.com/akanametov/yolo-face/blob/dev/LICENSE) 为 **GNU GPL-3.0**。README 的 License 节仍写「GPL-3.0 / Enterprise」并链到 Ultralytics，这是过时表述（官方现为 **AGPL-3.0** / Enterprise）。**未发现**针对 `yolo26n-face.pt` 的单独权重许可文件。
- **训练数据 WIDER FACE**：官方页 [WIDER FACE](https://shuoyang1213.me/WIDERFACE/index.html) License 栏写「Creative Common License (cc by-nc-nd)」。Hugging Face 数据集卡 [CUHK-CSE/wider_face](https://huggingface.co/datasets/CUHK-CSE/wider_face) 记为 **CC BY-NC-ND 4.0**（署名、非商业、禁止再创作/再分发衍生品）。因此，即使用官方 YOLO 架构微调出的人脸权重，也还要受该数据集条款约束。权重算不算 ND 意义上的 derivative work，属于常见灰色地带，**本文不给出法律结论**，只把条款原文来源列出。WIDER FACE **本身没有关键点标注**（官方说明是框与属性；技术框架第 87 行的勘误与此一致，本次核对官方页后确认页面未提供 5 点标注）。

**5 个面部关键点：现成的 YOLO26n-face 没有。**

- akanametov 全部人脸示例都是 `task=detect`，没有 face-pose 权重，也没有在 README 中声明 5 点输出。
- 官方姿态模型 [Pose Estimation with Ultralytics YOLO](https://docs.ultralytics.com/tasks/pose/) 写明：`yolo26n-pose.pt` 等在 **COCO keypoints** 上预训练，默认预测 **17 个 COCO 人体关键点**（鼻、眼、耳、肩、肘等），不是人脸 5 点。
- 若要「框 + 5 点」单模型，需要自己用 pose 头在 5 点数据上训练（技术框架路线 B）。是否已有公开的 YOLO26 人脸 5 点权重，**本次未发现，标未核实（倾向不存在常用现成权重）**。

---

## 2. YOLO5Face（deepcam-cn/yolov5-face）与本仓库所用 ONNX

### 2.1 代码许可、五点输出、官方精度

- 仓库：[deepcam-cn/yolov5-face](https://github.com/deepcam-cn/yolov5-face)。GitHub 标识与 [LICENSE](https://github.com/deepcam-cn/yolov5-face/blob/master/LICENSE) 均为 **GNU GPL-3.0**。
- 论文：Qi 等，*YOLO5Face: Why Reinventing a Face Detector*，arXiv:[2105.12931](https://arxiv.org/abs/2105.12931)（HTML：[2105.12931v2](https://arxiv.org/html/2105.12931v2)）。文中写明对 YOLOv5 的关键改动包括「adding a five-point landmark regression head」，并在 WIDER FACE 上评测。
- 官方 README「Pretrained-Models / Small family」与论文 Table 4 对 **YOLOv5n-0.5**（论文写作 YOLOv5n0.5，ShuffleNetv2-0.5 骨干）公布的 WIDER FACE **validation** 数字一致：

  | 模型 | Easy | Medium | Hard | Params (M) | FLOPs (G) |
  |---|---:|---:|---:|---:|---:|
  | YOLOv5n-0.5 | **90.76** | **88.12** | **73.82** | 0.447 | **0.571** |

  官方权重获取链为百度网盘与 Google Drive（README Pretrained-Models 表），不是 GitHub Release。
- 本仓库 `detector.py` 与上游导出约定一致：只接受已解码的 `[1,N,16]` = xywh、objectness、**五对 xy**、人脸概率。`LANDMARK_ORDER` 为左眼、右眼、鼻尖、左嘴角、右嘴角。这与论文的五点回归头、以及任务书「框 + 5 点」相符。
- 3DDFA_V2 兼容性：`tddfa.py` 的 `reconstruct(self, rgb, bbox)` 以及 `_prepare_input(rgb, bbox)` **只使用框**（xywh，按上游方式扩边后裁到 120×120）。`reconstruction.py` 调用为 `reconstructor.reconstruct(rgb, faces[0].bbox)`。因此只要检测器给出有效人脸框，即可接入现有重建；5 点不是 3DDFA 输入的必要条件。

### 2.2 清单所指向的 ONNX 许可与来源

本地清单 `backend/model-manifests/yolov5n05-face.research.json`（commit 35c0cd6）要点：

- 文件：`yolov5n-0.5-face.onnx`
- `source_url`：`https://github.com/clibdev/yolov5-face/releases/download/1.0.0/yolov5n-0.5-face.onnx`
- SHA-256：`269eb1e54313f9d1f7941ed9939fa247767539bca5801fc7aa7895960e93ca43`（size 5 928 024）
- `revision` 写明：`release:1.0.0@24e1951…; reviewed-source:d3246815d8747d26a91bf980afef2485bc29f839; exact-exporter-unverified`
- `code_license`：GPL-3.0（上游/发布者代码，不构成单独的权重许可）
- `weights_license`：原文即「No explicit upstream weight license found… Project owner decision 2026-11-01: used only for non-commercial academic research/demo… weights are not redistributed… This is not an upstream grant and not a legal clearance.」
- 决定人：宋明耀（member B, project owner），2026-11-01

本次核对 [clibdev/yolov5-face](https://github.com/clibdev/yolov5-face) 在清单所记 commit [`d324681`](https://github.com/clibdev/yolov5-face/blob/d3246815d8747d26a91bf980afef2485bc29f839/README.md) 的 README 与 [LICENSE](https://raw.githubusercontent.com/clibdev/yolov5-face/d3246815d8747d26a91bf980afef2485bc29f839/LICENSE)：

- 该仓库是 deepcam-cn/yolov5-face 的 fork；**LICENSE 同样是 GPL-3.0**。
- README 声明提供「Original pretrained models and converted ONNX models」。YOLOv5n-0.5-Face 的 ONNX SHA-256 为 **`269eb1e54313f9d1f7941ed9939fa247767539bca5801fc7aa7895960e93ca43`**，与本仓库清单 **完全一致**。
- README **没有**另写一份权重专用许可，也没有声明这些 ONNX 可按与 GPL 不同的条款使用。
- 叉仓库评测表复述了与论文相同的 Easy/Medium/Hard 数字，但把 GFLOPS 写成 **1.5**（官方/论文为 **0.571**）。应以论文与 deepcam README 为准；clibdev 的 FLOPs 口径 **未与官方对齐**。
- 清单中的 `exact-exporter-unverified` 仍然成立：可以确认文件哈希与 fork 发布页一致，但**不能**在不下载、不反推导出脚本的前提下，证明该 ONNX 一定由某一精确提交、精确命令从官方 `.pt` 导出。本次按任务要求未下载该 ONNX。

训练数据同样是 WIDER FACE（deepcam 与 clibdev 的训练/评测说明均指向该数据集），因此第 1.3 节的 CC BY-NC-ND 约束同样适用。

**本仓库与 GPL 的边界（本次核对）：** AgeMorph3D 源码许可为 **MIT License**（本地与 GitHub `main` 的 [LICENSE](https://github.com/xiaominaimoyu/AgeMorph3D/blob/main/LICENSE)，Copyright (c) 2026 MingYao Song）。检测实现 `backend/src/agemorph3d/detector.py` 通过 `onnxruntime` 加载已解码的 YOLO5Face ONNX；第 3 行只说明导出格式约定（「Export semantics: deepcam-cn/yolov5-face models/yolo.py (export_cat=True)」），随后在本模块内实现 letterbox / 阈值 / NMS，并不包含上游训练或原始检测头解码代码。在本地源码树中未发现 vendored 的 `models/yolo.py`、`ShuffleV2Block` 等 yolov5-face 源文件，也没有把 GNU GPL 全文放进本仓库 LICENSE。GPL-3.0 对「仅加载第三方 ONNX 权重、未复制 GPL 源代码」是否适用，以及该权重本身是否受 GPL 覆盖，**并不确定**；本文不做法律裁决。闭源分发时的 copyleft 风险因此也不能单凭「用了 ONNX」一句话断定。

---

## 3. 对比表与给导师的事实摘要

### 3.1 YOLO26n-face vs 当前 YOLO5Face

| 项目 | YOLO26n-face（任务书/技术框架计划） | YOLO5Face yolov5n-0.5（当前代码） |
|---|---|---|
| 是否存在 | **官方同名权重不存在**。第三人 `yolo26n-face.pt` 存在于 akanametov/yolo-face release 1.0.0 | 存在。官方 pt 在 deepcam README 的网盘/Drive；本仓库用 clibdev 导出的 ONNX |
| 权重位置 | `https://github.com/akanametov/yolo-face/releases/download/1.0.0/yolo26n-face.pt`（约 5.64 MB）。官方通用检测是 `yolo26n.pt`（COCO） | 清单：`https://github.com/clibdev/yolov5-face/releases/download/1.0.0/yolov5n-0.5-face.onnx`，SHA-256 已核对 README |
| 许可 | 推理依赖 Ultralytics（AGPL-3.0 / Enterprise）；akanametov 仓库代码 GPL-3.0；权重无单独许可；训练数据 WIDER FACE CC BY-NC-ND | 代码 GPL-3.0（deepcam 与 clibdev）；权重无单独上游许可；训练数据同样是 WIDER FACE；清单已记录所有者学术非商业、不转分发决定（非上游授权） |
| 关键点 | **只出框**。官方 pose 是 COCO 17 点人体，不是人脸 5 点 | **框 + 5 点**（输出 `[1,N,16]`），与任务书表述一致 |
| 已公布精度 | akanametov **未给出** YOLO26-face 的 WIDER Easy/Medium/Hard 数字（**未核实**）。不得把 COCO 40.9 mAP 当作人脸 AP | 论文与官方 README：**90.76 / 88.12 / 73.82**（WIDER FACE val，VGA / max side 640） |
| 与 3DDFA_V2 的衔接 | 只出框即可作为 `reconstruct(..., bbox)` 的输入；但会失去现成 5 点，实时/前端 5 点需另接模型或从 68 点投影 | 已接通。重建只用框；5 点已用于显示 |
| 工程状态 | 仓库中无 YOLO26 权重清单，无 `yolo_face.py` 实现（见 MU-1 §7 第 1 条） | `detector.py` + 研究清单已落地（B0 探针） |
| 再训练成本 | 若要坚持「框+5 点」，需自训 pose 头，并重新写检测后端与清单 | 已有微调脚本规划（T02），但正式训练尚未开始 |

### 3.2 对本科学位论文的选项（不替用户决定）

**选项 A（推荐作为当前主线向导师说明）：继续使用 YOLO5Face。**

- 理由：已经实现并与 3DDFA_V2 对齐；满足任务书「框 + 5 点」的能力描述；有可引用的正式论文与公开 val 数字；换模型并不自动消除 WIDER FACE 非商业/ND 问题，也还要处理 GPL。
- 风险：名称与任务书原文「YOLO26n-face」不一致，必须在开题中主动说明，不能改名顶替；权重没有单独上游许可（与选项 B 同类问题）；本仓库为 MIT、只通过 onnxruntime 加载 ONNX，GPL 对权重是否适用尚不确定（见 §2.2）。

**选项 B：改用 akanametov 的 YOLO26n-face 做检测主线。**

- 理由：名称更贴近任务书；可走官方 Ultralytics 训练/导出工具链；官方 YOLO26 本身是 2026 年正式版。
- 代价：现成权重**没有 5 点**；必须改写 `detector.py` 与清单；实时 5 点要么缺失，要么另训/另接；**没有**与 YOLO5Face 同口径的已发表 Easy/Medium/Hard 数字；引入 AGPL-3.0 义务；技术框架中的 COCO 指标不能写进检测实验表。对工期偏紧的本科毕设，切换成本明显高于收益。

**选项 C（对照，不替换主线）：** 主线保持 YOLO5Face；若时间允许，用 YOLO26n-face 做「只出框」的对照实验（仍用 3DDFA 吃框）。论文写清楚两条路线的输出差异。

### 3.3 建议告诉导师的话（事实清单，可直接改写成邮件/开题段落）

> 1. 任务书写的 YOLO26n-face：YOLO26 是 Ultralytics 2026-01-14 的官方版本，但官方没有人脸专用权重。名为 yolo26n-face.pt 的文件来自第三方仓库 akanametov/yolo-face，在 WIDER FACE 上做检测微调，只输出人脸框，不输出 5 个面部关键点。官方 yolo26n-pose 是人体 17 点，不能当作人脸 5 点。
> 2. 当前系统已经实现的是 YOLO5Face（yolov5n-0.5 ONNX）：有正式论文，验证集 Easy/Medium/Hard 为 90.76 / 88.12 / 73.82，输出框和 5 点；三维重建（3DDFA_V2）实际只使用框。
> 3. 技术框架里引用的 mAP 40.9、1.7 ms 等是 YOLO26n 在 COCO 上的通用检测数字，不是人脸检测结果，开题里不应再这样引用。
> 4. 两条检测路线都用了 WIDER FACE（CC BY-NC-ND），都只能按非商业科研使用；YOLO26 路线额外涉及 Ultralytics AGPL-3.0/企业许可。现用 YOLO5Face ONNX 没有单独的上游权重许可。研究清单把检测/重建权重登记为学术非商业、并写「不转分发」，这只是项目所有者的登记，不是上游授权。
> 5. 关于 BFM：用户已在文档中确认非商业研究使用，但「仓库不转分发」与公开事实不符。公开仓库 xiaominaimoyu/AgeMorph3D 的 Release `assets-bfm-2009`（2026-10-24 发布）附有可匿名下载的原始包 `BaselFaceModel.tgz`（240,287,841 字节）。README 第 47 行和 docs/model-assets.md 第 37 行也写了「改以 GitHub Release 附件分发」。这与 BFM 非商业许可 §3.3（禁止把 DATA 全部或部分分发给任何第三方）相冲突。是否删除该附件或改为私有，由我本人决定。**（时点性陈述）**「目前尚未处理」仅反映撰写 RD-1 修订时（2026-11-16）的核验结果。MU-5 起草给导师的说明之前，必须重新核查该 Release 附件是否仍公开；是否告知导师、如何表述，由用户本人决定。
> 6. 建议：开题与实现以 YOLO5Face 为准，在文中说明与任务书名称的差异；YOLO26n-face 若做，仅作为对照或后续工作，不在现阶段替换主线。是否采纳请导师裁定。

（给导师的成稿邮件由 MU-5 在 RD-1 通过后起草，须经用户确认再发送。）

---

## 4. MICA、FLAME、BFM 与 3DDFA_V2

### 4.1 MICA（Zielonka, Bolkart, Thies, ECCV 2022）

- 论文：*Towards Metrical Reconstruction of Human Faces*，ECCV 2022。官方仓库：[Zielon/MICA](https://github.com/Zielon/MICA)。项目页与安装说明见仓库 README。
- **代码与模型许可**：仓库 [LICENSE](https://github.com/Zielon/MICA/blob/master/LICENSE) 为 MPI-IS / Max-Planck 的「Software Copyright License for non-commercial scientific research purposes」。要点（原文大意，以链接全文为准）：
  - 仅授予个人、非独占、不可转让、免费的权利，用于**和平的非商业科研、非商业教育或非商业艺术项目**；
  - 禁止商业、色情、军事、监控用途，包括嵌入商业产品或服务；
  - **不得**在未经 Max-Planck 书面许可的情况下复制、修改并提供给第三方；
  - 除一份存档副本外，**不得再分发**；
  - 商业许可联系：`justus.thies@tuebingen.mpg.de`。
  克隆或下载该仓库即视为接受条款。本科毕业设计的非商业科研使用，与该许可的字面范围相符；**不能**把权重或 FLAME 衍生资产放进公开仓库分发。
- **注册与获取**：README 要求在 [flame.is.tue.mpg.de](https://flame.is.tue.mpg.de/) 注册账号，把 FLAME2020 放到指定目录；`install.sh` 用该账号密码从 MPI 文件服务器下载 `FLAME2020.zip`，并另从 Google Drive 下载 `mica.tar` 以及 InsightFace 的 antelopev2、buffalo_l。预训练权重另有 Drive 链接（README Pre-trained Models）。**没有免注册的官方镜像被本次确认为“可随意再分发”。**
- **输出是不是完整的 FLAME 表情+姿态？主要是身份形状。** demo.py（[源码](https://raw.githubusercontent.com/Zielon/MICA/master/demo.py)）在解码后保存：
  - `opdict['pred_canonical_shape_vertices']` → `mesh.ply` / `mesh.obj`（注释写按毫米保存）；
  - `opdict['pred_shape_code']` → **`identity.npy`**；
  - 由形状网格计算的 7/68 路标。
  没有保存表情系数或与 3DDFA 类似的 62 维参数向量。数据集说明 [datasets/README.md](https://github.com/Zielon/MICA/tree/master/datasets) 也写「It consists of shape geometry only」，并把 FLAME 参数拆成 `shape_params: betas[:300]`、`expression_params: betas[300:]`。因此：MICA 提供的是**度量尺度下的 FLAME 身份形状**，不是本仓库 `shape40 + expr10 + 姿态` 的即插即用替代。完整表情重建通常还要另接 DECA/EMOCA 等（FLAME 官网新闻亦将它们列为独立框架）。
- **依赖的数据集与第三方模型（各有独立条款）：**
  - MICA 训练集由约 8 个已有三维人脸集合在统一 FLAME 拓扑下配准（Stirling、D3DFACS、Florence、LYHM、FaceWarehouse、FRGC、BP4D+ 等；datasets README 写约 2315 人）。该页写明：「This dataset is for academic, non-commercial usage only… the license is shared and applies equivalently to both, the original and the corresponding derived one. Please read the original license of each original dataset」。FRGC 等还要求先向原方申请再向 `mica@tue.mpg.de` 确认。
  - 从零训练需 Glint360K 上的 ArcFace 初始化（README）。
  - demo 还依赖 InsightFace 的 RetinaFace 检测与 ArcFace 对齐模型（`install.sh` / demo.py）。这些模型的条款**不在** MICA LICENSE 覆盖范围内，**本次未逐份核验 InsightFace 许可全文**（标未核实）。

### 4.2 FLAME

- 官网：[https://flame.is.tue.mpg.de/](https://flame.is.tue.mpg.de/)。下载须「sign up and agree to the license」。
- **学术模型许可**（适用于 FLAME 2017 / 2019 / **2020** / 2023 以及 FLAME 2020 Blender 插件）：[modellicense.html](https://flame.is.tue.mpg.de/modellicense.html)。与 MICA 类似的非商业科研/教育/艺术条款：单用户、不可转让、禁止再分发与商业/色情/军事/监控用途；商业联系 `ps-license@tue.mpg.de`。MICA 的 `install.sh` 下载的是 **FLAME2020**，因此走的是这一学术许可，**不是**下面的开放许可。
- **FLAME 2023 Open**：同一许可页写明 **仅** 该变体为 Creative Commons Attribution（CC-BY），允许在署名等条件下用于包括商业在内的目的；仍禁止色情与诽谤性伪造内容。官网新闻（约 11/25）也宣布了这一开放模型。MICA 当前安装路径是否兼容 FLAME 2023 Open，**未核实**。不能假定“换成 Open 模型就可以跳过注册或自动清除 MICA 自身的非商业条款”。
- 维度（官网观众与论文）：形状主分量可达 300，表情 100，另有头部/下颌等姿态；与 BFM 裁剪版的 40+10 不是同一组基。

### 4.3 3DDFA_V2 与 Basel Face Model 2009

- **3DDFA_V2 代码许可**：仓库 [cleardusk/3DDFA_V2](https://github.com/cleardusk/3DDFA_V2) 在清单所钉 commit [`1b6c676`](https://github.com/cleardusk/3DDFA_V2/blob/1b6c67601abffc1e9f248b291708aef0e43b55ae/LICENSE) 为 **MIT License**（Copyright 含 Jianzhu Guo / CBSR 等）。MIT 覆盖的是软件；**不覆盖 BFM 数据**。
- **BFM 数据**：同一 commit 的 [bfm/readme.md](https://github.com/cleardusk/3DDFA_V2/blob/1b6c67601abffc1e9f248b291708aef0e43b55ae/bfm/readme.md) 写明：`bfm_noneck_v3.pkl` 这一修改版 BFM2009「is only for academic use. For commercial use, you need to apply for the commercial license」，并指向巴塞尔官方页。
- **BFM 2009 官方条款**：
  - 下载页 [faces.dmi.unibas.ch/bfm … downloads](https://faces.dmi.unibas.ch/bfm/main.php?id=downloads&nav=1-2)：须提供真实姓名、机构、有效邮箱，同意许可后才寄送登录与下载链接。关键点再次强调：**仅限内部非商业科研、评估或测试**；禁止再分发或再许可；发表须引用 Paysan 等 2009 文，并把公开报告寄给 Principal Investigator。商业许可联系 Unitectra（`mail@unitectra.ch`）。
  - 许可全文 PDF：[BFM_NonCommercial_License_Agreement.pdf](https://faces.dmi.unibas.ch/bfm/content/basel_face_model/downloads/BFM_NonCommercial_License_Agreement.pdf)。**§3.3** 原文为：*“LICENSEE shall not reverse engineer, disassemble or modify the DATA, or create derivatives based on the DATA, or rent, lease, loan, sub-license, or distribute the DATA in whole or in part to a different organizational unit of the LICENSEE or any third party.”* 下载页「Terms of Non-Commercial Use」亦概括为「NO DISTRIBUTION: You are not allowed to sublicense or distribute the DATA in whole or in part to any third party。」§3.2 只允许为存档或灾备制作一份备份，并不允许向第三方分发。
- 清单与部分文档的「不转分发」表述**与公开仓库现状不符**，须如实记录如下（本次核验只读元数据与网页，**未下载该附件**）：
  - 本地与 GitHub `main` 的 [README.md 第 47 行](https://github.com/xiaominaimoyu/AgeMorph3D/blob/main/README.md) 写：「原始 `BaselFaceModel.tgz` 因体积超过普通文件与 LFS 限制，改以 [Release 附件](https://github.com/xiaominaimoyu/AgeMorph3D/releases/tag/assets-bfm-2009) 分发」。同一文件第 43 行仍写研究清单「仓库不转分发权重」。
  - 本地与 GitHub `main` 的 [docs/model-assets.md 第 37 行](https://github.com/xiaominaimoyu/AgeMorph3D/blob/main/docs/model-assets.md) 写：用户原始 `BaselFaceModel.tgz` 为 **240,287,841** 字节（229.2 MiB），「不进入 Git 历史……改以 GitHub Release 附件分发」，并给出附件 SHA-256 `d6cf2dffb74404f4f7ee2cd56f611e6fdcb22081ebf993f8b01edf6207f6cce9`。第 3 行同样写「仓库不转分发」。
  - 本地仓库副本（`/workspace/AgeMorph3D`，commit `35c0cd6`；本次只读本地文件，未再访问 GitHub）中，至少还有三处同样写「不转分发」：`docs/干净环境与离线复现准备.md` 第 83 行（「只用于非商业学术/毕设演示、仓库不转分发。这不是上游授权。」）；`docs/模型资产诊断与严格服务缺项记录.md` 第 3 行（「非商业学术研究/毕业设计演示、本仓库不转分发」）；`docs/验收矩阵.md` 第 3 行（「学术非商业、不转分发」）。
  - 公开仓库可见性：GitHub API `GET /repos/xiaominaimoyu/AgeMorph3D` 返回 `private: false`，`visibility: public`（https://api.github.com/repos/xiaominaimoyu/AgeMorph3D ）。
  - 公开 Release：[assets-bfm-2009](https://github.com/xiaominaimoyu/AgeMorph3D/releases/tag/assets-bfm-2009)（API：https://api.github.com/repos/xiaominaimoyu/AgeMorph3D/releases ）。字段：`name` =「BFM 2009 research asset (BaselFaceModel.tgz)」；`draft: false`；`prerelease: false`；`published_at: 2026-10-24T11:23:38Z`（2026-10-24 13:23 Europe/Berlin，当时为夏令时 UTC+2）；附件 `BaselFaceModel.tgz`，`state: uploaded`，`size: 240287841`；API `digest` 为 `sha256:d6cf2dffb74404f4f7ee2cd56f611e6fdcb22081ebf993f8b01edf6207f6cce9`（与台账一致，本次未下载文件重算哈希）；`browser_download_url` 为 `https://github.com/xiaominaimoyu/AgeMorph3D/releases/download/assets-bfm-2009/BaselFaceModel.tgz`。
  - 匿名可下载：对上述 URL 做未认证 HTTP HEAD（不跟随重定向、不取正文，本次 `size_download=0`）返回 **HTTP 302**，`Location` 指向 `release-assets.githubusercontent.com`，响应头含 `filename=BaselFaceModel.tgz`。公开 Release 附件因此可在未登录时获取。源码 Git 树中未见该 `.tgz`（与文档「不进入 Git 历史」一致），但 **Release 附件属于向第三方分发**，不能用「未进 Git」否定分发事实。
  - 这与上列 BFM 许可 **§3.3** 及官网「NO DISTRIBUTION」概括相冲突。该 Release 的说明正文（GitHub Releases API 返回的 `body` 字段，2026-11-16 查阅 `GET https://api.github.com/repos/xiaominaimoyu/AgeMorph3D/releases`，对应 tag `assets-bfm-2009`）写有：「本附件存放用户原始 BFM 资产包，供本地研究环境复原，不随源码仓库分发。」但同一份 `body` 把该文件作为公开 Release 附件列出，且未认证即可下载，因此「不随源码仓库分发」并不能否定公开附件分发的事实。
  - **是否删除该附件、改为私有 Release，或采取其他处理，须由用户本人决定。本文只记录核实结果，不写成已经处理，也不代替用户操作。**
- 本仓库清单 `3ddfa-v2.research.json` 记录：用户曾于 **2026-10-19** 确认 BFM 非商业科研授权；回归器 ONNX、param_stats 与裁剪 BFM 没有单独的上游权重许可；所有者 2026-11-01 决定仅用于本科非商业科研/演示，并写本仓库不转分发。后一句与公开 Release 事实不符（见上）。「2026-10-19 已获授权」仍是仓库自述，**本次未向巴塞尔或用户本人重新核验授权邮件**。
- 本仓库重建使用裁剪 BFM：形状 40 维、表情 10 维、回归器输出 62 维（`tddfa.py`）。年龄方向在这一 **shape40 空间**中学习（`prepare_bfm_age.py`、`age_shape.py` 等，见 MU-1 §8.1，状态为研究中、`years_calibrated=false`）。

### 4.4 若切换到 FLAME 会打断什么

硬性不兼容（已有代码与计划文档均可印证，技术框架自身也把「BFM→FLAME 拓扑差异」列为 W17 闸门）：

1. **年龄方向空间**：当前方向是在 BFM shape40 里回归的；FLAME 是另一组基底（通常 300 维形状）。不能把已有系数搬到 FLAME 上，必须在 FLAME 形状空间重新采集与回归。仓库文档 `docs/模型与数据路线核验.md` 亦写「完整 BFM、3DDFA 裁剪版本与 FLAME 不能跨基混训」。
2. **网格拓扑与 UV**：3DDFA 使用的是 no-neck 裁剪 BFM 与自带 UV；FLAME 是全头（含颈部等）另一套三角化与 UV。GLB / morph target / 前端演示头模都要重做。
3. **参数契约**：现接口是 62 维（位姿相关 12 + shape40 + expr10）。MICA 主输出是身份形状码与规范顶点，没有同构的 expr10，实时位姿链也不同。
4. **许可与获取**：需完成 FLAME（及 MICA）注册；按这两份许可，模型与数据不得再分发给第三方（不仅是「不进 Git」，也包括公开 Release 附件；现有 BFM 附件问题见 §4.3）。InsightFace 等依赖还要另核条款。MICA 常用堆栈还可能涉及 pytorch3d 等，技术框架已将其列为风险。
5. **工期**：MU-1 已确认源码树**没有** `mica_wrapper.py` 或 FLAME 实现。在开题阶段把主线改成尚未落地、且会作废已有年龄形状工作的方案，风险很高。

**选项（同样不替用户决定）：** 主线保持 3DDFA_V2 + BFM（任务书允许主线受阻时用该保底）；MICA+FLAME 作为相关工作与（可选）对照，只有在已完成官方注册、且导师明确要求对比度量重建时再另开实验分支。不要把计划中的 MICA 画进当前系统架构主框（MU-1 §7 第 2 条）。

---

## 5. 综合结论与建议行动（附置信度）

| ID | 结论 / 建议 | 置信度 | 依据 |
|---|---|---|---|
| C1 | YOLO26 是 2026-01-14 发布的 Ultralytics 官方模型族 | 高 | 官方文档、新闻稿、社区公告 |
| C2 | 不存在 Ultralytics 官方 `YOLO26n-face` 权重 | 高 | 官方模型表与 yolo26 仓库未列出 |
| C3 | akanametov 的 `yolo26n-face.pt` 真实存在，WIDER FACE 训练，检测任务，第三人权重 | 高 | 其 README 与 release 1.0.0 资产列表 |
| C4 | 该权重（以及目前可见的同名社区模型）**不出人脸 5 点**；官方 pose 是人体 17 点 | 高 | akanametov 用法均为 detect；Ultralytics pose 文档 |
| C5 | 技术框架用 COCO 40.9 mAP 等为 YOLO26n-face 背书，口径错误，开题应改正 | 高 | 官方检测表写明 COCO 80 类 |
| C6 | 本仓库实际检测器是 YOLO5Face ONNX，输出框+5 点；3DDFA 只用框 | 高 | 本地 `detector.py` / `tddfa.py` / 清单 |
| C7 | yolov5n-0.5 的官方 val 指标为 90.76 / 88.12 / 73.82 | 高 | 论文 Table 4 与 deepcam README（同一数字） |
| C8 | 清单 ONNX 的 SHA-256 与 clibdev README 一致；仍无单独权重许可；导出过程未被本任务复现 | 高（哈希）/ 中（许可表述） | 清单 + clibdev README/LICENSE；未下载文件做字节复核 |
| C9 | 两条人脸检测路线都受 WIDER FACE CC BY-NC-ND 约束；YOLO26 路线另有 AGPL-3.0/企业许可 | 高（条款存在）/ 中（权重是否构成 ND 派生——法律问题，不裁决） | WIDER 官方页、HF 数据集卡、Ultralytics 许可页 |
| C10 | 建议学位论文主线保持 YOLO5Face，不在现阶段切换 YOLO26n-face；向导师书面说明名称差异 | 高（工程判断） | 第 3 节对比；最终由导师裁定 |
| C11 | MICA 与 FLAME 2020 均为 MPI 非商业科研许可，须官网注册，禁止再分发；MICA 主要输出身份形状，不是 BFM shape40 的替换 | 高 | LICENSE、modellicense、demo.py、datasets README |
| C12 | 切换到 FLAME 会使 BFM shape40 年龄方向及现有拓扑/UV/接口作废，开题主线应维持 3DDFA_V2+BFM | 高 | 本地代码与技术框架 W17 闸门表述 |
| C13 | 公开仓库 Release `assets-bfm-2009` 挂有可匿名下载的原始 `BaselFaceModel.tgz`（240,287,841 B，2026-10-24 发布）。清单/README 第 43 行、台账第 3 行，以及本地 `docs/干净环境与离线复现准备.md` 第 83 行、`docs/模型资产诊断与严格服务缺项记录.md` 第 3 行、`docs/验收矩阵.md` 第 3 行的「仓库不转分发」与 README 第 47 行、台账第 37 行及该 Release 的公开事实不符，并与 BFM 非商业许可 §3.3（禁止将 DATA 全部或部分分发给任何第三方）相冲突。是否删除或改为私有附件由用户本人决定；本文未处理该附件。MU-5 起草前须重查附件状态。 | 高（Release 元数据、文档原文、许可条款均已核；未下载附件重算哈希） | GitHub API releases、README L47、model-assets.md L37、上述三份本地文档、BFM 许可 PDF §3.3 |
| C14 | 清单所记「用户 2026-10-19 已确认 BFM 非商业授权」是仓库自述，本次未复核邮件或巴塞尔账号 | 中（记录存在，授权本身未再核实） | `3ddfa-v2.research.json` |
| C15 | 本仓库源码为 MIT；YOLO5Face 以 onnxruntime 加载 ONNX，未见复制 GPL 源码。GPL 对权重是否适用不确定 | 高（许可文件与源码检索）/ 中（法律适用） | 仓库 LICENSE、`detector.py` |

**建议行动（按优先级，均须用户或导师确认后才改仓库/发邮件）：**

1. 把本修订稿再交 Sentinel（SN-2）复审；通过后由 Atlas 知会用户。
2. **BFM 公开 Release 附件**：把核实结果告知用户。是否删除 `assets-bfm-2009` 中的 `BaselFaceModel.tgz`、改为私有 Release，或采取其他处理，**只能由用户本人决定并操作**。本文和审核都不代替用户处理，也不把该附件写成已处理。
3. 开题报告 / PPT / 架构图按 MU-1：主框写 YOLO5Face 与 3DDFA_V2+BFM；YOLO26、MICA+FLAME 进「计划中」。给导师的说明须如实写第 3.3 节关于 BFM 附件的现状，不要再写「仓库不转分发」。
4. 修正技术框架中把 COCO 指标当作人脸指标的表述（此项若改仓库文档，需用户批准）。
5. MU-5 可基于第 3.3 节起草给导师的说明，**仅在用户确认后发送**。
6. 不在本任务下载任何 YOLO / MICA / FLAME / BFM 权重或该 Release 附件。若以后要做 YOLO26 对照，先单独做许可与清单，再谈下载。
7. 若导师坚持 MICA 对照：先由学生在 FLAME 官网注册并保存许可同意记录，再评估工作量；不要与现有 BFM 年龄方向混训。

---

## 6. 未核实与限制

1. akanametov `yolo26n-face.pt` 在 WIDER FACE Easy/Medium/Hard（官方评测协议）上的具体 AP：**未核实**（README 未给数字，本次未下载权重、未跑评测）。
2. `yolo26n-face.pt` 的精确训练日期、超参、是否从官方 `yolo26n.pt` 微调：**未核实**（README 写 09.2025，与 release 资产时间戳不完全一致）。
3. 是否存在任何公开的 YOLO26 人脸 5 点（pose）权重：**未发现，视为未核实**。
4. 技术框架所写 `ultralytics==8.4.178` 是否为查阅当日最新版本：**未核实**。
5. clibdev ONNX 是否由某一精确上游提交与导出命令生成（清单已标 `exact-exporter-unverified`）：**未核实**（本次未下载 ONNX，也未复现导出）。
6. InsightFace antelopev2 / buffalo_l / RetinaFace 的完整许可条款：**未核实全文**。
7. MICA 与 FLAME 2023 Open（CC-BY）的兼容性：**未核实**。
8. 用户 2026-10-19 的 BFM 授权邮件 / 巴塞尔账号状态：仅见清单自述，**未再核实**。
9. AFLW2000-3D 许可与体积不在本任务范围（RD-3）。
10. 本文不构成律师意见；AGPL/GPL 与 CC BY-NC-ND 对「微调权重」的交叉适用，以及公开 Release 分发 BFM 的法律后果，只列到来源与事实，不做合规裁决或处理。
11. SAM、pSp/e4e 的许可、训练数据与权重来源不在 RD-1 范围，须由其他任务核查（资产台账已提到 SAM，本文不对其条款下结论）。

本次操作：只读取网页、GitHub API/README/LICENSE、模型卡说明和本地仓库文本；对 `BaselFaceModel.tgz` 的下载地址只做了不跟随重定向的 HEAD，没有下载 `.tgz` / `.pt` / `.onnx` / `.pkl` / 数据集，也没有修改 `/workspace/AgeMorph3D` 或该 Release。

---

## 7. 来源一览

查阅日期均为 2026-11-16（Europe/Berlin）。

### 官方与论文

- https://docs.ultralytics.com/models/yolo26 — YOLO26 正式文档、发布月份、官方模型表、COCO 指标、AGPL-3.0/Enterprise 声明
- https://www.ultralytics.com/news/ultralytics-redefines-state-of-the-art-vision-ai-with-yolo26 — 2026-01-14 正式发布新闻稿
- https://community.ultralytics.com/t/yolo26-available-now/1746 — `ultralytics>=8.4.0`
- https://www.ultralytics.com/license — AGPL-3.0 与 Enterprise 的适用范围（含微调模型）
- https://docs.ultralytics.com/tasks/pose/ — YOLO26-pose 为 COCO 17 点人体关键点
- https://arxiv.org/abs/2606.03748 — YOLO26 技术报告
- https://github.com/deepcam-cn/yolov5-face — YOLO5Face 仓库、精度表、预训练链接
- https://github.com/deepcam-cn/yolov5-face/blob/master/LICENSE — GPL-3.0
- https://arxiv.org/abs/2105.12931 与 https://arxiv.org/html/2105.12931v2 — 五点头、Table 4 数字
- https://shuoyang1213.me/WIDERFACE/index.html — WIDER FACE 官方页，License: cc by-nc-nd
- https://huggingface.co/datasets/CUHK-CSE/wider_face — 记为 CC BY-NC-ND 4.0
- https://github.com/Zielon/MICA — MICA 官方仓库与 README
- https://github.com/Zielon/MICA/blob/master/LICENSE — MICA 非商业科研许可
- https://raw.githubusercontent.com/Zielon/MICA/master/demo.py — 输出 `identity.npy` / 规范形状网格
- https://github.com/Zielon/MICA/tree/master/datasets — 训练子集、非商业、形状几何
- https://flame.is.tue.mpg.de/ — 须注册；FLAME 2020 等说明
- https://flame.is.tue.mpg.de/modellicense.html — 学术许可与 FLAME 2023 Open（CC-BY）的区分
- https://github.com/cleardusk/3DDFA_V2/blob/1b6c67601abffc1e9f248b291708aef0e43b55ae/LICENSE — MIT
- https://github.com/cleardusk/3DDFA_V2/blob/1b6c67601abffc1e9f248b291708aef0e43b55ae/bfm/readme.md — 修改版 BFM 仅学术使用
- https://faces.dmi.unibas.ch/bfm/main.php?id=downloads&nav=1-2 — BFM 2009 注册下载与非商业要点（含 NO DISTRIBUTION）
- https://faces.dmi.unibas.ch/bfm/content/basel_face_model/downloads/BFM_NonCommercial_License_Agreement.pdf — BFM 非商业许可全文（§3.3 禁止向第三方分发 DATA）
- https://github.com/xiaominaimoyu/AgeMorph3D — 公开仓库（API：`private: false`）
- https://github.com/xiaominaimoyu/AgeMorph3D/releases/tag/assets-bfm-2009 与 https://api.github.com/repos/xiaominaimoyu/AgeMorph3D/releases — Release 元数据（标签、发布时间、附件名与字节数）；本次未下载附件
- https://github.com/xiaominaimoyu/AgeMorph3D/blob/main/README.md — 第 43、47 行（与本地副本一致）
- https://github.com/xiaominaimoyu/AgeMorph3D/blob/main/docs/model-assets.md — 第 3、37 行（与本地副本一致）
- https://github.com/xiaominaimoyu/AgeMorph3D/blob/main/LICENSE — 本仓库 MIT License

### 第三方权重与 fork

- https://github.com/akanametov/yolo-face/blob/dev/README.md — YOLO26-n/s face、WIDERFace、detect 用法、仓库 LICENSE 指向
- https://github.com/akanametov/yolo-face/blob/dev/LICENSE — GPL-3.0
- https://github.com/akanametov/yolo-face/releases/tag/1.0.0 — `yolo26n-face.pt` 等资产
- https://huggingface.co/Shubham12864/YOLO26n-face — 另一社区 YOLO26n 人脸检测卡（对照，非任务书指定文件）
- https://platform.ultralytics.com/c-h-impala/intelligent-osprey/yolo26n-face — 平台社区训练指标（非官方 WIDER 协议）
- https://github.com/clibdev/yolov5-face/blob/d3246815d8747d26a91bf980afef2485bc29f839/README.md — ONNX 链接与 SHA-256
- https://raw.githubusercontent.com/clibdev/yolov5-face/d3246815d8747d26a91bf980afef2485bc29f839/LICENSE — GPL-3.0

### 本地仓库（只读）

- `backend/model-manifests/yolov5n05-face.research.json`
- `backend/model-manifests/3ddfa-v2.research.json`
- `backend/src/agemorph3d/detector.py`、`tddfa.py`、`reconstruction.py`
- `docs/AgeMorph3D_技术框架与模块行动计划.md`、`docs/模型与数据路线核验.md`、`docs/毕业设计要求与交付清单.md`
- `/workspace/AgeMorph3D_tasks/MU-1_示意图规格.md` §7
- `/workspace/AgeMorph3D_后续任务规划_v2.md` RD-1 条目（约第 107 行）
