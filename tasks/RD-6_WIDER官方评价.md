# RD-6 WIDER FACE 官方评价代码与条款（D02）

- 任务：Atlas 规划 v2 的 RD-6。对应毕业设计清单 D02「获取 WIDER FACE 检测数据和官方评价代码」中的评价入口、划分用法与条款核查；不代替 RN-3 的实际下载与哈希签收。
- 范围：只查公开网页、论文、GitHub/Hugging Face 说明与元数据。本地只读查阅了 `/workspace/AgeMorph3D` 中与 D02、实验协议有关的文档，以及 `/workspace/AgeMorph3D_数据集方案_v3.md`、规划 v2。**未克隆或改写项目的 GitHub 远程仓库。**
- **本次未下载任何数据集图像包、标注压缩包或官方评价压缩包。** 对 zip/pdf 仅做 HTTP HEAD（记录 `Content-Length`、`Last-Modified`、`ETag`），不取正文、不计算 SHA-256。
- 查阅日期：2026-11-16（UTC+8 / Asia/Shanghai）。下文 URL 均在该日访问。带有 `Last-Modified` 等时区标记的服务器时间，已换算到 UTC+8 / Asia/Shanghai 后再写。
- 原则：每条结论附一手来源；查不到的写「未核实」。本文不是法律意见，不替代用户或导师做最终决定。
- **修订说明（SN-2 MINOR 就地修正，不必再送审）：** 2026-11-16（UTC+8 / Asia/Shanghai）。全文访问日期与已换算的服务器时间统一改为 UTC+8 / Asia/Shanghai 标注。补充：官方 MATLAB 评价工具需校园 MATLAB 许可，或可试用 GNU Octave（须自行核验数值一致性），并引用 varunagrawal/tiny-faces-pytorch 的 Makefile。关于 YOLO5Face 仓库中四个 `.mat` 的位置：独立复核确认它们位于 `widerface_evaluate/ground_truth/` 下；GitHub Contents API 对目录项报告 `size=0` 是目录的常规取值，并不表示该文件夹为空，因此不改为「直接放在 `widerface_evaluate/` 下」。 2026-11-16 稍后补换算：原第 84–85 行两处 `Last-Modified` 仅写了 GMT，已补上 UTC+8。Sentinel 已撤回「四个 .mat 不在 ground_truth/」一条，位置表述未改。

---

## 0. 结论先行（供 Sentinel / 导师快速阅读）

