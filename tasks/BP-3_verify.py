#!/usr/bin/env python3
"""BP-3 用例单自检（只读）。仓库文件一律通过 `git show <提交>:<路径>` 从独立只读克隆读取，不读工作树，不写仓库。
v1.2（2026-11-21）：普通引用须在 35c0cd6 与 10f1918 两版都成立；〔@提交 路径:行号「原文」〕只核对该提交；
工作台旧文案只允许出现在 §5.3.0 对照表与修订记录。

检查：
  1. §1 中每个 G1 条款至少映射到一个用例；§6 覆盖矩阵与各用例“对应验收条款”字段一致；
  2. 九类必需场景都有用例；
  3. 每个用例 10 个字段齐全且非空；
  4. 全文每处〔路径:行号「原文」〕的原文出现在 35c0cd6 与 10f1918 该文件该行（空白归一化后子串匹配）；
     〔@提交 …〕只核对所标提交；
  6. 工作台旧文案（35c0cd6 界面）不出现在 §5.3.0 与修订记录以外；
  5. 附录 A 代码块与 BP-3_g1_check.py 一致。
退出码 0 = 全部通过。
"""
import re, subprocess, sys, collections

REPO = "/workspace/bp_ref/AgeMorph3D"  # 独立只读克隆，含 35c0cd6 与 10f1918
BASE_COMMIT, UI_COMMIT = "35c0cd6", "10f1918"
COMMITS = (BASE_COMMIT, UI_COMMIT)
DOC = "/workspace/AgeMorph3D_tasks/BP-3_G1验收用例单.md"
HELPER = "/workspace/AgeMorph3D_tasks/BP-3_g1_check.py"
FIELDS = ["编号", "类别", "必选", "对应验收条款", "前置条件", "输入数据", "逐步操作", "期望结果", "证据文件名", "判定/签收"]
REQUIRED_CATS = ["环境记录", "多身份", "多姿态", "无人脸", "多人脸", "坏图", "取消", "过期", "导出再导入"]
CASE_RE = r"G1-(?:ENV|ID|UI|NF|MF|BAD|EXP|CAN|EXPIRE|SUM)-\d{2}"
failures = []


def fail(msg):
    failures.append(msg)
    print("  ✗", msg)


_cache = {}
def repo_lines(path, commit):
    key = (commit, path)
    if key not in _cache:
        r = subprocess.run(["git", "-C", REPO, "show", f"{commit}:{path}"], capture_output=True, text=True)
        _cache[key] = r.stdout.splitlines() if r.returncode == 0 else None
    return _cache[key]


def norm(s):
    return re.sub(r"\s+", "", s)


text = open(DOC, encoding="utf-8").read()
lines = text.splitlines()

# ---- 条款 ----
clauses = []
in_s1 = False
for l in lines:
    if l.startswith("## 1."):
        in_s1 = True; continue
    if in_s1 and l.startswith("## "):
        break
    m = re.match(r"^\| (G1-C\d{2}) \|", l)
    if in_s1 and m:
        clauses.append(m.group(1))
print(f"[1] §1 条款数 = {len(clauses)}（不同 {len(set(clauses))}）")
if len(clauses) != len(set(clauses)) or not clauses:
    fail("§1 条款编号缺失或重复")

# ---- 用例切分 ----
cases = collections.OrderedDict()
cur = None
for i, l in enumerate(lines):
    m = re.match(rf"^### ({CASE_RE})\b", l)
    if m:
        cur = m.group(1)
        if cur in cases:
            fail(f"用例编号重复：{cur}")
        cases[cur] = []
        continue
    if cur and (l.startswith("### ") or l.startswith("## ")):
        cur = None
    if cur:
        cases[cur].append(l)
print(f"[2] 用例数 = {len(cases)}")

field_vals = {}
for cid, body in cases.items():
    blob = "\n".join(body)
    vals = {}
    for f in FIELDS:
        m = re.search(rf"^- \*\*{re.escape(f)}\*\*：(.*?)(?=^- \*\*|\Z)", blob, re.S | re.M)
        if not m:
            fail(f"{cid} 缺字段：{f}")
            continue
        v = m.group(1).strip()
        if f == "判定/签收":
            ok = "| 执行人 |" in v and "签收 B" in v and "签收 A" in v
            if not ok:
                fail(f"{cid} 判定/签收栏不完整")
        elif not v:
            fail(f"{cid} 字段为空：{f}")
        vals[f] = v
    if vals.get("编号") and vals["编号"].strip() != cid:
        fail(f"{cid} 编号字段不一致：{vals['编号']}")
    field_vals[cid] = vals
