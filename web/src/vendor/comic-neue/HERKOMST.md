# Comic Neue — meegeleverde webfonts

Bron: <https://github.com/crozynski/comicneue>
Licentie: SIL Open Font License 1.1 — zie `LICENSE`

Gehaald uit het Debian-pakket `fonts-comic-neue` (dezelfde bron die de server
gebruikt om vertalingen in te bakken voor de Kobo, zie
`server/bookpal/translate/overlay.py`), zodat web en Kobo dezelfde lettering
tonen in plaats van dat de een Comic Neue laat zien en de ander een
systeemfont.

Alleen de vier stijlen die de vertaaloverlay gebruikt: Regular, Bold, Italic,
BoldItalic. De Light-varianten van het pakket zijn niet meegenomen.

## Waarom een eigen stripfont in plaats van de systeemfont

Gemini kan geen font namaken — het levert alleen tekst, coördinaten en of het
origineel vet/cursief stond. Een systeemfont (de standaard sans-serif van de
browser) ziet er naast striplettering meteen "geplakt" uit; Comic Neue is
gemaakt om op Comic Sans te lijken zonder de reputatieschade, en is vrij
herdistribueerbaar.
