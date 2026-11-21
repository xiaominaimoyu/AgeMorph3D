# RN-2 box 数据清单（只列清单，不处理）

- 执行人：Runner（执行运营官）；依据：`/workspace/AgeMorph3D_后续任务规划_v2.md` 第 138 行（RN-2）、第 18/137 行（RN-0）
- 盘点时间：2026-11-16 约 05:55—06:10（柏林时间，UTC+1）
- 时间口径：下表所有修改时间都已换算为**柏林时间（UTC+1）**。box 系统时钟实际是 UTC，`ls` 直接显示的时间要加 1 小时；括号里另注 UTC+8 的地方是为了和规划文档对照。
- **边界**：本次只用了 `find`、`stat`、`du`、`ls` 读文件名和文件系统元数据。**没有删除、移动、改名任何文件，也没有打开任何数据文件的内容**（parquet、csv、mat、tar、zip、png、bin、json 文件列表、数据集说明页 md 都没打开）。只读过下面这几份小的非数据文件来判断来源：`/workspace/hfinfo.py`（脚本）、`/tmp/hf_size.txt`（HF 接口返回的大小统计）、规划和数据集方案文档、`/workspace/AgeMorph3D` 的 git 引用。没有下载任何东西，没有 push。**删不删由用户决定**，本清单里的“可清理”只是分类建议。

## 0. 结论摘要

| 类别 | 文件数 | 合计大小 | 与 AgeDB 有关 |
|---|---|---|---|
| A. `/workspace/hf/`（HF 数据集说明页 + 标签 CSV + zip） | 18 | 42,989,291 B（约 41 MiB） | 4 份（文件名含 agedb） |
| B. `/tmp/tree_*.json`（HF 仓库文件列表） | 11 | 249,391 B（约 244 KiB） | 2 份 |
| C. `/tmp` 下其他数据集相关文件（IMDB、LAGENDA、face_age 等） | 17 | 158,419,750 B（约 151 MiB） | 文件名都不含 agedb；chradden/face_age 相关 7 项经 Sentinel 审核核查，元数据不支持是 AgeDB 转存（见 C 节） |
| D. 工具链（本任务 RN-1 产生）**工具链，可清理** | 2 项 | 约 372 MiB + 233 MiB | 否 |
| E. 名称命中但不是数据 | 若干 | — | 1 处 git 分支名含 agedb |

- **已知的 6 个 AgeDB 相关文件全部在场并已列入**（A 节 4 份、B 节 2 份，标 ★）。
- 全盘按文件名查 `*agedb*`（`find / -xdev -iname '*agedb*'`）只找到这 6 个文件，再加上主副本 git 里的一个分支引用（E 节）。**没有发现其他 AgeDB 残留副本。**
- `/workspace/hf/agedb.parquet` **已不存在**（`ls` 报 No such file or directory）。全盘也没有任何 `.parquet` 数据文件（只有两个 Python 环境里 pyarrow 自带的 4 个测试用小 parquet，见 E 节）。`/tmp/mh_meta.csv` 也不存在。
- HF 标准缓存里没有数据：`~/.cache/huggingface/` 下没有 `hub/`、`datasets/`，只有一个 `.agent_harnesses.json`（见 E 节）；环境变量里没有设 `HF_HOME` 等 HF 变量。

## 1. 已知 6 个 AgeDB 相关文件核对

| # | 路径 | 大小（B） | 修改时间（柏林） | 状态 |
|---|---|---|---|---|
| ★1 | `/workspace/hf/ljnlonoljpiljm_agedb.md` | 1,141 | 2026-11-15 12:49:18 | 在 |
| ★2 | `/workspace/hf/marcelohaps_agedb.md` | 1,646 | 2026-11-15 12:49:18 | 在 |
| ★3 | `/workspace/hf/lhx05_agedb-224-by-identity.md` | 1,671 | 2026-11-15 12:49:19 | 在 |
| ★4 | `/workspace/hf/caojingtian1216_AgeDB.md` | 33 | 2026-11-15 12:49:18 | 在 |
| ★5 | `/tmp/tree_ljnlonoljpiljm_agedb.json` | 609 | 2026-11-15 12:57:56 | 在 |
| ★6 | `/tmp/tree_lhx05_agedb-224-by-identity.json` | 523 | 2026-11-15 12:57:55 | 在 |

