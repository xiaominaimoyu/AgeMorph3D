# MT-1 代码规模统计（内部参考，不进论文）

仅作内部参考，不进论文。这不是 L03 签认，也不是学校计数或个人工作量证明。

仓库原话（逐字引用）：

> 物理行数不证明个人原创贡献。注释、空行、测试、文档、生成文件和历史新增行都不是学校计数或个人工作量。1500 行/人与 4500 行/项目只作信息对照。
>
> ——出处：`tools/code_stats.py` 第 26–29 行常量 `DISCLAIMER`（提交 `35c0cd61b70976393f919dfff34834bad9a67dc8`）

同仓库另一处原文：

> 统计只作信息，不改变“物理行数不代表原创工作量或学校计数方式”。
>
> ——出处：`docs/毕业设计要求与交付清单.md` 第 76 行

说明：任务规划 MT-1 验收用语“物理行数不代表原创贡献”是对上述原文的缩写；本文按仓库原文逐字引用，不改写。

作者到成员 A/B 的映射列一律标为“待用户确认”，未做任何猜测。脚本对现存文件物理行的划归为“不计算”（`physical_lines_attributed` 为 null；`attribution` 为 `not_computed_current_lines_are_not_personal_property`）。本文未使用 `git blame`。

运行时刻：2026-11-15 21:07（UTC+8）。

---

## 1. 统计口径

| 项 | 值 |
|---|---|
| 仓库路径 | `/workspace/AgeMorph3D`（已跟踪文件未修改、未切分支、未 commit、未 checkout；当前 `git status --short` 为空） |
| 提交（完整） | `35c0cd61b70976393f919dfff34834bad9a67dc8` |
| 提交（短号） | `35c0cd6` |
| 分支 | `main` |
| 工作树 | 干净（`git status --porcelain` 为空；`dirty=false`） |
| 统计工具 | `tools/code_stats.py`（schema_version 1，task L03，role information_only） |
| 映射输入 | `tools/author-members.template.json`（模板中 `git_author`/`member` 均为空行，脚本跳过，映射为空） |
| Python | 3.13.5 |
| 对照阈值 | 任务书 L03：1500 行/人、4500 行/项目（只作信息对照） |

### 1.1 为何未直接把脚本输出写进仓库

`tools/code_stats.py` 的 `main()` 通过 `resolve_output()` 把 JSON/Markdown 报告限制为只能写在项目内的 `output/` 或 `logs/`。写入这两处会改动工作树，违反本任务“仓库副本严格只读”。脚本也不允许把 `--output`/`--markdown` 指到仓库外（会报 `OUTPUT_OUTSIDE_PROJECT`）。

因此未执行会写盘的 `python tools/code_stats.py --output ...`。实际做法：在仓库外 `import` 该模块，调用只读函数 `build_report(root, "HEAD", members_template)` 与 `render_markdown(report)`，把原始结果写到 `/tmp/MT-1_code_stats/report.json` 和 `/tmp/MT-1_code_stats/report.md`。初次运行时，该 `import` 在仓库内生成了被 `.gitignore` 忽略的字节码缓存 `tools/__pycache__/code_stats.cpython-313.pyc`；该文件不是已跟踪文件，当时 `git status` 仍干净，但缓存由本次统计生成。该缓存文件已删除，空的 `__pycache__` 目录一并删除。已跟踪文件未被修改；当前 `HEAD` 仍为 `35c0cd61b70976393f919dfff34834bad9a67dc8`，`git status --short` 为空。以后运行使用 `python -B` 或 `PYTHONDONTWRITEBYTECODE=1`，避免再次生成字节码。

脚本内部实际调用的只读 git 命令：

- `git rev-parse --verify HEAD`
- `git rev-parse --abbrev-ref HEAD`
- `git ls-tree -r -z <revision>`
- `git cat-file --batch`
- `git log <revision> --pretty=format:%x1e%H%x1f%aN%x1f%aE%x1f%P --numstat`
- `git status --porcelain`

随后用同一套 `classify_path` / `physical_lines` / `history_by_author` 逻辑在仓库外独立重算，与 `report.json` 完全一致。

### 1.2 物理行（按模块）怎么数

- 对象：指定提交树中的已跟踪 blob，不是工作区未提交文件（`counts_match_head_not_uncommitted_files=true`）。
- 计数：对每个文本 blob，`len(data.splitlines())`，即物理行，包含空行与注释，不按语言语法剔除。
- 文本判定：内容中含 NUL 字节（`b"\0"`）则视为二进制，不计入物理行。
- 无按扩展名的白名单或黑名单：已跟踪的文本文件不论扩展名都计入。
- 不计入：子模块（mode `160000`，本提交中无）；二进制文件（本提交 10 个，见下表）；未跟踪/未提交文件。
- 本提交已跟踪 blob 共 409 个：文本 399 个、二进制 10 个。已跟踪路径中无 `output/`、`logs/`。

### 1.3 模块（区域）划分

脚本常量 `AREAS = ("frontend", "backend", "preprocessing", "tools", "tests", "docs")`。分类规则（`classify_path`）：

