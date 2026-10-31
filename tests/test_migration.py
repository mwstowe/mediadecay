"""Tests for the hardened _migrate (P2 #5)."""
import sqlite3


def _columns(path, table):
    conn = sqlite3.connect(path)
    try:
        return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    finally:
        conn.close()


def test_init_db_is_idempotent(db):
    # db fixture already called init_db once; calling again must not error.
    db.init_db()
    db.init_db()


def test_schema_version_recorded(db):
    path = db.get_config()["database"]["path"]
    conn = sqlite3.connect(path)
    try:
        ver = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
    finally:
        conn.close()
    assert ver is not None and ver >= 1


def test_adds_missing_columns_to_legacy_schema(tmp_path, monkeypatch):
    """A pre-existing 'rules' table missing newer columns gets them added."""
    from mediadecay import config as config_mod
    from mediadecay import db as db_mod

    db_path = str(tmp_path / "legacy.db")
    cfg = {"database": {"path": db_path},
           "plex": {"url": "x", "token": "y"},
           "web": {"secret_key": "s", "admin_password": "p"}}
    monkeypatch.setattr(config_mod, "get_config", lambda: cfg)
    monkeypatch.setattr(db_mod, "get_config", lambda: cfg)
    config_mod._config = cfg

    # Simulate an old database: a minimal rules table without the newer columns.
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE rules (id INTEGER PRIMARY KEY, scope VARCHAR, action VARCHAR)")
    conn.commit()
    conn.close()

    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod.init_db()

    cols = _columns(db_path, "rules")
    for expected in ("processing_mode", "tvdb_id", "external_id", "move_to"):
        assert expected in cols, f"migration should have added {expected}"

    db_mod._engine = None
    db_mod._SessionLocal = None
    config_mod._config = None


def test_migrate_runs_twice_without_error(db):
    # Running _migrate directly a second time must be a no-op, not raise.
    db._migrate()
    db._migrate()
