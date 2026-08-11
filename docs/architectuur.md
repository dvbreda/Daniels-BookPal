# Daniels BookPal — architectuur & routekaart

## Context

Daniel wil één samenhangend lees-ecosysteem voor zijn eigen
collectie: comics (cbz/cbr), manga en boeken (epub/pdf) die op zijn UGREEN NASync DXP2800 staan,
leesbaar op iOS, Kobo en in de browser — met leesvoortgang die overal synct, zelfgemaakte tabs met
voorwaarden, slimme collecties, MangaDex-abonnementen die naar lokaal te downloaden zijn, vertaling
van zowel epubs als tekstwolkjes, en eenrichtingssync naar MyAnimeList en Goodreads.

Vandaag bestaat dat niet in één product: Panels is alleen iOS en kent geen MangaDex-bronnen,
Tachimanga doet bronnen maar geen eigen NAS-bibliotheek, Komga/Kavita doen de server maar hebben
geen goede iOS-lezer of vertaling. Het doel is die werelden achter één API en één datamodel te
zetten, zodat elk apparaat dezelfde bibliotheek, tabs en voortgang ziet.

Dit document legt de architectuur en het datamodel vast. **M0 en M1 zijn gebouwd**; de latere
milestones staan erin zodat de vroege keuzes ze niet blokkeren.

## Vastgelegde keuzes

| Onderwerp | Keuze |
|---|---|
| Volgorde | Server + web eerst; iOS en Kobo praten daarna met dezelfde API |
| Server | Python 3.12 + FastAPI + SQLite (WAL) via SQLAlchemy, in Docker op de NAS |
| Hardware | Intel N100, 8 GB DDR5 — x86, dus server-side OCR is haalbaar in een achtergrond-queue |
| Kobo | Géén KOReader. Server-rendered "Lite"-webversie, Nickel-integratie in de instellingen, en een eigen native app op FBInk (gestart via NickelMenu) |
| Kobo-lezer | Comics zelf tekenen; epub/pdf via **crengine + MuPDF** — dezelfde libraries die KOReader wrapt |
| Bubble-vertaling | Server-side pipeline met cache, plus on-device iOS-fallback |
| iOS | SwiftUI, sideload/TestFlight via betaald developer-account (geen App Store-review) |
| Vertaling | Gemini als eerste provider achter een `TranslationProvider`-interface |
| Trackers | Eenrichting: MyAnimeList via officiële API, Goodreads via automatisering van je eigen account |
| Repo | Privé — geen licentiebeperkingen op het linken van crengine/MuPDF |
| Toegang op afstand | ZeroTier naar de NAS; opslag zit achter een `storage/`-interface zodat Dropbox later kan |

## Repo-indeling

```
server/     Python 3.12 + FastAPI (Docker image, ook de worker)
web/        React + TypeScript + Vite PWA
ios/        SwiftUI Xcode-project
kobo/       bookpal-kobo — C11 + FBInk + crengine + MuPDF, cross-compiled voor armhf
docker/     compose + Dockerfiles
docs/       architectuur, API-contract, setup-notities
```

## Server-modules

- `library/scanner.py` — loopt de library-roots af, incrementeel (pad + grootte + mtime), met
  `watchdog` voor live wijzigingen. Nooit een volledige rescan als het niet hoeft.
- `formats/` — één interface (`page_count`, `get_page(i)`, `toc`, `metadata`) met adapters:
  `cbz.py` (zipfile), `cbr.py` (**libarchive/`bsdtar`, niet `unrar`** — vermijdt de unrar-licentie en
  leest RAR5), `epub.py` (ebooklib + eigen spine-parser), `pdf.py` (PyMuPDF).
- `metadata/` — ComicInfo.xml, epub-OPF, en filename-parsing voor serie/volume/hoofdstuk.
- `tabs/` — de regel-engine (zie hieronder), gedeeld door tabs én slimme collecties.
- `sources/` — `Source`-interface (`search`, `detail`, `chapters`, `page_urls`, `download`).
  Eerste implementatie `mangadex.py`.
