import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .acl import allowed_space_ids, has_global_role, memberships, require_space_role
from .agent import run_agent, stream_agent
from .config import get_settings
from .database import get_db
from .documents import (
    RETRYABLE_DOCUMENT_STATUSES,
    duplicate_document,
    next_document_version,
    normalize_filename,
)
from .evaluation import persist_suite_outcome, public_outcome, run_evaluation_suite
from .health import readiness_report
from .models import (
    AgentRun,
    AuditLog,
    Document,
    DocumentStatus,
    EvaluationCase,
    EvaluationCaseResult,
    EvaluationRun,
    EvaluationSuite,
    KnowledgeSpace,
    SpaceRole,
    User,
)
from .observability import EVALUATION_GATES, QUEUE_EVENTS, bounded
from .parsers import SUPPORTED
from .schemas import (
    ChatRequest,
    DocumentView,
    LoginRequest,
    SearchRequest,
    SpaceView,
    TokenResponse,
    UserView,
)
from .search import search_knowledge
from .security import create_token, current_user, redact, verify_password
from .storage import store
from .worker import ingest_document, purge_document

router = APIRouter(prefix="/api/v1")
settings = get_settings()


def audit(
    db: Session, actor: str | None, action: str, target_type: str, target_id: str | None, **details
) -> None:
    db.add(
        AuditLog(
            actor_id=actor,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details,
        )
    )


def enqueue_ingestion(db: Session, document: Document) -> None:
    """Dispatch ingestion while keeping a recoverable state if Redis is unavailable."""
    try:
        ingest_document.delay(document.id)
        QUEUE_EVENTS.labels("ingestion", "dispatched").inc()
    except Exception as exc:
        QUEUE_EVENTS.labels("ingestion", "dispatch_failed").inc()
        document.status = DocumentStatus.failed_retryable
        document.error_code = "QUEUE_ERROR"
        document.error_message = redact(str(exc))[:1000]
        db.commit()
        raise


@router.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Annotated[Session, Depends(get_db)]):
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    audit(db, user.id, "auth.login", "user", user.id)
    db.commit()
    return TokenResponse(
        access_token=create_token(user.id), refresh_token=create_token(user.id, "refresh")
    )


@router.get("/auth/me", response_model=UserView)
def me(user: Annotated[User, Depends(current_user)]):
    return UserView(id=user.id, email=user.email, display_name=user.display_name)


@router.get("/spaces", response_model=list[SpaceView])
def list_spaces(
    user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]
):
    result = []
    for membership in memberships(db, user.id):
        space = db.get(KnowledgeSpace, membership.space_id)
        if space:
            result.append(
                SpaceView(
                    id=space.id,
                    name=space.name,
                    description=space.description,
                    role=membership.role.value,
                )
            )
    return result


@router.get("/documents", response_model=list[DocumentView])
def list_documents(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    space_id: str | None = None,
):
    spaces = allowed_space_ids(db, user.id)
    if space_id:
        if space_id not in spaces:
            raise HTTPException(403, "Knowledge space is not accessible")
        spaces = [space_id]
    documents = db.scalars(
        select(Document)
        .where(Document.space_id.in_(spaces), Document.deleted_at.is_(None))
        .order_by(Document.created_at.desc())
    )
    return [
        DocumentView(
            id=item.id,
            space_id=item.space_id,
            filename=item.filename,
            content_type=item.content_type,
            size_bytes=item.size_bytes,
            version=item.version,
            status=item.status.value,
            error_code=item.error_code,
            created_at=item.created_at,
        )
        for item in documents
    ]


@router.post("/documents", response_model=DocumentView, status_code=202)
async def upload_document(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    space_id: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
):
    require_space_role(db, user.id, space_id, SpaceRole.curator)
    try:
        filename = normalize_filename(file.filename or "")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in SUPPORTED:
        raise HTTPException(415, f"Unsupported file type: {suffix}")
    limit = settings.max_email_mb if suffix == ".eml" else settings.max_file_mb
    content = await file.read(limit * 1024 * 1024 + 1)
    if len(content) > limit * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {limit} MB limit")
    digest = hashlib.sha256(content).hexdigest()
    duplicate = duplicate_document(db, space_id, digest)
    if duplicate:
        raise HTTPException(409, f"Duplicate document: {duplicate.id}")
    version = next_document_version(db, space_id, filename)
    document = Document(
        space_id=space_id,
        filename=filename,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(content),
        sha256=digest,
        object_key=f"{space_id}/{uuid.uuid4()}/{filename}",
        version=version,
        status=DocumentStatus.queued,
    )
    store.put(document.object_key, content, document.content_type)
    db.add(document)
    audit(
        db,
        user.id,
        "document.upload",
        "document",
        document.id,
        filename=filename,
        space_id=space_id,
    )
    try:
        db.commit()
    except Exception:
        db.rollback()
        store.delete(document.object_key)
        raise
    db.refresh(document)
    enqueue_ingestion(db, document)
    return DocumentView(
        id=document.id,
        space_id=document.space_id,
        filename=document.filename,
        content_type=document.content_type,
        size_bytes=document.size_bytes,
        version=document.version,
        status=document.status.value,
        error_code=document.error_code,
        created_at=document.created_at,
    )


