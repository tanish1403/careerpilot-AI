# Lane C notes (job connectors, normalization, matching)

Deviations / additions to API_CONTRACT (all additive):
- `GET /jobs` defaults to `status=open` (`status=any` for all); extra filters `role`, `min_salary`; "new" = first seen in the last 3 days.
- `POST /jobs/import-url` is synchronous (201); refusals return 422 `{detail, code, apply_url}` (`refused_domain|robots|login_wall|invalid_url`).
- `GET/PUT /matching/config` also carries `priority_weights` (sum to 1); `version` is a hash of weights+priority weights+algorithm+taxonomy version.
- Scores: fit/priority are 0-100; factor `score` is 0-1, `contribution` = weight*score*100. Insufficient job-side data scores a flagged neutral 0.5; missing profile evidence scores 0.
- Priority = weighted (fit, freshness, urgency, preference alignment, effort, goals), x0.5 if eligibility not satisfied, x0.9 if unknown, x0.1 if closed.
- Reproducibility: MatchResult reused for same profile_version + profile content hash + job_version + config_version on the same UTC day (`as_of` stored; freshness depends on it).
- Closed detection: only when `ConnectorResult.complete`; a job closes when every source record is missing from a complete listing of its own source (missing marker in `JobSourceRecord.raw["_cp"]`); manual/URL-imported records never auto-close. No migrations added.
- Runs use `core/system/runs.py` (`start_run/mark_running/finish_run/fail_run`) via FastAPI BackgroundTasks.
- Scheduler entry points: `job_connectors.service.run_source(db, source_id)`, `run_all_sources(db)`, `matching.service.score_all(db)`.