规划 v2 第 138 行写的是：前 4 份是 HF 数据集说明页，后 2 份是 HF 文件列表；Sentinel 按文件名全盘查过，都不含逐张图片、人名或年龄。本次没有打开内容，所以“不含图片、人名或年龄”沿用 Sentinel 的结论，不是我重新核实的。

**已删除的 `/workspace/hf/agedb.parquet`（约 180 MB）**：规划 v2 第 18、137、171、244 行记录，用户于 2026-11-15 21:01（UTC+8，即柏林 14:01）同意删除，Atlas 随即删除。本次的旁证有两条：
- 该路径现在不存在；
- 目录 `/workspace/hf/` 的修改时间是 2026-11-15 14:01:57（柏林）= 21:01:57（UTC+8），和记录的删除时间吻合。删除会改目录的修改时间，而这个目录里其他文件都没有晚于 13:05 的。

删除前没有记录 SHA-256（规划原文如此），本次无法补。

## 2. 详细清单

“来源”一栏的说明：有直接证据的写证据；只能从文件名、时间推断的标“推断”；没有证据的写“未知”。按时间看，这些文件都出现在 2026-11-15 12:40—14:10（柏林）之间。这正是 Radar 做 HF 数据集调研、Sentinel 审核数据集方案的时间段（Atlas 的记录：Radar 12:56 交 v1，13:02 被判不通过，13:08 交 v2，13:25 v3 通过）。所以除非另有说明，下面的来源都是“推断：数据集调研期间由调研/审核 Agent 拉取”，具体是哪个 Agent 下载的，没有找到逐条记录。

### A. `/workspace/hf/`（目录合计 18 个文件，42,989,291 B）

