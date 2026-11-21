#!/usr/bin/env python3
"""BP-1 校验（v2.1）：只读。仓库文件通过 git show 35c0cd6 读取，不读工作树，不写仓库。"""
import re, collections, subprocess, sys
REPO, COMMIT = "/workspace/AgeMorph3D", "35c0cd6"
PLAN = "/workspace/AgeMorph3D_后续任务规划_v2.md"
OUT = "/workspace/AgeMorph3D_tasks/BP-1_里程碑重排与验收标准.md"
ID = r"[RDPTELO]\d{2}"
ok = True

def gshow(path):
    return subprocess.run(["git", "-C", REPO, "show", f"{COMMIT}:{path}"],
                          capture_output=True, text=True, check=True).stdout.splitlines()

def expand(text):
    ids = []
    for a, b in re.findall(rf"({ID})\s*[—–-]\s*({ID})", text):
        if a[0] == b[0]:
            ids += [f"{a[0]}{n:02d}" for n in range(int(a[1:]), int(b[1:]) + 1)]
    ids += re.findall(ID, re.sub(rf"({ID})\s*[—–-]\s*({ID})", "", text))
    return ids

print(f"== 读取 {COMMIT} 固定版本 ==")
src = gshow("docs/后续任务清单.md")

# 1) 清单编号
rows = {}
for n, l in enumerate(src, 1):
    m = re.match(rf"^\| ({ID}) \|", l)
    if m:
        rows[m.group(1)] = (n, [c.strip() for c in l.strip().strip("|").split("|")])
src_ids = list(rows)
print(f"[1 清单] 表格行编号数={len(src_ids)} 不同={len(set(src_ids))}",
      dict(sorted(collections.Counter(i[0] for i in src_ids).items())))

# 2) 规划 v2 阶段表
plan = open(PLAN, encoding="utf-8").read().splitlines()
plan_stage = {}
for l in plan[48:58]:
    m = re.match(r"^\| (S\d) ", l)
    if m:
        cell = [c.strip() for c in l.strip().strip("|").split("|")][-1]
        plan_stage[m.group(1)] = expand(cell)
        k = re.findall(r"\bK\d\b", cell)
        if k: print(f"[2 规划v2] {m.group(1)} 含非47项编号: {k}")
pc = collections.Counter(i for v in plan_stage.values() for i in v)
print(f"[2 规划v2] 阶段表: 出现{sum(pc.values())}次, 不同{len(pc)}个; 重复:",
      {k: [s for s, v in plan_stage.items() if k in v] for k, c in pc.items() if c > 1})
print("[2 规划v2] 未列:", sorted(set(src_ids) - set(pc)))

# 3) 本文分配表 + §4 列表
out = open(OUT, encoding="utf-8").read()
blk = out.split("<!-- BP1-ASSIGN-BEGIN -->")[1].split("<!-- BP1-ASSIGN-END -->")[0]
assign, dup = {}, []
trows = [l for l in blk.splitlines() if re.match(rf"^\| {ID} \|", l)]
for l in trows:
    c = [x.strip() for x in l.strip().strip("|").split("|")]
    if c[0] in assign: dup.append(c[0])
    assign[c[0]] = c[4]
    if str(rows.get(c[0], (None,))[0]) != c[2]:
        print(f"!! {c[0]} 清单行号写 {c[2]}，实际 {rows.get(c[0], (None,))[0]}"); ok = False
print(f"[3 本文表] 行数={len(trows)} 不同={len(assign)} 重复={dup} "
      f"缺={sorted(set(src_ids)-set(assign))} 多={sorted(set(assign)-set(src_ids))}")
ok &= len(trows) == 47 and not dup and set(assign) == set(src_ids) == set(rows) and len(src_ids) == 47
stage, lists = None, {}
for l in out.splitlines():
    m = re.match(r"^### (S\d) ", l)
    if m: stage = m.group(1)
    m = re.match(r"^- \*\*本阶段任务（(\d+) 项）\*\*：(.*)$", l)
    if m and stage:
        ids = re.findall(ID, m.group(2))
        if len(ids) != int(m.group(1)): print(f"!! {stage} 声明{m.group(1)}项, 实列{len(ids)}"); ok = False
        lists[stage] = ids
