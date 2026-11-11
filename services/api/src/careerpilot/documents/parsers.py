"""Document parsers. Every parser returns a ParsedDocument of Lines with source locations so
extracted facts can point back to where they came from."""
from __future__ import annotations

import io
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import ocr
from .errors import DocumentError

MAX_BYTES = 20 * 1024 * 1024
TEXT_EXT = {"txt", "md", "markdown", "tex", "latex", "html", "htm", "rtf"}
IMAGE_EXT = {"png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp"}
SUPPORTED_EXT = TEXT_EXT | IMAGE_EXT | {"pdf", "docx", "doc"}
_LIGATURES = {"\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl",
              "\u00a0": " ", "\u200b": "", "\ufeff": ""}
_BULLETS = "\u2022\u25cf\u25aa\u25e6\u2023\u00b7\u25a0\u2043\u2219\u25cb\uf0b7\uf0a7"


@dataclass
class Line:
    text: str
    loc: str


@dataclass
class ParsedDocument:
    lines: list[Line]
    parser: str
    warnings: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    pages: int | None = None
    ocr_used: bool = False

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)


def _clean(s: str) -> str:
    for k, v in _LIGATURES.items():
        s = s.replace(k, v)
    return re.sub(r"[ \t]+", " ", s).strip()


def _lines_from_text(text: str, prefix: str = "line") -> list[Line]:
    out: list[Line] = []
    prev_blank = True
    for i, raw in enumerate(text.splitlines(), 1):
        t = _clean(raw)
        if not t:
            if not prev_blank:
                out.append(Line("", f"{prefix} {i}"))
            prev_blank = True
            continue
        prev_blank = False
        out.append(Line(t, f"{prefix} {i}"))
    return out


def detect_kind(data: bytes, filename: str) -> str:
    ext = Path(filename or "").suffix.lower().lstrip(".")
    if ext not in SUPPORTED_EXT:
        raise DocumentError("unsupported_type",
                            f"Unsupported file type '.{ext or '?'}'. Supported: "
                            + ", ".join(sorted(SUPPORTED_EXT)))
    head = data[:8]
    if ext == "pdf":
        if b"%PDF" not in data[:1024]:
            raise DocumentError("corrupt_file", "File has a .pdf extension but is not a PDF.")
        return "pdf"
    if ext == "docx":
        if not head.startswith(b"PK"):
            raise DocumentError("corrupt_file", "File has a .docx extension but is not a DOCX.")
        return "docx"
    if ext == "doc":
        if head.startswith(b"PK"):
            return "docx"  # misnamed docx
        if not head.startswith(b"\xd0\xcf\x11\xe0"):
            raise DocumentError("corrupt_file", "File has a .doc extension but is not a DOC.")
        return "doc"
    if ext in IMAGE_EXT:
        ok = (head.startswith(b"\x89PNG") or head.startswith(b"\xff\xd8") or
              head[:4] in (b"II*\x00", b"MM\x00*") or head.startswith(b"BM") or
              (head.startswith(b"RIFF") and data[8:12] == b"WEBP"))
        if not ok:
            raise DocumentError("corrupt_file", f"File is not a valid .{ext} image.")
        return "image"
    if ext == "rtf":
        if not data.lstrip()[:5].startswith(b"{\\rtf"):
            raise DocumentError("corrupt_file", "File has an .rtf extension but is not RTF.")
        return "rtf"
    if b"\x00" in data[:4096] and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise DocumentError("corrupt_file", "File looks binary, not text.")
    return {"markdown": "md", "latex": "tex", "htm": "html"}.get(ext, ext)


def _decode(data: bytes, warnings: list[str]) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", "replace")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        warnings.append("File is not valid UTF-8; decoded as Windows-1252, check accents.")
        return data.decode("cp1252", "replace")


