"""Bestanden van een link halen: een Dropbox-map, een deellink, een download.

Bedoeld voor het geval dat je iets ergens anders hebt staan en het op de NAS
wilt hebben zonder eerst je laptop erbij te pakken. Je plakt de deellink en
BookPal haalt hem op.

Twee dingen die hier belangrijker zijn dan gemak:

* **Waar de server heen mag.** Een endpoint dat een opgegeven URL ophaalt, haalt
  hem op vanaf de NAS — dus van binnen je eigen netwerk. Zonder controle is dat
  een manier om via BookPal bij je router, je andere containers of een
  cloud-metadata-adres te komen. Elke hop wordt daarom gecontroleerd, ook na een
  omleiding, en alles wat naar een privé-adres wijst gaat eruit.
* **Wat er binnenkomt.** Een deellink naar een map levert een zip met van alles
  erin. Alleen bestanden die BookPal kan lezen worden eruit gehaald, en nooit
  buiten de doelmap geschreven — een zip mag paden bevatten als
  ``../../etc/iets``.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlencode, urlparse, urlunparse

import httpx

from bookpal.formats import SUPPORTED_EXTENSIONS

logger = logging.getLogger(__name__)


class RemoteError(RuntimeError):
    """De link deed niet wat we ervan verwachtten."""


# Ruim genoeg voor een deel of een map met hoofdstukken, krap genoeg dat een
# vergissing niet je hele schijf vult.
MAX_BYTES = 4 * 1024 * 1024 * 1024

_MAX_REDIRECTS = 5
_CHUNK = 1024 * 1024

# Beeldformaten die in een cbz horen. Een zip met alleen deze erin is een
# hoofdstuk dat toevallig niet zo heet.
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"}

_UNSAFE_IN_NAME = re.compile(r"[^A-Za-z0-9 ._()\[\]-]+")


@dataclass
class FetchReport:
    saved: list[str] = field(default_factory=list)
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def normalise_url(url: str) -> str:
    """Maak van een deellink een downloadlink.

    Dropbox toont bij ``dl=0`` een voorbeeldpagina in plaats van het bestand;
    dat is HTML en geen strip. Hetzelfde geldt voor de nieuwere ``/scl/``-links.
    """
    parts = urlparse(url)
    host = (parts.hostname or "").lower()
    if host.endswith("dropbox.com"):
        query = [(key, value) for key, value in parse_qsl(parts.query) if key != "dl"]
        query.append(("dl", "1"))
        return urlunparse(parts._replace(query=urlencode(query)))
    return url


def _check_target(url: str) -> None:
    """Mag de server hierheen?

    Alleen https, en alleen naar een adres buiten je eigen netwerk. Het gaat om
    het IP en niet om de naam: een hostnaam die naar 127.0.0.1 of 192.168.x
    wijst is precies de manier waarop je zo'n endpoint misbruikt.
    """
    parts = urlparse(url)
    if parts.scheme != "https":
        raise RemoteError("alleen https-links worden opgehaald")
    host = parts.hostname
    if not host:
        raise RemoteError("deze link heeft geen adres")

    try:
        adressen = socket.getaddrinfo(host, parts.port or 443, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise RemoteError(f"{host} is niet op te zoeken: {exc}") from exc

    for info in adressen:
        adres = ipaddress.ip_address(info[4][0])
        if (
            adres.is_private
            or adres.is_loopback
            or adres.is_link_local
            or adres.is_reserved
            or adres.is_multicast
            or adres.is_unspecified
        ):
            raise RemoteError(
                f"{host} wijst naar een adres binnen je eigen netwerk; dat haalt BookPal niet op"
            )


def _filename(url: str, headers: httpx.Headers) -> str:
    """Hoe het bestand hoort te heten, zonder de servernaam te vertrouwen."""
    voorstel = ""
    disposition = headers.get("content-disposition", "")
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', disposition)
    if match:
        voorstel = match.group(1)
    if not voorstel:
        # De URL is gecodeerd; "Storm%2003.cbz" hoort "Storm 03.cbz" te worden.
        voorstel = unquote(Path(urlparse(url).path).name)
    voorstel = Path(voorstel).name  # nooit een pad, alleen een naam
    voorstel = _UNSAFE_IN_NAME.sub("_", voorstel).strip(" .")
    return voorstel or "download"


def download(
    url: str,
    target_dir: Path,
    *,
    client: httpx.Client | None = None,
    on_progress: Callable[[int, int | None], None] | None = None,
) -> FetchReport:
    """Haal deze link op en zet wat leesbaar is in ``target_dir``.

    Een zip met hoofdstukken erin — zoals een gedeelde Dropbox-map — wordt
    uitgepakt; een los bestand blijft zoals het is.
    """
    url = normalise_url(url)
    target_dir.mkdir(parents=True, exist_ok=True)
    eigen = client is None
    http = client or httpx.Client(timeout=60.0, follow_redirects=False)

    try:
        response = _get_following_redirects(http, url)
        naam = _filename(str(response.url), response.headers)
        tijdelijk = target_dir / f".{naam}.binnenkomend"
        try:
            _stream_to(response, tijdelijk, on_progress)
            return _place(tijdelijk, naam, target_dir)
        finally:
            tijdelijk.unlink(missing_ok=True)
            response.close()
    finally:
        if eigen:
            http.close()


def _get_following_redirects(http: httpx.Client, url: str) -> httpx.Response:
    """Volg omleidingen met de controle op elke hop.

    Een enkele controle vooraf is niet genoeg: een dienst mag omleiden, en dan
    is de laatste hop het adres dat er werkelijk toe doet.
    """
    for _ in range(_MAX_REDIRECTS):
        _check_target(url)
        try:
            response = http.get(url, follow_redirects=False)
        except httpx.HTTPError as exc:
            raise RemoteError(f"ophalen mislukt: {exc}") from exc
        if response.is_redirect:
            volgende = response.headers.get("location")
            response.close()
            if not volgende:
                raise RemoteError("de server leidt om zonder te zeggen waarheen")
            url = str(httpx.URL(url).join(volgende))
            continue
        if response.status_code >= 400:
            response.close()
            raise RemoteError(f"de server gaf {response.status_code}")
        return response
    raise RemoteError("te veel omleidingen")


def _stream_to(
    response: httpx.Response,
    target: Path,
    on_progress: Callable[[int, int | None], None] | None = None,
) -> None:
    # Hoeveel er komt, als de server het zegt. Bij een Dropbox-map is dat vaak
    # onbekend, en dan is het aantal binnengehaalde bytes het enige teken van
    # leven dat we kunnen geven.
    ruw = response.headers.get("content-length")
    totaal = int(ruw) if ruw and ruw.isdigit() else None

    geschreven = 0
    with target.open("wb") as uit:
        for blok in response.iter_bytes(_CHUNK):
            geschreven += len(blok)
            if geschreven > MAX_BYTES:
                raise RemoteError("dit bestand is groter dan BookPal in één keer ophaalt")
            uit.write(blok)
            if on_progress is not None:
                on_progress(geschreven, totaal)
    if geschreven == 0:
        raise RemoteError("er kwam niets binnen")


def _place(tijdelijk: Path, naam: str, target_dir: Path) -> FetchReport:
    """Zet neer wat er binnenkwam: los bestand, hoofdstuk-zip of map-zip."""
    report = FetchReport()
    suffix = Path(naam).suffix.lower()

    # Alleen ".zip" is dubbelzinnig: dat is net zo goed één hoofdstuk als een
    # gedeelde map met hoofdstukken erin. De andere formaten zijn óók zip —
    # een epub en een cbz zijn dat allebei — maar daar staat de betekenis vast,
    # en die uitpakken zou het boek juist slopen.
    if suffix in SUPPORTED_EXTENSIONS and suffix != ".zip":
        _move_without_overwriting(tijdelijk, target_dir / naam, report)
        return report

    if not zipfile.is_zipfile(tijdelijk):
        raise RemoteError(f"{naam} is niets wat BookPal kan lezen")

    with zipfile.ZipFile(tijdelijk) as archief:
        leden = [item for item in archief.namelist() if not item.endswith("/")]
        leesbaar = [item for item in leden if Path(item).suffix.lower() in SUPPORTED_EXTENSIONS]

        if not leesbaar:
            if leden and all(Path(item).suffix.lower() in _IMAGE_SUFFIXES for item in leden):
                # Alleen plaatjes: dit ís een hoofdstuk, het heet alleen geen cbz.
                doel = target_dir / (naam if suffix == ".cbz" else f"{Path(naam).stem}.cbz")
                _move_without_overwriting(tijdelijk, doel, report)
                return report
            raise RemoteError(f"in {naam} zit niets wat BookPal kan lezen")

        for item in leesbaar:
            veilig = _UNSAFE_IN_NAME.sub("_", Path(item).name).strip(" .")
            doel = target_dir / veilig
            if doel.exists():
                report.skipped += 1
                continue
            with archief.open(item) as bron, doel.open("wb") as uit:
                while blok := bron.read(_CHUNK):
                    uit.write(blok)
            report.saved.append(str(doel))

    return report


def _move_without_overwriting(bron: Path, doel: Path, report: FetchReport) -> None:
    if doel.exists():
        # Nooit overschrijven: wat er staat is waarschijnlijk van jou.
        report.skipped += 1
        return
    bron.replace(doel)
    report.saved.append(str(doel))


__all__ = ["MAX_BYTES", "FetchReport", "RemoteError", "download", "normalise_url"]