flat = [i for v in lists.values() for i in v]
mism = [(i, s, assign.get(i)) for s, v in lists.items() for i in v if assign.get(i) != s]
print("[3 本文§4] 各阶段数:", {s: len(v) for s, v in lists.items()}, "合计", len(flat),
      "重复:", [k for k, c in collections.Counter(flat).items() if c > 1], "与表不一致:", mism)
ok &= len(flat) == 47 and set(flat) == set(src_ids) and not mism and len(set(flat)) == 47

# 4) 依赖顺序
order = {i: (int(s[1]), k) for s, v in lists.items() for k, i in enumerate(v)}
SOFT = [r"不等\s*[^；;，,]*", r"随\s*[^；;，,]*推进"]   # 非硬前置（原文语义）
EXC = {("R11", "R08"): "已登记部分依赖：R11 只用 R08 的 G1 取消/过期部分（§7.3、§10 第7条）"}
dep_total, dep_ok, dep_exc, dep_bad, soft_seen = 0, 0, [], [], []
for t, (n, cells) in rows.items():
    dep = cells[4]
    for p in SOFT:
        for s in re.findall(p, dep): soft_seen.append(f"{t}: “{s}”")
        dep = re.sub(p, "", dep)
    for d in dict.fromkeys(expand(dep)):
        if d == t: continue
        dep_total += 1
        if order[d] < order[t]: dep_ok += 1
        elif (t, d) in EXC: dep_exc.append(f"{d}(S{order[d][0]}) → {t}(S{order[t][0]})：{EXC[(t, d)]}")
        else: dep_bad.append(f"{d}(S{order[d][0]}#{order[d][1]+1}) → {t}(S{order[t][0]}#{order[t][1]+1})")
print(f"[4 依赖] 编号依赖共 {dep_total} 条：满足 {dep_ok}，已登记例外 {len(dep_exc)}，未登记倒置 {len(dep_bad)}")
for s in soft_seen: print("    按原文不计为硬前置:", s)
for s in dep_exc: print("    例外:", s)
for s in dep_bad: print("  !! 倒置:", s)
ok &= not dep_bad

# 5) 引用行号核对
F = {"清单": gshow("docs/后续任务清单.md"), "矩阵": gshow("docs/验收矩阵.md"),
     "交付清单": gshow("docs/毕业设计要求与交付清单.md"), "总规划": gshow("docs/后续任务总规划.md"),
     "README": gshow("README.md"), "规划v2": plan,
     "剩余计划": gshow("docs/剩余关键工作开发计划.md")}
CITES = [("清单", 43, "2027年6月"), ("清单", 111, "M5 前冻结"), ("清单", 153, "不压缩验收"),
 ("清单", 155, "R11/G1、R12/G2评审通过"),
 ("矩阵", 41, "未指定数值质量阈值"), ("矩阵", 45, "G0完整服务契约"), ("矩阵", 46, "G1真实静态"),
 ("矩阵", 47, "G2实时姿态"), ("矩阵", 48, "G3年龄形状"), ("矩阵", 49, "G3年龄纹理"), ("矩阵", 49, "A/B实际复核眼区/遮挡/侧面/接缝及分歧，再冻单因素候选"),
 ("剩余计划", 33, "记录下一假设或范围差距"),
 ("矩阵", 50, "G3显示与资源"), ("矩阵", 51, "G3独立评价"), ("矩阵", 52, "T01基线注册"),
 ("矩阵", 53, "正式数据/预处理"), ("矩阵", 54, "训练/最终算法评价"), ("矩阵", 55, "学生自己写正文"),
 ("矩阵", 57, "503 MODEL_NOT_READY"), ("矩阵", 59, "须更新对应证据与检查范围"),
 ("交付清单", 21, "YOLO26n-face"), ("交付清单", 29, "10—20人主观打分"), ("交付清单", 50, "图表自行绘制"),
 ("交付清单", 56, "答辩后收口"), ("交付清单", 60, "不作为2026—2027项目的具体截止日"),
 ("交付清单", 62, "任务书阶段"), ("交付清单", 64, "调研与开题 | 2026-11-16—2027-01-31"),
 ("交付清单", 65, "YOLO微调/评测、重建NME及查看器基础"), ("交付清单", 66, "中期参考窗口04/15—04/20"),
 ("交付清单", 67, "10—20人评价"), ("交付清单", 68, "实际答辩日期另核"), ("交付清单", 70, "5月底内部包"),
 ("交付清单", 72, "A负责检测微调"),
 ("总规划", 111, "## 4. 里程碑与日历"), ("总规划", 113, "不压缩验收"), ("总规划", 117, "M0：范围"),
 ("总规划", 120, "纹理 POC 报告"), ("总规划", 121, "M4：训练资源到位"), ("总规划", 124, "真实设备/性能/GLB/纹理检查"),
 ("总规划", 125, "停止引入第二拓扑"), ("总规划", 126, "M9：内部完整交付"), ("总规划", 127, "学校正式交付与答辩"),
 ("总规划", 129, "12 月例会重估"), ("README", 102, "内部目标为5月31日"),
 ("规划v2", 49, "| 阶段 | 时间窗"), ("规划v2", 51, "S0 启动与解阻"), ("规划v2", 58, "S7 论文与答辩"),
 ("规划v2", 85, "BP-1"), ("规划v2", 238, "MINOR-4")]
