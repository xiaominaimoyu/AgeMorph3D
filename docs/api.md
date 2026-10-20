# 前端与本地后端接口契约 v1.2

更新日期：2026-10-20。B2/B3 静态链路及 B6 实时框、五点、纯旋转、可恢复错误和资源释放均已实现，继续使用 v1.2。现有研究清单仍为 unresolved，正式服务加载失败；真实 CPU 与实体相机研究、浏览器及传输证据分别见 [B23 记录](B23真实静态链路开发记录.md) 和 [B6 记录](B6实时姿态开发记录.md)。完整 G1/G2 尚未签收；年龄能力仍待 B4/B5。

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

服务在 lifespan 内创建单个 Runtime：未配置模型或配置清单不存在为 `missing`；已配置时先 `loading`，在同一个工作线程内严格核验条款、文件哈希、实例和 CPU 算子。重建自检还执行 canonical/纯旋转/GLB 构建。全部通过才为对应模型 `ready`，依赖/条款/完整性/加载/自检失败为 `error`。部分模型失败不覆盖其他模型的状态。无推理依赖也可启动无模型服务。当前未接年龄模型，两项仍为 `missing`。

`capabilities` 完整提供四个布尔字段：`reconstruction`、`age_morph`、`age_texture`、`realtime`。检测与重建两模型均严格加载/自检通过且服务未关闭时，`reconstruction` 和 `realtime` 为 true；两项年龄能力仍 false。当前真实研究清单得到许可 error，实际四项仍 false，不能用独立研究成功替代严格加载。前端接受 v1.1/v1.2 健康声明；版本未知、能力缺失或类型非法时禁用推理，不根据模型键名猜测能力。关闭先取消就绪状态，再等实际线程完成并释放实例。`device: cpu` 不表示已验证 GPU 不可用。

`source_age` 请求字段省略时为未知；提供时必须是最长32字符的 ASCII 普通十进制文本，数值在20—70之间，如 `42.5`。不接受布尔、科学计数法、非有限值、空值或任意其他表单字段。合法图片先解码并纠正 EXIF，模型未就绪返回 `503 MODEL_NOT_READY`；就绪后仅单人继续重建，无脸/多人分别为422 `NO_FACE/MULTI_FACE`，不选择其中一人。成功返回200和已发布的静态资产标识。`LocalApi.reconstruct(file, signal?, sourceAge?)` 已可显式发送源年龄，当前界面尚无源年龄输入控件，默认省略；演示目标年龄不会被当作照片源年龄。

重建结果示例（数组维度只作格式示意，真实后端使用模型定义的维度）：

```json
{
  "mesh_id": "subject-session-opaque-id",
  "topology_id": "tddfa-bfm-canon-v1-cc449ed7efa2860bed64be0a7e29ad8944912148c69f938ff768c8766d65e7cb",
  "asset_mode": "static",
  "capabilities": { "age_morph": false, "age_texture": false },
  "source_age": { "value": null, "method": "unknown", "calibration_id": null },
  "shape": [0],
  "expr": [0],
  "pose": { "R": [1, 0, 0, 0, 1, 0, 0, 0, 1], "t": [0, 0, 0] }
}
```

`mesh_id` 最长 100 字符，首位为字母或数字，其余只允许字母、数字、下划线和短横线。前端从该标识构造 GLB 路径，不接受任意 `model_url`。可选 `texture_url` 必须与当前本地 API 同源且位于 `/api/assets/` 下。旋转矩阵 `R` 为行优先的 9 个数值，平移 `t` 为 3 个数值。

成功结果的四个新增字段均必填：`topology_id` 与 mesh_id 使用相同标识语法。当前 `tddfa-bfm-canon-v1-{source_topology_sha256}` 明确固定顶点/面顺序及逐面绕序反转；源哈希和转换写入 GLB 元数据。`asset_mode` 仅为 `static | age_morph`，结果 `capabilities` 必须含两个布尔 `age_morph/age_texture`，全局能力不能替代本次结果能力。B2/B3 只生成 static、两项结果能力 false、texture_url=null。

`source_age.value` 为有限的20—70数值或 `null`，`method` 为 `unknown | user | estimated`，`calibration_id` 为标识或 `null`，三个字段均必填。`unknown` 必须两个值都为 null；`user` 必须有值且校准标识为 null；`estimated` 必须有值及非空校准标识，不能用没有依据的默认年龄代替估计器。校准标识本身不是质量证明。

