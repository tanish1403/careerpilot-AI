"""Post-compile ATS validation: extract the PDF text and compare it against what the source
says should be there (headings, order, content fragments, contact, links, single column)."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from ..documents.parsers import order_blocks, _column_gap  # noqa: F401
from .latex import unescape_latex
from .render import _brace_args, latex_plain, parse_source_claims

STANDARD_HEADINGS = {"summary", "experience", "education", "skills", "projects",
                     "publications", "certifications"}


def squash(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    return re.sub(r"[\W_]+", "", s, flags=re.U)


def expected_from_source(source: str) -> dict:
    name = contact = ""
    headings: list[str] = []
    urls: list[str] = []
    for raw in source.splitlines():
        s = raw.strip()
        if s.startswith(r"\cpname"):
            a = _brace_args(s[len(r"\cpname"):])
            name = latex_plain(a[0]) if a and "<<" not in a[0] else name
        elif s.startswith(r"\cpcontact"):
            a = _brace_args(s[len(r"\cpcontact"):])
            contact = a[0] if a and "<<" not in a[0] else contact
        elif s.startswith(r"\cpsection"):
            a = _brace_args(s[len(r"\cpsection"):])
            if a:
                headings.append(latex_plain(a[0]))
    for u in re.findall(r"\\href\{([^{}]+)\}", source):
        urls.append(u.replace(r"\%", "%").replace(r"\#", "#").replace(r"\~{}", "~"))
    claims = [t for _c, _k, t in parse_source_claims(source)]
    contact_plain = latex_plain(contact) if contact else ""
    return {"name": name, "headings": headings, "urls": sorted(set(urls)),
            "contact_plain": contact_plain, "claims": claims}


def validate_pdf(pdf_path: Path, source: str, compile_warnings: list[str] | None = None) -> dict:
    import pymupdf as fitz
    exp = expected_from_source(source)
    checks: list[dict] = []
    warnings: list[str] = list(compile_warnings or [])

    def chk(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    try:
        doc = fitz.open(pdf_path)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "checks": [{"name": "pdf_opens", "ok": False,
                                         "detail": type(e).__name__}], "warnings": warnings}
    with doc:
        pages = [p.get_text("text") for p in doc]
        text = "\n".join(pages)
        uris = {lk["uri"] for p in doc for lk in p.get_links() if lk.get("uri")}
        gap_pages = []
        for i, p in enumerate(doc, 1):
            blocks = [{"x0": b[0], "y0": b[1], "x1": b[2], "y1": b[3], "text": b[4]}
                      for b in p.get_text("blocks") if b[6] == 0]
            if _column_gap(blocks, p.rect.width) is not None:
                gap_pages.append(i)
        n_fonts = sum(len(p.get_fonts()) for p in doc)
        page_count = doc.page_count
    sq = squash(text)
    chk("text_extractable", len(sq) >= 40, f"{len(text)} characters extracted")
    lines = [ln.strip().lower() for ln in text.splitlines() if ln.strip()]
    missing_heads = [h for h in exp["headings"] if h.lower() not in lines]
    chk("headings_present", not missing_heads,
        "missing: " + ", ".join(missing_heads) if missing_heads else
        f"{len(exp['headings'])} headings found")
    nonstd = [h for h in exp["headings"] if h.lower() not in STANDARD_HEADINGS]
    if nonstd:
        warnings.append("Non-standard headings may confuse ATS parsers: " + ", ".join(nonstd))
    pos = [lines.index(h.lower()) for h in exp["headings"] if h.lower() in lines]
    chk("reading_order", pos == sorted(pos) and (
        not exp["name"] or not pos or squash(exp["name"]) in squash("".join(lines[:pos[0]]))),
        "name first, headings in order")
    frags: list[str] = []
    for c in exp["claims"]:
        frags.extend(x for x in c.split(" | ") if x.strip())
    missing = [f for f in frags if squash(f) and squash(f) not in sq]
    chk("content_matches_source", not missing,
        f"{len(frags) - len(missing)}/{len(frags)} content fragments found in PDF text"
        + (": e.g. " + "; ".join(m[:60] for m in missing[:3]) if missing else ""))
    cp = exp["contact_plain"]
    if cp:
        bad = [p for p in (x.strip() for x in cp.split("|")) if p and squash(p) not in sq]
        chk("contact_present", not bad, "all contact parts found" if not bad else
            "missing: " + "; ".join(bad))
    miss_urls = [u for u in exp["urls"] if unescape_latex(u) not in uris and u not in uris]
    chk("links_embedded", not miss_urls, f"{len(exp['urls']) - len(miss_urls)}/"
        f"{len(exp['urls'])} links are clickable"
        + (": missing " + ", ".join(miss_urls[:3]) if miss_urls else ""))
    chk("single_column", not gap_pages, "single-column layout" if not gap_pages else
        f"multi-column layout detected on page(s) {gap_pages}")
    if page_count > 2:
        warnings.append(f"Resume is {page_count} pages; most ATS/recruiters prefer 1-2.")
    if n_fonts == 0:
        warnings.append("No fonts found in the PDF.")
    return {"ok": all(c["ok"] for c in checks), "checks": checks, "warnings": warnings,
            "page_count": page_count, "text_chars": len(text)}
