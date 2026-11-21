# FG-8 说明：LX-1 到 LX-3 本机脚本包（第一阶段）

> 本文时间均为 UTC+8。

## 0. 基本信息

- **执行**：Forge（AI agent）。
  - 初版：2026-11-16 13:35（UTC+8）。
  - 按 Sentinel 复审返工：2026-11-21 15:37（UTC+8）。
  - 按 Sentinel SN-6（审到 `91d27d4`，0 CRITICAL / 1 MAJOR / 10 MINOR）第二轮返工：2026-11-21 15:54（UTC+8）；同步修了 FG-4 的同一 ZIP 问题（15:57，见第 7 节）。
- **仓库**：`/workspace/AgeMorph3D_fg8`（git worktree），本地分支 `feat/lx-local-scripts`，基于 `feat/agedb-parser` @ `377acaee8a42e578ebd0827bd2bddf8a41eedf32`。
- **推送状态**：push 地址仍为 `DISABLED_NO_PUSH`（worktree 级配置）。
  - **未 push、未开 PR、未 fetch/rebase，GitHub 上什么都没动。**
  - 未改主副本 `/workspace/AgeMorph3D`，也没有从主副本运行或导入任何东西。
  - 未执行 `git gc` / `reflog expire`。
- **数据边界**：没有读取、下载或打开任何 AgeDB 官方包、HF 转存或 `/workspace/hf`；没有用 `trust_remote_code`。测试只在临时目录里生成合成文件名（虚构名字，如 PersonA、Test_Subject_01、GammaPerson、Zéta）和小图。
- **环境**：venv `/workspace/.venvs/agemorph-fg8-31116`（Python 3.11.16、Pillow 13.0.0、ruff 0.17.1）。
  - 测试一律带 `-B` 和 `PYTHONDONTWRITEBYTECODE=1`，`QT_QPA_PLATFORM=offscreen`。
  - 返工期间 pytest 都用 `--basetemp=/tmp/fg8-pytest/...`，不往 `/tmp/pytest-of-box/` 写，也不触发 pytest 对那里的自动轮换（见第 6 节）。

## 1. 做了什么（范围不变）

只做规划 v2 第 102 行 LX 任务组里的 **LX-1 到 LX-3**。LX-4 到 LX-6 依赖 FG-6/FG-7，未做。

- **LX-1**：校验和解压官方包。不接收、不保存密码。
- **LX-2**：调用 FG-2 的 `export()`。
- **LX-3**：给出按身份划分的临时建议账本，并统计精确哈希重复。

**范围说明（2026-11-21）**：用户已把数据门槛放宽到 AgeDB 等纵向数据。FG-8 的设计不变：仍然**只在用户本机运行、对外只交回 summary**，本次没有为此改代码。

对外只有 `output/research/<目录>/summary.json`，其余报告都在 `local/` 下，标 `local_only`。用法见仓库里的 `docs/LX本机脚本包开发记录.md`。

## 2. Sentinel 复审意见 → 修复对照

