# FG-1 WIDER FACE 标注转换（bbx_gt → YOLO）

2026-11-16 完成 FG-1 合成工程子项：自写解析 `wider_face_<split>_bbx_gt.txt`，经 P02 框边界契约转为 YOLO 标签，并写出 K5 清单与审计。新增 86 项合成测试；完整后端 3006 → 3092 项通过（3 项既有跳过、1 条既有 Starlette 警告），Ruff/格式通过。**未取得、未读取任何真实 WIDER 数据；框端点约定、属性取值与真实文件布局仍待拿到官方文件后核对。**

代码：[wider_annotations.py](../preprocessing/wider_annotations.py)；测试：[test_wider_annotations.py](../backend/tests/test_wider_annotations.py)。依据数据集方案 v3 §5 第 3 条：WIDER 只下载原始 zip，自己解析 bbx_gt.txt 转 YOLO，不用 Bingsu 的转换版。

## 1. 运行

```powershell
& 'backend/.venv/Scripts/python.exe' -m preprocessing.wider_annotations --help
& 'backend/.venv/Scripts/python.exe' -m preprocessing.wider_annotations `
  --gt data/wider_face_split/wider_face_train_bbx_gt.txt --gt-sha256 <64位SHA-256> `
  --images-dir data/WIDER_train/images --split train --output-dir output/research/wider-train-v1
cd backend
& '.venv/Scripts/python.exe' -m pytest tests/test_wider_annotations.py -q
```

退出码：0 全部转换且输入稳定；1 有图片级失败或输入变化（报告仍写出）；2 参数/文件整体被拒（不写输出）。输出只能是新的 `output/research/` 目录，拒绝覆盖。

## 2. 解析契约（整文件严格）

每块：图片相对路径行、人脸数行、`max(n,1)` 行十个整数 `x1 y1 w h blur expression illumination invalid occlusion pose`。0 框图片保留的一行全零只作占位，不算人脸；占位行非零即拒绝。允许 UTF-8 BOM、CRLF、行尾空格和文件末尾空行。以下任一情况整文件拒绝并给出行号：截断、计数非整数/负数/超过 4096、列数不为 10、非整数、属性越出官方 readme 取值（blur/occlusion 0—2，其余 0—1）、路径重复或同名不同后缀、绝对路径/`..`/反斜杠/非 jpg/png。GT 文件按调用方给出的 SHA-256 绑定，上限 32 MiB。

## 3. 转换策略

| 情况 | 处理 | 记录 |
|---|---|---|
| `invalid=1` | 丢弃（优先于 blur 判断） | `INVALID_FLAG` |
| `blur > --max-blur` | 丢弃；默认 2 即全部保留，0/1 可收紧 | `BLUR_ABOVE_POLICY` |
| `w≤0` 或 `h≤0` | 丢弃 | `DEGENERATE_BOX` |
| 部分越界 | 按 P02 裁到画幅 `[0,W]×[0,H]` 后保留 | `clipped=true` 及裁剪后边界 |
| 完全在画幅外（含恰好贴边） | 丢弃 | `OUT_OF_FRAME` |
| 0 框图片 | 写空标签文件 | `zero_face_images` 计数 |

框按 P02 `xywh_edges` 解释为像素边界 `[x1, x1+w)`，调用 `annotation_transform.box`，与 P02 同用画幅限制（每边 ≤ 8192，面积 ≤ 16,777,216）。YOLO 行为 `0 cx cy w h`，按图像宽高归一化，保留 6 位小数。写出的文本会重新解析、还原到像素并再归一化；任一坐标误差超过 0.5 px 则该图失败（`ROUNDTRIP_ERROR_EXCEEDED`）。

图片只读头部取尺寸并逐字节哈希，不解码像素；只接受 JPEG/PNG，EXIF 方向不为 1 时该图失败（标注按存储像素给出，旋转会静默错位）。结束时重核 GT 和全部已登记图片的指纹，有变化则 `inputs_stable=false`。

## 4. K5 与划分

每张能读到文件的图片生成一条 K5 记录：`dataset_id=wider-face-<split>`、`kind=original`、`use=unassigned`、年龄 unknown、`exposure.preprocessing=yes`；转换成功为 `not_checked`，失败为 `failed` 并带原因。清单经 `dataset_manifest.validate_manifest` 校验并写 `audit_manifest` 结果（因未定义正式划分，审计含 `FORMAL_SPLITS_NOT_DEFINED`）。**本工具不分配 train/validation/test，不改 `split_freeze.py`**，`split_assignment_performed=false`；WIDER 官方 train/val 的使用方式由 P04 / E01 另定。清单超过 K5 的 16 MiB 读取上限时拒绝写出；按 12,880 条训练集长文件名估算约 11.5 MB。

## 5. 往返误差

合成测试对 7 种尺寸（1×1 至 8192×2048）2 万个随机框断言误差 ≤ 0.5 px 且 ≤ 0.75e-6×8192 ≈ 6.1e-3 px。另行扫描 20 万个随机框，实测最大 0.006144 px（8192 宽）；1024×1024 内部框 10 万个最大 0.000768 px。

## 6. 局限

- `x1+w` 为右边界（而非 `x1+w-1`）是常见约定，尚未在官方文件和图片上目视核对，报告中 `box_convention_verified_on_real_data=false`。
- WIDER 官方 AP 评测应使用官方 eval 工具和 `wider_face_val.mat`（含 easy/medium/hard 与忽略框），不能用本工具的 val YOLO 标签代替。
- K5 清单超过 `archive_preparation` 等 32 条工程小样工具的预算，正式批量接入需等数据入口评审后另行适配。
- 报告逐脸记录全部决策，训练集约 16 万脸时报告体积较大（上限 512 MiB）。
