# AgeMorph3D 技术框架分析与模块级行动计划

> 依据：《【任务书】基于YOLO与三维形变模型的跨年龄三维人脸重建及可视化系统》＋《AgeMorph3D_项目计划.md》
> 编制日期：2026-10-17　|　版本核验：全部版本号于 2026-10-17 通过 npm registry / PyPI / GitHub API 实测
> 团队：宋明耀（A，组长，算法线）｜王晋涛（B，组员，系统线）　|　周期：2026-11-16 — 2027-06-10（30 周）

---

## 0. 结论速览

**技术栈一句话**：YOLO26 人脸检测（ONNX）→ 3DDFA_V2/MICA 三维重建（PyTorch→ONNX）→ BFM/FLAME 年龄方向形状老化 ＋ SAM 纹理老化 → FastAPI + WebSocket 仅传参数 → three.js morph target 滑块实时渲染 → glTF 导出。

### 0.1 框架总表（锁定版本，均已核验）

| 层 | 选型 | 锁定版本 | 用途 |
|---|---|---|---|
| 检测框架 | ultralytics（YOLO26） | 8.4.178 | 人脸检测训练/微调/评测/ONNX 导出 |
| 检测权重 | yolo26n-face.pt（akanametov/yolo-face, release 1.0.0） | — | 人脸框检测（WIDER FACE 训练） |
| 检测权重（5点主线） | yolo26n-pose 自训练 | — | 框 ＋ 5 关键点（见 §1.3，任务书要求的补训项） |
| 重建（保底） | 3DDFA_V2 + BFM | 仓库固定 commit | 单图 3DMM 回归、UV 纹理 |
| 重建（主线） | MICA + FLAME | 仓库固定 commit | 全头网格、度量精度 |
| 深度学习 | PyTorch / TorchVision | 2.14.1 / 0.29.1（cu128） | 训练与旧仓库兼容（任务书硬约束 ≥2.7） |
| 推理部署 | ONNX Runtime | onnxruntime-gpu 1.31.0（WSL2）/ onnxruntime 1.31.0（CPU 回退） | 检测与重建统一推理，免每帧 Python 开销 |
| 模型交换 | ONNX | 1.23.2 | 导出（opset 17/18，nms=True 端到端） |
| 纹理老化 | SAM（yuval-alaluf/SAM） | 仓库固定 commit＋官方权重 | 目标年龄照片生成 |
| 后端 | FastAPI + Uvicorn | 0.143.3 / 0.54.0 | HTTP API ＋ WebSocket 服务 |
| WebSocket | websockets | 17.2 | uvicorn WS 后端实现 |
| 数据校验 | Pydantic v2（FastAPI 自带） | ≥2.9 | 消息/接口 schema |
| 文件上传 | python-multipart | 0.0.32 | `/api/reconstruct` 表单上传 |
| 前端渲染 | three.js | 0.186.1 | 模板网格、形状基、morph target、PBR、glTF |
| 前端构建 | Vite（npm） | 8.3.4 | 原生 ESM 开发/构建，不引入前端框架 |
| 网格工具 | trimesh / pygltflib | 5.1.1 / 1.16.5 | 网格处理、glTF/GLB（含 morph target）导出 |
| 数值工具 | NumPy / SciPy / scikit-learn | 2.5.4 / 1.18.1 / 1.9.1 | 参数处理、年龄方向回归 |
| 图像/视觉 | OpenCV / Pillow | 5.0.0.93 / 13.0.0.0 | 裁剪对齐、UV 拼接（遇兼容问题回退 OpenCV 4.x） |
| 评价 | insightface（ArcFace）、MiVOLO、FG-NET | insightface 2.1.x | 身份相似度、年龄估计、定性对比 |
| 测试 | pytest / Playwright | 9.1.1 / 1.64.0 | 单元测试；Chrome/Edge 兼容与性能自动化 |
| 代码质量 | ruff | 0.17.1 | lint ＋ format 统一风格 |
| 环境 | WSL2 Ubuntu ＋ CUDA 12.8 | — | 50 系显卡硬要求（PyTorch ≥2.7） |

### 0.2 模块地图与验收标准映射

| 模块 | 名称 | 主责 | 核心周次 | 对应验收 |
|---|---|---|---|---|
| M0 | 环境与工程化 | A+B | W1—W4 | 前置条件 |
| M1 | 人脸检测与对齐 | A | W1—W15 | D1 |
| M2 | 单图三维重建 | A | W1—W17 | D2 |
| M3 | 年龄方向与形状老化（核心创新） | A | W17—W22 | D3 |
| M4 | 纹理老化（SAM） | A | W19—W22 | D4 |
| M5 | 后端服务（FastAPI＋WS） | B | W4、W12—W26 | D5、D6 |
| M6 | 前端可视化（three.js） | B | W2、W12—W26 | D3、D7 |
| M7 | 资产与导出管线（glTF＋morph target） | B 主导、A 配合 | W17—W23 | D5、D6 |
| M8 | 集成测试与实验评价 | A+B | W23—W26 | D1—D7、全部量化指标 |
| M9 | 合规、文档与交付 | A+B | W1、W23—W30 | 交付物 1—13 |

---

## 1. 技术框架选型分析

### 1.1 四条选型原则（贯穿全项目）

1. **ONNX 化优先**：检测与重建模型一律导出 ONNX，后端用 onnxruntime 推理。B 在无 CUDA 的机器上也能用 CPU 版联调；避免每帧 Python/PyTorch 开销。
2. **仅传参数、不传网格**：实时链路每帧 ≤ 1 KB（框、5 点、β、ψ、pose）；模板网格、形状基、morph 位移文件一次性加载。
3. **实时线 / 离线线分离**：检测＋姿态驱动渲染走实时线（≥30 FPS）；重建＋年龄方向＋SAM 纹理＋导出走离线线（"拍照 → 生成 → 查看"，可等数秒）。
4. **能跑通压倒一切**：老仓库（3DDFA_V2 2020、SAM 2021）一律先跑通 demo 再谈集成；兼容性风险用"独立进程/独立环境/回退版本"消化，不做无谓重构。

