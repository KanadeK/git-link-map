import random

import pytest

from git_link_map.core import Entry, InputError, Snapshot, audit, parse_entries, resolve


def tree(files=(), links=None, modules=()):
    links = links or {}
    entries = {b"": Entry("directory")}
    entries.update({p: Entry("file") for p in files})
    entries.update({p: Entry("symlink") for p in links})
    entries.update({p: Entry("submodule") for p in modules})
    for path in list(entries):
        parts = path.split(b"/")
        for i in range(1, len(parts)):
            entries.setdefault(b"/".join(parts[:i]), Entry("directory"))
    return Snapshot(entries, links, "fixture")


@pytest.mark.parametrize(
    "target,code,at",
    [
        (b"file", "ok", "file"),
        (b"./file", "ok", "file"),
        (b"dir/../file", "ok", "file"),
        (b"dir//nested", "ok", "dir/nested"),
        (b".", "ok", ""),
        (b"missing", "missing", "missing"),
        (b"File", "missing", "File"),
        (b"missing/../file", "missing", "missing"),
        (b"file/../file", "not_directory", "file"),
        (b"file/", "not_directory", "file"),
        (b"file/.", "not_directory", "file"),
        (b"../file", "outside_tree", "../file"),
        (b"/etc/passwd", "absolute_target", "/etc/passwd"),
        (b"C:/file", "absolute_target", "C:/file"),
        (b"dir\\nested", "nonportable_target", "dir\\nested"),
        (b"", "invalid_target", "link"),
        (b"a\0b", "invalid_target", "link"),
    ],
)
def test_paths(target, code, at):
    result = resolve(tree([b"file", b"dir/nested"], {b"link": target}), b"link")
    assert result["code"] == code
    assert result["at"] == at


def test_chains_directory_links_and_parent_order():
    snap = tree([b"a/file", b"a/deep/n"], {b"d": b"a/deep", b"l": b"d/../file", b"chain": b"l"})
    result = resolve(snap, b"chain")
    assert result["code"] == "ok" and result["at"] == "a/file"
    assert [c["path"] for c in result["chain"]] == ["chain", "l", "d"]


def test_cycle_and_growing_cycle_are_bounded():
    snap = tree(links={b"a": b"b", b"b": b"a", b"grow": b"grow/x"})
    assert resolve(snap, b"a")["code"] == "cycle"
    assert resolve(snap, b"grow", max_hops=5)["code"] == "hop_limit"


def test_finite_repeated_directory_link_is_valid():
    snap = tree([b"file"], {b"d": b".", b"l": b"d/d/d/file"})
    assert resolve(snap, b"l")["code"] == "ok"


def test_submodule_is_explicit_unknown():
    snap = tree(links={b"a": b"module", b"b": b"module/file"}, modules=[b"module"])
    report = audit(snap)
    assert not report["ok"] and report["counts"] == {"submodule": 2}


def test_non_utf8_paths_survive_json():
    import json

    snap = tree([b"file\xff"], {b"l\xfe": b"file\xff"})
    encoded = json.dumps(audit(snap), ensure_ascii=True)
    assert "\\udcff" in encoded and "\\udcfe" in encoded
    assert json.loads(encoded)["ok"]


def test_empty_is_valid_and_hop_argument_checked():
    assert audit(tree())["ok"]
    for hops in [0, 257]:
        with pytest.raises(InputError):
            audit(tree(), max_hops=hops)


def test_order_is_stable():
    links = {f"link-{i}".encode(): b"file" for i in range(100)}
    baseline = audit(tree([b"file"], links))
    shuffled = list(links.items())
    random.Random(42).shuffle(shuffled)
    assert audit(tree([b"file"], dict(shuffled))) == baseline


@pytest.mark.parametrize(
    "raw,index",
    [
        (b"no terminator", True),
        (b"bad\0", True),
        (b"100644 " + b"a" * 40 + b" 1\tfile\0", True),
        (b"100644 nope 0\tfile\0", True),
        (b"100644 " + b"a" * 40 + b" 0\t../file\0", True),
        (b"100000 " + b"a" * 40 + b" 0\tfile\0", True),
    ],
)
def test_bad_git_inventory(raw, index):
    with pytest.raises(InputError):
        parse_entries(raw, index=index)


def test_index_infers_directories_and_rejects_duplicate():
    raw = b"100644 " + b"a" * 40 + b" 0\ta/b/c\0"
    result = parse_entries(raw, index=True)
    assert result[b"a"].kind == result[b"a/b"].kind == "directory"
    with pytest.raises(InputError, match="duplicate"):
        parse_entries(raw + raw, index=True)


def test_file_directory_conflict():
    raw = b"100644 " + b"a" * 40 + b" 0\ta\0"
    raw += b"100644 " + b"a" * 40 + b" 0\ta/b\0"
    with pytest.raises(InputError, match="conflict"):
        parse_entries(raw, index=True)
