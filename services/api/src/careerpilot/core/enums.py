"""Shared enums - the single source of truth for states used across lanes."""
from enum import Enum


class StrEnum(str, Enum):
    def __str__(self) -> str:  # pragma: no cover
        return self.value


class VerificationStatus(StrEnum):
    PROPOSED = "proposed"      # extracted/generated, NOT verified
    CONFIRMED = "confirmed"    # user confirmed
    REJECTED = "rejected"


class TriState(StrEnum):
    SATISFIED = "satisfied"
    NOT_SATISFIED = "not_satisfied"
    UNKNOWN = "unknown"        # unknown is never treated as satisfied


class ApplicationState(StrEnum):
    DISCOVERED = "Discovered"
    ANALYZED = "Analyzed"
    SHORTLISTED = "Shortlisted"
    REJECTED = "Rejected"
    RESUME_PREPARED = "ResumePrepared"
    REVIEW_REQUIRED = "ReviewRequired"
    NEEDS_EDIT = "NeedsEdit"
    APPROVED = "Approved"
    AUTOFILL_IN_PROGRESS = "AutofillInProgress"
    USER_SUBMISSION_REVIEW = "UserSubmissionReview"
    BLOCKED = "Blocked"
    SUBMITTED = "Submitted"
    CANCELLED = "Cancelled"
    ASSESSMENT = "Assessment"
    INTERVIEW = "Interview"
    OFFER = "Offer"


# Allowed transitions, copied from ARCHITECTURE.md section 4.
A = ApplicationState
TRANSITIONS: dict[ApplicationState, set[ApplicationState]] = {
    A.DISCOVERED: {A.ANALYZED},
    A.ANALYZED: {A.SHORTLISTED, A.REJECTED},
    A.SHORTLISTED: {A.RESUME_PREPARED},
    A.RESUME_PREPARED: {A.REVIEW_REQUIRED},
    A.REVIEW_REQUIRED: {A.NEEDS_EDIT, A.APPROVED},
    A.NEEDS_EDIT: {A.RESUME_PREPARED},
    A.APPROVED: {A.AUTOFILL_IN_PROGRESS},
    A.AUTOFILL_IN_PROGRESS: {A.USER_SUBMISSION_REVIEW, A.BLOCKED},
    A.USER_SUBMISSION_REVIEW: {A.SUBMITTED, A.CANCELLED},
    A.SUBMITTED: {A.ASSESSMENT, A.INTERVIEW, A.REJECTED},
    A.INTERVIEW: {A.OFFER, A.REJECTED},
    A.BLOCKED: set(), A.CANCELLED: set(), A.REJECTED: set(),
    A.ASSESSMENT: {A.INTERVIEW, A.REJECTED}, A.OFFER: set(),
}


def can_transition(src: ApplicationState, dst: ApplicationState) -> bool:
    return dst in TRANSITIONS.get(src, set())


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"            # waiting for human approval
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"            # expired: marked, never silently deleted
    UNKNOWN = "unknown"


class WorkMode(StrEnum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNKNOWN = "unknown"


class FeatureStatus(StrEnum):
    IMPLEMENTED = "implemented"
    EXPERIMENTAL = "experimental"
    PLANNED = "planned"
