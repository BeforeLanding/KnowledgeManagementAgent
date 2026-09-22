"""Run bounded Week 6 load plans and deterministic local microbenchmarks.

Compose and production-like modes are explicit placeholders for externally measured
runs; they never emit invented latency, resource, or index values.
"""

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

from app.load_testing import (  # noqa: E402
    EXPENSIVE_DOCUMENT_THRESHOLD,
    generate_documents,
    latency_summary,
    run_local_microbenchmark,
    validate_limits,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=("plan", "local", "compose", "production"), default="plan"
    )
    parser.add_argument("--documents", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--duration-seconds", type=int, default=60)
    parser.add_argument("--seed", type=int, default=606)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--email")
    parser.add_argument("--password-env", default="KMA_LOAD_PASSWORD")
    parser.add_argument("--space-id")
    parser.add_argument("--max-error-rate", type=float, default=0.0)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-expensive", action="store_true")
    parser.add_argument("--allow-production-like", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def _request_with_retry(
    client: httpx.Client, method: str, path: str, *, attempts: int = 2, **kwargs: Any
) -> tuple[httpx.Response, bool]:
    recovered = False
    for attempt in range(attempts):
        try:
            response = client.request(method, path, **kwargs)
            if response.status_code < 500:
                return response, recovered
        except (httpx.TimeoutException, httpx.NetworkError):
            response = None
        if attempt + 1 < attempts:
            recovered = True
    if response is None:
        raise RuntimeError("bounded request failed after retry")
    return response, recovered


def run_http_load(args: argparse.Namespace) -> dict[str, Any]:
    """Execute an explicitly enabled Compose or production-like HTTP measurement."""
    password = os.getenv(args.password_env, "")
    if not args.email or not password:
        raise ValueError(
            f"--email and secret environment variable {args.password_env} are required"
        )
    if args.mode == "production" and not args.base_url.lower().startswith("https://"):
        raise ValueError("production-like mode requires an HTTPS base URL")
    timeout = httpx.Timeout(30.0, connect=5.0)
    started = time.perf_counter()
    deadline = started + args.duration_seconds
    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=timeout) as client:
        login = client.post(
            "/api/v1/auth/login", json={"email": args.email, "password": password}
        )
        login.raise_for_status()
        client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
        documents = generate_documents(args.documents, args.seed)
        upload_latencies: list[float] = []
        uploaded_ids: list[str] = []
        errors = 0
        recovered = 0

        if args.mode == "compose":
            spaces = client.get("/api/v1/spaces")
            spaces.raise_for_status()
            allowed = [item for item in spaces.json() if item["role"] in {"admin", "curator"}]
            space_id = args.space_id or (allowed[0]["id"] if allowed else None)
            if not space_id:
                raise ValueError("no curator/admin space is available; pass --space-id")

            def upload(document):
                request_started = time.perf_counter()
                response, did_retry = _request_with_retry(
                    client,
                    "POST",
                    "/api/v1/documents",
                    data={"space_id": space_id},
                    files={"file": (document.filename, document.text, "text/plain")},
                )
                return response, (time.perf_counter() - request_started) * 1000, did_retry

            with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
                futures = [executor.submit(upload, document) for document in documents]
                for future in as_completed(futures):
                    response, latency, did_retry = future.result()
                    upload_latencies.append(latency)
                    recovered += int(did_retry)
                    if response.status_code == 202:
                        uploaded_ids.append(response.json()["id"])
                    else:
                        errors += 1

            ready = 0
            terminal_failures = 0
            maximum_queued = 0
            while uploaded_ids and time.perf_counter() < deadline:
                listing = client.get("/api/v1/documents")
                listing.raise_for_status()
                selected = [item for item in listing.json() if item["id"] in set(uploaded_ids)]
                ready = sum(item["status"] == "ready" for item in selected)
                maximum_queued = max(
                    maximum_queued,
                    sum(item["status"] in {"queued", "parsing", "indexing"} for item in selected),
                )
                terminal_failures = sum(
                    item["status"]
                    in {"failed_retryable", "failed_permanent", "needs_manual_processing"}
                    for item in selected
                )
                if ready + terminal_failures >= len(uploaded_ids):
                    break
                time.sleep(0.5)
        else:
            ready = terminal_failures = maximum_queued = 0

        retrieval_latencies: list[float] = []
        agent_latencies: list[float] = []

        def mixed_request(number: int):
            document = documents[number % len(documents)]
            marker = document.text.rsplit("DEMO-", 1)[-1].split(".", 1)[0]
            path = "/api/v1/search" if number % 2 == 0 else "/api/v1/chat"
            request_started = time.perf_counter()
            response, did_retry = _request_with_retry(
                client, "POST", path, json={"query": f"What is DEMO-{marker}?"}
            )
            return path, response, (time.perf_counter() - request_started) * 1000, did_retry

        with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            futures = []
            for number in range(args.requests):
                if time.perf_counter() >= deadline:
                    break
                futures.append(executor.submit(mixed_request, number))
            for future in as_completed(futures):
                path, response, latency, did_retry = future.result()
                recovered += int(did_retry)
                if response.status_code >= 400:
                    errors += 1
                elif path.endswith("search"):
                    retrieval_latencies.append(latency)
                else:
                    agent_latencies.append(latency)
    elapsed = time.perf_counter() - started
    completed = len(upload_latencies) + len(retrieval_latencies) + len(agent_latencies)
    error_rate = errors / max(1, completed + errors)
    return {
        "schema_version": 1,
        "data_classification": "synthetic-company-neutral",
        "mode": f"{args.mode}-http-integration",
        "scope": {
            "documents": args.documents,
            "concurrency": args.concurrency,
            "requested_requests": args.requests,
            "duration_limit_seconds": args.duration_seconds,
        },
        "measurements": {
            "ingestion": {
                **latency_summary(upload_latencies),
                "uploaded": len(uploaded_ids),
                "ready": ready,
                "terminal_failures": terminal_failures,
            },
            "queue": {"maximum_observed_non_ready": maximum_queued},
            "retrieval": latency_summary(retrieval_latencies),
            "agent": latency_summary(agent_latencies),
            "throughput_requests_per_second": completed / elapsed if elapsed else None,
            "error_rate": error_rate,
            "recovered_errors": recovered,
            "resource": None,
            "index": None,
        },
        "gate": {
            "max_error_rate": args.max_error_rate,
            "passed": error_rate <= args.max_error_rate,
        },
        "limitations": [
            "Container/host resource usage and Qdrant index size require external collectors "
            "and are null.",
            "Production-like mode is read-only; Compose mode uploads only explicit "
            "synthetic fixtures.",
        ],
    }


def plan(args: argparse.Namespace) -> dict:
    return {
        "schema_version": 1,
        "data_classification": "synthetic-company-neutral",
        "mode": args.mode,
        "execute": args.execute,
        "scope": {
            "documents": args.documents,
            "concurrency": args.concurrency,
            "requests": args.requests,
            "duration_seconds": args.duration_seconds,
        },
        "target": args.base_url if args.mode in {"compose", "production"} else None,
        "measurements": None,
    }


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        validate_limits(args.documents, args.concurrency, args.requests, args.duration_seconds)
        if args.documents >= EXPENSIVE_DOCUMENT_THRESHOLD and not args.confirm_expensive:
            raise ValueError("5k+ runs require --confirm-expensive")
        if args.mode == "production" and not args.allow_production_like:
            raise ValueError("production mode requires --allow-production-like")
        if args.mode == "local" and args.execute:
            result = run_local_microbenchmark(
                documents=args.documents,
                concurrency=args.concurrency,
                requests=args.requests,
                seed=args.seed,
                duration_seconds=args.duration_seconds,
            )
        elif args.mode in {"compose", "production"} and args.execute:
            result = run_http_load(args)
        else:
            result = plan(args)
        rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
        print(rendered)
        print(
            f"mode={result['mode']} documents={args.documents} execute={args.execute}",
            file=sys.stderr,
        )
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered + "\n", encoding="utf-8")
        gate = result.get("gate")
        return 0 if not gate or gate["passed"] else 1
    except (ValueError, OSError, httpx.HTTPError, RuntimeError) as exc:
        message = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(json.dumps({"status": "invalid", "error": message}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
