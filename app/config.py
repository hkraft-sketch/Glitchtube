from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    TEMP_DIR: Path = Path("/tmp/glitchtube")
    OUTPUT_FORMAT: str = "mp3"
    SNIPPET_DURATION_MS: int = 3000
    NUM_PARTS: int = 10
    MAX_VIDEO_DURATION_SEC: int = 3600
    CLEANUP_AGE_MINUTES: int = 30


settings = Settings()
