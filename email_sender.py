"""Test-mode email sender for SpecBot.

For demo safety, every email is routed to TEST_EMAIL_RECIPIENT regardless of
the factory contact selected in the UI. The intended recipient is recorded in
the body so the demo audience can see the routing.
"""

from __future__ import annotations

import base64
import mimetypes
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Any


def _build_body(intended_recipient_email: str, body: str) -> str:
    banner = (
        "[SpecBot demo — test-mode email]\n"
        f"Intended recipient (NOT actually emailed): {intended_recipient_email}\n"
        "Routed to: TEST_EMAIL_RECIPIENT\n"
        "----------------------------------------\n\n"
    )
    return banner + (body or "")


def _send_via_smtp(
    to_email: str,
    subject: str,
    body: str,
    attachment_path: str | None,
    from_email: str,
) -> dict[str, Any]:
    host = os.getenv("SMTP_HOST")
    port_str = os.getenv("SMTP_PORT", "587")
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")

    if not host:
        return {"ok": False, "error": "SMTP_HOST not set."}

    try:
        port = int(port_str)
    except ValueError:
        return {"ok": False, "error": f"Invalid SMTP_PORT: {port_str!r}"}

    msg = EmailMessage()
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    if attachment_path:
        path = Path(attachment_path)
        if path.is_file():
            ctype, _ = mimetypes.guess_type(str(path))
            maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
            msg.add_attachment(
                path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name
            )

    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
                if username and password:
                    smtp.login(username, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                smtp.ehlo()
                try:
                    smtp.starttls()
                    smtp.ehlo()
                except smtplib.SMTPNotSupportedError:
                    pass
                if username and password:
                    smtp.login(username, password)
                smtp.send_message(msg)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"SMTP error: {exc}"}

    return {"ok": True, "transport": "smtp", "to": to_email}


def _send_via_resend(
    to_email: str,
    subject: str,
    body: str,
    attachment_path: str | None,
    from_email: str,
) -> dict[str, Any]:
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        return {"ok": False, "error": "RESEND_API_KEY not set."}

    try:
        import requests
    except ImportError:
        return {"ok": False, "error": "requests package not installed."}

    payload: dict[str, Any] = {
        "from": from_email,
        "to": [to_email],
        "subject": subject,
        "text": body,
    }
    if attachment_path:
        path = Path(attachment_path)
        if path.is_file():
            payload["attachments"] = [
                {
                    "filename": path.name,
                    "content": base64.b64encode(path.read_bytes()).decode("utf-8"),
                }
            ]

    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        if response.status_code >= 300:
            return {"ok": False, "error": f"Resend {response.status_code}: {response.text[:300]}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Resend error: {exc}"}

    return {"ok": True, "transport": "resend", "to": to_email}


def send_factory_email(
    to_email: str,
    subject: str,
    body: str,
    attachment_path: str | None = None,
) -> dict[str, Any]:
    """Send a tech pack email in test mode.

    `to_email` is the *intended* factory contact; it's logged in the body but the
    actual delivery is forced to TEST_EMAIL_RECIPIENT. Returns:
        {"ok": bool, "error": str?, "transport": str?, "to": str}
    """
    test_recipient = os.getenv("TEST_EMAIL_RECIPIENT")
    if not test_recipient:
        return {
            "ok": False,
            "error": "TEST_EMAIL_RECIPIENT not set in .env. Refusing to send to a real address.",
        }

    from_email = os.getenv("EMAIL_FROM") or test_recipient
    full_body = _build_body(to_email, body)

    if os.getenv("RESEND_API_KEY"):
        return _send_via_resend(test_recipient, subject, full_body, attachment_path, from_email)
    if os.getenv("SMTP_HOST"):
        return _send_via_smtp(test_recipient, subject, full_body, attachment_path, from_email)

    return {
        "ok": False,
        "error": "No email transport configured. Set either RESEND_API_KEY or SMTP_HOST in .env.",
    }
