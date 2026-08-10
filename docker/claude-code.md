# Claude Code op de NAS

Waarom: een sessie die op de NAS zelf draait kan bij je echte bestanden, kan de
BookPal-container bouwen en herstarten, en kan dus dingen verifiëren die een
sessie in de cloud principieel niet kan.

Je DXP2800 voldoet ruim: x86\_64 en 8 GB, terwijl 4 GB het minimum is.

Je hebt een **Claude Pro-, Max-, Team- of Enterprise-abonnement** nodig. Het
gratis Claude.ai-plan geeft geen toegang tot Claude Code.

## Installeren

```bash
# 1. SSH naar de NAS (aanzetten in UGOS onder Terminal/SSH) en haal de repo op
mkdir -p /volume1/docker/bookpal && cd /volume1/docker/bookpal
git clone https://github.com/dvbreda/Daniels-BookPal.git
cd Daniels-BookPal

# 2. Paden invullen
cp .env.example .env
ls -d /volume1/_*          # kijk welke mappen je écht hebt
nano .env                  # zet BOOKPAL_BOEKEN/_STRIPS/_MANGA goed
echo "BOOKPAL_WORKSPACE=/volume1/docker/bookpal" >> .env
echo "HOST_UID=$(id -u)"  >> .env
echo "HOST_GID=$(id -g)"  >> .env

# 3. Container bouwen en starten
docker compose -f docker/claude-code.compose.yml up -d --build

# 4. Erin en inloggen
docker exec -it bookpal-claude claude
```

Bij de eerste start opent Claude Code een browser-login. In een container kan
de browser meestal niet terugkoppelen naar de container, dus krijg je in plaats
daarvan een **code te zien die je in de terminal plakt**. Dat is de bedoelde
route, geen storing.

Werkt dat niet, dan is er een tweede weg zonder browser op de NAS. Draai op je
laptop of telefoon (op een machine waar Claude Code al werkt):

```bash
claude setup-token
```

Kopieer de token die hij toont, zet hem in `.env` als `CLAUDE_CODE_OAUTH_TOKEN=…`
en herstart de container. De token is een jaar geldig.

> Zet die token niet in een chat, niet in een screenshot en niet in de repo —
> `.env` staat daarom in `.gitignore`.

## Controleren

```bash
docker exec -it bookpal-claude claude doctor      # installatie en instellingen
docker exec -it bookpal-claude claude --version
```

## Wat deze container mag

Bewust drie verschillende niveaus:

| Gemount | Rechten | Waarom |
|---|---|---|
| De repo | lezen + schrijven | daar wordt gewerkt |
| Je collectie | **alleen lezen** | echte bestanden onderzoeken zonder ze te kunnen beschadigen |
| `docker.sock` | volledig | om BookPal te bouwen en te herstarten |

Die laatste is de zwaarste: toegang tot de Docker-socket komt in de praktijk
neer op root op de NAS. Wil je dat niet, haal de regel dan uit
`claude-code.compose.yml` en bouw BookPal zelf vanuit je SSH-sessie. Alles
behalve het bouwen en herstarten van containers werkt dan gewoon door.

## Bijwerken

```bash
docker compose -f docker/claude-code.compose.yml build --no-cache
docker compose -f docker/claude-code.compose.yml up -d
```

De npm-installatie werkt niet vanzelf bij binnen de container, dus dit is de
manier om een nieuwe versie op te halen.
