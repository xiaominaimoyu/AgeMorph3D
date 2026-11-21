# GK-3 参考文献草稿

- **状态：草稿，须由学生本人终审后才能用进论文。**
- 初稿日期：2026-11-16（UTC+8 / Asia/Shanghai）
- r1 修订：2026-11-21（UTC+8 / Asia/Shanghai）。Sentinel 审核结论 PASS（0 CRITICAL / 0 MAJOR / 9 MINOR），已就地修订。
- **本文件为 r2**（2026-11-21，UTC+8 / Asia/Shanghai）：把 RD-7 已审核的中文文献补充并入 r1，另存为本文件。r1（`GK-3_参考文献草稿.md`，sha256 `2294aca149b6c60698ee525e3c802553d554c1b350fab183f483e6f6a7881f86`）未改动。
- 任务：在 r1 基础上并入 RD-7 的 6 篇新增中文文献；RD-7 标明的 1 篇备选单独列出，不进正文列表。
- 状态：草稿，须由学生本人终审后才能用进论文。不写论文正文，未改仓库 / GitHub / RD-2 / RD-7。
- 输入（只读）：
  - r1 `/workspace/AgeMorph3D_tasks/GK-3_参考文献草稿.md`（sha256 `2294aca149b6c60698ee525e3c802553d554c1b350fab183f483e6f6a7881f86`）
  - `/workspace/AgeMorph3D_tasks/RD-7_中文文献补充.md`（sha256 `b4a6befabf4a5a165963121dda5c421eabefe5ccc28c09200d0e34afae613da9`）
  - `/workspace/AgeMorph3D_tasks/RD-7_中文文献补充.bib`（sha256 `bdf338e416ba8f7b7a223bf206fe294dc4473783a9dafa750dc6c485110944f3`）
  - `/workspace/AgeMorph3D_tasks/RD-2_开题文献清单.md`（当前 sha256 `ac183237a813a854a03d5b69b289a65e5cb1336424ef9b8a126ffa523eb6fd38`；r1 著录时所记为 `7ea99704de641fa7ea665d752dce390788ef9455960169e921ea424cdc896dc0`，现已变化。r2 **不根据新版 RD-2 改写已有条目**，第 1—34 条仍用 r1 原文。）
  - `/workspace/AgeMorph3D_tasks/RD-2_开题文献清单.bib`（sha256 `68315a6c2591962fac5ae1a12b568840c4d80d2f069f5ee4b99f74d5cae5b7ac`，与 r1 记录一致）
- 排列与编号（过渡方案）：第 1—34 条（含 30a、30b）沿用 r1 / RD-2 编号，共 35 条；第 35—40 条依次对应 RD-7 新-1—新-6。正文列表合计 **41** 条。RD-7 备选-A（赵世杰等 2025）不进正文列表。`.bib` 中 `Liu_2024_JIG_zh` 仍是第 33 条的中文配套，不另编号。**30a/30b 与按 RD-2 / 增补顺序排列都只是过渡方案。** 学校论文模板要求 (5)：序号应按文中标注出现的先后顺序排，并用连续整数编号。终稿必须按正文首次引用顺序重新编为 [1]、[2]、…。

---

## 一、格式依据

仓库 `docs/` 的 Markdown 正文没有写出参考文献著录细则。进一步检查了 Word 模板（用 Python 抽取 `word/document.xml` 段落，未改任何仓库文件），**找到了西华大学本科毕业设计论文模板中的参考文献格式要求**，本稿按该校模板著录，不是「仓库中未找到、退回 GB/T 7714-2015」的情形。

依据文件（两份模板的参考文献格式条款与示例一致）：

1. `/workspace/AgeMorph3D/docs/任务书模板/附件4：2024届本科毕业设计论文+模板_计算机科学与技术（示例0513）(1).docx`，抽取段落约 P293—P326（要求条款 + 各类型格式与示例；P326 含 [EB/OL] 示例和文献类型标志代码表）。段落号按非空 `w:p` 从 1 计。
2. `/workspace/AgeMorph3D/docs/zip_extracted/4-本科毕业设计说明书模板.docx`，抽取段落约 P249—P275（同一套条款与示例）。

模板中的主要规定（摘录要点，不是逐字全文）：

- 篇数 ≥ 15；至少 5 篇中文、5 篇英文；近 3 年文献至少 5 篇。序号按文中标注出现的先后顺序排（模板要求 (5)）。本稿尚未排定正文引用顺序，故暂按 RD-2 清单顺序，终稿须改成连续整数。
- 英文人名用「姓 + 名的缩写」，参见模板示例（如 `Zhang S., Liu L., Diao L. H.`）。
- 多名作者之间用逗号加空格分隔；**各项信息之间的分隔符均使用英文半角，并加一空格**。
- 类型格式（本稿实际用到的）：
  - 期刊：`作者名. 期刊论文题目[J]. 期刊名称, 年, 卷(期): 起止页码.`
  - 会议：`作者名. 会议论文题目[C]. 学术会议论文集名称, 出版年份: 起止页码.`（**没有** GB/T 7714 常见的 `[C]//` 写法）
  - 网上文献：`作者名. 网上文章题目[EB/OL]. 网址, 查阅的年-月-日.`
- 文献类型标志与 GB/T 7714 一致：M / C / G / N / J / D / R / S / P / DB / CP / EB。

同目录任务书 `docs/任务书模板/【任务书】岁月镜AgeMorph3D-基于YOLO与三维形变模型的跨年龄三维人脸重建及可视化系统.docx` 的「八、推荐主要参考文献和资料」（P162 起）示例混用了 `[C]//Proceedings of …` 的写法，与上述论文模板不完全相同。**本稿以论文 / 说明书模板为准，不采用 `[C]//`。**

`docs/zip_extracted/2-开题报告模板.docx` 未另给完整著录细则。核过该模板「参考文献」节：除一条期刊示例（P89，`[J]`）外，还有一条学位论文示例（P91，`[D]`：`丛国华. 基于SKIA的可移植控件组的设计与实现[D]. 北京邮电大学, 2010.`），以及一条网上文献示例（P90，`[OL]`）。初稿写「仅有一条期刊示例」不准确，现予更正。

另：`docs/zip_extracted/1-任务书模板.docx` P58 写的是「推荐主要参考文献和资料【不少于10篇、其中至少2篇英文】」。这是任务书模板的篇数下限，低于论文模板的「≥15；至少 5 篇中文、5 篇英文；近 3 年至少 5 篇」。论文终稿应按更严的论文模板核对。

