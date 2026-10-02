from enum import Enum

from app.schemas.base import CamelModel


class StreamStatus(str, Enum):
    PAST = "past"
    UPCOMING = "upcoming"


class YouTubeVideo(CamelModel):
    video_id: str
    title: str
    description: str = ""
    published_at: str
    thumbnail_url: str = ""
