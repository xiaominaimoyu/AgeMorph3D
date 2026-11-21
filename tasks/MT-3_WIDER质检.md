# MT-3 WIDER FACE 分布与质检报告

- 作者：Metric（数据分析师）
- 撰写时间：2026-11-21 16:15（UTC+8）；FG-1 正式转换运行于 2026-11-21 16:00:47—16:01:00（UTC+8，取自 report.json 的 `recorded_at_utc`）
- 状态：**待 Sentinel 审核**
- 任务来源：规划 v2 第 119 行 MT-3（“排除率、各划分数量和磁盘占用都是实测值；没有 null 冒充 0”）；派发人 Atlas
- 数据：`/workspace/datasets/wider_face`（只读；RN-3 下载并解压，压缩包已按用户决定删除）
  - 标注：`extracted/wider_face_split/files/wider_face_split/`
  - 图片：`extracted/WIDER_train/files/WIDER_train/images/`、`extracted/WIDER_val/files/WIDER_val/images/`
- FG-1：`/workspace/AgeMorph3D_forge`，当前分支 `feat/wider-converter`（`git branch --show-current` 确认，未切换），提交 **`688bc092d60b4c2bd08a4d55d98be7aed8ec8e87`**（`688bc09`）。以 `git archive 688bc09` 导出到 `/tmp/MT-3/forge_688bc09/` 运行，没有在原工作树里执行任何代码
- 脚本与中间结果：`/tmp/MT-3/scripts/`（统计脚本）、`/tmp/MT-3/out/`（汇总 JSON、逐框/逐图 CSV、绘图用 CSV）、`/tmp/MT-3/root/output/research/wider-{train,val}-v1/`（FG-1 原样输出）、`/tmp/MT-3/logs/`（运行与测试日志）
- 范围：只做数值和元数据层面的统计与抽查；**本报告不含任何成品图**，第 9 节只给图表规格（任务书要求图表由学生自己画）

> 用语约定：“框”= bbx_gt.txt 里声明的一行人脸标注；“有效框”= `invalid=0` 的框；“缺失/null”表示该字段不存在，单独计数，不等于 0。

## 1. 结论摘要

1. **数量全部与据称一致**：train 12,880 张 / 159,420 个框；val 3,226 张 / 39,708 个框；test 只有文件清单 16,097 张（无框，图片未下载）。三者合计 32,203 张，与论文一致。标注引用的图片全部存在，磁盘上也没有无标注的图片。
2. **磁盘占用**（du 实测）：解压后图片 train 1,474,029,628 B（1.37 GiB），val 365,054,675 B（348 MiB），标注目录 9,100,296 B；数据集目录合计 1,854,324,541 B（字节和）/ 1,888,813,056 B（分配块）。
3. **FG-1 默认规则排除率**：train 2,491/159,420 = **1.563%**（invalid 2,399，退化框 27，整图失败带走 65）；val 596/39,708 = **1.501%**（invalid 585，退化框 11）。各规则之间**没有重叠**。
4. **FG-1 规则实测**：
   - invalid 丢弃：触发 2,399 + 585 次，抽查 6 例全部正确。
   - 越界裁剪：**部分越界的框为 0**，裁剪触发 0 次。仅有的 2 个越界框是 w=0 的退化框，按退化框丢弃。
   - EXIF：**16,106 张全部没有 EXIF**（Pillow 读取和原始字节扫描两种方法都是 0），方向规则触发 0 次。Orientation 字段全部为“缺失/null”，不是 1。
   - 右边界取 `x1+w`：真实数据支持该约定（0 起算，w 为像素数），**不应改为 `x1+w-1`**（理由见 6.4）。
5. **发现的 FG-1 问题**：
   - **(a) 超长图被拒，train 运行状态变为 failed**：train 有 1 张 1024×9108 的图触发 `RASTER_SIZE_LIMIT`（边长上限 8192），图上 65 个框全部未处理。这条行为不在 FG-1 说明的规则表里，并让 train 运行状态为 `failed`、退出码 1。
   - **(b) 8 张“无框”图被写成空标签**：train 4 张声明 0 框，val 4 张声明 1 框但该行全为 0。FG-1 都写成空标签，即 YOLO 负样本。我自查目视发现其中有图明显含人群或人脸。
   - **(c) 重复行原样写出**：3 组完全相同的重复标注行（train 2 组、val 1 组）原样写成重复的 YOLO 行。
   - **(d) 收紧 blur 风险很大**：如果把 `--max-blur` 收紧到 1，会丢 61% 的框，并让 train 904 张、val 244 张图变成空标签。
6. **其他数据异常**：
   - 3 组字节完全相同的图片，其中 1 组跨 train/val，而且两边标注不同。
   - bbx_gt.txt 把 .mat 里 3 个负宽度框截成了 w=0。
   - 有 1 px 宽的有效框：train 6 个，val 0 个。
7. **P06**：补上了 WIDER 部分的划分数量、质量分布、排除率、原图/归档/派生体积、转换耗时/吞吐/峰值内存。年龄、身份、推理耗时、显存、训练工时仍为 null（WIDER 没有年龄和身份标注，后几项本任务也没测），见第 8 节。
8. **FG-1 自带测试**：`test_wider_annotations.py` 97 passed；后端全量 3103 passed / 3 skipped / 1 warning，与 FG-1 说明一致。

## 2. 方法与口径

### 2.1 环境

- Python 3.11.16、Pillow 13.0.0：`/workspace/.venvs/agemorph-forge-31116`，即 FG-1 说明里的同一个 venv。
- 比对 .mat 用 SciPy 1.17.1 和 NumPy 2.4.6，用 `uv pip install --target /tmp/MT-3/pylib` 装在 /tmp，没有装进 venv。
- 所有 python 都加 `-B` 并设置 `PYTHONDONTWRITEBYTECODE=1`。
- pytest 加 `-p no:cacheprovider --basetemp=/tmp/MT-3/pytest/...`。

### 2.2 FG-1 的运行方式

FG-1 要求 `--root` 下同时放数据和 `output/research/` 输出，而数据目录只读。因此把三个解压目录用 `cp -r` 复制到 `/tmp/MT-3/root/data/`，再在其中运行 FG-1。

- **复制件与原件一致**：字节和逐一相同（train 1,474,029,628 / val 365,054,675 / split 9,100,296）。FG-1 自己也对每张图算了 SHA-256，并在结束时复核，`inputs_stable=true`。
- **命令**（另一个划分同理）：

```bash
cd /tmp/MT-3/forge_688bc09
PYTHONDONTWRITEBYTECODE=1 /workspace/.venvs/agemorph-forge-31116/bin/python -B -m preprocessing.wider_annotations \
  --root /tmp/MT-3/root --gt data/wider_face_split/wider_face_train_bbx_gt.txt \
  --gt-sha256 753a8c0591cc570a793bb7fd2de4db6e5357bb1abbe863d8739d586369e32d9d \
  --images-dir data/WIDER_train/images --split train --output-dir output/research/wider-train-v1
```

- 默认 `--max-blur 2`。`--max-blur 1/0` 只在 val 上另跑过一次，用来核对我的独立计算，跑完即删除输出。

### 2.3 独立统计

统计脚本（附录 A）**不复用 FG-1 的解析器**：

- 自己解析 bbx_gt.txt，再用 Pillow 只读文件头，得到宽高、格式、EXIF，不解码像素。
- 另用原始字节扫描 `Exif\0\0` APP1 段，交叉验证 EXIF。
- 把 FG-1 的逐框 decision/reason 按 (图片, 框序号) 拼接回来对照。

### 2.4 尺度分档

按论文原文的高度分档，补一个 `<10` 档和一个退化档。区间左闭右开：`≤0`、`[0,10)`、`[10,50)`、`[50,300)`、`[300,∞)`。宽度和 √(w·h) 用同一组边界，作补充参考。论文原文（arXiv:1511.06523v1，第 3.2 节；PDF 于本次下载到 `/tmp/MT-3/widerface_paper.pdf` 核对）：

> “Scale. We group the faces by their image size (height in pixels) into three scales: small (between 10-50 pixels), medium (between 50-300 pixels), large (over 300 pixels).”

> “we assign an ’Ignore’ flag to the face which is very difficult to be recognized due to low resolution and small scale (10 pixels or less).”

### 2.5 磁盘口径

- **字节和**：`find -type f -printf %s` 累加。
- **du -sb**：apparent size。
- **du -s -B1**：分配块，文件系统块大小 4096 B。
- GiB/MiB 均按 1024 进制。

## 3. 各划分数量与磁盘占用

### 3.1 数量（实测 vs 据称）

| 项目 | train | val | test |
|---|---:|---:|---:|
| 据称图片数 | 12,880 | 3,226 | —（任务未给） |
| bbx_gt.txt 图片条目 | 12,880 | 3,226 | 无 bbx_gt（只有 `wider_face_test_filelist.txt`：16,097 行，不重复） |
| 磁盘 jpg 文件 | 12,880 | 3,226 | **未下载**（RN-3 授权范围不含 WIDER_test.zip） |
| 标注引用但磁盘不存在 | 0 | 0 | — |
| 磁盘存在但无标注 | 0 | 0 | — |
| .mat 中图片数（`wider_face_{split}.mat`） | 12,880 | 3,226 | 16,097（`wider_face_test.mat` 只有 event_list/file_list，无框） |
| 事件目录 | 61 | 61 | 61 |
| 声明框数（bbx_gt.txt 计数行之和） | **159,420** | **39,708** | 无（官方不公开 test 框） |
| .mat 中框行数 | 159,424 | 39,708 | — |
| 每图声明框数：均值 / 中位 / 最大 | 12.38 / 3 / 1,968 | 12.31 / 3 / 709 | — |

说明：

- train 的 .mat 比 txt 多 4 行，正好是 4 张 0 框图在 .mat 里各存了一行全零占位（见 7.1）。
- train+val+test = 12,880+3,226+16,097 = **32,203** 张，与论文“32,203 images”一致；train+val 共 199,128 个声明框（含 invalid）。
- 事件目录编号为 0—59 和 61（没有 60），共 61 个；论文正文写“60 event categories”，两者不一致，这里只记录不展开。
- 所有图片都是 JPEG、RGB，宽一律 1024 px。高度范围：train 171—9,108 px，val 218—5,541 px；中位数 train 760、val 754。

**test 划分**：官方只发布文件清单，不发布框（RD-6 已写明 test 结果要提交官方评测）。test 图片不在 box 上，本报告的所有分布和排除率都**不包括 test**，也不能把 test 写成“0 框”。

### 3.2 磁盘占用（2026-11-21 16:0x UTC+8 实测）

| 对象 | 文件数 | 字节和 (B) | du -sb (B) | du -s -B1 分配 (B) | du -sh |
|---|---:|---:|---:|---:|---:|
| train 图片 `WIDER_train/files/WIDER_train/images` | 12,880 | 1,474,029,628 | 1,474,029,628 | 1,501,511,680 | 1.4G |
| val 图片 `WIDER_val/files/WIDER_val/images` | 3,226 | 365,054,675 | 365,054,675 | 371,990,528 | 355M |
| 标注 `wider_face_split/files/wider_face_split` | 7 | 9,100,296 | 9,100,296 | 9,121,792 | 8.7M |
| 数据集根 `/workspace/datasets/wider_face`（含 3 份 members.json 共 6,139,942 B，以及空的 archives/） | 16,116 | 1,854,324,541 | 1,854,324,541 | 1,888,813,056 | 1.8G |

