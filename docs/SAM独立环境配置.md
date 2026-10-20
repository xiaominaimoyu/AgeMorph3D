# SAM 独立环境配置与首次推理验证

记录日期：2026-10-20。范围：在本机为官方 SAM checkpoint 建一个隔离的离线研究环境，跑通最小 batch=1 推理，并记录可复现证据。**这不是服务能力上线**：年龄能力仍为 `false`，checkpoint 许可仍为 `research-only-unresolved`，输出仍是二维 RGB 图像，未做 UV 注册、身份评价或年尺度校准。

## 1. 本机环境

| 项 | 值 |
|---|---|
| 操作系统 | Windows 11 家庭中文版，10.0.26200 |
| CPU | AMD Ryzen AI 9 H 465（10 核 / 20 线程） |
| 内存 | 31.2 GB |
| GPU | NVIDIA GeForce RTX 5060 Laptop GPU（Blackwell，sm_120） |
| 显存 | 8,150.6 MiB（`total_memory` 8,546,484,224 B） |
| 驱动 | 595.79，报告 CUDA 13.2 |
| 磁盘 | D: 安装后剩余 55.3 GB |
| CUDA Toolkit | **未安装**，`nvcc` 不存在 |
| MSVC | Visual Studio 2022 Build Tools（x64 C++ 工具链） |
| 包管理 | uv 0.12.11；conda 25.11.1 |
| SAM 代码 | `data/third_party/SAM`，commit `c1895aef275e702fba7560284dc16df60d65210e` |
| 独立环境 | `data/envs/sam`（Python 3.11.16），约 4.3 GB |

`data/` 与 `output/` 都在 `.gitignore` 下；该环境、checkpoint 和 SAM 克隆都不进入源码发布，也不进入 `backend/model-manifests/`。

## 2. 为什么不照官方环境

官方 `environment/sam_env.yaml` 是 Python 3.6.7 / torch 1.6.0 / CUDA 10.x。直接照搬在本机会遇到三个硬问题：

1. **Blackwell 不支持旧 CUDA wheel。** RTX 5060 是 sm_120，cu121 及更旧的 wheel 会报 “no kernel image is available”；必须用 cu128 及更新构建（本机选 torch 2.11.0+cu128）。
2. **上游算子在 import 时编译 CUDA 扩展。** `models/stylegan2/op/fused_act.py` 和 `upfirdn2d.py` 在模块顶层调用 `torch.utils.cpp_extension.load`，需要 nvcc 和与 torch 完全匹配的 CUDA Toolkit；本机没有。上游自带的 `upfirdn2d_native` 也不能直接当回退，因为它使用了 `F.pad` 却没有导入 `torch.nn.functional`。
3. **torch ≥ 2.6 改了 `torch.load` 默认值。** SAM checkpoint 同时保存 `opts` 和 `state_dict`，默认 `weights_only=True` 会拒绝加载；`models/psp.py` 的加载调用必须显式 `weights_only=False`。

可选方案对比：

| 方案 | 代价 | 结论 |
|---|---|---|
| 安装 CUDA Toolkit 12.8 + 编译上游算子 | 额外 3—4 GB，版本/MSVC 组合敏感 | 不采用；batch=1 研究推理没有必要 |
| 纯 PyTorch 原生算子替代 | 少量性能损失，无数值语义变化 | **采用**，已做数值自检 |
| CPU 推理 | 无需 GPU，但 1024 StyleGAN2 很慢 | 保留 `--device cpu` 入口，本次未测 |

## 3. 原生算子替代

`tools/sam_native_ops/` 保留上游公开名称与参数名，因此官方 checkpoint 可以原样加载：

- `fused_act.py`：`leaky_relu(x + bias) * scale`，`bias` 参数名不变。
- `upfirdn2d.py`：零插值 + 常数 padding + depthwise `conv2d` + 抽取，支持正/负 padding，语义与上游 `upfirdn2d_native` 对齐。

安装器 `tools/sam_native_ops/install.py` 会：

- 校验两个上游文件的归一化 SHA-256（CRLF/LF 均匹配），不匹配就拒绝覆盖；
- 备份信息写入 `models/stylegan2/op/NATIVE_OPS.json`；
- 把 `models/psp.py` 的 checkpoint 加载改为 `weights_only=False`；
- 支持 `--check`（只报告）和 `--restore`（`git checkout` 还原）。

数值自检（`tools/sam_native_ops/selftest.py`）用显式循环参考实现对比，覆盖 up=2/3、down=1/2、正负 padding：

| 用例 | 最大绝对误差 |
|---|---:|
| `fused_leaky_relu` | 0 |
| `upfirdn2d` 5 组形状/步长/padding | ≤ 1.43e-6 |

## 4. 安装与复现

在仓库根目录执行（PowerShell）：

```powershell
uv venv --python 3.11 data/envs/sam
uv pip install --python data/envs/sam/Scripts/python.exe `
  --index-url https://download.pytorch.org/whl/cu128 `
  "torch==2.11.0+cu128" "torchvision==0.26.0+cu128"

