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

Dit document legt de architectuur en het datamodel vast. **M0 tot en met M3 en M5 tot en met M8 zijn
gebouwd**; open staan M4 (iOS) en M9/M10 (de native Kobo-app). Bij M2 hoort één kanttekening: de
Nickel-integratie is gebouwd en getest tegen een nagebootst apparaat, niet tegen een echte Kobo —
zie laag B in ontwerp 3. De latere milestones staan erin zodat de vroege keuzes ze niet blokkeren.

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
- `api/intake.py` — bestanden binnenhalen die niet uit een bron komen: uploaden vanuit de browser en
  deellinks die de NAS zelf ophaalt.
- `wiki/` — achtergrond bij een serie als epub, uit Wikipedia.
- `translate/` — provider-interface, `gemini.py`, plus de bubble-pipeline. Daarnaast `imagepage.py`
  (hele pagina hertekenen én inkleuren), `recolour.py` (de kleur van het model over ons lijnwerk),
  `batch.py` (een heel hoofdstuk in één keer) en `sidecar.py` (betaald werk op schijf).
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
wilt lezen. Drie onderdelen die los aan te zetten zijn, omdat ze los van elkaar nut hebben én los
van elkaar kunnen breken:
- **Boeken wegzetten** — per serie waar je bent plus een paar vooruit, naar een doelmap (USB-mount,
  netwerkmap of een Dropbox-map die de Kobo zelf ophaalt). Een Kobo heeft een paar GB en je leest er
  geen 700 hoofdstukken op, dus wat uit dat venster valt wordt opgeruimd — maar uitsluitend binnen
  onze eigen map.
- **Series als Kobo-planken** — geschreven als shelves in `KoboReader.sqlite`, dezelfde tabel die
  Calibre al beschrijft. Bestaande planken worden aangevuld en nooit vervangen, er wordt nooit iets
  uit `content` verwijderd, en er gaat altijd eerst een kopie van de database naast met tijdstempel.
- **Voortgang teruglezen** — `___PercentRead`, `ReadStatus` en `DateLastRead` uit diezelfde database
  terug naar de NAS, zodat lezen in Nickel óók meetelt. Alleen vooruit: een Kobo die een week in de
  la lag mag je stand niet terugzetten.

Nickel kent zijn boeken pas ná het loskoppelen, dus de eerste ronde na nieuwe bestanden kan nog niet
alles in een plank hangen. Dat komt als melding in het resultaat terug in plaats van stil te
mislukken. Proefstand staat standaard aan.

Dit is de enige laag die op reverse-engineering leunt en dus een firmware-update kan overleven of
niet; hij staat daarom apart en is uitschakelbaar. **En hij is nooit tegen een echt apparaat aan
geweest.** De tests bouwen een nagebootste Kobo — een map met `.kobo/KoboReader.sqlite` die de test
zelf aanmaakt, met dezelfde tabellen als het echte. Dat dekt onze kant (schema, back-up, planken
schrijven, voortgang terughalen), maar het bewijst niets over hoe Nickel reageert op wat wij erin
zetten. Beschouw laag B dus als *gebouwd en getest tegen een reconstructie*, niet als af.

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
`origin_language`, `origin_country`, uitgever, tags, bron-ref, `tracker_ids`, `sidecar_path`) ·
`edition` (uitgave binnen een serie, met rangschikking) · `book` (serie, uitgave, soort,
nummer, titel, paginacount, bestand óf bron-ref) · `progress` · `tab` · `collection` · `source` ·
`subscription` (policy `permanent`/`readahead`, `readahead_n`, `ttl_days`) · `download_job` ·
`translation` · `tracker_account` · `setting`.

Boeken hebben een bestand **of** een bron-referentie — dat is wat lokale en geabonneerde items in
dezelfde tab laat verschijnen, en wat "tijdelijk downloaden om vooruit te lezen" mogelijk maakt
(bestand erbij, TTL-opruiming laat de bron-referentie intact).

`edition` kwam er later bij (zie punt 15): een serie kan meerdere uitgaven hebben en elke aflevering
wordt gevuld door de best gerangschikte uitgave die hem heeft. Voortgang hangt aan de aflevering, niet
aan de uitgave. `series.sidecar_path` legt vast waar het betaalde werk van een serie op schijf staat,
zodat een verhuizing het niet verweesd achterlaat (punt 12).

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

## M0 tot en met M3 en M5 tot en met M8 — gebouwd

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
6. **M2** — `/api/progress` bestond al vanaf M1 (gedeeld door alle clients, zie ontwerp 4);
   daar bovenop **BookPal Lite** (`/lite`, Laag A uit ontwerp 3: server-rendered HTML, geen
   JavaScript, een pagina omslaan is een gewone link die tegelijk de voortgang bijwerkt) en
   **OPDS 1.2** (`/opds`, navigatiefeed met series + acquisitiefeed per serie). De Kobo-
   beeldprofielen (`images/profiles.py`) waren al vanaf M1 aanwezig. Lite heeft daarna een
   schakelaar gekregen om gelezen hoofdstukken en uitgelezen series te verbergen; zonder JavaScript,
   dus die stand woont in de URL en blijft over links heen staan.

   **Laag B** (`bookpal/kobosync/`) is er ook: boeken wegzetten, series als planken in
   `KoboReader.sqlite`, en voortgang alleen-vooruit teruglezen. Wat die laag precies doet en hoe
   voorzichtig hij dat doet staat bij ontwerp 3 — inclusief de belangrijkste kanttekening: getest
   tegen een zelfgebouwde reconstructie van het apparaat, niet tegen een echte Kobo. Daarom telt M2
   hier als gebouwd, maar laag B nog niet als bewezen.

   Onderweg kwam er een fout boven die niets met de Kobo te maken had: de scanner bewaarde
   sorteertitels met hoofdletters en het volgen van een bron zonder. SQLite sorteert op tekencode,
   dus "Claire" kwam vóór "crayon" en viel elke bibliotheeklijst in tweeën — in de web-app, in Lite
   én in OPDS. Eén schrijfwijze nu, met een backfill.
