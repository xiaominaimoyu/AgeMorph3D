#!/usr/bin/env python3
"""BP-2 校验脚本（只读）。

核对 /workspace/AgeMorph3D_tasks/BP-2_开题报告提纲与证据索引.md：
 1. 模板标题清单与模板 docx（35c0cd6）一致，且 §3、§2 按顺序全覆盖；
 2. 仓库/任务文件行号引用及原文片段与 35c0cd6（任务文件取当前内容）一致；
 3. Word 文件引用的原文片段确实在提取文本中（.doc 需要 soffice，否则 SKIP）；
 4. RD-2 编号与翻译候选存在；
 5. 需写单元带【学生需自写】，他人/签名单元带对应标记；
 6. 长段落启发式（去掉引用片段、代码后，单行/单格汉字 ≤ 120）；
 7. 姓名只出现在引用片段内，或以已确认的角色写法“A（宋明耀…）/B（王晋涛…）”出现（v1.1）；反向对应失败；声明 UTC+8。
只用标准库；不写仓库、不联网、不删除文件（.doc 转换写入系统临时目录，结束后由 tempfile 清理）。
"""
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
import io
from pathlib import Path

REPO = Path("/workspace/AgeMorph3D")
COMMIT = "35c0cd61b70976393f919dfff34834bad9a67dc8"
REF_REPO = Path("/workspace/bp_ref/AgeMorph3D")  # v1.2：只读克隆，含 10f1918
UI_COMMIT = "10f1918"
DOC = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/workspace/AgeMorph3D_tasks/BP-2_开题报告提纲与证据索引.md")
RD2 = Path("/workspace/AgeMorph3D_tasks/RD-2_开题文献清单.md")
BP1 = Path("/workspace/AgeMorph3D_tasks/BP-1_里程碑重排与验收标准.md")
TEMPLATE = "docs/zip_extracted/2-开题报告模板.docx"
MAX_CJK = 120
NAMES = ["宋明耀", "王晋涛"]

# 模板顺序的映射单元：(单元, [必须出现在 §3 标题与 §2 覆盖行中的模板原文标签])
EXPECTED = [
    ("T01", ["毕业设计/论文开题报告"]),
    ("T02", ["题    目："]),
    ("T03", ["学生姓名："]),
    ("T04", ["学    号："]),
    ("T05", ["专    业："]),
    ("T06", ["年    级："]),
    ("T07", ["学    院："]),
    ("T08", ["指导教师（签名）："]),
    ("T09", ["完成时间："]),
    ("T10", ["西华大学计算机与软件工程学院制"]),
    ("T11", ["西华大学计算机与软件工程学院毕业设计（论文）", "开题报告"]),
    ("T12", ["专业"]),
    ("T13", ["题目"]),
    ("T14", ["学生"]),
    ("T15", ["学号"]),
    ("T16", ["指导教师"]),
    ("T17", ["工号"]),
    ("T18", ["选题的背景、意义、相关技术（研究）现状、可行性与经济性、实用性（创新性）"]),
    ("T19", ["1.1 选题的背景"]),
    ("T20", ["1.2 选题的意义"]),
    ("T21", ["1.3 相关技术（研究）现状"]),
    ("T22", ["1.4 可行性与经济性分析"]),
    ("T23", ["1.5实用性（创新性）"]),
    ("T24", ["设计（研究）的主要内容和预期目标"]),
    ("T25", ["2.1 设计（研究）的主要内容"]),
    ("T26", ["2.1.1团队任务"]),
    ("T27", ["2.1.2个人任务"]),
    ("T28", ["2.1.3 系统（或算法）架构图（组成图）及说明", "图2-1 系统组成图"]),
    ("T29", ["2.2 预期目标"]),
    ("T30", ["拟采用的设计（研究）方法、步骤"]),
    ("T31", ["3.1 系统（或算法）流程图及说明", "图3-1 系统流程图"]),
    ("T32", ["3.2 关键技术/算法步骤（不少于800字）"]),
    ("T33", ["3.3 UI设计"]),
    ("T34", ["3.3.1 设计理念"]),
    ("T35", ["3.3.2 拟设计的布局与操作"]),
    ("T36", ["参考文献"]),
    ("T37", ["进度安排", "起讫时间", "计划完成内容"]),
    ("T38", ["签名", "学生签名"]),
    ("T39", ["指导教师意见"]),
    ("T40", ["系部（开题小组）意见"]),
    ("T41", ["版本：2024.03", "注：不足部分可加页。"]),
]
TYPE_MARK = {"填写": "【学生需自写】", "自写": "【学生需自写】", "他人": "【他人填写】", "签名": "【学生本人签名】"}

errors, notes = [], []


