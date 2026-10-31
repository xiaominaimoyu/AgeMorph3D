"""Read-only checks for the L03 line statistics tool."""

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
stats = importlib.import_module("code_stats")


def test_areas_keep_tests_separate_and_do_not_imply_ownership():
    assert stats.classify_path("frontend/src/viewer.ts") == "frontend"
    assert stats.classify_path("frontend/tests/viewer.test.ts") == "tests"
    assert stats.classify_path("backend/src/agemorph3d/app.py") == "backend"
    assert stats.classify_path("backend/tests/test_api.py") == "tests"
    assert stats.classify_path("preprocessing/archive_preparation.py") == "preprocessing"
    assert stats.classify_path("tools/code_stats.py") == "tools"
    assert stats.classify_path("docs/验收矩阵.md") == "docs"
    assert stats.classify_path("README.md") == "other"
    assert stats.physical_lines(b"a\nb\n") == 2
    assert stats.physical_lines(b"a\0b") is None


def _git(repo: Path, args: list[str], env: dict[str, str] | None = None) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, env=env, capture_output=True)


def _person(name: str, email: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": name,
            "GIT_COMMITTER_EMAIL": email,
        }
    )
    return env


def _commit(repo: Path, name: str, email: str, message: str) -> None:
    env = _person(name, email)
    _git(
        repo,
        ["-c", f"user.name={name}", "-c", f"user.email={email}", "commit", "-m", message],
        env,
    )


def _repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "project file"
    repo.mkdir()
    _git(repo, ["init", "-b", "main"])
    one = "Author One <one@example.invalid>"
    two = "Author Two <two@example.invalid>"
    frontend = repo / "frontend" / "src"
    frontend.mkdir(parents=True)
    (frontend / "main.ts").write_text("a\nb\nc\n", encoding="utf-8")
    backend = repo / "backend" / "src"
    backend.mkdir(parents=True)
    (backend / "app.py").write_text("x\ny\n", encoding="utf-8")
    tests = repo / "backend" / "tests"
    tests.mkdir()
    (tests / "test_app.py").write_text("1\n2\n3\n4\n", encoding="utf-8")
    (repo / "docs").mkdir()
    (repo / "docs" / "a.md").write_text("doc\n", encoding="utf-8")
    (repo / "README.md").write_text("root\n", encoding="utf-8")
    _git(repo, ["add", "."])
    _commit(repo, "Author One", "one@example.invalid", "base")
    (frontend / "main.ts").write_text("a\nb\n", encoding="utf-8")
    tools = repo / "tools"
    tools.mkdir()
    (tools / "tool.py").write_text("1\n2\n3\n4\n5\n", encoding="utf-8")
    (repo / "frontend" / "src" / "blob.bin").write_bytes(b"a\0b")
    _git(repo, ["add", "."])
    _commit(repo, "Author Two", "two@example.invalid", "edit")
    _git(repo, ["checkout", "-b", "side"])
    prepared = repo / "preprocessing"
    prepared.mkdir()
    (prepared / "job.py").write_text("p\n", encoding="utf-8")
    _git(repo, ["add", "preprocessing"])
    _commit(repo, "Author One", "one@example.invalid", "side")
    _git(repo, ["checkout", "main"])
    _git(
        repo,
        [
            "-c",
            "user.name=Author Two",
            "-c",
            "user.email=two@example.invalid",
            "merge",
            "--no-ff",
            "--no-edit",
            "side",
        ],
        _person("Author Two", "two@example.invalid"),
    )
    return repo, one, two