标注目录 7 个文件的字节数：

| 文件 | 字节数 |
|---|---:|
| `wider_face_train_bbx_gt.txt` | 4,947,163 |
| `wider_face_val_bbx_gt.txt` | 1,231,252 |
| `wider_face_train.mat` | 1,554,123 |
| `wider_face_val.mat` | 397,768 |
| `wider_face_test.mat` | 91,674 |
| `wider_face_test_filelist.txt` | 877,727 |
| `readme.txt` | 589 |

SHA-256：

| 文件 | SHA-256 |
|---|---|
| train bbx_gt | `753a8c0591cc570a793bb7fd2de4db6e5357bb1abbe863d8739d586369e32d9d` |
| val bbx_gt | `5ca83488f72758ca4826c35212610a8abf04a7af7b17eb407d6284007baba3b6` |
| readme | `5502e4b579091704264cc869178adc608660e664f1dbc2f47b0761e74c3de35b` |

**归档（zip）大小**：压缩包已于 2026-11-21 15:54:58—15:54:59（UTC+8）删除，**本次无法再 du**。下表数值取自 RN-3 回执（下载时实测，SHA-256 与 HF LFS 元数据互证），只引用、不复测：

| 压缩包 | 字节数 |
|---|---:|
| WIDER_train.zip | 1,465,602,149 |
| WIDER_val.zip | 362,752,168 |
| wider_face_split.zip | 3,591,642 |
| 合计 | 1,831,945,959（RN-3 记录的下载期峰值约 3.43 GiB apparent） |

**派生物（FG-1 输出，`/tmp/MT-3/root/output/research/`）**：

| 输出 | train | val |
|---|---:|---:|
| YOLO 标签文件数 | 12,879（少的 1 个是失败图） | 3,226 |
| 标签字节和 | 5,963,302 B | 1,486,256 B |
| 标签分配块（小文件按 4 KiB 计） | 55,582,720 B | 13,950,976 B |
| K5 `manifest.json` | 11,339,063 B（K5 上限 16 MiB 的 67.6%） | 2,821,203 B |
| `audit.json` | 7,405,129 B | 1,824,839 B |
| `report.json` | 123,160,904 B（上限 512 MiB） | 30,644,308 B |
| 输出目录合计 du -sb | 147,868,398 B | 36,776,606 B |
| 输出目录合计分配块 | 197,496,832 B | 49,250,304 B |

## 4. 分布统计（train / val 分列）

### 4.1 标注取值含义（readme.txt 原文，取自本次解压的官方 zip）

```text
Attached the mappings between attribute names and label values.

blur:
  clear->0
  normal blur->1
  heavy blur->2

expression:
  typical expression->0
  exaggerate expression->1

illumination:
  normal illumination->0
  extreme illumination->1

occlusion:
  no occlusion->0
  partial occlusion->1
  heavy occlusion->2

pose:
  typical pose->0
  atypical pose->1

invalid:
  false->0(valid image)
  true->1(invalid image)

The format of txt ground truth.
File name
Number of bounding box
x1, y1, w, h, blur, expression, illumination, invalid, occlusion, pose
```

（RD-6 当时引用的是第三方副本，并注明“未与官方 zip 字节比对”。本次文本来自官方 zip 解压件，SHA-256 `5502e4b5…`，字节 589，可以补上这一核对。）

论文对属性的补充定义（第 3.2 节原文）：

- occlusion：“A face is defined as ‘partially occluded’ if 1%-30% of the total face area is occluded. A face with occluded area over 30% is labeled as ‘heavily occluded’.”
- pose：“Face is annotated as atypical under two conditions: either the roll or pitch degree is larger than 30-degree; or the yaw is larger than 90-degree.”

readme 与论文都**没有**给出 blur、expression、illumination 的判定标准；readme 也没有说明坐标是从 0 还是从 1 起算、右端点是否包含在框内。readme 把 invalid 写成“invalid image”，但它实际是逐框字段。

**属性字段的缺失/null**：train 和 val 的所有框都是完整的 10 个整数，没有缺失或 null；取值全部在 readme 规定的范围内（FG-1 严格解析也没有触发 `GT_ATTRIBUTE_OUT_OF_RANGE`）。

### 4.2 属性分布

| 属性 | 取值 | readme 含义 | train 全部框 | train 有效框(invalid=0) | val 全部框 | val 有效框(invalid=0) |
|---|---:|---|---:|---:|---:|---:|
| invalid | 0 | false (valid image) | 157,021（98.50%） | — | 39,123（98.53%） | — |
| invalid | 1 | true (invalid image) | 2,399（1.50%） | — | 585（1.47%） | — |
| blur | 0 | clear | 22,791（14.30%） | 21,345（13.59%） | 5,686（14.32%） | 5,369（13.72%） |
| blur | 1 | normal blur | 40,811（25.60%） | 40,808（25.99%） | 10,381（26.14%） | 10,381（26.53%） |
| blur | 2 | heavy blur | 95,818（60.10%） | 94,868（60.42%） | 23,641（59.54%） | 23,373（59.74%） |
| occlusion | 0 | no occlusion | 95,860（60.13%） | 94,147（59.96%） | 23,812（59.97%） | 23,434（59.90%） |
| occlusion | 1 | partial occlusion | 27,830（17.46%） | 27,603（17.58%） | 7,185（18.09%） | 7,099（18.15%） |
| occlusion | 2 | heavy occlusion | 35,730（22.41%） | 35,271（22.46%） | 8,711（21.94%） | 8,590（21.96%） |
| pose | 0 | typical pose | 153,378（96.21%） | 151,029（96.18%） | 38,053（95.83%） | 37,486（95.82%） |
| pose | 1 | atypical pose | 6,042（3.79%） | 5,992（3.82%） | 1,655（4.17%） | 1,637（4.18%） |
| expression | 0 | typical expression | 157,575（98.84%） | 155,177（98.83%） | 39,308（98.99%） | 38,723（98.98%） |
| expression | 1 | exaggerate expression | 1,845（1.16%） | 1,844（1.17%） | 400（1.01%） | 400（1.02%） |
| illumination | 0 | normal illumination | 151,286（94.90%） | 148,955（94.86%） | 37,410（94.21%） | 36,843（94.17%） |
| illumination | 1 | extreme illumination | 8,134（5.10%） | 8,066（5.14%） | 2,298（5.79%） | 2,280（5.83%） |

百分比的分母：“全部框”为该划分的声明框总数（train 159,420、val 39,708）；“有效框”为 invalid=0 的框数（train 157,021、val 39,123）。

train 与 val 的各属性占比相差都在 1 个百分点以内。

invalid=1 框的其他属性分布明显不同：

- blur：train 中 blur=0 有 1,446 个（60.3%），blur=1 只有 3 个；val 中 blur=0 有 317 个，blur=1 为 0。
- 其余属性也多为 0。

我推测这是“未细标时的默认值”，但标注说明没有写，**这只是推测**，不应把 invalid 框的属性当作真实的清晰度统计。

### 4.3 尺度分布

| 口径 | 分档 | train 全部 | train 有效 | train invalid | val 全部 | val 有效 | val invalid |
|---|---|---:|---:|---:|---:|---:|---:|
| 高度 h | ≤0（退化） | 12（0.01%） | 12（0.01%） | 0（0.00%） | 6（0.02%） | 6（0.02%） | 0（0.00%） |
| 高度 h | <10 | 26,362（16.54%） | 24,087（15.34%） | 2,275（94.83%） | 6,898（17.37%） | 6,353（16.24%） | 545（93.16%） |
| 高度 h | 10-50 | 104,777（65.72%） | 104,653（66.65%） | 124（5.17%） | 25,475（64.16%） | 25,435（65.01%） | 40（6.84%） |
| 高度 h | 50-300 | 26,398（16.56%） | 26,398（16.81%） | 0（0.00%） | 6,890（17.35%） | 6,890（17.61%） | 0（0.00%） |
| 高度 h | ≥300 | 1,871（1.17%） | 1,871（1.19%） | 0（0.00%） | 439（1.11%） | 439（1.12%） | 0（0.00%） |
| 宽度 w | ≤0（退化） | 19（0.01%） | 19（0.01%） | 0（0.00%） | 9（0.02%） | 9（0.02%） | 0（0.00%） |
| 宽度 w | <10 | 43,262（27.14%） | 40,887（26.04%） | 2,375（99.00%） | 10,887（27.42%） | 10,307（26.35%） | 580（99.15%） |
| 宽度 w | 10-50 | 95,929（60.17%） | 95,905（61.08%） | 24（1.00%） | 23,552（59.31%） | 23,547（60.19%） | 5（0.85%） |
| 宽度 w | 50-300 | 19,176（12.03%） | 19,176（12.21%） | 0（0.00%） | 5,009（12.61%） | 5,009（12.80%） | 0（0.00%） |
| 宽度 w | ≥300 | 1,034（0.65%） | 1,034（0.66%） | 0（0.00%） | 251（0.63%） | 251（0.64%） | 0（0.00%） |
| √(w·h) | ≤0（退化） | 27（0.02%） | 27（0.02%） | 0（0.00%） | 11（0.03%） | 11（0.03%） | 0（0.00%） |
| √(w·h) | <10 | 38,367（24.07%） | 35,975（22.91%） | 2,392（99.71%） | 9,830（24.76%） | 9,247（23.64%） | 583（99.66%） |
| √(w·h) | 10-50 | 97,809（61.35%） | 97,802（62.29%） | 7（0.29%） | 23,847（60.06%） | 23,845（60.95%） | 2（0.34%） |
| √(w·h) | 50-300 | 21,859（13.71%） | 21,859（13.92%） | 0（0.00%） | 5,701（14.36%） | 5,701（14.57%） | 0（0.00%） |
| √(w·h) | ≥300 | 1,358（0.85%） | 1,358（0.86%） | 0（0.00%） | 319（0.80%） | 319（0.82%） | 0（0.00%） |

百分比的分母分别是该列的框数：train 全部 159,420 / 有效 157,021 / invalid 2,399；val 全部 39,708 / 有效 39,123 / invalid 585。

有效框的宽高分位数（不含 ≤0 的退化框；分位数取最近秩）：

| 有效框 | 最小 | P25 | 中位 | P75 | P95 | 最大 |
|---|---:|---:|---:|---:|---:|---:|
| train 高 h | 1 | 12 | 20 | 38 | 126 | 1,289 |
| train 宽 w | 1 | 9 | 16 | 30 | 94 | 976 |
| val 高 h | 1 | 12 | 20 | 39 | 126 | 1,224 |
| val 宽 w | 2 | 9 | 16 | 31 | 95 | 1,008 |

要点：

