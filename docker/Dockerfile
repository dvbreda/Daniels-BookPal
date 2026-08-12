# --- web-app bouwen ---------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /build
COPY web/package.json web/package-lock.json* ./
RUN npm ci || npm install
COPY web/ ./
RUN npm run build

# --- server -----------------------------------------------------------------
FROM python:3.12-slim AS server

# libarchive leest cbr (ook RAR5) zonder de licentieproblemen van unrar.
# libarchive-tools levert bsdtar mee voor handmatig speurwerk in een shell.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libarchive13 \
        libarchive-tools \
        # M8: zonder een echte TrueType-font valt Pillow terug op een bitmapfont
        # van vaste grootte — dan staat elke ingebakken vertaling in hetzelfde
        # priegelformaat en verschijnt er een leeg blokje voor tekens als ¥.
        # DejaVu is het vangnet; Comic Neue (SIL OFL) is de eerste keuze omdat
        # striplettering er nu eenmaal niet uitziet als een systeemfont.
        fonts-dejavu-core \
        fonts-comic-neue \
    && rm -rf /var/lib/apt/lists/*

# M7: de Goodreads-koppeling stuurt een echte browser aan, omdat hun API dood
# is en hun inlog via Amazon loopt. Alleen het pip-pakket zit in de image
# (47 MB); Chromium zelf (~170 MB) wordt pas gehaald als je de koppeling
# daadwerkelijk aanzet, en belandt in /data zodat het een herbouw overleeft.
ENV PLAYWRIGHT_BROWSERS_PATH=/data/playwright \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    BOOKPAL_DATA_DIR=/data \
    BOOKPAL_CACHE_DIR=/data/cache \
    # Op het volume, niet in de container-laag: anders is elke gedownloade
    # aflevering weg zodra het image opnieuw gebouwd wordt.
    BOOKPAL_DOWNLOAD_DIR=/data/downloads

WORKDIR /app

COPY server/pyproject.toml ./server/
COPY server/bookpal/__init__.py ./server/bookpal/
RUN pip install --no-cache-dir -e ./server

# Chromium heeft systeembibliotheken nodig die niet in python:slim zitten;
# zonder deze start hij wel maar valt hij meteen om ("Target page, context or
# browser has been closed"). Dit is de prijs van de Goodreads-koppeling: zo'n
# 300 MB aan libraries. De browser zelf komt er pas bij als je hem aanzet.
RUN playwright install-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY server/ ./server/
COPY --from=web /build/dist ./web/dist

# Niet als root draaien; /data is het enige dat beschreven wordt. UID/GID
# instelbaar: bestanden op de NAS staan vaak op 600, alleen leesbaar door de
# eigen gebruiker, dus moet deze container met diezelfde UID draaien om de
# collectie ooit te kunnen lezen. Zie HOST_UID/HOST_GID in compose.yml.
ARG UID=1000
ARG GID=1000
RUN (getent group ${GID} || groupadd -g ${GID} bookpal) && \
    useradd --create-home --uid ${UID} --gid ${GID} bookpal && \
    mkdir -p /data/vertalingen && chown -R ${UID}:${GID} /data /app
USER bookpal

WORKDIR /app/server
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

# Migraties draaien vóór de server start, zodat een update van het image nooit
# op een verouderd schema landt.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn bookpal.main:app --host 0.0.0.0 --port 8000"]