### 1.2 分层选型与备选对比

| 决策点 | 选定 | 备选 | 不选原因 |
|---|---|---|---|
| 检测框架 | ultralytics 8.4.x（YOLO26） | YOLO5Face（DeepFaceLab 系）、libfacedetection | 有官方训练/评测/导出全链路；YOLO26 是当前正式版且 n 级模型最轻 |
| 三维重建保底 | 3DDFA_V2 | PRNet、Deep3DFaceRecon | 自带 BFM 处理好的模型文件、摄像头 demo、ONNX 推理，CPU 可实时 |
| 三维重建主线 | MICA（FLAME） | DECA、HRN、pixel3DMM | 度量精度高、接口干净；DECA 依赖多（PyTorch3D 等）留作纹理参考 |
| 年龄方向（保底） | BFM 2009 `04_attributes.mat` | — | 官方自带年龄形状方向，拿来即用 |
| 年龄方向（主线） | UTKFace/FFHQ-Aging 批量重建 → 按年龄回归 | LSFM/LYHM 按年龄子模型 | 子模型要另签协议；自回归路线即本课题创新点（对齐 3D-STD 思路） |
| 纹理老化 | SAM（StyleGAN+pSp） | LATS、FADING、Cradle2Cane（扩散） | SAM 最成熟、有 MIT 许可、连续年龄控制；扩散类 8GB 显存吃紧 |
| 前端渲染 | three.js（原生 ESM＋Vite） | Babylon.js、Unity WebGL、react-three-fiber | morph target/glTF 生态最全；官方示例直接可参考；无框架更省 2 人工作量 |
| 后端 | FastAPI＋uvicorn＋websockets | Flask＋Flask-SocketIO、Tornado | 原生 async、Pydantic 校验、WebSocket 一等公民、自动 OpenAPI 文档 |
| 推理运行时 | onnxruntime | TorchScript、TensorRT | 跨机器（Windows CPU/WSL2 GPU）部署一致；TensorRT 作为加分项 |
| 导出格式 | glTF 2.0 / GLB（内嵌 morph target） | FBX、OBJ 序列 | 浏览器原生加载、Blender 可校验、morph target 标准支持 |

### 1.3 YOLO 版本决策（重点）

**结论：使用 YOLO26（ultralytics 8.4.178），权重 `yolo26n-face.pt`。**

