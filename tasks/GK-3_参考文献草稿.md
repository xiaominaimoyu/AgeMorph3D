# GK-3 参考文献草稿

- **状态：草稿，须由学生本人终审后才能用进论文。**
- 初稿日期：2026-11-16（UTC+8 / Asia/Shanghai）
- 本次修订：2026-11-21（UTC+8 / Asia/Shanghai）。Sentinel 审核结论 PASS（0 CRITICAL / 0 MAJOR / 9 MINOR），本稿按 MINOR 建议就地修订，未再送审。
- 任务：将 RD-2 开题文献清单整理为学校要求的参考文献格式，供开题报告 / 毕业论文使用。
- 输入（只读，未改仓库）：
  - `/workspace/AgeMorph3D_tasks/RD-2_开题文献清单.md`（sha256 `7ea99704de641fa7ea665d752dce390788ef9455960169e921ea424cdc896dc0`）
  - `/workspace/AgeMorph3D_tasks/RD-2_开题文献清单.bib`（sha256 `68315a6c2591962fac5ae1a12b568840c4d80d2f069f5ee4b99f74d5cae5b7ac`）
- 排列与编号（过渡方案）：本稿暂按 RD-2 清单编号 1—34（第 30 条含 30a、30b），共 **35** 条独立文献。`.bib` 另有 `Liu_2024_JIG_zh`，是第 33 条的中文著录配套，不另编号，这可以保留。**30a/30b 与按 RD-2 顺序排列都只是过渡方案。** 学校论文模板要求 (5) 写明：序号应按文中标注出现的先后顺序排，并用连续整数编号。终稿必须按正文首次引用顺序重新编为 [1]、[2]、…，不能把 30a/30b 或 RD-2 编号直接写进论文。

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

### 任务书第八节中的另一篇中文文献（未写入上方编号清单）

用户任务书「八、推荐主要参考文献和资料」第 [12] 条是另一篇中文文献。是否纳入本论文参考文献，**由用户决定**；本稿没有把它编进上面的 [1]—[34]，也没有为凑中文篇数把它算进 35 条。

任务书原文（无 DOI）为：

> [12] 张珂, 于婷婷, 石超君, 等. 融合通道位置注意力机制和并行空洞卷积的人脸年龄合成[J]. 中国图象图形学报, 2023, 28(12): 3870-3883.

出处：`/workspace/AgeMorph3D/docs/任务书模板/【任务书】岁月镜AgeMorph3D-基于YOLO与三维形变模型的跨年龄三维人脸重建及可视化系统.docx`，第八节标题在抽取段落 P162，本条在 P174（非空 `w:p` 从 1 计）。上引与该段原文一致。

DOI `10.11834/jig.230007` 由 Sentinel 经 Crossref 核实，任务书本条原文未写 DOI。同 DOI 也出现在仓库 `docs/AgeMorph3D_毕设可行性分析.md` 第 221 行；该处作者全写为「张珂, 于婷婷, 石超君, 娄文硕, 刘阳」，未用「等」。若纳入，编号清单外再加 1 篇中文，中文合计 2 篇，距论文模板「至少 5 篇中文」仍差 3 篇。本稿不编造文献填补。

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

---

## 四、统计与著录说明

### 4.1 数量

- 独立文献：**35** 条（RD-2 编号 1—34，其中 30 含 30a、30b）。
- `.bib` 条目：**36** 条（含第 33 条中文配套 `Liu_2024_JIG_zh`）。
- 第 2 节编号清单正文现无「待补」：**35** 条均已按学校模板写出完整条目。第 20 条页码位写的是论文编号 595，不是起止页码，已标「待导师确认」，不再计为「待补」。第 10、11、13、14、16 条的 ACM 文章号未写入正文（Crossref 只有 `1-13` 这类页数），在核对表中标「待补」，须查 ACM DL，不猜测。
- 中文文献：编号清单内 **1** 条（第 33 条）。任务书第八节 [12]（张珂等，2023）是另一篇已由 Sentinel 经 Crossref 核实的中文文献，是否纳入由用户决定；若纳入，中文为 2 篇，距论文模板「至少 5 篇中文」仍差 3 篇。本稿不编造文献填补。
- 英文文献：编号清单内 34 条，已多于「至少 5 篇」的要求。
- 「近 3 年」按整理日 2026-11 计、取出版年 2024—2026：第 21（2024 预印本）、29（2024）、32（2025）、33（2024）、34（2024），共 5 条，刚满论文模板「至少 5 篇」的下限。第 20 条为 2023 年，未计入。若 2027 年提交，且学院把「近 3 年」理解为 2025—2027，则可能只剩第 32 条（2025），**待导师确认**。