print(f"[3] 字段检查：{len(cases)} 个用例 × {len(FIELDS)} 个字段")

# ---- 类别 ----
cat_count = collections.Counter()
mandatory = collections.Counter()
for cid, v in field_vals.items():
    cat = v.get("类别", "").strip()
    cat_count[cat] += 1
    if v.get("必选", "").startswith("是"):
        mandatory[cat] += 1
print("[4] 类别分布：", dict(cat_count))
for c in REQUIRED_CATS:
    if mandatory[c] < 1:
        fail(f"必需场景缺少必选用例：{c}")

# ---- 覆盖 ----
case_clauses = {cid: set(re.findall(r"G1-C\d{2}", v.get("对应验收条款", ""))) for cid, v in field_vals.items()}
matrix = {}
in_s6 = False
for l in lines:
    if l.startswith("## 6."):
        in_s6 = True; continue
    if in_s6 and l.startswith("## "):
        break
    m = re.match(r"^\| (G1-C\d{2}) \| (.*) \|$", l)
    if in_s6 and m:
        matrix[m.group(1)] = set(re.findall(CASE_RE, m.group(2)))
for c in clauses:
    by_cases = {cid for cid, cs in case_clauses.items() if c in cs}
    if not by_cases:
        fail(f"条款无用例覆盖：{c}")
    if c not in matrix:
        fail(f"覆盖矩阵缺条款：{c}")
    elif matrix[c] != by_cases:
        fail(f"覆盖矩阵与用例字段不一致：{c} 矩阵={sorted(matrix[c])} 用例={sorted(by_cases)}")
unknown = {x for cs in case_clauses.values() for x in cs} - set(clauses)
if unknown:
    fail(f"用例引用了未定义条款：{sorted(unknown)}")
for c, cs in matrix.items():
    for cid in cs:
        if cid not in cases:
            fail(f"覆盖矩阵引用不存在的用例：{c} → {cid}")
print(f"[5] 覆盖：{sum(1 for c in clauses if any(c in cs for cs in case_clauses.values()))}/{len(clauses)} 条款至少有 1 个用例")

# ---- 汇总表 ----
summary_ids = re.findall(rf"^\| ({CASE_RE}) \|", text[text.find("## 7."):text.find("## 8.")], re.M)
if list(summary_ids) != list(cases):
    fail(f"§7 汇总表与用例列表不一致：{set(cases) ^ set(summary_ids)}")
n_mand = sum(1 for v in field_vals.values() if v.get("必选", "").startswith("是"))
m = re.search(r"\| 必选用例数 / 通过数 / 未通过数 / 阻塞数 \| (\d+) /", text)
if not m or int(m.group(1)) != n_mand:
    fail(f"§7 必选用例数与实际不符（实际 {n_mand}）")
print(f"[6] §7 汇总表 {len(summary_ids)} 行；必选 {n_mand}")

# ---- 引用 ----
cites = re.findall(r"〔(?:@([0-9a-f]{7,40}) )?([^〔〕:@]+):(\d+)「(.*?)」〕", text)
bad = 0
pinned = collections.Counter()
for commit, path, ln, snip in cites:
    targets = (commit,) if commit else COMMITS
    if commit and commit not in COMMITS:
        fail(f"引用标了未知提交：@{commit}"); bad += 1; continue
    pinned[commit or "两版"] += 1
    for cm in targets:
        src = repo_lines(path, cm)
        if src is None:
            fail(f"引用文件在 {cm} 不存在：{path}"); bad += 1; break
        n = int(ln)
        if not (1 <= n <= len(src)) or norm(snip) not in norm(src[n - 1]):
            fail(f"引用不符（{cm}）：{path}:{ln}「{snip[:40]}」"); bad += 1; break
examples = ("〔路径:行号", "〔@10f1918 路径:行号", "〔@35c0cd6 路径:行号")
stray = [x for x in re.findall(r"〔[^〕]*〕", text) if not x.startswith(examples)]  # 说明格式本身的示例不算引用
if len(stray) != len(cites):
    fail(f"有 {len(stray) - len(cites)} 处〔〕不符合 路径:行号「原文」 格式")