| 路径 | 大小（B） | 修改时间（柏林） | 来源 | AgeDB |
|---|---|---|---|---|
| `/workspace/hf/caojingtian1216_AgeDB.md` ★ | 33 | 11-15 12:49:18 | HF 数据集 `caojingtian1216/AgeDB` 的说明页（规划 v2 第 138 行）；同一秒批量生成，推断为调研脚本抓取 | **是** |
| `/workspace/hf/ljnlonoljpiljm_agedb.md` ★ | 1,141 | 11-15 12:49:18 | HF `ljnlonoljpiljm/agedb` 说明页（同上） | **是** |
| `/workspace/hf/marcelohaps_agedb.md` ★ | 1,646 | 11-15 12:49:18 | HF `marcelohaps/agedb` 说明页（同上） | **是** |
| `/workspace/hf/lhx05_agedb-224-by-identity.md` ★ | 1,671 | 11-15 12:49:19 | HF `lhx05/agedb-224-by-identity` 说明页（同上） | **是** |
| `/workspace/hf/CholeDYM_FFHQ_UV_albedo_sh_lit.md` | 704 | 11-15 12:49:18 | HF `CholeDYM/FFHQ_UV_albedo_sh_lit` 说明页（推断，按文件名 `作者_数据集.md` 的规律） | 否 |
| `/workspace/hf/NUS-SRI-2025_FFHQ-Aging-Dataset.md` | 2,738 | 11-15 12:49:18 | HF `NUS-SRI-2025/FFHQ-Aging-Dataset` 说明页（推断） | 否 |
| `/workspace/hf/caojingtian1216_CACD.md` | 15 | 11-15 12:49:18 | HF `caojingtian1216/CACD` 说明页（推断） | 否 |
| `/workspace/hf/csbhr_FFHQ-UV.md` | 24 | 11-15 12:49:18 | HF `csbhr/FFHQ-UV` 说明页（推断） | 否 |
| `/workspace/hf/ljnlonoljpiljm_imdb_wiki_faces.md` | 1,185 | 11-15 12:49:18 | HF `ljnlonoljpiljm/imdb_wiki_faces` 说明页（推断） | 否 |
| `/workspace/hf/n0kovo_lagenda.md` | 689 | 11-15 12:49:18 | HF `n0kovo/lagenda` 说明页（推断） | 否 |
| `/workspace/hf/nu-delta_utkface.md` | 467 | 11-15 12:49:19 | HF `nu-delta/utkface` 说明页（推断） | 否 |
| `/workspace/hf/oshaban_cacd_cropped_faces.md` | 24 | 11-15 12:49:19 | HF `oshaban/cacd_cropped_faces` 说明页（推断） | 否 |
| `/workspace/hf/systemk-ai_imdb-wiki.md` | 3,229 | 11-15 12:49:19 | HF `systemk-ai/imdb-wiki` 说明页（推断） | 否 |
| `/workspace/hf/ffhq_aging_labels.csv` | 4,975,668 | 11-15 12:51:04 | FFHQ-Aging 标签 CSV（推断：数据集方案 v2/v3 §C“从 HF 只拿标签 CSV”） | 否 |
| `/workspace/hf/imdb_train_new_1024.csv` | 22,130,681 | 11-15 13:03:40 | IMDB-Clean 标注的 1024 版本（推断：文件名对应 HF `caojingtian1216/imdb-clean-1024`；方案 v2 写明“不采用，属于非官方再分发”） | 否（IMDB-WIKI 系） |
| `/workspace/hf/imdb_valid_new_1024.csv` | 5,532,158 | 11-15 13:03:40 | 同上 | 否（IMDB-WIKI 系） |
| `/workspace/hf/imdb_test_new_1024.csv` | 6,745,576 | 11-15 13:03:40 | 同上 | 否（IMDB-WIKI 系） |
| `/workspace/hf/wfs.zip` | 3,591,642 | 11-15 13:05:08 | 未知。推断可能是 WIDER FACE 的 `wider_face_split.zip`（文件名缩写和大小约 3.6 MB 都对得上，方案 v2 §E 提到从 HF `CUHK-CSE/wider_face` 下载这个文件），未打开核实 | 否 |
| ↳ **已删除（2026-11-21 08:55:12 UTC+1 ＝ 15:55:12 UTC+8，见附录 G）** | | | 经 Atlas 转达的用户决定删除；删前 SHA-256 `c7561e4f…8a5c` 与 RN-3 官方 `wider_face_split.zip` 完全一致 | |

### B. `/tmp/tree_*.json`（HF 仓库文件列表，11 个，均为 11-15 12:57:55—56 同批生成）

推断来源：调研时调用 HF API 拉取的仓库文件树。同一时段装了带 `huggingface_hub 2.4.0` 的 `/workspace/.venv_sentinel`（12:57:11 创建），所以推断是 Sentinel 审核时生成的。规划 v2 第 138 行也把其中两份称为“HF 文件列表”。

