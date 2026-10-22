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

    # Document Store for LLM Test Suites
    test_suite_store_type: str = "json"  # "json" or "mongo"
    json_store_dir: Path = data_dir / "test_suites"
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_database_name: str = "tri9t_qa"
    mongo_collection_name: str = "generated_test_suites"

    # LLM Provider Configuration
    llm_provider: str = "mock"  # "mock" or "openai"
    llm_api_key: str | None = None
    llm_api_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.2
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 3  # Maximum total model attempts per request

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
