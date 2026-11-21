# AgeMorph3D 数据集方案 v3（按 Sentinel 第二轮复审修订）

仓库：https://github.com/xiaominaimoyu/AgeMorph3D （提交 35c0cd6）
核实日期：2026-11-15。文中“已核实”表示实际打开、下载或统计过；“估算”“未核实”的地方，后续要换成实测值。

## 1. 需求概要
- 项目性质：本科毕设，只用于研究（README.md 第 15 行）
- 流程：YOLO 检测 → 3DDFA_V2 拟合 BFM（40 个形状参数、10 个表情参数）→ 在形状空间里学“年龄方向”，覆盖 20—70 岁 → 导出 GLB（README.md 第 41、79 行；backend/src/agemorph3d/age_shape.py）。纹理直接用预训练 SAM，不重新训练。
- 核心数据需求：同一人有多个年龄段的照片，身份编号和年龄标签可信；70 岁端点要有精确标签；训练、验证、测试按身份划分（docs/数据资源清单.md 第 27 行；docs/模型与数据路线核验.md §3—4）
- 最低组合：WIDER FACE + AFLW2000-3D + FGNET（docs/数据资源清单.md 第 25 行）。AgeDB 必须从官网获取，镜像不能代替授权（同文件第 39、40、85 行）。

## 2. 最终组合

**A　AgeDB（主训练集）**
- 用途：学形状的年龄方向（同一人回归），提供源年龄锚点和 70 岁端点。
- 获取：官网 https://ibug.doc.ic.ac.uk/resources/agedb/ 。从 Dropbox 下载，解压密码需要发邮件申请。
- 规模：官方 16,488 张、568 人。下面是用 HF 镜像做的申请前参考统计，拿到官方包后要重新统计：
  - 20—70 岁 14,189 张；正好 70 岁 216 张；年龄跨度 ≥30 岁的有 495 人（全库 524 人）
  - 照片最短边 26—2232 像素，中位数 213；小于 128 像素的 2,096 张
  - 过滤口径一（最短边 ≥128 像素且年龄 20—70 岁）：12,388 张、566 人，跨度 ≥30 岁的 474 人，正好 70 岁 181 张
  - 过滤口径二（只要求最短边 ≥128 像素，Sentinel 复核）：14,392 张、567 人，跨度 ≥30 岁的 514 人
- 许可：仅限非商业研究。禁止复制、出版、分发标注或派生数据。
- 限制：名人照片偏差；分辨率低；AgeDB-30 是人脸识别常用的验证集，可能与身份评价器的训练数据重叠。

**B　IMDB-Clean（本期不采用）**
- 不采用的原因：IMDB-Clean 的人脸框是按原图坐标标的。要用它，必须下载官方 run_all.sh 里的原图 imdb_0..9.tar，合计约 269 GB，远超 41.5 GiB 的预算。
- 为什么不能拿 imdb_crop 代替（Sentinel 复核）：
  - IMDB-Clean 的 285,946 条样本里，有 23,242 条（约 8.1%）在 imdb_crop 中对应的原检测器没有检测到人脸；
  - 其余样本中，约 30.5% 的 imdb_crop 裁剪框与 IMDB-Clean 人脸框的 IoU 小于 0.1；
  - 两项合计，约 36% 的 IMDB-Clean 样本无法用 imdb_crop 正确对应。
- 退路（不推荐）：如果 A 的基线不够用，可以只用 imdb_crop 加原始的带噪年龄标签（年龄 = 拍摄年份 − 出生年份），并在论文里如实说明原始标签的噪声。注意：上面的 36% 只是 IMDB-Clean 样本里框对不上的比例，不能拿来代表原始带噪标签的噪声水平，这部分噪声需要另外评估。
- 如果以后预算允许、改用原图：IMDB-Clean 共 285,946 条，年龄 1—95 岁，标注采用 MIT 许可；图片仍按 IMDB-WIKI 条款执行，仅限学术研究。它的测试集与训练集、验证集都没有身份重叠，但训练集和验证集之间重叠 5,303 人。处理办法是把训练集和验证集合并，再按身份重新划分，测试集保持不动。HF 上的 caojingtian1216/imdb-clean-1024 是非官方再分发，不采用。

