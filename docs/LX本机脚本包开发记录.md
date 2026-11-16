# FG-8 第一阶段：LX-1 到 LX-3 本机脚本包

2026-11-16 完成 FG-8 第一阶段（规划 v2 第 102 行，LX 任务组只覆盖 LX-1 到 LX-3）。在用户 Windows 本机对已取得的 AgeDB 官方包做校验、解压、官方文件名统计，并给出按身份划分的建议账本。对外只写一份受字段白名单约束的 `summary.json`（汇总数字和文件 SHA-256），不含文件名、人名、身份编号、逐图记录或特征值。脚本不接收、不保存解压密码。长任务可按阶段断点续跑。测试只用合成文件名和小图；**没有读取或下载任何官方包、HF 转存或 `/workspace/hf`。** LX-4 到 LX-6 依赖尚未合并的 FG-6/FG-7，本阶段不做。

代码：[lx_local.py](../preprocessing/lx_local.py)；Windows 入口：[lx-local.ps1](../tools/lx-local.ps1)；测试：[test_lx_local.py](../backend/tests/test_lx_local.py)；样例：[lx-summary-sample.json](lx-summary-sample.json)。

## 1. 运行（只在用户本机）

CLI **默认拒绝运行**，必须显式传入 `--local-only-ack`。未传时退出码 2，不写任何文件。传入后向 stderr 打印「含文件名的输出仅限用户本机」。

在项目根目录（如 `D:\project file\AgeMorph3D`）PowerShell：

```powershell
& 'tools\lx-local.ps1' --help
& 'tools\lx-local.ps1' --local-only-ack `
  --archive data/datasets/AgeDB.zip `
  --images-dir data/datasets/agedb `
  --terms-snapshot data/datasets/agedb-terms.html `
  --output-dir output/research/lx-agedb-v1
```

或直接：`& 'backend\.venv\Scripts\python.exe' -m preprocessing.lx_local --local-only-ack ...`

- 把官方 AgeDB.zip 自己放到 `--archive` 路径（脚本不下载）。条款快照可选，只做大小和 SHA-256。
- **不要把解压密码传给脚本，也不要写进参数、环境变量或聊天。** 若 zip 带密码且目标文件夹还不存在，脚本退出并提示用资源管理器或 7-Zip 在本机交互解压，然后再次运行（检测到已解压目录会复用并设为只读）。未加密的 zip（例如本仓库合成测试包）会按 zip-slip 防护逐成员解压，不用 `extractall`。
- 同一 `--output-dir` 再次运行会续跑：已完成且输入哈希未变的阶段会复用产物。
- `--stages lx1,lx2,lx3` 可只跑一部分。退出码 0 表示 `summary.json` 状态为 passed；2 为整体拒绝。
- 回传给团队的只应是 `output/research/<目录>/summary.json`。回传前请自己打开看一眼。`local/` 下的报告含文件名，标了 `local_only`，不要外传。

## 2. 各阶段

| 阶段 | 做什么 | 回传到 summary 的内容 |
|---|---|---|
| LX-1 | 记录归档大小、SHA-256、文件修改时间（UTC）和哈希时刻；可选条款快照的大小与 SHA-256；已解压则复用，否则仅在未加密时安全解压；目录设为只读 | 归档/快照的字节数与哈希、解压方式、文件张数、是否只读 |
| LX-2 | 调用 FG-2 的 `agedb_filenames.export()`（库函数，不走需密码的表面） | v3 §2-A / §4.4 的汇总数字，以及 stats/manifest/audit/rejected 的 SHA-256 |
| LX-3 | 按身份给出 train/validation/test 建议（同一人全部正式样本在同一划分）；统计精确 SHA-256 重复和跨划分精确重复；排除 20—70 岁以外和读头失败的样本 | 各划分张数/身份数、排除计数、精确重复计数、建议账本 SHA-256 |

LX-3 的划分比例是**临时规则**：`int(sha256(seed:subject_id)[:8], 16) % 100`，0—69 训练、70—84 验证、85—99 测试，种子默认 `agemorph3d-lx3-identity-split-v1`。正式比例等 E01/BP-6。这是建议账本，`freeze_authorized` 与 `split_assignment_performed` 在 summary 里保持 false；`split_freeze.py` 本身也不会授权真正冻结。

## 3. 与未合并分支、现有工具的关系

- **FG-2**（本分支基于 `feat/agedb-parser` @ `377acae`）：直接调用 `export()` / `build()`。
- **FG-4**（`feat/safe-loading`，未合并）：没有合并该分支。LX-1 自己做等价防护：禁止 `extractall`、成员路径走 `_relative`/`_safe`（防 zip-slip）、拒绝加密成员、失败时删掉本次新建目录。本底的 `archive_preparation.prepare()` 有 32 张图和取得回执限制，不能直接处理官方包。
- **fix/env-and-imports**（未合并）：本底 `duplicate_screening.fingerprint_contract()` 仍钉死 Python 3.11.16。若以后调用 P03，在 3.11.18 上会因环境合同失败；不要合并该修复，只在说明里记录。
- **P01—P04 的 32 条上限**：`archive_preparation.MAX_IMAGES` 与 `split_freeze` / `duplicate_screening` 均为 32，且 P03 需要 P01 的规范化 PNG 和取得回执。官方 AgeDB 有 16,488 张，不能走现有 P01—P04。本阶段默认路径用 FG-2 清单做精确哈希去重和按身份建议划分；若调用方提供合格的 P01 报告和清单且记录数 ≤32，会调用 `duplicate_screening.screen` 与 `split_freeze.precheck`。缺少 P01 报告时 summary 记 `p03_p04_block_reason=PREPARATION_REPORT_REQUIRED`。

## 4. 提交与署名

本地提交以 `Forge (AI agent)` 署名，未推送，push 地址为 `DISABLED_NO_PUSH`。精确文件清单见 `/workspace/AgeMorph3D_tasks/FG-8_说明.md`，请用户补确认；署名在任何 push/PR 前由用户决定。