| 路径 | 大小（B） | 修改时间（柏林） | AgeDB |
|---|---|---|---|
| `/tmp/tree_ljnlonoljpiljm_agedb.json` ★ | 609 | 11-15 12:57:56 | **是** |
| `/tmp/tree_lhx05_agedb-224-by-identity.json` ★ | 523 | 11-15 12:57:55 | **是** |
| `/tmp/tree_Bingsu_wider_face_yolo.json` | 498 | 11-15 12:57:55 | 否 |
| `/tmp/tree_CUHK-CSE_wider_face.json` | 1,613 | 11-15 12:57:55 | 否 |
| `/tmp/tree_CholeDYM_FFHQ_UV_albedo_sh_lit.json` | 28,095 | 11-15 12:57:56 | 否 |
| `/tmp/tree_NUS-SRI-2025_FFHQ-Aging-Dataset.json` | 65,056 | 11-15 12:57:55 | 否 |
| `/tmp/tree_caojingtian1216_CACD.json` | 2,293 | 11-15 12:57:55 | 否 |
| `/tmp/tree_csbhr_FFHQ-UV.json` | 117,705 | 11-15 12:57:55 | 否 |
| `/tmp/tree_ljnlonoljpiljm_imdb_wiki_faces.json` | 6,655 | 11-15 12:57:56 | 否 |
| `/tmp/tree_n0kovo_lagenda.json` | 25,100 | 11-15 12:57:56 | 否 |
| `/tmp/tree_nu-delta_utkface.json` | 1,244 | 11-15 12:57:56 | 否 |

### C. `/tmp` 下其他数据集相关文件（规划里没点名，本次新发现）

| 路径 | 大小（B） | 修改时间（柏林） | 来源 | AgeDB | 备注 |
|---|---|---|---|---|---|
| `/tmp/imdb_meta.tar` | 22,937,600 | 11-15 13:09:55 | IMDB-WIKI 官方元数据包（推断：文件名对应 ETH 的 `imdb_meta.tar`） | 否 | 含人名和出生日期等元数据（按公开格式推断，未打开） |
| `/tmp/imdb/imdb.mat` | 22,935,644 | 2016-01-17 11:30:30 | 上一行 tar 解出来的文件（推断：修改时间保留了归档里的 2016 年原始时间，目录 `/tmp/imdb` 创建于 13:09:55，与 tar 同时） | 否 | 同上 |
| `/tmp/imdb_train_new.csv` | 32,675,640 | 11-15 13:09:30 | IMDB-Clean 官方标注（推断：文件名对应 GitHub `yiminglin-ai/imdb-clean`，方案 v2 §B） | 否 | — |
| `/tmp/imdb_valid_new.csv` | 8,168,893 | 11-15 13:09:31 | 同上 | 否 | — |
| `/tmp/imdb_test_new.csv` | 9,962,122 | 11-15 13:09:31 | 同上 | 否 | — |
| `/tmp/imdb_train_new_1024.csv` | 22,130,681 | 11-15 13:09:30 | 和 `/workspace/hf/` 下同名文件大小完全一致，推断是副本（未比对内容） | 否 | 重复 |
| `/tmp/imdb_valid_new_1024.csv` | 5,532,158 | 11-15 13:09:31 | 同上 | 否 | 重复 |
| `/tmp/imdb_test_new_1024.csv` | 6,745,576 | 11-15 13:09:31 | 同上 | 否 | 重复 |
| `/tmp/lagenda_ann` | 24,843,169 | 2024-02-18 20:35:38 | LAGENDA 标注（推断：文件名；方案 v2 写过“LAGENDA 的 age=-1 比例只抽查了前 4 万行”，说明调研时读过它；修改时间保留了上游 2024 年的时间） | 否 | 权限 600 |
| `/tmp/hf_size.txt` | 664 | 11-15 12:40:57 | HF datasets-server 对 `chradden/face_age` 的大小统计（读过，非数据：19,558 行，parquet 约 871 MB） | 待定 | 只是元数据 |
| `/tmp/face_age_readme.md` | 0 | 11-15 12:41:11 | 推断是 `chradden/face_age` 的说明页，空文件 | 待定 | — |
| `/tmp/15.png` | 51,688 | 11-15 12:41:12 | 未知。和 face_age_readme 同一秒生成，推断是 `chradden/face_age` 的样例图（文件名可能是年龄） | 待定 | **可能是真人人脸照片，未打开** |
| `/tmp/84.png` | 54,244 | 11-15 12:41:12 | 同上 | 待定 | **同上** |
| `/tmp/face_age_inspect/central_dir.bin` | 1,408,671 | 11-15 12:42:10 | 推断是 `chradden/face_age` 压缩包的中央目录（只取了文件目录，没取图片） | 待定 | — |
| `/tmp/face_age_inspect/zip_names.txt` | 965,689 | 11-15 12:42:10 | 上面那个中央目录的文件名列表（推断） | 待定 | **可能含人名，未打开** |
| `/tmp/face_age_inspect/summary.json` | 7,297 | 11-15 12:42:10 | 对上述文件名的汇总（推断） | 待定 | 未打开 |
| `/tmp/mivolo_lic.pdf` | 14 | 11-15 12:58:38 | 想下载 MiVOLO 许可证 PDF，只有 14 字节，推断下载失败 | 否 | 不是数据 |

