# ADR 0001: Single Python package, in-process background work

Status: accepted (2026-11-11)

## Context and decision
Blueprint proposed separate api/worker/shared-schemas services. We built one `careerpilot` package with FastAPI BackgroundTasks and APScheduler.

## Consequences
Simpler install on Windows, fewer moving parts. Cost: no process isolation, crashes can leave runs `running`, no horizontal scale. Revisit if multi-user is ever needed.
