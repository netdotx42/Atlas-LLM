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
    model_path: Path | None = None
    model_repo: str = "bartowski/Phi-3.5-mini-instruct-GGUF"
    model_file: str = "Phi-3.5-mini-instruct-Q4_K_M.gguf"
    model_n_ctx: int = Field(default=4096, ge=512, le=8192)
    model_max_tokens: int = Field(default=500, ge=64, le=2000)
    ui_dir: Path = Path("ui/dist")
    auth_enabled: bool = False
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    public_base_url: str = ""

    @property
    def resolved_model_path(self) -> Path:
        if self.model_path is not None:
            return self.model_path
        return Path("var/models") / self.model_file

    @property
    def warehouse_dir(self) -> Path:
        return self.data_dir / "warehouse"

    @property
    def metadata_path(self) -> Path:
        return self.data_dir / "metadata.sqlite"
