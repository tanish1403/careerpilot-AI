"""Lightweight secret scan over git-tracked (or all non-ignored) files. Exit 1 on findings.

Allow a known-safe line with the marker `scan-secrets: allow`.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "private key": re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    "openai/anthropic style key": re.compile(r"\bsk-(ant-|proj-)?[A-Za-z0-9_\-]{32,}"),
    "aws access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    "google api key": re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
}
BAD_NAMES = (".env", "secret.key")
BAD_SUFFIX = (".pem", ".key", ".db", ".sqlite")
SKIP_DIRS = {"node_modules", ".venv", ".git", "dist", "__pycache__", "data", ".pytest_cache"}


def files() -> list[Path]:
    try:
        out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.splitlines()
        return [ROOT / f for f in out if (ROOT / f).is_file()]
    except (OSError, subprocess.CalledProcessError):
        return [p for p in ROOT.rglob("*")
                if p.is_file() and not SKIP_DIRS & set(p.relative_to(ROOT).parts)]


def main() -> int:
    bad: list[str] = []
    for p in files():
        rel = p.relative_to(ROOT).as_posix()
        if p.name in BAD_NAMES or p.suffix in BAD_SUFFIX:
            bad.append(f"{rel}: forbidden file type committed")
            continue
        if p.stat().st_size > 2_000_000:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if "scan-secrets: allow" in line:
                continue
            for name, rx in PATTERNS.items():
                if rx.search(line):
                    bad.append(f"{rel}:{i}: {name}")
    for b in bad:
        print(b)
    print(f"secret scan: {'FAILED' if bad else 'ok'} ({len(bad)} finding(s))")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
