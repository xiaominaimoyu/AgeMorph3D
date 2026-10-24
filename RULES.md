# 开发规则

更新日期：2026-10-24。本文件落实用户当轮提供的AGENTS指令；更新的用户指令和适用的上层规则优先。

## 开始和实现

每项实现/重构/调试先检查`~/.config/opencode/skills/opencode-md/`及适用指令。当前该目录的`SKILL.md`未找到，使用用户已完整提供的编码原则。先检查并维护PRD、ARCHITECTURE、DESIGN、RULES、TASKS、PROGRESS六份说明，不覆盖既有用户内容。

明确假设与可验证出口，采用最少代码，只改任务所需文件。只清理自己产生的文件；真实代码和当前证据优先于历史报告。使用`rg`优先检索，独立读取可以并行，依赖操作按顺序执行。

## AI不得执行的操作

- 不修改或删除原有`.gitignore`；不暂存/发布被忽略文件、模型、数据、环境、日志、输出产物、凭证或本地会话缓存。
- 未确认本次精确文件清单前不执行Git操作；不使用全量暂存，不擅自强制推送。本地提交授权不等于推送授权。提交前先读忽略规则、完成全文件敏感检查；发现风险或Git错误按用户规则停止并完整报告。
- 不改身份分组、不把未知源龄填为默认年龄、不以源投影替代目标自有投影、不补造未知观测、不把生成条件当年龄真值。
- 不从研究报告、权重存在、合成测试或渲染成功推定许可、独立性、身份/年龄质量、G3或生产ready。保留无人脸、多脸、遮挡、漂移和所有失败分母。
- 不未经明确授权向他人发消息、提交访问申请或发布研究资产；本地开发和只读核查持续推进，无需额外确认。

## 验证与记录

按变更运行有意义的针对性测试，再运行必要回归、显式仓库配置的静态检查、构建及实际集成验证。检查通过后不无故重复全部测试。代码、声明、执行、真实模型结果和质量签收分别记录。

研究输入/源码/模型/环境使用精确指纹冻结并前后核查；旧证据不覆盖。独立算术复算不等于独立重跑模型。生产边界、无关用户文件和原始资产的保存状态需要可复核。

## graphify引用

新用户指令包含`@AGENTS.md`。早先检查未发现项目根或其两级祖先的该文件，也未从PATH找到`graphify`命令。2026-10-23稍后工具和技能文件出现；重新核查当前命令为`C:/Users/ASUS/.local/bin/graphify.exe`，技能分别在`C:/Users/ASUS/.agents/skills/graphify/SKILL.md`及`.codex/skills/graphify/SKILL.md`，其文件时间为本地23:29左右。根/两级祖先的AGENTS文件仍不存在，opencode编码技能也仍不存在。

用户随后明确完成全局配置，现已读取`C:/Users/ASUS/.codex/AGENTS.md`及其引用的`C:/Users/ASUS/AGENTS.md`。已按技能执行本机结构更新与遮罩查询，图谱实际位于`output/research/project-knowledge-20261023/graphify-out/`，可打开[本地HTML](output/research/project-knowledge-20261023/graphify-out/graph.html)。项目根下的同名默认目录仍不存在，查询时必须使用实际路径，不能因默认路径为空忽略已有图。

当前本机使用`output/research/mask-replay-20261023/graphify_local.py`封装调用，设置`GRAPHIFY_OUT`到已有忽略目录；v3在Popen和Windows CreateProcess入口只允许本机Python AST worker，拒绝外部进程/shell并禁用网络，避免触发用户尚未确认的Git操作。没有改`.gitignore`、全局配置或安装Git hooks。后续代码变更按全局规则运行本地`graphify update .`，先查询词汇/子图再定点阅读；图谱中的推断、递归自环和截断查询不能替代源代码或质量证据。封装与图谱是本机研究文件，克隆项目不保证具备。

初次封装入口误用`graphify.cli.main`已纠正为`graphify.__main__.main`，旧脚本和错误日志保留；更新命令已实际成功。不要把早先缺失的工具检查或未建图状态描述为当前状态，也不把结构抽取宣称为完整文档语义图谱。

旧进程guard只识别executable或argv列表，遗漏Windows的None+字符串命令行，已在最终核查发现并更正；旧日志的零Git计数不能证明没有只读Git查询，不能倒推为已阻断。旧版本与[更正记录](output/research/mask-replay-20261023/graphify-guard-correction.json)保留，后续只使用经过直接合成事件核验的v3。遮罩主实现及130个冻结输入的校验与图谱遥测分开保存。
