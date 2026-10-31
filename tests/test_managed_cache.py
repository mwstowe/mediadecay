"""Regression tests for the managed-media cache (P2: plain-data, detached-safe)."""
from datetime import datetime, timezone

from mediadecay.models import ManagedMedia


def _seed(db, rows):
    with db.session_scope() as s:
        for title, path, manager, mid in rows:
            s.add(ManagedMedia(title=title, file_path=path, manager=manager,
                               manager_id=mid, last_synced=datetime.now(timezone.utc)))


def test_cache_returns_immutable_plain_data(db, engine_mod):
    _seed(db, [("Show", "/tv/Show", "sonarr", "10")])
    cache = engine_mod._get_managed_media_cache()

    # Immutable container, not a live ORM list.
    assert isinstance(cache, tuple)
    entry = cache[0]
    # Plain namedtuple with the fields find_manager needs.
    assert entry.title == "Show"
    assert entry.file_path == "/tv/Show"
    assert entry.manager == "sonarr"
    assert entry.manager_id == "10"
    assert not isinstance(entry, ManagedMedia)


def test_cache_usable_after_session_closed(db, engine_mod):
    """Accessing fields must not raise DetachedInstanceError after the session
    that produced them is gone (the whole point of caching plain data)."""
    _seed(db, [("Movie", "/movies/Movie", "radarr", "5")])
    cache = engine_mod._get_managed_media_cache()
    # Force several field accesses well after the read session has closed.
    for _ in range(3):
        for e in cache:
            _ = (e.title, e.file_path, e.manager, e.manager_id)
    assert cache[0].manager == "radarr"


def test_find_manager_matches_by_path(db, engine_mod, monkeypatch):
    _seed(db, [
        ("Show", "/tv/Show", "sonarr", "10"),
        ("Anime", "/anime/Anime", "medusa", "tvdb1"),
    ])
    engine_mod._invalidate_managed_cache()

    class _Item:
        pass
    # An episode path under the Sonarr show folder.
    monkeypatch.setattr(engine_mod.plex, "get_file_paths",
                        lambda item: ["/tv/Show/Season 01/ep.mkv"])
    manager, mid = engine_mod.find_manager(_Item())
    assert (manager, mid) == ("sonarr", "10")


def test_find_manager_prefers_medusa(db, engine_mod, monkeypatch):
    # Same path claimed by two managers -> medusa wins per priority.
    _seed(db, [
        ("S", "/shared/Show", "sonarr", "10"),
        ("S", "/shared/Show", "medusa", "tvdb1"),
    ])
    engine_mod._invalidate_managed_cache()
    monkeypatch.setattr(engine_mod.plex, "get_file_paths", lambda item: ["/shared/Show"])
    manager, _mid = engine_mod.find_manager(object())
    assert manager == "medusa"


def test_invalidate_forces_refresh(db, engine_mod):
    _seed(db, [("One", "/a", "sonarr", "1")])
    assert len(engine_mod._get_managed_media_cache()) == 1
    _seed(db, [("Two", "/b", "sonarr", "2")])
    # Without invalidation the cache is stale.
    assert len(engine_mod._get_managed_media_cache()) == 1
    engine_mod._invalidate_managed_cache()
    assert len(engine_mod._get_managed_media_cache()) == 2
