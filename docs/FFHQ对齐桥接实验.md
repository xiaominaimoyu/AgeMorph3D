# 3DDFA 到 FFHQ / SAM 的对齐桥接实验

记录日期：2026-10-20。本批完成离线的“原照片 → 检测与 3DDFA → 原图 68 点 → FFHQ 风格 256 裁剪 → 既有 SAM 独立环境”桥接，未修改生产接口、依赖或模型清单。10 个预期成功样例各生成 20/45/70 三张二维图，共 30 张；另 2 个预期检测失败样例仍返回 `NO_FACE`。**这不构成年龄校准、身份保持、年龄纹理或 G3 验收。**

源码为 [ffhq_alignment.py](../backend/src/agemorph3d/ffhq_alignment.py) 和 [ffhq_bridge_probe.py](../tools/ffhq_bridge_probe.py)。SAM 权重、源码与环境继续使用 [既有配置](SAM独立环境配置.md)，不安装 CUDA Toolkit、SciPy 或 dlib，不混入 `backend/.venv`。

## 实现与坐标约定

3DDFA 的 120 像素回归输入与 FFHQ 裁剪的范围、方向不同；本批从原照片重新采样，不放大回归输入。`project_vertices(raw, model.keypoint_coordinates)` 保留当前原生稀疏索引与投影约定，得到 EXIF 转正后原图的 68 点；它们是模型估计，不是独立标注，也不把 FG-NET `.pts` 当作 iBUG 点序。

