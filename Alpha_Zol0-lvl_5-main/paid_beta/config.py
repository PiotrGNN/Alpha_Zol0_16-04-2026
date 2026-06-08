from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("PAID_BETA_DATABASE_URL", "sqlite:///./paid_beta.db")
    token_secret: str = os.getenv("PAID_BETA_TOKEN_SECRET", "")
    token_ttl_seconds: int = int(os.getenv("PAID_BETA_TOKEN_TTL_SECONDS", "86400"))
    app_url: str = os.getenv("PAID_BETA_APP_URL", "http://localhost:5173")
    cors_origins: tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.getenv("PAID_BETA_CORS_ORIGINS", "http://localhost:5173").split(",")
        if origin.strip()
    )
    stripe_secret_key: str = os.getenv("STRIPE_SECRET_KEY", "")
    stripe_webhook_secret: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    stripe_price_starter: str = os.getenv("STRIPE_PRICE_STARTER", "")
    stripe_price_pro: str = os.getenv("STRIPE_PRICE_PRO", "")
    stripe_price_report: str = os.getenv("STRIPE_PRICE_REPORT", "")
    bootstrap_admin_email: str = os.getenv("PAID_BETA_BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()

    def validate_runtime(self) -> None:
        if not self.token_secret or len(self.token_secret) < 32:
            raise RuntimeError("PAID_BETA_TOKEN_SECRET must contain at least 32 characters")


settings = Settings()
