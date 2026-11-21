# FG-4 说明：数据安全加载规则代码化

- 执行：Forge（AI agent），2026-11-16 初版与复审返工；2026-11-21 完成 Sentinel PASS 后的 5 条 MINOR（N1–N5）。本文时间一律为 UTC+8（项目文档约定）
- 状态：初版经 Sentinel 复审 FAIL（CRITICAL 0 / MAJOR 2 / MINOR 5），已按第 8 节返工；Sentinel 对 `3c3b34c`+`23cfd7b` 复审 PASS，另有 5 条 MINOR（N1–N5）已按第 9 节在 `23cfd7b` 之上新增一个提交修复，无需再复审；没有改写既有提交
- 仓库：`/workspace/AgeMorph3D_fg4`（git worktree，基于 `35c0cd6`），本地分支 `feat/safe-loading`
- push 地址已用 `git config --worktree` 设为 `DISABLED_NO_PUSH`（只影响本 worktree；主副本仍推向 GitHub，未改）。**未 push、未开 PR、未碰 GitHub。**
- 边界：没有读取 `/workspace/hf` 或任何真实数据/权重，没有下载；没有使用 `trust_remote_code`；测试只用临时目录里构造的压缩包和虚构文件名。主副本和 forge/fixes/fg2 三个 worktree 都没动。

## 1. 做了什么

**归档（接入 `preprocessing/archive_preparation.py`，对应 v3 §5 第 4 条）**

原实现已经有：不用 `extractall()`、先完整预检再建输出目录、统一路径规则（`..`、绝对路径、盘符/冒号、反斜杠、控制字符、Windows 保留名）、拒绝链接/设备/FIFO/套接字/PAX/GNU 长名、成员数/大小/总量上限、ZIP 中央目录预算、TAR 解压流计数。本次补充：

1. **TAR `filter="data"`**：新函数 `tar_data_filter`（Python 缺少 `tarfile.data_filter`，即 3.11.4 以前时，显式拒绝为 `TAR_DATA_FILTER_UNAVAILABLE`，绝不跳过），每个 TAR 成员在预检和解压两个阶段都调用标准库 `tarfile.data_filter`（目标目录为本次输出的 `files/`），任何 `FilterError` 都是最终拒绝（`TAR_DATA_FILTER_REJECTED`）。成员仍由工具自己逐个写成只读文件，从不交给 `extract/extractall`。
2. **ZIP 本地头一致**：本地文件头的文件名、压缩方法、加密位必须与中央目录一致（`ZIP_LOCAL_HEADER_MISMATCH`），防止中央目录写安全名、本地头藏 `../`。
3. **ZIP 条目不重叠**：数据区不得互相重叠，也不得伸进中央目录（`ZIP_ENTRY_OVERLAP`），防重叠条目型压缩炸弹。
4. **ZIP 压缩比**：声明大小 >1 MiB 的成员，膨胀倍数不得超过 200（`ZIP_COMPRESSION_RATIO_LIMIT`）。
5. **重名**：按 NFC 规范化 + casefold 判重，组合/分解两种 Unicode 写法视为同名。
6. **失败成员不留半截文件（待用户确认）**：解压阶段某成员失败（如 CRC 错误）时删除它的 `stage/*.part`，失败记录照常写进报告。这一行为变化是否接受，尚待用户确认。

1—5 都在创建输出目录前完成，被拒时工作区逐字节不变。

**torch.load（新增 `preprocessing/safe_loading.py`，对应 v3 §5 第 1、5 条）**

`torch_load_weights_only(root, pin, map_location="cpu")`：先校验 pin（相对路径、字节数、SHA-256）、后缀（`.pt/.pth/.ckpt`）、拒绝符号链接、4 GiB 上限；一次性读入内存再核对哈希，之后从内存字节加载（核对后换文件也不会被加载）；延迟导入 torch；始终 `weights_only=True`；torch 缺失、没有 `weights_only` 参数、加载报错都直接拒绝，**不会改成 `False` 重试**。

