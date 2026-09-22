import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.responses import Response

from .config import get_settings
from .database import Base, engine
from .routes import router

settings = get_settings()
REQUESTS = Counter("kma_http_requests_total", "HTTP requests", ["method", "path", "status"])
LATENCY = Histogram("kma_http_request_seconds", "HTTP request latency", ["method", "path"])

app = FastAPI(title="Knowledge Management Agent", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(engine)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    route = request.url.path
    REQUESTS.labels(request.method, route, response.status_code).inc()
    LATENCY.labels(request.method, route).observe(time.perf_counter() - started)
    return response


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": f"HTTP_{exc.status_code}",
            "message": str(exc.detail),
            "retryable": exc.status_code >= 500,
            "trace_id": request.headers.get("x-request-id"),
        },
    )


@app.exception_handler(Exception)
async def unknown_error(request: Request, exc: Exception):
    trace_id = request.headers.get("x-request-id") or str(uuid.uuid4())
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


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


app.include_router(router)
