from enum import Enum
from typing import Annotated

from app.schemas.base import BlankAsNone, CamelModel, IsoDateTime, Url


class StreamStatus(str, Enum):
    PAST = "past"
    UPCOMING = "upcoming"


class YouTubeStreamOut(CamelModel):
    video_id: str
    title: str
    description: str = ""
    published_at: IsoDateTime
    thumbnail_url: Annotated[Url | None, BlankAsNone] = None
