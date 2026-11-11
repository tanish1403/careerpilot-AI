"""LaTeX escaping and safety checks. All user-controlled text goes through escape_latex so that
control sequences in it can never execute."""
from __future__ import annotations

import re
import unicodedata

_MAP = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
        "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
        "<": r"\textless{}", ">": r"\textgreater{}", "|": r"\textbar{}", "`": r"\textasciigrave{}"}
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2060\u2066-\u2069\ufeff]")


def escape_latex(text: object) -> str:
    """Escape arbitrary text for use in running LaTeX text (XeLaTeX, unicode ok)."""
    s = unicodedata.normalize("NFC", str(text if text is not None else ""))
    s = _CTRL.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()
    return "".join(_MAP.get(c, c) for c in s)


_UNESC = [(r"\textbackslash{}", "\\"), (r"\textasciitilde{}", "~"),
          (r"\textasciicircum{}", "^"), (r"\textless{}", "<"), (r"\textgreater{}", ">"),
          (r"\textbar{}", "|"), (r"\textasciigrave{}", "`"), (r"\&", "&"), (r"\%", "%"),
          (r"\$", "$"), (r"\#", "#"), (r"\_", "_"), (r"\{", "{"), (r"\}", "}")]


def unescape_latex(s: str) -> str:
    out, i = [], 0
    while i < len(s):
        for a, b in _UNESC:
            if s.startswith(a, i):
                out.append(b)
                i += len(a)
                break
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


_SAFE_URL = re.compile(r"^(?:https?://|mailto:)[^\s\x00-\x1f]+$", re.I)


def safe_url(url: str | None) -> str | None:
    """Return a sanitised URL for \\href, or None if it is not http(s)/mailto."""
    if not url:
        return None
    u = url.strip()
    if not re.match(r"^(?:https?://|mailto:)", u, re.I):
        if re.match(r"^[\w.-]+\.[a-z]{2,}(?:/|$)", u, re.I):
            u = "https://" + u
        elif "@" in u and " " not in u:
            u = "mailto:" + u
        else:
            return None
    if not _SAFE_URL.match(u):
        return None
    return (u.replace("\\", "%5C").replace("{", "%7B").replace("}", "%7D")
            .replace("%", r"\%").replace("#", r"\#").replace("^", "%5E").replace("~", r"\~{}")
            .replace("\"", "%22"))


# Everything below guards USER-EDITED LaTeX source (PUT /resumes/{id}/source).
_FORBIDDEN = re.compile(
    r"\\(?:write|immediate|openout|openin|input|include|includeonly|InputIfFileExists|read|"
    r"readline|newwrite|newread|closeout|closein|catcode|csname|directlua|luaexec|"
    r"pdfshellescape|ShellEscape|shipout|special|openpipe|scantokens|detokenize|"
    r"usepackage\s*\[[^\]]*\]\s*\{(?:shellesc|minted|pythontex|write18)\}|"
    r"lstinputlisting|verbatiminput|VerbatimInput|externaldocument|pdfliteral|"
    r"def|edef|gdef|xdef|let|futurelet|outer|long)(?![a-zA-Z])")
_ALLOWED_PACKAGES = {"fontspec", "geometry", "hyperref", "enumitem", "titlesec", "xcolor",
                     "parskip", "fancyhdr", "microtype", "array", "ragged2e", "setspace",
                     "tabularx", "xparse", "etoolbox", "ifthen", "lmodern", "unicode-math",
                     "amssymb", "textcomp", "needspace", "multicol"}


def find_forbidden(source: str) -> list[str]:
    """Return human readable findings; an empty list means the source is acceptable."""
    findings: list[str] = []
    stripped = re.sub(r"(?<!\\)%[^\n]*", "", source)
    for m in _FORBIDDEN.finditer(stripped):
        findings.append(f"Forbidden command: {m.group(0)[:40]}")
    for m in re.finditer(r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}",
                         stripped):
        for pkg in (p.strip() for p in m.group(1).split(",")):
            if pkg and pkg not in _ALLOWED_PACKAGES:
                findings.append(f"Package not allowed: {pkg}")
    if re.search(r"\\documentclass", stripped) is None:
        findings.append("Missing \\documentclass")
    if len(source) > 400_000:
        findings.append("Source too large")
    return sorted(set(findings))
