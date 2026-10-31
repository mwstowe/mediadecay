"""Tests for form-parse robustness and the global error handler (P2)."""
from mediadecay.web.app import _int_or


def test_int_or_valid():
    assert _int_or("5", 0) == 5
    assert _int_or(5, 0) == 5


def test_int_or_invalid_returns_default():
    assert _int_or("", 7) == 7
    assert _int_or(None, 7) == 7
    assert _int_or("abc", 3) == 3
    assert _int_or("1.5", 9) == 9


def test_global_error_handler_renders_500(db, monkeypatch):
    import bcrypt

    import mediadecay.scheduler as sched
    from mediadecay import config as config_mod
    from mediadecay.web.app import create_app

    config_mod.get_config()["web"]["admin_password"] = bcrypt.hashpw(b"p", bcrypt.gensalt()).decode()
    monkeypatch.setattr(sched, "start_scheduler", lambda app: None)

    app = create_app()
    app.config["TESTING"] = True
    # TESTING propagates exceptions by default; disable so the handler runs.
    app.config["PROPAGATE_EXCEPTIONS"] = False

    # Register the failing route BEFORE the first request is handled.
    @app.route("/_boom_test")
    def _boom():
        raise RuntimeError("kaboom")

    client = app.test_client()
    with client.session_transaction() as s:
        s["authed"] = True

    r = client.get("/_boom_test")
    assert r.status_code == 500
    assert b"Something went wrong" in r.data
    # The raw traceback is not leaked, only the message.
    assert b"Traceback" not in r.data


def test_http_exceptions_keep_their_status(web_client):
    r = web_client.get("/no/such/route")
    assert r.status_code == 404  # not turned into a 500 by the handler