- **版本依据**：YOLO26 是 ultralytics 当前正式版（YOLO27 官方标注"即将推出"、未发布）；`yolo26n` 为 2.4 M 参数 / 5.5 GFLOPs，官方 COCO 指标 mAP50-95 = 40.9、T4 TensorRT10 仅 1.7 ms——8 GB 显存笔记本与 CPU 回退都跑得动。
- **权重来源**：[akanametov/yolo-face](https://github.com/akanametov/yolo-face) release `1.0.0`，`yolo26n-face.pt` 与 `yolo26s-face.pt`（WIDER FACE 训练，2025-09 发布）。推理/微调均用 `pip install ultralytics` 的官方 API，不装额外依赖。
- **⚠ 关键勘误（必须先解决）**：核验仓库 README 后确认，**`yolo26n-face.pt` 是纯检测（detect）权重，只输出人脸框，不输出 5 个关键点**（任务书写的是"输出人脸框与 5 个关键点"）。WIDER FACE 本身也无关键点标注。应对两条路线：
  - **路线 A（保底，1 周内落地）**：`yolo26n-face.pt` 出框 → 3DDFA_V2 自带的裁剪对齐流程做 120×120 归一化（其内部按框对齐）→ 拟合后 68 点投影取 5 点用于前端显示与调试。
  - **路线 B（主线，正好喂饱论文"模型训练与实验"章节）**：用 `yolo26n-pose` 架构在 5 点标注数据上训练（WFLW 98 点、300W-LP 68 点均可缩标为 5 点），得到"框 ＋ 5 点"单模型输出；检测精度在 WIDER FACE 上评（用其 bbox 输出），额外报告 5 点 NME。训练数据与脚本入 `training/yolo/`。
- **微调与评测方案**：WIDER FACE 官方划分（Easy/Medium/Hard），`yolo task=detect mode=train model=yolo26n-face.pt data=datasets/widerface.yaml ...`；评测脚本 `experiments/detection/eval_widerface.py` 输出 mAP 表 ＋ FPS（GPU/CPU 两栏），对比基线：微调前权重、YOLO5Face、3DDFA_V2 自带 FaceBoxes。
- **ONNX 导出**（对接到后端）：
  ```python
  from ultralytics import YOLO
  model = YOLO("yolo26n-face.pt")
  model.export(format="onnx", dynamic=False, nms=True, device="cuda:0")  # 端到端含 NMS
  ```
  产物 `yolo26n-face.onnx` 入 `backend/assets/models/`（不入 Git，README 记获取/生成方式）。
- **许可证说明**：ultralytics 为 AGPL-3.0。毕设（开源、非商用）无碍；论文"相关技术"与 README 中注明即可。也可用同仓库 `yolov12n-face.pt`/`yolov11n-face.pt` 作对照实验。

### 1.4 前端：three.js（0.186.1）

- **够用的能力**：WebGL2 渲染、`Mesh.morphTargetInfluences` 权重驱动、`GLTFLoader`、`OrbitControls`、PMREM 环境光照、`KTX2Loader`（纹理压缩备选）。
- **必读官方示例**（B 在 W2 跑通，作为 M6 起点）：
  - `webgl_morphtargets_webcam.html`——摄像头 ＋ morph target ＋ 头部姿态驱动，与本题前端形态几乎同构；
  - `webgl_morphtargets_face.html`——人脸关键点驱动 morph target；`webgl_animation_skinning_morph.html`——morph 权重插值写法。
- **前端形态**：Vite ＋ 原生 ES Module ＋（可选）TypeScript；无 React/Vue——单页面 2 个画布（`video`／2D overlay ＋ three.js canvas），引入框架只会增加联调成本。
- **实时链路的数学**：姿态（R、t）是刚体变换，每帧只更新一个 `Object3D.matrix`；β/ψ 变化仅在"重新拍照/重建"时发生，客户端用本地形状基重建几何。因此**每帧消息里只有 pose ＋ 少量参数**，形状基虽大（18 MB 量级）但只加载一次，可 float16/int16 量化减半（M7 任务项）。
- **年龄滑块实现约定**：3—4 档 morph target（20/45/70，后续可扩 20/35/50/70），滑块 w∈[0,1] 映射到相邻两档权重（两个 `morphTargetInfluences` 线性插值），保证连续、无跳变。

### 1.5 后端：FastAPI ＋ WebSocket（0.143.3 ＋ 0.54.0）

- **为什么 FastAPI**：原生 async（摄像头帧高并发 IO 不阻塞）、Pydantic v2 强校验（接口冻结后可自文档化）、WebSocket 一等公民（`@app.websocket`）、自动 `/docs` 便于 A/B 联调。
- **组成**：`fastapi` ＋ `uvicorn[standard]`（内含 websockets 17.2）＋ `python-multipart`（图片上传）＋ `pydantic`（schema）。全部锁定版本见 §4.2。
- **推理接入**：`onnxruntime-gpu 1.31.0`（WSL2）推理；推理调用放入线程池（`anyio.to_thread.run_sync`），避免阻塞事件循环；模型懒加载＋启动预热（`/api/health` 报告加载状态与推理设备）。
- **并发模型**：单摄像头会话（`face_state` 带 `seq`，丢弃过期帧、单飞写入）；HTTP 与 WS 共享同一个"模型注册表"单例（`backend/app/core/registry.py`）。
- **备选不选**：Flask＋Flask-SocketIO（同步模型多一层兼容层，异步推理别扭）；Tornado（生态与文档学习成本高，无 Pydantic 体系）。

### 1.6 算法栈（A 线）与兼容性

- **PyTorch 2.14.1 ＋ torchvision 0.29.1（cu128）**：任务书硬约束"CUDA 12.8 ＋ PyTorch ≥2.7"。RTX 5060 必须走此版本，否则 `no kernel image is available`。
- **3DDFA_V2 兼容性**：2020 年代码，需处理：(1) `Sim3DR` Cython 扩展在新 NumPy 头文件下编译问题——优先编译，失败则跳过扩展走纯 Python 顶点路径；(2) 若不可救药，单独建 `agdfa` 环境（numpy<2）只跑重建，仍以 ONNX 产物对接主环境。
- **MICA**：依赖 FLAME 许可；如 demo 需要 pytorch3d 等重依赖，只在 WSL2 安装（Windows 原生编译困难），并把输出统一成与 3DDFA_V2 相同的参数字典接口（`reconstruction/params.py` 做适配层）。
- **SAM**：用官方 pSp 预训练权重推理（不重训）；8 GB 显存用 256 分辨率跑通即可（论文指标以 256 为主，1024 作为加分项）。
- **评价工具**：insightface（ArcFace 余弦相似度）、MiVOLO（年龄估计）、FG-NET（定性对比图组）——只在 W23 起接入，不进入产品运行时依赖。

### 1.7 工程与质量工具

- **Git**：`feat/`、`fix/` 分支，约定式提交，tag：`v0.1-mvp`（阶段 2 末）、`v0.5-aging`（阶段 3 末）、`v1.0-final`（阶段 4 末）。模型、数据集、`output/`、`logs/` 一律 `.gitignore`。
- **ruff 0.17.1**：lint＋format（替代 black＋flake8）；`pre-commit` 可选。
- **pytest 9.1.1**：单元测试（参数序列化、morph 权重映射、坐标系变换）；**Playwright 1.64.0**：Chrome/Edge 双浏览器冒烟测试＋WS payload 体积自动化检查。

---

## 2. 模块分解与详细行动计划

> 每模块格式：**目标 → 输入/输出 → 步骤 → 验收 → 风险 → 责任人/周次**。
> 与项目计划的 A/B 任务卡编号（A1—A11、B1—B10）交叉引用，不另立体系。

### M0 环境与工程化（A+B，W1—W4）

**目标**：两台机器都能在 30 分钟内从零复现环境并跑通健康检查。

**步骤**：
1. 仓库骨架按 §4.4 建目录；写 `.gitignore`（模型/数据/输出/日志）、`README.md`（环境＋获取方式）。
2. WSL2 环境：conda 建 `agemorph` 环境（Python 3.11），按 §4.2 锁定清单安装；验证 `torch.cuda.is_available()` → `True`、onnxruntime GPU provider 列表含 `CUDAExecutionProvider`。
3. 一键脚本：`tools/setup_env.sh`（安装）＋`tools/download_assets.py`（按 manifest 下载/校验模型与数据，含 sha256）。
4. 记录版本矩阵到 `docs/env.md`（CUDA/PyTorch/ORT/驱动）；A 在阶段 0 完成，B 照文档独立复现一次（互为验证）。
5. 接口文档 `docs/api.md` v0.1 建稿（内容即 §3），W6 冻结。

**验收**：双方机器 `pytest -q` 通过空跑用例；`docs/env.md` 能让第三者复现。

**风险**：50 系显卡驱动/CUDA 版本链（R2）——用 `nvidia-smi`＋`nvcc --version` 双确认；Docker 备选。

---

### M1 人脸检测与对齐（A，W1—W15；对应 A3、A4）

**目标**：输入一帧画面 → 输出 `bbox ＋ 5 关键点 ＋ 置信度`，GPU ≥30 FPS；WIDER FACE Easy mAP ≥ 90%。

**输入/输出**：
- 输入：单帧图像（BGR ndarray，480p/720p 降采样）；
- 输出：`{"bbox":[x,y,w,h], "landmarks":[[u,v]×5], "conf":0.99}`（与 WS `face_state` 前段同构）。

**步骤**：
1. W1—W3：拉取 `yolo26n-face.pt`，跑通单图/摄像头推理；确认输出结构（核对 §1.3 勘误，决定 5 点路线 A/B）。
2. W4—W8：WIDER FACE 数据准备（`tools/prepare_widerface.py`：官方 TXT → YOLO 格式 `training/yolo/widerface.yaml`）；完成微调训练脚本 `training/yolo/train_detect.py`。
3. W12—W13：集成到 3DDFA_V2 流程替换 FaceBoxes（`backend/detection/yolo_face.py` 提供 `detect(frame) -> FaceResult`）；对齐裁剪逻辑（按框外扩比例、灰度归一化 120×120）。
4. W13—W15：微调训练（路线 B 同时训 5 点 pose：WFLW/300W-LP 转 5 点，脚本 `training/yolo/prepare_landmarks5.py`）；评测 `experiments/detection/eval_widerface.py` → mAP/FPS 表 ＋ 曲线图（自绘，禁贴图）。
5. 导出 ONNX（`nms=True`、`dynamic=False`）并接入 onnxruntime 推理路径；对拍 PyTorch 输出一致性（IoU>0.99）。

**验收**：D1（框＋5 点目测/帧率日志）；Easy mAP ≥ 90%；ONNX 与 PyTorch 对拍通过。

**风险**：5 点权重缺失（已在 §1.3 处置）；WIDER FACE 下载慢——国内镜像/学校网络；训练显存——n 级模型 batch 16/640 仅 2—3 GB，安全。

---

### M2 单图三维重建（A，W1—W17；对应 A1、A2、A5、A6）

**目标**：输入对齐后人脸图 → 输出 `{shape, expr, pose, uv_texture, verts}`；保底 3DDFA_V2 跑通，主线 MICA 同接口。

**步骤**：
1. W1：提交 FLAME 注册、BFM 2009 申请（GNM Head 作免申请备选，Apache-2.0）；留痕许可状态表 `docs/model_licenses.md`。
2. W2—W3：WSL2 跑通 3DDFA_V2 `demo_webcam_smooth.py`（摄像头实时）；建立兼容性补丁记录（NumPy/Sim3DR）。
3. W4—W8：吃透参数含义（形状 α、表情 β、姿态 R/t、UV 纹理生成路径），写 `backend/reconstruction/tddfa_wrapper.py`：`reconstruct(img, bbox) -> ReconstructResult`（dataclass，被 M5 直接调用）。
4. W9：端到端保底 demo：YOLO 检测 → 裁剪 → 3DDFA 重建 → 投影关键点回原图叠加（命令行版）。
5. W10：MICA 选型验证（demo 跑通、输出 FLAME 顶点）；写 `mica_wrapper.py` 并统一到 `params.py` 适配层（同一 `ReconstructResult`）。
6. W12—W14：集成进后端管线；AFLW2000-3D NME 评测 `experiments/reconstruction/eval_aflw2000.py`，输出对比表（3DDFA_V2 官方权重 / 微调后 / MICA）。
7. W16：ONNX 化：3DDFA_V2 用官方 ONNX 权重；MICA 用 `torch.onnx.export`（dynamic axes）尝试，失败则保留 PyTorch 进程内推理（接口不变，不阻塞集成）。

**验收**：D2（重建参数 ＋ UV 纹理 ＋ 叠加对比图）；NME 不劣于开源基线。

**风险**：FLAME/BFM 许可等待（R1，阶段 0 先提交）；MICA 依赖重（pytorch3d）——主线可迟至 W17，不阻塞保底。

---

### M3 年龄方向与形状老化（A，W17—W22；对应 A7、A8。全程第一优先级风险项）

**目标**：拿到 `w(age)` 连续可控的逐顶点年龄位移，导出为前端 morph target，且与模板网格**顶点编号一一对应**。

**步骤**：
1. **W17 拓扑对齐验证（硬闸门）**：写 `tools/bfm_to_morphtarget.py`，把 BFM 年龄方向换算为逐顶点位移；同时验证 FLAME 拓扑导出链路。**结果决定全程锁定哪个拓扑**（R3），另一拓扑只做对照实验。
2. W17—W18：`backend/aging/bfm_age.py`——读 `04_attributes.mat` 年龄方向 → 形状基线性映射 → 逐顶点 `delta_age`；对 `delta_age` 做 L2 归一化（滑块 w∈[0,1] 均匀映射，防非线性跳变）。
3. W18：导出 `age_20/age_45/age_70`（后续可扩 20/35/50/70）三档 morph 位移 `.bin`；`meta.json` 记录顶点数、坐标顺序、sha256（格式见 §3.3）。
4. W19—W21：主线回归——`training/aging/regress_age_direction.py`：UTKFace/FFHQ-Aging 批量重建（复用 M2 wrapper，异步队列跑）→ 按年龄分桶 → 岭回归估计 FLAME 形状空间的年龄方向 → 输出回归系数与单调性检查图（`experiments/aging/`）。
5. W21—W22：单调性/合理性检查脚本：年龄 20→70 逐岁采样顶点位移，检查下颌、眼窝、鼻唇沟方向的位移趋势与幅度；异常则回退保底方向（R5）。

**验收**：D3（拖动滑块形变连续、单调、无穿模）；W17 拓扑闸门通过；回归系数入论文。

**风险**：三维老化无现成代码（R5）——保底 BFM 方向先上，回归作为论文改进实验；拓扑切换重做 morph（R3）——W17 闸门锁定。

---

### M4 纹理老化（A，W19—W22；对应 A9）

**目标**：目标年龄纹理生成 → UV 展开贴回 → 前端可见皱纹/肤色变化，UV 无错位（D4）。

**步骤**：
1. W19—W20：SAM 环境与权重接入（`backend/aging/sam_texture.py`）：输入对齐人脸 → 输出目标年龄照片（20—70 岁连续输入）；记录 8 GB 显存下的分辨率/耗时基线（256 先跑通）。
2. W20—W21：UV 管线：保底拓扑用 3DDFA_V2 自带 UV（`bfm_uv`）把老化照片展成纹理贴图；主线拓扑用 DECA 的 FLAME UV 布局（资产记录进 manifest）。
3. W21—W22：纹理回贴：`texture_aged.png` 与 base 纹理做年龄档位（20/45/70）输出；接 `/api/aging` 返回 `texture_url`。
4. 消融准备：仅形状老化 / 仅纹理老化 / 两者叠加（实验章节用）。

**验收**：D4；纹理切换可见且无错位。

**风险**：8 GB 显存（R4）——半精度＋256 分辨率，必要时租云 GPU；UV 错位——以人脸基准点对拍校验。

---

### M5 后端服务（B，W4、W12—W26；对应 B3、B7）

**目标**：FastAPI＋WebSocket 全套接口（§3 冻结版），Mock 先行、ONNX 后接，单帧 payload < 1 KB。

**步骤**：
1. W4—W5：骨架 `backend/app/main.py`＋`api/routes.py`＋`ws/handler.py`＋`core/config.py`＋`core/registry.py`；`/api/health` 返回模型加载状态与设备。
2. W5—W6：Mock 实现——`/api/reconstruct` 返回固定 β/ψ/pose 与占位纹理；WS `face_state` 回显（供 B 前端与 A 后端并行开发）。
3. W12—W13：真检测接入（调用 M1 wrapper）；WS 帧循环：`receive_bytes`（JPEG）→ 线程池推理 → `send_json(face_state)`；过载策略：丢弃旧帧、`seq` 单调、单飞。
4. W16—W23：重建与老化接入（M2/M3/M4 wrapper）；HTTP 接口全量实现（§3.2）；glTF 导出接口接 M7。
5. 资源管理：模型启动预热（可选 `lifespan` 中加载）、uvicorn 单 worker（多 worker 会复制模型显存）；`logs/` 结构化日志（请求耗时、payload 大小、错误码）。
6. W23—W26：性能压测脚本 `experiments/system/bench_ws.py`：统计帧延迟分布、payload 体积（断言 < 1 KB）、断线重连行为。

**验收**：D6（网络面板 payload < 1 KB）；D5 的后端侧（导出接口返回文件流）。

**风险**：WS 高帧率下事件循环阻塞——一律线程池；Windows/WSL2 联调差异——B 用 CPU onnxruntime 也能跑通。

---

### M6 前端可视化（B，W2、W12—W26；对应 B2、B4、B5、B6）

**目标**：three.js 场景一次加载模板网格＋形状基＋morph 位移；年龄滑块 20—70 连续调节；摄像头拍照流程；导出按钮；Chrome/Edge 双可用。

**步骤**：
1. W2：跑通官方 `webgl_morphtargets_webcam` 与 `webgl_morphtargets_face` 示例（记录到 `docs/notes/`）。
2. W12—W14：`frontend/` 工程化（Vite＋three 0.186.1）；`viewer.js`：GLTFLoader 加载模板网格（`/api/assets/{mesh_id}/mesh.glb`），PMREM 环境光＋`MeshStandardMaterial`，OrbitControls。
3. W12—W14：`ws-client.js`：WebSocket 连接、发帧（`canvas.toBlob('image/jpeg', 0.7)` → ArrayBuffer）、收 `face_state`；`camera.js`：`getUserMedia`＋2D overlay 画框/5 点。
4. W17—W19：`slider.js`：滑块 → morph 权重映射（相邻档位插值）；`viewer.js` 增加 `morphTargetInfluences` 驱动；实时链路中 pose 驱动（矩阵更新）与 β/ψ（本地形状基重建）分离处理。
5. W18—W20：`texture.js`（或并入 viewer）：UV 纹理加载与切换（base/aged）；光照调优。
6. W19—W21：`ui.js`：拍照流程（冻结帧 → 调 `/api/reconstruct` → 进入"生成中"状态 → 完成后可拖滑块）、导出按钮（调 `/api/export/gltf` 下载 GLB；`renderer.domElement.toDataURL` 截图，需 `preserveDrawingBuffer:true`）、错误提示（无人脸/多人脸/超时）。
7. W21—W26：性能与兼容：渲染 ≥30 FPS；requestAnimationFrame 节流；Chrome/Edge 手工矩阵＋Playwright 冒烟脚本 `tests/e2e/`。

**验收**：D3（滑块形变）、D7（双浏览器）、D6 前端侧（只收参数）。

**风险**：形状基文件大——量化/裁剪分量（M7 配合）；morph 法语序踩坑——先用两档位移验证再上多档。

---

### M7 资产与导出管线（B 主导、A 配合，W17—W23；对应 B7）

**目标**：资产 manifest 规范 ＋ morph 位移二进制规范 ＋ glTF/GLB（含 morph target）导出可在 three.js 编辑器/Blender 打开。

**步骤**：
1. W17—W18：确定资产目录与命名（§3.4）：`mesh.glb`（base mesh＋UV）、`morph/age_xx.bin`、`meta.json`、纹理 PNG；`tools/make_delta_bin.py` 固化格式与 sha256 校验。
2. W18—W19：形状基压缩与加载方案：β 维度裁剪（BFM 40 维全留／FLAME 取前 50）＋ float16/int16 量化，加载耗时实测记录。
3. W21—W23：glTF 导出：`backend/export/gltf_export.py`（pygltflib 手写 accessor＋morph targets；trimesh 辅助几何处理），产出 GLB 含 POSITION/NORMAL/TEXCOORD_0/indices＋image＋morph targets（v1 先 POSITION delta，NORMAL delta 视光照效果决定是否补）。
4. 校验流程：three.js 编辑器在线打开 ＋ Blender 导入，截图入 `docs/`；`/api/export/image` 用无头渲染或前端截图接口产出 PNG。

**验收**：D5（导出文件可打开）；资产 manifest 前后端一致（哈希校验通过）。

**风险**：trimesh 不写 morph target——以 pygltflib 为准；坐标/腰间尺度差异（BFM 单位 vs FLAME 米制）——meta.json 显式记录单位与坐标系（右手 Y-up，前向 +Z）。

---

### M8 集成测试与实验评价（A+B，W23—W26；对应 B8、A10）

**目标**：全部量化指标出数（项目计划 §2.2），系统指标达标。

**步骤**：
1. 端到端延迟：拍照 → 生成（重建＋年龄方向＋纹理）≤ 5 s；渲染 ≥ 30 FPS；`experiments/system/bench_e2e.py`。
2. payload 体积：WS 每帧 < 1 KB 自动断言（Playwright 抓帧大小）。
3. 兼容性矩阵：Chrome/Edge（Windows）＋分辨率 1280×720/1920×1080；Playwright 冒烟＋手工表格。
4. 检测：WIDER FACE mAP/FPS 表；重建：AFLW2000-3D NME 表；年龄变换：MiVOLO MAE 曲线、ArcFace 余弦相似度（含对照组：仅 2D 老化）、FG-NET 定性图组、消融（仅形状/仅纹理/两者）。
5. 主观实验：10—20 人 5 分制双维度（像目标年龄/像本人），问卷与统计脚本入 `experiments/subjective/`。

**验收**：项目计划 §2.2 表格全部有数；阶段 4 评审通过。

---

### M9 合规、文档与交付（A+B，W1、W23—W30；覆盖交付物 1—13）

**步骤**：
1. W1 起：知情同意书模板 `docs/compliance/知情同意书.md`＋本地处理声明；采集照片前签署；不采集未满 14 岁（R9）。
2. W23—W26：合规文档定稿；README 补齐（环境、模型获取、运行步骤）；`cloc` 每两周统计代码量（≥1500 行/人，R10）。
3. W27—W28：演示视频脚本（3—5 分钟：检测 → 重建 → 滑块 → 纹理 → 导出 → 合规说明）；B 主导录制。
4. W27—W29：论文（A 算法章节、B 系统章节＋技术选型对比/经济效益与社会贡献/法律健康安全环境分析）；外文翻译各一篇（A 选 3D-STD/MICA，B 选 three.js/WebGL 方向）。
5. W29—W30：查重、评阅表、答辩 PPT。

---

## 3. 接口与数据格式 v1.0（草案；W6 冻结，其后只增不改）

### 3.1 WebSocket 协议

| 项 | 约定 |
|---|---|
| 端点 | `ws://localhost:8000/ws/frame` |
| 传输 | 帧：二进制（JPEG/WebP，建议 640×480、质量 0.7）；控制/回包：JSON 文本 |
| 方向 | C→S `frame`（二进制）｜S→C `face_state` / `error` / `status` |
| 节流 | 后端单飞处理；过载丢弃旧帧；`seq` 单调递增用于对账 |

```jsonc
// S→C face_state（示例；序列化 < 1 KB）
{
  "type": "face_state", "seq": 123, "ts": 1755432000123,
  "bbox": [120.5, 88.0, 210.0, 210.0],
  "landmarks": [[150,140],[262,138],[205,190],[160,236],[250,238]],
  "shape": [/* 50 floats */], "expr": [/* 50 floats */],
  "pose": { "R": [/* 9 */], "t": [/* 3 */] },
  "conf": 0.99
}
// S→C error
{ "type": "error", "code": "NO_FACE|MULTI_FACE|TIMEOUT|BAD_INPUT", "msg": "..." }
// S→C status
{ "type": "status", "models": {"detector":"yolo26n-face.onnx","recon":"3ddfa_v2"},
  "device": "cuda", "fps": 33.2 }
```

> 参数维度（shape/expr）以实现时的模型为准（3DDFA_V2 与 FLAME 不同），**W6 冻结后写入 `docs/api.md`**，前端按冻结维度写死。

### 3.2 HTTP API（沿用项目计划 §4.2，补全资产端点）

| 方法 | 路径 | 用途 | 返回 |
|---|---|---|---|
| POST | `/api/reconstruct` | 上传照片 → 重建 | `{mesh_id, shape, expr, pose, texture_url}` |
| POST | `/api/aging` | `{mesh_id, age}` → 目标年龄 | `{shape_aged, texture_url}` |
| GET | `/api/assets/{mesh_id}/manifest.json` | 资产清单（网格/基/位移/纹理/哈希） | JSON |
| GET | `/api/assets/{mesh_id}/mesh.glb` | 模板网格＋UV | GLB |
| GET | `/api/assets/{mesh_id}/morph/{name}.bin` | 逐顶点位移（float32） | 二进制 |
| POST | `/api/export/gltf` | 导出当前年龄模型 | 文件流（.glb) |
| POST | `/api/export/image` | 导出渲染截图 | PNG |
| GET | `/api/health` | 模型、版本、设备 | `{models, device, version}` |

