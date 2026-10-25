import argparse
import json
import subprocess
import sys
from pathlib import Path

from . import __version__
from .core import InputError, audit, read_snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit Git symlink targets without checkout.")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--repo", type=Path, default=Path("."))
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--ref", help="commit/tree/ref; defaults to HEAD")
    source.add_argument("--index", action="store_true", help="audit staged contents")
    parser.add_argument("--max-hops", type=int, default=40)
    args = parser.parse_args(argv)
    try:
        result = audit(
            read_snapshot(args.repo, ref=args.ref, index=args.index), max_hops=args.max_hops
        )
        print(json.dumps(result, indent=2, ensure_ascii=True, sort_keys=True))
        return 0 if result["ok"] else 1
    except (InputError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
