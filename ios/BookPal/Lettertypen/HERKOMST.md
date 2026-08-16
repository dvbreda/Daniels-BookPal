# DigitalStrip — de striplettering voor de tekstballonnen

Familie: **DigitalStrip**. Drie sneden, met deze PostScript-namen (dát is wat je
in `Font.custom(...)` opgeeft, niet de bestandsnaam):

| Bestand | PostScript-naam |
|---|---|
| `digistrip.ttf` | `DigitalStrip` |
| `digistrip_b.ttf` | `DigitalStripBold` |
| `digistrip_i.ttf` | `DigitalStripItalic` |

Er is geen vet-cursieve snede. `Striplettering.naam` laat vet dan winnen: bold
bleef in alle metingen stabiel, terwijl italic een oordeel is dat het model bij
herhaling anders geeft.

Waarom deze en niet Comic Neue: Daniel vond deze mooier voor de ballonnen. Comic
Neue stond er eerst (SIL OFL 1.1, uit het Debian-pakket `fonts-comic-neue`) en
is uit deze app verwijderd; hij zit nog wel in `web/src/vendor/comic-neue/` en in
de server-container.

**Let op — de drie clients lopen nu uit de pas.** De web-app en de ingebakken
versie voor de Kobo tekenen nog met Comic Neue, deze app met DigitalStrip.
Dezelfde vertaalde pagina ziet er dus anders uit op je telefoon dan in de
browser, terwijl `docs/architectuur.md` juist vastlegt dat ze gelijk horen te
zijn ("zodat overlay en ingebakken versie er hetzelfde uitzien"). Dit hoort
rechtgetrokken te worden door DigitalStrip ook in `web/` en in de
server-container te zetten — dat laatste vraagt een nieuwe image en een uitrol.

**Herkomst niet vastgelegd.** In de bestanden zit geen licentie- of
copyright-veld (nameID 13/14 ontbreken), dus waar deze vandaan komt is hier niet
te achterhalen. Bij Comic Neue stond dat er wel bij, en dat was de reden dat we
'm konden verantwoorden. Vraag Daniel waar hij ze vandaan heeft en vul het hier
aan; voor een privérepo en eigen gebruik is er verder niets aan de hand.
