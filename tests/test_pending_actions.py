"""Regression tests for the P0 dry-run / confirmed-state fixes in
process_pending_actions (engine.py)."""
from datetime import datetime, timedelta, timezone

from mediadecay.models import PendingAction


def _make_expired_pending(db, title="Old Movie", rating_key="100"):
    """Insert a pending action whose confirmation window has already expired
    and whose notification was confirmed sent."""
    now = datetime.now(timezone.utc)
    with db.session_scope() as s:
        pa = PendingAction(
            plex_rating_key=rating_key,
            media_title=title,
            token="tok-" + rating_key,
            confirm_method="snooze",
            notified_at=now - timedelta(days=10),
            expires_at=now - timedelta(days=1),
            confirmed=False,
            cancelled=False,
            notification_sent=True,
        )
        s.add(pa)


class _DeleteRecorder:
    """Stub manager client that records destructive calls."""
    def __init__(self):
        self.calls = []

    def delete_series(self, *a, **k):
        self.calls.append(("sonarr.delete_series", a, k))

    def delete_movie(self, *a, **k):
        self.calls.append(("radarr.delete_movie", a, k))

    def delete_show(self, *a, **k):
        self.calls.append(("medusa.delete_show", a, k))

    def cleanup_for_title(self, *a, **k):
        self.calls.append(("ombi.cleanup_for_title", a, k))


def _wire_manager(engine_mod, monkeypatch, manager, recorder, delete_ok=True):
    """Point engine at a stub manager and make find_manager return it."""
    monkeypatch.setattr(engine_mod, "find_manager", lambda item: (manager, "555"))
    # Avoid any real Plex call inside the expiry block.
    monkeypatch.setattr(engine_mod.plex, "_server", lambda: _FakeServer())
    if manager == "sonarr":
        monkeypatch.setattr(engine_mod.sonarr, "delete_series", recorder.delete_series)
    elif manager == "radarr":
        monkeypatch.setattr(engine_mod.radarr, "delete_movie", recorder.delete_movie)
    elif manager == "medusa":
        monkeypatch.setattr(engine_mod.medusa, "delete_show", recorder.delete_show)
        monkeypatch.setattr(engine_mod, "_delete_direct", lambda r: None)
    monkeypatch.setattr(engine_mod.ombi, "cleanup_for_title", recorder.cleanup_for_title)
    # Never cancel via plex activity in these tests.
    monkeypatch.setattr(engine_mod, "_user_cancelled_via_plex", lambda pa: False)


class _FakeItem:
    title = "Old Movie"
    type = "movie"
    ratingKey = 100


class _FakeServer:
    def fetchItem(self, key):
        return _FakeItem()


def test_dry_run_performs_no_deletions(db, engine_mod, monkeypatch):
    _make_expired_pending(db)
    rec = _DeleteRecorder()
    _wire_manager(engine_mod, monkeypatch, "sonarr", rec)

    result = engine_mod.process_pending_actions(dry_run=True)

    # Reported as would-delete, but NO destructive call happened...
    assert "Old Movie" in result
    assert rec.calls == [], f"dry run must not delete, got {rec.calls}"
    # ...and the pending action stays unconfirmed for a real run.
    with db.readonly_session() as s:
        pa = s.query(PendingAction).one()
        assert pa.confirmed is False


def test_live_expired_deletes_and_marks_confirmed(db, engine_mod, monkeypatch):
    _make_expired_pending(db)
    rec = _DeleteRecorder()
    _wire_manager(engine_mod, monkeypatch, "sonarr", rec)

    result = engine_mod.process_pending_actions(dry_run=False)

    assert "Old Movie" in result
    names = [c[0] for c in rec.calls]
    assert "sonarr.delete_series" in names
    # delete_files=True must be passed
    call = next(c for c in rec.calls if c[0] == "sonarr.delete_series")
    assert call[2].get("delete_files") is True
    with db.readonly_session() as s:
        pa = s.query(PendingAction).one()
        assert pa.confirmed is True


def test_failed_delete_leaves_unconfirmed_for_retry(db, engine_mod, monkeypatch):
    _make_expired_pending(db)
    monkeypatch.setattr(engine_mod, "find_manager", lambda item: ("sonarr", "555"))
    monkeypatch.setattr(engine_mod.plex, "_server", lambda: _FakeServer())
    monkeypatch.setattr(engine_mod, "_user_cancelled_via_plex", lambda pa: False)

    def _boom(*a, **k):
        raise RuntimeError("Sonarr unreachable")
    monkeypatch.setattr(engine_mod.sonarr, "delete_series", _boom)

    result = engine_mod.process_pending_actions(dry_run=False)

    # Delete failed -> not reported as deleted, and left unconfirmed to retry.
    assert "Old Movie" not in result
    with db.readonly_session() as s:
        pa = s.query(PendingAction).one()
        assert pa.confirmed is False