- `trackers/` — `Tracker`-interface, `mal.py` en `goodreads.py`.
- `progress/` — REST-endpoints; elke client post dezelfde positie.
- `images/` — **de spil voor Kobo**: pagina's herschalen en hercoderen per doel-profiel (WebP voor
  web/iOS; Gray8 op exacte paneelresolutie, gedither, voor de Kobo), met schijfcache.
- `opds/` — OPDS 1.2 + OpenSearch per tab/collectie. Klein en goedkoop vangnet voor andere apps.
- `lite/` — server-rendered HTML voor de Kobo-browser.
- `kobosync/` — de Nickel-integratie uit de instellingen.
- `translate/` — provider-interface, `gemini.py`, plus de bubble-pipeline.
- `auth/` — één gebruiker, meerdere apparaat-tokens; secrets in een aparte store, nooit in de repo.

## Zes ontwerpen die de rest bepalen

### 1. Herkomst ("strips uit Europa" vs "manga uit Japan")

Dit is de lastigste eis, want **ComicInfo.xml kent geen land van herkomst** — alleen `LanguageISO`,
`Publisher` en `Manga=Yes/YesAndRightToLeft`. `origin_language` en `origin_country` worden dus op
Series afgeleid via een keten, eerste treffer wint:

1. handmatige override in de UI (altijd het laatste woord);
2. online metadata — MangaDex geeft `originalLanguage` (`ja`/`ko`/`zh`/`en`) rechtstreeks;
3. ComicInfo-signalen: `Manga=YesAndRightToLeft` → `ja`, `LanguageISO`, uitgever-mapping
   (Dupuis/Dargaud/Casterman → `be`/`fr`, Shueisha/Kodansha → `ja`);
4. de default van de library-root (`/manga` → `ja`, `/strips` → `eu`).

Regels filteren op een afgeleide `origin_region` (`europe`/`japan`/`korea`/`us`/…), niet op los land,
zodat één tab-regel niet twaalf landen hoeft op te sommen.

### 2. Regel-engine voor tabs en slimme collecties

Een tab = naam + icoon + volgorde + **regel** + weergave (`grid`/`list`, `group_by`). Een regel is een
JSON-boom (`and`/`or`/`not` + condities op `extension`, `origin_region`, `root`, `tag`, `publisher`,
`series`, `source` (`local`/`remote`), `reading_status`). Die boom wordt **gecompileerd naar een
SQLAlchemy-query** — geen `eval`, geen stringinterpolatie.

```jsonc
// "Strips"
{"and": [{"extension": {"in": ["cbz","cbr"]}}, {"origin_region": {"eq": "europe"}}]}
```

Slimme collecties gebruiken exact dezelfde engine plus een `group_by` (serie, map, auteur, jaar);
"submappen als collectie" is die engine met `group_by: folder` op een root die dat aan heeft staan.
Eén engine, drie features — dit is de belangrijkste reden om dit vroeg goed te zetten.

### 3. Kobo zonder KOReader — drie lagen

**Laag A — BookPal Lite (server-side, geen code op het apparaat).** De Kobo-browser is een oude
QtWebKit met bewust beperkte JavaScript; een moderne React/Vite-build draait daar simpelweg niet.
Daarom een aparte, server-gerenderde HTML-weergave: geen framework, geen moderne JS, grote
tapdoelen, en paginanavigatie via **gewone links**. Dat laatste is het slimme deel — een pagina
omslaan is een GET, dus de server registreert de voortgang zonder ook maar één regel JavaScript.
Beelden komen al op paneelresolutie en in grijstinten binnen.

**Laag B — Nickel-integratie, aan/uit in de instellingen.** Voor als je gewoon in Kobo's eigen lezer
wilt lezen. Per onderdeel te schakelen:
- **Boeken wegzetten** — gekozen tabs worden naar een doelmap gesynct (USB-mount, netwerkmap of een
  Dropbox-map die de Kobo zelf ophaalt), met een read-ahead van N items per serie.
- **Tabs als Kobo-collecties** — jouw tabs worden als shelves in `KoboReader.sqlite` geschreven;
  dezelfde tabel die Calibre al beschrijft.
