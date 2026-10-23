"""Database engine, session factory, and FastAPI dependency."""

from typing import Generator
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.base import Base
# Import models to ensure they are registered with Base.metadata
from app.db import models  # noqa: F401

# Configure engine
connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    echo=False,
)


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Enforce foreign key constraints on SQLite connections."""
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    except Exception:
        pass


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency providing a transactional SQLAlchemy session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(bind_engine=None) -> None:
    """Create all tables in the configured database and apply self-healing column migrations."""
    target_engine = bind_engine or engine
    Base.metadata.create_all(bind=target_engine)

    # Lightweight self-healing column migration for SQLite
    try:
        with target_engine.connect() as conn:
            cursor = conn.connection.cursor()
            cols = [col[1] for col in cursor.execute("PRAGMA table_info(selections)").fetchall()]
            if cols:
                if "document_id" not in cols:
                    cursor.execute("ALTER TABLE selections ADD COLUMN document_id VARCHAR(36) REFERENCES documents(id)")
                if "description" not in cols:
                    cursor.execute("ALTER TABLE selections ADD COLUMN description TEXT")
                if "metadata_json" not in cols:
                    cursor.execute("ALTER TABLE selections ADD COLUMN metadata_json TEXT")
                if "updated_at" not in cols:
                    cursor.execute("ALTER TABLE selections ADD COLUMN updated_at DATETIME")
                conn.connection.commit()
    except Exception:
        pass


def drop_db(bind_engine=None) -> None:
    """Drop all tables (used for testing)."""
    target_engine = bind_engine or engine
    Base.metadata.drop_all(bind=target_engine)
