"""Regression tests for the P0 fail-closed fixes in _delete_direct and
_remove_empty_shows (engine.py)."""
from plexapi.exceptions import NotFound

from mediadecay.models import Rule


class _FakeSection:
    def __init__(self, locations):
        self.locations = locations


class _FakeLibrary:
    def __init__(self, sections):
        self._sections = sections

    def sections(self):
        return self._sections


class _FakeServer:
    def __init__(self, item, sections):
        self._item = item
        self.library = _FakeLibrary(sections)

    def fetchItem(self, key):
        return self._item


class _FakeItem:
    def __init__(self, title="Movie", type_="movie", paths=None):
        self.title = title
        self.type = type_
        self.ratingKey = 1
        self._paths = paths or []


def _make_result(engine_mod, title="Movie", rating_key="1"):
    return engine_mod.EvalResult(title=title, rating_key=rating_key, action="delete", manager="none")


def test_delete_direct_refuses_when_roots_unknown(db, engine_mod, monkeypatch, tmp_path):
    """If library roots can't be enumerated, no file may be deleted."""
    victim = tmp_path / "movie.mkv"
    victim.write_text("data")

    item = _FakeItem(paths=[str(victim)])

    # sections() raises -> roots cannot be determined
    class _BrokenLibrary:
        def sections(self):
            raise RuntimeError("Plex down")

    class _Server:
        library = _BrokenLibrary()
        def fetchItem(self, key):
            return item

    monkeypatch.setattr(engine_mod.plex, "_server", lambda: _Server())
    monkeypatch.setattr(engine_mod.plex, "get_file_paths", lambda it: it._paths)

    engine_mod._delete_direct(_make_result(engine_mod))

    assert victim.exists(), "file must NOT be deleted when roots are unknown"


def test_delete_direct_deletes_when_under_known_root(db, engine_mod, monkeypatch, tmp_path):
    """Sanity: with a known root that contains the path, deletion proceeds."""
    root = tmp_path / "Movies"
    root.mkdir()
    victim = root / "movie.mkv"
    victim.write_text("data")

    item = _FakeItem(paths=[str(victim)])
    server = _FakeServer(item, [_FakeSection([str(root)])])
    monkeypatch.setattr(engine_mod.plex, "_server", lambda: server)
    monkeypatch.setattr(engine_mod.plex, "get_file_paths", lambda it: it._paths)

    engine_mod._delete_direct(_make_result(engine_mod))

    assert not victim.exists(), "file under a known root should be deleted"


def test_delete_direct_skips_path_outside_roots(db, engine_mod, monkeypatch, tmp_path):
    """A path outside all known roots is left alone even when roots are known."""
    root = tmp_path / "Movies"
    root.mkdir()
    outside = tmp_path / "elsewhere.mkv"
    outside.write_text("data")

    item = _FakeItem(paths=[str(outside)])
    server = _FakeServer(item, [_FakeSection([str(root)])])
    monkeypatch.setattr(engine_mod.plex, "_server", lambda: server)
    monkeypatch.setattr(engine_mod.plex, "get_file_paths", lambda it: it._paths)

    engine_mod._delete_direct(_make_result(engine_mod))

    assert outside.exists(), "path outside known roots must not be deleted"


# --- _remove_empty_shows ---

def _make_show_rule(db, rating_key="42", title="Ended Show"):
    with db.session_scope() as s:
        s.add(Rule(scope="show", plex_rating_key=rating_key, media_title=title,
                   action="manage", remove_show_when_empty="always", enabled=True))


def test_remove_empty_shows_skips_on_transient_plex_error(db, engine_mod, monkeypatch):
    """A transient Plex error must NOT be treated as 'show gone' -> no delete."""
    _make_show_rule(db)
    report = engine_mod.EngineReport()

    class _Server:
        def fetchItem(self, key):
            raise RuntimeError("Plex timeout")  # transient, not NotFound

    monkeypatch.setattr(engine_mod.plex, "_server", lambda: _Server())

    called = []
    monkeypatch.setattr(engine_mod, "find_manager_by_rule",
                        lambda rule: called.append("find") or ("sonarr", "555"))
    monkeypatch.setattr(engine_mod.sonarr, "delete_series",
                        lambda *a, **k: called.append("delete_series"))

    engine_mod._remove_empty_shows(report)

    assert "delete_series" not in called, "transient Plex error must not delete the show"
    # Rule is left in place for a later run.
    with db.readonly_session() as s:
        assert s.query(Rule).count() == 1


def test_remove_empty_shows_removes_on_notfound(db, engine_mod, monkeypatch):
    """NotFound from Plex is definitive -> the ended show is removed."""
    _make_show_rule(db)
    report = engine_mod.EngineReport()

    class _Server:
        def fetchItem(self, key):
            raise NotFound("gone")

    monkeypatch.setattr(engine_mod.plex, "_server", lambda: _Server())
    monkeypatch.setattr(engine_mod, "find_manager_by_rule", lambda rule: ("sonarr", "555"))

    deleted = []
    monkeypatch.setattr(engine_mod.sonarr, "delete_series",
                        lambda mid, **k: deleted.append((mid, k)))

    engine_mod._remove_empty_shows(report)

    assert deleted, "ended show that is NotFound in Plex should be removed from manager"
    assert deleted[0][1].get("delete_files") is True
