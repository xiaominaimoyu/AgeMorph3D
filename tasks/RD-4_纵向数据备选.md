# RD-4 AgeDB 纵向数据备选核查

- 任务：按《AgeMorph3D 后续任务规划 v2》RD-4，为「同一人、多个年龄、有身份编号、覆盖到 70 岁、可合法取得并用于学术研究」的年龄方向学习，核查 AgeDB 的备选资源。对照方案 v3 §6 与 `docs/数据资源清单.md` §1。
- 查阅日期：2026-11-16（UTC+8，与规划 v2 及仓库文档约定一致）。下文 URL 均在该日访问。带有 `Last-Modified` 等时区标记的服务器时间，已换算到 UTC+8 后再写。本次核查看板会话所在时区为 Europe/Berlin（当时 UTC+1），与 UTC+8 的日历日期同为 2026-11-16。
- 范围：只做调研。**未下载任何数据集图像或标注压缩包。** 对 zip 等只做 HTTP HEAD（记录 `Content-Length` 等），不取正文、不计算 SHA-256。未访问、也未改动项目仓库 `xiaominaimoyu/AgeMorph3D` 的 GitHub。本地只读查阅了方案 v3 与仓库文档中已登记的数字，并标明哪些不是本次官方包实测。
- 判定标准（与 K2 / 方案 v3 的「同身份相对回归」一致）：
  1. 同一人在不同年龄有多张观测；
  2. 有可用的人物编号（或等价身份字段）；
  3. 年龄标签能覆盖到 70 岁，最好有正好 70 岁的精确标签；
  4. 可通过官方或原作者入口、按条款取得，限学术非商业使用；
  5. **排除未授权转存**（Hugging Face、Kaggle、HyperAI 等第三方再分发），并说明原因。
- 结论档：「可用」「有条件」「排除」。本文不是法律意见，不代替用户或导师做最终决定。

---

## 0. 结论先行

1. **在「已获准、有身份、精确年龄、覆盖到 70 岁」这组条件同时满足时，目前没有比官方 AgeDB 更省事的公开直链替代。** AgeDB 仍是方案 v3 的首选：官网可申请、人工精确到年的年龄、568 人 / 16,488 张、年龄 1—101 岁。条件是用户或导师用学校邮箱向 `s.moschoglou@imperial.ac.uk` 申请解压密码，并遵守「仅限非商业研究、不得再分发标注或派生数据、仅允许同一组织单一地点内部副本」的条款。
2. **若 AgeDB 密码拿不到或官方包统计后 70 岁端点不足，最接近的合法备选是向 iBUG 填写 KANFace 申请表，而不是 MORPH。** KANFace 有人工身份与精确到年的年龄（0—100 岁），论文写明每人平均约 39 张静图，同一人可出现在多个年龄（示例达 35 个不同年龄），与 AgeDB「每人平均 29 张、每人平均年龄跨度 50.3 年」更接近。建议与 AgeDB 申请并行发起，不必等到 12 月底；是否申请、由谁提交，由用户本人决定。MORPH 非商业 Album 2 虽有身份和精确年龄、上界到 77，但白纸写明照片拍摄于 2003 至 2007 年末，每人跨度最多约 5 年，平均每人仅 4 张、相邻间隔平均 164 天；Table C 最高一档只到「50+」（3,933 张，占 7.1%），没有 ≥70 岁分档。现行 UNCW 产品页只列商业产品，**未见学术版，可得性存疑**。图像来源为执法公开记录照（mugshot），伦理上须由用户和导师权衡。因此 **不把 MORPH 排为优先备选**，仅作为跨度很短、须另行权衡的有条件候补。这一点也影响 BP-5 应急方案的排序。
3. **FG-NET 不能当新的主训练集，也不能当外部盲测。** 它是真正的同人纵向库（82 人、1,002 张，文件名含身份与年龄），但年龄只到 **69 岁，没有正好 70 岁**；原始官方站点已不再提供数据；项目本地已经用过。只可作既有研究的回顾性诊断（与方案 v3 §2-G、数据资源清单一致）。
4. **不能当作 K2 纵向主集替代的常见库：** CACD（官方年龄只到 62，且作者不建议用于年龄估计）；CALFW 是跨龄验证对、年龄多为算法估计；CPLFW 是跨姿态不是跨年龄；UTKFace / FairFace / MegaAge / AFAD / LAGENDA 没有可用于同人回归的身份编号，或年龄不到 70，或只是年龄组/后验分布；Adience 虽有人物标签，但年龄是区间、最老一组为 `60-`。IMDB-WIKI / IMDB-Clean 有身份和可到 70 岁以上的标签，但年龄由拍摄年减出生年得到、噪声大，且要用 IMDB-Clean 的框必须下约 269 GB 原图，方案 v3 已决定本期不采用。
5. **未授权转存一律排除**，包括但不限于 MORPH 的 Hugging Face 条目（如 `treetreesha/morph2`、`wulala1219/morph2`）、`caojingtian1216/imdb-clean-1024`、AgeDB 的任何 HF/Kaggle 镜像、CACD 的第三方 pkl 转存，以及 LAGENDA 的非官方大包再分发。镜像不能代替官方授权。

---

## 1. 对照基准：AgeDB（方案 v3 主候选，不是「新备选」）

