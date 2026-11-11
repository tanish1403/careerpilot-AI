import sys
from datetime import timedelta
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parents[1] / "fixtures"))
from c_support import Router, fixture_json, json_resp, sleeps, use_router  # noqa: E402,F401

from careerpilot.db.base import utcnow  # noqa: E402
from careerpilot.db.models import (IngestionLog, Job, JobRequirement, JobSource,  # noqa: E402
                                   JobSourceRecord)
from careerpilot.job_connectors import service  # noqa: E402


def add_source(db, kind, config, name=None, **kw):
    s = JobSource(kind=kind, name=name or kind, config=config, **kw)
    db.add(s)
    db.commit()
    return s


def gh_router(data=None, status=200):
    data = data or fixture_json("greenhouse_acme.json")
    return Router().add("greenhouse.io/v1/boards/acme", json_resp(data) if status == 200 else httpx.Response(status))


def test_run_source_persists_jobs_requirements_provenance_and_log(db, use_router):
    use_router(gh_router())
    src = add_source(db, "greenhouse", {"board_token": "acme", "company_name": "Acme"})
    log = service.run_source(db, src.id)
    assert (log.status, log.fetched, log.created, log.closed) == ("success", 3, 3, 0)
    jobs = db.query(Job).order_by(Job.title).all()
    assert len(jobs) == 3
    j = next(j for j in jobs if j.title.startswith("Senior"))
    assert j.first_seen_at and j.last_verified_at and j.status == "open" and j.seniority == "senior"
    assert j.company_id is not None and j.canonical_url == "https://boards.greenhouse.io/acme/jobs/4001"
    rec = db.query(JobSourceRecord).filter_by(job_id=j.id).one()
    assert rec.source_id == src.id and rec.external_id == "4001" and rec.collection_method == "public_api"
    reqs = db.query(JobRequirement).filter_by(job_id=j.id).all()
    norm = {(r.kind, r.normalized): r.mandatory for r in reqs}
    assert norm[("skill", "python")] is True and norm[("skill", "kubernetes")] is True
    assert norm[("skill", "kafka")] is False and norm[("education", "degree:bachelor")] is True
    assert db.get(JobSource, src.id).last_status == "success"
    assert db.query(IngestionLog).count() == 1


def test_rerun_is_idempotent_and_updates_last_verified(db, use_router):
    use_router(gh_router())
    src = add_source(db, "greenhouse", {"board_token": "acme"})
    service.run_source(db, src.id)
    before = {j.id: (j.first_seen_at, j.last_verified_at, j.version) for j in db.query(Job).all()}
    later = utcnow() + timedelta(hours=5)
    stats = service.ingest_result(db, src, service.run_coro_sync(
        service.build_connector("greenhouse").fetch({"board_token": "acme"})), now=later)
    db.commit()
    assert (stats.created, stats.unchanged) == (0, 3) and db.query(Job).count() == 3
    for j in db.query(Job).all():
        assert j.first_seen_at == before[j.id][0] and j.last_verified_at.replace(tzinfo=None) > before[j.id][1].replace(tzinfo=None)
        assert j.version == before[j.id][2]            # unchanged content does not bump version


def test_dedupe_across_sources_keeps_both_provenance_rows(db, use_router):
    lever = [{"id": "lv9", "text": "Sr. Backend Engineer", "categories": {"location": "Remote (US)"},
              "hostedUrl": "https://jobs.lever.co/acme/lv9?lever-source=x", "applyUrl": "https://jobs.lever.co/acme/lv9/apply",
              "descriptionPlain": "Payments infra. Requirements:\n- Python"}]
    r = gh_router().add("api.lever.co/v0/postings/acme", json_resp(lever))
    use_router(r)
    a = add_source(db, "greenhouse", {"board_token": "acme", "company_name": "Acme"})
    b = add_source(db, "lever", {"company": "acme", "company_name": "Acme Inc."})
    service.run_source(db, a.id)
    log_b = service.run_source(db, b.id)
    assert log_b.created == 0 and log_b.updated in (0, 1)
    assert db.query(Job).filter(Job.title.like("%Backend%")).count() == 1
    job = db.query(Job).filter(Job.title.like("%Backend%")).one()
    recs = db.query(JobSourceRecord).filter_by(job_id=job.id).all()
    assert {x.source_id for x in recs} == {a.id, b.id} and len(recs) == 2
    assert {x.external_id for x in recs} == {"4001", "lv9"}
    assert job.title == "Senior Backend Engineer"        # primary (first) source owns the content


