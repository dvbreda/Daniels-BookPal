import { describe, expect, it } from "vitest";

import { cellAt, cellOrder, cellTransform, indexOfCell } from "./grid";

describe("cellOrder", () => {
  it("loopt links naar rechts, rij voor rij", () => {
    expect(cellOrder(2, 2, false)).toEqual([
      { row: 0, col: 0 },
      { row: 0, col: 1 },
      { row: 1, col: 0 },
      { row: 1, col: 1 },
    ]);
  });

  it("begint rechtsboven bij manga", () => {
    // Dit is het hele punt: bij rechts-naar-links is cel 0 de rechterbovenhoek.
    expect(cellOrder(2, 2, true)[0]).toEqual({ row: 0, col: 1 });
    expect(cellOrder(2, 2, true)[1]).toEqual({ row: 0, col: 0 });
  });

  it("houdt rijen van boven naar beneden, ook bij manga", () => {
    const volgorde = cellOrder(2, 2, true);
    expect(volgorde.slice(2).map((c) => c.row)).toEqual([1, 1]);
  });

  it("werkt met een oneven raster", () => {
    expect(cellOrder(3, 2, false)).toHaveLength(6);
    expect(cellOrder(1, 3, true)).toEqual([
      { row: 0, col: 2 },
      { row: 0, col: 1 },
      { row: 0, col: 0 },
    ]);
  });
});

describe("cellTransform", () => {
  it("schaalt met de grootste richting", () => {
    // Anders past een cel horizontaal maar blijft hij verticaal half leeg,
    // en dan lees je alsnog niets.
    expect(cellTransform({ row: 0, col: 0 }, 2, 3).scale).toBe(3);
    expect(cellTransform({ row: 0, col: 0 }, 3, 2).scale).toBe(3);
  });

  it("zet de linkerbovencel naar rechtsonder toe", () => {
    const t = cellTransform({ row: 0, col: 0 }, 2, 2);
    expect(t.translateX).toBeCloseTo(25);
    expect(t.translateY).toBeCloseTo(25);
  });

  it("zet de rechteronderhoek de andere kant op", () => {
    const t = cellTransform({ row: 1, col: 1 }, 2, 2);
    expect(t.translateX).toBeCloseTo(-25);
    expect(t.translateY).toBeCloseTo(-25);
  });

  it("laat een raster van 1x1 de pagina ongemoeid", () => {
    expect(cellTransform({ row: 0, col: 0 }, 1, 1)).toEqual({
      scale: 1,
      translateX: 0,
      translateY: 0,
    });
  });
});

describe("cellAt", () => {
  it("vindt de cel onder een tik", () => {
    expect(cellAt(0.1, 0.1, 2, 2)).toEqual({ row: 0, col: 0 });
    expect(cellAt(0.9, 0.9, 2, 2)).toEqual({ row: 1, col: 1 });
  });

  it("blijft binnen het raster aan de randen", () => {
    // Een tik precies op de rand mag geen cel buiten het raster opleveren.
    expect(cellAt(1, 1, 2, 2)).toEqual({ row: 1, col: 1 });
    expect(cellAt(-0.2, -0.2, 2, 2)).toEqual({ row: 0, col: 0 });
  });
});

describe("indexOfCell", () => {
  it("geeft de plek in de leesvolgorde", () => {
    expect(indexOfCell({ row: 0, col: 1 }, 2, 2, true)).toBe(0);
    expect(indexOfCell({ row: 0, col: 1 }, 2, 2, false)).toBe(1);
  });
});