# ---------------------------------------------------------------- PDF
def _column_gap(blocks: list[dict], page_w: float) -> float | None:
    """Find a vertical whitespace gutter in the middle of the page. Returns its x centre."""
    narrow = [b for b in blocks if (b["x1"] - b["x0"]) < page_w * 0.6]
    if len(narrow) < 6:
        return None
    iv = sorted((b["x0"], b["x1"]) for b in narrow)
    merged: list[list[float]] = [list(iv[0])]
    for a, b in iv[1:]:
        if a <= merged[-1][1] + 6:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    best = None
    for i in range(len(merged) - 1):
        gap = merged[i + 1][0] - merged[i][1]
        centre = (merged[i][1] + merged[i + 1][0]) / 2
        if gap >= 10 and page_w * 0.15 <= centre <= page_w * 0.85:
            left = [b for b in narrow if b["x1"] <= centre and len(b["text"]) >= 40]
            right = [b for b in narrow if b["x0"] >= centre and len(b["text"]) >= 40]
            if len(left) >= 3 and len(right) >= 3 and (best is None or gap > best[0]):
                best = (gap, centre)
    return best[1] if best else None


def order_blocks(blocks: list[dict], page_w: float) -> list[dict]:
    """Reading order: full-width blocks separate bands; inside a band, left column then right."""
    gap = _column_gap(blocks, page_w)
    key = lambda b: (round(b["y0"] / 4), b["x0"])  # noqa: E731
    if gap is None:
        return sorted(blocks, key=key)
    out: list[dict] = []
    left: list[dict] = []
    right: list[dict] = []

    def flush() -> None:
        out.extend(sorted(left, key=lambda b: (b["y0"], b["x0"])))
        out.extend(sorted(right, key=lambda b: (b["y0"], b["x0"])))
        left.clear()
        right.clear()

    for b in sorted(blocks, key=lambda b: (b["y0"], b["x0"])):
        if b["x0"] < gap < b["x1"]:
            flush()
            out.append(b)
        elif b["x1"] <= gap:
            left.append(b)
        else:
            right.append(b)
    flush()
    return out


def _parse_pdf(data: bytes) -> ParsedDocument:
    import pymupdf as fitz
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as e:  # noqa: BLE001
        raise DocumentError("corrupt_file", f"PDF could not be opened: {type(e).__name__}") from e
    try:
        if doc.needs_pass:
            raise DocumentError("corrupt_file", "PDF is password-protected; remove the password.")
        if doc.page_count == 0:
            raise DocumentError("corrupt_file", "PDF has no readable pages (file is damaged).")
        warnings: list[str] = []
        lines: list[Line] = []
        links: list[str] = []
        used_ocr = False
        for pno, page in enumerate(doc, 1):
            try:
                raw = page.get_text("blocks")
                links += [lk["uri"] for lk in page.get_links() if lk.get("uri")]
            except Exception as e:  # noqa: BLE001
                raise DocumentError("corrupt_file",
                                    f"PDF page {pno} is damaged: {type(e).__name__}") from e
            blocks = [{"x0": b[0], "y0": b[1], "x1": b[2], "y1": b[3], "text": b[4].strip()}
                      for b in raw if b[6] == 0 and b[4].strip()]
            text_chars = sum(len(b["text"]) for b in blocks)
            page_lines: list[str] = []
            if text_chars < 25:
                if page.get_images(full=True) or text_chars == 0:
                    if ocr.is_available():
                        try:
                            page_lines = ocr.ocr_pdf_page(page).splitlines()
                            used_ocr = True
                            warnings.append(f"Page {pno}: text recognised with OCR; "
                                            "verify carefully.")
                        except Exception as e:  # noqa: BLE001
                            warnings.append(f"Page {pno}: OCR failed ({type(e).__name__}).")
                    else:
                        warnings.append(f"Page {pno} looks scanned and OCR is unavailable "
                                        "(install tesseract).")
            else:
                for b in order_blocks(blocks, page.rect.width):
                    page_lines.extend(b["text"].split("\n"))
            merged: list[str] = []
            for t in page_lines:
                t = _clean(t)
                if merged and merged[-1] and all(c in _BULLETS for c in merged[-1]):
                    merged[-1] = merged[-1] + " " + t
                else:
                    merged.append(t)
            for n, t in enumerate(merged, 1):
                if t:
                    lines.append(Line(t, f"page {pno}, line {n}"))
        if not any(line.text for line in lines):
            if not ocr.is_available() and any("scanned" in w for w in warnings):
                raise DocumentError("ocr_unavailable",
                                    "This PDF has no text layer (scanned). OCR needs the "
                                    "'tesseract' program, which was not found. Install it "
                                    "and re-run parsing.")
            raise DocumentError("empty_file", "No text could be extracted from the PDF.")
        parser = "pymupdf+ocr" if used_ocr else "pymupdf"
        return ParsedDocument(lines, parser, warnings, links, doc.page_count, used_ocr)
    finally:
        doc.close()