作者截断：学校模板的英文标准示例为前 3 名 + `et al.`（`Beser B., Droms R., Stump G., et al.`）；中文期刊示例则列出了全部 4 位作者、未用「等」。GB/T 7714-2015 顺序编码制为超过 3 人时写前 3 名加「等」/ `et al.`。本稿 **中英文一律按前 3 名 + 等 / et al.** 处理，并在第 33 条注明 RD-2 已有 6 位作者全写的中文示例，终审时可改。英文姓名样式按学校示例（`Yang S.`），**不用** GB/T 常见的全大写姓氏（`YANG S`）。

---

## 二、参考文献（按 RD-2 顺序，过渡编号）

下列条目可直接作为粘贴底稿，但须由学生本人终审。没有根据网络检索补全缺项。学校模板示例未要求在正文著录中写入 DOI；DOI 与 arXiv 编号见第三节核对表之后的对照。

**编号说明：** 此处的 [1]—[34] 与 30a/30b 只为与 RD-2 对齐，不是终稿编号。学校论文模板要求 (5)：「序号应按文中标注出现的先后顺序排」，须用连续整数。论文定稿时必须按正文首次引用顺序重新编号。第 33 条的中文配套 bib 键不单独编号，这一点可以保留。

[1] Yang S., Luo P., Loy C. C., et al. WIDER FACE: A Face Detection Benchmark[C]. 2016 IEEE Conference on Computer Vision and Pattern Recognition (CVPR), 2016: 5525-5533.
[2] Qi D., Tan W., Yao Q., et al. YOLO5Face: Why Reinventing a Face Detector[C]. Computer Vision – ECCV 2022 Workshops, 2023: 228-244.
[3] Deng J., Guo J., Ververas E., et al. RetinaFace: Single-Shot Multi-Level Face Localisation in the Wild[C]. 2020 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR), 2020: 5202-5211.
[4] Redmon J., Divvala S., Girshick R., et al. You Only Look Once: Unified, Real-Time Object Detection[C]. 2016 IEEE Conference on Computer Vision and Pattern Recognition (CVPR), 2016: 779-788.
[5] Blanz V., Vetter T. A morphable model for the synthesis of 3D faces[C]. Proceedings of the 26th annual conference on Computer graphics and interactive techniques - SIGGRAPH ’99, 1999: 187-194.
[6] Paysan P., Knothe R., Amberg B., et al. A 3D Face Model for Pose and Illumination Invariant Face Recognition[C]. 2009 Sixth IEEE International Conference on Advanced Video and Signal Based Surveillance, 2009: 296-301.
[7] Zhu X., Lei Z., Liu X., et al. Face Alignment Across Large Poses: A 3D Solution[C]. 2016 IEEE Conference on Computer Vision and Pattern Recognition (CVPR), 2016: 146-155.
[8] Zhu X., Liu X., Lei Z., et al. Face Alignment in Full Pose Range: A 3D Total Solution[J]. IEEE Transactions on Pattern Analysis and Machine Intelligence, 2019, 41(1): 78-92.
[9] Guo J., Zhu X., Yang Y., et al. Towards Fast, Accurate and Stable 3D Dense Face Alignment[C]. Computer Vision – ECCV 2020, 2020: 152-168.
[10] Feng Y., Feng H., Black M. J., et al. Learning an animatable detailed 3D face model from in-the-wild images[J]. ACM Transactions on Graphics, 2021, 40(4): 1-13.
[11] Li T., Bolkart T., Black M. J., et al. Learning a model of facial shape and expression from 4D scans[J]. ACM Transactions on Graphics, 2017, 36(6): 1-17.
[12] Zielonka W., Bolkart T., Thies J. Towards Metrical Reconstruction of Human Faces[C]. Computer Vision – ECCV 2022, 2022: 250-269.
[13] Egger B., Smith W. A. P., Tewari A., et al. 3D Morphable Face Models—Past, Present, and Future[J]. ACM Transactions on Graphics, 2020, 39(5): 1-38.
[14] Alaluf Y., Patashnik O., Cohen-Or D. Only a matter of style: age transformation using a style-based regression model[J]. ACM Transactions on Graphics, 2021, 40(4): 1-12.
[15] Richardson E., Alaluf Y., Patashnik O., et al. Encoding in Style: a StyleGAN Encoder for Image-to-Image Translation[C]. 2021 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR), 2021: 2287-2296.
[16] Tov O., Alaluf Y., Nitzan Y., et al. Designing an encoder for StyleGAN image manipulation[J]. ACM Transactions on Graphics, 2021, 40(4): 1-14.
[17] Yao X., Puy G., Newson A., et al. High Resolution Face Age Editing[C]. 2020 25th International Conference on Pattern Recognition (ICPR), 2021: 8624-8631.
[18] Tang X., Wang Z., Luo W., et al. Face Aging with Identity-Preserved Conditional Generative Adversarial Networks[C]. 2018 IEEE/CVF Conference on Computer Vision and Pattern Recognition, 2018: 7939-7947.
[19] Or-El R., Sengupta S., Fried O., et al. Lifespan Age Transformation Synthesis[C]. Computer Vision – ECCV 2020, 2020: 739-755.
[20] Chen X., Lathuilière S. Face Aging via Diffusion-based Editing[C]. 34th British Machine Vision Conference 2023, BMVC 2023, Aberdeen, UK, November 20-24, 2023, 2023: 595.
[21] Wahid J., Zhan F., Rao P., et al. DiffAge3D: Diffusion-based 3D-aware Face Aging[EB/OL]. https://arxiv.org/abs/2408.15922, 2026-11-16.
[22] Suo J., Zhu S. C., Shan S., et al. A Compositional and Dynamic Model for Face Aging[J]. IEEE Transactions on Pattern Analysis and Machine Intelligence, 2010, 32(3): 385-401.
[23] Fu Y., Guo G., Huang T. S. Age Synthesis and Estimation via Faces: A Survey[J]. IEEE Transactions on Pattern Analysis and Machine Intelligence, 2010, 32(11): 1955-1976.
[24] Kostinger M., Wohlhart P., Roth P. M., et al. Annotated Facial Landmarks in the Wild: A large-scale, real-world database for facial landmark localization[C]. 2011 IEEE International Conference on Computer Vision Workshops (ICCV Workshops), 2011: 2144-2151.
[25] Moschoglou S., Papaioannou A., Sagonas C., et al. AgeDB: The First Manually Collected, In-the-Wild Age Database[C]. 2017 IEEE Conference on Computer Vision and Pattern Recognition Workshops (CVPRW), 2017: 1997-2005.
[26] Panis G., Lanitis A., Tsapatsoulis N., et al. Overview of research on facial ageing using the FG-NET ageing database[J]. IET Biometrics, 2016, 5(2): 37-46.
[27] Rothe R., Timofte R., Van Gool L. DEX: Deep EXpectation of Apparent Age from a Single Image[C]. 2015 IEEE International Conference on Computer Vision Workshop (ICCVW), 2015: 252-257.
[28] Rothe R., Timofte R., Van Gool L. Deep Expectation of Real and Apparent Age from a Single Image Without Facial Landmarks[J]. International Journal of Computer Vision, 2018, 126(2-4): 144-157.
[29] Kuprashevich M., Tolstykh I. MiVOLO: Multi-input Transformer for Age and Gender Estimation[C]. Analysis of Images, Social Networks and Texts, 2024: 212-226.
[30a] Everingham M., Van Gool L., Williams C. K. I., et al. The Pascal Visual Object Classes (VOC) Challenge[J]. International Journal of Computer Vision, 2010, 88(2): 303-338.
[30b] Deng J., Guo J., Xue N., et al. ArcFace: Additive Angular Margin Loss for Deep Face Recognition[C]. 2019 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR), 2019: 4685-4694.
[31] Evans A., Romeo M., Bahrehmand A., et al. 3D graphics on the web: A survey[J]. Computers & Graphics, 2014, 41: 43-61.
[32] Gong B., Qi L., Wu J., et al. The Aging Multiverse: Generating Condition-Aware Facial Aging Tree via Training-Free Diffusion[C]. Proceedings of the SIGGRAPH Asia 2025 Conference Papers, 2025: 1-12.
[33] 刘菲, 张堃博, 杨青, 等. 三维人脸成像及重建技术综述[J]. 中国图象图形学报, 2024, 29(9): 2441-2470.
[34] Teng Q., Wang R., Cui X., et al. Exploring 3D-aware Lifespan Face Aging via Disentangled Shape-Texture Representations[C]. 2024 IEEE International Conference on Multimedia and Expo (ICME), 2024: 1-6.
[35] 张珂, 梁龙萍, 郭玉荣, 王子念. 面向人脸年龄估计的开集半监督多任务学习方法[J]. 中国图象图形学报, 2025, 30(12): 3804-3823. https://www.cjig.cn/zh/article/doi/10.11834/jig.250023/ 。出版社页印有 DOI 10.11834/jig.250023，尚未在 doi.org 注册（截至 2026-11-21）。
    （RD-7 新-1，A / 宋明耀。著录按 RD-7 正式推荐行原文，用官网链接，不把尚未在 doi.org 注册的 DOI 写入著录行主体；说明附于行末，亦为 RD-7 原文。）
