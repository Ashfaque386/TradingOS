"""REL-015 E15.3 (GLH-06, SEC-039): WORM (write-once-read-many) audit archive tier.

A real, independent second immutability layer for AUDIT_LOG (src/models/audit.py), on top of --
not instead of -- the existing Postgres BEFORE UPDATE OR DELETE trigger (the b3c4d5e6f7a8
migration). `src/core/audit.py`'s own module docstring named this as a real, previously-open
gap: "no object storage with write-once guarantees exists in this environment's docker-compose
stack." MinIO's S3-compatible API supports real Object Lock (the same mechanism AWS S3 Object
Lock uses) once a bucket is created with it enabled -- this closes that gap with a real (if
locally-hosted) WORM store, not a simulated one.

Object Lock must be enabled at bucket-creation time -- the S3/MinIO API has no "add lock to an
existing bucket" operation -- so `ensure_bucket()` below is the one-time setup this requires,
self-healing on every run the same way `vault.ensure_kv_engine()` self-heals its own one-time
Vault setup.

Retention: COMPLIANCE mode (not even this bucket's own root credentials can shorten or delete the
lock before it expires -- stronger than GOVERNANCE mode, which a sufficiently-privileged
principal can override) for 7 years from archive time. This is a proportionate stand-in for
SEBI's multi-year broker/audit recordkeeping expectations, not itself a certified legal retention
figure -- a real production deployment would confirm the exact number with compliance counsel.

Idempotency by object existence, not a DB marker column: this module and its caller
(scripts/archive_audit_log.py) never write to `audit_log` itself -- the object key
`audit-log/{id:012d}.json` already existing in the bucket IS the "this row was archived" record,
consistent with audit_log genuinely never receiving an UPDATE from anything, ever (adding an
`archived_at` marker column would itself require an UPDATE the Postgres trigger already,
correctly, refuses to allow).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.config import Settings, get_settings
from src.models.audit import AuditLog

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client

_OBJECT_PREFIX = "audit-log/"
_RETENTION = timedelta(days=365 * 7)
_ARCHIVE_AGE = timedelta(hours=24)


def _client(settings: Settings) -> S3Client:
    return boto3.client(
        "s3",
        endpoint_url=settings.audit_archive_s3_endpoint,
        aws_access_key_id=settings.audit_archive_s3_access_key,
        aws_secret_access_key=settings.audit_archive_s3_secret_key,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        region_name="us-east-1",
    )


def ensure_bucket(settings: Settings | None = None) -> None:
    """Idempotent: creates the Object-Lock-enabled bucket if it doesn't exist yet. Safe to call
    on every run (see module docstring)."""
    settings = settings or get_settings()
    client = _client(settings)
    try:
        client.head_bucket(Bucket=settings.audit_archive_s3_bucket)
        return  # already exists
    except ClientError:
        pass
    client.create_bucket(Bucket=settings.audit_archive_s3_bucket, ObjectLockEnabledForBucket=True)


def _object_key(row_id: int) -> str:
    return f"{_OBJECT_PREFIX}{row_id:012d}.json"


def _serialize(row: AuditLog) -> bytes:
    payload: dict[str, Any] = {
        "id": row.id,
        "actor_type": row.actor_type,
        "actor_id": row.actor_id,
        "action": row.action,
        "entity_type": row.entity_type,
        "entity_id": str(row.entity_id) if row.entity_id is not None else None,
        "before_state": row.before_state,
        "after_state": row.after_state,
        "prompt_snapshot": row.prompt_snapshot,
        # INET columns deserialize as ipaddress.IPv4Address/IPv6Address, not str -- confirmed the
        # hard way against real archived rows (110 real "Object of type IPv4Address is not JSON
        # serializable" failures on the first live run against production audit_log data).
        # src/core/audit.py's own _canonical_payload does the same str() conversion for the same
        # reason.
        "ip_address": str(row.ip_address) if row.ip_address is not None else None,
        "created_at": row.created_at.isoformat(),
        "entry_hash": row.entry_hash,
        "prev_entry_hash": row.prev_entry_hash,
    }
    return json.dumps(payload, sort_keys=True).encode("utf-8")


def archive_row(row: AuditLog, *, settings: Settings | None = None) -> None:
    """Writes one audit_log row as an Object-Lock-protected object. Real regulatory-grade
    immutability: COMPLIANCE mode means not even this bucket's root credentials can shorten the
    retention window or delete the object before it expires -- verified for real by
    tests/integration/test_audit_archive.py's own delete-attempt test, not just asserted here."""
    settings = settings or get_settings()
    client = _client(settings)
    retain_until = datetime.now(UTC) + _RETENTION
    client.put_object(
        Bucket=settings.audit_archive_s3_bucket,
        Key=_object_key(row.id),
        Body=_serialize(row),
        ContentType="application/json",
        ObjectLockMode="COMPLIANCE",
        ObjectLockRetainUntilDate=retain_until,
    )


