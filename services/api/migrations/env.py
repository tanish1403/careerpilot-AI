from alembic import context
from careerpilot.core.config import get_settings
from careerpilot.db import Base
from sqlalchemy import create_engine

target_metadata = Base.metadata


def _url():
    return context.config.get_main_option("sqlalchemy.url") or get_settings().db_url


def run_migrations_online():
    engine = create_engine(_url())
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


def run_migrations_offline():
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


run_migrations_offline() if context.is_offline_mode() else run_migrations_online()
