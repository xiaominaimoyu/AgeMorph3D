# AgeMorph3D 本地后端

本地 FastAPI 服务已实现 B1 模型生命周期和 v1.2 契约。**HTTP/WS 成功推理与 GLB 发布尚未接入**；合法推理请求仍返回 `503 MODEL_NOT_READY`。独立 B0 已运行真实 YOLO 五点检测与 3DDFA/BFM 重建；服务现在可严格核验清单、加载模型并执行 CPU 算子自检，不会返回演示网格冒充成功。

2026-10-19基础服务限定范围已通过阶段验收，实际证据、两项传输层边界和后续出口见[基础服务验收报告](../docs/基础服务验收报告.md)。这不代表整个后端或完整G0已验收。

## 启动

在 Windows PowerShell 中执行；需要 [uv](https://docs.astral.sh/uv/) 和首次下载依赖所需的网络。使用独立 Python 3.11 环境，锁定依赖见 `uv.lock`。

```powershell
cd 'D:\project file\AgeMorph3D\backend'
uv --cache-dir ..\output\uv-cache sync --locked --python 3.11
.\.venv\Scripts\python.exe -m agemorph3d
```

服务绑定 `http://127.0.0.1:8000`，单进程，关闭代理头信任，限制同时连接数。按 `Ctrl+C` 退出并释放工作线程。不要使用系统默认 Python 运行本项目，也不要增加 Uvicorn worker 来复制未来的模型实例。健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health | ConvertTo-Json -Depth 5
```

另一个终端从 `frontend/` 执行 `npm run dev`，在页面中连接本地服务。默认无模型配置时各项为 `missing`；配置后状态来自真实核验/加载/自检。当前成功处理链路未发布，重建、实时检测和年龄纹理能力仍禁用；演示模式可单独使用。

## 配置模型生命周期

模型清单路径可从环境变量指定，不根据同名权重文件自动就绪：

```powershell
$env:AGEMORPH_DETECTOR_MANIFEST = 'D:\project file\AgeMorph3D\data\models\yolov5n05-face\manifest.json'
$env:AGEMORPH_RECONSTRUCTOR_MANIFEST = 'D:\project file\AgeMorph3D\data\models\3ddfa-v2\manifest.json'
.\.venv\Scripts\python.exe -m agemorph3d
```

加载需要先 `uv sync --locked --extra inference`。未配置/清单不存在为 `missing`，已配置先 `loading`，严格资产核验、实例构造和真实 CPU 算子自检通过才为 `ready`；失败为脱敏 `error`。现有两份 B0 研究清单仍为 `license_status=unresolved`，使用上面的路径会得到许可核验错误，服务不会偷偷启用研究绕过。用户提供的 BFM 非商业研究授权保留在台账中，这不是整套候选资产的分发条款证明。

单个模型 `ready` 表示该算子通过加载/自检，不代表 `/api/reconstruct` 或 `/ws/frame` 已成功实现。B1 的四项全局能力仍为 false。加载与请求共用一个工作线程，加载期间其他处理返回429；健康接口可读取状态。初始化不承诺硬超时或中断底层算子；退出先禁止新任务和迟到结果就绪，再等待实际线程完成、清理实例，可能需要等待运行中的算子。

## 配置与边界

默认允许 `http://127.0.0.1:5173`、`http://localhost:5173` 以及相应 `4173` 来源。若 Vite 自动改端口，指定白名单后重启服务，例如：

```powershell
$env:AGEMORPH_ALLOWED_ORIGINS = 'http://127.0.0.1:5174,http://localhost:5174'
.\.venv\Scripts\python.exe -m agemorph3d
```

配置只接受 HTTP(S) 回环 origin，不接受 `*`、路径、账号、查询或片段。HTTP 无 Origin 时允许本机命令行调用；浏览器 Origin 必须在白名单中。WS 必须携带白名单 Origin。Host 独立校验，CORS 不启用凭据。运行命令始终只监听回环地址，来源检查不替代绑定限制。

| 输入/处理 | 本批限制 |
|---|---|
| 图片 | 真正可解码的 JPEG、PNG、WebP，非空、≤10 MiB、≤1600 万像素；声明 MIME 与文件格式一致；拒绝动画 |
| Multipart | 一个 `image` 文件和可选 `source_age` 十进制文本（20—70）；未知字段拒绝；请求总量≤图片限额+64 KiB；原图在内存中解码并纠正 EXIF 方向，不落盘 |
| JSON | 请求体≤128 KiB；年龄为有限的 20—70 数值，不接受字符串或布尔值；未知字段拒绝 |
| 实时帧 | 仅二进制 JPEG，≤2 MiB，最长边≤640；服务回复≤1024 UTF-8 字节 |
| 工作线程 | 模型加载/自检及图片校验共用单个活跃任务、无等待队列，忙时429；HTTP正文接收与处理共享25秒预算，WS处理6秒 |
| 取消/超时 | 调用方停止等待后仍占用实际运行任务的槽位，直至线程完成；不承诺中断已执行的算子 |
| 资产 | 不挂载磁盘目录，当前所有网格ID返回404；GLB发布、TTL和容量缓存留待B2/B3/B7 |

HTTP 错误统一提供字符串 `detail` 和稳定 `code`。API与输入错误不回显原图、文件名或完整参数。HTTP 响应设置 `Cache-Control: no-store`。WS 坏帧和模型缺失会先发送一次终结 `error`，再关闭连接；没有实现成功 `face_state` 推理。

上述错误约定限于进入应用的请求和帧。Uvicorn连接达到16上限时可能直接返回无CORS的纯文本503；超过2 MiB的WS消息在协议层以1009关闭，不产生JSON终结消息。这两项已作为非阻断边界记录，完整G0收口时继续处理。

OpenAPI JSON 位于 `/openapi.json`；本批关闭需要外部 CDN 的 Swagger/ReDoc 页面。完整协议见 [接口文档](../docs/api.md)。

## 验证与后续开发

B0 的可选推理依赖安装、模型清单、旧资产受限转换、真实检测和重建命令见 [B0 模型验证与复现](../docs/B0模型验证与复现.md)。不安装该 extra 时仍可启动无模型 API，推理模块的数值测试会明确跳过。B1 的状态转换、静态/源年龄契约和本次实测见 [B1 协议与生命周期开发记录](../docs/B1协议与生命周期开发记录.md)。

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check src tests
.\.venv\Scripts\ruff.exe format --check src tests
```

测试只在测试目录中构造图片，不使用真实人物照片或权重。`test_inputs.py` 验证解码、schema 和配置，`test_api.py` 验证 HTTP/WS 契约，`test_runtime.py` 验证并发、超时和取消后的真实槽位生命周期。

`test_model_lifecycle.py` 通过合成适配器验证加载、部分失败、关闭和迟到释放，并检查无推理依赖时的服务导入；`test_result_contract.py`、`test_reconstruction_contract_api.py` 验证新增成功契约和源年龄输入。真实 CPU 自检和真实服务检查独立记录在 B1 证据中。

下一步按 [后端计划](../docs/后端任务计划.md) 收口 B0 条款/五点定义与 canonical 坐标，推进 B2/B3 真实重建/GLB/缓存。静态契约已定义，但真实资产发布、年龄方向与 UV 纹理仍需对应实现和验收。资产状态见 [模型台账](../docs/model-assets.md)。

服务资源通过 [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/) 创建和关闭；图像校验使用 [Pillow Image](https://pillow.readthedocs.io/en/stable/reference/Image.html)。实际验证证据与剩余事项见 [本批开发记录](../docs/后端开发记录.md)。
