"""Check an explicit public-source inventory, not arbitrary runtime folders."""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_SUFFIXES = {".py", ".md", ".json", ".yml"}
SPECIAL_NAMES = {".gitignore", ".gitattributes"}
PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{30,}"),
    re.compile(r"[A-Za-z]:[\\/](?:Users|work)[\\/]", re.I),
]


def inspect_text(name: str, text: str) -> list[str]:
    problems = []
    if PurePosixPath(name).suffix not in ALLOWED_SUFFIXES and name not in SPECIAL_NAMES:
        problems.append("unapproved file type")
    if "\x00" in text or any(pattern.search(text) for pattern in PATTERNS):
        problems.append("sensitive-looking or binary content")
    return problems


def check(root: Path) -> list[str]:
    problems = []
    inventory = json.loads((root / "public-files.json").read_text(encoding="utf-8"))
    if (not isinstance(inventory, list) or any(not isinstance(v, str) for v in inventory)
            or len(inventory) != len(set(inventory))):
        raise ValueError("Invalid public inventory")
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=root, check=True,
                             stdout=subprocess.PIPE).stdout.decode("utf-8").split("\0")
    tracked = [name for name in tracked if name]
    if set(tracked) != set(inventory):
        problems.append("tracked files differ from public inventory")
    for name in inventory:
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name:
            problems.append("unsafe inventory path")
            continue
        path = root / name
        # Relative ancestors stop at '.', so the boundary includes root only.
        if any((root / part).is_symlink() for part in (relative, *relative.parents)):
            problems.append("symlink in public inventory")
            continue
        if not path.is_file() or path.stat().st_size > 131072:
            problems.append("missing or oversized public file")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            problems.append("non-UTF-8 public file")
            continue
        problems.extend(inspect_text(name, text))
    return problems


if __name__ == "__main__":
    try:
        findings = check(ROOT)
        if findings:
            print("Public surface check failed: " + "; ".join(sorted(set(findings))), file=sys.stderr)
            raise SystemExit(1)
        print("Public surface check passed (limited static checks; human review still required)")
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print("Public surface check could not complete", file=sys.stderr)
        raise SystemExit(1) from error
