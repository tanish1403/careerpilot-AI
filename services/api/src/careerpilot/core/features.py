"""Feature registry: the UI/README read real status from here.
Lanes set their feature to IMPLEMENTED only when acceptance tests pass."""
from .enums import FeatureStatus as S

FEATURES: dict[str, dict] = {
    "profile": {"status": S.EXPERIMENTAL, "label": "Profile & evidence"},
    "document_ingestion": {"status": S.EXPERIMENTAL, "label": "Document ingestion"},
    "resume_studio": {"status": S.EXPERIMENTAL, "label": "Resume Studio"},
    "job_discovery": {"status": S.EXPERIMENTAL, "label": "Job discovery"},
    "matching": {"status": S.EXPERIMENTAL, "label": "Job matching"},
    "providers": {"status": S.EXPERIMENTAL, "label": "AI model manager"},
    "agents": {"status": S.EXPERIMENTAL, "label": "Agents & workflows"},
    "applications": {"status": S.EXPERIMENTAL, "label": "Application center"},
    "browser_autofill": {"status": S.EXPERIMENTAL, "label": "Supervised autofill"},
    "learning": {"status": S.EXPERIMENTAL, "label": "Learning Studio"},
    "interviews": {"status": S.EXPERIMENTAL, "label": "Mock interviews"},
    "company_research": {"status": S.EXPERIMENTAL, "label": "Company research"},
    "scheduler": {"status": S.EXPERIMENTAL, "label": "Scheduler & digest"},
    "system": {"status": S.EXPERIMENTAL, "label": "System health & backup"},
}