**静态检查（启发式，不是安全证明）**：`audit_source/audit_tree` 用 AST 扫描仓库 Python 源码（跳过 `.venv*`、`node_modules`、`output`、`data` 等目录；唯一豁免 `backend/tests/test_safe_loading.py`，因为它以字符串形式存放检测器自己的正反例）。每个模块先解析 `import x as y`、`from x import y as z` 别名，再检查：`torch.load` / `torch.serialization.load`（含 `from torch.serialization import load`）缺少字面量 `weights_only=True` 或带 `**kwargs`；`torch.jit.load`/`torch.hub.load`；`pickle/_pickle/cPickle/dill/joblib` 的 `load/loads/Unpickler` 及继承 `pickle.Unpickler`；`numpy.load` 的 `allow_pickle` 非字面量 `False`（关键字或第三位置参数，如 `np.load(x, None, True)`）或带 `**kwargs`；`trust_remote_code` 非字面量 `False`；`getattr(<敏感模块>, 名称)`；敏感模块的星号导入；字典字面量里的不安全参数（覆盖 `**{'allow_pickle': True}`）；`shutil.unpack_archive`、`.extract(`、`.extractall(` 没有 `filter="data"`；非文档字符串的 str/bytes 字面量含 `weights_only=False`/`trust_remote_code=True`/`allow_pickle=True`。全仓库结果按（文件、拒绝码、规范化代码片段）与已知清单逐条比对。这套新规则在仓库里没有发现额外存量，已知清单仍为 6 条。看不到：经变量传递的函数对象、`importlib`/`__import__` 动态导入、`exec/eval`、非 Python 文件、第三方库内部加载、由变量或拼接拼出的字符串补丁（如 `'weights_only=' + 'False'`）、`getattr(torch, 'serialization').load`（`getattr` 规则不把 `'serialization'` 当作敏感名，随后的 `.load` 也无法还原为 `torch.serialization.load`）、以及 JSON 风格写在字符串里的 `"weights_only": False`（字面量规则只匹配 `weights_only=False` 这种赋值写法）。以下加载器本次未纳入检查范围：`marshal`、`yaml.load` / `yaml.unsafe_load`、`pandas.read_pickle`、`shelve`、`cloudpickle`。

## 2. 文件

| 文件 | 改动 |
|---|---|
| `preprocessing/archive_preparation.py` | 修改，+66/−6 行（返工再 +4/−1） |
| `preprocessing/safe_loading.py` | 新增，137 行（返工重写静态检查部分） |
| `backend/tests/test_archive_preparation.py` | 追加 96 项负例/正例（83 → 176 → 返工后 179） |
| `backend/tests/test_safe_loading.py` | 新增，37 项 → 返工后 78 项 → MINOR 后 92 项 |
| `docs/数据安全加载规则开发记录.md` | 新增，仓库内开发记录 |
| `docs/归档解压与逐图核验开发记录.md` | 顶部加一行，说明失败成员 `.part` 清理的行为变化（MINOR 改为待用户确认） |
| `ARCHITECTURE.md`、`TASKS.md`、`PROGRESS.md` | 各加一条 FG-4 记录；MINOR 提交再改计数与待确认表述 |

## 3. 设计决定

| 问题 | 决定 | 理由 |
|---|---|---|
| tar 用 `filter="data"` 的方式 | 不改成 `extractall(filter="data")`，而是对每个成员调用同一个 `tarfile.data_filter`，再叠加原有更严格的规则 | 原工具是有界流式写只读文件 + 逐文件哈希；换成 `extractall` 会丢掉这些保证。两套规则叠加，任何一套拒绝都算拒绝 |
| 新增的 ZIP 检查放在哪 | 预检阶段（建目录前） | 要求“恶意包全部被拒且无部分输出”；改动前，重叠条目/本地头不一致/伸进中央目录这三类要到解压阶段才暴露，已经建好输出目录 |
| 压缩比阈值 | 200 倍、1 MiB 起算，用模块常量，不加进计划 `limits` 字段 | 图片接近 1:1；加字段会让已有计划 JSON 失效 |
| 失败成员的 `.part` | 当前实现会删除（**待用户确认**） | 符合“无部分输出”；失败码和报告仍保留。**这改变了 D06 原记录“处理开始后的失败保留 stage”**，已在原记录顶部注明；是否接受尚待用户确认，不作为已定结论 |
| 损坏但非恶意的成员（CRC 错） | 保持原行为：逐条记录失败，其他成员继续 | 原有回归测试明确要求这一点；它不会往目标外写文件 |
| SAM 存量（4 处，见下） | **本次不改，是否修改待用户决定**；静态检查里逐条列为已知存量；按（文件、拒绝码、规范化片段）比对，新增或改动任一条都会让测试失败 | 这些存量**没有被验证为安全**。SAM checkpoint 的 `opts` 可能含 `argparse.Namespace`，改成 `True` 可能加载失败；本环境没有 torch/权重无法验证；`tools/sam_worker.py` 被多个探针按源码哈希引用 |
| torch 导入 | 函数内延迟导入，可注入桩模块 | torch 不在锁定依赖里，与 `tools/sam_worker.py` 的做法一致 |

