"""Tests for the structured configuration page (replaces raw-YAML editing)."""
import bcrypt
import pytest
import yaml


def _write_config(path):
    cfg = {
        "plex": {
            "url": "http://127.0.0.1:32400",
            "token": "PLEX_SECRET_TOKEN",
            "user_tokens": {"alice": "ALICE_SECRET"},
            "user_emails": {"alice": "alice@example.com"},
        },
        "sonarr": {"url": "http://127.0.0.1:8989", "api_key": "SONARR_SECRET"},
        "web": {
            "secret_key": "WEBSECRET",
            "admin_password": bcrypt.hashpw(b"testpass", bcrypt.gensalt()).decode(),
            "port": 9393,
            "base_url": "https://md.example.com:9393",
        },
        "notifications": {
            "enabled": True, "method": "email",
            "email": {"from": "md@example.com", "admin": "admin@example.com",
                      "smtp_host": "smtp.example.com", "smtp_port": 587,
                      "smtp_pass": "SMTPSECRET"},
            "discord": {"webhook_url": "https://discord/hook/SECRET"},
        },
        "maintenance": {"dry_run": True, "schedule": "03:00",
                        "excluded_libraries": ["3D Movies"]},
        "database": {"path": "will-be-overridden.db"},
    }
    with open(path, "w") as f:
        yaml.dump(cfg, f)
    return cfg


@pytest.fixture
def config_client(tmp_path, monkeypatch):
    """Web client backed by a real on-disk config file."""
    import mediadecay.scheduler as sched
    from mediadecay import config as config_mod
    from mediadecay import db as db_mod

    cfg_path = str(tmp_path / "config.yaml")
    _write_config(cfg_path)
    # DB path inside tmp.
    with open(cfg_path) as f:
        raw = yaml.safe_load(f)
    raw["database"]["path"] = str(tmp_path / "test.db")
    with open(cfg_path, "w") as f:
        yaml.safe_dump(raw, f)

    monkeypatch.setenv("MEDIACLEANER_CONFIG", cfg_path)
    config_mod._config = None
    db_mod._engine = None
    db_mod._SessionLocal = None
    monkeypatch.setattr(sched, "start_scheduler", lambda app: None)

    from mediadecay.web.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    client.get("/login")
    with client.session_transaction() as s:
        tok = s.get("_csrf_token")
    client.post("/login", data={"password": "testpass", "csrf_token": tok})
    client._cfg_path = cfg_path

    def _token():
        with client.session_transaction() as s:
            return s.get("_csrf_token")
    client.csrf_token = _token
    yield client
    config_mod._config = None
    db_mod._engine = None
    db_mod._SessionLocal = None


def _current(client):
    with open(client._cfg_path) as f:
        return yaml.safe_load(f)


def test_page_renders_without_leaking_secrets(config_client):
    r = config_client.get("/config")
    body = r.data.decode()
    assert r.status_code == 200
    # Structured form present.
    assert 'name="cfg__plex__url"' in body
    # No secret value is rendered into the HTML.
    for secret in ("PLEX_SECRET_TOKEN", "SONARR_SECRET", "SMTPSECRET",
                   "ALICE_SECRET", "discord/hook/SECRET", "WEBSECRET"):
        assert secret not in body, f"secret {secret!r} leaked into the page"


def test_edit_nonsecret_field_persists(config_client):
    tok = config_client.csrf_token()
    # Change the Sonarr URL; leave all password fields blank (=> keep).
    data = {
        "csrf_token": tok,
        "__section__plex": "1", "__section__sonarr": "1", "__section__web": "1",
        "__section__notifications": "1", "__section__maintenance": "1",
        "cfg__plex__url": "http://127.0.0.1:32400",
        "cfg__sonarr__url": "http://10.0.0.5:8989",
        "cfg__web__port": "9393",
        "cfg__notifications__enabled": "on",
        "cfg__notifications__method": "email",
        "email__from": "md@example.com",
        "email__admin": "admin@example.com",
        "email__smtp_host": "smtp.example.com",
        "email__smtp_port": "587",
        "user_emails_name[]": "alice",
        "user_emails_value[]": "alice@example.com",
        "excluded_libraries": "3D Movies\n",
    }
    r = config_client.post("/config", data=data)
    assert r.status_code == 200
    cfg = _current(config_client)
    assert cfg["sonarr"]["url"] == "http://10.0.0.5:8989"
    # Secrets left blank must be preserved.
    assert cfg["plex"]["token"] == "PLEX_SECRET_TOKEN"
    assert cfg["sonarr"]["api_key"] == "SONARR_SECRET"
    assert cfg["notifications"]["email"]["smtp_pass"] == "SMTPSECRET"
    assert cfg["notifications"]["discord"]["webhook_url"] == "https://discord/hook/SECRET"


