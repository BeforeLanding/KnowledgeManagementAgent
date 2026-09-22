from app.acl import allowed_space_ids
from app.database import Base
from app.models import KnowledgeSpace, SpaceMembership, SpaceRole, User
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_space_membership_filters_access():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="viewer@test.invalid", display_name="Viewer", password_hash="x")
        allowed = KnowledgeSpace(name="Allowed")
        blocked = KnowledgeSpace(name="Blocked")
        db.add_all([user, allowed, blocked])
        db.flush()
        db.add(SpaceMembership(user_id=user.id, space_id=allowed.id, role=SpaceRole.viewer))
        db.commit()
        assert allowed_space_ids(db, user.id) == [allowed.id]
        assert blocked.id not in allowed_space_ids(db, user.id)
