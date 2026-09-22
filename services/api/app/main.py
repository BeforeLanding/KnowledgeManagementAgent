import logging
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from .agent import AgentRunError
from .config import get_settings
from .health import readiness_report
from .observability import HTTP_LATENCY, HTTP_REQUESTS, record_security_failure
from .routes import router

settings = get_settings()
logger = logging.getLogger("kma.api")
app = FastAPI(title="Knowledge Management Agent", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    started = time.perf_counter()
    trace_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.trace_id = trace_id
    response = await call_next(request)
    route_object = request.scope.get("route")
    route = getattr(route_object, "path", "unmatched")
    HTTP_REQUESTS.labels(request.method, route, str(response.status_code)).inc()
    HTTP_LATENCY.labels(request.method, route).observe(time.perf_counter() - started)
    response.headers["X-Request-ID"] = trace_id
    return response


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": f"HTTP_{exc.status_code}",
            "message": str(exc.detail),
            "retryable": exc.status_code >= 500,
            "trace_id": getattr(request.state, "trace_id", None),
        },
    )


@app.exception_handler(AgentRunError)
async def agent_error(request: Request, exc: AgentRunError):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.code,
            "message": str(exc),
            "retryable": exc.retryable,
            "trace_id": exc.trace_id or getattr(request.state, "trace_id", None),
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    del exc
    record_security_failure("input")
    return JSONResponse(
        status_code=422,
        content={
            "code": "INVALID_REQUEST",
            "message": "Request validation failed",
            "retryable": False,
            "trace_id": getattr(request.state, "trace_id", None),
        },
    )


@app.exception_handler(Exception)
async def unknown_error(request: Request, exc: Exception):
    trace_id = getattr(request.state, "trace_id", str(uuid.uuid4()))
    logger.error("request_failed request_id=%s error_type=%s", trace_id, type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content={
            "code": "INTERNAL_ERROR",
            "message": "Unexpected server error",
            "retryable": True,
            "trace_id": trace_id,
        },
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/live")
def liveness():
    return {"status": "live"}


@app.get("/health/ready")
def readiness():
    report = readiness_report()
    return JSONResponse(report, status_code=200 if report["status"] == "ready" else 503)


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


app.include_router(router)