[36] 钟易澄, 裴玉茹, 李培鑫. 基于跨视角一致约束的单视角三维人脸重建[J]. 计算机辅助设计与图形学学报, 2024, 36(4): 543-551. DOI: 10.3724/SP.J.1089.2024.19772.
    （RD-7 新-2，A / 宋明耀。著录按 RD-7 原文。）
[37] 徐崇润, 刘利刚. 人脸图像去模糊和三维重建的联合优化方法[J]. 计算机辅助设计与图形学学报, 2025, 37(4): 583-592. DOI: 10.3724/SP.J.1089.2023-00334.
    （RD-7 新-3，A / 宋明耀。著录按 RD-7 原文。）
[38] 胡佳平, 周漾. 三维风格化人脸生成与结构化建模[J]. 中国图象图形学报, 2025, 30(4): 1155-1169. DOI: 10.11834/jig.240380.
    （RD-7 新-4，A / 宋明耀。著录按 RD-7 原文。）
[39] 刘畅, 张宇明, 张乾, 欧巧凤, 赵同硕, 陈昊, 石磊. 基于改进式DDGI的Web3D场景云渲染[J]. 图学学报, 2024, 45(6): 1364-1374.
    （RD-7 新-5，B / 王晋涛。著录按 RD-7 正式行原文，**不写 DOI**（官网目次印有编号，但 doi.org/Crossref 404）。官网链接见核对表，未写入本行，因 RD-7 正式 GB/T 行未包含该链接。**待确认：该刊是否算学校认定的中文核心；与 three.js / 人脸网格查看器的贴合度。**）
[40] 刘鑫达, 李康, 耿国华, 周明全. 文化遗产保护中虚拟现实技术研究进展[J]. 计算机辅助设计与图形学学报, 2025, 37(4): 545-560. DOI: 10.3724/SP.J.1089.2024-00509.
    （RD-7 新-6，B / 王晋涛。著录按 RD-7 原文。**待确认：是否贴题**（RD-7 写明这是虚拟现实与文化遗产综述，不是 Web3D / three.js 专文）。）

### 备选（不进入正文列表）

RD-7 已核实、但明确「未计入主表」的 1 篇。此处单独列出，不编号进 [1]—[40]。

- 备选-A（RD-7；角色 A / 宋明耀；bib `Zhao_2025_JCAD_SHFaceGen`）：赵世杰, 梁瑾裕, 杜晓飞, 高宏娟. 球谐函数局部特征投影的三维人脸生成方法[J]. 计算机辅助设计与图形学学报, 2025, 37(3): 385-395. DOI: 10.3724/SP.J.1089.2024-00298.
    （RD-7 说明：与「形状空间中的方向/属性控制」有相近处，但不是年龄变换或 3DMM 拟合论文。）

### 已有中文文献的去重说明

- **刘菲 等 2024**（RD-2 第 33 条 / bib `Liu_2024_JIG`、`Liu_2024_JIG_zh`）：已在正文列表第 33 条。RD-7 将其列为「已有-1、不计入新增」，r2 **不重复著录**。
- **张珂 等 2023**（任务书第八节 [12]）：RD-7 将其列为「已有-2、不计入新增」，不是 6 篇新增之一，故 **仍不编入正文列表**，是否纳入由用户决定。下面保留 r1 的任务书原文核对，并补上 RD-7 已独立核实的全写著录。

### 任务书第八节中的另一篇中文文献（未写入上方编号清单）

用户任务书「八、推荐主要参考文献和资料」第 [12] 条是另一篇中文文献。RD-7 把它当作已有条目复核，没有当作新增主条目。是否纳入本论文参考文献，**仍由用户决定**。

任务书原文（无 DOI）为：

> [12] 张珂, 于婷婷, 石超君, 等. 融合通道位置注意力机制和并行空洞卷积的人脸年龄合成[J]. 中国图象图形学报, 2023, 28(12): 3870-3883.