| 项 | 内容 | 来源（2026-11-16 访问） |
|---|---|---|
| 官方入口 | https://ibug.doc.ic.ac.uk/resources/agedb/ （亦见 https://www.ibug.doc.ic.ac.uk/resources/agedb/） | iBUG 资源页，HTTP 可达 |
| 申请方式 | Dropbox 下载压缩包；解压密码须发邮件给 `s.moschoglou@imperial.ac.uk`（页面写作 s [dot] moschoglou [at] imperial [dot] ac [dot] uk） | 同上，「You can download the database from here. For the zip password…」 |
| 规模（论文） | 16,488 张，568 人；每人平均 29 张；最小/最大年龄 1 / 101；每人平均年龄跨度 50.3 年 | 官方 PDF：https://www.ibug.doc.ic.ac.uk/media/uploads/documents/agedb.pdf §2 |
| 身份与年龄字段 | 每张图标注 identity、age、gender。官方文件名格式为 `<id>_<name>_<age>_<gender>.jpg`（方案 v3 §4；本次未打开官方包复核文件名） | 论文 §2；方案 v3 |
| 70 岁覆盖 | 年龄上界 101，因此**口径上覆盖 70 岁**。方案 v3 用申请前参考统计写「正好 70 岁 216 张」等数字，并写明须用官方包重计；**这些张数不是本次对官方包的实测，标未核实（官方包）** | 论文年龄范围；方案 v3 §2-A、§4 |
| 许可要点 | 「available for non-commercial research purposes only」；不得复制、出售、交易或为商业目的利用任何标注及派生数据；「not to further copy, publish or distribute any portion of annotations」；例外是同一组织、单一地点的内部副本；可随时终止访问；图像来自互联网，版权不在 iBUG | 官方页条款原文 |
| 官方包大小 | 本次未下载，未做 HEAD（Dropbox 链在「here」，未在未登录情况下跟下载）。方案 v3 预算登记峰值约 0.4 GiB、常驻约 0.2 GiB，为估算 | 方案 v3 §3 |
| 判定 | **有条件可用（当前首选）**：条款与用途匹配本科非商业研究，但必须先取得密码并只用官方包；不得使用任何转存。AgeDB-30 是人脸识别常用验证协议，若用 ArcFace 类模型做身份评价，可能偏乐观（方案 v3 §6） | — |

引用：Moschoglou 等，*AgeDB: the first manually collected, in-the-wild age database*，CVPR Workshop 2017。官方页提供了 BibTeX。

---

## 2. 逐项候选

下列「70 岁」一栏：能从官方或原论文确认年龄上界 ≥70 的，写「覆盖」；能确认没有 70 岁精确标签的，写「无」；张数/人数未公布的，写「未核实」。

### 2.1 FG-NET Aging Database

| 项 | 内容 | 来源（2026-11-16） |
|---|---|---|
| 历史官方入口 | 欧盟 FP5 项目 FG-NET 产出；文献常用 Andreas Lanitis 维护的页面，例如 AFAD 官网参考文献 [1] 所引 `http://sting.cycollege.ac.cy/alanitis/fgnetaging.html`。另有综述说明 2004 年与 MORPH 一同公开 | Panis & Lanitis，*An Overview of Research Activities in Facial Age Estimation Using the FG-NET Aging Database*；AFAD 页面参考文献；Lanitis 等，*Toward automatic simulation of aging effects on face images*，IEEE TPAMI 2002 |
| 本日可达性 | 上述 Cyprus College 地址本机 HTTP 500；`http://www-prima.inrialpes.fr/FGnet/` 同样 500。Yanwei Fu 页写「the original FG-NET website does not provide this data any more」 | 本日本机 HEAD；https://yanweifu.github.io/FG_NET_data/ |
| 常用研究镜像 | https://yanweifu.github.io/FG_NET_data/ ，提供 `FGNET.zip`。作者写明「I donot own this dataset. This dataset is just used for research purpose。」数据来自 Cory (Ke Chen) | 同上 |
| 镜像包大小（HEAD，非下载） | `https://yanweifu.github.io/FG_NET_data/FGNET.zip`：`Content-Length=46221653`（46,221,653 字节），`Last-Modified=Wed, 04 Nov 2026 02:52:00 GMT`（2026-11-04 10:52 UTC+8）。与仓库数据资源清单中本地 manifest 声明的 46,221,653 字节一致 | HTTPS HEAD；`docs/数据资源清单.md` |
| 规模与字段 | 82 人、1,002 张；年龄 **0—69**。文件名如 `078A11.JPG`：第 78 号人、11 岁（`A` 表示 Age）。另有 68 点标注 | Fu 页说明；Panis & Lanitis 综述：「ages ranging between newborns to 69 years old」 |
| 70 岁 | **无正好 70 岁。** 项目本地成年研究子集亦记录为标签 20—69、没有 70（数据资源清单） | 同上 |
| 许可 | 原始官方条款文本本日未能从已失效站点取得，**未核实**。Fu 镜像不是版权人声明，不能代替原始授权。许可证在第三方目录中常被标为 Unknown | Fu 页；本次未找回官方 License 原文 |
| 判定 | **有条件（仅既有回顾，排除作为新主集或盲测）**。真正的同人纵向库，但没有 70 岁端点，体量很小，官方发放渠道已中断；项目已经用过（方案 v3 §2-G）。不建议再从镜像下载一份 | — |

### 2.2 KANFace（iBUG）

