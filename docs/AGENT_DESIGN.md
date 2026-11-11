# Agent design (as implemented)

Eight agents in `agent_workflows/agents.py`: `profile`, `job_discovery`, `matching`, `resume`, `application`,
`interview`, `study_planner`, `research`. Status: **experimental** (tested with mocked providers).

- **Engine:** small persistent linear step runner, not LangGraph (the package is installed but unused: its
  checkpointers do not map onto the `Checkpoint` table). Steps are `agent` or `approval`; inputs can reference
  `$.inputs.x` and `$.steps.<id>.<field>`; per-step retries and checkpoints; approval nodes pause the run and
  resume from the database. No branching. Runs execute in-process; a crash mid-step leaves the run `running`.
- **Permissions:** every step gets a `ToolGrant` (frozen, default empty). `ToolBroker` denies ungranted tool calls
  (`PermissionError`, audited `tool.denied`). Grants come from workflow/supervisor policy, never from model or job text.
- **Untrusted content:** job descriptions and documents are wrapped with `wrap_untrusted` (closing-tag escapes
  neutralised) and scanned for injection phrases; flags are stored on the job.
- **Structured output:** schema instruction plus jsonschema validation on every model including fallbacks; one corrective re-ask per model.
- **Consent and cost:** `sensitive` agents (profile) skip non-local providers unless Setting `allow_external_llm`
  is true. Unknown model price gives `cost_usd = null`; budgets per agent and per run.
- **Mock mode:** deterministic outputs without any provider, used by tests.
- **Cannot do:** submit applications (no tool exists for it), edit consent or allowlist settings.
