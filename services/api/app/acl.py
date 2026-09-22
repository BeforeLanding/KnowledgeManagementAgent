from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import SpaceMembership, SpaceRole

ROLE_RANK = {SpaceRole.viewer: 1, SpaceRole.curator: 2, SpaceRole.admin: 3}


def memberships(db: Session, user_id: str) -> list[SpaceMembership]:
    return list(db.scalars(select(SpaceMembership).where(SpaceMembership.user_id == user_id)))


def allowed_space_ids(db: Session, user_id: str) -> list[str]:
    return [item.space_id for item in memberships(db, user_id)]


def require_space_role(
    db: Session, user_id: str, space_id: str, minimum: SpaceRole
) -> SpaceMembership:
    member = db.scalar(
        select(SpaceMembership).where(
            SpaceMembership.user_id == user_id, SpaceMembership.space_id == space_id
        )
    )
    if not member or ROLE_RANK[member.role] < ROLE_RANK[minimum]:
        raise HTTPException(403, "Insufficient knowledge-space permission")
    return member
