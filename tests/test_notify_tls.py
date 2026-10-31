"""Regression tests for SMTP TLS handling in notify._send_email (P1 #8)."""
from typing import ClassVar

import pytest

from mediadecay import notify


class _FakeSMTP:
    """Records TLS/login/send calls. Shared recorder across instances."""
    instances: ClassVar[list] = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.events = []
        self.starttls_supported = True
        _FakeSMTP.instances.append(self)

    def ehlo(self):
        self.events.append("ehlo")

    def has_extn(self, name):
        return name == "starttls" and self.starttls_supported

    def starttls(self):
        self.events.append("starttls")

    def login(self, user, pw):
        self.events.append(("login", user))

    def send_message(self, msg):
        self.events.append("send")

    def quit(self):
        self.events.append("quit")


class _FakeSMTPSSL(_FakeSMTP):
    kind = "ssl"


@pytest.fixture(autouse=True)
def _reset():
    _FakeSMTP.instances = []
    yield


def _cfg(**over):
    base = {"smtp_host": "mail.example.com", "smtp_port": 587,
            "from": "md@example.com"}
    base.update(over)
    return base


def test_port_465_uses_implicit_ssl(monkeypatch):
    monkeypatch.setattr(notify.smtplib, "SMTP_SSL", _FakeSMTPSSL)
    monkeypatch.setattr(notify.smtplib, "SMTP", _FakeSMTP)
    notify._send_email("s", "b", _cfg(smtp_port=465), "to@example.com")
    inst = _FakeSMTP.instances[0]
    assert isinstance(inst, _FakeSMTPSSL)
    assert "starttls" not in inst.events  # implicit TLS, no STARTTLS
    assert "send" in inst.events


def test_port_587_attempts_starttls(monkeypatch):
    monkeypatch.setattr(notify.smtplib, "SMTP", _FakeSMTP)
    notify._send_email("s", "b", _cfg(smtp_port=587, smtp_user="u", smtp_pass="p"),
                       "to@example.com")
    inst = _FakeSMTP.instances[0]
    assert "starttls" in inst.events
    assert ("login", "u") in inst.events
    # login must come after starttls
    assert inst.events.index("starttls") < inst.events.index(("login", "u"))


def test_refuses_cleartext_login_when_no_starttls(monkeypatch):
    monkeypatch.setattr(notify.smtplib, "SMTP", _FakeSMTP)

    def _factory(host, port, timeout=None):
        inst = _FakeSMTP(host, port, timeout)
        inst.starttls_supported = False  # server can't do STARTTLS
        return inst
    monkeypatch.setattr(notify.smtplib, "SMTP", _factory)

    with pytest.raises(RuntimeError, match="cleartext"):
        notify._send_email("s", "b", _cfg(smtp_port=25, smtp_user="u", smtp_pass="p"),
                           "to@example.com")
    # Credentials were never sent.
    inst = _FakeSMTP.instances[0]
    assert not any(isinstance(e, tuple) and e[0] == "login" for e in inst.events)


def test_tls_none_without_credentials_is_allowed(monkeypatch):
    monkeypatch.setattr(notify.smtplib, "SMTP", _FakeSMTP)
    # No user -> plaintext relay is acceptable (e.g. local MTA).
    notify._send_email("s", "b", _cfg(smtp_port=25, smtp_tls="none"), "to@example.com")
    inst = _FakeSMTP.instances[0]
    assert "send" in inst.events
    assert "starttls" not in inst.events


def test_send_is_best_effort_and_never_raises(monkeypatch):
    def _boom(*a, **k):
        raise OSError("smtp down")
    monkeypatch.setattr(notify, "_send_email", _boom)
    monkeypatch.setattr(notify, "get_config", lambda: {
        "notifications": {"enabled": True, "method": "email",
                          "email": {"admin": "a@example.com"}}})
    # Must not raise.
    notify.send("subject", "body")
