# FG-1 WIDER FACE 标注转换器 · 说明

- 执行：Forge；完成时间 2026-11-16 约 05:35（UTC+1，即 12:35 UTC+8）
- 分支：本地 `feat/wider-converter`（worktree `/workspace/AgeMorph3D_forge`，基于 `35c0cd6`）
- 提交：`c2a1d58`（转换模块 + 测试）、`e324d28`（仓库内开发记录与 ARCHITECTURE/TASKS/PROGRESS 条目）、`688bc09`（按 Sentinel 审核 MINOR 修正，2026-11-16 约 05:50 UTC+1）
- Sentinel 审核：PASS（无 CRITICAL/MAJOR，7 条 MINOR 已处理，见第 8 节）
- worktree 推送地址已设为 `DISABLED_NO_PUSH`（仅本 worktree），保持不动
- **未 push、未开 PR、未动任何远程**；主副本 `/workspace/AgeMorph3D` 工作区未改动；只用合成数据，未下载、未读取任何真实 WIDER 文件。

## 1. 做了什么

新增 `preprocessing/wider_annotations.py`（CLI：`python -m preprocessing.wider_annotations`）：

1. 严格解析 `wider_face_<split>_bbx_gt.txt`：路径行 → 人脸数行 → `max(n,1)` 行十个整数 `x1 y1 w h blur expression illumination invalid occlusion pose`；0 框图片的一行全零按占位处理，不算人脸。
2. 每个框经 P02 `annotation_transform.box`（`xywh_edges` 像素边界契约）得到裁剪后边界，再转成 YOLO `0 cx cy w h`（按图像宽高归一化，6 位小数）。
3. 每张图片写一个标签 `.txt`（0 框图片为空文件），并输出 K5 清单 `manifest.json`（经 `dataset_manifest.validate_manifest` 校验）、`audit.json`（`audit_manifest`）和逐图逐脸的 `report.json`。

中断前留下的未提交草稿经审查后保留主体，做了以下修正：
- 新增“同名不同后缀/仅大小写不同”检查（`GT_DUPLICATE_IMAGE_STEM`），否则 `a.jpg`/`a.png` 会共用一个标签文件和 sample_id，在写出途中整体崩溃；
- 结束时除 GT 外，再重核全部已登记图片的大小和 SHA-256，变化则 `inputs_stable=false`（与 P02 的做法一致）；
- K5 清单写出前检查不超过 K5 读取上限 16 MiB（`K5_MANIFEST_TOO_LARGE`）；
- 按仓库 ruff 配置（行宽 100）重新格式化；补充模块说明。

## 2. 改动文件

| 文件 | 说明 |
|---|---|
| `preprocessing/wider_annotations.py` | 新增，497 行 |
| `backend/tests/test_wider_annotations.py` | 新增，97 项合成测试（首版 86 项 + 审核修正 11 项） |
| `docs/WIDER标注转换开发记录.md` | 新增，仓库内开发记录（沿用 P02 等记录的格式） |
| `ARCHITECTURE.md`、`TASKS.md`、`PROGRESS.md` | 各加一条 FG-1 条目（RULES 要求维护这几份说明） |

`annotation_transform.py`、`dataset_manifest.py`、`split_freeze.py` 均未修改（相对 35c0cd6 diff 为空），是以导入复用的方式接入。

## 3. 与数据集方案 v3 §5.3 对应的设计决定

v3 §5 第 3 条（即“§5.3”）只规定：禁用 `trust_remote_code`，WIDER 下载原始 zip，**自己解析 bbx_gt.txt 转 YOLO**；§2-E 再次写明不用 Bingsu 版。本实现完全自写，没有依赖任何第三方转换脚本或 HF 数据集脚本。§5.3 没有规定标记的取舍，以下为本次的决定（均写进报告的 `policy` 字段，便于审核）：

