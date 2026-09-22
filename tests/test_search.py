from types import SimpleNamespace

from app.database import Base
from app.models import Chunk, Document, DocumentStatus, KnowledgeSpace
from app.schemas import SearchFilters
from app.search import search_knowledge
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_search_rechecks_postgres_visibility(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        space = KnowledgeSpace(name="Synthetic Search")
        db.add(space)
        db.flush()
        documents = []
        chunks = []
        for index, status in enumerate([DocumentStatus.ready, DocumentStatus.deleted]):
            document = Document(
                space_id=space.id,
                filename=f"journal-{index}.txt",
                content_type="text/plain",
                size_bytes=10,
                sha256=str(index) * 64,
                object_key=f"synthetic/{index}",
                status=status,
            )
            db.add(document)
            db.flush()
            chunk = Chunk(
                document_id=document.id,
                space_id=space.id,
                ordinal=0,
                locator="line 1",
                text=f"synthetic status {index}",
                token_count=3,
            )
            db.add(chunk)
            documents.append(document)
            chunks.append(chunk)
        db.commit()

        points = [
            SimpleNamespace(
                id=chunk.id,
                score=1.0 - index / 10,
                payload={
                    "document_id": document.id,
                    "space_id": space.id,
                    "filename": document.filename,
                    "locator": chunk.locator,
                    "text": chunk.text,
                },
            )
            for index, (document, chunk) in enumerate(zip(documents, chunks, strict=True))
        ]
        fake = SimpleNamespace(query_points=lambda **_kwargs: SimpleNamespace(points=points))
        monkeypatch.setattr("app.search.client", lambda: fake)
        monkeypatch.setattr("app.search.ensure_collection", lambda _client: None)

        hits = search_knowledge(db, "synthetic status", [space.id], SearchFilters(), 10)

        assert [item["document_id"] for item in hits] == [documents[0].id]
