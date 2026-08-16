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
    # Vooruit downloaden terwijl je leest, gedebounced per serie. De ronde op
    # een interval houdt een serie bij; deze loopt achter je aan zodra je een
    # paar hoofdstukken achter elkaar omslaat. 0 zet het uit.
    readahead_debounce_seconds: float = 15.0

    # M7: gedebouncede tracker-push na een voortgangsupdate. Uit in tests
    # (elders uitgezet via monkeypatch), anders blijft er een echte
    # achtergrond-timer hangen na de teardown van elke test.
    trackers_enabled: bool = True
    # Hoe lang een serie stil moet blijven voordat de push echt uitgaat.
    # Voorkomt dat elke paginawissel een eigen aanroep naar MyAnimeList wordt.
    tracker_debounce_seconds: float = 20.0

    # M8: tekstwolkjes vertalen via Gemini. Zonder sleutel blijft alles
    # gewoon werken; de lezer toont dan het origineel.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3-flash-preview"
    # Waarheen vertaald wordt als de client niets meegeeft.
    translate_lang: str = "nl"
    # De achtergrondwachtrij die pagina's vooruit vertaalt. Uit in tests
    # (elders uitgezet via monkeypatch), anders blijft er een thread hangen.
    translations_enabled: bool = True
    # Vooruit vertalen vanaf je leespositie, net als het vooruitlezen van M5:
    # de NAS loopt vast op wat je zo gaat lezen. 0 zet het uit.
    translate_readahead_pages: int = 3

    # De twee beeldmodellen die een hele pagina hertekenen mét vertaling. Duur
    # per pagina, dus nooit vanzelf — tenzij je de stand "vanzelf" bewust op een
    # beeldstand zet, en dan kost elke paginawissel translate_readahead_pages
    # pagina's. Zie docs/architectuur.md onder "De drie vertaalstanden" voor de
    # gemeten kwaliteit.
    gemini_image_model_fast: str = "gemini-3.1-flash-image"
    gemini_image_model_pro: str = "gemini-3-pro-image"

    # Mappen waar losse bestanden vandaan komen om te importeren: downloads,
    # een Dropbox-map, wat iemand je stuurt. Read-only aankoppelen mag niet —
    # importeren verplaatst.
    intake_dirs: list[str] = ["/intake"]

    # Waar vertalingen blijvend bewaard worden, buiten de database om. Een
    # vertaling kost geld; die mag niet verdwijnen als de database opnieuw
    # wordt opgebouwd. De collectie zelf is read-only aangekoppeld, dus dit
    # kan niet naast de strips staan — vandaar een eigen map.
    sidecar_dir: Path = Path("./data/vertalingen")

    @property
    def database_url(self) -> str:
        return f"sqlite:///{(self.data_dir / 'bookpal.db').resolve()}"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.sidecar_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
