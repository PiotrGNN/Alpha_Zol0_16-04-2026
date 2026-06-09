from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_or_file(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is not None:
        return value.strip()
    file_path = os.getenv(f"{name}_FILE", "").strip()
    if not file_path:
        return default
    path = Path(file_path)
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"unable to read secret file for {name}") from exc


@dataclass(frozen=True)
class Settings:
    environment: str = os.getenv("PAID_BETA_ENV", "development").strip().lower()
    database_url: str = _env_or_file("PAID_BETA_DATABASE_URL", "sqlite:///./paid_beta.db")
    token_secret: str = _env_or_file("PAID_BETA_TOKEN_SECRET")
    token_ttl_seconds: int = int(os.getenv("PAID_BETA_TOKEN_TTL_SECONDS", "86400"))
    password_reset_ttl_seconds: int = int(
        os.getenv("PAID_BETA_PASSWORD_RESET_TTL_SECONDS", "1800")
    )
    expose_password_reset_token: bool = _bool_env(
        "PAID_BETA_EXPOSE_PASSWORD_RESET_TOKEN", False
    )
    app_url: str = os.getenv("PAID_BETA_APP_URL", "http://localhost:8080")
    cors_origins: tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.getenv("PAID_BETA_CORS_ORIGINS", "http://localhost:8080").split(",")
        if origin.strip()
    )
    stripe_secret_key: str = _env_or_file("STRIPE_SECRET_KEY")
    stripe_webhook_secret: str = _env_or_file("STRIPE_WEBHOOK_SECRET")
    stripe_price_starter: str = os.getenv("STRIPE_PRICE_STARTER", "")
    stripe_price_pro: str = os.getenv("STRIPE_PRICE_PRO", "")
    stripe_price_report: str = os.getenv("STRIPE_PRICE_REPORT", "")
    bootstrap_admin_email: str = os.getenv(
        "PAID_BETA_BOOTSTRAP_ADMIN_EMAIL", ""
    ).strip().lower()
    bootstrap_admin_secret: str = _env_or_file("PAID_BETA_ADMIN_BOOTSTRAP_SECRET")
    allow_admin_bootstrap: bool = _bool_env("PAID_BETA_ALLOW_ADMIN_BOOTSTRAP", True)
    rate_limit_window_seconds: int = int(
        os.getenv("PAID_BETA_RATE_LIMIT_WINDOW_SECONDS", "60")
    )
    rate_limit_auth_requests: int = int(
        os.getenv("PAID_BETA_RATE_LIMIT_AUTH_REQUESTS", "20")
    )
    rate_limit_checkout_requests: int = int(
        os.getenv("PAID_BETA_RATE_LIMIT_CHECKOUT_REQUESTS", "10")
    )
    smtp_host: str = os.getenv("PAID_BETA_SMTP_HOST", "")
    smtp_port: int = int(os.getenv("PAID_BETA_SMTP_PORT", "587"))
    smtp_username: str = os.getenv("PAID_BETA_SMTP_USERNAME", "")
    smtp_password: str = _env_or_file("PAID_BETA_SMTP_PASSWORD")
    smtp_from: str = os.getenv("PAID_BETA_SMTP_FROM", "")
    smtp_starttls: bool = _bool_env("PAID_BETA_SMTP_STARTTLS", True)
    trading_scorecard_path: str = os.getenv(
        "PAID_BETA_TRADING_SCORECARD_PATH",
        "analysis/zol0_profitability_audit_scorecard.json",
    )
    terms_approved: bool = _bool_env("PAID_BETA_TERMS_APPROVED", False)
    privacy_approved: bool = _bool_env("PAID_BETA_PRIVACY_APPROVED", False)
    refunds_approved: bool = _bool_env("PAID_BETA_REFUNDS_APPROVED", False)
    risk_disclosure_approved: bool = _bool_env(
        "PAID_BETA_RISK_DISCLOSURE_APPROVED", False
    )

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def legal_approved(self) -> bool:
        return all(
            (
                self.terms_approved,
                self.privacy_approved,
                self.refunds_approved,
                self.risk_disclosure_approved,
            )
        )

    def validate_runtime(self) -> None:
        if not self.token_secret or len(self.token_secret) < 32:
            raise RuntimeError("PAID_BETA_TOKEN_SECRET must contain at least 32 characters")
        if self.token_ttl_seconds <= 0 or self.password_reset_ttl_seconds <= 0:
            raise RuntimeError("paid-beta token TTL values must be positive")
        if self.expose_password_reset_token and self.is_production:
            raise RuntimeError(
                "PAID_BETA_EXPOSE_PASSWORD_RESET_TOKEN is forbidden in production"
            )
        if self.is_production:
            if not self.database_url.startswith(("postgresql://", "postgresql+")):
                raise RuntimeError("production paid-beta database must be PostgreSQL")
            required = {
                "STRIPE_SECRET_KEY": self.stripe_secret_key,
                "STRIPE_WEBHOOK_SECRET": self.stripe_webhook_secret,
                "STRIPE_PRICE_STARTER": self.stripe_price_starter,
                "STRIPE_PRICE_PRO": self.stripe_price_pro,
                "STRIPE_PRICE_REPORT": self.stripe_price_report,
                "PAID_BETA_SMTP_HOST": self.smtp_host,
                "PAID_BETA_SMTP_FROM": self.smtp_from,
            }
            missing = sorted(name for name, value in required.items() if not value)
            if missing:
                raise RuntimeError(
                    "missing production paid-beta settings: " + ", ".join(missing)
                )
            if not self.app_url.startswith("https://"):
                raise RuntimeError("production PAID_BETA_APP_URL must use HTTPS")
            if any("localhost" in origin or "127.0.0.1" in origin for origin in self.cors_origins):
                raise RuntimeError("production CORS origins cannot use localhost")
            if not self.legal_approved:
                raise RuntimeError(
                    "production paid-beta legal approvals are incomplete"
                )


settings = Settings()
