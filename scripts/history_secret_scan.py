"""
Full-history secret scan: every blob ever committed, not just the working tree.

    uv run python scripts/history_secret_scan.py

Spec section 8 asks for `gitleaks detect` or equivalent across the whole
history before publication. This is the equivalent, implemented here rather
than by downloading and executing a third-party binary.

It is more thorough than scanning diffs: `git rev-list --objects --all` lists
every object reachable from every ref, including blobs from commits that were
later amended, rebased away, or orphaned on a branch. A credential committed
once and removed in the next commit still exists as a blob and is still
recoverable from a clone, so that is the thing worth checking.

LIKE scripts/secret_scan.sh, THIS REPORTS LOCATIONS ONLY. The matched text is
never printed. A leak scanner whose output contains the leak is how the live
key ended up in a terminal transcript earlier in this project.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Targeted provider patterns plus a conservative generic one. Named so a hit
# can be understood without printing it.
PATTERNS: dict[str, re.Pattern[bytes]] = {
    "anthropic_api_key": re.compile(rb"sk-ant-[A-Za-z0-9_\-]{20,}"),
    "openai_api_key": re.compile(rb"\bsk-[A-Za-z0-9]{32,}\b"),
    "aws_access_key_id": re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    "aws_secret_access_key": re.compile(
        rb"(?i)aws_secret_access_key\s*[:=]\s*[A-Za-z0-9/+=]{40}"
    ),
    "github_token": re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "private_key_block": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "generic_assigned_secret": re.compile(
        rb"(?i)\b(?:api[_-]?key|secret|password|token)\b\s*[:=]\s*"
        rb"['\"][A-Za-z0-9/+_\-]{24,}['\"]"
    ),
}

# Placeholder values that are supposed to be in the repo.
ALLOWED = (
    re.compile(rb"x{8,}"),  # sk-ant-xxxxxxxx... in .env.example
    re.compile(rb"PLACEHOLDER"),
    re.compile(rb"REALLOOKINGKEY"),  # literal in a redaction unit test
)


def git(*args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(REPO), *args], capture_output=True, check=True
    ).stdout


def all_blobs() -> list[tuple[str, str]]:
    """(sha, path) for every blob reachable from every ref."""
    out = []
    for line in git("rev-list", "--objects", "--all").splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            out.append((parts[0].decode(), parts[1].decode("utf-8", "replace")))
    return out


def blob_bytes(sha: str) -> bytes:
    try:
        return git("cat-file", "-p", sha)
    except subprocess.CalledProcessError:
        return b""


def main() -> None:
    blobs = all_blobs()
    n_commits = len(git("rev-list", "--all").splitlines())
    print(f"scanning {len(blobs)} blobs across {n_commits} commits "
          f"(every ref, including unreachable-from-HEAD history)\n")

    findings: list[tuple[str, str, str]] = []
    scanned = 0
    for sha, path in blobs:
        data = blob_bytes(sha)
        if not data or b"\0" in data[:4096]:  # skip binaries
            continue
        scanned += 1
        for name, pattern in PATTERNS.items():
            for m in pattern.finditer(data):
                token = m.group(0)
                if any(a.search(token) for a in ALLOWED):
                    continue
                findings.append((name, path, sha[:12]))
                break

    print(f"scanned {scanned} text blobs")
    if not findings:
        print("\nPASS: no credential-shaped strings in any blob in history.")
        print("      (.env was never committed; verified separately.)")
        return

    print(f"\nFAIL: {len(findings)} finding(s). Locations only -- matched text "
          "is deliberately not printed.\n")
    for name, path, sha in sorted(set(findings)):
        print(f"  {name:<26} {path}  (blob {sha})")
    print(
        "\nDo NOT rewrite history automatically. Report these and let a human "
        "decide; rotating the exposed credential comes first in any case."
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