- invalid 框几乎全是极小脸：train 中 h<10 的占 94.8%，√(w·h)<10 的占 99.7%。这与论文“10 pixels or less 赋 Ignore”的描述相符；但 readme 的 invalid 字段是否就是论文的 Ignore，标注说明没有写明。
- **有效框里仍有 train 24,087 个、val 6,353 个高度 <10 px 的框**，FG-1 默认会保留它们。
- 宽度 <5 px 的有效非退化框：train 4,037 个，val 1,168 个。宽度恰为 1 px 的：train 6 个，val 0 个。

### 4.4 每图框数分布

| 每图声明框数 | train 图片数 | val 图片数 |
|---|---:|---:|
| 0 | 4 | 0 |
| 1 | 4,631 | 1,122 |
| 2–5 | 3,804 | 981 |
| 6–10 | 1,538 | 399 |
| 11–50 | 2,335 | 582 |
| 51–100 | 326 | 83 |
| >100 | 242 | 59 |

## 5. 按 FG-1 规则的排除率（默认 `--max-blur 2`）

FG-1 判定顺序（代码 `convert_faces`）：

1. invalid=1 → `INVALID_FLAG`；
2. blur > max_blur → `BLUR_ABOVE_POLICY`；
3. w≤0 或 h≤0 → `DEGENERATE_BOX`；
4. 裁剪后无面积 → `OUT_OF_FRAME`。

此外，整图失败（读图失败、超尺寸、EXIF≠1 等）时，该图所有框记为 `not_processed`，不写标签。

下表“原始条件”列按条件本身独立计数，不受判定顺序影响，用来检查规则之间的重叠。

### 5.1 框级

| 规则 | train 框 | train 占全部框 | val 框 | val 占全部框 |
|---|---:|---:|---:|---:|
| invalid=1（`INVALID_FLAG`） | 2,399 | 1.505% | 585 | 1.473% |
| w≤0 或 h≤0（`DEGENERATE_BOX`） | 27 | 0.017% | 11 | 0.028% |
| 非退化但完全在画幅外（`OUT_OF_FRAME`） | 0 | 0 | 0 | 0 |
| 部分越界、裁剪后保留（不排除，`clipped=true`） | 0 | 0 | 0 | 0 |
| 整图失败带走（`not_processed`，`RASTER_SIZE_LIMIT`） | 65 | 0.041% | 0 | 0 |
| 重叠：invalid∩退化 / invalid∩整图失败 / 退化∩整图失败 | 0 / 0 / 0 | — | 0 / 0 / 0 | — |
| **合计排除（并集）** | **2,491** | **1.563%** | **596** | **1.501%** |
| 写入 YOLO 标签的框 | 156,929 | 98.437% | 39,112 | 98.499% |

- FG-1 的 report.json 汇总与上表逐项一致：train 为 kept 156,929 / INVALID_FLAG 2,399 / DEGENERATE_BOX 27 / not_processed 65 / clipped 0；val 为 39,112 / 585 / 11 / 0 / 0。
- 本表里的 0 都是实测计数为 0，不是缺失。
- train+val 合计排除 3,087/199,128 = 1.550%。

### 5.2 图级

| 规则 | train 图 | train 占比 | val 图 | val 占比 |
|---|---:|---:|---:|---:|
| 含 ≥1 个 invalid 框 | 447 | 3.470% | 134 | 4.154% |
| 含 ≥1 个退化框 | 23 | 0.179% | 9 | 0.279% |
| 同一图既有 invalid 又有退化框 | 7 | — | 2 | — |
| 整图失败（不写标签） | 1 | 0.008% | 0 | 0 |
| **含 ≥1 个被排除框（并集）** | **464** | **3.602%** | **141** | **4.371%** |
| 转换后为空标签（负样本） | 4（全是声明 0 框的图） | — | 4（全是“声明 1 框且该行全 0”的图） | — |
| 其中因 invalid 丢光所有框而变空 | 0 | — | 0 | — |

### 5.3 收紧 blur 的情景（FG-1 支持 `--max-blur 1/0`，默认不用）

| 情景 | train 排除框（占比） | train 空标签图 | val 排除框（占比） | val 空标签图 |
|---|---:|---:|---:|---:|
| `--max-blur 1`（丢 heavy blur） | 97,334（61.06%） | 904（7.02%） | 23,965（60.35%） | 244（7.56%） |
| `--max-blur 0`（只留 clear） | 138,100（86.63%） | 4,807（37.32%） | 34,343（86.49%） | 1,167（36.18%） |

- val 两个情景我用 FG-1 实跑过：`--max-blur 1` 保留 15,743 个框（`BLUR_ABOVE_POLICY` 23,373、`DEGENERATE_BOX` 7、`INVALID_FLAG` 585），`--max-blur 0` 保留 5,365 个框；空标签图分别为 244 和 1,167。全部与上表的独立计算一致。
- train 的这两行是独立计算的结果，没有用 FG-1 实跑。
- 退化框在这两个情景下减少，是因为有的退化框先被 blur 规则判掉了；这是判定顺序造成的，不是框数变了。

## 6. 用真实数据检验 FG-1 自定的规则

抽查规则：每条规则以 `random.Random("20261121:<规则名>")` 从触发集合中无放回抽样，集合不够就全取。抽查只比对数值和元数据，没有生成任何叠框图。

### 6.1 invalid 丢弃

- **触发次数**：train 2,399 框 / 447 图；val 585 框 / 134 图。
- **结论**：规则执行正确。抽查 6 例全部为 `dropped / INVALID_FLAG`，没有写入标签；全量逐框比对也没有发现 invalid 框进入标签。

| # | 划分 | 文件 | gt 行 | 原始标注（x1 y1 w h blur expr illum invalid occl pose） | FG-1 结果 |
|---|---|---|---:|---|---|
| 1 | train | 8--Election_Campain/8_Election_Campain_Election_Campaign_8_531.jpg | 180580 | 191 707 9 10 0 0 0 1 1 0 | dropped, INVALID_FLAG |
| 2 | train | 2--Demonstration/2_Demonstration_Demonstrators_2_371.jpg | 60985 | 101 223 5 6 0 0 0 1 0 0 | dropped, INVALID_FLAG |
| 3 | train | 0--Parade/0_Parade_marchingband_1_388.jpg | 4802 | 341 164 4 4 0 0 0 1 0 0 | dropped, INVALID_FLAG |
| 4 | train | 8--Election_Campain/8_Election_Campain_Election_Campaign_8_320.jpg | 182410 | 145 244 4 6 0 0 0 1 0 0 | dropped, INVALID_FLAG |
| 5 | val | 35--Basketball/35_Basketball_basketballgame_ball_35_216.jpg | 32337 | 6 408 4 6 2 0 0 1 2 0 | dropped, INVALID_FLAG |
| 6 | train | 12--Group/12_Group_Team_Organized_Group_12_Group_Team_Organized_Group_12_864.jpg | 35965 | 987 551 4 5 0 0 0 1 0 0 | dropped, INVALID_FLAG |

**需要注意（不是 FG-1 的错误，而是策略风险）**：被丢弃的 invalid 框在 YOLO 训练里没有忽略区域，会被当成背景。官方评测把这类框作为“忽略”，匹配到既不算 TP 也不算 FP（RD-6 第 97—99 行）。这些框 94.8% 的高度 <10 px，影响有限，但 T02 是否需要做忽略掩码，留给 T02/E01 决定。

### 6.2 越界裁剪

| 检查 | train | val |
|---|---:|---:|
| x1<0 / y1<0 | 0 / 0 | 0 / 0 |
| x1+w > W | 1（w=0 的退化框） | 1（w=0 的退化框） |
| y1+h > H | 0 | 0 |
| 部分越界、需要裁剪的非退化框 | **0** | **0** |
| FG-1 `faces_clipped` | 0 | 0 |
| 恰好贴右边（x1+w = W），保留不裁 | 749 | 188 |
| 恰好贴下边（y1+h = H） | 313 | 95 |
| x1 = 0 / y1 = 0 | 688 / 575 | 213 / 186 |

**结论**：在官方 bbx_gt.txt 上，“部分越界则裁剪”这条规则**实际触发 0 次**，所以只能由合成测试保证它的正确性。

两个 `x1+w>W` 的框都是 w=0、x1>W 的退化框，FG-1 先判退化，因此记为 `DEGENERATE_BOX`，没有进入裁剪分支，结果正确。

- `54--Rescue/54_Rescue_rescuepeople_54_29.jpg` 第 161871 行：`1050 142 0 50 2 0 0 0 1 0`，图宽 1024
- `39--Ice_Skating/39_Ice_Skating_iceskiing_39_583.jpg`（val）第 34471 行：`1026 474 0 23 2 0 0 0 2 0`，图宽 1024

贴边框抽查 6 例（全部 kept、`clipped=false`，右边界正好是 1024）：

| # | 文件（train） | gt 行 | 原始 x1 y1 w h | 图宽高 | FG-1 裁剪后 xyxy 边界 | YOLO（cx cy w h） | YOLO 反算 xyxy（px） |
|---|---|---:|---|---|---|---|---|
| 1 | 2--Demonstration/2_Demonstration_Demonstration_Or_Protest_2_746.jpg | 70939 | 1015 452 9 13 | 1024×682 | [1015, 452, 1024, 465] | 0.995605 0.672287 0.008789 0.019062 | [1014.9996, 451.9996, 1023.9995, 464.9999] |
| 2 | 17--Ceremony/17_Ceremony_Ceremony_17_979.jpg | 49331 | 1014 497 10 16 | 1024×740 | [1014, 497, 1024, 513] | 0.995117 0.682432 0.009766 0.021622 | [1013.9996, 496.9995, 1024.0, 512.9998] |
| 3 | 12--Group/12_Group_Group_12_Group_Group_12_547.jpg | 27773 | 1005 407 19 44 | 1024×768 | [1005, 407, 1024, 451] | 0.990723 0.558594 0.018555 0.057292 | [1005.0002, 407.0001, 1024.0005, 451.0003] |
| 4 | 12--Group/12_Group_Large_Group_12_Group_Large_Group_12_31.jpg | 31821 | 1016 354 8 18 | 1024×660 | [1016, 354, 1024, 372] | 0.996094 0.55 0.007812 0.027273 | [1016.0005, 353.9999, 1024.0, 372.0001] |
| 5 | 2--Demonstration/2_Demonstration_Political_Rally_2_425.jpg | 72533 | 1019 212 5 9 | 1024×648 | [1019, 212, 1024, 221] | 0.997559 0.334105 0.004883 0.013889 | [1019.0003, 212.0, 1024.0005, 221.0001] |
| 6 | 2--Demonstration/2_Demonstration_Demonstration_Or_Protest_2_659.jpg | 86874 | 950 417 74 86 | 1024×1366 | [950, 417, 1024, 503] | 0.963867 0.33675 0.072266 0.062958 | [949.9996, 417.0002, 1024.0, 503.0008] |

YOLO 写 6 位小数后，反算的右边界可能超出 1024 约 0.0005 px（例 3、5），属于 6 位小数的舍入，远小于 FG-1 的 0.5 px 往返上限。

### 6.3 EXIF 方向