几何参考固定版本的 [SAM 官方脚本](https://github.com/yuval-alaluf/SAM/blob/c1895aef275e702fba7560284dc16df60d65210e/scripts/align_all_parallel.py)：取两眼各六点的均值及两个嘴角，计算定向方形 `quad`，顺序为左上、左下、右下、右上。对整数像素中心坐标，输出大小为 `N`：

```text
source(u,v) = q0 + (u+0.5)/N * (q3-q0) + (v+0.5)/N * (q1-q0)
```

`source_to_aligned` 和 `aligned_to_source` 为互逆 3×3 矩阵。quad 四角映到输出边界 `−0.5..N−0.5`，而非四个角像素中心；这与上游 Pillow `QUAD(quad + 0.5)` 的几何一致。[Pillow 坐标文档](https://pillow.readthedocs.io/en/stable/handbook/concepts.html#coordinate-system)区分像素边界与中心。

本实现采用 NumPy 连续双线性取样、nearest-even 整数量化和无额外大数组的反射补边；**没有复刻上游 shrink 滤波及高斯/中位数补边融合，不能声称像素完全一致。** 这些差异写入每份报告 metadata。输入受 16MP、输出边长 32—1024 及眼口几何/裁剪预算限制；CLI 固定输出 256×256。

`valid-mask.png` 只有在采样中心满足 `0≤x≤W−1, 0≤y≤H−1`、具备原图完整双线性支持时才为白。反射补边提供 SAM 上下文，不成为可观测纹理；该 mask 也没有识别手、眼镜、头发等外部遮挡。返回数组为独立只读数据。

## 单图复现

在项目根目录执行，两个输出目录均须不存在。第一步使用 CPU 后端环境；第二步使用已配置的 SAM 环境。

```powershell
.\backend\.venv\Scripts\python.exe tools/ffhq_bridge_probe.py `
  --image data/samples/astronaut.png `
  --detector-manifest data/models/yolov5n05-face/manifest.json `
  --reconstructor-manifest data/models/3ddfa-v2/manifest.json `
  --output-dir output/research/ffhq-repro `
  --research-allow-unresolved

.\data\envs\sam\Scripts\python.exe tools/sam_probe.py `
  --sam-root data/third_party/SAM `
  --checkpoint data/models/sam/sam_ffhq_aging.pt `
  --image output/research/ffhq-repro/aligned.png `
  --target-ages 20,45,70 `
  --output-dir output/research/ffhq-repro-sam
```

第一步输出 `aligned.png`、`valid-mask.png`、`coordinates.json`、`source-landmarks.png`、`source-roi.png`、`aligned-landmarks.png`、`report.json`。绿色 ROI 只作说明，没有导出或复写私有 120 像素预处理。报告绑定原图、模型清单及逐资产哈希，记录 CPU 自检、有效区比例、像素中心约定和坐标往返误差。

研究开关只存在于此离线 CLI。默认不带开关时，当前未收口许可的模型清单被严格拒绝；不会改为 `verified` 或改变服务 readiness。既有目录在加载模型前拒绝，输出采用独占创建，失败保留外来文件，模型在 `finally` 释放。无脸、多脸、解码和加载失败有稳定错误码。

## 本机真实实验

| 检查 | 实际证据 | 限制 |
|---|---|---|
| 输入 | SAM 官方 `866.jpg`、公开 astronaut、8 个不同成年 FG-NET 身份；另有 2 个原报告 `NO_FACE` 对照 | 人为选择的可行性样例，不是随机测试集或总体成功率 |
| 成功链路 | 10 次 CPU 检测/重建/FFHQ 对齐，10 次独立 SAM 进程、30 张 1024×1024 RGB 输出 | 20/45/70 是 checkpoint 条件输入，不是已验证的真实输出年龄 |
| 特殊输入 | 约 −31.66° 眼线倾斜、约 −35.60° 拟合 yaw proxy、灰度样例均完成 | 角度是模型估计，未标定相机或姿态质量 |
| 原图支持 | 有效区比例 67.8665%—100% | 最低样例约 32.13% 是未观测补边，禁止直接写入 UV |
| 坐标往返 | 原图 68 点最大绝对误差 `2.2737367544323206e-13` 像素 | 仅证明数值映射互逆，不证明关键点定位精度 |
| 阴性对照 | `013A21.JPG`、`067A23.JPG` 仍返回 `NO_FACE`，跳过 SAM | 未降低检测阈值制造成功 |
| 隔离与失败 | 默认严格许可拒绝；重跑到既有目录拒绝且原文件哈希不变 | 年龄能力与许可状态不变 |
| SAM 运行 | torch `2.11.0+cu128`，GPU capability `(12,0)`；前向约 106.5—432.7ms，最大显存分配约 2709.6MiB | 逐进程 batch=1，范围含首次前向，不含加载；不是端到端性能验收 |

FG-NET 成功样例为 `012A27`、`082A27`、`004A63`、`006A55`、`062A45`、`005A35`、`057A25`、`003A38`；年龄取自镜像文件名，未用出生记录复核。没有以这些样例训练、拟合年龄方向或划分训练/测试集，也没有同人真实跨龄配对评价。

本机证据保存在被忽略的目录，不随源码或报告公开分发照片及派生图：

- [总报告](../output/research/ffhq-bridge-20261020/report.json)：逐样例输入/输出哈希、mask 比例、运行统计及失败。
- [本地对照图](../output/research/ffhq-bridge-20261020/contact-sheet.jpg)：原图 ROI、FFHQ、SAM20/45/70；已人工查看方向和裁剪。可见生成会改变部分面部形状、头发及背景，不能由可观看替代身份评价。
- [选样记录](../output/research/ffhq-bridge-review-20261020/samples.json)：选择原因、输入哈希和已有失败对照。
- [独立坐标参考](../output/research/ffhq-bridge-review-20261020/coordinate-review.json)：从固定上游脚本抽取算法并注入相同 68 点，无需导入 dlib/SciPy；无 padding/shrink 的参考与直接原图 QUAD 像素一致。
- [独立算法审查](../output/research/ffhq-bridge-review-20261020/alignment-code-review.json)：12 种旋转/边界/小图合成情况，对照显式反射 padding + Pillow QUAD，RGB 最大差 1、mask 完全一致；不包含完整上游滤波等价主张。
- [全量测试日志](../output/research/ffhq-bridge-20261020/pytest-final.json)与[最终源码/资产核对](../output/research/ffhq-bridge-20261020/verification-summary.json)。

SAM 权重 SHA-256 为 `6fbd6085e2e6001f51f6dee896ae5ba7bd6c3fab5c06fadba75f2a12188ba143`，FG-NET 归档 SHA-256 为 `228acddeba96e469f2ded9475ee87f4ab16398de27a2f3ec35a266a46ef2f7fc`，本批实际重算一致。SAM 固定 commit 与原生算子配置沿用既有登记，未重装环境或覆盖旧研究结果。

## 回归与下一步

新增纯算法 37 项和 CLI 编排 17 项测试；后端全量 **820 项通过**，一项既有 Starlette/httpx 弃用提示。Ruff 检查通过，55 个 Python 文件格式检查通过。前端未改，本批未重跑浏览器或摄像头验收。

下一步先建立按身份分组、保留独立评价的同人真实跨龄检查。AgeDB 仍待密码；SAM 与 FG-NET 仍为 `research-only-unresolved`。应分开评估年龄偏差、身份变化和形状/纹理质量，不把 FG-NET 经验点序映射或样例观察当作独立标准。

SAM 会非刚性改变脸型和轮廓，因此本批的逆矩阵只可回映射**源照片与其对齐裁剪**，不能证明生成图可直接逆投影。UV 前还需对每个目标输出重新检测、对应与重建，处理可见性、外部遮挡、接缝和未知区，再评估是否使用生成像素。`service_ready`、`g3_complete`、`years_calibrated`、`identity_accepted`、`uv_registered` 均保持 `false`；本批未训练或执行 Git 提交/推送。
