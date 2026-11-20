from io import BytesIO
from typing import Any

import pytest
from minio.commonconfig import GOVERNANCE
from minio.objectlockconfig import DAYS, ObjectLockConfig

from app.storage import MinioStore, StorageUnavailable


class FakeMinio:
    def __init__(self, exists: bool = False, lock_config: ObjectLockConfig | None = None) -> None:
        self.exists = exists
        self.lock_config = lock_config
        self.created_with_lock = False
        self.put_args: tuple[Any, ...] | None = None

    def bucket_exists(self, _bucket: str) -> bool:
        return self.exists

    def make_bucket(self, _bucket: str, object_lock: bool = False) -> None:
        self.exists = True
        self.created_with_lock = object_lock

    def set_object_lock_config(self, _bucket: str, config: ObjectLockConfig) -> None:
        self.lock_config = config

    def get_object_lock_config(self, _bucket: str) -> ObjectLockConfig:
        if self.lock_config is None:
            return ObjectLockConfig(None, None, None)
        return self.lock_config

    def put_object(
        self,
        bucket: str,
        key: str,
        stream: BytesIO,
        size: int,
        content_type: str,
    ) -> None:
        self.put_args = (bucket, key, stream.read(), size, content_type)


def test_new_bucket_is_created_with_default_retention() -> None:
    client = FakeMinio()

    MinioStore(client, "originals").ensure_bucket(GOVERNANCE, 1)

    assert client.created_with_lock
    assert client.lock_config == ObjectLockConfig(GOVERNANCE, 1, DAYS)


def test_existing_bucket_without_default_retention_is_rejected() -> None:
    store = MinioStore(FakeMinio(exists=True), "originals")

    with pytest.raises(StorageUnavailable, match="without default object-lock retention"):
        store.ensure_bucket(GOVERNANCE, 1)


def test_existing_bucket_with_different_policy_is_rejected() -> None:
    client = FakeMinio(
        exists=True,
        lock_config=ObjectLockConfig(GOVERNANCE, 2, DAYS),
    )

    with pytest.raises(StorageUnavailable, match="does not match"):
        MinioStore(client, "originals").ensure_bucket(GOVERNANCE, 1)


def test_put_streams_object_and_returns_uri() -> None:
    client = FakeMinio()
    store = MinioStore(client, "originals")

    uri = store.put("case/file.pdf", BytesIO(b"pdf"), 3, "application/pdf")

    assert uri == "s3://originals/case/file.pdf"
    assert client.put_args == (
        "originals",
        "case/file.pdf",
        b"pdf",
        3,
        "application/pdf",
    )


def test_unsupported_retention_policy_is_rejected() -> None:
    store = MinioStore(FakeMinio(), "originals")

    with pytest.raises(ValueError, match="supported mode"):
        store.ensure_bucket("NONE", 1)
