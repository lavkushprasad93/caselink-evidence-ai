"""Original files go to a MinIO bucket with Object Lock."""

import io
import logging
import uuid
from threading import Lock
from typing import BinaryIO, Protocol

from minio import Minio
from minio.commonconfig import COMPLIANCE, GOVERNANCE
from minio.error import MinioException, S3Error
from minio.objectlockconfig import DAYS, ObjectLockConfig
from urllib3.exceptions import HTTPError

from app.config import settings

log = logging.getLogger(__name__)


class StorageUnavailable(Exception):
    pass


class ObjectStore(Protocol):
    def put(self, key: str, stream: BinaryIO, size: int, content_type: str) -> str:
        """Store the object and return its s3:// URI."""
        ...


class MinioStore:
    def __init__(self, client: Minio, bucket: str) -> None:
        self.client, self.bucket = client, bucket

    def ensure_bucket(self, mode: str, days: int) -> None:
        if mode not in {GOVERNANCE, COMPLIANCE} or days < 1:
            raise ValueError("Object-lock retention must use a supported mode and positive days.")

        try:
            if not self.client.bucket_exists(self.bucket):
                try:
                    self.client.make_bucket(self.bucket, object_lock=True)
                except S3Error as exc:
                    if exc.code not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                        raise
                else:
                    self.client.set_object_lock_config(
                        self.bucket,
                        ObjectLockConfig(mode, days, DAYS),
                    )

            config = self.client.get_object_lock_config(self.bucket)
        except (MinioException, HTTPError, OSError) as exc:
            raise StorageUnavailable("Could not verify the MinIO bucket configuration.") from exc

        if config.mode is None:
            raise StorageUnavailable(
                f"Bucket '{self.bucket}' exists without default object-lock retention."
            )
        if config.mode != mode or config.duration != days or config.duration_unit != DAYS.title():
            raise StorageUnavailable(
                f"Bucket '{self.bucket}' retention does not match the configured policy."
            )
        log.info("Bucket %s has object lock (%s, %s days)", self.bucket, mode, days)

    def put(self, key: str, stream: BinaryIO, size: int, content_type: str) -> str:
        try:
            self.client.put_object(
                self.bucket,
                key,
                stream,
                size,
                content_type=content_type,
            )
        except (MinioException, HTTPError, OSError) as exc:
            raise StorageUnavailable("Could not store the object in MinIO.") from exc
        return f"s3://{self.bucket}/{key}"


def make_store() -> MinioStore:
    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    return MinioStore(client, settings.originals_bucket)


_ready_store: MinioStore | None = None
_store_lock = Lock()


def get_store() -> ObjectStore:
    """Return a store after verifying its bucket and default retention policy."""
    global _ready_store
    with _store_lock:
        if _ready_store is None:
            store = make_store()
            store.ensure_bucket(
                settings.originals_retention_mode,
                settings.originals_retention_days,
            )
            _ready_store = store
        return _ready_store


def selftest(store: MinioStore) -> None:
    """Upload, read, and attempt to delete a uniquely named object."""
    key = f"selftest/{uuid.uuid4()}.txt"
    data = b"caselink storage self-test"
    result = store.client.put_object(
        store.bucket,
        key,
        io.BytesIO(data),
        len(data),
        content_type="text/plain",
    )
    if not result.version_id:
        raise SystemExit("FAIL: MinIO did not return an object version ID.")
    print(f"  upload ok          ({key})")

    response = store.client.get_object(store.bucket, key, version_id=result.version_id)
    try:
        stored = response.read()
    finally:
        response.close()
        response.release_conn()
    assert stored == data, "stored bytes differ from uploaded bytes"
    print("  read back ok       (bytes identical)")

    try:
        store.client.remove_object(store.bucket, key, version_id=result.version_id)
    except S3Error as exc:
        retained_invalid_request = (
            exc.code == "InvalidRequest" and "worm protected" in (exc.message or "").casefold()
        )
        if (
            exc.code not in {"AccessDenied", "AccessDeniedByRetention"}
            and not retained_invalid_request
        ):
            raise
        print(f"  delete refused     ({exc.code})")
    else:
        raise SystemExit(
            "FAIL: the object version was deleted. Object lock is NOT protecting this bucket."
        )


if __name__ == "__main__":
    import logging
    import sys

    logging.basicConfig(level=logging.INFO)
    store_ = make_store()
    store_.ensure_bucket(settings.originals_retention_mode, settings.originals_retention_days)
    print(f"Bucket '{settings.originals_bucket}' is ready with object lock.")
    if "--selftest" in sys.argv:
        selftest(store_)
        print("Storage self-test passed.")
