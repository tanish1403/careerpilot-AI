# Contributing

## Setup
- Linux/macOS: `python -m venv .venv && .venv/bin/pip install -e "services/api[dev]"`, then `cd apps/web && npm ci`.
- Windows (CMD, no WSL): `scripts\windows\setup.cmd` (untested on real Windows so far; please report issues).
- Run: `python scripts/dev.py` (API on 127.0.0.1:8000, Vite on 5173).

## Checks (CI runs the same)
- `cd services/api && ../../.venv/bin/python -m pytest -q tests`
- `ruff check --isolated --select E9,F63,F7,F82 services/api scripts tests` (blocking; full `ruff check` still reports many style findings)
- `cd apps/web && npm run lint && npm run typecheck && npm test && npm run build`
- `python scripts/scan_secrets.py`
- Regenerate docs after route or model changes: `python scripts/gen_api_reference.py`,
  `python scripts/gen_data_model.py` (the contract report is rewritten by the h_safety test).

## Rules
- Tests use mocked HTTP; no live network, no real resumes or keys.
- Schema changes need a new Alembic revision; do not edit `0001`.
- Never log or return secrets; wrap untrusted text with `core.untrusted.wrap_untrusted`.
- Nothing may set an application to `Submitted` except the confirm-submitted flow (a test enforces this).
- Be honest in docs: status claims must match `core/features.py`.
- Sign-off: contributions are accepted under Apache-2.0.
