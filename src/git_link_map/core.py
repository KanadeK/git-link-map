"""Resolve symlinks using Git objects, with no host filesystem traversal."""

from __future__ import annotations

import os
import re
import subprocess
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path

MAX_OUTPUT = 64 * 1024 * 1024
MAX_ENTRIES = 200_000
MAX_TARGET = 4096
OID = re.compile(rb"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


class InputError(ValueError):
    """The Git snapshot cannot be read completely."""


def display(raw: bytes) -> str:
    return raw.decode("utf-8", "surrogateescape")


@dataclass(frozen=True)
class Entry:
    kind: str
    oid: bytes = b""


@dataclass
class Snapshot:
    entries: dict[bytes, Entry]
    links: dict[bytes, bytes]
    source: str


def git(repo: Path, *args: str, data: bytes | None = None) -> bytes:
    env = os.environ.copy()
    # Preserve explicit GIT_INDEX_FILE (e.g. a pre-commit alternate index), but
    # do not let GIT_DIR/GIT_WORK_TREE silently override --repo.
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR"):
        env.pop(key, None)
    env.update(
        GIT_NO_LAZY_FETCH="1",
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_OPTIONAL_LOCKS="0",
        GIT_TERMINAL_PROMPT="0",
        GIT_ALLOW_PROTOCOL="",
    )
    result = subprocess.run(
        ["git", "--no-replace-objects", "-C", str(repo), "-c", "core.fsmonitor=false", *args],
        input=data,
        capture_output=True,
        timeout=60,
        env=env,
    )
    if result.returncode:
        raise InputError("Git failed: " + display(result.stderr[:4096]).strip())
    if len(result.stdout) > MAX_OUTPUT:
        raise InputError(f"Git output exceeds {MAX_OUTPUT} bytes")
    return result.stdout


def parse_entries(raw: bytes, *, index: bool) -> dict[bytes, Entry]:
    entries = {b"": Entry("directory")}
    records = raw.split(b"\0")
    if records[-1] != b"":
        raise InputError("unterminated Git inventory")
    if len(records) - 1 > MAX_ENTRIES:
        raise InputError("too many Git entries")
    for record in records[:-1]:
        try:
            header, name = record.split(b"\t", 1)
            first, second, third = header.split(b" ")
        except ValueError as exc:
            raise InputError("malformed Git inventory") from exc
        if (
            not name
            or len(name) > MAX_TARGET
            or any(p in (b"", b".", b"..") for p in name.split(b"/"))
        ):
            raise InputError("invalid Git path")
        if index:
            mode, oid, stage = first, second, third
            if stage != b"0":
                raise InputError("unmerged index: resolve conflicts before auditing")
        else:
            mode, _object_type, oid = first, second, third
        if not OID.fullmatch(oid):
            raise InputError("invalid Git object ID")
        kinds = {
            b"100644": "file",
            b"100755": "file",
            b"120000": "symlink",
            b"160000": "submodule",
            b"040000": "directory",
        }
        if mode not in kinds:
            raise InputError(f"unsupported Git mode: {display(mode)}")
        if name in entries:
            raise InputError("duplicate Git path")
        entries[name] = Entry(kinds[mode], oid)
    # The index has no directory entries. Include implicit directories and
    # reject impossible file/directory conflicts instead of guessing.
    for name in list(entries):
        parts = name.split(b"/")
        for i in range(1, len(parts)):
            parent = b"/".join(parts[:i])
            if parent in entries and entries[parent].kind != "directory":
                raise InputError("Git inventory contains a file/directory conflict")
            entries.setdefault(parent, Entry("directory"))
            if len(entries) > MAX_ENTRIES:
                raise InputError("too many Git entries including directories")
    return entries


def read_link_blobs(repo: Path, entries: dict[bytes, Entry]) -> dict[bytes, bytes]:
    oids = sorted({v.oid for v in entries.values() if v.kind == "symlink"})
    if not oids:
        return {}
    request = b"\n".join(oids) + b"\n"
    headers = git(repo, "cat-file", "--batch-check", data=request).splitlines()
    if len(headers) != len(oids):
        raise InputError("incomplete Git size response")
    sizes = []
    for oid, header in zip(oids, headers, strict=True):
        parts = header.split()
        if len(parts) != 3 or parts[0] != oid or parts[1] != b"blob":
            raise InputError("missing or non-blob symlink object")
        size = int(parts[2])
        if size < 0 or size > MAX_TARGET:
            raise InputError(f"symlink target exceeds {MAX_TARGET} bytes")
        sizes.append(size)
    if sum(sizes) + sum(len(h) + 2 for h in headers) > MAX_OUTPUT:
        raise InputError("too many symlink bytes")
    raw = git(repo, "cat-file", "--batch", data=request)
    contents = {}
    offset = 0
    for oid, header, size in zip(oids, headers, sizes, strict=True):
        start = offset + len(header) + 1
        if raw[offset:start] != header + b"\n" or raw[start + size : start + size + 1] != b"\n":
            raise InputError("malformed Git content response")
        contents[oid] = raw[start : start + size]
        offset = start + size + 1
    if offset != len(raw):
        raise InputError("trailing Git content response")
    return {p: contents[e.oid] for p, e in entries.items() if e.kind == "symlink"}


def read_snapshot(repo: Path, *, ref: str | None = None, index: bool = False) -> Snapshot:
    if ref is not None and index:
        raise InputError("choose a ref or the index, not both")
    if index:
        raw = git(repo, "ls-files", "--stage", "--full-name", "-z", "--", ":/")
        source = "index"
    else:
        tree = git(
            repo, "rev-parse", "--verify", "--end-of-options", (ref or "HEAD") + "^{tree}"
        ).strip()
        if not OID.fullmatch(tree):
            raise InputError("ref did not resolve to one tree")
        raw = git(repo, "ls-tree", "--full-tree", "-r", "-t", "-z", tree.decode("ascii"))
        source = "tree:" + tree.decode("ascii")
    entries = parse_entries(raw, index=index)
    return Snapshot(entries, read_link_blobs(repo, entries), source)


def resolve(snapshot: Snapshot, link: bytes, *, max_hops: int = 40) -> dict:
    if not 1 <= max_hops <= 256:
        raise InputError("max_hops must be between 1 and 256")
    chain: list[dict] = []
    pending = deque(link.split(b"/"))
    current: list[bytes] = []
    seen: set[tuple[bytes, tuple[bytes, ...]]] = set()

    def result(code: str, at: bytes) -> dict:
        return {
            "path": display(link),
            "target": display(snapshot.links[link]),
            "code": code,
            "at": display(at),
            "chain": chain,
        }

    while pending:
        here = b"/".join(current)
        kind = snapshot.entries[here].kind
        if kind == "submodule":
            return result("submodule", here)
        if kind != "directory":
            return result("not_directory", here)
        part = pending.popleft()
        if part in (b"", b"."):
            continue
        if part == b"..":
            if not current:
                return result("outside_tree", b"../" + b"/".join(pending))
            current.pop()
            continue
        path = b"/".join([*current, part])
        entry = snapshot.entries.get(path)
        if entry is None:
            return result("missing", path)
        if entry.kind != "symlink":
            current.append(part)
            continue
        target = snapshot.links[path]
        state = (path, tuple(pending))
        if state in seen:
            return result("cycle", path)
        seen.add(state)
        if len(chain) >= max_hops:
            return result("hop_limit", path)
        chain.append({"path": display(path), "target": display(target)})
        if not target or b"\0" in target:
            return result("invalid_target", path)
        if target.startswith(b"/") or re.match(rb"^[A-Za-z]:", target):
            return result("absolute_target", target)
        if b"\\" in target:
            return result("nonportable_target", target)
        pending.extendleft(reversed(target.split(b"/")))
    final = b"/".join(current)
    if snapshot.entries[final].kind == "submodule":
        return result("submodule", final)
    return result("ok", final)


def audit(snapshot: Snapshot, *, max_hops: int = 40) -> dict:
    if not 1 <= max_hops <= 256:
        raise InputError("max_hops must be between 1 and 256")
    links = [resolve(snapshot, p, max_hops=max_hops) for p in sorted(snapshot.links)]
    counts = Counter(r["code"] for r in links)
    return {
        "schema_version": 1,
        "source": snapshot.source,
        "ok": all(r["code"] == "ok" for r in links),
        "link_count": len(links),
        "counts": dict(sorted(counts.items())),
        "links": links,
    }
