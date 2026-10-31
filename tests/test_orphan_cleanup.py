"""Regression tests for cleanup_orphaned_rules fail-closed behavior (P1 #10)."""
from plexapi.exceptions import NotFound

from mediadecay.models import Rule


def _make_rule(db, title="Ghost Show", rating_key="77"):
    with db.session_scope() as s:
        s.add(Rule(scope="show", plex_rating_key=rating_key, media_title=title,
                   action="manage", enabled=True))


class _PlexNotFound:
    """Plex server stub whose fetchItem always reports the item gone."""
    def fetchItem(self, key):
        raise NotFound("gone")


def test_rule_not_deleted_when_manager_unreachable(db, engine_mod, monkeypatch):
    _make_rule(db)
    monkeypatch.setattr(engine_mod.plex, "_server", lambda: _PlexNotFound())

    # Sonarr is down -> raises; Medusa/Radarr return empty.
    def _sonarr_down():
        raise ConnectionError("Sonarr unreachable")
    monkeypatch.setattr(engine_mod.sonarr, "get_all_series", _sonarr_down)
    monkeypatch.setattr(engine_mod.medusa, "get_all_shows", list)
    monkeypatch.setattr(engine_mod.radarr, "get_all_movies", list)

    orphaned = engine_mod.cleanup_orphaned_rules()

    assert orphaned == [], "must not orphan a rule when a manager is unreachable"
    with db.readonly_session() as s:
        assert s.query(Rule).count() == 1, "rule must be preserved"


def test_rule_deleted_when_confirmed_absent_everywhere(db, engine_mod, monkeypatch):
    _make_rule(db)
    monkeypatch.setattr(engine_mod.plex, "_server", lambda: _PlexNotFound())
    # All managers reachable and return nothing -> genuinely orphaned.
    monkeypatch.setattr(engine_mod.sonarr, "get_all_series", list)
    monkeypatch.setattr(engine_mod.medusa, "get_all_shows", list)
    monkeypatch.setattr(engine_mod.radarr, "get_all_movies", list)

    orphaned = engine_mod.cleanup_orphaned_rules()

    assert len(orphaned) == 1
    with db.readonly_session() as s:
        assert s.query(Rule).count() == 0


def test_rule_preserved_when_still_in_manager(db, engine_mod, monkeypatch):
    _make_rule(db, title="Ghost Show")
    monkeypatch.setattr(engine_mod.plex, "_server", lambda: _PlexNotFound())
    # Sonarr still has a matching title.
    monkeypatch.setattr(engine_mod.sonarr, "get_all_series",
                        lambda: [{"title": "Ghost Show", "tvdbId": 1}])
    monkeypatch.setattr(engine_mod.medusa, "get_all_shows", list)
    monkeypatch.setattr(engine_mod.radarr, "get_all_movies", list)

    orphaned = engine_mod.cleanup_orphaned_rules()

    assert orphaned == []
    with db.readonly_session() as s:
        assert s.query(Rule).count() == 1
