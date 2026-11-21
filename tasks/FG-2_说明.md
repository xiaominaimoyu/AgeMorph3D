# FG-2 说明：AgeDB 官方文件名解析与本机统计 CLI

> **署名改写（2026-11-21 约 16:20 UTC+8，FG-PUSH-PREP，用户本人确认、经 Atlas 转达）：**本地分支上作者或提交者为 Forge (AI agent) 的提交已改写为作者和提交者都是 MingYao Song <2441377859@qq.com>，并加 `Co-authored-by: Forge (AI agent) <forge-agent@agemorph3d.invalid>`；作者时间、提交时间、提交说明正文和树内容都没变。下文提交哈希已换成新哈希，括号里是原哈希；表格里“作者”栏写的 Forge (AI agent) 是改写前的状态。备份引用 `refs/backup/pre-rewrite/<分支名>`，完整对照见 `署名改写记录.md`。

- 执行：Forge（AI agent），2026-11-16（UTC+1）
- 仓库：`/workspace/AgeMorph3D_fg2`（git worktree，基于 `35c0cd6`），本地分支 `feat/agedb-parser`
- push 地址已设为 `DISABLED_NO_PUSH`（`git config --worktree`，只影响本 worktree；主副本未改）。**未 push、未开 PR、未碰 GitHub。**
- 数据边界：没有读取、下载或打开任何 AgeDB 官方包、HF 转存或 `/workspace/hf` 下的文件；测试只在临时目录里生成合成文件名和小图。

## 1. 做了什么

新增 `preprocessing/agedb_filenames.py`：用户拿到官方包、自己解压后，在本机对文件夹运行，按 v3 §4 第 4 步（§4.4）用官方文件名 `<id>_<name>_<age>_<gender>.jpg` 重新统计 v3 §2-A 的数字。

- **解析**：按 `_` 切分，id 取最左段，age 和 gender 取最右两段，中间全部是名字，所以名字里有下划线也能正确解析。
- **统计**：20—70 岁张数、正好 70 岁张数、年龄跨度 ≥30 岁的人数（同时给“全部年龄”和“只看 20—70 岁”两种口径）、最短边分布（min/max/中位数/分位数/<128 张数/分箱），以及 v3 §2-A 的两个过滤口径（最短边 ≥128 且 20—70；只要求最短边 ≥128）各自重算的张数、人数、跨度人数、70 岁张数。
- **坏文件名**：逐条拒绝并写明原因（18 种原因码），不静默丢弃；`k5_records + rejected = entries_scanned`。
- **K5**：每个合法文件一条 K5 记录，经 `dataset_manifest.validate_manifest` 校验并写 `audit_manifest` 结果，能被 `dataset_manifest` CLI 读回；`use=unassigned`，不分配 train/validation/test，不改 `split_freeze.py`。
- **输出分级**：`stats.json` 只有汇总数字，不含文件名、人名、图片 id 或身份编号（有测试断言）；`rejected.json`、`manifest.json`、`audit.json` 含文件名，只能留在本机。
- **约定沿用 FG-1**：输出只能是新的 `output/research/` 目录；所有读取、哈希和 JSON 组装在建目录前完成，写出中途失败会删除本次新建的目录和空父目录（退出码 2 不留输出）；`Image.open(formats=["JPEG"])` 只读头不解码；解压炸弹警告按错误处理；拒绝符号链接/重解析点；16 MiB 单图上限、K5 16 MiB 上限、其他输出 64 MiB 上限；无网络、pickle、eval、torch。
- `stats.json` 记录 `python_runtime`（实际补丁号）和 `pillow_version`，避免 Sentinel 在小修复分支提出的那类溯源缺失。

## 2. 文件

| 文件 | 说明 |
|---|---|
| `preprocessing/agedb_filenames.py` | 新增，解析 + 统计 + K5 + CLI（500 行） |
| `backend/tests/test_agedb_filenames.py` | 新增，113 项合成测试（650 行） |
| `docs/AgeDB文件名解析开发记录.md` | 新增，仓库内开发记录 |
| `ARCHITECTURE.md`、`TASKS.md`、`PROGRESS.md` | 各加一条 FG-2 记录（RULES 要求维护六份说明） |

