"""Notification dispatch — email or Discord webhook."""

import logging
import smtplib
from email.message import EmailMessage

import requests

from mediadecay.config import get_config

log = logging.getLogger(__name__)


def _default_recipient() -> str:
    """Get admin email from config."""
    cfg = get_config().get("notifications", {}).get("email", {})
    return cfg.get("admin", "")


def send(subject: str, body: str):
    """Best-effort notification (maintenance reports). Never raises."""
    cfg = get_config().get("notifications", {})
    if not cfg.get("enabled"):
        return

    method = cfg.get("method", "email")
    try:
        if method == "email":
            recipient = _default_recipient()
            if recipient:
                _send_email(subject, body, cfg.get("email", {}), recipient)
        elif method == "discord":
            _send_discord(subject, body, cfg["discord"])
    except Exception as e:
        log.error(f"Failed to send {method} notification: {e}")


def send_to(subject: str, body: str, recipient: str):
    """Send to a specific email recipient (for confirmation emails).

    Raises on failure so the caller can react (e.g. not start a deletion
    countdown when the confirmation email never went out).
    """
    cfg = get_config().get("notifications", {})
    _send_email(subject, body, cfg.get("email", {}), recipient)


def _send_email(subject: str, body: str, cfg: dict, recipient: str):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.get("from", cfg.get("smtp_user", "mediadecay@localhost"))
    msg["To"] = recipient
    msg.set_content(body)

    host = cfg["smtp_host"]
    port = int(cfg.get("smtp_port", 587))
    user = cfg.get("smtp_user")
    password = cfg.get("smtp_pass")
    # TLS mode: explicit override, else inferred from port.
    #   ssl      -> implicit TLS (SMTP_SSL), typical for port 465
    #   starttls -> plain connect then STARTTLS upgrade, typical for 587/25
    #   none     -> no encryption (only valid when no credentials are sent)
    mode = cfg.get("smtp_tls")
    if mode is None:
        mode = "ssl" if port == 465 else "starttls"

    if mode == "ssl":
        smtp = smtplib.SMTP_SSL(host, port, timeout=30)
    else:
        smtp = smtplib.SMTP(host, port, timeout=30)
    try:
        if mode == "starttls":
            smtp.ehlo()
            if smtp.has_extn("starttls"):
                smtp.starttls()
                smtp.ehlo()
            elif user:
                # Refuse to send credentials over an unencrypted channel.
                raise RuntimeError(
                    "SMTP server does not support STARTTLS but credentials are "
                    "configured; refusing to send password in cleartext. Set "
                    "smtp_tls: ssl (port 465) or use a TLS-capable server."
                )
        elif mode == "none" and user:
            raise RuntimeError(
                "smtp_tls is 'none' but credentials are configured; refusing to "
                "send password in cleartext."
            )
        if user:
            smtp.login(user, password)
        smtp.send_message(msg)
    finally:
        try:
            smtp.quit()
        except Exception:
            pass


def _send_discord(subject: str, body: str, cfg: dict):
    content = f"**{subject}**\n```\n{body[:1900]}\n```"
    requests.post(cfg["webhook_url"], json={"content": content}, timeout=15)
