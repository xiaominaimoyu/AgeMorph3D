# AgeMorph3D 本地后端

第一批 B1 服务实现：FastAPI 能在没有模型时启动，并向前端准确报告不可用能力。**尚未接入真实检测、三维重建、年龄形状或年龄纹理模型**；合法推理请求返回 `503 MODEL_NOT_READY`，不会返回演示网格。B0 模型可行性、B2/B3 真实照片重建与 GLB 发布仍待实施。

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

另一个终端从 `frontend/` 执行 `npm run dev`，在页面中连接本地服务。连接成功后应看到各模型 `missing` 和能力不可用，重建、实时检测、年龄纹理操作保持禁用。演示模式仍可单独使用。

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
| Multipart | 只允许一个 `image` 文件；请求总量≤图片限额+64 KiB；原图在内存中解码并纠正 EXIF 方向，不落盘 |
| JSON | 请求体≤128 KiB；年龄为有限的 20—70 数值，不接受字符串或布尔值；未知字段拒绝 |
| 实时帧 | 仅二进制 JPEG，≤2 MiB，最长边≤640；服务回复≤1024 UTF-8 字节 |
| 工作线程 | 当前用于图片校验，单个活跃任务、无等待队列，忙时429；HTTP正文接收与处理共享25秒预算，WS处理6秒 |
| 取消/超时 | 调用方停止等待后仍占用实际运行任务的槽位，直至线程完成；不承诺中断已执行的算子 |
| 资产 | 不挂载磁盘目录，当前所有网格ID返回404；GLB发布、TTL和容量缓存留待B2/B3/B7 |

HTTP 错误统一提供字符串 `detail` 和稳定 `code`。API与输入错误不回显原图、文件名或完整参数。HTTP 响应设置 `Cache-Control: no-store`。WS 坏帧和模型缺失会先发送一次终结 `error`，再关闭连接；没有实现成功 `face_state` 推理。

OpenAPI JSON 位于 `/openapi.json`；本批关闭需要外部 CDN 的 Swagger/ReDoc 页面。完整协议见 [接口文档](../docs/api.md)。

## 验证与后续开发

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check src tests
.\.venv\Scripts\ruff.exe format --check src tests
```

测试只在测试目录中构造图片，不使用真实人物照片或权重。`test_inputs.py` 验证解码、schema 和配置，`test_api.py` 验证 HTTP/WS 契约，`test_runtime.py` 验证并发、超时和取消后的真实槽位生命周期。

下一步按 [后端计划](../docs/后端任务计划.md) 核验 YOLO 人脸权重及五点来源、3DDFA/BFM 与固定拓扑，接入实际算法后才能把相应能力设为可用。静态资产模式、GLB编码、源年龄、年龄方向与UV纹理均不能靠将健康状态改为 `ready` 完成。资产状态见 [模型台账](../docs/model-assets.md)。

服务资源通过 [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/) 创建和关闭；图像校验使用 [Pillow Image](https://pillow.readthedocs.io/en/stable/reference/Image.html)。实际验证证据与剩余事项见 [本批开发记录](../docs/后端开发记录.md)。
