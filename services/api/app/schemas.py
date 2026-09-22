from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserView(BaseModel):
    id: str
    email: str
    display_name: str


class SpaceView(BaseModel):
    id: str
    name: str
    description: str
    role: str


class DocumentView(BaseModel):
    id: str
    space_id: str
    filename: str
    content_type: str
    size_bytes: int
    version: int
    status: str
    error_code: str | None
    created_at: datetime


class SearchFilters(BaseModel):
    document_ids: list[str] = Field(default_factory=list)
    created_from: datetime | None = None
    created_to: datetime | None = None
    file_types: list[str] = Field(default_factory=list)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    top_k: int = Field(default=10, ge=1, le=20)


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None
    filters: SearchFilters = Field(default_factory=SearchFilters)


class Citation(BaseModel):
    document_id: str
    chunk_id: str
    filename: str
    locator: str
    snippet: str


class ChatResponse(BaseModel):
    status: str
    answer: str
    citations: list[Citation]
    trace_id: str


class ErrorBody(BaseModel):
    code: str
    message: str
    retryable: bool = False
    trace_id: str | None = None