def test_history_separates_physical_lines_from_added_lines(tmp_path):
    repo, one, two = _repo(tmp_path)
    report = stats.build_report(repo, "HEAD", None)
    areas = report["areas"]
    assert areas["frontend"]["physical_lines"] == 2
    assert areas["backend"]["physical_lines"] == 2
    assert areas["tests"]["physical_lines"] == 4
    assert areas["docs"]["physical_lines"] == 1
    assert areas["tools"]["physical_lines"] == 5
    assert areas["preprocessing"]["physical_lines"] == 1
    assert areas["other"]["physical_lines"] == 1
    assert report["binary_file_count"] == 1
    by_name = {item["git_author"]: item for item in report["authors"]}
    assert by_name[one]["lines_added"] == 12
    assert by_name[one]["lines_deleted"] == 0
    assert by_name[two]["lines_added"] == 5
    assert by_name[two]["lines_deleted"] == 1
    assert by_name[two]["merge_commits"] == 1
    assert by_name[two]["binary_changes"] == 1
    assert report["l03_signed_off"] is False
    assert report["requirement_comparison"]["passes_requirement"] is False
    assert report["requirement_comparison"]["project_compared_to_4500"] == "below"
    assert report["disclaimer"] == stats.DISCLAIMER
    assert all(item["member"] is None for item in report["authors"])


def test_mapping_assigns_only_exact_authors_and_not_physical_lines(tmp_path):
    repo, one, _two = _repo(tmp_path)
    mapping = repo / "output" / "members.json"
    mapping.parent.mkdir()
    mapping.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "authors": [
                    {"git_author": "", "member": ""},
                    {"git_author": one, "member": "B"},
                ],
            }
        ),
        encoding="utf-8",
    )
    report = stats.build_report(repo, "HEAD", mapping)
    members = report["requirement_comparison"]["members"]
    assert members["B"]["lines_added"] == 12
    assert members["B"]["historical_added_lines_compared_to_1500"] == "below"
    assert members["B"]["physical_lines_attributed"] is None
    assert members["A"]["mapped_author_count"] == 0
    assert members["A"]["historical_added_lines_compared_to_1500"] is None
    assert report["assignment"]["unassigned_authors"]


def test_incomplete_or_unknown_mapping_is_rejected(tmp_path):
    path = tmp_path / "members.json"
    path.write_text(
        json.dumps({"schema_version": 1, "authors": [{"git_author": "A <a@b>", "member": ""}]}),
        encoding="utf-8",
    )
    with pytest.raises(stats.CodeStatsError) as caught:
        stats.load_mapping(path)
    assert caught.value.code == "MAPPING_INCOMPLETE"
    path.write_text(
        json.dumps({"schema_version": 1, "authors": [{"git_author": "A <a@b>", "member": "C"}]}),
        encoding="utf-8",
    )
    with pytest.raises(stats.CodeStatsError) as caught:
        stats.load_mapping(path)
    assert caught.value.code == "MAPPING_INVALID"


def test_template_maps_nobody():
    template = ROOT / "tools" / "author-members.template.json"
    assert stats.load_mapping(template) == {}
    text = template.read_text(encoding="utf-8")
    assert '"git_author": ""' in text
    assert "MingYao" not in text
    assert "@qq.com" not in text


def test_report_stays_in_ignored_directory_and_states_the_limit(tmp_path):
    repo, _one, _two = _repo(tmp_path)
    output = repo / "output" / "code-stats" / "report.json"
    markdown = repo / "output" / "code-stats" / "report.md"
    code = stats.main(["--root", str(repo), "--output", str(output), "--markdown", str(markdown)])
    assert code == 0
    body = json.loads(output.read_text(encoding="utf-8"))
    rendered = markdown.read_text(encoding="utf-8")
    assert "不证明个人原创贡献" in body["disclaimer"]
    assert "不证明个人原创贡献" in rendered
    assert "passes_requirement" in rendered
    assert body["requirement_comparison"]["passes_requirement"] is False
    with pytest.raises(stats.CodeStatsError) as caught:
        stats.main(["--root", str(repo), "--output", str(repo / "docs" / "report.json")])
    assert caught.value.exit_code == 6


def test_git_write_commands_are_refused(tmp_path):
    with pytest.raises(stats.CodeStatsError) as caught:
        stats.git_read(tmp_path, ["commit", "-m", "no"])
    assert caught.value.code == "GIT_WRITE_FORBIDDEN"
    source = (ROOT / "tools" / "code_stats.py").read_text(encoding="utf-8")
    assert "git push" not in source
    assert "git commit" not in source
