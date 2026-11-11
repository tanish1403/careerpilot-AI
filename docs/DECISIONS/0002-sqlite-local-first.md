# ADR 0002: SQLite with Alembic, soft deletes

Status: accepted (2026-11-11)

## Context and decision
SQLite file in `data/`; models carry `workspace_id` and `deleted_at`; schema via Alembic `0001`, later lanes add revisions rather than editing it.

## Consequences
Zero-setup local storage and easy backup. Cost: single-writer, no Postgres testing.