- **统计**：
  - Pillow `getexif()` 结果：train 12,880 张、val 3,226 张都**没有任何 EXIF 标签**（标签数 0），Orientation（0x0112）全部为“缺失/null”。等于 1 的为 0 张，不等于 1 的为 0 张。
  - 独立核对：在每个文件的前 64 KiB 里扫描 `Exif\0\0` APP1 段，train 和 val 都是 0 个文件。
- **FG-1**：report.json 里每张图的 `exif_orientation` 都是 `null`。FG-1 的策略是 `orientation in (None, 1)` 即放行，所以 `EXIF_ORIENTATION_NOT_IDENTITY` 触发 0 次。
- **标注是按哪个方向标的**：数据里没有 EXIF，存储像素方向就是唯一的方向。另外，所有非退化框都落在“存储宽×高”的画幅内（y1+h>H 为 0；x1+w>W 只有上面 2 个退化框），没有任何框只在宽高互换后才能放进画幅，说明标注与存储像素方向一致。
- **抽查**（5 例，全部为 EXIF 标签数 0、Orientation 缺失/null、FG-1 记 null）：
  - 2--Demonstration/2_Demonstration_Protesters_2_824.jpg
  - 33--Running/33_Running_Running_33_91.jpg
  - 35--Basketball/35_Basketball_playingbasketball_35_32.jpg
  - 44--Aerobics/44_Aerobics_Aerobics_44_316.jpg
  - 43--Row_Boat/43_Row_Boat_Canoe_43_413.jpg
- **结论**：EXIF 规则在 WIDER 上实际触发 0 次，FG-1 说明里“RN-3 后续核对第 2 条”的答案是 **0 张**。这条规则仍然有用（防止以后换数据源时出现静默错位），但在 WIDER 上不会生效。

### 6.4 右边界：`x1+w` 还是 `x1+w-1`

FG-1 把 (x1, y1, w, h) 当作像素边界：框为 [x1, x1+w) × [y1, y1+h)，右边界 = x1+w（P02 `xywh_edges`）。readme 只写了 “x1, y1, w, h”，没有规定起点和端点。

**用真实数据检验**：三种可能的约定会在画幅边缘留下不同的痕迹：

| 假设 | 预期 | train 实测 | val 实测 | 判断 |
|---|---|---|---|---|
| H1：0 起算，w 是像素数（x1+w 是开区间右边界，最右像素为 x1+w-1） | x1 最小可为 0；x1+w 最大 = W；不会出现 W+1 | x1=0 有 688 个；x1+w=W 有 749 个；=W+1 为 0；>W 只有退化框 | x1=0 有 213 个；=W 有 188 个；=W+1 为 0 | **与数据一致** |
| H2：1 起算（MATLAB 风格），w 是像素数 | 不会出现 x1=0；x1+w 最大 = W+1 | x1=0 出现 688 次 | 同左 | 被否定 |
| H3：x1+w 本身就是最右像素（闭区间） | x1+w 最大 = W-1，不会出现 = W | = W 出现 749 次 | = W 出现 188 次 | 被否定 |

- 贴边处有明显堆积：x1+w−W 取 −3/−2/−1/0 时，train 分别为 109/160/242/749 个框，val 为 27/35/63/188 个；W+1 没有出现。y 方向同样如此：y1+h−H 取 −3…0 时，train 为 37/41/67/313，val 为 6/13/18/95。说明标注工具把框限制在 [0, W]，与 H1 一致。
- 官方 .mat 里还保留了 3 个负宽度的原始框（见 7.3）：`1050 142 −26 50`、`1026 474 −2 23`（两者 x1+w = 1024 = W），以及 `0 5 −11 5`。前两个的另一端正好落在 W，说明标注工具记录的边界最大值是 W，而不是 W−1，也支持 H1。

**结论**：

1. FG-1 用 `x1+w` 作为开区间右边界是对的，框宽保留 w 个像素。抽查 6 个 w<10 的小框，YOLO 宽 × 图宽 = w，误差 ≤0.000512 px；全量标签的宽度误差最大 0.000512 px。
2. 如果改成 `x1+w-1`，并且仍按“边界”交给 `xywh_edges`，每个框会少 1 px 宽和 1 px 高。对中位宽 16 px 的框，这是约 6% 的系统性缩小；对 w<10 的框（train 有效框 40,879 个）超过 10%。**所以不应改为 x1+w-1。**
3. “x1+w-1”只有在用闭区间像素坐标表示最右像素时才是对的，它和 x1+w（开区间边界）描述的是同一组像素，不是另一种约定。
4. 官方评测的第三方实现（wondervictor `box_overlaps.pyx`）在面积和 IoU 里用 `(x2−x1+1)`（RD-6 第 171 行）。由于 GT 和预测都按同样方式处理，这不影响训练标签的取法，但 E01 写 AP 口径时要沿用官方工具，不要自行改写。
5. **还没解决的**：边缘统计只能区分 H1/H2/H3，不能证明标注员在框的内部边缘是否多画或少画了 1 px（标注精度问题）。FG-1 的 `box_convention_verified_on_real_data` 是否改为 true，建议由 Forge/用户根据本节决定。本报告不替 FG-1 改标志。

小框抽查（w<10、kept，6 例）：

| # | 文件（train） | gt 行 | 原始 x1 y1 w h | 图宽高 | FG-1 xyxy 边界 | YOLO w×W（px） |
|---|---|---:|---|---|---|---:|
| 1 | 2--Demonstration/2_Demonstration_Political_Rally_2_17.jpg | 68303 | 676 312 9 14 | 1024×684 | [676, 312, 685, 326] | 8.9999 |
| 2 | 2--Demonstration/2_Demonstration_Demonstrators_2_185.jpg | 80161 | 741 367 6 9 | 1024×808 | [741, 367, 747, 376] | 5.9996 |
| 3 | 35--Basketball/35_Basketball_basketballgame_ball_35_1041.jpg | 122583 | 120 296 6 5 | 1024×849 | [120, 296, 126, 301] | 5.9996 |
| 4 | 7--Cheering/7_Cheering_Cheering_7_548.jpg | 176163 | 125 346 7 8 | 1024×684 | [125, 346, 132, 354] | 7.0001 |
| 5 | 36--Football/36_Football_Football_36_147.jpg | 128967 | 276 22 9 9 | 1024×640 | [276, 22, 285, 31] | 8.9999 |
| 6 | 0--Parade/0_Parade_Parade_0_167.jpg | 10516 | 317 466 8 11 | 1024×683 | [317, 466, 325, 477] | 7.9995 |

### 6.5 FG-1 规则表以外的触发

**(a) `RASTER_SIZE_LIMIT`（整图失败）——FG-1 问题**

- **触发**：train 1 张 / val 0 张。文件 `50--Celebration_Or_Party/50_Celebration_Or_Party_houseparty_50_321.jpg`，gt 第 155889 行，尺寸 1024×9108，1,124,042 B，声明 65 个框，EXIF 缺失/null。
- **原因**：FG-1 复用 P02 的 `annotation_transform._size`，要求边长 ≤ `MAX_SIDE`=8192，总像素 ≤ 16 MiB 像素。这张图 9.33 M 像素，总像素没超，只是高度 9108 超过了边长上限。
- **后果**：
  - 65 个框全部 `not_processed`，不写标签；
  - train 运行 `status=failed`，CLI 退出码 1（FG-1 说明：1 = 有图片级失败）；
  - K5 里这条记录为 `processing=failed`。
- **结论**：这是真实数据里合法存在的超长图，不是坏图。FG-1 说明第 3 节的规则表没有这一条，需要决定：放宽 WIDER 的边长上限，还是把这张图登记为明确排除并记录原因。**这需要 Forge/用户决定，本任务不改代码。**

**(b) 退化框（`DEGENERATE_BOX`）**

- 触发：train 27 框 / 23 图，val 11 框 / 9 图；其中 w=0 的 train 19 / val 9，h=0 的 train 12 / val 6，w=h=0 的 train 4 / val 4；没有负值。
- 规则执行正确。抽查 6 例全部为 `dropped / DEGENERATE_BOX`：

| # | 划分 | 文件 | gt 行 | 原始标注 | 结果 |
|---|---|---|---:|---|---|
| 1 | train | 54--Rescue/54_Rescue_rescuepeople_54_29.jpg | 161871 | 1050 142 0 50 2 0 0 0 1 0 | DEGENERATE_BOX |
| 2 | val | 50--Celebration_Or_Party/50_Celebration_Or_Party_houseparty_50_715.jpg | 39477 | 0 0 0 0 0 0 0 0 0 0（该图唯一一行） | DEGENERATE_BOX → 空标签 |
| 3 | train | 2--Demonstration/2_Demonstration_Demonstration_Or_Protest_2_543.jpg | 76125 | 235 386 0 1 2 0 0 0 0 0 | DEGENERATE_BOX |
| 4 | train | 35--Basketball/35_Basketball_basketballgame_ball_35_805.jpg | 116892 | 945 314 0 0 2 0 0 0 1 0 | DEGENERATE_BOX |
| 5 | val | 2--Demonstration/2_Demonstration_Demonstration_Or_Protest_2_476.jpg | 17233 | 648 397 0 2 2 0 0 0 2 0 | DEGENERATE_BOX |
| 6 | train | 36--Football/36_Football_americanfootball_ball_36_184.jpg | 129122 | 1 43 0 5 2 0 0 0 0 0 | DEGENERATE_BOX |

**(c) 0 框图和“伪 0 框图”变成空标签——需要决定**

- train 4 张声明 0 框（txt 里是一行全零占位，.mat 里也是一行全零），FG-1 写成 0 字节的空标签：
  - `0--Parade/0_Parade_Parade_0_452.jpg`（gt 第 10422 行）
  - `2--Demonstration/2_Demonstration_Political_Rally_2_444.jpg`（86537）
  - `39--Ice_Skating/39_Ice_Skating_iceskiing_39_380.jpg`（133392）
  - `46--Jockey/46_Jockey_Jockey_46_576.jpg`（145712）
- val 4 张声明 **1** 框，但这一行是 `0 0 0 0 0 0 0 0 0 0`。FG-1 按退化框丢弃，结果同样是空标签：
  - `0--Parade/0_Parade_Parade_0_275.jpg`（第 1223 行）
  - `37--Soccer/37_Soccer_soccer_ball_37_281.jpg`（34070）
  - `50--Celebration_Or_Party/50_Celebration_Or_Party_houseparty_50_715.jpg`（39477）
  - `7--Cheering/7_Cheering_Cheering_7_426.jpg`（44364）
- **问题**：FG-1 把“0 框图”等同于“YOLO 负样本”。我为自己核对，在 `/tmp/MT-3/selfcheck/` 拼了这 8 张的缩略图（不进报告）。目视看到其中多张是密集人群场景，例如 val `7_Cheering_Cheering_7_426` 下部有可辨认的观众面部，`0_Parade_Parade_0_275` 是密集的游行队伍。说明这些图很可能是“未标注”，而不是“无人脸”。
- **影响**：拿它们作负样本，会让模型学会“人脸 = 背景”，不过只有 8 张。建议在 T02 里从训练集中排除（或标记为不可用），不要当负样本。**需要用户/Forge 决定。**

**(d) 完全重复的标注行**