7. **M3** — `bookpal/tabs/rules.py` compileert een regelboom naar een SQLAlchemy-expressie
   op `Series`: `and`/`or`/`not` plus condities op `extension`, `kind`, `origin_region`, `root`,
   `publisher`, `tag`, `series`, `source` en `reading_status`. Tags gaan via het gedocumenteerde
   `json_each`-idioom voor SQLite; `reading_status` via een dubbele `NOT EXISTS` (de ORM kent geen
   `relationship.all()`). `/api/tabs` en `/api/collections` delen die ene engine. De web-app heeft
   een tabbalk plus beheerschermen voor tabs (`/tabs`) en collecties (`/collecties`), met een
   gedeelde `RuleEditor`: een voorwaarden-bouwer voor het gangbare geval (platte "en") en een
   JSON-modus voor geneste `and`/`or`/`not`. Groeperen (`group_by`) gebeurt voorlopig client-side
   in `CollectionViewPage`; server-side groepering komt terug zodra "submappen als collectie"
   op grote mappen gaat knellen.

8. **M5, deels** — `bookpal/sources/` met de `Source`-interface (`search`, `detail`, `chapters`,
   `page_urls`, `download`), een token-bucket rate limiter en `mangadex.py`. Abonneren maakt boeken
   mét bron-referentie en zónder bestand; downloaden hangt er een cbz aan zonder die referentie te
   wissen, zodat de TTL-opruiming het bestand later kan weghalen terwijl het hoofdstuk zichtbaar
   blijft. Gedownloade bestanden landen in een gewone library-root, dus ze lopen daarna door
   dezelfde scanner, formats en beeldprofielen als eigen bestanden. `originalLanguage` voedt stap 2
   van de herkomst-keten en `links.mal` vult `tracker_ids` alvast voor M7.

   `worker.py` draait de drie taken op een interval in een achtergrond-thread (bewust een thread:
   ophalen is synchroon en hoort niet in de event loop). De beslissing zit in `plan_readahead`, een
   pure functie: begin bij het eerste nog niet uitgelezen deel en pak daarvandaan `readahead_n`
   hoofdstukken zonder bestand. Alles vóór die grens blijft met rust — dat is gelezen of bewust
   overgeslagen, en opnieuw ophalen zou juist de bandbreedte kosten die voor het vooruitlezen
   bedoeld is. Eén hikkende bron stopt de ronde niet; de fout komt in het rapport terecht.

   De web-app heeft `/bronnen` om te zoeken, te volgen en een ronde met de hand te draaien.
   `BookOut.from_source` en `expires_at` maken de drie toestanden zichtbaar die anders niet uit
   elkaar te houden zijn: eigen bestand, opgehaald, en nog online.

   Een bron hoort een gepubliceerde API te hebben waarvan het gebruik is toegestaan; scrapers voor
   sites die commercieel werk zonder licentie herdistribueren horen hier niet thuis. De interface
   staat los van de implementatie, dus een nette bron toevoegen is één bestand.

9. **M6** — vendored **foliate-js** (`web/src/vendor/foliate/`, gepinde commit, niet het npm-pakket
   van een derde — herkomst staat in `HERKOMST.md` ernaast) achter een eigen `EpubReader`. Downloads
   lopen via `downloadWithProgress.ts` met een voortgangsbalk, want een epub van een paar honderd MB
   zag er zonder die balk uit als een hang. `sort_volume` op `Book` bepaalt de leesvolgorde nu apart
   van de weergavetitel, wat nodig bleek zodra series een `Deel 10` naast een `Deel 2` hadden staan.

10. **M7** — `bookpal/trackers/` is eenrichtingsverkeer: BookPal leest nooit iets terug van
    MyAnimeList of Goodreads, dus is er geen conflict om op te lossen. `Tracker` is een kleine ABC
    (`push()` + `close()`); `MyAnimeListTracker` praat PKCE-OAuth2 (MAL ondersteunt alleen de
    `plain`-challenge, geen S256) en een rate-limiter die dezelfde `RateLimiter`-klasse hergebruikt
    als de MangaDex-bron (verplaatst naar `bookpal/ratelimit.py`). Goodreads heeft geen
    `Tracker`-implementatie — de publieke API is dood sinds eind 2020, en geraden veldnamen die
    "waarschijnlijk werken" zijn erger dan geen automatisering, want ze falen onopgemerkt. In plaats
    daarvan exporteert `export_csv()` de hele bibliotheek naar het CSV-formaat van My Books → Import
    and Export.

    Pushen gebeurt gedebounced per serie: `trackers/scheduler.py` reset per `series_id` een
    `threading.Timer` bij elke voortgangsupdate, en pas als een serie een paar seconden stil is
    gebleven gaat de push voor precies díe serie uit — nooit de rest van de bibliotheek, ook niet als
    er meerdere accounts gekoppeld zijn. Een nieuw account staat standaard op dry-run
    (`TrackerAccount.dry_run`), dus deze trigger is uit zichzelf onschadelijk totdat je 'm bewust
    aanzet. De web-app heeft `/trackers` om een MAL-app te koppelen (client-id/secret zelf
    registreren op `myanimelist.net/apiconfig`, autorisatie-URL openen, code terugplakken),
    dry-run/actief te schakelen, met de hand te pushen, en de Goodreads-CSV te downloaden.

