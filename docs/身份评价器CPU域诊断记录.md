# 身份评价器CPU域诊断记录

2026-10-23。SFace/YuNet隔离研究适配、合成回归和首次真实照片/生成图域诊断已完成。194个图像请求中192个取得特征，2个记录`NO_FACE`；6,022个比较请求中5,855个有分数、167个为空。它补上了可运行的身份研究工具，尚未完成本域质量签收、渲染域验证、阈值校准或独立评价；生产年龄能力继续关闭。

## 固定资产、协议与输入

采用OpenCV Zoo固定commit `48b10fa505aeb51fbd127fc60a5c660040e823b7`的SFace 2021dec和YuNet 2023mar。实际大小及SHA-256与官方LFS指针一致；两目录README声明全部文件分别为Apache-2.0和MIT，见[来源核查](独立评价器候选核查.md)。两模型及六份文档快照保存在Git忽略目录，不进入生产模型清单。独立资产审计核对二进制及固定版本文档原文，不能替代整个数据、派生资产或分发链的许可核查。

先用空白图和合成112×112芯片完成CPU加载及重复特征自检，再冻结[机器协议](identity-evaluator-v1.json)及真实输入；首次真实身份分数在冻结后生成。环境为Python 3.11.16、Pillow 13.0.0、OpenCV 4.14.0、NumPy 2.4.6，OpenCV DNN CPU单线程。没有安装依赖、修改SAM环境、重新生成SAM图或训练模型。

| 请求范围 | 数量及处理 |
|---|---|
| N0原图 | 开发85张、校准70张，共155张；沿用原身份分组 |
| 既有开发源 | 10个，其中8张已在155张中，另外2张为外部源；未知源龄保留null |
| 既有SAM图 | N4的37张按N0源/目标条件及原始图像pin关联；不读取UV atlas、GLB或重建数组 |
| 唯一图像 | 155 + 10 − 8 + 37 = 194；初始及评分后大小/hash全部一致 |
| 原图比较 | 仅组内无序对：C(85,2) + C(70,2) = 5,985；不加入跨组对 |
| 源与生成图比较 | 37对：同龄控制8、其他条件23、未知源龄6；不预设生成图身份正确 |
| 上游失败 | N0的013A21、067A23单列，不虚构缺失生成请求；这两张原图仍在155张中尝试检测 |

研究保留组的137张原图未进入本次身份推理，也未读取保留组模型结果。先前近重复批次的自动原图签名接触及历史预处理接触已单独披露，本批不把这些数据宣称为未接触的外部评价。

## 实现与计数语义

[研究CLI](../tools/identity_evaluator_probe.py)复用N0元数据验证、有界字节快照及后端解码器。先验证同一份快照，再进行EXIF校正、RGB转BGR。YuNet固定最长边320且仅下采样，按实际取整后的宽高比例把检测框及五点映回原图，再由SFace对齐原始BGR到112×112。320、INTER_AREA和多脸失败是本地冻结策略，不能称为官方验证过的当前域准确率配置。

无脸、多脸均失败，不自动选择最大脸。特征必须为有限、非零的128维向量；分数为归一化余弦，不采用教程阈值。模型构造前、评分后均复核模型和文档；图像在全部比较/汇总后再次检查，末端变化会清除特征、使关联分数为空并重算。元数据或源码漂移同样拒绝成功发布。显式关闭解码图像并释放模型引用、恢复原OpenCV线程设置。

同人先在身份内平均，再对有效身份均权；异人先在无序身份对内平均，再对有效身份对均权。同龄/跨龄分层分别保留，另合并全部年龄的异人比较，在身份对内重新计算均值。生成图按类别先在源内平均，再对源均权。失败单位保留请求数和null均值；零请求分层显示0个单位。13个汇总是有重叠的统计视图，不能相加当成新的比较分母。

## 首次真实结果

失败原图为开发组`013A21.JPG`和`067A23.JPG`，均为`NO_FACE`；本轮没有因结果调低检测阈值或换裁剪。开发原图83/85、校准原图70/70、额外源图2/2及SAM图37/37取得特征。两张失败原图影响167个原图比较；完整请求分母仍是194张和6,022对。

| 比较 | 请求 / 有分数 | 有效 / 可评价单位 | 余弦宏均 |
|---|---:|---:|---:|
| 开发：同人跨龄 | 358 / 346 | 10 / 10身份 | 0.636892 |
| 开发：异人全部年龄 | 3,212 / 3,057 | 45 / 45身份对 | 0.074210 |
| 开发：同人同龄 | 0 / 0 | 0 / 0身份 | null |
| 校准：同人跨龄 | 157 / 157 | 13 / 13身份 | 0.628686 |
| 校准：异人全部年龄 | 2,256 / 2,256 | 105 / 105身份对 | 0.068861 |
| 校准：同人同龄 | 2 / 2 | 2 / 2身份 | 0.853203 |
| SAM：同龄控制 | 8 / 8 | 8 / 8源 | 0.655535 |
| SAM：其他条件 | 23 / 23 | 8 / 8源 | 0.606027 |
| SAM：未知源龄 | 6 / 6 | 2 / 2源 | 0.636281 |

