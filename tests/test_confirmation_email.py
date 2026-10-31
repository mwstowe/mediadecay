"""Regression tests for the confirmation-email send contract (bug: admin
fallback returned None and left confirmations un-expirable)."""

from mediadecay.models import PendingAction, Rule, Trigger


def _make_rule(db, watched_by="any", confirm_email=None):
    with db.session_scope() as s:
        rule = Rule(scope="show", plex_rating_key="500", media_title="Show",
                    action="manage", watched_by=watched_by, enabled=True)
        rule.triggers = [Trigger(type="watched", days=7, action="delete",
                                 confirm_days=7, confirm_methods="snooze",
                                 confirm_email=confirm_email, enabled=True)]
        s.add(rule)
        s.flush()
        return rule.id, rule.triggers[0].id


def test_admin_fallback_counts_as_sent(db, engine_mod, monkeypatch):
    """watched_by='any' with no user email -> admin fallback -> sent=True."""
    rid, tid = _make_rule(db, watched_by="any")
    sent_calls = {"send": 0, "send_to": 0}
    monkeypatch.setattr(engine_mod.notify, "send",
                        lambda *a, **k: sent_calls.__setitem__("send", sent_calls["send"] + 1))
    monkeypatch.setattr(engine_mod.notify, "send_to",
                        lambda *a, **k: sent_calls.__setitem__("send_to", sent_calls["send_to"] + 1))
    # Avoid a real Plex call inside _send_confirmation_email.
    monkeypatch.setattr(engine_mod.plex, "_server",
                        lambda: (_ for _ in ()).throw(Exception("no plex")))

    with db.session_scope() as s:
        rule = s.get(Rule, rid)
        trigger = s.get(Trigger, tid)
        engine_mod._handle_pending_confirm(s, rule, trigger, "500", "Show", dry_run=False)

    assert sent_calls["send"] == 1  # admin fallback used
    with db.readonly_session() as s:
        pa = s.query(PendingAction).filter_by(plex_rating_key="500").one()
        assert pa.notification_sent is True, "admin-fallback send must start the timer"
        assert pa.notified_to is None  # no specific recipient recorded


def test_specific_recipient_recorded(db, engine_mod, monkeypatch):
    rid, tid = _make_rule(db, confirm_email="user@example.com")
    monkeypatch.setattr(engine_mod.notify, "send_to", lambda *a, **k: None)
    monkeypatch.setattr(engine_mod.notify, "send", lambda *a, **k: None)
    monkeypatch.setattr(engine_mod.plex, "_server",
                        lambda: (_ for _ in ()).throw(Exception("no plex")))

    with db.session_scope() as s:
        rule = s.get(Rule, rid)
        trigger = s.get(Trigger, tid)
        engine_mod._handle_pending_confirm(s, rule, trigger, "500", "Show", dry_run=False)

    with db.readonly_session() as s:
        pa = s.query(PendingAction).filter_by(plex_rating_key="500").one()
        assert pa.notification_sent is True
        assert pa.notified_to == "user@example.com"


def test_send_failure_does_not_start_timer(db, engine_mod, monkeypatch):
    rid, tid = _make_rule(db, confirm_email="user@example.com")

    def _boom(*a, **k):
        raise RuntimeError("smtp down")
    monkeypatch.setattr(engine_mod.notify, "send_to", _boom)
    monkeypatch.setattr(engine_mod.notify, "send", _boom)
    monkeypatch.setattr(engine_mod.plex, "_server",
                        lambda: (_ for _ in ()).throw(Exception("no plex")))

    with db.session_scope() as s:
        rule = s.get(Rule, rid)
        trigger = s.get(Trigger, tid)
        engine_mod._handle_pending_confirm(s, rule, trigger, "500", "Show", dry_run=False)

    with db.readonly_session() as s:
        pa = s.query(PendingAction).filter_by(plex_rating_key="500").one()
        assert pa.notification_sent is False, "failed send must NOT start the timer"