11. **M8** — `bookpal/translate/` doet detectie, uitlezen én vertalen in **één** multimodale
    Gemini-aanroep per pagina, in plaats van de keten YOLOv8 → crop → manga-ocr/PaddleOCR → Gemini
    die hierboven beschreven staat. Die afwijking is bewust en om drie redenen:

    * Het model ziet de **hele pagina**, niet losse uitgeknipte strings. Dat is precies wat deze
      architectuur wilde bereiken met "vertaling mét paginacontext" — een keten die strings
      doorgeeft, gooit die context juist weg.
    * Geen ~700 MB aan modelgewichten (torch, manga-ocr, YOLO) in een image die op een N100 draait.
    * Nagemeten op een echte pagina uit de eigen bibliotheek: gemini-3-flash-preview vond alle acht
      tekstvlakken met vakken die sluitend om de tekst zaten, waar 2.5-flash er zeven vond en de
      laatste regel van elke ballon afkapte.

    De prijs is een netwerkverzoek per pagina en een API-sleutel. `BubbleTranslator` is daarom een
    aparte ABC: een lokale YOLO+OCR-pipeline kan er later naast zonder dat de rest iets merkt.

    **De drie vertaalstanden.** Hier wijzen `translate/modes.py` en
    `translate/imagepage.py` naartoe. De keuze is een echte
    afweging en geen voorkeur: de goedkope stand is voorspelbaar correct maar zichtbaar geplakt, de
    dure standen lezen mooier maar kunnen er stilzwijgend naast zitten.

    | Stand | Wat er terugkomt | Prijs/pagina | Gemeten |
    |---|---|---|---|
    | `TEXT` | Tekst + coördinaten; wij tekenen zelf met Comic Neue | ~$0,002 | Raakt de tekening nooit aan; op een ballon tikken geeft het origineel |
    | `IMAGE_FAST` | De hele pagina hertekend mét vertaling | ~$0,067 | Liet op **3 van de 4** proefpagina's iets liggen: een onvertaalde ballon, een verzonnen regel, en één keer een gewijzigd bedrag op een menukaart |
    | `IMAGE_PRO` | Hetzelfde, met het zware model | ~$0,134 | In **alle vier** de proeven bruikbaar |

    Dat gewijzigde bedrag is de gevaarlijkste fout van de drie, want die ziet er correct uit. Vandaar
    dat de prompt getallen, bedragen en eigennamen expliciet als onaantastbaar benoemt, en vandaar
    dat het origineel altijd één tik verderop blijft staan — bij de beeldstanden is dat de enige
    controle die de lezer heeft.

    Tegen de andere stilzwijgende fouten van een generatief model:

    * **Afmeting terugzetten.** Het model levert zijn eigen canonieke resolutie (848×1256 voor een
      pagina van 810×1200). Gemeten over twee pagina's is de compositie na terugschalen 0 tot 1 pixel
      verschoven — dus terugschalen is genoeg, maar het moet wel gebeuren, anders klopt geen enkele
      coördinaat meer.
    * **Grijswaarden bewaken.** Een zwart-witte manga hoort zwart-wit terug te komen; het model geeft
      altijd RGB terug.

    De stand wordt op modelnaam-niveau bewaard (`gemini`, `gemini-image-fast`, `gemini-image-pro`) en
    niet als "gemini": een pagina die met het goedkope beeldmodel is gedaan mag niet doorgaan voor
    een pagina die met het dure is gedaan, en andersom moet je beide van dezelfde pagina kunnen
    hebben zonder dat ze elkaar overschrijven. Ligt er meer dan één, dan wint de duurste — daar is
    al voor betaald.

    Een vierde, hybride stand is geprobeerd en weer verwijderd: het beeldmodel de ballonnen laten
    leegvegen zodat onze eigen tekst er netjes in past. Zowel het snelle als het zware model gaven de
    pagina ongewijzigd terug, mét de tekst er nog in, waardoor onze vertaling er dubbel overheen
    kwam. Erasure is kennelijk iets anders dan hertekenen.

    **Drie schakelaars, en waar geld kan lopen.** Er zijn drie standen instelbaar, want het zijn
    drie verschillende afwegingen (`translate/preferences.py`):

    | Schakelaar | Standaard | Waarom |
    |---|---|---|
    | Vanzelf (de wachtrij) | `TEXT` | Loopt zonder dat je iets doet, dus hoort goedkoop te zijn |
    | De knop in de lezer | `IMAGE_FAST` | Druk je zelf op een pagina, dan is die het waard |
    | Inkleuren | `IMAGE_FAST` | Zie de inkleurmeting hieronder |

    **Let op wat "vanzelf" betekent.** Elke klus in de wachtrij draagt zijn eigen stand mee — die
    wordt meegegeven bij het inleggen en niet ter plekke opgehaald, zodat werk dat al klaarstaat
    blijft zoals het bedoeld was toen je erom vroeg. Staat die schakelaar op een beeldstand, dan kost
    **elke paginawissel drie pagina's vooruit in die stand**. Dat is de enige plek in de app waar
    geld kan lopen zonder dat er iemand op een knop drukt; daarom staat hij standaard op tekst en
    noemt de instelling de prijs per pagina erbij.

    Resultaten komen in de bestaande `translation`-tabel (`payload` bevat de vlakken), dus M8 had
    geen migratie nodig — het datamodel uit M0 had hier al ruimte voor gelaten. Vakken worden
    genormaliseerd op 0..1 bewaard en niet in pixels: dezelfde vertaling moet over elk beeldprofiel
    passen, en web, Kobo en miniatuur hebben alle drie een andere afmeting.

    `queue.py` is geen FIFO maar een gesorteerde wachtrij: een voortgangsupdate zet de pagina's vlak
    vóór je uit vooraan, zodat de NAS vooruitloopt op wat je leest. Eén thread, want op een N100
    telt het uitserveren van beeld zwaarder dan snel vertalen.

    Er zijn **drie** manieren om de vertaling te tonen, en welke de beste is hangt af van de client:

    | Vorm | Endpoint | Voor wie |
    |---|---|---|
    | JSON-vlakken | `/pages/{n}/translation` | Web-lezer: tekent een HTML-overlay, blijft scherp bij zoomen en je kunt op een ballon tikken voor het origineel |
    | Doorzichtige PNG | `/pages/{n}/overlay` | BookPal Lite, Kobo, straks iOS: een laag over de pagina, met CSS te stapelen zonder JavaScript |
    | Ingebakken pagina | `/pages/{n}?translate=nl` | Clients die maar één plat plaatje aankunnen, zoals de eigen Kobo-app van M9 |

    De losse laag is voor de meeste clients de betere: de pagina zelf blijft **één gedeelde
    afbeelding**, dus aan- en uitzetten hoeft die pagina niet opnieuw op te halen. Op een echte
    pagina uit de bibliotheek gemeten: de laag is 43 kB tegen 249 kB voor de pagina (17 %), en hij
    komt in 6 ms uit de cache waar inbakken 328 ms kost — élke aanvraag opnieuw, want een ingebakken
    pagina is niet te cachen zonder van elke pagina twee volledige varianten te bewaren. De
    cachesleutel van de laag bevat de opgeslagen vertaling zelf, dus opnieuw vertalen levert vanzelf
    een nieuwe laag op in plaats van de oude te blijven tonen.

    Alle drie de vormen delen hetzelfde tekenwerk (`_draw_onto`), zodat de Kobo en de web-app niet
    uit elkaar kunnen gaan lopen. Het inbakken behoudt bovendien de geditherde grijswaarden — die
    naar RGB tillen zou precies het werk weggooien waar het Kobo-profiel voor bestaat.

    **Lettering.** Gemini kan geen font namaken — het levert tekst, coördinaten en of het origineel
    vet/cursief stond, geen glyphs. Beide kanten tekenen die tekst daarom met **Comic Neue** (SIL OFL
    1.1, een vrij te herdistribueren remake van Comic Sans) in plaats van een systeemfont: de server
    heeft het Debian-pakket `fonts-comic-neue`, de web-app dezelfde vier stijlen zelf gehost als
    webfont (`web/src/vendor/comic-neue/`), zodat overlay en ingebakken versie er hetzelfde uitzien.
    `Bubble.upper` zet de vertaling zelf in kapitalen als de brontekst dat ook was — striplettering
    staat traditioneel vol in kapitalen, en een vertaling in onderkast daartussen valt op als
    "ingeplakt". Dat vragen we niet aan het model; het staat al in de brontekst.

    De prompt vraagt Gemini nu ook om `bold`/`italic` per vlak, met een expliciete waarschuwing dat
    "italic" een écht schuine nadruk betekent en niet gewoon een golvend handlettering-lettertype —
    zonder die waarschuwing markeerde het model bijna elke ballon als cursief. Zelfs met de
    waarschuwing blijft dit een oordeel, geen meting: hetzelfde verzoek op dezelfde pagina gaf bij
    herhaling een wisselende uitkomst. Bold bleef in alle metingen wel stabiel. Het effect van een
    foutieve `italic` is bovendien mild — Comic Neue Italic blijft goed leesbaar — dus dit is
    geaccepteerd als grens van wat een taalmodel betrouwbaar kan beoordelen aan een tekening, in
    plaats van dat er tot in het oneindige aan de prompt gesleuteld is.

    **Onderzocht en bewust niet gebouwd: Gemini de ballon zelf laten "schoonvegen" met
    beeldgeneratie** (`gemini-2.5-flash-image`), zodat onze eigen tekst op een gepaste achtergrond
    komt te staan in plaats van op een simpel wit vlak. Op een hele pagina werkt dit niet: het model
    regenereert de compositie in zijn eigen canonieke resolutie, niet pixel-voor-pixel identiek —
    getest op een echte pagina, en na terugschalen naar de oorspronkelijke afmeting stonden panelen
    en ballonvormen meetbaar verschoven ten opzichte van de al bepaalde tekstvakken. Op een los
    uitgeknipt ballonnetje werkt het schoonvegen zelf wél overtuigend, maar dat zou een aparte
    beeldgeneratie-aanroep per tekstvlak vergen — bij acht vlakken op een pagina een veelvoud van de
    tijd en kosten van de huidige aanpak. Zou dit ooit terugkomen, dan als aparte, expliciet
    duurdere stand naast de huidige — nooit als vervanging, want de huidige aanpak is voor de meeste
    pagina's al goed genoeg.

    Van de conclusie hierboven is één deel later achterhaald: dat het model de compositie op een hele
    pagina te veel verschuift. Dat bleek niet aan de hele pagina te liggen maar aan de opdracht — zie
    het anker in punt 13. Het schoonvegen zelf staat nog steeds uit.