| 编号 | 意见 | 修复（提交 `8312999` 代码 / `91d27d4` 文档） | 对应测试 |
|---|---|---|---|
| MAJOR-1 | 续跑不复核输入，会复用过期或半成品产物 | 见表下说明 | `test_resume_recomputes_lx2_when_an_input_image_changes`、`test_resume_discards_edited_lx2_outputs`、`test_lx3_alone_refuses_when_inputs_changed_since_lx2`、`test_failed_lx3_leaves_no_stale_ledger_and_stashes_old_summary`、`test_reused_folder_is_verified_against_zip_central_directory` |
| MAJOR-2 | BadZipFile 未捕获，泄漏文件名和 traceback，退出码 1 | 见表下说明 | `test_cli_corrupt_archive_exits_2_with_fixed_code_and_no_leak`（3 种损坏输入，子进程实跑）、`test_cli_bad_crc_member_is_caught_without_traceback_or_names`、`test_cli_argument_errors_do_not_echo_values` |
| MAJOR-3 | LX-3 偏离规划（没有近重复检查、没有 P01 质检）且未披露 | **按用户决定不替用户选方法**，summary 用一组写死取值的字段如实标注“未做/待定”（字段表见表下说明） | `test_summary_discloses_pending_user_decisions_and_unchecked_near_duplicates`、`test_rejected_summary_still_carries_the_disclosures`、`test_committed_sample_summary_is_clean_and_whitelisted` |
| MINOR-1 | 白名单只管键、不管值 | 每个键都有取值规则（见表下说明） | `test_summary_value_whitelist_rejects_name_like_values`（14 种坏值） |
| MINOR-2 | 旧 summary 处理 | 每次运行开始时把旧 summary 移到 `local/summary.stale.json`；任何失败都写入 `status=rejected` 的 summary（同样带披露字段） | `test_failed_lx3_…`、`test_rejected_summary_…` |
| MINOR-3 | `--images-dir` 范围 | 只允许 `data/datasets/<agedb…>` 这一层；拒绝 `data`、`data/datasets`、更深子目录、`..`、绝对路径、反斜杠 | `test_images_dir_scope_is_restricted`（8 种） |
| MINOR-4 | 解压结果要对照 zip 中央目录核对 | 逐个核对文件名、大小和 CRC32，支持 zip 带顶层文件夹；已解压目录先核对、通过后才设只读 | `test_reused_folder_is_verified_against_zip_central_directory`、`test_reused_folder_matches_zip_with_a_top_level_folder` |
| MINOR-5 | lx2/k5 状态 | `lx2_status` 为 needs_review 时整体 status 记 needs_review、退出码 1；summary 新增 `k5_audit_finding_codes`（只有代码，例如 `NEAR_DUPLICATE_REVIEW_PENDING`、`TRAINING_OVERLAP_UNRESOLVED`，不含样本编号） | `test_lx2_needs_review_propagates_to_summary_status_and_exit_code` |
| MINOR-6 | 小格计数披露 | 新增 `small_cell_suppression_status=pending_user_decision`；`--suppress-small-cells` 以 `SMALL_CELL_SUPPRESSION_POLICY_UNSETTLED` 拒绝；`--help` 和文档写明风险 | `test_small_cell_suppression_is_refused_until_the_user_decides` |
| MINOR-7 | ps1 问题 | 见表下说明。**没有 pwsh，ps1 未在 Windows 实机运行，只做了静态测试** | `test_powershell_entry_keeps_exit_codes_and_caller_state` |
| MINOR-8 | 措辞和 UTC+8 | 开发记录和本说明统一用 UTC+8；“等价”改为“部分等价”；划分称“临时建议”；明确精确重复为 0 不证明无泄漏 | 文档 |
| MINOR-9 | 测试覆盖 | `test_lx_local.py` 从 18 项增至 47 项，覆盖上面每一项；子进程测试改为 `python -B` + `PYTHONDONTWRITEBYTECODE=1` | — |
| 附加 | “与 FG-4 等价”表述过度 | 补齐缺口，并改称**部分等价**（覆盖和未覆盖项见表下说明） | `test_safe_extract_rejects_symlink_and_device_members`、`…_nfc_and_casefold_duplicate_names`、`…_high_compression_ratio`、`…_prepended_data_and_overlapping_entries`、`test_cli_corrupt_archive_…[plain text]` |

**MAJOR-1 修复：**
- **LX-2**：同时满足以下三条才复用，否则删除本输出 `local/` 下的旧产物重跑，并作废 LX-3 状态：
  1. 重新计算的输入清单哈希与记录一致（清单含每个文件的 SHA-256、大小和路径）；
  2. 四个产物（stats/rejected/manifest/audit）的 SHA-256 都与 `state.json` 记录一致；
  3. 记录的产物目录与本次一致。
- **LX-3**：
  - 开跑前先复核 LX-2 产物哈希，manifest 哈希不符时报 `LX2_OUTPUT_CHANGED`。
  - 本次没跑 LX-2 时，还要重新计算输入清单；输入变了报 `LX2_STALE_RERUN_REQUIRED`。
  - 先作废 `lx3` 状态，删除旧账本和 P03/P04 半成品（`p03-screen`、`p04-freeze` 等），然后重算。
