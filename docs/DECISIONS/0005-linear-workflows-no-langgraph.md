# ADR 0005: Own linear workflow runner instead of LangGraph

Status: accepted (2026-11-11)

## Context and decision
LangGraph checkpointers do not map to the `Checkpoint` table without a custom saver. A small persistent runner provides checkpoints, retries, approval interrupts, resume from DB.

## Consequences
Less dependency surface; no branching. Agents stay experimental.
