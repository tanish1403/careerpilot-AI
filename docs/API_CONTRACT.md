# API Contract (v1) - agreed shapes for parallel lanes

Base `/api/v1`. JSON. Auth: `Authorization: Bearer <token>` on everything except
`/health`, `/ready`, `/features`, `/auth/*`. Errors: `{"detail": "..."}` with 4xx/5xx.
Lists: `{"items": [...], "total": n}` and query `limit` (default 50), `offset`.
Long-running work returns `202 {"run_id": "...", "status": "pending"}`; poll `GET /runs/{run_id}`
-> `{id, status, agent, error, output_refs, usage, provider_meta, started_at, finished_at}`.
IDs are 32-char hex strings. Timestamps ISO-8601 UTC. **No endpoint ever returns a secret value**
(providers expose `has_secret: bool` only).

## Lane A - core/system
- `POST /auth/setup {username,password}` (only when no user exists) -> `{token}`
- `POST /auth/login {username,password}` -> `{token}`; `GET /auth/me` -> `{username, setup_required}`; `GET /auth/status` (public) -> `{setup_required}`
- `GET /settings` -> `{key: value}`; `PUT /settings/{key} {value}`
- `GET /system/diagnostics` -> `{version, python, db:{ok,size_bytes,migration}, disk_free_bytes, tools:{xelatex,tesseract,playwright,ollama}, scheduler:{running}}`
- `GET /system/logs?limit=` -> `{items:[AuditEvent]}`; `GET /system/events` same shape (task/event log)
- `POST /system/backup` -> `{filename, size_bytes}`; `GET /system/backups`; `POST /system/restore {filename}`; `GET /system/backups/{filename}` download
- `GET /system/export` -> zip (all user data as JSON, secrets excluded); `DELETE /system/data {confirm:"DELETE"}`
- `GET /runs/{id}`; `GET /runs?status=&limit=`
- `GET /notifications`; `POST /notifications/{id}/read`
- `GET /dashboard` -> `{counts:{jobs,new_jobs,applications,by_state:{},shortlisted}, upcoming:[...], recent_events:[...], top_matches:[...], feature_status:{}}`

## Lane B - profile / documents / resume
- `GET/PUT /profiles/current` -> CandidateProfile `{id, full_name, headline, email, phone, location, links, summary, preferences, version, completeness:{score, missing:[...]}, contradictions:[{kind, detail, fact_ids}]}`
- `GET /profiles/current/export` (JSON), `POST /profiles/import`
- CRUD (verified-status aware) `/experiences /education /skills /projects /publications /certifications` -> each item has `status` (proposed|confirmed|rejected) and `fact_id`
- `GET /facts?status=&category=`; `POST /facts/{id}/confirm|reject`; `PATCH /facts/{id} {value}` (edit sets status=confirmed only on explicit `confirm:true`)
- `POST /documents` multipart(file, kind) -> `{document, parse_run}` ; unsupported/corrupt -> 422 `{detail, code:"unsupported_type"|"corrupt_file"|"empty_file"}`
- `GET /documents`; `GET /documents/{id}`; `GET /documents/{id}/download`; `GET /documents/{id}/parse-runs`; `POST /documents/{id}/parse`; `GET /parse-runs/{id}` -> `{status, parser, warnings, facts:[ProfileFact]}`
- `GET /resumes?job_id=`; `POST /resumes/generate {job_id?, job_description?, template_id?, label?}` -> ResumeVersion `{id, version_no, label, latex_source, pdf_available, validation_report, claims:[{id,text,evidence_ids,needs_confirmation}]}`
- `GET /resumes/{id}`; `PUT /resumes/{id}/source {latex_source}` (creates new version); `POST /resumes/{id}/compile`; `GET /resumes/{id}/pdf`; `GET /resumes/{id}/tex`
- `GET /resumes/{id}/diff?against=<id|original>` -> `{hunks:[{op,text}], summary}`; `POST /resumes/{id}/restore`
- `POST /resumes/{id}/claims/{claim_id}/confirm`; `GET /resume-templates`
- `POST /cover-letters/generate {job_id, resume_id?}` -> `{text, claims:[...], needs_confirmation:[...]}`

## Lane C - jobs / matching
- `GET/POST/PATCH/DELETE /sources` (kind, name, config, enabled, rate_limit_per_min); `GET /sources/kinds` -> `[{kind, permitted_usage, config_schema}]`
- `POST /sources/{id}/test`; `POST /sources/{id}/run` -> 202 run; `GET /sources/{id}/health`; `GET /ingestion-logs`
- `POST /jobs/import-url {url}` ; `POST /jobs/import-text {title, company, description, url?}`
- `GET /jobs?q=&status=&source_kind=&work_mode=&location=&seniority=&posted_within_days=&new_only=&saved=&min_fit=&sort=priority|posted|fit&limit&offset` -> items `{id,title,company_name,location,work_mode,posted_at,first_seen_at,last_verified_at,status,saved,sources:[{kind,url}],match:{eligibility,fit_score,priority_score}|null}`
- `GET /jobs/{id}` -> job + `requirements`, `source_records`, `match`, `injection_flags`; `POST /jobs/{id}/save|unsave`; `POST /jobs/{id}/verify` (re-check source link)
- `POST /matches/score {job_ids?|all:true}` -> 202 run; `GET /matches?job_id=`; `GET /matches/{id}` -> `{eligibility, eligibility_details:[{requirement, state, evidence}], fit_score, priority_score, factors:{name:{weight,score,contribution,evidence:[...]}}, missing:[...], disclaimer}`
- `POST /matches/{id}/feedback {relevant?, action?, reason?}`
- `GET/PUT /matching/config` -> `{weights:{technical_skills:.25,experience:.20,projects:.15,education:.10,domain:.10,role_alignment:.10,location:.05,freshness:.05}, version}` (weights must sum to 1)
- `GET /matching/preferences-filters`

