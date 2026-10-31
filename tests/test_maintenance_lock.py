"""Tests for the cross-process maintenance lock (P2 #4)."""
import subprocess
import sys
import textwrap


def test_second_acquire_in_same_process_fails(db, engine_mod):
    assert engine_mod.acquire_maintenance_lock() is True
    try:
        # A second acquire in the same process must fail (threading.Lock).
        assert engine_mod.acquire_maintenance_lock() is False
    finally:
        engine_mod.release_maintenance_lock()
    # After release it can be acquired again.
    assert engine_mod.acquire_maintenance_lock() is True
    engine_mod.release_maintenance_lock()


def test_guard_yields_false_when_held(db, engine_mod):
    with engine_mod.maintenance_guard() as a:
        assert a is True
        with engine_mod.maintenance_guard() as b:
            assert b is False
    # Fully released now.
    with engine_mod.maintenance_guard() as c:
        assert c is True


def test_lock_is_cross_process(db, engine_mod, tmp_path):
    """A second OS process must not be able to acquire the same file lock."""
    lock_path = engine_mod._lock_file_path()

    # Hold the file lock in a child process, then try to acquire here.
    holder = subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(f"""
            import fcntl, time, sys
            fh = open({lock_path!r}, "w")
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            sys.stdout.write("locked\\n"); sys.stdout.flush()
            time.sleep(5)
        """)],
        stdout=subprocess.PIPE,
    )
    try:
        # Wait for the child to confirm it holds the lock.
        line = holder.stdout.readline()
        assert line.strip() == b"locked"

        # Now our acquire must fail because the child holds the file lock.
        acquired = engine_mod.acquire_maintenance_lock()
        if acquired:
            engine_mod.release_maintenance_lock()
        assert acquired is False, "file lock must block a second process"
    finally:
        holder.terminate()
        holder.wait(timeout=5)

    # Once the child is gone, the OS releases the lock and we can acquire.
    assert engine_mod.acquire_maintenance_lock() is True
    engine_mod.release_maintenance_lock()