# ---------------------------------------------------------------- DOCX
def _parse_docx(data: bytes) -> ParsedDocument:
    import docx
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    try:
        d = docx.Document(io.BytesIO(data))
    except Exception as e:  # noqa: BLE001
        raise DocumentError("corrupt_file", f"DOCX could not be opened: {type(e).__name__}") from e
    lines: list[Line] = []
    warnings: list[str] = []
    seen_boxes: set[str] = set()

    def para_line(p: Paragraph, loc: str) -> None:
        t = _clean(p.text)
        if not t:
            if lines and lines[-1].text:
                lines.append(Line("", loc))
            return
        ppr = p._p.pPr
        is_list = ppr is not None and ppr.numPr is not None
        style = (p.style.name if p.style is not None else "") or ""
        if (is_list or style.lower().startswith("list")) and t[0] not in _BULLETS + "-*":
            t = "\u2022 " + t
        lines.append(Line(t, loc))

    def walk_table(tbl: Table, tno: int) -> None:
        for rno, row in enumerate(tbl.rows, 1):
            cells: list[str] = []
            seen_ids: set[int] = set()
            for cell in row.cells:
                if id(cell._tc) in seen_ids:
                    continue
                seen_ids.add(id(cell._tc))
                parts = [_clean(p.text) for p in cell.paragraphs if _clean(p.text)]
                if parts:
                    cells.append(" ".join(parts))
                for nested in cell.tables:
                    walk_table(nested, tno)
            if cells:
                lines.append(Line(" | ".join(cells), f"table {tno}, row {rno}"))
        lines.append(Line("", f"table {tno} end"))

    for sec in d.sections:
        for p in sec.header.paragraphs:
            if _clean(p.text):
                lines.append(Line(_clean(p.text), "header"))
    pno = tno = 0
    for child in d.element.body.iterchildren():
        if child.tag == qn("w:p"):
            pno += 1
            para_line(Paragraph(child, d), f"paragraph {pno}")
        elif child.tag == qn("w:tbl"):
            tno += 1
            walk_table(Table(child, d), tno)
    for tx in d.element.body.iter(qn("w:txbxContent")):
        t = _clean(" ".join(x.text or "" for x in tx.iter(qn("w:t"))))
        if t and t not in seen_boxes and all(t not in line.text for line in lines):
            seen_boxes.add(t)
            lines.append(Line(t, "text box"))
            warnings.append("Text boxes were found; their reading order may be uncertain.")
    links = [r.target_ref for r in d.part.rels.values()
             if r.reltype.endswith("/hyperlink") and r.is_external]
    if not any(line.text for line in lines):
        raise DocumentError("empty_file", "The DOCX contains no text.")
    return ParsedDocument(lines, "python-docx", sorted(set(warnings)), links)


