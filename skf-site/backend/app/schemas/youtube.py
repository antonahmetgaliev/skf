from app.schemas.championship import CamelModel


class YouTubeVideo(CamelModel):
    video_id: str
    title: str
    description: str = ""
    published_at: str
    thumbnail_url: str = ""
