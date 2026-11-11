"""Tool grants. Agents have NO ambient db/browser/filesystem access: everything goes through a
ToolBroker holding an immutable ToolGrant issued by the Supervisor from policy (never from
retrieved content). Denied access raises PermissionError and is audited."""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.audit import audit
from ..db.models import Document, Job, ProfileFact
from .interface import AgentPermissions


@dataclass(frozen=True)
class ToolSpec:
    name: str
    needs: tuple[str, str | None]            # (permission field, resource) e.g. ("reads","jobs")
    handler: Callable[..., Any]


def permits(perm: AgentPermissions, spec: ToolSpec) -> bool:
    field, res = spec.needs
    if field == "reads":
        return res in perm.reads
    if field == "writes":
        return res in perm.writes
    if field == "network":
        return perm.network
    if field == "browser":
        return perm.browser
    if field == "can_submit":
        return perm.can_submit
    return False


class ToolGrant(BaseModel):
    model_config = {"frozen": True}
    agent: str
    step: str = "main"
    tools: frozenset[str] = frozenset()


def _lazy(module: str, attr: str):
    try:
        fn = getattr(importlib.import_module(f"careerpilot.{module}"), attr, None)
    except ImportError:
        fn = None
    if fn is None:
        raise NotImplementedError(f"{module}.{attr} is not available yet")
    return fn


def _documents_read(db: Session, document_id: str) -> dict:
    doc = db.get(Document, document_id)
    if not doc or doc.deleted_at:
        raise LookupError("document not found")
    return {"document_id": doc.id, "filename": doc.filename,
            "text": _lazy("documents", "extract_text")(doc)}


def _profile_read_facts(db: Session, profile_id: str | None = None) -> list[dict]:
    q = db.query(ProfileFact).filter(ProfileFact.status == "confirmed",
                                     ProfileFact.deleted_at.is_(None))
    if profile_id:
        q = q.filter(ProfileFact.profile_id == profile_id)
    return [{"id": f.id, "category": f.category, "key": f.key, "value": f.value} for f in q.all()]


def _profile_propose_facts(db: Session, profile_id: str, facts: list[dict],
                           document_id: str | None = None) -> list[str]:
    ids = []
    for f in facts:   # always 'proposed'; verified facts are never touched here
        row = ProfileFact(profile_id=profile_id, category=f.get("category", "other"),
                          key=str(f.get("key", ""))[:200], value=f.get("value") or {},
                          status="proposed", confidence=f.get("confidence"),
                          source_document_id=document_id, source_location=f.get("evidence_location"))
        db.add(row)
        db.flush()
        ids.append(row.id)
    return ids


def _jobs_read(db: Session, job_id: str) -> dict:
    j = db.get(Job, job_id)
    if not j or j.deleted_at:
        raise LookupError("job not found")
    return {"id": j.id, "title": j.title, "company_name": j.company_name, "location": j.location,
            "description": j.description, "requirements": j.requirements}


def _forbidden(db: Session, **_: Any):
    raise PermissionError("submission is never available as an agent tool")


TOOLS: dict[str, ToolSpec] = {s.name: s for s in [
    ToolSpec("documents.read", ("reads", "documents"), _documents_read),
    ToolSpec("profile.read_facts", ("reads", "profile_facts"), _profile_read_facts),
    ToolSpec("profile.propose_facts", ("writes", "profile_facts:proposed"), _profile_propose_facts),
    ToolSpec("jobs.read", ("reads", "jobs"), _jobs_read),
    ToolSpec("matching.score", ("reads", "jobs"),
             lambda db, **kw: _lazy("matching", "score_job")(db, **kw)),
    ToolSpec("resume.generate", ("writes", "resume_versions"),
             lambda db, **kw: _lazy("resume_engine", "generate_resume")(db, **kw)),
    ToolSpec("connectors.fetch", ("network", None),
             lambda db, **kw: _lazy("job_connectors", "fetch_jobs")(db, **kw)),
    ToolSpec("learning.context", ("reads", "learning"),
             lambda db, **kw: _lazy("learning", "learning_context")(db, **kw)),
    ToolSpec("research.fetch", ("network", None),
             lambda db, **kw: _lazy("learning", "fetch_public_page")(db, **kw)),
    ToolSpec("browser.submit", ("can_submit", None), _forbidden),
]}


class ToolBroker:
    """The only handle an agent gets to the outside world."""

    def __init__(self, db: Session, grant: ToolGrant, run_id: str | None = None):
        self._db = db
        self.grant = grant
        self._run_id = run_id

    def has(self, name: str) -> bool:
        return name in self.grant.tools

    def call(self, name: str, **kwargs: Any) -> Any:
        spec = TOOLS.get(name)
        if spec is None or name not in self.grant.tools:
            audit(self._db, "tool.denied", actor=f"agent:{self.grant.agent}", subject_type="run",
                  subject_id=self._run_id, detail={"tool": name, "step": self.grant.step})
            raise PermissionError(f"tool {name!r} not granted to {self.grant.agent} "
                                  f"for step {self.grant.step!r}")
        audit(self._db, "tool.call", actor=f"agent:{self.grant.agent}", subject_type="run",
              subject_id=self._run_id, detail={"tool": name, "arg_keys": sorted(kwargs)})
        return spec.handler(self._db, **kwargs)
