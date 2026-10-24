# 模型与环境资产台账

核查日期：2026-10-20。B0真实CPU、B1生命周期、B2/B3静态GLB及B6实时框/五点/姿态均已实现。现有清单仍未通过完整许可核验，真实服务G1/G2未签收。原始哈希见 [B0记录](B0模型验证与复现.md)，生命周期见 [B1记录](B1协议与生命周期开发记录.md)，静态及实时/实体设备证据分别见 [B23记录](B23真实静态链路开发记录.md) 和 [B6记录](B6实时姿态开发记录.md)。

本批B4/B5完成现有资产范围的年龄属性强度方向、用户源年龄输入及基础照片UV，见 [B45记录](B45年龄方向与UV开发记录.md)。2026-10-20 另行获取官方 SAM checkpoint 与 FG-NET 研究镜像小样：SAM 已在独立环境跑通 batch=1 二维推理，FG-NET 未用于训练但已完成解码/检测/68 点一致性研究检查；年尺度、年龄纹理和身份质量仍未签收，两项服务年龄能力仍false。获取来源、哈希与许可边界见 [年龄模型与校准样例获取记录](年龄模型与校准样例获取记录.md)，SAM 环境见 [SAM 独立环境配置](SAM独立环境配置.md)。后续[FFHQ桥接实验](FFHQ对齐桥接实验.md)已完成10个预期成功样例与30张二维SAM输出、2个NO_FACE对照，保留原图有效区；不改变许可或G3状态。