1. 路径任一段为 `tests`，或文件名以 `test_` 开头、以 `_test.py` 结尾，或文件名含 `.test.` / `.spec.`，一律记为 `tests`（即使位于 `backend/` 等产品目录下）。
2. 否则，若路径第一段属于上述六个区域且不是 `tests`，记入该区域。
3. 其余记为 `other`（例如根目录文档、`design/`、`training/`）。`other` 不计入“六区物理行”。

与 4500 行对照使用的是**六区物理行**（`scoped_physical_lines`），不是“已跟踪文本物理行合计”。

### 1.4 按作者怎么数（不是当前文件的 blame 物理行）

- 作者身份原样取自 git：`Name <email>`（`%aN` / `%aE`）。
- 提交数包含合并提交；新增/删除行只统计**非合并提交**的 `git log --numstat`（合并提交的 numstat 被跳过）。
- 二进制变更单独计数（added/deleted 为 `-`），不计入新增/删除行。
- **当前树的物理行不按作者划分。** 本文未运行 `git blame`。按作者表中的是历史新增/删除，与按模块表中的现存物理行不是同一个数。

### 1.5 已跟踪文本的扩展名分布（辅助口径，不是学校分类）

| 扩展名 | 文件数 | 物理行 |
|---|---:|---:|
| `.py` | 188 | 75038 |
| `.ts` | 32 | 10756 |
| `.md` | 95 | 10282 |
| `.mjs` | 18 | 7972 |
| `.json` | 47 | 4336 |
| `.css` | 5 | 2137 |
| `.html` | 5 | 1010 |
| `.lock` | 1 | 626 |
| `.ps1` | 3 | 83 |
| 无扩展名（`.gitignore`、`LICENSE`） | 2 | 70 |
| `.toml` | 1 | 43 |
| `.cmd` | 1 | 17 |
| `.svg` | 1 | 1 |
| **文本合计** | **399** | **112371** |

### 1.6 未计入物理行的二进制文件（10 个）

| 路径 |
|---|
| `docs/zip_extracted/1-任务书模板.docx` |
| `docs/zip_extracted/2-开题报告模板.docx` |
| `docs/zip_extracted/3-毕业设计（论文）中期报告模板.docx` |
| `docs/zip_extracted/4-本科毕业设计说明书模板.docx` |
| `docs/zip_extracted/5-软件使用说明书模板.docx` |
| `docs/zip_extracted/6-外文翻译模板.docx` |
| `docs/【任务书】基于YOLO与三维形变模型的跨年龄三维人脸重建及可视化系统.doc` |
| `docs/任务书模板/【任务书】岁月镜AgeMorph3D-基于YOLO与三维形变模型的跨年龄三维人脸重建及可视化系统.docx` |
| `docs/任务书模板/附件4：2024届本科毕业设计论文+模板_计算机科学与技术（示例0513）(1).docx` |
| `docs/审核评估-毕业设计要求.docx` |

---

## 2. 按模块的物理行数

数字来自提交 `35c0cd61b70976393f919dfff34834bad9a67dc8` 的已跟踪文本文件。

| 区域 | 文件数 | 物理行 | 是否计入六区（对 4500 的对照口径） |
|---|---:|---:|---|
| frontend | 33 | 10686 | 是 |
| backend | 45 | 10763 | 是 |
| preprocessing | 11 | 5213 | 是 |
| tools | 56 | 26614 | 是 |
| tests | 114 | 44833 | 是 |
| docs | 125 | 12021 | 是 |
| **六区小计** | **384** | **110130** | **是（`scoped_physical_lines`）** |
| other | 15 | 2241 | 否 |
| **已跟踪文本合计** | **399** | **112371** | 否（含 other） |

`other` 路径明细：

| 路径 | 物理行 |
|---|---:|
| `design/index.html` | 684 |
| `training/preflight.py` | 501 |
| `PROGRESS.md` | 217 |
| `README.md` | 128 |
| `TASKS.md` | 120 |
| `design/设计系统说明.md` | 114 |
| `training/baseline-draft-v1.json` | 113 |
| `ARCHITECTURE.md` | 109 |
| `PRD.md` | 80 |
| `.gitignore` | 49 |
| `DESIGN.md` | 49 |
| `RULES.md` | 35 |
| `LICENSE` | 21 |
| `design/overview.md` | 20 |
| `training/__init__.py` | 1 |
| **other 合计** | **2241** |

---

## 3. 按 git 作者的历史新增/删除行

身份原样来自 git，未做合并或改写。成员映射留空，标“待用户确认”。下表是非合并提交的历史 numstat，**不是**当前文件按作者划分的物理行。

| git 作者 | 成员 A/B | 提交数 | 其中合并提交 | 非合并提交 | 历史新增行 | 历史删除行 | 二进制变更次数 | 划归的现存物理行 |
|---|---|---:|---:|---:|---:|---:|---:|---|
| `MingYao Song <24…@qq.com>` | 待用户确认 | 56 | 6 | 50 | 104177 | 1178 | 0 | 不计算 |
| `Cursor Agent <cursoragent@cursor.com>` | 待用户确认 | 20 | 8 | 12 | 7032 | 180 | 0 | 不计算 |
| `AgeMorph3D Team <agemorph3d@local>` | 待用户确认 | 1 | 0 | 1 | 2506 | 0 | 10 | 不计算 |
| **合计** | — | **77** | **14** | **63** | **113715** | **1358** | **10** | 不计算 |

