#!/usr/bin/env python3
"""BP-6 E01 冻结要点自检（只读，不联网，不写任何文件）。

仓库文件一律通过 `git show 35c0cd6:<路径>` 读取，不读工作树；工作区文件（绝对路径）直接读；
外部来源只核对本次抓取后保存在 /workspace/bp6_work/ 的本地副本。
检查：
  1. 〔路径:行号「原文」〕：原文出现在该文件该行（空白归一化后子串匹配）；
  2. 〔E-n:行号「原文」〕（代码/文本副本，按行）与〔E-n「原文」〕（PDF/网页转文本，按全文子串）；
     引用的 E 编号都登记在 §10；无本地副本的 E-3、E-9 不得被逐字引用；
  3. 必需章节 §0—§10；冻结项 N-1—N-13、W-1—W-13、A-1—A-9 齐全不重复；
  4. 关键口径存在：sqrt(宽×高) 归一化、三个 yaw 箱、三箱均值平均、68 点含不可见点、2D；
     Easy/Medium/Hard、IoU 0.5、官方 eval_tools、val 冻结评价、不称官方 test；
  5. §3 test.data.zip 只有一项“能”，其余均为“不能”，且至少 5 项“不能”；
  6. §6 阈值表每行冻结阈值均为“留空”；
  7. 正文 URL 都登记在 §10；时间只用 UTC+8；
  8. 仓库仍在 35c0cd6 且工作树无改动；
  9. 「第 N 行」写法的引用逐条核对登记的关键词（lineref.py）；
  10. v1.1 修订要点在文中存在（v1.3 起按用户答复的已决形式核对）；
  12. v1.3：Q-10/Q-11 已关闭、Q-12 待确认、Q-3 仍待决、许可与数据目录。
退出码 0 = 全部通过。
"""
import re, subprocess, sys, html

REPO, COMMIT = "/workspace/AgeMorph3D", "35c0cd6"
DOC = "/workspace/AgeMorph3D_tasks/BP-6_E01冻结要点.md"
W = "/workspace/bp6_work/"
EXT_LINE = {"E-1": W + "3DDFA_benchmark_aflw2000.py", "E-2": W + "3DDFA_readme.md", "E-7": W + "3DDFA_V2_readme.md",
            "E-11": W + "3DDFA_benchmark.py"}
EXT_TEXT = {"E-4": W + "1804.01005.txt", "E-5": W + "1511.07212.txt", "E-6": W + "3162.txt",
            "E-8": W + "wider_results.html", "E-10": W + "w.txt"}
NO_COPY = {"E-3", "E-9"}
failures = []


def fail(msg):
    failures.append(msg)
    print("  ✗", msg)


def norm(s):
    return re.sub(r"\s+", "", s)


_cache = {}
def file_lines(path):
    if path not in _cache:
        if path.startswith("/"):
            try:
                _cache[path] = open(path, encoding="utf-8", errors="ignore").read().splitlines()
            except OSError:
                _cache[path] = None
        else:
            r = subprocess.run(["git", "-C", REPO, "show", f"{COMMIT}:{path}"], capture_output=True, text=True)
            _cache[path] = r.stdout.splitlines() if r.returncode == 0 else None
    return _cache[path]


def full_text(path):
    t = open(path, encoding="utf-8", errors="ignore").read()
    if path.endswith(".html"):
        t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return norm(t)


text = open(DOC, encoding="utf-8").read()
lines = text.splitlines()

# 1. 仓库/工作区引用
cites = re.findall(r"〔([^〔〕:：]+?):(\d+)「(.+?)」〕", text)
cites = [c for c in cites if not re.fullmatch(r"E-\d+", c[0])]
print(f"[1] 仓库/工作区行号引用 {len(cites)} 处")
nrepo = 0
for path, ln, quote in cites:
    fl = file_lines(path)
    if fl is None:
        fail(f"无法读取 {path}"); continue
    n = int(ln)
    if not (1 <= n <= len(fl)):
        fail(f"{path}:{n} 越界"); continue
    if norm(quote) not in norm(fl[n - 1]):
        fail(f"{path}:{n} 原文不符：「{quote[:40]}」")
    nrepo += 0 if path.startswith("/") else 1
print(f"    其中仓库(35c0cd6) {nrepo} 处")
if nrepo == 0:
    fail("没有仓库引用")