- **LX-1**：复用已解压目录前，先按 zip 中央目录核对（见 MINOR-4）。
- **新字段**：`lx2_resumed`。

**MAJOR-2 修复：**
- 所有读 zip 的入口统一走 `_checked_infos`：`zipfile` 的异常和 EOF/zlib 错误一律转成固定代码，例如 `ARCHIVE_NOT_ZIP`、`ZIP_END_INVALID`、`ZIP_LAYOUT_UNSUPPORTED`、`ARCHIVE_CORRUPT_OR_NOT_ZIP`。
- 返工中还发现并修复了一处真实泄漏：CLI 失败路径的 `_record_error` 拿到的 root 是字符串，触发 AttributeError，打印完整 traceback（含路径）且退出码 1。修复为：`main` 先把 root 转成 Path；`_record_error` 兜底捕获全部异常。
- 参数错误改用自定义 parser，不回显参数值。
- 现在失败时退出码为 2，stdout 只打印 `{"status":"rejected","error_code":…}`。

**MAJOR-3 固定披露字段：**
- `near_duplicate_checked_at_full_scale=false`
- `near_duplicate_method_status=pending_user_decision`
- `split_rule_status=provisional_pending_user_decision`
- `split_ratio_has_source=false`（70/15/15 无出处）
- `split_age_stratified=false`
- `small_cell_suppression_status=pending_user_decision`
- `pending_user_decisions=[NEAR_DUPLICATE_METHOD, SPLIT_RULE, SMALL_CELL_SUPPRESSION]`
- 另外保留 `p01_quality_checks_performed=false` 和 `exact_duplicate_zero_does_not_prove_no_leakage=true`。
- 这些字段的值或类型一旦被改，summary 校验就以 `SUMMARY_DISCLOSURE_ALTERED` 拒绝；拒绝时写出的 summary 也带这些字段。
- 文档第 3 节有同一张表。

**MINOR-1 取值规则：**
- `lx2_status` 只能是 passed / needs_review。
- `k5_audit_status` 只能是 metadata_consistent / completed_with_findings。
- `screening_status` 只能是 passed / failed，`split_freeze_status` 只能是 consistent / blocked。
- 整数必须非负，且不能是 bool。
- 计数字典的键必须符合 TOKEN/年龄段/性别格式。
- 审计代码必须是大写代码格式，去重并排序。

**MINOR-7 ps1 修复：**
- 原来的 `Write-Error` 在 `$ErrorActionPreference='Stop'` 下会变成终止错误，退出码不再是 2；改为写 stderr 后 `exit 2`。
- 用 `#Requires -Version 5.1` 声明版本要求。
- 用 `Push-Location`/`Pop-Location` 运行，结束后恢复调用者的目录和 `PYTHONDONTWRITEBYTECODE`。
- 选 Python 的顺序：`backend\.venv`，然后 `py -3.11`，最后 PATH 上的 `python`（拒绝 WindowsApps 占位程序）。
- 原样传回退出码（0/1/2）。

**“部分等价”说明：**
- 新补的检查：
  - EOCD/多卷/ZIP64 布局，中央目录上限；
  - 条目重叠，本地头与中央目录一致性；
  - 前置数据（只接受 `PK\x03\x04`/`PK\x05\x06` 开头）；
  - 成员实际长度必须等于声明长度。
- 原有的检查：符号链接/设备成员、压缩比、NFC+casefold 同名、非 zip 输入。
- 这些规则是对照 FG-4 `archive_preparation._zip_guard/_zip_layout` 重新实现的，没有共用代码。
- 未覆盖：tar/tar.gz（这里不支持）和 FG-4 的 `safe_loading` 模块（未合并）。

**其他顺带修复：**
- 原来 ≤32 条走 P03/P04 时，身份分组的 `origin` 写成 `synthetic`，真实数据上这是不实声明。现改为 `official`：分组来自官方文件名里的姓名字段，按 FG-2 规则确定。（**第二轮已收紧**：只有同次运行归档核对一致时才写 `official`，否则 `unknown`，见第 7 节 MINOR-10。）
- 修了 ruff E501 两处、B905 一处。

## 3. 提交与精确文件清单（待用户确认）

