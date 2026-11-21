# RD-2 开题文献清单

- 任务：Atlas 规划 v2 的 RD-2（开题文献包）。规划原文要求至少 20 篇，含 BibTeX 与 DOI 或 arXiv 链接，并标出与 A/B 谁的分工相关；为 A、B 各推荐 2—3 篇外文翻译原文候选。本文文件名按本次任务书写作 `RD-2_开题文献清单.md`（规划表中的产出名是 `RD-2_文献清单.md`）。
- 查阅日期：2026-11-16（UTC+8 / Asia/Shanghai）。下文 URL 与检索均在该日访问。
- 范围：只做文献与元数据核实，**未下载**论文 PDF、数据集、权重或模型文件；**未访问、也未改动**项目仓库 `xiaominaimoyu/AgeMorph3D` 的 GitHub。本地只读查阅了 `/workspace/AgeMorph3D` 中的分工说明，以及 `/workspace/AgeMorph3D_后续任务规划_v2.md` 第 108—112 行。
- 核实途径：每条正式出版物的题名、作者、DOI、页码与 BibTeX，优先取自 Crossref 官方接口 `https://api.crossref.org/works/{DOI}/transform/application/x-bibtex`。arXiv 题名、作者与许可取自当日打开的摘要页（`https://arxiv.org/abs/{id}`）。OpenAlex 仅用于：核验 WIDER FACE 的正确 arXiv 编号、IPCGAN 作者顺序，以及部分许可字段的旁证。规划要求优先 DBLP，但当日 `dblp.org` 返回 Anubis 人机验证页，**本次未能使用 DBLP BibTeX**。
- 原则：不编造文献。查不到的写「未核实」。BibTeX 保持 Crossref 返回原文（含其对 LNCS 章节使用的 `@inbook`、个别姓名与空格写法）；FADING 已正式发表于 BMVC 2023，BibTeX 以官方会议条目为底并补上 arXiv 编号与 DataCite DOI；DiffAge3D 仍为预印本，有 DataCite/arXiv DOI（doi.org 可跳转），Crossref 无会议/期刊记录。IJCV 两条的 `year`/`month` 改用纸刊时间，不照抄 Crossref 把 `issued`（在线首发）写成 `year` 的做法。本文不是法律意见，也不构成对翻译版权的授权判断。
- 配套文件：`/workspace/AgeMorph3D_tasks/RD-2_开题文献清单.bib`（与正文中的 BibTeX 相同）。
- **修订说明（Sentinel SN-2 FAIL 后就地修正；已复核 PASS）：** 2026-11-16（UTC+8 / Asia/Shanghai）。主要更正：Rothe（IJCV）与 Everingham（IJCV）改用纸刊年与卷号，并删去方向反了的提示；FADING 改为 BMVC 2023 的 `@inproceedings`（官方 BibTeX 取自 https://proceedings.bmvc2023.org/595/ 的 Internet Archive 快照，因当日该站 TLS 失败），同时保留 arXiv 编号与 DataCite DOI；DiffAge3D 仍为预印本，但补上 DataCite DOI（doi.org 可跳转；Crossref 对 10.48550 返回 404 是正常的，该 DOI 在 DataCite 注册）。全部 `month=June` 一类未加花括号的月份已改为 `month={June}`。篇数统一表述为：基础 31 条（编号 1–30，第 30 条含 30a、30b），本次增补第 31–34 条，合计 **35 条记录**。补全 A/B 姓名冲突的出处与日期；§2.2 标明「贴合度需导师确认」，并增加已核实的 Web 三维可视化综述作为 B 的候选。可选增补：SIGGRAPH Asia 2025 *The Aging Multiverse*、已核实的中文综述，以及此前误标为「未核实」的 3D-STD（现已核到 ICME 2024 DOI）。 **可选 MINOR 就地修正（不必再送审，2026-11-16，UTC+8 / Asia/Shanghai）：** §2 标题改为 A 3 篇、B 4 篇；§6 来源表补上第 31/32/34 条 Crossref、arXiv 2312.16881 与 cjig.cn 出版社页；第 33 条旁增补经 cjig.cn 核实的 GB/T 7714 中文著录。 **修订说明（2026-11-21，UTC+8 / Asia/Shanghai）：** A = 宋明耀（用户本人 2026-11-21 确认）；B = 王晋涛（用户本人 2026-11-21 确认，负责系统；原话「是，B 是王晋涛，负责系统」）。其余条目未改。

---

## 0. 结论先行

1. **已核实 35 条记录**（§3 编号 1—34，其中第 30 条含 30a、30b 两篇；第 1—30 条对应初稿的 31 条记录，第 31—34 条为本次增补），覆盖规划点名的人脸检测（WIDER FACE、YOLO5Face、RetinaFace、YOLO 系列）、三维重建/3DMM（BFM 2009、3DDFA、3DDFA_V2、DECA、MICA、FLAME、Egger 2020 综述）、人脸老化（SAM、pSp/e4e、HRFAE、IPCGAN、Lifespan Age Transformation、FADING、三维老化相关工作）、年龄估计与数据集（AgeDB、FG-NET、IMDB-WIKI/DEX、AFLW 与 AFLW2000-3D）、评价（PASCAL VOC AP、ArcFace）。每篇均有 DOI 或 arXiv 链接，以及一行与本课题的相关性说明。
2. **A / B 的分工**以学校交付清单为准：A 负责检测微调、重建、年龄方向、纹理与算法实验和对应论文章节；B 负责 three.js/交互、后端与通信、系统测试、经济/社会及相关因素分析、系统论文章节和演示。共同承担文献、开题、总体设计、接口、绪论/总结和数据合规。来源：`docs/毕业设计要求与交付清单.md` 第 72 行；规划 v2 第 27 行。
3. **A = 宋明耀（用户本人 2026-11-21 确认）**，负责算法。**B = 王晋涛（用户本人 2026-11-21 确认）**，负责系统（确认渠道：Radar 对话中的问题卡「B（系统）是王晋涛吗？」；原话「是，B 是王晋涛，负责系统」），与 Atlas 的分工说明及 2026-10-17 技术框架文档一致。需要保留的文档冲突记录如下：规划 v2 第 27 行曾写「两人姓名还没有和 A/B 对应上」。`docs/AgeMorph3D_技术框架与模块行动计划.md` **编制日期为 2026-10-17**（文首第 4–5 行），写「宋明耀（A，组长，算法线）｜王晋涛（B，组员，系统线）」；两周后的 `docs/model-assets.md`、`docs/模型资产诊断与严格服务缺项记录.md`（文首日期 **2026-11-01**）写「项目所有者宋明耀（成员 B）」。同一天、同一表述还出现在 `backend/model-manifests/3ddfa-v2.research.json` 第 12 行与 `backend/model-manifests/yolov5n05-face.research.json` 第 12 行，原文均为 `"license_decided_by": "宋明耀 (member B, project owner)"`（`license_decided_at` 为 2026-11-01）。`backend/tests/test_model_assets.py` 第 168 行是 `assert "宋明耀" in manifest["license_decided_by"]`，它断言清单里出现该姓名，行文本身没有写「member B」。旧文档中「宋明耀（成员 B）」的写法与用户本人确认不符，**以用户 2026-11-21 的确认为准**。下文 A 的翻译候选对应宋明耀；B 的候选对应王晋涛（用户本人 2026-11-21 确认）。
4. **翻译必须由学生本人完成**（规划 v2 第 12 行；交付清单第 31、49 行）。机器人只提供候选与事实索引，不代写译文。
5. 外文翻译候选见 §2。规划里点名、但本次**未核实到**可作为翻译原文的条目，见 §5。

---

## 1. A / B 分工与旧文档中的翻译建议

| 角色 | 分工（已写入交付清单，作为推荐依据） | 来源 |
|---|---|---|
| A（算法与实验） | 检测微调、重建、年龄方向、纹理与算法实验，以及对应的算法论文章节 | `docs/毕业设计要求与交付清单.md` 第 72 行 |
| B（系统与集成） | three.js / 交互、后端与通信、系统测试、经济/社会及相关因素分析、系统论文章节和演示 | 同上 |
| 共同 | 文献、开题、总体设计、接口、绪论/总结、数据合规 | 同上 |

