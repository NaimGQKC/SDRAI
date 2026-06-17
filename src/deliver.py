"""deliver.py — send the digest via Gmail SMTP.

Uses a Google App Password (needs 2FA on the account), never the real password.
"""
from __future__ import annotations

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def send_digest(html: str, date: str, subject: str | None = None) -> None:
    """Send the HTML digest. Raises if credentials are missing or SMTP fails."""
    sender = os.getenv("GMAIL_ADDRESS")
    password = os.getenv("GMAIL_APP_PASSWORD")
    to_addr = os.getenv("DIGEST_TO") or sender

    if not (sender and password and to_addr):
        raise RuntimeError(
            "Missing GMAIL_ADDRESS / GMAIL_APP_PASSWORD / DIGEST_TO — cannot send digest."
        )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject or f"Hit-list — {date}"
    msg["From"] = sender
    msg["To"] = to_addr
    msg.attach(MIMEText("Your hit-list is ready. Open in an HTML-capable client.", "plain"))
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, [to_addr], msg.as_string())
