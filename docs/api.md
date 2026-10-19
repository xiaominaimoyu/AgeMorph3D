# 前端与本地后端接口契约 v1.2

更新日期：2026-10-19。B1 已接入严格模型加载/CPU 自检及生命周期，冻结显式静态成功结果、结果级能力和源年龄。前端已具备对应的静态加载/导出路径；服务端成功重建、GLB 发布及实时/年龄推理仍待 B2/B3/B6/B4/B5，不能把契约示例或浏览器夹具当作真实 G1。

## 地址与数据边界

默认服务根地址：`http://127.0.0.1:8000`。协议限 `http`/`https`，主机限 `localhost`、`127.0.0.1`、`[::1]`；不得包含账号、路径、查询参数或片段。前端开发服务与 API 可能端口不同，后端应只为实际使用的本地前端来源配置 CORS。

用户照片、摄像头帧和推理输出不发送到云端，不写入前端持久存储。健康检查仅表示服务/模型状态；HTTP 成功不能单独证明模型已加载。服务应区分演示/真实模式和可用能力。

## HTTP

| 方法 | 路径 | 请求 | 响应用途 |
|---|---|---|---|
| GET | `/api/health` | 无 | `{models, device, version, api_version: "1.2", capabilities}` |
| POST | `/api/reconstruct` | `multipart/form-data`，图片字段 `image`，可选 `source_age` | `{mesh_id, topology_id, asset_mode, capabilities, source_age, shape, expr, pose, texture_url?}` |
| POST | `/api/aging` | JSON，含 `mesh_id`、`age` | `{shape_aged, texture_url?}` |
| GET | `/api/assets/{mesh_id}/mesh.glb` | 无 | 自包含 GLB，详见下文 |
| POST | `/api/export/gltf` | 当前模型与年龄 | 后端导出预留；前端本身支持本地 GLB 导出 |
| POST | `/api/export/image` | 当前模型与年龄 | 后端导出预留；前端本身支持 PNG 截图 |

`age` 为 20—70 范围内数值。参数字段以 `shape`、`expr`、`shape_aged` 为规范名称，旧文档的 `beta`、`psi` 不应作为第二套新协议继续扩展。参数数组必须非空、最多 300 个有限数值，维度由对应模型定义；当前前端校验和保留数组，但不会据此重建几何。

`/api/health` 的 `models` 固定列出 `detector`、`reconstructor`、`age_shape`、`age_texture`。每项为 `{state, backend, provider, detail}`，`state` 取 `missing/loading/ready/error`，`backend/provider` 为字符串或 `null`，`detail` 为脱敏可读原因。HTTP 200 表示服务存活，不表示推理可用。

服务在 lifespan 内创建单个 Runtime：未配置模型或配置清单不存在为 `missing`；已配置时先 `loading`，在同一个工作线程内严格核验条款、文件哈希、实例和 CPU 算子。全部通过才为对应模型 `ready`，依赖/条款/完整性/加载/自检失败为 `error`。部分模型失败不覆盖其他模型的状态。无推理依赖也可启动无模型服务。当前未接年龄模型，两项仍为 `missing`。

`capabilities` 完整提供四个布尔字段：`reconstruction`、`age_morph`、`age_texture`、`realtime`。B1 尚无成功资产发布或实时链路，因此四项仍为 `false`，即使单个算子模型已 `ready` 也不开放对应端点。前端接受 v1.1/v1.2 健康声明；版本未知、能力缺失或类型非法时禁用推理，不根据模型键名猜测能力。真实加载中的健康状态可观察；关闭先取消就绪状态，再等实际线程完成并释放实例。`device: cpu` 不表示已验证 GPU 不可用。

`source_age` 请求字段省略时为未知；提供时必须是最长32字符的 ASCII 普通十进制文本，数值在20—70之间，如 `42.5`。不接受布尔、科学计数法、非有限值、空值或任意其他表单字段。合法请求在 B1 仍返回 `503 MODEL_NOT_READY`，不产生重建结果。`LocalApi.reconstruct(file, signal?, sourceAge?)` 已可显式发送源年龄，当前界面尚无源年龄输入控件，默认省略；演示目标年龄不会被当作照片源年龄。

重建结果示例（数组维度只作格式示意，真实后端使用模型定义的维度）：