出处：`/workspace/AgeMorph3D/docs/任务书模板/【任务书】岁月镜AgeMorph3D-基于YOLO与三维形变模型的跨年龄三维人脸重建及可视化系统.docx`，第八节标题在抽取段落 P162，本条在 P174（非空 `w:p` 从 1 计）。上引与该段原文一致。

RD-7（2026-11-21）已打开出版社文章页独立核实，并给出全写 GB/T 行（5 位作者 + DOI；与可行性分析第 221 行一致）：

> 张珂, 于婷婷, 石超君, 娄文硕, 刘阳. 融合通道位置注意力机制和并行空洞卷积的人脸年龄合成[J]. 中国图象图形学报, 2023, 28(12): 3870-3883. DOI: 10.11834/jig.230007.

若纳入，正文列表中文将从 7 篇增为 8 篇（已满足「至少 5 篇中文」）。本稿不擅自把它编进 [1]—[40]。

---

## 三、核对表

| 编号 | bib key | 类型 | 缺失字段(待补) | 冲突/备注 |
|---|---|---|---|---|
| 1 | Yang_2016 | [C] | 无 | 完整。 |
| 2 | Qi_2023 | [C] | 无 | bib 为 @inbook（Crossref 对 LNCS 章节的返回类型），按学校会议论文格式著为 [C]。出版年为 2023（LNCS），会议为 ECCV 2022 Workshops（RD-2 已说明）。题名中的不换行空格已改为普通空格。 |
| 3 | Deng_2020 | [C] | 无 | 完整。 |
| 4 | Redmon_2016 | [C] | 无 | 完整。 |
| 5 | Blanz_1999 | [C] | 无 | 论文集名称保留 bib 原文（含弯引号 ’99）。 |
| 6 | Paysan_2009 | [C] | 无 | 完整。 |
| 7 | Zhu_2016 | [C] | 无 | 完整。 |
| 8 | Zhu_2019 | [J] | 无 | 完整。期刊年按 bib / RD-2 为 2019。 |
| 9 | Guo_2020 | [C] | 无 | bib 为 @inbook，著为 [C]。题名按 bib。 |
| 10 | Feng_2021 | [J] | 无 | 完整。页码 `1-13` 是 Crossref 给出的页数，不是 ACM TOG 的文章号（如 Article 88 这类）。文章号待补，须在 ACM Digital Library 核对后补，本稿不猜测。 |
| 11 | Li_2017 | [J] | 无 | 完整。页码 `1-17` 是 Crossref 页数，未带 ACM 文章号。文章号待补，须在 ACM DL 核对，不猜测。 |
| 12 | Zielonka_2022 | [C] | 无 | bib 为 @inbook，著为 [C]。题名中的不换行空格已改为普通空格。 |
| 13 | Egger_2020 | [J] | 无 | 作者共 13 人，按前 3 名 + et al. 截断。题名中的破折号（—）保留 bib 原文。页码 `1-38` 是 Crossref 页数，未带 ACM 文章号。文章号待补，须在 ACM DL 核对，不猜测。 |
| 14 | Alaluf_2021 | [J] | 无 | 完整（恰好 3 位作者，未截断）。页码 `1-12` 是 Crossref 页数，未带 ACM 文章号。文章号待补，须在 ACM DL 核对，不猜测。 |
| 15 | Richardson_2021 | [C] | 无 | 完整。 |
| 16 | Tov_2021 | [J] | 无 | 完整。页码 `1-14` 是 Crossref 页数，未带 ACM 文章号。文章号待补，须在 ACM DL 核对，不猜测。 |
| 17 | Yao_2021 | [C] | 无 | 出版年按 bib 为 2021；会议名称为 2020 25th ICPR（RD-2 已说明）。 |
| 18 | Tang_2018 | [C] | 无 | 完整。作者顺序按 RD-2 采用的 Crossref/OpenAlex 官方顺序。 |
| 19 | Or_El_2020 | [C] | 无 | bib 为 @inbook，著为 [C]。 |
| 20 | Chen_2023_BMVC | [C] | 无 | BMVC 2023 为线上论文集，RD-2 所录官方 BibTeX 没有页码。正文写作 `2023: 595.`。595 不是起止页码，而是论文编号：RD-2 已记录官方页面 `https://proceedings.bmvc2023.org/595/` 与官方 `url` `https://papers.bmvc2023.org/0595.pdf`。Sentinel 说明 DBLP / Semantic Scholar 的 595 同为论文编号。此项标「待导师确认」（备选是省去页码位）。DOI 为 DataCite 预印本 DOI（10.48550/arXiv.2309.11321），RD-2 写明未见另外的 Crossref 会议 DOI。作者按 bib「Xiangyi Chen and Stéphane Lathuilière」（名在前）解析。 |
| 21 | Wahid_2024_DiffAge3D | [EB/OL] | 无 | 仍为预印本（RD-2 核实至 2026-11-16 无 Crossref 会议/期刊记录）。按学校网上文献格式著为 [EB/OL]；网址取 bib，引用日期取 RD-2 查阅日期 2026-11-16。DataCite DOI 不写入学校模板正文格式，见下表备注。 |
| 22 | Jinli_Suo_2010 | [J] | 无 | bib 作者字段为「Jinli Suo and Song-Chun Zhu and Shiguang Shan and Xilin Chen」（无逗号、名在前），RD-2 写明保持 Crossref 原样。本稿按「名 姓」解析，其中 Song-Chun 著为 `Zhu S. C.`（前一版误写为 `Zhu S.`，已改）。顺序未改。 |
| 23 | Yun_Fu_2010 | [J] | 无 | bib 作者字段为「Yun Fu and Guodong Guo and Huang, T S」混用两种写法；「Huang, T S」著为 Huang T. S.。前两位按「名 姓」解析为 Fu Y., Guo G.，待核。 |
| 24 | Kostinger_2011 | [C] | 无 | 第一作者按 Crossref 拼写 Kostinger（无变音符号）。RD-2 已说明 TU Graz 页面常用 Köstinger，引用时可保留 Crossref 写法并在正文注明。 |
| 25 | Moschoglou_2017 | [C] | 无 | 完整。 |
| 26 | Panis_2016 | [J] | 无 | 完整。RD-2 提醒：此为 FG-NET 研究综述，不是数据库首次发布的原始技术报告。 |
| 27 | Rothe_2015 | [C] | 无 | 第三作者与第 28、30a 条统一写为 `Van Gool L.`。Crossref 对第 27 条的元数据有误（写成 `Gool, Luc Van`）；第 28 条和第 30a 条的 family 均为 `Van Gool`。不再作为未决项。 |
| 28 | Rothe_2018 | [J] | 无 | 年份、卷期按 RD-2 已核实的纸刊信息（2018 年，卷 126，第 2-4 期），不用 Crossref 默认 BibTeX 的在线首发年 2016。 |
| 29 | Kuprashevich_2024 | [C] | 无 | bib 为 @inbook，著为 [C]。论文集名称按 Crossref/bib 为 Analysis of Images, Social Networks and Texts（未改写成规划里出现过的 ICMV）。题名中的不换行空格已改为普通空格。 |
| 30a | Everingham_2010 | [J] | 无 | 年份、卷期按 RD-2 已核实的纸刊信息（2010 年，卷 88，第 2 期），不用 Crossref 默认的在线首发年 2009。 |
| 30b | Deng_2019 | [C] | 无 | 完整。 |
| 31 | Evans_2014 | [J] | 无 | RD-2 / bib 未提供期号，按「年, 卷: 页」著录（不把期号标为待补）。 |
| 32 | Gong_2025 | [C] | 无 | 完整。 |
| 33 | Liu_2024_JIG；Liu_2024_JIG_zh | [J] | 无 | 同一篇文献在 bib 中有英、中两条（Liu_2024_JIG 与 Liu_2024_JIG_zh）。正文按中文条著录（中文题名、刊名、作者）。作者截为前 3 名加「等」；RD-2 另给出 6 位作者全写的中文示例（未用「等」，并附 DOI），终审时可改回全写。MD 正文称 Crossref 英文题名的冒号为全角，bib 英文题名为半角冒号——本稿中文条不使用英文题名。中文条 url 为出版社文章页，英文条 url 为 doi.org，不是数据冲突，而是两条配套记录。 |
| 34 | Teng_2024 | [C] | 无 | 完整。bib 另有 eprint/arXiv 编号，学校会议格式未要求写入正文。 |
| 35 | Zhang_2025_JIG_AgeEst | [J] | 无 | RD-7 新-1。正式行用官网链接；出版社页印有 DOI 10.11834/jig.250023，但截至 2026-11-21 尚未在 doi.org 注册，不作为已注册 DOI 写入。角色 A。著录为 RD-7 正式推荐行原文。 |
| 36 | Zhong_2024_JCAD_SVFaceRecon | [J] | 无 | RD-7 新-2。角色 A。著录为 RD-7 原文。 |
| 37 | Xu_2025_JCAD_DeblurRecon | [J] | 无 | RD-7 新-3。角色 A。著录为 RD-7 原文。DOI 中的 2023 是稿件编号年份，纸刊年为 2025（RD-7 已说明）。 |
| 38 | Hu_2025_JIG_StylizedFace | [J] | 无 | RD-7 新-4。角色 A。著录为 RD-7 原文。 |
| 39 | Liu_2024_JOG_Web3D | [J] | 无 | RD-7 新-5。角色 B。不著录 DOI（目次编号 doi.org 404）。官网链接：http://www.txxb.com.cn/CN/Y2024/V45/I6/1364 （RD-7 bib / 文章页；正式 GB/T 行未写入该链接）。**待确认：是否算中文核心；是否贴题。** |
| 40 | Liu_2025_JCAD_VRHeritage | [J] | 无 | RD-7 新-6。角色 B。著录为 RD-7 原文。**待确认：是否贴题。** |
| 备选 | Zhao_2025_JCAD_SHFaceGen | [J] | 无 | RD-7 备选-A，不进正文列表。角色 A。著录为 RD-7 原文。 |


