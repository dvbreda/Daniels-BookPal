# Daniels BookPal

Eén leesomgeving voor comics, manga en boeken die op de NAS staan — leesbaar in
de browser, straks op iOS en op de Kobo, met leesvoortgang die overal hetzelfde
is.

De volledige architectuur en routekaart staat in [`docs/architectuur.md`](docs/architectuur.md).

## Wat er nu werkt (M0 + M1)

- **Scannen** van cbz, cbr, cb7, epub en pdf, incrementeel: een bestand dat niet
  veranderd is wordt niet opnieuw geopend.
- **Metadata** uit ComicInfo.xml, epub-OPF en de bestandsnaam, met groepering per
  serie.
- **Herkomst** afgeleid via een keten van sterk naar zwak, zodat "strips uit
  Europa" en "manga uit Japan" uit elkaar te houden zijn — en jouw handmatige
  correctie een rescan overleeft.
- **Beeldprofielen**: dezelfde pagina als WebP voor de browser of als geditherde
  grijswaarden op exacte Kobo-paneelresolutie, met schijfcache.
- **REST-API** voor bibliotheek, series, boeken, pagina's, covers en voortgang.
- **Web-app** met bibliotheekgrid en een stripleer: enkel/dubbel, automatische
  herkenning van dubbelpagina's, doorlopende modus voor webtoons, links-naar-
  rechts én rechts-naar-links, zoom, fit-modi en vooruitladen.

Nog niet: tabs als opslaanbare regels (M3), iOS (M4), MangaDex (M5), vertaling
(M6/M8), trackers (M7) en de Kobo-app (M9/M10).

## Draaien op de NAS

```bash
cp .env.example .env
ls -d /volume1/_*        # kijk welke mappen je écht hebt
nano .env                # zet BOOKPAL_BOEKEN / _STRIPS / _MANGA goed
docker compose -f docker/compose.yml up -d --build
```

Open daarna **`http://<nas>:1997`**, ga naar **Instellingen** en voeg je mappen
toe met het pad **zoals de container ze ziet** — dus `/library/strips`, niet
`/volume1/_strips`. Druk op **Scannen**.

Zet per map de standaard-herkomst goed (`/library/manga` → Japan): dat is het
vangnet voor bestanden zonder ComicInfo.xml, en het is een instelling per map.
Daarom zijn aparte mappen per soort handiger dan één grote map.

De collectie wordt alleen gelezen (`:ro` in de compose); BookPal schrijft
uitsluitend in zijn eigen `/data`-volume.

Wil je Claude Code op de NAS zelf laten draaien, zie
[`docker/claude-code.md`](docker/claude-code.md).

## Lokaal ontwikkelen

```bash
# server
cd server
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/alembic upgrade head
.venv/bin/uvicorn bookpal.main:app --reload

# web (in een tweede terminal)
cd web
npm install
npm run dev          # draait op :5173 en proxyt /api naar :8000
```

API-documentatie draait mee op `http://127.0.0.1:8000/docs`.

## Controleren

```bash
cd server && .venv/bin/ruff check . && .venv/bin/mypy bookpal && .venv/bin/pytest -q
cd web && npm run lint && npm test && npm run build
```

De tests **genereren** hun eigen cbz-, cb7-, epub- en pdf-bestanden; er staat
geen leesmateriaal in de repo.

## Indeling

```
server/     Python 3.12 + FastAPI + SQLite
  bookpal/
    formats/    cbz, cbr (libarchive), epub, pdf — één interface
    metadata/   bestandsnamen ontleden, herkomst-keten
    library/    de scanner
    images/     beeldprofielen en cache
    api/        REST-endpoints
web/        React + TypeScript + Vite
docker/     Dockerfile en compose
docs/       architectuur en routekaart
```
