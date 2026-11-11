"""Matching evaluation / regression dataset (hand-labelled).

Two synthetic candidate profiles x five jobs each = 10 labelled pairs. The labels are the expected
rank order (best first) written BEFORE looking at engine output, plus the expected eligibility
state per pair. Changing weights/heuristics such that a rank flips must be a deliberate decision:
update the labels in the same change. Synthetic data only - no real personal information."""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "fixtures"))
from c_support import make_profile  # noqa: E402

from careerpilot.job_connectors import service as ingest  # noqa: E402
from careerpilot.matching import service as ms  # noqa: E402

AS_OF = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)


def req(*lines):
    return "Requirements\n" + "\n".join(f"- {x}" for x in lines)


PROFILE_BACKEND = dict(
    skills=["Python", "PostgreSQL", "Docker", "AWS", "REST APIs"],
    experiences=[("Backend Engineer", "Foo Payments", "2016-03", "2024-09",
                  ["Built payments APIs in Python", "Operated PostgreSQL on AWS"], True)],
    education=[("BSc", "Computer Science", "State University", True)],
    projects=[("Ledger service", "payments ledger in python", ["Python", "PostgreSQL"], True)],
    prefs={"roles": ["backend engineer"], "work_modes": ["remote"]}, location="Austin, TX")

JOBS_BACKEND = [   # (label, title, location, description, expected_eligibility)
    ("best", "Senior Backend Engineer", "Remote - US",
     "Fintech payments platform.\n" + req("5+ years of experience with Python", "PostgreSQL and AWS experience",
                                         "Bachelor's degree in Computer Science"), "satisfied"),
    ("good", "Backend Engineer", "Austin, TX (Hybrid)",
     "Backend services.\n" + req("3+ years of Python", "Docker", "REST APIs"), "satisfied"),
    ("mixed", "Full Stack Engineer", "Remote",
     "Product team.\n" + req("3+ years of software engineering", "React and TypeScript", "Node.js") + "\nNice to have\n- Python", "not_satisfied"),
    ("weak", "Frontend Engineer", "Remote",
     "Web UI.\n" + req("React", "Vue", "CSS", "3+ years of frontend"), "not_satisfied"),
    ("worst", "Machine Learning Researcher", "Boston, MA",
     "Research lab.\n" + req("PhD in Computer Science", "PyTorch and TensorFlow", "8+ years of experience",
                             "Deep learning publications"), "not_satisfied"),
]

PROFILE_DATA = dict(
    skills=["Python", "pandas", "scikit-learn", "SQL", "PyTorch"],
    experiences=[("Data Scientist", "Bar Analytics", "2019-02", "2024-08",
                  ["Churn models with scikit-learn", "SQL pipelines for retail analytics"], True)],
    education=[("MSc", "Statistics", "City University", True)],
    projects=[("Forecasting", "demand forecasting with pandas", ["Python", "pandas", "scikit-learn"], True)],
    prefs={"roles": ["data scientist"], "work_modes": ["hybrid"], "locations": ["London"]}, location="London, UK")

JOBS_DATA = [
    ("best", "Senior Data Scientist", "London (Hybrid)",
     "Retail analytics.\n" + req("4+ years of experience", "pandas and scikit-learn", "SQL", "Master's degree in a quantitative field"),
     "satisfied"),
    # Judgement call recorded in the labels: for a London-based data scientist who wants hybrid, the in-city
    # Data Analyst role (role family + location match, SQL evidenced) outranks a remote ML-engineering role
    # that needs Docker/Kubernetes the candidate cannot evidence, even though PyTorch matches.
    ("good", "Data Analyst", "London",
     "BI team.\n" + req("SQL", "Tableau", "Excel"), "not_satisfied"),
    ("mixed", "Machine Learning Engineer", "Remote",
     "ML platform.\n" + req("PyTorch", "Python", "Docker and Kubernetes"), "not_satisfied"),
    ("weak", "Backend Engineer", "Berlin",
     "Services.\n" + req("Python", "Django", "PostgreSQL", "Redis"), "not_satisfied"),
    ("worst", "iOS Developer", "Madrid",
     "Mobile apps.\n" + req("Swift", "Objective-C", "iOS SDK experience", "5+ years of mobile"), "not_satisfied"),
]


def run_dataset(db, profile, jobs):
    make_profile(db, **profile)
    ids = {}
    for label, title, loc, desc, _ in jobs:
        j = ingest.import_text(db, title=title, company="Eval Co", description=desc)
        j.location = loc
        j.work_mode = "remote" if "remote" in loc.lower() else "hybrid" if "hybrid" in loc.lower() else "unknown"
        j.version += 1
        db.commit()
        ids[label] = j.id
    ms.score_all(db, as_of=AS_OF)
    return {label: ms.latest_match(db, jid) for label, jid in ids.items()}


@pytest.mark.parametrize("profile,jobs", [(PROFILE_BACKEND, JOBS_BACKEND), (PROFILE_DATA, JOBS_DATA)],
                         ids=["backend_profile", "data_profile"])
def test_labelled_rank_order_and_eligibility(db, profile, jobs):
    res = run_dataset(db, profile, jobs)
    order = [label for label, *_ in jobs]                       # hand-labelled best -> worst
    fit = [res[l].fit_score for l in order]
    prio = [res[l].priority_score for l in order]
    assert fit == sorted(fit, reverse=True) and len(set(fit)) == len(fit), f"fit order broke: {dict(zip(order, fit))}"
    assert prio == sorted(prio, reverse=True) and len(set(prio)) == len(prio), f"priority order broke: {dict(zip(order, prio))}"
    for label, _, _, _, expected in jobs:
        assert res[label].eligibility == expected, (label, res[label].eligibility)


def test_unconfirmed_evidence_lowers_the_score(db):
    """Same profile, but skills are only 'proposed': fit must drop and eligibility must not be satisfied."""
    confirmed = run_dataset(db, PROFILE_BACKEND, JOBS_BACKEND[:1])["best"]
    from careerpilot.db import Base
    from careerpilot.db.session import get_engine
    db.close()
    Base.metadata.drop_all(get_engine()); Base.metadata.create_all(get_engine())
    from careerpilot.db.session import SessionLocal
    db2 = SessionLocal()
    prof = dict(PROFILE_BACKEND, skills=[], unconfirmed_skills=PROFILE_BACKEND["skills"],
                experiences=[(t, c, a, b, bl, False) for t, c, a, b, bl, _ in PROFILE_BACKEND["experiences"]],
                education=[(a, b, c, False) for a, b, c, _ in PROFILE_BACKEND["education"]],
                projects=[(a, b, c, False) for a, b, c, _ in PROFILE_BACKEND["projects"]])
    unconfirmed = run_dataset(db2, prof, JOBS_BACKEND[:1])["best"]
    db2.close()
    assert unconfirmed.fit_score < confirmed.fit_score - 20
    assert unconfirmed.eligibility != "satisfied"
    assert all(d["state"] != "satisfied" for d in unconfirmed.eligibility_details)
