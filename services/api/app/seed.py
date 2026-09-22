from sqlalchemy import select

from .config import get_settings
from .database import SessionLocal
from .evaluation import evaluation_configuration
from .models import (
    EvaluationCase,
    EvaluationSuite,
    KnowledgeSpace,
    SpaceMembership,
    SpaceRole,
    User,
)
from .security import hash_password


def seed() -> None:
    if not get_settings().seed_demo_data:
        return
    with SessionLocal() as db:
        if db.scalar(select(User).limit(1)):
            has_smoke_cases = db.scalar(
                select(EvaluationCase.id).where(EvaluationCase.suite == "smoke").limit(1)
            )
            has_smoke_suite = db.scalar(
                select(EvaluationSuite.id)
                .where(EvaluationSuite.name == "smoke", EvaluationSuite.version == "1.0")
                .limit(1)
            )
            if has_smoke_cases and not has_smoke_suite:
                db.add(
                    EvaluationSuite(
                        name="smoke",
                        version="1.0",
                        description="Bounded synthetic smoke suite",
                        configuration=evaluation_configuration(),
                    )
                )
                db.commit()
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
                EvaluationSuite(
                    name="smoke",
                    version="1.0",
                    description="Bounded synthetic smoke suite",
                    configuration=evaluation_configuration(),
                ),
                EvaluationCase(
                    suite="smoke",
                    version="1.0",
                    query="What is the demo shipment status?",
                    tags=["single-document"],
                    ordinal=1,
                    is_must_pass=True,
                ),
                EvaluationCase(
                    suite="smoke",
                    version="1.0",
                    query="What confidential decision was made?",
                    expected_status="insufficient_evidence",
                    tags=["acl"],
                    ordinal=2,
                    is_must_pass=True,
                ),
            ]
        )
        db.commit()


if __name__ == "__main__":
    seed()