| 提交 | 时间（UTC+8） | 作者 / 提交者 | 文件（精确清单） |
|---|---|---|---|
| `515dcb084f492ebd41c212c8e1578345dbc5e7af`（初版，未改写） | 2026-11-16 13:35:47 | Forge (AI agent) <forge-agent@agemorph3d.invalid> | 新增 `preprocessing/lx_local.py`、`backend/tests/test_lx_local.py`、`tools/lx-local.ps1`、`docs/LX本机脚本包开发记录.md`、`docs/lx-summary-sample.json`；修改 `TASKS.md`、`PROGRESS.md` |
| `83129998027cea1ff2a5a628e481dc0321b6fe07` | 2026-11-21 15:37:37 | MingYao Song <2441377859@qq.com>（作者 = 提交者），尾注 `Co-authored-by: Forge (AI agent) <forge-agent@agemorph3d.invalid>` | 修改 `preprocessing/lx_local.py`、`backend/tests/test_lx_local.py`、`tools/lx-local.ps1`、`docs/lx-summary-sample.json`（由合成夹具重新生成） |
| `91d27d4ff95758003054c77d9f6f813c8aeb41f9` | 2026-11-21 15:37:37 | 同上（含同一 Co-authored-by 尾注） | 修改 `docs/LX本机脚本包开发记录.md`、`TASKS.md`、`PROGRESS.md` |
| `864452865a3e865a9aec6b0f6e45fcda255c9827`（第二轮代码） | 2026-11-21 15:54:06 | 同上 | 修改 `preprocessing/lx_local.py`、`backend/tests/test_lx_local.py`、`tools/lx-local.ps1`、`docs/lx-summary-sample.json`（由合成夹具重新生成） |
| `f3fbe7a972bd4fa085116319ca12dae220368118`（第二轮文档） | 2026-11-21 15:54:06 | 同上 | 修改 `docs/LX本机脚本包开发记录.md`、`TASKS.md`、`PROGRESS.md` |

- **提交方式**：第一轮两条新提交叠在 `515dcb0` 之上，第二轮两条叠在 `91d27d4` 之上，都没有改写历史。逐个文件 `git add -- <路径>`，没有用 `-A`/`.`。
- **提交前检查**：
  - 读了 `.gitignore` 和 `RULES.md`；`git check-ignore` 确认这 7 个文件都不被忽略（两轮各查一次）。
  - 做了敏感检查：没有密码、令牌、真实人名，也没有 `/workspace/hf` 路径。样例 summary 通过白名单和泄漏测试。
- **署名**：署名口径由用户本人确认（经 Atlas 转达，2026-11-21）：作者和提交者都是 MingYao Song <2441377859@qq.com>，加 `Co-authored-by: Forge (AI agent)`，不抹去 AI 署名。
- **515dcb0 的作者**：仍是 Forge (AI agent)。按指示本执行者**没有改写任何旧提交的署名**；旧本地提交的署名改写（带备份 ref）由上级另行处理。
- **待用户确认**：**RULES.md 第 14 行要求的本批精确文件清单**。推送需要用户逐次批准（U-9）。
- **合并提示**：`PROGRESS.md` 文首和 FG-1/FG-2 一样各加了一行，以后合并时要手工保留各段。

## 4. 测试与检查

命令在 `backend/` 下运行：`PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python -B -m pytest -q -rfEsxX -p no:cacheprovider --basetemp=/tmp/fg8-pytest/full`

| 项 | 结果 |
|---|---|
| `tests/test_lx_local.py` | **63 通过**（初版 18 → 第一轮 47 → 第二轮 63） |
| 完整后端 | **3186 通过 / 3 跳过 / 0 失败**（第一轮 3170；+16 即第二轮新增测试；初版 3141） |
| Sentinel 对抗测试（只读其 clone，复制到临时目录运行后删除） | 25 通过、1 失败：`test_tamper_disclosures` 用的探测值现在被白名单拒绝，即期望行为 |
| `ruff check` / `ruff format --check`（`--config backend/pyproject.toml`） | `lx_local.py`、`test_lx_local.py` 均通过；I001 在这两个文件为 0，没有新增（全仓库 I001 仍是 base 自带的 37 处，不属于本批） |

