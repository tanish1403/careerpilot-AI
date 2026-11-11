"""Programmatic fixture documents + profile seeding helpers for Lane B tests."""
from __future__ import annotations

import io

RESUME_TEXT = """Jane Q. Doe
Berlin, Germany | jane.doe@example.com | +49 151 2345 6789 | github.com/janedoe
Senior Software Engineer

SUMMARY
Backend engineer focused on distributed systems and data pipelines.

EXPERIENCE
Senior Software Engineer, Acme Corp - Berlin, Germany    Jan 2020 - Present
- Built a payments service handling 2M requests per day using Python and Kafka.
- Reduced p99 latency by 35% by redesigning the caching layer.
- Mentored 4 junior engineers.
Software Engineer
Globex Inc | Munich    06/2016 - Dec 2019
- Led migration of 40 services to Kubernetes.
- Wrote internal Go tooling for deployments.

EDUCATION
Technical University of Munich
M.Sc. in Computer Science, 2014 - 2016 GPA: 1.7

SKILLS
Languages: Python, Go, SQL
Tools: Docker, Kubernetes, Kafka

PROJECTS
Tinysearch | Rust, Tantivy
- Built a search engine over 1M documents.

CERTIFICATIONS
AWS Certified Solutions Architect - Amazon Web Services, 2021
"""

SPANISH_TEXT = """María García López
Madrid, España | maria.garcia@example.es | +34 600 123 456

EXPERIENCIA
Ingeniera de Software, Telefónica - Madrid    enero 2018 - Presente
- Diseñé microservicios para facturación con Java y Spring.

EDUCACIÓN
Universidad Politécnica de Madrid
Grado en Ingeniería Informática, 2013 - 2017

HABILIDADES
Lenguajes: Java, Python, SQL
"""


def docx_bytes(lines: list[tuple[str, str]]) -> bytes:
    import docx
    d = docx.Document()
    for style, text in lines:
        if style == "bullet":
            d.add_paragraph(text, style="List Bullet")
        elif style == "h":
            d.add_heading(text, level=1)
        else:
            d.add_paragraph(text)
    b = io.BytesIO()
    d.save(b)
    return b.getvalue()


def make_docx_resume() -> bytes:
    return docx_bytes([
        ("p", "Jane Q. Doe"),
        ("p", "Berlin, Germany | jane.doe@example.com | +49 151 2345 6789"),
        ("h", "Experience"),
        ("p", "Senior Software Engineer, Acme Corp - Berlin    Jan 2020 - Present"),
        ("bullet", "Built a payments service handling 2M requests per day."),
        ("bullet", "Reduced p99 latency by 35%."),
        ("h", "Education"),
        ("p", "Technical University of Munich"),
        ("p", "M.Sc. in Computer Science, 2014 - 2016"),
        ("h", "Skills"),
        ("p", "Languages: Python, Go, SQL"),
    ])


def make_table_docx() -> bytes:
    import docx
    d = docx.Document()
    d.add_paragraph("Sam Table")
    d.add_paragraph("sam.table@example.com")
    d.add_heading("Experience", level=1)
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text = "Data Analyst, Initech"
    t.cell(0, 1).text = "Mar 2019 - Present"
    t.cell(1, 0).text = "Built dashboards for 12 teams."
    t.cell(1, 1).text = ""
    d.add_heading("Skills", level=1)
    t2 = d.add_table(rows=1, cols=2)
    t2.cell(0, 0).text = "Languages"
    t2.cell(0, 1).text = "SQL, Python"
    b = io.BytesIO()
    d.save(b)
    return b.getvalue()


def make_two_column_pdf() -> bytes:
    import pymupdf as fitz
    doc = fitz.open()
    page = doc.new_page()  # 595 x 842
    page.insert_textbox(fitz.Rect(40, 30, 555, 70), "Alex Columnar", fontsize=16)
    page.insert_textbox(fitz.Rect(40, 62, 555, 80),
                        "alex.columnar@example.com | Zurich, Switzerland", fontsize=10)
    left = [
        (100, "EXPERIENCE\nLEFTCOL-ALPHA Staff Engineer at Orbit Labs 2019 - Present\n"
              "Designed the LEFTCOL-BETA ingestion platform used by many teams across the "
              "organisation every single day without fail."),
        (260, "LEFTCOL-GAMMA Wrote extensive runbooks and mentoring material for new hires "
              "joining the platform group during rapid growth."),
        (400, "LEFTCOL-DELTA Led incident response rotations and postmortems for the whole "
              "infrastructure organisation for three years."),
    ]
    right = [
        (100, "SKILLS\nRIGHTCOL-ALPHA Python, Rust, Postgres and a long list of other "
              "technologies used daily in production systems everywhere."),
        (260, "EDUCATION\nRIGHTCOL-BETA ETH Zurich MSc Computer Science 2012 - 2014 with a "
              "focus on distributed algorithms and systems."),
        (400, "RIGHTCOL-GAMMA Additional coursework in databases, compilers and operating "
              "systems taught at the university level."),
    ]
    for y, t in left:
        page.insert_textbox(fitz.Rect(40, y, 270, y + 140), t, fontsize=10)
    for y, t in right:
        page.insert_textbox(fitz.Rect(320, y, 555, y + 140), t, fontsize=10)
    return doc.tobytes()


