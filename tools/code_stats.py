"""Read-only physical-line and git-author statistics for L03.

Counts lines in the git tree and sums commit numstat. It does not map a git
author to member A or B unless a mapping file says so, and it does not treat
line counts as original contribution or as a school acceptance.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath

AREAS = ("frontend", "backend", "preprocessing", "tools", "tests", "docs")
IGNORED_ROOTS = ("output", "logs")
PER_PERSON = 1500
PER_PROJECT = 4500
READ_ONLY_GIT = frozenset({"rev-parse", "ls-tree", "cat-file", "log", "status"})
DISCLAIMER = (
    "物理行数不证明个人原创贡献。注释、空行、测试、文档、生成文件和历史新增行"
    "都不是学校计数或个人工作量。1500 行/人与 4500 行/项目只作信息对照。"
)


class CodeStatsError(Exception):
    def __init__(self, code: str, detail: str, exit_code: int = 1) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.exit_code = exit_code


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def classify_path(path: str) -> str:
    """Separate tests from product areas. Do not assign a directory to a person."""
    pure = PurePosixPath(path.replace("\\", "/"))
    parts = pure.parts
    name = pure.name
    if "tests" in parts or name.startswith("test_") or name.endswith("_test.py"):
        return "tests"
    if ".test." in name or ".spec." in name:
        return "tests"
    if parts and parts[0] in AREAS and parts[0] != "tests":
        return parts[0]
    return "other"


def git_read(root: Path, args: Sequence[str], *, text: bool = False) -> subprocess.CompletedProcess:
    if not args or args[0] not in READ_ONLY_GIT:
        raise CodeStatsError("GIT_WRITE_FORBIDDEN", "代码统计只运行只读 git 命令。", 1)
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=text,
    )


def _require_repo(root: Path) -> str:
    completed = git_read(root, ["rev-parse", "--verify", "HEAD"], text=True)
    if completed.returncode != 0:
        raise CodeStatsError("NOT_A_REPOSITORY", "当前目录没有可读取的 git 提交。", 1)
    return completed.stdout.strip()


def _list_blobs(root: Path, revision: str) -> list[tuple[str, str]]:
    completed = git_read(root, ["ls-tree", "-r", "-z", revision])
    if completed.returncode != 0:
        raise CodeStatsError("GIT_READ_FAILED", "无法列出该提交中的文件。", 1)
    blobs = []
    for record in completed.stdout.split(b"\0"):
        if not record:
            continue
        meta, _, path = record.partition(b"\t")
        mode, kind, blob = meta.split(b" ")
        if kind != b"blob" or mode == b"160000":
            continue
        blobs.append((blob.decode("ascii"), path.decode("utf-8", "surrogateescape")))
    return blobs


def _cat_blobs(root: Path, blobs: Sequence[tuple[str, str]]) -> dict[str, bytes]:
    if not blobs:
        return {}
    process = subprocess.Popen(
        ["git", "-C", str(root), "cat-file", "--batch"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    assert process.stdin is not None and process.stdout is not None
    for blob, _path in blobs:
        process.stdin.write(f"{blob}\n".encode())
    process.stdin.close()
    contents: dict[str, bytes] = {}
    for _blob, path in blobs:
        header = process.stdout.readline()
        if not header:
            raise CodeStatsError("GIT_READ_FAILED", "读取文件内容时 git 提前结束。", 1)
        _oid, kind, size_text = header.decode("ascii").split()
        size = int(size_text)
        data = process.stdout.read(size)
        newline = process.stdout.read(1)
        if kind != "blob" or len(data) != size or newline != b"\n":
            raise CodeStatsError("GIT_READ_FAILED", "git 返回的文件内容长度不一致。", 1)
        contents[path] = data
    process.wait()
    if process.returncode != 0:
        raise CodeStatsError("GIT_READ_FAILED", "git cat-file 没有成功结束。", 1)
    return contents


def physical_lines(data: bytes) -> int | None:
    if b"\0" in data:
        return None
    return len(data.splitlines())


def tree_lines(root: Path, revision: str) -> dict[str, object]:
    blobs = _list_blobs(root, revision)
    contents = _cat_blobs(root, blobs)
    areas = {area: {"files": 0, "physical_lines": 0} for area in (*AREAS, "other")}
    binary = []
    for path, data in contents.items():
        area = classify_path(path)
        lines = physical_lines(data)
        if lines is None:
            binary.append(path)
            continue
        bucket = areas[area]
        bucket["files"] = int(bucket["files"]) + 1
        bucket["physical_lines"] = int(bucket["physical_lines"]) + lines
    scoped = sum(int(areas[area]["physical_lines"]) for area in AREAS)
    other = int(areas["other"]["physical_lines"])
    return {
        "areas": areas,
        "binary_files": binary,
        "binary_file_count": len(binary),
        "scoped_physical_lines": scoped,
        "other_physical_lines": other,
        "tracked_text_physical_lines": scoped + other,
    }


def _empty_author() -> dict[str, object]:
    return {
        "commits": 0,
        "merge_commits": 0,
        "non_merge_commits": 0,
        "lines_added": 0,
        "lines_deleted": 0,
        "binary_changes": 0,
        "by_area": {area: {"added": 0, "deleted": 0} for area in (*AREAS, "other")},
    }


def history_by_author(root: Path, revision: str) -> list[dict[str, object]]:
    completed = git_read(
        root,
        ["log", revision, "--pretty=format:%x1e%H%x1f%aN%x1f%aE%x1f%P", "--numstat"],
    )
    if completed.returncode != 0:
        raise CodeStatsError("GIT_READ_FAILED", "无法读取提交历史。", 1)
    authors: dict[str, dict[str, object]] = {}
    records = completed.stdout.split(b"\x1e")
    for record in records:
        if not record.strip():
            continue
        header, _, body = record.partition(b"\n")
        parts = header.decode("utf-8", "surrogateescape").split("\x1f")
        if len(parts) != 4:
            raise CodeStatsError("GIT_HISTORY_UNREADABLE", "提交头无法解析。", 1)
        _commit, name, email, parents = parts
        identity = f"{name} <{email}>"
        stats = authors.setdefault(identity, _empty_author())
        stats["commits"] = int(stats["commits"]) + 1
        parent_count = len([item for item in parents.split(" ") if item])
        if parent_count > 1:
            stats["merge_commits"] = int(stats["merge_commits"]) + 1
            continue
        stats["non_merge_commits"] = int(stats["non_merge_commits"]) + 1
        for line in body.splitlines():
            if not line.strip():
                continue
            added, deleted, path = line.decode("utf-8", "surrogateescape").split("\t", 2)
            if added == "-" or deleted == "-":
                stats["binary_changes"] = int(stats["binary_changes"]) + 1
                continue
            area = classify_path(path)
            by_area = stats["by_area"]
            assert isinstance(by_area, dict)
            bucket = by_area[area]
            bucket["added"] += int(added)
            bucket["deleted"] += int(deleted)
            stats["lines_added"] = int(stats["lines_added"]) + int(added)
            stats["lines_deleted"] = int(stats["lines_deleted"]) + int(deleted)
    rows = []
    for identity, stats in authors.items():
        rows.append({"git_author": identity, "member": None, **stats})
    rows.sort(key=lambda item: (-int(item["commits"]), str(item["git_author"])))
    return rows


def load_mapping(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CodeStatsError("MAPPING_UNREADABLE", "作者映射文件无法读取。", 1) from error
    if not isinstance(loaded, dict) or set(loaded) - {"schema_version", "authors", "note"}:
        raise CodeStatsError(
            "MAPPING_INVALID", "作者映射只接受 schema_version、authors 和 note。", 1
        )
    if loaded.get("schema_version") != 1 or not isinstance(loaded.get("authors"), list):
        raise CodeStatsError(
            "MAPPING_INVALID", "作者映射的 schema_version 必须是 1，authors 必须是列表。", 1
        )
    mapping: dict[str, str] = {}
    for item in loaded["authors"]:
        if not isinstance(item, dict) or set(item) - {"git_author", "member"}:
            raise CodeStatsError("MAPPING_INVALID", "每个作者只填写 git_author 和 member。", 1)
        author = item.get("git_author")
        member = item.get("member")
        if not isinstance(author, str) or not isinstance(member, str):
            raise CodeStatsError("MAPPING_INVALID", "git_author 和 member 必须是字符串。", 1)
        if author == "" and member == "":
            continue
        if author == "" or member == "":
            raise CodeStatsError(
                "MAPPING_INCOMPLETE",
                "已填写的作者必须同时有 git_author 和 member。空行请整行留空，不要猜测。",
                1,
            )
        if member not in {"A", "B"}:
            raise CodeStatsError("MAPPING_INVALID", "member 只能是 A 或 B。", 1)
        if author in mapping:
            raise CodeStatsError("MAPPING_DUPLICATE", "同一个 git 作者不能映射两次。", 1)
        mapping[author] = member
    return mapping


def _compare(value: int, threshold: int) -> str:
    if value > threshold:
        return "above"
    if value < threshold:
        return "below"
    return "equal"


def apply_mapping(
    authors: list[dict[str, object]], mapping: Mapping[str, str]
) -> dict[str, object]:
    known = {str(item["git_author"]) for item in authors}
    absent = sorted(author for author in mapping if author not in known)
    for item in authors:
        member = mapping.get(str(item["git_author"]))
        item["member"] = member
    members = {}
    for member in ("A", "B"):
        selected = [item for item in authors if item["member"] == member]
        added = sum(int(item["lines_added"]) for item in selected)
        members[member] = {
            "mapped_author_count": len(selected),
            "mapped_authors": [item["git_author"] for item in selected],
            "commits": sum(int(item["commits"]) for item in selected),
            "lines_added": added,
            "lines_deleted": sum(int(item["lines_deleted"]) for item in selected),
            "physical_lines_attributed": None,
            "attribution": "not_computed_current_lines_are_not_personal_property",
            "historical_added_lines_compared_to_1500": (
                None if not selected else _compare(added, PER_PERSON)
            ),
        }
    return {
        "mapped_author_count": len(mapping),
        "mapped_but_absent_from_history": absent,
        "unassigned_authors": [item["git_author"] for item in authors if item["member"] is None],
        "members": members,
    }


def requirement_comparison(scoped_lines: int, members: Mapping[str, object]) -> dict[str, object]:
    return {
        "information_only": True,
        "passes_requirement": False,
        "physical_lines_do_not_prove_original_contribution": True,
        "school_counting_method_not_claimed": True,
        "thresholds": {"per_person": PER_PERSON, "per_project": PER_PROJECT},
        "project_scoped_physical_lines": scoped_lines,
        "project_compared_to_4500": _compare(scoped_lines, PER_PROJECT),
        "project_difference_from_4500": scoped_lines - PER_PROJECT,
        "members": members,
        "detail": DISCLAIMER,
    }


def worktree_state(root: Path) -> dict[str, object]:
    completed = git_read(root, ["status", "--porcelain"], text=True)
    if completed.returncode != 0:
        return {"available": False, "dirty": None, "status_count": None}
    lines = [line for line in completed.stdout.splitlines() if line]
    return {"available": True, "dirty": bool(lines), "status_count": len(lines)}


def build_report(root: Path, revision: str, mapping_path: Path | None) -> dict[str, object]:
    head = _require_repo(root)
    if revision != "HEAD":
        verified = git_read(root, ["rev-parse", "--verify", f"{revision}^{{commit}}"], text=True)
        if verified.returncode != 0:
            raise CodeStatsError("REVISION_MISSING", "指定的提交不存在。", 1)
        head = verified.stdout.strip()
    branch = git_read(root, ["rev-parse", "--abbrev-ref", "HEAD"], text=True)
    tree = tree_lines(root, head)
    authors = history_by_author(root, head)
    mapping = load_mapping(mapping_path)
    assigned = apply_mapping(authors, mapping)
    scoped = int(tree["scoped_physical_lines"])
    return {
        "schema_version": 1,
        "task": "L03",
        "role": "information_only",
        "l03_signed_off": False,
        "l04_text_written": False,
        "disclaimer": DISCLAIMER,
        "revision": head,
        "branch": branch.stdout.strip() if branch.returncode == 0 else None,
        "worktree": worktree_state(root),
        "counts_match_head_not_uncommitted_files": True,
        "areas": tree["areas"],
        "scoped_physical_lines": scoped,
        "other_physical_lines": tree["other_physical_lines"],
        "tracked_text_physical_lines": tree["tracked_text_physical_lines"],
        "binary_file_count": tree["binary_file_count"],
        "binary_files": tree["binary_files"],
        "authors": authors,
        "assignment": {
            "mapped_author_count": assigned["mapped_author_count"],
            "mapped_but_absent_from_history": assigned["mapped_but_absent_from_history"],
            "unassigned_authors": assigned["unassigned_authors"],
        },
        "requirement_comparison": requirement_comparison(scoped, assigned["members"]),
    }


def render_markdown(report: Mapping[str, object]) -> str:
    lines = [
        "# 代码规模信息对照",
        "",
        DISCLAIMER,
        "",
        "这不是 L03 签认，也不是论文正文。当前行来自指定提交中的已跟踪文件；"
        "历史新增和删除来自非合并提交的 numstat。二者不是同一个数。",
        "",
        f"- 提交：`{report['revision']}`",
        f"- 六个区域物理行：{report['scoped_physical_lines']}",
        f"- 其他路径物理行：{report['other_physical_lines']}",
        "",
        "## 区域",
        "",
        "| 区域 | 文件数 | 物理行 |",
        "|---|---:|---:|",
    ]
    areas = report["areas"]
    assert isinstance(areas, dict)
    for name in (*AREAS, "other"):
        bucket = areas[name]
        lines.append(f"| {name} | {bucket['files']} | {bucket['physical_lines']} |")
    comparison = report["requirement_comparison"]
    assert isinstance(comparison, dict)
    lines.extend(
        [
            "",
            "## 与任务书数字的信息对照",
            "",
            (
                f"项目六区物理行相对 4500 为 `{comparison['project_compared_to_4500']}`，"
                f"差值 {comparison['project_difference_from_4500']}。"
                "`passes_requirement` 固定为 false。"
            ),
            "",
            "个人行只有在映射文件把 git 作者明确写成 A 或 B 之后，才汇总这些作者的历史新增行。"
            "现存文件的物理行不划给任何人。",
            "",
            "| 成员 | 映射作者数 | 历史新增行 | 相对 1500 | 划归的现存物理行 |",
            "|---|---:|---:|---|---|",
        ]
    )
    members = comparison["members"]
    assert isinstance(members, dict)
    for name in ("A", "B"):
        member = members[name]
        lines.append(
            "| {name} | {count} | {added} | {compared} | 不计算 |".format(
                name=name,
                count=member["mapped_author_count"],
                added=member["lines_added"],
                compared=member["historical_added_lines_compared_to_1500"],
            )
        )
    lines.extend(["", "## git 作者", "", "下面的身份原样来自 git。未映射就是未映射。", ""])
    authors = report["authors"]
    assert isinstance(authors, list)
    for item in authors:
        lines.append(
            f"- `{item['git_author']}`：成员 {item['member'] or '未映射'}，"
            f"提交 {item['commits']}（其中合并 {item['merge_commits']}），"
            f"新增 {item['lines_added']}，删除 {item['lines_deleted']}"
        )
    lines.append("")
    return "\n".join(lines)


def resolve_output(root: Path, requested: Path | None, default: Path) -> Path:
    path = default if requested is None else requested
    raw = path.expanduser()
    chosen = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    if not chosen.is_relative_to(root):
        raise CodeStatsError("OUTPUT_OUTSIDE_PROJECT", "报告只能写在项目内。", 6)
    relative = chosen.relative_to(root)
    if not relative.parts or relative.parts[0] not in IGNORED_ROOTS:
        raise CodeStatsError("OUTPUT_NOT_IGNORED", "报告只能写在 output/ 或 logs/。", 6)
    return chosen


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="只读统计 git 物理行和作者历史。不判断个人贡献。")
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--revision", default="HEAD")
    parser.add_argument("--members", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--markdown", type=Path, default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    root = (project_root() if args.root is None else args.root).expanduser().resolve()
    if not root.is_dir():
        raise CodeStatsError("ROOT_MISSING", "项目根目录不存在。", 6)
    output = resolve_output(root, args.output, root / "output" / "code-stats" / "report.json")
    markdown = resolve_output(root, args.markdown, root / "output" / "code-stats" / "report.md")
    report = build_report(root, args.revision, args.members)
    _write(output, json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False).encode())
    _write(markdown, render_markdown(report).encode("utf-8"))
    sys.stdout.write(
        json.dumps(
            {
                "report": str(output),
                "markdown": str(markdown),
                "l03_signed_off": False,
                "passes_requirement": False,
            },
            ensure_ascii=False,
        )
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CodeStatsError as error:
        sys.stdout.write(
            json.dumps(
                {"code": error.code, "detail": error.detail, "l03_signed_off": False},
                ensure_ascii=False,
            )
        )
        sys.stdout.write("\n")
        raise SystemExit(error.exit_code) from None