def test_same_canonical_url_dedupes_even_when_titles_differ(db):
    from careerpilot.job_connectors.interface import ConnectorResult, RawJob

    def raw(kind, ext, title):
        return RawJob(source_kind=kind, external_id=ext, source_url="https://acme.example/j/1?utm_source=a",
                      canonical_url="https://acme.example/j/1", title=title, company="Acme")
    s1, s2 = add_source(db, "greenhouse", {"board_token": "a"}), add_source(db, "lever", {"company": "a"})
    service.ingest_result(db, s1, ConnectorResult(jobs=[raw("greenhouse", "1", "Engineer")]))
    service.ingest_result(db, s2, ConnectorResult(jobs=[raw("lever", "2", "Totally Different Title")]))
    assert db.query(Job).count() == 1 and db.query(JobSourceRecord).count() == 2


def test_similar_but_distinct_roles_are_not_merged(db):
    from careerpilot.job_connectors.interface import ConnectorResult, RawJob
    mk = lambda i, t: RawJob(source_kind="lever", external_id=i, source_url=f"https://a.example/{i}",  # noqa: E731
                             canonical_url=f"https://a.example/{i}", title=t, company="Acme", location="Austin")
    s = add_source(db, "lever", {"company": "a"})
    service.ingest_result(db, s, ConnectorResult(jobs=[mk("1", "Software Engineer II"), mk("2", "Software Engineer III"),
                                                       mk("3", "Frontend Engineer"), mk("4", "Backend Engineer")]))
    assert db.query(Job).count() == 4


def test_missing_jobs_are_closed_not_deleted_then_reopened(db, use_router):
    data = fixture_json("greenhouse_acme.json")
    use_router(gh_router(data))
    src = add_source(db, "greenhouse", {"board_token": "acme"})
    service.run_source(db, src.id)
    dropped = dict(data, jobs=data["jobs"][:2], meta={"total": 2})
    use_router(gh_router(dropped))
    log = service.run_source(db, src.id)
    assert log.closed == 1 and db.query(Job).count() == 3          # marked, never deleted
    closed = db.query(Job).filter_by(status="closed").one()
    assert closed.title == "Data Scientist" and closed.version == 2
    assert db.query(JobSourceRecord).count() == 3
    # reopening when it reappears
    use_router(gh_router(data))
    log = service.run_source(db, src.id)
    assert db.query(Job).filter_by(status="open").count() == 3 and db.get(Job, closed.id).version == 3
    assert (log.closed, log.updated) == (0, 1)


def test_incomplete_result_never_closes_jobs(db, use_router):
    data = fixture_json("greenhouse_acme.json")
    use_router(gh_router(data))
    src = add_source(db, "greenhouse", {"board_token": "acme"})
    service.run_source(db, src.id)
    partial = dict(data, jobs=[data["jobs"][0], {"id": 77, "absolute_url": "https://x/77"}], meta={"total": 2})
    use_router(gh_router(partial))
    log = service.run_source(db, src.id)
    assert log.status == "partial" and log.closed == 0 and db.query(Job).filter_by(status="closed").count() == 0
    # meta.total larger than returned also means incomplete
    use_router(gh_router(dict(data, jobs=data["jobs"][:1], meta={"total": 3})))
    assert service.run_source(db, src.id).closed == 0


def test_job_open_while_any_source_still_lists_it(db):
    from careerpilot.job_connectors.interface import ConnectorResult, RawJob
    mk = lambda kind, ext: RawJob(source_kind=kind, external_id=ext, source_url=f"https://{kind}.example/{ext}",  # noqa: E731
                                  canonical_url=f"https://{kind}.example/{ext}", title="Data Engineer",
                                  company="Acme", location="Remote")
    a, b = add_source(db, "greenhouse", {"board_token": "a"}), add_source(db, "lever", {"company": "a"})
    service.ingest_result(db, a, ConnectorResult(jobs=[mk("gh", "1")]))
    service.ingest_result(db, b, ConnectorResult(jobs=[mk("lv", "2")]))
    assert db.query(Job).count() == 1
    st = service.ingest_result(db, a, ConnectorResult(jobs=[], complete=True))
    assert st.closed == 0 and db.query(Job).one().status == "open"
    st = service.ingest_result(db, b, ConnectorResult(jobs=[], complete=True))
    assert st.closed == 1 and db.query(Job).one().status == "closed"


