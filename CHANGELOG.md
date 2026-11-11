# Changelog

Format: Keep a Changelog. Versioning: 0.x, no stability guarantees.

## [Unreleased]

## [0.1.0] - 2026-11-11 (first integrated build, not yet tagged)

### Added
- FastAPI backend (single `careerpilot` package, SQLite, Alembic `0001`): auth, settings, profile and
  evidence facts, document ingestion, Resume Studio (LaTeX), job connectors, matching, provider gateway,
  agent workflows, applications with submit-approval gate, supervised autofill, learning, scheduler,
  system backup/export.
- React/Vite web UI (15 pages).
- Windows CMD scripts (`scripts/windows/*.cmd`, untested on Windows) and `scripts/dev.py`.
- Cross-cutting safety tests, contract coverage report, generated API reference and data model docs.
- Feature status registry (`GET /api/v1/features`): job discovery, agents, browser autofill, interviews
  and company research are EXPERIMENTAL.