@router.post("/documents/{document_id}/retry", status_code=202)
def retry_document(
    document_id: str,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    document = db.get(Document, document_id)
    if not document or document.deleted_at:
        raise HTTPException(404, "Document not found")
    require_space_role(db, user.id, document.space_id, SpaceRole.curator)
    if document.status not in RETRYABLE_DOCUMENT_STATUSES:
        raise HTTPException(409, f"Document in {document.status.value} state cannot be retried")
    document.status = DocumentStatus.queued
    document.error_code = None
    document.error_message = None
    audit(db, user.id, "document.retry", "document", document.id)
    db.commit()
    enqueue_ingestion(db, document)
    return {"id": document.id, "status": document.status.value}


@router.delete("/documents/{document_id}", status_code=202)
def delete_document(
    document_id: str,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    document = db.get(Document, document_id)
    if not document or document.deleted_at:
        raise HTTPException(404, "Document not found")
    require_space_role(db, user.id, document.space_id, SpaceRole.curator)
    document.deleted_at = datetime.now(UTC)
    document.status = DocumentStatus.deleted
    audit(db, user.id, "document.delete", "document", document.id)
    db.commit()
    purge_document.delay(document.id)
    return {"id": document.id, "status": "deleted"}


@router.post("/search")
def search(
    payload: SearchRequest,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    hits = search_knowledge(db, user.id, payload.query, payload.filters, payload.top_k)
    audit(db, user.id, "knowledge.search", "query", None, result_count=len(hits))
    db.commit()
    return hits


@router.post("/chat")
def chat(
    payload: ChatRequest,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return run_agent(
        db,
        user.id,
        payload.query,
        payload.filters,
        payload.conversation_id,
    )


@router.post("/chat/stream")
def chat_stream(
    payload: ChatRequest,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    user_id = user.id

    def events():
        for item in stream_agent(
            db,
            user_id,
            payload.query,
            payload.filters,
            payload.conversation_id,
        ):
            data = dict(item["data"])
            data.pop("status_code", None)
            yield f"event: {item['event']}\ndata: {json.dumps(data)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/traces")
def traces(user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]):
    runs = db.scalars(
        select(AgentRun)
        .where(AgentRun.user_id == user.id)
        .order_by(AgentRun.created_at.desc())
        .limit(100)
    )
    return [
        {
            "id": run.id,
            "query": run.query,
            "status": run.status,
            "answer": run.answer,
            "citations": run.citations,
            "trace": run.trace,
            "latency_ms": run.latency_ms,
            "created_at": run.created_at,
        }
        for run in runs
    ]


@router.get("/evaluations/cases")
def evaluation_cases(
    user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]
):
    if not has_global_role(db, user.id, SpaceRole.admin):
        raise HTTPException(403, "Evaluation case definitions require administrator access")
    return list(
        db.scalars(
            select(EvaluationCase).order_by(
                EvaluationCase.suite, EvaluationCase.version, EvaluationCase.ordinal
            ).limit(500)
        )
    )


@router.get("/evaluations/suites")
def evaluation_suites(
    user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]
):
    del user
    suites = list(
        db.scalars(
            select(EvaluationSuite)
            .where(EvaluationSuite.data_classification == "synthetic-company-neutral")
            .order_by(EvaluationSuite.name, EvaluationSuite.version.desc())
        )
    )
    return [
        {
            "name": item.name,
            "version": item.version,
            "description": item.description,
            "data_classification": item.data_classification,
        }
        for item in suites
    ]


def _bounded_run(
    db: Session,
    user: User,
    suite: str,
    version: str | None,
    *,
    acting_user_override: str | None = None,
):
    suite_statement = select(EvaluationSuite).where(EvaluationSuite.name == suite)
    if version is not None:
        suite_statement = suite_statement.where(EvaluationSuite.version == version)
    suite_record = db.scalar(
        suite_statement.order_by(
            EvaluationSuite.created_at.desc(), EvaluationSuite.version.desc()
        ).limit(1)
    )
    if suite_record and suite_record.data_classification != "synthetic-company-neutral":
        raise HTTPException(400, "Only company-neutral synthetic suites may be executed")
    if version is None:
        version = suite_record.version if suite_record else None
    count = len(
        list(
            db.scalars(
                select(EvaluationCase.id).where(
                    EvaluationCase.suite == suite,
                    *([EvaluationCase.version == version] if version else []),
                )
            )
        )
    )
    if count > settings.evaluation_sync_case_limit:
        raise HTTPException(
            409,
            "Suite exceeds the synchronous evaluation limit; use the local/CI runner",
        )
    try:
        outcome = run_evaluation_suite(
            db,
            suite,
            version,
            acting_user_override=acting_user_override,
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    gate_passed = outcome.passed == outcome.total
    EVALUATION_GATES.labels(
        bounded("suite", outcome.suite), "success" if gate_passed else "failure"
    ).inc()
    persisted = persist_suite_outcome(db, user.id, outcome, gate_passed=gate_passed)
    result = public_outcome(outcome)
    result["run_id"] = persisted.id
    result["gate_passed"] = gate_passed
    return result


@router.post("/evaluations/smoke")
def run_smoke(
    user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]
):
    result = _bounded_run(db, user, "smoke", None, acting_user_override=user.id)
    audit(db, user.id, "evaluation.run", "suite", result["run_id"], suite="smoke")
    db.commit()
    return result


@router.post("/evaluations/suites/{suite}/runs")
def run_named_evaluation_suite(
    suite: str,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    version: str | None = None,
):
    if not has_global_role(db, user.id, SpaceRole.admin):
        raise HTTPException(403, "Only administrators may run configured acting-user suites")
    result = _bounded_run(db, user, suite, version)
    audit(db, user.id, "evaluation.run", "suite", result["run_id"], suite=suite)
    db.commit()
    return result


@router.get("/evaluations/runs")
def evaluation_runs(
    user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]
):
    statement = select(EvaluationRun)
    if not has_global_role(db, user.id, SpaceRole.admin):
        statement = statement.where(EvaluationRun.requested_by_id == user.id)
    runs = list(db.scalars(statement.order_by(EvaluationRun.started_at.desc()).limit(50)))
    return [
        {
            "id": run.id,
            "suite": run.suite_name,
            "version": run.suite_version,
            "status": run.status,
            "total": run.total_cases,
            "passed": run.passed_cases,
            "gate_passed": run.gate_passed,
            "metrics": run.metrics,
            "safe_summary": run.safe_summary,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
        }
        for run in runs
    ]


