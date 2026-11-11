# Architecture

One Python package (`services/api/src/careerpilot`) served by FastAPI; one React/Vite SPA (`apps/web`).
The blueprint's separate `worker` and `shared_schemas` services were not built: background work runs in-process
(FastAPI `BackgroundTasks` and APScheduler). `packages/shared-schemas` is a placeholder.

```
Browser (React SPA) --HTTP/JSON, Bearer token--> FastAPI (api/app.py, routes mounted at /api/v1)
   routes -> domain modules -> SQLAlchemy -> SQLite (data/careerpilot.db), files in data/{uploads,artifacts,backups}
```

## Modules
| Package | Role |
|---|---|
| `api/` | App factory, CORS, routers (auto-mounted), auth dependency |
| `core/` | config, auth (PBKDF2 + HMAC token), secrets (Fernet), audit, redaction, untrusted-text wrapper, enums/state machine, feature registry, `system/` (bootstrap, runs, backup) |
| `db/` | SQLAlchemy models (44 tables, soft delete, workspace id), Alembic `0001` |
| `documents/` | Upload validation, parsers, fact extraction, profile service |
| `resume_engine/` | Resume generation, claim mapping, LaTeX safety scan and compile (LaTeX templates in `/templates`) |
| `job_connectors/` | Greenhouse, Lever, Ashby, career-page, URL import, optional jobspy adapter, URL policy, normalization, dedupe |
| `matching/` | Taxonomy, eligibility, fit/priority scoring, config |
| `provider_gateway/` | Adapters (openai-compatible, ollama, anthropic), routing, retries, fallback, budgets, consent |
| `agent_workflows/` | 8 agents, supervisor with per-step tool grants, tool broker, persistent linear runner, mock mode |
| `applications/` | Application service, answer classifier, submit approval/confirm flow |
| `browser_automation/` | Playwright sessions, allowlist, blocker detection, redirect vetting |
| `learning/`, `interviews/`, `research/`, `scheduler/` | Study plans, mock interviews, company briefs, scheduled tasks and digest |

## Key flows
- **Evidence:** upload -> parse run -> `proposed` facts -> user confirms -> typed rows -> resume claims reference fact ids.
- **Application:** `Discovered -> Analyzed -> Shortlisted -> ResumePrepared -> ReviewRequired -> Approved -> AutofillInProgress -> UserSubmissionReview -> Submitted`.
  `Approved` is reachable only via `approve-resume`; `Submitted` only via `confirm-submitted` after a `granted` submit approval whose snapshot fingerprint still matches.
  `Blocked`, `Cancelled`, `Rejected`, `Offer` are terminal (see KNOWN_ISSUES).
- **Long-running work** returns 202 with a `run_id` polled at `GET /runs/{id}`.

See `docs/DATA_MODEL.md` and `docs/API_REFERENCE.md` (generated) and `docs/DECISIONS/`.