| 情况 | 处理 | 理由 |
|---|---|---|
| `invalid=1` | 丢弃，原因 `INVALID_FLAG`；优先于 blur 判断 | 官方定义为无效框，官方评测也不计入 |
| blur | 默认 `--max-blur 2` 全部保留；可设 0/1 收紧，超出记 `BLUR_ABOVE_POLICY` | 严重模糊的小脸属于 hard 子集，默认不删；是否收紧留给 T02 配置决定 |
| `w≤0` 或 `h≤0` | 丢弃，`DEGENERATE_BOX` | 无面积 |
| 部分越界 | 裁到画幅后保留，记录 `clipped=true` 和裁剪后坐标 | 沿用 P02 的 clipped 定义 |
| 完全越界（含恰好贴边） | 丢弃，`OUT_OF_FRAME` | 画幅内无面积 |
| 0 框图片 | 空标签文件 | YOLO 的负样本约定 |
| 任何格式错误 | 整个文件拒绝并给出行号，不写任何输出 | 与仓库其他工具“严格拒绝、不猜”的风格一致 |
| EXIF 方向 ≠ 1 | 该图失败 | 标注按存储像素给出，旋转会导致静默错位 |

所有声明的人脸都保留在报告里，带 decision/reason，不会静默消失。

**划分**：K5 记录一律 `use=unassigned`，报告 `split_assignment_performed=false`；不改动 `split_freeze.py` 或任何划分逻辑，有测试断言这一点。

## 4. 如何运行

```bash
# 在仓库根目录
python -m preprocessing.wider_annotations \
  --gt data/wider_face_split/wider_face_train_bbx_gt.txt --gt-sha256 <SHA-256> \
  --images-dir data/WIDER_train/images --split train \
  --output-dir output/research/wider-train-v1 [--max-blur 0|1|2]
cd backend && python -m pytest tests/test_wider_annotations.py -q
```

退出码：0 = 全部成功；1 = 有图片级失败或输入有变化（仍写报告）；2 = 整体被拒且不留输出（建目录后才发现的拒绝会先删除本次新建的输出目录及本次新建的空父目录，已有内容不动）。输出目录必须是新的 `output/research/...`。

## 5. 测试结果

环境：box Linux，Python 3.11.16 + Pillow 13.0.0（`uv sync --frozen --extra inference`，venv 位于 `/workspace/.venvs/agemorph-forge-31116`，在仓库外）。

| 状态 | 结果 |
|---|---|
| 基线 35c0cd6（草稿暂时移出） | 3006 passed, 3 skipped, 1 条既有警告 |
| 首版（e324d28） | 3092 passed, 3 skipped, 1 条既有警告（+86） |
| 审核修正后（688bc09） | **3103 passed**, 3 skipped, 1 条既有警告（+97，全部为新增用例） |
| 新增测试单独 | 97 passed |
| ruff 0.17.1 check / format | **只针对新增的两个文件**通过；35c0cd6 全库仍有 17 处既有 I001（另由小修复分支处理） |

3 项跳过取决于环境，并非固定：`test_local_run.py:810` 需设 `AGEMORPH_LOCAL_RUN_LIVE=1`；`test_local_run.py:947`、`test_repro_check.py:315` 在没有项目 venv/Vite 入口时跳过。

附注：最初用 Python 3.11.18 跑基线时有 171 项失败，全部来自 `tools/near_duplicate_probe.py` 写死的环境版本（3.11.16/13.0.0），与本任务无关；改用 3.11.16 后基线全绿。

测试覆盖：0 框图片及占位行；invalid、blur 三档阈值、invalid 优先；部分越界裁剪（左/右/上/下/整幅）；完全越界与贴边；零/负宽高；27 种格式错误（截断、计数非法、列数、非整数、属性越界、重复路径/同名不同后缀、非法路径、空文件等）及错误行号；P02 契约一致性；YOLO 文本格式与解析；图片缺失/损坏/EXIF 旋转的逐图失败；运行中输入被改；参数拒绝且不写输出；拒绝覆盖；K5 清单校验与 `unassigned`；CLI 三种退出码和 `python -m` 运行；建目录后拒绝（sample_id 冲突、K5 清单过大、报告过大、意外异常）不留输出目录且不动已有目录；GIF/BMP/TIFF/WEBP 内容即使后缀为 .jpg 也不被探测。

