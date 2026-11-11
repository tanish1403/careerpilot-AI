# CareerPilot AI --- Implementation Plan

## 1. Delivery strategy

Build in vertical slices. Each phase must leave the application
runnable, documented, and testable. Do not implement all agents,
connectors, and automation simultaneously. The highest-risk areas are
source compliance, resume factuality, browser automation reliability,
and credential/security boundaries.

### Phase 0 --- Product and engineering foundation

**Deliverables** - Finalize MVP scope and explicit non-goals. - Create
repository structure and architecture decision records. - Select licence
after dependency review (MIT or Apache-2.0 are candidates; decide before
release). - Define code style, type checking, linting, test conventions,
commit rules. - Establish threat model and data classification. - Create
Windows CMD setup scripts and `.env.example`. - Add CI for lint, type
checks, unit tests, dependency and secret scanning.

**Acceptance criteria** - Fresh Windows machine can follow setup
instructions without WSL. - Backend health endpoint and frontend shell
run locally. - No secrets or personal files are tracked by Git. - CI
runs on every pull request.

### Phase 1 --- Local application shell and system controls

**Deliverables** - React/TypeScript dashboard shell with sidebar and
responsive layouts. - FastAPI backend, versioned API, health/readiness
endpoints. - SQLite persistence and SQLAlchemy migrations. - Local
authentication/session strategy appropriate for a single-user
instance. - Settings pages, task/event log, system diagnostics. -
Import/export and backup foundations.

**Acceptance criteria** - User can launch and stop the app using
documented CMD scripts. - Frontend can read/write a test setting through
the backend. - Database migrations and backup/restore tests pass. - No
API credential is exposed in browser responses.

### Phase 2 --- Career profile and document ingestion

**Deliverables** - Candidate profile editor. - Education, experience,
skills, projects, publications, certifications, preferences. - Upload
and parse PDF, DOCX, DOC, TXT, Markdown, RTF, LaTeX, HTML. - Optional
OCR pipeline for scanned PDF/images. - Human review of extracted
fields. - Evidence records linking facts to source file and location. -
Profile completeness and contradiction checks.

**Acceptance criteria** - User can upload a supported resume and review
extracted facts. - Parser reports unsupported/corrupt files clearly. -
No extracted fact is silently treated as verified. - User can edit,
confirm, reject, and export the profile. - Tests include multi-column
resumes, tables, scanned pages, malformed files, and non-English text
where supported.

### Phase 3 --- Resume Studio

**Deliverables** - Master resume assembled from verified profile
evidence. - Versioned LaTeX templates. - LaTeX source editor and
compiled PDF preview. - Tailoring against a pasted or imported job
description. - ATS-oriented checks: headings, reading order, text
extraction, links, layout. - Claim-to-evidence traceability. - Resume
diff, restore, export PDF/TEX and later DOCX. - Cover-letter drafts.

**Acceptance criteria** - Every generated claim maps to verified
evidence or is clearly marked for user confirmation. - PDF compilation
runs in a controlled process with time/resource limits. - Generated PDF
text is extracted and compared with expected content. - User can inspect
and restore every version. - Resume tailoring never changes factual
dates, titles, degrees, or metrics without explicit user edits.

### Phase 4 --- Job source adapters and normalized job store

**Deliverables** - Connector interface and source registry. -
Greenhouse, Ashby, and Lever adapters. - Company career-page connector
framework. - Optional JobSpy adapter only after licence and source
compliance review. - User-supplied URL ingestion. - Job normalization,
deduplication, freshness, verification, expiry detection. - Per-source
rate limits, retries, backoff, and connector health. - Source coverage
and ingestion logs.

**Acceptance criteria** - Same job from multiple sources is deduplicated
without losing source references. - First-seen and last-verified
timestamps are stored. - Expired jobs are marked, not silently
deleted. - Connector errors do not stop other connectors. - Automated
tests use fixtures and mocked HTTP responses; live smoke tests are
opt-in. - Each connector has documented permitted usage and limitations.

### Phase 5 --- Matching and job intelligence

**Deliverables** - Job description parser and requirement taxonomy. -
Hard eligibility checks with unknown state. - Configurable fit
scoring. - Application priority ranking. - Evidence and missing-skill
explanations. - Filters for new, recent, location, salary, seniority,
work mode, source, role. - User feedback: relevant/not relevant,
applied/skip, reason. - Match evaluation dataset and regression tests.

**Acceptance criteria** - Every score exposes contributing factors and
evidence. - Unknown requirements are not treated as satisfied. - Weights
are configurable. - Fit score is never presented as a guaranteed
selection probability. - Ranking can be reproduced from saved
profile/job/scoring versions.