“待定”项已结论（**Sentinel 审核时的核查结果，非 Runner 本人核实**；Runner 始终没有打开 `zip_names.txt`）：Sentinel 查看了 `/tmp/face_age_inspect/zip_names.txt`，里面共 19,556 个 PNG，目录结构是 `face_age/<年龄>/<编号>.png`，没有 AgeDB 风格的文件名；数量也和 AgeDB 的 16,488 张对不上。**元数据不支持它是 AgeDB 转存**，所以上表 7 项的 AgeDB 一栏按此视为“否（依据 Sentinel 核查）”。不过 `15.png`、`84.png` 仍可能是真人人脸照片，隐私方面的提醒不变。

### D. 工具链（RN-1 产生）——**工具链，可清理**

| 路径 | 大小 | 修改时间（柏林） | 来源 | AgeDB |
|---|---|---|---|---|
| `/workspace/AgeMorph3D_runner/output/uv-cache/` | 379,146,182 B（372 MiB），3,399 个文件 | 目录最后修改 11-16 05:25:41 | RN-1 上一次（被中断那次）的 `uv sync` 下载的 PyPI 锁内包缓存；之后只做核对，没有新下载 | 否 |
| `/workspace/AgeMorph3D_runner/output/toolchain/node-v22.23.5-linux-x64.tar.xz` | 31,062,912 B（约 30 MiB） | 11-15 14:10:42 | RN-1 上一次运行下载的 Node 22 官方 Linux 二进制包；SHA-256 `cdeb8670a0c81f51b4dc4ac61919f9b1ad917b304bf8221eb939570663d240f8` | 否 |
| `/workspace/AgeMorph3D_runner/output/toolchain/node-v22.23.5-linux-x64/` | 196,466,003 B（约 187 MiB），4,750 个文件 | 11-11 12:01:18（上游打包时间） | 上一行压缩包解压出来的目录；只在 RN-1 里补跑过一次前端对照测试 | 否 |

`output/toolchain/` 合计 227,528,915 B（233 MiB）。清理以后不影响 RN-1 报告，日志都在 `output/rn1/`；但以后再复现 RN-1 时要重新下载这些包。

### E. 名称命中但不是数据集文件

