"""Accounts, permissions and the append-only audit store."""

import sqlite3

import pytest

from synapse_h.audit import AuditLog
from synapse_h.audit_store import SQLiteAuditStore as _Store
from synapse_h.auth import MAX_FAILURES, PERMISSIONS, UserStore, hash_password, verify_password


_open: list = []


def SQLiteAuditStore(path):
    store = _Store(path)
    _open.append(store)
    return store


@pytest.fixture(autouse=True)
def _close_stores():
    yield
    while _open:
        _open.pop().close()


def fast_hash(pw):
    return hash_password(pw, iterations=1000)


def test_password_hash_round_trip_and_rejects_garbage():
    h = fast_hash("correct horse battery")
    assert h.startswith("pbkdf2_sha256$1000$") and "correct" not in h
    assert verify_password("correct horse battery", h)
    assert not verify_password("wrong", h)
    assert not verify_password("x", "not-a-hash") and not verify_password("x", "md5$1$a$b")


def test_roles_limit_what_users_can_do():
    store = UserStore.from_mapping({
        "kim": {"name": "전원 간호사 김", "role": "coordinator", "password_hash": fast_hash("pw-kim-123456")},
        "lee": {"name": "조회", "role": "viewer", "password_hash": fast_hash("pw-lee-123456")},
    })
    kim = store.authenticate("kim", "pw-kim-123456")
    lee = store.authenticate("lee", "pw-lee-123456")
    assert kim.can("decide") and not kim.can("export_audit")
    assert lee.can("view") and not lee.can("decide")
    assert PERMISSIONS["supervisor"] >= PERMISSIONS["coordinator"] >= PERMISSIONS["viewer"]
    assert store.authenticate("kim", "nope") is None and store.authenticate("ghost", "x") is None


def test_repeated_failures_lock_the_account():
    store = UserStore.from_mapping({"kim": {"role": "coordinator", "password_hash": fast_hash("pw-kim-123456")}})
    for i in range(MAX_FAILURES):
        assert store.authenticate("kim", "wrong", now=1000 + i) is None
    assert store.authenticate("kim", "pw-kim-123456", now=1010) is None  # locked
    assert store.authenticate("kim", "pw-kim-123456", now=1000 + 301) is not None  # lockout expired


def test_invalid_account_config_is_rejected():
    with pytest.raises(ValueError):
        UserStore.from_mapping({"x": {"role": "admin", "password_hash": "h"}})
    assert not UserStore.from_mapping({}).enabled


def test_store_persists_and_reloads(tmp_path):
    path = tmp_path / "audit.db"
    log = AuditLog(store=SQLiteAuditStore(path))
    log.case_opened("A-1", "visible", "kim", at=100)
    log.decision("A-1", "H1", 1, mode="visible", user="kim", at=110)
    log.contact_outcome("A-1", "H1", True, at=160)
    reloaded = AuditLog.from_store(SQLiteAuditStore(path))
    assert [e["event"] for e in reloaded.events] == ["case_opened", "select", "contact_outcome"]
    assert [e["seq"] for e in reloaded.events] == [1, 2, 3]
    assert reloaded.metrics()["first_contact_accept"] == 1.0
    assert reloaded.store.verify() == []


def test_updates_and_deletes_are_blocked(tmp_path):
    store = SQLiteAuditStore(tmp_path / "audit.db")
    AuditLog(store=store).case_opened("A-1", "visible", at=1)
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        store._conn.execute("UPDATE audit_events SET event='x'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        store._conn.execute("DELETE FROM audit_events")


def test_tampering_outside_the_app_breaks_the_chain(tmp_path):
    path = tmp_path / "audit.db"
    log = AuditLog(store=SQLiteAuditStore(path))
    for i in range(3):
        log.case_opened(f"A-{i}", "visible", at=i)
    with sqlite3.connect(path) as raw:
        raw.execute("DROP TRIGGER audit_no_update")
        raw.execute("UPDATE audit_events SET payload = replace(payload, 'A-1', 'A-9') WHERE seq = 2")
    raw.close()
    problems = SQLiteAuditStore(path).verify()
    assert problems == ["seq 2: content does not match its hash"]


def test_two_sessions_share_one_sequence(tmp_path):
    path = tmp_path / "audit.db"
    a, b = AuditLog(store=SQLiteAuditStore(path)), AuditLog(store=SQLiteAuditStore(path))
    a.case_opened("A-1", "visible", at=1)
    b.case_opened("B-1", "visible", at=2)
    a.case_opened("A-2", "visible", at=3)
    assert [e["seq"] for e in SQLiteAuditStore(path).load()] == [1, 2, 3]
    assert SQLiteAuditStore(path).verify() == []