SAM 存量的准确情况（初版写“两处在加载前已核对 SHA-256”是错的，已更正）：

1. `tools/sam_probe.py:96`、`:98`：按路径 `torch.load(..., weights_only=False)`，`TypeError` 时退回不带参数的调用。**加载前没有任何校验**；SHA-256 只在加载和推理后（`:179`）写进报告。
2. `tools/sam_worker.py:119`：`verify_assets` 先按路径算 SHA-256，`SamEngine` 再按路径重新打开并 `torch.load(..., weights_only=False)`，校验与反序列化读的不是同一份字节，存在 **TOCTOU** 窗口。
3. 第 4 处（初版漏报）：`tools/sam_native_ops/install.py:34-39` 的字节串补丁在 `:156` 把第三方 SAM `models/psp.py` 改写为 `weights_only=False`（`:136-137` 的清单说明也写了这一点）。`pSp(...)` 在 `tools/sam_worker.py:134`、`tools/sam_probe.py:116` 构造时会**第二次**按路径加载同一 checkpoint。现在由字符串/字节字面量规则检测，报告 2 条。
4. 另外按新规则如实列出 `backend/src/agemorph3d/prepare_tddfa.py:46` 的 `_NumpyAssetUnpickler(pickle.Unpickler)`：`find_class` 只放行 NumPy 少数类、禁止持久引用、只在 SHA-256 匹配后运行；该哈希来自调用方 CLI 的 `--bfm-sha256` / `--tri-sha256` / `--stats-sha256`（`prepare_tddfa.py:278`），不是仓库内固化的钉死值：核对的是完整性（这次读取是否与调用方给出的摘要一致），不是出处（摘要本身是否可信、文件来自哪里）。不属 SAM。

即：SAM 是 2 个文件 3 处直接调用 + `psp.py` 补丁 = 4 处；已知清单共 6 条（sam_probe 2、sam_worker 1、install.py 2、prepare_tddfa 1）。另外 `tools/age_evaluator_probe.py` 用 `importlib` 导入本地固定的 MiVOLO 源码（`use_safetensors=True`、`local_files_only=True`），静态检查看不到这类动态导入，这里一并告知。

## 4. 测试

环境：box Linux，Python 3.11.16 + Pillow 13.0.0 + ruff 0.17.1，venv 在仓库外 `/workspace/.venvs/agemorph-fg4-31116`（`uv sync --project backend --frozen --offline --extra inference --python 3.11.16`，只用本机缓存）。torch 未安装。命令在 `backend/` 下：`python -B -m pytest -q -rfEsxX -p no:cacheprovider`。

| 项 | 结果 |
|---|---|
| 35c0cd6 完整后端（改动前） | 3006 通过 / 3 跳过 / 0 失败 |
| feat/safe-loading 完整后端（初版提交后） | 3136 通过 / 3 跳过 / 0 失败（新增 130 项） |
| feat/safe-loading 完整后端（返工提交后，`23cfd7b`） | 3180 通过 / 3 跳过 / 0 失败（相对 35c0cd6 新增 174 项） |
| feat/safe-loading 完整后端（MINOR 提交后） | **3194 通过** / 3 跳过 / 0 失败（相对 35c0cd6 新增 188 项；相对 `23cfd7b` 再增 14 项） |
| `test_archive_preparation.py` | 179 通过（原 83 项全部仍通过） |
| `test_safe_loading.py` | 92 通过（返工后 78，MINOR 后再增加 14 项） |
| 初版新测试在旧 `archive_preparation.py` 上 | 16 项失败，但含义不同：其中 **9 项只是因为旧代码里没有 `tar_data_filter` 函数**（直接调用该函数的测试报 AttributeError，不说明旧代码会放行这些成员）；**7 项反映新行为**（Unicode 重名、重叠条目、本地头不一致、伸进中央目录、压缩比、每个 TAR 成员两阶段经过 data_filter、`.part` 清理）。TAR 链接/设备/绝对路径等在旧代码里已被仓库自身规则拒绝，`data_filter` 对它们是**纵深防御** |
| ruff 0.17.1 check / format | **只针对改动 Python 文件**通过（初版与返工针对 4 个文件；MINOR 针对 `preprocessing/safe_loading.py`、`backend/tests/test_safe_loading.py`）；35c0cd6 全库仍有 17 处既有 I001（如 `preprocessing/duplicate_screening.py`），本分支未新增 |