- **Voortgang teruglezen** — `___PercentRead`, `ReadStatus` en `DateLastRead` uit diezelfde database
  terug naar de NAS, zodat lezen in Nickel óók meetelt.
Dit is de enige laag die op reverse-engineering leunt en dus een firmware-update kan overleven of
niet; hij staat daarom apart en is uitschakelbaar.

**Laag C — `bookpal-kobo`, eigen native app op FBInk.** C11, cross-compiled met `koxtoolchain` voor
armhf, gestart via NickelMenu (dat staat er al op).
- **FBInk** doet het framebuffer-tekenwerk en de EPDC-verversing — snelle A2-modus bij het omslaan,
  volle GC16 bij een nieuwe pagina — en levert via `fbink_input_scan`/libevdev de touch-invoer.
- **Comics**: het apparaat doet bijna geen werk. De server stuurt kant-en-klare, al geditherde
  Gray8-beelden op exact de paneelresolutie, dus de Kobo blit alleen nog. Dezelfde
  `images/`-pipeline als web en iOS, ander profiel — en de reden dat dit vlot kan zijn op zulke
  hardware. Inclusief RTL-paginarichting, marges bijsnijden en panel-zoom.
- **Epub en pdf**: we schrijven géén layoutengine — dat doet KOReader ook niet. Die wrapt
  **crengine** (CoolReader, epub/fb2, met hyphenation en CSS) en **MuPDF** (pdf, en ook cbz/cbr).
  Wij linken dezelfde twee C-libraries; ze cross-compilen al aantoonbaar voor armhf. Daarmee is dit
  vooral integratie- en UI-werk in plaats van maandenlang engine-bouwen. Vertaalde epubs zijn
  server-side al gegenereerd, dus de Kobo-app hoeft daar niets extra's voor te doen.
- Eigen UI: tabs → serie → hoofdstuk → lezer, met tap links/rechts, swipe en long-press-menu.
- Voortgang gaat rechtstreeks naar de server met onze eigen boek-ID's — geen Nickel-database nodig.
- Buitenshuis vereist ZeroTier op de Kobo; binnen wifi praat het apparaat direct met de NAS.

### 4. Voortgang-sync

Positie wordt per (gebruiker, boek) opgeslagen als `{page}` voor comics of een CFI voor epub, met
apparaat en tijdstempel; laatste schrijver wint, maar het conflict blijft zichtbaar in de API. Alle
clients gebruiken hetzelfde endpoint, dus er is één waarheid en geen vertaallaag tussen
apparaat-specifieke identifiers.

### 5. Vertaling

**Epub, twee modi.** (a) Server genereert een volledig vertaalde epub met Gemini — tekst per
hoofdstuk gechunkt, inline HTML-tags behouden, resultaat gecached en downloadbaar. Deze modus werkt
overal, ook op de Kobo, dus die bouwen we eerst. (b) Op iOS per alinea live via het Apple
`Translation`-framework (SwiftUI-only API, wat past omdat de app SwiftUI is).

**Tekstwolkjes.** Pipeline op de NAS: YOLOv8-bubbeldetectie (ONNX) → crop → OCR (`manga-ocr` voor
verticaal Japans, PaddleOCR voor latijns schrift) → Gemini-vertaling mét paginacontext, zodat losse
wolkjes niet uit hun verband vertaald worden. Resultaat per pagina opgeslagen als polygonen +
brontekst + vertaling; web en iOS tekenen daar een overlay mee. **Voor de Kobo bakt de server de
vertaling direct in het gerenderde beeld** — dat kan juist omdat die beelden toch al server-side
klaargemaakt worden. Geen inpainting in v1; overlay is goedkoper en goed genoeg. De queue geeft
prioriteit aan de pagina's vóór je leespositie, zodat de NAS vooruitloopt op wat je leest. iOS valt
terug op Vision + Apple Translate als de NAS onbereikbaar is.

### 6. Trackers (eenrichting, BookPal → buiten)

