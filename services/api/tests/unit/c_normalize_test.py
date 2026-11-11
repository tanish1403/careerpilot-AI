import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "fixtures"))

from careerpilot.job_connectors import normalize as n  # noqa: E402
from careerpilot.job_connectors.requirements import extract_requirements  # noqa: E402
from careerpilot.matching.taxonomy import canonical_skill, find_skills  # noqa: E402


def test_canonical_url_strips_tracking_keeps_identity():
    a = n.canonical_url("HTTPS://www.Example.com/jobs/1/?utm_source=x&gh_src=y&gh_jid=77&ref=foo#frag")
    assert a == "https://example.com/jobs/1?gh_jid=77"
    assert n.canonical_url("https://example.com/jobs/1?gh_jid=77&utm_campaign=z") == a


def test_title_similarity_distinguishes_levels():
    assert n.title_similarity("Sr. Backend Engineer", "Senior Back-end Engineer") >= 0.85
    assert n.title_similarity("Software Engineer II", "Software Engineer III") == 0.0
    assert n.title_similarity("Senior Engineer", "Junior Engineer") == 0.0
    assert not n.probable_duplicate("Frontend Engineer", "NYC", "Backend Engineer", "NYC")
    assert not n.probable_duplicate("Backend Engineer", "New York", "Backend Engineer", "San Francisco")
    assert n.probable_duplicate("Backend Engineer", "Remote - US", "Backend Engineer", "Remote (US)")


def test_company_normalization():
    assert n.norm_company("Acme, Inc.") == n.norm_company("ACME") == "acme"


def test_html_to_text_handles_escaped_html_and_bullets():
    t = n.html_to_text("&lt;p&gt;Hello&lt;/p&gt;&lt;ul&gt;&lt;li&gt;A&lt;/li&gt;&lt;li&gt;B&lt;/li&gt;&lt;/ul&gt;&lt;script&gt;x&lt;/script&gt;")
    assert [x for x in t.splitlines() if x] == ["Hello", "- A", "- B"] and "\n\n- B" not in t
    assert "script" not in n.html_to_text("<p>ok</p><script>alert(1)</script>")


def test_infer_and_salary():
    assert n.infer_seniority("Sr. Data Engineer") == "senior"
    assert n.infer_work_mode("Remote - US") == "remote" and n.infer_work_mode("Hybrid, London") == "hybrid"
    assert n.parse_salary_range("$150,000 - $190,000 per year") == (150000, 190000)
    assert n.parse_salary_range("$50 - $60 per hour")[0] == 50 * 2080
    assert n.parse_salary_range("$120k-$160k") == (120000, 160000)
    assert n.parse_salary_range("competitive") is None


def test_taxonomy_synonyms():
    assert canonical_skill("JS") == "javascript" and canonical_skill("K8s") == "kubernetes"
    assert find_skills("We use JS, k8s and Postgres; NoSQL; go to market") == ["javascript", "kubernetes", "postgresql"]
    assert canonical_skill("Obscure Thing") == "obscure thing"


DESC = """About the role
We build things with Rust club.
Requirements
- 5+ years of experience with Python and Postgres
- Bachelor's degree in CS or equivalent
- Must be authorized to work in the US
Nice to have
- Experience with Kubernetes
Benefits
- Free lunch"""


def test_requirement_extraction_mandatory_vs_preferred():
    items = extract_requirements(DESC)
    by = {(i.kind, i.normalized): i for i in items}
    assert by[("skill", "python")].mandatory and by[("skill", "postgresql")].mandatory
    assert by[("experience", "experience_years:5")].mandatory
    assert by[("education", "degree:bachelor")].mandatory
    assert by[("authorization", "authorization:work_authorization")].mandatory
    assert by[("skill", "kubernetes")].mandatory is False
    assert ("skill", "rust") not in by          # benefits/about sections are ignored