3 项跳过取决于环境：`test_local_run.py:810` 需设 `AGEMORPH_LOCAL_RUN_LIVE=1`；`test_local_run.py:947`、`test_repro_check.py:315` 在没有项目 venv/Vite 入口时跳过。

负例覆盖（全部断言：抛出预期拒绝码、工作区快照逐字节不变、输出目录不存在、目标外和上一级目录没有出现逃逸文件）：ZIP 19 种路径穿越写法（`..`、绝对、UNC、`C:`、`C:x`、反斜杠、`a\..\..`、`./`、`//`、`:stream`、`CON`/`aux`、末尾空格/点、控制字符）；ZIP 符号链接/字符设备/块设备/FIFO/套接字 × 3 种目标；目录带数据；加密位；重叠条目；本地头改名；条目伸进中央目录；4 MiB 全零压缩炸弹；声明大小炸弹；成员数炸弹；ZIP/TAR 重名（同名、大小写、Unicode 组合/分解）；TAR/TAR.GZ 10 种路径穿越；TAR 符号链接/硬链接（相对、绝对、指向包内）、字符/块设备、FIFO、连续文件；GNU 长名藏 `../`；PAX `path` 覆盖；gzip 炸弹（成员声明超限，及藏在 tar 尾部零填充里的流式炸弹）。`tar_data_filter` 对 6 类成员抛出与标准库一致的错误类型。正例：带数据描述符的 ZIP、不同的 Unicode 名字、原有全部正例仍通过；每个 TAR 成员都在预检和解压两阶段经过 `data_filter`。torch：始终 `weights_only=True`、失败不重试、旧 torch 拒绝、torch 缺失、8 种 pin/路径/后缀/位置/大小错误都在加载前拒绝、符号链接、换文件不影响、模块导入不加载 torch。静态检查：返工后 57 个规则用例，MINOR 后再增加 14 项（`torch.serialization.load` 与 `np.load` 第三位置 `allow_pickle` 的正反例），共 71 个规则用例 + 文件/行号/片段 + 目录跳过与豁免 + 按片段比对 + 全仓库检查。缺少 `tarfile.data_filter`：单元调用与 TAR/TAR.GZ 端到端都拒绝为 `TAR_DATA_FILTER_UNAVAILABLE` 且工作区不变；ZIP 不受影响。

## 5. 已知局限

1. ZIP64、多磁盘、加密、自解压前缀、PAX/GNU 长名 TAR 仍不支持（原策略），真实发行包超出时需单独评审。
2. 200 倍 / 1 MiB 是经验值，没有用真实数据验证；零填充较多的合法文件可能被拒。
3. ZIP 条目之间的小空隙（数据描述符等）允许，只拒绝重叠。
4. torch 路径只用桩模块验证，没有真实 torch 和 checkpoint。
5. 静态检查是启发式，不能证明仓库没有不安全加载（盲区见第 1 节）。已知清单比对不含行号，同一文件里文本完全相同的片段挪位置不会被区分。
6. `pyproject.toml` 是 `>=3.11,<3.12`，没有排除 3.11.0–3.11.3；本次没有改 pyproject/lock（会动锁文件，留给用户），改为运行时显式拒绝。
7. `feature_join.py` 把 `archive_preparation.py` 列入源码哈希清单，本次改动后旧的 P05 报告无法按原依赖哈希重放（`SCHEMA` 和报告格式未变）。
8. 本分支与 FG-1/FG-2 分支都在 `ARCHITECTURE.md`/`TASKS.md`/`PROGRESS.md` 加了条目，多个分支合并时这几处需要手工合并文本（内容不矛盾）。