# 2. 外部引用
src = text.split("## 10.")[1] if "## 10." in text else ""
registered = set(re.findall(r"^\| (E-\d+) \|", src, re.M))
ext_line = re.findall(r"〔(E-\d+):(\d+)「(.+?)」〕", text)
ext_text = re.findall(r"〔(E-\d+)「(.+?)」〕", text)
print(f"[2] 外部按行引用 {len(ext_line)} 处，按全文引用 {len(ext_text)} 处；§10 登记 {len(registered)} 个来源")
for eid, ln, quote in ext_line:
    if eid not in registered:
        fail(f"{eid} 未在 §10 登记")
    if eid not in EXT_LINE:
        fail(f"{eid} 没有可按行核对的本地副本"); continue
    fl = file_lines(EXT_LINE[eid])
    n = int(ln)
    if fl is None or not (1 <= n <= len(fl)) or norm(quote) not in norm(fl[n - 1]):
        fail(f"{eid}:{n} 原文不符：「{quote[:40]}」")
for eid, quote in ext_text:
    if eid not in registered:
        fail(f"{eid} 未在 §10 登记")
    if eid in NO_COPY or eid not in EXT_TEXT:
        fail(f"{eid} 无本地副本，不能逐字引用"); continue
    if norm(quote) not in full_text(EXT_TEXT[eid]):
        fail(f"{eid} 原文不符：「{quote[:40]}」")
for eid in sorted(set(re.findall(r"\bE-\d+\b", text.split("## 10.")[0]))):
    if eid not in registered:
        fail(f"正文提到 {eid} 但 §10 未登记")

# 3. 章节与冻结项
heads = [l for l in lines if l.startswith("## ")]
for k in range(0, 11):
    if not any(h.startswith(f"## {k}.") for h in heads):
        fail(f"缺少 §{k}")
for pre, n in (("N", 13), ("W", 13), ("A", 9)):
    ids = re.findall(rf"^\| ({pre}-\d+) \|", text, re.M)
    if ids != [f"{pre}-{i}" for i in range(1, n + 1)]:
        fail(f"{pre} 冻结项应为 {pre}-1—{pre}-{n}，实际 {ids}")
print(f"[3] 章节 {len(heads)} 个；冻结项检查完成")

# 4. 关键口径
must = {
    "sqrt 归一化": "sqrt(宽 × 高)",
    "非眼距": "不是眼距",
    "yaw 箱 1": "[0°,30°]", "yaw 箱 2": "(30°,60°]", "yaw 箱 3": "(60°,90°]",
    "三箱均值平均": "三箱均值的算术平均",
    "可见性（v1.3 已冻结为登记例外）": "**冻结为 68 点全部计入，包括不可见点**",
    "一致度非误差": "不是与真值的误差",
    "2D": "**2D**",
    "Easy/Medium/Hard": "Easy / Medium / Hard",
    "IoU 0.5": "IoU 阈值 0.5",
    "官方工具": "eval_tools",
    "val 冻结评价": "官方 val 作模型选定后的冻结评价",
    "不称官方 test": "不得称官方 test",
}
for k, v in must.items():
    if v not in text:
        fail(f"缺少关键口径：{k}（{v}）")
print("[4] 关键口径检查完成")

# 5. test.data.zip 用途表
sec3 = text.split("## 3.")[1].split("## 4.")[0]
rows = [l for l in sec3.splitlines() if l.startswith("| ") and not l.startswith("| 用途") and not l.startswith("|---")]
can = [r for r in rows if r.split("|")[2].strip().startswith("**能")]
cannot = [r for r in rows if r.split("|")[2].strip().startswith("**不能")]
print(f"[5] test.data.zip：能 {len(can)} 项，不能 {len(cannot)} 项")
if len(can) != 1 or "NME" not in can[0] or len(cannot) < 5 or len(can) + len(cannot) != len(rows):
    fail("test.data.zip 用途表应只有 NME 一项“能”，其余“不能”")
if not any("AP" in r for r in cannot):
    fail("test.data.zip 用途表未写明不能算 AP")

# 6. 阈值留空
sec6 = text.split("## 6.")[1].split("## 7.")[0]
trows = [l for l in sec6.splitlines() if l.startswith("| ") and not l.startswith("| 指标") and not l.startswith("|---")]
print(f"[6] 阈值表 {len(trows)} 行")
if not trows:
    fail("§6 阈值表为空")
for r in trows:
    if r.split("|")[2].strip() != "**留空**":
        fail(f"阈值未留空：{r[:40]}")

# 7. URL 与时区
body = text.split("## 10.")[0]
for u in sorted(set(re.findall(r"https?://[^\s）)」|，。]+", body))):
    if u not in src:
        fail(f"正文 URL 未登记：{u}")
for bad in ["UTC+1", "CET", "Europe/Berlin"]:
    if bad in text:
        fail(f"出现非 UTC+8 时区：{bad}")
utc = re.findall(r"UTC[+\-]\d+", text)
if any(u != "UTC+8" for u in utc):
    fail(f"其他 UTC 偏移：{set(utc)}")
print(f"[7] UTC 标记 {len(utc)} 处")

