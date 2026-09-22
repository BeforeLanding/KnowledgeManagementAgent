from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import SpaceMembership, SpaceRole
from .observability import record_security_failure

ROLE_RANK = {SpaceRole.viewer: 1, SpaceRole.curator: 2, SpaceRole.admin: 3}


def memberships(db: Session, user_id: str) -> list[SpaceMembership]:
    return list(db.scalars(select(SpaceMembership).where(SpaceMembership.user_id == user_id)))


def allowed_space_ids(db: Session, user_id: str) -> list[str]:
    return [item.space_id for item in memberships(db, user_id)]


def has_global_role(db: Session, user_id: str, minimum: SpaceRole) -> bool:
    """Use the user's highest current space role for evaluation administration."""
    return any(ROLE_RANK[item.role] >= ROLE_RANK[minimum] for item in memberships(db, user_id))


def require_space_role(
    db: Session, user_id: str, space_id: str, minimum: SpaceRole
) -> SpaceMembership:
    member = db.scalar(
        select(SpaceMembership).where(
            SpaceMembership.user_id == user_id, SpaceMembership.space_id == space_id
        )
    )
    if not member or ROLE_RANK[member.role] < ROLE_RANK[minimum]:
        record_security_failure("authorization")
        raise HTTPException(403, "Insufficient knowledge-space permission")
    return member
