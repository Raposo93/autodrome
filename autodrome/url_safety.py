from urllib.parse import urlsplit


YOUTUBE_THUMBNAIL_HOSTS = {"i.ytimg.com", "img.youtube.com"}


def validate_youtube_thumbnail_url(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise ValueError("Invalid YouTube thumbnail URL")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise ValueError("Invalid YouTube thumbnail URL") from error
    if (
        parsed.scheme != "https"
        or parsed.hostname not in YOUTUBE_THUMBNAIL_HOSTS
        or parsed.username
        or parsed.password
        or port not in {None, 443}
        or not parsed.path.startswith("/")
    ):
        raise ValueError("Thumbnail URL must use an allowed YouTube image host")
    return value
