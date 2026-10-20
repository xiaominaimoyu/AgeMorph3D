# AgeMorph3D 本地后端

本地 FastAPI 服务已实现 v1.2、模型生命周期、B2/B3 静态 GLB 和 B6 实时框/五点/纯旋转。**现有研究清单仍为 unresolved，正式服务保持许可错误，完整 G1/G2 尚未签收。** 真实 CPU、实体摄像头、Chrome/Edge 及合成传输证据分别见 [B23 记录](../docs/B23真实静态链路开发记录.md) 和 [B6 记录](../docs/B6实时姿态开发记录.md)。年龄能力尚未实现。

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

另一个终端从 `frontend/` 执行 `npm run dev`，在页面中连接本地服务。默认无模型配置时各项为 `missing`；检测与重建均严格就绪才开放静态重建和实时检测。现有研究清单得到许可错误，入口仍禁用；年龄能力保持禁用。模型就绪后，勾选本地处理同意、切换摄像头、开启摄像头，再连接实时检测；停止、切换来源或离开页面会释放资源。

## 配置模型生命周期

模型清单路径可从环境变量指定，不根据同名权重文件自动就绪：

```powershell
$env:AGEMORPH_DETECTOR_MANIFEST = 'D:\project file\AgeMorph3D\data\models\yolov5n05-face\manifest.json'
$env:AGEMORPH_RECONSTRUCTOR_MANIFEST = 'D:\project file\AgeMorph3D\data\models\3ddfa-v2\manifest.json'
.\.venv\Scripts\python.exe -m agemorph3d
```

加载需要先 `uv sync --locked --extra inference`。未配置/清单不存在为 `missing`，已配置先 `loading`，严格资产核验、实例构造和真实 CPU 算子自检通过才为 `ready`；失败为脱敏 `error`。现有两份 B0 研究清单仍为 `license_status=unresolved`，使用上面的路径会得到许可核验错误，服务不会偷偷启用研究绕过。用户提供的 BFM 非商业研究授权保留在台账中，这不是整套候选资产的分发条款证明。

单个模型 `ready` 表示该算子通过加载/自检，重建自检还包含 canonical/纯旋转/GLB 构建。两模型均ready且服务未关闭时，reconstruction与realtime为true，两项年龄能力仍false。加载、HTTP和WS共用一个工作线程；忙时不排队，HTTP429/WS相关BUSY，健康状态可读取。退出先禁止新任务和迟到发布，再清除缓存、等待实际线程完成并清理实例。

## 运行本机真实静态研究样例

从项目根目录执行，输出目录须为新的结果目录；原有文件不会覆盖：

```powershell
.\backend\.venv\Scripts\python.exe -m agemorph3d.static_probe --detector-manifest data/models/yolov5n05-face/manifest.json --reconstructor-manifest data/models/3ddfa-v2/manifest.json --image data/samples/astronaut.png --output-dir output/backend/b23/repro-static --research-allow-unresolved
```

该显式研究开关只作用于离线CLI，服务不接受它。成功输出mesh.glb、result.json和report.json，报告保留license_verified=false、service_ready=false、g1_complete=false；默认不带开关则严格拒绝现有清单。`--source-age` 仅接受明确的用户年龄，示例省略为unknown。输出是裁剪的开放脸部表面，身份/表情已应用，没有UV、纹理或年龄形变。高度归一化为1、Y向上、正面+Z，实际人体米制尺度未标定。

可使用既有查看器执行本机Chrome/Edge加载、导出和再导入检查：

```powershell
$env:AGEMORPH_RESEARCH_MESH = (Resolve-Path output/backend/b23/repro-static/mesh.glb).Path
$env:AGEMORPH_RESEARCH_RESULT = (Resolve-Path output/backend/b23/repro-static/result.json).Path
Set-Location frontend
node tests/static-mesh-research.mjs
```