### 3.3 morph target 资产格式（定稿 v1）

```jsonc
// manifest.json 片段
{
  "mesh_id": "bfm_v1",                  // 或 flame_v1
  "vertex_count": 38365,
  "coordinate": "right-handed, Y-up, +Z-front, unit: mm",
  "age_range": [20, 70],
  "targets": [
    { "name": "age_20", "delta": "morph/age_20.bin", "sha256": "..." },
    { "name": "age_45", "delta": "morph/age_45.bin", "sha256": "..." },
    { "name": "age_70", "delta": "morph/age_70.bin", "sha256": "..." }
  ],
  "slider": { "weight": 0.0, "direction": "linear", "interp": "piecewise-neighbor" }
}
```

- `delta.bin`：**float32 little-endian，布局 `[V×3]`，行优先（v0.x,v0.y,v0.z, v1.x, ...），顶点顺序与 `mesh.glb` 的 POSITION accessor 严格一致**。
- 位移为**相对基准网格**的绝对偏移（非相邻年龄差分）；档位不足时前端在相邻档位间线性插值（两个 `morphTargetInfluences`）。
- 写入时同步输出 `sha256`，前后端加载时校验。

### 3.4 资产目录与命名

```
backend/assets/               # 不入 Git
├── models/                   # yolo26n-face.onnx, 3ddfa/*.onnx, mica/*.onnx, sam/*
├── bfm/                      # BFM 原始模型文件（04_attributes.mat 等）
├── flame/                    # FLAME 模型文件（如主线启用）
└── meshes/
    └── bfm_v1/
        ├── mesh.glb
        ├── manifest.json
        ├── morph/age_20.bin | age_45.bin | age_70.bin
        └── textures/base.png | age_20.png | age_45.png | age_70.png
frontend/public/assets/       # 只放符号链接或构建拷贝（开发期直连后端静态目录亦可）
```

