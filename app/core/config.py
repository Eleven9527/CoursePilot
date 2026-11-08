from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "My Agent RAG API")
    version: str = os.getenv("APP_VERSION", "0.1.0")
    api_prefix: str = os.getenv("API_PREFIX", "/api/v1")
    host: str = os.getenv("HOST", "127.0.0.1")
    port: int = int(os.getenv("PORT", "8000"))
    reload: bool = os.getenv("RELOAD", "true").lower() == "true"
    database_url: str = os.getenv('DATABASE_URL', '').strip()
    milvus_uri: str = os.getenv('MILVUS_URI', '').strip()
    milvus_token: str = os.getenv('MILVUS_TOKEN', '').strip()
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "").strip()
    embedding_base_url: str = os.getenv("EMBEDDING_BASE_URL", "").strip()
    embedding_api_key: str = os.getenv("EMBEDDING_API_KEY", "").strip()
    embedding_dimension: int = int(os.getenv("EMBEDDING_DIMENSION", "").strip() or "0")
    data_dir: Path = Path(os.getenv("DATA_DIR", "data"))
    mineru_executable: str = os.getenv("MINERU_EXECUTABLE", "").strip()
    mineru_tier_pdf: str = os.getenv("MINERU_TIER_PDF", "basic").strip()
    mineru_tier_non_pdf: str = os.getenv("MINERU_TIER_NON_PDF", "flash").strip()
    mineru_timeout_seconds: int = int(os.getenv("MINERU_TIMEOUT_SECONDS", "3600"))
    chunk_size: int = int(os.getenv("CHUNK_SIZE", "800"))
    chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "100"))
    worker_poll_interval_seconds: float = float(os.getenv("WORKER_POLL_INTERVAL_SECONDS", "2"))

    @property
    def embedding_enabled(self) -> bool:
        return bool(self.embedding_model and self.embedding_base_url and self.embedding_dimension > 0 and self.milvus_uri)

    @property
    def database_path(self) -> Path:
        return self.data_dir / "documents.db"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def parsed_dir(self) -> Path:
        return self.data_dir / "parsed"


settings = Settings()