## 6. 待用户决定

1. **SAM 的 4 处**（`tools/sam_probe.py:96/98` 加载前无校验；`tools/sam_worker.py:119` 先哈希后按路径重读、有 TOCTOU；`tools/sam_native_ops/install.py:34-39/156` 把 `psp.py` 改成 `weights_only=False`，`pSp` 二次加载）：保持现状，还是在有 torch 和权重的机器上改成“读一次字节→核对 SHA-256→从内存 `weights_only=True` 加载”（必要时用 `torch.serialization.add_safe_globals` 放行 `argparse.Namespace`），同时处理 `pSp` 的二次加载，并重跑 SAM 验证。
2. **失败成员 `.part` 清理**改变了 D06 原记录的“保留 stage”，是否接受。
3. **提交文件清单**：RULES.md 第 14 行要求先确认精确文件清单再做 Git 操作，下面的本地提交事先没有经用户确认，请补确认。
4. **署名**：用户已决定，以后推送的提交作者用 `MingYao Song <2441377859@qq.com>`，并加 `Co-authored-by: Forge (AI agent) <forge-agent@agemorph3d.invalid>`。MINOR 这条新提交已按此署名；`c96d6bc`/`8beaa8d`/`3c3b34c`/`23cfd7b` 仍为 Forge 署名，本次未改写，改写留待后续步骤。推送仍须用户逐次批准（U-9）。
5. **Python 下限**：是否把 `requires-python` 收紧到 `>=3.11.4`（需重新生成锁文件）。

## 7. 提交与精确文件清单（待用户确认）

| 提交 | 时间（UTC+8） | 作者/提交者 | 文件（精确清单） |
|---|---|---|---|
| `c96d6bcb8c86f390f3977f8911e9e5a19122a34a` | 2026-11-16 13:17:35 | Forge (AI agent) <forge-agent@agemorph3d.invalid> | `preprocessing/archive_preparation.py`（修改）、`preprocessing/safe_loading.py`（新增）、`backend/tests/test_archive_preparation.py`（修改）、`backend/tests/test_safe_loading.py`（新增） |
| `8beaa8d5ed38cf2ff3f54cc044bf3596b18d0363` | 2026-11-16 13:17:35 | 同上 | `docs/数据安全加载规则开发记录.md`（新增）、`docs/归档解压与逐图核验开发记录.md`、`ARCHITECTURE.md`、`TASKS.md`、`PROGRESS.md`（修改） |
| `3c3b34c2a8bd79329327c6be6c3a2d5e6fd674b5`（返工） | 2026-11-16 13:39:48 | 同上 | `preprocessing/safe_loading.py`、`preprocessing/archive_preparation.py`、`backend/tests/test_safe_loading.py`、`backend/tests/test_archive_preparation.py`（均为修改）；提交后完整后端 3180 通过 / 3 跳过 |
| `23cfd7b19e727708ba045c223f1bf5df74ca5563`（返工） | 2026-11-16 13:39:48 | 同上 | `docs/数据安全加载规则开发记录.md`、`docs/归档解压与逐图核验开发记录.md`、`ARCHITECTURE.md`、`TASKS.md`、`PROGRESS.md`（均为修改）；仅文档，测试数同上 |
| `4b5e5c5946695246a0fddb9ccdee7ef3757fa8a1`（MINOR） | 2026-11-21 15:31:49 | MingYao Song <2441377859@qq.com>；Co-authored-by: Forge (AI agent) <forge-agent@agemorph3d.invalid> | `preprocessing/safe_loading.py`、`backend/tests/test_safe_loading.py`、`docs/数据安全加载规则开发记录.md`、`docs/归档解压与逐图核验开发记录.md`、`ARCHITECTURE.md`、`TASKS.md`、`PROGRESS.md`（均为修改）；提交后完整后端 3194 通过 / 3 跳过 |
| `42e634b0ea23563e77c6eb4eeecf81bad88f0777`（ZIP 布局补强） | 2026-11-21 15:57:15 | 同上（作者 = 提交者，含同一 Co-authored-by 尾注） | `preprocessing/archive_preparation.py`、`backend/tests/test_archive_preparation.py`、`docs/数据安全加载规则开发记录.md`、`TASKS.md`、`PROGRESS.md`（均为修改）；提交前完整后端 3199 通过 / 3 跳过 |

