#!/usr/bin/env python3
"""BP-5 AgeDB 应急方案自检（只读，不联网，不写任何文件）。

仓库文件一律通过 `git show 35c0cd6:<路径>` 读取，不读工作树；工作区文件（绝对路径）直接读。
检查：
  1. 全文每处〔路径:行号「原文」〕的原文出现在该文件该行（空白归一化后子串匹配）；
  2. 必需章节 §0—§10 齐全；
  3. 四个候选（AgeDB、KANFace、imdb_crop、MORPH）在 §4 各有小节，且七个属性行齐全；
  4. §5.1 对照表含四个候选列和六个必需维度行；
  5. 触发条件 TC-1—TC-6、决策记录条款 DR-1—DR-11 齐全且不重复；
  6. §3.1 排序：AgeDB 顺位 1 ＞ KANFace 顺位 2 ＞ MORPH 顺位 4；KANFace 标明"用户决定"；MORPH 标明"不作为优先备选"；
  7. 正文出现的外部 URL 都登记在 §10；
  8. 时间只用 UTC+8（不出现 UTC+1/CET/Europe/Berlin）；
  9. 仓库仍在 35c0cd6 且工作树无改动；
  10. 「第 N 行」写法的引用逐条核对登记的关键词（lineref.py）。
退出码 0 = 全部通过。
"""
import re, subprocess, sys

REPO, COMMIT = "/workspace/AgeMorph3D", "35c0cd6"
DOC = "/workspace/AgeMorph3D_tasks/BP-5_AgeDB应急方案.md"
failures = []


def fail(msg):
    failures.append(msg)
    print("  ✗", msg)


_cache = {}
def file_lines(path):
    if path not in _cache:
        if path.startswith("/"):
            try:
                _cache[path] = open(path, encoding="utf-8").read().splitlines()
            except OSError:
                _cache[path] = None
        else:
            r = subprocess.run(["git", "-C", REPO, "show", f"{COMMIT}:{path}"], capture_output=True, text=True)
            _cache[path] = r.stdout.splitlines() if r.returncode == 0 else None
    return _cache[path]


def norm(s):
    return re.sub(r"\s+", "", s)


text = open(DOC, encoding="utf-8").read()
lines = text.splitlines()

# 1. 引用
cites = re.findall(r"〔([^〔〕:：]+?):(\d+)「(.+?)」〕", text)
print(f"[1] 行号引用 {len(cites)} 处")
repo_n = ws_n = 0
for path, ln, quote in cites:
    fl = file_lines(path)
    if fl is None:
        fail(f"无法读取 {path}"); continue
    n = int(ln)
    if n < 1 or n > len(fl):
        fail(f"{path}:{n} 越界"); continue
    if norm(quote) not in norm(fl[n - 1]):
        fail(f"{path}:{n} 原文不符：「{quote[:40]}」")
    if path.startswith("/"):
        ws_n += 1
    else:
        repo_n += 1
print(f"    仓库(35c0cd6) {repo_n} 处，工作区 {ws_n} 处")
if repo_n == 0:
    fail("没有任何仓库行号引用")

# 2. 章节
heads = [l for l in lines if l.startswith("## ")]
for k in range(0, 11):
    if not any(h.startswith(f"## {k}.") for h in heads):
        fail(f"缺少 §{k}")
print(f"[2] 章节 {len(heads)} 个")


def section(prefix):
    out, on = [], False
    for l in lines:
        if l.startswith(prefix):
            on = True; continue
        if on and (l.startswith("### ") or l.startswith("## ")):
            break
        if on:
            out.append(l)
    return "\n".join(out)

# 3. 候选属性
ATTRS = ["访问方式", "许可要点", "规模", "身份字段", "年龄标签类型与范围", "70 岁覆盖", "下载大小"]
cands = {"AgeDB": "### 4.1", "KANFace": "### 4.2", "imdb_crop": "### 4.3", "MORPH": "### 4.4"}
for name, pre in cands.items():
    h = [l for l in lines if l.startswith(pre)]
    if not h or name not in h[0]:
        fail(f"§4 缺少 {name} 小节"); continue
    body = section(pre)
    for a in ATTRS:
        if not re.search(rf"^\| {re.escape(a)} \|", body, re.M):
            fail(f"{name} 缺少属性行：{a}")
print("[3] 候选属性检查完成")

# 4. T04 对照表
t = section("### 5.1")
hdr = [l for l in t.splitlines() if l.startswith("| 维度")]
if not hdr or not all(c in hdr[0] for c in ["AgeDB", "KANFace", "imdb_crop", "MORPH"]):
    fail("§5.1 表头缺少候选列")