这些是冻结配置下、成功取得特征条件下的描述性均值，不是准确率、身份保持通过率或20—70岁全域结论。真实同人/异人均值有分离，仍不能据此证明逐对可靠或选择质量门槛。同龄控制本身也有变化，不能把其他条件比较的变化全部归因于年龄；各源条件数与年龄差不同，两行宏均差不是受控年龄效应。未知源没有默认年龄，SAM请求年龄没有成为真实年龄标签。

训练身份及数据版本重叠仍未知，FG-NET镜像用途和独立数据取得条件另列。尚无渲染脸输入、误接受/误拒绝率、冻结阈值、置信区间或外部独立身份评价，本轮没有开放G3分项。

## 验证与证据

[合成测试](../backend/tests/test_identity_evaluator_probe.py)33项通过，覆盖稳定余弦、坐标逆映射、无脸/多脸、未知年龄、宏均与空值、输入前后漂移、拒绝覆盖及释放。测试发现Pillow转换RGB图仅使用其上下文退出仍可访问像素，修正为显式关闭并保留回归。另保护不同年龄负例先按身份对合并、再均权，防止按图池化或先分层平均。

完整后端1,381项通过，保留1条既有Starlette/httpx弃用警告；六个研究Python文件Ruff及格式检查通过。生产源码、`.gitignore`及未相关文件13个既有pin均复验未变。本批未改前端，不重复先前浏览器显示验收。

独立代码审查、结果复核分别记录。后者使用纯标准库重建194个输入、6,022个请求，从保存的128维特征重算全部余弦、13个汇总和438个单位汇总，与CSV最大分数误差为0；文件指纹前后核对通过。它没有再次解码照片、加载模型或独立提取特征，因此只支持元数据/指纹/已保存特征到统计的链路，不能证明检测或身份准确率。

| 证据 | 路径 / SHA-256 |
|---|---|
| 获取及合成自检 | [acquisition.json](../output/research/identity-evaluator-20261023/acquisition.json)、[synthetic-selfcheck.json](../output/research/identity-evaluator-20261023/synthetic-selfcheck.json) |
| 真实输入冻结 | [input-freeze.json](../output/research/identity-evaluator-20261023/input-freeze.json)，`ec427681789acdad3dc9a63e16c47510095614e06a1b87262476a979e6bdad4f` |
| 实现及运行计划 | [implementation-freeze.json](../output/research/identity-evaluator-20261023/implementation-freeze.json)、[study-plan.json](../output/research/identity-evaluator-20261023/study-plan.json)，计划`b76a71c16e9a689db51f47fdcd76f60a8bd1df167fd38cca7c68987a2cfa2b8f` |
| 真实诊断 | [evaluation/report.json](../output/research/identity-evaluator-20261023/evaluation/report.json)，`361cc108f9a29c8c35dcaae77739b6dd6de87b7cf898fa7e5981ec7ebea2f6b2` |
| 完整请求 | [evaluation/pairs.csv](../output/research/identity-evaluator-20261023/evaluation/pairs.csv)，`6b62dc591d7ff0f453ca28a82588b7632c32df149db06125ee5b8f230669b06e` |
| 独立审计 | [资产](../output/research/identity-evaluator-20261023/independent-assets-audit.json)、[代码](../output/research/identity-evaluator-20261023/independent-code-audit.json)、[结果](../output/research/identity-evaluator-20261023/independent-result-audit.json) |
| 最终核对 | [测试日志](../output/research/identity-evaluator-20261023/backend-tests.log)、[verification.json](../output/research/identity-evaluator-20261023/verification.json) |

复现依赖本机匹配的资产与冻结输入，需指定新输出目录；工具不下载模型。退出码0表示没有图像失败；本次退出码1保留两张`NO_FACE`，`integrity_status=passed`、`execution_status=completed_with_failures`，不是静默丢样本后的成功。

```powershell
.\backend\.venv\Scripts\python.exe tools/identity_evaluator_probe.py `
  --study-plan output/research/identity-evaluator-20261023/study-plan.json `
  --output-dir output/research/identity-evaluator-reproduction/evaluation

.\backend\.venv\Scripts\python.exe -m pytest -q backend/tests/test_identity_evaluator_probe.py
```

下一阶段先准备MiVOLO固定源码最小环境及合成加载验证，继续保留年龄数据用途、训练来源和60—70岁覆盖缺口；随后补身份评价渲染域和质量校准协议。不得根据保留组结果反调阈值，也不因工具可运行而接入生产年龄服务。本批新开发尚未提交或推送。