def make_text_pdf(text: str) -> bytes:
    import pymupdf as fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(40, 40, 555, 800), text, fontsize=10)
    return doc.tobytes()


def make_scanned_pdf() -> bytes:
    """A PDF whose only content is a raster image of text (no text layer)."""
    import pymupdf as fitz
    src = fitz.open()
    p = src.new_page()
    p.insert_textbox(fitz.Rect(40, 40, 555, 400),
                     "Rita Scanner\nrita.scanner@example.com\n\nEXPERIENCE\n"
                     "Field Engineer, Scanco 2018 - 2022\nSKILLS\nPython, Excel", fontsize=18)
    png = p.get_pixmap(dpi=200).tobytes("png")
    out = fitz.open()
    page = out.new_page()
    page.insert_image(page.rect, stream=png)
    return out.tobytes()


CORRUPT_PDF = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog /Pages 99 0 R >>\nthis is not a real pdf"
CORRUPT_DOCX = b"PK\x03\x04 definitely not a zip archive"


def seed_confirmed_profile(db, extra_unconfirmed: bool = True):
    """Create a profile with confirmed facts (+ optionally PROPOSED ones that must never leak)."""
    from careerpilot.documents import profile_service as ps
    p = ps.get_profile(db)
    ps.update_profile(db, p, {"full_name": "Jane Q. Doe", "email": "jane.doe@example.com",
                              "phone": "+49 151 2345 6789", "location": "Berlin, Germany",
                              "links": {"github": "https://github.com/janedoe"},
                              "summary": "Backend engineer focused on distributed systems."})
    ids = {}
    def item(cat, data):
        r = ps.create_item(db, p, cat, data)
        ids[(cat, data.get("name") or data.get("company") or data.get("institution"))] = r.fact_id
        return r
    item("experience", {"company": "Acme Corp", "title": "Senior Software Engineer",
                        "location": "Berlin, Germany", "start_date": "Jan 2020",
                        "end_date": "Present",
                        "bullets": ["Built a payments service handling 2M requests per day "
                                    "using Python and Kafka.",
                                    "Reduced p99 latency by 35% by redesigning the caching "
                                    "layer.",
                                    "Mentored 4 junior engineers.",
                                    "Organised the quarterly team offsite."]})
    item("experience", {"company": "Globex Inc", "title": "Software Engineer",
                        "start_date": "2016-06", "end_date": "2019-12",
                        "bullets": ["Led migration of 40 services to Kubernetes.",
                                    "Wrote internal Go tooling for deployments."]})
    item("education", {"institution": "Technical University of Munich", "degree": "M.Sc.",
                       "field": "Computer Science", "start_date": "2014", "end_date": "2016"})
    for n, c in [("Python", "Languages"), ("Go", "Languages"), ("SQL", "Languages"),
                 ("Kubernetes", "Tools"), ("Kafka", "Tools")]:
        item("skill", {"name": n, "category": c})
    item("project", {"name": "Tinysearch", "technologies": ["Rust"],
                     "bullets": ["Built a search engine over 1M documents."]})
    if extra_unconfirmed:
        ps.create_fact(db, p, "experience", {
            "company": "FakeCo Ghost Ltd", "title": "Chief Fabrication Officer",
            "start_date": "2010", "end_date": "2012",
            "bullets": ["Increased revenue by 999% at FakeCo."]}, status="proposed")
        ps.create_fact(db, p, "skill", {"name": "Haskell", "category": "Languages"},
                       status="proposed")
        ps.create_fact(db, p, "experience", {"company": "RejectedCo", "title": "Engineer",
                                             "start_date": "2001", "end_date": "2002",
                                             "bullets": ["Rejected bullet."]},
                       status="rejected")
    db.flush()
    return p, ids
