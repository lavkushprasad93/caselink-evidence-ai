import logging
from collections.abc import Callable

from celery import Celery
from kombu.exceptions import OperationalError
from redis.exceptions import RedisError

from app.config import settings

log = logging.getLogger(__name__)

celery_app = Celery("caselink", broker=settings.redis_url)
celery_app.conf.update(
    broker_connection_timeout=settings.redis_publish_timeout_seconds,
    broker_connection_max_retries=0,
    broker_transport_options={
        "socket_connect_timeout": settings.redis_publish_timeout_seconds,
        "socket_timeout": settings.redis_publish_timeout_seconds,
    },
    task_ignore_result=True,
    task_publish_retry=False,
)


@celery_app.task(name="app.jobs.process_document")
def process_document(document_id: str) -> None:
    log.info("Document processing queued for %s", document_id)


def enqueue(document_id: str) -> bool:
    try:
        process_document.apply_async(args=[document_id], retry=False)
    except (OperationalError, RedisError) as exc:
        log.warning("Could not enqueue document %s: %s", document_id, exc)
        return False
    return True


def get_enqueue() -> Callable[[str], bool]:
    return enqueue