| 资产 | 本次实际状态 | 来源/许可/哈希 | 剩余证据 |
|---|---|---|---|
| API/推理环境 | Python 3.11.16，项目 `backend/.venv/`；可选 `inference` extra；无推理依赖也可启动基础 API | 依赖源/版本/哈希见 `backend/uv.lock`；实测 CPUExecutionProvider；加载与请求共用单工作线程 | GPU provider、严格真实服务成功链路和实际性能仍独立验证 |
| YOLO 人脸五点 | clibdev 转换 ONNX nano0.5；本地真实样例 1 脸/5 点，另有空白/双人/横竖补边/镜像检查 | 原作者 deepcam，代码 GPL-3.0；固定 release 1.0.0；ONNX SHA-256 `269eb1e54313f9d1f7941ed9939fa247767539bca5801fc7aa7895960e93ca43` | 独立权重条款、原 PT/ONNX 等价、五点精确定义与精度；研究成功不改变服务 readiness |
| 用户原始 BFM | 已确认非商业研究授权，提供TGZ/H5；原文件未改，B45已证明年龄方向的形状基对应 | 原始哈希见B0，逐成员/派生哈希见B45；本地研究用途 | 不推断公开派生分发许可；原模型UV索引不能替代当前裁剪UV，年尺度仍需校准 |
| 3DDFA/BFM 重建 | 官方 ONNX/裁剪基已真实 CPU 运行；38,365 顶点、76,073 面、40 shape/10 expr；身份/表情已应用于静态网格 | cleardusk commit `1b6c67601abffc1e9f248b291708aef0e43b55ae`；代码 MIT、修改 BFM 学术限制另记；逐文件哈希见 B0 文档 | 独立权重/派生条款、不同真实身份与服务 G1；不能用一个样例证明精度 |
| 拓扑/稀疏点 | 独立 `tri.pkl` 重建面序；NPZ v2 保留官方 204 坐标索引，回投影 68 点 | 拓扑 SHA-256 `cc449ed7efa2860bed64be0a7e29ad8944912148c69f938ff768c8766d65e7cb`；第44组混合坐标原样记录 | 不将原生稀疏点误称为 68 个网格顶点，不静默修补上游数据 |
| canonical/GLB | 右手Y-up、正面+Z，bbox高度1，记录中心/比例；SVD纯旋转；B23无纹理样例1,838,792B，B45照片UV样例2,217,416B | 固定新拓扑与逐面绕序，顶点/面顺序保留；原始/派生哈希见各批记录 | 非米制、开放面部、无完整后脑；可选基础UV不包含年龄目标 |
| 派生资产缓存 | 随机标识的不可变内存字节，TTL1800秒、总量512MiB、128项、单项64MiB；读取租约防逐出，取消/关闭不发布迟到结果 | 不读取任意文件路径，不落盘原图/裁剪/服务 GLB；进程退出清空 | 默认值不是性能承诺；读取占满时返回429，过期/未知标识404 |
| 实时/实体相机 | 已复用同一真实模型对生成框、五点和SVD纯旋转；逐帧不生成GLB；ASUS摄像头与Chrome/Edge取得限定范围本地证据 | 未新增模型/数据/依赖；JPEG原坐标、预览镜像S R S、t=0未标定；相机帧不保存 | 严格服务仍许可error；研究与合成证据分列，人工姿态质量及完整G2未签收 |
| UV/基础照片纹理 | 官方UV为[38365,2]；已实现连续max-Z/朝向/范围可见性、单atlas与内嵌PNG，未知区域透明；真实双浏览器像素往返通过 | 原uv.npz SHA `d191871a33467b3b6c0565b62469b17e16241efd1683c681ea9550dc9c741228`未改；生产可选uv角色另需绑定有序topology与严格许可/hash | 无外部遮挡分割或去光照；单身份公开样例；不等同年龄纹理 |
| 年龄形状方向 | 服务仍missing；已从原199维PC/EV/age属性映射至38,365顶点，原生强度−50—50研究可运行 | 原53,490顶点对应裁剪顶点，全部40PCA逐项零误差；派生NPZ `e94e8f294a2a36264a6751eaffdcd4854f7587800de1ccde31d4969424850b5b`，不公开分发 | 第200项语义未证明，按官方示例忽略；没有年尺度；用户源年龄输入不替代校准或身份验收 |
| 年龄纹理 | 服务missing；原BFM纹理方向仅派生未应用于照片；官方SAM checkpoint已在独立环境跑通batch=1二维推理（稳定约0.12 s，峰值显存约2.7 GB，1024×1024输出）；原图68点到FFHQ桥接取得10样例/30输出证据 | [SAM](https://github.com/yuval-alaluf/SAM)代码MIT；checkpoint无独立许可声明，FFHQ派生数据CC BY-NC-SA 4.0；checkpoint大小2,270,547,237B、SHA-256 `6fbd6085e2e6001f51f6dee896ae5ba7bd6c3fab5c06fadba75f2a12188ba143`；本机用原生PyTorch算子shim替代JIT CUDA扩展（自检误差≤1.4e-6） | 权重条款未收口；年尺度/小数年龄、生成图重对齐/重建/UV、身份质量仍未验证；FFHQ几何兼容不含完整上游滤波等价，见[桥接](FFHQ对齐桥接实验.md)、[SAM环境](SAM独立环境配置.md)与[获取记录](年龄模型与校准样例获取记录.md) |
| GPU 推理 | 服务侧尚未安装或验证；研究侧 SAM 已在独立环境用 CUDA 跑通 batch=1 | 本次仅有真实 CPU ONNX 推理证据；SAM 研究运行不构成服务 GPU provider 证据 | GPU provider 需要真实运行，不用设备名称替代 |
| 训练/校准数据 | 未开始训练；已取得FG-NET研究镜像全量1,002张/82人及20—70子集292张/55人；20—70子集已完成解码/检测/68点研究检查（292张全部解码，290张单人脸并重建成功） | 归档SHA-256 `228acddeba96e469f2ded9475ee87f4ab16398de27a2f3ec35a266a46ef2f7fc`；镜像页仅写研究用途，原始站点已停止分发，许可`research-only-unresolved`；逐图清单见`data/datasets/fgnet/`，检查报告见`output/research/fgnet-pipeline-20261020/` | 不可商用/再分发；检查只证明可读入/可重建，不证明身份或年尺度；先作外部检查，AgeDB需邮件申请密码；见[获取记录](年龄模型与校准样例获取记录.md) |

健康响应的device:cpu不是GPU不可用诊断。检测/重建状态由严格许可/哈希核验、实例构造和CPU自检决定，重建自检含canonical/GLB。两者均ready且未关闭时开放reconstruction和realtime，年龄仍false；当前两份真实研究清单仍unresolved，服务加载为许可error、四项能力仍false；无配置则missing。离线实时探针及独立研究摄像头联调不改变许可门槛，不产生严格服务readiness。

当前真实研究证据为 `output/backend/b23/real-static/report.json` 和 `output/backend/b23/browser/static-mesh-research.json`：同一照片经真实 CPU 模型生成 canonical GLB；Chrome/Edge 实际查看器各完成一次离线资产加载、导出和重新加载，位置/法线/索引保持。该浏览器批次使用独立本地资产服务和软件 WebGL，无严格服务真实推理成功证据，不宣称 G1 或新 UI 导入功能。原图镜像、EXIF 旋转、空白、多脸、坏图和严格清单拒绝的结果见 B2/B3 记录。[glTF 规范](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#coordinate-system-and-units)使用米制场景约定，当前数字表示归一化展示对象，不代表源 BFM 或人体尺度已获得米制标定。

取得的模型、旧格式源文件、NPZ、样例及推理输出放在本机 `data/`、`output/`，源码 `backend/model-manifests/` 只记录元数据。用户原始目录继续保留，本轮未移动或改写。候选清单默认拒绝未收口条款，显式研究开关不产生服务 readiness 或公开分发许可。选择背景见 [模型与数据路线核验](模型与数据路线核验.md)。

## BFM 原始包分发位置

用户原始 `BaselFaceModel.tgz` 为 240,287,841 字节（229.2 MiB），超过 GitHub 普通文件 100 MB 上限，且当前账号 LFS 配额已耗尽，因此不进入 Git 历史（`*.tgz` 保持忽略），改以 GitHub Release 附件分发：[assets-bfm-2009](https://github.com/xiaominaimoyu/AgeMorph3D/releases/tag/assets-bfm-2009)。附件 SHA-256 为 `d6cf2dffb74404f4f7ee2cd56f611e6fdcb22081ebf993f8b01edf6207f6cce9`，仅用于复原本地研究环境，仍受 BFM 非商业研究许可约束，不构成商业授权、公开派生分发许可或服务 readiness。
