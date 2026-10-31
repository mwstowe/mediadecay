"""Regression tests for server-side move-destination validation (P2)."""


def test_invalid_move_dest_rejected_browse(web_client, monkeypatch):
    from mediadecay import engine
    from mediadecay.clients import plex as plex_client

    monkeypatch.setattr(plex_client, "get_move_destinations",
                        lambda: [{"value": "sonarr:/tv"}])

    called = []
    monkeypatch.setattr(engine, "_do_move", lambda *a, **k: called.append(a))
    # If validation is bypassed, the route calls _server() next; make that loud
    # so a regression can't masquerade as a generic backend failure.
    monkeypatch.setattr(plex_client, "_server",
                        lambda: (_ for _ in ()).throw(AssertionError("reached _server()")))

    tok = web_client.csrf_token()
    r = web_client.post("/browse/Movies/123/move",
                        data={"move_to": "sonarr:/etc/passwd", "csrf_token": tok},
                        follow_redirects=True)

    assert called == [], "invalid destination must not reach _do_move"
    assert b"Invalid move destination" in r.data


def test_invalid_move_dest_rejected_immediate(web_client, monkeypatch):
    from mediadecay import engine
    from mediadecay.clients import plex as plex_client

    monkeypatch.setattr(plex_client, "get_move_destinations",
                        lambda: [{"value": "radarr:/movies"}])
    called = []
    monkeypatch.setattr(engine, "_do_move", lambda *a, **k: called.append(a))

    tok = web_client.csrf_token()
    r = web_client.post("/immediate/move/123",
                        data={"move_to": "radarr:/arbitrary/path", "csrf_token": tok})

    assert r.status_code in (302, 303)
    assert called == []


def test_missing_move_dest_redirects(web_client, monkeypatch):
    from mediadecay import engine
    called = []
    monkeypatch.setattr(engine, "_do_move", lambda *a, **k: called.append(a))

    tok = web_client.csrf_token()
    r = web_client.post("/browse/Movies/123/move", data={"csrf_token": tok})
    assert r.status_code in (302, 303)
    assert called == []
