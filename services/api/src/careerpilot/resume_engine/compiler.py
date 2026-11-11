"""Controlled XeLaTeX compilation: no shell, -no-shell-escape, temp dir, timeout, rlimits,
restricted file access (openin_any/openout_any=p)."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from ..core.config import get_settings


@dataclass
class CompileResult:
    ok: bool
    error: str | None = None
    log_excerpt: str = ""
    duration_s: float = 0.0
    timed_out: bool = False
    warnings: list[str] | None = None


def xelatex_path() -> str | None:
    return shutil.which("xelatex")


def _limits(cpu_s: int):
    def apply() -> None:  # runs in the child before exec (POSIX only)
        import resource
        for lim, val in ((resource.RLIMIT_CPU, cpu_s), (resource.RLIMIT_FSIZE, 100 << 20),
                         (resource.RLIMIT_CORE, 0), (resource.RLIMIT_NOFILE, 512),
                         (resource.RLIMIT_AS, 4 << 30)):
            try:
                resource.setrlimit(lim, (val, val))
            except (ValueError, OSError):
                pass
        os.setsid()
    return apply


def _excerpt(log: str) -> str:
    lines = log.splitlines()
    out: list[str] = []
    for i, ln in enumerate(lines):
        if ln.startswith("!") or ":error:" in ln.lower() or ln.startswith("l."):
            out.extend(lines[i:i + 3])
    return "\n".join(out[:30])[:2500]


def compile_latex(source: str, out_pdf: Path, timeout: int | None = None) -> CompileResult:
    exe = xelatex_path()
    if not exe:
        return CompileResult(False, "xelatex was not found on PATH; install TeX Live or MiKTeX.")
    s = get_settings()
    timeout = timeout or s.latex_timeout_s
    cache = Path(s.data_dir) / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="cp_tex_") as d:
        work = Path(d)
        (work / "resume.tex").write_text(source, encoding="utf-8")
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": d,
               "XDG_CACHE_HOME": str(cache), "TEXMFVAR": str(cache / "texmf-var"),
               "openin_any": "p", "openout_any": "p", "shell_escape": "f",
               "LANG": "C.UTF-8", "SOURCE_DATE_EPOCH": "0"}
        cmd = [exe, "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error",
               "-file-line-error", "-output-directory", str(work), "resume.tex"]
        kw: dict = {"preexec_fn": _limits(timeout + 5)} if os.name == "posix" else {}
        try:
            proc = subprocess.run(cmd, cwd=d, env=env, capture_output=True, timeout=timeout,
                                  stdin=subprocess.DEVNULL, shell=False, check=False, **kw)
        except subprocess.TimeoutExpired:
            return CompileResult(False, f"LaTeX compilation timed out after {timeout}s.",
                                 duration_s=time.monotonic() - t0, timed_out=True)
        log_path = work / "resume.log"
        log = log_path.read_text("utf-8", "replace") if log_path.exists() else \
            proc.stdout.decode("utf-8", "replace")
        pdf = work / "resume.pdf"
        dur = time.monotonic() - t0
        if proc.returncode != 0 or not pdf.exists():
            return CompileResult(False, "LaTeX compilation failed.", _excerpt(log), dur)
        out_pdf.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(pdf, out_pdf)
        warns = sorted({m.group(0)[:120] for m in re.finditer(r"Missing character:[^\n]*", log)})
        return CompileResult(True, None, "", dur, warnings=warns[:10])