| 项 | 内容 | 来源（2026-11-16） |
|---|---|---|
| 官方入口 | https://ibug.doc.ic.ac.uk/resources/kanface/ | iBUG 资源页 |
| 申请 | 「To gain access to the dataset, please visit this fill in the form below。」须在官方页填表，不是公开直链 | 官方页 |
| 规模 | 约 40K 静图与 44K 序列（共约 1,450 万视频帧），**1,045** 人。论文更精确写 41,036 张静图；每人平均约 39 张、约 13 段视频；544 对亲属关系，566,198 个亲属对 | 官方页；Georgopoulos 等，arXiv:[2005.07302](https://arxiv.org/abs/2005.07302)（HTML：[v2](https://arxiv.org/html/2005.07302)）摘要与 §2、Table 1 |
| 身份与年龄 | **人工标注** identity、精确年龄、性别、亲属关系。年龄由出生日期与视频/照片摄制日期相减，精确到年。每人在多个年龄有图像/视频（论文示例同一人 35 个不同年龄） | 论文 §2 |
| 年龄范围与 70 岁 | 官方页与论文均为 **0—100** 岁，**覆盖到 70 岁**。正好 70 岁的张数/人数 **未在页面或论文表中公布，未核实** | 官方页；论文 Figure 1、Table 1 |
| 许可要点 | 「available for research purposes only」；图像和视频来自互联网，版权归原所有者；不得为非研究目的复制、出售或利用标注及派生数据；不得再出版或分发标注，例外为同一组织单一地点内部副本；可随时终止访问 | 官方页条款（与 AgeDB 表述非常接近） |
| 大小 | 含大量视频，官方未公布下载体积，**未核实**。若只申请静图子集，体积仍未知 | — |
| 判定 | **有条件（AgeDB 之外的优先备选）**：与 AgeDB 同属 iBUG、条款同类，且明确是同人多龄、精确年龄、上界到 100，每人平均约 39 张。须填表获准；注意名人偏差，以及与 AgeDB / IMDb 来源可能重叠（未核身份交集）。获准前不要从任何镜像取数据。**建议与 AgeDB 申请并行发起，不必等到 12 月底；申请由用户本人决定和提交。** | — |

### 2.3 MORPH（学术非商业 Album 2 / Non-Commercial Release）

| 项 | 内容 | 来源（2026-11-16） |
|---|---|---|
| 现行产品页 | https://www.uncw.edu/research/innovation/commercialization/technology-portfolio/morph | UNCW Office of Innovation & Commercialization，HTTP 可达 |
| 历史学术入口 | Face Aging Group：文献与 NIST 目录登记 `http://faceaginggroup.com/morph/`（有的写作 https://www.faceaginggroup.com/morph/）。本日本机对 `https://www.faceaginggroup.com/morph/` 的 HEAD **没有返回可用状态行**，站点是否仍开放 **未核实** | NIST Biometric Database Catalog 条目；本机 HEAD |
| 现行页面是否仍提供学术版 | 本日复核产品页正文，只列出 MORPH Multimedia、MultiMediaLite、MORPH 5、MORPH 4。未见 Non-Commercial、Album 2，也未见可免费或按学术协议申请的发放入口。页中「academic」只出现在站点导航（Academic Calendar、Academic Catalogues 等），与数据集许可无关。**现行页面未见学术版，可得性存疑。** | 同上产品页，2026-11-16（UTC+8）阅读 HTML 正文 |
| 申请方式 | 历史上的非商业 Album 2 **不是公开直链**。若用户或导师仍希望询问是否还有学术授权，可联系 Office of Innovation & Commercialization（此前在上级 commercialization 页登记的邮箱为 `oic@uncw.edu`，电话 910-962-2014）。不能把现行产品页理解为仍在发放非商业 Album 2。本文不能代替申请。 | UNCW MORPH 页；https://www.uncw.edu/research/innovation/commercialization/ |
| 非商业版规模（白纸正文，本次已阅读） | 「55,000 unique images of more than 13,000 individuals, spanning from 2003 to late 2007。」表格精确数字为 **55,134 张、13,618 人**；年龄 **16—77**，中位年龄 33；「average number of images per individual is 4」；「average time between photos is 164 days, with the minimum being 1 day and the maximum being 1681 days」（1,681 天约 4.6 年）。整库拍摄窗口为 2003 至 2007 年末，**每人跨度最多约 5 年**。 | https://people.uncw.edu/vetterr/MORPH-NonCommercial-Stats.pdf（315,488 字节；`Last-Modified=Sun, 23 Jan 2011 21:00:50 GMT` = 2011-01-24 05:00 UTC+8）。KANFace 论文 Table 1 亦列 MORPH 2：55,134 / 13,618 / 16—77 |
| 身份与年龄 | 纵向库，同一人有多时相。白纸 Table D 元数据含：Subject Identifier（六位、前导零）、Picture Identifier、Date of Birth、Image Date、Age Difference（距上一张的天数）、Image Filename（`ID_[picture_id][M/F][Age].JPG`）、Race、Gender、Facial Hair Flag、Glasses Flag | 白纸 Table D |
| 十年段分布（Table C） | 最高一档是 **「50+」：3,933 张，占 7.1%**（3,933 / 55,134）。其余：&lt;20 为 7,469；20–29 为 16,325；30–39 为 15,357；40–49 为 12,050。**没有 ≥70 岁分档**，因此不能从白纸得出正好 70 岁或 ≥70 的张数。 | 白纸 Table C（行列合计已复核为 55,134） |
| 性别与族裔（Table A） | 男性 46,645 张，占 **84.6%**（46,645 / 55,134）；African 42,589 张，占 **77.2%**（42,589 / 55,134） | 白纸 Table A |
| 70 岁端点 | 年龄上界虽写到 77，70—77 岁的样本若存在，也只会落在「50+」这一档里，**张数未公布**。对需要「精确 70 岁端点、同人长跨度」的 K2 而言，不能把「上界 77」写成可用的 70 岁覆盖。 | 白纸开篇年龄范围与 Table C |
| 现行更大版本 | 产品页：MORPH 5 约 521,000 张 / 106,000 人，年龄 18—89；MORPH 4 约 402,000 张 / 67,600 人。这些是产品描述，许可与价格未在页面公开，**不能当作可免费学术下载** | UNCW MORPH 页 |
| 许可 | 历史上的非商业发放须经 UNCW 授权。**具体非商业协议原文须在申请时取得，本次未拿到签字文本。** 禁止使用 HF 转存（见 §3）。 | UNCW 页；白纸 URL |
| 图像来源与伦理 | Ricanek & Tesafaye，*MORPH: A longitudinal image database of normal adult age-progression*，IEEE FG 2006（doi:10.1109/fgr.2006.78）的**全文本日未能取得**（IEEE stamp 接口返回 HTTP 418；KIT BeFIT 页上的「PDF」链指向该付费接口）。该文公开摘要写的是「longitudinal spans from a few months to over twenty years」【未核实】，与后来非商业 Album 2（2003—2007，最多约 5 年）不是同一批规模；AgeDB 论文 Table 2 将 2006 年的 MORPH 记为 1,724 张 / 464 人，应视为早期 Album 1。关于 **Album 2** 的来源，后来的公开论文写明：数据集「assembled in the mid-2000s from public records」，「consists of mugshot images」，作者「curated a version of MORPH Album 2」（Krishnapriya 等，CVPRW 2019，arXiv:1904.07325 §3，参考文献 [11] 指向 2006 年原文）。据此，Album 2 图像是执法机构公开记录中的登记照（booking / mugshot）【推断，由 public records 与 mugshot 两词得出】。将其用于本科毕业设计，除许可条款外还有伦理与数据来源争议，**须由用户和导师权衡**。这一点不是法律意见。 | 2006 摘要：https://doi.org/10.1109/fgr.2006.78 ；2019 论文：https://arxiv.org/abs/1904.07325 、https://arxiv.org/pdf/1904.07325 |
| 判定 | **有条件，但不作为优先备选。** 虽有身份和精确年龄，但每人跨度不到 5 年、十年段最高档只到 50+、现行页面未见学术版、图像为执法登记照。禁止使用 HF 转存。 | — |

### 2.4 CACD（Cross-Age Celebrity Dataset）

| 项 | 内容 | 来源（2026-11-16） |
|---|---|---|
| 官方入口 | http://bcsiriuschen.github.io/CARC/ | 作者项目页，可达 |
| 获取 | 官方提供元数据+特征（页上写 4.4G）、仅元数据（817K）、OpenCV 裁剪人脸图（3.5G）、16 点位置（24M）、以及 CACD-VS 验证对（198M）。学术用途，页面直接给下载链，未见额外注册表 | 同上 Dataset 节 |
| 规模与字段 | 163,446 张，2,000 名名人；结构含 `identity`（名人编号）、`name`、`birth`、`age`（估计）、`year` | 官方页 |
| 年龄与 70 岁 | 用搜索年份（2004—2013）减出生年得到估计年龄；官方与论文均写年龄 **16—62**。**达不到 70 岁端点** | 官方页摘要与 Dataset 节；Chen 等，ECCV 2014 |
| 标签质量 | 作者写明：年份标签粗糙，**「we do not suggest to apply it to age-estimation works」**；rank>5 的名人含噪声，不应用于评价 | 官方页 Notes |
| 许可 | 「made available for academic research purpose only」；图像来自互联网，版权归原所有者；若权利人要求可删除（`bcsiriuschen@gmail.com`） | 官方页 Dataset 节开头 |
| 判定 | **排除作为本课题 20—70 岁年龄方向主集**（没有 70 岁；作者不建议用于年龄估计）。若只做跨龄识别对照，须另冻协议，并只用官方入口，不用第三方 pkl 转存（方案 v3 §5 已禁用 `caojingtian1216/CACD/data/cada_train.pkl`） | — |

### 2.5 CALFW 与 CPLFW

**CALFW**（Cross-Age LFW）官方页：http://www.whdeng.cn/CALFW/index.html 。在 LFW 身份上挑选约 3,000 对有年龄差的正对和相应负对，保持 LFW 的 6,000 对、十折协议。年龄差来自「在网上尽量找年龄差距大的照片」，再用年龄估计算法估计年龄后挑选（论文 arXiv:[1708.08197](https://arxiv.org/abs/1708.08197)）。这是**人脸验证基准**，不是按精确岁数组织的同人年龄回归库；没有官方公布的正好 70 岁计数。页面要求引用论文，**未写完整的数据集许可条款**（许可文本未核实）。图像来自互联网。

**判定：排除作为年龄方向训练主集。** 身份字段存在（沿用 LFW），但不能提供本课题所需的精确 70 岁端点与按岁回归监督。

**CPLFW**（Cross-Pose LFW）官方页：http://www.whdeng.cn/CPLFW/index.html 。任务是**跨姿态**验证，不是跨年龄。

**判定：排除**（与年龄方向需求不符）。

### 2.6 LAG（Large Age-Gap）

| 项 | 内容 | 来源（2026-11-16） |
|---|---|---|
| 官方入口 | http://www.ivl.disco.unimib.it/activities/large-age-gap-face-verification/ | 米兰比可卡大学 Imaging and Vision Laboratory，可达 |
| 获取 | 页面提供两个 zip：100×100（70MB）、200×200（215MB）。未见注册表。本次未对 zip 做 HEAD | 官方页 |
| 规模 | 1,010 名名人，3,828 张；「For each identity at least one child/young image and one adult/old image are present」 | 官方页 |
| 身份与年龄 | 有身份（名人）；年龄表述为 child/young 对 adult/old，**未在页面给出精确到年的年龄字段，也未给出是否覆盖 70 岁** | 官方页；Bianco，PRL 2017，doi:10.1016/j.patrec.2017.03.006 |
| 许可 | 页面只要求引用指定 BibTeX，**没有单独的 License Agreement。许可范围未核实**。图像为名人公开照片 | 官方页 |
| 判定 | **排除作为主集（信息不足且不像精确 70 岁回归库）**；若将来只做大龄差验证对照，须先向作者确认条款与年龄标注精度 | — |

### 2.7 UTKFace

| 项 | 内容 | 来源（2026-11-16） |
|---|---|---|
| 官方入口 | https://susanqq.github.io/UTKFace/ | AICIP / Zhang 等，可达 |
| 获取 | 野外图 ZIP（页上写 1.3GB）、对齐裁剪（107MB）、68 点（12MB）。页上可下，未见申请表。本次未 HEAD、未下载 | 官方页 Datasets 表 |
| 规模与字段 | 20,000+ 张，年龄 0—116，另有性别与种族。文件名 `[age]_[gender]_[race]_[date&time].jpg`。时间戳是「图像被收入 UTKFace 的时间」，**不是人物编号** | 官方页 Labels |
| 同人关系 | **没有 subject / identity 字段。** 不能做同身份多龄回归（与数据资源清单第 27、37 行一致） | 官方页；项目文档 |
| 70 岁 | 标签范围到 116，可出现 70 岁**单张**标签，但不是纵向同人库 | — |
| 许可 | 「avaiable for non-commercial research purposes only」；图像来自互联网，版权归原所有者；年龄/性别/种族由 DEX 估计后再经人工复核 | 官方页 License Claim |
| 判定 | **排除作为 K2 纵向主集。** 最多在另冻的横断面/质量协议下作可选工程资源，且须披露 DEX 来源（与 SAM/IMDB-WIKI 可能有估计器重叠） | — |

### 2.8 IMDB-WIKI 与 IMDB-Clean

**IMDB-WIKI** 官方页：https://data.vision.ee.ethz.ch/cvl/rrothe/imdb-wiki/

- 规模：IMDb 20,284 名名人的 460,723 张 + Wikipedia 62,328 张，合计 **523,051** 张。元数据含 `name`、`dob`、`photo_taken`、IMDb 部分另有 `celeb_names` / `celeb_id`。年龄用拍摄年（假定年中）减出生日期计算。作者写明不能保证年龄准确（时间戳错误、电影周期等）。
- 年龄范围：官方输出层按 0—100 岁设计；KANFace Table 1 亦记 IMDB-WIKI 为 0—100。**覆盖到 70 岁**；正好 70 岁张数官网未公布，**未核实**。
- 许可（官方页 License 节原文）：「Please notice that this dataset is made available for academic research purpose only. All the images are collected from the Internet, and the copyright belongs to the original owners. …」
- 体积：官方列出 IMDb 原图分 10 个 tar，各约 24—29 GB（页上文字；与方案 v3「约 269 GB」一致的量级）。另提供 cropped faces（页上写 7 GB）及 Wikipedia 包。本次未逐个 HEAD。
- 数据泄漏：DEX 在 IMDB-WIKI 上训练，SAM 的年龄损失又用在 FFHQ-Aging 上微调过的 DEX（方案 v3 §6）。用该库评价 SAM 会偏乐观。

**IMDB-Clean** 官方仓库：https://github.com/yiminglin-ai/imdb-clean （默认分支 `master`，GitHub 许可 SPDX：MIT）

- README Disclaimer：「We only provide new annotations under MIT licence. The images are from the IMDB-WIKI dataset. We do not own any of these images. Please refer to their website for the licence to use these images。」
- 用法：`run_all.sh` 从 IMDB-WIKI **官方原图** 生成清理后的裁剪与划分。方案 v3 已核实：框在原图坐标系，原图约 269 GB；不能用 `imdb_crop` 代替（约 36% 对不上）。HF `caojingtian1216/imdb-clean-1024` 为非官方再分发，不采用。
- 方案 v3 登记：285,946 条，年龄 1—95；训练/验证有 5,303 人重叠。这些是既有核对，本次未重新下载 CSV 复核。

**判定：有条件，但本期按方案 v3「不采用」。** 有身份、年龄可到 70 以上，官方学术条款明确；然而标签噪声大、原图远超预算、并与 DEX/SAM 存在评价泄漏。只有在 AgeDB 与 KANFace 都不可用、且用户明确接受上述限制时，才考虑「imdb_crop + 原始带噪标签」的退路，并须在论文中如实写噪声。MORPH 因跨度短、可得性存疑和来源争议，也不宜插到这条退路之前。

### 2.9 MegaAge 与 MegaAge-Asian

官方页：https://mmlab.ie.cuhk.edu.hk/projects/MegaAge/

- 规模：MegaAge **41,941** 张，标注为年龄**后验分布**；MegaAge-Asian **40,000** 张亚洲人脸。论文（含勘误附录）写年龄 **0—70**。图像随机取自 MegaFace 与 YFCC100M，用 FG-NET 作参考做两两比较后形成后验（arXiv:[1708.09687](https://arxiv.org/abs/1708.09687)）。
- 身份：官方说明是大规模面部年龄库，**没有把「同一人多个年龄」作为组织方式，也未提供用于纵向回归的 subject 字段**。来源 MegaFace 本身是识别库，但 MegaAge 发放的是带后验的人脸图像集合，不能直接当作 AgeDB 式同人序列。
- 许可（官方页 Note，须同意才能下载）：仅限非商业研究；图像来自互联网，产权不在 MMLAB/SenseTime；不得为商业目的利用图像或派生数据；不得再复制、出版或分发，例外为同一组织单一地点内部副本；可随时终止；发表须引用 Zhang 等 BMVC 2017。
- 70 岁：标签设计到 70，但是后验/估计，不是户籍式精确岁，也不是同人端点。

**判定：排除作为纵向主集。** 条款允许学术使用，但缺身份纵向结构。

### 2.10 Adience

官方页：https://talhassner.github.io/home/projects/Adience/Adience-data.html  
许可原文：https://talhassner.github.io/home/projects/Adience/LICENSE.txt

- 26,580 张，**2,284** 人；**有 Subject labels**；8 个年龄组：0–2, 4–6, 8–13, 15–20, 25–32, 38–43, 48–53，**60-**。图像来自 Flickr 公开相册，页面写原图作者以 Creative Commons 发布。下载前须在页面登记，通过 FTP（`agas.openu.ac.il` / `http://www.cslab.openu.ac.il/download/`）取得。页上体积：faces.tar.gz 936M，aligned.tar.gz 1.9G。
- 许可关键句：授予有限、非独占、免版税、不可再许可、不可转让、**可撤销**的许可，「download, access and use … for your research purposes only」；各图像版权仍归原作者。
- 70 岁：最老一组是 `60-`，**不是精确 70 岁标签**，也无法稳定筛出正好 70 岁。

**判定：排除作为精确 20—70 岁方向主集。** 虽有人物编号，但是年龄组监督；若改做区间任务，必须另冻协议。

### 2.11 FairFace

官方仓库 README：https://github.com/joojs/fairface/blob/master/README.md（模型与数据链也指向 https://github.com/dchen236/FairFace）

- 用途是种族、性别、年龄属性的平衡集，用于偏差测量。标签为年龄**组**，**未见人物身份字段**，也不是同人多龄纵向库。
- 许可：README 写 **CC BY 4.0**。
- 论文：Karkkainen & Joo，WACV 2021。

**判定：排除**（无身份纵向结构，年龄非精确岁）。

### 2.12 AFAD（Asian Face Age Dataset）

官方说明（GitHub Pages 源码，站点 https://afad-dataset.github.io/ 本日 WebFetch 为 404，故改读仓库源文件）：https://raw.githubusercontent.com/afad-dataset/afad-dataset.github.io/master/index.html

- 作者：Zhenxing Niu, Mo Zhou, Xinbo Gao, Gang Hua。论文：*Ordinal Regression with a Multiple Output CNN for Age Estimation*，CVPR 2016。
- 规模：**164,432** 张（女 63,680，男 100,752），年龄 **15—40**。另有 AFAD-Lite（约 60K，22 个连续年龄，同为 15—40）。下载：`https://github.com/afad-dataset/tarball` 与 `tarball-lite`。
- 组织方式按年龄与性别；简介只提 age 与 gender labels，**未见 subject / identity 字段**。自拍来自人人网。
- 许可：「Please notice that this dataset is made available for academic research purpose only.」无更长的法律文本。
- 70 岁：上界 40，**不覆盖**。

**判定：排除**（无 70 岁，且不是已说明的同人纵向库）。

### 2.13 LFW 的年龄变体

- **LFW 本身**没有官方精确年龄或同人年龄序列协议，不能当年龄方向训练集。
- **CALFW** 已在 §2.5 排除（验证对 + 估计年龄）。
- CACD 元数据有 `lfw` 标记（是否与 LFW 名人重叠），这不是 LFW 官方年龄集。
- 第三方给 LFW 后贴的年龄估计，不是原作者发放，**不得当作已获准的纵向真值**。

**判定：排除作为 K2 替代。**

### 2.14 LAGENDA（MiVOLO 配套）

官方页：https://wildchlamydia.github.io/lagenda/

- 来自 Open Images 的 67,159 张图、84,192 个个体，年龄 0—95；强调各年龄段平衡，**「The license for this dataset is CC 2.0」**（页面原文如此，未写全称是不是 CC BY 2.0）。标注为年龄估计/性别，格式是每张图上的人脸框；`age=-1` 表示该框没有年龄真值，只供检测。方案 v3 已记录官方全表中 age=-1 占 75.8%。
- **没有把「同一人多个年龄」作为身份纵向字段发布。** 页面写含极少名人。
- 官方提供下载按钮；方案 v3 记载某非官方转存约 49.5 GiB，超出预算，**不得从转存获取**。

**判定：排除作为纵向主集**（无身份序列；大量无年龄框；体积大）。CC 具体版本以官方文件为准，页面「CC 2.0」表述不完整。

### 2.15 三维 / 其他纵向人脸库（简表）

| 资源 | 官方入口 | 要点 | 判定 |
|---|---|---|---|
| FaceScape | https://nju-3dv.github.io/projects/FaceScape/ | 847 人 × 20 种表情，共 16,940 个模型（约 90% 公开）；有年龄与性别名单；拓扑统一的三维模型。须填写许可协议发到 `nju3dv@nju.edu.cn`，本科生/研究生须由导师申请。关键条款：仅限内部非商业研究，禁止商业；论文中只能使用 publishable list 中的肖像。TU Models 约 120GB。这是**同一采集时段的多表情**，不是多年跟踪的年龄纵向；拓扑也不是本项目的 BFM | **排除作为年龄方向数据**（可另作三维重建资料，须单独申请，且与 3DDFA_V2+BFM 路线不兼容） |
| 儿童三维纵向 | 如 PLOS One 等研究中的 7—17 岁年度 3D 扫描 | 只覆盖未成年人，不到 20—70 | **排除** |
| UvA-NEMO 等微笑/亲属视频库 | KANFace Table 1 记 400 人、8—76 岁、含部分亲属 | 本日未逐一打开其官方条款与发放方式，**未核实**是否可申请、是否有精确年龄序列 | **未核实，不列入可用** |

FaceScape 许可摘要来源：项目页 Data Access 与「NO COMMERCIAL USE」「RESTRICTED USE IN RESEARCH」要点；完整协议 PDF：https://nju-3dv.github.io/projects/FaceScape/static/license/LicenseAgreement_FaceScape.pdf（本次阅读了项目页转述，未把 PDF 当数据集下载）。

---

## 3. 未授权转存（一律排除）

下列途径**不能**代替官方授权，即使文件能打开、许可证栏看起来「宽松」也不行。原因：原条款普遍禁止再分发图像或标注；转存者不是权利人；有的还被改标成与原文冲突的许可证。

| 转存或非正式副本 | 为什么排除 |
|---|---|
| AgeDB 的 Hugging Face / Kaggle 等镜像 | 官方禁止再分发标注；解压密码须向作者申请。方案 v3 已要求不保留、不再下载任何转存；用户已同意删除本地 `agedb.parquet` |
| `caojingtian1216/imdb-clean-1024` | IMDB-Clean 作者只发放新标注（MIT），图像须按 IMDB-WIKI 官方条款从原址获取。该 HF 包是非官方再分发（方案 v3 §2-B） |
| `treetreesha/morph2`、`wulala1219/morph2` 等 HF 上的 MORPH II | MORPH 须经 UNCW 授权；方案 v3 §6 已定为未授权转存 |
| `caojingtian1216/CACD/data/cada_train.pkl` 等 CACD 转存 | 应用官方项目页；方案 v3 §5 因 pickle 安全风险也不使用 |
| HyperAI、OpenDataLab、Kaggle 上的 FG-NET / CACD / 其他人脸年龄包 | 第三方汇总，不能提供原许可，更不能改写许可证 |
| LAGENDA 的非官方大包再分发（如方案 v3 提到的 n0kovo） | 即使官方采用较宽松的 CC 表述，仍应走官方页；转存体积与完整性无官方保证 |
| Yanwei Fu 的 FG-NET 镜像 | **不是偷偷爬取的商业站**，作者公开声明不拥有数据、仅供研究，且因原站停服而被广泛引用。但它**仍然不是原始授权文本**，也不得再二次分发。本项目本地已有副本，**不必再下** |

Internet Archive 或个人网盘只可用于核验历史页面，不得当作发放源。

---

## 4. 对照总表与使用建议

| 数据集 | 官方入口 | 须申请/注册 | 身份字段 | 年龄 | 覆盖 70 岁 | 约计规模 | 许可（摘要） | 判定 |
|---|---|---|---|---|---|---|---|---|
| AgeDB | iBUG 资源页 | 是（邮件索取密码） | 有（id + 姓名） | 精确到年，1—101；每人平均跨度 50.3 年、平均 29 张 | 是（正好 70 岁张数须官方包重计） | 16,488 / 568 | 非商业研究；禁再分发标注 | **有条件，首选** |
| KANFace | iBUG 资源页 | 是（网上表格） | 有（人工） | 精确到年，0—100；每人平均约 39 张 | 是（正好 70 岁张数未公布） | 41,036 静图 / 1,045；另有视频 | 仅研究；禁再分发标注 | **有条件，首选备选**（建议与 AgeDB 并行申请） |
| MORPH 非商业 Album 2 | 历史 Face Aging Group；现行 UNCW 产品页未见学术版 | 是（授权；可得性存疑） | 有 | 精确，16—77；拍摄于 2003—2007 年末，每人跨度最多约 5 年，平均 4 张、间隔 164 天 | 上界 77，但 Table C 最高档仅 50+（3,933 张，7.1%），无 ≥70 分档 | 55,134 / 13,618 | 须官方协议；禁止转存；执法登记照，伦理须权衡 | **有条件，非优先候补** |
| FG-NET | 原站已失效；Fu 研究镜像 | 原授权未核实 | 有（文件名编号） | 精确，0—69 | **无** | 1,002 / 82；zip 46,221,653 B | 原始条款未核实 | **仅既有回顾** |
| IMDB-WIKI | ETH CVL 官方页 | 否（直链） | 有（celeb_id / name） | 拍摄年−出生年，噪声大，0—100 | 是（张数未核实） | 523,051 | 仅学术研究；版权归原图所有者 | **有条件，本期不采用** |
| IMDB-Clean | GitHub 官方标注 + 须配 WIKI 原图 | 标注公开；原图同上 | 有 | 清理后约 1—95 | 是 | 285,946（v3） | 标注 MIT；图像仍 WIKI 条款 | **有条件，本期不采用** |
| CACD | 作者项目页 | 否 | 有 | 粗估，16—62 | **无** | 163,446 / 2,000；裁剪约 3.5G | 仅学术研究 | **排除（主集）** |
| CALFW | whdeng.cn | 否 | 有（LFW 身份） | 估计年龄差，验证对 | 未作为精确端点提供 | 6,000 对 | 条款不完整，未核实 | **排除（主集）** |
| CPLFW | whdeng.cn | 否 | 有 | 不适用（姿态） | 无 | 验证对 | 未写完整许可 | **排除** |
| LAG | UNIMIB IVL | 否 | 有（名人） | 年轻/年长对，精度未核实 | 未核实 | 3,828 / 1,010 | 仅见引用要求 | **排除（主集）** |
| UTKFace | 官网 | 否 | **无** | 0—116，DEX+人工 | 仅有单张标签 | 20k+；约 1.3GB/107MB | 非商业研究 | **排除（纵向）** |
| MegaAge / Asian | CUHK MMLab | 同意条款后下载 | **无纵向 ID** | 后验，0—70 | 非同人端点 | 41,941 / 40,000 | 非商业；禁再分发 | **排除（纵向）** |
| Adience | Hassner 项目页 | 须登记 | 有 | 8 个年龄组，最老 60- | 无精确 70 | 26,580 / 2,284 | 可撤销的研究许可 | **排除（精确岁）** |
| FairFace | GitHub | 否 | **无** | 年龄组 | 无 | 训练+验证（Drive） | CC BY 4.0 | **排除** |
| AFAD | afad-dataset 说明页/仓库 | 否 | **未见** | 15—40 | **无** | 164,432 | 仅学术研究 | **排除** |
| LAGENDA | 官方项目页 | 否 | **无纵向 ID** | 0—95，大量 −1 | 非同人端点 | 67,159 图 | 页面写 CC 2.0 | **排除（纵向）** |
| FaceScape | 南大 3DV 项目页 | 是（协议+导师） | 有（采集 ID） | 名单含年龄，非多年跟踪 | 未核实 | 847×20；模型约 120GB | 非商业；肖像发表受限 | **排除（年龄方向）** |

**给导师与用户的建议（非决定）：**

1. 继续按方案 v3 申请 **AgeDB 官方密码**，拿到后只在本机统计 20—70 岁与正好 70 岁，用官方文件名复核，不再使用任何转存。
2. **建议同时、尽快在 iBUG 填写 KANFace 申请，不必等到 12 月底。** 是否申请、由谁用学校身份提交，由用户本人决定。不要从网盘或 HF 预取。
3. **不要把 MORPH 当作 AgeDB 拿不到时的优先备选。** 白纸已证实每人跨度不到 5 年、十年段最高档只到 50+；现行产品页未见学术版，可得性存疑；图像为执法登记照，须由用户和导师权衡伦理后再决定是否询问 UNCW OIC（`oic@uncw.edu`）。即便询问，也不要从 HF 预取。
4. **FG-NET** 保持本地既有副本，只作回顾，不再下载，也不写进「新的外部测试集」。
5. 不要用 CACD、UTKFace、MegaAge、Adience、FairFace、AFAD、CALFW/CPLFW、LAGENDA 替换 K2 的纵向含义。
6. IMDB 路线仅作为预算与泄漏都可接受时的书面退路，本期不下载。

---

## 5. 未核实事项

1. AgeDB 官方压缩包的实测字节数、SHA-256，以及正好 70 岁的张数/人数（方案 v3 的 216 张等来自申请前参考统计，须官方包重计）。
2. 现行 UNCW 产品页是否会再次出现非商业 Album 2 或明确的学术授权通道（本日未见）；MORPH 4/5 的学术价格与协议全文；`faceaginggroup.com` 本日是否可访问。Ricanek & Tesafaye（FG 2006）论文正文本日未能从 IEEE/ACM 取得，其中是否自行写明「执法登记照」未核到原文。白纸 Table C 没有 ≥70 岁分档，**不再把无法从白纸核实的 ≥70 张数列为待查项**。
3. KANFace 正好 70 岁的张数/人数、下载包体积、表格提交后的审核周期；与 AgeDB 的身份重叠。
4. FG-NET 原始官方 License 全文；历史官方站本日均不可达。
5. IMDB-WIKI / IMDB-Clean 中正好 70 岁的张数；各 tar 的本次 HEAD 逐包字节数（页上已有分卷约 24—29 GB 的文字）。
6. LAG 是否有精确年龄、是否覆盖 70 岁，以及完整许可文本。
7. CALFW/CPLFW 的完整数据集许可条款。
8. LAGENDA 页面「CC 2.0」的准确许可证全称与法律文本。
9. AFAD 官网 https://afad-dataset.github.io/ 本日 404，说明改从仓库 `index.html` 读取；是否另有仍在线的镜像页，未再追。
10. FaceScape 受试者年龄是否包含 70 岁；儿童三维纵向库的发放条款（已因年龄范围排除，未深挖）。
11. UvA-NEMO 及其他未逐页打开的亲属/表情库的官方条款与可申请性。
12. 第三方目录中关于各库「体积」的数字，凡未经本次 HEAD 或官方页面明文给出的，均不作为实测。

---

## 6. 来源列表（均于 2026-11-16、UTC+8 访问）

官方页面与条款：

- https://ibug.doc.ic.ac.uk/resources/agedb/ — AgeDB 条款、申请邮箱
- https://www.ibug.doc.ic.ac.uk/media/uploads/documents/agedb.pdf — AgeDB 论文（16,488 / 568 / 1—101）
- https://ibug.doc.ic.ac.uk/resources/kanface/ — KANFace 条款与申请说明
- https://www.uncw.edu/research/innovation/commercialization/technology-portfolio/morph — MORPH 现行产品页
- https://www.uncw.edu/research/innovation/commercialization/ — OIC 联系方式 `oic@uncw.edu`
- https://people.uncw.edu/vetterr/MORPH-NonCommercial-Stats.pdf — 非商业版统计白纸（本次阅读正文，315,488 字节）
- http://bcsiriuschen.github.io/CARC/ — CACD 官方页（16—62，学术研究，不建议用于年龄估计）
- http://www.whdeng.cn/CALFW/index.html 、 http://www.whdeng.cn/CPLFW/index.html
- http://www.ivl.disco.unimib.it/activities/large-age-gap-face-verification/ — LAG
- https://susanqq.github.io/UTKFace/ — UTKFace 格式与非商业条款
- https://data.vision.ee.ethz.ch/cvl/rrothe/imdb-wiki/ — IMDB-WIKI 规模、字段、License 原文
- https://github.com/yiminglin-ai/imdb-clean — IMDB-Clean 官方标注仓库（MIT 仅覆盖新标注）
- https://raw.githubusercontent.com/yiminglin-ai/imdb-clean/master/README.md
- https://mmlab.ie.cuhk.edu.hk/projects/MegaAge/ — MegaAge 条款与规模
- https://talhassner.github.io/home/projects/Adience/Adience-data.html 与 LICENSE.txt
- https://github.com/joojs/fairface/blob/master/README.md — FairFace CC BY 4.0
- https://raw.githubusercontent.com/afad-dataset/afad-dataset.github.io/master/index.html — AFAD 说明（15—40，仅学术）
- https://wildchlamydia.github.io/lagenda/ — LAGENDA
- https://nju-3dv.github.io/projects/FaceScape/ — FaceScape 获取与非商业要点
- https://yanweifu.github.io/FG_NET_data/ — FG-NET 研究镜像说明
- https://yanweifu.github.io/FG_NET_data/FGNET.zip — 仅 HEAD，46,221,653 字节

论文与综述：

- https://arxiv.org/abs/2005.07302 — KANFace
- https://arxiv.org/abs/1708.08197 — CALFW
- https://arxiv.org/abs/1708.09687 — MegaAge（0—70，后验标注）
- https://arxiv.org/abs/2106.11145 — FP-Age / IMDB-Clean
- https://doi.org/10.1109/fgr.2006.78 — Ricanek & Tesafaye，FG 2006（本次只核到公开摘要，全文未取得）
- https://arxiv.org/abs/1904.07325 、https://arxiv.org/pdf/1904.07325 — Krishnapriya 等，CVPRW 2019（Album 2 为 public records / mugshot images）
- Lanitis 等，TPAMI 2002（FG-NET）；Chen 等，ECCV 2014（CACD）；Niu 等，CVPR 2016（AFAD）；Bianco，PRL 2017（LAG）

本项目已有文档（只读）：

- `/workspace/AgeMorph3D_数据集方案_v3.md`
- `/workspace/AgeMorph3D/docs/数据资源清单.md`
- `/workspace/AgeMorph3D_后续任务规划_v2.md` RD-4 行

---

## 7. 修订记录（2026-11-16，UTC+8）

据 Sentinel SN-2 对 RD-4 的 FAIL（1 条 MAJOR、3 条 MINOR）修订。本次打开并阅读了 MORPH 非商业白纸正文，以及 AgeDB 官方 PDF、KANFace arXiv:2005.07302 与 Krishnapriya 等 CVPRW 2019（arXiv:1904.07325）。未下载任何数据集图像或标注包，未改动项目 GitHub。

- **MAJOR：** 不再把 MORPH 排为「AgeDB 拿不到时的优先备选」。白纸证实拍摄于 2003—2007 年末、每人跨度最多约 5 年、平均 4 张、间隔 164 天；Table C 最高档为 50+（3,933 张，7.1%），无 ≥70 分档；男性 84.6%、African 77.2%。AgeDB 论文 §2 写明每人平均年龄跨度 50.3 年、平均 29 张；KANFace 论文写明每人平均约 39 张。§0 第 2 条、§2.2、§4 表与建议已改为 KANFace 在前。§5 第 2 条删除「无法核实的 ≥70 岁张数」待查项。
- **MINOR 1：** 写明现行 UNCW 产品页只列 MORPH 4/5 等商业产品，「现行页面未见学术版，可得性存疑」。
- **MINOR 2：** 补充执法登记照的来源与伦理说明，并如实写明 2006 年 FG 论文全文本日未取得，Album 2 的 mugshot / public records 表述核自 2019 年公开论文。
- **MINOR 3：** 建议 KANFace 与 AgeDB 申请并行发起，不必等到 12 月底；申请由用户本人决定和提交。
- 可选整理（复审通过后）：对调 §2.2 与 §2.3，使 KANFace 写在 MORPH 之前；将 2006 年摘要短语标为【未核实】，将「执法机构登记照」标为【推断】。
