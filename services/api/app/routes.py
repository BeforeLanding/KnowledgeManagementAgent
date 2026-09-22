import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .acl import allowed_space_ids, memberships, require_space_role
from .agent import run_agent
from .config import get_settings
from .database import get_db
from .documents import (
    RETRYABLE_DOCUMENT_STATUSES,
    duplicate_document,
    next_document_version,
    normalize_filename,
)
from .models import (
    AgentRun,
    AuditLog,
    Document,
    DocumentStatus,
    EvaluationCase,
    KnowledgeSpace,
    SpaceRole,
    User,
)
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
    except Exception as exc:
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
    spaces = allowed_space_ids(db, user.id)
    hits = search_knowledge(db, payload.query, spaces, payload.filters, payload.top_k)
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
        allowed_space_ids(db, user.id),
        payload.filters,
        payload.conversation_id,
    )


@router.post("/chat/stream")
def chat_stream(
    payload: ChatRequest,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    result = run_agent(
        db,
        user.id,
        payload.query,
        allowed_space_ids(db, user.id),
        payload.filters,
        payload.conversation_id,
    )

    def events():
        yield f"event: run_started\ndata: {json.dumps({'trace_id': result.trace_id})}\n\n"
        yield 'event: tool_started\ndata: {"tool":"search_knowledge"}\n\n'
        yield 'event: tool_completed\ndata: {"tool":"search_knowledge"}\n\n'
        yield f"event: token\ndata: {json.dumps({'text': result.answer})}\n\n"
        for citation in result.citations:
            yield f"event: citation\ndata: {citation.model_dump_json()}\n\n"
        yield f"event: run_completed\ndata: {result.model_dump_json()}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


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
    return list(db.scalars(select(EvaluationCase).limit(500)))


@router.post("/evaluations/smoke")
def run_smoke(
    user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]
):
    cases = list(db.scalars(select(EvaluationCase).where(EvaluationCase.suite == "smoke")))
    results = []
    spaces = allowed_space_ids(db, user.id)
    for case in cases:
        hits = search_knowledge(db, case.query, spaces, SearchRequest(query=case.query).filters, 5)
        returned = {item["document_id"] for item in hits}
        expected = set(case.expected_document_ids)
        forbidden = set(case.forbidden_document_ids)
        passed = expected.issubset(returned) and not returned.intersection(forbidden)
        results.append({"case_id": case.id, "passed": passed, "returned": list(returned)})
    audit(db, user.id, "evaluation.run", "suite", None, suite="smoke", total=len(cases))
    db.commit()
    return {
        "suite": "smoke",
        "total": len(results),
        "passed": sum(item["passed"] for item in results),
        "results": results,
    }