---

## 4. 环境与依赖（可复制粘贴）

### 4.1 基线

- WSL2 Ubuntu（24.04 LTS）；NVIDIA 驱动 ≥ 满足 CUDA 12.8（`nvidia-smi` 确认）；
- conda（或 Miniconda）＋ Python 3.11；Node.js ≥ 20（前端构建）。

### 4.2 Python（`requirements.txt` 锁定草案）

```text
# 深度学习核心（cu128 索引）
torch==2.14.1
torchvision==0.29.1
# 检测
ultralytics==8.4.178
# 推理/导出
onnx==1.23.2
onnxruntime-gpu==1.31.0        # B 的 CPU 机器装 onnxruntime==1.31.0
# 服务
fastapi==0.143.3
uvicorn[standard]==0.54.0
websockets==17.2
python-multipart==0.0.32
# 数值/图像/网格
numpy==2.5.4
scipy==1.18.1
scikit-learn==1.9.1
Pillow==13.0.0
opencv-python==5.0.0.93        # 遇兼容问题回退 4.12.x
trimesh==5.1.1
pygltflib==1.16.5
# 工具
ruff==0.17.1
pytest==9.1.1
```

安装命令：

```bash
conda create -n agemorph python=3.11 -y && conda activate agemorph
pip install torch==2.14.1 torchvision==0.29.1 --index-url https://download.pytorch.org/whl/cu128
pip install -r requirements.txt
python -c "import torch, onnxruntime as ort; print(torch.cuda.is_available(), ort.get_available_providers())"
# 期望：True  ['TensorrtExecutionProvider', 'CUDAExecutionProvider', 'CPUExecutionProvider']
```

