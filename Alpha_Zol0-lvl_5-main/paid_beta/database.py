from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import settings


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


def init_db() -> None:
    from . import economics_models, models  # noqa: F401

    if not settings.is_production:
        Base.metadata.create_all(bind=engine)
        return

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    required = {
        "alembic_version",
        "paid_beta_users",
        "paid_beta_artifacts",
        "paid_beta_artifact_grants",
        "paid_beta_audit_logs",
        "paid_beta_economics_periods",
    }
    missing = sorted(required - tables)
    if missing:
        raise RuntimeError(
            "paid-beta production schema is not migrated: " + ", ".join(missing)
        )
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    if version != "0003_revenue_readiness_gate":
        raise RuntimeError(
            f"paid-beta production schema revision mismatch: {version!r}"
        )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