## 6. 往返误差（像素 → YOLO 文本 → 像素）

- 测试内：2 万个随机框、7 种尺寸（1×1 至 8192×2048），断言 ≤ 0.5 px 且 ≤ 0.75e-6×8192 ≈ 6.1e-3 px。
- 另行扫描 20 万个随机框：**实测最大 0.006144 px**（出现在 8192 宽图上）。
- WIDER 典型尺寸（1024×1024 内部框，10 万个）：最大 0.000768 px。
- 模块内另有守卫：超过 0.5 px 时该图直接失败。

## 7. 已知局限 / 待定

1. 右边界取 `x1+w`，与 P02 `xywh_edges` 一致。官方 readme 未规定端点；wondervictor/WiderFace-Evaluation 先算 x+w，再在面积和 IoU 里 +1。保持 `box_convention_verified_on_real_data=false`。
2. WIDER 官方 AP 应使用官方 eval 工具和 `wider_face_val.mat`（含 easy/medium/hard 和忽略框），不能拿本工具生成的 val YOLO 标签代替。
3. K5 清单规模（训练集估算约 11.5 MB）超过 `archive_preparation` 等 32 条小样工具的预算，正式批量接入要等数据入口评审后再适配。
4. `--max-blur` 的取值留给 T02/E01 决定；默认不删模糊框。

### RN-3（拿到真实数据后）的后续核对
1. 统计“格式错误整文件拒绝”在官方 train/val 文件上的命中数（命中则记录行号和原因再决定，不自动放宽）。
2. 统计 EXIF 方向 ≠ 1 导致的逐图失败数。
3. 对小脸目视抽查叠加，确认 `x1+w` 约定后才能把 `box_convention_verified_on_real_data` 改为 true。

## 8. Sentinel 审核 MINOR 处理（688bc09）

1. 退出码 2 不留输出：`SAMPLE_ID_COLLISION` 改在建目录前检查；之后的 `K5_MANIFEST_TOO_LARGE`、`REPORT_TOO_LARGE` 及任何意外异常，先删除本次新建的输出目录和本次新建的空父目录再抛出，已有目录不动。新增测试逐一断言（含 `output/research` 已存在/不存在两种情况）。
2. `_image_info` 的 `Image.open` 加 `formats=["JPEG","PNG"]`；新增测试：GIF/BMP/TIFF/WEBP 内容（后缀为 .jpg）被拒，记 `IMAGE_UNREADABLE`。
3. 跳过项与 Ruff 范围说明见第 5 节。
4/5. RN-3 后续核对与右边界依据见第 7 节。
6. 署名与文件清单见第 9 节。
7. 推送地址：已为 `DISABLED_NO_PUSH`。

## 9. 提交署名与文件清单（请用户确认）

三个提交暂以 `Forge (AI agent) <forge-agent@agemorph3d.invalid>` 署名，均未推送。推送或开 PR 前由用户决定署名；Sentinel 建议保留 AI 来源（保留 AI 作者，或用户署名并加 `Co-authored-by`），避免 `tools/code_stats.py` 把它计为个人贡献（与 L03 冲突）。

**如实说明**：仓库 RULES.md 第 14 行要求精确文件清单确认后才做 Git 操作。这三个本地提交的文件清单**事先没有经用户确认**（只有 Atlas 转达的“完成本地提交”指令）。精确清单如下，请用户补确认；如不同意，可在推送前调整：

- `c2a1d58`：A `preprocessing/wider_annotations.py`；A `backend/tests/test_wider_annotations.py`
- `e324d28`：A `docs/WIDER标注转换开发记录.md`；M `ARCHITECTURE.md`；M `TASKS.md`；M `PROGRESS.md`
- `688bc09`：M `preprocessing/wider_annotations.py`；M `backend/tests/test_wider_annotations.py`；M `docs/WIDER标注转换开发记录.md`；M `ARCHITECTURE.md`；M `TASKS.md`；M `PROGRESS.md`