```json
{
  "mesh_id": "subject-session-opaque-id",
  "topology_id": "bfm-noneck-v3-topology-id",
  "asset_mode": "static",
  "capabilities": { "age_morph": false, "age_texture": false },
  "source_age": { "value": null, "method": "unknown", "calibration_id": null },
  "shape": [0],
  "expr": [0],
  "pose": { "R": [1, 0, 0, 0, 1, 0, 0, 0, 1], "t": [0, 0, 0] }
}
```

`mesh_id` 最长 100 字符，首位为字母或数字，其余只允许字母、数字、下划线和短横线。前端从该标识构造 GLB 路径，不接受任意 `model_url`。可选 `texture_url` 必须与当前本地 API 同源且位于 `/api/assets/` 下。旋转矩阵 `R` 为行优先的 9 个数值，平移 `t` 为 3 个数值。

成功结果的四个新增字段均必填：`topology_id` 与 mesh_id 使用相同标识语法，表示后端固定的拓扑/顶点序版本；实际与 GLB/基哈希的对应验证留待 B2/B3。`asset_mode` 仅为 `static | age_morph`，结果 `capabilities` 必须含两个布尔 `age_morph/age_texture`，全局能力不能替代本次结果能力。

`source_age.value` 为有限的20—70数值或 `null`，`method` 为 `unknown | user | estimated`，`calibration_id` 为标识或 `null`，三个字段均必填。`unknown` 必须两个值都为 null；`user` 必须有值且校准标识为 null；`estimated` 必须有值及非空校准标识，不能用没有依据的默认年龄代替估计器。校准标识本身不是质量证明。

`static` 必须 `age_morph=false`；`age_morph` 模式必须 `age_morph=true` 且源年龄已知。纹理能力独立于形状，`age_texture=true` 还要求已知源年龄及有效基础 `texture_url`，其真实可用性与年尺度仍需 B5 验收。缺少新字段的旧成功响应被明确拒绝，不自动猜静态。未知源年龄不显示为30/45岁，静态原始结果不带虚构年龄标签。

图片仅接受非空 JPG、PNG、WebP，最大 10 MiB、1600 万像素。JSON 请求超时为 30 秒、响应最大 128 KiB；前端不发送凭证、不缓存照片响应、不跟随重定向。HTTP 错误消息使用 FastAPI 常见的 `{ "detail": "可读说明" }` 格式。

接口对应代码为 `frontend/src/contracts.ts`、`frontend/src/services.ts` 以及 `backend/src/agemorph3d/`；首批契约测试位于 `backend/tests/`。合法图片和年龄请求当前返回503，资产路由返回404，两个服务端导出预留路由尚未实现。

## 当前可接入的三维资产

v1.2 仅接收**自包含 GLB**。`static` 接收没有 morph target 的原始静态网格；`age_morph` 仍严格要求年龄目标。不要依赖远程纹理、外部 buffer、未配置的压缩解码器或浏览器侧下载模型权重。

- `age_morph` 的 morph target 必须以 `age_20`、`age_45`、`age_70` 命名；前端将目标年龄映射到相邻两档并线性插值。缺失、损坏或用静态模式加载带 morph 的年龄网格均拒绝，不静默降级。
- 三个 target 与基准网格顶点编号、数量和拓扑一致。位移是相对基准网格的偏移。
- 后端返回的 GLB 必须已经应用该次重建的身份形状和表情；当前前端不会根据 `shape/expr` 数组和形状基重算网格。
- 坐标系统采用右手 Y-up、面向 +Z；单位和姿态缩放应由后端统一，避免把毫米平移直接用于米制网格。
- 接收静态 Mesh，不支持 SkinnedMesh；总顶点不超过 150 万。模型加载后居中，最大包围盒边长归一化为视口单位 2.8。实时姿态应用 `R` 旋转，`t` 仅保存为元数据，等待后端完成相机和尺度标定。
- GLB 最大 64 MiB；独立纹理最大 16 MiB、1600 万像素；加载最长 30 秒，取消、切换示例和销毁视口会中止未完成请求。资产请求也禁止凭证和重定向。
- 重建返回的 `texture_url` 作为基础纹理，同时用于目标与基准模型；`/api/aging` 纹理仅覆盖目标模型，改变目标年龄后恢复基础纹理。
- 当前前端可以展示演示网格、导出它，并接收符合约定的真实 GLB。加载失败应明确显示错误，不能将演示网格当作本次真实重建结果。