复用、未修改：`dataset_manifest.py`、`resource_acquisition.py`、`archive_preparation.py`、`annotation_transform.py`、`split_freeze.py`。

## 3. 设计决定（与 v3 §4.4 / §2-A 的对应）

| 问题 | 决定 | 理由 |
|---|---|---|
| 名字含下划线 | id 取左，age/gender 取右，中间都是名字；名字末尾的 `_<数字>` 归名字 | 官方格式两端固定，中间是唯一可变段 |
| 身份 | NFC 规范化后的名字，区分大小写；只差大小写的单独计数，不自动合并 | AgeDB 的 id 是图片编号，人由名字区分；自动合并可能把不同的人并在一起 |
| 年龄有效性 | ASCII 整数、无前导零、0—120；20—70 以外照常保留并计数 | 与 `age_label` 上限一致；RULES 禁止把年龄改成默认值；v3 需要 19/71 这类边界也被统计 |
| 性别 | 只接受小写 `m`=male、`f`=female，其他全部拒绝 | 官方写法；不猜测大写或其他写法 |
| 重复 id | 所有副本都拒绝 | 不替用户挑选哪一份 |
| 图片头读不了 | 进 K5（`failed`），参与年龄统计，不参与最短边统计 | 保留失败分母，年龄来自文件名 |
| 跨度 ≥30 | 每人 max−min ≥30，两种口径（全部年龄 / 只看 20—70） | v3 §2-A 没写明用哪种 |
| age_source | `dataset_annotation` | 官方人工年龄标注写在文件名里；不是研究者自己推断的 |
| subject_id | `agedb-subject:<名字 SHA-256 前 24 位>` | 满足 K5 标识符语法；**不是匿名化**（名人名字可被反查），清单仍不出本机 |
| 不内置 HF 参考值 | 只出官方统计，比对交给 MT-2 | 计划 §0.6：只和 v3 §2-A 已记录的汇总比对，不用转存 |

## 4. 用户在本机怎么运行

前提：已按 LX-1 把官方 AgeDB.zip 自己解压到 `data/datasets/agedb/`（密码只在用户手里，脚本不接收密码）。在项目根目录（如 `D:\project file\AgeMorph3D`）PowerShell 中：

```powershell
& 'backend/.venv/Scripts/python.exe' -m preprocessing.agedb_filenames `
  --images-dir data/datasets/agedb --output-dir output/research/agedb-stats-v1 `
  --local-only-ack
```

- 退出码 0：全部合法、可读、输入未变；1：有被拒文件名/读不了的图/输入变化，输出照常写出，请看 `rejected.json`；2：整体拒绝（如输出目录已存在、路径非法、没有合法文件），不留输出。
- 终端打印的 JSON 和 `stats.json` 都只有汇总；`rejected.json`、`manifest.json`、`audit.json` 不要发给任何机器人。正式回传给团队仍走 FG-8 的 `summary.json`，回传前自己看一眼。

## 5. 测试

环境：box Linux，Python 3.11.16 + Pillow 13.0.0 + ruff 0.17.1，`uv sync --project backend --frozen --offline --extra inference --python 3.11.16`，venv 在仓库外 `/workspace/.venvs/agemorph-fg2-31116`（只用本机 uv 缓存，未联网下载）。命令在 `backend/` 下：`python -B -m pytest -q -rfEsxX -p no:cacheprovider`。

| 项 | 结果 |
|---|---|
| 35c0cd6 完整后端（改动前） | 3006 通过 / 3 跳过 / 0 失败 |
| feat/agedb-parser 完整后端（3ff80d6（原 377acae） 后） | **3123 通过** / 3 跳过 / 0 失败（新增 117 项；0376625（原 23a480d） 时为 3119/113） |
| `tests/test_agedb_filenames.py` | 117 通过 |
| ruff 0.17.1 check / format | **只针对新增的两个文件**通过；35c0cd6 全库仍有 17 处既有 I001（由小修复分支处理），本分支未新增 |