print(f"[7] 引用：{len(cites)} 处（两版均核 {pinned['两版']}，仅 10f1918 {pinned['10f1918']}，仅 35c0cd6 {pinned['35c0cd6']}），涉及 {len({c[1] for c in cites})} 个文件，不符 {bad}")

# ---- 工作台旧文案 ----
OLD_UI = ["¾ 侧面", "取消当前任务", "正在生成三维模型", "STANDARD HEAD", "LOCAL MODEL", "恢复至 30 岁", "恢复源年龄",
          "将人像照片拖放至此", "标准人脸模型", "导出三维模型 GLB", "保存效果图 PNG", "年龄对比", "照片拍摄时年龄",
          "可以旋转查看与导出", "已取消当前重建任务", "静态重建模型已导出", "重建已取消，可调整输入后重试", "layout.ts:"]
def strip_allowed(t):
    a = t.find("### 5.3.0"); b = t.find("### G1-UI-01")
    t = t[:a] + t[b:] if 0 <= a < b else t
    return "\n".join(l for l in t.splitlines() if not l.startswith("| v1"))  # 修订记录行
body = strip_allowed(text)
left = [w for w in OLD_UI if w in body]
if "### 5.3.0" not in text:
    fail("缺 §5.3.0 新旧界面对照")
if left:
    fail(f"§5.3.0 与修订记录以外仍有旧界面文案：{left}")
for sel in ("frontend/src/main.ts", "frontend/index.html"):
    if any(p == sel and not c for c, p, _, _ in cites):
        fail(f"{sel} 的引用须标 @提交")
print(f"[9] 工作台旧文案检查：{len(OLD_UI)} 项，残留 {len(left)}")

# ---- 附录 A ----
m = re.search(r"## 附录 A.*?```python\n(.*?)\n```", text, re.S)
helper = open(HELPER, encoding="utf-8").read().rstrip("\n")
if not m or m.group(1) != helper:
    fail("附录 A 与 BP-3_g1_check.py 不一致")
else:
    print("[8] 附录 A 与 BP-3_g1_check.py 一致")

# ---- [10] v1.3：Q-3 已关闭，执行提交 10f1918 ----
U = "【用户已确认 2026-11-21，经 Atlas 转达】"
_q3 = re.search(r"^- \*\*Q-3.*$", text, re.M)
_q3 = _q3.group(0) if _q3 else ""
if "已关闭" not in _q3 or U not in _q3 or "在 `10f1918` 上执行" not in _q3:
    fail("Q-3 未按已关闭 + 10f1918 + 用户确认标记写")
_head = "\n".join(text.splitlines()[:8])
if "执行提交号仍待用户决定" in text or "在 `10f1918` 上执行" not in _head:
    fail("页首未写明 G1 在 10f1918 上执行")
if "| 与 35c0cd6 的差异 |" in text or "| 是否为 10f1918 |" not in text:
    fail("环境记录未改为核对 10f1918")
if "（若 Q-3 决定在旧提交执行）" in text:
    fail("§5.3.0 表头仍按 Q-3 待决写")
print("[10] Q-3 已关闭，执行提交 10f1918（页首、环境记录、§5.3.0、§8 一致）")

# v1.4（Sentinel MINOR-6）：切换规则标【建议】、git status 前置、RULES.md:14、FX-2 待决项
_q3s = re.search(r"^- \*\*Q-3.*$", text, re.M)
_q3s = _q3s.group(0) if _q3s else ""
for need in ("【建议】执行当天若 HEAD 不是 `10f1918`", "`git status --porcelain` 输出为空", "〔RULES.md:14「未确认本次精确文件清单前不执行Git操作」〕"):
    if need not in _q3s:
        fail(f"Q-3 切换规则缺：{need}")
_fx = re.search(r"^- \*\*Q-9 FX-2.*$", text, re.M)
if not _fx or "待用户决定" not in _fx.group(0) or "已关闭" in _fx.group(0):
    fail("缺 Q-9（FX-2 合入后执行提交）待决项")
if "【用户已确认 2026-11-21】" in text or "经 Atlas 转达给 Blueprint" not in text:
    fail("确认标记未标来源或缺定义")
print("[11] 切换规则【建议】+ git status 前置 + RULES.md:14；Q-9（FX-2）待决；标记带来源")

print()
print("结果：", "PASS" if not failures else f"FAIL（{len(failures)} 项）")
sys.exit(0 if not failures else 1)
