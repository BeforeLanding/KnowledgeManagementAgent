"""Liveness and bounded dependency readiness checks."""

from collections.abc import Callable
from dataclasses import asdict, dataclass
from math import ceil
from time import perf_counter

from qdrant_client import QdrantClient
from redis import Redis
from sqlalchemy import text

from .config import get_settings
from .database import engine
from .observability import READINESS
from .storage import store


@dataclass(frozen=True)
class DependencyStatus:
    ready: bool
    latency_ms: int
    code: str


Check = Callable[[], None]


def _postgres() -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def _redis() -> None:
    settings = get_settings()
    client = Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=settings.readiness_timeout_seconds,
        socket_timeout=settings.readiness_timeout_seconds,
    )
    client.ping()


def _qdrant() -> None:
    settings = get_settings()
    QdrantClient(
        url=settings.qdrant_url, timeout=max(1, ceil(settings.readiness_timeout_seconds))
    ).get_collections()


def _minio() -> None:
    store.client.bucket_exists(store.bucket)


def dependency_checks() -> dict[str, Check]:
    return {"postgres": _postgres, "redis": _redis, "qdrant": _qdrant, "minio": _minio}


def readiness_report(checks: dict[str, Check] | None = None) -> dict:
    components: dict[str, dict] = {}
    for name, check in (checks or dependency_checks()).items():
        started = perf_counter()
        try:
            check()
            status = DependencyStatus(True, int((perf_counter() - started) * 1000), "READY")
        except Exception:
            status = DependencyStatus(False, int((perf_counter() - started) * 1000), "UNAVAILABLE")
        READINESS.labels(name).set(int(status.ready))
        components[name] = asdict(status)
    overall = "ready" if all(item["ready"] for item in components.values()) else "not_ready"
    return {"status": overall, "components": components}
