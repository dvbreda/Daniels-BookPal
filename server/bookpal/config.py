"""Instellingen, gelezen uit environment-variabelen met prefix ``BOOKPAL_``."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BOOKPAL_", env_file=".env", extra="ignore")

    # Waar de SQLite-database staat. De map wordt aangemaakt als hij nog niet bestaat.
    data_dir: Path = Path("./data")

    # Waar herschaalde pagina's en covers gecached worden.
    cache_dir: Path = Path("./data/cache")

    # Waar hoofdstukken van een bron (M5) belanden. Dit is een gewone map die
    # ook gescand wordt, zodat gedownloade en eigen bestanden hetzelfde pad
    # door de app volgen.
    download_dir: Path = Path("./data/downloads")

    # Maximale grootte van de beeldcache in megabytes; 0 = onbeperkt.
    cache_max_mb: int = 4096

    # CORS-origins voor de web-app tijdens ontwikkeling.
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @property
    def database_url(self) -> str:
        return f"sqlite:///{(self.data_dir / 'bookpal.db').resolve()}"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.download_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