`--basetemp` 的父目录（`/tmp/fg8-pytest`）须先 `mkdir -p`，pytest 不建多级父目录。第二轮提交前后代码一致（提交后 `ruff format --check` 通过、无改动）。

3 项跳过与先前相同：`test_local_run.py:810`、`test_local_run.py:947`、`test_repro_check.py:315`。另有 1 条已有的 Starlette 警告。

## 5. 仍待用户决定（经 Atlas）

1. **官方规模的近重复方法**：脚本未做、未选。summary 写明 `near_duplicate_method_status=pending_user_decision`。
2. **划分规则**：70/15/15 没有出处，也没有按年龄分层，目前只是临时哈希规则。summary 写明 `split_rule_status=provisional_pending_user_decision`。
3. **小格计数抑制**：未做，规则待定，`--suppress-small-cells` 会被拒绝。
4. **在 Windows 本机实跑 `tools/lx-local.ps1`**：这里没有 PowerShell，未实测。
5. **本批精确文件清单确认**（RULES.md:14），以及 push/PR 是否进行、何时进行（逐次批准）。
6. **旧提交署名改写**：用户已确认署名口径；改写 515dcb0 等旧本地提交由上级另行操作，本执行者未动。
7. **依赖分支**：FG-4 和 fix/env-and-imports 仍未合并。本底 P03 仍钉死 Python 3.11.16，用户本机若是 3.11.18，调用 P03 时会被记入 `p03_p04_block_reason`。
8. **group_id 是否加盐**：`group_id` 是姓名字段的无盐 SHA-256 前 16 位十六进制，**不是匿名化**，拿公开的 568 个姓名逐个算哈希就能反查。本次没有改方案，是否加盐（以及盐放哪里）由用户决定。
9. **严格 ZIP 布局的代价**：带空隙或前置数据的合法 ZIP 会被拒（fail-closed）；如官方包恰好是这种格式需用户决定是否放宽。
10. **ps1 退出码**：Python 自身崩溃（退出码 1）与 needs_review（1）在启动器层面无法区分，已写明。

## 6. 本机状况记录（只报告，未删除）

**主副本 `__pycache__` 来源（2026-11-16 13:26–13:28 UTC+8）：**
- **涉及的文件**：主副本 `/workspace/AgeMorph3D` 下有 29 个 `cpython-311` 的 `.pyc`，分布在四个目录：
  - `preprocessing/__pycache__`：13:26:11–13:26:15；
  - `tools/__pycache__`：13:26:15；
  - `training/__pycache__`：13:27:20；
  - `backend/src/agemorph3d/__pycache__`：13:27:49–13:28:25。
- **与 FG-8 的时间线**（UTC+8）：
  - fg8 worktree 创建于 13:25:14（reflog：branch created from 377acae）；
  - fg8 venv 创建于 13:34:11（pyvenv.cfg）；
  - 初版提交 515dcb0 在 13:35:47。
- **pyc 内容**：只有主副本已有的模块，例如 archive_preparation、resource_acquisition、duplicate_screening、split_freeze、dataset_manifest、near_duplicate_probe、training/preflight、backend app。**没有** `agedb_filenames` 或 `lx_local`，这两个模块主副本里根本没有。主副本 `backend/tests/` 下也没有 `__pycache__`。
- **排除项**：
  - 同一时间窗内机器上的其他写入只有 MT-4 任务（`/tmp/MT-4`，Python 3.13 venv），而这批是 3.11 字节码，不是它。
  - 各 venv 的 editable `.pth` 都指向各自的 worktree，没有指向主副本的。
  - 测试里的路径都按测试文件位置解析，在 worktree 里跑测试不会写到主副本。