> 3DDFA_V2 若与主环境冲突，单独建 `agdfa` 环境（numpy<2）只跑重建，产物经 ONNX/文件对接。

### 4.3 前端（`frontend/package.json` 要点）

```json
{
  "type": "module",
  "dependencies": { "three": "0.186.1" },
  "devDependencies": { "vite": "^8.3.4" },
  "scripts": { "dev": "vite --host", "build": "vite build", "preview": "vite preview" }
}
```

### 4.4 仓库目录（文件级，与项目计划 §9 对齐）

```
AgeMorph3D/
├── backend/
│   ├── app/          main.py, api/routes.py, ws/handler.py, core/{config,registry}.py, schemas.py
│   ├── detection/    yolo_face.py, export_onnx.py
│   ├── reconstruction/ tddfa_wrapper.py, mica_wrapper.py, params.py
│   ├── aging/        bfm_age.py, regression.py, sam_texture.py, uv_map.py
│   ├── export/       gltf_export.py, image_export.py
│   └── assets/       （见 §3.4，不入 Git）
├── frontend/
│   ├── index.html, vite.config.js, package.json
│   └── src/          main.js, viewer.js, ws-client.js, api-client.js, camera.js, slider.js, texture.js, ui.js
├── training/
│   ├── yolo/         widerface.yaml, train_detect.py, train_pose5.py, prepare_landmarks5.py
│   └── aging/        regress_age_direction.py
├── experiments/
│   ├── detection/eval_widerface.py
│   ├── reconstruction/eval_aflw2000.py
│   ├── aging/{eval_mivolo_arcface.py, monotonicity_check.py}
│   ├── system/{bench_ws.py, bench_e2e.py}
│   └── subjective/survey.py
├── tools/            setup_env.sh, download_assets.py, prepare_widerface.py,
│                     bfm_to_morphtarget.py, make_delta_bin.py
├── tests/            unit/…, e2e/…（Playwright）
├── docs/             env.md, api.md, model_licenses.md, compliance/, notes/
├── requirements.txt, .gitignore, README.md
```