def norm(s):
    return re.sub(r"\s+", "", s)


def git_show(path):
    r = subprocess.run(["git", "-C", str(REPO), "show", f"{COMMIT}:{path}"], capture_output=True)
    return r.stdout if r.returncode == 0 else None


def docx_paragraphs(data):
    xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode("utf-8")
    paras = []
    for chunk in re.split(r"</w:p>", xml):
        texts = re.findall(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>", chunk)
        if texts:
            t = "".join(texts)
            t = t.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
            paras.append(t)
    return paras


_doc_cache = {}


def binary_text(path):
    if path in _doc_cache:
        return _doc_cache[path]
    data = git_show(path)
    text = None
    if data is None:
        text = None
    elif path.endswith(".docx"):
        text = "\n".join(docx_paragraphs(data))
    elif path.endswith(".doc"):
        soffice = shutil.which("soffice") or shutil.which("libreoffice")
        if soffice:
            with tempfile.TemporaryDirectory() as td:
                src = Path(td) / "in.doc"
                src.write_bytes(data)
                subprocess.run([soffice, "--headless", "--convert-to", "txt:Text", "--outdir", td, str(src)],
                               capture_output=True, timeout=180)
                out = Path(td) / "in.txt"
                if out.exists():
                    text = out.read_text(encoding="utf-8", errors="replace")
        if text is None:
            text = "__SKIP__"
    _doc_cache[path] = text
    return text


_text_cache = {}


def text_lines(path):
    if path in _text_cache:
        return _text_cache[path]
    if path.startswith("@10f1918 "):
        r = subprocess.run(["git", "-C", str(REF_REPO), "show", f"{UI_COMMIT}:{path[len('@10f1918 '):]}"], capture_output=True)
        lines = r.stdout.decode("utf-8").splitlines() if r.returncode == 0 else None
    elif path.startswith("/workspace/"):
        p = Path(path)
        lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else None
    else:
        data = git_show(path)
        lines = data.decode("utf-8").splitlines() if data is not None else None
    _text_cache[path] = lines
    return lines


doc = DOC.read_text(encoding="utf-8")
lines = doc.splitlines()

# ---------- 1. 模板自检 ----------
tdata = git_show(TEMPLATE)
if tdata is None:
    errors.append("无法从 35c0cd6 读取模板")
    tparas = []
else:
    tparas = docx_paragraphs(tdata)
tall = norm("\n".join(tparas))
for unit, labels in EXPECTED:
    for lab in labels:
        if norm(lab) not in tall:
            errors.append(f"[模板] {unit} 标签不在模板中：{lab}")
exp_norm = {norm(l) for _, labs in EXPECTED for l in labs}
numbered = [p.strip() for p in tparas if re.match(r"^\d\.\d(\.\d)?\s*\S", p.strip())]
for h in numbered:
    if norm(h) not in exp_norm:
        errors.append(f"[模板] 模板编号小节未列入清单：{h}")
notes.append(f"模板编号小节 {len(numbered)} 个，全部在清单内" if all(norm(h) in exp_norm for h in numbered) else "")

# ---------- 2. §3 标题顺序与 §2 覆盖表 ----------
def section(start, end):
    a = next(i for i, l in enumerate(lines) if l.startswith(start))
    b = next(i for i, l in enumerate(lines) if l.startswith(end))
    return a, b

s2a, s2b = section("## 2.", "## 3.")
s3a, s3b = section("## 3.", "## 4.")
heads = [(i, l) for i, l in enumerate(lines[s3a:s3b], start=s3a) if l.startswith("### ")]
head_ids = [re.match(r"### (T\d\d)", l).group(1) for _, l in heads if re.match(r"### (T\d\d)", l)]
if head_ids != [u for u, _ in EXPECTED]:
    errors.append(f"[顺序] §3 单元顺序不符：{head_ids}")
cov = {}
for l in lines[s2a:s2b]:
    m = re.match(r"\| (T\d\d) \|", l)
    if m:
        cells = [c.strip() for c in l.strip().strip("|").split("|")]
        cov[m.group(1)] = cells
sections = {}
for k, (i, l) in enumerate(heads):
    end = heads[k + 1][0] if k + 1 < len(heads) else s3b
    sections[l.split()[1]] = (l, "\n".join(lines[i + 1:end]))
for unit, labels in EXPECTED:
    if unit not in sections:
        errors.append(f"[覆盖] §3 缺 {unit}")
        continue
    h = norm(sections[unit][0])
    for lab in labels:
        if norm(lab).rstrip("：") not in h:
            errors.append(f"[覆盖] {unit} 标题缺模板原文：{lab}")
    if unit not in cov:
        errors.append(f"[覆盖] §2 覆盖表缺 {unit}")
    else:
        row = norm("|".join(cov[unit]))
        for lab in labels:
            if norm(lab).rstrip("：").rstrip("。") not in row:
                errors.append(f"[覆盖] §2 {unit} 行缺模板原文：{lab}")

# ---------- 5. 标记 ----------
type_count = {}
for unit, _ in EXPECTED:
    if unit not in cov or unit not in sections:
        continue
    typ = cov[unit][3]
    type_count[typ] = type_count.get(typ, 0) + 1
    body = sections[unit][1]
    mark = TYPE_MARK.get(typ)
    if mark and mark not in body:
        errors.append(f"[标记] {unit}（{typ}）缺 {mark}")
    if typ == "固定" and "【学生需自写】" in body:
        errors.append(f"[标记] {unit} 为固定文字却标了【学生需自写】")

# ---------- 3/4. 引用 ----------
cit_re = re.compile(r"〔([^〔〕「」]+?)「(.+?)」〕")
all_brackets = re.findall(r"〔[^〔〕]*〕", doc)
cits = cit_re.findall(doc)
if len(all_brackets) != len(cits):
    bad = [b for b in all_brackets if not cit_re.fullmatch(b)]
    errors.append(f"[引用] 格式不合规：{bad[:5]}")
stat = {"repo_line": 0, "ui_10f1918": 0, "task_line": 0, "word": 0, "word_skip": 0}
for target, anchor in cits:
    m = re.match(r"^(.*?):(\d+)(?:-(\d+))?$", target)
    a = norm(anchor)
    if m:
        path, l1 = m.group(1), int(m.group(2))
        l2 = int(m.group(3)) if m.group(3) else l1
        tl = text_lines(path)
        if tl is None:
            errors.append(f"[引用] 文件不存在：{path}")
            continue
        if not (1 <= l1 <= l2 <= len(tl)):
            errors.append(f"[引用] 行号越界：{target}")
            continue
        seg = norm("".join(tl[l1 - 1:l2]))
        if a not in seg:
            errors.append(f"[引用] 片段不在所引行：{target}「{anchor}」")
        stat["task_line" if path.startswith("/workspace/") else ("ui_10f1918" if path.startswith("@10f1918 ") else "repo_line")] += 1
    else:
        path = target
        if not (path.endswith(".docx") or path.endswith(".doc")):
            errors.append(f"[引用] 文本文件缺行号：{target}")
            continue
        t = binary_text(path)
        if t is None:
            errors.append(f"[引用] Word 文件不存在：{path}")
        elif t == "__SKIP__":
            stat["word_skip"] += 1
        elif a not in norm(t):
            errors.append(f"[引用] 片段不在 Word 文件：{path}「{anchor}」")
        else:
            stat["word"] += 1

# ---------- RD-2 编号 ----------
rd2 = RD2.read_text(encoding="utf-8")
rd2_ids = set(re.findall(r"^#### (\d+)\.", rd2, re.M)) | set(re.findall(r"\*\*(30[ab])\.", rd2))
rd2_tr = set(re.findall(r"^\| ([AB]\d)", rd2, re.M))
used = set(re.findall(r"RD-2#(\d+[ab]?)", doc))
used_tr = set(re.findall(r"RD-2·([AB]\d)", doc))
for u in sorted(used):
    if u not in rd2_ids:
        errors.append(f"[RD-2] 编号不存在：RD-2#{u}")
for u in sorted(used_tr):
    if u not in rd2_tr:
        errors.append(f"[RD-2] 翻译候选不存在：RD-2·{u}")

# ---------- BP-1 阶段检查点编号 ----------
bp1 = BP1.read_text(encoding="utf-8")
for sid in sorted(set(re.findall(r"\bS\d-\d+\b", doc))):
    if sid not in bp1:
        errors.append(f"[BP-1] 检查点编号不存在：{sid}")

# ---------- 6. 长段落启发式 / 7. 姓名 ----------
def strip_quoted(s):
    s = re.sub(r"〔[^〔〕]*〕", "", s)
    s = re.sub(r"「[^「」]*」", "", s)
    s = re.sub(r"“[^”]*”", "", s)
    s = re.sub(r"`[^`]*`", "", s)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    return s

max_seen, in_code = 0, False
for no, l in enumerate(lines, 1):
    if l.startswith("```"):
        in_code = not in_code
        continue
    if in_code:
        continue
    parts = l.strip().strip("|").split("|") if l.lstrip().startswith("|") else [l]
    for p in parts:
        n = len(re.findall(r"[\u4e00-\u9fff]", strip_quoted(p)))
        max_seen = max(max_seen, n)
        if n > MAX_CJK:
            errors.append(f"[长段落] 第 {no} 行有 {n} 个汉字（去引用后）")
    bare = strip_quoted(l)
    # v1.1：用户 2026-11-21 确认 A=宋明耀、B=王晋涛。只允许“角色A（宋明耀…）/A（宋明耀）/角色B（王晋涛…）/B（王晋涛）”形式；反向对应即失败
    if re.search(r"(?:角色)?A（王晋涛|(?:角色)?B（宋明耀", bare):
        errors.append(f"[姓名] 第 {no} 行出现与用户确认相反的角色对应")
    allowed = re.sub(r"(?:角色)?A（宋明耀[^）]*）|(?:角色)?B（王晋涛[^）]*）", "", bare)
    for nm in NAMES:
        if nm in allowed:
            errors.append(f"[姓名] 第 {no} 行在引用片段和已确认角色写法之外出现姓名")
if "UTC+8" not in "\n".join(lines[:12]):
    errors.append("[时区] 文首未声明 UTC+8")

# ---------- v1.2：T34/T35 改钉 10f1918（【建议】）、Q11 仍待确认 ----------
_t34 = doc[doc.index("### T34"):doc.index("### T35")] if "### T34" in doc and "### T35" in doc else ""
_t35 = doc[doc.index("### T35"):doc.index("### T36")] if "### T35" in doc and "### T36" in doc else ""
if not _t34 or not _t35:
    errors.append("[v1.2] 找不到 T34/T35 段")
else:
    for name, seg in (("T34", _t34), ("T35", _t35)):
        live = [c for c in re.findall(r"〔([^〔〕「」]+?)「", seg) if c.startswith("frontend/src/layout.ts")]
        if name == "T35" and live:
            errors.append(f"[v1.2] T35 仍引用 35c0cd6 的 layout.ts：{live}")
        if name == "T34" and (len(live) != 1 or "只在 `35c0cd6`，`10f1918` 已删除" not in seg):
            errors.append("[v1.2] T34 的 layout.ts 引用须只剩一条并注明已删除")
        if "〔@10f1918 " not in seg:
            errors.append(f"[v1.2] {name} 缺 @10f1918 引用")
    if "【建议】改钉 `10f1918`" not in _t35 or "Q11 尚未询问用户，仍待确认" not in _t35:
        errors.append("[v1.2] T35 注意未写【建议】与 Q11 待确认")
_q11 = re.search(r"^11\. \*\*Q11.*$", doc, re.M)
if not _q11 or "仍待确认" not in _q11.group(0) or "已关闭" in _q11.group(0):
    errors.append("[v1.2] Q11 须仍为待确认")
if "全计 68 点含不可见点" not in doc:
    errors.append("[v1.2] 评价口径未同步 NME 全计 68 点")

# ---------- v1.3：Sentinel 11-21 MINOR ----------
_rdrow = [l for l in lines if l.startswith("| RD-2（")]
if len(_rdrow) != 1 or "更保守" in doc.split("## 8. 修订记录")[0] or "B = 王晋涛（用户本人 2026-11-21 确认）" not in _rdrow[0]:
    errors.append("[v1.3] §4 RD-2 行须引现行 B 确认原文，且不得再写“更保守”")
for need in ("「是，B 是王晋涛，负责系统」", "「第二位组员王晋涛，我算法，王晋涛系统」", "「我算法」", "经 Radar 转达",
             "FX-2_说明.md:18", "按【建议】改钉", "【用户已确认 2026-11-21，经 Atlas 转达】：用户本人答复、经 Atlas 转达"):
    if need not in doc:
        errors.append(f"[v1.3] 缺少：{need}")
if "【用户已确认 2026-11-21】" in doc:
    errors.append("[v1.3] 残留未标来源的确认标记")

# ---------- 输出 ----------
print("BP-2 verify @", COMMIT[:7])
print(f"映射单元 {len(EXPECTED)}；§3 标题 {len(head_ids)}；§2 覆盖行 {len(cov)}")
print("类型计数：", "、".join(f"{k}{v}" for k, v in sorted(type_count.items())))
print(f"引用：仓库行号 {stat['repo_line']}（35c0cd6）+ {stat['ui_10f1918']}（@10f1918），任务文件行号 {stat['task_line']}，Word 片段 {stat['word']}，Word 跳过 {stat['word_skip']}")
print(f"RD-2 编号 {len(used)} 个、翻译候选 {len(used_tr)} 个均已核对")
print(f"最长单行/单格汉字数（去引用后）：{max_seen}（上限 {MAX_CJK}）")
for n in notes:
    if n:
        print(n)
if errors:
    print(f"FAIL：{len(errors)} 项")
    for e in errors:
        print(" -", e)
    sys.exit(1)
print("PASS")
