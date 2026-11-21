# RD-3 AFLW / AFLW2000-3D 许可与获取核查

- 任务：按《AgeMorph3D 后续任务规划 v2》RD-3，核查原始 AFLW 与 AFLW2000-3D 的许可条款、官方获取途径、是否需要注册，以及可核验的包装大小。
- 访问日期：2026-11-16（UTC+8 / Asia/Shanghai）。下文凡未另标时区的日期，均为此日或此日前的来源日期。
- 范围限制：只做调研。未下载任何数据集或 zip 包（允许对官方 URL 做 HEAD / 记录 Content-Length；Google Drive 只读取了预览页元数据，未跟随 `export=download`）。未访问、也未改动项目仓库 `xiaominaimoyu/AgeMorph3D` 的 GitHub。
- 方法：重试 CBSR 官方页与官方 zip；查阅 TU Graz AFLW 官方页与申请表、3DDFA / 3DDFA_V2 README、朱翔昱个人主页、论文与补充材料、TensorFlow Datasets 目录与构建脚本；用 Internet Archive CDX（元数据，不是下载）核验历史官方包长度；标注未授权转存。
- **修订说明（SN-2 MINOR 就地修正，不必再送审）：** 2026-11-16（UTC+8 / Asia/Shanghai）。全文访问日期与已换算的服务器/存档时间统一改为 UTC+8 / Asia/Shanghai 标注。补充：3DDFA 提供的 `test.data.zip` 本身就是 AFLW 裁剪图的再分发，同样受 AFLW 非商业、不得再分发条款约束。本次写入时已删除本任务留下的网页临时文件。 2026-11-16 稍后补正：原「TPAMI, 2017, 41(1)」已改为纸刊年 2019（Crossref 10.1109/TPAMI.2017.2778152）。 再补一句：2017 是 IEEE Early Access 在线提前发表的纪年，不是投稿/接受记录年（Crossref `published-online` 为空，`created` 为 2017-11-28）。

---

## 0. 五条结论

1. **原始 AFLW** 的官方入口是格拉茨工业大学 ICG 页面。条款原文在该页「License Agreement」：仅限非商业研究；Flickr 图像所有权不在校方，须遵守图片权利人及 Yahoo 使用条款，并禁止对图像及其派生数据做任何商业性复制或利用；除同一组织、单一地点的内部副本外，不得再复制、出版或分发数据库的任何部分；发表须引用指定论文；申请者所属机构将被列为用户。获取不是公开直链，必须通过官方申请表，需要注册/申请。官方包装大小未在页面公布，申请表之后才可能提供下载，本次无法对官方包做 HEAD，**大小仍为未核实**。
2. **AFLW2000-3D** 是朱翔昱等在 3DDFA 工作中，为前 2000 个 AFLW 样本拟合的三维人脸及对应 68 点标记，用于三维人脸对齐评测。历史官方入口是 CBSR 项目页及其 zip：`http://www.cbsr.ia.ac.cn/users/xiangyuzhu/projects/3DDFA/main.htm` 与 `.../Database/AFLW2000-3D.zip`。2026-11-16 对这两个 HTTP 地址的 HEAD/GET 均为 **500、Content-Length: 0**；HTTPS 握手失败。因此**本次未能从官方服务器测得 Content-Length**。
3. 替代官方入口方面：第一作者当前主页把 CVPR 2016 论文旁的「AFLW2000-3D」链到作者 Google Drive 上的 `AFLW2000-3D.zip`（预览页标题与 `itemprop` 均为该文件名，`application/zip`，未被标记为回收站）。该预览页元数据中的大小字段为 **87,413,900 字节（合 83.36 MiB）**——这是页面元数据，不是官方 CBSR 服务器的直播 HEAD，也不是本次对文件正文的校验。TensorFlow Datasets 目录写的 Download size `83.36 MiB` 与该数字一致，但其构建脚本仍指向已宕机的 CBSR zip，TFDS 本身不是许可授权，也不是 CBSR 不可用时的替代发放渠道。Internet Archive CDX 记录该官方 zip 历史捕获长度为 87,076,467 字节（2023-03-20）和 87,110,961 字节（2026-04-05），同属存档长度而非直播 HEAD。
4. **未找到 AFLW2000-3D 的独立许可文本。** CBSR 历史页面与作者主页均只描述数据用途，没有单独的 License Agreement。3DDFA / 3DDFA_V2 源码为 MIT，不覆盖数据。cleardusk/3DDFA#221（2022-10-28 提出，至本次访问仍为 open、无回复）正是在问 300W-LP 与 AFLW2000-3D 的许可是否等同于 300-W / AFLW。图像来自 AFLW 前 2000 个样本，因此 TU Graz 条款中的非商业限制与「不得再分发任何部分」至少约束这些图像；CBSR/作者是否另有授权对外发放带三维标注的子集，**未核实**。3DDFA README 中的 `test.data.zip`（作者自述约 151M，裁剪后的 AFLW 与 AFLW2000-3D 测试图）**不能**代替官方 `AFLW2000-3D.zip`。
5. **Kaggle、HyperAI 等第三方转存不得作为获取途径。** 其中一份 Kaggle 副本还把许可证标成 Apache 2.0，与 AFLW 官方条款明显冲突。本次未发现突出的 Hugging Face Datasets 同名条目；若日后出现，同样不得使用。Internet Archive 仅用于核验历史页面和 CDX 长度，也不得当作下载源。建议：待 CBSR 恢复后走官方 zip，或使用作者主页给出的 Drive 链接，并同时完成 AFLW 官方申请；是否联系作者或 TU Graz 联系人，由用户决定。