1. **官方主页**是 [shuoyang1213.me/WIDERFACE](http://shuoyang1213.me/WIDERFACE/)。原 CUHK MMLab 入口 [mmlab.ie.cuhk.edu.hk/projects/WIDERFace/](https://mmlab.ie.cuhk.edu.hk/projects/WIDERFace/) 用 meta refresh 指向该主页，并写「The page was moved to this link」。**官方结果与评价脚本页**仍托管在 CUHK： [WiderFace_Results.html](https://mmlab.ie.cuhk.edu.hk/projects/WIDERFace/WiderFace_Results.html)。主页列出的图像镜像包括 Google Drive、Tencent Drive、Hugging Face。
2. **官方评价工具**文件名是 `eval_tools.zip`，结果页链接为 `./support/eval_script/eval_tools.zip`。本日可访问的完整地址是 `https://mmlab.ie.cuhk.edu.hk/projects/WIDERFace/support/eval_script/eval_tools.zip`。HEAD：`Content-Length=6434835`（6,434,835 字节），`Content-Type=application/zip`，`Last-Modified=Wed, 24 Apr 2019 10:23:23 GMT`（即 2019-04-24 18:23:23 UTC+8 / Asia/Shanghai），`ETag="623013-58744176a7b30"`。官方主页 News 写：2017-03-31「The new version of evaluation code and validation results is released」。语言为 **MATLAB**，主入口是 `wider_eval.m`（需设置 `pred_dir` 与 `legend_name`）。它按 PASCAL VOC 口径计算 **Easy / Medium / Hard 的 AP**，并绘制 **PR 曲线**。压缩包正文未下载，包内完整文件清单、是否含单独许可文件、SHA-256 均标「未核实」。运行该官方 MATLAB 工具需要可用的**校园 MATLAB 许可**；若没有 MATLAB，可用 **GNU Octave** 尝试调用同一入口 `wider_eval.m`，但与 MathWorks MATLAB 的数值是否一致必须自行对照测试，不能默认等价。已有公开项目采用 Octave：`varunagrawal/tiny-faces-pytorch` 的 Makefile 中 `evaluation` 目标为 `cd eval_tools/ && octave wider_eval.m`，其 README 写明 “this needs Matlab/Octave”。来源：https://github.com/varunagrawal/tiny-faces-pytorch/blob/master/Makefile 、https://github.com/varunagrawal/tiny-faces-pytorch （README；2026-11-16，UTC+8 / Asia/Shanghai，只读查阅，未下载评价数据）。
3. **预测文件格式**（val 本地评测与 test 提交相同）：按 61 个事件子目录存放，与图像同名的 `.txt`；首行图像名，次行人脸数，随后每行 `left top width height score`。官方示例包：`https://mmlab.ie.cuhk.edu.hk/projects/WIDERFace/support/example/Submission_example.zip`（HEAD：624 字节，同一 `Last-Modified`）。
4. **Val 与 test 必须分开写。** 官方按每个事件类随机划分 **40% / 10% / 50%** 为 train / val / test。公开数字为训练 12,880 张、验证 3,226 张、测试 16,097 张（合计 32,203）。**验证集框标注公开**，可用官方工具本地计算 Easy/Medium/Hard AP。**测试集不公开框真值**，须把预测文件交给作者评测；联系邮箱仍是 `shuoyang.1213@gmail.com`。主页仍写「An evaluation server will be available soon」。本日在官方页面上**没有**发现已上线的评测服务器；**2026 年该邮箱是否仍受理提交，未核实**。本科论文默认应报告 **官方验证集** 成绩，且写明评测脚本；不得把本地数字写成「官方 test」。
5. **YOLO5Face 论文与官方仓库报告的是验证集。** 论文 Table 4 标题为 WiderFace **validation**；YOLOv5n0.5（即本仓库所用 yolov5n-0.5）在 VGA（长边 640）上为 Easy **90.76** / Medium **88.12** / Hard **73.82**。仓库评测步骤走的是内置的 `widerface_evaluate/evaluation.py`，这是 [wondervictor/WiderFace-Evaluation](https://github.com/wondervictor/WiderFace-Evaluation) 的非官方 Python 移植，**不能代替官方 MATLAB 作为论文口径的唯一依据**。该论文把划分写成 50%/10%/40%，与官方 40%/10%/50% 不符，引用时不要沿用这个比例。
6. **给本课题的报告建议（与已有实验协议一致，不是替用户做决定）：** 只用 train（必要时在 train 内部再切一块开发集）做微调和选模型；官方 val 作为冻结后的检测评价指标；若实际上用 val 调参，必须在论文里改称验证用途并披露，仍不得称官方 test。正式 AP 必须用官方 `eval_tools`（校园 MATLAB 许可，或经自行核验数值一致后的 GNU Octave）和包内的 `wider_*_val.mat`（含 Easy/Medium/Hard 的计入名单与忽略框），**不能用自写 YOLO 标签或 Ultralytics mAP50–95 代替**。Python 移植只可作开发对照，论文需写明脚本身份；若数字与官方 MATLAB 不一致，以官方工具为准。
7. **许可：** 官方主页 License 栏只写「Creative Common License (cc by-nc-nd)」，**未写版本号**。Hugging Face 数据集卡 [CUHK-CSE/wider_face](https://huggingface.co/datasets/CUHK-CSE/wider_face) 记为 **CC BY-NC-ND 4.0**。使用时需署名并引用 Yang 等 CVPR 2016；限非商业；官方页未授权再分发衍生数据。官方评价工具本身的许可文件**未打开压缩包，未核实**。

---

## 1. 官方站点与镜像

### 1.1 作者指定的入口

| 入口 | 本日访问结果（2026-11-16，UTC+8 / Asia/Shanghai） | 作用 |
|---|---|---|
| http://shuoyang1213.me/WIDERFACE/ 与 `/index.html` | 外部抓取工具返回了完整页面正文（含 News、Description、Download、Submission、Citation、License、Contact）。本机 `curl` 经 198.18.0.1（`Server: Pingora`）对 HTTP 返回 **500**，对 HTTPS 出现证书名不匹配（证书 CN 为 `*.github.com`），故本机未能直接保存该站 HTML。页面内容以抓取结果与 CUHK 仍在线的跳转页互证。 | **数据集主页**（作者现用站点） |
| https://mmlab.ie.cuhk.edu.hk/projects/WIDERFace/ | HTTP 200。正文只有「The page was moved to this link」，`<meta http-equiv="refresh" content="0;URL='http://shuoyang1213.me/WIDERFACE/'" />`，以及指向 `http://shuoyang1213.me/WIDERFACE/` 的锚点。同一路径的 **HTTP（非 HTTPS）** 本机亦为 500。 | 历史官方入口，明确迁到 shuoyang 主页 |
| https://mmlab.ie.cuhk.edu.hk/projects/WIDERFace/WiderFace_Results.html | HTTP 200，完整结果与评价说明页，链到 `./support/eval_script/eval_tools.zip` 与 `./support/paper.pdf`。shuoyang 上的同名结果页本机 HTTP 为 500。 | **官方评价与排行说明页** |

来源：[CUHK 落地页 HTML](https://mmlab.ie.cuhk.edu.hk/projects/WIDERFace/)（2026-11-16 保存）；[CUHK 结果页](https://mmlab.ie.cuhk.edu.hk/projects/WIDERFace/WiderFace_Results.html)；主页正文见对 http://shuoyang1213.me/WIDERFACE/ 的抓取。

作者列出的图像下载渠道（主页 Download 栏原文要点）：WIDER Face Training / Validation / Testing Images 各提供 **Google Drive、Tencent Drive、Hugging Face**；另有 Face annotations、Examples and formats of the submissions。具体 Drive 文件 ID 因主页 HTML 未能在本机完整保存，**未从官方页逐条抄出**；TensorFlow Datasets 脚本里记录了一组常用 Google Drive ID，只作第三方记录，不能自动当成当前官方链接（见 §6）。

项目方案 v3 §2-E 写的官网 `http://shuoyang1213.me/WIDERFACE/` 与上述主页一致；HF 上的 [CUHK-CSE/wider_face](https://huggingface.co/datasets/CUHK-CSE/wider_face) 卡片 Homepage 也指向该地址，License 为 `cc-by-nc-nd-4.0`。CUHK-CSE 是否由原作者直接维护，**未另核机构账号授权书**，但官方主页已把 Hugging Face 列为下载选项。

### 1.2 数据集规模与划分（官方口径）

主页 Description 与论文摘要一致：从公开 WIDER 数据集中选取 **32,203** 张图像，标注 **393,703** 张人脸；按事件类组织。主页写「**61** event classes」；CVPR / arXiv 论文 §3.1 写「**60** event classes」。二者不一致，见 §6。Hugging Face 卡片与主页同为 61 类，并给出张数：

- 训练 12,880，验证 3,226，测试 16,097（12,880 + 3,226 + 16,097 = 32,203）。
- 「For each event class, we randomly select 40%/10%/50% data as training, validation and testing sets.」

来源：官方主页 Description；Yang 等，*WIDER FACE: A Face Detection Benchmark*，arXiv:[1511.06523](https://arxiv.org/abs/1511.06523)（HTML：[v1](https://arxiv.org/html/1511.06523)）、[CVPR 2016 开放获取页](https://openaccess.thecvf.com/content_cvpr_2016/html/Yang_WIDER_FACE_A_CVPR_2016_paper.html)；[CUHK-CSE/wider_face 数据集卡](https://huggingface.co/datasets/CUHK-CSE/wider_face)。

官方主页 News（与评测相关的条目）：

- 2015-11-19：WIDER FACE v1.0 发布（图像、框、事件类）。
- 2016-04-17：姿态与遮挡等属性标签可用。
- **2017-03-31：发布新版评价代码和验证集结果；增加文本版真值，并修正框标注的舍入问题。**

因此，取得数据时应使用带文本真值的现行划分（2017-03-31 及之后），不要混用更早、已修正舍入问题之前的标注。文本标注包的现行官方地址见 §2.4（仅 HEAD，未下载）。

---

## 2. 官方评价工具

### 2.1 准确链接、文件名、版本与体积

官方结果页「Evaluation Code」一节原文：提供「Evaluation and Plotting scripts for generating the PR curves」；下载锚文本为「Evaluation, Plotting scripts and the PR curves」，目标为 `./support/eval_script/eval_tools.zip`。页上还提醒：下载的 tar/zip 里的 PR 曲线不一定是最新排行，必要时需单独拷贝最新曲线再跑绘图脚本。

| 项 | 记录 |
|---|---|
| 文件名 | `eval_tools.zip` |
| 官方相对路径 | `support/eval_script/eval_tools.zip` |
| 本日可访问的绝对 URL | https://mmlab.ie.cuhk.edu.hk/projects/WIDERFace/support/eval_script/eval_tools.zip |
| 历史同名 URL（主页域） | http://shuoyang1213.me/WIDERFACE/support/eval_script/eval_tools.zip（本日本机 HEAD 为 500，**未核实**是否在其他网络可用） |
| 语言 | MATLAB。第三方文档一致指出主程序为 `wider_eval.m` |
| 官方自称版本日期 | 主页 News：2017-03-31 发布「new version of evaluation code and validation results」 |
| 服务器文件时间（HEAD，非解压后源码日期） | `Last-Modified=2019-04-24 10:23:23 GMT` = **2019-04-24 18:23:23 UTC+8 / Asia/Shanghai** |
| 字节数（HEAD） | 6,434,835 |
| ETag | `"623013-58744176a7b30"` |
| SHA-256 | **未核实**（未下载正文） |
| 压缩包内许可文件 | **未核实**（未打开压缩包） |

来源：[官方结果页](https://mmlab.ie.cuhk.edu.hk/projects/WIDERFace/WiderFace_Results.html)；对该 zip 的 HTTPS HEAD（2026-11-16）；官方主页 News。`wider_eval.m` 的用法见 PaddleDetection 文档 [FaceDetection](https://paddledetection.readthedocs.io/featured_model/FACE_DETECTION_en.html) 与 img2pose 仓库 issue [#8](https://github.com/vitoralbiero/img2pose/issues/8)（维护者说明：运行 `wider_eval.m`，把 `pred_dir` 指到预测目录，`legend_name` 设为模型名）。这些是对官方 MATLAB 入口的转述，不是官方 README 原文；**官方 zip 内 README 原文未打开，未核实。**

与评价工具同时、同一台 CUHK 服务器上还提供：

- 官方论文 PDF：https://mmlab.ie.cuhk.edu.hk/projects/WIDERFace/support/paper.pdf（HEAD：3,255,241 字节，`Last-Modified=2019-04-24 10:23:20 GMT` = 2019-04-24 18:23:20 UTC+8 / Asia/Shanghai）。本文引用论文内容时用 arXiv HTML / CVPR 开放获取页，**未下载该 PDF。**
- 提交示例：https://mmlab.ie.cuhk.edu.hk/projects/WIDERFace/support/example/Submission_example.zip（HEAD：624 字节，`Last-Modified=2019-04-24 10:23:22 GMT` = 2019-04-24 18:23:22 UTC+8 / Asia/Shanghai）。**未下载。**
- 文本划分/标注包：https://mmlab.ie.cuhk.edu.hk/projects/WIDERFace/support/bbx_annotation/wider_face_split.zip（HEAD：3,591,642 字节，`Last-Modified=2019-04-24 10:23:23 GMT` = 2019-04-24 18:23:23 UTC+8 / Asia/Shanghai，与评价工具同一分钟）。**未下载。** Hugging Face 上 `data/wider_face_split.zip` 的 `x-linked-size` 同为 3,591,642，与 CUHK 该文件大小一致（仅 HEAD/响应头，未下正文）。

### 2.2 计算什么

官方结果页原文：

> We adopt the same evaluation metric employed in the PASCAL VOC dataset. If the ratio of the intersection of a detected region with an annotated face region is greater than 0.5, a score of 1 is assigned to the detected region, and 0 otherwise. Further details for the evaluation procedure can be found in our paper.

即：**IoU 阈值 0.5 的 PASCAL VOC 检测评价**，输出 Easy、Medium、Hard 三个设置下的 **PR 曲线与 AP**。结果页同时给出 Scenario-Ext（可用任何外部数据训练，在 **test** 上评）与 Scenario-Int（用 WIDER 的 train/val 训练，在 **test** 上评）。论文与主页对这两个情景的定义一致。

需要单独标明的表述差异：结果页写 IoU「**greater than** 0.5」；广泛使用的 Python 移植与常见 VOC 实现使用「**大于等于** 0.5」（见 §3）。**官方 MATLAB 源码里的比较符未打开 zip，未核实。** 论文报告时应写明所用脚本与阈值实现。

Easy / Medium / Hard **不是**简单按人脸像素高度切成三份互斥集合。论文 §3.3 写明：依照 KITTI、MALF 的思路，根据 **EdgeBox** 在每图 8,000 个 proposal 时的检出率定义三个难度，平均召回约为 **92% / 76% / 34%**。论文结论处只把 easy 子集描述为「typically with faces of over 50 pixels height」，这是概括，不是正式切分规则。计入某个设置的人脸名单，固定写在评价工具的 `wider_easy_val.mat` / `wider_medium_val.mat` / `wider_hard_val.mat` 的 `gt_list` 中；不在该名单中的框按忽略处理（匹配到也不记真阳性或假阳性）。Hard 是计入人脸最多的设置，因此包含大量小脸；论文还单独把高度 10–50 / 50–300 / ≥300 像素作为尺度分析，不要把「Hard」直接等同于「小脸子集」，但报告 Hard AP 时必须意识到其中包含极小人脸。对「三套设置是否嵌套（Hard ⊃ Medium ⊃ Easy）」论文未写死，后继工作常如此描述，见 §6。

另外，论文 §3.2 规定：对因低分辨率、尺度过小（**10 像素或更小**）而极难识别的脸，赋予与 PASCAL VOC 类似的 **Ignore** 标记。这些脸是否被某个设置计入，也是通过上述 `gt_list` 体现的，而不是在评测时再读一遍文本里的 ignore/invalid 字段。

AP 的积分方式：官方页只说采用 VOC。非官方 Python 移植用 **1000 个分数阈值** 采样 PR，再按 VOC 的精度包络面积计算 AP（见 §3）。官方 MATLAB 是否同样取 1000 点，**未打开 zip，未直接核实**；多份对官方脚本的转述与该移植一致。

来源：官方结果页；arXiv:[1511.06523](https://arxiv.org/html/1511.06523) §3.1–3.3、§6。

### 2.3 预测文件的输入格式（官方要求）

官方主页 Submission 一节（val 本地评测与 test 提交使用同一格式）要点：

- 每张图一个文本文件，**文件名与图像相同**（扩展名为 `.txt`）。
- 按事件类别分目录。例如测试图像为 `./0--Parade/0_Parade_marchingband_1_5.jpg`，则结果写在 `./0--Parade/0_Parade_marchingband_1_5.txt`。
- 每个文本文件的检测框一行，格式为 `[left, top, width, height, score]`。页上同时给出结构说明：图像名、该图人脸数，然后逐框列出。更清楚的示例见官方 `Submission_example.zip`（未下载，格式与结果页/主页及第三方转述一致）。

第三方对示例包的转述（[wondervictor issue #3](https://github.com/wondervictor/WiderFace-Evaluation/issues/3)）与主页一致，并给出示例目录：

```
pred_dir/
  0--Parade/
    0_Parade_marchingband_1_20.txt
    0_Parade_marchingband_1_74.txt
  1--Handshaking/
    ...
```

单个 txt 内容形如：

```
0_Parade_marchingband_1_20
<检测框数量>
x y w h confidence
...
```

来源：官方主页 Submission；官方结果页「Reporting results」；提交示例 URL 见 §2.1。

### 2.4 官方评测需要的真值，而不是 YOLO 标签

验证集本地官方 AP 依赖评价工具中的 MATLAB 真值，而不是 `wider_face_val_bbx_gt.txt` 转成的 YOLO `.txt`。非官方 Python 移植的 README 写明 GroungTruth（原文如此）为：

- `wider_face_val.mat`
- `wider_easy_val.mat`
- `wider_medium_val.mat`
- `wider_hard_val.mat`

其默认路径写为 `/Users/Vic/Downloads/eval_tools/ground_truth/`，说明这些 mat 位于官方 `eval_tools` 解压后的 `ground_truth/` 目录。这与项目 FG-1 已记录的结论一致：官方 AP 必须用官方评测工具和这些 mat（含难度名单与忽略框），不能用本项目转换器生成的 val YOLO 标签代替。

文本标注（供训练转换，不是官方 AP 引擎的输入）格式，官方 2017-03-31 起提供。第三方保存的 `wider_face_split/readme.txt`（[akofman 仓库中的副本](https://github.com/akofman/wider-face-pascal-voc-annotations/blob/master/wider_face_split/readme.txt)，**不是本次从官方 zip 解出的原件**）写明：

```
File name
Number of bounding box
x1, y1, w, h, blur, expression, illumination, invalid, occlusion, pose
```

属性取值：blur 0/1/2（clear / normal / heavy）；expression 0/1（typical / exaggerate）；illumination 0/1（normal / extreme）；occlusion 0/1/2（no / partial / heavy）；pose 0/1（typical / atypical）；invalid 0/1（valid / invalid image）。TensorFlow Datasets 的解析脚本还记录：测试集对应文件是 `wider_face_test_filelist.txt`（无框）；训练/验证为 `wider_face_{train,val}_bbx_gt.txt`；标注为 0 框的图像仍会有一行占位零。这些与项目 FG-1 合成测试所依据的格式相符，但 **readme 原文是否与官方 zip 字节级一致，未打开官方包，未核实。**

WIDER FACE **不提供五点关键点标注**。不得把检测框当成五点真值（D02 验收原文即有此条）。

来源：[wondervictor README](https://github.com/wondervictor/WiderFace-Evaluation/blob/master/README.md)；[evaluation.py](https://raw.githubusercontent.com/wondervictor/WiderFace-Evaluation/master/evaluation.py) 的 `get_gt_boxes()`；[akofman readme 副本](https://github.com/akofman/wider-face-pascal-voc-annotations/blob/master/wider_face_split/readme.txt)；[TFDS wider_face.py](https://github.com/tensorflow/datasets/blob/master/tensorflow_datasets/object_detection/wider_face.py)；本地 `docs/后续任务清单.md` D02 行；`/workspace/AgeMorph3D_tasks/FG-1_说明.md`。

---

## 3. 非官方 Python 移植（须标明非正式）

下列实现都是社区对官方 MATLAB 流程的重写，**不是**作者发布的官方工具。可以在没有 MATLAB 的开发环境里做对照，但论文若报告「官方 AP」，应以 `eval_tools.zip` 中的 MATLAB 脚本为准，或同时给出两种脚本的数字并解释差异。

### 3.1 wondervictor/WiderFace-Evaluation（最常用；YOLO5Face 所用）

- 仓库：https://github.com/wondervictor/WiderFace-Evaluation
- GitHub API（2026-11-16）：创建于 2018-08-24T06:47:17Z（2018-08-24 14:47:17 UTC+8 / Asia/Shanghai）；`pushed_at=2024-03-04T07:00:38Z`（2024-03-04 15:00:38 UTC+8 / Asia/Shanghai）；默认分支 `master`；许可 **MIT**（SPDX：MIT；Copyright 2018 Vic Chan）；约 181 star / 40 fork。LICENSE 只约束该 Python 代码，**不构成数据集或官方 MATLAB 的许可**。
- 用法：先 `python3 setup.py build_ext --inplace`，再 `python3 evaluation.py -p <预测目录> -g <真值目录>`。真值目录需含上述四个 `.mat`。
- 行为与官方协议对齐的部分（据其源码，不是官方背书）：读取事件/文件列表与三个难度的 `gt_list`；IoU 默认 0.5；对分数做全局 min–max 归一化（`norm_score`）；1000 个阈值采样 PR；用 VOC 精度包络面积算 AP；输出 `Easy/Medium/Hard Val AP`。`box_overlaps.pyx` 在宽高计算中使用 **+1**（`(x2-x1+1)*(y2-y1+1)`），这是 MATLAB 常用的闭区间框面积写法。
- README **没有**声称与官方 MATLAB 数字逐位一致。默认 `-g` 路径为作者本机的 `/Users/Vic/Downloads/eval_tools/ground_truth/`，说明它依赖官方工具里的 mat，而不是另造一套真值。

已知差异与陷阱（报告 Python 数字时必须写明）：

1. **预测框是否已按分数从高到低排序。** `evaluation.py` 的 `image_eval` / `img_pr_info` **不会**先排序，而是假定高分在前，用「最后一个超过当前阈值的下标」做前缀统计。官方 MATLAB 一侧的转述是 `read_pred.m` 会按分数降序排序（未打开官方源码，标「据转述」）。YOLO5Face 仓库 issue [#287](https://github.com/deepcam-cn/yolov5-face/issues/287) 用对照实验表明：把同一张图的检测按置信度升序保存后，Val AP 会显著下降；评论写明 `evaluate.py assumes that preds are sorted by confidence in descending order`。
2. IoU「> 0.5」与「≥ 0.5」、以及 +1 像素面积，都可能造成与口头描述或与未对齐实现之间的微小差别。
3. 变量名 `ignore` 在该脚本里实际是「该设置下计入的人脸」（`gt_list` 的 1 基索引减一后置 1）；未计入的人脸被匹配时既不是 TP 也不是 FP。阅读源码时不要按英语 ignore 的日常含义理解反了。

来源：仓库 README、LICENSE、`evaluation.py`、`box_overlaps.pyx`；GitHub API；issue #3、#287。

### 3.2 YOLO5Face 仓库内的副本

[deepcam-cn/yolov5-face](https://github.com/deepcam-cn/yolov5-face) 的官方评测步骤（README「WIDERFace Evaluation」）为：

```
python3 test_widerface.py --weights 'your test model' --img-size 640
cd widerface_evaluate
python3 evaluation.py
```

`widerface_evaluate/` 目录含与 wondervictor 同名的 `evaluation.py`（9017 字节，略大于上游 8520 字节）、`box_overlaps.pyx`、`setup.py`、`README.md`（507 字节，与上游相同）以及 **`ground_truth/` 子目录下的四个** `wider_*_val.mat`。也就是说，**YOLO5Face 公开代码走的是该非官方 Python 移植**，而不是调用 MATLAB `wider_eval.m`。论文 Table 4 的验证集数字是否曾用官方 MATLAB 复核，**论文未写，未核实**。

独立复核（2026-11-16，UTC+8 / Asia/Shanghai；只读 GitHub Contents API，未克隆仓库、未下载权重或数据）：对 `https://api.github.com/repos/deepcam-cn/yolov5-face/contents/widerface_evaluate` 的 GET 显示，`ground_truth` 的 `type` 为 `dir`，字段 `size` 为 0。GitHub Contents API 对**目录项**通常报告 `size=0`，这并不表示该文件夹为空。继续列出 `https://api.github.com/repos/deepcam-cn/yolov5-face/contents/widerface_evaluate/ground_truth`（并与默认分支的 git tree 交叉核对）可见四个 `.mat` 均位于 `widerface_evaluate/ground_truth/` 下：`wider_face_val.mat` 397,768 字节，`wider_easy_val.mat` 409,036 字节，`wider_medium_val.mat` 412,725 字节，`wider_hard_val.mat` 424,085 字节。因此本文仍采用「四个 mat 在 `ground_truth/` 子目录中」的表述，**不改为**「直接放在 `widerface_evaluate/` 下、且 `ground_truth` 为空」。

来源：[README 原文](https://raw.githubusercontent.com/deepcam-cn/yolov5-face/master/README.md)；GitHub API 目录列表。

### 3.3 其他非官方移植（仅登记）

- [xiyinmsu/python-wider_eval](https://github.com/xiyinmsu/python-wider_eval)：README 写明把官方 MATLAB「转换成 Python，沿用同一逻辑和多数变量/函数名」，并要求先下载官方 `eval_tools.zip`。作者称比 MATLAB 快约 2.5 倍。同样是非官方实现。
- 不少检测项目（RetinaFace、InsightFace、PaddleDetection 等）或内置 wondervictor 副本，或先导出官方格式再调用 MATLAB。PaddleDetection 文档明确要求：先生成 txt，再 `wget` 官方 `eval_tools.zip`，修改并运行 `wider_eval.m`。

**结论：** 开发阶段可用 Python 移植做快速对照；冻结后的论文数字应再跑（或仅跑）官方 `eval_tools`（校园 MATLAB，或经自行核验后的 GNU Octave），并在文中写明脚本、运行环境、提交格式、输入尺度和划分。不得把 Python 移植称为「官方评价代码」。

---

## 4. Val 与 test 应如何使用（D02 / 论文口径）

### 4.1 官方规则

| 划分 | 比例（按事件类） | 图像数（公开卡片） | 框真值 | 本课题应如何用 |
|---|---|---|---|---|
| train | 40% | 12,880 | 公开（文本 + 训练转换用） | 微调与（默认）内部开发切分；可转成 YOLO 格式训练。不要在报告里把 train 图像上的分数当作检测泛化指标。 |
| val | 10% | 3,226 | **公开**。官方 AP 用 `eval_tools` 中的 mat，而不是 YOLO 标签 | **默认：模型选定之后的冻结评价**（与 `docs/实验协议.md`、`experiment-protocol-v1.json` 一致）。若实际拿 val 调参，必须披露，改称验证用途。 |
| test | 50% | 16,097 | **不公开**。只有文件列表 | 不可在本地「跑出官方 test AP」。若要官方 test 数字，须按官方格式把预测提交给 `shuoyang.1213@gmail.com`，等作者返回。本科论文**不是必须**提交 test；未返回前不得写「已完成官方测试」。 |

官方主页原文：「Similar to MALF and Caltech datasets, we do not release bounding box ground truth for the test images. Users are required to submit final prediction files, which we shall proceed to evaluate。」「Please contact us to evaluate your detection results. An evaluation server will be available soon。」「For questions and result submission, please contact Shuo Yang at shuoyang.1213@gmail.com」。结果页「Reporting results」重复同一邮箱。

**评测服务器与提交是否仍然开放：** 官方页面从至少多年前起就写「will be available soon」，本日仍是这句，未见已上线的官方服务器链接。是否仍有人处理邮件提交，**未核实**（未见 2024–2026 年官方确认，本文也未向该邮箱发信）。第三方竞赛平台（例如历史上的研讨会挑战）不能自动当成 WIDER 官方持续测试入口。建议：毕业论文以官方 **val** 为可独立复现的主结果；只有在作者实际返回 test 分数时，才可把 test 作为附加官方数字，并保留往来邮件。

来源：官方主页 Description / Submission / Contact；官方结果页；论文 §3.1；HF 数据集卡 Data Splits。

### 4.2 YOLO5Face 论文报告的是哪一划分

Qi 等，*YOLO5Face: Why Reinventing a Face Detector*，arXiv:[2105.12931](https://arxiv.org/abs/2105.12931)（HTML：[v2](https://arxiv.org/html/2105.12931v2)）：

- Table 2 消融、Table 4 与现有方法对比，均明确写在 **WiderFace validation** 上。
- Table 4 中 **YOLOv5n0.5**（ShuffleNetv2-0.5，与官方 README「yolov5n-0.5」及本仓库所用规格对应）：Easy **90.76**、Medium **88.12**、Hard **73.82**，参数 0.447 M，0.571 GFLOPs。仓库 README 写这些数字来自「Single Scale Inference on VGA resolution（max side is equal to 640 and scale）」。
- §4.5 另外给出多尺度等设置下、更大模型在 val **和 test** 上的 PR/AP（例如文中 YOLOv5x6 的 test 为 95.8 / 94.9 / 90.5）。这与 Table 4 的 VGA 单尺度验证集数字不是同一实验设置，引用时必须分开。
- 论文 §4.1 误把划分写成「train/validation/test sets by ratio **50%/10%/40%**」。这与官方 40%/10%/50% 不符。本课题文档与开题材料应采用官方比例，不要沿用该笔误。

来源：上述论文 HTML；[deepcam README](https://raw.githubusercontent.com/deepcam-cn/yolov5-face/master/README.md)。

### 4.3 建议本课题如何在论文中报告（D02 / E01 / E03）

以下与仓库已有协议对齐，供导师审定，不是代为决定：

1. **主结果写「WIDER FACE 验证集，官方 Easy / Medium / Hard AP（及 PR 曲线）」**，并写清：输入尺度（若与 YOLO5Face 对比，注明 VGA、长边 640 或实际采用的尺度）、NMS 与置信处理、是否多尺度/翻转、**评测脚本的准确身份与版本**（建议：官方 `eval_tools.zip`，记录 URL、`Last-Modified` 或日后实测的 SHA-256）。
2. **训练只使用 train**（或 train 内再切开发集）。官方 val 默认留到模型选定之后再评一次。若因样本少而用 val 调参，必须在实验协议和论文中明示，且仍不得称官方 test。
3. **不要在 test 上调参，也不要反复提交 test 来选择模型。** 未获作者返回分数时，不写官方 test AP。
4. 自写脚本把 `wider_face_*_bbx_gt.txt` 转成 YOLO，只用于训练/工程检查（v3 §2-E、§5：不用 Bingsu 转换，自己写）。**正式 AP 必须把检测导出为官方提交格式，交给官方评价工具（及其中的 mat）。**
5. 不要把 Ultralytics / COCO 的 mAP50 或 mAP50–95 写成 WIDER 官方 AP。
6. 对比 YOLO5Face 基线时，对齐其论文已声明的条件：验证集、VGA 长边 640、同一套 Easy/Medium/Hard；并注明对方公开代码使用的是 Python 移植。若本课题用官方 MATLAB 复现 yolov5n-0.5 的 90.76 / 88.12 / 73.82 出现差异，应如实记录，不以 Python 数字「改写」官方口径。
7. Hard 集合包含大量小脸，也包含被 Easy/Medium 计入的脸（若名单确实嵌套；嵌套关系见 §6）。解释失败案例时不要只谈「模型不会检小脸」，但必须报告 Hard，不能只用 Easy 宣称「mAP ≥ 90%」。
8. 在论文或附录固定：评测命令、`pred_dir` 结构、IoU 阈值、是否按分数降序保存 txt、所用 `eval_tools` 的来源与文件时间/哈希。

仓库依据：`docs/后续任务清单.md` D02、E03；`docs/数据资源清单.md` WIDER 行（「默认 train 内开发、官方 val 在模型选择后冻结评价；若使用 val 调参须披露……不自写替代官方 AP……不声称完成官方 test」）；`docs/实验协议.md` §1–2；`docs/experiment-protocol-v1.json` 的 `detection` 字段；规划 v2 对 RD-6 / E01 的验收说明。

### 4.4 常见陷阱（应写进实验记录）

- 在 val 上训练或把 val 当选模型依据，却在论文中写成「未见过的官方验证/测试」。
- 在 test 图像上调阈值、NMS 或输入尺度。
- 用 YOLO 格式的 val 标签、自写 AP、或 COCO 指标代替官方工具。
- 预测 txt 未按事件目录存放、未写图像名与框数、xywh 与分数列错、或未按分数降序（Python 移植会错）。
- 忽略框与 invalid / 小于约 10 像素的 Ignore 脸被当成必须检出的正例，或相反地被错误丢弃。
- 把 2017-03-31 之前、舍入问题修正前的标注与现行评测混用。
- 把论文里的 60 个事件类、或 YOLO5Face 论文里的 50%/10%/40% 当成官方划分。
- 未下载 test 图像却声称已评官方 test；或下载了 test 图像后因没有真值而用「自己估的框」评测。
- 比较不同论文的 AP 时忽略输入分辨率（VGA 对多尺度）、是否用 val 调参、以及 MATLAB 还是 Python 评测。

---

## 5. 许可与引用要求

### 5.1 数据集

官方主页 License 栏原文仅为：

> Creative Common License (cc by-nc-nd)

**官方页没有写 3.0 还是 4.0，也没有链到法律文本。** Hugging Face [CUHK-CSE/wider_face](https://huggingface.co/datasets/CUHK-CSE/wider_face) 的 YAML `license: cc-by-nc-nd-4.0`，卡片「Licensing Information」写「Creative Commons Attribution-NonCommercial-NoDerivatives 4.0 International (CC BY-NC-ND 4.0)」。在官方未给出版本的前提下，较稳妥的写法是：官方自我声明为 CC BY-NC-ND；4.0 来自该 HF 卡片，不是主页原文。

[CC BY-NC-ND 4.0 deed](https://creativecommons.org/licenses/by-nc-nd/4.0/deed.en) 的要点（deed 不是法律文本本身，完整条款见 [legalcode](https://creativecommons.org/licenses/by-nc-nd/4.0/legalcode)）：

- 署名（Attribution）；
- 非商业（NonCommercial）；
- 禁止再分发经过 remix / transform / build upon 的材料（NoDerivatives）。Deed 脚注还有一句：「Merely changing the format never creates a derivative。」格式转换是否构成派生、权重是否构成派生，属于法律判断，**本文不下结论**。

对本课题的实务含义（与方案 v3 已有决定一致，供遵守而非法律建议）：数据只用于本科非商业科研；论文与开题须引用原论文并注明许可；**不要再分发图像、标注或自行转换后的 YOLO 标签包**；自己写转换脚本、把结果留在本机或项目约定的存储位置，不把转换结果公开挂到仓库。ND 与「内部转换自用」如何解释，如有疑问应问导师或学校。

### 5.2 必须使用的引用

官方主页给出的 BibTeX：

```
@inproceedings{yang2016wider,
  Author = {Yang, Shuo and Luo, Ping and Loy, Chen Change and Tang, Xiaoou},
  Booktitle = {IEEE Conference on Computer Vision and Pattern Recognition (CVPR)},
  Title = {WIDER FACE: A Face Detection Benchmark},
  Year = {2016}
}
```

论文开放获取页：https://openaccess.thecvf.com/content_cvpr_2016/html/Yang_WIDER_FACE_A_CVPR_2016_paper.html（页码 5525–5533）。arXiv：https://arxiv.org/abs/1511.06523 。

若报告检测数字并与 YOLO5Face 对比，应同时引用 Qi 等 2021（arXiv:2105.12931）。若实际使用了 wondervictor 代码作对照，应在实验细节中标明仓库 URL 与许可（MIT），不要把它写成官方工具。

### 5.3 评价工具的许可

官方结果页只提供 zip 下载，未在网页上另写评价脚本的许可证。**未下载、未解压，故官方 MATLAB 代码的许可未核实。** 使用时至少应保留官方来源 URL 与文件元数据，并遵守数据集的非商业与署名要求；是否允许把 `eval_tools` 源码再分发到本项目公开仓库，**未核实，建议先不要把该 zip 或解出的 mat/脚本推进公开 GitHub。**

wondervictor 的 MIT 许可只覆盖其 Python 代码（及注明来自 Fast R-CNN、Sergey Karayev 的 `box_overlaps.pyx`），**不能**用来再分发官方 mat 真值或 WIDER 图像。

---

## 6. 未核实或需标明限度的事项

1. 官方 `eval_tools.zip` 的 SHA-256、解压后完整文件列表、是否含 LICENSE/README 原文、`wider_eval.m` 等源码的比较符（`>` 还是 `>=`）与是否在读取预测时排序：**未打开压缩包，未核实。** `wider_eval.m`、`read_pred.m`、`norm_score.m`、`evaluation.m` 等文件名来自第三方转述。
2. http://shuoyang1213.me/WIDERFACE/ 在部分网络（含本次本机出口）返回 HTTP 500；主页正文来自外部抓取，与 CUHK 跳转页、结果页互证。该域在其他网络或日后是否稳定，需在 RN-3 下载前再测。
3. 官方主页列出的 Google Drive / Tencent Drive / Hugging Face 的**逐条 URL 与文件 ID**，未能从本机保存的官方 HTML 完整抄出。TFDS 记录的 Drive ID（训练 `15hGDLhsx8bLgLcIRD5DhYt5iBxnjNF1M`、验证 `1GUCogbp16PMGa39thoMMeWxp7Rp5oM8Q`、测试 `1HIfDbVEWKmsYKJZm4lchTBDLW5N7dY5T`、标注 `1sAl2oml7hK6aZRdgRjqQJsjV5CEr7nl4`）只是第三方脚本中的历史记录，**本日未逐一打开 Drive 页核实是否仍有效**。
4. 事件类数量：官方主页与 HF 卡片为 **61**，CVPR/arXiv 论文为 **60**。Released 目录是否恰为 61 个事件文件夹，未下载数据，未直接数。Python 移植处理进度条常见为 61 个事件。
5. Easy/Medium/Hard 名单是否严格嵌套（Hard 包含 Medium 与 Easy）：WIDER 原论文未写死；后继论文常这样描述。未打开 mat，未核实。
6. 官方 MATLAB 与 wondervictor Python 在同一组预测上是否给出相同 AP：**本次未跑评测，未核实。** 已知排序问题会导致 Python 结果偏离。
7. YOLO5Face Table 4 的验证集数字是否曾用官方 MATLAB 复核：论文未说明，**未核实**。
8. **测试集邮件提交在 2026 年是否仍被受理、作者是否仍返回分数：未核实。** 官方评测服务器未见上线。
9. 官方 License 未写 CC 版本号；4.0 仅见于 HF 卡片。
10. 官方评价工具自身的版权/许可证：**未核实。**
11. `wider_face_split/readme.txt` 以第三方副本引述，未与官方 zip 字节比对。
12. 图像包、标注包、评价包的 SHA-256 与解压后体积：方案 v3 中 train+val 约 1.71 GiB 常驻、峰值约 3.4 GiB 是既有登记，**本次未下载，未重测。** 测试集约占多少磁盘，未核实；清单已提示「不默认必须下载 test 图像」。

---

## 7. 来源列表（均于 2026-11-16、UTC+8 / Asia/Shanghai 访问）

官方站点与工具（网页或 HEAD，未下载 zip/pdf 正文）：

- http://shuoyang1213.me/WIDERFACE/ — 数据集主页（正文经外部抓取；本机 HTTP 500）
- https://mmlab.ie.cuhk.edu.hk/projects/WIDERFace/ — 历史入口，跳转到上一地址
- https://mmlab.ie.cuhk.edu.hk/projects/WIDERFace/WiderFace_Results.html — 官方结果与评价说明
- https://mmlab.ie.cuhk.edu.hk/projects/WIDERFace/support/eval_script/eval_tools.zip — 官方评价工具（仅 HEAD）
- https://mmlab.ie.cuhk.edu.hk/projects/WIDERFace/support/example/Submission_example.zip — 提交示例（仅 HEAD）
- https://mmlab.ie.cuhk.edu.hk/projects/WIDERFace/support/bbx_annotation/wider_face_split.zip — 文本划分/标注（仅 HEAD）
- https://mmlab.ie.cuhk.edu.hk/projects/WIDERFace/support/paper.pdf — 官方论文 PDF（仅 HEAD）

论文与许可：

- https://arxiv.org/abs/1511.06523 、 https://arxiv.org/html/1511.06523 — WIDER FACE 论文
- https://openaccess.thecvf.com/content_cvpr_2016/html/Yang_WIDER_FACE_A_CVPR_2016_paper.html — CVPR 2016 开放获取记录（5525–5533 页）
- https://arxiv.org/abs/2105.12931 、 https://arxiv.org/html/2105.12931v2 — YOLO5Face 论文
- https://huggingface.co/datasets/CUHK-CSE/wider_face — 规模、划分、CC BY-NC-ND 4.0 卡片
- https://huggingface.co/datasets/CUHK-CSE/wider_face/blob/main/README.md — 同上，含 YAML `license: cc-by-nc-nd-4.0`
- https://creativecommons.org/licenses/by-nc-nd/4.0/deed.en 与 https://creativecommons.org/licenses/by-nc-nd/4.0/legalcode — CC BY-NC-ND 4.0

非官方评测实现与说明：

- https://github.com/wondervictor/WiderFace-Evaluation — Python 移植（MIT）
- https://raw.githubusercontent.com/wondervictor/WiderFace-Evaluation/master/README.md
- https://raw.githubusercontent.com/wondervictor/WiderFace-Evaluation/master/evaluation.py
- https://raw.githubusercontent.com/wondervictor/WiderFace-Evaluation/master/box_overlaps.pyx
- https://raw.githubusercontent.com/wondervictor/WiderFace-Evaluation/master/LICENSE
- https://github.com/wondervictor/WiderFace-Evaluation/issues/3 — 预测格式
- https://github.com/deepcam-cn/yolov5-face — YOLO5Face 代码与 README 评测步骤
- https://raw.githubusercontent.com/deepcam-cn/yolov5-face/master/README.md
- https://github.com/deepcam-cn/yolov5-face/issues/287 — 预测排序影响 Python AP
- https://github.com/xiyinmsu/python-wider_eval — 另一 Python 移植
- https://paddledetection.readthedocs.io/featured_model/FACE_DETECTION_en.html — 官方 MATLAB 调用步骤的第三方说明
- https://github.com/vitoralbiero/img2pose/issues/8 — `wider_eval.m` 用法转述
- https://github.com/akofman/wider-face-pascal-voc-annotations/blob/master/wider_face_split/readme.txt — 官方标注 readme 的第三方副本
- https://github.com/tensorflow/datasets/blob/master/tensorflow_datasets/object_detection/wider_face.py — 标注文件名与历史 Drive ID（第三方）

本项目已有文档（只读，非网络来源）：

- `/workspace/AgeMorph3D/docs/后续任务清单.md`（D02、E03）
- `/workspace/AgeMorph3D/docs/数据资源清单.md`
- `/workspace/AgeMorph3D/docs/实验协议.md`
- `/workspace/AgeMorph3D/docs/experiment-protocol-v1.json`
- `/workspace/AgeMorph3D_数据集方案_v3.md` §2-E
- `/workspace/AgeMorph3D_后续任务规划_v2.md` RD-6 行
- `/workspace/AgeMorph3D_tasks/FG-1_说明.md`
