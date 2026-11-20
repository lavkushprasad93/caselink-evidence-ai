from typing import Any

from kombu.exceptions import OperationalError

from app import jobs


def test_enqueue_reports_success_when_task_is_published(monkeypatch: Any) -> None:
    monkeypatch.setattr(jobs.process_document, "apply_async", lambda **_kwargs: None)

    assert jobs.enqueue("document-1") is True


def test_enqueue_returns_false_on_broker_failure(monkeypatch: Any) -> None:
    def fail_publish(**_kwargs: Any) -> None:
        raise OperationalError("Redis unavailable")

    monkeypatch.setattr(jobs.process_document, "apply_async", fail_publish)

    assert jobs.enqueue("document-1") is False
