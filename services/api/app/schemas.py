from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator


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

    @field_validator("document_ids")
    @classmethod
    def unique_document_ids(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    @field_validator("file_types")
    @classmethod
    def normalize_file_types(cls, values: list[str]) -> list[str]:
        normalized = (value.strip().lower().removeprefix(".") for value in values)
        return list(dict.fromkeys(value for value in normalized if value))

    @model_validator(mode="after")
    def validate_date_range(self) -> "SearchFilters":
        if self.created_from and self.created_to and self.created_from > self.created_to:
            raise ValueError("created_from must be before or equal to created_to")
        return self


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