for dim in ["身份划分键", "equal_identity 权重", "年龄跨度要求", "标签类型登记", "70 岁端点", "评价独立性"]:
    if not re.search(rf"^\| \*\*{re.escape(dim)}\*\* \|", t, re.M):
        fail(f"§5.1 缺少维度：{dim}")
    else:
        row = re.search(rf"^\| \*\*{re.escape(dim)}\*\* \|(.*)$", t, re.M).group(1)
        cells = [c.strip() for c in row.split("|") if c.strip()]
        if len(cells) != 4:
            fail(f"§5.1 维度 {dim} 应有 4 个候选单元格，实际 {len(cells)}")
print("[4] T04 对照表检查完成")

# 5. TC / DR
tc = re.findall(r"^\| \*\*(TC-\d)\*\* \|", section("### 2.2"), re.M)
if sorted(tc) != [f"TC-{i}" for i in range(1, 7)]:
    fail(f"触发条件应为 TC-1—TC-6，实际 {tc}")
dr = re.findall(r"^\| (DR-\d+) \|", section("## 7."), re.M)
if dr != [f"DR-{i}" for i in range(1, 12)]:
    fail(f"决策记录条款应为 DR-1—DR-11，实际 {dr}")
print(f"[5] TC {len(tc)} 条，DR {len(dr)} 条")

# 6. 排序
r = section("### 3.1")
def rank(name):
    m = re.search(rf"^\| (\d+|终局) \| [^|]*{name}", r, re.M)
    return m.group(1) if m else None
ra, rk, rm = rank("AgeDB"), rank("KANFace"), rank("MORPH")
print(f"[6] 顺位 AgeDB={ra} KANFace={rk} MORPH={rm}")
if not (ra == "1" and rk == "2" and rm and rm.isdigit() and int(rm) > 2):
    fail("排序不符合 AgeDB ＞ KANFace ＞ MORPH")
krow = [l for l in r.splitlines() if "KANFace" in l and l.startswith("| 2")]
if not krow or "用户本人决定" not in krow[0] or "待用户决定" not in krow[0]:
    fail("KANFace 行未写明由用户决定")
mrow = [l for l in r.splitlines() if "MORPH" in l and re.match(r"^\| \d", l)]
if not mrow or "不作为优先备选" not in mrow[0]:
    fail("MORPH 行未写明不作为优先备选")

# 7. URL 登记
src = section("## 10.")
body_txt = text.split("## 10.")[0]
urls = set(re.findall(r"https?://[^\s）)」|，。]+", body_txt))
for u in sorted(urls):
    if u not in src:
        fail(f"正文 URL 未登记于 §10：{u}")
src_urls = re.findall(r"https?://[^\s|]+", src)
print(f"[7] 正文 URL {len(urls)} 个；§10 登记 {len(src_urls)} 个")
if len(src_urls) < 7:
    fail("§10 外部来源少于 7 个")

# 8. 时区
for bad in ["UTC+1", "CET", "Europe/Berlin", "UTC+01"]:
    if bad in text:
        fail(f"出现非 UTC+8 时区标记：{bad}")
utc = re.findall(r"UTC[+\-]\d+", text)
if any(u != "UTC+8" for u in utc):
    fail(f"出现其他 UTC 偏移：{set(utc)}")
print(f"[8] UTC 标记 {len(utc)} 处，全部 UTC+8" if all(u == "UTC+8" for u in utc) else "[8] 时区异常")