### Phase 6 --- Provider gateway and agent orchestration

**Deliverables** - Provider configuration UI and encrypted secret
storage. - Model registry and capability metadata. - Connection tests
and model discovery where supported. - LiteLLM integration or equivalent
adapter abstraction. - Per-task/per-agent model routing. - Fallbacks,
timeouts, retries, budgets, token/cost tracking. - Typed agent
inputs/outputs. - LangGraph workflow checkpoints and human approval
nodes. - Agent execution logs and pause/resume controls.

**Acceptance criteria** - User can configure at least one
cloud-compatible provider and Ollama. - Provider failure is surfaced and
fallback behavior is tested. - Secrets never appear in frontend payloads
or logs. - Agents can be run independently with deterministic schemas. -
A workflow can pause for approval and resume from checkpoint.

### Phase 7 --- Application center and supervised browser autofill

**Deliverables** - Application lifecycle and Kanban. - Per-job
application workspace. - Field mapping from verified profile. - Answer
drafting with evidence references. - Playwright-based supported-form
automation. - Domain allowlist and explicit user-started browser
session. - Review screen before final submission. - Screenshot/event
logs with sensitive data redaction. - Application confirmation and
follow-up tracking.

**Acceptance criteria** - Autofill never submits by default. - Unknown
or sensitive questions are escalated to the user. - Automation stops on
CAPTCHA, authentication challenge, unsupported page, or policy
restriction. - Duplicate submission protection is implemented. - Every
field is validated before user review. - User can edit any answer and
inspect the final form before submission.

### Phase 8 --- Learning Studio and interview preparation

**Deliverables** - Career-track templates and editable study plans. -
Job-driven skill-gap learning recommendations. - Resource library with
source URLs and access dates. - DSA/topic progress tracking and revision
reminders. - Company research briefs. - Mock interview sessions:
technical, coding, project, system design, behavioral. - Feedback rubric
and session history. - Adaptive plan based on user feedback and
outcomes.

**Acceptance criteria** - Study tasks are editable and schedulable. -
Recommendations explain which target jobs or skill gaps motivated
them. - Interview feedback distinguishes factual correctness from
communication feedback. - The user can export study plans and session
notes. - No fabricated company interview questions are represented as
verified historical questions.

### Phase 9 --- Scheduler, notifications, and weekly review

**Deliverables** - Configurable daily and recurring job scans. - Daily
digest and high-priority alerts. - Study schedule generation. -
Application follow-up reminders. - Weekly conversion and activity
report. - Desktop notifications as optional capability. - Scheduler
pause/resume and missed-run recovery.

**Acceptance criteria** - Timezone is explicit and configurable. -
Re-running a scheduled task is idempotent. - Scheduler failures are
visible and retryable. - User can disable any automation. - No task
performs an application submission without its required approval.

### Phase 10 --- Hardening, packaging, and public release

**Deliverables** - Security review and threat-model update. -
Performance and recovery tests. - Windows installer or documented
portable setup. - Optional Docker Compose for advanced deployment. -
Backup/restore and data export. - Full documentation and screenshots. -
Licence and third-party notices. - Release workflow, changelog, issue
templates, contribution guide.

**Acceptance criteria** - Fresh install, upgrade, backup, restore, and
uninstall paths are tested. - No critical/high unresolved security
findings. - All advertised features have tests or are explicitly marked
experimental. - Public README clearly distinguishes implemented,
planned, and experimental functionality.

## 2. Suggested MVP scope

The first usable MVP should include: 1. Local dashboard and profile. 2.
Resume upload and parsing with human review. 3. Master resume and LaTeX
PDF generation. 4. Greenhouse/Ashby/Lever job ingestion. 5. Job matching
with transparent evidence. 6. Saved jobs and application tracking. 7.
One configurable model provider plus Ollama option. 8. Daily job scan
and daily digest. 9. Manual application preparation (no autonomous
submission). 10. Basic study planner.

Do not put broad auto-apply, dozens of job portals, voice interviews,
multi-user hosting, or advanced predictive selection into the first MVP.

## 3. Work breakdown and dependency order

  Workstream                    Depends on                     Priority
  ----------------------------- ------------------------------ ----------
  Repo, API, UI, DB             None                           P0
  Profile and evidence model    Foundation                     P0
  Document parser               Profile model                  P0
  Resume engine                 Verified profile               P0
  Job source adapters           Foundation                     P0
  Job normalization             Source adapters                P0
  Matching                      Profile + normalized jobs      P0
  Model gateway                 Foundation                     P1
  Agent orchestration           Model gateway + schemas        P1
  Application tracker           Job store                      P1
  Browser autofill              Profile + tracker + policies   P2
  Interview and learning        Profile + job intelligence     P1
  Scheduler                     Stable background tasks        P1
  Multi-user/cloud deployment   Security and tenancy design    P3

