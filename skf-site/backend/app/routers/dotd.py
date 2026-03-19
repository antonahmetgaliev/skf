"""Driver of the Day (DOTD) voting router."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user, get_current_user_optional, require_admin
from app.database import get_db
from app.models.dotd import DotdCandidate, DotdPoll, DotdVote
from app.models.user import User
from app.schemas.dotd import DotdCandidateOut, DotdPollCreate, DotdPollOut

router = APIRouter(prefix="/dotd", tags=["Driver of the Day"])

_RESULT_VISIBLE_HOURS = 24  # keep closed polls visible for 24 h


# ── helper ────────────────────────────────────────────────────────────────────

def _can_see_counts(poll: DotdPoll, user: User | None, my_vote: DotdVote | None) -> bool:
    """Return True if this requester should see vote counts."""
    if user is not None and user.role.name in ("admin", "super_admin"):
        return True
    if my_vote is not None:
        return True
    if not poll.is_open:
        return True
    return False


def _build_poll_out(poll: DotdPoll, user: User | None) -> DotdPollOut:
    """Construct a DotdPollOut, hiding vote counts when appropriate."""
    my_vote: DotdVote | None = None
    if user is not None:
        my_vote = next((v for v in poll.votes if str(v.user_id) == str(user.id)), None)

    show_counts = _can_see_counts(poll, user, my_vote)

    # Build vote-count map
    count_map: dict[uuid.UUID, int] = {}
    for v in poll.votes:
        count_map[v.candidate_id] = count_map.get(v.candidate_id, 0) + 1

    # Sort candidates: championship_position asc, nulls last
    sorted_candidates = sorted(
        poll.candidates,
        key=lambda c: (c.championship_position is None, c.championship_position or 0),
    )

    candidates_out = [
        DotdCandidateOut(
            id=c.id,
            simgrid_driver_id=c.simgrid_driver_id,
            driver_name=c.driver_name,
            championship_position=c.championship_position,
            vote_count=count_map.get(c.id, 0) if show_counts else None,
        )
        for c in sorted_candidates
    ]

    return DotdPollOut(
        id=poll.id,
        championship_id=poll.championship_id,
        championship_name=poll.championship_name,
        race_id=poll.race_id,
        race_name=poll.race_name,
        created_at=poll.created_at,
        closes_at=poll.closes_at,
        is_open=poll.is_open,
        candidates=candidates_out,
        has_voted=my_vote is not None,
        my_vote_candidate_id=my_vote.candidate_id if my_vote else None,
        total_votes=len(poll.votes),
    )


async def _get_poll_or_404(poll_id: uuid.UUID, db: AsyncSession) -> DotdPoll:
    result = await db.execute(
        select(DotdPoll)
        .options(
            selectinload(DotdPoll.candidates).selectinload(DotdCandidate.votes),
            selectinload(DotdPoll.votes),
        )
        .where(DotdPoll.id == poll_id)
    )
    poll = result.scalar_one_or_none()
    if poll is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Poll not found.")
    return poll


# ── endpoints ─────────────────────────────────────────────────────────────────

@router.get("/polls", response_model=list[DotdPollOut])
async def list_polls(
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> list[DotdPollOut]:
    """Return all active polls and polls closed within the last 24 hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=_RESULT_VISIBLE_HOURS)

    result = await db.execute(
        select(DotdPoll)
        .options(
            selectinload(DotdPoll.candidates).selectinload(DotdCandidate.votes),
            selectinload(DotdPoll.votes),
        )
        .where(
            # open OR closed within 24 h
            (DotdPoll.is_manually_closed == False) | (DotdPoll.closes_at > cutoff)  # noqa: E712
        )
        .order_by(DotdPoll.created_at.desc())
    )
    polls = result.scalars().all()

    # Filter in Python to correctly handle the 24 h window regardless of
    # is_manually_closed flag — a manually-closed poll should stay visible
    # for 24 h from closes_at / manual close moment.
    visible: list[DotdPoll] = []
    now = datetime.now(timezone.utc)
    for p in polls:
        closes = p.closes_at
        if closes.tzinfo is None:
            closes = closes.replace(tzinfo=timezone.utc)
        if p.is_open or (now - closes) <= timedelta(hours=_RESULT_VISIBLE_HOURS):
            visible.append(p)

    return [_build_poll_out(p, user) for p in visible]


@router.post("/polls", response_model=DotdPollOut, status_code=status.HTTP_201_CREATED)
async def create_poll(
    payload: DotdPollCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> DotdPollOut:
    """Create a new DOTD poll (admin only)."""
    closes = payload.closes_at
    if closes.tzinfo is None:
        closes = closes.replace(tzinfo=timezone.utc)
    if closes <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="closes_at must be in the future.",
        )

    poll = DotdPoll(
        championship_id=payload.championship_id,
        championship_name=payload.championship_name,
        race_id=payload.race_id,
        race_name=payload.race_name,
        closes_at=closes,
        created_by_user_id=current_user.id,
    )
    db.add(poll)
    await db.flush()  # get poll.id without committing

    for c in payload.candidates:
        db.add(
            DotdCandidate(
                poll_id=poll.id,
                simgrid_driver_id=c.simgrid_driver_id,
                driver_name=c.driver_name,
                championship_position=c.championship_position,
            )
        )

    await db.commit()
    return _build_poll_out(await _get_poll_or_404(poll.id, db), current_user)


@router.patch("/polls/{poll_id}/close", response_model=DotdPollOut)
async def close_poll(
    poll_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> DotdPollOut:
    """Manually close a poll (admin only)."""
    poll = await _get_poll_or_404(poll_id, db)
    poll.is_manually_closed = True
    # Set closes_at to now so the 24h window starts correctly
    poll.closes_at = datetime.now(timezone.utc)
    await db.commit()
    return _build_poll_out(await _get_poll_or_404(poll_id, db), current_user)


@router.post("/polls/{poll_id}/vote", response_model=DotdPollOut)
async def cast_vote(
    poll_id: uuid.UUID,
    candidate_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DotdPollOut:
    """Cast a vote for a candidate in a poll."""
    poll = await _get_poll_or_404(poll_id, db)

    if not poll.is_open:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This poll is no longer accepting votes.",
        )

    # Check for duplicate vote
    existing = next((v for v in poll.votes if v.user_id == current_user.id), None)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already voted in this poll.",
        )

    # Validate candidate belongs to this poll
    candidate = next((c for c in poll.candidates if str(c.id) == str(candidate_id)), None)
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidate not found in this poll.",
        )

    db.add(
        DotdVote(
            poll_id=poll.id,
            user_id=current_user.id,
            candidate_id=candidate_id,
            voted_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()
    # Expire only the poll so _get_poll_or_404 reloads its relationships
    # fresh (votes list now includes the just-inserted row). Expiring only
    # `poll` avoids touching current_user, which cannot be lazy-loaded in
    # an async session.
    db.expire(poll)
    return _build_poll_out(await _get_poll_or_404(poll_id, db), current_user)
