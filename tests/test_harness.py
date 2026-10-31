"""Sanity check that the fixtures build an isolated DB correctly."""
from mediadecay.models import Rule


def test_db_is_isolated_and_writable(db):
    with db.session_scope() as s:
        s.add(Rule(scope="library", plex_library="Movies", action="manage"))
    with db.readonly_session() as s:
        assert s.query(Rule).count() == 1


def test_engine_imports(engine_mod):
    assert hasattr(engine_mod, "process_pending_actions")
    assert hasattr(engine_mod, "_delete_direct")
