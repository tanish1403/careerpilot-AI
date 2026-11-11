import re

import pytest

import b_support as S
from careerpilot.db.models import ResumeClaim
from careerpilot.documents import profile_service as ps
from careerpilot.resume_engine import cover_letter as cl
from careerpilot.resume_engine import service as svc
from careerpilot.resume_engine.latex import escape_latex, find_forbidden, safe_url
from careerpilot.resume_engine.model import build_model
from careerpilot.resume_engine.render import latex_plain, parse_source_claims, render_body
from careerpilot.resume_engine.tailor import check_integrity, tailor, validate_rewording
from careerpilot.resume_engine import versions as vs

JD = ("We need a backend engineer with strong Python and Kafka experience, Kubernetes, "
      "AWS and Terraform. You will design payments services and reduce latency.")


def test_escape_latex_neutralizes_injection():
    evil = r"\input{/etc/passwd} \write18{rm -rf /} $x$ 50% & #1 _a_ {b} ~ ^ \catcode`\^^M=9"
    out = escape_latex(evil)
    assert "\\input{" not in out.replace(r"\textbackslash{}input", "")
    assert r"\textbackslash{}input\{/etc/passwd\}" in out
    assert r"\textbackslash{}write18\{rm -rf /\}" in out
    for ch in "&%$#_":
        assert re.search(rf"(?<!\\){re.escape(ch)}", out) is None, ch
    assert "\n" not in escape_latex("a\nb\r\nc") and "\x00" not in escape_latex("a\x00b")
    assert latex_plain(out) == " ".join(evil.split())   # round-trips for claim matching


def test_safe_url():
    assert safe_url("javascript:alert(1)") is None
    assert safe_url("file:///etc/passwd") is None
    assert safe_url("https://a.example/x?y=1%202#frag").count(r"\%") == 1
    assert safe_url("linkedin.com/in/jane") == "https://linkedin.com/in/jane"
    assert safe_url("a@b.example") == "mailto:a@b.example"
    assert "{" not in safe_url("https://a.example/{x}")


def test_find_forbidden():
    base = "\\documentclass{article}\n\\usepackage{fontspec}\n\\begin{document}x\\end{document}"
    assert find_forbidden(base) == []
    for evil in (r"\input{/etc/passwd}", r"\immediate\write18{id}", r"\openout3=x",
                 r"\usepackage{shellesc}", r"\catcode`\%=12", r"\csname x\endcsname",
                 r"\def\x{y}", r"\read16 to \x"):
        assert find_forbidden(base.replace("x\\end", evil + "\\end")), evil
    assert find_forbidden("no class here")
    assert find_forbidden(base.replace("fontspec", "evilpkg"))
    # commented-out commands are not code
    assert find_forbidden(base.replace("x\\end", "% \\input{y}\n\\end")) == []


def test_resume_contains_only_confirmed_facts(db):
    p, ids = S.seed_confirmed_profile(db)
    model = build_model(db, p)
    body, claims = render_body(model)
    blob = body + " ".join(c.text for c in claims)
    for banned in ("FakeCo", "Fabrication", "999%", "Haskell", "RejectedCo", "Rejected bullet"):
        assert banned not in blob
    assert "Acme Corp" in blob and "Globex" in blob
    ev = {e for c in claims for e in c.evidence_ids}
    confirmed = {f.id for f in ps.confirmed_facts(db, p)}
    assert ev and ev <= confirmed
    assert all(c.evidence_ids and not c.needs_confirmation for c in claims)


def test_unconfirmed_never_appear_even_after_tailoring_and_cover_letter(db):
    p, _ = S.seed_confirmed_profile(db)
    v = svc.generate(db, p, job_description=JD + " FakeCo Haskell", compile_pdf=False)
    full = v.latex_source + " ".join(c.text for c in vs.claims_of(db, v))
    for banned in ("FakeCo", "Fabrication", "Haskell", "RejectedCo"):
        assert banned not in full


def test_no_confirmed_facts_is_refused(db):
    p = ps.get_profile(db)
    ps.create_fact(db, p, "skill", {"name": "Go"})  # proposed only
    with pytest.raises(ps.ProfileError) as e:
        svc.generate(db, p, compile_pdf=False)
    assert e.value.code == "no_confirmed_facts"