- **处理结果（2026-11-21）**：这 29 个 `.pyc` 已由 Atlas 删除（本执行者没有动主副本）。本次只读核对：主副本 venv 以外已无 `.pyc`；第二轮所有运行均带 `-B`，fg8/fg4 worktree 在本次返工期间没有新 `.pyc`。
- **判断**：这批 pyc 很可能是 FG-8 前一位执行者（同一执行者刚做完 FG-2 补强）在 13:26–13:28 做的：fg8 venv 还没建好，就用某个 3.11 解释器、以主副本为工作目录或 `sys.path`，导入 P01–P04 等现有模块查看 API。所导入的模块正好是 LX-3 要调用的那几个。**这是根据时间和模块集合的推断，没有日志直接证明；前一位执行者的会话记录这里读不到。** 返工期间所有运行都带 `-B` 和 `PYTHONDONTWRITEBYTECODE=1`，没有在主副本或 worktree 产生新的 `.pyc`（已用 `find -newermt` 核实）。（当时未删除，后由 Atlas 删除，见上。）
- **顺带**：fg8 worktree 自己的 `preprocessing/__pycache__`（13:32:54）和 `backend/tests/__pycache__`（13:31:33）是初版测试写的，可能来自子进程测试没带 `-B`，现已修正。这两个目录被 `.gitignore` 忽略，未删除。

**`/tmp/pytest-of-box/`：**
- 本次开始时只剩 `pytest-96/97/98`，全部建于 2026-11-21 15:28 左右（UTC+8），是其他代理在并发跑 pytest。2026-11-16 那批目录在本次之前就已经被 pytest 默认的“只保留最近 3 个”轮换掉了，不是本次删除的。
- 本次第一次跑 `test_lx_local.py` 时没加 `--basetemp`，按默认规则可能轮换掉了当时最旧的一个目录（大概率是其他代理当天刚建的 `pytest-95`），无法确认。
- 之后所有运行都改用 `--basetemp=/tmp/fg8-pytest/...`，完整套件前后 `/tmp/pytest-of-box/` 内容没有变化。
- **第二轮**：完整套件期间 `/tmp/pytest-of-box/` 新出现 `pytest-99`。不是本执行者所为（本次一律 `--basetemp=/tmp/fg8-pytest/...` 或 `/tmp/fg4-pytest/...`），来源是 Runner 的 `/workspace/AgeMorph3D_runner/output/fe1/run-backend-pytest.sh`。该目录下文件一律未删，由用户决定。
- **建议**：所有代理跑 pytest 时都带 `--basetemp`，否则 pytest 会自动轮换掉 `/tmp/pytest-of-box` 下的旧目录。

**主副本 HEAD 有变动（与本任务无关）：** 主副本 HEAD 在 2026-11-21 15:26:12（UTC+8）fast-forward 到 `10f1918`（reflog：`merge origin/main`），不是本次所为，可能是 Runner 或其他代理所为。本分支仍基于 377acae，按 Atlas 指示没有 rebase。

## 7. 第二轮：Sentinel SN-6 意见 → 修复对照

审到 `91d27d4`，结论 FAIL（0 CRITICAL / 1 MAJOR / 10 MINOR）。修复是叠在 `91d27d4` 上的两条新提交 `8644528`（代码）和 `f3fbe7a`（文档），以及 FG-4 的独立提交 `42e634b`；没有改写历史。