- 五个提交都逐个 `git add -- <路径>`，没有用 `-A`；`git check-ignore` 确认所有提交文件都不在忽略规则内；没有暂存被忽略文件（`backend/src/agemorph3d_backend.egg-info/` 是 venv 安装产生的忽略目录，未提交）。MINOR 这条没有改写既有提交。
- 敏感检查：新增内容里没有密码、令牌、真实人名或 `/workspace/hf` 路径；测试中的 `/etc/passwd` 只是链接目标字符串，从不读取；静态检查用例只是源码字符串，从不执行。
- 本地临时文件已清理（worktree 内的 `.ruff_cache`、`__pycache__`）；pytest 的 `tmp_path` 位于 `/tmp/pytest-of-box`，按要求未动。日志在 `/workspace/AgeMorph3D_tasks/.fg4_logs/`（返工后：`rework_final.log`）。

## 8. Sentinel 复审意见与对应修正

| 意见 | 修正 | 位置 |
|---|---|---|
| MAJOR-1 SAM 描述不准确、漏报第 4 处 | `sam_probe` 改为“加载前无校验，SHA 只在加载后写报告”；写明 `sam_worker` 的 TOCTOU；补上 `install.py` 改写 `psp.py` 与 `pSp` 二次加载；字符串/字节字面量规则把补丁检测为已知存量；删除“新增任何违规测试都会失败” | `3c3b34c`（检测、已知清单）；`23cfd7b`（开发记录 §3、ARCHITECTURE、TASKS、PROGRESS）；本文 §3、§6 |
| MAJOR-2 静态检查可被绕过、表述绝对 | 按模块解析导入别名；`getattr`、`**kwargs`、字典字面量、`unpack_archive`、`.extract(`、pickle 系、`torch.jit/hub.load`、星号导入、字符串补丁；为 Sentinel 列出的每种绕过各加用例；重新建立已知清单（新增 install.py 2 条、prepare_tddfa 1 条，没有隐藏）；开发记录 §3/§4 写明是启发式、列出盲区 | `3c3b34c`、`23cfd7b` |
| MINOR-1 TASKS 写“SAM两处” | 改为 2 文件 3 处调用 + `psp.py` 补丁 = 4 处 | `23cfd7b` |
| MINOR-2 缺 `data_filter` 时行为不明 | 显式 `TAR_DATA_FILTER_UNAVAILABLE`；monkeypatch 删除属性后单元/端到端测试；没改 pyproject/lock，见 §5、§6 | `3c3b34c`、`23cfd7b` |
| MINOR-3 “16 项失败”表述 | 拆成 9 项（函数不存在）+ 7 项（新行为），其余属纵深防御 | 本文 §4 |
| MINOR-4 时间应为 UTC+8 | 本文统一为 UTC+8；本次改动的仓库文档只写日期（2026-11-16，在 UTC+8 下不变），没有写具体时刻 | 本文 |
| MINOR-5 已知存量只比数量 | 改为按（文件、拒绝码、规范化片段）逐条比对，并加测试证明“同文件换一种违规写法”会失败；残余盲区（同文本挪位置）已写明 | `3c3b34c`；开发记录 §3 |

## 9. Sentinel 复审 PASS 后的 MINOR（N1–N5）

Sentinel 对 `3c3b34c`+`23cfd7b` 复审 PASS，并列出 5 条可直接修的 MINOR，无需再复审。修复是在 `23cfd7b` 之上新增一个提交，没有改写既有提交。精确文件清单与提交哈希见第 7 节。

