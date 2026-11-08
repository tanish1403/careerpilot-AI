from fastapi import APIRouter
from sqlalchemy import text

from ...core.features import FEATURES
from ...db.session import get_engine

router = APIRouter(tags=["system"])


@router.get("/health")
def health():
    return {"status": "ok", "version": "0.1.0"}


@router.get("/ready")
def ready():
    try:
        with get_engine().connect() as c:
            c.execute(text("select 1"))
        return {"ready": True}
    except Exception as e:  # noqa: BLE001
        return {"ready": False, "detail": type(e).__name__}


@router.get("/features")
def features():
    return {k: {"label": v["label"], "status": str(v["status"])} for k, v in FEATURES.items()}
