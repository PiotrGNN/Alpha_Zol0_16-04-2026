from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text

try:
    # New in SQLAlchemy 1.4+/2.0: declarative_base lives in sqlalchemy.orm
    from sqlalchemy.orm import declarative_base
except Exception:
    # Fallback for older SQLAlchemy
    from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os


def _resolve_database_url() -> str:
    configured = str(os.getenv("DATABASE_URL") or "").strip()
    if configured:
        return configured
    if str(os.getenv("LIVE", "0")).strip() == "1":
        raise RuntimeError(
            "DATABASE_URL is required when LIVE=1; SQLite fallback is disabled "
            "for live runtime."
        )
    return "sqlite:///./zol0.db"


DATABASE_URL = _resolve_database_url()
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
    if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Decision(Base):
    __tablename__ = "decisions"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, nullable=False)
    decision = Column(String(32), nullable=False)
    details = Column(Text)


class Equity(Base):
    __tablename__ = "equity"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, nullable=False)
    equity = Column(Float, nullable=False)
    pnl = Column(Float, nullable=False)


# Model logów do bazy
class LogEntry(Base):
    __tablename__ = "logs"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, nullable=False)
    event = Column(String(64), nullable=False)
    details = Column(Text)


def init_db():
    Base.metadata.create_all(bind=engine)
