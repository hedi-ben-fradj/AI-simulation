"""Database engine/session setup and migrations.

PostgreSQL is the authoritative store (``DATABASE_URL=postgresql+psycopg://...``).
SQLite is supported for tests and quick local runs. The schema is managed by
Alembic; ``Database.migrate()`` upgrades to the latest revision.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_URL = "sqlite:///./aisim.db"
# Shipped inside the package so installed (non-editable) deployments can migrate.
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_URL)


class Database:
    def __init__(self, url: str | None = None):
        self.url = url or database_url()
        kwargs: dict = {"future": True, "pool_pre_ping": True}
        if self.url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        else:
            kwargs.update(pool_size=10, max_overflow=10)
        self.engine: Engine = create_engine(self.url, **kwargs)
        if self.url.startswith("sqlite"):
            @event.listens_for(self.engine, "connect")
            def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA synchronous=NORMAL")
                cur.close()
        self.sessions = sessionmaker(self.engine, expire_on_commit=False, future=True)

    @property
    def is_sqlite(self) -> bool:
        return self.url.startswith("sqlite")

    @contextmanager
    def session(self):
        s: Session = self.sessions()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def migrate(self) -> None:
        """Upgrade the schema to the latest Alembic revision."""
        import logging

        from alembic import command
        from alembic.config import Config

        # Alembic logs its plugin setup at INFO; only surface problems.
        logging.getLogger("alembic").setLevel(logging.WARNING)

        cfg = Config()
        cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
        cfg.set_main_option("sqlalchemy.url", self.url.replace("%", "%%"))
        cfg.attributes["connection_engine"] = self.engine
        command.upgrade(cfg, "head")

    def dispose(self) -> None:
        self.engine.dispose()
