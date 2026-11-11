"""Lane F: company research + companies."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...core.auth import current_user
from ...db.models import Company
from ...db.session import get_db
from ...research import service as svc

router = APIRouter(tags=["research"], dependencies=[Depends(current_user)])


class ResearchIn(BaseModel):
    company: str = Field(min_length=1, max_length=200)
    role: str | None = None
    job_id: str | None = None
    urls: list[str] = Field(default_factory=list, max_length=5)
    interview_notes: list[dict] = Field(default_factory=list, max_length=20)


@router.post("/research/company", status_code=202)
def research_company(body: ResearchIn, db: Session = Depends(get_db)):
    c = svc.build_brief(db, body.company, body.role, body.job_id, body.urls, body.interview_notes)
    return svc.company_dict(c)


@router.get("/companies")
def list_companies(db: Session = Depends(get_db)):
    return [svc.company_dict(c) for c in db.query(Company).filter(Company.deleted_at.is_(None)).order_by(Company.name)]


@router.get("/companies/{cid}")
def get_company(cid: str, db: Session = Depends(get_db)):
    c = db.get(Company, cid)
    if c is None or c.deleted_at is not None:
        raise HTTPException(404, "company not found")
    return svc.company_dict(c)
