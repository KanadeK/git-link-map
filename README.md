# git-link-map

Audit symbolic links in a Git commit tree or staged index, even when your
checkout contains ordinary text files because `core.symlinks=false`.

The tool reads Git's mode `120000` blobs and resolves each target against the
selected Git snapshot. It reports the full chain and final location, or explains
why the link is dangling, cyclic, absolute, outside the tree, traversing a
regular file, or crossing an opaque submodule. It never follows host filesystem
links or changes the repository.

## Install

Requires Python 3.11+ and Git with `rev-parse --end-of-options` (Git 2.30+).
There are no Python runtime dependencies. Tested locally with Git 2.56 and in
CI with the Git provided by current Linux and Windows runners.

```sh
git clone https://github.com/KanadeK/git-link-map.git
cd git-link-map
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# PowerShell: .venv\Scripts\Activate.ps1
python -m pip install .
git-link-map --version
```

A wheel is available in GitHub Releases: `python -m pip install <wheel-path>`.
This project is not published to PyPI. Uninstall with
`python -m pip uninstall git-link-map`. No caches, services or configuration
files are created by the auditor.

## Use

```sh
git-link-map --repo path/to/repository
git-link-map --repo path/to/repository --ref v1.0.0
git-link-map --repo path/to/repository --index
git-link-map --repo path/to/repository --index > symlink-report.json
```

Default is `HEAD`, including files that were never checked out. `--index` uses
staged blobs and works before the first commit; an unmerged index is an error.
Both modes audit the entire repository when invoked from a subdirectory.
`GIT_INDEX_FILE` is honored for alternate indexes. `GIT_DIR`, `GIT_WORK_TREE`
and `GIT_COMMON_DIR` are removed from subprocess environments so `--repo` selects
the requested repository. Replacement refs and automatic object fetching are
disabled; missing objects fail rather than being downloaded.

Try a reproducible failure without needing OS symlink privileges:

```sh
python examples/demo.py ../link-demo
git-link-map --repo ../link-demo --index
```

The demo creates a new isolated repository with one valid and one dangling
staged link. The audit returns **1** with `counts: {"missing": 1, "ok": 1}`.
Delete the demo directory when finished; the auditor itself performs no cleanup
or writes. Run the command on a repository with only valid links to get exit 0.

## Report and semantics

JSON is written to stdout, with stable bytewise path ordering. Each link has
`path`, raw `target`, `code`, `at` (final location or failure point), and a
`chain` of expanded links. Control characters and non-UTF-8 filename bytes are
escaped in JSON; undecodable bytes use Python's surrogateescape representation.
`source` pins the resolved tree object ID, or says `index` for staged contents.

| Code | Meaning |
|---|---|
| `ok` | Resolves to a tracked file or directory in the selected snapshot |
| `missing` | A required path component is absent (matching is case-sensitive) |
| `cycle` | The same link and remaining path state recurs |
| `hop_limit` | Expansion exceeds the explicit bound, including growing cycles |
| `outside_tree` | Parent traversal crosses the repository root |
| `absolute_target` | Absolute POSIX target or a Windows drive prefix |
| `nonportable_target` | A target contains backslashes; semantics are OS-specific |
| `not_directory` | A suffix, slash, `.` or `..` traverses a regular file |
| `submodule` | Resolution needs a gitlink; its contents are not inspected |
| `invalid_target` | Empty target or embedded NUL |

Exit codes: **0** all links resolve (including a snapshot with zero links),
**1** at least one non-`ok` result, **2** invalid input or incomplete audit.
Input errors are JSON on stderr. Unknown submodule contents deliberately do not
produce a successful result. `--max-hops` defaults to 40 and accepts 1–256.

Resolution is a case-sensitive POSIX component walk: expand directory symlinks
before evaluating the following `..`. A nonexistent component does not vanish
just because a later `..` would cancel it. Directory targets and trailing slash
requirements are supported. This models a POSIX checkout; it does not emulate
every Windows junction or filesystem normalization rule. The native
`git cat-file --follow-symlinks` command differs on some dot-component inputs;
tests use both Git and Linux filesystem oracles in their applicable domains.

## Boundaries and integration

This checks *tracked snapshot* links. It cannot establish permissions, target
existence outside Git, whether an external link is intentional, or whether a
platform will materialize a valid link. Intentional external links still fail.
Submodule traversal and worktree/untracked targets are outside version 0.1.0.
There is no allowlist hiding unresolved links.

Use on a trusted local repository with a stable index. Git executable/config
and object storage remain trusted; this is not an arbitrary repository sandbox.
Git commands have a 60-second timeout. Inventory is limited to 200,000 entries,
paths/targets to 4096 bytes and each captured Git response to 64 MiB. Git output
is captured before checking its size, so these are processing limits, not a
hard memory sandbox. The auditor reads raw blobs without filters or hooks and
blocks all Git transport protocols for its subprocesses.

For CI, install the tool and run `git-link-map --ref HEAD`. With pre-commit,
use `git-link-map --index` and `pass_filenames: false`. Unlike
[pre-commit's check-symlinks](https://github.com/pre-commit/pre-commit-hooks), this
tool reports against Git objects rather than the materialized worktree.

Python API: `read_snapshot(Path(...), ref="HEAD")` / `read_snapshot(..., index=True)`
and `audit(snapshot)` from `git_link_map.core`. See [DESIGN.md](DESIGN.md).
API/schema stability is provisional in 0.1.x.

## 中文说明

直接读取 Git 提交树或暂存区中的符号链接对象，不依赖 Windows 是否有创建链接的权限。
可以发现断链、循环、越界、绝对路径、穿过普通文件的路径，并给出完整解析链。
对子模块内部内容明确报告未知，不会误判成功。仅检查已跟踪内容，不修改工作区或索引。

安装后运行 `git-link-map --repo 仓库路径 --index` 检查暂存内容，省略 `--index`
则检查 HEAD。结果是 JSON，退出码 0/1/2 分别表示通过、发现问题、输入或执行错误。
示例脚本能在 Windows 上创建不需要真实符号链接的复现仓库。
