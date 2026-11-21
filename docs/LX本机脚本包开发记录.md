# FG-8 第一阶段：LX-1 到 LX-3 本机脚本包

本文时间均为 UTC+8。2026-11-16 完成 FG-8 第一阶段初版（规划 v2 第 102 行；LX 任务组本阶段只做 LX-1 到 LX-3）。2026-11-21 按 Sentinel 复审意见返工（3 项 MAJOR、9 项 MINOR，另含“与 FG-4 等价”表述过度一项）。

脚本在用户自己的 Windows 电脑上，对用户已取得的 AgeDB 官方包做三件事：校验和解压、按官方文件名统计、给出按身份划分的**临时建议账本**。

- 对外只写一份 `summary.json`。它受字段白名单和取值白名单双重约束，只含汇总数字、固定代码和文件 SHA-256，不含文件名、人名、身份编号、逐图记录或特征值。
- 脚本不接收、不保存解压密码。
- 测试只用合成文件名（虚构人名）和小图。**没有读取或下载任何官方包、HF 转存或 `/workspace/hf`。**
- LX-4 到 LX-6 依赖尚未合并的 FG-6/FG-7，本阶段不做。

代码：[lx_local.py](../preprocessing/lx_local.py)；Windows 入口：[lx-local.ps1](../tools/lx-local.ps1)；测试：[test_lx_local.py](../backend/tests/test_lx_local.py)；样例：[lx-summary-sample.json](lx-summary-sample.json)（由合成夹具生成）。

## 1. 运行（只在用户本机）

CLI **默认拒绝运行**，必须显式传入 `--local-only-ack`。未传时退出码 2，不写任何文件。传入后会向 stderr 打印「含文件名的输出仅限用户本机」。

在项目根目录（如 `D:\project file\AgeMorph3D`）打开 PowerShell：

```powershell
& 'tools\lx-local.ps1' --help
& 'tools\lx-local.ps1' --local-only-ack `
  --archive data/datasets/AgeDB.zip `
  --images-dir data/datasets/agedb `
  --terms-snapshot data/datasets/agedb-terms.html `
  --output-dir output/research/lx-agedb-v1
```

ps1 选 Python 的顺序：`backend\.venv\Scripts\python.exe`，然后 `py -3.11`，最后 PATH 上的 `python`（拒绝 Microsoft Store 占位程序）。它用 `Push-Location`/`Pop-Location` 运行，结束后恢复调用者的当前目录和 `PYTHONDONTWRITEBYTECODE`，不写字节码，并原样传回退出码。**ps1 只做了静态检查，没有在 Windows 实机运行过。**

- **官方包**：自己把 AgeDB.zip 放到 `--archive` 路径，脚本不下载。条款快照可选，只记录大小和 SHA-256。
- **解压密码**：不要传给脚本，也不要写进参数、环境变量或聊天。
  - zip 带密码且目标文件夹还不存在时，脚本会退出，提示你用资源管理器或 7-Zip 在本机交互解压，然后再运行一次。
  - 已解压的文件夹会先按 zip 中央目录逐个核对文件名、大小和 CRC32，核对通过后才设为只读。中央目录不需要密码就能读。
- **`--images-dir`**：必须是 `data/datasets/` 下以 `agedb` 开头的专用目录（如 `data/datasets/agedb`），不能是 `data`、`data/datasets` 本身或更深的子目录。
- **退出码**：0 表示 passed；1 表示 needs_review（例如 LX-2 有被拒文件）；2 表示拒绝。拒绝时 stdout 只打印 `{"status":"rejected","error_code":<固定代码>}`，不打印文件名、路径或 traceback；参数错误也不会回显参数值。
- **回传**：只回传 `output/research/<目录>/summary.json`，回传前请自己打开看一眼。`local/` 下的报告含文件名，标了 `local_only`，不要外传。

## 2. 各阶段

| 阶段 | 做什么 | 写进 summary 的内容 |
|---|---|---|
| LX-1 | 记录归档的大小、SHA-256、修改时间和哈希时刻；可选条款快照的大小和 SHA-256；已解压就核对后复用，否则只在未加密时安全解压；最后把目录设为只读 | 归档和快照的字节数与哈希、解压方式、文件张数、是否只读、与中央目录是否一致、是否做了 CRC 核对 |
| LX-2 | 调用 FG-2 的 `agedb_filenames.export()`（库函数，不走需要密码的接口） | v3 §2-A / §4.4 的汇总数字；stats、manifest、audit、rejected 的 SHA-256；`lx2_status`；`k5_audit_status`；K5 审计发现代码（只有代码，不含样本编号） |
| LX-3 | 按身份给出 train/validation/test 临时建议，同一人的全部正式样本放在同一划分；统计精确 SHA-256 重复和跨划分精确重复；20—70 岁以外和读头失败的样本记为排除 | 各划分张数和身份数、排除计数、精确重复计数、建议账本 SHA-256、待决事项的固定披露 |

## 3. 未做/待定（待用户决定，脚本不替用户选）

summary.json 里有一组固定披露字段，取值写死在代码里。被改动的 summary 无法通过白名单校验（报 `SUMMARY_DISCLOSURE_ALTERED`）。“精确重复为 0”因此不会被读成“没有重叠”。

