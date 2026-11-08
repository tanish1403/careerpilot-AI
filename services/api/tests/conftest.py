import os, tempfile
import pytest

_tmp = tempfile.mkdtemp(prefix="cp_test_")
os.environ["CAREERPILOT_DATA_DIR"] = _tmp
os.environ["CAREERPILOT_AUTH_DISABLED_FOR_TESTS"] = "true"
os.environ["CAREERPILOT_SCHEDULER_ENABLED"] = "false"


@pytest.fixture()
def db():
    from careerpilot.db import Base
    from careerpilot.db.session import SessionLocal, get_engine, reset_engine
    reset_engine()
    Base.metadata.drop_all(get_engine())
    Base.metadata.create_all(get_engine())
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture()
def client(db):
    from fastapi.testclient import TestClient
    from careerpilot.api.app import create_app
    with TestClient(create_app()) as c:
        yield c