- 共 3 组：
  - train `2--Demonstration/2_Demonstration_Protesters_2_231.jpg` 第 65587/65588 行：`55 463 24 29 …`
  - train `7--Cheering/7_Cheering_Cheering_7_17.jpg` 第 177779/177780 行：`410 314 3 8 …`
  - val `21--Festival/21_Festival_Festival_21_604.jpg` 第 23962/24001 行：`219 454 9 15 …`
- FG-1 两行都保留，标签文件里各出现一行重复的 YOLO 行（已用 `sort | uniq -d` 核实）。
- 影响很小（3 个框），但 FG-1 没有去重，也没有告警。

### 6.6 FG-1 自带测试

| 运行 | 命令要点 | 结果 |
|---|---|---|
| FG-1 新增测试 | `python -B -m pytest tests/test_wider_annotations.py -q -p no:cacheprovider --basetemp=/tmp/MT-3/pytest/wider`（在 `/tmp/MT-3/forge_688bc09/backend`，`PYTHONPATH` 指向导出副本的 `backend/src`） | **97 passed**，4.12 s |
| 后端全量 | 同上，不指定文件，`--basetemp=/tmp/MT-3/pytest/full` | **3103 passed, 3 skipped, 1 warning**，78.71 s，退出码 0 |

- 与 FG-1 说明第 5 节一致（3103 passed / 3 skipped / 1 条既有警告）。这次的警告是 starlette 的 `StarletteDeprecationWarning`（httpx → httpx2）。
- pytest 9.1.1。
- 环境注意：第一次运行时 `--basetemp` 的父目录 `/tmp/MT-3/pytest` 还不存在，`tmp_path` 夹具报 `FileNotFoundError`，结果是 67 passed / 30 errors。建好父目录后全部通过。这是运行环境问题，不是 FG-1 的缺陷。

### 6.7 标签全量独立核对

- 用独立实现对每张已转换的图重新计算期望的 YOLO 行（丢 invalid、丢退化框、裁到画幅、按 6 位小数格式化），与 FG-1 写出的标签文件逐行比较。结果：train 12,879 个文件、val 3,226 个文件，**不一致 0 个**。
- 标签行数与 kept 一致：train 156,929 行，val 39,112 行。
- FG-1 报告的往返误差最大值：train 0.002432 px，val 0.003199 px，均 ≤ 0.5 px。
- K5 审计：`completed_with_findings`，5 类待办发现与合成数据时相同（正式划分未定义、用途登记未收口、身份复核待办、近重复复核待办、训练来源重叠未知），全部记录 `use=unassigned`，没有做划分。
- train 的 K5 审计报告 `declared_duplicate_groups: 2`，见 7.2。

## 7. 数据异常清单（单列）

| # | 异常 | train | val | 处理与说明 |
|---|---|---:|---:|---|
| 7.1 | 声明 0 框的图 | 4 | 0 | 见 6.5(c)；.mat 中同样各存一行全零 |
| 7.1b | 声明 1 框但该行全零（伪 0 框图） | 0 | 4 | 见 6.5(c) |
| 7.2 | 字节完全相同（SHA-256 相同）的图片组 | 2 组（组内两张图都在 train） | 另有 1 组跨 train/val | 见下 |
| 7.3 | bbx_gt.txt 与 .mat 不一致的框 | 2 | 1 | .mat 里是负宽度，txt 截成 w=0；见下 |
| 7.4 | w=0 或 h=0 的框（退化框） | 27 | 11 | 其中 w=0：19 / 9；h=0：12 / 6；w=h=0：4 / 4；负值 0 |
| 7.5 | x1+w>W 的框 | 1 | 1 | 都是退化框（x1>W，w=0） |
| 7.6 | 部分越界的框 | 0 | 0 | 裁剪规则没有真实触发 |
| 7.7 | 同一图内完全重复的标注行 | 2 组 | 1 组 | 见 6.5(d) |
| 7.8 | 边长超过 8192 的图 | 1（1024×9108） | 0 | 见 6.5(a)；没有超过 16 MiB 像素或 16 MiB 字节的图 |
| 7.9 | 标注引用但不存在的图片 / 磁盘上无标注的图片 | 0 / 0 | 0 / 0 | — |
| 7.10 | 属性字段缺失/null 或超范围 | 0 | 0 | — |
| 7.11 | EXIF Orientation 缺失/null | 12,880（全部） | 3,226（全部） | 不是 1；FG-1 视同不旋转 |
| 7.12 | 宽 1 px 的有效框 | 6 | 0 | 保留；属于极小脸 |

**7.2 字节完全相同的图片**（三组标注都不相同，说明同一张图被独立标注了两次）：

| 组 | 图 A | 图 B | 标注对比 |
|---|---|---|---|
| SHA-256 `d10ce6ae5b44…` | train `29--Students_Schoolkids/29_Students_Schoolkids_Students_Schoolkids_29_475.jpg` | val `35--Basketball/35_Basketball_playingbasketball_35_476.jpg` | 各 2 个框，坐标不同（例：`328 14 88 164` 对 `314 12 96 152`）。**这是 train/val 之间的跨集精确重复**，与 S3“跨集精确重复为 0”的要求冲突；但 WIDER 的 train/val 是官方划分，是否处理要由 E01/P04 决定 |
| `171f8b108b2c…` | train `39--Ice_Skating/39_Ice_Skating_Ice_Skating_39_617.jpg` | train `5--Car_Accident/5_Car_Accident_Accident_5_907.jpg` | 37 个框对 50 个框，事件类别也不同 |
| `05a248b1ec39…` | train `41--Swimming/41_Swimming_Swimmer_41_745.jpg` | train `41--Swimming/41_Swimming_Swimming_41_184.jpg` | 各 1 个框：`454 468 88 88` 对 `472 458 62 92` |

**7.3 txt 与 .mat 的差异**：其余 159,418 行（train）和 39,707 行（val）的框坐标与 6 个属性完全一致。

| 划分 | 文件 | gt 行 | .mat（x y w h） | txt（x y w h） |
|---|---|---:|---|---|
| train | 54--Rescue/54_Rescue_rescuepeople_54_29.jpg | 161871 | 1050 142 **−26** 50 | 1050 142 0 50 |
| train | 7--Cheering/7_Cheering_Cheering_7_17.jpg | 177955 | 0 5 **−11** 5 | 0 5 0 5 |
| val | 39--Ice_Skating/39_Ice_Skating_iceskiing_39_583.jpg | 34471 | 1026 474 **−2** 23 | 1026 474 0 23 |

这 3 个框不论按哪个文件处理，画幅内都没有面积，丢弃是正确的。

## 8. 对应 P06：补上的真实数字

P06 的位置：仓库 `docs/后续任务清单.md` 第 94 行（交付要求“各年龄/质量/划分数量、排除率、身份限制、耗时/磁盘估算齐全”），以及 `docs/数据预处理报告.md` 第 60 行和第 3 节第 82 行（“实际质量排除率、原图/归档/派生几何实际体积、推理耗时、吞吐、峰值显存及正式训练工时预算均为null”）。

仓库主副本当前为 `10f1918`，两份文件**只读，没有改动**。P06 原报告统计的是 FG-NET N0 研究清单（292 条）；下表是 WIDER FACE 这一新数据源的对应数字，**不与那 292 条相加**。

| P06 项目 | 原状态 | WIDER 实测（本报告） | 出处 |
|---|---|---|---|
| 划分数量 | 正式三组均为 0 | 官方 train 12,880 图 / 159,420 框；val 3,226 / 39,708；test 16,097 图（只有文件清单，无框，未下载）。K5 记录一律 `use=unassigned`，**不是项目的正式 train/validation/test** | §3.1 |
| 质量分布 | 未测 | blur/occlusion/pose/expression/illumination/invalid 及尺度分布 | §4 |
| 实际质量排除率 | null | FG-1 默认：train 1.563%（2,491 框）、val 1.501%（596 框）；图级 3.602% / 4.371%；整图失败 train 1 张 | §5 |
| 原图体积 | null | train 1,474,029,628 B，val 365,054,675 B（字节和；分配块分别为 1,501,511,680 B 和 371,990,528 B） | §3.2 |
| 归档体积 | null | 1,831,945,959 B（3 个 zip；引自 RN-3 回执，压缩包已删除，本次无法复测） | §3.2 |
| 派生几何体积 | null | YOLO 标签：train 5,963,302 B / val 1,486,256 B（字节和），分配块 55,582,720 / 13,950,976 B；K5 清单 + 审计 + 报告：train 141,905,096 B，val 35,290,350 B | §3.2 |
| 耗时/吞吐（数据转换） | null | FG-1 转换（读文件头 + SHA-256 + 写标签和清单），8 vCPU 的 box、单进程：train 40.90 s（约 315 图/s），val 10.07 s（约 320 图/s）；两次子进程的最大峰值 RSS 1,093,516 KiB（约 1.04 GiB）。来自 `/tmp/MT-3/out/timing.json` 的第二次计时运行（第一次因 box 上没有 `bc`，没记下时间），两次输出的 summary 完全相同 | `/tmp/MT-3/out/timing.json` |
| 年龄 | — | **不适用 / null**：WIDER FACE 没有年龄标注；FG-1 写入的年龄为 `unknown`，不是 0 | — |
| 身份限制 | — | **不适用 / null**：WIDER 没有身份字段，K5 中 `subject_id=null`，身份复核为 pending；只能补充“精确重复的图片 3 组，其中 1 组跨 train/val”这一事实 | §7.2 |
| 推理耗时、吞吐 | null | **仍为 null**（本任务没有运行模型） | — |
| 峰值显存 | null | **仍为 null** | — |
| 正式训练工时预算 | null | **仍为 null**（T01/T02 尚未短跑） | — |

## 9. 图表规格（只给规格，由学生自己画）

所有数据来自 `/tmp/MT-3/out/`。`faces_{train,val}.csv` 每行一个框，`images_{train,val}.csv` 每行一张图；下表的 `chart_*.csv` 是汇总好的数据。

| 编号 | 图的类型 | 横轴 | 纵轴 | 分组 / 颜色 | 数据来源（文件 · 列） | 说明 |
|---|---|---|---|---|---|---|
| G1 | 分组柱状图 | 高度分档（≤0, <10, 10–50, 50–300, ≥300） | 框数占比（%） | train / val 两色；可分别画“全部”和“有效” | `chart_scale.csv` · split, subset, measure=h_bin, bin, share_of_subset | 分档按论文 §3.2；图注写明区间左闭右开 |
| G2 | 直方图（对数纵轴） | 有效框高度 h（px，按 2 px 分箱，0–300；>300 归入最后一箱） | 框数（对数） | train / val 叠加，半透明 | `faces_*.csv` · h，筛选 invalid=0 且 degenerate=0 | 在 10 px 和 50 px 处画参考竖线 |
| G3 | 100% 堆叠柱状图 | 属性（blur, occlusion, pose, expression, illumination） | 占比（%） | 堆叠为取值；train 和 val 各一组柱 | `chart_attr.csv` · split, subset=valid, attribute, label, share_of_subset | 取值名用 readme 原文 |
| G4 | 热力图 | 高度分档 | 属性取值（blur 0/1/2；occlusion 0/1/2；pose 0/1） | 每个属性一个子图；只用 train | `chart_cross_hbin_attr.csv` · h_bin, attribute, value, valid_faces | 按行或列归一化，二选一并在图注写明 |
| G5 | 横向柱状图 | 框数 | 61 个事件 | train 和 val 并排；可另标 invalid 数 | `chart_events.csv` · event, faces_declared, faces_invalid, faces_kept_fg1 | 按事件编号排序 |
| G6 | 柱状图 | 每图框数分档（0, 1, 2–5, 6–10, 11–50, 51–100, >100） | 图片数 | train / val | `chart_faces_per_image.csv` | — |
| G7 | 瀑布图或表格 | 规则（invalid → 退化 → 整图失败） | 被排除的框数 | train / val 各一张 | 本报告 §5.1 表 | 并集 = 各项之和（实测没有重叠） |
| G8 | 散点图或直方图 | 图片高度（px） | 图片数 | train / val | `chart_image_height.csv` · height | 在 8192 处画参考线，标出唯一超限的那张图 |

