/**
 * Waar een tekstballon komt te staan en hoe groot de letters worden.
 *
 * Losgetrokken van het tekenen omdat het precies het soort rekenwerk is dat er
 * op het scherm "bijna goed" uitziet: een ballon die net te klein is knipt zijn
 * tekst weg, en dan lijkt het alsof er niets vertaald is.
 */

/** Een vlak op de pagina, genormaliseerd op 0..1: [x0, y0, x1, y1]. */
export type Box = [number, number, number, number];

/**
 * Hoeveel het vlak buiten de gedetecteerde tekst groeit.
 *
 * Een ronde vorm die precies ín het tekstvlak past verliest juist de hoeken
 * waar de tekst staat. Door het vlak op te rekken en de tekstruimte gelijk te
 * houden ligt de tekst weer op het wit in plaats van op de tekening.
 */
const GROEI = 0.05;

/** Ruwe maat voor hoeveel tekens er in een vlak passen bij normale lettergrootte. */
const TEKENS_PER_VLAK = 1000;

export function expandBox([x0, y0, x1, y1]: Box, groei: number = GROEI): Box {
  const breedte = x1 - x0;
  const hoogte = y1 - y0;
  return [
    Math.max(0, x0 - breedte * groei),
    Math.max(0, y0 - hoogte * groei),
    Math.min(1, x1 + breedte * groei),
    Math.min(1, y1 + hoogte * groei),
  ];
}

/**
 * Hoeveel de letters moeten krimpen om de tekst te laten passen.
 *
 * 1 als het ruim past. De maat hiervoor keek alleen naar de breedte van het
 * vlak, waardoor een lange zin in een klein vlak overliep — en werd weggeknipt.
 * Krimpen gebeurt alleen als het nodig is; groter dan de basismaat wordt het
 * nooit, want dan zou een kort woord ineens beeldvullend worden.
 */
export function fontScale(box: Box, textLength: number): number {
  const [x0, y0, x1, y1] = box;
  const ruimte = (x1 - x0) * (y1 - y0) * TEKENS_PER_VLAK;
  if (ruimte <= 0) return 1;
  return Math.min(1, Math.sqrt(ruimte / Math.max(1, textLength)));
}
