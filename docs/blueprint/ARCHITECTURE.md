# CareerPilot AI --- Architecture and Agent Design

## 1. Architectural boundaries

Keep the application modular and provider-neutral:

-   `web`: presentation only; never stores provider secrets.
-   `api`: authentication, validation, domain services, API contracts.
-   `worker`: scheduled and long-running jobs.
-   `provider_gateway`: model provider adapters, routing, budgets,
    retries.
-   `job_connectors`: source-specific job ingestion.
-   `resume_engine`: parsing, evidence mapping, LaTeX generation, PDF
    validation.
-   `browser_automation`: supported form adapters and approval gates.
-   `agent_workflows`: typed agents and durable workflow graphs.
-   `shared_schemas`: common Pydantic/TypeScript contracts.

Avoid circular dependencies. Domain services should not import UI code
or specific model vendors.

## 2. High-level flow

``` mermaid
flowchart TD
  UI[React Web UI] --> API[FastAPI]
  API --> DB[(SQLite / PostgreSQL)]
  API --> FILES[Local Document Storage]
  API --> GW[Model Gateway]
  API --> Q[Task Queue / Scheduler]
  Q --> WORKER[Worker]
  WORKER --> CONNECTORS[Job Source Adapters]
  WORKER --> RESUME[Resume Engine]
  WORKER --> AGENTS[Agent Workflows]
  AGENTS --> GW
  AGENTS --> DB
  AGENTS --> APPROVAL[Human Approval Checkpoint]
  APPROVAL --> UI
  AGENTS --> BROWSER[Playwright Supported Adapters]
```

## 3. Agent contracts

Each agent should be a typed service with explicit permissions, not an
unrestricted autonomous process.

### Profile Agent

Input: document ID, parser options. Output: proposed profile facts,
confidence, evidence location, warnings. Permissions: read uploaded
document; propose profile changes. It cannot silently overwrite verified
facts.

### Job Discovery Agent

Input: enabled sources, search criteria, time window. Output: normalized
jobs, source provenance, connector warnings. Permissions: read source
configuration; access only approved connectors; no login bypass.

### Matching Agent

Input: profile version, job version, scoring configuration. Output:
eligibility state, fit score, priority score, factor breakdown, evidence
references. Permissions: read profile and job data; cannot edit profile.

### Resume Agent

Input: job ID, profile version, template ID. Output: resume plan,
evidence-linked claims, LaTeX source, compiled artifact, validation
report. Permissions: read verified profile evidence; create new resume
versions; cannot fabricate or edit source facts.

### Application Agent

Input: application ID, approved resume version, user preferences.
Output: proposed field mapping, drafted answers, autofill report,
blockers. Permissions: access only the approved application session and
selected documents. Submission is a separate gated action.

### Interview Agent

Input: target role/company/JD, interview format, session history.
Output: questions, evaluation rubric, feedback, recommended revision
tasks. Permissions: read selected profile and job data; store session
feedback.

### Study Planner Agent

Input: target tracks, job skill gaps, available time, prior progress.
Output: editable study schedule and resources with source links.
Permissions: read career goals and learning history; create proposed
tasks.

### Research Agent

Input: company and role. Output: sourced company brief, role context,
interview themes, questions to ask. Permissions: public research only;
cite source URLs and retrieval timestamps.

### Supervisor

The Supervisor dispatches tasks and manages workflow state. It should
not receive broad filesystem, database, or browser access. Tools are
granted per workflow step.

## 4. Workflow state machine

``` mermaid
stateDiagram-v2
  [*] --> Discovered
  Discovered --> Analyzed
  Analyzed --> Shortlisted
  Analyzed --> Rejected
  Shortlisted --> ResumePrepared
  ResumePrepared --> ReviewRequired
  ReviewRequired --> NeedsEdit
  NeedsEdit --> ResumePrepared
  ReviewRequired --> Approved
  Approved --> AutofillInProgress
  AutofillInProgress --> UserSubmissionReview
  AutofillInProgress --> Blocked
  UserSubmissionReview --> Submitted
  UserSubmissionReview --> Cancelled
  Submitted --> Assessment
  Submitted --> Interview
  Submitted --> Rejected
  Interview --> Offer
  Interview --> Rejected
```

A workflow run must persist state, inputs, output references,
model/provider metadata, timestamps, retries, approval actor, and error
details. Use idempotency keys for ingestion and application actions.

## 5. Model gateway contract

Define a provider-neutral interface:

-   `list_models(provider_profile)`
-   `test_connection(provider_profile)`
-   `generate(request, task_policy)`
-   `embed(request, task_policy)` (optional capability)
-   `health(provider_profile)`
-   `usage(run_id)`

A model capability record should include: chat, structured output, tool
calling, vision, embeddings, context length if known, streaming, and
provider protocol. Treat capabilities as declared/verified metadata, not
assumptions based only on model name.

Routing policy can consider task type, capability, user preference, cost
ceiling, latency, and availability. Fallbacks must preserve the same
structured output contract and record when a fallback was used.

## 6. Browser automation safety boundary

-   Browser automation is initiated by a user or an explicitly
    configured workflow.
-   Maintain per-site adapters and an allowlist.
-   Use visible browser mode during initial development and debugging.
-   Inspect accessible labels and form semantics before selectors.
-   Never evade CAPTCHA, MFA, authentication, access controls, or
    anti-bot measures.
-   Stop if the form is ambiguous or asks for unsupported/sensitive
    declarations.
-   Never click final submit without a separate explicit approval.
-   Capture a review snapshot and field-value summary before submission.
-   Record confirmation URL/reference after successful submission.
-   Protect cookies and browser profiles as secrets.

## 7. Prompt-injection and untrusted data

Job descriptions, company pages, uploaded documents, and form text are
untrusted data. They must never be interpreted as instructions to the
agent. Tool permissions come from application policy, not retrieved
content. Use structured extraction, content boundaries, output
validation, and allowlisted tools.

## 8. Observability

Each run should record: - Run ID and parent workflow ID - Agent and
version - Provider/model and fallback - Start/end time and status -
Token/cost metadata where available - Input/output schema version -
Source/document/job IDs - Retry count - Approval checkpoints - Redacted
error details

Do not log raw resumes, API keys, passwords, cookies, or complete
application forms by default.