data/envs/sam/Scripts/python.exe tools/sam_native_ops/install.py `
  --sam-root data/third_party/SAM
data/envs/sam/Scripts/python.exe tools/sam_native_ops/selftest.py
```

GPU 可用性检查：

```powershell
data/envs/sam/Scripts/python.exe -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available(), torch.cuda.get_device_capability(0))"
```

本机实测输出：`2.11.0+cu128 12.8 True (12, 0)`，并在 GPU 上完成 1024×1024 matmul。

推理探针（输出目录必须不存在）：

```powershell
data/envs/sam/Scripts/python.exe tools/sam_probe.py `
  --sam-root data/third_party/SAM `
  --checkpoint data/models/sam/sam_ffhq_aging.pt `
  --image data/third_party/SAM/notebooks/images/866.jpg `
  --target-ages 20,45,70 `
  --output-dir output/research/sam-probe-20261020
```

`--device cpu` 可切到 CPU；`--target-ages` 接受 1—10 个 0—100 的不重复整数。

## 5. 本机验证结果

输入 `notebooks/images/866.jpg`（1024×1024，SHA-256 `93ca3e8d…9804`），先缩到 256×256，再按官方契约补第 4 通道 `age/100`。输出为 1024×1024 RGB。

| 指标 | 结果 |
|---|---|
| checkpoint 加载 | 0.79 s（页缓存命中） |
| 模型构建（含第二次加载） | 3.66 s |
| 首次前向（含 CUDA 懒初始化） | 0.451 s |
| 稳定前向（45/70 岁） | 0.123 s / 0.119 s |
| 峰值显存（含模型权重） | 2,693.6 / 2,709.6 / 2,708.6 MiB |
| 20 岁输出 SHA-256 | `0d8bd8b09e41c7d354cd75784ed244de7f9ca52d9c2a86a67d8e8ebe1a6de562` |
| 45 岁输出 SHA-256 | `fe1ae63722229578f40d6cd557e6fc15a58c2b61e087acf3c38925dfb582b93c` |
| 70 岁输出 SHA-256 | `63420d03e2ebc07096967693f698938796fd29e2bb0e6dca7293b543b38bea3f` |
| 复现性 | 另起进程重跑 45 岁，PNG 逐字节一致 |

输出图像在 `output/research/sam-probe-20261020/`，报告在同目录 `report.json`；`output/` 不提交。模型报告确认：`input_nc=4`、`output_size=1024`、`start_from_latent_avg=false`、`start_from_encoded_w_plus=true`；checkpoint 自身带 `latent_avg` 和 `pretrained_encoder.*`，因此不需要 README 另列的 pSp 辅助权重。

## 6. 输入契约与限制

- 输入必须是 **FFHQ 风格对齐的 256×256（或可缩放到 256×256）人脸**；本探针只做 resize，不做检测/对齐。
- 本项目 3DDFA 的裁剪与 FFHQ 对齐不是同一坐标系，**不能**把 `backend` 的 3DDFA 裁剪图直接喂给 SAM；现已完成从原照片 68 点重新采样的[离线桥接实验](FFHQ对齐桥接实验.md)，并保留坐标逆变换和原图有效区。
- 目标年龄按整数处理（官方 `AgeTransformer` 就是 `int(age)/100`），没有逐岁连续性保证。
- 输出是二维图像，不是 BFM/UV 纹理，也没有做重投影、接缝、遮挡或身份保持评价。
- `randomize_noise=False` 只保证本机复现；不构成跨设备/跨版本确定性承诺。
- checkpoint 与 FFHQ 派生权重仍是非商业研究用途、许可未收口，禁止再分发。

## 7. 回滚

```powershell
data/envs/sam/Scripts/python.exe tools/sam_native_ops/install.py `
  --sam-root data/third_party/SAM --restore
```

还原 `models/psp.py`、两个算子文件并删除 `NATIVE_OPS.json`。删除整个 `data/envs/sam` 可回收约 4.3 GB；checkpoint 与 SAM 克隆可单独保留。

## 8. 这次验证没有证明什么

- 没有证明 SAM 对项目用户人脸的年龄效果、身份保持或 artifacts 水平；
- 没有建立源年龄/目标年龄到年尺度的映射；
- 没有把二维输出注册到 UV 或 3D 网格；
- 没有做按身份分组的评价，也没有 AgeDB 真值校准；
- 没有改变严格服务的 `age_texture`、`age_slider` 或 readiness。

后续[桥接实验](FFHQ对齐桥接实验.md)已用 10 个成功样例生成 FFHQ 风格的 256×256 裁剪，并在本环境产生 30 张 SAM 二维输出；另 2 个预期失败样例返回 `NO_FACE`。这只验证输入输出链路；下一步做按身份分组的同人真实跨龄评价，UV 注册和年尺度校准另立实验，服务状态不变。
