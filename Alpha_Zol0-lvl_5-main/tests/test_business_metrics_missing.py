from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from paid_beta.business_metrics import build_business_metrics
from paid_beta.database import Base


def test_missing_history_is_fail_closed():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    result = build_business_metrics(db)
    assert result["closed_beta_ready"] is False
    assert result["scale_ready"] is False
    assert "FOUR_WEEK_HISTORY_MISSING" in result["closed_beta_blockers"]