### DOI 与 arXiv 对照（学校模板正文格式未要求写入，仅供核对；全部取自 RD-2，未另查）

| 编号 | DOI | arXiv |
|---|---|---|
| 1 | 10.1109/cvpr.2016.596 | arXiv:1511.06523（仅见 RD-2 正文，bib 无 eprint 字段） |
| 2 | 10.1007/978-3-031-25072-9_15 | arXiv:2105.12931（仅见 RD-2 正文，bib 无 eprint 字段） |
| 3 | 10.1109/cvpr42600.2020.00525 | — |
| 4 | 10.1109/cvpr.2016.91 | — |
| 5 | 10.1145/311535.311556 | — |
| 6 | 10.1109/avss.2009.58 | — |
| 7 | 10.1109/cvpr.2016.23 | — |
| 8 | 10.1109/tpami.2017.2778152 | — |
| 9 | 10.1007/978-3-030-58529-7_10 | arXiv:2009.09960（仅见 RD-2 正文，bib 无 eprint 字段） |
| 10 | 10.1145/3450626.3459936 | — |
| 11 | 10.1145/3130800.3130813 | — |
| 12 | 10.1007/978-3-031-19778-9_15 | — |
| 13 | 10.1145/3395208 | arXiv:1909.01815（仅见 RD-2 正文，bib 无 eprint 字段） |
| 14 | 10.1145/3450626.3459805 | arXiv:2102.02754（仅见 RD-2 正文，bib 无 eprint 字段） |
| 15 | 10.1109/cvpr46437.2021.00232 | — |
| 16 | 10.1145/3450626.3459838 | — |
| 17 | 10.1109/icpr48806.2021.9412383 | — |
| 18 | 10.1109/cvpr.2018.00828 | — |
| 19 | 10.1007/978-3-030-58539-6_44 | — |
| 20 | 10.48550/arXiv.2309.11321 | arXiv:2309.11321 |
| 21 | 10.48550/arXiv.2408.15922 | arXiv:2408.15922 |
| 22 | 10.1109/tpami.2009.39 | — |
| 23 | 10.1109/tpami.2010.36 | — |
| 24 | 10.1109/iccvw.2011.6130513 | — |
| 25 | 10.1109/cvprw.2017.250 | — |
| 26 | 10.1049/iet-bmt.2014.0053 | — |
| 27 | 10.1109/iccvw.2015.41 | — |
| 28 | 10.1007/s11263-016-0940-3 | — |
| 29 | 10.1007/978-3-031-54534-4_15 | — |
| 30a | 10.1007/s11263-009-0275-4 | — |
| 30b | 10.1109/cvpr.2019.00482 | — |
| 31 | 10.1016/j.cag.2014.02.002 | — |
| 32 | 10.1145/3757377.3763988 | — |
| 33 | 10.11834/jig.230697 | — |
| 34 | 10.1109/icme57554.2024.10687595 | arXiv:2312.16881 |
| 35 | 出版社页印有 10.11834/jig.250023，doi.org 未注册（RD-7；故正式行不用 DOI） | — |
| 36 | 10.3724/SP.J.1089.2024.19772 | — |
| 37 | 10.3724/SP.J.1089.2023-00334 | — |
| 38 | 10.11834/jig.240380 | — |
| 39 | （不著录。目次印有 10.11996/JG.j.2095-302X.2024061364，doi.org/Crossref 404） | — |
| 40 | 10.3724/SP.J.1089.2024-00509 | — |
| 备选 | 10.3724/SP.J.1089.2024-00298 | — |