## Lane D - providers / agents / workflows
- `GET/POST /providers`; `GET/PATCH/DELETE /providers/{id}`; body `{display_name, protocol, base_url, api_key? (write-only), enabled, timeout_s, max_retries}`; response has `has_secret`, never the key
- `GET /providers/presets` -> OmniRoute, OpenRouter, FreeLLMAPI, Ollama, Anthropic, OpenAI, Gemini, Groq, Together, DeepSeek, Mistral, LM Studio, vLLM, custom (user-editable defaults, NOT hardcoded assumptions)
- `POST /providers/{id}/test` -> `{ok, latency_ms, detail}`; `POST /providers/{id}/discover` -> models; `GET /models`; `PATCH /models/{id}` (capabilities, enabled)
- `GET /usage?run_id=&from=&to=` -> tokens/cost aggregates
- `GET/PUT /agents` , `GET/PUT /agents/{name}/config {enabled, primary_model_id, fallback_model_ids, budget_usd}`; `POST /agents/{name}/run {input}` -> 202 run; `POST /runs/{id}/pause|resume|cancel`
- `GET/POST /workflows`; `POST /workflows/{id}/run` -> 202; `GET /workflow-runs/{id}` (+ `/checkpoints`); `POST /workflow-runs/{id}/approve {approve: bool, comment?}`
- `GET /approvals?status=pending`; `POST /approvals/{id}/decide {grant: bool}`

## Lane E - applications / automation
- `GET /applications?state=` ; `POST /applications {job_id}` (idempotent per job) ; `GET /applications/{id}` -> `{..., job, resume_version, answers, events, allowed_transitions, blockers}`
- `POST /applications/{id}/transition {to_state, note?}` (validated by `can_transition`; 409 on illegal; reaching `Submitted` only via submit approval)
- `GET /applications/kanban` -> `{columns:[{state, items:[...]}]}`
- `POST /applications/{id}/prepare` -> 202 run (resume + drafted answers); `GET/PUT /applications/{id}/answers`; `POST /answers/{id}/confirm`
- `POST /applications/{id}/approve-resume {resume_version_id}`
- `POST /automation/sessions {application_id}` (explicit, user-started; domain must be allowlisted) ; `GET /automation/sessions/{id}`; `POST /automation/sessions/{id}/fill-preview` -> `{fields:[{label, proposed_value, source, status:ok|needs_user|sensitive|unsupported}], blockers:[]}`
- `POST /automation/sessions/{id}/autofill`; `POST /automation/sessions/{id}/stop`
- `POST /applications/{id}/request-submit` -> creates `Approval(kind=submit)` with snapshot; `POST /applications/{id}/confirm-submitted {approval_id, confirmation_ref?}` (manual-submit tracking); there is **no endpoint that submits without a granted submit approval**
- `GET/PUT /automation/allowlist`; `GET /automation/adapters`

## Lane F - learning / interviews / research / scheduler
- `GET/POST /study-plans`; `POST /study-plans/generate {tracks[], hours_per_week, job_ids?}`; `GET/PATCH/DELETE /study-plans/{id}`; tasks `GET/POST /study-plans/{id}/tasks`, `PATCH /study-tasks/{id}`; `GET /study-plans/{id}/export` (markdown); `GET /learning/templates`; `GET/POST /learning/resources`; `GET /learning/skill-gaps` -> `[{skill, jobs:[{id,title}], count}]`; `GET /learning/progress`
- `GET/POST /interviews`; `POST /interview-sessions {kind, job_id?, target_role?}`; `POST /interview-sessions/{id}/answer {text}` -> next question + running notes; `POST /interview-sessions/{id}/finish` -> feedback `{factual_correctness, communication, revision_tasks}`; `GET /interview-sessions`; `GET /interview-sessions/{id}/export`
- `POST /research/company {company, role?, job_id?}` -> 202; `GET /companies`, `GET /companies/{id}` -> brief with `sources:[{url, retrieved_at}]`, `interview_themes` flagged `unverified` when not sourced
- `GET/POST/PATCH /scheduler/tasks`; `POST /scheduler/tasks/{id}/run-now`; `POST /scheduler/pause|resume`; `GET /scheduler/runs`; `GET /scheduler/status`; `GET /digest/latest`; `GET /reports/weekly`

All `/jobs`, `/matches`, etc. collection endpoints are workspace-scoped and ignore soft-deleted rows.
