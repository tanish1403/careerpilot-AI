from datetime import datetime, timedelta, timezone

import pytest

from careerpilot.db.models import (Application, CandidateProfile, Job, JobRequirement, ScheduledTask, Skill,
                                   StudyTask, TaskRun)
from careerpilot.interviews import service as iv
from careerpilot.learning import service as ln
from careerpilot.scheduler import service as sch
from careerpilot.scheduler import tasks as tk
from careerpilot.research import service as rs

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


def mkjob(db, title, skills, saved=True):
    j = Job(dedupe_key=title, title=title, company_name="Acme", canonical_url="https://x/" + title, saved=saved)
    db.add(j)
    db.flush()
    for s in skills:
        db.add(JobRequirement(job_id=j.id, text=s, kind="skill", mandatory=True, normalized=s))
    db.flush()
    return j


def test_sm2_progression_and_lapse():
    e, i, r = ln.sm2_next(2.5, 0, 0, 5)
    assert (i, r) == (1, 1) and e > 2.5
    e, i, r = ln.sm2_next(e, i, r, 4)
    assert (i, r) == (6, 2)
    e2, i2, r2 = ln.sm2_next(e, i, r, 4)
    assert i2 == round(6 * e) and r2 == 3
    e3, i3, r3 = ln.sm2_next(e2, i2, r2, 1)
    assert (i3, r3) == (1, 0)
    assert ln.sm2_next(1.3, 1, 1, 0)[0] == 1.3   # floor
    with pytest.raises(ValueError):
        ln.sm2_next(2.5, 0, 0, 6)


def test_plan_motivated_by_confirmed_gaps_only(db):
    p = CandidateProfile(full_name="T")
    db.add(p)
    db.flush()
    db.add(Skill(profile_id=p.id, name="Python", status="confirmed"))
    db.add(Skill(profile_id=p.id, name="Kubernetes", status="proposed"))   # unconfirmed is still a gap
    mkjob(db, "Platform Eng", ["Python", "Kubernetes", "Terraform"])
    mkjob(db, "SRE", ["Terraform"])
    mkjob(db, "Unsaved", ["Rust"], saved=False)
    db.flush()
    gaps = {g["skill"]: g for g in ln.skill_gaps(db)}
    assert "python" not in gaps and "rust" not in gaps
    assert gaps["terraform"]["count"] == 2 and gaps["kubernetes"]["count"] == 1
    plan = ln.generate_plan(db, ["dsa"], 7.0, now=NOW)
    assert {g["skill"] for g in plan.motivation["skill_gaps"]} == {"terraform", "kubernetes"}
    tasks = db.query(StudyTask).filter(StudyTask.plan_id == plan.id).all()
    gap_tasks = [t for t in tasks if "Skill gap" in (t.reason or "")]
    assert len(gap_tasks) == 2 and all("saved job" in t.reason for t in gap_tasks)
    assert all(t.due_at for t in tasks)
    md = ln.export_markdown(db, plan)
    assert "terraform" in md and "- [ ]" in md and md.startswith("# ")
    with pytest.raises(ValueError):
        ln.generate_plan(db, ["nope"])


def test_replan_and_review_scheduling(db):
    plan = ln.generate_plan(db, ["dsa"], 5.0, now=NOW - timedelta(days=30))
    r = ln.replan(db, plan, 10.0, now=NOW)
    assert r["overdue_before"] > 0
    t = db.query(StudyTask).filter(StudyTask.plan_id == plan.id).first()
    assert t.due_at.replace(tzinfo=timezone.utc) > NOW
    ln.record_review(db, t, 5, NOW)
    assert t.revise_at == NOW + timedelta(days=1)
    assert t in ln.due_revisions(db, NOW + timedelta(days=2))
    assert ln.progress(db)["dsa"]


def test_resources_seed_not_claimed_accessed(db):
    seeds = [r for r in ln.resources(db) if r["origin"] == "seed"]
    assert seeds and all(r["accessed_on"] is None and r["url"].startswith("https://") for r in seeds)


def test_feedback_separates_factual_from_communication(db):
    s = iv.create_session(db, "technical", None, "Backend")
    # factually strong but tiny answer, then factually empty but long fluent answer
    iv.answer(db, s, "Index gives faster lookup but slows write and uses storage space.")
    iv.answer(db, s, "Well " + "this is a long and clear explanation about many unrelated things. " * 6)
    fb = iv.build_feedback(db, s)
    pq = fb["factual_correctness"]["per_question"]
    assert pq[0]["score"] == 1.0 and pq[1]["score"] == 0.0
    assert "score" not in fb["communication"] or fb["communication"]["overall"] is not None
    assert set(fb) == {"factual_correctness", "communication", "revision_tasks"}
    assert fb["revision_tasks"] and fb["revision_tasks"][0]["concepts_missing"]
    assert "word_count" not in str(fb["factual_correctness"]["per_question"][0])
    assert all(q["label"] == "practice question" for q in iv.questions_for(db, s))


def test_unassessable_question_not_scored(db):
    s = iv.create_session(db, "behavioral", None, None)
    iv.answer(db, s, "When I joined, the situation was a goal to cut latency; I decided and built a cache; result improved.")
    f = iv.build_feedback(db, s)["factual_correctness"]
    assert f["overall"] is None and f["per_question"][0]["assessed"] is False