# 清单任务行
CITES += [("清单", n, f"| {t} |") for t, (n, _) in rows.items()]
bad = [(f, n, s) for f, n, s in CITES if s not in F[f][n - 1]]
print(f"[5 引用] 核对 {len(CITES)} 处行号引用：通过 {len(CITES)-len(bad)}，失败 {len(bad)}", bad if bad else "")
ok &= not bad

# [6] v2.2（2026-11-21）用户答复落实检查
import subprocess as _sp, re as _re
_doc = open("/workspace/AgeMorph3D_tasks/BP-1_里程碑重排与验收标准.md", encoding="utf-8").read()
def _show(repo, commit, path):
    r = _sp.run(["git", "-C", repo, "show", f"{commit}:{path}"], capture_output=True, text=True)
    return r.stdout.splitlines() if r.returncode == 0 else None
_err = [("docs/model-assets.md", 3, "宋明耀（成员 B）"), ("docs/模型资产诊断与严格服务缺项记录.md", 3, "宋明耀（成员 B）"),
        ("backend/model-manifests/3ddfa-v2.research.json", 12, "宋明耀 (member B, project owner)"),
        ("backend/model-manifests/yolov5n05-face.research.json", 12, "宋明耀 (member B, project owner)"),
        ("backend/tests/test_model_assets.py", 168, "宋明耀"), ("docs/AgeMorph3D_技术框架与模块行动计划.md", 5, "宋明耀（A，组长，算法线）")]
_bad6 = []
for repo, commit in (("/workspace/AgeMorph3D", "35c0cd6"), ("/workspace/bp_ref/AgeMorph3D", "10f1918")):
    for path, n, needle in _err:
        L = _show(repo, commit, path)
        if L is None or needle not in L[n - 1]:
            _bad6.append(f"{commit}:{path}:{n}")
    if not _bad6:
        g = _sp.run(["git", "-C", repo, "grep", "-n", "-E", "宋明耀[^\\n]{0,6}(成员 ?B|member B)", commit], capture_output=True, text=True).stdout.splitlines()
        if len(g) != 4:
            _bad6.append(f"{commit}: 写宋明耀为 B 的位置数 {len(g)} != 4")
for path, n, _ in _err[:4]:
    if path not in _doc:
        _bad6.append(f"文档未登记 {path}")
_conf = _doc.count("已确认（用户 2026-11-21）")
for node in ("M0 补签 11-22【已确认", "G1 12-06【已确认", "G2 12-27【已确认", "M3 01-03【已确认"):
    if node not in _doc:
        _bad6.append(f"缺已确认标签：{node}")
for bad_txt in ("A/B 尚未与姓名对应", "本文排期按“维持门槛”编。"):
    if bad_txt in _doc:
        _bad6.append(f"残留旧表述：{bad_txt}")
for need in ("禁止再分发", "CC BY-NC-ND", "不进仓库", "Q-11", "Q-10"):
    if need not in _doc:
        _bad6.append(f"U-4 更新缺少：{need}")
print(f"[6 v2.2] 文档错误位置核对（35c0cd6 与 10f1918）、四节点已确认标签（全文 {_conf} 处）、U-4 许可/待决项：", "通过" if not _bad6 else f"失败 {_bad6}")
ok &= not _bad6