**C　FFHQ-Aging（可选，默认只取标签 CSV）**
- 用途：校准年龄段。不能用它独立评估 SAM，因为两者同源。
- 获取：官方仓库 https://github.com/royorel/FFHQ-Aging-Dataset 。
- 默认做法：只从 HF 下载标签 CSV，大小可以忽略不计。
- 不采用 NUS 转存的 images512x512_matte_white_background_categorised（约 1.35 万张，3.8 GiB）：这个子集已经去掉了背景，不适合拿来和 SAM 的输入做对照。
- 如果需要图片：用官方脚本生成 512 像素全量，Sentinel 估算约 22 GiB，这个数没有实测。
- 规模：70,000 张，按年龄段标注。
- 许可：CC BY-NC-SA 4.0；FFHQ 原图禁止用于人脸识别。

**E　WIDER FACE（检测）**
- 用途：人脸检测器的微调和评估。
- 获取：官网 http://shuoyang1213.me/WIDERFACE/ ，或直接下载 HF 上 CUHK-CSE/wider_face 的原始 zip。
- 规模：训练 12,880 张、验证 3,226 张；训练加验证共 1.71 GiB。
- 许可：CC BY-NC-ND 4.0。
- 处理：不用 Bingsu 的 YOLO 转换版，自己写脚本转格式。

**F　AFLW2000-3D（重建评测，新增）**
- 用途：只做冻结测试，不用于挑选模型。
- 获取：CBSR 官网 http://www.cbsr.ia.ac.cn/users/xiangyuzhu/projects/3DDFA/main.htm ，或 3DDFA 仓库提供的 test.data.zip。
- 规模：2,000 张，带 68 点三维标注，下载包约 83 MiB。
- 注意：3DDFA 提供的 test.data.zip（151 MB）只有 120×120 的裁剪图，不含 .mat 三维参数，只能用来算关键点误差（NME），测不了完整的重建流程，和 CBSR 原版不等价。完整评测必须用 CBSR 原版。
- 状态：CBSR 官网对我和 Sentinel 都返回 HTTP 500。作者主页链接的 Google Drive 文件实测 87,413,900 B（约 83.4 MiB），没有独立许可文本。许可（2026-11-16 RD-3 已核实，见 `AgeMorph3D_tasks/RD-3_AFLW核查.md`）：底层 AFLW 须经 TU Graz 申请表获取，仅限非商用研究、不得再分发；这些条款至少约束 AFLW2000-3D 的图像和 3DDFA 的 test.data.zip。不使用 Kaggle/HF 镜像。是否向 TU Graz 申请由用户决定。

**G　FGNET**
- 本地已有，不重新下载。已经被项目用过，不能再当外部盲测集。

**已删除**
- FFHQ-UV：不训练纹理；拓扑是 HiFi3D++ 而不是 BFM；年龄标签是 API 估计的；样本被打乱过；与 SAM 同源。
- 所有 AgeDB / IMDB-WIKI 的 HF 转存（包括比对用途在内，一律不保留）。

## 3. 磁盘预算（上限 41.5 GiB）

| 项 | 下载阶段峰值 | 删掉压缩包后常驻 |
|---|---|---|
| A AgeDB（估算） | 0.4 | 0.2 |
| E WIDER 训练 + 验证 | 3.4 | 1.7 |
| F AFLW2000-3D | 0.8 | 0.5 |
| G FGNET | 0 | 0.04 |
| **必需合计** | **约 4.6** | **约 2.4** |
| C 标签 CSV（可选） | ≈0 | ≈0 |
| C 512 像素全量（可选，估算） | 约 22 | 约 22 |
| B 退路：imdb_crop + 带噪标签（不推荐） | 13.1 | ≤6.6 |

操作规则：一次只下载一个数据集；解压并核对哈希后再删压缩包；下载前重新测一次磁盘空间。

## 4. AgeDB 官方申请
1. 由用户本人或导师用学校邮箱发邮件给 s.moschoglou@imperial.ac.uk ，申请解压密码。
2. 下载 AgeDB.zip。记录下载日期、文件大小和 SHA-256，并保存一份条款页面的快照。
3. 解压到 data/datasets/agedb/，设为只读。不进 Git，不上云，不分享。
4. 用官方文件名格式 `<id>_<name>_<age>_<gender>.jpg` 重新统计第 2 节的数字。
5. 拿到官方数据后，只把统计结果和本文已记录的汇总数字做比对。不保留、也不再下载任何 AgeDB 转存。

