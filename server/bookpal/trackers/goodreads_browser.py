"""Goodreads koppelen via een echte browser (M7).

Goodreads geeft sinds eind 2020 geen API-sleutels meer uit en hun inlog loopt
via Amazon. Er bestaat ook geen derde-partij-API die kán schrijven: alles wat
er is, leest alleen publieke gegevens. Wie zijn planken wil bijwerken heeft dus
geen andere weg dan de site zelf bedienen.

Dat is bewust defensief gebouwd, want het is de meest breekbare koppeling in de
app:

* **Nooit een CAPTCHA of verificatiestap omzeilen.** Als Amazon er een opwerpt,
  stopt het hier en krijg jij de vraag te zien om zelf te beantwoorden. Die
  controle staat er om te weten dat er een mens achter zit — dat is dan ook zo,
  alleen zit die ergens anders.
* **Zacht falen.** Als Goodreads morgen zijn HTML verandert, stopt de sync en
  blijft de rest van de app gewoon werken.
* **Een screenshot bij elke mislukking**, want zonder beeld is een kapotte
  selector niet te vinden.

De sessie wordt bewaard zodat er niet bij elke ronde opnieuw ingelogd hoeft te
worden; herhaald inloggen is precies wat Amazon als verdacht ziet.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

from bookpal.config import settings
from bookpal.trackers.base import ReadingStatus, TrackerError

logger = logging.getLogger(__name__)

SIGN_IN_URL = "https://www.goodreads.com/user/sign_in"
SEARCH_URL = "https://www.goodreads.com/search"

# Waar de browser en de foutscreenshots belanden. In /data, zodat ze een
# herbouw van de image overleven en niet in de container-laag groeien.
BROWSER_DIR = "/data/playwright"

_SHELF = {
    ReadingStatus.READING: "currently-reading",
    ReadingStatus.COMPLETED: "read",
    ReadingStatus.PLAN_TO_READ: "to-read",
    ReadingStatus.ON_HOLD: "to-read",
    ReadingStatus.DROPPED: "to-read",
}


class GoodreadsChallenge(TrackerError):
    """Amazon wil een CAPTCHA of code zien.

    Geen fout in onze code en niets om omheen te werken: de vraag hoort bij de
    accounteigenaar terecht te komen. ``image_path`` wijst naar wat er getoond
    werd, ``kind`` zegt of het om een plaatje of een toegestuurde code gaat.
    """

    def __init__(self, kind: str, message: str, image_path: str | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.image_path = image_path


@dataclass
class SyncReport:
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def available() -> tuple[bool, str]:
    """Kan er überhaupt een browser gestart worden?

    Chromium wordt pas op verzoek gedownload — een NAS hoeft geen 170 MB
    browser te dragen voor een koppeling die je misschien nooit aanzet.
    """
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        return False, "playwright is niet geïnstalleerd"

    browsers = Path(BROWSER_DIR)
    if not browsers.is_dir() or not any(browsers.glob("chromium*")):
        return False, "de browser is nog niet gedownload"
    return True, ""


def install_browser() -> str:
    """Haal Chromium op. Duurt een minuut en gebeurt één keer."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        raise TrackerError(f"browser downloaden mislukt: {result.stderr[-300:]}")
    return "browser geïnstalleerd"


def _shot(page: Any, naam: str) -> str | None:
    """Bewaar wat er op het scherm stond. Zonder beeld is een kapotte selector
    niet te vinden."""
    try:
        path = Path(BROWSER_DIR) / "schermen"
        path.mkdir(parents=True, exist_ok=True)
        target = path / f"{naam}.png"
        page.screenshot(path=str(target), full_page=False)
        return str(target)
    except Exception:  # pragma: no cover - diagnostiek mag nooit de oorzaak zijn
        logger.warning("screenshot %s mislukt", naam, exc_info=True)
        return None


def _detect_challenge(page: Any) -> None:
    """Kijk of Amazon een controle opwerpt, en stop dan.

    Bewust géén poging om er langs te komen: dat is precies waar zo'n controle
    voor bedoeld is. De vraag gaat naar de accounteigenaar.
    """
    html = page.content().lower()

    # AWS WAF: Goodreads geeft dan een vrijwel lege pagina met een
    # javascript-uitdaging terug in plaats van de site. Gemeten op een echte
    # ingelogde sessie — inloggen lukt, maar elke pagina daarna is dit.
    if "awswafcookiedomainlist" in html or "gokuprops" in html:
        raise GoodreadsChallenge(
            "waf",
            "Goodreads herkent de geautomatiseerde browser en serveert een botcontrole "
            "(AWS WAF). Inloggen lukt wel, maar de site zelf blijft dicht.",
            _shot(page, "waf"),
        )

    if page.locator("#auth-captcha-image").count() or "enter the characters you see" in html:
        raise GoodreadsChallenge(
            "captcha",
            "Amazon vraagt om een CAPTCHA. Los hem op in de app om door te gaan.",
            _shot(page, "captcha"),
        )
    if page.locator("#auth-mfa-otpcode").count() or "two-step verification" in html:
        raise GoodreadsChallenge(
            "otp",
            "Amazon vraagt om een verificatiecode (tweestapsverificatie).",
            _shot(page, "otp"),
        )
    if "approve the notification" in html or "we sent a notification" in html:
        raise GoodreadsChallenge(
            "approval",
            "Amazon wacht op goedkeuring in je Amazon-app; keur het daar goed en probeer opnieuw.",
            _shot(page, "approval"),
        )


