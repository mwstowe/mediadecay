"""Shared pytest fixtures for MediaDecay.

Each test gets an isolated on-disk SQLite database and a minimal in-memory
config, so no test touches a real deployment, Plex, or the *arr apps.
"""
import pytest

MINIMAL_CONFIG = {
    "plex": {"url": "http://127.0.0.1:32400", "token": "testtoken"},
    "web": {"secret_key": "test-secret", "admin_password": "x"},
    "sonarr": {"url": "http://127.0.0.1:8989", "api_key": "k"},
    "radarr": {"url": "http://127.0.0.1:7878", "api_key": "k"},
    "medusa": {"url": "https://127.0.0.1:8081", "api_key": "k"},
    "ombi": {"url": "http://127.0.0.1:5000", "api_key": "k"},
    "notifications": {"enabled": False},
    "maintenance": {"dry_run": False},
}


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Initialize an isolated database and config, yield the db module.

    Resets the module-level engine/session globals so each test is independent.
    We do NOT reload the db module: reloading would create a fresh Base while
    models.py still references the old one, so create_all() would register no
    tables. Instead we reset globals in place.
    """
    import mediadecay.models  # noqa: F401 — register tables on the shared Base
    from mediadecay import config as config_mod
    from mediadecay import db as db_mod

    cfg = {k: dict(v) if isinstance(v, dict) else v for k, v in MINIMAL_CONFIG.items()}
    cfg["database"] = {"path": str(tmp_path / "test.db")}

    config_mod._config = cfg
    monkeypatch.setattr(config_mod, "load_config", lambda path=None: cfg)
    monkeypatch.setattr(config_mod, "get_config", lambda: cfg)
    # db.py and engine.py call get_config via their own imported name.
    monkeypatch.setattr(db_mod, "get_config", lambda: cfg)

    # Force a fresh engine/session bound to the temp DB path.
    db_mod._engine = None
    db_mod._SessionLocal = None

    db_mod.init_db()
    yield db_mod

    db_mod._engine = None
    db_mod._SessionLocal = None
    config_mod._config = None


@pytest.fixture
def engine_mod(db, monkeypatch):
    """Return the engine module with its managed-media cache cleared and
    client modules importable. Tests monkeypatch client functions as needed.

    We do not reload engine (that would rebind its module-level client and db
    references and detach them from our monkeypatches). We just reset shared
    state and align its get_config to the test config.
    """
    from mediadecay import config as config_mod
    from mediadecay import engine
    monkeypatch.setattr(engine, "get_config", config_mod.get_config, raising=False)
    engine._invalidate_managed_cache()
    yield engine
    engine._invalidate_managed_cache()
