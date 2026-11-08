# Build rules for parallel lanes

1. **Own only your files.** Lane ownership is by directory (see below). Never edit another lane's files,
   `db/models.py`, `core/*`, `api/app.py`, `docs/API_CONTRACT.md`, or `migrations/0001*`.
   If you need a schema change, add a NEW Alembic revision file named `00NN_<lane>_<what>.py`
   (lane A=02xx, B=03xx, C=04xx, D=05xx, E=06xx, F=07xx; set down_revision to "0001" for the first one
   and chain within your own lane) - and ALSO tell the integrator in your final report.
   Prefer storing extra data in existing JSON columns to avoid migrations.
2. Routes: create `api/routes/<your_module>.py` exposing `router = APIRouter()`; app auto-mounts it at /api/v1.
   Use `Depends(current_user)` on every endpoint except the public ones in API_CONTRACT.md. Use `Depends(get_db)`.
3. Follow `docs/API_CONTRACT.md` exactly. If you must deviate, document it in `docs/LANE_<X>_NOTES.md`.
4. Tests: write pytest tests under `services/api/tests/unit|integration/<lane>_*`. Use fixtures from
   `tests/conftest.py` (`db`, `client`). Use mocked HTTP (httpx.MockTransport) - no live network.
   Run with: `cd services/api && ../../.venv/bin/python -m pytest -q tests/<yours>`.
5. Never log/return secrets or raw resumes. Wrap untrusted text with `core.untrusted.wrap_untrusted`.
   Use `core.audit.audit` for audit events (details are auto-redacted).
6. Status honesty: when your lane's acceptance tests pass, set your features to IMPLEMENTED by calling
   nothing - just report; the integrator flips `core/features.py`. Anything untested stays EXPERIMENTAL.
7. Python 3.11+ compatible, type hints, ruff-clean style, line length 100. Windows-safe paths (pathlib).
8. Finish with a short report: what works, tests run + results, known gaps, migrations added.

Lane ownership: A=`api/routes/{auth,settings,system,runs,notifications,dashboard}.py`, `core/*`-adjacent new files under
`core/system/`, `scripts/windows/`; B=`documents/`, `resume_engine/`, `templates/latex/`, routes
`{profile,facts,documents,resumes}.py`; C=`job_connectors/`, `matching/`, routes `{sources,jobs,matches}.py`;
D=`provider_gateway/`, `agent_workflows/`, routes `{providers,agents,workflows,approvals}.py`;
E=`browser_automation/`, `applications/` (new pkg), routes `{applications,automation}.py`;
F=`learning/`, `scheduler/`, routes `{learning,interviews,research,scheduler}.py`;
G (frontend)=`apps/web/`; H=`docs/` (except contract files), `.github/`, `tests/browser`, `tests/evaluation`, root files.