---

## 5. 30 周时间线 × 模块映射（与项目计划 §6.2 合并）

| 周 | 日期 | A（算法） | B（系统） | 模块交汇点 |
|---|---|---|---|---|
| W1 | 11.16 | M0 环境；FLAME/BFM 申请（M2） | M0 环境；技术选型初稿 | 接口讨论启动 |
| W2 | 11.23 | M2 3DDFA 摄像头 demo | M6 官方示例跑通 | 保底/主线切换条件确认 |
| W3 | 11.30 | M2 BFM 格式摸底；M1 权重核验 | M6 网格加载原型 | 架构图初稿 |
| W4 | 12.07 | M1 数据准备 | M5 FastAPI 骨架 | 接口文档 v0.1 |
| W5 | 12.14 | M1 数据管线 | M5 Mock 接口＋前端联调 | 开题分工 |
| W6 | 12.21 | M1 训练脚本 | M6 可视化预研 | **接口文档 v1.0 冻结** |
| W7 | 12.28 | M1 预训练评估 | M6 交互草案 | 开题初稿 |
| W8 | 01.04 | M2 参数含义梳理 | B1 论文章节素材 | 导师审阅开题 |
| W9 | 01.11 | M2 端到端 demo（检测→重建） | 总体设计图 | 可行性定稿 |
| W10 | 01.18 | M2 MICA 选型验证 | M6 UI 线框 | 开题修改 |
| W11 | 01.25 | 开题定稿（A 部分） | 开题定稿（B 部分） | **提交开题报告** |
| W12 | 02.01 | M1 集成 | M6 网格＋形状基 | — |
| W13 | 02.08 | M1 微调 | M5 WS 骨架 | 第一次联调 |
| W14 | 02.15 | M2 重建集成；AFLW 测试 | M6 渲染管线 | **开题答辩 02.20—03.01** |
| W15 | 02.22 | M1 评测出数 | M6 光照材质 | 检测实验 |
| W16 | 03.01 | M2 ONNX 导出 | M6 性能基线 | 阶段 2 评审 |
| W17 | 03.08 | **M3 拓扑闸门**；位移换算 | M6 morph 加载 | **首个滑块原型（硬闸门）** |
| W18 | 03.15 | M3 morph 导出 | M6 滑块映射 | 单调性检查 |
| W19 | 03.22 | M3 批量重建启动；M4 SAM 接入 | M6 UV 纹理 | 回归数据积累 |
| W20 | 03.29 | M3 回归出图；M4 UV 展开 | M6 纹理切换 | 回归曲线 |
| W21 | 04.05 | M4 纹理贴回 | M6 UI 完善 | 纹理老化首次可见 |
| W22 | 04.12 | M3/M2 保底-主线合并评估 | M6 集成演示版 | **中期报告 04.15—04.20** |
| W23 | 04.19 | M8 实验协议（MiVOLO/ArcFace） | M5 ONNX 接入；M7 glTF 导出 | 阶段 3 评审 |
| W24 | 04.26 | M8 FG-NET 对比 | M8 联调（payload 断言） | payload 检查 |
| W25 | 05.03 | M8 主观打分 | M8 延迟测试 | 实验数据初版 |
| W26 | 05.10 | M8 图表 | M8 兼容性测试 | **阶段 4 评审；合规定稿** |
| W27 | 05.17 | 论文算法章节；M9 | 论文系统章节；视频脚本 | 论文初稿 |
| W28 | 05.24 | 外文翻译；论文修改 | **视频录制** | 送导师评阅 05.20 起 |
| W29 | 05.31 | 查重修改 | 查重修改；PPT | 终稿 |
| W30 | 06.07 | 答辩准备 | 答辩准备 | **答辩** |

