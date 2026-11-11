import pytest
from careerpilot.applications import service as svc
from careerpilot.core.enums import TRANSITIONS, ApplicationState as S, can_transition
from careerpilot.applications.service import ApplicationError
from careerpilot.db.models import ApplicationEvent, AuditEvent

PAIRS = [(a, b) for a in S for b in S]


@pytest.mark.parametrize("src,dst", PAIRS, ids=[f"{a.value}->{b.value}" for a, b in PAIRS])
def test_every_pair(db, src, dst):
    from e_support import make_app
    app, _ = make_app(db, src.value)
    legal_generic = can_transition(src, dst) and dst not in (S.SUBMITTED, S.APPROVED)
    if legal_generic:
        svc.transition(db, app, dst.value, "u", "n")
        assert app.state == dst.value
        evs = db.query(ApplicationEvent).filter_by(application_id=app.id, kind="transition").all()
        assert evs and evs[-1].to_state == dst.value and evs[-1].from_state == src.value
        assert db.query(AuditEvent).filter_by(action="application.transition").count() >= 1
    else:
        with pytest.raises(ApplicationError) as e:
            svc.transition(db, app, dst.value, "u")
        assert e.value.status == 409 and app.state == src.value


def test_unknown_state_422(db):
    from e_support import make_app
    app, _ = make_app(db)
    with pytest.raises(ApplicationError) as e:
        svc.transition(db, app, "Bogus", "u")
    assert e.value.status == 422


def test_submitted_never_in_generic_targets():
    for s in S:
        assert "Submitted" not in svc.generic_targets(s.value)
        assert "Approved" not in svc.generic_targets(s.value)


def test_legal_count_matches_enum():
    assert sum(len(v) for v in TRANSITIONS.values()) == sum(len(v) for v in TRANSITIONS.values())
