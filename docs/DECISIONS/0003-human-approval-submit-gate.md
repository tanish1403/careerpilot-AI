# ADR 0003: Submission is always manual

Status: accepted (2026-11-11)

## Context and decision
The app never submits. `Approved` only via `approve-resume`; `Submitted` only via `confirm-submitted` after a granted, fingerprint-matched approval. Enforced by a static test and route checks.

## Consequences
Protects the user from silent or mistaken applications. Cost: more clicks. `Blocked` being terminal is an open defect.
