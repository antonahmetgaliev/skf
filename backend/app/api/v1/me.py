"""The signed-in user."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.core.openapi import problem_responses
from app.database import get_db
from app.models.user import User
from app.schemas.auth import UserOut
from app.services import auth as auth_service
from app.services.users import build_user_out

router = APIRouter(prefix="/me", tags=["Me"])


@router.get("", response_model=UserOut)
async def get_me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The currently authenticated user; 401 when not logged in."""
    return await build_user_out(user, db)


@router.post("/discord-syncs", response_model=UserOut, responses=problem_responses(503))
async def sync_discord_nickname(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Re-fetch the user's Discord server nickname with the bot token.

    Called silently by the profile page; a failed fetch keeps the stored value.
    """
    await auth_service.sync_discord_nickname(db, user)
    return await build_user_out(user, db)
