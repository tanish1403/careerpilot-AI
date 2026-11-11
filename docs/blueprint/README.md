# CareerPilot AI

### Local-first, open-source AI career operating system

CareerPilot AI is a self-hostable career platform that helps a job
seeker manage the full job-search lifecycle: candidate profiling, job
discovery, job matching, resume tailoring, application preparation,
interview practice, learning plans, and application tracking.

The product is designed to be **local-first, provider-neutral,
auditable, and human-controlled**. It should work on Windows without
requiring WSL. Cloud LLM APIs are optional; local inference through
Ollama is supported.

> **Project status:** Product blueprint / implementation specification.
> This repository is not yet an implemented application. Do not
> interpret planned features as already working.

## Product principles

1.  **Candidate-owned data:** users can export, back up, and delete
    their information.
2.  **Evidence-backed resumes:** generated claims must trace to verified
    profile evidence. The system must not invent qualifications,
    metrics, dates, or achievements.
3.  **Human approval:** prepare and autofill applications, but pause
    before final submission by default. Submission is only enabled for
    explicitly permitted workflows and after user authorization.
4.  **Provider neutrality:** route tasks to OmniRoute, OpenRouter,
    FreeLLMAPI, Ollama, Claude, OpenAI, or compatible endpoints without
    binding agents to one vendor.
5.  **Source transparency:** every job stores its source, original URL,
    first-seen time, last-verified time, and collection method.
6.  **Reliable automation:** workflows need checkpoints, retries,
    idempotency, audit logs, and recovery.
7.  **Open-source by design:** use dependencies with compatible
    licences; record third-party notices and review licences before
    reuse.
8.  **No false guarantees:** match scores are decision-support signals,
    not promises of interviews or selection.

## Core capabilities

-   Candidate profile and career evidence library
-   Resume ingestion: PDF, DOCX, DOC, TXT, Markdown, RTF, LaTeX, HTML,
    and scanned images where practical
-   Job discovery through public APIs, permitted feeds, company career
    pages, search alerts, and optional connectors
-   Job normalization, deduplication, freshness tracking, and source
    verification
-   Configurable eligibility, fit, and application-priority scoring
-   ATS-oriented resume tailoring with LaTeX source and PDF export
-   Cover letters and application-answer drafts
-   Assisted browser autofill for supported forms
-   Approval gates and application tracking
-   Company research and interview preparation
-   Adaptive study plans, DSA practice, technical tracks, and mock
    interviews
-   Agent and workflow control center
-   Provider/model configuration, fallback routing, usage and cost
    visibility
-   Local-first storage, backups, logs, and system diagnostics

## Recommended technology

  -----------------------------------------------------------------------
  Layer                               Initial recommendation
  ----------------------------------- -----------------------------------
  Frontend                            React + TypeScript + Vite (or
                                      Next.js if server-rendering becomes
                                      necessary)

  UI                                  Tailwind CSS, shadcn/ui, accessible
                                      component patterns

  State/data                          TanStack Query; Zustand only for
                                      local UI state

  Backend                             Python + FastAPI + Pydantic

  Persistence                         SQLite for single-user MVP;
                                      PostgreSQL for multi-user/advanced
                                      deployment

  ORM/migrations                      SQLAlchemy + Alembic

  Vector retrieval                    pgvector when PostgreSQL is
                                      enabled; keep an abstraction for
                                      local alternatives

  Background work                     APScheduler for MVP; Celery/RQ +
                                      Redis when concurrency justifies it

  Agent workflows                     LangGraph for durable multi-step
                                      workflows; PydanticAI for typed
                                      agent tasks

  Model gateway                       LiteLLM or a thin provider adapter
                                      layer; evaluate actual
                                      compatibility per provider

  Browser automation                  Playwright with explicit domain and
                                      action policies

  Documents                           PyMuPDF, python-docx,
                                      Tesseract/PaddleOCR as optional OCR
                                      components

  Resume rendering                    LaTeX (XeLaTeX or LuaLaTeX) in a
                                      controlled local toolchain

  Observability                       Structured logs, OpenTelemetry;
                                      optional Langfuse with privacy
                                      controls

  Packaging                           Windows CMD scripts first; optional
                                      Docker Compose for advanced
                                      deployment
  -----------------------------------------------------------------------

The stack is a recommendation, not a requirement to install every
service in the first milestone. Start with the smallest viable local
stack.

## Model providers

The model manager should support configurable provider profiles:

-   OmniRoute
-   OpenRouter
-   FreeLLMAPI (only where its endpoint and API contract are compatible)
-   Ollama
-   Anthropic Claude
-   OpenAI
-   Gemini, Groq, Together, DeepSeek, Mistral, and other compatible
    providers
-   Custom OpenAI-compatible base URLs
-   Optional local OpenAI-compatible servers such as LM Studio or vLLM

