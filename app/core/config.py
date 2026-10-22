"""Application configuration module."""

from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Tri9T-CT200-DocIntelligence"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    debug: bool = True

    # Base paths
    base_dir: Path = Path(__file__).resolve().parent.parent.parent
    data_dir: Path = base_dir / "data"

    # Database
    database_url: str = "sqlite:///./tri9t_documents.db"
    default_document_key: str = "CT-200"

    # Known document manuals
    v1_manual_filename: str = "ct200_manual.pdf"
    v2_manual_filename: str = "ct200_manual_v2.pdf"

    @property
    def v1_manual_path(self) -> Path:
        return self.data_dir / self.v1_manual_filename

    @property
    def v2_manual_path(self) -> Path:
        return self.data_dir / self.v2_manual_filename

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
