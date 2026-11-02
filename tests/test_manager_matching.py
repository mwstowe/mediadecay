"""Regression tests for ID-based manager matching (review #10) and
Sonarr wanted-series filtering (review #6)."""

from mediadecay.models import Rule


def _make_show_rule(db, **kw):
    defaults = dict(scope="show", plex_rating_key="55", media_title="Reboot",
                    action="manage", enabled=True)
    defaults.update(kw)
    with db.session_scope() as s:
        s.add(Rule(**defaults))


# --- find_manager_by_rule: prefer durable IDs over title (review #10) ---

def test_find_manager_by_rule_prefers_tvdb_id(db, engine_mod, monkeypatch):
    # Two Sonarr series share the title "Reboot" but different TVDB IDs.
    # Title matching would be ambiguous; the rule's tvdb_id must disambiguate.
    _make_show_rule(db, tvdb_id=2002)
    monkeypatch.setattr(engine_mod.sonarr, "get_all_series", lambda: [
        {"title": "Reboot", "id": 1, "tvdbId": 1001},
        {"title": "Reboot", "id": 2, "tvdbId": 2002},
    ])
    monkeypatch.setattr(engine_mod.medusa, "get_all_shows", list)
    monkeypatch.setattr(engine_mod.radarr, "get_all_movies", list)

    with db.readonly_session() as s:
        rule = s.query(Rule).one()
        manager, manager_id = engine_mod.find_manager_by_rule(rule)

    assert manager == "sonarr"
    assert manager_id == 2, "must select the series whose tvdbId matches the rule"


def test_find_manager_by_rule_radarr_tmdb(db, engine_mod, monkeypatch):
    _make_show_rule(db, media_title="A Movie", tmdb_id=777)
    monkeypatch.setattr(engine_mod.sonarr, "get_all_series", list)
    monkeypatch.setattr(engine_mod.medusa, "get_all_shows", list)
    monkeypatch.setattr(engine_mod.radarr, "get_all_movies",
                        lambda: [{"title": "A Movie", "id": 9, "tmdbId": 777}])

    with db.readonly_session() as s:
        rule = s.query(Rule).one()
        manager, manager_id = engine_mod.find_manager_by_rule(rule)

    assert (manager, manager_id) == ("radarr", 9)


def test_find_manager_by_rule_title_fallback_without_ids(db, engine_mod, monkeypatch):
    # No IDs on the rule -> fall back to title match via managed-media cache.
    _make_show_rule(db, media_title="Legacy Show")
    from mediadecay.models import ManagedMedia
    with db.session_scope() as s:
        s.add(ManagedMedia(title="Legacy Show", manager="medusa", manager_id="tvdb123",
                           file_path="/tv/Legacy Show"))
    engine_mod._invalidate_managed_cache()

    with db.readonly_session() as s:
        rule = s.query(Rule).one()
        manager, manager_id = engine_mod.find_manager_by_rule(rule)

    assert (manager, manager_id) == ("medusa", "tvdb123")


def test_find_manager_by_rule_none_when_id_unmatched(db, engine_mod, monkeypatch):
    # Rule has a tvdb_id but no manager has it -> ("none", None), and the
    # title fallback is NOT used (IDs present), so a same-title but different
    # show cannot be matched by accident.
    _make_show_rule(db, media_title="Reboot", tvdb_id=9999)
    monkeypatch.setattr(engine_mod.sonarr, "get_all_series",
                        lambda: [{"title": "Reboot", "id": 1, "tvdbId": 1001}])
    monkeypatch.setattr(engine_mod.medusa, "get_all_shows", list)
    monkeypatch.setattr(engine_mod.radarr, "get_all_movies", list)

    with db.readonly_session() as s:
        rule = s.query(Rule).one()
        result = engine_mod.find_manager_by_rule(rule)

    assert result == ("none", None)


# --- Sonarr get_wanted_series: only series missing files (review #6) ---

def test_wanted_series_excludes_complete_series(monkeypatch):
    from mediadecay.clients import sonarr
    monkeypatch.setattr(sonarr, "get_all_series", lambda: [
        {"title": "Complete", "monitored": True,
         "statistics": {"episodeCount": 10, "episodeFileCount": 10}},
        {"title": "Missing", "monitored": True,
         "statistics": {"episodeCount": 10, "episodeFileCount": 3}},
        {"title": "Unmonitored", "monitored": False,
         "statistics": {"episodeCount": 10, "episodeFileCount": 0}},
        {"title": "No stats yet", "monitored": True},
    ])

    titles = [s["title"] for s in sonarr.get_wanted_series()]

    assert "Missing" in titles
    assert "No stats yet" in titles          # no stats -> not hidden
    assert "Complete" not in titles          # fully downloaded -> not wanted
    assert "Unmonitored" not in titles       # unmonitored -> excluded
