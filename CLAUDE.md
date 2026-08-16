# Daniels BookPal — werkafspraken

Lees eerst `README.md` en `docs/architectuur.md`; die beschrijven wat het is en
hoe je het draait. Dit bestand gaat alleen over hoe we hier werken.

## Taal
- Codecommentaar, docstrings, commitberichten en UI-tekst: Nederlands.
- Namen van testfuncties: Engels en als zin (`test_the_place_is_remembered`),
  met een Nederlandse docstring als er iets uit te leggen valt.

## Commentaar en commits
Leg de *waarom* vast, niet de wat. Bij voorkeur met het bewijs erbij: "gemeten
over twee pagina's ging de uitlijning van 0,840 naar 0,886". Een commitbericht
noemt het probleem, de keuze en wat er gemeten is — geen opsomming van diffs.

## Meten in plaats van beweren
Bij alles wat een AI-model doet: eerst een proef op echte pagina's, met getallen
en een plaat om naar te kijken. Uitspraken als "het snelle model is te zwak"
zijn pas geldig als ze gemeten zijn; eerdere aannames zijn zo al drie keer
onderuitgegaan.

## Geld
Elke Gemini-aanroep kost geld (tekst ~$0,002, beeld $0,067–$0,134 per pagina).
Vraag het altijd eerst als een taak aanroepen nodig heeft, en zeg hoeveel
pagina's het worden. Wat betaald is hoort nooit verloren te gaan: de sidecars
naast de serie zijn de waarheid, de database is de index.

## Klaar is geverifieerd
Volledige suite (`ruff`, `mypy`, `pytest`, `npm run lint`, `npm test`,
`npm run build`) én — waar dat kan — controleren op echte data. Faalt er iets,
zeg dat met de uitvoer erbij in plaats van het te verzachten.

## Verifiëren en uitrollen op de NAS

De NAS is via ssh bereikbaar en draait de live versie op poort 1997. De
werkkopie daar (`/volume1/docker/bookpal`) is vanaf nu alleen een uitrolplek —
ontwikkelen gebeurt op de MacBook, dus daar niets bewerken.

```bash
# uitrollen: eerst halen wat je gepusht hebt, dan bouwen
ssh <nas> 'cd /volume1/docker/bookpal && git pull && docker compose -f compose.yml up -d --build'

# controleren op echte data
curl -s http://<nas>:1997/api/health
ssh <nas> 'docker exec bookpal python -c "..."'   # sidecars, tellingen, metingen
ssh <nas> 'docker logs bookpal --tail 50'