# 8. 仓库
head = subprocess.run(["git", "-C", REPO, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
dirty = subprocess.run(["git", "-C", REPO, "status", "--porcelain"], capture_output=True, text=True).stdout.strip()
print(f"[8] 仓库 HEAD={head}，工作树改动 {len(dirty.splitlines()) if dirty else 0} 项")
anc = subprocess.run(["git", "-C", REPO, "merge-base", "--is-ancestor", COMMIT, "HEAD"]).returncode == 0
# 2026-11-21：/workspace/AgeMorph3D 被其他进程快进到 10f1918（非 Blueprint 操作）。引用仍固定读 35c0cd6；这里只要求工作树干净且 HEAD 是 35c0cd6 或其后代。
if not anc or dirty:
    fail("仓库 HEAD 不含 35c0cd6 或工作树有改动")

# 9. 「第 N 行」写法
sys.path.insert(0, "/workspace/AgeMorph3D_tasks")
import lineref
WS = "/workspace/"
T = WS + "AgeMorph3D_tasks/"
ALIASES = {
    "v3": WS + "AgeMorph3D_数据集方案_v3.md",
    "RD-3": T + "RD-3_AFLW核查.md",
    "RD-6": T + "RD-6_WIDER官方评价.md",
    "实验协议": "docs/实验协议.md",
    "清单": "docs/后续任务清单.md",
    "项目计划": "docs/AgeMorph3D_项目计划.md",
    "BP-1": T + "BP-1_里程碑重排与验收标准.md",
}
REG = {
    ("v3", "54"): "只能用来算关键点误差（NME）",
    ("RD-3", "15"): "Google Drive",
    ("RD-3", "145"): "CBSR 直链不可用。作者主页改由 Google Drive 分享同名 zip",
    ("RD-3", "191"): "从 `pt3d_68` 读取 68 点",
    ("RD-6", "19"): "不能用自写 YOLO 标签或 Ultralytics mAP50–95 代替",
    ("实验协议", "13"): "默认从WIDER train内部留开发用途",
    ("实验协议", "20"): "不能从已看测试分数倒推通过线",
    ("实验协议", "60"): "不能把眼镜/不可见区域的拟合点当标注真值",
    ("清单", "111"): "E01 在 M0 起草、M5 前冻结",
    ("清单", "115"): "年龄网格",
    ("项目计划", "49"): "3DDFA_V2 官方基线约 3.0% 量级",
    ("BP-1", "186"): "共同，A（宋明耀） 主笔",
}
n9 = lineref.check(text, ALIASES, REG, fail)
print(f"[9] 「第 N 行」引用核对通过 {n9} 处")

# 10. v1.1 修订要点
for k, v_ in {
    "Q-10": "- **Q-10", "Q-11": "- **Q-11",
    "N-A 由用户决定（v1.3 已决定）": "用户已决定在“本机”获取并使用",
    "只在本机（v1.3 本机所指待确认）": "绝不进仓库、不传给任何第三方或 agent",
    "第 60 行引全": "不能把眼镜/不可见区域的拟合点当标注真值」〕",
    "N-12 成功率并列": "并与成功率（成功数/全部请求数）**并列报告**",
    "years_calibrated": "网格值不是标定过的年份",
}.items():
    if v_ not in text:
        fail(f"缺少 v1.1 修订要点：{k}")
if "experiment-protocol-v1.json:8「\"quality_threshold\": null」" in text:
    fail("§6 仍引 experiment-protocol-v1.json:8")
print("[10] v1.1 修订要点检查完成")

# 11. v1.2 要点（保留部分）：许可、v1.1 修正、文档错误位置
for k, v_ in {
    "AFLW 禁止再分发": "禁止再分发",
    "WIDER 许可": "CC BY-NC-ND",
    "不进仓库": "一律不进仓库",
    "MAJOR-1 保留": "MAJOR-1（N-A 轨获取途径与许可、交用户决定）",
    "MAJOR-2 保留": "MAJOR-2（68 点含不可见点与实验协议冲突）",
    "static_fallback 引用": "\"shape_route\": \"static_fallback\"",
    "Pose_Para 单位": "`Pose_Para`（单位为弧度",
}.items():
    if v_ not in text:
        fail(f"缺少 v1.2 要点：{k}")
for path in ("docs/model-assets.md:3", "docs/模型资产诊断与严格服务缺项记录.md:3",
             "backend/model-manifests/3ddfa-v2.research.json:12", "backend/model-manifests/yolov5n05-face.research.json:12"):
    if path not in text:
        fail(f"未登记文档错误位置：{path}")
print("[11] v1.2 要点检查完成")

# 12. v1.3：用户第二轮答复（2026-11-21）——已关闭项、仍待决项、许可与数据目录
U = "【用户已确认 2026-11-21，经 Atlas 转达】"
def qline(q):
    m = re.search(rf"^- \*\*{q}[（*【].*$", text, re.M)
    return m.group(0) if m else ""
q10, q11, q12, q3 = qline("Q-10"), qline("Q-11"), qline("Q-12"), qline("Q-3")
if not ("已关闭" in q10 and U in q10 and "实验协议第 60 行" in q10):
    fail("Q-10 未按用户答复关闭（须含“已关闭”、确认标记与实验协议第 60 行）")
if not ("已关闭" in q11 and U in q11 and "非商用" in q11 and "禁止再分发" in q11 and "绝不进仓库" in q11):
    fail("Q-11 未关闭或许可说明缺失")
if not ("【待确认】" in q12 and "/workspace/datasets/" in q12 and "已关闭" not in q12):
    fail("Q-12（“本机”所指）须为【待确认】且未关闭")
if not q3 or "已关闭" in q3 or "仍待决" not in q3:
    fail("Q-3 须仍待决")
n2 = re.search(r"^\| N-2 \|.*$", text, re.M)
if not n2 or "冻结为 68 点全部计入" not in n2.group(0) or U not in n2.group(0) or "登记的协议例外" not in n2.group(0):
    fail("N-2 未改为全计 68 点的登记例外")
for old in ("可见性口径未冻结", "未冻结，待 A/B 与导师决定（Q-10）", "取决于 Q-10", "存放位置待用户确认 |"):
    if old in text:
        fail(f"仍有旧口径：{old}")
if "/workspace/datasets/" not in text or text.count(U) < 8:
    fail("数据目录或确认标记不足")
if "docs/实验协议.md:60「不能把眼镜/不可见区域的拟合点当标注真值」" not in text:
    fail("§0.2 未引用实验协议第 60 行")
print(f"[12] v1.3 用户答复检查完成（确认标记 {text.count(U)} 处）")

# 13. v1.4：Sentinel 11-21 MINOR
KEEP = "确认前【建议】`test.data.zip` 暂不放进 box"
CONS = "只在用户自己的电脑上获取和使用，box 上不放"
AFB = "/workspace/datasets/aflw2000_3d` 的 AFLW2000-3D 原版"
_s02 = re.search(r"^4\. \*\*新增 Q-12【待确认】\*\*.*$", text, re.M)
_s02 = _s02.group(0) if _s02 else ""
_na = re.search(r"^\| \*\*N-A 基准复现轨\*\* \|.*$", text, re.M)
_na = _na.group(0) if _na else ""
for name, seg, needs in (("Q-12", q12, (KEEP, CONS, AFB, "一并交用户确认")), ("§0.2 第 4 条", _s02, (KEEP, CONS, AFB, "一并交用户确认")), ("N-A 行", _na, (KEEP, CONS))):
    for nd in needs:
        if nd not in seg:
            fail(f"{name} 缺：{nd}")
for name, seg in (("Q-10", q10), ("§0.2 Q-10", (re.search(r"^2\. \*\*Q-10 已关闭\*\*.*$", text, re.M) or [""])[0])):
    if "B（王晋涛）：未询问；导师：未告知" not in seg or "冻结稿签认前须告知导师、由 B（王晋涛）复核" not in seg:
        fail(f"{name} 未写 B/导师状态或冻结前置")
_s83 = re.search(r"^3\. \*\*可见性（协议冲突.*$", text, re.M)
if not _s83 or "冻结前置：冻结稿签认前须告知导师、由 B（王晋涛）复核" not in _s83.group(0):
    fail("§8 第 3 条缺冻结前置")
if not re.search(r"^## 9\. .*Q-10.*B 未询问、导师未告知", text, re.M):
    fail("§9 标题未与 Q-10 状态一致")
_nb = re.search(r"^\| \*\*N-B 项目链路轨\*\* \|.*$", text, re.M)
if not _nb or "已由 Runner 按 RN-3 下载" not in _nb.group(0) or "0444" not in _nb.group(0):
    fail("N-B 行未写已下载、压缩包删除与只读")
if "test_model_assets.py:168" not in text.split("### 0.2")[0]:
    fail("§0.1 旧写法清单缺 test_model_assets.py:168")
if "【用户已确认 2026-11-21】" in text or "经 Atlas 转达给 Blueprint" not in text:
    fail("确认标记未标来源或缺定义")
print("[13] v1.4：Q-12 保守口径与 box 上 AFLW 原版一并待确认；Q-10 B/导师状态与冻结前置；N-B 已下载；test_model_assets 附注")

print("\n结果：", "PASS" if not failures else f"FAIL（{len(failures)} 项）")
sys.exit(0 if not failures else 1)
