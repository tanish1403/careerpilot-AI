# Lane D notes

## Layout
- `provider_gateway/`: `gateway.py` (routing, retries, fallback, budgets, usage), `adapters.py`
  (openai_compatible, ollama, anthropic; httpx with injectable transport), `hooks.py` (Lane B hooks),
  `deps.py` (test injection of `transport`/`sleep`, `agent_mock_mode`), `presets.py`.
- `agent_workflows/`: 8 agents (`agents.py`), `supervisor.py` (per-step `ToolGrant`), `tools.py`
  (`ToolBroker`; denials raise `PermissionError` and audit `tool.denied`), `runner.py`, `mock.py`.
- Routes: `providers.py`, `agents.py`, `workflows.py`, `approvals.py`, `run_control.py`
  (`POST /runs/{id}/pause|resume|cancel`; Lane A's `runs.py` only has GETs).

## Behaviour
- Routing uses declared/verified `Model.capabilities` only, never model names. Order: AgentConfig
  primary then fallbacks, else all enabled models (verified first, preferred provider first).
- Structured output: schema instruction + jsonschema validation on EVERY model including fallbacks;
  one corrective re-ask per model before failing over. Attempts are scrubbed of keys.
- Consent: `TaskPolicy.sensitive_document` skips non-local providers unless Setting
  `allow_external_llm` is true (else `ConsentRequired`). Local = ollama, `extra.local`, loopback/private
  hosts. Agents with `sensitive=True` (profile) and both Lane B hooks set the flag.
- Cost: Setting `pricing` = `{"<model_id>" or "<provider_id>:<model_id>": {"prompt_per_1k", "completion_per_1k"}}`.
  Unknown price -> `cost_usd = None` (never 0). Budgets: agent `budget_usd` and Setting `run_budget_usd`.
- Lane B hooks are installed when `api/routes/agents.py` is imported (app start), and only if unset. They
  return `None`/raise (rules-only fallback) on refusal, mock mode or provider failure; refusals are audited
  (`llm.consent_refused`).
- Approvals: `POST /approvals/{id}/decide {grant}`. `kind=submit` (subject application) is delegated to
  `applications.service.grant_submit`, so the snapshot-fingerprint check, invalidation and events are
  identical to Lane E's stop-gap `POST /applications/{id}/grant-submit`; both routes work and can
  coexist. `workflow_run` approvals resume the run in a background task. Other kinds just record the decision.

## Deviations / gaps
- Workflow engine is the small persistent step runner (not LangGraph, although `langgraph` is installed):
  LangGraph checkpointers would not map onto the `Checkpoint` table without a custom saver. Semantics are the
  same: per-node checkpoints, interrupt at approval nodes, resume from DB in a new runner instance.
- Workflow definition format: `{"steps": [{"id", "type": "agent"|"approval", "agent", "input" (supports
  "$.inputs.x" / "$.steps.<id>.<field>"), "grants", "retries"}]}`. Linear only (no branching).
- Background execution uses FastAPI `BackgroundTasks` (in-process); no external queue. A crash mid-step
  leaves the run `running`; call `POST /runs/{id}/resume` semantics only cover paused runs.
- Streaming and the `gemini` native protocol are not implemented (Gemini is reachable via its
  OpenAI-compatible endpoint preset). Embeddings: openai_compatible and ollama only.
- Agent tools that call other lanes (matching, resume, connectors, learning) are lazily imported and degrade to
  a warning when the target function is absent.
- No migrations added.