## 4. Proposed API boundaries

Use `/api/v1` and typed request/response schemas.

-   `/profiles` --- candidate profile CRUD and export
-   `/documents` --- upload, parse, review, download
-   `/experiences`, `/skills`, `/projects`, `/education`,
    `/publications`
-   `/resumes` --- generate, compile, preview, versions, diff
-   `/jobs` --- search, filters, detail, saved jobs
-   `/sources` --- connector configuration, test, run, health
-   `/matches` --- score, explain, feedback
-   `/applications` --- lifecycle, answers, events, review
-   `/automation` --- browser sessions, fill preview, approval
-   `/providers` --- provider profiles, connection test, models
-   `/agents` --- configuration, run, pause, resume
-   `/workflows` --- definitions, execution, checkpoints
-   `/study-plans` --- schedule and progress
-   `/interviews` --- sessions, feedback, history
-   `/scheduler` --- schedules, runs, status
-   `/system` --- health, logs, backup, restore, diagnostics

All mutating endpoints require authorization and validation.
Long-running work should return a run ID and expose status via polling
or SSE/WebSocket.

## 5. Key data entities

-   User / Workspace
-   CandidateProfile
-   ProfileFact / Evidence
-   Experience / Education / Skill / Project / Publication /
    Certification
-   Document / ParseRun
-   ResumeTemplate / ResumeVersion / ResumeClaim
-   JobSource / Job / JobRequirement
-   MatchResult / MatchFeedback
-   Company
-   Application / ApplicationAnswer / ApplicationEvent
-   Interview / InterviewSession / InterviewFeedback
-   StudyPlan / StudyTask / LearningResource
-   Provider / Model / AgentConfig
-   Workflow / WorkflowRun / Checkpoint
-   ScheduledTask / TaskRun
-   AuditEvent / Notification

Use stable IDs, created/updated timestamps, soft-delete where
appropriate, and workspace ownership on all user data.

## 6. Non-functional requirements

-   Windows 10/11 support; no WSL requirement.
-   Backend and frontend can run independently.
-   Local-only mode must be possible.
-   Secrets encrypted at rest and redacted from logs.
-   Explicit user consent before external transmission of sensitive
    documents.
-   Configurable data retention and deletion.
-   Exportable user data.
-   Idempotent background tasks.
-   Rate limits and retry/backoff per source.
-   Observability without collecting unnecessary personal content.
-   Accessibility and responsive UI.
-   Automated tests for core workflows.
-   No feature advertised as complete until acceptance criteria pass.

## 7. Risk register

  -----------------------------------------------------------------------
  Risk                                Mitigation
  ----------------------------------- -----------------------------------
  Job sites block or prohibit         Prefer public APIs, approved feeds,
  automation                          user-provided URLs; document
                                      limitations

  Job data becomes stale              Store timestamps, re-verify links,
                                      expire stale listings

  Duplicate jobs                      Canonical URL + source ID +
                                      similarity dedupe

  Resume hallucination                Evidence-linked claims, validation,
                                      user review

  LLM provider outages                Timeouts, retry, optional fallback,
                                      manual mode

  API cost spikes                     Per-task budgets, cheaper routing,
                                      usage dashboard

  Browser automation breaks           Supported-site adapters, fixtures,
                                      screenshots, stop-on-uncertainty

  Sensitive data leakage              Local-first defaults, encrypted
                                      secrets, redaction, provider
                                      consent

  Misleading match scores             Explain factors; do not claim
                                      selection probability

  Scope explosion                     MVP gates and phase acceptance
                                      criteria
  -----------------------------------------------------------------------

## 8. Definition of done for every feature

A feature is complete only when: - UI and API are implemented. - Input
validation and error states exist. - Unit and relevant integration tests
pass. - Logs are useful but do not leak secrets or personal data. -
Documentation is updated. - Permission and privacy implications are
reviewed. - Empty, loading, success, and failure states are designed. -
Feature status is accurately represented in the UI.

## 9. First implementation sprint

1.  Create repository and docs.
2.  Build FastAPI service and React shell.
3.  Add SQLite, SQLAlchemy, and Alembic.
4.  Add profile schema and CRUD.
5.  Add resume upload and parser interface.
6.  Add provider configuration schema (secrets remain server-side).
7.  Add health/status panel.
8.  Add Windows CMD setup/start/stop scripts.
9.  Add unit tests and a clean-install walkthrough.

At the end of Sprint 1, a user should be able to launch the application,
create a profile, upload a resume, inspect extracted facts, and save
them locally. This is a meaningful foundation, not a mock dashboard.