## 10. 发现的 FG-1 问题与待决定事项

这些都需要用户或 Forge 决定，本报告不替任何人做决定，也没有改代码。

| # | 问题 | 严重程度（我的建议） | 建议的选项 |
|---|---|---|---|
| F1 | `RASTER_SIZE_LIMIT` 让 1 张合法的超长图（1024×9108，65 框）整图失败，train 运行 `status=failed`、退出码 1；FG-1 说明的规则表里没有这一条 | 中 | ① 对 WIDER 放宽边长上限（总像素仍在 16 M 以内）；② 维持现状，在规则表里登记为明确排除（1 图 / 65 框） |
| F2 | 0 框图和“1 框但全零”的图被写成空标签（负样本），共 8 张，目视看有人群或人脸 | 中 | ① 在 T02 中把这 8 张排除出训练；② 保持为负样本并在报告中披露 |
| F3 | 完全重复的标注行没有去重，也没有告警（3 组） | 低 | 记录到报告中即可，或加一条告警 |
| F4 | `box_convention_verified_on_real_data` 仍为 false | 低 | 第 6.4 节的边缘统计支持 x1+w；是否改为 true 由 Forge/用户决定 |
| F5 | invalid 框直接丢弃，YOLO 训练里没有忽略区域 | 低（是策略，不是缺陷） | 由 T02/E01 决定是否加忽略掩码 |
| F6 | `--max-blur 1/0` 会丢 60%—87% 的框，并产生 900 张以上的空标签图 | 提示 | 如果要收紧 blur，同样需要考虑忽略区域 |
| D1 | train/val 之间有 1 组字节完全相同的图片 | 提示 | 由 E01/P04 决定是否披露或剔除；官方划分不建议擅自改动 |

## 11. 复现

```bash
# 0) 导出 FG-1（不在原工作树里执行）
git -C /workspace/AgeMorph3D_forge archive --format=tar --prefix=forge_688bc09/ 688bc09 | tar -x -C /tmp/MT-3
# 1) 把数据复制到 FG-1 要求的 root（原数据只读，FG-1 要求输出在 root/output/research 下）
mkdir -p /tmp/MT-3/root/data && S=/workspace/datasets/wider_face/extracted
cp -r $S/wider_face_split/files/wider_face_split $S/WIDER_train/files/WIDER_train $S/WIDER_val/files/WIDER_val /tmp/MT-3/root/data/
chmod -R u+w /tmp/MT-3/root
# 2) FG-1 转换：命令见 §2.2（train/val 各一次）
# 3) 独立统计（按顺序）
export PYTHONDONTWRITEBYTECODE=1; PY=/workspace/.venvs/agemorph-forge-31116/bin/python
$PY -B /tmp/MT-3/scripts/mt3_stats.py
PYTHONPATH=/tmp/MT-3/pylib $PY -B /tmp/MT-3/scripts/mt3_mat_edges.py
PYTHONPATH=/tmp/MT-3/pylib $PY -B /tmp/MT-3/scripts/mt3_mat_diff.py
$PY -B /tmp/MT-3/scripts/mt3_verify_sample.py
python3 -B /tmp/MT-3/scripts/mt3_time_convert.py
python3 -B /tmp/MT-3/scripts/mt3_chart_csv.py
# 4) 测试：见 §6.6（先 mkdir -p /tmp/MT-3/pytest）
```

脚本 SHA-256：

| 脚本 | SHA-256 |
|---|---|
| `mt3_stats.py` | `ae9bcef3520ded6b960f8c81b4cd3ce9b0a6388b09bccb2a7dd42c93e6a62594` |
| `mt3_mat_edges.py` | `cb1d678bea87fae1e76a3da1e569e56460a418e0c23e67ec6cf9efe579042445` |
| `mt3_mat_diff.py` | `e5480d58c483f5c9e417b5c9ea710653250dc680376064875e520585c754958c` |
| `mt3_verify_sample.py` | `5c80777e68a10ccfcc001f0895eb13f6e5ca2b461b54bcefe31f881a80c66322` |
| `mt3_time_convert.py` | `770d6deac14b2080a780704ea67545f1d255b21a05b1e64745a1862b16b0281e` |
| `mt3_chart_csv.py` | `37be7c431bb811f936854fc88536c4ad5346d438aa913e43d6c3de32e17202ab` |

**只读核对**（运行前后各拍一次快照，比较 `git status --porcelain --ignored`，以及全部文件的路径、大小、mtime）：

| 对象 | 运行前后 | 当前状态 |
|---|---|---|
| `/workspace/AgeMorph3D_forge` | 完全相同 | 仍在 `feat/wider-converter` @ `688bc09`，未 checkout，未 commit |
| `/workspace/AgeMorph3D` | 完全相同 | `10f1918`，未改动 |
| `/workspace/datasets/wider_face` | 完全相同（共 16,252 个条目：大小、mtime、权限均未变） | — |

所有 `__pycache__`、pytest 缓存和输出都只在 `/tmp/MT-3/` 下。

**磁盘说明**：`/tmp/MT-3/root/data/` 是 1.85 GB 的数据复制件，只用于运行 FG-1。报告定稿后我已删除它（FG-1 的输出、汇总和 CSV 保留）；需要复跑时按上面第 1 步重新复制，约 3 秒。

## 附录 A：关键脚本

### A.1 `/tmp/MT-3/scripts/mt3_stats.py`