def test_tailoring_reorders_but_never_alters_facts(db):
    p, _ = S.seed_confirmed_profile(db)
    master = build_model(db, p)
    tailored, rep = tailor(master, JD, max_bullets=2)
    assert check_integrity(master, tailored) == []
    for te, me in zip(sorted(tailored.experiences, key=lambda e: e.fact_id),
                      sorted(master.experiences, key=lambda e: e.fact_id)):
        assert (te.title, te.org, te.dates, te.location) == (me.title, me.org, me.dates,
                                                              me.location)
        assert {b.text for b in te.bullets} <= {b.text for b in me.bullets}
        assert len(te.bullets) <= 2
    acme = next(e for e in tailored.experiences if e.org == "Acme Corp")
    assert "Python and Kafka" in acme.bullets[0].text      # most JD-relevant first
    assert "offsite" not in " ".join(b.text for b in acme.bullets)
    assert rep["omitted_bullets"] >= 1
    # the master model is untouched
    assert len(next(e for e in master.experiences if e.org == "Acme Corp").bullets) == 4
    # dates/metrics survive into the final source
    v = svc.generate(db, p, job_description=JD, compile_pdf=False)
    assert "Jan 2020" in v.latex_source and "Present" in v.latex_source
    assert "2M requests" in v.latex_source and "35\\%" in v.latex_source
    skills_in = {n for g in tailored.skill_groups for n in g.names}
    assert skills_in == {"Python", "Go", "SQL", "Kubernetes", "Kafka"}
    assert "AWS" in rep["missing_keywords"] or "aws" in rep["missing_keywords"]
    assert "terraform" in rep["missing_keywords"]
    assert "aws" not in v.latex_source.lower() and "terraform" not in v.latex_source.lower()


def test_tailoring_never_adds_skills_from_jd(db):
    p, _ = S.seed_confirmed_profile(db)
    master = build_model(db, p)
    tailored, _ = tailor(master, "Rust Haskell Terraform AWS Scala Java expert needed")
    names = {n.lower() for g in tailored.skill_groups for n in g.names}
    assert not names & {"haskell", "terraform", "aws", "scala", "java", "rust"}
    tailored.skill_groups[0].names.append("Haskell")
    assert any("Haskell" in x for x in check_integrity(master, tailored))


def test_integrity_check_detects_tampering(db):
    p, _ = S.seed_confirmed_profile(db)
    master = build_model(db, p)
    for mutate, needle in [
        (lambda m: setattr(m.experiences[0], "dates", "Jan 2015 \u2013 Present"), "dates"),
        (lambda m: setattr(m.experiences[0], "title", "CTO"), "title"),
        (lambda m: setattr(m.education[0], "title", "PhD, Physics"), "title"),
        (lambda m: m.experiences[0].bullets[0].__setattr__("text", "Saved 90% of costs."),
         "bullet"),
    ]:
        t, _ = tailor(master, JD)
        mutate(t)
        probs = check_integrity(master, t)
        assert probs and any(needle in x for x in probs), (needle, probs)


SRC = "Built a payments service handling 2M requests per day using Python and Kafka."


@pytest.mark.parametrize("bad", [
    "Built a payments service handling 20M requests per day using Python and Kafka.",
    "Built a payments service handling 2M requests per day using Python and Kafka in 2023.",
    "Built a payments service handling 2M requests per day using Python, Kafka and Terraform.",
    "Built a payments service handling 2M requests per day using Python and Kafka at Google.",
    "Built a payments service handling 2 million requests per day using Python and Kafka.",
    "Built a payments service handling 2M requests per day using Python and Kubernetes.",
    "Built a payments service handling 2M requests per day using Python and Kafka, a 50% gain.",
    "",
])
def test_reword_validator_rejects_fabrication(bad):
    ok, why = validate_rewording(bad, SRC, SRC)
    assert not ok, why


def test_reword_validator_accepts_faithful_rewrite():
    ok, why = validate_rewording("Built a payments service that handles 2M requests per day "
                                 "with Python and Kafka.", SRC, SRC)
    assert ok, why


def test_llm_reword_with_fabricated_number_is_dropped(db):
    p, _ = S.seed_confirmed_profile(db)
    master = build_model(db, p)

    def evil(bullet, wrapped_jd):
        assert "<UNTRUSTED_DATA" in wrapped_jd
        return bullet.replace("2M", "20M").replace("35%", "53%")

    t, rep = tailor(master, JD, reword=evil)
    assert rep["rewordings"] == [] or all("20M" not in r["new"] for r in rep["rewordings"])
    assert rep["rejected_rewordings"]
    assert check_integrity(master, t) == []
    texts = " ".join(b.text for e in t.entries() for b in e.bullets)
    assert "20M" not in texts and "53%" not in texts

    def good(bullet, wrapped_jd):
        return bullet.replace("Built", "Designed and built") if "Built a payments" in bullet \
            else None
    t2, rep2 = tailor(master, JD, reword=good)
    assert rep2["rewordings"] and check_integrity(master, t2) == []
    body, claims = render_body(t2)
    flagged = [c for c in claims if c.needs_confirmation]
    assert flagged and "Designed and built" in flagged[0].text   # reworded => visibly flagged


