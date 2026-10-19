# 模型与环境资产台账

核查日期：2026-10-19。独立 B0 探针已运行真实 YOLO 五点检测和 3DDFA/BFM CPU 重建；服务层尚未接入模型生命周期和推理。完整命令、哈希、坐标及验收边界见 [B0 模型验证与复现](B0模型验证与复现.md)。

| 资产 | 本次实际状态 | 来源/许可/哈希 | 剩余证据 |
|---|---|---|---|
| API/推理环境 | Python 3.11.16，项目 `backend/.venv/`；可选 `inference` extra | 依赖源/版本/哈希见 `backend/uv.lock`；实测 CPUExecutionProvider | 生命周期、GPU provider 和服务端资源实测仍独立验证 |
| YOLO 人脸五点 | clibdev 转换 ONNX nano0.5；本地真实样例 1 脸/5 点，另有空白/双人/横竖补边/镜像检查 | 原作者 deepcam，代码 GPL-3.0；固定 release 1.0.0；ONNX SHA-256 `269eb1e54313f9d1f7941ed9939fa247767539bca5801fc7aa7895960e93ca43` | 独立权重条款、原 PT/ONNX 等价、五点精确定义与精度；研究成功不改变服务 readiness |
| 用户原始 BFM | 已确认非商业研究授权，提供 TGZ/H5；原文件未改 | 原始哈希见 `output/backend/b0/tddfa-research/user-assets.json`；本地研究用途 | 不推断公开派生分发许可；原始基、UV 索引和年龄属性映射需另验 |
| 3DDFA/BFM 重建 | 官方 ONNX/裁剪基已真实 CPU 运行；38,365 顶点、76,073 面、40 shape/10 expr | cleardusk commit `1b6c67601abffc1e9f248b291708aef0e43b55ae`；代码 MIT、修改 BFM 学术限制另记；逐文件哈希见 B0 文档 | canonical 轴向/单位、纯旋转、GLB/缓存和浏览器闭环尚未接入 |
| 拓扑/稀疏点 | 独立 `tri.pkl` 重建面序；NPZ v2 保留官方 204 坐标索引，回投影 68 点 | 拓扑 SHA-256 `cc449ed7efa2860bed64be0a7e29ad8944912148c69f938ff768c8766d65e7cb`；第44组混合坐标原样记录 | 不将原生稀疏点误称为 68 个网格顶点，不静默修补上游数据 |
| UV | 官方 `UV[indices]` 为 `[38365,2]`，有限且在 `[0,1]` | `BFM_UV.mat`、`indices.npy` 哈希见下载清单；本地输出 `uv.npz` | 基础纹理、可见性/遮挡、接缝和 GLB 材质尚未验收 |
| 年龄形状 | 服务 `missing`，无可用年龄形变 | 原始 BFM 有 200 项 age_shape/age_tex 属性，完整基199维与裁剪基40维不同 | 映射、年尺度、源年龄、连续性、身份保持未验；不能直接跨基相加 |
| 年龄纹理 | 服务 `missing`，未安装/下载 [SAM](https://github.com/yuval-alaluf/SAM) | 仍为候选 | 权重条款、显存/算子及 UV 投影/接缝验证 |
| GPU 推理 | 尚未安装或验证 | 本次仅有真实 CPU ONNX 推理证据 | GPU provider 需要真实运行，不用设备名称替代 |
| 训练数据 | 没有下载训练集或开始训练 | 只有公开成年人人像 astronaut 最小样例，来源和哈希已登记 | 后端出口评审之后推进数据获取、预处理和训练 |

健康响应的 `device: cpu` 仍属于基础服务状态，不是 GPU 不可用的诊断。独立探针的 CPU 执行另有真实报告。`runtime.py` 尚未接模型加载，四项服务状态仍固定 `missing`；放置文件不会自动就绪。

取得的模型、旧格式源文件、NPZ、样例及推理输出放在本机 `data/`、`output/`，源码 `backend/model-manifests/` 只记录元数据。用户原始目录继续保留，本轮未移动或改写。候选清单默认拒绝未收口条款，显式研究开关不产生服务 readiness 或公开分发许可。选择背景见 [模型与数据路线核验](模型与数据路线核验.md)。