`static` 必须 `age_morph=false`；`age_morph` 模式必须 `age_morph=true` 且源年龄已知。纹理能力独立于形状，`age_texture=true` 还要求已知源年龄及有效基础 `texture_url`，其真实可用性与年尺度仍需 B5 验收。缺少新字段的旧成功响应被明确拒绝，不自动猜静态。未知源年龄不显示为30/45岁，静态原始结果不带虚构年龄标签。

图片仅接受非空 JPG、PNG、WebP，最大 10 MiB、1600 万像素。JSON 请求超时为 30 秒、响应最大 128 KiB；前端不发送凭证、不缓存照片响应、不跟随重定向。HTTP 错误消息使用 FastAPI 常见的 `{ "detail": "可读说明" }` 格式。

接口对应代码为 `frontend/src/contracts.ts`、`frontend/src/services.ts` 以及 `backend/src/agemorph3d/`。照片成功与缓存集成测试使用明确的合成适配器，真实 CPU 权重另经离线探针验证；两类证据不替代严格模型服务 G1。年龄请求仍503，两个服务端导出预留路由尚未实现。

## 静态几何、缓存与取消

3DDFA 的身份40维、表情10维已经应用在返回的38365顶点上，网格为裁剪的开放人脸表面。canonical 沿原始模型 X、Y向上、正面+Z，按 `q=(v-bbox_center)/bbox_height` 等比归一化。保存源中心、高度和尺度以便还原；顶点及面顺序保持，原始每面 `[a,b,c]` 固定改为 `[a,c,b]`，形成单面材质的外向法线。

这是一件高度为1的归一化展示物体。glTF标准按米解释容器中的线性单位，但本项目没有证明裁剪 BFM 的原始物理单位，不能由此推断真实人脸高1米或据此测量人体。GLB 的 `coordinate_metadata` 明确 `canonical_unit=dimensionless`、`source_units=unverified`、`metric_scale_verified=false`。姿态从投影3×3块通过 SVD/polar 获得正交旋转，显式拒绝反射/奇异块；不把尺度或剪切写入 R，不把图像平移冒充米制平移，t为三个0。该旋转未烘入 canonical 网格，HTTP前端也不再次施加它。

成功后分配128位随机资产ID（当前为32位小写十六进制）。`GET /api/assets/{mesh_id}/mesh.glb` 仅从登记的内存缓存读取，Content-Type为 `model/gltf-binary`，设置Content-Length和no-store；不挂载目录。默认TTL1800秒、总容量512MiB、最多128项、单项64MiB。TTL从发布开始、不因访问延长；满时淘汰未被读取固定的LRU项，无法容纳时429/BUSY。过期、淘汰、进程重启或未知ID返回404/ASSET_NOT_FOUND。

读取租约固定不可变字节，直到ASGI发送完成、失败或取消才释放；资产过期后拒绝新读取，已开始的读取可以完成。原图只短暂保留在有界内存，服务不写照片或派生网格临时文件。关闭清除缓存，新进程没有旧资产；生成失败、调用者取消、超时或观测到断开时不发布迟到资产。实际原生算子仍运行至结束，期间保持单工作线程忙状态。发布前再次核对HTTP绝对截止时间；已经观测到的断开以499/CANCELLED终结，不要求断开的浏览器收到它。

## 当前可接入的三维资产

v1.2 仅接收**自包含 GLB**。`static` 接收没有 morph target 的原始静态网格；`age_morph` 仍严格要求年龄目标。不要依赖远程纹理、外部 buffer、未配置的压缩解码器或浏览器侧下载模型权重。

- `age_morph` 的 morph target 必须以 `age_20`、`age_45`、`age_70` 命名；前端将目标年龄映射到相邻两档并线性插值。缺失、损坏或用静态模式加载带 morph 的年龄网格均拒绝，不静默降级。
- 三个 target 与基准网格顶点编号、数量和拓扑一致。位移是相对基准网格的偏移。
- 后端返回的 GLB 必须已经应用该次重建的身份形状和表情；当前前端不会根据 `shape/expr` 数组和形状基重算网格。
- 坐标系统采用右手 Y-up、面向 +Z；当前输出为明确标注的非米制人体测量网格，采用上文的统一归一化尺度；不能把原始图像平移当作空间米制平移。
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