---

## 6. 风险与切换判据（技术向）

| ID | 风险 | 概率/影响 | 触发条件 | 预案 |
|---|---|---|---|---|
| T1 | yolo26n-face 无 5 点（已确认） | 确定/中 | W3 核验 | 路线 A（3DDFA 投影 5 点）兜底；路线 B（pose 训练）进论文 |
| T2 | 50 系显卡＋老仓库不兼容 | 高/中 | 安装即报错 | PyTorch 2.14＋cu128；3DDFA 独立环境；ONNX 路径绕开 |
| T3 | BFM→FLAME 拓扑差异（R3） | 中/高 | **W17 闸门失败** | 锁定单一拓扑跑完整链路；另一拓扑只做对照 |
| T4 | 年龄方向视觉效果不合理（R5） | 高/高 | W21 单调性检查不过 | 回退 BFM 官方方向；自估计方向写成改进实验 |
| T5 | 8 GB 显存不足（SAM/回归批处理） | 中/中 | OOM | 半精度＋降分辨率；离线线隔离；租云 GPU |
| T6 | 3DDFA_V2 在新 NumPy/Torch 崩 | 中/中 | 编译/运行报错 | Sim3DR 跳过／补丁；`agdfa` 独立环境 |
| T7 | FLAME/BFM 许可等待（R1） | 中/高 | 阶段 1 末未获批 | 3DDFA 自带 BFM 先用；GNM Head 免申请备选 |
| T8 | WS 高帧率阻塞/丢帧 | 中/低 | 帧率 < 30 | 线程池推理＋单飞＋旧帧丢弃；降采样 480p |

**三个硬闸门**：W6 接口冻结、W17 拓扑锁定、W22 主线/保底合并评估（效果闸门）。

---

## 7. 阶段 0 立即行动清单（本周起，至 2026-11-15）

1. **提交许可申请**：FLAME（官网注册）、BFM 2009（下载申请）、LSFM/LyHM（可选）；记录 `docs/model_licenses.md`。
2. **下载官方权重**：`yolo26n-face.pt`（yolo-face release 1.0.0）、3DDFA_V2 权重、SAM 官方权重、MiVOLO 权重（W23 前到位即可）。
3. **M0 环境**：按 §4.2 在 WSL2 建 `agemorph` 环境，跑通 §4.1 验证命令；产出 `docs/env.md`。
4. **跑通三件套 demo**：3DDFA_V2 `demo_webcam_smooth.py`；`yolo predict model=yolo26n-face.pt`；three.js `webgl_morphtargets_webcam`。
5. **核验 5 点问题**：确认 yolo26n-face 输出是否含关键点，落地方案 A/B（T1）。
6. **拉仓库骨架**：按 §4.4 建目录＋`.gitignore`＋README 初稿。
7. **写 `docs/api.md` v0.1**：内容即 §3，W6 冻结前允许改。
8. **与导师确认**：题目范围（年龄变换 ≠ 年龄预测）、20—70 岁限定、数据集清单与合规流程。
9. **数据准备**：WIDER FACE、AFLW2000-3D、UTKFace/FFHQ-Aging、FG-NET 的下载与校验脚本（`tools/download_assets.py` 骨架）。
10. **周例会制度**：定固定时间；首次议程＝保底/主线切换判据（W17 拓扑、W22 效果）。

---

*本文件与《AgeMorph3D_项目计划.md》配套使用：项目计划管"做什么、何时做"，本文件管"用什么做、每个模块怎么做"。*
