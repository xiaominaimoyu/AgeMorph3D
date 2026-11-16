# FG-2 AgeDB 官方文件名解析与本机统计

2026-11-16 完成 FG-2 合成工程子项：按数据集方案 v3 §4 第 4 步（“§4.4”），解析官方文件名 `<id>_<name>_<age>_<gender>.jpg`，在用户本机对已解压的官方文件夹重新统计 v3 §2-A 的各项数字，并写出 K5 清单与审计。新增 117 项合成测试；完整后端 3006 → 3123 项通过（Python 3.11.16 / Pillow 13.0.0，1 条既有 Starlette 警告）。3 项跳过取决于环境：`test_local_run.py:810` 需设 `AGEMORPH_LOCAL_RUN_LIVE=1`，`test_local_run.py:947` 与 `test_repro_check.py:315` 在没有项目 venv/Vite 时跳过。Ruff 0.17.1 check/format 只针对新增的两个文件通过；35c0cd6 全库仍有 17 处既有 I001。**没有取得、读取或下载任何 AgeDB 官方包、镜像或转存；测试只用临时目录里生成的合成文件名和小图。**

代码：[agedb_filenames.py](../preprocessing/agedb_filenames.py)；测试：[test_agedb_filenames.py](../backend/tests/test_agedb_filenames.py)。

## 1. 运行（只在用户本机）

CLI **默认拒绝运行**，必须显式传入 `--local-only-ack` 才会执行。未传时退出码 2、向 stderr 说明原因，不写任何文件。传入后启动时向 stderr 打印醒目警告「含文件名的输出仅限用户本机」。

```powershell
& 'backend/.venv/Scripts/python.exe' -m preprocessing.agedb_filenames --help
& 'backend/.venv/Scripts/python.exe' -m preprocessing.agedb_filenames `
  --local-only-ack `
  --images-dir data/datasets/agedb --output-dir output/research/agedb-stats-v1
```

脚本只读文件夹，不接收也不需要解压密码（用户自己解压）。退出码：0 全部文件名合法、图片头可读且输入在运行中未变；1 有被拒文件名、读不了的图片或输入变化（输出照常写出，需要人工看 `rejected.json`）；2 整体拒绝（未传 `--local-only-ack`、参数/路径非法、输出目录已存在、没有任何合法文件、超出预算等），不留任何输出：所有读取、哈希和 JSON 组装都在建目录之前完成，写文件中途出错会删掉本次新建的输出目录及本次新建的空父目录。

输出（新的 `output/research/` 目录，已被 .gitignore 忽略）：

| 文件 | 内容 | 能否离开本机 |
|---|---|---|
| `stats.json` | 只有汇总数字、拒绝原因计数、清点哈希、运行环境（Python 实际补丁号、Pillow 版本）和标志位；不含文件名、人名、图片编号或身份编号 | 设计上只含汇总，但正式回传仍走 FG-8 的 `summary.json` 白名单，回传前用户自己看一眼 |
| `rejected.json` | 每个被拒条目的相对路径和原因；顶层带 `local_only: true` | 不能（含文件名） |
| `audit.json` | `audit_manifest` 结果，属外层报告，顶层带 `local_only: true` | 不能（含文件名/样本编号） |
| `manifest.json` | K5 清单，**保持 K5 字段结构不变**，不加 `local_only` | 不能（含文件名） |

## 2. 解析契约

- 后缀：`.jpg`（大小写不敏感）；内容只按 JPEG 读头，`Image.open(..., formats=["JPEG"])`，其他格式即使后缀是 .jpg 也不会被探测。
- 拆分：按 `_` 分割，第一段是 id，最后两段是 age 和 gender，中间全部拼回作为 name。所以名字里可以有下划线；名字末尾的 `_<数字>` 也算名字的一部分。
- id：ASCII 数字、不带前导零（`0` 除外）、最多 9 位。id 是**图片**编号，不是人；同一 id 出现在多个文件上时，所有副本都拒绝（`DUPLICATE_IMAGE_ID`），不挑任何一个。
- name：非空；首尾不能是空格或下划线；不能有控制/格式类字符（Unicode C 类，例如零宽空格）；最多 200 字符。身份 = NFC 规范化后的名字，**区分大小写**；只差大小写的名字会在 `identities_differing_only_by_case` 中计数，留给人工核对，不自动合并。
- age：ASCII 整数、不带前导零、0—120（与 `dataset_manifest.age_label` 一致）。20—70 以外的年龄是合法记录，照常进入 K5 和统计（审计里标 `outside`），不会被拒，也不会被改成默认值。
- gender：只接受官方的小写 `m`（male）和 `f`（female）；大写、空、其他字母或单词一律 `GENDER_INVALID`。K5 没有性别字段，性别只出现在 `stats.json` 的计数里。

