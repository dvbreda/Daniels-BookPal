/**
 * Rasterzoom: een pagina in cellen verdelen en die één voor één vullend tonen.
 *
 * Overgenomen uit leadingmangazoom (KOReader). Het probleem dat het oplost:
 * een mangapagina op een telefoon is leesbaar noch te overzien — je zit
 * constant in en uit te zoomen. Met een raster spring je per tik naar het
 * volgende paneelgebied, op ware grootte.
 *
 * De leesrichting telt hier écht: bij manga loopt een rij van rechts naar
 * links, dus cel 0 zit rechtsboven en niet linksboven. Vandaar dat de volgorde
 * een eigen functie is met eigen tests — dit is precies het soort ding dat er
 * op het scherm "bijna goed" uitziet.
 */

export interface GridCell {
  /** Positie in het raster, vanaf linksboven geteld. */
  row: number;
  col: number;
}

export interface GridTransform {
  scale: number;
  /** Percentage van de eigen breedte/hoogte dat de pagina opschuift. */
  translateX: number;
  translateY: number;
}

/**
 * De cellen in leesvolgorde: rijen van boven naar beneden, en binnen een rij
 * mee met de leesrichting.
 */
export function cellOrder(rows: number, cols: number, rightToLeft: boolean): GridCell[] {
  const cells: GridCell[] = [];
  for (let row = 0; row < rows; row += 1) {
    for (let step = 0; step < cols; step += 1) {
      cells.push({ row, col: rightToLeft ? cols - 1 - step : step });
    }
  }
  return cells;
}

/**
 * Hoe de pagina geschaald en verschoven moet worden om deze cel te vullen.
 *
 * De schaal is de grootste van beide richtingen: bij een raster van 2×3 wil je
 * niet dat een cel horizontaal past maar verticaal maar half gevuld is —
 * dan lees je alsnog niets. Liever iets buiten beeld dan te klein.
 */
export function cellTransform(cell: GridCell, rows: number, cols: number): GridTransform {
  const scale = Math.max(rows, cols);
  // Het middelpunt van de cel, als fractie van de pagina.
  const centerX = (cell.col + 0.5) / cols;
  const centerY = (cell.row + 0.5) / rows;
  // Verschuiven zodat dat middelpunt in het midden van het scherm komt.
  return {
    scale,
    translateX: (0.5 - centerX) * 100,
    translateY: (0.5 - centerY) * 100,
  };
}

/** Welke cel hoort bij een tik op deze plek? Fracties van 0..1. */
export function cellAt(x: number, y: number, rows: number, cols: number): GridCell {
  const clamp = (value: number, max: number) => Math.min(max - 1, Math.max(0, Math.floor(value)));
  return { row: clamp(y * rows, rows), col: clamp(x * cols, cols) };
}

/** De plek van een cel in de leesvolgorde, of -1 als hij er niet in zit. */
export function indexOfCell(
  cell: GridCell,
  rows: number,
  cols: number,
  rightToLeft: boolean,
): number {
  return cellOrder(rows, cols, rightToLeft).findIndex(
    (candidate) => candidate.row === cell.row && candidate.col === cell.col,
  );
}