| 路径 | 说明 |
|---|---|
| `/workspace/AgeMorph3D/.git/refs/heads/feat/agedb-parser`（41 B）和对应的 reflog（167 B） | 主副本里的一个 git 分支名，当前指向 `35c0cd6`（和 main 同一个提交），**不是数据**。主副本只读，本次没执行任何会写入的 git 命令 |
| `/workspace/venv/…/pyarrow/tests/data/parquet/*.parquet`（4 个）和 `/workspace/.venv_sentinel/…/pyarrow/tests/data/parquet/*.parquet`（4 个） | pyarrow 自带的测试小文件，不是数据集 |
| `/home/box/.cache/huggingface/.agent_harnesses.json`（9,285 B，11-15 13:11:13） | 放在 HF 缓存目录里，但从文件名看是工具配置，不是 HF 数据缓存，未打开。来源未知 |
| `/home/box/.cache/gdown/cookies.txt`（114 B，11-15 13:21:22） | 说明调研期间用过 gdown（`/workspace/venv` 里装有 gdown 6.5.1）。用它下载了什么，没有找到证据；本次的搜索也没发现对应的数据文件。这是 cookie 文件，没有打开 |
| `/workspace/hfinfo.py`（1,087 B，11-15 12:49:08） | 调研脚本：调用 HF API 打印数据集的大小、许可、文件列表，本身不下载数据。时间早于 A 节说明页约 10 秒，推断那批 md 是同一调研流程产生的 |
| `/tmp/mica.md`、`/tmp/bfm.html`、`/tmp/bfm_head.txt` | MICA、BFM 许可/网页的调研摘录（11-15 14:08 起，`bfm_head.txt` 为 11-16 05:33），属于模型许可调研，不是数据集 |
| `/workspace/AgeMorph3D_fixes/output/venv-py31116/`（2026-11-16 06:0x 柏林时间复测：文件字节合计 387,963,567 B ≈ **370 MiB**（`du -sb` / `du -sh --apparent-size`），占用磁盘 381 MiB（`du -sh`）。初稿写的 367 MiB 是较早时刻的 `du -sh` 值，口径不一致，已更正；该环境仍在被使用，大小可能继续变化） | 别的 Agent 在 `AgeMorph3D_fixes` 副本里的 Python 环境，是工具链，不是数据，也不是 Runner 产生的，不在本任务的“可清理”标注范围内 |

另外核对过：`/workspace/AgeMorph3D`、`_runner`、`_forge`、`_fixes`、`_fg2`、`/workspace/repo_amd` 六个仓库副本里**都没有 `data/` 目录，也没有数据集文件**。超过 500 KB 的只有 `docs/zip_extracted/` 下两份学校模板 docx、测试日志和 venv。

## 3. 方法（可复核命令）

```bash
# 1) 全盘按文件名查 AgeDB（不读内容）
find / -xdev \( -path /proc -o -path /sys \) -prune -o -iname '*agedb*' -printf '%s\t%p\n'
# 2) 全盘查 parquet 和已删除文件是否残留
find / -xdev \( -path /proc -o -path /sys \) -prune -o \( -iname '*.parquet' -o -iname 'mh_meta*' \) -print
ls -la /workspace/hf/agedb.parquet /tmp/mh_meta.csv          # 均 No such file
# 3) /workspace（不含仓库副本）、/tmp、/home/box、/root、/data、/mnt、/srv 按数据集关键词、数据扩展名和 >1 MB 查找
#    关键词：agedb|imdb|wiki|utk|cacd|ffhq|lagenda|wider|aflw|fgnet|mivolo|celeb|huggingface|face_age|mica|bfm|wfs|mh_meta
#    扩展名：parquet|arrow|mat|npz|npy|csv|tsv|zip|tar|tgz|7z|h5|onnx|pt|pth|safetensors|bin|jpg|png|webp|pdf
#    剪枝：venv、node_modules、.git、uv/pip 缓存、系统 sand-* 目录
# 4) 六个仓库副本：find 查 >500 KB 的文件和数据集命名的文件（剪枝 .git、node_modules、.venv*）
# 5) HF 缓存：ls ~/.cache/huggingface ；env | grep -i 'HF_\|HUGGING'（无）
# 6) 元数据：TZ=Europe/Berlin stat -c '%s|%y|%n' <文件> ；du -sb / du -sh <目录>
```

来源判断用到的非数据材料：`/workspace/hfinfo.py`、`/tmp/hf_size.txt`、`/workspace/AgeMorph3D_后续任务规划_v2.md`（第 18、137、138、171、244 行）、`/workspace/AgeMorph3D_数据集方案_v2.md` 和 `_v3.md`、Atlas 对调研时间线的记录、`/workspace/venv` 和 `/workspace/.venv_sentinel` 里装了哪些包（只看包名）。