| 字段 | 固定值 | 含义 |
|---|---|---|
| `near_duplicate_checked_at_full_scale` | false | 官方规模没有做感知近重复检查 |
| `near_duplicate_method_status` | `pending_user_decision` | 官方规模用什么近重复方法，待用户决定 |
| `p01_quality_checks_performed` | false | 没有做 P01 解码和方向质检 |
| `exact_duplicate_zero_does_not_prove_no_leakage` | true | 精确重复为 0 不证明没有泄漏 |
| `split_rule_status` | `provisional_pending_user_decision` | 划分规则只是临时规则 |
| `split_ratio_has_source` | false | 70/15/15 没有出处 |
| `split_age_stratified` | false | 没有按年龄分层 |
| `small_cell_suppression_applied` / `small_cell_suppression_status` | false / `pending_user_decision` | 没有做小格抑制，规则待定 |
| `pending_user_decisions` | `NEAR_DUPLICATE_METHOD`、`SPLIT_RULE`、`SMALL_CELL_SUPPRESSION` | 三项待决事项 |
| `freeze_authorized` / `split_assignment_performed` | false / false | 只是建议账本，没有冻结 |

- **临时划分规则**：`int(sha256(seed:subject_id)[:8], 16) % 100`。0—69 进训练集，70—84 进验证集，85—99 进测试集。种子默认 `agemorph3d-lx3-identity-split-v1`。
- **小格计数**：568 人的公开名人集上，`age_min`/`age_max`、分位数和很小的格子可能指认到单人。本版本不抑制这些格子。传 `--suppress-small-cells` 会以 `SMALL_CELL_SUPPRESSION_POLICY_UNSETTLED` 拒绝，以免擅自选定规则。

## 4. 断点续跑与输入复核

`local/state.json` 记录各阶段的输入哈希和产物哈希。

- **LX-1**：每次都重新计算归档哈希；复用已解压目录前，先和中央目录核对。
- **LX-2**：同时满足以下三条才复用，否则删除本输出 `local/` 下的旧产物重跑，并作废 LX-3 状态：
  1. 重新计算的输入清单哈希与记录一致（清单含每个文件的 SHA-256、大小和路径）；
  2. 四个产物文件的 SHA-256 都与记录一致；
  3. 上次运行标记为通过。
- **LX-3**：每次都重算。开跑前先复核 LX-2 产物哈希；没跑 LX-2 时还要重新计算输入清单哈希，输入变了就报 `LX2_STALE_RERUN_REQUIRED`，产物被改就报 `LX2_OUTPUT_CHANGED`。旧账本、P03/P04 的半成品会先删掉。
- **旧的 summary.json**：每次运行开始时移到 `local/summary.stale.json`。失败时写入 `status=rejected` 的 summary，不会留下上一次“通过”的结果。
- **字段**：`lx2_resumed` 表示 LX-2 是否复用；`inputs_stable` 表示输入是否与上次一致。

## 5. 与未合并分支、现有工具的关系

- **FG-2**（本分支基于 `feat/agedb-parser` @ `377acae`）：直接调用 `export()` / `build()`。
- **FG-4**（`feat/safe-loading`，未合并）：LX-1 的安全解压与 FG-4 **部分等价**，规则是在这里重新实现的，没有共用代码。
  - 已覆盖：
    - 非 zip 输入、前置数据（自解压壳）、多卷或 ZIP64 布局；
    - 中央目录过大，条目重叠，本地头与中央目录不一致；
    - 加密成员，符号链接或设备成员，不支持的压缩方法；
    - 单成员、总量和压缩比上限；
    - NFC + casefold 后同名，成员实际长度与声明不符；
    - 不使用 `extractall`，用 `_relative`/`_safe` 防 zip-slip；失败时删除本次新建的目录。
  - 未覆盖：tar/tar.gz（这里不支持），以及 FG-4 的 `safe_loading` 模块（未合并）。
  - 本底的 `archive_preparation.prepare()` 有 32 张图上限和取得回执要求，不能处理官方包。
- **fix/env-and-imports**（未合并）：本底的 `duplicate_screening.fingerprint_contract()` 仍钉死 Python 3.11.16。用户本机若是其他补丁版本，调用 P03 会因环境合同失败，原因会记入 `p03_p04_block_reason`。
- **P01—P04 的 32 条上限**：现有工具都按 32 条小样设计，P03 还需要 P01 的规范化 PNG 和取得回执。官方 AgeDB 有 16,488 张，不能走这条链。只有调用方提供合格的 P01 报告和清单、且记录不超过 32 条时，才会调用 `screen` 和 `precheck`。身份分组的 `origin` 记为 `official`（分组来自官方文件名里的姓名字段）。

## 6. 提交与署名

- 全部是本地提交，未推送；push 地址为 `DISABLED_NO_PUSH`。
- 返工提交按用户决定署名：作者用用户本人，并加 `Co-authored-by: Forge (AI agent)`。
- 精确文件清单见 `/workspace/AgeMorph3D_tasks/FG-8_说明.md`，请用户确认（RULES.md 第 14 行）。
- 推送和开 PR 需要用户逐次批准。