旧文档 `docs/AgeMorph3D_技术框架与模块行动计划.md` 第 303 行曾建议「A 选 3D-STD/MICA，B 选 three.js/WebGL 方向」。本次将 **MICA**（Zielonka 等，ECCV 2022）列为 A 的**备选**（已核实，见第 12 条），但篇幅约 20 页，略长。**「3D-STD」** 现已核实为 Teng 等 ICME 2024（第 34 条），列为 A 的短篇备选，不替换与代码主线更贴近的 A1。three.js 本身仍未核实到官方学术论文。B 原有的 B1–B3 偏模型/算法/检测数据集，**与交付清单第 72 行（three.js/交互、后端与通信、系统测试）的贴合度需导师确认**。本次增补第 31 条 Evans 等 2014 年 *3D graphics on the web: A survey*（DOI [10.1016/j.cag.2014.02.002](https://doi.org/10.1016/j.cag.2014.02.002)）作为已核实的 Web 三维可视化方向候选。

---

## 2. 外文翻译原文候选（A 3 篇，B 4 篇）

说明：篇幅按 Crossref 页码起止估算，不等于学校字数要求。预印本许可不等于出版社版本许可；即使用 CC 预印本，是否允许作为翻译底本，仍须按学校规定处理。下列 A 的候选对应宋明耀（用户本人 2026-11-21 确认）；B 的候选对应王晋涛（用户本人 2026-11-21 确认）。

### 2.1 推荐给 A（算法与实验）

| 优先级 | 文献 | 与 A 的哪一部分相关 | 篇幅与适合度 | 许可（已核实部分） |
|---|---|---|---|---|
| A1（首选） | Guo 等，*Towards Fast, Accurate and Stable 3D Dense Face Alignment*（3DDFA_V2），ECCV 2020。DOI [10.1007/978-3-030-58529-7_10](https://doi.org/10.1007/978-3-030-58529-7_10)；arXiv [2009.09960](https://arxiv.org/abs/2009.09960) | 代码实际使用的三维重建 / 稠密对齐主线；年龄方向建立在该路输出的 BFM 形状系数上 | LNCS 第 152—168 页（约 17 页）。内容与实现最贴近，篇幅偏长但仍属会议论文常见长度，适合作为算法章翻译首选 | 2026-11-16 打开的 arXiv 摘要页许可为 [arXiv.org nonexclusive-distrib 1.0](http://arxiv.org/licenses/nonexclusive-distrib/1.0/)，**不是 CC**。Springer 正式版版权未在本次打开许可页核对 |
| A2 | Qi 等，*YOLO5Face: Why Reinventing a Face Detector*，ECCV 2022 Workshops（Crossref 记录出版年 2023）。DOI [10.1007/978-3-031-25072-9_15](https://doi.org/10.1007/978-3-031-25072-9_15)；arXiv [2105.12931](https://arxiv.org/abs/2105.12931) | 代码实际使用的检测器（YOLO5Face / yolov5n-0.5）；A 负责检测微调与 WIDER 指标解读 | 第 228—244 页（约 17 页）。直接对应检测实验，适合作为第二条候选 | arXiv 摘要页为 [CC BY 4.0](http://creativecommons.org/licenses/by/4.0/)（须署名）。Springer 正式版是另一版本，版权未在本次打开许可页核对 |
| A3 | Alaluf、Patashnik、Cohen-Or，*Only a matter of style: age transformation using a style-based regression model*（SAM），ACM TOG 2021。DOI [10.1145/3450626.3459805](https://doi.org/10.1145/3450626.3459805)；arXiv [2102.02754](https://arxiv.org/abs/2102.02754) | 任务书与管线中的纹理 / 年龄外貌变换对照；A 负责纹理与年龄方向实验 | TOG 40(4): 1—12（12 页）。篇幅更适合本科翻译；主题对准「跨年龄」纹理一侧，而不应写成系统已改用该方法（代码主线仍是 3DDFA_V2+BFM） | arXiv 摘要页为 nonexclusive-distrib 1.0。OpenAlex 将 ACM 正式版记为 CC BY-SA，**本次未打开 ACM 许可页逐字核对**，故正式版许可仍标「未独立核实」 |

**A 的备选（不占 3 个名额，供导师替换）：** Teng 等 3D-STD（第 34 条，ICME 2024，约 6 页，短、与「形状/纹理分离的三维老化」直接相关，旧文档曾建议 A 译此文）；Zielonka 等 MICA（第 12 条，约 20 页，偏长；模型本身为非商业许可，见已通过的 RD-1，与论文版权不是一回事）；Zhu 等 3DDFA CVPR 2016（第 7 条，约 10 页，若希望先译方法前身，可与 A1 对调，但不要两人译同一篇）。

### 2.2 推荐给 B（系统与集成）

B 的分工依据交付清单第 72 行：three.js / 交互、后端与通信、系统测试、经济/社会及相关因素分析、系统论文章节和演示。下表 B1–B3 与系统资产、后端封装的方法、以及系统测试协议相关，但本身是模型 / 算法 / 数据集论文，**贴合度需导师确认**。B4 是本次按「系统、可视化或 Web3D」方向补上的已核实候选。

| 优先级 | 文献 | 与 B 的哪一部分相关 | 篇幅与适合度 | 许可（已核实部分） |
|---|---|---|---|---|
| B1 | Paysan 等，*A 3D Face Model for Pose and Illumination Invariant Face Recognition*（Basel Face Model 2009），AVSS 2009。DOI [10.1109/AVSS.2009.58](https://doi.org/10.1109/AVSS.2009.58) | 系统实际加载、展示并导出的三维模型；前端 morph / GLB 所依据的网格与形状基；亦涉及 B 在集成时必须遵守的非商业、不得再分发约束（条款本身见 RD-1，不在本篇论文里）。**贴合度需导师确认**（本文是模型论文，不是 Web 可视化论文） | 第 296—301 页（约 6 页）。短、完整、与系统资产直接相关，很适合本科翻译篇幅 | 未核实到 arXiv 预印本。IEEE 正式版版权未打开许可页，须按学校外文翻译的版权规定处理 |
| B2 | Zhu 等，*Face Alignment Across Large Poses: A 3D Solution*（3DDFA），CVPR 2016。DOI [10.1109/CVPR.2016.23](https://doi.org/10.1109/CVPR.2016.23) | 后端所封装方法的前身与输出含义（三维对齐 / 系数）；并引入 AFLW2000-3D，与系统评测集、不得误用测试包有关（见 RD-3）。**贴合度需导师确认** | 第 146—155 页（约 10 页）。篇幅适中。算法细节以 A 的 3DDFA_V2 为首选，B 宜侧重「系统调用的是什么、输出如何被可视化」，不要与 A1 选成同一篇 | 未在本次为该 DOI 核对本篇的 arXiv 摘要许可。IEEE 正式版版权须按学校规定处理 |
| B3 | Yang 等，*WIDER FACE: A Face Detection Benchmark*，CVPR 2016。DOI [10.1109/CVPR.2016.596](https://doi.org/10.1109/CVPR.2016.596)；arXiv [1511.06523](https://arxiv.org/abs/1511.06523) | B 负责系统测试：官方 val / test 划分、AP 口径与提交方式（详见已通过的 RD-6）。论文中的检测基准与评价协议，是演示与测试章节不得把验证集成绩写成「官方测试集」的依据。**贴合度需导师确认**（本文是检测基准，不是前端实现） | 第 5525—5533 页（约 9 页）。篇幅合适，且直接服务系统测试写作 | arXiv 摘要页为 [nonexclusive-distrib 1.0](http://arxiv.org/licenses/nonexclusive-distrib/1.0/)，不是 CC。IEEE 正式版版权须按学校规定处理 |
| B4（Web 三维方向） | Evans、Romeo、Bahrehmand、Agenjo、Blat，*3D graphics on the web: A survey*，*Computers & Graphics* 41: 43–61，2014。DOI [10.1016/j.cag.2014.02.002](https://doi.org/10.1016/j.cag.2014.02.002) | 直接对应 B 的 three.js / Web 三维可视化与浏览器端 3D 资产交付（WebGL、浏览器运行时），比 B1–B3 更贴近系统线。three.js 本身仍不是一篇官方论文，本综述可作为该方向的学术原文 | Crossref 第 43—61 页（约 19 页），略长于通常的本科翻译篇幅，是否采用需导师确认 | Elsevier 期刊；本次未打开出版社许可页，须按学校外文翻译的版权规定处理 |

**不推荐作为 B 的翻译原文、但列入阅读：** Egger 等 2020 综述（第 13 条）质量高，但 Crossref 页码为 1—38，对本科「一篇翻译」通常过长。three.js 官方文档不是学术论文，是否允许当作外文翻译原文，需问导师。B1–B3 若导师认为不够贴近系统线，优先考虑 B4。

---

## 3. 已核实文献（35 条记录，编号 1—34）

下列「相关性」是针对本课题管线的一句话说明，不是对该文贡献的全面评价。除特别说明外，题名、作者、DOI、页码取自 Crossref（2026-11-16，UTC+8 / Asia/Shanghai）。IJCV 两条的 `year`/`month` 已改为纸刊时间；所有条目的月份写成 `month={June}` 形式，以免 BibTeX 把 June 等当作未定义宏。FADING 以 BMVC 官方 BibTeX 为底。

### 3.1 人脸检测

#### 1. Yang 等，WIDER FACE（CVPR 2016）

- DOI：[10.1109/CVPR.2016.596](https://doi.org/10.1109/CVPR.2016.596)；arXiv：[1511.06523](https://arxiv.org/abs/1511.06523)（OpenAlex 将该预印本列为同一工作的位置；2026-11-16 打开摘要页，题名与作者与 Crossref 一致。注意：**不要**写成 1511.05911，该编号是另一篇无关论文）。
- 相关性：本课题检测微调与官方 Easy/Medium/Hard AP 的数据集和评价协议来源；系统测试须区分 val 与 test（见 RD-6）。
- 许可：arXiv 摘要页为 nonexclusive-distrib 1.0。推荐给 B 的翻译候选之一。

```bibtex
@inproceedings{Yang_2016, title={WIDER FACE: A Face Detection Benchmark}, url={http://dx.doi.org/10.1109/CVPR.2016.596}, DOI={10.1109/cvpr.2016.596}, booktitle={2016 IEEE Conference on Computer Vision and Pattern Recognition (CVPR)}, publisher={IEEE}, author={Yang, Shuo and Luo, Ping and Loy, Chen Change and Tang, Xiaoou}, year={2016}, month={June}, pages={5525–5533} }
```

#### 2. Qi 等，YOLO5Face（ECCV 2022 Workshops）

- DOI：[10.1007/978-3-031-25072-9_15](https://doi.org/10.1007/978-3-031-25072-9_15)；arXiv：[2105.12931](https://arxiv.org/abs/2105.12931)。Crossref 将出版年记为 2023（LNCS 出版年），会议为 ECCV 2022 Workshops。
- 相关性：仓库实际使用的人脸检测器及其 WIDER FACE 验证集指标（见 RD-1、RD-6）。推荐给 A 的翻译候选之一。
- 许可：arXiv 摘要页为 CC BY 4.0。

```bibtex
@inbook{Qi_2023, title={YOLO5Face: Why Reinventing a Face Detector}, ISBN={9783031250729}, ISSN={1611-3349}, url={http://dx.doi.org/10.1007/978-3-031-25072-9_15}, DOI={10.1007/978-3-031-25072-9_15}, booktitle={Computer Vision – ECCV 2022 Workshops}, publisher={Springer Nature Switzerland}, author={Qi, Delong and Tan, Weijun and Yao, Qi and Liu, Jingfeng}, year={2023}, pages={228–244} }
```

#### 3. Deng 等，RetinaFace（CVPR 2020）

- DOI：[10.1109/cvpr42600.2020.00525](https://doi.org/10.1109/cvpr42600.2020.00525)
- 相关性：常用的单阶段人脸检测与五点定位对照方法；讨论检测选型时与 YOLO5Face 并列引用。

```bibtex
@inproceedings{Deng_2020, title={RetinaFace: Single-Shot Multi-Level Face Localisation in the Wild}, url={http://dx.doi.org/10.1109/cvpr42600.2020.00525}, DOI={10.1109/cvpr42600.2020.00525}, booktitle={2020 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)}, publisher={IEEE}, author={Deng, Jiankang and Guo, Jia and Ververas, Evangelos and Kotsia, Irene and Zafeiriou, Stefanos}, year={2020}, month={June}, pages={5202–5211} }
```

#### 4. Redmon 等，YOLO（CVPR 2016）

- DOI：[10.1109/CVPR.2016.91](https://doi.org/10.1109/CVPR.2016.91)
- 相关性：YOLO 系列的代表性会议论文，用于交代检测框架的来源。本次**未核实到**名为 “YOLOv5” 的对等正式会议/期刊论文；Ultralytics YOLOv5 是代码库，不宜冒充已发表论文。YOLO5Face 已作为第 2 条单独列出。

```bibtex
@inproceedings{Redmon_2016, title={You Only Look Once: Unified, Real-Time Object Detection}, url={http://dx.doi.org/10.1109/CVPR.2016.91}, DOI={10.1109/cvpr.2016.91}, booktitle={2016 IEEE Conference on Computer Vision and Pattern Recognition (CVPR)}, publisher={IEEE}, author={Redmon, Joseph and Divvala, Santosh and Girshick, Ross and Farhadi, Ali}, year={2016}, month={June}, pages={779–788} }
```

### 3.2 三维人脸重建与 3DMM

#### 5. Blanz 与 Vetter，三维可变形模型（SIGGRAPH 1999）

- DOI：[10.1145/311535.311556](https://doi.org/10.1145/311535.311556)
- 相关性：3DMM 的经典来源，后续 BFM、3DDFA 均建立在这一表示之上。Crossref 另有 2023 年 *Seminal Graphics Papers* 转载，引用请用 1999 年原文这条 DOI，不要用转载记录代替首次发表。

```bibtex
@inproceedings{Blanz_1999, series={SIGGRAPH ’99}, title={A morphable model for the synthesis of 3D faces}, url={http://dx.doi.org/10.1145/311535.311556}, DOI={10.1145/311535.311556}, booktitle={Proceedings of the 26th annual conference on Computer graphics and interactive techniques  - SIGGRAPH ’99}, publisher={ACM Press}, author={Blanz, Volker and Vetter, Thomas}, year={1999}, pages={187–194}, collection={SIGGRAPH ’99} }
```

#### 6. Paysan 等，Basel Face Model（AVSS 2009）

- DOI：[10.1109/AVSS.2009.58](https://doi.org/10.1109/AVSS.2009.58)
- 相关性：本课题代码使用的三维人脸统计模型（BFM）原文。推荐给 B 的翻译首选。许可与再分发约束见 RD-1，不要从本条推断「可以随仓库分发模型」。

```bibtex
@inproceedings{Paysan_2009, title={A 3D Face Model for Pose and Illumination Invariant Face Recognition}, url={http://dx.doi.org/10.1109/AVSS.2009.58}, DOI={10.1109/avss.2009.58}, booktitle={2009 Sixth IEEE International Conference on Advanced Video and Signal Based Surveillance}, publisher={IEEE}, author={Paysan, Pascal and Knothe, Reinhard and Amberg, Brian and Romdhani, Sami and Vetter, Thomas}, year={2009}, month={Sept}, pages={296–301} }
```

#### 7. Zhu 等，3DDFA（CVPR 2016）

- DOI：[10.1109/CVPR.2016.23](https://doi.org/10.1109/CVPR.2016.23)
- 相关性：三维稠密对齐方法的会议版，并发布 AFLW2000-3D（在 AFLW 前 2000 个样本上拟合的三维人脸）。推荐给 B 的翻译候选之一。获取与许可见 RD-3。

```bibtex
@inproceedings{Zhu_2016, title={Face Alignment Across Large Poses: A 3D Solution}, url={http://dx.doi.org/10.1109/CVPR.2016.23}, DOI={10.1109/cvpr.2016.23}, booktitle={2016 IEEE Conference on Computer Vision and Pattern Recognition (CVPR)}, publisher={IEEE}, author={Zhu, Xiangyu and Lei, Zhen and Liu, Xiaoming and Shi, Hailin and Li, Stan Z.}, year={2016}, month={June}, pages={146–155} }
```

#### 8. Zhu 等，3DDFA 期刊扩展（TPAMI 2019）

- DOI：[10.1109/TPAMI.2017.2778152](https://doi.org/10.1109/TPAMI.2017.2778152)。Crossref 记录的期刊年是 2019，卷 41 期 1，页 78—92。
- 相关性：第 7 条的期刊完整版（*Face Alignment in Full Pose Range: A 3D Total Solution*）。开题与相关工作可同时列出会议版与期刊版，但翻译不宜两人都选这一组。

```bibtex
@article{Zhu_2019, title={Face Alignment in Full Pose Range: A 3D Total Solution}, volume={41}, ISSN={1939-3539}, url={http://dx.doi.org/10.1109/TPAMI.2017.2778152}, DOI={10.1109/tpami.2017.2778152}, number={1}, journal={IEEE Transactions on Pattern Analysis and Machine Intelligence}, publisher={Institute of Electrical and Electronics Engineers (IEEE)}, author={Zhu, Xiangyu and Liu, Xiaoming and Lei, Zhen and Li, Stan Z.}, year={2019}, month={Jan}, pages={78–92} }
```

#### 9. Guo 等，3DDFA_V2（ECCV 2020）

- DOI：[10.1007/978-3-030-58529-7_10](https://doi.org/10.1007/978-3-030-58529-7_10)；arXiv：[2009.09960](https://arxiv.org/abs/2009.09960)
- 相关性：仓库实际使用的重建实现所依据的方法。推荐给 A 的翻译首选。

```bibtex
@inbook{Guo_2020, title={Towards Fast, Accurate and Stable 3D Dense Face Alignment}, ISBN={9783030585297}, ISSN={1611-3349}, url={http://dx.doi.org/10.1007/978-3-030-58529-7_10}, DOI={10.1007/978-3-030-58529-7_10}, booktitle={Computer Vision – ECCV 2020}, publisher={Springer International Publishing}, author={Guo, Jianzhu and Zhu, Xiangyu and Yang, Yang and Yang, Fan and Lei, Zhen and Li, Stan Z.}, year={2020}, pages={152–168} }
```

#### 10. Feng 等，DECA（ACM TOG 2021）

- DOI：[10.1145/3450626.3459936](https://doi.org/10.1145/3450626.3459936)
- 相关性：从野生图像学习可动画、带细节的三维人脸模型，常作为与 3DDFA_V2 / BFM 路线对照的方法。

```bibtex
@article{Feng_2021, title={Learning an animatable detailed 3D face model from in-the-wild images}, volume={40}, ISSN={1557-7368}, url={http://dx.doi.org/10.1145/3450626.3459936}, DOI={10.1145/3450626.3459936}, number={4}, journal={ACM Transactions on Graphics}, publisher={Association for Computing Machinery (ACM)}, author={Feng, Yao and Feng, Haiwen and Black, Michael J. and Bolkart, Timo}, year={2021}, month={July}, pages={1–13} }
```

#### 11. Li 等，FLAME（ACM TOG 2017）

- DOI：[10.1145/3130800.3130813](https://doi.org/10.1145/3130800.3130813)
- 相关性：任务书曾出现的替代拓扑；本仓库代码主线是 BFM 而非 FLAME。许可与获取见 RD-1，引用时不要写成「本系统已改用 FLAME」。

```bibtex
@article{Li_2017, title={Learning a model of facial shape and expression from 4D scans}, volume={36}, ISSN={1557-7368}, url={http://dx.doi.org/10.1145/3130800.3130813}, DOI={10.1145/3130800.3130813}, number={6}, journal={ACM Transactions on Graphics}, publisher={Association for Computing Machinery (ACM)}, author={Li, Tianye and Bolkart, Timo and Black, Michael J. and Li, Hao and Romero, Javier}, year={2017}, month={Nov}, pages={1–17} }
```

#### 12. Zielonka 等，MICA（ECCV 2022）

- DOI：[10.1007/978-3-031-19778-9_15](https://doi.org/10.1007/978-3-031-19778-9_15)。Crossref 题名为 *Towards Metrical Reconstruction of Human Faces*。
- 相关性：任务书与旧规划中出现的重建对照；代码主线未采用。模型许可为非商业，见 RD-1。可作为 A 的偏长备选翻译，不宜与「系统已使用 MICA」混写。

```bibtex
@inbook{Zielonka_2022, title={Towards Metrical Reconstruction of Human Faces}, ISBN={9783031197789}, ISSN={1611-3349}, url={http://dx.doi.org/10.1007/978-3-031-19778-9_15}, DOI={10.1007/978-3-031-19778-9_15}, booktitle={Computer Vision – ECCV 2022}, publisher={Springer Nature Switzerland}, author={Zielonka, Wojciech and Bolkart, Timo and Thies, Justus}, year={2022}, pages={250–269} }
```

#### 13. Egger 等，3DMM 综述（ACM TOG 2020）

- DOI：[10.1145/3395208](https://doi.org/10.1145/3395208)；arXiv：[1909.01815](https://arxiv.org/abs/1909.01815)
- 相关性：3DMM 历史与现状的权威综述，适合开题「相关工作」阅读。Crossref 页码 1—38，一般不适合作为本科单篇翻译原文。arXiv 摘要页许可为 nonexclusive-distrib 1.0；OpenAlex 将 ACM 正式版记为 CC BY，未独立打开 ACM 许可页核对。

```bibtex
@article{Egger_2020, title={3D Morphable Face Models—Past, Present, and Future}, volume={39}, ISSN={1557-7368}, url={http://dx.doi.org/10.1145/3395208}, DOI={10.1145/3395208}, number={5}, journal={ACM Transactions on Graphics}, publisher={Association for Computing Machinery (ACM)}, author={Egger, Bernhard and Smith, William A. P. and Tewari, Ayush and Wuhrer, Stefanie and Zollhoefer, Michael and Beeler, Thabo and Bernard, Florian and Bolkart, Timo and Kortylewski, Adam and Romdhani, Sami and Theobalt, Christian and Blanz, Volker and Vetter, Thomas}, year={2020}, month={June}, pages={1–38} }
```

### 3.3 人脸老化

#### 14. Alaluf 等，SAM（ACM TOG 2021）

- DOI：[10.1145/3450626.3459805](https://doi.org/10.1145/3450626.3459805)；arXiv：[2102.02754](https://arxiv.org/abs/2102.02754)。Crossref 题名为 *Only a matter of style: age transformation using a style-based regression model*。
- 相关性：本课题对照的风格/年龄外貌变换方法（纹理一侧）。推荐给 A 的翻译候选之一。

```bibtex
@article{Alaluf_2021, title={Only a matter of style: age transformation using a style-based regression model}, volume={40}, ISSN={1557-7368}, url={http://dx.doi.org/10.1145/3450626.3459805}, DOI={10.1145/3450626.3459805}, number={4}, journal={ACM Transactions on Graphics}, publisher={Association for Computing Machinery (ACM)}, author={Alaluf, Yuval and Patashnik, Or and Cohen-Or, Daniel}, year={2021}, month={July}, pages={1–12} }
```

#### 15. Richardson 等，pSp（CVPR 2021）

- DOI：[10.1109/cvpr46437.2021.00232](https://doi.org/10.1109/cvpr46437.2021.00232)
- 相关性：StyleGAN 编码器，是 SAM / e4e 一类年龄编辑管线的常用前级。

```bibtex
@inproceedings{Richardson_2021, title={Encoding in Style: a StyleGAN Encoder for Image-to-Image Translation}, url={http://dx.doi.org/10.1109/cvpr46437.2021.00232}, DOI={10.1109/cvpr46437.2021.00232}, booktitle={2021 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)}, publisher={IEEE}, author={Richardson, Elad and Alaluf, Yuval and Patashnik, Or and Nitzan, Yotam and Azar, Yaniv and Shapiro, Stav and Cohen-Or, Daniel}, year={2021}, month={June}, pages={2287–2296} }
```

#### 16. Tov 等，e4e（ACM TOG 2021）

- DOI：[10.1145/3450626.3459838](https://doi.org/10.1145/3450626.3459838)
- 相关性：面向编辑的 StyleGAN 编码器，常与 pSp、SAM 一并讨论。

```bibtex
@article{Tov_2021, title={Designing an encoder for StyleGAN image manipulation}, volume={40}, ISSN={1557-7368}, url={http://dx.doi.org/10.1145/3450626.3459838}, DOI={10.1145/3450626.3459838}, number={4}, journal={ACM Transactions on Graphics}, publisher={Association for Computing Machinery (ACM)}, author={Tov, Omer and Alaluf, Yuval and Nitzan, Yotam and Patashnik, Or and Cohen-Or, Daniel}, year={2021}, month={July}, pages={1–14} }
```

#### 17. Yao 等，HRFAE（ICPR 2020，Crossref 出版记录为 2021 年 1 月）

- DOI：[10.1109/icpr48806.2021.9412383](https://doi.org/10.1109/icpr48806.2021.9412383)。会议名称在 Crossref 中为 *2020 25th International Conference on Pattern Recognition (ICPR)*，出版记录为 year={2021}、month={Jan}，页 8624—8631。
- 相关性：高分辨率人脸年龄编辑，作为二维年龄编辑对照。

```bibtex
@inproceedings{Yao_2021, title={High Resolution Face Age Editing}, url={http://dx.doi.org/10.1109/icpr48806.2021.9412383}, DOI={10.1109/icpr48806.2021.9412383}, booktitle={2020 25th International Conference on Pattern Recognition (ICPR)}, publisher={IEEE}, author={Yao, Xu and Puy, Gilles and Newson, Alasdair and Gousseau, Yann and Hellier, Pierre}, year={2021}, month={Jan}, pages={8624–8631} }
```

#### 18. Tang 等，IPCGAN（CVPR 2018）

- DOI：[10.1109/CVPR.2018.00828](https://doi.org/10.1109/CVPR.2018.00828)
- 相关性：带身份保持的条件 GAN 人脸老化，常作为经典对照。Crossref 与 OpenAlex 的作者顺序均为 Xu Tang, Zongwei Wang, Weixin Luo, Shenghua Gao；本文采用这一官方元数据顺序。

```bibtex
@inproceedings{Tang_2018, title={Face Aging with Identity-Preserved Conditional Generative Adversarial Networks}, url={http://dx.doi.org/10.1109/CVPR.2018.00828}, DOI={10.1109/cvpr.2018.00828}, booktitle={2018 IEEE/CVF Conference on Computer Vision and Pattern Recognition}, publisher={IEEE}, author={Tang, Xu and Wang, Zongwei and Luo, Weixin and Gao, Shenghua}, year={2018}, month={June}, pages={7939–7947} }
```

#### 19. Or-El 等，Lifespan Age Transformation Synthesis（ECCV 2020）

- DOI：[10.1007/978-3-030-58539-6_44](https://doi.org/10.1007/978-3-030-58539-6_44)
- 相关性：覆盖人生跨度的年龄变换合成，常与 SAM 并列作为二维老化对照。

```bibtex
@inbook{Or_El_2020, title={Lifespan Age Transformation Synthesis}, ISBN={9783030585396}, ISSN={1611-3349}, url={http://dx.doi.org/10.1007/978-3-030-58539-6_44}, DOI={10.1007/978-3-030-58539-6_44}, booktitle={Computer Vision – ECCV 2020}, publisher={Springer International Publishing}, author={Or-El, Roy and Sengupta, Soumyadip and Fried, Ohad and Shechtman, Eli and Kemelmacher-Shlizerman, Ira}, year={2020}, pages={739–755} }
```

#### 20. Chen 与 Lathuilière，FADING（BMVC 2023；arXiv:2309.11321）

- 正式发表：第 34 届 British Machine Vision Conference（BMVC 2023，Aberdeen，2023-11-20 至 24）。arXiv 摘要页 Comments 写着 “accepted at BMVC 2023”。官方页面 https://proceedings.bmvc2023.org/595/ 在 2026-11-16 从本环境访问时 TLS/HTTP 失败；官方 BibTeX 取自 Internet Archive 快照 `https://web.archive.org/web/20260519031506/https://proceedings.bmvc2023.org/595/`（捕获时间 2026-05-19 03:15:06 UTC = 2026-05-19 11:15:06 UTC+8 / Asia/Shanghai）。快照中的 Citation 块题名、作者与会议信息与摘要页一致，方法名 **FADING**（Face Aging via DIffusion-based editiNG）在官方页摘要中写明。
- DataCite / arXiv DOI：[10.48550/arXiv.2309.11321](https://doi.org/10.48550/arXiv.2309.11321)。2026-11-16 用 doi.org 做 HEAD：302 到 `https://arxiv.org/abs/2309.11321`；DataCite API 返回同一题名与作者，`publicationYear=2023`，类型为 Preprint。Crossref 对该 DOI 返回 404 是正常的（此 DOI 在 DataCite 注册，不在 Crossref）。**不要再写成「没有 DOI」。** 本次未在 Crossref 检索到另外的会议/期刊 DOI。
- arXiv：[2309.11321](https://arxiv.org/abs/2309.11321)（摘要页许可为 CC BY 4.0）。
- 相关性：规划点名的扩散人脸老化方法，作为较新的二维老化对照。
- BibTeX：以下以官方 `@inproceedings{Chen_2023_BMVC, ...}` 为底，补上 `eprint` / `archivePrefix` 与 DataCite DOI。官方 `url` 指向 `https://papers.bmvc2023.org/0595.pdf`，本文**未下载**该 PDF。

```bibtex
@inproceedings{Chen_2023_BMVC,
author    = {Xiangyi Chen and Stéphane Lathuilière},
title     = {Face Aging via Diffusion-based Editing},
booktitle = {34th British Machine Vision Conference 2023, {BMVC} 2023, Aberdeen, UK, November 20-24, 2023},
publisher = {BMVA},
year      = {2023},
url       = {https://papers.bmvc2023.org/0595.pdf},
eprint    = {2309.11321},
archivePrefix = {arXiv},
doi       = {10.48550/arXiv.2309.11321}
}
```
#### 21. Wahid 等，DiffAge3D（arXiv:2408.15922，2024 预印本）

- arXiv：[2408.15922](https://arxiv.org/abs/2408.15922)。摘要页题名为 *DiffAge3D: Diffusion-based 3D-aware Face Aging*，作者 Junaid Wahid, Fangneng Zhan, Pramod Rao, Christian Theobalt。本次在 Crossref 中**未检索到会议/期刊正式出版记录**，故仍按预印本著录。
- DataCite / arXiv DOI：[10.48550/arXiv.2408.15922](https://doi.org/10.48550/arXiv.2408.15922)。2026-11-16 用 doi.org 做 HEAD：302 到该摘要页；DataCite API 返回同一题名与作者，`publicationYear=2024`，类型为 Preprint。Crossref 对该 DOI 返回 404 是正常的。**不要写成「没有 DOI」。**
- 相关性：明确的三维感知人脸老化工作，可与本课题「在三维形状空间做年龄方向」的路线对照；摘要称现有方法多限于二维设定。不表示本仓库实现了该方法。
- 许可：arXiv 摘要页为 CC BY 4.0。
- BibTeX 来源：根据摘要页元数据整理，并补上 DataCite DOI。

```bibtex
@misc{Wahid_2024_DiffAge3D,
  title = {DiffAge3D: Diffusion-based 3D-aware Face Aging},
  author = {Wahid, Junaid and Zhan, Fangneng and Rao, Pramod and Theobalt, Christian},
  year = {2024},
  eprint = {2408.15922},
  archivePrefix = {arXiv},
  doi = {10.48550/arXiv.2408.15922},
  url = {https://arxiv.org/abs/2408.15922},
  note = {Preprint only as of 2026-11-16 (UTC+8). DataCite/arXiv DOI resolves at doi.org; no Crossref conference/journal record was found.}
}
```
#### 22. Suo 等，组合与动态人脸老化模型（TPAMI 2010）

- DOI：[10.1109/tpami.2009.39](https://doi.org/10.1109/tpami.2009.39)
- 相关性：较早的人脸老化生成模型（组合 / 动态模型），作为「三维或结构化老化」相关工作的历史引用。Crossref 将作者字段写作 `Jinli Suo and Song-Chun Zhu and Shiguang Shan and Xilin Chen`，此处保持原样。

```bibtex
@article{Jinli_Suo_2010, title={A Compositional and Dynamic Model for Face Aging}, volume={32}, ISSN={0162-8828}, url={http://dx.doi.org/10.1109/tpami.2009.39}, DOI={10.1109/tpami.2009.39}, number={3}, journal={IEEE Transactions on Pattern Analysis and Machine Intelligence}, publisher={Institute of Electrical and Electronics Engineers (IEEE)}, author={Jinli Suo and Song-Chun Zhu and Shiguang Shan and Xilin Chen}, year={2010}, month={Mar}, pages={385–401} }
```

#### 23. Fu、Guo 与 Huang，年龄合成与估计综述（TPAMI 2010）

- DOI：[10.1109/tpami.2010.36](https://doi.org/10.1109/tpami.2010.36)
- 相关性：年龄合成与估计的经典综述，适合开题相关工作。Crossref 作者字段为 `Yun Fu and Guodong Guo and Huang, T S`，保持原样。

```bibtex
@article{Yun_Fu_2010, title={Age Synthesis and Estimation via Faces: A Survey}, volume={32}, ISSN={0162-8828}, url={http://dx.doi.org/10.1109/tpami.2010.36}, DOI={10.1109/tpami.2010.36}, number={11}, journal={IEEE Transactions on Pattern Analysis and Machine Intelligence}, publisher={Institute of Electrical and Electronics Engineers (IEEE)}, author={Yun Fu and Guodong Guo and Huang, T S}, year={2010}, month={Nov}, pages={1955–1976} }
```

### 3.4 年龄估计、数据集

#### 24. Kostinger 等，AFLW（ICCV Workshops 2011）

- DOI：[10.1109/iccvw.2011.6130513](https://doi.org/10.1109/iccvw.2011.6130513)
- 相关性：AFLW 原始数据集论文；AFLW2000-3D 使用了其前 2000 个样本（见 RD-3）。Crossref 将第一作者拼为 Kostinger（无变音符号）；TU Graz 页面常用 Köstinger，引用时可以保留 Crossref 写法并在正文中注明。

```bibtex
@inproceedings{Kostinger_2011, title={Annotated Facial Landmarks in the Wild: A large-scale, real-world database for facial landmark localization}, url={http://dx.doi.org/10.1109/iccvw.2011.6130513}, DOI={10.1109/iccvw.2011.6130513}, booktitle={2011 IEEE International Conference on Computer Vision Workshops (ICCV Workshops)}, publisher={IEEE}, author={Kostinger, Martin and Wohlhart, Paul and Roth, Peter M. and Bischof, Horst}, year={2011}, month={Nov}, pages={2144–2151} }
```

#### 25. Moschoglou 等，AgeDB（CVPR Workshops 2017）

- DOI：[10.1109/CVPRW.2017.250](https://doi.org/10.1109/CVPRW.2017.250)
- 相关性：本课题年龄方向学习计划采用的、带身份编号的年龄数据集。获取须走官方申请，见已通过的数据集方案 v3，不要使用非官方转存。

```bibtex
@inproceedings{Moschoglou_2017, title={AgeDB: The First Manually Collected, In-the-Wild Age Database}, url={http://dx.doi.org/10.1109/CVPRW.2017.250}, DOI={10.1109/cvprw.2017.250}, booktitle={2017 IEEE Conference on Computer Vision and Pattern Recognition Workshops (CVPRW)}, publisher={IEEE}, author={Moschoglou, Stylianos and Papaioannou, Athanasios and Sagonas, Christos and Deng, Jiankang and Kotsia, Irene and Zafeiriou, Stefanos}, year={2017}, month={July}, pages={1997–2005} }
```

#### 26. Panis 等，FG-NET 研究综述（IET Biometrics 2016）

- DOI：[10.1049/iet-bmt.2014.0053](https://doi.org/10.1049/iet-bmt.2014.0053)
- 相关性：可核验的、专门讨论 FG-NET 老化数据库的正式论文。须写明：这是对该数据库研究的概述，**不是**数据库首次发布时的原始技术报告；本次未核实到带 DOI 的「FG-NET 原始发布论文」。引用数据库本身时，应同时说明官方获取途径，而不是把本条当成发布公告。

```bibtex
@article{Panis_2016, title={Overview of research on facial ageing using the FG-NET ageing database}, volume={5}, ISSN={2047-4946}, url={http://dx.doi.org/10.1049/iet-bmt.2014.0053}, DOI={10.1049/iet-bmt.2014.0053}, number={2}, journal={IET Biometrics}, publisher={Institution of Engineering and Technology (IET)}, author={Panis, Gabriel and Lanitis, Andreas and Tsapatsoulis, Nicholas and Cootes, Timothy F.}, year={2016}, month={June}, pages={37–46} }
```

#### 27. Rothe 等，DEX / IMDB-WIKI，ICCV Workshops 2015

- DOI：[10.1109/iccvw.2015.41](https://doi.org/10.1109/iccvw.2015.41)
- 相关性：DEX 与 IMDB-WIKI 数据集的研讨会首次发表。Crossref 第三作者写作 `Gool, Luc Van`。更完整的期刊扩展见下一条。

```bibtex
@inproceedings{Rothe_2015, title={DEX: Deep EXpectation of Apparent Age from a Single Image}, url={http://dx.doi.org/10.1109/iccvw.2015.41}, DOI={10.1109/iccvw.2015.41}, booktitle={2015 IEEE International Conference on Computer Vision Workshop (ICCVW)}, publisher={IEEE}, author={Rothe, Rasmus and Timofte, Radu and Gool, Luc Van}, year={2015}, month={Dec}, pages={252–257} }
```

#### 28. Rothe 等，DEX 期刊扩展（IJCV 纸刊 2018，卷 126）

- DOI：[10.1007/s11263-016-0940-3](https://doi.org/10.1007/s11263-016-0940-3)。Crossref 记录：`published-online` / `issued` = **2016-08-10**，`published-print` = **2018-04**，`volume=126`，`issue=2-4`，页 144–157。Crossref 默认 BibTeX 的 `year={2016}` 取的是在线首发年。本文改用**纸刊年 2018、卷 126、第 2–4 期**；可在正文同时注明在线首发于 2016-08。
- 相关性：IMDB-WIKI 与无关键点年龄估计的期刊完整版。数据集方案 v3 已说明 IMDB-Clean / 原图体积问题，引用时不要把「提及 IMDB-WIKI」写成「本期已采用该数据集」。

```bibtex
@article{Rothe_2018,
  title = {Deep Expectation of Real and Apparent Age from a Single Image Without Facial Landmarks},
  volume = {126},
  ISSN = {1573-1405},
  url = {http://dx.doi.org/10.1007/s11263-016-0940-3},
  DOI = {10.1007/s11263-016-0940-3},
  number = {2-4},
  journal = {International Journal of Computer Vision},
  publisher = {Springer Science and Business Media LLC},
  author = {Rothe, Rasmus and Timofte, Radu and Van Gool, Luc},
  year = {2018},
  month = {April},
  pages = {144--157},
  note = {Print issue April 2018, volume 126, issues 2--4. Crossref published-online/issued: 2016-08-10; published-print: 2018-04. The citation year follows the print issue.}
}
```
#### 29. Kuprashevich 与 Tolstykh，MiVOLO（LNCS 2024）

- DOI：[10.1007/978-3-031-54534-4_15](https://doi.org/10.1007/978-3-031-54534-4_15)。Crossref 的 booktitle 为 *Analysis of Images, Social Networks and Texts*。
- 相关性：规划点名的年龄 / 性别估计方法，可用于评价或对照年龄标签质量，不是本仓库的重建主线。

```bibtex
@inbook{Kuprashevich_2024, title={MiVOLO: Multi-input Transformer for Age and Gender Estimation}, ISBN={9783031545344}, ISSN={1611-3349}, url={http://dx.doi.org/10.1007/978-3-031-54534-4_15}, DOI={10.1007/978-3-031-54534-4_15}, booktitle={Analysis of Images, Social Networks and Texts}, publisher={Springer Nature Switzerland}, author={Kuprashevich, Maksim and Tolstykh, Irina}, year={2024}, pages={212–226} }
```

### 3.5 评价

#### 30. Everingham 等，PASCAL VOC（IJCV 纸刊 2010，卷 88） 与 Deng 等，ArcFace（CVPR 2019）

评价协议与身份保持评价是两类指标，本条用两个已核实条目覆盖规划中的「评价」，在 `.bib` 中分作两条。

**30a. PASCAL VOC 挑战（WIDER FACE 官方 AP 所沿用的口径来源之一，见 RD-6）。** DOI：[10.1007/s11263-009-0275-4](https://doi.org/10.1007/s11263-009-0275-4)。Crossref 记录：`published-online` / `issued` = **2009-09-09**，`published-print` = **2010-06**，`volume=88`，`issue=2`，页 303–338。Crossref 默认 BibTeX 的 `year={2009}` 取的是在线首发年。本文改用**纸刊年 2010、卷 88、第 2 期**；可同时注明在线首发于 2009-09。篇幅 303—338，不推荐作本科单篇翻译。

```bibtex
@article{Everingham_2010,
  title = {The Pascal Visual Object Classes (VOC) Challenge},
  volume = {88},
  ISSN = {1573-1405},
  url = {http://dx.doi.org/10.1007/s11263-009-0275-4},
  DOI = {10.1007/s11263-009-0275-4},
  number = {2},
  journal = {International Journal of Computer Vision},
  publisher = {Springer Science and Business Media LLC},
  author = {Everingham, Mark and Van Gool, Luc and Williams, Christopher K. I. and Winn, John and Zisserman, Andrew},
  year = {2010},
  month = {June},
  pages = {303--338},
  note = {Print issue June 2010, volume 88, issue 2. Crossref published-online/issued: 2009-09-09; published-print: 2010-06. The citation year follows the print issue.}
}
```
**30b. ArcFace（身份保持评价常用损失与模型）。** DOI：[10.1109/CVPR.2019.00482](https://doi.org/10.1109/CVPR.2019.00482)。规划 RD-2 点名；用于跨年龄后的身份一致性，而不是检测 AP。

```bibtex
@inproceedings{Deng_2019, title={ArcFace: Additive Angular Margin Loss for Deep Face Recognition}, url={http://dx.doi.org/10.1109/CVPR.2019.00482}, DOI={10.1109/cvpr.2019.00482}, booktitle={2019 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)}, publisher={IEEE}, author={Deng, Jiankang and Guo, Jia and Xue, Niannan and Zafeiriou, Stefanos}, year={2019}, month={June}, pages={4685–4694} }
```

计数口径统一为：**35 条独立记录**（编号 1—34，其中第 30 条含 30a、30b 两篇）。第 1—30 条即初稿的 31 条；第 31—34 条为本次增补。不少于 20 篇的要求已满足。


### 3.6 系统与 Web 三维可视化（本次增补，供 B 翻译）

#### 31. Evans 等，*3D graphics on the web: A survey*（Computers & Graphics，2014）

- DOI：[10.1016/j.cag.2014.02.002](https://doi.org/10.1016/j.cag.2014.02.002)。Crossref：作者 Alun Evans, Marco Romeo, Arash Bahrehmand, Javi Agenjo, Josep Blat；`volume=41`，页 43–61；`year=2014`，`published-print` 为 2014-06。
- 相关性：WebGL 与浏览器端三维图形的综述，对应 B 的 three.js / 前端可视化与 GLB 交付，而不依赖 three.js 官方论文（本次仍未核到）。推荐为 B4，篇幅略长，是否用作翻译原文需导师确认。
- 许可：Elsevier 期刊，本次未打开出版社许可页。

```bibtex
@article{Evans_2014,
  title = {3D graphics on the web: A survey},
  volume = {41},
  ISSN = {0097-8493},
  url = {http://dx.doi.org/10.1016/j.cag.2014.02.002},
  DOI = {10.1016/j.cag.2014.02.002},
  journal = {Computers \& Graphics},
  publisher = {Elsevier BV},
  author = {Evans, Alun and Romeo, Marco and Bahrehmand, Arash and Agenjo, Javi and Blat, Josep},
  year = {2014},
  month = {June},
  pages = {43--61}
}
```

### 3.7 近年工作、中文文献与 3D-STD 补核（本次增补）

初稿没有 2025–2026 年的文献，也没有中文文献。学校模板若对中外文比例或近年文献有要求，请按模板自行核对，下列只提供已核实的条目，不代替学校格式审查。

#### 32. Gong 等，*The Aging Multiverse*（SIGGRAPH Asia 2025）

- DOI：[10.1145/3757377.3763988](https://doi.org/10.1145/3757377.3763988)。Crossref 题名为 *The Aging Multiverse: Generating Condition-Aware Facial Aging Tree via Training-Free Diffusion*；作者 Bang Gong, Luchao Qi, Jiaye Wu, Zhicheng Fu, Chunbo Song, John Nicholson, Roni Sengupta；会议论文集 *Proceedings of the SIGGRAPH Asia 2025 Conference Papers*；`published-online` = 2025-12-14，`published-print` = 2025-12-15；页 1–12。纸刊年与在线年同为 2025。
- 相关性：较新的、无需额外训练的扩散人脸老化工作，可补开题「近年进展」一节。不是本仓库实现。
- 许可：本次未打开 ACM 许可页。

```bibtex
@inproceedings{Gong_2025,
  series = {SA Conference Papers ’25},
  title = {The Aging Multiverse: Generating Condition-Aware Facial Aging Tree via Training-Free Diffusion},
  url = {http://dx.doi.org/10.1145/3757377.3763988},
  DOI = {10.1145/3757377.3763988},
  booktitle = {Proceedings of the SIGGRAPH Asia 2025 Conference Papers},
  publisher = {ACM},
  author = {Gong, Bang and Qi, Luchao and Wu, Jiaye and Fu, Zhicheng and Song, Chunbo and Nicholson, John and Sengupta, Roni},
  year = {2025},
  month = {December},
  pages = {1--12},
  collection = {SA Conference Papers ’25}
}
```

#### 33. 刘菲 等，三维人脸成像及重建技术综述（中国图象图形学报，2024）

- DOI：[10.11834/jig.230697](https://doi.org/10.11834/jig.230697)。Crossref / OpenAlex：英文题名 *3D face imaging and reconstruction technology： a review*（Crossref 原文在冒号处使用全角冒号）；期刊 *Journal of Image and Graphics*（中国图象图形学报）；卷 29、期 9、页 2441–2470、年 2024。OpenAlex 的出版商 OA 文件名含「三维人脸成像及重建技术综述.pdf」，据此核实中文题名；**未下载该 PDF**。`docs/AgeMorph3D_毕设可行性分析.md` 第 219–220 行的著录与上述卷期页、DOI 一致。
- 作者：不照抄 Crossref 的 `author` 字段——该字段把单位名称也写成了作者，且 given/family 疑似颠倒。此处作者顺序取 OpenAlex 的 `raw_author_name`（2026-11-16 访问）：Liu Fei, Zhang Kunbo, Yang Qing, Zhou Shubo, Wang Yunlong, Sun Zhenan，对应中文「刘菲、张堃博、杨青、周树波、王云龙、孙哲南」（可行性分析第 219 行的中文姓名与此一致）。
- 相关性：中文入门综述，覆盖近年深度学习三维人脸重建。初稿没有中文文献；是否需要、以及中外文比例，请按学校开题/论文模板自行核对。知网全文本次未打开（学校图书馆入口）。
- 许可：OpenAlex 记为 bronze OA，未给出 CC 许可字段；未打开期刊许可页。

```bibtex
@article{Liu_2024_JIG,
  title = {3D face imaging and reconstruction technology: a review},
  author = {Liu, Fei and Zhang, Kunbo and Yang, Qing and Zhou, Shubo and Wang, Yunlong and Sun, Zhenan},
  journal = {Journal of Image and Graphics},
  volume = {29},
  number = {9},
  pages = {2441--2470},
  year = {2024},
  doi = {10.11834/jig.230697},
  url = {https://doi.org/10.11834/jig.230697},
  ISSN = {1006-8961},
  note = {Chinese title 三维人脸成像及重建技术综述 (verified from the publisher OA filename in OpenAlex, PDF not downloaded). Journal: 中国图象图形学报. Volume, issue, pages and English title from Crossref. Author order from OpenAlex raw_author_name on 2026-11-16 (UTC+8); the Crossref author field incorrectly lists affiliations as authors and appears to invert given/family names, so it was not copied verbatim.}
}
```

GB/T 7714 中文著录（中文题名、刊名与作者已用 2026-11-16 打开的出版社文章页 https://www.cjig.cn/zh/article/doi/10.11834/jig.230697/ 的 `citation_title`、`citation_journal_title`、`citation_author` 核实；未下载 PDF）：

> 刘菲, 张堃博, 杨青, 周树波, 王云龙, 孙哲南. 三维人脸成像及重建技术综述[J]. 中国图象图形学报, 2024, 29(9): 2441-2470. DOI: 10.11834/jig.230697.

```bibtex
@article{Liu_2024_JIG_zh,
  title = {三维人脸成像及重建技术综述},
  author = {刘菲 and 张堃博 and 杨青 and 周树波 and 王云龙 and 孙哲南},
  journal = {中国图象图形学报},
  volume = {29},
  number = {9},
  pages = {2441--2470},
  year = {2024},
  doi = {10.11834/jig.230697},
  url = {https://www.cjig.cn/zh/article/doi/10.11834/jig.230697/},
  note = {GB/T 7714 Chinese fields. Authors and title verified from the cjig.cn article-page citation_* meta on 2026-11-16 (UTC+8 / Asia/Shanghai); PDF not downloaded.}
}
```

#### 34. Teng 等，3D-STD（ICME 2024）

- DOI：[10.1109/icme57554.2024.10687595](https://doi.org/10.1109/icme57554.2024.10687595)。Crossref 题名为 *Exploring 3D-aware Lifespan Face Aging via Disentangled Shape-Texture Representations*；作者 Qianrui Teng, Rui Wang, Xing Cui, Peipei Li, Zhaofeng He；会议 *2024 IEEE International Conference on Multimedia and Expo (ICME)*；`published-print` = 2024-07-15；页 1–6。arXiv：[2312.16881](https://arxiv.org/abs/2312.16881)（2026-11-16 打开摘要页，题名与作者与 Crossref 一致；许可为 nonexclusive-distrib 1.0）。
- 相关性：用三维表示把老化拆成形状与纹理，与本课题「形状空间年龄方向 + 纹理变换」的分工直接相关。初稿曾把「3D-STD」写成未核实，现予更正。旧文档曾建议 A 翻译此文；篇幅短（6 页），宜作 A 的备选，不替换与代码主线更贴近的 3DDFA_V2。
- 许可：arXiv 摘要页为 nonexclusive-distrib 1.0；IEEE 正式版版权未打开许可页。

```bibtex
@inproceedings{Teng_2024,
  title = {Exploring 3D-aware Lifespan Face Aging via Disentangled Shape-Texture Representations},
  url = {http://dx.doi.org/10.1109/icme57554.2024.10687595},
  DOI = {10.1109/icme57554.2024.10687595},
  booktitle = {2024 IEEE International Conference on Multimedia and Expo (ICME)},
  publisher = {IEEE},
  author = {Teng, Qianrui and Wang, Rui and Cui, Xing and Li, Peipei and He, Zhaofeng},
  year = {2024},
  month = {July},
  pages = {1--6},
  eprint = {2312.16881},
  archivePrefix = {arXiv}
}
```

---

## 4. 使用与引用时的注意

1. Crossref 为 LNCS 章节返回 `@inbook`（YOLO5Face、3DDFA_V2、MICA、LATS、MiVOLO），这是官方接口原文，不是录入错误。若学校模板要求 `@inproceedings`，可在不改动题名、DOI、页码的前提下由学生自行调整条目类型，并保留 DOI。
2. 预印本与正式版可能在年份、页码甚至题名大小写上不同；开题和论文中应同时给出 DOI（若有）和 arXiv 编号（若有），不要只引预印本却写成会议页码，或只引会议却使用未核对的 arXiv 编号。IJCV 等期刊请优先使用纸刊年与卷期（见第 28、30a 条）；Crossref 默认 BibTeX 的 `year` 常常取在线首发年。
2b. 所有月份字段已写成 `month={June}`（或 `{April}`、`{December}` 等），避免 `month=June` 被 BibTeX / bibtexparser 当作未定义的宏。不要改回无花括号的写法。
3. 仓库代码与任务书用词不一致（检测器、重建模型）已在 RD-1 核过：文献综述应写清「任务书原方案 / 代码实际采用」，不要把 MICA、FLAME、YOLO26n-face 写成已实现主线。
4. 翻译版权：即使预印本为 CC BY，正式出版社版本仍可能另有版权；nonexclusive-distrib 1.0 **不**等于可以自由再发布译文。是否可用某版本作翻译底本，需问导师并按学校规定处理。本文不作法律意见。

---

## 5. 未核实或明确不收入的条目

| 条目 | 说明 |
|---|---|
| DBLP BibTeX | 2026-11-16 访问 `dblp.org` 的 `.bib` 接口时，返回 Anubis「Making sure you're not a bot」页，未能取得 DBLP 记录。上文 BibTeX 不以 DBLP 为来源。 |
| 「3D-STD」作为翻译原文 | 初稿未能核实。现已核到 Teng 等 ICME 2024，DOI 10.1109/icme57554.2024.10687595，见第 34 条；列为 A 的短篇备选。 |
| three.js / WebGL 官方论文 | 仍未核实到 three.js 官方学术论文。已改用 Evans 等 2014 年 Web 三维综述（第 31 条 / B4）作为该方向的已核实候选。是否允许用 three.js 文档或 Khronos 规范代替外文翻译，需问导师。 |
| YOLOv5 正式论文 | 未核实到与 Ultralytics YOLOv5 对等的正式会议/期刊论文。检测框架引用请用第 4 条，人脸检测请用第 2 条。 |
| FG-NET 数据库的「原始发布论文」 | 已收入 2016 年综述（第 26 条）。带 DOI 的原始发布文献本次未核到。 |
| FADING / DiffAge3D 的 DOI | 两篇都有 DataCite/arXiv DOI（10.48550/arXiv.2309.11321、10.48550/arXiv.2408.15922），doi.org 可跳转；Crossref 返回 404 并不能说明「没有 DOI」。FADING 已发表于 BMVC 2023，但本次未在 Crossref 检索到另外的会议 DOI。DiffAge3D 仍只有预印本。 |
| 第 3、4、7、8、10、11、15—19、22—29 条的 arXiv 许可 | 除文中已打开摘要页并写明许可者外，其余条目本次只核了 Crossref（或 OpenAlex 旁证），**不把未打开的 arXiv 编号或许可写进正文**。 |
| OpenAlex 所记的 ACM CC 许可 | 第 13、14 条的正式版 CC 标记来自 OpenAlex 字段，未打开 ACM 页面核对，不得写成「已核实的出版社许可」。 |
| 任务书中的 YOLO26n-face | 不是一篇文献；存在性与许可见 RD-1，不在本清单重复展开。 |

---

## 6. 来源列表（均于 2026-11-16、UTC+8 / Asia/Shanghai 访问）

| 来源 | URL 或位置 | 用途 |
|---|---|---|
| Crossref 内容协商 BibTeX | `https://api.crossref.org/works/{DOI}/transform/application/x-bibtex` | 第 1—19、22—32、34 条的题名、作者、DOI、页码与 BibTeX（含第 31、32、34 条；第 33 条只用其卷期页，作者未照抄） |
| Crossref 检索 API | `https://api.crossref.org/works?query.bibliographic=...` | 用题名定位正确 DOI（曾排除错误的 10.1109/AVSS.2009.25、10.1109/CVPR.2016.592 等） |
| arXiv 摘要页 | `https://arxiv.org/abs/1511.06523`、`2105.12931`、`2009.09960`、`2102.02754`、`1909.01815`、`2309.11321`、`2408.15922`、`2312.16881` | 预印本题名、作者、许可；FADING、DiffAge3D 与 3D-STD（第 34 条）的全文信息源 |
| OpenAlex | `https://api.openalex.org/works/doi:...` | WIDER FACE 的 arXiv 编号 1511.06523；IPCGAN 作者顺序；部分许可旁证 |
| 规划 v2 | `/workspace/AgeMorph3D_后续任务规划_v2.md` 第 12、27、108—112 行 | 任务范围、翻译不可代写；第 27 行曾写 A/B 姓名未绑定（现 A 已由用户本人确认） |
| 交付清单 | `/workspace/AgeMorph3D/docs/毕业设计要求与交付清单.md` 第 31、49、72 行 | 分工与个人翻译要求 |
| 技术框架（2026-10-17） | `docs/AgeMorph3D_技术框架与模块行动计划.md` 第 4–5、303 行 | 编制日期；旧的翻译选题建议；「宋明耀（A）」 |
| 模型资产登记（2026-11-01） | `docs/model-assets.md`、`docs/模型资产诊断与严格服务缺项记录.md` 文首 | 「宋明耀（成员 B）」 |
| 研究清单与测试 | `backend/model-manifests/3ddfa-v2.research.json` 与 `yolov5n05-face.research.json` 第 12 行；`backend/tests/test_model_assets.py` 第 168 行 | “member B, project owner”；测试只断言姓名 |
| 可行性分析中的中文综述 | `docs/AgeMorph3D_毕设可行性分析.md` 第 219–220 行 | 中文题名线索；卷期页与 DOI 已用 Crossref / OpenAlex 复核 |
| 中国图象图形学报出版社页（第 33 条） | https://www.cjig.cn/zh/article/doi/10.11834/jig.230697/ | 中文题名、刊名与 `citation_author`（刘菲、张堃博、杨青、周树波、王云龙、孙哲南）；2026-11-16 打开文章页，未下载 PDF |
| DataCite API 与 doi.org | `https://api.datacite.org/dois/10.48550/arXiv....` 、`https://doi.org/10.48550/arXiv....` | FADING / DiffAge3D 的预印本 DOI |
| BMVC 官方页（Wayback） | `https://web.archive.org/web/20260519031506/https://proceedings.bmvc2023.org/595/` | FADING 官方 BibTeX；当日直播站 TLS 失败 |
| DBLP | `https://dblp.org/rec/....bib` | 当日被拦截，未采用 |

---

## 7. 给 Sentinel / Atlas 的摘要

- 产出：`/workspace/AgeMorph3D_tasks/RD-2_开题文献清单.md` 与同名 `.bib`。
- 已核实 **35 条记录**（编号 1—34，第 30 条含 30a、30b）。
- A 的翻译候选：3DDFA_V2、YOLO5Face、SAM（备选 3D-STD、MICA）。
- B 的翻译候选：B1–B3（BFM 2009、3DDFA CVPR 2016、WIDER FACE，贴合度需导师确认）以及 B4 Evans 等 2014 Web 三维综述。
- 未代写任何译文；未下载 PDF、数据或权重；未改项目 GitHub。
- A = 宋明耀（用户本人 2026-11-21 确认）；B = 王晋涛（用户本人 2026-11-21 确认）。仍待确认：学校模板对中外文比例的要求；B4 篇幅是否适合作为翻译原文。
