import pymupdf
import pytest

import b_support as S
from careerpilot.documents import profile_service as ps
from careerpilot.resume_engine import compiler
from careerpilot.resume_engine import service as svc
from careerpilot.resume_engine import versions as vs

pytestmark = pytest.mark.skipif(compiler.xelatex_path() is None, reason="xelatex not installed")
JD = "Backend engineer: Python, Kafka, Kubernetes, payments, latency."


def _pdf_text(path):
    with pymupdf.open(path) as d:
        return "\n".join(p.get_text() for p in d)


@pytest.mark.parametrize("tpl", ["classic", "modern"])
def test_compile_and_validate_real_pdf(db, tpl):
    p, _ = S.seed_confirmed_profile(db)
    v = svc.generate(db, p, job_description=JD, template_id=tpl)
    rep = v.validation_report
    assert rep["compile"]["ok"], rep["compile"]
    assert v.pdf_path and open(v.pdf_path, "rb").read(4) == b"%PDF"
    pdf = rep["pdf"]
    names = {c["name"]: c for c in pdf["checks"]}
    assert pdf["ok"], pdf
    for n in ("text_extractable", "headings_present", "reading_order",
              "content_matches_source", "contact_present", "links_embedded", "single_column"):
        assert names[n]["ok"], names[n]
    assert pdf["page_count"] == 1
    text = _pdf_text(v.pdf_path)
    for needle in ("Jane Q. Doe", "Acme Corp", "Jan 2020", "2M requests", "35%", "Kafka",
                   "Technical University of Munich", "jane.doe@example.com"):
        assert needle in text, needle
    for banned in ("FakeCo", "Haskell", "RejectedCo"):
        assert banned not in text
    # heading order as rendered
    low = text.lower()
    assert low.index("experience") < low.index("education") < low.index("skills")
    with pymupdf.open(v.pdf_path) as d:
        uris = {lk["uri"] for pg in d for lk in pg.get_links()}
    assert "mailto:jane.doe@example.com" in uris and "https://github.com/janedoe" in uris


def test_validator_detects_content_mismatch(db):
    from careerpilot.resume_engine import validator
    p, _ = S.seed_confirmed_profile(db)
    v = svc.generate(db, p, compile_pdf=True)
    tampered = v.latex_source.replace(r"\cpsection{Skills}",
                                      r"\cpsection{Skills}" + "\n" + r"\cpskills{Fake}{Quantum} "
                                      "% cp:claim=" + "a" * 32)
    rep = validator.validate_pdf(__import__("pathlib").Path(v.pdf_path), tampered)
    assert not rep["ok"]
    assert not {c["name"]: c for c in rep["checks"]}["content_matches_source"]["ok"]


def test_latex_injection_in_user_text_is_inert(db, tmp_path):
    p = ps.get_profile(db)
    ps.update_profile(db, p, {"full_name": r"Eve \input{/etc/passwd}", "email": "e@example.com"})
    ps.create_item(db, p, "experience", {
        "company": r"Evil\write18{touch /tmp/pwned_cp} & Co", "title": r"Hacker $\catcode`\%=9$",
        "start_date": "2020", "end_date": "2021",
        "bullets": [r"Used \immediate\write18{id} 100% of #the _time_ ^ ~ {braces}",
                    r"\openout3=/tmp/pwned_cp2 \input{resume.tex}"]})
    import os
    v = svc.generate(db, p)
    assert v.validation_report["compile"]["ok"], v.validation_report["compile"]
    assert not os.path.exists("/tmp/pwned_cp") and not os.path.exists("/tmp/pwned_cp2")
    assert r"\input{" not in v.latex_source.replace(r"\textbackslash{}input", "")
    text = _pdf_text(v.pdf_path)
    assert "root:" not in text                       # /etc/passwd was not read
    assert "\\input" in text or "input" in text      # shown literally
    assert "write18" in text and "touch /tmp/pwned_cp" in text
    assert v.validation_report["pdf"]["ok"], v.validation_report["pdf"]


def test_compiler_blocks_file_reads_and_shell_even_if_scan_bypassed():
    src = ("\\documentclass{article}\\begin{document}\n\\input{/etc/passwd}\n"
           "\\end{document}")
    out = __import__("pathlib").Path(__import__("tempfile").mkdtemp()) / "o.pdf"
    res = compiler.compile_latex(src, out, timeout=30)
    if res.ok:
        assert "root:" not in _pdf_text(out)
    shell = ("\\documentclass{article}\\begin{document}\\immediate\\write18{touch /tmp/pwned_cp3}"
             "x\\end{document}")
    compiler.compile_latex(shell, out, timeout=30)
    assert not __import__("os").path.exists("/tmp/pwned_cp3")


def test_compile_timeout_is_enforced(tmp_path):
    loop = ("\\documentclass{article}\\begin{document}\\makeatletter"
            "\\@whilenum 1=1 \\do{}\\makeatother\\end{document}")
    res = compiler.compile_latex(loop, tmp_path / "o.pdf", timeout=3)
    assert not res.ok and res.timed_out and "timed out" in res.error


def test_compile_error_reported(tmp_path):
    res = compiler.compile_latex("\\documentclass{article}\\begin{document}\\undefinedcmd"
                                 "\\end{document}", tmp_path / "o.pdf", timeout=30)
    assert not res.ok and "undefinedcmd" in res.log_excerpt


def test_restore_keeps_pdf_and_diff_against_original(db):
    p, _ = S.seed_confirmed_profile(db)
    v1 = svc.generate(db, p)
    v2 = svc.edit_source(db, p, v1, v1.latex_source.replace("Mentored 4", "Mentored 5"),
                         compile_pdf=True)
    assert v2.validation_report["compile"]["ok"] and v2.pdf_path != v1.pdf_path
    r = svc.restore(db, p, v1)
    assert r.pdf_path and r.pdf_path != v1.pdf_path
    assert "Mentored 5" not in _pdf_text(r.pdf_path)
    d = vs.diff_sources(vs.root_of(db, v2).latex_source, v2.latex_source, [], [])
    assert "Mentored 5" in " ".join(h["text"] for h in d["hunks"] if h["op"] == "add")
