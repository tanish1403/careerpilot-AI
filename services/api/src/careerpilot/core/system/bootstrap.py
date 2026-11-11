"""Safe schema bootstrap: the `alembic upgrade head` equivalent run at app start."""
import logging
from pathlib import Path

from sqlalchemy import inspect

from ...db.session import get_engine

log = logging.getLogger("careerpilot.bootstrap")


def _api_root() -> Path:
    # .../services/api/src/careerpilot/core/system/bootstrap.py -> services/api
    return Path(__file__).resolve().parents[4]


def _alembic_config():
    from alembic.config import Config
    root = _api_root()
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    return cfg


def ensure_schema() -> str:
    """Bring the DB to head. Returns 'upgraded' | 'stamped' | 'error'. Never raises.

    - fresh DB: run migrations
    - tables exist but no alembic_version (created via metadata): stamp head
    - otherwise: upgrade head
    """
    from alembic import command
    from ...core.config import get_settings
    try:
        names = set(inspect(get_engine()).get_table_names())
        cfg = _alembic_config()
        cfg.set_main_option("sqlalchemy.url", get_settings().db_url.replace("%", "%%"))
        if "alembic_version" not in names and "users" in names:
            command.stamp(cfg, "heads")
            return "stamped"
        command.upgrade(cfg, "heads")
        return "upgraded"
    except Exception:  # noqa: BLE001
        log.exception("schema bootstrap failed")
        return "error"


def current_revision() -> str | None:
    from sqlalchemy import text
    try:
        with get_engine().connect() as c:
            row = c.execute(text("select version_num from alembic_version")).first()
            return row[0] if row else None
    except Exception:  # noqa: BLE001
        return None


def startup(app=None) -> None:  # noqa: ANN001
    ensure_schema()


def register() -> None:
    """Idempotently append the startup hook to the app factory's hook list."""
    from ...api import app as app_module
    if startup not in app_module.STARTUP_HOOKS:
        app_module.STARTUP_HOOKS.insert(0, startup)