| 意见 | 修正 |
|---|---|
| N1 盲区列表不完整 | 静态检查补上 `torch.serialization.load`（含 `from torch.serialization import load` 等别名）与 `np.load` 第三位置 `allow_pickle`，并加 14 项正反例。新规则扫描全仓库后**没有发现额外存量**，未把任何新结果悄悄写入 6 条已知清单。仍看不到的写法，以及本次未纳入范围的加载器（`marshal`、`yaml.load`/`yaml.unsafe_load`、`pandas.read_pickle`、`shelve`、`cloudpickle`），已同时写进开发记录 §3 与本文 §1 |
| N2 “不改 SAM 代码（用户决定）” | 改为“本次不改，是否修改待用户决定”（本文 §3） |
| N3 `prepare_tddfa` SHA 来源 | 写明哈希来自调用方 CLI `--*-sha256`（`prepare_tddfa.py:278`），核对的是完整性、不是出处（开发记录 §3、本文 §3） |
| N4 本文格式 | §3 表中的“torch 导入”行收回表内，SAM 说明放在表后；§5、§6 改为连续编号 |
| N5 失败成员 `.part` 写成已定 | 开发记录 §1、归档原记录顶部、本文 §1/§3/§6 均改为待用户确认 |

## 10. ZIP 严格连续布局（2026-11-21，随 FG-8 Sentinel SN-6 第二轮 MINOR-3 同步）

Sentinel 在复审 FG-8 时指出 FG-8 的 ZIP 检查（照 FG-4 重写）放过首尾拼接的 ZIP，并指出 FG-4 `archive_preparation.py:116` 有同一问题。原因：`_zip_guard` 只要求“中央目录起点 + 长度 ≤ 结束记录位置”，`_zip_layout` 只查条目重叠；CPython `zipfile` 发现偏移差时会把所有偏移平移（内部 `concat`），于是拼接包只读出后一个、前一个包被静默放过，前置或尾随数据同理。

修复在 `4b5e5c5` 之上新增提交 `42e634b`，没有改写历史：

| 检查 | 拒绝码 |
|---|---|
| 文件开头必须是第一个本地头（空包只能是结束记录本身） | `ZIP_PREFIX_UNSUPPORTED` |
| 末 64 KB 内只允许 1 个结束记录，注释必须正好到文件尾（无尾随数据）；不支持多卷/ZIP64 | `ZIP_END_AMBIGUOUS`、`ZIP_END_INVALID`、`ZIP_LAYOUT_UNSUPPORTED` |
| 中央目录紧接结束记录 | `ZIP_DIRECTORY_NOT_ADJACENT` |
| `zipfile` 给出的 `start_dir`、条目数与结束记录一致（排除平移） | `ZIP_DIRECTORY_INVALID` |
| 条目从 0 开始首尾相接，最后条目紧接中央目录（数据描述符按 12/16 字节计） | `ZIP_ENTRY_GAP`、`ZIP_ENTRY_OVERLAP` |
| 目录预算（条目数、1 MiB）仍在 `ZipFile` 分配前检查，且先于相邻性检查 | `ZIP_DIRECTORY_LIMIT` |

- **测试**：`test_archive_preparation.py` 179 → 184（拼接包、自洽前置、中央目录前空隙、尾随数据与注释里藏结束记录、正常 stored/deflated 包仍通过）。把实现换回 `4b5e5c5` 版本跑这 5 项：前 4 项失败、最后 1 项通过，证明测试能抓到原问题。
- **完整后端**：`--basetemp=/tmp/fg4-pytest/full`（父目录 `/tmp/fg4-pytest` 须先 `mkdir -p`，pytest 不会建多级父目录），venv `agemorph-fg4-31116`：**3199 通过 / 3 跳过 / 0 失败**（76.2 s，1 条既有 Starlette 警告）。之后 `ruff format` 只改了一处换行（纯格式），再跑 `test_archive_preparation.py`+`test_safe_loading.py` 276 通过。
- **ruff**：两个改动文件 check/format 通过（`--config backend/pyproject.toml`）。
- **代价（已写进开发记录）**：极少数合法但带空隙或前置数据的 ZIP（自解压包、`zip -A` 修过偏移的包）也会被拒，属有意的保守做法。
- **署名**：作者 = 提交者 = MingYao Song <2441377859@qq.com>，尾注 Co-authored-by: Forge (AI agent)。署名口径由用户本人确认（经 Atlas 转达，2026-11-21）。
- push 地址仍为 `DISABLED_NO_PUSH`；未 push、未 fetch/rebase。**本提交的精确文件清单待用户确认（RULES.md 第 14 行）。**
- `feature_join.py` 的源码哈希清单包含 `archive_preparation.py`，本次改动后旧 P05 报告同样无法按原依赖哈希重放（与 §1 已述相同）。