Eén `Tracker`-interface, twee implementaties. Eenrichting betekent: nooit teruglezen, dus geen
conflictafhandeling. Per tab of library instelbaar welke tracker geldt (manga → MAL, boeken →
Goodreads). Pushen gebeurt bij het uitlezen van een hoofdstuk of boek, gedebounced per serie.

- **MyAnimeList** — officiële API v2, OAuth2 met PKCE, `PATCH /v2/manga/{id}/my_list_status` met
  `num_chapters_read`, `num_volumes_read`, `status` en `score`. De ID-koppeling komt grotendeels
  gratis: MangaDex geeft de MAL-id mee in de external links van een serie. Voor lokale bestanden een
  titelzoekopdracht met handmatige bevestiging, opgeslagen op de serie.
- **Goodreads** — de publieke API is dood (sinds eind 2020 geen nieuwe keys, geen ondersteuning), dus
  dit gaat via automatisering van je eigen account: eenmalig inloggen met een headless browser om de
  sessiecookies te bemachtigen, daarna gewone form-posts met `httpx` en die cookiejar. Bewust
  defensief gebouwd: staat standaard uit, heeft een dry-run-modus die laat zien wát er gepusht zou
  worden, is streng gerate-limit, en **faalt zacht** — als Goodreads z'n UI wijzigt stopt de sync,
  maar je blijft gewoon lezen. Als vangnet levert dezelfde module ook een Goodreads-CSV-export
  (My Books → Import and Export), zodat je nooit klemzit als de automatisering breekt.

## Datamodel (kern)

`library_root` · `file` (pad, grootte, mtime, hash) · `series` (titel, sorteertitel,
`origin_language`, `origin_country`, uitgever, tags, bron-ref, `tracker_ids`) · `book` (serie, soort,
nummer, titel, paginacount, bestand óf bron-ref) · `progress` · `tab` · `collection` · `source` ·
`subscription` (policy `permanent`/`readahead`, `readahead_n`, `ttl_days`) · `download_job` ·
`translation` · `tracker_account` · `setting`.

Boeken hebben een bestand **of** een bron-referentie — dat is wat lokale en geabonneerde items in
dezelfde tab laat verschijnen, en wat "tijdelijk downloaden om vooruit te lezen" mogelijk maakt
(bestand erbij, TTL-opruiming laat de bron-referentie intact).

## Milestones

| # | Inhoud | Resultaat |
|---|---|---|
| **M0** | Monorepo, Dockerfile + compose, ruff/mypy/pytest, tsc/vitest, GitHub Actions | CI groen |
| **M1** | Scanner, formats, metadata, SQLite, REST API, cover/pagina-serving; web: bibliotheek + comic-lezer | *"Ik lees mijn strips in de browser"* |
| **M2** | Voortgang-sync + Kobo-beeldprofiel + **BookPal Lite** + **Nickel-integratie in settings** + OPDS | Kobo leest en synct, zonder code op het apparaat |
| **M3** | Regel-engine: tabs + slimme collecties, met UI om ze te maken | Eigen tabs op alle clients |
| **M4** | iOS-app: bibliotheek, native comic-lezer, downloads, sync | Panels-achtige ervaring |
| **M5** | MangaDex-bron: zoeken, volgen, online lezen, permanent/tijdelijk downloaden | Abonnementen |
| **M6** | Epub/pdf-lezer (foliate-js) + epub-vertaling via Gemini | Boeken + vertaalde epubs |
| **M7** | Tracker-sync: MyAnimeList + Goodreads, eenrichting | Je lijsten lopen vanzelf bij |
| **M8** | Bubble-pipeline + iOS on-device fallback + ingebakken versie voor Kobo | Vertaalde manga |
| **M9** | `bookpal-kobo`: FBInk, touch, tabs, comics, offline, NickelMenu-installer | Eigen native comic-lezer op de Kobo |
| **M10** | `bookpal-kobo`: epub + pdf via crengine en MuPDF | Volwaardige eigen lezer op de Kobo |

## M0 + M1 — gebouwd

