# AgeMorph3D 本地后端

本地 FastAPI 服务已实现 v1.2 契约、模型生命周期及 B2/B3 照片到静态 GLB 链路。检测/重建模型严格加载与自检通过后，可返回单人 canonical 网格和有界缓存中的 GLB。**现有研究清单仍为 unresolved，配置它们仍返回503，尚未通过真实服务 G1。** 真实 CPU 离线生成和 Chrome/Edge 网格往返已验证，见 [B23 开发记录](../docs/B23真实静态链路开发记录.md)。实时和年龄推理仍待实现。

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

另一个终端从 `frontend/` 执行 `npm run dev`，在页面中连接本地服务。默认无模型配置时各项为 `missing`；配置后状态来自真实核验/加载/自检。只有检测与重建均就绪才开放静态重建；现有研究清单得到许可错误，入口仍禁用。实时和年龄能力保持禁用，演示模式可单独使用。

## 配置模型生命周期

模型清单路径可从环境变量指定，不根据同名权重文件自动就绪：

```powershell
$env:AGEMORPH_DETECTOR_MANIFEST = 'D:\project file\AgeMorph3D\data\models\yolov5n05-face\manifest.json'
$env:AGEMORPH_RECONSTRUCTOR_MANIFEST = 'D:\project file\AgeMorph3D\data\models\3ddfa-v2\manifest.json'
.\.venv\Scripts\python.exe -m agemorph3d
```

加载需要先 `uv sync --locked --extra inference`。未配置/清单不存在为 `missing`，已配置先 `loading`，严格资产核验、实例构造和真实 CPU 算子自检通过才为 `ready`；失败为脱敏 `error`。现有两份 B0 研究清单仍为 `license_status=unresolved`，使用上面的路径会得到许可核验错误，服务不会偷偷启用研究绕过。用户提供的 BFM 非商业研究授权保留在台账中，这不是整套候选资产的分发条款证明。

单个模型 `ready` 表示该算子通过加载/自检，重建自检还包含 canonical/纯旋转/GLB 构建。B2/B3 仅在两模型均ready、服务未关闭时将 reconstruction能力置为true，其他三项保持false。加载与请求共用一个工作线程，加载期间其他处理返回429；健康接口可读取状态。初始化不承诺硬超时或中断底层算子；退出先禁止新任务和迟到发布，再清除缓存、等待实际线程完成并清理实例。

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

`test_static_mesh.py`、`test_asset_cache.py`、`test_static_api.py`、`test_static_probe.py` 覆盖本轮几何、GLB、TTL/LRU/租约、成功接口、断开/取消/超时/关闭及独立研究路径。自动化适配器为合成夹具，真实权重和浏览器证据另见 B23 记录。

下一步按 [后端计划](../docs/后端任务计划.md) 收口候选权重条款，在正式服务以获准照片完成 G1并补充不同身份/侧脸质量证据，再转 B6实体相机。年龄方向与 UV纹理仍需 B4/B5 对应实现和验收。资产状态见 [模型台账](../docs/model-assets.md)。

服务资源通过 [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/) 创建和关闭；图像校验使用 [Pillow Image](https://pillow.readthedocs.io/en/stable/reference/Image.html)。实际验证证据与剩余事项见 [本批开发记录](../docs/后端开发记录.md)。
