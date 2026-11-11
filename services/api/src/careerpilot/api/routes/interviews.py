"""Lane F: interviews + practice sessions."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...core.auth import current_user
from ...db.models import Interview, InterviewFeedback, InterviewSession
from ...db.session import get_db
from ...interviews import service as svc

router = APIRouter(tags=["interviews"], dependencies=[Depends(current_user)])


class InterviewIn(BaseModel):
    company: str | None = None
    role: str | None = None
    scheduled_at: datetime | None = None
    format: str | None = None
    notes: str | None = None
    application_id: str | None = None


class SessionIn(BaseModel):
    kind: str
    job_id: str | None = None
    target_role: str | None = Field(default=None, max_length=200)


class AnswerIn(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


class FinishIn(BaseModel):
    use_llm: bool = False


def _iv(i: Interview) -> dict:
    return {"id": i.id, "company": i.company, "role": i.role, "format": i.format, "notes": i.notes,
            "application_id": i.application_id, "scheduled_at": i.scheduled_at.isoformat() if i.scheduled_at else None}


def _sess(db: Session, sid: str) -> InterviewSession:
    s = db.get(InterviewSession, sid)
    if s is None or s.deleted_at is not None:
        raise HTTPException(404, "session not found")
    return s


def _sd(db: Session, s: InterviewSession) -> dict:
    fb = db.query(InterviewFeedback).filter(InterviewFeedback.session_id == s.id).first()
    qs = svc.questions_for(db, s)
    answered = sum(1 for t in s.transcript if t["role"] == "candidate")
    return {"id": s.id, "kind": s.kind, "target_role": s.target_role, "job_id": s.job_id, "status": s.status,
            "transcript": s.transcript, "created_at": s.created_at.isoformat(),
            "current_question": svc.public_q(qs[answered]) if s.status == "active" and answered < len(qs) else None,
            "feedback": svc.feedback_dict(fb)}


@router.get("/interviews")
def list_interviews(db: Session = Depends(get_db)):
    return [_iv(i) for i in db.query(Interview).filter(Interview.deleted_at.is_(None)).order_by(Interview.created_at.desc())]


@router.post("/interviews", status_code=201)
def create_interview(body: InterviewIn, db: Session = Depends(get_db)):
    i = Interview(**body.model_dump())
    db.add(i)
    db.flush()
    return _iv(i)


@router.post("/interview-sessions", status_code=201)
def create_session(body: SessionIn, db: Session = Depends(get_db)):
    try:
        s = svc.create_session(db, body.kind, body.job_id, body.target_role)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    except LookupError as e:
        raise HTTPException(404, str(e)) from None
    return _sd(db, s)


@router.get("/interview-sessions")
def list_sessions(db: Session = Depends(get_db)):
    return [_sd(db, s) for s in db.query(InterviewSession).filter(InterviewSession.deleted_at.is_(None))
            .order_by(InterviewSession.created_at.desc())]


@router.post("/interview-sessions/{sid}/answer")
def answer(sid: str, body: AnswerIn, db: Session = Depends(get_db)):
    try:
        return svc.answer(db, _sess(db, sid), body.text)
    except ValueError as e:
        raise HTTPException(409, str(e)) from None


@router.post("/interview-sessions/{sid}/finish")
def finish(sid: str, body: FinishIn | None = None, db: Session = Depends(get_db)):
    fb = svc.finish(db, _sess(db, sid), bool(body and body.use_llm))
    return svc.feedback_dict(fb)


@router.get("/interview-sessions/{sid}/export", response_class=PlainTextResponse)
def export(sid: str, db: Session = Depends(get_db)):
    return PlainTextResponse(svc.export_markdown(db, _sess(db, sid)), media_type="text/markdown")