def test_claims_flag_missing_evidence(db):
    p, _ = S.seed_confirmed_profile(db)
    v = svc.generate(db, p, compile_pdf=False)
    src = v.latex_source.replace(
        r"\end{cpitems}",
        r"\item Invented a time machine." + "\n" + r"\end{cpitems}", 1)
    nv = svc.edit_source(db, p, v, src)
    claims = vs.claims_of(db, nv)
    inv = [c for c in claims if "time machine" in c.text]
    assert inv and inv[0].needs_confirmation and inv[0].evidence_ids == []
    # an edit to an existing bullet keeps evidence but demands re-confirmation
    src2 = nv.latex_source.replace("Mentored 4 junior engineers.", "Mentored 40 junior engineers.")
    nv2 = svc.edit_source(db, p, nv, src2)
    ch = [c for c in vs.claims_of(db, nv2) if "Mentored 40" in c.text][0]
    assert ch.needs_confirmation and ch.evidence_ids
    untouched = [c for c in vs.claims_of(db, nv2) if "payments service" in c.text][0]
    assert not untouched.needs_confirmation
    # explicit confirmation clears the flag
    svc.confirm_claim(db, nv2, ch.id)
    assert not db.get(ResumeClaim, ch.id).needs_confirmation


def test_edit_source_rejects_unsafe_latex(db):
    p, _ = S.seed_confirmed_profile(db)
    v = svc.generate(db, p, compile_pdf=False)
    with pytest.raises(ps.ProfileError) as e:
        svc.edit_source(db, p, v, v.latex_source.replace(
            r"\begin{document}", r"\begin{document}\immediate\write18{id}"))
    assert e.value.code == "unsafe_latex"


def test_versioning_restore_and_diff(db):
    p, _ = S.seed_confirmed_profile(db)
    v1 = svc.generate(db, p, compile_pdf=False, label="first")
    v2 = svc.edit_source(db, p, v1, v1.latex_source.replace("Mentored 4", "Mentored 5"))
    v3 = svc.edit_source(db, p, v2, v2.latex_source.replace("Mentored 5", "Mentored 6"))
    assert [v1.version_no, v2.version_no, v3.version_no] == [1, 2, 3]
    assert v3.parent_version_id == v2.id and vs.root_of(db, v3).id == v1.id
    d = vs.diff_sources(v1.latex_source, v3.latex_source,
                        [c.text for c in vs.claims_of(db, v1)],
                        [c.text for c in vs.claims_of(db, v3)])
    ops = {h["op"] for h in d["hunks"]}
    assert {"add", "remove"} <= ops and "Mentored 6" in " ".join(h["text"] for h in d["hunks"]
                                                                 if h["op"] == "add")
    assert d["claims_added"] and "1 line(s) added" in d["summary"]
    r = svc.restore(db, p, v1)
    assert r.version_no == 4 and r.label == "Restored from v1"
    strip = lambda s: re.sub(r"\s*% cp:claim=\w+", "", s)  # noqa: E731
    assert strip(r.latex_source) == strip(v1.latex_source)
    assert "Mentored 6" not in r.latex_source
    # history is untouched
    assert "Mentored 6" in db.get(type(v3), v3.id).latex_source
    ids_v1 = {c.id for c in vs.claims_of(db, v1)}
    assert not ids_v1 & {c.id for c in vs.claims_of(db, r)}
    assert len(vs.claims_of(db, r)) == len(vs.claims_of(db, v1))
    assert not any(cid in r.latex_source for cid in ids_v1)


def test_claim_markers_survive_roundtrip(db):
    p, _ = S.seed_confirmed_profile(db)
    v = svc.generate(db, p, compile_pdf=False)
    parsed = parse_source_claims(v.latex_source)
    claim_ids = {c.id for c in vs.claims_of(db, v)}
    assert {cid for cid, _k, _t in parsed} == claim_ids


def test_cover_letter_evidence_rules(db):
    from careerpilot.db.models import Job
    p, _ = S.seed_confirmed_profile(db)
    job = Job(workspace_id="default", dedupe_key="k1", title="Backend Engineer",
              company_name="Initrode", description=JD, canonical_url="https://x.example/j")
    db.add(job)
    db.flush()
    out = cl.generate_cover_letter(db, p, job)
    assert "Backend Engineer" in out["text"] and "Initrode" in out["text"]
    assert out["claims"] and all(c["evidence_ids"] for c in out["claims"])
    confirmed = {f.id for f in ps.confirmed_facts(db, p)}
    assert {e for c in out["claims"] for e in c["evidence_ids"]} <= confirmed
    for banned in ("FakeCo", "Haskell", "999"):
        assert banned not in out["text"]
    # fabricated LLM rewrite is rejected, faithful one is flagged for confirmation
    out2 = cl.generate_cover_letter(db, p, job, rewrite=lambda t, j: t + " I also led 500 people.")
    assert "500 people" not in out2["text"]
    out3 = cl.generate_cover_letter(db, p, job, rewrite=lambda t, j: t.replace(
        "my work included", "my contributions included"))
    assert out3["needs_confirmation"] or "contributions" not in out3["text"]
