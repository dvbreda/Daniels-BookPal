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

    # M5: automatisch abonnementen bijwerken en vooruitlezen. Uit te zetten als
    # je liever zelf bepaalt wanneer er verkeer naar een bron gaat.
    subscriptions_enabled: bool = True
    subscriptions_interval_minutes: int = 60

    # M7: gedebouncede tracker-push na een voortgangsupdate. Uit in tests
    # (elders uitgezet via monkeypatch), anders blijft er een echte
    # achtergrond-timer hangen na de teardown van elke test.
    trackers_enabled: bool = True
    # Hoe lang een serie stil moet blijven voordat de push echt uitgaat.
    # Voorkomt dat elke paginawissel een eigen aanroep naar MyAnimeList wordt.
    tracker_debounce_seconds: float = 20.0

    @property
    def database_url(self) -> str:
        return f"sqlite:///{(self.data_dir / 'bookpal.db').resolve()}"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.download_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
