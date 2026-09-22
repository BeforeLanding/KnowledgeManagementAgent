from datetime import datetime
from typing import Any

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


class EvaluationSource(BaseModel):
    document_id: str = Field(min_length=1, max_length=120)
    chunk_id: str | None = Field(default=None, max_length=120)


class EvaluationCaseDefinition(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    query: str = Field(min_length=1, max_length=4000)
    language: str = Field(default="en", pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    acting_user: str = Field(min_length=1, max_length=120)
    expected_status: str = Field(default="answered", pattern=r"^(answered|insufficient_evidence)$")
    expected_sources: list[EvaluationSource] = Field(default_factory=list)
    forbidden_sources: list[EvaluationSource] = Field(default_factory=list)
    required_facts: list[str] = Field(default_factory=list, max_length=50)
    rubric: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list, max_length=50)
    must_pass: bool = False

    @field_validator("required_facts", "tags")
    @classmethod
    def normalized_non_empty_values(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values if value.strip()]
        if len(normalized) != len(values):
            raise ValueError("values must be non-empty")
        return list(dict.fromkeys(normalized))


class EvaluationSuiteDefinition(BaseModel):
    schema_version: int = Field(default=1, ge=1, le=1)
    name: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=40)
    description: str = Field(default="", max_length=1000)
    data_classification: str
    configuration: dict[str, str | int | float | bool] = Field(default_factory=dict)
    cases: list[EvaluationCaseDefinition] = Field(min_length=1, max_length=500)

    @field_validator("data_classification")
    @classmethod
    def company_neutral_synthetic_only(cls, value: str) -> str:
        if value != "synthetic-company-neutral":
            raise ValueError("only synthetic-company-neutral evaluation data is accepted")
        return value

    @model_validator(mode="after")
    def unique_case_ids(self) -> "EvaluationSuiteDefinition":
        case_ids = [case.id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("case ids must be unique within a suite version")
        required = {"prompt", "model", "provider", "embedding", "chunking", "retrieval", "code"}
        missing = required.difference(self.configuration)
        if missing:
            raise ValueError(f"configuration is missing: {', '.join(sorted(missing))}")
        return self
