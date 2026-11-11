import json

import httpx
import pytest

from careerpilot.agent_workflows.mock import MockGateway
from careerpilot.agent_workflows.runner import WorkflowRunner, latest_checkpoint
from careerpilot.db.models import (Approval, AuditEvent, Checkpoint, Workflow, WorkflowRun)
from careerpilot.db.session import SessionLocal
from tests.d_support import Sleeps

DEFN = {"version": 1, "steps": [
    {"id": "prep", "type": "agent", "agent": "interview", "input": {"role": "$.inputs.role"}},
    {"id": "review", "type": "approval", "message": "ok to continue?"},
    {"id": "final", "type": "agent", "agent": "study_planner", "input": {},
     "grants": []}]}


def mk_wf(db, defn=DEFN):
    w = Workflow(name="wf", definition=defn)
    db.add(w)
    db.commit()
    return w


async def test_pause_at_approval_and_resume_in_new_runner_instance(db):
    w = mk_wf(db)
    r1 = WorkflowRunner(db, MockGateway(), sleep=Sleeps())
    run = r1.create(w.id, {"role": "Dev"})
    run = await r1.advance(run.id)
    assert run.status == "paused"
    ap = db.query(Approval).filter_by(subject_id=run.id).one()
    assert ap.status == "pending" and ap.kind == "workflow"
    cps = db.query(Checkpoint).filter_by(run_id=run.id).all()
    assert any(c.awaiting_approval for c in cps)
    with pytest.raises(ValueError):          # cannot resume before a decision
        await r1.resume(run.id)
    rid = run.id
    db.close()                               # "restart": new session + new runner
    db2 = SessionLocal()
    r2 = WorkflowRunner(db2, MockGateway(), sleep=Sleeps())
    from careerpilot.agent_workflows.runner import decide_approval
    decide_approval(db2, ap.id, True, "tester")
    db2.commit()
    done = await r2.resume(rid)
    assert done.status == "succeeded" and done.approval_actor == "tester"
    assert set(done.output_refs["outputs"]) == {"prep", "final"}
    # prep ran exactly once (checkpoint resume, not replay)
    assert db2.query(WorkflowRun).filter_by(parent_run_id=rid, agent="interview").count() == 1
    db2.close()


async def test_denied_approval_cancels(db):
    w = mk_wf(db)
    r = WorkflowRunner(db, MockGateway(), sleep=Sleeps())
    run = await r.advance(r.create(w.id, {"role": "Dev"}).id)
    from careerpilot.agent_workflows.runner import decide_approval
    decide_approval(db, db.query(Approval).filter_by(subject_id=run.id).one().id, False, "me")
    db.commit()
    assert (await r.resume(run.id)).status == "cancelled"


async def test_cancel_and_pause_and_idempotency(db):
    w = mk_wf(db)
    r = WorkflowRunner(db, MockGateway(), sleep=Sleeps())
    a = r.create(w.id, {"role": "Dev"}, idempotency_key="k")
    b = r.create(w.id, {"role": "Dev"}, idempotency_key="k")
    assert a.id == b.id
    r.pause(a.id)
    assert (await r.advance(a.id)).status == "paused"     # paused runs do not advance
    run = await r.resume(a.id)
    assert run.status == "paused"                         # now at approval
    r.cancel(a.id)
    db.refresh(run)
    assert run.status == "cancelled"
    assert db.query(Approval).filter_by(subject_id=a.id).one().status == "expired"
    with pytest.raises(ValueError):
        r.cancel(a.id)


class Flaky(MockGateway):
    def __init__(self, fails):
        super().__init__()
        self.fails = fails

    async def generate(self, req, policy):
        if self.fails > 0:
            self.fails -= 1
            raise RuntimeError("transient")
        return await super().generate(req, policy)


async def test_step_retry_counts(db):
    w = mk_wf(db, {"steps": [{"id": "s", "type": "agent", "agent": "interview",
                              "input": {"role": "x"}, "retries": 2}]})
    s = Sleeps()
    r = WorkflowRunner(db, Flaky(2), sleep=s)
    run = await r.advance(r.create(w.id, {}).id)
    assert run.status == "succeeded" and run.retries == 2 and len(s.calls) == 2
    w2 = mk_wf(db, {"steps": [{"id": "s", "type": "agent", "agent": "interview",
                               "input": {"role": "x"}, "retries": 1}]})
    run2 = await WorkflowRunner(db, Flaky(5), sleep=Sleeps()).advance(
        WorkflowRunner(db, None).create(w2.id, {}).id)
    assert run2.status == "failed" and "transient" in run2.error


async def test_supervisor_denial_in_workflow_is_audited_and_fails_run(db):
    w = mk_wf(db, {"steps": [{"id": "s", "type": "agent", "agent": "interview",
                              "input": {"role": "x"}, "grants": ["browser.submit"]}]})
    r = WorkflowRunner(db, MockGateway(), sleep=Sleeps())
    run = await r.advance(r.create(w.id, {}).id)
    assert run.status == "succeeded"       # grant silently clipped to nothing...
    assert db.query(AuditEvent).filter_by(action="tool.grant_clipped").count() == 1