3 项跳过取决于环境：`test_local_run.py:810` 需设 `AGEMORPH_LOCAL_RUN_LIVE=1`；`test_local_run.py:947`、`test_repro_check.py:315` 在没有项目 venv/Vite 入口时跳过。1 条警告是既有 Starlette 警告。

覆盖：合法解析（含名字里的下划线、数字段、Unicode、NFC）；43 种坏文件名各自的原因码；年龄 19/20/70/71 边界及 0—120 全部合法；性别 m/f 与各种非法写法；跨度 29/30 及两种口径、跨人不混算；最短边 min/max/中位数（奇偶）/分位数/分箱/<128；两个过滤口径重算；K5 清单校验并经 `dataset_manifest.export_manifest` 读回、文件哈希正确、审计 inside/outside；`stats.json` 不含名字/文件名/id；拒绝记录与总数对账；重复 id；非 JPEG/截断/空文件/超大/解压炸弹；EXIF 方向；符号链接文件/目录/整个输入目录；嵌套与过深目录；非 UTF-8 文件名；Windows 非法字符；输入运行中被改；清点哈希；CLI 退出码 0/1/2 和 `python -m` 方式；预算超限、无合法文件、写出中途失败都不留输出；源码无网络/pickle/eval。

## 6. 已知局限 / 待确认

1. 文件名约定（顺序、性别字母、后缀）只依据 v3 §4 和原论文描述，没有对照真实官方包；`verified_on_real_data`、`identity_from_name_verified_on_real_data` 保持 false。LX-2 跑完后请先看 `rejected.json`，再抽查几个文件名。
2. 身份只能按名字字符串认定，同名不同人、同人不同拼写无法从文件名区分。
3. K5 清单按 16,488 条估算约 13.5 MiB，离 16 MiB 上限余量约 15%；名字特别长时可能触发 `K5_MANIFEST_TOO_LARGE`（会整体拒绝，不会半截写出）。
4. 本分支与 FG-1 分支都在 `ARCHITECTURE.md`/`TASKS.md`/`PROGRESS.md` 的同一位置加了条目，以后两个分支都合并时这三处会有文本冲突，需要手工合并（内容互不矛盾）。
5. FG-8 要从本工具的 `stats.json` 再筛出白名单 `summary.json`；本工具不负责白名单。

## 7. 提交与精确文件清单（待用户确认）

| 提交 | 时间（UTC+1） | 作者 | 文件（精确清单） |
|---|---|---|---|
| `55ccc39bcbe94f8fd536d33b2f20f2c3c4c4df0e（原 d67a4b9e2b3093e353263f201c3eb32fa036ea10）` | 作者时间 2026-11-16 06:04:41 | Forge (AI agent) <forge-agent@agemorph3d.invalid> | `preprocessing/agedb_filenames.py`（新增）、`backend/tests/test_agedb_filenames.py`（新增） |
| `037662540c878ab182cb204406353ec7101296d2（原 23a480d263f20211c7bffc49a1f1311bf9ce4ce7）` | 2026-11-16 06:04:41 | 同上 | `docs/AgeDB文件名解析开发记录.md`（新增）、`ARCHITECTURE.md`、`TASKS.md`、`PROGRESS.md`（各 +1 条） |

- 逐个文件 `git add -- <路径>` 暂存，没有用 `git add -A`；提交前 `git check-ignore` 确认这 6 个文件都不在忽略规则内；没有暂存任何被忽略文件（`backend/src/agemorph3d_backend.egg-info/` 是 venv 安装产生的忽略目录，未提交）。
- 提交前做了敏感检查：新增文件里没有密码、令牌、真实人名或 `/workspace/hf` 路径；测试里的人名都是虚构的。
- **RULES.md 第 14 行要求先确认精确文件清单再做 Git 操作：这两个本地提交的文件清单事先没有经用户确认，请用户补确认。**
- **署名待用户决定**：目前保留 AI 来源（`Forge (AI agent)`）。push/PR 前由用户决定保留 AI 作者，还是用户署名并加 Co-authored-by；不建议抹掉 AI 来源。
- 推送需要用户逐次批准（U-9）。

## 补充（2026-11-16 06:1x，Europe/Berlin）：测试夹具人名替换