### 4.2 著录选择（请终审时一并核对）

1. **arXiv / 预印本**：第 21 条 DiffAge3D 在 RD-2 中仍为预印本，按学校网上文献格式著为 **[EB/OL]**，写入 bib 中的 URL，引用日期用 RD-2 文首与该条均写明的查阅日期 2026-11-16。不采用「[J]. arXiv preprint arXiv:…」的另一种常见写法，以免与学校模板已给出的 [EB/OL] 示例不一致。第 20 条 FADING 已正式发表于 BMVC 2023，按 **[C]** 著录。官方 BibTeX 无页码，正文页码位现写论文编号 595（来自 RD-2 已记录的官方路径），待导师确认；也可改成省去该位。不把预印本或 PDF 页码写进去。
2. **作者截断与姓名**：超过 3 人写前 3 名加 `et al.` / 「等」（是否改回全写见下方确认表）。西方姓名为「姓 + 名首字母缩写，首字母后加点，多词名之间空格」（如 `Loy C. C.`、`Black M. J.`、`Smith W. A. P.`、`Zhu S. C.`）。带连字符的姓保留（`Or-El`、`Cohen-Or`、`Kemelmacher-Shlizerman`）。第 27、28、30a 条第三人统一为 `Van Gool L.`。`et al.` 自带句点，其后直接接题名，不再加句点。
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
| 6 | 是否纳入任务书第八节 [12]（张珂等，2023） | 只在清单外说明，未编号 | 纳入后中文为 2 篇，仍差 3 篇。 |
| 7 | 第 20 条 FADING 的 `2023: 595.` | 595 是论文编号，不是页码 | 保留论文编号，还是省去该位，待导师确认。 |
| 8 | 第 10、11、13、14、16 条 ACM TOG 文章号 | 正文仍用 Crossref 的 `1-13` 这类页数；文章号待补 | 请在 ACM Digital Library 核对后补上（例如 Article 88 这种写法）。本稿不猜测具体号。 |
| 9 | 「近 3 年」口径 | 按 2026-11、出版年 2024—2026 计为 5 条 | 若 2027 年提交且口径改为 2025—2027，可能只剩第 32 条，待导师确认。 |
| 10 | 终稿编号 | 现用 RD-2 号及 30a/30b | 必须按正文首次引用顺序改成连续整数。 |

### 4.3 自检结果（2026-11-21 修订后重跑）

- PASS: 第 2 节独立文献 35 条（1—34，含 30a、30b）。
- PASS: 全部 36 个 bib key 在核对表「bib key」列中各出现恰好 1 次。
- PASS: 第 2 节编号条目无「待补」。
- PASS: 第 27、28、30a 条均统一为 Van Gool L.
- PASS: 第 27 条核对表已改为以 Van Gool 为准，不再列为未决项。
- PASS: 第 22 条为 Zhu S. C.
- PASS: 第 20 条为 2023: 595.，已去掉待补。
- PASS: 595 可在 RD-2 官方 URL（proceedings.bmvc2023.org/595/、0595.pdf）中找到。
- PASS: 第 2 节条目中的页码、卷期、出版年、DOI（若有）及第 20 条论文编号 595 均可在 RD-2 中找到原文（页码连字符已做等价折算）。
- INFO: 按出版年 2024—2026 的近 3 年条目：['21', '29', '32', '33', '34']（共 5）；若按 2025—2027：['32']（共 1）。
- PASS: 近 3 年计数与文中说明一致（2026-11 口径 5 条；2025—2027 口径仅第 32 条）。
- PASS: 已写入任务书[12]说明。
- PASS: 已写入DOI 230007。
- PASS: 已写入待确认表。
- PASS: 已写入开题[D]示例。
- PASS: 已写入1-任务书模板篇数。
- PASS: 已写入附件4 P326。
- PASS: 任务书[12]引文与 docx P174 原文一致。
- PASS: 任务书[12]未写入编号清单。
- PASS: 第 10、11、13、14、16 条核对表已注明 ACM 文章号待补、不猜测。
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

