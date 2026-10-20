# 模型与环境资产台账

核查日期：2026-10-20。B0真实CPU、B1生命周期、B2/B3静态GLB及B6实时框/五点/姿态均已实现。现有清单仍未通过完整许可核验，真实服务G1/G2未签收。原始哈希见 [B0记录](B0模型验证与复现.md)，生命周期见 [B1记录](B1协议与生命周期开发记录.md)，静态及实时/实体设备证据分别见 [B23记录](B23真实静态链路开发记录.md) 和 [B6记录](B6实时姿态开发记录.md)。

| 资产 | 本次实际状态 | 来源/许可/哈希 | 剩余证据 |
|---|---|---|---|
| API/推理环境 | Python 3.11.16，项目 `backend/.venv/`；可选 `inference` extra；无推理依赖也可启动基础 API | 依赖源/版本/哈希见 `backend/uv.lock`；实测 CPUExecutionProvider；加载与请求共用单工作线程 | GPU provider、严格真实服务成功链路和实际性能仍独立验证 |
| YOLO 人脸五点 | clibdev 转换 ONNX nano0.5；本地真实样例 1 脸/5 点，另有空白/双人/横竖补边/镜像检查 | 原作者 deepcam，代码 GPL-3.0；固定 release 1.0.0；ONNX SHA-256 `269eb1e54313f9d1f7941ed9939fa247767539bca5801fc7aa7895960e93ca43` | 独立权重条款、原 PT/ONNX 等价、五点精确定义与精度；研究成功不改变服务 readiness |
| 用户原始 BFM | 已确认非商业研究授权，提供 TGZ/H5；原文件未改 | 原始哈希见 `output/backend/b0/tddfa-research/user-assets.json`；本地研究用途 | 不推断公开派生分发许可；原始基、UV 索引和年龄属性映射需另验 |
| 3DDFA/BFM 重建 | 官方 ONNX/裁剪基已真实 CPU 运行；38,365 顶点、76,073 面、40 shape/10 expr；身份/表情已应用于静态网格 | cleardusk commit `1b6c67601abffc1e9f248b291708aef0e43b55ae`；代码 MIT、修改 BFM 学术限制另记；逐文件哈希见 B0 文档 | 独立权重/派生条款、不同真实身份与服务 G1；不能用一个样例证明精度 |
| 拓扑/稀疏点 | 独立 `tri.pkl` 重建面序；NPZ v2 保留官方 204 坐标索引，回投影 68 点 | 拓扑 SHA-256 `cc449ed7efa2860bed64be0a7e29ad8944912148c69f938ff768c8766d65e7cb`；第44组混合坐标原样记录 | 不将原生稀疏点误称为 68 个网格顶点，不静默修补上游数据 |
| canonical/GLB | 右手 Y-up、正面 +Z；bbox 高度归一化到1，记录中心/比例；SVD 提取纯旋转，反射/奇异块拒绝；自包含静态 GLB 为1,838,792字节 | 新拓扑为 `tddfa-bfm-canon-v1-` 加原拓扑哈希；每面 `(a,b,c)→(a,c,b)`，顶点及面顺序保留；原始/派生哈希见 B2/B3 报告 | 无源米制单位证明，不能当人体测量；开放面部，无完整后脑、UV、纹理或年龄目标 |
| 派生资产缓存 | 随机标识的不可变内存字节，TTL1800秒、总量512MiB、128项、单项64MiB；读取租约防逐出，取消/关闭不发布迟到结果 | 不读取任意文件路径，不落盘原图/裁剪/服务 GLB；进程退出清空 | 默认值不是性能承诺；读取占满时返回429，过期/未知标识404 |
| 实时/实体相机 | 已复用同一真实模型对生成框、五点和SVD纯旋转；逐帧不生成GLB；ASUS摄像头与Chrome/Edge取得限定范围本地证据 | 未新增模型/数据/依赖；JPEG原坐标、预览镜像S R S、t=0未标定；相机帧不保存 | 严格服务仍许可error；研究与合成证据分列，人工姿态质量及完整G2未签收 |
| UV | 官方 `UV[indices]` 为 `[38365,2]`，有限且在 `[0,1]` | `BFM_UV.mat`、`indices.npy` 哈希见下载清单；本地输出 `uv.npz` | 基础纹理、可见性/遮挡、接缝和 GLB 材质尚未验收 |
| 年龄形状 | 服务 `missing`，无可用年龄形变 | 原始 BFM 有 200 项 age_shape/age_tex 属性，完整基199维与裁剪基40维不同 | 映射、年尺度、源年龄、连续性、身份保持未验；不能直接跨基相加 |
| 年龄纹理 | 服务 `missing`，未安装/下载 [SAM](https://github.com/yuval-alaluf/SAM) | 仍为候选 | 权重条款、显存/算子及 UV 投影/接缝验证 |
| GPU 推理 | 尚未安装或验证 | 本次仅有真实 CPU ONNX 推理证据 | GPU provider 需要真实运行，不用设备名称替代 |
| 训练数据 | 没有下载训练集或开始训练 | 只有公开成年人人像 astronaut 最小样例，来源和哈希已登记 | 后端出口评审之后推进数据获取、预处理和训练 |

健康响应的device:cpu不是GPU不可用诊断。检测/重建状态由严格许可/哈希核验、实例构造和CPU自检决定，重建自检含canonical/GLB。两者均ready且未关闭时开放reconstruction和realtime，年龄仍false；当前两份真实研究清单仍unresolved，服务加载为许可error、四项能力仍false；无配置则missing。离线实时探针及独立研究摄像头联调不改变许可门槛，不产生严格服务readiness。

当前真实研究证据为 `output/backend/b23/real-static/report.json` 和 `output/backend/b23/browser/static-mesh-research.json`：同一照片经真实 CPU 模型生成 canonical GLB；Chrome/Edge 实际查看器各完成一次离线资产加载、导出和重新加载，位置/法线/索引保持。该浏览器批次使用独立本地资产服务和软件 WebGL，无严格服务真实推理成功证据，不宣称 G1 或新 UI 导入功能。原图镜像、EXIF 旋转、空白、多脸、坏图和严格清单拒绝的结果见 B2/B3 记录。[glTF 规范](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#coordinate-system-and-units)使用米制场景约定，当前数字表示归一化展示对象，不代表源 BFM 或人体尺度已获得米制标定。

取得的模型、旧格式源文件、NPZ、样例及推理输出放在本机 `data/`、`output/`，源码 `backend/model-manifests/` 只记录元数据。用户原始目录继续保留，本轮未移动或改写。候选清单默认拒绝未收口条款，显式研究开关不产生服务 readiness 或公开分发许可。选择背景见 [模型与数据路线核验](模型与数据路线核验.md)。