---

## 1. 原始 AFLW（Annotated Facial Landmarks in the Wild）

### 1.1 官方入口与规模

| 项 | 内容 | 来源（2026-11-16 访问） |
|---|---|---|
| 现行官方页 | https://www.tugraz.at/institute/icg/research/team-bischof/learning-recognition-surveillance/downloads/aflw/ | 该页全文，HTTP 200 |
| 旧域名 | http://lrs.icg.tugraz.at/research/aflw/ （Köstinger 等 2011 论文脚注亦引用此址） | 本次 HEAD：**HTTP 500，Content-Length: 0** |
| 内容（官方页） | Flickr 采集的真实场景人脸；约 25k 张已标注人脸，每张最多 21 个可见性标记的关键点；另提供人脸矩形与与 FDDB 兼容的椭圆，以及用平均三维人脸 + POSIT 得到的粗略头部姿态；官方页写明「No rescaling or cropping has been performed」 | 同上，「Database」「Description」两节 |
| 官方对照表 | AFLW 一行作 25,993 个 landmarked 样本、21 点；主体数标为「-」（不是按身份组织的纵向库） | 同上表格 |
| 官方页更新口径 | 约 25k 已标注人脸；其中 59% 标记为女性、41% 为男性（页面写 updated）；约 380k 个人工关键点 | 同上 |
| 2011 论文口径 | 25,993 张人脸，分布在 21,997 幅图像中；389,473 个关键点；当时性别比例写 56% / 44% | https://www.tugraz.at/fileadmin/user_upload/Institute/ICG/Documents/lrs/pubs/koestinger_befit_11.pdf |
| 3DDFA 论文口径 | 「AFLW contains 21,080 in-the-wild faces」（与官方 25,993 不一致，文献里常用此数；原因未在官方页说明） | arXiv:1511.07212 §6.1；CVPR 2016 同文 |

AFLW **没有**按同一人、多个年龄组织的身份编号，不能当作 AgeDB 一类纵向年龄数据的替代（此点与本项目 RD-4 分工有关，此处只记录官方字段：官方表「# subjects」为「-」）。

### 1.2 许可条款（原文链接与关键句）

条款原文就在官方页「License Agreement」一节，锚点为页面内 `#license`：

https://www.tugraz.at/institute/icg/research/team-bischof/learning-recognition-surveillance/downloads/aflw/#license

开头句：*“By downloading the database you agree to the following restrictions:”* 五条限制如下（英文为页面原文，拼写如 negociated 保持不改）：

1. *“The AFLW database is available for non-commercial research purposes only.”*
2. *“The AFLW database includes images obtained from FlickR which are not property of Graz University of Technology. Graz University of Technology is not responsible for the content nor the meaning of these images. Any use of the images must be negociated with the respective picture owners, according to the Yahoo terms of use. In particular, you agree not to reproduce, duplicate, copy, sell, trade, resell or exploit for any commercial purposes, any portion of the images and any portion of derived data.”*
3. *“You agree not to further copy, publish or distribute any portion of the AFLW database. Except, for internal use at a single site within the same organization it is allowed to make copies of the database.”*
4. *“All submitted papers or any publicly available text using the AFLW database must cite our paper”*
5. *“The organization represented by you will be listed as users of the AFLW database.”*