拒绝原因码：`SUFFIX_NOT_JPG`、`FILENAME_PATTERN_MISMATCH`、`ID_INVALID`、`NAME_INVALID`、`AGE_NOT_INTEGER`、`AGE_LEADING_ZERO`、`AGE_OUT_OF_RANGE`、`GENDER_INVALID`、`FILENAME_NOT_UTF8`、`PATH_NOT_UTF8`、`DUPLICATE_IMAGE_ID`、`PATH_INVALID`（Windows 不允许的字符/保留名等）、`LINK_OR_REPARSE_PATH`、`PATH_TOO_DEEP`（`--images-dir` 下最多 3 层子文件夹）、`NOT_REGULAR_FILE`、`FILE_EMPTY`、`IMAGE_TOO_LARGE`（>16 MiB）、`FILE_UNREADABLE`。每个被扫描到的条目要么进 K5，要么进 `rejected.json`，`k5_records + rejected = entries_scanned`。

文件名合法但图片头读不了（截断、非 JPEG、解压炸弹）的图片仍进 K5，状态 `failed`、原因 `agedb_header:IMAGE_UNREADABLE`；它们参与按文件名的年龄/身份统计，不参与最短边统计（`images_without_size` 单独计数）。

## 3. 统计口径（对应 v3 §2-A）

| 字段 | 口径 |
|---|---|
| `images` / `identities` | 进入 K5 的图片数 / 不同名字数 |
| `images_age_20_70` | 20 ≤ age ≤ 70（两端都含） |
| `images_age_exact_70` | age == 70 |
| `identities_span_ge_30` | 每人 max(age) − min(age) ≥ 30（含 30），用该人全部年龄 |
| `identities_span_ge_30_within_20_70` | 同上，但只用 20—70 岁的图片（v3 §2-A 没写明是哪种，两种都给） |
| `short_side_px` | min(宽, 高) 的 min/max/中位数（偶数个时取中间两数平均）、最近秩分位 p5/p25/p50/p75/p95、`below_128` 和分箱直方图；EXIF 方向不影响最短边，只计数 `exif_orientation_not_identity` |
| `filter_short_ge_128_age_20_70` | 口径一：最短边 ≥128 且 20—70 岁，过滤后重新算张数、人数、跨度 ≥30 人数、70 岁张数 |
| `filter_short_ge_128` | 口径二：只要求最短边 ≥128 |

另给年龄十年分箱、性别计数、年龄最小/最大值。比对 v3 §2-A 的工作由 MT-2 只用汇总数字完成，本工具不内置 HF 镜像的参考值。

## 4. K5 与划分

每条记录：`sample_id=agedb:<id>`、`dataset_id=agedb-official`、`subject_id=agedb-subject:<名字 SHA-256 前 24 位>`、`kind=original`、`use=unassigned`、`age` 为 exact 整数、`age_source=dataset_annotation`（官方人工年龄标注写在文件名里）、`exposure.preprocessing=yes`，其余 exposure 为 unknown。`subject_id` 只是为满足 K5 标识符语法的化名，名人名字可以被字典反查，**不是匿名化**，清单本身仍只能留在本机。数据集 `version` 绑定清点哈希 `inventory_sha256`（全部 K5 文件的 SHA-256/字节数/路径和全部拒绝条目），文件夹内容一变就不同。清单经 `validate_manifest` 校验、能被 `dataset_manifest` CLI 读回；超过 K5 的 16 MiB 读取上限时整体拒绝。按 16,488 条、28 字符名字估算约 13.5 MiB。**本工具不分配 train/validation/test，不改 `split_freeze.py`**，`split_assignment_performed=false`。

## 5. 局限

- 文件名约定只来自 v3 §4 与原论文描述，没有对照真实官方包；`verified_on_real_data` 与 `identity_from_name_verified_on_real_data` 保持 false。
- 身份按名字字符串认定；同名不同人、同一人不同拼写都无法从文件名区分，只能人工核对。
- 只接受小写 m/f 和 `.jpg` + JPEG 内容；如果官方包里有别的写法，会被如实拒绝或记为失败，不会自动放宽。
- 读取 EXIF 方向只做计数；不解码像素，也不做人脸检测或质量评估。

## 6. LX-2（用户拿到官方包后）的核对

1. 看 `rejected.json` 和 `image_failures_by_code`：真实包里是否有被拒文件名或读不了的图，命中几处；有命中先记录原因再决定，不自动跳过。
2. 抽查几个文件名，确认 id/name/age/gender 顺序、性别字母和名字拼写与本工具假设一致，再考虑把两个 `verified_*` 标志改为 true。
3. 核对 `identities` 是否为官方的 568，`images` 是否为 16,488；只差大小写的名字逐个人工确认。

## 7. 提交与署名

本地提交以 `Forge (AI agent)` 署名，未推送，push 地址设为 `DISABLED_NO_PUSH`。RULES 第 14 行要求先确认精确文件清单再做 Git 操作：本批提交的文件清单**事先没有经用户确认**，清单见 `/workspace/AgeMorph3D_tasks/FG-2_说明.md`，请用户补确认；署名由用户在任何 push/PR 前决定，建议保留 AI 来源。