# ---------------------------------------------------------------- legacy DOC
def _parse_doc(data: bytes) -> ParsedDocument:
    with tempfile.TemporaryDirectory(prefix="cp_doc_") as d:
        src = Path(d) / "in.doc"
        src.write_bytes(data)
        antiword = shutil.which("antiword")
        if antiword:
            try:
                p = subprocess.run([antiword, str(src)], capture_output=True, timeout=60,
                                   check=False)
            except subprocess.TimeoutExpired as e:
                raise DocumentError("corrupt_file", "antiword timed out on this file.") from e
            if p.returncode == 0 and p.stdout.strip():
                w: list[str] = []
                lines = _lines_from_text(_decode(p.stdout, w))
                return ParsedDocument(lines, "antiword", w + ["Legacy .doc parsed best-effort."])
        office = shutil.which("soffice") or shutil.which("libreoffice")
        if office:
            try:
                p = subprocess.run([office, "--headless", "--convert-to", "docx", "--outdir", d,
                                    str(src)], capture_output=True, timeout=120, check=False,
                                   env={"HOME": d, "PATH": "/usr/bin:/bin:/usr/local/bin"})
            except subprocess.TimeoutExpired as e:
                raise DocumentError("corrupt_file", "LibreOffice timed out.") from e
            out = Path(d) / "in.docx"
            if out.exists():
                parsed = _parse_docx(out.read_bytes())
                parsed.parser = "libreoffice+python-docx"
                parsed.warnings.append("Legacy .doc converted best-effort via LibreOffice.")
                return parsed
            raise DocumentError("corrupt_file", "LibreOffice could not convert this .doc file.")
    raise DocumentError("unsupported_type",
                        "Legacy .doc files need 'antiword' or LibreOffice installed. "
                        "Save the file as .docx or PDF and upload that instead.")


# ---------------------------------------------------------------- text-ish formats
def _parse_txt(data: bytes) -> ParsedDocument:
    w: list[str] = []
    return ParsedDocument(_lines_from_text(_decode(data, w)), "text", w)


_MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+|mailto:[^)\s]+)\)")