Each provider profile needs: display name, protocol, base URL, secret
reference, enabled state, connection test, available model IDs,
capability metadata, timeout, retry policy, and usage tracking. Never
send API secrets to the frontend or include them in logs. Provider/model
names are user configuration, not hardcoded assumptions.

## Job discovery strategy

Use adapters, not a single universal scraper.

Priority integration order: 1. Greenhouse public job board endpoints 2.
Ashby public job posting endpoints 3. Lever public postings endpoints 4.
Company career pages and ATS-specific public endpoints 5. Optional
JobSpy adapter after licence, maintenance, site terms, and source
coverage review 6. User-supplied URLs and job alerts 7. Additional
portals only through permitted feeds, official integrations, or
compliant collection methods

Do not bypass authentication, CAPTCHAs, paywalls, access controls, or
anti-bot protections. Respect each website's terms, robots guidance
where applicable, rate limits, and API rules. LinkedIn and other
restricted platforms must not be accessed through unauthorized scraping.
Preserve direct links so users can apply on the source site.

Every normalized job should include source ID, source URL, canonical
URL, title, company, location, work mode, description, requirements,
posted date if available, first-seen timestamp, last-verified timestamp,
expiry/closed status, and raw-source reference.

## Matching model

Keep three separate outputs:

-   **Eligibility:** mandatory conditions satisfied / not satisfied /
    unknown.
-   **Profile fit:** evidence-based similarity across skills,
    experience, projects, education, and domain.
-   **Application priority:** fit plus freshness, urgency, preference
    alignment, effort, and user-defined goals.

Initial configurable fit weights (starting defaults, not empirically
validated): - Technical skills: 25% - Experience/seniority: 20% -
Project relevance: 15% - Education/eligibility: 10% - Domain knowledge:
10% - Role/career alignment: 10% - Location/work preferences: 5% -
Freshness: 5%

Expose evidence and missing requirements beside every score. Do not
label a fit score as a probability of selection. A future outcome model
may be trained only after sufficient, consented, high-quality
application outcome data exists and must be calibrated and evaluated for
bias.

## Resume and application integrity

-   Maintain a canonical master profile and evidence records.
-   Every generated bullet should reference one or more evidence IDs.
-   Preserve original documents and version generated artifacts.
-   Show a diff between original and tailored resume.
-   Validate generated PDF text extraction and layout.
-   Do not fabricate keywords, employment, dates, degrees, publications,
    metrics, or skills.
-   Ask the user for missing personal declarations.
-   Do not guess work authorization, demographic, disability, legal,
    background-check, or consent answers.
-   Autofill is allowed only on supported pages and must stop for user
    review before submission by default.
-   Record the exact resume, answers, destination, timestamp, and user
    approval associated with each application.

## Main product areas

1.  Overview dashboard
2.  My Profile / Career Evidence
3.  Job Discovery
4.  Job Matching
5.  Resume Studio
6.  Application Center
7.  Daily Planner
8.  Learning Studio
9.  Mock Interview Studio
10. Company Research
11. Agent Control Center
12. Workflow Builder
13. Integrations
14. AI Model Manager
15. System Health, Data, Security, and Documentation

## Suggested repository layout

``` text
careerpilot-ai/
  README.md
  LICENSE
  CONTRIBUTING.md
  SECURITY.md
  CHANGELOG.md
  docs/
    PRODUCT_REQUIREMENTS.md
    IMPLEMENTATION_PLAN.md
    ARCHITECTURE.md
    DATA_MODEL.md
    AGENT_DESIGN.md
    JOB_SOURCES_AND_COMPLIANCE.md
    SECURITY_AND_PRIVACY.md
    TEST_STRATEGY.md
    WINDOWS_SETUP.md
    USER_GUIDE.md
    API_REFERENCE.md
    DECISIONS/
  apps/
    web/
  services/
    api/
    worker/
  packages/
    shared-schemas/
    provider-gateway/
    job-connectors/
    resume-engine/
    browser-automation/
    agent-workflows/
  templates/
    latex/
  data/
    .gitkeep
  scripts/
    windows/
  tests/
    unit/
    integration/
    browser/
    evaluation/
  .env.example
  .gitignore
```

Never commit `.env`, API keys, browser profiles, personal resumes,
generated applications, local databases, or logs containing personal
information.

## Development status and realistic expectations

A complete, reliable platform cannot responsibly be delivered as a
single untested code dump. The implementation should be delivered in
vertical slices, each runnable and tested. The first milestone should be
a working local foundation, then profile/resume, job ingestion/matching,
and finally supervised application automation and interview coaching.

See `IMPLEMENTATION_PLAN.md` for phases, acceptance criteria, and a
proposed build order. See `ARCHITECTURE.md` for component boundaries and
workflow design.
