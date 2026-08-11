# foliate-js — meegeleverde kopie

Bron: <https://github.com/johnfactotum/foliate-js>
Commit: `78914aef4466eb960965702401634c2cb348e9b1` (2026-05-01)
Licentie: MIT, © 2022 John Factotum — zie `LICENSE`

`vendor/zip.js` komt uit diezelfde repo en is
[zip.js](https://github.com/gildas-lormeau/zip.js) (BSD-3-Clause);
`vendor/fflate.js` is [fflate](https://github.com/101arrowz/fflate) (MIT).

## Waarom meegeleverd en niet uit npm

Er staat een `foliate-js` op npm, maar die is gepubliceerd door een derde en
niet door de auteur. De metadata verwijst wel naar de officiële repo, en juist
dat zegt niets: die velden zijn vrij in te vullen. Daarom halen we de code
rechtstreeks bij de bron, op een vastgezette commit die hierboven staat.

De bibliotheek is hier ook op ingericht: het zijn losse ES-modules zonder
buildstap of runtime-afhankelijkheden.

## Wat er niet in zit

`pdf.js` is vervangen door een stub. Het origineel importeert een meegeleverde
pdf.js-distributie van ~13 MB, en BookPal heeft die niet nodig: pdf-pagina's
worden server-side gerenderd en gelezen met de eigen stripleer. De stub houdt
`view.js` bouwbaar zonder dat we die 13 MB meeslepen.

Verder is alles meegenomen wat `view.js` kan laden, ook formaten die BookPal
zelf niet aanbiedt (mobi, fb2). Dat is bewust: ze zijn samen klein, ze worden
alleen dynamisch geladen als je zo'n bestand opent, en zo blijft dit een
onbewerkte kopie in plaats van een fork die we moeten bijhouden.

## Bijwerken

1. Haal de nieuwe commit op bij de repo hierboven.
2. Kopieer dezelfde bestandenlijst; laat `pdf.js`, `reader.js`,
   `rollup.config.js` en `eslint.config.js` weg.
3. Zet de commit-hash hierboven bij.
4. Controleer of `view.js` niets nieuws dynamisch importeert dat hier ontbreekt
   — de buildstap valt er anders over.
