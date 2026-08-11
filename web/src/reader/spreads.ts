/**
 * Bepaalt welke pagina's samen op één scherm komen.
 *
 * Dubbele pagina's zijn de lastigste kant van een stripleeservaring. Drie regels
 * maken het verschil tussen "leest als een album" en "alles staat verschoven":
 *
 * 1. De omslag staat altijd alleen — anders loopt de rest van het boek één
 *    pagina uit de pas, want in een gedrukt album staat pagina 1 rechts.
 * 2. Een liggende pagina is een uitklapper of dubbelpagina en vult het scherm
 *    alleen.
 * 3. Twee staande pagina's naast elkaar, maar nooit een staande naast een
 *    liggende.
 *
 * De verhoudingen komen binnen zodra een beeld geladen is; tot die tijd gaan we
 * uit van staand, wat voor vrijwel elke stripbladzijde klopt.
 */

export type Spread = number[];

export interface SpreadOptions {
  /** Verhouding breedte/hoogte per pagina-index, voor zover al bekend. */
  aspects: Record<number, number>;
  /** Omslag alleen tonen. Uit bij webtoons, waar geen omslagconventie geldt. */
  coverAlone?: boolean;
}

const LANDSCAPE_THRESHOLD = 1.0;

export function isLandscape(aspect: number | undefined): boolean {
  return aspect !== undefined && aspect > LANDSCAPE_THRESHOLD;
}

export function buildSpreads(
  pageCount: number,
  doublePage: boolean,
  options: SpreadOptions,
): Spread[] {
  if (pageCount <= 0) return [];
  if (!doublePage) {
    return Array.from({ length: pageCount }, (_, index) => [index]);
  }

  const { aspects, coverAlone = true } = options;
  const spreads: Spread[] = [];
  let index = 0;

  if (coverAlone) {
    spreads.push([0]);
    index = 1;
  }

  while (index < pageCount) {
    if (isLandscape(aspects[index])) {
      spreads.push([index]);
      index += 1;
      continue;
    }
    const next = index + 1;
    if (next < pageCount && !isLandscape(aspects[next])) {
      spreads.push([index, next]);
      index += 2;
      continue;
    }
    spreads.push([index]);
    index += 1;
  }

  return spreads;
}

/** In welke spread zit een pagina? Nodig om na een moduswissel op dezelfde
 * plek te blijven staan in plaats van naar het begin te springen. */
export function spreadIndexOfPage(spreads: Spread[], page: number): number {
  const found = spreads.findIndex((spread) => spread.includes(page));
  return found === -1 ? 0 : found;
}

/**
 * De leesvolgorde binnen een spread.
 *
 * Bij manga leest de rechterpagina eerst, dus die moet links in de DOM staan
 * gespiegeld worden. Dit is precies wat een generieke fotoviewer niet doet en
 * waarom manga daarin altijd verkeerd om aanvoelt.
 */
export function orderForDisplay(spread: Spread, rightToLeft: boolean): Spread {
  return rightToLeft ? [...spread].reverse() : spread;
}

/** Welke pagina's alvast in het geheugen laden. */
export function pagesToPreload(
  spreads: Spread[],
  currentSpread: number,
  aheadSpreads: number,
): number[] {
  const pages: number[] = [];
  for (let offset = 1; offset <= aheadSpreads; offset += 1) {
    const forward = spreads[currentSpread + offset];
    if (forward) pages.push(...forward);
  }
  // Eén spread terug, zodat terugbladeren ook direct is.
  const back = spreads[currentSpread - 1];
  if (back) pages.push(...back);
  return pages;
}

export function percentFor(spreads: Spread[], spreadIndex: number, pageCount: number): number {
  if (pageCount <= 0) return 0;
  const spread = spreads[spreadIndex];
  if (!spread || spread.length === 0) return 0;
  const lastPage = Math.max(...spread);
  return Math.min(100, Math.round(((lastPage + 1) / pageCount) * 100));
}
