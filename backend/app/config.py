"""
Réglages, lus dans l'environnement (préfixe MT_) ou un fichier .env.

    MT_DEMO=1            mode démo : fournisseur simulé, base séparée pré-remplie
    MT_PROVIDER=yahoo    fournisseur de données ("yahoo" ou "simule")
    MT_DB_PATH=...       chemin du fichier SQLite
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MT_", env_file=ROOT / ".env", extra="ignore")

    demo: bool = False
    provider: str = "yahoo"
    db_path: Path | None = None
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    # Durée de validité du cache des cours du jour (les cours passés ne changent plus).
    cache_ttl_minutes: int = 360

    @property
    def effective_provider(self) -> str:
        return "simule" if self.demo else self.provider

    @property
    def database_url(self) -> str:
        path = self.db_path or ROOT / "data" / ("demo.db" if self.demo else "mini_terminal.db")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{Path(path).as_posix()}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
