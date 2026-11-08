from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / "templates").exists() and (p / "services").exists():
            return p
    return Path.cwd()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CAREERPILOT_", env_file=".env", extra="ignore")

    data_dir: Path = _repo_root() / "data"
    database_url: str | None = None
    secret_key_file: str = "secret.key"
    session_ttl_hours: int = 24 * 7
    timezone: str = "UTC"
    allow_external_llm: bool = False       # explicit consent before sending documents externally
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    templates_dir: Path = _repo_root() / "templates"
    latex_timeout_s: int = 60
    scheduler_enabled: bool = True
    auth_disabled_for_tests: bool = False

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite:///{(self.data_dir / 'careerpilot.db').as_posix()}"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def artifacts_dir(self) -> Path:
        return self.data_dir / "artifacts"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    for d in (s.data_dir, s.uploads_dir, s.artifacts_dir, s.backups_dir):
        d.mkdir(parents=True, exist_ok=True)
    return s


def reset_settings_cache() -> None:
    get_settings.cache_clear()