def test_updating_a_secret_replaces_it(config_client):
    tok = config_client.csrf_token()
    data = {
        "csrf_token": tok,
        "__section__plex": "1", "__section__sonarr": "1", "__section__web": "1",
        "cfg__plex__url": "http://127.0.0.1:32400",
        "cfg__plex__token": "NEW_PLEX_TOKEN",
        "cfg__sonarr__url": "http://127.0.0.1:8989",
        "cfg__web__port": "9393",
    }
    r = config_client.post("/config", data=data)
    assert r.status_code == 200
    assert _current(config_client)["plex"]["token"] == "NEW_PLEX_TOKEN"


def test_bool_and_excluded_libraries(config_client):
    tok = config_client.csrf_token()
    # Omit dry_run checkbox but mark the maintenance section submitted => false.
    data = {
        "csrf_token": tok,
        "__section__plex": "1", "__section__sonarr": "1", "__section__web": "1",
        "__section__maintenance": "1",
        "cfg__plex__url": "http://127.0.0.1:32400",
        "cfg__sonarr__url": "http://127.0.0.1:8989",
        "cfg__web__port": "9393",
        "excluded_libraries": "Movies 3D\nHome Videos\n",
    }
    config_client.post("/config", data=data)
    cfg = _current(config_client)
    assert cfg["maintenance"]["dry_run"] is False
    assert cfg["maintenance"]["excluded_libraries"] == ["Movies 3D", "Home Videos"]


def test_invalid_config_rejected(config_client):
    tok = config_client.csrf_token()
    # Clearing the required Plex URL must fail validation and not persist.
    data = {
        "csrf_token": tok,
        "__section__plex": "1", "__section__web": "1",
        "cfg__plex__url": "",
        "cfg__web__port": "9393",
    }
    r = config_client.post("/config", data=data)
    assert b"Invalid config" in r.data
    # Original value still on disk.
    assert _current(config_client)["plex"]["url"] == "http://127.0.0.1:32400"


def test_add_remove_buttons_rendered(config_client):
    body = config_client.get("/config").data.decode()
    # Explicit Add buttons for both key/value editors.
    assert 'class="btn btn-sm btn-primary kv-add" data-target="user_tokens"' in body
    assert 'class="btn btn-sm btn-primary kv-add" data-target="user_emails"' in body
    # Existing rows carry a Remove button.
    assert "kv-remove" in body
    # The old grow-on-type helper is gone.
    assert "wireGrow" not in body


def test_existing_rows_have_no_trailing_blank(config_client):
    body = config_client.get("/config").data.decode()
    # The alice row renders; there should be exactly one name input per existing
    # entry (no always-present extra blank row appended by the template).
    assert body.count('name="user_emails_name[]"') == 1
    assert body.count('name="user_tokens_name[]"') == 1


def test_removing_all_rows_clears_map(config_client):
    tok = config_client.csrf_token()
    # Submit the plex section with NO user_emails/user_tokens rows at all.
    data = {
        "csrf_token": tok,
        "__section__plex": "1", "__section__sonarr": "1", "__section__web": "1",
        "cfg__plex__url": "http://127.0.0.1:32400",
        "cfg__sonarr__url": "http://127.0.0.1:8989",
        "cfg__web__port": "9393",
    }
    r = config_client.post("/config", data=data)
    assert r.status_code == 200
    cfg = _current(config_client)
    assert cfg["plex"]["user_emails"] == {}
    assert cfg["plex"]["user_tokens"] == {}


def test_adding_a_user_email_row_persists(config_client):
    tok = config_client.csrf_token()
    data = {
        "csrf_token": tok,
        "__section__plex": "1", "__section__sonarr": "1", "__section__web": "1",
        "cfg__plex__url": "http://127.0.0.1:32400",
        "cfg__sonarr__url": "http://127.0.0.1:8989",
        "cfg__web__port": "9393",
        # Two rows (as the Add button would produce).
        "user_emails_name[]": ["alice", "bob"],
        "user_emails_value[]": ["alice@example.com", "bob@example.com"],
    }
    r = config_client.post("/config", data=data)
    assert r.status_code == 200
    emails = _current(config_client)["plex"]["user_emails"]
    assert emails == {"alice": "alice@example.com", "bob": "bob@example.com"}
