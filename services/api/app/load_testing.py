"""Deterministic company-neutral fixtures and bounded local load measurements."""

import json
import math
import queue
import threading
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from random import Random
from statistics import mean
from typing import Any

DATA_CLASSIFICATION = "synthetic-company-neutral"
MAX_DOCUMENTS = 10_000
MAX_CONCURRENCY = 32
MAX_REQUESTS = 100_000
MAX_DURATION_SECONDS = 3_600
EXPENSIVE_DOCUMENT_THRESHOLD = 5_000


@dataclass(frozen=True)
class SyntheticDocument:
    id: str
    filename: str
    text: str
    sha256: str


def synthetic_document(index: int, seed: int) -> SyntheticDocument:
    token = sha256(f"week6:{seed}:{index}".encode()).hexdigest()[:12].upper()
    text = (
        f"Company-neutral synthetic load document {index}. "
        f"The deterministic marker is DEMO-{token}. Recovery group is {index % 97}."
    )
    return SyntheticDocument(
        id=f"synthetic-load-{index:05d}",
        filename=f"synthetic-load-{index:05d}.txt",
        text=text,
        sha256=sha256(text.encode()).hexdigest(),
    )


def generate_documents(count: int, seed: int = 606) -> list[SyntheticDocument]:
    if not 1 <= count <= MAX_DOCUMENTS:
        raise ValueError(f"documents must be between 1 and {MAX_DOCUMENTS}")
    return [synthetic_document(index, seed) for index in range(count)]


def write_manifest(path: Path, documents: list[SyntheticDocument], seed: int) -> None:
    payload = {
        "schema_version": 1,
        "data_classification": DATA_CLASSIFICATION,
        "seed": seed,
        "count": len(documents),
        "documents": [asdict(document) for document in documents],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, math.ceil(quantile * len(ordered)) - 1)
    return ordered[rank]


def latency_summary(values: list[float]) -> dict[str, float | None]:
    return {
        "p50_ms": percentile(values, 0.50),
        "p95_ms": percentile(values, 0.95),
        "p99_ms": percentile(values, 0.99),
        "mean_ms": mean(values) if values else None,
    }


def validate_limits(
    documents: int, concurrency: int, requests: int, duration_seconds: int
) -> None:
    bounds = (
        ("documents", documents, 1, MAX_DOCUMENTS),
        ("concurrency", concurrency, 1, MAX_CONCURRENCY),
        ("requests", requests, 1, MAX_REQUESTS),
        ("duration_seconds", duration_seconds, 1, MAX_DURATION_SECONDS),
    )
    for name, value, minimum, maximum in bounds:
        if not minimum <= value <= maximum:
            raise ValueError(f"{name} must be between {minimum} and {maximum}")


def run_local_microbenchmark(
    *, documents: int, concurrency: int, requests: int, seed: int, duration_seconds: int
) -> dict[str, Any]:
    """Measure only in-process generation/index/search behavior; no capacity claim."""
    validate_limits(documents, concurrency, requests, duration_seconds)
    started = time.perf_counter()
    tracemalloc.start()
    fixtures = generate_documents(documents, seed)
    work: queue.Queue[SyntheticDocument] = queue.Queue(maxsize=max(concurrency * 4, 1))
    index: dict[str, SyntheticDocument] = {}
    index_lock = threading.Lock()
    maximum_depth = 0
    producer_done = threading.Event()

    def producer() -> None:
        nonlocal maximum_depth
        for document in fixtures:
            work.put(document)
            maximum_depth = max(maximum_depth, work.qsize())
        producer_done.set()

    def consumer() -> None:
        while not producer_done.is_set() or not work.empty():
            try:
                document = work.get(timeout=0.01)
            except queue.Empty:
                continue
            with index_lock:
                index[document.text.rsplit("DEMO-", 1)[-1].split(".", 1)[0]] = document
            work.task_done()

    ingest_started = time.perf_counter()
    producer_thread = threading.Thread(target=producer)
    workers = [threading.Thread(target=consumer) for _ in range(concurrency)]
    producer_thread.start()
    for worker in workers:
        worker.start()
    producer_thread.join()
    for worker in workers:
        worker.join()
    ingest_seconds = time.perf_counter() - ingest_started

    random = Random(seed)
    markers = list(index)
    retrieval_latencies: list[float] = []
    agent_latencies: list[float] = []
    errors = 0
    recovered_errors = 0
    deadline = started + duration_seconds

    def request_once(number: int) -> tuple[float, float, bool]:
        request_started = time.perf_counter()
        marker = markers[random.randrange(len(markers))]
        should_retry = number > 0 and number % 101 == 0
        if should_retry:
            recovery_started = time.perf_counter()
            document = index.get(marker)
            retrieval_ms = (time.perf_counter() - recovery_started) * 1000
        else:
            document = index.get(marker)
            retrieval_ms = (time.perf_counter() - request_started) * 1000
        if document is None:
            return retrieval_ms, (time.perf_counter() - request_started) * 1000, False
        _answer = f"Grounded synthetic answer from {document.id}."
        return retrieval_ms, (time.perf_counter() - request_started) * 1000, should_retry

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = []
        for number in range(requests):
            if time.perf_counter() >= deadline:
                break
            futures.append(executor.submit(request_once, number))
        for future in as_completed(futures):
            try:
                retrieval_ms, agent_ms, recovered = future.result()
                retrieval_latencies.append(retrieval_ms)
                agent_latencies.append(agent_ms)
                recovered_errors += int(recovered)
            except Exception:
                errors += 1
    elapsed = time.perf_counter() - started
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    completed = len(agent_latencies)
    return {
        "schema_version": 1,
        "data_classification": DATA_CLASSIFICATION,
        "mode": "local-deterministic-microbenchmark",
        "scope": {
            "documents": documents,
            "concurrency": concurrency,
            "requested_requests": requests,
            "completed_requests": completed,
            "duration_limit_seconds": duration_seconds,
        },
        "measurements": {
            "ingestion": {
                "seconds": ingest_seconds,
                "documents_per_second": documents / ingest_seconds if ingest_seconds else None,
            },
            "queue": {"maximum_observed_depth": maximum_depth},
            "retrieval": latency_summary(retrieval_latencies),
            "agent": latency_summary(agent_latencies),
            "throughput_requests_per_second": completed / elapsed if elapsed else None,
            "error_rate": errors / completed if completed else 1.0,
            "recovered_injected_errors": recovered_errors,
            "resource": {"tracemalloc_peak_bytes": peak},
            "index": {
                "entries": len(index),
                "serialized_bytes": sum(len(json.dumps(asdict(item))) for item in index.values()),
            },
        },
        "limitations": [
            "This is an in-process deterministic microbenchmark, not a Compose or production "
            "capacity result.",
            "It does not measure PostgreSQL, Redis, Qdrant, MinIO, network, container, "
            "or model latency.",
        ],
    }