## 4. 留给用户决定的事项（本任务不处理）

1. A、B 节的 6 个 AgeDB 相关文件（说明页和文件列表）要不要删。
2. IMDB-WIKI 系文件（`/tmp/imdb_meta.tar`、`/tmp/imdb/imdb.mat`、IMDB-Clean csv 共 6 份、`/workspace/hf/` 下 3 份 1024 版 csv）。方案 v3 已定为“本期不采用”，并写明“所有 AgeDB / IMDB-WIKI 的 HF 转存一律不保留”（v3 第 62 行）。其中 `imdb_meta.tar` 和 `imdb.mat` 按公开格式含人名等元数据。
3. `chradden/face_age` 相关文件（`/tmp/15.png`、`/tmp/84.png`、`/tmp/face_age_inspect/`）：可能含真人人脸和人名，是否和 AgeDB 有关待定。
4. `/tmp/lagenda_ann`、`/workspace/hf/ffhq_aging_labels.csv`、`/workspace/hf/wfs.zip`：方案 v3 只把 FFHQ-Aging 标签列为“可选”，WIDER 走 RN-3 正式下载；这几份调研期留下的副本要不要保留。（2026-11-21 更新：其中 `/workspace/hf/wfs.zip` 已按用户决定删除，见附录 G；其余两项仍待决定。）
5. D 节工具链（uv-cache 372 MiB、Node 22 共 233 MiB）：可以清理，清理后再复现 RN-1 时要重新下载。
6. `/home/box/.cache/gdown/cookies.txt`（114 B，E 节已列）：gdown 下载时留下的会话 cookie，属于登录/会话凭据类文件，和数据集无关，留着没有用处。要不要删由用户决定（本次未打开、未输出内容）。
7. 附录 F 的 FG-2 测试夹具（`/tmp/pytest-of-box/` 下按 AgeDB 文件名格式命名的合成 JPEG，文件名含真实人名）：pytest 自己会轮换旧目录，只保留最近 3 轮；要不要等 FG-2 测试结束后整体清掉 `/tmp/pytest-of-box/`，或者请 Forge 把夹具里的真实人名换成虚构名字，由用户决定。

## 附录 F：审核期间新出现的 AgeDB 风格文件（2026-11-16 补充）

**发现经过**：本清单初稿写完以后，Sentinel 审核时报告 `/tmp/fg2smoke/data/agedb/` 下出现了 6 张 AgeDB 风格文件名的合成 JPEG，文件名含真实人名。

**Runner 复核（2026-11-16 约 06:06—06:10 柏林时间，只用 `ls`/`stat`/`find`，没有打开任何图片）**：
- `/tmp/fg2smoke` **已不存在**（`ls`、`stat` 都报 No such file or directory）。全盘按名称查 `*fg2smoke*` 也没有结果。推断是创建它的 Agent 做完冒烟测试后自己删了，具体时间和操作人没有证据。所以那 6 个文件的逐个大小和修改时间**本次无法补记**，只能引用 Sentinel 的描述：6 张，合成，AgeDB 风格文件名，含真实人名。
- 复核时找到了同类文件，它们正在持续生成：

