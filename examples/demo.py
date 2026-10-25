"""Create an isolated Git index with valid and dangling links, without OS symlinks."""

import argparse
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("directory", type=Path, help="new directory to create")
args = parser.parse_args()
args.directory.mkdir(parents=True, exist_ok=False)


def git(*arguments, data=None):
    return subprocess.run(
        ["git", "-C", str(args.directory), *arguments],
        input=data,
        capture_output=True,
        check=True,
    ).stdout.strip()


git("init", "-b", "main")
for name, mode, content in [
    ("LICENSE", "100644", b"Demonstration text.\n"),
    ("valid-link", "120000", b"LICENSE"),
    ("broken-link", "120000", b"LICENSE-missing"),
]:
    oid = git("hash-object", "-w", "--stdin", data=content).decode()
    git("update-index", "--add", "--cacheinfo", mode, oid, name)
print("Created an isolated staged fixture with one valid and one dangling link.")
print("Run: git-link-map --repo <directory> --index")