邮件要点（英文）：
- 主题：Request for AgeDB password – non-commercial undergraduate thesis research
- 申请人的姓名、学校、导师
- 用途是 AgeMorph3D 毕设，属于非商业研究；只用 20—70 岁的成人照片
- 只在本机单一站点使用；不复制、不发布、不分发图片或标注；会引用 Moschoglou et al., CVPRW 2017；毕设结束后删除数据

## 5. 安全加载规则
1. 不对来源不可信的 .pkl / .pth / .pt 文件做 unpickle。确实要读时，先用 `fickling --check-safety` 检查；`torch.load` 一律加 `weights_only=True`。优先使用 parquet、csv、jpg 格式的来源。
2. 重点标记以下文件，本方案不使用：
   - caojingtian1216/CACD/data/cada_train.pkl（1.37 GiB）
   - imdb-clean-1024 里的 pkl
   - FFHQ-Aging 转存里的 deeplab_model/*.pth
3. 禁用 `trust_remote_code`。WIDER FACE 用 `hf_hub_download` 直接下载 data/WIDER_train.zip、WIDER_val.zip 和 wider_face_split.zip，然后自己解析 bbx_gt.txt 并转成 YOLO 格式。
4. 解压前先核对哈希，并在隔离目录里解压。tar 包用 `tarfile.extractall(filter="data")` 防止路径穿越；zip 包解压前逐个检查成员路径，防止 zip-slip。
5. fickling 只是启发式检查，通过了也不代表文件安全。`weights_only=True` 加载报错时，直接放弃这个文件，不能改成 False 再试。

## 6. 风险
- **许可**：所有数据都只能用于非商业研究。FFHQ-UV（已从方案中删除）的代码采用 MIT 许可；数据派生自 FFHQ，适用 CC BY-NC-SA 4.0；人脸属性数据仅限研究使用（见 https://github.com/csbhr/FFHQ-UV/blob/main/README_dataset.md 的 Disclaimer）。
- **数据泄漏**：
  - SAM 的年龄损失用的是在 FFHQ-Aging 上微调过的 DEX，而 DEX 又在 IMDB-WIKI 上预训练过，所以用 B 或 C 评估 SAM 都有泄漏。
  - 3DDFA 用 300W-LP 训练过。
  - AgeDB-30 是 ArcFace 类模型常用的验证集，用这类模型做身份评价时，结果可能偏乐观。
- **偏差**：名人照片多、西方面孔多、化妆修图多；拍摄年代也会和年龄效应混在一起。
- **个人信息保护法（PIPL）**：
  - 人脸属于第 28 条规定的敏感个人信息（生物识别）。
  - 建议只用成年人子集，只在本机处理，不再分发；论文里尽量少放能认出人的人脸；毕设结束后删除数据并留下删除记录。
  - 是否需要做第 55 条的影响评估，请咨询导师或学校。
- **不推荐**：
  - MORPH II 的 HF 转存（treetreesha/morph2、wulala1219/morph2），属于未授权转存。
  - LAGENDA 的 n0kovo 转存：有 49.5 GiB，超出预算。官方全表 347,509 行里，75.8% 的行 age=-1。这是官方有意附带的未标注检测框，不是标签缺失，但能用的年龄样本只有约四分之一。（Sentinel 用全表统计得出）
  - CACD，年龄是粗估的，最大只到 62 岁。

## 7. 与 Sentinel 意见的核对结论（第二轮）
- AgeDB 最短边的最大值是 2232（出自一张 2239×2232 的图，2239 是它的宽度）。双方已确认。
- CACD 的 pkl：HF 显示 safe，只引用了 numpy；protectAI 那一项仍未扫描。方案里继续不使用。
- LAGENDA：官方全表中 age=-1 占 75.8%，这些是有意附带的未标注检测框（Sentinel 用全表统计得出）。
- FFHQ-UV 的“属性仅限研究”：README_dataset.md 的 Disclaimer 里有原文，已改回。
- B：原图需要约 269 GB，超出预算，本期不采用，并已移出必需合计。
- 仍待核实：CBSR 官方入口恢复后的实际大小；AFLW 官方包大小。（许可条款已由 RD-3 核实，见上文。）
