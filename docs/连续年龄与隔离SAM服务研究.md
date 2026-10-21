# 连续年龄与隔离 SAM 服务研究

2026-10-21。对应六阶段表格第5项，即后续计划 N5/N6。完成连续显示策略、数值研究、独立常驻 SAM worker，以及有界会话与前后端合成契约。生产 `/api/aging` 仍为 `503 MODEL_NOT_READY`；本批没有真实 SAM→目标重建→遮挡审核→UV→生产响应的端到端服务，不将2D生成图直接用作年龄纹理。

机器协议见 [age-continuity-service-v1.json](age-continuity-service-v1.json)。N3仍选择静态形状回退；N4的纹理视觉质量、身份和许可欠项继续保留。第6项G3分项验收尚未完成。

本批输入、源码与产物校验及分项状态汇总见 [verification.json](../output/research/age-stage5-20261021/verification.json)。

## 年龄与原始资产策略

源龄保留20—70内的有限小数值，未知保持null。服务会话中未知源龄不能请求绝对年龄；整数SAM条件与显示插值分开。`target == source`先于整数检查，直接返回原始GLB、PNG和形状系数对象，不把SAM同龄图替换为原始结果。其他小数目标明确拒绝，不取整、不夹取、不给默认源龄。小数源龄的SAM几何差分仍不受支持。

数值显示工具允许在实际已有的相邻年龄锚点间插值，超出覆盖范围拒绝外推。若具备真实源纹理，可加入精确源龄锚点，并与20/45/70重合项去重。本轮真实N4输入只有生成图atlas，10个源的原始纹理重置资产未传入探针，均明确标记missing；原始源龄42.5的精确字节恢复由合成契约测试验证，不能当作10个真实源的纹理重置验收。

实现见 [age_continuity.py](../backend/src/agemorph3d/age_continuity.py)。形状沿用静态回退；纹理显示实验先把sRGB解码到线性光，再插值预乘RGB与alpha。只有一端支持的区域按alpha淡出，两端均未知仍为RGBA零，不填补颜色。浮点混合需要单独BLEND显示链；当前查看器没有这项插值实现，原N4资产仍是二值alpha、MASK/0.5。

## N5数值证据

主报告：[continuity/report.json](../output/research/age-stage5-20261021/continuity/report.json)。37张atlas、10个源、27个相邻区间全部通过输入和数组检查；27/27区间的可见支持域变化，每段XOR为111—1224 texels，Jaccard为0.9364717—0.9933636。阈值中点左右各0.001岁时，浮点及uint8 MASK可见性翻转数都等于该段XOR，不能用共同可见区域颜色连续掩盖这些区域的出现/消失。

296个锚点邻域请求中216个在覆盖内，80个在边界外并保留为outside_anchor_coverage。步长1、0.1、0.01、0.001岁各54个有效请求；最大黑背景合成通道RMS依次约0.0026537、0.00026537、0.000026537、0.0000026537，白背景依次约0.0114905、0.00114905、0.000114905、0.0000114905。浮点左右极限收敛不等于MASK渲染连续。最大量化合成通道误差约0.00414738，不作为视觉质量阈值。

27个区间各有一个小数显示探针，27次直接SAM小数条件全部拒绝。另按冻结协议的10个固定目标年龄对10个源执行100例补充网格，30例为整数条件、70例小数直接条件被拒绝；结果见 [fixed-age-grid.json](../output/research/age-stage5-20261021/fixed-age-grid.json)。这些是已有生成atlas的显示计算，未知源龄并未因此获得API能力。

独立复核从PNG alpha重新计算全部27段XOR/Jaccard，并核对阈值翻转数，全部一致，见 [independent-continuity-audit.json](../output/research/age-stage5-20261021/independent-continuity-audit.json)。本批未打开保留组年龄结果、未训练、未增加校准身份。

## N6 worker与会话契约

[SAM父端](../backend/src/agemorph3d/sam_worker.py)不导入torch，使用独立环境启动[常驻worker](../tools/sam_worker.py)。通信仅为本机stdio：4字节大端长度+JSON/base64，帧最大8MiB、对齐PNG最大1MiB、仅256×256单帧RGB输入、输出1024×1024生成PNG。stdout只用于协议，stderr持续排空且最多保留64KiB尾部。输入、输出SHA-256、请求ID、整数年龄、PID和加载次数均校验。

worker在反序列化前核验已知checkpoint的2,270,547,237字节和完整SHA-256，并核验loader/native shim。实际构建模型、有限值前向自检后仅报告`research_loaded`，始终`research_only=true, service_ready=false`。模型构建一次，上游pSp启动流程读取checkpoint两次；报告不把“常驻模型一次”写成“文件只读一次”。未提供下载、训练或生产许可绕过。

单飞、超时和取消按实际任务管理：调用者停止等待后，处理槽仍占用。两层processor必须在finally中`await worker.wait_idle()`，防止父端请求超时先结束而会话租约提前释放。CUDA设备锁在同一workspace的客户端间排他，并持有至实际worker和Windows虚拟环境启动器都退出；它不管理其他应用的GPU使用。关闭先拒绝新任务、排空或终止自己拥有的worker，再完成coordinator drain，不能只等挂起的coordinator后才关闭worker。

[会话缓存](../backend/src/agemorph3d/aging_sessions.py)保存不可变原始RGB、对齐PNG、拟合/对齐序列化上下文、原始GLB/PNG、源龄来源及系数；序列化上下文的模型/坐标/UV验证由未来真实processor负责，本批不提供未经质量验收的真实processor。默认128MiB、16个会话、固定300秒TTL。原始和所有派生字节及float64系数均计预算，Python对象开销额外存在。访问和派生结果不续期，派生结果随原会话到期；LRU只淘汰未固定会话。

