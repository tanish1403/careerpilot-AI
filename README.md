# CareerPilot AI

Local-first, human-controlled career assistant: profile and evidence library, resume tailoring, job matching,
application tracking, and supervised form autofill. Single user, runs on your machine, SQLite storage,
cloud LLMs optional (off by default; local Ollama supported).

> Early software (v0.1, untagged). It has only been exercised by automated tests on Linux. It never submits an
> application for you: final submission is always a manual step you confirm.

## Status

The source of truth is the live registry: `GET http://127.0.0.1:8000/api/v1/features` (from
`services/api/src/careerpilot/core/features.py`). Snapshot:

| Feature | Status | What that means |
|---|---|---|
| Profile and evidence facts | implemented | Facts stay `proposed` until you confirm them |
| Document ingestion | implemented | PDF/DOCX/TXT/MD/RTF/TeX/HTML; OCR needs `tesseract` |
| Resume Studio | implemented | LaTeX source, claim-to-evidence mapping, PDF needs a LaTeX install |
| Job matching | implemented | Eligibility, fit and priority scores with explanations |
| AI model manager | implemented | Provider/model registry, routing, fallback, budgets, consent gate |
| Application center | implemented | State machine, approvals, manual-submit confirmation |
| Learning Studio | implemented | Study plans, DSA/track templates, revisions |
| Scheduler and digest | implemented | In-process APScheduler |
| System health and backup | implemented | Diagnostics, backup/restore, export, delete |
| Job discovery | experimental | Connectors (Greenhouse, Lever, Ashby, career page, URL import) tested with mocks only; no live job-board run has been done |
| Agents and workflows | experimental | Linear step runner with checkpoints; LangGraph is not used |
| Supervised autofill | experimental | Tested against local fixture forms only; no real ATS tested |
| Mock interviews | experimental | Offline/deterministic paths tested |
| Company research | experimental | Offline/deterministic paths tested |

Match scores are decision support, not predictions of interviews or offers.

## Quickstart

Requires Python 3.11+ and Node 20+ (for the web UI). Optional: `xelatex` (PDF export), `tesseract`
(scanned documents), Playwright Chromium (autofill).

**Windows (CMD, no WSL)** - the `.cmd` scripts have not been run on real Windows yet; please report problems:
```
scripts\windows\setup.cmd
scripts\windows\start.cmd
```
Also `stop.cmd`, `test.cmd`, `backup.cmd`. Details: `docs/WINDOWS_SETUP.md`.

**Linux/macOS**
```
python -m venv .venv
.venv/bin/pip install -e "services/api[dev]"
(cd services/api && ../../.venv/bin/python -m alembic upgrade heads)
(cd apps/web && npm ci)
.venv/bin/python scripts/dev.py          # API :8000, web :5173 ; --api-only, --stop
```
Open http://localhost:5173 and create the single local account on first run.

Copy `.env.example` to `.env` to override settings (all optional). Data lives in `./data` (git-ignored).

## Tests

`cd services/api && ../../.venv/bin/python -m pytest -q tests` (543 tests at last run); web: `npm run lint|typecheck|test|build`
in `apps/web`; browser smoke: `python tests/browser/h_e2e_smoke.py`. See `docs/TEST_STRATEGY.md`.

## Docs

`docs/ARCHITECTURE.md`, `docs/USER_GUIDE.md`, `docs/SECURITY_AND_PRIVACY.md`, `docs/JOB_SOURCES_AND_COMPLIANCE.md`,
`docs/API_REFERENCE.md` (generated), `docs/DATA_MODEL.md` (generated), `docs/DECISIONS/`, `docs/blueprint/`
(original specification, not a description of what is built), `docs/KNOWN_ISSUES.md`.

## License

Apache-2.0 (`LICENSE`, `NOTICE`). One dependency (PyMuPDF) is AGPL-3.0: see `THIRD_PARTY_NOTICES.md`.