1. **M0** — `server/` met FastAPI-skelet, `pyproject.toml` (ruff, mypy, pytest), Dockerfile met
   libarchive; `web/` met Vite + React + TS + Tailwind + TanStack Query; `compose.yml` met
   volumes voor je library-roots, de SQLite-DB en de paginacache; GitHub Actions die lint + tests
   draait. Testfixtures worden **gegenereerd** (kleine cbz/cbr/epub/pdf) zodat er geen materiaal in
   de repo komt.
2. **Datamodel + migraties** — bovenstaande tabellen via SQLAlchemy + Alembic, inclusief de velden
   die pas later gevuld worden (`origin_*`, bron-refs, `tracker_ids`), zodat de latere milestones
   geen migratiepijn geven.
3. **Scanner + formats** — incrementele scan, ComicInfo/OPF/filename-metadata, serie-groepering en
   de herkomst-keten uit ontwerp 1.
4. **API** — `/api/libraries`, `/api/series`, `/api/books`, `/api/books/{id}/pages/{n}` (met
   profiel-parameter voor formaat/breedte en schijfcache), `/api/books/{id}/cover`, `/api/progress`.
   Het beeldprofiel wordt meteen als concept ingebouwd, want daar hangen M2 en M9 volledig aan.
5. **Web-lezer** — bibliotheekgrid met covers, en de comic-lezer met paged LTR/RTL, automatische
   dubbele-pagina-detectie, continue verticale modus voor webtoons, pinch/scroll-zoom, fit-modi en
   preload van omliggende pagina's. Voor epub/pdf komt in M6 **foliate-js** (MIT; epub/mobi/fb2/cbz
   en pdf via pdf.js) — die engine wordt ook in een WKWebView op iOS hergebruikt, zodat er maar één
   epub-lezer voor web en iOS onderhouden hoeft te worden.

## Verificatie

- `docker compose up` op de NAS; scan een echte root en controleer serie-groepering en covers.
- `pytest` op de gegenereerde fixtures: scanner-idempotentie (tweede scan = nul wijzigingen),
  format-adapters, herkomst-keten per stap, regel-compiler (JSON → verwachte resultaatset),
  beeldprofielen (juiste afmeting, grijswaarden, cache-hit).
- `curl` op de endpoints; pagina-serving controleren op formaat en cache-gedrag.
- Web-app in de browser: een cbz, een cbr en een RTL-manga doorbladeren; voortgang overleeft refresh.
- Vanaf M2: op de Kobo-browser naar `/lite` — bladeren, lezen, en controleren dat de voortgang zonder
  JavaScript meeloopt in de web-app; daarna de Nickel-integratie aanzetten en een boek in Kobo's
  eigen lezer half uitlezen, en zien dat het percentage terugkomt.
- Vanaf M7: trackers eerst in dry-run draaien en de voorgenomen pushes nalopen voordat het live gaat.
- Vanaf M9: `bookpal-kobo` cross-compilen, via NickelMenu starten, en de verversingsmodi visueel
  controleren (geen spookbeelden bij snel omslaan).

## Aandachtspunten

- **MangaDex** — publieke API met een minimum van ~5 req/s per IP en strengere limieten op
  `/at-home/server/`. De source-laag krijgt een rate-limiter en een eigen User-Agent; gebruik blijft
  persoonlijk. Sideload via je developer-account betekent dat App Store-regels niet in de weg zitten.
- **Goodreads-automatisering is inherent breekbaar.** Het is je eigen account en je eigen data, dus
  er is niets mis mee, maar er is geen contract: elke UI-wijziging kan de sync stilleggen. Vandaar de
  zachte failure, de dry-run en de CSV-export ernaast.
- **N100** — genoeg voor OCR in een achtergrond-queue (orde grootte seconden per pagina), niet voor
  realtime. De worker draait als apart compose-profiel dat je uit kunt zetten; de iGPU kan later via
  OpenVINO ingezet worden als het te traag blijkt.
- **De Kobo-app is de grootste brok na iOS**, en staat bewust achteraan: laag A en B geven je al een
  werkende Kobo, en tegen die tijd staan de API en de beeldpipeline vast.
- **Scope** — dit is een meermaandsproject. Elke milestone levert iets bruikbaars op, zodat er
  onderweg altijd iets werkt in plaats van pas aan het eind.
