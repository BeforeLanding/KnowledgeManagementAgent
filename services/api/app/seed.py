from sqlalchemy import select

from .database import Base, SessionLocal, engine
from .models import EvaluationCase, KnowledgeSpace, SpaceMembership, SpaceRole, User
from .security import hash_password


def seed() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.scalar(select(User).limit(1)):
            return
        users = [
            User(
                email="admin@example.com",
                display_name="Demo Admin",
                password_hash=hash_password("Admin123!"),
            ),
            User(
                email="curator@example.com",
                display_name="Demo Curator",
                password_hash=hash_password("Curator123!"),
            ),
            User(
                email="viewer@example.com",
                display_name="Demo Viewer",
                password_hash=hash_password("Viewer123!"),
            ),
        ]
        public = KnowledgeSpace(
            name="Operations Journal", description="Synthetic engineering journals"
        )
        restricted = KnowledgeSpace(
            name="Leadership Briefings", description="Synthetic restricted emails"
        )
        db.add_all(users + [public, restricted])
        db.flush()
        db.add_all(
            [
                SpaceMembership(space_id=public.id, user_id=users[0].id, role=SpaceRole.admin),
                SpaceMembership(space_id=restricted.id, user_id=users[0].id, role=SpaceRole.admin),
                SpaceMembership(space_id=public.id, user_id=users[1].id, role=SpaceRole.curator),
                SpaceMembership(space_id=public.id, user_id=users[2].id, role=SpaceRole.viewer),
                EvaluationCase(
                    suite="smoke",
                    version="1.0",
                    query="What is the demo shipment status?",
                    tags=["single-document"],
                ),
                EvaluationCase(
                    suite="smoke",
                    version="1.0",
                    query="What confidential decision was made?",
                    expected_status="insufficient_evidence",
                    tags=["acl"],
                ),
            ]
        )
        db.commit()


if __name__ == "__main__":
    seed()