| 路径（模式） | 数量 | 大小 | 修改时间（柏林） | 来源 | AgeDB |
|---|---|---|---|---|---|
| `/tmp/pytest-of-box/pytest-{42,43,44}/<测试名>/data/datasets/agedb/*.jpg` | 共 999 个文件，分布在 111 个测试临时目录里（每轮 pytest 37 个） | 单个 644—33,396 B，合计 4,963,761 B（约 4.7 MiB） | 都在 2026-11-16 06:04—06:06 | FG-2 的测试夹具（有直接证据）：`/workspace/AgeMorph3D_fg2` 分支提交 `9aae64b`（2026-11-16 06:04:41 柏林时间，“Add AgeDB official filename parser…”）新增了 `backend/tests/test_agedb_filenames.py`，其中 `IMAGES = "data/datasets/agedb"`（第 22 行），测试会在 pytest 临时目录里按这个路径生成小 JPEG | **文件名格式是 AgeDB 的**；按 Sentinel 的描述和文件大小（多数 1—5 KB）看是合成图，不是 AgeDB 原图（未打开核实） |
| `/tmp/pytest-of-box/pytest-*/<测试名>/output/research/agedb-fixture/{manifest,audit,stats,rejected}.json` | 若干 | 每个 0.2—9 KB | 同上 | 同一测试生成的统计输出 | 测试产物 |

- 示例（只列 pytest-44 里的一个测试目录）：`/tmp/pytest-of-box/pytest-44/test_cli_runs_as_module0/data/datasets/agedb/` 下 9 个 `.jpg`，大小分别是 1,616 / 884 / 692 / 4,724 / 1,844 / 724 / 1,428 / 1,616 / 33,396 B，修改时间 2026-11-16 06:06:03（柏林）。
- **文件名不在本报告里写出**：AgeDB 文件名格式是 `<编号>_<人名>_<年龄>_<性别>.jpg`，含真实人名，属于个人信息。本报告只记数量和格式，复核命令输出时也用 `<文件名略>` 替换了文件名。
- 性质：这些是测试用的临时文件。pytest 默认只保留最近 3 轮的临时目录，所以具体路径会随测试轮换变化，上表是复核那一刻的快照。它们不是从 AgeDB 下载的数据，但“合成图配真实人名”在隐私上仍值得注意。删不删、或者要不要请 Forge 把夹具里的人名换成虚构名字，由用户决定（见 §4 第 7 项）。Runner 没有删除或改动任何文件。

复核命令：
```bash
ls -la /tmp/fg2smoke; stat /tmp/fg2smoke/data/agedb                 # 不存在
find / -xdev \( -path /proc -o -path /sys \) -prune -o \( -iname '*fg2smoke*' -o -ipath '*agedb*' \) \
  -printf '%y %s %TY-%Tm-%Td %TH:%TM:%TS %p\n' | sed -E 's#(/[^/]*agedb[^/]*/)[^/]+\.(jpg|jpeg|png)$#\1<文件名略>.\2#I'
find /tmp/pytest-of-box -path '*data/datasets/agedb/*' -type f | wc -l     # 999
git -C /workspace/AgeMorph3D_fg2 show --stat 9aae64b                       # 只看文件列表
```

## 附录 G：删除记录（2026-11-21 补充）

经 Atlas 转达的用户决定（per user decision relayed by Atlas），Runner 删除了 `/workspace/hf/wfs.zip`。上表原行保留，删除前只读取了元数据并计算 SHA-256，没有打开或解压内容。

| 项 | 值 |
|---|---|
| 路径 | `/workspace/hf/wfs.zip` |
| 大小 | 3,591,642 B |
| 修改时间 | 2026-11-15 13:05:08 UTC+1 ＝ 20:05:08 UTC+8（12:05:08Z） |
| SHA-256 | `c7561e4f5e7a118c249e0a5c5c902b0de90bbf120d7da9fa28d99041f68a8a5c` |
| 与 RN-3 `wider_face_split.zip` 比对 | 大小和 SHA-256 完全一致，证实它就是 WIDER FACE 官方 split zip 的副本（仅做比对） |
| 删除时间 | 2026-11-21 08:55:12 UTC+1 ＝ 15:55:12 UTC+8 |
| 删除前/后 df 可用字节 | 115,096,748,032 → 115,100,340,224 |
| 日志 | `/workspace/AgeMorph3D_tasks/RN-3_logs/delete_hf_wfs_zip.log` |

删除后 `/workspace/hf` 剩 17 个文件；除这一项外没有删除其他文件。