对毕设的直接含义（解释，不是条款本身）：仅限非商业研究；不得把数据库的任何部分再分发到组织外；对图像及**派生数据**的商业性利用也被第 2 条禁止。AFLW2000-3D 使用了 AFLW 图像，因此这些限制至少覆盖那一部分图像；见第 2.3 节。

指定引用：

> Martin Koestinger, Paul Wohlhart, Peter M. Roth and Horst Bischof. Annotated Facial Landmarks in the Wild: A Large-scale, Real-world Database for Facial Landmark Localization. In Proc. First IEEE International Workshop on Benchmarking Facial Image Analysis Technologies, 2011.

BibTeX 亦列于同一页面「Citation」节。DOI 未在该页给出；论文 PDF 官方副本：https://www.tugraz.at/fileadmin/user_upload/Institute/ICG/Documents/lrs/pubs/koestinger_befit_11.pdf

未发现比该网页条款更长的独立 PDF 许可协议。**未核实** Yahoo / Flickr 现行条款与 2011 年页面表述的对应关系。

### 1.3 获取方式与是否需要注册

官方页「Download Instructions」原文：

> “If you agree with the terms of the license agreement, you can request access to AFLW via this request form.”

申请表（现行，需同意条款后方可申请，**不是公开直链**）：

https://cloud.tugraz.at/index.php/apps/forms/s/R7nejN42iY58E754eqHMfDKS

- 本次对该 URL 的 HEAD 与 GET 均为 HTTP 200（UTC+8 / Asia/Shanghai 访问）。页面为 TU Graz Nextcloud「Formulare」，标题 *AFLW Download Request*，分享者为 **Possegger, Horst（possegger@tugraz.at）**。
- 表单字段依赖 JavaScript 渲染；在关闭脚本的抓取下只能看到标题与分享者，**完整字段清单未复核**。本次只读取页面，**没有提交申请**。
- 官方页源码中，旧的「写信给 LRS 组获取下载说明」已被注释掉，现行路径就是上述表格。

**结论：获取原始 AFLW 需要向 TU Graz 提交申请（注册/申请），不能从官方页直接下载。**

### 1.4 大小

官方页与 2011 论文均未给出包装文件的字节数或 GiB 数。下载链接位于申请通过之后，本次没有可 HEAD 的官方 zip URL。

**原始 AFLW 官方包大小：未核实。** 第三方转存上的体积不得当作官方实测。

---

## 2. AFLW2000-3D

### 2.1 定义与用途

朱翔昱、雷震、刘晓明、石海林、李子青在 3DDFA 论文中写明：为在非受控环境下评测三维人脸对齐，他们构建了 AFLW2000-3D，其中包含 **前 2000 个 AFLW 样本的三维真值人脸及对应的 68 个关键点**；构造细节在补充材料。并说明：AFLW 只标可见点，会在三维评价中出现「假好对齐」，因此需要这一套含不可见点的 68 点标注。

来源：

