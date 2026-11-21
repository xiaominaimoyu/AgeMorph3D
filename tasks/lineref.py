"""「第 N 行」写法引用核对（BP-5、BP-6 自检共用；只读，不联网）。

做法：
  - 找出正文里每一处「第 N 行」「第 N—M 行」「第 N、M 行」；
  - 在它前面 40 个字符内找最靠后（并列时取最长）的已知别名，确定被引文件；
  - 每个 (别名, 行号/行段) 必须在登记表里有一条“该行应含的关键词”，
    关键词须出现在该行（行段则任一行）中；未解析或未登记的引用一律记为失败。
仓库文件用 git show 35c0cd6 读取，工作区文件直接读。
"""
import re, subprocess

REPO, COMMIT = "/workspace/AgeMorph3D", "35c0cd6"
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


PAT = re.compile(r"第\s*(\d+(?:\s*[—–\-、，,和与及]\s*\d+)*)\s*行")


def check(text, aliases, registry, fail):
    """aliases: {别名: 路径}；registry: {(别名, 'N' 或 'N-M'): 关键词}。返回核对条数。"""
    n_ok = 0
    names = sorted(aliases, key=len, reverse=True)
    for m in PAT.finditer(text):
        win = text[max(0, m.start() - 40):m.start()]
        best = None
        for a in names:
            p = win.rfind(a)
            if p >= 0:
                end = p + len(a)
                if best is None or end > best[1] or (end == best[1] and len(a) > len(best[0])):
                    best = (a, end)
        lineno = text.count("\n", 0, m.start()) + 1
        if best is None:
            fail(f"文档第 {lineno} 行：「{m.group(0)}」无法确定被引文件"); continue
        alias = best[0]
        spec = m.group(1)
        if "—" in spec or "–" in spec or re.search(r"\d\s*-\s*\d", spec):
            a, b = [int(x) for x in re.findall(r"\d+", spec)[:2]]
            items = [(f"{a}-{b}", range(a, b + 1))]
        else:
            items = [(x, [int(x)]) for x in re.findall(r"\d+", spec)]
        fl = file_lines(aliases[alias])
        if fl is None:
            fail(f"无法读取 {aliases[alias]}"); continue
        for key, rng in items:
            needle = registry.get((alias, key))
            if needle is None:
                fail(f"文档第 {lineno} 行：{alias} 第 {key} 行未登记关键词"); continue
            if max(rng) > len(fl):
                fail(f"{alias} 第 {key} 行越界"); continue
            if not any(norm(needle) in norm(fl[i - 1]) for i in rng):
                fail(f"{alias} 第 {key} 行不含「{needle}」")
            else:
                n_ok += 1
    return n_ok