按 Atlas / Sentinel 要求，`backend/tests/test_agedb_filenames.py` 中可能被读作真实人名的夹具名已换成明显虚构的名字：`Jean_Paul_Example`→`Test_Subject_01`、`MariaFake`→`PersonM`、`O'Brien-Fake`→`Person'O-Test`、`Zoë Fake`→`Personë Test`、`Zoe\u0301`/`Zo\u00e9`→`Persone\u0301`/`Person\u00e9`（Unicode 组合/预组合测试语义不变）。修正以 fixup 并入本地提交（从未推送），原 `9aae64b`/`2986bec` 已重写为 `55ccc39（原 d67a4b9）`/`0376625（原 23a480d）`，新历史中逐提交检查无上述人名。113 项测试通过，ruff check/format 通过。`/tmp/pytest-of-box/` 下旧测试生成的文件按要求未删除，由用户决定。旧提交对象仍在本地 reflog 中，待 Git 垃圾回收或用户决定后清理。

## 补充（2026-11-16 06:22，Europe/Berlin）：Sentinel 复审后的两项跟进

按 Atlas 指派落实 Sentinel FG-2 复审建议（MINOR-2 / MINOR-4）：

1. **CLI 默认拒绝运行**。必须显式传入 `--local-only-ack` 才执行；未传时退出码 2，stderr 说明原因，stdout 输出 `{"status":"rejected","error_code":"LOCAL_ONLY_ACK_REQUIRED",...}`，不创建、不写入任何输出。传入后启动时向 stderr 打印醒目警告「含文件名的输出仅限用户本机」。`--help` 已写明该要求，且不需要该参数即可查看帮助。门禁只在 CLI `main()`，库函数 `export()` / `build()` 仍可供测试和后续 LX-2 调用。
2. **`local_only: true` 加在外层报告**。`rejected.json` 原本已有；`audit.json`（`audit_manifest` 结果之上额外写入顶层字段）现也带 `local_only: true`。**不改 K5 `manifest.json` 字段结构**（`dataset_manifest.validate_manifest` 仍按原合同校验）。`stats.json` 只含汇总、不含文件名，不是「含文件名的外层报告」，因此不加 `local_only`（正式回传仍走 FG-8 白名单）。

| 提交 | 时间（Europe/Berlin） | 作者 | 文件（精确清单） |
|---|---|---|---|
| `3ff80d6d4ab465f08f1c48528754412211ef1cd1（原 377acaee8a42e578ebd0827bd2bddf8a41eedf32）` | 作者时间 2026-11-16 06:22:25 | Forge (AI agent) <forge-agent@agemorph3d.invalid> | `preprocessing/agedb_filenames.py`、`backend/tests/test_agedb_filenames.py`、`docs/AgeDB文件名解析开发记录.md`、`TASKS.md`、`PROGRESS.md`（均修改；TASKS/PROGRESS 各在原 FG-2 条目上补一句，未另插文首新段） |

- 叠在 `0376625（原 23a480d）` 之上的一条新本地提交，没有改写既有历史；`git add -- <路径>` 逐个暂存，未使用 `-A`。
- 提交前读了 `.gitignore`（这 5 个文件均不被忽略）；敏感检查：无密码、令牌、真实人名或 `/workspace/hf` 路径。
- 测试：`tests/test_agedb_filenames.py` **117 通过**（原 113，新增 4 项：无 flag 拒绝且不写文件、有 flag 打印警告、`--help` 列出必填参数、外层报告/K5 结构）；完整后端 **3123 通过 / 3 跳过 / 0 失败**（Python 3.11.16 / Pillow 13.0.0，`QT_QPA_PLATFORM=offscreen`；跳过项与先前相同）。ruff 0.17.1 对上述两个 Python 文件 `check` 与 `format --check` 均通过（在 `backend/` 下按仓库 `line-length = 100` 运行）。
- **未 push、未开 PR、未碰 GitHub**；`remote.origin.pushurl=DISABLED_NO_PUSH`。未删除或改动 `/tmp/pytest-of-box/`，未执行 `git gc` / `reflog expire`。未读取真实 AgeDB 或 `/workspace/hf`。
- 署名与 RULES 第 14 行文件清单仍待用户确认。