def test_no_unsourced_claims():
    with pytest.raises(ValueError):
        rs.make_claim("Acme is great", "", NOW)


def test_registry_has_no_submit_kind():
    assert sch.kinds() == ["daily_digest", "follow_up", "job_scan", "study_schedule", "weekly_report"]
    with pytest.raises(AssertionError):
        tk.assert_no_submit_kind(["job_scan", "submit_application"])
    with pytest.raises(ValueError):
        sch.validate_task("submit_application", "0 9 * * *", "UTC")


def test_cron_and_timezone_validation():
    for bad in ("nope", "61 * * * *", "* * * *"):
        with pytest.raises(ValueError):
            sch.make_trigger(bad, "UTC")
    with pytest.raises(ValueError):
        sch.make_trigger("0 9 * * *", "Mars/Base")


def test_dst_fire_times_keep_local_wall_clock():
    s, e = datetime(2026, 3, 6, tzinfo=timezone.utc), datetime(2026, 3, 11, tzinfo=timezone.utc)
    ts = sch.fire_times("0 9 * * *", "America/New_York", s, e)
    assert [t.hour for t in ts] == [9] * len(ts)
    utc_hours = {t.strftime("%m-%d"): t.astimezone(timezone.utc).hour for t in ts}
    assert utc_hours["03-07"] == 14 and utc_hours["03-09"] == 13   # DST began 03-08
    assert sch.period_key(ts[0]) != sch.period_key(ts[1])


def mktask(db, kind="daily_digest", cron="0 9 * * *", tz="UTC", created=None, **cfg):
    t = ScheduledTask(name=kind, kind=kind, cron=cron, timezone=tz, config=cfg)
    if created:
        t.created_at = created
    db.add(t)
    db.flush()
    return t


def test_idempotent_rerun(db):
    t = mktask(db)
    r1 = sch.execute(db, t, "k1", now=NOW)
    r2 = sch.execute(db, t, "k1", now=NOW + timedelta(hours=1))
    assert r1.id == r2.id and r1.status == "succeeded"
    assert db.query(TaskRun).filter(TaskRun.task_id == t.id).count() == 1


def test_missed_run_recovery_bounded(db):
    t = mktask(db, created=NOW - timedelta(days=10))
    runs = sch.catch_up(db, NOW)
    assert len(runs) == 1                       # default bound
    assert sch.catch_up(db, NOW) == []
    assert db.query(TaskRun).count() == 1
    t2 = mktask(db, "follow_up", created=NOW - timedelta(days=10), catchup_max=5)
    sch.catch_up(db, NOW)
    # 48h window: at most 3 fires (09:00 on 9th, 10th... bounded by window), never 10 days
    assert 1 <= db.query(TaskRun).filter(TaskRun.task_id == t2.id).count() <= 3


def test_failure_visible_and_retry(db, monkeypatch):
    t = mktask(db, "follow_up")
    calls = {"n": 0}

    def boom(db_, task, now):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("api_key=sk-secret123456789 failed")
        return {"ok": True}
    monkeypatch.setitem(tk.HANDLERS, "follow_up", boom)
    r = sch.execute(db, t, "p1", now=NOW)
    assert r.status == "failed" and "sk-secret123456789" not in r.error
    assert sch.execute(db, t, "p1", now=NOW).status == "failed" and calls["n"] == 1   # no silent rerun
    r = sch.execute(db, t, "p1", now=NOW, retry=True)
    assert r.status == "succeeded" and r.result["attempts"] == 2
    from careerpilot.db.models import Notification
    assert db.query(Notification).filter(Notification.kind == "scheduler_failure").count() == 1


def test_digest_content(db):
    from careerpilot.db.models import MatchResult, Notification, Setting
    j = mkjob(db, "Great Job", ["python"])
    p = CandidateProfile(full_name="T")
    db.add(p)
    db.flush()
    db.add(MatchResult(profile_id=p.id, job_id=j.id, profile_version=1, job_version=1, config_version="c",
                       eligibility="satisfied", fit_score=0.9, priority_score=0.8))
    plan = ln.generate_plan(db, ["dsa"], 70.0, now=NOW)
    db.add(Application(job_id=j.id, state="Shortlisted", follow_up_at=NOW - timedelta(hours=1)))
    db.flush()
    r = sch.execute(db, mktask(db), "d1", now=NOW)
    assert r.status == "succeeded"
    d = db.get(Setting, "digest.latest").value
    assert d["top_matches"][0]["title"] == "Great Job" and d["new_jobs"]["count"] >= 1
    assert len(d["follow_ups_due"]) == 1 and d["study_due"]
    assert db.query(Notification).filter(Notification.kind == "digest").count() == 1


def test_weekly_report_funnel(db):
    j = mkjob(db, "J", [])
    db.add(Application(job_id=j.id, state="Shortlisted"))
    db.flush()
    r = tk.weekly_report(db, datetime.now(timezone.utc))
    assert r["funnel"] == {"Shortlisted": 1} and r["activity"]["jobs_discovered"] == 1


def test_job_scan_without_profile_or_sources(db):
    r = sch.execute(db, mktask(db, "job_scan"), "s1", now=NOW)
    assert r.status == "succeeded" and r.result["sources_run"] == 0