纯静态结果显示“原始重建，年龄变换不可用”，禁用年龄、预设、重置及年龄对照。若未来只有纹理能力可用，可选择纹理目标年龄，但不声明几何变化。静态导出名含 `original`，GLB 来源保留 `asset_mode/source_age/topology_id`，不写 `age/ageAnchors/displayAge`；已应用年龄纹理时另记 `texture_age`。年龄模式重置和对照采用已知源年龄，演示仍为30岁。静态夹具浏览器测试不证明真实照片 G1。

旧技术文档中的 `manifest.json` + `morph/*.bin` 管线属于后续扩展，**本轮不交付独立 manifest/位移加载器**。`shape/expr` 逐帧应用也需等形状基资产协议定义后再实施。

## WebSocket 实时帧

端点：`ws://127.0.0.1:8000/ws/frame`，与 HTTP 服务使用相同主机/端口；HTTPS 地址使用 `wss`。客户端发送 JPEG 二进制帧（最长边 640 像素，质量 0.7），发送频率上限 10 FPS，服务端返回 JSON。拍照上传最长边为 1280 像素。

```json
{
  "type": "face_state",
  "seq": 1,
  "ts": 0,
  "bbox": [120, 80, 200, 220],
  "landmarks": [[160, 150], [240, 150], [200, 190], [175, 230], [225, 230]],
  "pose": { "R": [1, 0, 0, 0, 1, 0, 0, 0, 1], "t": [0, 0, 0] },
  "conf": 0.99
}
```

`bbox` 为 `[x, y, width, height]`，关键点坐标位于发送图像像素坐标系中，顺序为左眼、右眼、鼻尖、左嘴角、右嘴角。预览镜像和画布缩放必须同时映射叠加坐标，不能只镜像视频。

当前前端实时接入支持框、关键点和姿态；`shape/expr` 不用于逐帧生成新几何。摄像头尚未连接服务时仅显示本地预览，不显示伪造的检测框或识别置信度。

客户端限制每条服务端文本消息不超过 1024 字节；这个限制不适用于发送的 JPEG 图像和一次性资产。采用单飞策略，只保留一个等待回复的帧，按 `seq` 忽略过期结果，避免慢推理积压视频帧。连接或单帧等待超过 8 秒会停止连接，由用户手动重新连接，不在后台反复重试。10 FPS 是传帧上限，不是三维画布渲染帧率。

服务还可发送 `{ "type": "status", "device": "cpu", "fps": 8.5 }`；`fps` 可省略。状态消息不能替代帧回复，收到 `face_state` 或 `error` 才确认当前帧已处理。

本批接入实现要求WS有白名单Origin和回环Host；输入只接受≤2 MiB、最长边≤640的JPEG二进制帧。连接先收到`status`，有效帧收到一次`MODEL_NOT_READY`错误后以1013关闭；坏帧收到错误后以1003关闭。客户端不会得到伪造框点。成功`face_state`、可恢复无人脸/多人脸推理留待B6；示例不是当前算法输出。

## 错误与状态

```json
{ "type": "error", "code": "NO_FACE", "msg": "未检测到人脸，请使用清晰的正面照片。" }
```

错误码至少包含 `NO_FACE`、`MULTI_FACE`、`TIMEOUT`、`BAD_INPUT`、`MODEL_NOT_READY`。HTTP 使用对应失败状态码并提供可读消息；WebSocket 使用 `error` 消息。用户取消、网络失败、响应格式错误和资产加载失败需要有不同处理，不应统一转成成功演示。

HTTP错误响应为`{"detail":"可读说明","code":"稳定错误码"}`。本批使用400坏图/坏multipart、403来源或Host拒绝、413超限、415格式不支持、422字段无效、429忙、503模型未就绪、504超时；JSON和实际流入字节均受限。忙时带`Retry-After: 1`。HTTP响应禁止缓存。推理成功、资源发布/TTL、真实摄像头尺寸映射和GLB导出再导入检查仍待后续阶段。