```python
"""MT-3 independent WIDER FACE statistics (read-only on data; writes only /tmp/MT-3/out).

Run: PYTHONDONTWRITEBYTECODE=1 /workspace/.venvs/agemorph-forge-31116/bin/python -B \
       /tmp/MT-3/scripts/mt3_stats.py
Independent of FG-1: own bbx_gt parser; Pillow header reads only (no pixel decoding).
FG-1 decisions are joined from the FG-1 report.json files for comparison.
"""
import csv, json, os, sys, warnings
from collections import Counter, defaultdict
from PIL import Image

Image.MAX_IMAGE_PIXELS = None  # header-only reads; we want true sizes even for huge images
DATA = "/workspace/datasets/wider_face/extracted"
SPLITF = f"{DATA}/wider_face_split/files/wider_face_split"
IMG = {"train": f"{DATA}/WIDER_train/files/WIDER_train/images",
       "val": f"{DATA}/WIDER_val/files/WIDER_val/images"}
FG1 = {s: f"/tmp/MT-3/root/output/research/wider-{s}-v1/report.json" for s in IMG}
OUT = "/tmp/MT-3/out"
ATTR = ["blur", "expression", "illumination", "invalid", "occlusion", "pose"]
BINS = [(0, 10, "<10"), (10, 50, "10-50"), (50, 300, "50-300"), (300, 10**9, ">=300")]


def binof(v):
    if v <= 0:
        return "<=0"
    for lo, hi, name in BINS:
        if lo <= v < hi:
            return name


def parse(path):
    lines = open(path, encoding="utf-8").read().splitlines()
    out, i = [], 0
    while i < len(lines):
        name = lines[i].strip(); n = int(lines[i + 1]); rows = []
        for k in range(max(n, 1)):
            vals = [int(t) for t in lines[i + 2 + k].split()]
            assert len(vals) == 10, (path, i + 3 + k)
            rows.append(vals)
        out.append({"image": name, "line": i + 1, "n": n, "rows": rows if n else [], "placeholder": rows if n == 0 else None})
        i += 2 + max(n, 1)
    return out


def header(path):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with Image.open(path) as im:
            exif = im.getexif()
            return im.format, im.mode, im.size, exif.get(0x0112), len(exif)


def main():
    summary = {}
    for split in ("train", "val"):
        gt = parse(f"{SPLITF}/wider_face_{split}_bbx_gt.txt")
        on_disk = set()
        for root, _, files in os.walk(IMG[split]):
            for f in files:
                on_disk.add(os.path.relpath(os.path.join(root, f), IMG[split]))
        names = [e["image"] for e in gt]
        fg1 = json.load(open(FG1[split]))
        fg1_rows = {r["image"].split("/images/", 1)[1]: r for r in fg1["records"]}
        S = {"gt_images": len(gt), "gt_unique_images": len(set(names)), "disk_images": len(on_disk),
             "gt_missing_on_disk": sorted(set(names) - on_disk), "disk_not_in_gt": sorted(on_disk - set(names)),
             "events_gt": len({n.split("/")[0] for n in names}), "events_disk": len({n.split("/")[0] for n in on_disk}),
             "declared_faces": sum(e["n"] for e in gt), "zero_face_images": [e["image"] for e in gt if e["n"] == 0],
             "zero_face_placeholder_nonzero": [e["image"] for e in gt if e["n"] == 0 and any(e["placeholder"][0])]}
        face_rows, img_rows = [], []
        c = defaultdict(Counter)
        for e in gt:
            p = os.path.join(IMG[split], e["image"])
            fmt, mode, (W, H), ori, nexif = header(p)
            r1 = fg1_rows[e["image"]]
            img_rows.append({"split": split, "image": e["image"], "event": e["image"].split("/")[0], "gt_line": e["line"],
                             "declared_faces": e["n"], "width": W, "height": H, "format": fmt, "mode": mode,
                             "exif_tags": nexif, "exif_orientation": "missing/null" if ori is None else ori,
                             "bytes": os.path.getsize(p), "fg1_status": r1["status"], "fg1_error": r1["error_code"] or "",
                             "fg1_kept": r1["kept_faces"]})
            c["format"][fmt]; c["format"][fmt] += 1; c["mode"][mode] += 1
            c["exif_orientation"]["missing/null" if ori is None else str(ori)] += 1
            c["has_exif"][nexif > 0] += 1
            c["img_width"][W] += 1; c["img_height"][H] += 1
            seen = Counter(tuple(v) for v in e["rows"])
            for k, v in enumerate(e["rows"]):
                x, y, w, h = v[:4]; a = dict(zip(ATTR, v[4:]))
                f1 = r1["faces"][k]
                flags = {
                    "degenerate": w <= 0 or h <= 0,
                    "x1_neg": x < 0, "y1_neg": y < 0,
                    "x1_eq0": x == 0, "y1_eq0": y == 0,
                    "right_eq_W": x + w == W, "right_eq_W1": x + w == W + 1, "right_gt_W": x + w > W,
                    "bottom_eq_H": y + h == H, "bottom_eq_H1": y + h == H + 1, "bottom_gt_H": y + h > H,
                    "fully_out": (min(x + w, W) <= max(x, 0)) or (min(y + h, H) <= max(y, 0)),
                    "dup_row": seen[tuple(v)] > 1,
                }
                row = {"split": split, "image": e["image"], "event": e["image"].split("/")[0], "face_index": k,
                       "gt_line": e["line"] + 2 + k, "x1": x, "y1": y, "w": w, "h": h, **a, "img_w": W, "img_h": H,
                       "h_bin": binof(h), "w_bin": binof(w), "sqrt_area_bin": binof((max(w, 0) * max(h, 0)) ** 0.5),
                       **{k2: int(v2) for k2, v2 in flags.items()},
                       "fg1_decision": f1["decision"], "fg1_reason": f1.get("reason") or "",
                       "fg1_clipped": int(f1.get("clipped") is True)}
                face_rows.append(row)
        # ---- counters
        F = face_rows
        valid = [f for f in F if f["invalid"] == 0]
        def dist(rows, key):
            cc = Counter(str(r[key]) for r in rows); return dict(sorted(cc.items()))
        S["attr_all"] = {k: dist(F, k) for k in ATTR}
        S["attr_valid"] = {k: dist(valid, k) for k in ATTR if k != "invalid"}
        S["attr_invalid_only"] = {k: dist([f for f in F if f["invalid"] == 1], k) for k in ATTR if k != "invalid"}
        for key in ("h_bin", "w_bin", "sqrt_area_bin"):
            S[key + "_all"] = dist(F, key); S[key + "_valid"] = dist(valid, key)
            S[key + "_invalid"] = dist([f for f in F if f["invalid"] == 1], key)
        S["flags"] = {k: sum(f[k] for f in F) for k in ("degenerate", "x1_neg", "y1_neg", "x1_eq0", "y1_eq0",
                       "right_eq_W", "right_eq_W1", "right_gt_W", "bottom_eq_H", "bottom_eq_H1", "bottom_gt_H",
                       "fully_out", "dup_row")}
        S["w_eq0"] = sum(f["w"] == 0 for f in F); S["h_eq0"] = sum(f["h"] == 0 for f in F)
        S["w_neg"] = sum(f["w"] < 0 for f in F); S["h_neg"] = sum(f["h"] < 0 for f in F)
        S["wh_both0"] = sum(f["w"] == 0 and f["h"] == 0 for f in F)
        S["degenerate_and_invalid"] = sum(f["degenerate"] and f["invalid"] == 1 for f in F)
        S["degenerate_rows_attr_all_zero"] = sum(f["degenerate"] and all(f[a] == 0 for a in ATTR) for f in F)
        S["x1_min"] = min(f["x1"] for f in F); S["y1_min"] = min(f["y1"] for f in F)
        S["right_minus_W_max"] = max(f["x1"] + f["w"] - f["img_w"] for f in F)
        S["bottom_minus_H_max"] = max(f["y1"] + f["h"] - f["img_h"] for f in F)
        hs = sorted(f["h"] for f in valid if f["h"] > 0); ws = sorted(f["w"] for f in valid if f["w"] > 0)
        q = lambda a, p: a[min(len(a) - 1, int(p * (len(a) - 1) + 0.5))]
        S["valid_h_quantiles"] = {p: q(hs, p) for p in (0, 0.25, 0.5, 0.75, 0.95, 1)}
        S["valid_w_quantiles"] = {p: q(ws, p) for p in (0, 0.25, 0.5, 0.75, 0.95, 1)}
        S["images"] = {k: dict(sorted(v.items(), key=lambda t: str(t[0]))) for k, v in c.items()
                       if k in ("format", "mode", "exif_orientation", "has_exif")}
        S["img_width_top"] = Counter(c["img_width"]).most_common(5)
        S["img_height_minmax"] = [min(c["img_height"]), max(c["img_height"])]
        S["img_width_minmax"] = [min(c["img_width"]), max(c["img_width"])]
        S["img_over_8192_side"] = [r["image"] for r in img_rows if max(r["width"], r["height"]) > 8192]
        S["img_over_16Mpx"] = [r["image"] for r in img_rows if r["width"] * r["height"] > 16 * 1024**2]
        S["img_over_16MiB"] = [r["image"] for r in img_rows if r["bytes"] > 16 * 1024**2]
        # ---- FG-1 rule exclusions (raw conditions, overlap-aware)
        A = {id(f) for f in F if f["invalid"] == 1}; B = {id(f) for f in F if f["degenerate"]}
        C = {id(f) for f in F if f["fully_out"] and not f["degenerate"]}
        fail_imgs = {r["image"] for r in img_rows if r["fg1_status"] != "converted"}
        Dset = {id(f) for f in F if f["image"] in fail_imgs}
        b2 = {id(f) for f in F if f["blur"] == 2}; b1 = {id(f) for f in F if f["blur"] >= 1}
        S["rules_face"] = {"invalid": len(A), "degenerate": len(B), "out_of_frame_nondegenerate": len(C),
                           "image_failed_faces": len(Dset), "invalid&degenerate": len(A & B),
                           "invalid&image_failed": len(A & Dset), "degenerate&image_failed": len(B & Dset),
                           "union_default": len(A | B | C | Dset),
                           "blur2": len(b2), "blur>=1": len(b1),
                           "union_max_blur1": len(A | B | C | Dset | b2), "union_max_blur0": len(A | B | C | Dset | b1)}
        byimg = lambda ids: len({f["image"] for f in F if id(f) in ids})
        S["rules_image"] = {"invalid": byimg(A), "degenerate": byimg(B), "image_failed": len(fail_imgs),
                            "invalid&degenerate_same_image": len({f["image"] for f in F if id(f) in A} & {f["image"] for f in F if id(f) in B}),
                            "any_default": byimg(A | B | C | Dset), "blur2": byimg(b2)}
        perimg = defaultdict(list)
        for f in F: perimg[f["image"]].append(f)
        def all_dropped(ids):
            return sorted(im for im, fs in perimg.items() if fs and all(id(f) in ids for f in fs))
        S["images_all_faces_excluded_default"] = all_dropped(A | B | C | Dset)
        S["images_all_faces_excluded_default_excl_failed"] = [im for im in all_dropped(A | B | C) ]
        S["images_all_faces_excluded_max_blur1"] = len(all_dropped(A | B | C | Dset | b2))
        S["images_all_faces_excluded_max_blur0"] = len(all_dropped(A | B | C | Dset | b1))
        # FG-1 report comparison
        S["fg1_summary"] = fg1["summary"]; S["fg1_status"] = fg1["status"]; S["fg1_inputs_stable"] = fg1["inputs_stable"]
        S["fg1_decisions"] = dict(Counter(f"{f['fg1_decision']}:{f['fg1_reason']}" for f in F))
        S["fg1_clipped"] = sum(f["fg1_clipped"] for f in F)
        summary[split] = S
        for name, rows in (("faces", face_rows), ("images", img_rows)):
            with open(f"{OUT}/{name}_{split}.csv", "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    # test split: filelist only (no boxes); images not downloaded
    tl = [l.strip() for l in open(f"{SPLITF}/wider_face_test_filelist.txt") if l.strip()]
    summary["test"] = {"filelist_lines": len(tl), "unique": len(set(tl)), "events": len({t.split('/')[0] for t in tl}),
                       "images_on_box": "not downloaded (RN-3 scope)", "boxes": "none published (filelist only)"}
    json.dump(summary, open(f"{OUT}/summary.json", "w"), ensure_ascii=False, indent=1, default=str)
    print("ok")


if __name__ == "__main__":
    main()
```

### A.2 `/tmp/MT-3/scripts/mt3_mat_edges.py`

```python
"""MT-3: compare bbx_gt.txt vs official .mat (boxes+labels) and edge histograms. Writes /tmp/MT-3/out/mat_edges.json"""
import csv, json
from collections import Counter
import numpy as np
from scipy.io import loadmat
D = "/workspace/datasets/wider_face/extracted/wider_face_split/files/wider_face_split"
out = {}
for s in ("train", "val"):
    m = loadmat(f"{D}/wider_face_{s}.mat")
    keys = [k for k in m if not k.startswith("__")]
    rows = list(csv.DictReader(open(f"/tmp/MT-3/out/faces_{s}.csv")))
    imgs = list(csv.DictReader(open(f"/tmp/MT-3/out/images_{s}.csv")))
    txt = {}
    for r in rows:
        txt.setdefault(r["image"], []).append([int(r[k]) for k in ("x1","y1","w","h","blur","expression","illumination","invalid","occlusion","pose")])
    for im in imgs:
        txt.setdefault(im["image"], [])
    lab = {"blur": "blur_label_list", "expression": "expression_label_list", "illumination": "illumination_label_list",
           "invalid": "invalid_label_list", "occlusion": "occlusion_label_list", "pose": "pose_label_list"}
    n_img = n_face = img_mismatch = 0; missing = []; mism = []
    ev = m["event_list"]
    for e in range(len(ev)):
        event = str(ev[e][0][0])
        files = m["file_list"][e][0]
        for j in range(len(files)):
            name = f"{event}/{files[j][0][0]}.jpg"
            n_img += 1
            bb = np.asarray(m["face_bbx_list"][e][0][j][0]).reshape(-1, 4).astype(int)
            att = [np.asarray(m[lab[a]][e][0][j][0]).reshape(-1).astype(int) for a in lab]
            mat_rows = [list(bb[i]) + [int(a[i]) for a in att] for i in range(len(bb))]
            n_face += len(mat_rows)
            if name not in txt:
                missing.append(name); continue
            if [list(map(int, r)) for r in mat_rows] != txt[name]:
                img_mismatch += 1
                if len(mism) < 10: mism.append({"image": name, "mat_n": len(mat_rows), "txt_n": len(txt[name]), "mat_first": [int(v) for v in mat_rows[0]] if mat_rows else None, "txt_first": txt[name][0] if txt[name] else None})
    out[s] = {"mat_keys": keys, "mat_images": n_img, "mat_faces": n_face, "missing_in_txt": missing,
              "images_with_any_difference": img_mismatch, "examples": mism}
    # edge histograms (all non-degenerate faces)
    nd = [r for r in rows if r["degenerate"] == "0"]
    out[s]["right_minus_W"] = dict(sorted(Counter(int(r["x1"]) + int(r["w"]) - int(r["img_w"]) for r in nd if int(r["x1"]) + int(r["w"]) - int(r["img_w"]) >= -3).items()))
    out[s]["bottom_minus_H"] = dict(sorted(Counter(int(r["y1"]) + int(r["h"]) - int(r["img_h"]) for r in nd if int(r["y1"]) + int(r["h"]) - int(r["img_h"]) >= -3).items()))
    out[s]["x1_le2"] = dict(sorted(Counter(int(r["x1"]) for r in nd if int(r["x1"]) <= 2).items()))
    out[s]["y1_le2"] = dict(sorted(Counter(int(r["y1"]) for r in nd if int(r["y1"]) <= 2).items()))
    v = [r for r in nd if r["invalid"] == "0"]
    out[s]["valid_nondeg"] = len(v)
    for t in (5, 10, 20):
        out[s][f"valid_w_lt{t}"] = sum(int(r["w"]) < t for r in v)
        out[s][f"valid_h_lt{t}"] = sum(int(r["h"]) < t for r in v)
    out[s]["valid_w_eq1"] = sum(int(r["w"]) == 1 for r in v)
    # test mat
tm = loadmat(f"{D}/wider_face_test.mat")
out["test_mat"] = {"keys": [k for k in tm if not k.startswith("__")], "images": int(sum(len(tm["file_list"][e][0]) for e in range(len(tm["event_list"]))))}
json.dump(out, open("/tmp/MT-3/out/mat_edges.json", "w"), indent=1, default=str)
print(json.dumps(out, indent=1, default=str)[:4000])
```