# 9. 仓库未改动
head = subprocess.run(["git", "-C", REPO, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
dirty = subprocess.run(["git", "-C", REPO, "status", "--porcelain"], capture_output=True, text=True).stdout.strip()
print(f"[9] 仓库 HEAD={head}，工作树改动 {len(dirty.splitlines()) if dirty else 0} 项")
anc = subprocess.run(["git", "-C", REPO, "merge-base", "--is-ancestor", COMMIT, "HEAD"]).returncode == 0
# 2026-11-21：/workspace/AgeMorph3D 被其他进程快进到 10f1918（非 Blueprint 操作）。引用仍固定读 35c0cd6；这里只要求工作树干净且 HEAD 是 35c0cd6 或其后代。
if not anc or dirty:
    fail("仓库 HEAD 不含 35c0cd6 或工作树有改动")

# 10. 「第 N 行」写法
sys.path.insert(0, "/workspace/AgeMorph3D_tasks")
import lineref
W = "/workspace/"
T = W + "AgeMorph3D_tasks/"
ALIASES = {
    "RD-4": T + "RD-4_纵向数据备选.md",
    "v3": W + "AgeMorph3D_数据集方案_v3.md",
    "规划 v2": W + "AgeMorph3D_后续任务规划_v2.md",
    "RN-2_box数据清单.md": T + "RN-2_box数据清单.md",
    "清单": "docs/后续任务清单.md",
    "数据资源清单": "docs/数据资源清单.md",
    "实验协议": "docs/实验协议.md",
    "总规划": "docs/后续任务总规划.md",
    "baseline 协议": "docs/age-shape-baseline-v1.json",
}
REG = {
    ("RD-4", "19"): "KANFace 申请表",
    ("RD-4", "68"): "正好 70 岁的张数/人数",
    ("RD-4", "71"): "有条件（AgeDB 之外的优先备选）",
    ("RD-4", "79-80"): "Office of Innovation & Commercialization",
    ("RD-4", "80"): "Office of Innovation & Commercialization",
    ("RD-4", "87"): "具体非商业协议原文须在申请时取得",
    ("RD-4", "88"): "须由用户和导师权衡",
    ("RD-4", "141"): "正好 70 岁张数官网未公布",
    ("RD-4", "152"): "有条件，但本期按方案 v3「不采用」",
    ("v3", "9"): "70 岁端点要有精确标签",
    ("v3", "17-18"): "正好 70 岁 216 张",
    ("v3", "26"): "约 269 GB",
    ("v3", "31"): "36% 只是 IMDB-Clean 样本里框对不上的比例",
    ("v3", "105"): "DEX 又在 IMDB-WIKI 上预训练过",
    ("v3", "109-112"): "个人信息保护法（PIPL）",
    ("规划 v2", "68"): "B1 AgeDB 密码",
    ("RN-2_box数据清单.md", "91-92"): "/tmp/imdb_meta.tar",
    ("清单", "105"): "| T04 |",
    ("数据资源清单", "29"): "不能同时称作外部未见测试",
    ("实验协议", "20"): "正式执行依次固定",
    ("实验协议", "29"): "精确真实标签、区间及unknown分开",
    ("总规划", "186"): "不把区间中点当精确真实标签",
    ("baseline 协议", "50"): "finite 20-70 only",
}
n10 = lineref.check(text, ALIASES, REG, fail)
print(f"[10] 「第 N 行」引用核对通过 {n10} 处")

# [11] v1.3 第二轮答复：已关闭 / 仍待决
import re as _re
U = "【用户已确认 2026-11-21，经 Atlas 转达】"
_m = _re.search(r"^- \*\*Q-11.*$", text, _re.M)
_q11 = _m.group(0) if _m else ""
if "已关闭" not in _q11 or U not in _q11 or "AgeDB 仍只在用户本机处理" not in _q11:
    fail("Q-11 未按已关闭 + 用户确认标记写")
if "评审日期仍【建议/待确认】" not in _q11:
    fail("Q-11 未保留评审日期【建议/待确认】")
for old in ("**门槛未开的情形（纵向数据）**", "门槛未开时顺延？", "纵向数据仍走"):
    if old in text:
        fail(f"残留旧规则：{old}")
for need in ("门槛放开后的 TC 逻辑", "正常判定", "/workspace/datasets/", "AgeDB 不放进该目录", "不替用户选路线",
             "禁止再分发", "CC BY-NC-ND", "不进 Git", "BP-6 Q-12", "日期【建议/待确认】"):
    if need not in text:
        fail(f"v1.3 缺少：{need}")
for q in ("Q-1", "Q-3", "Q-4", "Q-7"):
    _m = _re.search(rf"^- \*\*{q}\*\*.*$", text, _re.M)
    if not _m or "已关闭" in _m.group(0):
        fail(f"{q} 应仍待决")
_v11 = text.index("- v1.1（"); _v12 = text.index("- v1.2（")
if not (_v11 < text.index("  10. §10 补存") < _v12 and _v11 < text.index("  另：§1.3") < _v12):
    fail("v1.1 条目未归位")
_dr10 = _re.search(r"^\| DR-10 \|.*$", text, _re.M)
if not _dr10 or "「我算法」" not in _dr10.group(0) or "经 Atlas 转达" not in _dr10.group(0):
    fail("DR-10 “用户本人即 A”未标来源")
if "【用户已确认 2026-11-21】" in text or "经 Atlas 转达给 Blueprint" not in text:
    fail("确认标记未标来源或缺定义")
print(f"[11] v1.3：Q-11 已关闭、TC 逻辑已改、Q-1/3/4/7 仍待决，确认标记 {text.count(U)} 处")

print("\n结果：", "PASS" if not failures else f"FAIL（{len(failures)} 项）")
sys.exit(0 if not failures else 1)