## 三-B、A / B 分工对照

本派单写明：**A = 宋明耀**（算法：检测微调、重建、年龄方向、纹理与算法实验）；**B = 王晋涛**（系统：three.js / 交互、后端、系统测试），且 B 的姓名已由用户确认。RD-7 文首仍写「B 的姓名仅出自 Atlas、用户本人尚未书面确认」，与本派单不一致；**对照表按本派单采用「王晋涛」**，并在此注明来源差异。

分组只根据 RD-2 / RD-7 已经写明的相关性或推荐角色，不另作推测。来源未指定角色的标「待定」；明确同时服务两条线的标「共同」。正文仍保留上面的单一编号列表。

| 编号 | 角色 | 依据（不出自来源的不写） |
|---|---|---|
| 1 | 共同 | RD-2：检测微调与官方 AP（A）+ 系统测试须区分 val/test（B）；亦为 B 翻译候选 B3（贴合度需导师确认） |
| 2 | A | RD-2 翻译候选 A2（YOLO5Face，检测微调） |
| 3 | A | RD-2：检测选型时与 YOLO5Face 并列的对照 |
| 4 | A | RD-2：检测框架来源 |
| 5 | 共同 | RD-2：3DMM 经典来源，后续 BFM、3DDFA 均建立其上；未单独指定翻译角色 |
| 6 | B | RD-2 翻译候选 B1（系统实际加载的 BFM）；贴合度需导师确认 |
| 7 | 共同 | RD-2：B 翻译候选 B2，亦列为 A 的备选翻译；贴合度需导师确认 |
| 8 | 共同 | RD-2：第 7 条的期刊扩展 |
| 9 | A | RD-2 翻译首选 A1（3DDFA_V2，重建主线） |
| 10 | A | RD-2：与 3DDFA_V2 / BFM 路线对照的重建方法 |
| 11 | A | RD-2：任务书曾出现的替代拓扑，并写明代码主线不是 FLAME |
| 12 | A | RD-2：A 的偏长备选翻译（MICA） |
| 13 | 共同 | RD-2：开题「相关工作」综述，未指定单人翻译 |
| 14 | A | RD-2 翻译候选 A3（SAM，纹理 / 年龄外貌） |
| 15 | A | RD-2：SAM / e4e 一类年龄编辑管线的常用前级 |
| 16 | A | RD-2：常与 pSp、SAM 一并讨论 |
| 17 | A | RD-2：二维年龄编辑对照 |
| 18 | A | RD-2：经典身份保持老化对照 |
| 19 | A | RD-2：与 SAM 并列的二维老化对照 |
| 20 | A | RD-2：规划点名的扩散人脸老化，作为较新的二维老化对照 |
| 21 | A | RD-2：三维感知人脸老化，与「在三维形状空间做年龄方向」对照 |
| 22 | A | RD-2：「三维或结构化老化」相关工作的历史引用 |
| 23 | 共同 | RD-2：年龄合成与估计综述，适合开题相关工作 |
| 24 | 共同 | RD-2：AFLW 原始数据集，AFLW2000-3D 用其前 2000 个样本；未单独指定角色 |
| 25 | A | RD-2：年龄方向学习计划采用的数据集 |
| 26 | A | RD-2：FG-NET 老化数据库的可核验综述 |
| 27 | A | RD-2：DEX / IMDB-WIKI，年龄估计 |
| 28 | A | RD-2：第 27 条的期刊扩展 |
| 29 | A | RD-2：规划点名的年龄 / 性别估计，用于评价或对照年龄标签 |
| 30a | 共同 | RD-2：WIDER FACE 官方 AP 所沿用的评价口径（检测实验与系统测试） |
| 30b | 共同 | RD-2：跨年龄后的身份一致性评价 |
| 31 | B | RD-2 翻译候选 B4（Web 三维可视化综述） |
| 32 | A | RD-2：较新的扩散人脸老化，补开题「近年进展」；未指定翻译角色，主题属算法线 |
| 33 | 共同 | RD-2 / RD-7 已有-1：中文三维重建综述，开题文献 |
| 34 | A | RD-2：A 的短篇备选翻译（3D-STD） |
| 35 | A | RD-7 新-1：人脸年龄估计，年龄方向与相关实验 |
| 36 | A | RD-7 新-2：单视角三维人脸重建，与 3DDFA_V2 + BFM 主线相关 |
| 37 | A | RD-7 新-3：模糊人脸三维重建，在 AFLW 等数据上评估 |
| 38 | A | RD-7 新-4：带纹理的结构化三维人脸网格；风格化不是主线 |
| 39 | B | RD-7 新-5：Web3D 客户端与云渲染，与 three.js / 浏览器三维展示相关。**待确认：是否核心、是否贴题。** |
| 40 | B | RD-7 新-6：虚拟现实与文化遗产综述，不是 Web3D / three.js 专文。**待确认：是否贴题。** |
| 备选 | A | RD-7 备选-A：三维人脸局部属性生成，不是年龄变换或 3DMM 拟合论文 |

按角色归类（只列正文列表；备选见上节）：

- **A（宋明耀）：** 2、3、4、9、10、11、12、14、15、16、17、18、19、20、21、22、25、26、27、28、29、32、34、35、36、37、38
- **B（王晋涛）：** 6、31、39、40
- **共同：** 1、5、7、8、13、23、24、30a、30b、33
- **待定：** 无（上表凡未单独指定翻译角色、但来源已写明服务开题或同时涉及两条线的，已标共同，并写了依据）

---

## 四、统计与著录说明

### 4.1 数量

