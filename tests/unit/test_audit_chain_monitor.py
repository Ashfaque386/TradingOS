"""REL-031 (SEC-040): pure-function unit coverage for the archive-side hash recomputation --
no DB or network needed. `run_divergence_check`'s full behavior (real Postgres + real MinIO) is
covered by tests/integration/test_audit_chain_monitor.py, matching this codebase's own convention
of testing SQLAlchemy/S3-backed logic against real local infrastructure, not mocks."""

import uuid
from datetime import datetime

from src.core.audit import recompute_entry_hash
from src.core.audit_chain_monitor import _recompute_archived_entry_hash


def _archived_dict(**overrides: object) -> dict[str, object]:
    entity_id = uuid.uuid4()
    created_at = datetime(2026, 8, 8, 12, 0, 0)
    base: dict[str, object] = {
        "actor_type": "System",
        "actor_id": "chain-monitor-unit-test",
        "action": "TEST_EVENT",
        "entity_type": "Test",
        "entity_id": str(entity_id),
        "before_state": None,
        "after_state": {"n": 1},
        "prompt_snapshot": None,
        "ip_address": "127.0.0.1",
        "created_at": created_at.isoformat(),
        "prev_entry_hash": "0" * 64,
        "entry_hash": recompute_entry_hash(
            actor_type="System",
            actor_id="chain-monitor-unit-test",
            action="TEST_EVENT",
            entity_type="Test",
            entity_id=entity_id,
            before_state=None,
            after_state={"n": 1},
            prompt_snapshot=None,
            ip_address="127.0.0.1",
            created_at=created_at,
            prev_hash="0" * 64,
        ),
    }
    base.update(overrides)
    return base


def test_recompute_archived_entry_hash_matches_the_original_write_time_hash():
    archived = _archived_dict()

    assert _recompute_archived_entry_hash(archived) == archived["entry_hash"]


def test_recompute_archived_entry_hash_detects_a_tampered_after_state_field():
    archived = _archived_dict()
    archived["after_state"] = {"n": 9999}

    assert _recompute_archived_entry_hash(archived) != archived["entry_hash"]


def test_recompute_archived_entry_hash_detects_a_tampered_prev_entry_hash_field():
    archived = _archived_dict()
    archived["prev_entry_hash"] = "f" * 64

    assert _recompute_archived_entry_hash(archived) != archived["entry_hash"]


def test_recompute_archived_entry_hash_handles_a_null_entity_id_and_ip_address():
    archived = _archived_dict(entity_id=None, ip_address=None)
    # entry_hash above was computed with a real entity_id/ip_address -- recompute it fresh for
    # the null case so this test proves the null path itself round-trips correctly.
    created_at = datetime.fromisoformat(str(archived["created_at"]))
    archived["entry_hash"] = recompute_entry_hash(
        actor_type=str(archived["actor_type"]),
        actor_id=str(archived["actor_id"]),
        action=str(archived["action"]),
        entity_type=str(archived["entity_type"]),
        entity_id=None,
        before_state=None,
        after_state={"n": 1},
        prompt_snapshot=None,
        ip_address=None,
        created_at=created_at,
        prev_hash=str(archived["prev_entry_hash"]),
    )

    assert _recompute_archived_entry_hash(archived) == archived["entry_hash"]