12. **Betaald werk op schijf: sidecars naast de serie.** Een vertaling kost geld, bij de beeldstanden
    tientallen centen per pagina. Die mag daarom niet alleen in de database staan: een database
    opnieuw opbouwen of een scan die misgaat zou betekenen dat je opnieuw betaalt voor werk dat al
    gedaan is. **De schijf is de waarheid, de database is de index** — bij het vertalen wordt eerst
    op schijf gekeken, dus een bestaand bestand bespaart een aanroep.

    Ze stonden eerst in een apart Docker-volume: op de NAS te vinden, maar onder `/volume1/@docker`,
    en dat verbergt elke bestandsbeheerder. Precies de plek waar je niet kijkt. Nu staan ze naast de
    serie, zoals ondertitels naast een videobestand:

    ```
    Oishinbo/.sidecars/Oishinbo - v03 - 012.cbz.json    wat we van dat bestand weten
    Oishinbo/.sidecars/v03c012/p0007-nl.json            de tekstvlakken
    Oishinbo/.sidecars/v03c012/p0007-nl-image_pro.webp  hele pagina, duur model
    Oishinbo/.sidecars/v03c012/p0007-kleur.webp         ingekleurd
    ```

    Eén verborgen laag per serie, met alles van ons erin. De hoofdstukmappen daarbinnen hebben geen
    punt: ben je er eenmaal, dan wil je zien wat er is. De mapnaam is `v03c012` met nullen ervoor,
    zodat een `ls` op leesvolgorde staat. De scanner slaat alles met een punt al over, dus hij kan
    zichzelf nooit als collectie terugvinden.

    Ook een serie die je alleen online volgt krijgt zijn map: dan staat de vertaling klaar op de plek
    waar de bestanden komen zodra je ze importeert. De downloadmap telt daarbij niet mee als thuis —
    die is cache en wordt opgeruimd, en betaald werk hoort niet in de vuilnisbak te staan. Waar een
    serie terechtkomt wordt vastgelegd op de serie zelf (`Series.sidecar_path`), zodat een
    verhuizing later het werk niet verweesd achterlaat.

    De verhuizing draaide bij het opstarten en bracht twee dingen boven. Hernoemen kan niet over een
    apparaatgrens (volume naar aangekoppelde map), dus het gaat via kopiëren en weggooien — en
    mislukt er iets, dan wordt de klus niet afgevinkt en probeert een volgende start het opnieuw. En
    48 bestanden hoorden bij mappen die naar oude titels heetten ("39 Yarō Abe", inmiddels "Hoofdstuk
    39") of naar een uitgave ("One Piece (Official Colored)"); die waren ook in de oude indeling al
    onvindbaar, want er werd altijd op de huidige titel gezocht. Teruggevonden via het nummer vooraan
    de mapnaam. Live: 101 van de 101 bestanden staan nu naast hun serie.

13. **Inkleuren** (`translate/recolour.py` + `_COLOUR_PROMPT` in `imagepage.py`). Een zwart-witte
    pagina door het beeldmodel laten schilderen, als eigen variant naast de vertalingen — nooit
    erboven, want een ingekleurde pagina mag nooit in de plaats komen van een vertaalde. Vandaar een
    eigen sleutel (`gemini-color`) en geen `TranslateMode`.

    **Alleen de kleur van het model, het lijnwerk houden we zelf vast.** Een model dat een pagina
    inkleurt, tekent hem in feite opnieuw, en de inkt komt er zachter uit dan hij erin ging: op
    Oishinbo deel 1 pagina 1 zakte het aandeel zwart van 12,9% naar 6,9%. Bij een strip is dat
    precies het verkeerde verlies — het lijnwerk ís de tekening. Dus nemen we van het ingekleurde
    beeld alleen tint en verzadiging over en komt de helderheid van onze eigen pagina; niet als
    vervanging maar als *ondergrens*, zodat een wassing die donkerder is dan het papier blijft staan
    en de aquareltextuur behouden blijft. Gemeten: zwart weer op 13,6% bij 15,4% kleur.

    **De opdracht begint bij wat er níét mag veranderen.** Door de omtrekken, paneelranden en
    ballonnen als anker te benoemen — met de uitleg erbij dat iemand de pagina straks precies over
    het origineel legt — blijft de compositie staan. Gemeten als overlap met het origineel, zonder
    correctie achteraf: pagina 1 ging van 0,840 naar 0,886 en 0,881 in twee runs, pagina 16 van 0,861
    naar 0,868. En meteen meer kleur (33,4% tegen 28,1%), want minder onzekerheid over de tekening
    laat meer ruimte voor verf.

    **Een losse kleurlaag opvragen werkt niet.** Het model schildert die laag opnieuw uit het hoofd
    in plaats van hem uit te lijnen — mooie aquarel, maar de mensen stonden ergens anders dan in het
    paneel. De omweg via de hele ingekleurde pagina is wél uitgelijnd, want daar kopieert het model
    zijn eigen invoer.

    **Kleur is niet taalgebonden.** Er wordt één keer per pagina ingekleurd, altijd van het
    origineel, en de combinatie met een vertaling wordt bij het eerste opvragen berekend en bewaard.
    Rekenwerk, geen aanroep — een tweede taal kost dus niets meer, waar dat eerst $0,067 per pagina
    was. Wel per geval de juiste regel, en dat is geen detail:

    * **over het origineel** de donkerste van de twee (`recompose`), zodat de aquarelwassing zijn
      textuur houdt — beide lagen hebben daar dezelfde tekst;
    * **over een vertaalde pagina** alleen de kleur (`tint_only`), want de ingekleurde pagina heeft
      nog de oorspronkelijke letters en die drukken er anders dwars doorheen. Gemeten aan het aandeel
      zwart: 16,1% tegen 8,8% in het origineel; met alleen de kleur 8,3%, en de pagina leest weer.

    **Zelfherstellend.** Wat het model letterlijk teruggaf gaat als `kleur-ruw` naar de sidecar,
    vóór onze bewerking — dat is het enige stuk waar geld in zit, de rest is rekenwerk. Ontbreekt de
    bewerkte versie, dan wordt hij uit de ruwe plaat opnieuw gemaakt; is die er niet maar ligt er nog
    een taalversie van een vorige opzet, dan zit de kleur daar ook nog in en wordt hij daaruit
    gehaald (met `tint_only`, want die heeft de verkeerde letters). Beide zonder aanroep. Dit kwam er
    pas later in: de eerste opzet bewaarde alleen de bewerking, en toen kostte elke wijziging in de
    samenstelling — op één dag drie keer — opnieuw geld om te zien wat hij deed.

    **Al gekleurde pagina's.** Bij een pagina die de tekenaar zelf al kleurde is inkleuren geen
    inkleuren maar overschilderen: op een pagina uit Dirkjan werd het paarse jasje zwart en de
    knalgroene achtergrond een zachte wassing, voor hetzelfde geld als een echte inkleuring. De
    server antwoordt daar met 412 (`AlreadyColour`) en de lezer maakt er een vraag van; bevestigen
    doet het alsnog. Geen verbod dus. De grens meet alleen óf er kleur is — verzadiging boven 5% van
    de pagina — want tweekleurendruk van volle kleur onderscheiden bleek niet betrouwbaar te meten
    (beide gaven drie tinten, een kleuromslag zelfs één). Zwart-witte binnenpagina's meten 0,0%, en
    vergeeld papier valt er niet in omdat de maat naar verzadiging kijkt en niet naar het verschil
    tussen de kanalen.

    **Het snelle model volstaat, anders dan bij vertalen.** Dat argument kwam uit de vertaalproef,
    maar bij inkleuren komt geen letter kijken — en sinds het lijnwerk van ons is, kan het model de
    tekst sowieso niet raken. Gemeten op twee pagina's, beide modellen achter elkaar:

    | Pagina | Model | Uitlijning | Kleur | Tijd |
    |---|---|---|---|---|
    | p1 | snel | 0,879 | 25,8% | 12s |
    | p1 | zwaar | 0,906 | 19,1% | 21s |
    | p16 | snel | 0,862 | 19,1% | 13s |
    | p16 | zwaar | 0,875 | 26,0% | 23s |

    Het zware model lijnt een fractie beter uit, maar dat zie je nauwelijks nu het lijnwerk toch van
    ons komt; de hoeveelheid kleur wisselt per pagina welke kant op. Voor de helft van de prijs en de
    helft van de wachttijd — vandaar het snelle model als standaard.

    **In de lezer.** Een merkje naast dat voor vertaling zegt of er kleur ligt en zet het met één tik
    aan of uit; een pagina die de tekenaar zelf al kleurde krijgt een eigen tekst en geen knop, want
    "daar valt niets in te kleuren" is iets anders dan "nog niet gedaan". Wat er eenmaal ligt wordt
    nooit vanzelf vervangen — anders kost elke pagina die je terugbladert opnieuw geld — dus staat er
    onder de instellingen een regel "Opnieuw" met twee knoppen, vertalen en inkleuren. Daarbij hoort
    een oplopend versienummer per pagina als cachebreker: de afbeelding staat op hetzelfde adres, dus
    zonder dat bleef de vorige versie in beeld en leek er niets te gebeuren. Live geverifieerd op
    Oishinbo p23: één inkleuring van 14 seconden, daarna kleur mét scherpe Nederlandse tekst zonder
    tweede aanroep.

14. **Een heel hoofdstuk in één keer** (`translate/batch.py`). Drie knoppen bij het begin van een
    hoofdstuk — tekst, ingetekend, inkleuren — via de batch-API van Gemini, die de helft van het
    gewone tarief rekent. Je betaalt ervoor met wachttijd: gemeten duurde een batch van twee pagina's
    129 seconden (tekst), 174 (kleur) en 113 (ingetekend), tegen 8 tot 21 seconden voor één pagina
    los. Dat is ongeacht of het er twee of tweehonderd zijn — je wacht op de wachtrij van Google, niet
    op het rekenen zelf. Precies verkeerd voor de pagina waar je op zit te wachten, precies goed voor
    een hoofdstuk dat je klaarzet. Vandaar apart van `queue.py`, die je tijdens het lezen bijhoudt.

    De tokens zijn identiek aan los werk; dat is gemeten, in en uit. De halve prijs is het tarief van
    Google en niet iets wat wij uit de API kunnen aflezen, dus staat die factor apart in het antwoord
    en kan de lezer tonen dát dit het batchtarief is.

    **Nooit starten zonder bedrag.** Eerst een plan opvragen (hoeveel pagina's staan er nog open, wat
    kost dat), dan pas de vraag "starten?" met het totaal erbij. Wat er al ligt valt uit het plan, dus
    je betaalt nooit twee keer. Dit is de enige knop in de app die met één druk een heel hoofdstuk
    afrekent.

    Bewust één klus tegelijk. De naam van de lopende opdracht gaat naar de instellingen-tabel en
    wordt bij het opstarten weer opgepakt: draait de container opnieuw op terwijl er een batch loopt,
    dan is die bij Google gewoon nog bezig, en zonder die naam zou niemand het antwoord ophalen en
    was het geld weg. Eén pagina die met een filter terugkomt gooit de rest niet weg. De
    verzoekopbouw is uit beide vertalers gelicht naar losse functies (`build_text_request`,
    `build_image_request`, `build_colour_request`), zodat los werk en batchwerk gegarandeerd dezelfde
    opdracht sturen. Live geverifieerd op Oishinbo deel 1: 7 pagina's tekst in ~150s, resultaten
    leesbaar via de gewone endpoint, en het plan daarna op nul.

15. **Uitgaven binnen een serie, en samenvoegen.** Van dezelfde reeks bestaan vaak meerdere versies
    naast elkaar: de gekleurde uitgave die achterloopt, het zwart-witte origineel dat compleet is, je
    eigen bestanden, en van een boek soms drie drukken. Dat waren tot nu toe aparte series — of, na
    een samenvoeging, één serie waarin het tweede abonnement werd weggegooid.

    Nu heeft een serie geordende uitgaven. Elke aflevering is een vakje dat elke uitgave kan vullen,
    en je krijgt per vakje de best gerangschikte uitgave die hem heeft. Dragon Ball Super leest
    daarmee 1 t/m 9 in kleur en vanaf 10 vanzelf zwart-wit, zonder iets om te zetten. **Voortgang
    hangt aan de aflevering en niet aan de uitgave**, zodat het omzetten van je voorkeur geen halve
    serie weer ongelezen maakt. Boeken zonder deelnummer groeperen op titel en zijn met de hand aan
    elkaar te koppelen voor drukken die net anders heten.

    Een treffer bij een bron wordt herkend als iets wat je al in huis hebt: "Shinya Shokudou" bij de
    bron en "Shinya Shokudo" in jouw map zijn hetzelfde ding, alleen de romanisering verschilt. Het
    zoekresultaat zegt dat vooraf ("Wordt een uitgave van «…»") en de knop heet dan "Bron toevoegen"
    — anders druk je op volgen zonder te weten dat je een tweede serie maakt. Hernoem je een serie
    naar een naam die al bestaat, dan komt samenvoegen terug als *voorstel*: gelijknamig is niet
    altijd hetzelfde, en samenvoegen laat zich niet met één druk terugdraaien. Samenvoegen behoudt
    beide abonnementen — dat is juist het geval waarvoor je samenvoegt — en legt de bron-reeks per
    abonnement vast vóórdat de opgaande serie verdwijnt.

16. **Bestanden binnenhalen die niet uit een bron komen** (`api/intake.py`). Uploaden vanuit de
    browser (ook vanaf je telefoon) en een deellink plakken die de NAS zelf ophaalt; een gedeelde map
    komt binnen als zip en wordt uitgepakt. Omdat de server die link ophaalt vanáf de NAS — dus van
    binnen je eigen netwerk — wordt elke hop gecontroleerd, ook na een omleiding, en gaat alles wat
    naar een privé-adres wijst eruit. Wat binnenkomt wordt nooit buiten de doelmap geschreven, en een
    epub blijft heel (die is óók een zip). Ophalen gebeurt op de achtergrond met een balkje en het
    aantal binnengehaalde bytes: 882 MB kwam eerder binnen zonder één teken van leven, en dat is niet
    te onderscheiden van "er gebeurt niets". Eén download tegelijk.

## Buiten het plan gebouwd

M0 t/m M8 waren vooraf bedacht. Wat hieronder staat is er tijdens het gebruik bij gekomen — geen
mijlpaal, maar wel onderdeel van het werkende geheel. Ze staan hier apart zodat de mijlpalenlijst
blijft zeggen wat hij zei.

1. **Uitgave-export.** Een hoofdstuk dat volledig hertekend of ingekleurd is, wordt vanzelf een
   leesbare cbz naast de serie: `<naam>.nl.cbz`, `<naam>.col.cbz`, `<naam>.col.nl.cbz`. Tot dan was
   betaald werk alleen zichtbaar ín de lezer, en dat is zonde van tientallen centen per pagina. De
   editie komt achteraan in de voorkeur — hij verschijnt vanzelf, maar wordt nooit ongevraagd je
   eerste keus. Vereiste een eigen kolom (`Edition.export_key`), want zonder herkenning zou
   `for_local_files` zo'n editie voor "je eigen bestanden" aanzien: beide hebben geen abonnement en
   geen mappad. Getriggerd na elke voltooide pagina — los, via een batch, of via een sidecar die van
   een client binnenkomt.

2. **Sidecars uitwisselen tussen apparaten** (`/api/sidecars`). Zodra een telefoon onderweg zelf
   vertaalt, ontstaat er betaald werk op een tweede plek. Drie routes: inventaris, ophalen,
   terugzetten. Een botsing laat staan wat er al ligt — twee kanten met dezelfde pagina hebben
   allebei iets bruikbaars — en `stored` in het antwoord zegt de client of híj degene was die het
   neerzette. Dat is nodig zodra er een derde of vierde apparaat meedoet. De naam komt van buiten en
   wordt een pad, dus die loopt eerst langs een streng patroon.

3. **De iOS-app werkt zonder NAS.** Pagina's die je ooit opende komen van schijf terug
   (`Paginacache`), de startpagina en bibliotheek vallen terug op hun laatste geslaagde antwoord, met
   een balk erboven zodat je weet dat je naar een oude stand kijkt. Eén opslagbudget voor de hele
   bibliotheek; vol betekent dat het langst niet bekekene het eerst gaat, behalve series met "offline
   bewaren" en alles wat van een abonnement komt. Buiten je netwerk heb je vaak wél internet en geen
   NAS: dan roept de app zelf Gemini aan met een sleutel uit de sleutelhanger, en het resultaat gaat
   naar een lokale sidecarmap die bij de eerstvolgende verbinding synchroniseert.

4. **Grove indeling boeken/strips/manga** als serverfilter (`?group=`). "Strips" is *wel een strip,
   maar niet uit Japan*, en dat was met geen enkele losse parameter te zeggen. Naschiften in de
   client liet series wegvallen zodra de paginalimiet bereikt werd, en telde het totaal verkeerd.

5. **Panelherkenning zonder model** — recursieve XY-snede, gespiegeld in Python en Swift. Twee
   drempels moesten samen omlaag (`GOOT_VULLING` 0,012 → 0,05, `GOOT_MINIMUM` 0,012 → 0,008); los
   van elkaar hielp geen van beide. Wat het niet kan: een grote witte ballon die een paneelrand raakt
   maakt een valse goot. Drie oplossingen geprobeerd, gemeten en teruggedraaid.

6. **MangaKakalot als bron** — de eerste zonder API. De regel "geen scrapers" in `sources/base.py`
   was een startbeperking om M5 eenvoudig te houden, geen blijvend uitgangspunt. Deze bron leest de
   HTML van de site en faalt daarom hard en bij naam zodra de opmaak verandert; een lege lijst zou
   als "deze reeks heeft niets" gelezen worden. Zoeken kan niet (de zoekpagina vult zichzelf in de
   browser), dus `search` lost een geplakte URL op.

7. **Losse pagina's als hoofdstuk.** Een map met minstens drie plaatjes in de intake wordt bij het
   importeren tot één cbz geregen, op nummer gesorteerd en niet alfabetisch — een browser slaat op
   als `1.jpg` tot `10.jpg`. Voor wie zelf scant of pagina voor pagina opslaat.

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
- Vanaf M8: alles wat een model doet op een échte pagina meten, met getallen en een plaat om naar te
  kijken — een uitspraak over een model geldt hier pas als hij gemeten is. Zie de metingen bij punt
  11 en 13; eerdere aannames zijn al drie keer onderuitgegaan.
- Vanaf M9: `bookpal-kobo` cross-compilen, via NickelMenu starten, en de verversingsmodi visueel
  controleren (geen spookbeelden bij snel omslaan).

**Wat nog niet op echte data is nagelopen.** De batch-route is via scripts gemeten (punt 14), maar de
drie knoppen bij het begin van een hoofdstuk zijn nog niet zelf ingedrukt; hetzelfde geldt voor
inkleuren en ingetekend vertalen via de knoppen in de lezer. En laag B is nooit tegen een echte Kobo
aan geweest — zie ontwerp 3.

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
- **De Gemini-sleutel heeft in de containerlogs gestaan**, in platte tekst. Hij ging als
  query-parameter mee en `httpx` logt elk verzoek met volledige URL. Dat is gerepareerd — de sleutel
  zit nu in een `x-goog-api-key`-header — maar een sleutel die eenmaal in een logbestand heeft
  gestaan is gelekt, ook als die logs alleen op je eigen NAS staan. **Vervang hem, en controleer bij
  het toevoegen van een provider dat het geheim niet in een URL terechtkomt.**
- **Op één plek loopt er geld zonder dat iemand op een knop drukt**: de schakelaar "vanzelf". Staat
  die op een beeldstand, dan kost elke paginawissel drie pagina's vooruit. Standaard staat hij op
  tekst; zie punt 11.
- **Scope** — dit is een meermaandsproject. Elke milestone levert iets bruikbaars op, zodat er
  onderweg altijd iets werkt in plaats van pas aan het eind.
