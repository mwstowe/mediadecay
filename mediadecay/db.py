from contextlib import contextmanager

import logging

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from mediadecay.config import get_config

log = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        cfg = get_config()
        db_path = cfg.get("database", {}).get("path", "mediadecay.db")
        _engine = create_engine(f"sqlite:///{db_path}", echo=False,
                                connect_args={"timeout": 30, "check_same_thread": False})

        @event.listens_for(_engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA wal_autocheckpoint=100")
            cursor.close()

    return _engine


def get_session() -> Session:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine())
    return _SessionLocal()


@contextmanager
def session_scope():
    """Provide a transactional scope around a series of operations.

    Creates a session, yields it, commits on success, rolls back on exception,
    and always closes the session.
    """
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def readonly_session():
    """Provide a read-only session scope (no commit).

    Creates a session, yields it for read operations, rolls back on exception,
    and always closes the session without committing.
    """
    session = get_session()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def checkpoint():
    """Force a WAL checkpoint — flush all data to the main DB file."""
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
        conn.commit()


def init_db():
    from mediadecay import models  # noqa: F401

    Base.metadata.create_all(get_engine())
    _migrate()


def _migrate():
    """Apply additive schema migrations to an existing database.

    Base.metadata.create_all() (called in init_db before this) already creates
    any missing *tables*, so here we only need to add columns that were
    introduced after a table first existed, plus a one-time data migration.

    This is intentionally lightweight (no Alembic): it is idempotent via
    PRAGMA table_info existence checks, isolates each step so one failure
    doesn't abort the rest, sets a busy_timeout so it waits rather than
    erroring under concurrent access, and records a schema_version marker.
    """
    import sqlite3
    from contextlib import closing

    # Current additive-migration revision. Bump when adding a new _add_col/step.
    SCHEMA_VERSION = 1

    cfg = get_config()
    db_path = cfg.get("database", {}).get("path", "mediadecay.db")

    with closing(sqlite3.connect(db_path, timeout=30)) as conn:
        conn.execute("PRAGMA busy_timeout=30000")

        def _add_col(table, col, coltype, default=None):
            try:
                existing = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
                if not existing:
                    return  # table doesn't exist (shouldn't happen post create_all)
                if col not in existing:
                    defstr = f" DEFAULT {default}" if default is not None else ""
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}{defstr}")
            except sqlite3.OperationalError as e:
                # Isolate: a single failing ALTER must not abort the whole run.
                log.warning(f"Migration: could not add {table}.{col}: {e}")

        # Record a schema_version marker (informational; also lets us detect a
        # database written by a newer version of the app).
        conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        current = row[0] if row and row[0] is not None else 0
        if current > SCHEMA_VERSION:
            log.warning(f"Database schema_version {current} is newer than this app "
                        f"supports ({SCHEMA_VERSION}); proceeding read-compatibly.")

        # Rules table migrations
        _add_col("rules", "processing_mode", "VARCHAR", "'episode'")
        _add_col("rules", "remove_show_when_empty", "VARCHAR", "'if_ended'")
        _add_col("rules", "snoozed_until", "DATETIME", "NULL")
        _add_col("rules", "move_to", "VARCHAR", "NULL")
        _add_col("rules", "tvdb_id", "INTEGER", "NULL")
        _add_col("rules", "tmdb_id", "INTEGER", "NULL")
        _add_col("rules", "external_id", "VARCHAR", "NULL")
        _add_col("rules", "external_source", "VARCHAR", "NULL")

        # PendingAction migrations
        _add_col("pending_actions", "trigger_id", "INTEGER", "NULL")
        _add_col("pending_actions", "notified_to", "VARCHAR", "NULL")
        _add_col("pending_actions", "notification_sent", "BOOLEAN", "0")

        # Trigger migrations
        _add_col("triggers", "move_to", "VARCHAR", "NULL")

        # One-time data migration: Rule.action delete/move -> manage, pushing
        # move_to down to triggers. Self-neutralizing after the first run.
        try:
            existing_rules = [r[1] for r in conn.execute("PRAGMA table_info(rules)").fetchall()]
            if "move_to" in existing_rules:
                rows = conn.execute(
                    "SELECT id, move_to FROM rules WHERE action='move' AND move_to IS NOT NULL"
                ).fetchall()
                for rule_id, move_to in rows:
                    conn.execute("UPDATE triggers SET move_to=?, action='move' WHERE rule_id=?",
                                 (move_to, rule_id))
                conn.execute("UPDATE rules SET action='manage' WHERE action IN ('delete', 'move')")
        except sqlite3.OperationalError as e:
            log.warning(f"Migration: action/move_to data migration skipped: {e}")

        if current < SCHEMA_VERSION:
            conn.execute("DELETE FROM schema_version")
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))

        conn.commit()
