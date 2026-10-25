import json
import subprocess
import sys

import pytest

from git_link_map import core
from git_link_map.cli import main


def command(repo, *args, data=None):
    result = subprocess.run(["git", "-C", str(repo), *args], input=data, capture_output=True)
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.fixture
def repo(tmp_path):
    command(tmp_path, "init", "-b", "main")
    command(tmp_path, "config", "user.name", "KanadeK")
    command(tmp_path, "config", "user.email", "121669563+KanadeK@users.noreply.github.com")
    command(tmp_path, "config", "commit.gpgsign", "false")
    command(tmp_path, "config", "core.symlinks", "false")
    return tmp_path


def add(repo, path, content, mode="100644"):
    oid = command(repo, "hash-object", "-w", "--stdin", data=content).strip()
    command(repo, "update-index", "--add", "--cacheinfo", mode, oid.decode(), path)
    return oid


def commit(repo):
    command(repo, "commit", "-m", "fixture")


def test_real_index_and_tree_without_checkout(repo):
    add(repo, "dir/file", b"hello")
    add(repo, "link", b"dir/file", "120000")
    add(repo, "chain", b"link", "120000")
    assert not (repo / "link").exists()
    before = (repo / ".git/index").read_bytes()
    staged = core.audit(core.read_snapshot(repo, index=True))
    assert staged["ok"] and staged["link_count"] == 2
    assert before == (repo / ".git/index").read_bytes()
    commit(repo)
    saved = core.audit(core.read_snapshot(repo))
    assert saved["links"] == staged["links"]
    # Worktree contents never affect a commit-tree report.
    (repo / "link").write_text("invalid host text")
    assert core.audit(core.read_snapshot(repo)) == saved
    add(repo, "new", b"missing", "120000")
    assert core.audit(core.read_snapshot(repo))["ok"]
    assert not core.audit(core.read_snapshot(repo, index=True))["ok"]


def test_differential_native_git_follow_symlinks(repo):
    add(repo, "a/file", b"payload")
    add(repo, "a/deep/entry", b"other")
    links = {"d": b"a/deep", "l": b"d/../file", "chain": b"l"}
    for path, target in links.items():
        add(repo, path, target, "120000")
    commit(repo)
    report = core.audit(core.read_snapshot(repo))
    assert report["ok"]
    for item in report["links"]:
        raw = command(
            repo, "cat-file", "--batch", "--follow-symlinks", data=f"HEAD:{item['path']}\n".encode()
        )
        oid = command(repo, "rev-parse", f"HEAD:{item['at']}").strip()
        assert raw.split(b" ", 1)[0] == oid


def test_cli_exit_codes_and_json(repo):
    add(repo, "broken", b"gone", "120000")
    commit(repo)
    result = subprocess.run(
        [sys.executable, "-m", "git_link_map", "--repo", str(repo)], capture_output=True, text=True
    )
    assert result.returncode == 1
    assert json.loads(result.stdout)["counts"] == {"missing": 1}
    assert main(["--repo", str(repo), "--ref", "does-not-exist"]) == 2
    assert main(["--repo", str(repo), "--max-hops", "0"]) == 2


def test_weird_names_and_targets(repo):
    # Build a tree object directly. Windows' index rejects these names even
    # without checkout, but it can still read such a tree from another OS.
    target = command(repo, "hash-object", "-w", "--stdin", data=b"data").strip()
    link = command(repo, "hash-object", "-w", "--stdin", data=b"target\tname").strip()
    raw = b"100644 blob " + target + b"\ttarget\tname\0"
    raw += b"120000 blob " + link + b"\tlink\nname\0"
    tree_id = command(repo, "mktree", "-z", data=raw).strip().decode()
    assert core.audit(core.read_snapshot(repo, ref=tree_id))["ok"]


def test_subdirectory_index_still_audits_entire_repo(repo):
    add(repo, "root-link", b"missing", "120000")
    (repo / "subdir").mkdir()
    assert core.audit(core.read_snapshot(repo / "subdir", index=True))["link_count"] == 1


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX filesystem oracle runs on Linux CI")
def test_component_resolution_against_real_posix_filesystem(repo):
    import os

    (repo / "a/deep").mkdir(parents=True)
    (repo / "a/file").write_bytes(b"payload")
    add(repo, "a/file", b"payload")
    add(repo, "a/deep/n", b"n")
    targets = {"d": b"a/deep", "l": b"d/./../file", "repeat": b"./l"}
    for path, target in targets.items():
        os.symlink(target.decode(), repo / path)
        add(repo, path, target, "120000")
    report = core.audit(core.read_snapshot(repo, index=True))
    for item in report["links"]:
        assert item["code"] == "ok"
        assert (repo / item["path"]).resolve() == repo / item["at"]


def test_oversized_target_is_input_error(repo):
    add(repo, "link", b"a" * (core.MAX_TARGET + 1), "120000")
    with pytest.raises(core.InputError, match="exceeds"):
        core.read_snapshot(repo, index=True)


def test_unmerged_index_is_rejected(repo):
    oid = command(repo, "hash-object", "-w", "--stdin", data=b"x").strip()
    command(repo, "update-index", "--index-info", data=b"100644 " + oid + b" 1\tconflict\n")
    with pytest.raises(core.InputError, match="unmerged"):
        core.read_snapshot(repo, index=True)


def test_submodule_without_initialization(repo):
    add(repo, "file", b"a")
    commit(repo)
    oid = command(repo, "rev-parse", "HEAD").strip()
    command(repo, "update-index", "--add", "--cacheinfo", "160000", oid.decode(), "module")
    add(repo, "link", b"module/file", "120000")
    assert core.audit(core.read_snapshot(repo, index=True))["counts"] == {"submodule": 1}


def test_alternate_index_is_respected(repo, monkeypatch):
    add(repo, "good", b"data")
    alternate = repo / "alternate-index"
    alternate.write_bytes((repo / ".git/index").read_bytes())
    add(repo, "bad", b"missing", "120000")
    monkeypatch.setenv("GIT_INDEX_FILE", str(alternate))
    assert core.audit(core.read_snapshot(repo, index=True))["link_count"] == 0


def test_wrong_git_dir_env_does_not_override_repo(repo, monkeypatch):
    add(repo, "a", b".", "120000")
    monkeypatch.setenv("GIT_DIR", str(repo / "unrelated"))
    assert core.audit(core.read_snapshot(repo, index=True))["ok"]


def test_git_protocols_disabled(repo, monkeypatch):
    seen = {}
    original = subprocess.run

    def wrapped(*args, **kwargs):
        seen.update(kwargs.get("env", {}))
        return original(*args, **kwargs)

    monkeypatch.setattr(core.subprocess, "run", wrapped)
    core.read_snapshot(repo, index=True)
    assert seen["GIT_ALLOW_PROTOCOL"] == ""
    assert seen["GIT_NO_LAZY_FETCH"] == "1"


def test_snapshot_ref_and_index_conflict(repo):
    with pytest.raises(core.InputError):
        core.read_snapshot(repo, ref="HEAD", index=True)