# [7] v2.3（2026-11-21 第二轮答复）：已关闭项、仍待决项、【建议】项
_U = "【用户已确认 2026-11-21，经 Atlas 转达】"
_bad7 = []
def _line(prefix):
    m = _re.search(rf"^{_re.escape(prefix)}.*$", _doc, _re.M)
    return m.group(0) if m else ""
_q4, _q2, _q5 = _line("- Q-4 U-4："), _line("- Q-2 U-3："), _line("- Q-5 G2 用例单：")
for need in ("/workspace/datasets/", "Q-11 已关闭", "Q-10 已关闭", "Q-12", "【待确认】", "数据入口评审日期【建议/待确认】", _U):
    if need not in _q4:
        _bad7.append(f"Q-4 缺：{need}")
if "10f1918" not in _q5 or _U not in _q5:
    _bad7.append("Q-5 未写 G1/G2 在 10f1918 执行")
if "【建议】写 A（宋明耀）" not in _q2 or "仍待用户确认" not in _q2:
    _bad7.append("Q-2：L02 须为【建议】A（宋明耀）且仍待确认")
_s71 = _line("| S7-1 L02 |")
if "A（宋明耀）本人【建议，待用户确认】" not in _s71:
    _bad7.append("S7-1 签收人未按【建议】写 A（宋明耀）")
for old in ("存放位置仍待用户确认", "存放位置待用户确认", "**不在本次放开范围内**", "仍待 A/B 与导师决定（BP-6 Q-10）",
            "放开范围只限这两个数据集", "纵向数据仍走此链"):
    if old in _doc:
        _bad7.append(f"残留旧表述：{old}")
for need in ("禁止再分发", "CC BY-NC-ND", "不进仓库", "AgeDB 仍只在用户本机处理", "### v2.2 → v2.3"):
    if need not in _doc:
        _bad7.append(f"缺少：{need}")
# v2.4（Sentinel MINOR-8）：L02 执行人每一处都须为【建议】；评审日期待定写法须全部保留
_body = _doc.split("### v2.3 → v2.4")[0]
_l02 = [l for l in _body.splitlines() if "L02" in l and "A（宋明耀）" in l]
for l in _l02:
    if "【建议" not in l or "【用户已确认" in l or "已确认（用户" in l:
        _bad7.append(f"L02 执行人须为【建议】且不得标已确认：{l[:40]}…")
if len(_l02) < 6:
    _bad7.append(f"L02【建议】A（宋明耀）处数 {len(_l02)} < 6（第 94、245、249、335、366、459 行一带）")
_rd = len(_re.findall(r"评审日期仍?为?【建议/待确认】", _body))
if _rd != 6:
    _bad7.append(f"“数据入口评审日期仍【建议/待确认】”类写法应为 6 处，实为 {_rd}")
if "→ D02/D04 正式下载（≤01-17）→ P01" in _doc:
    _bad7.append("§7.2 门槛链仍写评审后才正式下载 D02/D04")
for need in ("RN-3_WIDER_FACE_下载回执.json", "RN-3_AFLW2000-3D_下载回执.json", "经 Atlas 转达", "### v2.3 → v2.4"):
    if need not in _doc:
        _bad7.append(f"v2.4 缺少：{need}")
for old in ("RN-3_WIDER下载收据.json", "RN-3_AFLW下载收据.json", "【用户已确认 2026-11-21】"):
    if old in _doc:
        _bad7.append(f"残留旧表述：{old}")
for p in ("RN-3_WIDER_FACE_下载回执.json", "RN-3_AFLW2000-3D_下载回执.json"):
    import os as _os
    if not _os.path.exists("/workspace/AgeMorph3D_tasks/" + p):
        _bad7.append(f"回执文件不存在：{p}")
print(f"[7 v2.3/v2.4] L02【建议】{len(_l02)} 处、评审日期待定 {_rd} 处； 确认标记 {_doc.count(_U)} 处；Q-10/Q-11 关闭、Q-12 待定：", "通过" if not _bad7 else f"失败 {_bad7}")
ok &= not _bad7
print("结论:", "PASS（47 项不漏不重；依赖顺序无未登记倒置；引用行号全部核对通过）" if ok else "FAIL")
sys.exit(0 if ok else 1)
