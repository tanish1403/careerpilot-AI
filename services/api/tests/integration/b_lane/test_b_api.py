import io

import pytest

import b_support as S
from careerpilot.resume_engine import compiler


def _upload(client, name, data, kind="resume"):
    return client.post("/api/v1/documents", files={"file": (name, io.BytesIO(data))},
                       data={"kind": kind})


def test_upload_review_confirm_flow(client):
    r = _upload(client, "resume.txt", S.RESUME_TEXT.encode())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["parse_run"]["status"] == "succeeded" and body["parse_run"]["parser"] == "text"
    facts = body["parse_run"]["facts"]
    assert facts and all(f["status"] == "proposed" for f in facts)
    assert all(f["source_document_id"] == body["document"]["id"] for f in facts)
    doc_id, run_id = body["document"]["id"], body["parse_run"]["id"]
    assert client.get(f"/api/v1/documents/{doc_id}").json()["filename"] == "resume.txt"
    assert client.get("/api/v1/documents").json()["total"] == 1
    dl = client.get(f"/api/v1/documents/{doc_id}/download")
    assert dl.content == S.RESUME_TEXT.encode()
    assert client.get(f"/api/v1/documents/{doc_id}/parse-runs").json()["total"] == 1
    pr = client.get(f"/api/v1/parse-runs/{run_id}").json()
    assert pr["facts"] and "warnings" in pr
    # nothing confirmed => items empty, profile untouched
    assert client.get("/api/v1/experiences").json()["total"] == 0
    assert client.get("/api/v1/facts?status=confirmed").json()["total"] == 0
    # confirm experience + contact
    exp = [f for f in facts if f["category"] == "experience"][0]
    c = client.post(f"/api/v1/facts/{exp['id']}/confirm")
    assert c.status_code == 200 and c.json()["status"] == "confirmed"
    items = client.get("/api/v1/experiences").json()
    assert items["total"] == 1 and items["items"][0]["fact_id"] == exp["id"]
    contact = [f for f in facts if f["category"] == "contact"][0]
    client.post(f"/api/v1/facts/{contact['id']}/confirm")
    prof = client.get("/api/v1/profiles/current").json()
    assert prof["full_name"] == "Jane Q. Doe" and prof["version"] >= 3
    assert {"score", "missing"} <= set(prof["completeness"])
    assert isinstance(prof["contradictions"], list)
    # patch semantics
    f2 = [f for f in facts if f["category"] == "skill"][0]
    pt = client.patch(f"/api/v1/facts/{f2['id']}", json={"value": {"name": "Python 3"}})
    assert pt.json()["status"] == "proposed" and pt.json()["value"]["name"] == "Python 3"
    pt = client.patch(f"/api/v1/facts/{f2['id']}", json={"value": {"name": "Python"},
                                                         "confirm": True})
    assert pt.json()["status"] == "confirmed"
    assert client.post(f"/api/v1/facts/{f2['id']}/reject").json()["status"] == "rejected"
    assert client.get("/api/v1/facts?category=skill&status=rejected").json()["total"] == 1
    assert client.post("/api/v1/facts/nope/confirm").status_code == 404
    # re-parse creates a new parse run
    rp = client.post(f"/api/v1/documents/{doc_id}/parse")
    assert rp.status_code == 200 and rp.json()["id"] != run_id
    assert client.get(f"/api/v1/documents/{doc_id}/parse-runs").json()["total"] == 2


@pytest.mark.parametrize("name,data,code", [
    ("x.pdf", S.CORRUPT_PDF, "corrupt_file"), ("x.docx", S.CORRUPT_DOCX, "corrupt_file"),
    ("x.txt", b"", "empty_file"), ("x.pdf", b"", "empty_file"),
    ("x.exe", b"MZ\x00", "unsupported_type"), ("noext", b"hello", "unsupported_type"),
])
def test_upload_errors_are_422_with_codes(client, name, data, code):
    r = _upload(client, name, data)
    assert r.status_code == 422, r.text
    j = r.json()
    assert j["code"] == code and isinstance(j["detail"], str) and j["detail"]
    assert client.get("/api/v1/documents").json()["total"] == 0


def test_upload_pdf_docx_and_html(client):
    for name, data in (("c.pdf", S.make_two_column_pdf()), ("r.docx", S.make_docx_resume()),
                       ("t.docx", S.make_table_docx()),
                       ("r.html", b"<h1>Jane</h1><h2>Skills</h2><p>Languages: Go, SQL</p>")):
        r = _upload(client, name, data)
        assert r.status_code == 201, (name, r.text)
        assert r.json()["parse_run"]["status"] == "succeeded", name