- 预印本：https://arxiv.org/abs/1511.07212 （2015-11-23；HTML 版 §6.1）
- CVPR 2016（Oral）：Face Alignment Across Large Poses: A 3D Solution。Open Access 补充材料：https://openaccess.thecvf.com/content_cvpr_2016/supplemental/Zhu_Face_Alignment_Across_2016_CVPR_supplemental.pdf
- 扩展期刊：Xiangyu Zhu, Xiaoming Liu, Zhen Lei, Stan Z. Li. Face Alignment in Full Pose Range: A 3D Total Solution. IEEE TPAMI, **2019**, 41(1): 78–92（DOI [10.1109/TPAMI.2017.2778152](https://doi.org/10.1109/TPAMI.2017.2778152)；Crossref `published-print` / `issued` / `published` 均为 2019-01，卷 41 期 1。Crossref 的 `published-online` 字段为空；记录 `created` 为 2017-11-28。DOI 中的 2017 应理解为 IEEE Early Access（在线提前发表）的纪年，不是「投稿/接受记录年」，纸刊年仍写 2019）。作者主页给出 PDF 与补充材料链接。

历史官方页（见 2.2）对下载项的说明原文（Internet Archive 2017-08-30 快照，及公开搜索索引仍缓存的页面文字，措辞一致）：

> “AFLW2000-3D: The fitted 3D faces of the first 2000 AFLW samples, which can be used for 3D face alignment evaluation.”

论文中的评测划分（AFLW2000-3D，68 点，按偏航角）：\([0^\circ,30^\circ]\) 1,306 张，\([30^\circ,60^\circ]\) 462 张，\([60^\circ,90^\circ]\) 232 张，合计 2,000。这是论文数字，不是本次打开数据包的清点。

注意不要与密歇根州立大学 CVLAB 页面的「LFW and AFLW2000」混淆（https://cvlab.cse.msu.edu/lfw-and-aflw2000-datasets.html）：那是人脸正面化等相关工作中的另一套 AFLW2000，不是 AFLW2000-3D。

### 2.2 官方入口与本次 CBSR 重试

**历史及文献中的官方入口（仍应视为正源，尽管当前不可用）：**

| URL | 角色 |
|---|---|
| http://www.cbsr.ia.ac.cn/users/xiangyuzhu/projects/3DDFA/main.htm | 3DDFA 项目页 / AFLW2000-3D 发布说明 |
| http://www.cbsr.ia.ac.cn/users/xiangyuzhu/projects/3DDFA/Database/AFLW2000-3D.zip | 官方数据包直链（页面相对链接 `Database/AFLW2000-3D.zip`） |

论文亦将相关代码与数据发布指向 `http://www.cbsr.ia.ac.cn/users/xiangyuzhu/`（arXiv:1511.07212 文末）。

**2026-11-16（约 12:56 UTC+8 / Asia/Shanghai）实测（只做 HEAD/短 GET，未保存数据正文）：**

| 请求 | 结果 |
|---|---|
| `HEAD http://www.cbsr.ia.ac.cn/users/xiangyuzhu/projects/3DDFA/main.htm` | HTTP/1.1 **500 Internal Server Error**，**Content-Length: 0**，无正文 |
| `HEAD http://www.cbsr.ia.ac.cn/users/xiangyuzhu/projects/3DDFA/Database/AFLW2000-3D.zip` | 同上：500，Content-Length: 0 |
| 对应 HTTPS 两址 | TLS 意外 EOF，`http_code=000`，未建立会话 |
| `GET` 项目页 | 仍为 500，下载大小 0 |

因此：**官方 CBSR 服务器上的页面条款与 zip 的 Content-Length，本次均未能直接测得。** 这与数据集方案 v3 中此前记录的 HTTP 500 一致，官网仍未恢复。

Internet Archive CDX（只查询捕获元数据，未下载 zip；2026-11-16 查询 `https://web.archive.org/cdx/search/cdx`）显示：

- 项目页多次 200 捕获，最近一次成功记录为 **2026-09-16 03:47:40 UTC**（2026-09-16 11:47:40 UTC+8 / Asia/Shanghai；CDX `length=9414`，HTML）。2026-10-12 的捕获失败。本次再取 2026-09-16 的 HTML 快照时，Archive.org 返回 429（机器人流量拦截），故 **2026 年页面全文未能复核**；2017-08-30 快照（`20170830032603`）曾成功取到 HTML，其中已有「AFLW2000-3D database released」及上述 zip 说明，**页面可见文字中未出现 License / Agreement 一类条款标题**。
- 官方 zip URL 的 CDX 记录：
  - `20230320064003`，HTTP 200，`application/x-zip-compressed`，**length=87,076,467**
  - `20260405220653`，HTTP 200，`application/x-zip-compressed`，**length=87,110,961**

这两次存档长度相差 34,494 字节，也不能当作今天官方服务器的 Content-Length。Archive.org **不得**作为获取途径。

### 2.3 许可与是否需要注册

| 问题 | 结论 | 依据与缺口 |
|---|---|---|
| 是否有独立的 AFLW2000-3D 许可文本？ | **未找到。** 官方页（历史快照与搜索缓存文字）、作者主页、TFDS 构建脚本均无 License Agreement 或条款 PDF | 2017 快照可见文字无 license/agreement；作者主页仅给下载链接；https://github.com/tensorflow/datasets/blob/master/tensorflow_datasets/datasets/aflw2k3d/aflw2k3d_dataset_builder.py 只有 Apache-2.0 的**代码**许可，不作用于数据 |
| 3DDFA 源码许可能否覆盖数据？ | **不能。** 仓库徽标为 MIT，只约束代码 | https://github.com/cleardusk/3DDFA （readme.md，MIT badge）；https://github.com/cleardusk/3DDFA_V2 （readme.md，MIT badge）。3DDFA 更新说明写 V2「the copyright is explained by Jianzhu Guo and the CBSR group」，针对的是代码/模型发布，不是数据集条款 |
| 与 AFLW 条款的关系 | **推断，且被未答复的问题所印证。** 图像是「first 2000 AFLW samples」，故 AFLW 第 1–3 条（非商业、图像与派生数据不得商业利用、除组织内单点内部副本外不得再分发）至少约束这些图像。三维拟合标注由 CBSR / 论文作者产生，其单独授权范围未见到文本 | 论文 §6.1；TU Graz 条款第 3 条；下方 Issue |
| 作者是否书面确认过许可？ | **未核实。** | [cleardusk/3DDFA#221](https://github.com/cleardusk/3DDFA/issues/221)（MartFire，2022-10-28 提出）：*"The project is under the MIT license but I would like to know the licenses of 300-W-LP and AFLW2000-3D. Are they the same as 300-W and AFLW?"* 至 2026-11-16 仍为 **open，无回复，无后续评论** |
| 历史上是否要注册才能下官方 zip？ | 历史官方页提供 **公开直链**，未见申请表或登录墙。这与原始 AFLW「必须填申请表」不同 | 2017 快照中的 `href="Database/AFLW2000-3D.zip"`；TFDS 构建脚本同样直接 `download_and_extract` 该 URL |
| 当前？ | CBSR 直链不可用。作者主页改由 Google Drive 分享同名 zip，预览页可匿名打开（见 2.4），仍未见附加的许可点击或申请表。**Drive 分享是否构成正式许可授予：未核实** | 作者主页链接，见下节 |

**稳妥做法（建议，不代替用户决定）：** 即使从作者 Drive 或日后恢复的 CBSR 直链取得 AFLW2000-3D，也应同时通过 TU Graz 官方申请表完成原始 AFLW 的授权；在作者或 CBSR 书面说明之前，不要把 MIT 或第三方网站上的许可证标签（例如 Kaggle 的 Apache 2.0）当作数据包的许可。

### 2.4 替代官方入口（非转存）

以下视为「作者或官方文档指向的入口」，**不是** Kaggle / HF 一类未授权镜像。其中目前真正可打开的，主要是作者主页上的 Drive 链接。

**（1）第一作者个人主页（现行，2026-11-16 可访问）**

- https://xiangyuzhu-open.github.io/homepage/
- 在 CVPR 2016 条目「Face Alignment Across Large Poses: A 3D Solution」下，同时给出 `[Github]`、`[300W-LP]`、`[AFLW2000-3D]`。
- AFLW2000-3D 的 href（作者放出的替代入口）：

  https://drive.google.com/file/d/0B7OEHD3T4eCkZXU4Zy1zZVgzUHc/view?usp=sharing&resourcekey=0-h0GyCbYRA67dgDbelEFxhA

- 本次只打开预览页（HTTP 200，约 87,560 字节的 HTML），**未**请求 `export=download`，**未**下载 zip。预览页显示：
  - `<title>` / `og:title` / `itemprop="name"`：`AFLW2000-3D.zip`
  - `docs-dm`：`application/zip`
  - `isItemTrashed`: false
  - 与文件 id、`resourcekey`、`"zip"` 出现在同一段查看器数据里的大小字段：`[null,null,"87413900"]`，即 **87,413,900 字节**。
  - 87,413,900 ÷ 1,048,576 = **83.36 MiB**（四舍五入到百分位，与 TFDS 目录的 Download size 一致）。
- 这是 **Google Drive 预览页元数据**，不是 CBSR 服务器的 `Content-Length`，也不是对文件的哈希核验。是否与 CBSR 历史官方包字节级相同，**未核实**。

同一条目的 300W-LP 亦指向作者 Drive（`id=0B7OEHD3T4eCkVGs0TkhUWFN6N1k`），不在本任务范围，仅说明作者用同一方式分发 3DDFA 相关数据。

**（2）cleardusk/3DDFA README**

- https://raw.githubusercontent.com/cleardusk/3DDFA/master/readme.md（2026-11-16）
- 训练/评测表把 `test.data.zip` 写为「The cropped images of AFLW and ALFW-2000-3D testset」，作者自述大小 **151M**，链接为百度网盘或 Google Drive（`https://drive.google.com/file/d/1r_ciJ1M0BSRTwndIBt42GlPFRv6CvvEP/view?usp=sharing`）。
- 本次对 Drive `uc?export=download` 只做了 HEAD：HTTP 303 到 `drive.usercontent.google.com`，**Content-Length: 0**，未跟随正文，故 151M **只是 README 自述，不是本次实测**。
- **`test.data.zip` 不是官方 `AFLW2000-3D.zip` 的等价物**：前者是供该仓库 `benchmark.py` 使用的裁剪测试图（README 与项目既有方案 v3 §2-F 已指出 120×120 裁剪、只能做 NME 一类评测）；后者才是项目页发布的「前 2000 AFLW 样本的拟合三维人脸」数据包。不得用 `test.data.zip` 代替官方包。
- 此外，`test.data.zip` **本身就是 AFLW 裁剪图的再分发**（README 写明为 cropped images of AFLW and AFLW-2000-3D testset）。因此它同样受 TU Graz AFLW 条款中非商业使用、以及除组织内单点内部副本外不得把数据库任何部分再分发给第三方的约束（见上文第 1–3 条）。即便可以从作者给出的网盘链接取得该文件，也不等于获得了再分发或商业使用的授权；本课题不得把它当作可自由传播的测试包，也不得再上传到第三方平台。

**（3）cleardusk/3DDFA_V2 README**

- https://raw.githubusercontent.com/cleardusk/3DDFA_V2/master/readme.md（注意是小写 `readme.md`；`README.md` 为 404）
- MIT 许可；作者机构链接仍指向 CBSR 个人页。FAQ 写训练使用 300W-LP，并给出上述 300W-LP Drive。**该 README 没有列出 AFLW2000-3D 的下载项**，因此不能单独作为 AFLW2000-3D 的获取说明，只能作为指向 CBSR / 作者工作的旁证。

**（4）TensorFlow Datasets `aflw2k3d`（目录数字，不是发放渠道）**

- 目录：https://www.tensorflow.org/datasets/catalog/aflw2k3d
  - Homepage 仍写 CBSR 项目页
  - Download size：**83.36 MiB**；Dataset size：42.48 MiB；2,000 条；图像记载为 450×450×3
- 构建脚本：https://raw.githubusercontent.com/tensorflow/datasets/master/tensorflow_datasets/datasets/aflw2k3d/aflw2k3d_dataset_builder.py
  - `dl_manager.download_and_extract("http://www.cbsr.ia.ac.cn/users/xiangyuzhu/projects/3DDFA/Database/AFLW2000-3D.zip")`
  - 解压后目录约定为 `AFLW2000/`，文件名为 `image0*.jpg` 与同名 `.mat`，从 `pt3d_68` 读取 68 点
- 目录中的 83.36 MiB 与作者 Drive 预览页的 87,413,900 字节相符，**但不是本次对 CBSR 的 HEAD**。TFDS 在 CBSR 宕机时若改走自己的缓存或镜像，会构成第三方再分发；**不得把 `tfds.load("aflw2k3d")` 当作已授权的替代官方源**。450×450 是加载器对官方包解压结果的约定描述，不是本次打开 zip 的实测。

**（5）其他出现官方 URL 的代码引用**（仅作「他们也指向 CBSR」，不作获取途径）：例如 hailo-ai/hailo_model_zoo 的 `create_aflw2k3d_tddfa_tfrecord.py` 将未裁剪官方包写为 CBSR 的 `AFLW2000-3D.zip`。

### 2.5 大小对照（必须分开写来源，不可混成一次实测）

| 数字 | 来源与方法 | 能否当作「官方服务器实测 Content-Length」 |
|---|---|---|
| 无法测得 | 2026-11-16 对 CBSR 官方 zip 的 HEAD/GET：500，Content-Length 0 | 否（失败） |
| **87,413,900 字节（83.36 MiB）** | 作者主页所链 Google Drive 预览页元数据（2026-11-16）；文件名 `AFLW2000-3D.zip` | 否，但是目前唯一与作者现行入口对应、且未下载文件得到的大小 |
| 83.36 MiB（目录）/ 42.48 MiB（加载后） | TFDS 目录，非 HEAD | 否 |
| 87,076,467 字节 | IA CDX，官方 zip，2023-03-20 捕获 length | 否（存档长度） |
| 87,110,961 字节 | IA CDX，官方 zip，2026-04-05 捕获 length | 否（存档长度；与前一档及 Drive 元数据均有差异，原因未核实） |
| 「151M」 | 3DDFA README 对 **test.data.zip** 的自述 | 否；且对象不是官方 AFLW2000-3D.zip |
| 88.8 MB 等 | Kaggle 转存页面自述 | 否；且不得使用该来源 |

---

## 3. 未授权转存（不得使用）

AFLW 条款第 3 条禁止将数据库任何部分再复制、出版或分发给组织以外的第三方。下列来源即使「看起来完整」或标注了某种许可证，也**不得作为本项目的获取途径**：

| 来源 | URL | 说明（2026-11-16） |
|---|---|---|
| Kaggle：AFLW2000-3D | https://www.kaggle.com/datasets/mohamedadlyi/aflw2000-3d | 第三方上传的同名数据集，非 TU Graz / CBSR 官方渠道 |
| Kaggle：AFLW2000-3D-P3 | https://www.kaggle.com/datasets/gianpaolobulleddu/aflw2000-3d-p3 | 页面 Usability 3.13；**License 被标为 Apache 2.0**，与 AFLW 非商业、禁止再分发的条款冲突；页面自述体积 88.8 MB，目录名 `AFLW2000`，含 jpg/mat。不得使用，也不得采信该许可证标签 |
| HyperAI | https://hyper.ai/cn/datasets/17153 | 第三方数据集介绍/下载页，非官方 |
| Hugging Face Datasets | （本次检索未发现以 AFLW 或 AFLW2000-3D 为名的突出正式条目；检索结果多为无关数据集或论文页） | 若日后出现转存，同样不得使用 |
| Internet Archive 上的官方 zip 快照 | 见 §2.2 CDX | 只用于核验历史是否存在过该文件及捕获长度；**不要从 Wayback 下载数据包** |
| TFDS 可能的缓存/镜像 | 见 §2.4 | 构建脚本指向官方 URL，但 TFDS 不是许可方 |

Google Drive 链接仅当它出现在**作者本人学术主页**（或日后官方页）时，才按 §2.4 视为替代官方入口；出现在第三方仓库、网盘分享或论坛的同一文件 id，仍应回到作者主页核对，而不是从转贴处下载。

---

## 4. 与 AgeMorph3D 的关系（供后续任务对照，不作新的选型决定）

- AFLW / AFLW2000-3D 的既定用途是 **人脸关键点 / 三维对齐评测与相关训练**，不是按身份跨越年龄的纵向库。官方 AFLW 表没有可用的 subject 计数。
- 仓库方案中把它与 WIDER FACE、FGNET 等并列，服务的是 3DDFA_V2 对齐评测链路，而不是年龄方向的身份划分（后者见 RD-4）。
- 3DDFA 仓库提供的 `test.data.zip` 只能支撑该仓库自己的裁剪评测流程，不能替代官方 AFLW2000-3D 包，也不能替代经申请获得的原始 AFLW。
- 本报告不下载、不镜像、不把任何转存拷入 `/workspace`。

---

## 5. 未核实项

1. 原始 AFLW 官方包装文件的字节数 / GiB（无公开 zip 可 HEAD）。
2. AFLW 申请表的完整字段（页面需 JavaScript）；申请通过后实际发放的方式、是否仍用网盘或校内账户。
3. CBSR 官方 zip **今天**的 Content-Length 与校验和（服务器 500）。
4. 作者 Drive 上 `AFLW2000-3D.zip`（87,413,900 字节）与 CBSR 历史官方包是否字节级一致，以及 Drive 文件的 SHA-256（未下载，未哈希）。
5. Internet Archive 两次 CDX length 与 Drive 元数据不一致的原因。
6. AFLW2000-3D 的独立书面许可，以及 CBSR / 作者是否被 TU Graz 或图像权利人授权再分发前 2000 张 AFLW 图像；Issue #221 仍无答复。
7. 2026-09-16 的 CBSR 页面全文（Wayback 本次 429）。
8. Yahoo / Flickr 现行条款与 AFLW 页面第 2 条的对应关系。
9. `test.data.zip` 的实测大小（只有 README 自述 151M）。
10. 是否存在仍在线的 CBSR 镜像域名或自动化所新站点托管同一 zip（本次只确认作者 GitHub.io 主页给出了 Drive 链接；CBSR 个人页本身同样指向已宕机主机）。

---

## 6. 来源一览

| 来源 | URL | 访问日期（UTC+8 / Asia/Shanghai） |
|---|---|---|
| TU Graz AFLW 官方页（条款原文） | https://www.tugraz.at/institute/icg/research/team-bischof/learning-recognition-surveillance/downloads/aflw/ | 2026-11-16 |
| AFLW 官方申请表 | https://cloud.tugraz.at/index.php/apps/forms/s/R7nejN42iY58E754eqHMfDKS | 2026-11-16（只读，未提交） |
| Köstinger 等 2011 论文 PDF | https://www.tugraz.at/fileadmin/user_upload/Institute/ICG/Documents/lrs/pubs/koestinger_befit_11.pdf | 2026-11-16 |
| 旧 AFLW 域名 | http://lrs.icg.tugraz.at/research/aflw/ | 2026-11-16（HTTP 500） |
| CBSR 3DDFA 项目页与官方 zip | http://www.cbsr.ia.ac.cn/users/xiangyuzhu/projects/3DDFA/main.htm ；…/Database/AFLW2000-3D.zip | 2026-11-16（HTTP 500 / TLS 失败） |
| 朱翔昱个人主页（含 Drive 替代入口） | https://xiangyuzhu-open.github.io/homepage/ | 2026-11-16 |
| 作者 Drive 预览页（AFLW2000-3D.zip） | https://drive.google.com/file/d/0B7OEHD3T4eCkZXU4Zy1zZVgzUHc/view?usp=sharing&resourcekey=0-h0GyCbYRA67dgDbelEFxhA | 2026-11-16（只读预览页） |
| arXiv:1511.07212 | https://arxiv.org/abs/1511.07212 | 2026-11-16 |
| CVPR 2016 补充材料 | https://openaccess.thecvf.com/content_cvpr_2016/supplemental/Zhu_Face_Alignment_Across_2016_CVPR_supplemental.pdf | 2026-11-16 |
| 3DDFA README | https://raw.githubusercontent.com/cleardusk/3DDFA/master/readme.md | 2026-11-16 |
| 3DDFA_V2 README | https://raw.githubusercontent.com/cleardusk/3DDFA_V2/master/readme.md | 2026-11-16 |
| 3DDFA Issue #221 | https://github.com/cleardusk/3DDFA/issues/221 | 2026-11-16 |
| TFDS 目录与构建脚本 | https://www.tensorflow.org/datasets/catalog/aflw2k3d ；https://raw.githubusercontent.com/tensorflow/datasets/master/tensorflow_datasets/datasets/aflw2k3d/aflw2k3d_dataset_builder.py | 2026-11-16 |
| Internet Archive CDX | https://web.archive.org/cdx/search/cdx?url=http://www.cbsr.ia.ac.cn/users/xiangyuzhu/projects/3DDFA/… | 2026-11-16（元数据） |
| Kaggle / HyperAI 转存 | 见 §3 | 2026-11-16 |

---

## 7. 建议获取路径（不代替用户决定，也不开始下载）

1. 原始 AFLW：由有高校邮箱的本人或导师，经官方申请表向 TU Graz 申请；联系人可从申请表页看到为 Horst Possegger（possegger@tugraz.at）。在用户本人要求之前，不代写、不代发申请邮件。
2. AFLW2000-3D：优先等待或重试 CBSR 官方 zip；若需现在取得，以作者主页上的 Drive 链接为替代官方入口，而不要从 Kaggle、HyperAI、HF 或 Wayback 下载。建议同时完成第 1 步的 AFLW 申请。
3. 不要使用 `test.data.zip` 冒充官方 AFLW2000-3D；该文件本身是 AFLW 裁剪图的再分发，同样受非商业、不得再分发条款约束。
4. 许可书面空白（Issue #221 未答复）如需在论文或开题中写死，应向朱翔昱 / CBSR 或导师确认，而不是把 MIT 或第三方许可证标签写进数据条款。