### A.3 `/tmp/MT-3/scripts/mt3_mat_diff.py`

```python
"""MT-3: row-level diff txt vs .mat for images flagged by mt3_mat_edges.py."""
import csv, json
import numpy as np
from scipy.io import loadmat
D = "/workspace/datasets/wider_face/extracted/wider_face_split/files/wider_face_split"
T = {"train": ["54--Rescue/54_Rescue_rescuepeople_54_29.jpg", "7--Cheering/7_Cheering_Cheering_7_17.jpg"],
     "val": ["39--Ice_Skating/39_Ice_Skating_iceskiing_39_583.jpg"]}
lab = ["blur", "expression", "illumination", "invalid", "occlusion", "pose"]
res = []
for s, ims in T.items():
    m = loadmat(f"{D}/wider_face_{s}.mat")
    rows = [r for r in csv.DictReader(open(f"/tmp/MT-3/out/faces_{s}.csv")) if r["image"] in ims]
    for e in range(len(m["event_list"])):
        event = str(m["event_list"][e][0][0])
        for j, f in enumerate(m["file_list"][e][0]):
            name = f"{event}/{f[0][0]}.jpg"
            if name not in ims: continue
            bb = np.asarray(m["face_bbx_list"][e][0][j][0]).reshape(-1, 4)
            att = [np.asarray(m[a + "_label_list"][e][0][j][0]).reshape(-1) for a in lab]
            tr = [r for r in rows if r["image"] == name]
            for i in range(len(bb)):
                mv = [float(v) for v in bb[i]] + [int(a[i]) for a in att]
                tv = [int(tr[i][k]) for k in ("x1","y1","w","h", *lab)]
                if [round(v, 6) for v in mv] != tv:
                    res.append({"split": s, "image": name, "face_index": i, "gt_line": tr[i]["gt_line"], "mat_raw": [str(bb[i][k]) for k in range(4)] + mv[4:], "mat_dtype": str(bb.dtype), "txt": tv})
print(json.dumps(res, indent=1))
json.dump(res, open("/tmp/MT-3/out/mat_txt_row_diffs.json", "w"), indent=1)
```

### A.4 `/tmp/MT-3/scripts/mt3_verify_sample.py`

```python
"""MT-3: verify FG-1 label files against independent recomputation; fixed-seed spot checks; raw EXIF scan.
Writes /tmp/MT-3/out/verify.json and /tmp/MT-3/out/samples.json. Read-only on data."""
import csv, json, os, random
SEED = 20261121
ROOT = "/tmp/MT-3/root/output/research"
IMG = {"train": "/workspace/datasets/wider_face/extracted/WIDER_train/files/WIDER_train/images",
       "val": "/workspace/datasets/wider_face/extracted/WIDER_val/files/WIDER_val/images"}
ver, pools = {}, {k: [] for k in ("invalid", "degenerate", "touch_right", "small_kept", "zero_face_img", "raster", "exif_meta")}
for s in ("train", "val"):
    rep = json.load(open(f"{ROOT}/wider-{s}-v1/report.json"))
    recs = {r["image"].split("/images/", 1)[1]: r for r in rep["records"]}
    faces = list(csv.DictReader(open(f"/tmp/MT-3/out/faces_{s}.csv")))
    imgs = list(csv.DictReader(open(f"/tmp/MT-3/out/images_{s}.csv")))
    by = {}
    for f in faces: by.setdefault(f["image"], []).append(f)
    n_lab = n_empty = n_lines = mism = maxdiff_px = 0; width_px_err = 0.0
    for im in imgs:
        name = im["image"]; r = recs[name]
        lab = f"{ROOT}/wider-{s}-v1/labels/" + name[:-4] + ".txt"
        if r["status"] != "converted":
            assert not os.path.exists(lab); continue
        n_lab += 1
        lines = open(lab).read().splitlines(); n_lines += len(lines); n_empty += (len(lines) == 0)
        W, H = int(im["width"]), int(im["height"])
        exp = []
        for f in by.get(name, []):
            x, y, w, h = (int(f[k]) for k in ("x1", "y1", "w", "h"))
            if f["invalid"] == "1" or w <= 0 or h <= 0: continue
            l, t, rr, b = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
            if rr <= l or b <= t: continue
            exp.append("0 " + " ".join(f"{v:.6f}" for v in ((l + rr) / 2 / W, (t + b) / 2 / H, (rr - l) / W, (b - t) / H)))
            width_px_err = max(width_px_err, abs(float(exp[-1].split()[3]) * W - (rr - l)))
        if exp != lines: mism += 1
    ver[s] = {"label_files": n_lab, "empty_label_files": n_empty, "label_lines": n_lines,
              "images_label_mismatch_vs_independent": mism, "max_abs_width_px_err_after_6dp": width_px_err,
              "label_files_on_disk": sum(len(fs) for _, _, fs in os.walk(f"{ROOT}/wider-{s}-v1/labels"))}
    def fg1(f, recs=recs):
        led = recs[f["image"]]["faces"][int(f["face_index"])]
        return {k: led.get(k) for k in ("decision", "reason", "clipped", "clipped_xyxy_edges", "yolo")}
    for f in faces:
        base = {"split": s, "image": f["image"], "gt_line": int(f["gt_line"]),
                "raw": " ".join(f[k] for k in ("x1", "y1", "w", "h", "blur", "expression", "illumination", "invalid", "occlusion", "pose")),
                "img_wh": [int(f["img_w"]), int(f["img_h"])]}
        if f["invalid"] == "1": pools["invalid"].append((f, base))
        if f["degenerate"] == "1": pools["degenerate"].append((f, base))
        if f["right_eq_W"] == "1" and f["fg1_decision"] == "kept": pools["touch_right"].append((f, base))
        if f["fg1_decision"] == "kept" and int(f["w"]) < 10: pools["small_kept"].append((f, base))
    for im in imgs:
        if im["declared_faces"] == "0": pools["zero_face_img"].append((None, {"split": s, "image": im["image"], "gt_line": int(im["gt_line"]), "declared_faces": 0, "fg1_status": im["fg1_status"], "label_bytes": os.path.getsize(f"{ROOT}/wider-{s}-v1/labels/" + im["image"][:-4] + ".txt")}))
        if im["fg1_status"] != "converted": pools["raster"].append((None, {"split": s, "image": im["image"], "gt_line": int(im["gt_line"]), "size": [int(im["width"]), int(im["height"])], "declared_faces": int(im["declared_faces"]), "fg1_error": im["fg1_error"], "fg1_report_exif": recs[im["image"]]["exif_orientation"]}))
        pools["exif_meta"].append((None, {"split": s, "image": im["image"], "exif_tags": im["exif_tags"], "exif_orientation": im["exif_orientation"], "fg1_report_exif": recs[im["image"]]["exif_orientation"]}))
    pools.setdefault("_fg1", {})[s] = fg1
K = {"invalid": 6, "degenerate": 6, "touch_right": 6, "small_kept": 6, "zero_face_img": 4, "raster": 1, "exif_meta": 5}
samples = {}
for k, pool in pools.items():
    if k == "_fg1": continue
    rng = random.Random(f"{SEED}:{k}")
    pick = rng.sample(pool, min(K[k], len(pool)))
    out = []
    for f, base in pick:
        if f is not None:
            base = {**base, "fg1": pools["_fg1"][base["split"]](f)}
            if base["fg1"]["yolo"]:
                W, H = base["img_wh"]; cx, cy, w, h = base["fg1"]["yolo"]
                base["yolo_back_px_xyxy"] = [round((cx - w / 2) * W, 4), round((cy - h / 2) * H, 4), round((cx + w / 2) * W, 4), round((cy + h / 2) * H, 4)]
        out.append(base)
    samples[k] = {"pool_size": len(pool), "k": len(pick), "seed": f"{SEED}:{k}", "items": out}
# raw EXIF APP1 scan (bytes, independent of Pillow)
exif_raw = {}
for s, d in IMG.items():
    n = 0
    for root, _, fs in os.walk(d):
        for fn in fs:
            with open(os.path.join(root, fn), "rb") as fh:
                head = fh.read(65536)
            n += b"Exif\x00\x00" in head
    exif_raw[s] = n
ver["raw_exif_app1_in_first_64KiB"] = exif_raw
json.dump(ver, open("/tmp/MT-3/out/verify.json", "w"), indent=1)
json.dump(samples, open("/tmp/MT-3/out/samples.json", "w"), indent=1, ensure_ascii=False)
print(json.dumps(ver, indent=1))
```

### A.5 `/tmp/MT-3/scripts/mt3_time_convert.py`

```python
"""MT-3: time FG-1 conversion (wall clock + child peak RSS); output to a fresh timing dir under /tmp/MT-3/root."""
import hashlib, json, resource, subprocess, sys, time, os
PY = "/workspace/.venvs/agemorph-forge-31116/bin/python"
res = {}
for s, d in (("train", "WIDER_train"), ("val", "WIDER_val")):
    gt = f"data/wider_face_split/wider_face_{s}_bbx_gt.txt"
    sha = hashlib.sha256(open(f"/tmp/MT-3/root/{gt}", "rb").read()).hexdigest()
    cmd = [PY, "-B", "-m", "preprocessing.wider_annotations", "--root", "/tmp/MT-3/root", "--gt", gt, "--gt-sha256", sha,
           "--images-dir", f"data/{d}/images", "--split", s, "--output-dir", f"output/research/timing-{s}"]
    t = time.perf_counter()
    p = subprocess.run(cmd, cwd="/tmp/MT-3/forge_688bc09", capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    dt = time.perf_counter() - t
    summ = json.loads(p.stdout)["summary"]
    res[s] = {"exit": p.returncode, "wall_s": round(dt, 2), "summary": summ}
res["children_peak_rss_kib"] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
res["nproc"] = os.cpu_count()
json.dump(res, open("/tmp/MT-3/out/timing.json", "w"), indent=1)
print(json.dumps(res, indent=1))
```

`mt3_chart_csv.py`（绘图用汇总 CSV）只做计数汇总，原文见 `/tmp/MT-3/scripts/mt3_chart_csv.py`，SHA-256 见 §11。
