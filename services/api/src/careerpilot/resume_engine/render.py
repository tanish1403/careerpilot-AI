"""ResumeModel -> LaTeX source + claims. Every emitted line carries a `% cp:claim=<id>` marker
so claims survive user edits of the LaTeX source."""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..db.base import new_id
from .latex import escape_latex, safe_url, unescape_latex
from .model import Entry, ResumeModel

MARK = re.compile(r"\s*%\s*cp:claim=([0-9a-f]{32})\s*$")
_SYMBOLS = r"(?:backslash|asciitilde|asciicircum|less|greater|bar|asciigrave)"
_HREF = re.compile(r"\\href\{[^{}]*\}\{([^{}]*)\}")
_GENERIC = re.compile(r"\\(?!text" + _SYMBOLS + r"\b)[a-zA-Z]+\*?\{([^{}]*)\}")


def latex_plain(s: str) -> str:
    s = _HREF.sub(r"\1", s)
    for _ in range(3):
        s = _GENERIC.sub(r"\1", s)
    return " ".join(unescape_latex(s).split())


@dataclass
class ClaimDraft:
    id: str
    text: str
    evidence_ids: list[str]
    needs_confirmation: bool = False


def _link(url: str, label: str) -> str:
    u = safe_url(url)
    return rf"\href{{{u}}}{{{escape_latex(label)}}}" if u else escape_latex(label)


def _display(url: str) -> str:
    return re.sub(r"^(?:https?://|mailto:)(?:www\.)?", "", url).rstrip("/")


def contact_line(model: ResumeModel) -> str:
    c = model.contact
    parts: list[str] = []
    if c.get("email"):
        parts.append(_link("mailto:" + c["email"], c["email"]))
    if c.get("phone"):
        parts.append(escape_latex(c["phone"]))
    if c.get("location"):
        parts.append(escape_latex(c["location"]))
    for _k, u in (c.get("links") or {}).items():
        parts.append(_link(u, _display(u)))
    return r" \textbar{} ".join(parts)


def _entry_line(e: Entry) -> tuple[str, str]:
    loc = e.location
    args = [escape_latex(e.title), escape_latex(e.org), escape_latex(e.dates)]
    if e.kind == "project" and e.url:
        args.append(_link(e.url, _display(e.url)))
        loc = _display(e.url)
    else:
        args.append(escape_latex(loc))
    line = r"\cpentry" + "".join("{%s}" % a for a in args)
    plain = " | ".join(p for p in (latex_plain(a) for a in args) if p)
    return line, plain


def render_body(model: ResumeModel) -> tuple[str, list[ClaimDraft]]:
    out: list[str] = []
    claims: list[ClaimDraft] = []

    def claim(text: str, ev: list[str], needs: bool = False) -> str:
        cid = new_id()
        claims.append(ClaimDraft(cid, text, ev, needs or not ev))
        return f" % cp:claim={cid}"

    if model.summary:
        out.append(r"\cpsection{Summary}")
        t = escape_latex(model.summary[0])
        out.append(r"\cpsummary{%s}%s" % (t, claim(latex_plain(t), [model.summary[1]])))

    def entries(title: str, items: list[Entry]) -> None:
        if not items:
            return
        out.append(r"\cpsection{%s}" % title)
        for e in items:
            line, plain = _entry_line(e)
            out.append(line + claim(plain, [e.fact_id]))
            if e.bullets:
                out.append(r"\begin{cpitems}")
                for b in e.bullets:
                    t = escape_latex(b.text)
                    out.append(r"\item %s%s" % (t, claim(latex_plain(t), b.evidence_ids,
                                                          b.reworded)))
                out.append(r"\end{cpitems}")

    entries("Experience", model.experiences)
    entries("Education", model.education)
    entries("Projects", model.projects)
    if model.skill_groups:
        out.append(r"\cpsection{Skills}")
        for g in model.skill_groups:
            cat, items = escape_latex(g.category), escape_latex(", ".join(g.names))
            out.append(r"\cpskills{%s}{%s}%s" % (cat, items, claim(
                f"{latex_plain(cat)}: {latex_plain(items)}", g.fact_ids)))
    entries("Publications", model.publications)
    entries("Certifications", model.certifications)
    return "\n".join(out), claims


def fill_template(template: str, model: ResumeModel, body: str) -> str:
    # str.replace of fixed placeholders; filled values are already escaped LaTeX.
    return (template.replace("<<NAME>>", escape_latex(model.name or "Your Name"))
            .replace("<<CONTACT>>", contact_line(model)).replace("<<BODY>>", body))


def parse_source_claims(source: str) -> list[tuple[str | None, str, str]]:
    """Find claim-bearing lines in (possibly user-edited) LaTeX.
    Returns (claim_id | None, kind, plain_text)."""
    found: list[tuple[str | None, str, str]] = []
    for raw in source.splitlines():
        m = MARK.search(raw)
        cid = m.group(1) if m else None
        line = MARK.sub("", raw).rstrip()
        s = line.strip()
        if s.startswith(r"\item"):
            found.append((cid, "bullet", latex_plain(s[5:].strip())))
        elif s.startswith(r"\cpentry"):
            args = _brace_args(s[len(r"\cpentry"):])
            found.append((cid, "entry", " | ".join(p for p in (latex_plain(a) for a in args)
                                                   if p)))
        elif s.startswith(r"\cpskills"):
            a = _brace_args(s[len(r"\cpskills"):])
            if len(a) >= 2:
                found.append((cid, "skills", f"{latex_plain(a[0])}: {latex_plain(a[1])}"))
        elif s.startswith(r"\cpsummary"):
            a = _brace_args(s[len(r"\cpsummary"):])
            if a:
                found.append((cid, "summary", latex_plain(a[0])))
    return found


def _brace_args(s: str) -> list[str]:
    args, depth, buf, i = [], 0, "", 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            if depth > 0:
                buf += s[i:i + 2]
            i += 2
            continue
        if c == "{":
            depth += 1
            if depth > 1:
                buf += c
        elif c == "}":
            depth -= 1
            if depth == 0:
                args.append(buf)
                buf = ""
            elif depth > 0:
                buf += c
            else:
                break
        elif depth > 0:
            buf += c
        elif not c.isspace():
            break
        i += 1
    return args
