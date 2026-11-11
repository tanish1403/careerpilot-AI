"""Feature registry: the UI/README read real status from here.
Lanes set their feature to IMPLEMENTED only when acceptance tests pass."""
from .enums import FeatureStatus as S

# IMPLEMENTED = acceptance tests pass. EXPERIMENTAL = built and tested only against mocks/fixtures
# (job_discovery: no live-board runs; agents: linear workflows, no LangGraph; browser_autofill:
# local fixture forms only; interviews/company_research: offline/deterministic paths tested).
FEATURES: dict[str, dict] = {
    "profile": {"status": S.IMPLEMENTED, "label": "Profile & evidence"},
    "document_ingestion": {"status": S.IMPLEMENTED, "label": "Document ingestion"},
    "resume_studio": {"status": S.IMPLEMENTED, "label": "Resume Studio"},
    "job_discovery": {"status": S.EXPERIMENTAL, "label": "Job discovery"},
    "matching": {"status": S.IMPLEMENTED, "label": "Job matching"},
    "providers": {"status": S.IMPLEMENTED, "label": "AI model manager"},
    "agents": {"status": S.EXPERIMENTAL, "label": "Agents & workflows"},
    "applications": {"status": S.IMPLEMENTED, "label": "Application center"},
    "browser_autofill": {"status": S.EXPERIMENTAL, "label": "Supervised autofill"},
    "learning": {"status": S.IMPLEMENTED, "label": "Learning Studio"},
    "interviews": {"status": S.EXPERIMENTAL, "label": "Mock interviews"},
    "company_research": {"status": S.EXPERIMENTAL, "label": "Company research"},
    "scheduler": {"status": S.IMPLEMENTED, "label": "Scheduler & digest"},
    "system": {"status": S.IMPLEMENTED, "label": "System health & backup"},
}
