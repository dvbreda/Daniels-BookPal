# Claude Code op de NAS

Waarom: een sessie die op de NAS zelf draait kan bij je echte bestanden, kan de
BookPal-container bouwen en herstarten, en kan dus dingen verifiëren die een
sessie in de cloud principieel niet kan.

Je DXP2800 voldoet ruim: x86\_64 en 8 GB, terwijl 4 GB het minimum is.

Je hebt een **Claude Pro-, Max-, Team- of Enterprise-abonnement** nodig. Het
gratis Claude.ai-plan geeft geen toegang tot Claude Code.

## Eerst: de repo op de NAS krijgen zonder git

UGOS heeft geen `git`, en de repo is privé — een anonieme download werkt dus
ook niet. De oplossing is git te lenen uit een container in plaats van hem te
installeren; dan blijft de NAS schoon en overleeft het een firmware-update.

### 1. Maak een token

Je gewone GitHub-wachtwoord werkt niet; GitHub accepteert dat sinds 2021 niet
meer voor git. Geef je het toch op, dan volgt:

```
remote: Invalid username or token. Password authentication is not supported
```

Maak dus een **Personal Access Token**. Twee smaken, allebei goed:

**Fine-grained** (github.com → Settings → Developer settings → Personal access
tokens → Fine-grained tokens → Generate new token):

- Resource owner: `dvbreda`
- Repository access: **Only select repositories** → `Daniels-BookPal`
- Permissions → Repository permissions → **Contents: Read-only**

**Classic** (→ Tokens (classic) → Generate new token): vink alleen `repo` aan.

Kopieer de token meteen; GitHub toont hem daarna nooit meer.

### 2. Controleer de token vóór je kloont

Scheelt gokken. `read -rs` houdt hem uit je shell-geschiedenis:

```bash
read -rsp "GitHub token: " GH_TOKEN; echo; export GH_TOKEN
curl -s -o /dev/null -w "%{http_code}\n" \
  -H "Authorization: Bearer $GH_TOKEN" \
  https://api.github.com/repos/dvbreda/Daniels-BookPal
```

| Antwoord | Betekenis |
|---|---|
| `200` | goed, ga door |
| `401` | token ongeldig, verlopen of verkeerd geplakt |
| `404` | token geldig, maar heeft geen toegang tot déze repo |

### 3. Klonen

```bash
mkdir -p /volume1/docker/bookpal && cd /volume1/docker/bookpal

docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -e GH_TOKEN \
  -v /volume1/docker/bookpal:/w -w /w alpine/git \
  -c credential.helper='!f(){ echo username=x-access-token; echo password=$GH_TOKEN; };f' \
  clone -b claude/daniels-bookpal-app-wiud2v \
  https://github.com/dvbreda/Daniels-BookPal.git
```

Twee details die er bewust in zitten:

- `-e GH_TOKEN` zonder waarde geeft de variabele door uit je huidige shell. De
  token staat dus niet in het commando, en dus niet in je geschiedenis of in
  `ps`. De credential-helper voert hem binnen de container aan git.
- `--user "$(id -u):$(id -g)"` zorgt dat de bestanden van jou worden en niet
  van root — anders kun je ze straks niet bewerken.

Dit bootstrap-probleem bestaat maar één keer: de Claude-container hieronder
bevat zelf wél git, dus bijwerken gaat daarna met

```bash
docker exec -it bookpal-claude git pull
```

Liever git tóch op de NAS zelf? `sudo apt update && sudo apt install -y git`
werkt meestal op UGOS, maar kan bij een firmware-update verdwijnen.

## Installeren

```bash
cd /volume1/docker/bookpal/Daniels-BookPal

# Paden invullen
cp .env.example .env
ls -d /volume1/_*          # kijk welke mappen je écht hebt
nano .env                  # zet BOOKPAL_BOEKEN/_STRIPS/_MANGA goed
echo "BOOKPAL_WORKSPACE=/volume1/docker/bookpal" >> .env
echo "HOST_UID=$(id -u)"  >> .env
echo "HOST_GID=$(id -g)"  >> .env

# Container bouwen en starten
docker compose -f compose.claude.yml up -d --build

# Erin en inloggen
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
`compose.claude.yml` en bouw BookPal zelf vanuit je SSH-sessie. Alles
behalve het bouwen en herstarten van containers werkt dan gewoon door.

## Bijwerken

```bash
docker compose -f compose.claude.yml build --no-cache
docker compose -f compose.claude.yml up -d
```

Claude Code wordt in de image als root geïnstalleerd en draait als gebruiker
`node`, dus de ingebouwde auto-update kan niet bij zijn eigen installatiemap.
Opnieuw bouwen is daarom de manier om een nieuwe versie op te halen.