- 正文列表独立文献：**41** 条（第 1—34 条含 30a、30b，共 35 条，沿用 r1；第 35—40 条 = RD-7 新-1—新-6）。
- 备选（不进正文列表）：**1** 条（RD-7 备选-A，赵世杰等 2025）。
- bib 键：RD-2 的 36 个（含第 33 条中文配套 `Liu_2024_JIG_zh`）+ RD-7 的 7 个 = **43** 个，各出现一次。
- 第 2 节正文列表无「待补」。第 20 条页码位仍是论文编号 595，待导师确认。第 10、11、13、14、16 条 ACM 文章号仍待补（不猜测）。
- **中文文献（正文列表）：7 篇**（第 33 条刘菲等 2024，加上第 35—40 条）。已达到论文模板「至少 5 篇中文」的要求。任务书 [12] 张珂等 2023 仍在清单外，由用户决定；若纳入则为 8 篇。备选-A 不计入这 7 篇。
- **英文文献（正文列表）：34 篇**，已多于「至少 5 篇」的要求。
- **「近 3 年」两种口径**（只计正文列表，按出版年；**从哪年算，待导师确认**）：
  - 按 2026-11、出版年 2024—2026：原有第 21、29、32、33、34 共 5 条，加上第 35—40 全部 6 条，合计 **11** 条。第 20 条（2023）与清单外的张珂等 2023 不计入。
  - 若 2027 年提交、口径为 2025—2027：原有仅第 32 条（2025），新增中第 35、37、38、40（均为 2025）计入，第 36、39（2024）不计入，合计 **5** 条。备选-A 亦为 2025，若不进正文列表则不计入。

### 4.2 著录选择（请终审时一并核对）

1. **arXiv / 预印本**：第 21 条 DiffAge3D 在 RD-2 中仍为预印本，按学校网上文献格式著为 **[EB/OL]**，写入 bib 中的 URL，引用日期用 RD-2 文首与该条均写明的查阅日期 2026-11-16。不采用「[J]. arXiv preprint arXiv:…」的另一种常见写法，以免与学校模板已给出的 [EB/OL] 示例不一致。第 20 条 FADING 已正式发表于 BMVC 2023，按 **[C]** 著录。官方 BibTeX 无页码，正文页码位现写论文编号 595（来自 RD-2 已记录的官方路径），待导师确认；也可改成省去该位。不把预印本或 PDF 页码写进去。
2. **作者截断与姓名**：第 1—34 条（英文及第 33 条中文）仍按 r1，超过 3 人写前 3 名加 `et al.` / 「等」。**第 35—40 条及备选严格沿用 RD-7 正式行，作者全写，未改成「等」。**西方姓名为「姓 + 名首字母缩写，首字母后加点，多词名之间空格」（如 `Loy C. C.`、`Black M. J.`、`Smith W. A. P.`、`Zhu S. C.`）。带连字符的姓保留（`Or-El`、`Cohen-Or`、`Kemelmacher-Shlizerman`）。第 27、28、30a 条第三人统一为 `Van Gool L.`。`et al.` 自带句点，其后直接接题名，不再加句点。
3. **中英文标点**：按学校要求，条目内分隔符一律英文半角并加空格（如 `2024, 29(9): 2441-2470.`）。页码起止符统一为 ASCII 连字符 `-`（bib 中多为 en-dash `–` 或 TeX 的 `--`，数字本身未改）。题名、论文集名称中的 en-dash / 长破折号 / 弯引号保留来源原文；Springer 题名里的不换行空格（U+00A0）改为普通空格，不改词。
4. **@inbook**：YOLO5Face、3DDFA_V2、MICA、LATS、MiVOLO 在 Crossref/RD-2 中为 `@inbook`，按学校会议论文格式改著为 [C]，未改题名、年份与页码。
5. **期刊缺期号**：仅第 31 条（Evans 等）RD-2 未提供期号，写成 `2014, 41: 43-61.`，不把期号标成「待补」。
6. **纸刊年**：第 28、30a 条按 RD-2 已核实的纸刊年（2018、2010），与 bib 一致。
7. **未写入正文的信息**：DOI、ISBN、ISSN、publisher、month、eprint 学校模板相应格式未要求，不写入第 2 节条目；DOI / arXiv 见上表。第 1、2、9、13、14 条的 arXiv 编号只写在 RD-2 正文、未写入对应 bib 的 eprint 字段，对照表中已标明「仅见 RD-2 正文」。
8. **MD 与 bib**：逐字段对照后，正式出版物的题名、作者、年、卷期、页码在 MD 代码块与 `.bib` 之间没有实质性分歧（见自检）。第 33 条的中、英配套 url 不同，已在备注说明。

### 4.2.1 待用户/导师确认

下列选择原先分散在 §1、§4.2 和核对表中，现汇成一表，便于一次定稿。

| # | 事项 | 本稿现状 | 需确认的选择 |
|---|---|---|---|
| 1 | 作者是否截成前 3 名加 et al. / 「等」 | 中英文一律截断 | 学校模板中文期刊示例是 4 位作者全写、未用「等」；RD-2 第 33 条也给出了 6 位全写的中文示例。是否改为中文全写、或全部全写，请定。 |
| 2 | 正文是否加 DOI / arXiv 号 | 第 2 节未写入；对照表另列 | RD-2 第 528 行建议：「开题和论文中应同时给出 DOI（若有）和 arXiv 编号（若有）」。学校模板示例没有 DOI。是否在终稿条目末补上，请定。 |
| 3 | 会议论文写 `[C].` 还是 `[C]//` | 按论文模板写 `[C].` | 任务书第八节示例用了 `[C]//Proceedings of …`。本稿以论文 / 说明书模板为准。若导师要求与任务书一致，需改。 |
| 4 | 第 24 条第一作者拼写 | 按 Crossref 写 `Kostinger` | RD-2 已说明 TU Graz 常用 `Köstinger`。正文里写哪一种，请定。 |
| 5 | `[EB/OL]` 引用日期 | 第 21 条现写 RD-2 查阅日期 2026-11-16 | 终稿应改为学生本人实际查阅的日期。 |
| 6 | 是否纳入任务书第八节 [12]（张珂等，2023） | 仍在清单外。RD-7 已核实全写著录与 DOI，但把它列为已有、不计入新增，故 r2 未编入 [1]—[40] | 纳入后中文为 8 篇（已满足 ≥5）。 |
| 7 | 第 20 条 FADING 的 `2023: 595.` | 595 是论文编号，不是页码 | 保留论文编号，还是省去该位，待导师确认。 |
| 8 | 第 10、11、13、14、16 条 ACM TOG 文章号 | 正文仍用 Crossref 的 `1-13` 这类页数；文章号待补 | 请在 ACM Digital Library 核对后补上（例如 Article 88 这种写法）。本稿不猜测具体号。 |
| 9 | 「近 3 年」从哪年算 | 2024—2026 口径下正文列表 11 条；2025—2027 口径下 5 条 | 请导师确认起算规则。张珂等 2023、第 20 条 2023 在前一口径下不计入。 |
| 10 | 终稿编号 | 现用 RD-2 号、30a/30b，以及续编的 35—40 | 必须按正文首次引用顺序改成连续整数。 |
| 11 | 新-5（第 39 条）是否算核心 | 《图学学报》不在 RD-7 所述任务点名的优先短名单中；RD-7 请导师确认是否计入学校「中文核心」目录 | 是否保留在正文列表，请定。 |
| 12 | 新-5（第 39 条）是否贴题 | RD-7：与 three.js / 浏览器三维展示相关，但技术点是全局光照与云渲染，不是人脸网格查看器 | 请导师确认贴合度。 |
| 13 | 新-6（第 40 条）是否贴题 | RD-7：优先期刊上的 VR / 文化遗产综述，**不是** Web3D / three.js 专文 | 请导师确认贴合度。 |