@router.get("/evaluations/runs/{run_id}")
def evaluation_run(
    run_id: str,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    run = db.get(EvaluationRun, run_id)
    if not run:
        raise HTTPException(404, "Evaluation run not found")
    if run.requested_by_id != user.id and not has_global_role(db, user.id, SpaceRole.admin):
        raise HTTPException(403, "Evaluation run is not accessible")
    results = list(
        db.scalars(
            select(EvaluationCaseResult)
            .where(EvaluationCaseResult.run_id == run.id)
            .order_by(EvaluationCaseResult.ordinal, EvaluationCaseResult.case_id)
        )
    )
    return {
        "id": run.id,
        "suite": run.suite_name,
        "version": run.suite_version,
        "status": run.status,
        "total": run.total_cases,
        "passed": run.passed_cases,
        "gate_passed": run.gate_passed,
        "metrics": run.metrics,
        "safe_summary": run.safe_summary,
        "results": [
            {
                "case_id": item.case_id,
                "passed": item.passed,
                "status": item.actual_status,
                "latency_ms": item.latency_ms,
                "error_category": item.error_category,
                "metrics": item.metrics,
                "safe_summary": item.safe_summary,
            }
            for item in results
        ],
    }


@router.get("/operations/status")
def operations_status(
    user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]
):
    """Small redacted status view; never returns topology, content, or identifiers."""
    del user
    latest = db.scalar(select(EvaluationRun).order_by(EvaluationRun.started_at.desc()).limit(1))
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    failed_runs = db.scalar(
        select(func.count()).select_from(AgentRun).where(
            AgentRun.created_at >= cutoff, AgentRun.status == "failed"
        )
    ) or 0
    refused_runs = db.scalar(
        select(func.count()).select_from(AgentRun).where(
            AgentRun.created_at >= cutoff, AgentRun.status == "insufficient_evidence"
        )
    ) or 0
    return {
        "release": settings.release_version,
        "readiness": readiness_report(),
        "evaluation_gate": None
        if latest is None
        else {
            "suite": latest.suite_name,
            "version": latest.suite_version,
            "status": latest.status,
            "gate_passed": latest.gate_passed,
            "completed_at": latest.completed_at,
        },
        "security_summary": {
            "window_hours": 24,
            "failed_agent_runs": failed_runs,
            "refusals": refused_runs,
            "postgres_authoritative": True,
            "details_redacted": True,
        },
    }
