"""Custom championships (calendar events not on SimGrid) and their races.

Access rule: admins manage every championship; community managers only those
belonging to a community assigned to them — never the community-less ones,
and they cannot move a championship out of their communities.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import is_admin
from app.core.errors import NotFound
from app.models.custom_championship import CustomChampionship, CustomRace
from app.models.user import User
from app.schemas.calendar import (
    CustomChampionshipCreate,
    CustomChampionshipOut,
    CustomChampionshipUpdate,
    CustomRaceCreate,
    CustomRaceSync,
    CustomRaceUpdate,
)
from app.services.communities import ensure_community_access, managed_community_ids


def _strip(value: str | None) -> str | None:
    return value.strip() if value else None


def to_out(champ: CustomChampionship) -> CustomChampionshipOut:
    data = CustomChampionshipOut.model_validate(champ)
    if champ.game_rel is not None:
        data.game_name = champ.game_rel.name
    return data


async def list_stmt(db: AsyncSession, user: User, community_id: uuid.UUID | None) -> Select:
    """The query for the championships *user* may see, newest first."""
    stmt = select(CustomChampionship).order_by(CustomChampionship.created_at.desc())
    if community_id is not None:
        await ensure_community_access(db, user, community_id)
        return stmt.where(CustomChampionship.community_id == community_id)
    if not is_admin(user):
        stmt = stmt.where(CustomChampionship.community_id.in_(await managed_community_ids(db, user)))
    return stmt


async def get_accessible(db: AsyncSession, user: User, champ_id: uuid.UUID) -> CustomChampionship:
    champ = (
        await db.execute(select(CustomChampionship).where(CustomChampionship.id == champ_id))
    ).scalar_one_or_none()
    if champ is None:
        raise NotFound("Custom championship not found.")
    await ensure_community_access(db, user, champ.community_id)
    return champ


async def create(db: AsyncSession, user: User, body: CustomChampionshipCreate) -> CustomChampionship:
    await ensure_community_access(db, user, body.community_id)
    champ = CustomChampionship(
        name=body.name.strip(),
        game=body.game.strip(),
        car_class=_strip(body.car_class),
        description=body.description,
        community_id=body.community_id,
        game_id=body.game_id,
        created_by_user_id=user.id,
    )
    for idx, race in enumerate(body.races):
        champ.races.append(
            CustomRace(date=race.date, end_date=race.end_date, track=_strip(race.track), sort_order=idx)
        )
    db.add(champ)
    await db.commit()
    await db.refresh(champ)
    return champ


async def update(
    db: AsyncSession, user: User, champ: CustomChampionship, body: CustomChampionshipUpdate
) -> CustomChampionship:
    changes = body.model_dump(exclude_unset=True, by_alias=False)
    if "community_id" in changes and changes["community_id"] != champ.community_id:
        # Moving a championship needs access to the destination too.
        await ensure_community_access(db, user, changes["community_id"])
    for field, value in changes.items():
        setattr(champ, field, value.strip() if isinstance(value, str) else value)
    await db.commit()
    await db.refresh(champ)
    return champ


async def delete(db: AsyncSession, champ: CustomChampionship) -> None:
    await db.delete(champ)
    await db.commit()


# ── Races ────────────────────────────────────────────────────────────────────


async def _get_race(db: AsyncSession, champ: CustomChampionship, race_id: uuid.UUID) -> CustomRace:
    race = (
        await db.execute(
            select(CustomRace).where(CustomRace.id == race_id, CustomRace.championship_id == champ.id)
        )
    ).scalar_one_or_none()
    if race is None:
        raise NotFound("Race not found.")
    return race


async def add_race(db: AsyncSession, champ: CustomChampionship, body: CustomRaceCreate) -> CustomRace:
    race = CustomRace(
        championship_id=champ.id,
        date=body.date,
        end_date=body.end_date,
        track=_strip(body.track),
        sort_order=max((r.sort_order for r in champ.races), default=-1) + 1,
    )
    db.add(race)
    await db.commit()
    await db.refresh(race)
    return race


async def update_race(
    db: AsyncSession, champ: CustomChampionship, race_id: uuid.UUID, body: CustomRaceUpdate
) -> CustomRace:
    race = await _get_race(db, champ, race_id)
    for field, value in body.model_dump(exclude_unset=True, by_alias=False).items():
        setattr(race, field, value.strip() if isinstance(value, str) else value)
    await db.commit()
    await db.refresh(race)
    return race


async def delete_race(db: AsyncSession, champ: CustomChampionship, race_id: uuid.UUID) -> None:
    race = await _get_race(db, champ, race_id)
    await db.delete(race)
    await db.commit()


async def replace_races(
    db: AsyncSession, champ: CustomChampionship, items: list[CustomRaceSync]
) -> list[CustomRace]:
    """Replace the full race list: ids present are updated, absent ones created,
    existing races missing from *items* deleted."""
    incoming_ids = {r.id for r in items if r.id is not None}
    existing = {r.id: r for r in champ.races}

    for rid, race in existing.items():
        if rid not in incoming_ids:
            await db.delete(race)

    for idx, item in enumerate(items):
        race = existing.get(item.id) if item.id else None
        if race is not None:
            race.track = _strip(item.track)
            race.date = item.date
            race.end_date = item.end_date
            race.sort_order = idx
        else:
            db.add(
                CustomRace(
                    championship_id=champ.id,
                    track=_strip(item.track),
                    date=item.date,
                    end_date=item.end_date,
                    sort_order=idx,
                )
            )

    await db.commit()
    await db.refresh(champ)
    return list(champ.races)
