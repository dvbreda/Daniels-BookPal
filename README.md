# Daniels BookPal

Eén leesomgeving voor comics, manga en boeken die op de NAS staan — leesbaar in
de browser, straks op iOS en op de Kobo, met leesvoortgang die overal hetzelfde
is.

De volledige architectuur en routekaart staat in [`docs/architectuur.md`](docs/architectuur.md).

## Wat er nu werkt (M0 + M1 + M3 + M5 + M6 + M7 + deels M2)

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
- **BookPal Lite** (`/lite`): server-rendered lezer zonder JavaScript voor de
  Kobo-browser. Een pagina omslaan is een gewone link, dus de voortgang wordt
  bijgewerkt zonder dat het apparaat iets hoeft uit te voeren.
- **OPDS** (`/opds`): catalogfeed voor apps die dat al spreken, zoals Chunky of
  KyBook.
- **Tabs en slimme collecties** (`/tabs` en `/collecties` in de web-app):
  opslaanbare regels — combinaties van soort, bestandstype, herkomst, uitgever,
  label, map, bron en leesstatus — die naar een SQLAlchemy-query compileren.
  Eén engine voor allebei; collecties groeperen hun uitkomst bovendien op
  uitgever of map.

- **Bronnen** (`/bronnen` in de web-app): MangaDex zoeken, volgen en
  hoofdstukken ophalen. Een gevolgd hoofdstuk is eerst een boek zonder bestand;
  ophalen hangt er een cbz aan die daarna door dezelfde scanner, lezer en
  beeldprofielen loopt als je eigen bestanden. Kaartjes tonen waar iets vandaan
  komt: geen badge voor je eigen bestanden, ☁ voor wat nog online staat, ✓ voor
  opgehaald en ⏳ met het aantal dagen voor een tijdelijke download.
- **Vooruitlezen**: een achtergrond-worker haalt periodiek nieuwe hoofdstukken
  op en downloadt er `readahead_n` vooruit vanaf waar je gebleven bent.
  Tijdelijke downloads verlopen na hun TTL — dan gaat alleen het bestand weg,
  het hoofdstuk blijft staan. Uit te zetten met `BOOKPAL_SUBSCRIPTIONS_ENABLED=false`,
  of handmatig te draaien via de knop "Nu bijwerken".

- **Epub-lezer** (foliate-js, herschikbare tekst met eigen instellingen voor
  lettergrootte en thema): downloads tonen nu een voortgangsbalk in plaats van
  stil te lijken hangen bij een groot bestand.
- **Trackers** (`/trackers` in de web-app): eenrichtingssync naar MyAnimeList
  na een voortgangsupdate, gedebounced per serie zodat niet elke paginawissel
  een eigen aanroep wordt. Nieuw gekoppelde accounts staan standaard op
  dry-run. Goodreads heeft geen live koppeling meer (de publieke API is dood
  sinds eind 2020) — daarvoor is er een CSV-export voor My Books → Import and
  Export. Uit te zetten met `BOOKPAL_TRACKERS_ENABLED=false`.

Nog niet: Nickel-integratie in de instellingen (rest van M2), iOS (M4),
bubble-vertaling voor manga (M8) en de Kobo-app (M9/M10).

## Draaien op de NAS

Heeft je NAS geen `git`? Dat is normaal op UGOS. Leen hem uit een container in
plaats van hem te installeren — de volledige uitleg staat in
[`docker/claude-code.md`](docker/claude-code.md):

```bash
mkdir -p /volume1/docker/bookpal && cd /volume1/docker/bookpal

# Een GitHub-token, niet je wachtwoord — dat werkt niet meer voor git.
read -rsp "GitHub token: " GH_TOKEN; echo; export GH_TOKEN

docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -e GH_TOKEN \
  -v /volume1/docker/bookpal:/w -w /w alpine/git \
  -c credential.helper='!f(){ echo username=x-access-token; echo password=$GH_TOKEN; };f' \
  clone -b claude/daniels-bookpal-app-wiud2v \
  https://github.com/dvbreda/Daniels-BookPal.git
```

Daarna:

```bash
cd Daniels-BookPal
cp .env.example .env
ls -d /volume1/_*        # kijk welke mappen je écht hebt
nano .env                # zet BOOKPAL_BOEKEN / _STRIPS / _MANGA, HOST_UID en HOST_GID goed
docker compose up -d --build
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
compose.yml         BookPal draaien
compose.claude.yml  Claude Code op de NAS
docker/     Dockerfiles
docs/       architectuur en routekaart
```
