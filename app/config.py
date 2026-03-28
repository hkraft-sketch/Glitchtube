from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    TEMP_DIR: Path = Path("/tmp/glitchtube")


settings = Settings()