def test_manual_jobs_are_never_auto_closed(db):
    from careerpilot.job_connectors.interface import ConnectorResult
    j = service.import_text(db, title="Dev", company="Acme", description="Build things in Python.")
    src = add_source(db, "greenhouse", {"board_token": "a"})
    service.ingest_result(db, src, ConnectorResult(jobs=[], complete=True))
    assert db.get(Job, j.id).status == "open"


def test_one_failing_connector_does_not_stop_others(db, use_router):
    r = (Router().add("greenhouse.io/v1/boards/broken", httpx.Response(500))
         .add("api.ashbyhq.com/posting-api/job-board/globex", json_resp(fixture_json("ashby_globex.json")))
         .add("api.lever.co/v0/postings/gone", httpx.Response(404)))
    use_router(r)
    bad = add_source(db, "greenhouse", {"board_token": "broken"}, name="bad")
    gone = add_source(db, "lever", {"company": "gone"}, name="gone")
    good = add_source(db, "ashby", {"job_board_name": "globex"}, name="good")
    off = add_source(db, "ashby", {"job_board_name": "globex"}, name="off", enabled=False)
    logs = {l.source_id: l for l in service.run_all_sources(db)}
    assert logs[bad.id].status == "failed" and "500" in logs[bad.id].error
    assert logs[gone.id].status == "failed" and "not found" in logs[gone.id].error
    assert logs[good.id].status == "success" and logs[good.id].created == 2
    assert off.id not in logs and db.query(Job).count() == 2
    assert db.get(JobSource, bad.id).last_status == "failed" and db.get(JobSource, bad.id).last_error
    assert db.query(IngestionLog).count() == 3


def test_run_source_survives_unexpected_connector_exception(db):
    class Boom:
        async def fetch(self, cfg):
            raise RuntimeError("kaput")
    src = add_source(db, "greenhouse", {"board_token": "a"})
    log = service.run_source(db, src.id, connector=Boom())
    assert log.status == "failed" and "kaput" in log.error


def test_jobspy_source_run_fails_clearly_when_disabled(db):
    src = add_source(db, "jobspy", {})
    log = service.run_source(db, src.id)
    assert log.status == "failed" and "licence" in log.error


def test_import_text_and_description_cleaning(db):
    j = service.import_text(db, title="Senior Python Developer", company="Acme",
                            description="<p>Requirements</p><ul><li>5 years of Python</li></ul>", url="https://x.example/p?utm_source=a")
    assert "<" not in j.description and j.canonical_url == "https://x.example/p" and j.seniority == "senior"
    again = service.import_text(db, title="Senior Python Developer", company="Acme",
                                description="<p>Requirements</p><ul><li>5 years of Python</li></ul>", url="https://x.example/p")
    assert again.id == j.id and db.query(Job).count() == 1


def test_verify_job_marks_closed_on_404_and_respects_robots(db, use_router):
    j = service.import_text(db, title="Dev", company="Acme", description="Python dev role.", url="https://acme.example/jobs/1")
    use_router(Router().add("/robots.txt", httpx.Response(404)))        # job page -> 404
    out = service.verify_job(db, j.id)
    assert out["status"] == "closed" and db.get(Job, j.id).status == "closed"
    use_router(Router().add("/robots.txt", httpx.Response(404)).add("/jobs/1", httpx.Response(200, text="<p>ok</p>")))
    assert service.verify_job(db, j.id)["status"] == "open" and db.get(Job, j.id).status == "open"
    use_router(Router().add("/robots.txt", httpx.Response(200, text="User-agent: *\nDisallow: /")))
    assert service.verify_job(db, j.id)["status"] == "unverifiable"