### 4.3 自检结果（r2，2026-11-21 重跑）

- PASS: 正文列表 41 条（1—34 含 30a/30b，加 35—40）。
- PASS: 正文列表著录行无「待补」。
- PASS: 张珂 2023 未进入正文列表（仍作用户待决说明）。
- PASS: 刘菲 2024 仅出现在第 33 条，未因 RD-7 重复著录。
- PASS: 备选-A 单独成节，未进入正文列表。
- PASS: RD-2 的 36 个与 RD-7 的 7 个 bib key 在核对表「bib key」列中各出现恰好 1 次（合计 43）。
- PASS: 第 35—40 条及备选的著录行均可在 RD-7 中逐字找到，未改写任何字符。
- PASS: 第 39 条（新-5）著录行无 DOI。
- PASS: 第 35 条（新-1）正式行用官网链接，并保留 RD-7 关于 DOI 未注册的原文说明。
- PASS: 正文列表中文 7 篇、英文 34 篇。
- PASS: 近 3 年按 2024—2026 计为 11 条（原 5 + 新 6）。
- PASS: 近 3 年按 2025—2027 计为 5 条（32、35、37、38、40）。
- PASS: 已在对应条目旁及待确认表中标注新-5 是否核心、新-5/新-6 是否贴题、「近 3 年」从哪年算。
- PASS: 已增加 A/B 分工对照（A 宋明耀、B 王晋涛）。
- PASS: r1 文件未被改写（sha 前缀仍为 2294aca1）。
- PASS: 自检总评 通过。

## 五、审核修订（2026-11-21）

Sentinel 对初稿（sha256 前缀 `c8205d6f`，mtime 2026-11-16 13:48 UTC+8）的结论为 PASS（0 CRITICAL / 0 MAJOR / 9 MINOR）。按 MINOR 就地修订，未改仓库、未改 RD-2，也未再送审。修订要点：

1. 增补任务书第八节 [12]（张珂等，2023）的说明，不编入编号清单；引文已与任务书 docx P174 原文核对。DOI 采用 Sentinel 经 Crossref 核实的 `10.11834/jig.230007`。若纳入，中文为 2 篇，仍差 3 篇。
2. 第 27、28、30a 条第三人统一为 `Van Gool L.`；删去第 27 条待核。说明 Crossref 第 27 条元数据有误，第 28、30a 条 family 为 `Van Gool`。
3. 第 22 条 `Zhu S.` 改为 `Zhu S. C.`（Song-Chun）。
4. 第 20 条 FADING 由「待补」改为 `2023: 595.`。595 是论文编号（RD-2 已有官方路径），不是起止页码，标「待导师确认」。第 2 节待补条数改为 0。
5. 写明 30a/30b 与按 RD-2 排序只是过渡方案；模板要求 (5) 须按正文首次引用顺序用连续整数重新编号。中文配套不单独编号，可保留。
6. 新增「待用户/导师确认」表，汇总作者截断、是否加 DOI、`[C].` 与 `[C]//`、Kostinger 拼写、[EB/OL] 查阅日、是否纳入任务书 [12]、FADING 595、ACM TOG 文章号、近 3 年口径与终稿编号。
7. 补充：按 2026-11 计「近 3 年」为 5 条；若 2027 年提交，可能只剩第 32 条，待导师确认。
8. 更正 §1：开题报告模板有 [J]、[D] 各一条（另有一条 [OL]）；1-任务书模板要求「不少于10篇、其中至少2篇英文」（P58）。附件4 依据范围改为 P293—P326。
9. 第 10、11、13、14、16 条注明 Crossref 的 `1-13` 一类是页数、未带 ACM 文章号；文章号待补，须查 ACM DL，不猜测。


## 六、r2 修订（2026-11-21）

将 Sentinel 已审核的 RD-7 中文文献补充并入 r1，**另存为** `GK-3_参考文献草稿_r2.md`。r1 文件未改。未改仓库、GitHub、RD-2 或 RD-7，未写论文正文。

1. 正文列表由 35 条增至 **41** 条：第 35—40 条依次为 RD-7 新-1—新-6。著录行从 RD-7「GB/T 7714」正式行**逐字复制**。新-1 用官网链接；新-5 不写 DOI。作者按 RD-7 全写，未改成「等」。
2. RD-7 备选-A（赵世杰等 2025，`Zhao_2025_JCAD_SHFaceGen`）单独列为「备选」，不进正文列表。
3. **去重：** 刘菲等 2024 已是第 33 条，不重复。张珂等 2023 在 RD-7 中是「已有-2、不计入新增」，不是 6 篇新增之一，故仍留在清单外由用户决定；旁补 RD-7 已核实的全写 + DOI 著录。
4. 在第 39、40 条旁及「待用户/导师确认」表中标注：新-5 是否算核心、新-5 / 新-6 是否贴题、「近 3 年」从哪年算。
5. 新增 A/B 分工对照。A = 宋明耀，B = 王晋涛（按本派单；RD-7 文首曾写 B 的姓名尚未由用户书面确认，已注明差异）。分组依据仅取 RD-2 / RD-7 已写明的相关性，不另推测。
6. 更新统计：正文列表中文 7 篇（已满 ≥5）、英文 34 篇；近 3 年在 2024—2026 口径下 11 条，在 2025—2027 口径下 5 条。
7. 著录字符改动：无（见自检）。新-5 官网链接未写入著录行（RD-7 正式行本来没有），只写入核对表。

输入哈希（写入时）：见文首。说明：开始作业时 RD-7 的 md 哈希曾为 `637a9ee1…`，写入前再核为文首所记值；`.bib` 哈希始终为 `bdf338e4…`。RD-2 的 md 相对 r1 著录时已变化，r2 未据此改写第 1—34 条。
