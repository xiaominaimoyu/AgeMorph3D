#!/usr/bin/env python3
"""BP-3b G2 用例单自检（只读）。仓库文件一律通过 `git show 10f1918:<路径>` 从独立只读克隆读取，不读工作树，不写仓库。

检查：
  1. §1 条款编号唯一；每个条款至少映射到一个用例；§6 覆盖矩阵与各用例“对应验收条款”字段一致；
  2. 必需场景都有必选用例；
  3. 每个用例 10 个字段齐全且非空；签收栏为 B（王晋涛）联调 / A（宋明耀）核对；
  4. 全文每处〔路径:行号「原文」〕在 10f1918 该文件该行成立；〔@tasks 文件:行号「原文」〕在任务目录文件该行成立；
  5. 文中出现的接口路径都在 10f1918 的后端代码里；local-run 子命令/参数、pytest 用例名真实存在；
  6. §7 汇总表与用例顺序一致，必选数一致；固定提交声明存在；
  7. 附录 A/B 与 BP-3b_g2_ws.py、BP-3b_g2_console.js 一致。
退出码 0 = 全部通过。
"""
import re, subprocess, sys, collections

REPO, COMMIT = "/workspace/bp_ref/AgeMorph3D", "10f1918"
TASKS = "/workspace/AgeMorph3D_tasks"
DOC = f"{TASKS}/BP-3b_G2验收用例单.md"
HELPER = f"{TASKS}/BP-3b_g2_ws.py"
CONSOLE = f"{TASKS}/BP-3b_g2_console.js"
FIELDS = ["编号", "类别", "必选", "对应验收条款", "前置条件", "输入数据", "逐步操作", "期望结果", "证据文件名", "判定/签收"]
REQUIRED_CATS = ["严格加载", "协议", "无人脸", "多人脸", "单飞", "拒绝", "超限", "断线释放", "缺模型", "deadline",
                 "实体相机", "转头方向", "无人脸/多人脸恢复", "长时", "断开与重开", "重启", "语义", "环境记录"]
CASE_RE = r"G2-(?:ENV|WS|CAM|SUM)-\d{2}"
SIGN_HEADER = "| 执行人 | 执行时间（UTC+8） | 结果（通过/未通过/阻塞） | 签收 B（王晋涛，联调） | 签收 A（宋明耀，核对） | 备注 |"
failures = []


def fail(msg):
    failures.append(msg)
    print("  ✗", msg)


_cache = {}
def repo_lines(path):
    if path not in _cache:
        r = subprocess.run(["git", "-C", REPO, "show", f"{COMMIT}:{path}"], capture_output=True, text=True)
        _cache[path] = r.stdout.splitlines() if r.returncode == 0 else None
    return _cache[path]


def task_lines(name):
    try:
        return open(f"{TASKS}/{name}", encoding="utf-8").read().splitlines()
    except OSError:
        return None


def norm(s):
    return re.sub(r"\s+", "", s)


text = open(DOC, encoding="utf-8").read()
lines = text.splitlines()
body_text = text[: text.find("## 附录 A")]  # 附录是工具源码，不参与引用/接口扫描

# ---- 0. 固定提交 ----
r = subprocess.run(["git", "-C", REPO, "rev-parse", "--verify", f"{COMMIT}^{{commit}}"], capture_output=True, text=True)
if r.returncode != 0:
    fail(f"独立克隆中没有提交 {COMMIT}")
if f"固定提交（pinned）：`{COMMIT}`" not in text:
    fail("缺少固定提交声明")
print(f"[0] 固定提交 {COMMIT} = {r.stdout.strip()[:12]}")

# ---- 1. 条款 ----
clauses = []
in_s1 = False
for l in lines:
    if l.startswith("## 1."):
        in_s1 = True; continue
    if in_s1 and l.startswith("## "):
        break
    m = re.match(r"^\| (G2-C\d{2}) \|", l)
    if in_s1 and m:
        clauses.append(m.group(1))
print(f"[1] §1 条款数 = {len(clauses)}（不同 {len(set(clauses))}）")
if len(clauses) != len(set(clauses)) or not clauses:
    fail("§1 条款编号缺失或重复")
for l in lines:
    m = re.match(r"^\| (G2-C\d{2}) \| [^|]+ \| (.*) \|$", l)
    if m and "〔" not in m.group(2):
        fail(f"{m.group(1)} 来源栏没有文件+行号引用")