启动coordinator后每秒清理空闲过期会话。过期/关闭中的在途上下文拒绝新借用、继续计预算，直到实际任务/响应租约结束；这表示释放缓存所有权，不承诺操作系统内存安全擦除。超时、取消、失败或执行中到期不发布迟到结果，过期后可重新重建。worker通信与上下文库不把私人图像落盘，离线probe的输出文件属于显式研究产物。

## 实际运行与合成联调

真实worker报告：[sam-worker-cpu/report.json](../output/research/age-stage5-20261021/sam-worker-cpu/report.json)。现场GPU0已占7065/8151MiB，本批没有停止原有应用，改用CPU和2线程；本轮没有复验真实CUDA前向或显存峰值。使用既有official-866对齐图、45整数条件，实际worker PID31796、启动器34736，模型构建一次；两次PNG SHA-256均为`ad675924ab07656173137f569267eeb5c8678bcf54bdf190b6152985d7d51031`。模型加载约6.109秒，自检约4.602秒，总启动约23.097秒；两次前向约4.138/3.366秒，往返约4.660/3.517秒。两个进程正常退出码0，未强制终止；CPU的`peak_vram_bytes=0`不代表测量了CUDA资源释放。

前后端使用[显式合成factory](../backend/tests/fixtures/aging_contract_app.py)与[浏览器脚本](../frontend/tests/aging-session-contract.mjs)，只接收内置合成PNG，生产factory不读取合成开关。实际LocalApi/FaceViewer在Chrome/Edge中加载静态三角形、请求/缓存整数目标、42.5源龄恢复、拒绝42.6直接生成、取消后保持pin/BUSY、过期后重建，并导出纹理再读回比较RGBA SHA-256。它证明接口与资源传输，不证明真实人脸或身份/年龄质量。

生产探测继续返回503，年龄形状/纹理能力均false。生产API仍为v1.2，没有新增生产PNG路由；测试factory的`base.png`和`age-NNN.png`与会话同TTL，资产发送期间持有租约。`shape_aged`仅为既有客户端契约字段，当前查看器不据此重算几何。SAM输出仍须目标自身重建、遮挡策略、共同UV注册与质量/许可出口，方可成为真实年龄纹理。

自动化检查：后端1156项通过（1条既有Starlette/httpx弃用警告），前端47项通过，TypeScript/Vite构建通过。后端新增46项连续性/探针、40项worker与两层超时、23项会话/合成契约测试。Ruff使用显式`backend/pyproject.toml`配置。首轮Chrome/Edge 2/2通过；交叉审查后将测试服务清理改为Windows父进程句柄监视、不依赖HTTP在线，并在新冻结后复跑2/2通过，见[最终浏览器报告](../output/research/age-stage5-20261021/synthetic-browser-final/aging-session-contract.json)。两轮共4次真实浏览器均无pageerror和外部请求，最终配置以复跑为准。原SAM worker/启动器、两轮测试服务实际进程与启动器均已退出，5177/18007均无监听，见[资源核验](../output/research/age-stage5-20261021/resource-audit.json)。

## 冻结、复现与剩余出口

输入选择先冻结117个pin；N5运行前冻结123个输入/源码pin，worker运行前冻结55个输入/源码pin，首轮浏览器运行前冻结15个pin。此前已查看全部N4开发atlas和27段支持域统计，不能称盲测。一次手录错误的报告hash被前置校验拒绝，未生成结果，记录在preflight-correction.log。新epsilon/量化统计按冻结策略执行；固定年龄网格和独立alpha复核单列。源码快照与各冻结文件均留在[本批输出目录](../output/research/age-stage5-20261021)。浏览器清理分支在首轮通过后接受交叉审查修复，后续冻结和复跑单列，不改写首次记录。

```powershell
.\backend\.venv\Scripts\python.exe tools/age_continuity_probe.py `
  --registration-sha256 60bd2dd94c818011ac7fec6f257b4191d67abe47b9c2323e5eb5e86be2d1eba8 `
  --study-plan output/research/age-stage5-20261021/continuity-plan.json `
  --output-dir output/research/age-stage5-reproduction/continuity

# 独立100例固定网格补充；该辅助脚本在首轮结果后存档，复算字节一致。
# 主CLI不会自动生成这一补充报告。
.\backend\.venv\Scripts\python.exe output/research/age-stage5-20261021/fixed-grid-reproduction.py `
  --output output/research/age-stage5-reproduction/fixed-age-grid.json

$env:OMP_NUM_THREADS='2'
$env:MKL_NUM_THREADS='2'
.\backend\.venv\Scripts\python.exe -B tools/sam_worker_probe.py `
  --image output/research/ffhq-bridge-20261020/official-866/aligned.png `
  --target-age 45 --device cpu --research-allow-unresolved `
  --startup-timeout-s 120 --request-timeout-s 120 --shutdown-timeout-s 15 `
  --output-dir output/research/age-stage5-reproduction/sam-worker-cpu

$env:AGEMORPH_CONTRACT_OUTPUT=Join-Path (Get-Location) 'output/research/age-stage5-reproduction/browser'
Set-Location frontend
node tests/aging-session-contract.mjs
```

这些命令依赖本机已有、被Git忽略的研究资产和冻结文件，不是可重新分发的数据包。研究产物、权重、模型环境与截图不进入Git。

当前可以交付N5/N6研究工程与合成契约。真实原始源纹理重置的逐图证据、完整渲染连续性、真实年龄UV服务、CUDA本轮设备证据、形状/纹理/身份质量和条款仍有欠项；G3各分项继续未签收。下一步按表格第6项逐项核验，只有满足对应出口才开放能力。