`seq` 每连接从1开始，对服务实际消费的每个应用输入递增，成功和错误共用同一序列；`ts` 为服务组装成功回复时的 Unix 毫秒时间，并非曝光时间。`bbox=[x,y,width,height]` 使用纠正 EXIF 后、未镜像 JPEG 的像素坐标，x向右、y向下。五点保留检测器顺序：图像左眼、图像右眼、鼻尖、图像左嘴角、图像右嘴角；左右按图像定义。眼中心/眼角的精确定义和质量仍需另验。框位于输入内，五点可能落在图像外，保留有限的有符号坐标（绝对值≤16384），不静默裁点。

前端以该帧实际编码尺寸绘制，视频与叠加画布同时做水平镜像；发出的 JPEG 不镜像。纯旋转 R 从 3DDFA 原始投影通过 SVD/polar 提取，拒绝反射、奇异或病态矩阵，保留右手 Y-up、正面+Z。镜像预览的三维展示使用 `S R S`，`S=diag(-1,1,1)`；不把镜像反射直接作为 R。`t=[0,0,0]` 表示未估计米制平移。实时帧不生成/缓存GLB，不传完整shape/expr，也不更新网格身份或年龄。

当前前端实时接入支持框、关键点和姿态；`shape/expr` 不用于逐帧生成新几何。摄像头尚未连接服务时仅显示本地预览，不显示伪造的检测框或识别置信度。

双方限制每条服务端文本消息≤1024 UTF-8字节；这个限制不适用于 JPEG 和一次性资产。数值使用8位有效数字压缩，不重复传完整参数。客户端单飞，成功和错误均需匹配当前等待的序号；旧回复不解除等待，意外未来序号被拒绝。连接、编码或单帧等待超过8秒停止，由用户手动重连。10 FPS是传帧上限，不是模型吞吐或画布帧率。

服务还可发送 `{ "type": "status", "device": "cpu", "fps": 8.5 }`；`fps` 可省略。状态消息不能替代帧回复，收到 `face_state` 或 `error` 才确认当前帧已处理。

WS校验白名单Origin和回环Host，输入仅为≤2 MiB、最长边≤640的JPEG二进制。连接先收到status，每个已消费输入至多一条终结回复；连接已断开时丢弃结果，不承诺向消失的客户端确认。无人/多人分别为NO_FACE/MULTI_FACE；全局线程被HTTP或其他连接占用时为BUSY。这三项清除前端旧框/姿态，并允许同一连接继续。模型未就绪→MODEL_NOT_READY/1013；坏帧→相应输入错误/1003；处理超时→TIMEOUT/1013；模型失败→脱敏POSE_FAILED/1011；其他内部失败→INTERNAL_ERROR/1011。致命错误均先回复再关闭，除传输失败无法送达外。

服务器不排队推理。如果客户端在当前回复前流水发送第二帧，两个已消费序号各收到BUSY并以1013关闭；当前结果丢弃，其余尚未消费的协议缓冲不承诺逐帧JSON。工作与成功发送共享6秒绝对预算，成功发送另受1秒上限，错误发送/关闭各限1秒；调度到实际发送协程后再次核对剩余预算。发送尚未开始时过期可返回TIMEOUT；发送本身超时则送达状态未知，结束连接而不重复发送终结消息。断开/取消/超时不会提前释放原生CPU任务槽位。启动器禁用WS压缩，设置`ws_max_queue=1`；该队列选项适用于legacy websockets实现，当前Uvicorn自动选择的SansIO使用暂停/恢复读取背压，实际版本及双层限制见B6记录。

## 错误与状态

```json
{ "type": "error", "seq": 1, "code": "NO_FACE", "msg": "未检测到人脸，请正对摄像头并保持光线充足。" }
```

错误码至少包含 `NO_FACE`、`MULTI_FACE`、`TIMEOUT`、`BAD_INPUT`、`MODEL_NOT_READY`。HTTP 使用对应失败状态码并提供可读消息；WebSocket 使用 `error` 消息。用户取消、网络失败、响应格式错误和资产加载失败需要有不同处理，不应统一转成成功演示。

HTTP错误响应为`{"detail":"可读说明","code":"稳定错误码"}`。本批使用400坏图/坏multipart、403来源或Host拒绝、404资产不存在、413超限、415格式不支持、422字段无效或无人/多人、429忙、503模型未就绪、504超时，静态推理/几何失败为500/RECONSTRUCTION_FAILED；JSON和实际流入字节均受限。忙时带`Retry-After: 1`。HTTP响应禁止缓存。真实服务G1/G2仍需条款收口后的严格成功链路和人工质量验收；B6的实际设备、独立研究与合成测试证据分别记录。