def fetch_archived_row(row_id: int, *, settings: Settings | None = None) -> dict[str, Any] | None:
    """REL-031 (SEC-040): reads one archived object's real JSON body back out of the WORM bucket
    -- `src/core/audit_chain_monitor.py` uses this to independently recompute the archived copy's
    own hash and to cross-check it against the live table's stored `entry_hash` for the same id.
    Returns `None` (not an exception) for a missing key, the one expected "not archived yet" case
    a caller iterating `list_archived_ids()` output would never actually hit, but a caller probing
    an arbitrary id might."""
    settings = settings or get_settings()
    client = _client(settings)
    try:
        response = client.get_object(
            Bucket=settings.audit_archive_s3_bucket, Key=_object_key(row_id)
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
            return None
        raise
    body: dict[str, Any] = json.loads(response["Body"].read())
    return body


def list_archived_ids(settings: Settings | None = None) -> set[int]:
    """Real S3 ListObjectsV2 pagination -- every row id already archived, so the caller can skip
    re-uploading them (idempotency by object existence, see module docstring)."""
    settings = settings or get_settings()
    client = _client(settings)
    ids: set[int] = set()
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=settings.audit_archive_s3_bucket, Prefix=_OBJECT_PREFIX):
        for obj in page.get("Contents", []):
            stem = obj["Key"][len(_OBJECT_PREFIX) : -len(".json")]
            ids.add(int(stem))
    return ids


def archive_pending_rows(session: Session, *, settings: Settings | None = None) -> tuple[int, int]:
    """REL-081: the real nightly archive cycle -- moved here (unchanged) from
    `scripts/archive_audit_log.py::main()`'s own inline logic, so both that script (kept as a
    manual/CLI escape hatch) and the in-process scheduler job
    (`src/agents/scheduler.py::run_audit_archive_job`) call the exact same real logic. Ensures
    the WORM bucket exists, finds every real `audit_log` row older than `_ARCHIVE_AGE` not yet
    archived (idempotent by object existence, see module docstring), and archives each --one
    row's real failure never stops the rest. Returns `(archived_count, failure_count)`, both
    honest counts, never fabricated."""
    ensure_bucket(settings)

    # AuditLog.created_at is TIMESTAMP WITHOUT TIME ZONE, storing naive-UTC wall-clock values
    # (see src/core/audit.py's _canonical_payload docstring for the same convention) -- comparing
    # against a naive-UTC cutoff, not an aware one, keeps this query correct.
    cutoff = datetime.now(UTC).replace(tzinfo=None) - _ARCHIVE_AGE
    rows = list(
        session.scalars(
            select(AuditLog).where(AuditLog.created_at < cutoff).order_by(AuditLog.id.asc())
        )
    )
    if not rows:
        return (0, 0)

    already_archived = list_archived_ids(settings)
    pending = [row for row in rows if row.id not in already_archived]
    if not pending:
        return (0, 0)

    archived_count = 0
    failure_count = 0
    for row in pending:
        try:
            archive_row(row, settings=settings)
            archived_count += 1
        except Exception:  # noqa: BLE001 -- one row's failure must not stop the rest
            failure_count += 1
    return (archived_count, failure_count)
