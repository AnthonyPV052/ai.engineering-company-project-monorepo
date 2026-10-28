#No funciona aún. Problema con Resend.
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


def send_password_reset_email(*, recipient: str, reset_token: str, expires_at: datetime) -> None:
    api_key = os.getenv("RESEND_API_KEY")
    sender = os.getenv("RESEND_FROM_EMAIL")
    app_base_url = os.getenv("APP_BASE_URL", "http://localhost:3000").rstrip("/")

    if not api_key or not sender:
        raise RuntimeError("RESEND_API_KEY and RESEND_FROM_EMAIL are required to send password reset emails")

    reset_url = f"{app_base_url}/reset-password?token={reset_token}"
    remaining_minutes = max(1, round((expires_at - datetime.now(timezone.utc)).total_seconds() / 60))
    payload = json.dumps(
        {
            "from": sender,
            "to": recipient,
            "subject": "Restablece tu contraseña de Brasaland",
            "html": (
                "<p>Recibimos una solicitud para restablecer tu contraseña.</p>"
                f'<p><a href="{reset_url}">Restablecer contraseña</a></p>'
                f"<p>Este enlace caduca en {remaining_minutes} minutos y solo puede utilizarse una vez.</p>"
            ),
        }
    ).encode("utf-8")
    request = Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=10) as response:
            if response.status not in {200, 201, 202}:
                raise RuntimeError(f"Resend returned an unexpected status: {response.status}")
    except HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")[:500]
        logger.warning("Resend rejected password-reset email with HTTP %s: %s", exc.code, response_body)
        raise RuntimeError("Could not send password reset email") from exc
    except URLError as exc:
        logger.warning("Could not reach Resend while sending password-reset email: %s", exc.reason)
        raise RuntimeError("Could not send password reset email") from exc
