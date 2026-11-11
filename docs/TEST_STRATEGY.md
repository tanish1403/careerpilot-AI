# Test strategy

| Layer | Where | Notes |
|---|---|---|
| Backend unit/integration | `services/api/tests/{unit,integration}` (543 passing at last run, ~2 min) | In-memory/temp SQLite; mocked HTTP (`httpx.MockTransport`); no live network |
| Match evaluation | `tests/evaluation/c_match_eval*.py` | Fixture-based regression of scoring |
| Cross-cutting safety (Lane H) | `tests/integration/h_safety_test.py` | Key non-disclosure over every GET route and logs; submit gate (static + routes + behaviour); contract coverage; injection isolation |
| End-to-end API | `tests/integration/i_e2e_test.py` | Integrated flow |
| Frontend | `apps/web` vitest + eslint + tsc | `npm run lint|typecheck|test|build` |
| Browser smoke | `tests/browser/h_e2e_smoke.py` | Playwright: temp data dir, health, setup, login, dashboard; set `CP_E2E_UI=1` to also load the Vite shell |
| Secret scan | `scripts/scan_secrets.py` | Key patterns and forbidden file types over non-ignored files |

Contract coverage is written to `docs/CONTRACT_COVERAGE.md` by the safety test; it fails only if one of an allowlist of safety-critical routes disappears.
Lint: blocking ruff gate is syntax/undefined-name only (full default rules report ~600 style findings). Audits (`pip-audit`, `npm audit`) are non-blocking.

Not covered: real Windows, live job boards, real ATS forms, real LLM providers, accessibility audit, load testing.