独立核对：`git rev-list --count 35c0cd61b70976393f919dfff34834bad9a67dc8` 为 77，与上表提交数合计一致。

提示：作者 `Cursor Agent <cursoragent@cursor.com>` 在非合并提交中新增 7,032 行，将来整理 L03 个人贡献时需要和用户本人的提交分开说明。本条仅为提示，不下结论。

各作者历史新增/删除按区域（非合并提交 numstat；空行表示该区域增减均为 0，仍列出便于对照）：

| git 作者 | 区域 | 历史新增 | 历史删除 |
|---|---|---:|---:|
| `MingYao Song <24…@qq.com>` | frontend | 10862 | 176 |
| `MingYao Song <24…@qq.com>` | backend | 10941 | 222 |
| `MingYao Song <24…@qq.com>` | preprocessing | 5213 | 0 |
| `MingYao Song <24…@qq.com>` | tools | 21877 | 6 |
| `MingYao Song <24…@qq.com>` | tests | 43342 | 183 |
| `MingYao Song <24…@qq.com>` | docs | 10535 | 520 |
| `MingYao Song <24…@qq.com>` | other | 1407 | 71 |
| `Cursor Agent <cursoragent@cursor.com>` | backend | 49 | 5 |
| `Cursor Agent <cursoragent@cursor.com>` | tools | 4300 | 98 |
| `Cursor Agent <cursoragent@cursor.com>` | tests | 1707 | 32 |
| `Cursor Agent <cursoragent@cursor.com>` | docs | 926 | 34 |
| `Cursor Agent <cursoragent@cursor.com>` | other | 50 | 11 |
| `AgeMorph3D Team <agemorph3d@local>` | tools | 526 | 0 |
| `AgeMorph3D Team <agemorph3d@local>` | docs | 1114 | 0 |
| `AgeMorph3D Team <agemorph3d@local>` | other | 866 | 0 |

---

## 4. 对照任务书 L03（1500 行/人、4500 行/项目）

只作信息对照。脚本字段 `passes_requirement` 固定为 `false`，`l03_signed_off` 为 `false`。六区物理行包含测试、文档、工具脚本、空行和注释；按仓库原话，这些都不是学校计数或个人工作量。

产品代码小计（frontend + backend + preprocessing，不含 tools / tests / docs / other）：10686 + 10763 + 5213 = 26,662 行。此口径不是脚本中用于对照 4500 的 `scoped_physical_lines`（六区 110130），只作内部参考。

对照参考（交付清单原文，逐字引用）：

> 每人代码≥1500行、项目≥4500行，§五（一） | 本轮[工程源码规模快照](../output/research/thesis-purpose-20261030/source-size-snapshot.json)含67份核心PY/TS、20335物理行 | 阈值按用户提供的任务书登记；快照包含注释/文档字符串，不代表原创工作量或学校计数方式，每人归属仍unknown。后续按真实开发/审查记录核贡献，不能用测试、上游代码或自动生成行数充数
>
> ——出处：`docs/毕业设计要求与交付清单.md` 第 32 行

| 对照项 | 口径 | 实测值 | 阈值 | 差值 | 相对阈值（脚本 `_compare`） | 是否可作为通过结论 |
|---|---|---:|---:|---:|---|---|
| 项目（六区物理行） | `scoped_physical_lines` | 110130 | 4500 | +105630 | above | 否（`passes_requirement` 固定为 false；仅内部参考，不进论文） |
| 项目（已跟踪文本合计） | 六区 + other，不用于官方对照 | 112371 | 4500 | +107871 | （非脚本对照口径） | 否 |
| 成员 A | 映射作者的历史新增行 | 未映射，不汇总 | 1500 | — | 待用户确认 | 否 |
| 成员 B | 映射作者的历史新增行 | 未映射，不汇总 | 1500 | — | 待用户确认 | 否 |

成员汇总表（映射为空，数字为脚本在未映射时的输出，不是“该成员零贡献”）：

| 成员 | 映射作者数 | 已映射的 git 作者 | 历史新增行 | 历史删除行 | 相对 1500 | 划归的现存物理行 |
|---|---:|---|---:|---:|---|---|
| A | 0 | （空，待用户确认） | 0 | 0 | 不比较（`null`） | 不计算 |
| B | 0 | （空，待用户确认） | 0 | 0 | 不比较（`null`） | 不计算 |

---

## 5. 运行说明与限制

- 全部数字来自对提交 `35c0cd6` 的实际运行与独立重算，未编造。
- 未绘制任何图表或生成图片（图表由学生本人按任务书要求绘制）。
- 未把 git 作者映射到 A/B，等待用户确认（规划中的 U-3）。
- 原始机器可读结果：`/tmp/MT-1_code_stats/report.json`、`/tmp/MT-1_code_stats/report.md`（脚本 `render_markdown` 的直接输出）。