# ---- 2. 用例 ----
cases = collections.OrderedDict()
cur = None
for l in lines:
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
            fail(f"{cid} 缺字段：{f}"); continue
        v = m.group(1).strip()
        if f == "判定/签收":
            if SIGN_HEADER not in v:
                fail(f"{cid} 判定/签收栏不是 B（王晋涛）联调 / A（宋明耀）核对")
        elif not v:
            fail(f"{cid} 字段为空：{f}")
        vals[f] = v
    if vals.get("编号", "").strip() != cid:
        fail(f"{cid} 编号字段不一致")
    field_vals[cid] = vals
print(f"[3] 字段检查：{len(cases)} 个用例 × {len(FIELDS)} 个字段")

mandatory = collections.Counter()
for cid, v in field_vals.items():
    if v.get("必选", "").startswith("是"):
        mandatory[v.get("类别", "").strip()] += 1
for c in REQUIRED_CATS:
    if mandatory[c] < 1:
        fail(f"必需场景缺少必选用例：{c}")
print(f"[4] 必需场景 {len(REQUIRED_CATS)} 类，均有必选用例" if all(mandatory[c] for c in REQUIRED_CATS) else "[4] 必需场景有缺")

# ---- 3. 覆盖 ----
case_clauses = {cid: set(re.findall(r"G2-C\d{2}", v.get("对应验收条款", ""))) for cid, v in field_vals.items()}
matrix = {}
in_s6 = False
for l in lines:
    if l.startswith("## 6."):
        in_s6 = True; continue
    if in_s6 and l.startswith("## "):
        break
    m = re.match(r"^\| (G2-C\d{2}) \| (.*) \|$", l)
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
print(f"[5] 覆盖：{sum(1 for c in clauses if any(c in cs for cs in case_clauses.values()))}/{len(clauses)} 条款至少有 1 个用例")

# ---- 4. 汇总 ----
summary_ids = re.findall(rf"^\| ({CASE_RE}) \|", text[text.find("## 7."):text.find("## 8.")], re.M)
if list(summary_ids) != list(cases):
    fail(f"§7 汇总表与用例列表不一致：{set(cases) ^ set(summary_ids)}")
n_mand = sum(1 for v in field_vals.values() if v.get("必选", "").startswith("是"))
m = re.search(r"\| 必选用例数 / 通过数 / 未通过数 / 阻塞数 \| (\d+) /", text)
if not m or int(m.group(1)) != n_mand:
    fail(f"§7 必选用例数与实际不符（实际 {n_mand}）")
if f"{len(cases)} 个用例（{n_mand} 个必选" not in text:
    fail("修订记录中的用例数/必选数与实际不符")
print(f"[6] §7 汇总表 {len(summary_ids)} 行；必选 {n_mand}，可选 {len(cases) - n_mand}")

# ---- 5. 引用 ----
cites = re.findall(r"〔(?:@(tasks) )?([^〔〕:@]+):(\d+)「(.*?)」〕", body_text)
bad = 0
for scope, path, ln, snip in cites:
    src = task_lines(path) if scope else repo_lines(path)
    if src is None:
        fail(f"引用文件不存在：{'tasks/' if scope else COMMIT + ':'}{path}"); bad += 1; continue
    n = int(ln)
    if not (1 <= n <= len(src)) or norm(snip) not in norm(src[n - 1]):
        fail(f"引用不符：{path}:{ln}「{snip[:40]}」"); bad += 1
stray = re.findall(r"〔[^〕]*〕", body_text)
stray = [x for x in stray if not x.startswith(("〔路径:行号", "〔@tasks 文件名:行号"))]
if len(stray) != len(cites):
    fail(f"有 {len(stray) - len(cites)} 处〔〕不符合引用格式")
print(f"[7] 引用：{len(cites)} 处（仓库 {sum(1 for c in cites if not c[0])}，任务文档 {sum(1 for c in cites if c[0])}），涉及 {len({c[1] for c in cites})} 个文件，不符 {bad}")

# ---- 6. 接口与命令真实存在 ----
app = "\n".join(repo_lines("backend/src/agemorph3d/app.py") or [])
NON_REPO_OK = {"/research/ws"}  # B6 记录中的研究端点，本文只说明“不得使用”
paths = set(re.findall(r"(/(?:api|ws|research)/[A-Za-z_]+)", body_text))
for p in sorted(paths):
    if p in NON_REPO_OK:
        continue
    if f'"{p}' not in app:
        fail(f"接口路径不在 {COMMIT} 的 app.py：{p}")
