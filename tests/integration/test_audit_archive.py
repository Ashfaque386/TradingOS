"""REL-015 E15.3 (GLH-06, SEC-039) integration tests, against the REAL local `minio` compose
service -- no mocking, matching this codebase's convention of testing real local infrastructure
directly (see tests/integration/test_vault.py for the same pattern against real Vault).

Uses hand-built `AuditLog` ORM instances (never inserted into Postgres) rather than real
`write_audit_entry` rows: `archive_row`/`list_archived_ids` only ever read Python attributes or
talk to MinIO, never the database, so there's no need to touch the real, permanent, shared
audit_log table (see test_audit_tamper_detection.py's own module docstring on why that table is
handled so carefully elsewhere). Each test uses a random high `id` to avoid colliding with
another test run's objects in the same real bucket.
"""

import json
import random
from datetime import UTC, datetime

from botocore.client import Config
from botocore.exceptions import ClientError

from src.core import audit_archive
from src.core.audit_archive import _client, archive_row, ensure_bucket, list_archived_ids
from src.core.config import get_settings
from src.models.audit import AuditLog


def _fake_row(row_id: int) -> AuditLog:
    return AuditLog(
        id=row_id,
        actor_type="System",
        actor_id="worm-archive-test",
        action="TEST_EVENT",
        entity_type="Test",
        entity_id=None,
        before_state=None,
        after_state={"probe": row_id},
        prompt_snapshot=None,
        ip_address=None,
        created_at=datetime(2026, 1, 1),
        entry_hash="a" * 64,
        prev_entry_hash="0" * 64,
    )


def test_ensure_bucket_is_idempotent():
    ensure_bucket()
    ensure_bucket()  # must not raise the second time (bucket already exists)


def test_archive_row_then_list_archived_ids_reflects_it():
    ensure_bucket()
    row_id = random.randint(10**9, 2 * 10**9)
    row = _fake_row(row_id)

    assert row_id not in list_archived_ids()
    archive_row(row)
    assert row_id in list_archived_ids()


def test_archived_object_content_round_trips():
    ensure_bucket()
    row_id = random.randint(10**9, 2 * 10**9)
    row = _fake_row(row_id)
    archive_row(row)

    settings = get_settings()
    client = _client(settings)
    response = client.get_object(
        Bucket=settings.audit_archive_s3_bucket, Key=audit_archive._object_key(row_id)
    )
    stored = json.loads(response["Body"].read())
    assert stored["id"] == row_id
    assert stored["action"] == "TEST_EVENT"
    assert stored["after_state"] == {"probe": row_id}
    assert stored["entry_hash"] == "a" * 64


def test_a_real_delete_attempt_against_an_archived_object_version_fails():
    """The actual WORM guarantee, proven for real rather than merely asserted: MinIO's Object
    Lock (COMPLIANCE mode) must reject a genuine attempt to delete the specific stored version of
    an archived object before its retention window expires. A bare `delete_object` with no
    VersionId on a versioned bucket only creates a soft-delete marker (leaving the locked version
    untouched) and would misleadingly "succeed" -- targeting the exact VersionId is what actually
    exercises the lock."""
    ensure_bucket()
    row_id = random.randint(10**9, 2 * 10**9)
    row = _fake_row(row_id)

    settings = get_settings()
    client = _client(settings)
    key = audit_archive._object_key(row_id)

    put_response = client.put_object(
        Bucket=settings.audit_archive_s3_bucket,
        Key=key,
        Body=audit_archive._serialize(row),
        ContentType="application/json",
        ObjectLockMode="COMPLIANCE",
        ObjectLockRetainUntilDate=datetime(2033, 1, 1, tzinfo=UTC),
    )
    version_id = put_response["VersionId"]

    raised = False
    try:
        client.delete_object(Bucket=settings.audit_archive_s3_bucket, Key=key, VersionId=version_id)
    except ClientError:
        raised = True
    assert raised, (
        "deleting a specific locked object version should have been rejected by Object Lock -- "
        "if this passes, the WORM guarantee is not real"
    )


def test_endpoint_uses_path_style_addressing_for_minio_compatibility():
    """Not a business behavior per se, but a real config regression this module depends on:
    MinIO (unlike real AWS S3) requires path-style addressing -- virtual-hosted-style would try
    to resolve a DNS name like `audit-archive.minio`, which doesn't exist on this network."""
    settings = get_settings()
    client = _client(settings)
    config: Config = client.meta.config
    assert config.s3["addressing_style"] == "path"