| 意见 | 修复 | 测试 |
|---|---|---|
| MAJOR-1 偶数张图时中位数是小数，被白名单拒收 | 保留 FG-2 的真实中位数；白名单接受有限、非负、非 bool 的整数或 x.5（偶数张取中间两数平均）；拒 NaN/inf/bool/负数；0 张可读时统一为 7 个键（median `null`，分位数 `null`，直方图 `{}`）。口径写进开发记录 | `test_even_image_count_runs_end_to_end_with_true_median`（CLI 端到端 72.5）、`test_even_image_count_with_whole_median_and_odd_count`、`test_zero_readable_images_give_consistent_short_side_keys`、`test_median_and_histogram_values_are_checked` |
| MINOR-1 续跑时旧账本/P03/P04 半成品/state 里的 lx3 残留 | 新 `invalidate_lx3`：LX-3 开始时、以及 LX-2 需要重算时（含只跑 LX-2），先删账本与 P03/P04 产物、从 state 去掉 lx3，再做校验；校验失败也不留旧账本。开发记录原 :76 已改 | `test_failed_lx3_verification_still_clears_ledger_and_state`、`test_lx2_only_rerun_with_changed_inputs_clears_old_ledger` |
| MINOR-2 try 之前的失败不写拒收 summary | 分两段：A 段只校验根目录和输出目录、不写任何东西；B 段（在 try 内）之后任何失败都写拒收 summary。state.json 损坏报 `STATE_CORRUPT` 且原样保留。输出目录无效（越界、不在 `output/research/` 下）时**任何地方都不写**；顺带修了 main 的错误处理会在无效目录里新建 state.json 的问题。文档写明哪些情况写、哪些不写 | `test_corrupt_state_json_writes_rejected_summary_and_keeps_state`、`test_out_of_scope_images_dir_writes_rejected_summary`、`test_invalid_output_dir_writes_nothing_anywhere`（3 组参数） |
| MINOR-3 拼接 ZIP 只读出后一个包 | 严格连续布局：首个本地头在 0、条目无空隙、中央目录紧接最后条目并紧接结束记录、唯一结束记录、无前置/尾随数据。FG-4 同一问题单独提交 `42e634b` 修复，FG-4 文档与 `FG-4_说明.md` §10 已更新 | `test_concatenated_zip_is_rejected_not_partially_read`、`test_zip_layout_gaps_and_trailing_data_are_rejected`；FG-4 新增 5 项（4 项在旧代码上失败） |
| MINOR-4 ps1 | 取第一个 Application 类型的 python；跳过 WindowsApps 占位；先探测 `py -3.11`，缺失时报固定码并退出 2；启动失败、非 0/1/2 退出码一律 2；恢复 `PYTHONDONTWRITEBYTECODE`。**仍未在 Windows 实跑** | `test_powershell_launcher_failures_map_to_exit_2`（静态） |
| MINOR-5 署名表述 | 改为“署名口径由用户本人确认（经 Atlas 转达，2026-11-21）” | — |
| MINOR-6 仓库文档里有本机路径 | 已删，改为“本批精确文件清单另行提交给用户确认（RULES.md 第 14 行）”；`/workspace/hf` 改为“本机 HF 目录” | — |
| MINOR-7 LX-2 复用条件文档与代码不一致 | 开发记录改为与代码 `_lx2_reusable` 逐条一致：state 里 LX-2 为 passed；输入清单哈希一致；记录的产物目录就是本输出的 `local/agedb-stats` 且四个产物都有哈希；四个文件都存在、不是链接、SHA-256 一致。任一不满足就先作废 LX-3 再重跑 LX-2 | — |
| MINOR-8 强制披露字段不全 | `FORCED_DISCLOSURES` 增加 `p01_quality_checks_performed=false`、`exact_duplicate_zero_does_not_prove_no_leakage=true`（并把小格抑制、冻结、划分是否执行等固定值一并纳入） | `test_every_forced_disclosure_detects_tampering` |
| MINOR-9 直方图可为负 | 直方图计数与分位数须为非负整数 | `test_median_and_histogram_values_are_checked` |
| MINOR-10 origin 与 group_id | 只有 `dataset_id == agedb-official` 且同次运行 `extracted_archive_consistent == true` 才记 `official`，否则 `unknown`；写入账本、basis 和 summary（新键 `identity_group_origin`）。文档写明 `group_id` 是无盐 SHA-256 前 16 位，**不是匿名化**，可按公开的 568 个姓名反查；方案未改，是否加盐待用户决定 | `test_identity_group_origin_requires_verified_official_archive` |
| `--basetemp` 父目录 | 开发记录和本文写明父目录须先存在 | — |

- **测试数**：`test_lx_local.py` 47 → 63；完整后端 3186 通过 / 3 跳过；ruff check/format 对改动文件通过。FG-4：184 项 / 完整 3199 通过 / 3 跳过。
- **数据**：全部合成，虚构名字（DeltaPerson、EpsilonPerson 等）；未读 `/workspace/hf`，未下载任何真实数据。
- **未做**：未 push、未开 PR、未 fetch/rebase、未改写旧提交署名；push 地址仍为 `DISABLED_NO_PUSH`。**第二轮两条提交和 FG-4 `42e634b` 的精确文件清单待用户确认（RULES.md 第 14 行）。**