def test_routes_workflow_approval_flow(client, db):
    c = client
    w = c.post("/api/v1/workflows", json={"name": "w", "definition": DEFN})
    assert w.status_code == 201
    bad = c.post("/api/v1/workflows", json={"name": "b", "definition": {"steps": [
        {"id": "x", "type": "agent", "agent": "nope"}]}})
    assert bad.status_code == 422
    from tests.d_support import setting
    setting(db, "agent_mock_mode", True)
    db.commit()
    r = c.post(f"/api/v1/workflows/{w.json()['id']}/run", json={"inputs": {"role": "Dev"}},
               headers={"Idempotency-Key": "abc"})
    assert r.status_code == 202
    rid = r.json()["id"]
    got = c.get(f"/api/v1/workflow-runs/{rid}").json()
    assert got["status"] == "paused" and got["pending_approval"]
    cps = c.get(f"/api/v1/workflow-runs/{rid}/checkpoints").json()["items"]
    assert [x["seq"] for x in cps] == sorted(x["seq"] for x in cps) and cps[-1]["awaiting_approval"]
    assert c.post(f"/api/v1/runs/{rid}/resume").status_code == 409     # still pending
    inbox = c.get("/api/v1/approvals?status=pending").json()
    assert inbox["total"] == 1
    ok = c.post(f"/api/v1/workflow-runs/{rid}/approve", json={"approve": True, "comment": "go"})
    assert ok.status_code == 202
    assert c.get(f"/api/v1/workflow-runs/{rid}").json()["status"] == "succeeded"
    assert c.get("/api/v1/approvals?status=pending").json()["total"] == 0
    # idempotent re-run returns same run
    again = c.post(f"/api/v1/workflows/{w.json()['id']}/run", json={"inputs": {"role": "Dev"}},
                   headers={"Idempotency-Key": "abc"})
    assert again.json()["id"] == rid


def test_routes_pause_cancel_and_decide_endpoint(client, db):
    from tests.d_support import setting
    setting(db, "agent_mock_mode", True)
    db.commit()
    w = client.post("/api/v1/workflows", json={"name": "w", "definition": DEFN}).json()
    rid = client.post(f"/api/v1/workflows/{w['id']}/run", json={"inputs": {"role": "D"}}).json()["id"]
    ap = client.get("/api/v1/approvals?status=pending").json()["items"][0]
    d = client.post(f"/api/v1/approvals/{ap['id']}/decide", json={"grant": True})
    assert d.status_code == 200 and d.json()["status"] == "granted"
    assert client.get(f"/api/v1/workflow-runs/{rid}").json()["status"] == "succeeded"
    assert client.post(f"/api/v1/approvals/{ap['id']}/decide", json={"grant": True}).status_code == 409
    assert client.post(f"/api/v1/runs/{rid}/cancel").status_code == 409     # terminal
    rid2 = client.post(f"/api/v1/workflows/{w['id']}/run", json={"inputs": {"role": "D"}}).json()["id"]
    assert client.post(f"/api/v1/runs/{rid2}/cancel").json()["status"] == "cancelled"


def test_agents_routes_and_run(client, db):
    from tests.d_support import setting
    setting(db, "agent_mock_mode", True)
    db.commit()
    items = client.get("/api/v1/agents").json()["items"]
    assert len(items) == 8
    assert client.put("/api/v1/agents/interview/config",
                      json={"enabled": True, "budget_usd": 1.5}).json()["budget_usd"] == 1.5
    assert client.put("/api/v1/agents/interview/config",
                      json={"primary_model_id": "ghost"}).status_code == 422
    r = client.post("/api/v1/agents/interview/run", json={"input": {"role": "Dev"}})
    assert r.status_code == 202
    run = client.get(f"/api/v1/runs/{r.json()['id']}").json()
    assert run["status"] == "succeeded" and "questions" in run["output_refs"]["output"]
    assert client.post("/api/v1/agents/interview/run", json={"input": {}}).status_code == 422
    client.put("/api/v1/agents/interview/config", json={"enabled": False})
    assert client.post("/api/v1/agents/interview/run", json={"input": {"role": "x"}}).status_code == 409


def test_submit_approval_decide_consistent_with_lane_e(client, db):
    from e_support import make_app, make_profile, make_resume
    app, job = make_app(db, "ReviewRequired")
    p, _ = make_profile(db)
    rv = make_resume(db, p, job)
    db.commit()
    client.post(f"/api/v1/applications/{app.id}/approve-resume", json={"resume_version_id": rv.id})
    for to in ("AutofillInProgress", "UserSubmissionReview"):
        client.post(f"/api/v1/applications/{app.id}/transition", json={"to_state": to})
    ap = client.post(f"/api/v1/applications/{app.id}/request-submit").json()
    assert client.get("/api/v1/approvals?status=pending&kind=submit").json()["total"] == 1
    d = client.post(f"/api/v1/approvals/{ap['id']}/decide", json={"grant": True})
    assert d.status_code == 200 and d.json()["status"] == "granted"
    r = client.post(f"/api/v1/applications/{app.id}/confirm-submitted",
                    json={"approval_id": ap["id"], "confirmation_ref": "C1"})
    assert r.status_code == 200 and r.json()["state"] == "Submitted"