def log_in(email: str, password: str) -> dict[str, Any]:
    """Log in en geef de sessie terug om te bewaren.

    Het wachtwoord wordt hier alleen gebruikt, niet bewaard: wat er teruggaat is
    de sessie, en daarmee hoeft er de volgende keer niet opnieuw ingelogd te
    worden — herhaald inloggen is precies wat Amazon als verdacht ziet.
    """
    ok, reden = available()
    if not ok:
        raise TrackerError(reden)

    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(args=["--no-sandbox"])
        except PlaywrightError as exc:
            # Meestal ontbrekende systeembibliotheken; een kale
            # TargetClosedError zegt de gebruiker niets.
            raise TrackerError(
                "de browser kon niet starten. Draait de container met de "
                f"laatste image? ({exc})"
            ) from exc
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="en-US",
        )
        page = context.new_page()
        try:
            page.goto(SIGN_IN_URL, wait_until="networkidle", timeout=45_000)
            # Goodreads toont eerst keuzeknoppen; het e-mailformulier zit
            # achter "Sign in with email" en staat op Amazons inlogdomein.
            page.get_by_text("Sign in with email").first.click()
            page.wait_for_load_state("networkidle", timeout=45_000)

            page.fill("#ap_email", email)
            page.fill("#ap_password", password)
            page.click("#signInSubmit")
            page.wait_for_load_state("networkidle", timeout=45_000)

            _detect_challenge(page)

            if "/ap/signin" in page.url:
                raise TrackerError(
                    "Inloggen is niet gelukt; controleer je e-mailadres en wachtwoord."
                )

            state: dict[str, Any] = context.storage_state()
            return state
        except PlaywrightTimeout as exc:
            _shot(page, "timeout")
            raise TrackerError(f"Goodreads reageerde niet op tijd: {exc}") from exc
        finally:
            context.close()
            browser.close()


def push(state: dict[str, Any], entries: list[tuple[str, str, ReadingStatus]]) -> SyncReport:
    """Zet planken bij Goodreads.

    ``entries`` is (titel, auteur, status). Er wordt op titel gezocht en de
    eerste treffer gepakt — bewust lomp, want een exacte koppeling per boek
    zou je handmatig moeten leggen en dat is niet waar dit voor is.
    """
    ok, reden = available()
    if not ok:
        raise TrackerError(reden)

    from playwright.sync_api import sync_playwright

    report = SyncReport()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox"])
        context = browser.new_context(storage_state=state)
        page = context.new_page()
        try:
            for title, author, status in entries:
                try:
                    _set_shelf(page, title, author, status)
                    report.updated.append(title)
                except GoodreadsChallenge:
                    raise
                except Exception as exc:
                    logger.warning("Goodreads %s: %s", title, exc)
                    report.errors.append(f"{title}: {exc}")
        finally:
            context.close()
            browser.close()
    return report


def _set_shelf(page: Any, title: str, author: str, status: ReadingStatus) -> None:
    query = quote(f"{title} {author}".strip())
    page.goto(f"{SEARCH_URL}?q={query}", wait_until="networkidle", timeout=45_000)
    _detect_challenge(page)

    first = page.locator("a.bookTitle").first
    if not first.count():
        # Een lege pagina betekent hier zelden "niet gevonden": Goodreads
        # serveert dan een botcontrole in plaats van zoekresultaten. Dat
        # onderscheid hoort in de melding, anders ga je selectors debuggen
        # terwijl er iets heel anders aan de hand is.
        if len(page.content()) < 5_000:
            raise GoodreadsChallenge(
                "waf",
                "Goodreads serveert een botcontrole (AWS WAF) in plaats van de pagina. "
                "De geautomatiseerde sessie wordt herkend; gebruik de CSV-export.",
                _shot(page, "waf"),
            )
        raise TrackerError("niet gevonden op Goodreads")
    first.click()
    page.wait_for_load_state("networkidle", timeout=45_000)

    shelf = _SHELF[status]
    # Goodreads heeft twee varianten van de plankknop naast elkaar (oud en
    # nieuw); proberen tot er een werkt is minder broos dan gokken welke.
    for selector in (
        f'button[aria-label*="{shelf}"]',
        'button:has-text("Want to Read")',
        ".wtrToRead",
    ):
        target = page.locator(selector).first
        if target.count():
            target.click()
            page.wait_for_timeout(1200)
            return
    raise TrackerError("de plankknop is niet gevonden; Goodreads heeft z'n pagina gewijzigd")


def sidecar_dir() -> Path:
    return Path(settings.data_dir) / "playwright"
