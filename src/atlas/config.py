from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process settings. Production writes stay off unless a later phase adds approval."""

    model_config = SettingsConfigDict(env_prefix="ATLAS_", extra="ignore")

    data_dir: Path = Path("var/atlas")
    max_rows: int = Field(default=1000, ge=1, le=100_000)
    max_ingest_rows: int = Field(default=1_000_000, ge=1)
    max_upload_bytes: int = Field(default=50 * 1024 * 1024, ge=1)
    null_error_rate: float = Field(default=0.2, ge=0, le=1)
    read_only: bool = True

    @property
    def warehouse_dir(self) -> Path:
        return self.data_dir / "warehouse"

    @property
    def metadata_path(self) -> Path:
        return self.data_dir / "metadata.sqlite"
