import pytest

import b_support as S
from careerpilot.documents import ocr
from careerpilot.documents.errors import DocumentError
from careerpilot.documents.parsers import parse_bytes
from careerpilot.documents.extractor import extract


def _text(data, name):
    return parse_bytes(data, name).text


def test_txt_md_rtf_tex_html():
    assert "Jane Q. Doe" in _text(S.RESUME_TEXT.encode(), "r.txt")
    md = "# Jane Doe\n\n## Experience\n* Built **things** at [Acme](https://acme.example)\n"
    p = parse_bytes(md.encode(), "r.md")
    assert "Built things at Acme (https://acme.example)" in p.text and "#" not in p.text
    assert p.links == ["https://acme.example"]
    rtf = rb"{\rtf1\ansi\deff0 {\fonttbl{\f0 Arial;}} Jane Doe\par Experience\par Built things\par}"
    assert "Built things" in _text(rtf, "r.rtf")
    tex = (r"\documentclass{article}\begin{document}\section{Experience}"
           r"\textbf{Engineer} \hfill 2020\begin{itemize}\item Built \& shipped X\end{itemize}"
           "% comment\n\\end{document}")
    t = _text(tex.encode(), "r.tex")
    assert "Experience" in t and "Built & shipped X" in t and "comment" not in t
    html = ("<html><head><style>x{}</style></head><body><h1>Jane</h1><p>Hello <b>World</b></p>"
            "<div style='display:none'>HIDDEN-INJECT</div><ul><li>Item A</li></ul>"
            "<a href='https://x.example'>x</a></body></html>")
    h = parse_bytes(html.encode(), "r.html")
    assert "Hello World" in h.text and "HIDDEN-INJECT" not in h.text and "Item A" in h.text
    assert h.links == ["https://x.example"]
    assert any("Hidden" in w for w in h.warnings)


def test_docx_with_list_bullets_and_extraction():
    d = parse_bytes(S.make_docx_resume(), "r.docx")
    assert any(ln.text.startswith("• Built a payments") for ln in d.lines)
    res = extract(d)
    exp = [f for f in res.facts if f.category == "experience"]
    assert exp and exp[0].value["company"] == "Acme Corp"
    assert len(exp[0].value["bullets"]) == 2
    assert exp[0].value["start_date"] == "2020-01" and exp[0].value["end_date"] == "Present"


def test_docx_tables_are_read():
    d = parse_bytes(S.make_table_docx(), "t.docx")
    assert "Data Analyst, Initech | Mar 2019 - Present" in d.text
    assert "Languages | SQL, Python" in d.text
    res = extract(d)
    cats = {f.category for f in res.facts}
    assert "experience" in cats and "skill" in cats


def test_two_column_pdf_reading_order():
    d = parse_bytes(S.make_two_column_pdf(), "c.pdf")
    t = d.text
    left = [t.index(f"LEFTCOL-{x}") for x in ("ALPHA", "BETA", "GAMMA", "DELTA")]
    right = [t.index(f"RIGHTCOL-{x}") for x in ("ALPHA", "BETA", "GAMMA")]
    assert left == sorted(left) and right == sorted(right)
    assert max(left) < min(right), "whole left column must be read before the right column"
    assert t.index("Alex Columnar") < min(left)
    assert d.pages == 1


def test_corrupt_empty_unsupported():
    with pytest.raises(DocumentError) as e:
        parse_bytes(S.CORRUPT_PDF, "x.pdf")
    assert e.value.code == "corrupt_file"
    with pytest.raises(DocumentError) as e:
        parse_bytes(b"not a pdf at all", "x.pdf")
    assert e.value.code == "corrupt_file"
    with pytest.raises(DocumentError) as e:
        parse_bytes(S.CORRUPT_DOCX, "x.docx")
    assert e.value.code == "corrupt_file"
    with pytest.raises(DocumentError) as e:
        parse_bytes(b"", "x.pdf")
    assert e.value.code == "empty_file"
    with pytest.raises(DocumentError) as e:
        parse_bytes(b"   \n \n", "x.txt")
    assert e.value.code == "empty_file"
    with pytest.raises(DocumentError) as e:
        parse_bytes(b"MZ\x90\x00", "x.exe")
    assert e.value.code == "unsupported_type"
    with pytest.raises(DocumentError) as e:
        parse_bytes(b"\x00\x01\x02\x03" * 50, "x.txt")
    assert e.value.code == "corrupt_file"


def test_non_english_extraction():
    d = parse_bytes(S.SPANISH_TEXT.encode(), "es.txt")
    res = extract(d)
    by = {f.category: f for f in res.facts}
    assert by["contact"].value["full_name"] == "María García López"
    exp = by["experience"].value
    assert exp["company"] == "Telefónica" and exp["start_date"] == "2018-01"
    assert exp["end_date"] == "Present"
    assert by["education"].value["institution"].startswith("Universidad")
    assert {f.value["name"] for f in res.facts if f.category == "skill"} >= {"Java", "SQL"}


def test_legacy_doc_gives_clear_result(tmp_path):
    # A real OLE header but junk content: either converted (unlikely) or a clear error.
    junk = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600
    with pytest.raises(DocumentError) as e:
        parse_bytes(junk, "old.doc")
    assert e.value.code in ("unsupported_type", "corrupt_file")
    assert e.value.message


@pytest.mark.skipif(not ocr.is_available(), reason="tesseract not installed")
def test_scanned_pdf_uses_ocr():
    d = parse_bytes(S.make_scanned_pdf(), "scan.pdf")
    assert d.ocr_used and d.parser == "pymupdf+ocr"
    assert "Rita" in d.text and any("OCR" in w for w in d.warnings)


def test_scanned_pdf_without_ocr_reports_clearly(monkeypatch):
    monkeypatch.setattr(ocr, "is_available", lambda: False)
    with pytest.raises(DocumentError) as e:
        parse_bytes(S.make_scanned_pdf(), "scan.pdf")
    assert e.value.code == "ocr_unavailable" and "tesseract" in e.value.message


def test_extraction_never_confirms():
    res = extract(parse_bytes(S.RESUME_TEXT.encode(), "r.txt"))
    assert res.facts
    assert all(f.status == "proposed" for f in res.facts)
    assert all(0 <= f.confidence <= 1 for f in res.facts)
    assert all(f.source_location for f in res.facts)
    cats = {f.category for f in res.facts}
    assert {"contact", "summary", "experience", "education", "skill", "project",
            "certification"} <= cats