def test_profile_put_get_and_item_crud(client):
    r = client.put("/api/v1/profiles/current", json={"full_name": "Pat Lee", "links": {
        "github": "https://github.com/pat"}, "preferences": {"work_mode": "remote"}})
    assert r.status_code == 200 and r.json()["full_name"] == "Pat Lee"
    v = r.json()["version"]
    for path, body in [("experiences", {"company": "X", "title": "Dev", "start_date": "2020"}),
                       ("education", {"institution": "MIT", "degree": "BSc"}),
                       ("skills", {"name": "Go"}), ("projects", {"name": "P"}),
                       ("publications", {"title": "T", "year": "2020"}),
                       ("certifications", {"name": "C"})]:
        c = client.post(f"/api/v1/{path}", json=body)
        assert c.status_code == 201, (path, c.text)
        item = c.json()
        assert item["status"] == "confirmed" and item["fact_id"]
        assert client.get(f"/api/v1/{path}/{item['id']}").status_code == 200
        u = client.patch(f"/api/v1/{path}/{item['id']}", json={
            k: (v2 + "2" if isinstance(v2, str) and k not in ("start_date", "year") else v2)
            for k, v2 in body.items()})
        assert u.status_code == 200
        assert client.get(f"/api/v1/{path}").json()["total"] == 1
        assert client.delete(f"/api/v1/{path}/{item['id']}").status_code == 204
        assert client.get(f"/api/v1/{path}").json()["total"] == 0
        assert client.get(f"/api/v1/{path}/{item['id']}").status_code == 404
    assert client.get("/api/v1/profiles/current").json()["version"] > v
    assert client.post("/api/v1/experiences", json={"title": "no company"}).status_code == 422


def test_profile_export_import(client):
    client.put("/api/v1/profiles/current", json={"full_name": "Pat Lee"})
    client.post("/api/v1/skills", json={"name": "Go"})
    exp = client.get("/api/v1/profiles/current/export")
    assert exp.status_code == 200 and exp.json()["facts"]
    r = client.post("/api/v1/profiles/import?mode=replace", json=exp.json())
    assert r.status_code == 200 and r.json()["imported"] >= 1
    assert client.get("/api/v1/skills").json()["total"] == 1
    assert client.post("/api/v1/profiles/import", json={"bad": 1}).status_code == 422


@pytest.mark.skipif(compiler.xelatex_path() is None, reason="xelatex missing")
def test_resume_api_flow(client, db):
    from careerpilot.db.models import Job
    p, _ = S.seed_confirmed_profile(db)
    db.commit()
    job = Job(workspace_id="default", dedupe_key="j1", title="Backend Engineer",
              company_name="Initrode", description="Python Kafka Kubernetes payments AWS",
              canonical_url="https://x.example/1")
    db.add(job)
    db.commit()
    assert client.get("/api/v1/resume-templates").json()["total"] >= 2
    g = client.post("/api/v1/resumes/generate", json={"job_id": job.id, "label": "For Initrode"})
    assert g.status_code == 201, g.text
    r = g.json()
    assert r["pdf_available"] and r["version_no"] == 1 and r["claims"]
    assert r["validation_report"]["pdf"]["ok"]
    assert "tailoring" in r["validation_report"]
    assert all({"id", "text", "evidence_ids", "needs_confirmation"} <= set(c)
               for c in r["claims"])
    assert "FakeCo" not in r["latex_source"]
    rid = r["id"]
    assert client.get(f"/api/v1/resumes?job_id={job.id}").json()["total"] == 1
    assert client.get(f"/api/v1/resumes/{rid}/pdf").content[:4] == b"%PDF"
    assert "documentclass" in client.get(f"/api/v1/resumes/{rid}/tex").text
    assert client.get(f"/api/v1/resumes/{rid}").json()["id"] == rid
    # edit -> new version with flagged claim, unsafe rejected
    bad = client.put(f"/api/v1/resumes/{rid}/source", json={
        "latex_source": r["latex_source"].replace(r"\begin{document}",
                                                  r"\begin{document}\input{/etc/passwd}")})
    assert bad.status_code == 422 and bad.json()["code"] == "unsafe_latex"
    src = r["latex_source"].replace(r"\end{cpitems}", r"\item Won a Nobel prize." + "\n"
                                    + r"\end{cpitems}", 1)
    e = client.put(f"/api/v1/resumes/{rid}/source", json={"latex_source": src})
    assert e.status_code == 201
    ev = e.json()
    assert ev["version_no"] == 2
    flagged = [c for c in ev["claims"] if c["needs_confirmation"]]
    assert len(flagged) == 1 and "Nobel" in flagged[0]["text"] and flagged[0]["evidence_ids"] == []
    cc = client.post(f"/api/v1/resumes/{ev['id']}/claims/{flagged[0]['id']}/confirm")
    assert cc.status_code == 200 and cc.json()["needs_confirmation"] is False
    comp = client.post(f"/api/v1/resumes/{ev['id']}/compile")
    assert comp.json()["pdf_available"]
    d = client.get(f"/api/v1/resumes/{ev['id']}/diff?against=original").json()
    assert any(h["op"] == "add" and "Nobel" in h["text"] for h in d["hunks"])
    rs = client.post(f"/api/v1/resumes/{rid}/restore")
    assert rs.status_code == 201 and rs.json()["version_no"] == 3
    assert "Nobel" not in rs.json()["latex_source"]
    # cover letter
    cl = client.post("/api/v1/cover-letters/generate", json={"job_id": job.id})
    assert cl.status_code == 200 and cl.json()["claims"] and "Initrode" in cl.json()["text"]
    assert client.post("/api/v1/cover-letters/generate", json={"job_id": "zz"}).status_code == 404
    assert client.get("/api/v1/resumes/nope").status_code == 404


def test_generate_without_confirmed_facts_is_422(client):
    r = client.post("/api/v1/resumes/generate", json={})
    assert r.status_code == 422 and r.json()["code"] == "no_confirmed_facts"