脚本独占本机5175/18003、自动关闭服务器，输出到output/backend/b23/browser。它不提供健康/重建接口，不连接正式模型服务；使用软件WebGL，不替代 G1或实体相机验收。

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
| 工作线程 | 模型加载/自检、解码、推理和GLB编码共用单个活跃任务，无等待队列，忙时429；HTTP正文接收与处理共享25秒预算，WS处理6秒 |
| 取消/超时 | 调用方停止等待后仍占用实际运行任务的槽位，直至线程完成；不发布迟到GLB，发布前核对绝对截止时间；不承诺中断原生算子 |
| 资产 | 随机128位ID；内存TTL/LRU缓存，默认30分钟/512MiB/128项，单项64MiB；读取租约保护活跃响应，过期/淘汰/重启后404；不挂载磁盘目录 |

缓存配置为 `AGEMORPH_ASSET_TTL_SECONDS`、`AGEMORPH_ASSET_MAX_BYTES` 和 `AGEMORPH_ASSET_MAX_ENTRIES`，均需正数，容量/项数必须整数。原图和成功派生网格只在有界内存中保留；不存在网格临时文件或磁盘重启清理任务。关闭清除缓存，旧ID失效。满时仅淘汰未固定的LRU项，容量被读取固定时429；新读取不得获取过期项，已开始的读取可正常完成。

HTTP错误提供字符串detail和稳定code，禁止缓存且不回显照片/文件名/完整参数。WS成功为带seq的face_state，NO_FACE/MULTI_FACE/BUSY清除旧叠加后可继续；其他错误先回复再关闭。视频与叠加同时镜像，JPEG保持原方向，三维显示旋转使用S R S；t为未标定的0。逐帧不生成GLB/资产或年龄几何。流水发送会关闭而不排队，断开丢弃结果。工作与成功发送共享6秒绝对预算，发送另限1秒，错误发送/关闭各限1秒；发送超时不重复确认，详情见接口文档。

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

`test_static_mesh.py`、`test_asset_cache.py`、`test_static_api.py`、`test_static_probe.py` 覆盖本轮几何、GLB、TTL/LRU/租约、成功接口、断开/取消/超时/关闭及独立研究路径。自动化适配器为合成夹具，真实权重和浏览器证据另见 B23 记录。

`test_realtime.py` 验证像素、五点、SVD旋转及失败脱敏；`test_realtime_api.py` 验证逐帧成功/恢复、HTTP/WS共享单飞、流水拒绝、断开/超时/关闭后的槽位与迟到结果；`test_realtime_probe.py` 验证独立研究CLI的严格许可、边界和相机释放。测试夹具不代表真实权重或G2。

本机独立真实研究复现（从项目根目录运行，输出文件必须不存在）：

```powershell
.\backend\.venv\Scripts\python.exe -m agemorph3d.realtime_probe --detector-manifest data/models/yolov5n05-face/manifest.json --reconstructor-manifest data/models/3ddfa-v2/manifest.json --camera-index 0 --frame-count 30 --output output/backend/b6/repro-camera.json --research-allow-unresolved
```

相机会短暂开启，帧仅在内存处理；不打开窗口/网络服务，不保存照片或逐帧参数，只写计数、尺寸、数值检查与耗时汇总。用`--image data/samples/astronaut.png`替换`--camera-index 0`可复验公开样例；帧数1—120，最长边640。相机循环15秒预算在原生调用间检查，不能硬中断阻塞的驱动read。默认不带研究开关则严格拒绝当前清单，报告始终service_ready=false、g2_complete=false。

后续先收口候选权重条款及严格真实服务G1/G2，补人工左右转头/姿态质量和长时间恢复记录。年龄方向与UV纹理需B4/B5分别验收。参见 [后端计划](../docs/后端任务计划.md) 与 [模型台账](../docs/model-assets.md)。

服务资源通过 [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/) 创建和关闭；图像校验使用 [Pillow Image](https://pillow.readthedocs.io/en/stable/reference/Image.html)。实际验证证据与剩余事项见 [本批开发记录](../docs/后端开发记录.md)。