def _parse_md(data: bytes) -> ParsedDocument:
    w: list[str] = []
    text = _decode(data, w)
    links = [m.group(2) for m in _MD_LINK.finditer(text)]
    text = _MD_LINK.sub(lambda m: f"{m.group(1)} ({m.group(2)})", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)
    text = re.sub(r"(?<![\w*])[*_]([^*_\n]+)[*_](?![\w*])", r"\1", text)
    text = re.sub(r"^\s*[*+-]\s+", "\u2022 ", text, flags=re.M)
    text = re.sub(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$", "", text, flags=re.M)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    return ParsedDocument(_lines_from_text(text), "markdown", w, links)


def _parse_rtf(data: bytes) -> ParsedDocument:
    from striprtf.striprtf import rtf_to_text
    w: list[str] = []
    try:
        text = rtf_to_text(_decode(data, w), errors="ignore")
    except Exception as e:  # noqa: BLE001
        raise DocumentError("corrupt_file", f"RTF could not be parsed: {type(e).__name__}") from e
    lines = _lines_from_text(text)
    if not any(line.text for line in lines):
        raise DocumentError("empty_file", "The RTF contains no text.")
    return ParsedDocument(lines, "striprtf", w)


_TEX_SEC = re.compile(r"\\(?:sub)*section\*?\{([^{}]*)\}|\\(?:cv|resume)section\{([^{}]*)\}")


def latex_to_text(src: str) -> tuple[str, list[str]]:
    src = re.sub(r"(?<!\\)%.*", "", src)
    links = re.findall(r"\\href\{([^{}]+)\}", src) + re.findall(r"\\url\{([^{}]+)\}", src)
    m = re.search(r"\\begin\{document\}(.*)\\end\{document\}", src, re.S)
    if m:
        src = m.group(1)
    src = _TEX_SEC.sub(lambda m: f"\n\n{m.group(1) or m.group(2)}\n", src)
    src = re.sub(r"\\href\{([^{}]*)\}\{([^{}]*)\}", r"\2 (\1)", src)
    src = re.sub(r"\\begin\{(?:itemize|enumerate|description)\}(\[[^\]]*\])?", "\n", src)
    src = re.sub(r"\\item(\[[^\]]*\])?", "\n\u2022 ", src)
    src = re.sub(r"\\(?:\\|newline|par)\*?(\[[^\]]*\])?", "\n", src)
    src = re.sub(r"\\(?:hfill|quad|qquad|vspace\*?\{[^}]*\}|hspace\*?\{[^}]*\})", " ", src)
    for _ in range(6):  # innermost-first removal of \cmd{...}
        src = re.sub(r"\}\s*\{", "} | {", src)
        new = re.sub(r"\\[a-zA-Z@]+\*?(?:\[[^\]]*\])?\{([^{}]*)\}", r"\1", src)
        if new == src:
            break
        src = new
    src = re.sub(r"\\begin\{[^}]*\}|\\end\{[^}]*\}", "\n", src)
    for a, b in (("\\&", "&"), ("\\%", "%"), ("\\$", "$"), ("\\#", "#"), ("\\_", "_"),
                 ("\\{", "{"), ("\\}", "}"), ("~", " "), ("---", "\u2014"), ("--", "\u2013")):
        src = src.replace(a, b)
    src = re.sub(r"\\[a-zA-Z@]+\*?", " ", src)
    src = src.replace("$", "").replace("{", "").replace("}", "")
    return src, links


def _parse_tex(data: bytes) -> ParsedDocument:
    w: list[str] = []
    text, links = latex_to_text(_decode(data, w))
    lines = _lines_from_text(text)
    if not any(line.text for line in lines):
        raise DocumentError("empty_file", "The LaTeX file contains no readable text.")
    return ParsedDocument(lines, "latex-strip", w, links)


def _parse_html(data: bytes) -> ParsedDocument:
    from bs4 import BeautifulSoup
    w: list[str] = []
    soup = BeautifulSoup(_decode(data, w), "html.parser")
    for t in soup(["script", "style", "noscript", "template", "head"]):
        t.decompose()
    hidden = [t for t in soup.find_all(True)
              if t.get("hidden") is not None or t.get("aria-hidden") == "true"
              or re.search(r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0",
                           t.get("style", "") or "", re.I)]
    for t in hidden:
        t.decompose()
    if hidden:
        w.append("Hidden HTML elements were ignored.")
    links = [a["href"] for a in soup.find_all("a", href=True)]
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for t in soup.find_all(["td", "th"]):
        t.append(" | ")
    for t in soup.find_all(["p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr",
                            "section", "ul", "ol", "table", "header", "footer", "article"]):
        t.insert_before("\n")
        t.append("\n")
    for li in soup.find_all("li"):
        li.insert(0, "\u2022 ")
    text = soup.get_text()
    text = re.sub(r"\|\s*\n", "\n", text)
    lines = _lines_from_text(text)
    if not any(line.text for line in lines):
        raise DocumentError("empty_file", "The HTML contains no visible text.")
    return ParsedDocument(lines, "beautifulsoup", w, links)


def _parse_image(data: bytes, filename: str) -> ParsedDocument:
    if not ocr.is_available():
        raise DocumentError("ocr_unavailable",
                            "Images need OCR, but the 'tesseract' program was not found. "
                            "Install tesseract or upload a text-based PDF/DOCX.")
    suffix = Path(filename).suffix.lower() or ".png"
    try:
        text = ocr.ocr_image_bytes(data, suffix)
    except Exception as e:  # noqa: BLE001
        raise DocumentError("corrupt_file", f"OCR could not read the image: {e}") from e
    lines = _lines_from_text(text)
    if not any(line.text for line in lines):
        raise DocumentError("empty_file", "OCR found no text in the image.")
    return ParsedDocument(lines, "tesseract", ["Text recognised with OCR; verify carefully."],
                          ocr_used=True)


def parse_bytes(data: bytes, filename: str) -> ParsedDocument:
    """Parse an uploaded file. Raises DocumentError with a contract-defined code."""
    if not data:
        raise DocumentError("empty_file", "The file is empty (0 bytes).")
    if len(data) > MAX_BYTES:
        raise DocumentError("too_large", f"File exceeds {MAX_BYTES // (1024 * 1024)} MB limit.")
    kind = detect_kind(data, filename)
    if kind == "pdf":
        return _parse_pdf(data)
    if kind == "docx":
        return _parse_docx(data)
    if kind == "doc":
        return _parse_doc(data)
    if kind == "image":
        return _parse_image(data, filename)
    parsed = {"txt": _parse_txt, "md": _parse_md, "rtf": _parse_rtf, "tex": _parse_tex,
              "html": _parse_html}[kind](data)
    if not any(line.text for line in parsed.lines):
        raise DocumentError("empty_file", "The file contains no text.")
    return parsed
