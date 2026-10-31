"""Regression tests for _safe_rollback_move (P1 #6 move-rollback safety)."""


def test_rollback_restores_files(engine_mod, tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    new.mkdir()
    (new / "file.mkv").write_text("data")

    ok = engine_mod._safe_rollback_move(str(new), str(old), "Show")

    assert ok is True
    assert old.exists() and (old / "file.mkv").exists()
    assert not new.exists()


def test_rollback_noop_when_same_path(engine_mod, tmp_path):
    p = tmp_path / "same"
    p.mkdir()
    assert engine_mod._safe_rollback_move(str(p), str(p), "Show") is True


def test_rollback_noop_when_dest_missing(engine_mod, tmp_path):
    # Forward move never completed: nothing at new_path -> nothing to roll back.
    old = tmp_path / "old"
    new = tmp_path / "new"  # does not exist
    assert engine_mod._safe_rollback_move(str(new), str(old), "Show") is True


def test_rollback_aborts_when_both_exist(engine_mod, tmp_path):
    # Both source and destination present -> must NOT clobber; returns False.
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (old / "orig.mkv").write_text("original")
    (new / "moved.mkv").write_text("moved")

    ok = engine_mod._safe_rollback_move(str(new), str(old), "Show")

    assert ok is False
    # Both left intact — nothing destroyed.
    assert (old / "orig.mkv").exists()
    assert (new / "moved.mkv").exists()


def test_check_incomplete_moves_reports_and_survives_no_db(engine_mod, db):
    from datetime import datetime, timezone

    from mediadecay.models import MoveState

    with db.session_scope() as s:
        s.add(MoveState(
            started_at=datetime.now(timezone.utc),
            media_title="Interrupted Show",
            plex_rating_key="9",
            source_manager="sonarr", source_path="/a",
            dest_manager="medusa", dest_path="/b",
            status="moving_files",
        ))

    incomplete = engine_mod.check_incomplete_moves()
    titles = [m.media_title for m in incomplete]
    assert "Interrupted Show" in titles
