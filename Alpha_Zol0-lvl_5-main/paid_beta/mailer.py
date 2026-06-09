from __future__ import annotations

import smtplib
from email.message import EmailMessage

from .config import settings


def send_password_reset(*, email: str, reset_url: str) -> None:
    if not settings.smtp_host or not settings.smtp_from:
        if settings.is_production:
            raise RuntimeError("password reset email delivery is not configured")
        return

    message = EmailMessage()
    message["Subject"] = "ZoL0 Analytics password reset"
    message["From"] = settings.smtp_from
    message["To"] = email
    message.set_content(
        "A password reset was requested for your ZoL0 Analytics account.\n\n"
        f"Reset link: {reset_url}\n\n"
        "If you did not request this reset, ignore this message."
    )

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as client:
        if settings.smtp_starttls:
            client.starttls()
        if settings.smtp_username:
            client.login(settings.smtp_username, settings.smtp_password)
        client.send_message(message)