lr = "\n".join(repo_lines("tools/local_run.py") or [])
for sub in set(re.findall(r"local-run\.ps1 (\w+)", body_text)):
    if f'"{sub}"' not in lr.split("choices=", 1)[-1].split(")", 1)[0]:
        fail(f"local-run 子命令不存在：{sub}")
for flag in set(re.findall(r"local-run\.ps1 \w+((?: --[a-z-]+(?: \$\w+)?)*)", body_text)):
    for f in re.findall(r"--[a-z-]+", flag):
        if f'"{f}"' not in lr:
            fail(f"local-run 参数不存在：{f}")
tests = "\n".join(repo_lines("backend/tests/test_realtime_api.py") or [])
for t in set(re.findall(r"test_realtime_api\.py::(\w+)", body_text)):
    if f"def {t}(" not in tests:
        fail(f"pytest 用例不存在：{t}")
ids = set(re.findall(r'getElementById\(\'(\w[\w-]*)\'\)', body_text))
html = "\n".join(repo_lines("frontend/index.html") or [])
for i in ids:
    if f'id="{i}"' not in html:
        fail(f"页面元素不存在：#{i}")
print(f"[8] 接口 {len(paths)} 个、local-run 命令、pytest 用例名、页面元素 {len(ids)} 个已核对")

# ---- 7. 附录 ----
for title, lang, path in (("附录 A", "python", HELPER), ("附录 B", "javascript", CONSOLE)):
    m = re.search(rf"## {title}.*?```{lang}\n(.*?)\n```", text, re.S)
    if not m or m.group(1) != open(path, encoding="utf-8").read().rstrip("\n"):
        fail(f"{title} 与 {path.rsplit('/', 1)[-1]} 不一致")
print("[9] 附录 A/B 与工具文件比对完成")

# [10] v1.1：Q 状态（Q-3 已关闭；Q-1 仍为【建议】30 分钟且待决；Q-2、Q-4—Q-7 待决）
U = "【用户已确认 2026-11-21，经 Atlas 转达】"
def _q(n):
    m = re.search(rf"^- \*\*Q-{n} .*$", text, re.M)
    return m.group(0) if m else ""
if not ("已关闭" in _q(3) and U in _q(3) and "在 `10f1918` 上执行" in _q(3)):
    fail("Q-3 未按已关闭 + 10f1918 + 用户确认标记写")
if not ("仍待决" in _q(1) and "【建议】30 分钟" in _q(1)) or "已关闭" in _q(1) or U in _q(1):
    fail("Q-1 应为【建议】30 分钟、仍待决")
for n in (2, 4, 5, 6, 7):
    if not _q(n) or "已关闭" in _q(n) or U in _q(n):
        fail(f"Q-{n} 应仍待决")
if "或写明差异并已重跑" in text or "G2 在此提交上执行**" + U not in text:
    fail("页首/G2-ENV-01 未改为固定在 10f1918 执行")
if "26 个用例（25 个必选" not in text:
    fail("用例总数表述缺失")
print("[10] Q-3 已关闭；Q-1（【建议】30 分钟）、Q-2、Q-4—Q-7 仍待决")

# v1.2（Sentinel MINOR-6）：切换规则标【建议】、git status 前置、RULES.md:14、FX-2 待决项
_q3s = re.search(r"^- \*\*Q-3.*$", text, re.M)
_q3s = _q3s.group(0) if _q3s else ""
for need in ("【建议】执行当天若 HEAD 不是 `10f1918`", "`git status --porcelain` 输出为空", "〔RULES.md:14「未确认本次精确文件清单前不执行Git操作」〕"):
    if need not in _q3s:
        fail(f"Q-3 切换规则缺：{need}")
_fx = re.search(r"^- \*\*Q-8 FX-2.*$", text, re.M)
if not _fx or "待用户决定" not in _fx.group(0) or "已关闭" in _fx.group(0):
    fail("缺 Q-8（FX-2 合入后执行提交）待决项")
if "【用户已确认 2026-11-21】" in text or "经 Atlas 转达给 Blueprint" not in text:
    fail("确认标记未标来源或缺定义")
print("[11] 切换规则【建议】+ git status 前置 + RULES.md:14；Q-8（FX-2）待决；标记带来源")

print()
print("结果：", "PASS" if not failures else f"FAIL（{len(failures)} 项）")
sys.exit(0 if not failures else 1)
