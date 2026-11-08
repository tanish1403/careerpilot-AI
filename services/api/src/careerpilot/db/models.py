"""All entities from IMPLEMENTATION_PLAN section 5. Lanes may ADD columns via new
Alembic revisions but must not rename/remove these without updating this file."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, Entity, fk, utcnow


def S(n=255, **kw):
    return mapped_column(String(n), **kw)


# ---- workspace / user -------------------------------------------------------
class User(Entity, Base):
    __tablename__ = "users"
    username: Mapped[str] = S(100, unique=True)
    password_hash: Mapped[str] = S(255)
    role: Mapped[str] = S(20, default="owner")


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# ---- profile / evidence -----------------------------------------------------
class CandidateProfile(Entity, Base):
    __tablename__ = "candidate_profiles"
    full_name: Mapped[str | None] = S(200, nullable=True)
    headline: Mapped[str | None] = S(300, nullable=True)
    email: Mapped[str | None] = S(200, nullable=True)
    phone: Mapped[str | None] = S(50, nullable=True)
    location: Mapped[str | None] = S(200, nullable=True)
    links: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)  # roles, locations, work mode, salary
    version: Mapped[int] = mapped_column(Integer, default=1)


class Document(Entity, Base):
    __tablename__ = "documents"
    profile_id: Mapped[str | None] = fk("candidate_profiles", nullable=True)
    filename: Mapped[str] = S(300)
    mime: Mapped[str | None] = S(100, nullable=True)
    storage_path: Mapped[str] = S(500)
    sha256: Mapped[str] = S(64, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = S(30, default="resume")


class ParseRun(Entity, Base):
    __tablename__ = "parse_runs"
    document_id: Mapped[str] = fk("documents")
    status: Mapped[str] = S(20, default="pending")
    parser: Mapped[str | None] = S(50, nullable=True)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_text_ref: Mapped[str | None] = S(500, nullable=True)


class ProfileFact(Entity, Base):
    """Evidence record. A fact is NEVER verified unless status == 'confirmed'."""
    __tablename__ = "profile_facts"
    profile_id: Mapped[str] = fk("candidate_profiles")
    category: Mapped[str] = S(30, index=True)   # experience|education|skill|project|publication|certification|other
    key: Mapped[str] = S(200)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = S(20, default="proposed", index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_document_id: Mapped[str | None] = fk("documents", nullable=True)
    source_location: Mapped[str | None] = S(200, nullable=True)  # e.g. "page 2, line 14"
    parse_run_id: Mapped[str | None] = fk("parse_runs", nullable=True)


class _ProfileItem:
    profile_id: Mapped[str] = fk("candidate_profiles")
    fact_id: Mapped[str | None] = fk("profile_facts", nullable=True)
    status: Mapped[str] = S(20, default="proposed")


class Experience(Entity, _ProfileItem, Base):
    __tablename__ = "experiences"
    company: Mapped[str] = S(200)
    title: Mapped[str] = S(200)
    location: Mapped[str | None] = S(200, nullable=True)
    start_date: Mapped[str | None] = S(20, nullable=True)
    end_date: Mapped[str | None] = S(20, nullable=True)
    bullets: Mapped[list] = mapped_column(JSON, default=list)


class Education(Entity, _ProfileItem, Base):
    __tablename__ = "education"
    institution: Mapped[str] = S(200)
    degree: Mapped[str | None] = S(200, nullable=True)
    field: Mapped[str | None] = S(200, nullable=True)
    start_date: Mapped[str | None] = S(20, nullable=True)
    end_date: Mapped[str | None] = S(20, nullable=True)
    grade: Mapped[str | None] = S(50, nullable=True)


class Skill(Entity, _ProfileItem, Base):
    __tablename__ = "skills"
    name: Mapped[str] = S(100)
    category: Mapped[str | None] = S(50, nullable=True)
    level: Mapped[str | None] = S(30, nullable=True)
    years: Mapped[float | None] = mapped_column(Float, nullable=True)


class Project(Entity, _ProfileItem, Base):
    __tablename__ = "projects"
    name: Mapped[str] = S(200)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = S(500, nullable=True)
    technologies: Mapped[list] = mapped_column(JSON, default=list)
    bullets: Mapped[list] = mapped_column(JSON, default=list)


class Publication(Entity, _ProfileItem, Base):
    __tablename__ = "publications"
    title: Mapped[str] = S(400)
    venue: Mapped[str | None] = S(300, nullable=True)
    year: Mapped[str | None] = S(10, nullable=True)
    url: Mapped[str | None] = S(500, nullable=True)


class Certification(Entity, _ProfileItem, Base):
    __tablename__ = "certifications"
    name: Mapped[str] = S(300)
    issuer: Mapped[str | None] = S(200, nullable=True)
    date: Mapped[str | None] = S(20, nullable=True)
    url: Mapped[str | None] = S(500, nullable=True)


# ---- resume -----------------------------------------------------------------
class ResumeTemplate(Entity, Base):
    __tablename__ = "resume_templates"
    name: Mapped[str] = S(100)
    version: Mapped[str] = S(20, default="1")
    latex_source: Mapped[str] = mapped_column(Text)


class ResumeVersion(Entity, Base):
    __tablename__ = "resume_versions"
    profile_id: Mapped[str] = fk("candidate_profiles")
    job_id: Mapped[str | None] = fk("jobs", nullable=True)
    template_id: Mapped[str | None] = fk("resume_templates", nullable=True)
    parent_version_id: Mapped[str | None] = S(32, nullable=True)
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    latex_source: Mapped[str] = mapped_column(Text)
    pdf_path: Mapped[str | None] = S(500, nullable=True)
    validation_report: Mapped[dict] = mapped_column(JSON, default=dict)
    profile_version: Mapped[int] = mapped_column(Integer, default=1)
    label: Mapped[str | None] = S(200, nullable=True)


class ResumeClaim(Entity, Base):
    __tablename__ = "resume_claims"
    resume_version_id: Mapped[str] = fk("resume_versions")
    text: Mapped[str] = mapped_column(Text)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    needs_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)


# ---- jobs -------------------------------------------------------------------
class Company(Entity, Base):
    __tablename__ = "companies"
    name: Mapped[str] = S(200, index=True)
    website: Mapped[str | None] = S(500, nullable=True)
    brief: Mapped[dict] = mapped_column(JSON, default=dict)
    brief_retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class JobSource(Entity, Base):
    __tablename__ = "job_sources"
    kind: Mapped[str] = S(30)  # greenhouse|ashby|lever|career_page|url|jobspy
    name: Mapped[str] = S(200)
    config: Mapped[dict] = mapped_column(JSON, default=dict)  # e.g. {"board_token": "acme"}
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    rate_limit_per_min: Mapped[int] = mapped_column(Integer, default=30)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = S(20, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Job(Entity, Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("workspace_id", "dedupe_key", name="uq_job_dedupe"),)
    dedupe_key: Mapped[str] = S(64, index=True)
    company_id: Mapped[str | None] = fk("companies", nullable=True)
    title: Mapped[str] = S(400)
    company_name: Mapped[str] = S(200)
    location: Mapped[str | None] = S(300, nullable=True)
    work_mode: Mapped[str] = S(20, default="unknown")
    description: Mapped[str] = mapped_column(Text, default="")
    requirements: Mapped[list] = mapped_column(JSON, default=list)
    salary_text: Mapped[str | None] = S(200, nullable=True)
    seniority: Mapped[str | None] = S(50, nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    canonical_url: Mapped[str] = S(1000)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = S(20, default="open", index=True)
    saved: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)


class JobSourceRecord(Entity, Base):
    """Provenance: one row per (source, external id) so dedupe never loses references."""
    __tablename__ = "job_source_records"
    job_id: Mapped[str] = fk("jobs")
    source_id: Mapped[str | None] = fk("job_sources", nullable=True)
    external_id: Mapped[str] = S(200)
    source_url: Mapped[str] = S(1000)
    collection_method: Mapped[str] = S(50)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)


class JobRequirement(Entity, Base):
    __tablename__ = "job_requirements"
    job_id: Mapped[str] = fk("jobs")
    text: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = S(30, default="skill")  # skill|experience|education|location|authorization|other
    mandatory: Mapped[bool] = mapped_column(Boolean, default=False)
    normalized: Mapped[str | None] = S(200, nullable=True)


class IngestionLog(Entity, Base):
    __tablename__ = "ingestion_logs"
    source_id: Mapped[str | None] = fk("job_sources", nullable=True)
    status: Mapped[str] = S(20)
    fetched: Mapped[int] = mapped_column(Integer, default=0)
    created: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    closed: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


# ---- matching ---------------------------------------------------------------
class MatchResult(Entity, Base):
    __tablename__ = "match_results"
    profile_id: Mapped[str] = fk("candidate_profiles")
    job_id: Mapped[str] = fk("jobs")
    profile_version: Mapped[int] = mapped_column(Integer)
    job_version: Mapped[int] = mapped_column(Integer)
    config_version: Mapped[str] = S(64)
    eligibility: Mapped[str] = S(20)       # satisfied|not_satisfied|unknown
    eligibility_details: Mapped[list] = mapped_column(JSON, default=list)
    fit_score: Mapped[float] = mapped_column(Float)
    priority_score: Mapped[float] = mapped_column(Float)
    factors: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    missing: Mapped[list] = mapped_column(JSON, default=list)


class MatchFeedback(Entity, Base):
    __tablename__ = "match_feedback"
    match_id: Mapped[str] = fk("match_results")
    relevant: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    action: Mapped[str | None] = S(20, nullable=True)  # applied|skip
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


# ---- applications -----------------------------------------------------------
class Application(Entity, Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("workspace_id", "job_id", name="uq_application_job"),)
    job_id: Mapped[str] = fk("jobs")
    state: Mapped[str] = S(30, default="Discovered", index=True)
    resume_version_id: Mapped[str | None] = fk("resume_versions", nullable=True)
    approved_by: Mapped[str | None] = S(100, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submission_approval_id: Mapped[str | None] = S(32, nullable=True)
    confirmation_ref: Mapped[str | None] = S(500, nullable=True)
    destination_url: Mapped[str | None] = S(1000, nullable=True)
    idempotency_key: Mapped[str | None] = S(64, nullable=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApplicationAnswer(Entity, Base):
    __tablename__ = "application_answers"
    application_id: Mapped[str] = fk("applications")
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_user: Mapped[bool] = mapped_column(Boolean, default=False)
    user_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)


class ApplicationEvent(Entity, Base):
    __tablename__ = "application_events"
    application_id: Mapped[str] = fk("applications")
    kind: Mapped[str] = S(40)
    from_state: Mapped[str | None] = S(30, nullable=True)
    to_state: Mapped[str | None] = S(30, nullable=True)
    actor: Mapped[str | None] = S(100, nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


# ---- interviews / learning --------------------------------------------------
class Interview(Entity, Base):
    __tablename__ = "interviews"
    application_id: Mapped[str | None] = fk("applications", nullable=True)
    company: Mapped[str | None] = S(200, nullable=True)
    role: Mapped[str | None] = S(200, nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    format: Mapped[str | None] = S(50, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class InterviewSession(Entity, Base):
    __tablename__ = "interview_sessions"
    interview_id: Mapped[str | None] = fk("interviews", nullable=True)
    kind: Mapped[str] = S(30)  # technical|coding|project|system_design|behavioral
    target_role: Mapped[str | None] = S(200, nullable=True)
    job_id: Mapped[str | None] = fk("jobs", nullable=True)
    transcript: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = S(20, default="active")


class InterviewFeedback(Entity, Base):
    __tablename__ = "interview_feedback"
    session_id: Mapped[str] = fk("interview_sessions")
    factual_correctness: Mapped[dict] = mapped_column(JSON, default=dict)  # kept separate from...
    communication: Mapped[dict] = mapped_column(JSON, default=dict)        # ...communication feedback
    revision_tasks: Mapped[list] = mapped_column(JSON, default=list)


class StudyPlan(Entity, Base):
    __tablename__ = "study_plans"
    name: Mapped[str] = S(200)
    track: Mapped[str | None] = S(100, nullable=True)
    motivation: Mapped[dict] = mapped_column(JSON, default=dict)  # which jobs/skill gaps motivated it
    hours_per_week: Mapped[float | None] = mapped_column(Float, nullable=True)


class StudyTask(Entity, Base):
    __tablename__ = "study_tasks"
    plan_id: Mapped[str] = fk("study_plans")
    title: Mapped[str] = S(300)
    topic: Mapped[str | None] = S(100, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = S(20, default="todo")
    resource_id: Mapped[str | None] = S(32, nullable=True)
    revise_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class LearningResource(Entity, Base):
    __tablename__ = "learning_resources"
    title: Mapped[str] = S(300)
    url: Mapped[str] = S(1000)
    topic: Mapped[str | None] = S(100, nullable=True)
    accessed_on: Mapped[str | None] = S(20, nullable=True)


# ---- providers / agents / workflows ----------------------------------------
class Provider(Entity, Base):
    __tablename__ = "providers"
    display_name: Mapped[str] = S(100)
    protocol: Mapped[str] = S(30)   # openai_compatible|ollama|anthropic|gemini
    base_url: Mapped[str] = S(500)
    secret_ref: Mapped[str | None] = S(100, nullable=True)  # name in encrypted secret store
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    timeout_s: Mapped[int] = mapped_column(Integer, default=60)
    max_retries: Mapped[int] = mapped_column(Integer, default=2)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Secret(Base):
    """Encrypted at rest. Never returned by any API."""
    __tablename__ = "secrets"
    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Model(Entity, Base):
    __tablename__ = "models"
    provider_id: Mapped[str] = fk("providers")
    model_id: Mapped[str] = S(200)
    capabilities: Mapped[dict] = mapped_column(JSON, default=dict)  # chat, structured_output, tool_calling, vision, embeddings, context_length, streaming
    verified: Mapped[bool] = mapped_column(Boolean, default=False)  # declared vs verified
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class AgentConfig(Entity, Base):
    __tablename__ = "agent_configs"
    agent: Mapped[str] = S(50, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    primary_model_id: Mapped[str | None] = S(32, nullable=True)
    fallback_model_ids: Mapped[list] = mapped_column(JSON, default=list)
    budget_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)


class Workflow(Entity, Base):
    __tablename__ = "workflows"
    name: Mapped[str] = S(100)
    definition: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class WorkflowRun(Entity, Base):
    __tablename__ = "workflow_runs"
    workflow_id: Mapped[str | None] = fk("workflows", nullable=True)
    parent_run_id: Mapped[str | None] = S(32, nullable=True)
    agent: Mapped[str | None] = S(50, nullable=True)
    agent_version: Mapped[str | None] = S(20, nullable=True)
    status: Mapped[str] = S(20, default="pending", index=True)
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    output_refs: Mapped[dict] = mapped_column(JSON, default=dict)
    provider_meta: Mapped[dict] = mapped_column(JSON, default=dict)  # provider/model/fallback used
    usage: Mapped[dict] = mapped_column(JSON, default=dict)          # tokens/cost
    retries: Mapped[int] = mapped_column(Integer, default=0)
    approval_actor: Mapped[str | None] = S(100, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = S(100, nullable=True, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Checkpoint(Entity, Base):
    __tablename__ = "checkpoints"
    run_id: Mapped[str] = fk("workflow_runs")
    step: Mapped[str] = S(100)
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    awaiting_approval: Mapped[bool] = mapped_column(Boolean, default=False)


class Approval(Entity, Base):
    """Explicit human approval. Final submission requires kind='submit' tied to one application."""
    __tablename__ = "approvals"
    kind: Mapped[str] = S(30)  # resume|autofill|submit|workflow
    subject_type: Mapped[str] = S(30)
    subject_id: Mapped[str] = S(32, index=True)
    status: Mapped[str] = S(20, default="pending")  # pending|granted|denied|expired
    actor: Mapped[str | None] = S(100, nullable=True)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)  # exact resume/answers/destination reviewed
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ---- scheduler / audit ------------------------------------------------------
class ScheduledTask(Entity, Base):
    __tablename__ = "scheduled_tasks"
    name: Mapped[str] = S(100)
    kind: Mapped[str] = S(40)  # job_scan|daily_digest|study_schedule|follow_up|weekly_report
    cron: Mapped[str] = S(100)
    timezone: Mapped[str] = S(60, default="UTC")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TaskRun(Entity, Base):
    __tablename__ = "task_runs"
    __table_args__ = (UniqueConstraint("task_id", "period_key", name="uq_taskrun_period"),)
    task_id: Mapped[str] = fk("scheduled_tasks")
    period_key: Mapped[str] = S(40)  # idempotency: one run per task per period
    status: Mapped[str] = S(20, default="pending")
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEvent(Entity, Base):
    __tablename__ = "audit_events"
    actor: Mapped[str | None] = S(100, nullable=True)
    action: Mapped[str] = S(100, index=True)
    subject_type: Mapped[str | None] = S(50, nullable=True)
    subject_id: Mapped[str | None] = S(32, nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)  # must be pre-redacted


class Notification(Entity, Base):
    __tablename__ = "notifications"
    kind: Mapped[str] = S(30)
    title: Mapped[str] = S(300)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
