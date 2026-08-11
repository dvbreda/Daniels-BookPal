import { describe, expect, it } from "vitest";

import {
  buildSpreads,
  orderForDisplay,
  pagesToPreload,
  percentFor,
  spreadIndexOfPage,
} from "./spreads";

describe("buildSpreads", () => {
  it("geeft losse pagina's in enkelmodus", () => {
    expect(buildSpreads(3, false, { aspects: {} })).toEqual([[0], [1], [2]]);
  });

  it("zet de omslag alleen en paart daarna", () => {
    // Zonder deze regel loopt een heel album één pagina uit de pas.
    expect(buildSpreads(5, true, { aspects: {} })).toEqual([[0], [1, 2], [3, 4]]);
  });

  it("laat een liggende pagina het scherm alleen vullen", () => {
    // Pagina 3 is een dubbelpagina-illustratie.
    const spreads = buildSpreads(6, true, { aspects: { 3: 1.6 } });
    expect(spreads).toEqual([[0], [1, 2], [3], [4, 5]]);
  });

  it("paart een staande pagina nooit met een liggende", () => {
    const spreads = buildSpreads(4, true, { aspects: { 2: 1.5 } });
    expect(spreads).toEqual([[0], [1], [2], [3]]);
  });

  it("laat een oneven laatste pagina alleen", () => {
    expect(buildSpreads(4, true, { aspects: {} })).toEqual([[0], [1, 2], [3]]);
  });

  it("kan de omslag meepakken als er geen omslagconventie is", () => {
    expect(buildSpreads(4, true, { aspects: {}, coverAlone: false })).toEqual([
      [0, 1],
      [2, 3],
    ]);
  });

  it("gaat uit van staand zolang de verhouding onbekend is", () => {
    expect(buildSpreads(3, true, { aspects: {} })).toEqual([[0], [1, 2]]);
  });

  it("behandelt een leeg boek", () => {
    expect(buildSpreads(0, true, { aspects: {} })).toEqual([]);
  });

  it("behandelt een boek van één pagina", () => {
    expect(buildSpreads(1, true, { aspects: {} })).toEqual([[0]]);
  });
});

describe("orderForDisplay", () => {
  it("laat westerse strips ongemoeid", () => {
    expect(orderForDisplay([1, 2], false)).toEqual([1, 2]);
  });

  it("spiegelt manga zodat rechts eerst gelezen wordt", () => {
    expect(orderForDisplay([1, 2], true)).toEqual([2, 1]);
  });

  it("verandert niets aan een enkele pagina", () => {
    expect(orderForDisplay([5], true)).toEqual([5]);
  });
});

describe("spreadIndexOfPage", () => {
  it("vindt de spread van een pagina, zodat een moduswissel je positie houdt", () => {
    const spreads = buildSpreads(6, true, { aspects: {} });
    expect(spreadIndexOfPage(spreads, 4)).toBe(2);
  });

  it("valt terug op het begin bij een onbekende pagina", () => {
    expect(spreadIndexOfPage([[0], [1]], 99)).toBe(0);
  });
});

describe("pagesToPreload", () => {
  it("laadt vooruit én één spread terug", () => {
    const spreads = buildSpreads(9, true, { aspects: {} });
    // spreads: [0] [1,2] [3,4] [5,6] [7,8]
    expect(pagesToPreload(spreads, 1, 2)).toEqual([3, 4, 5, 6, 0]);
  });

  it("loopt niet voorbij het einde", () => {
    const spreads = buildSpreads(3, false, { aspects: {} });
    expect(pagesToPreload(spreads, 2, 3)).toEqual([1]);
  });
});

describe("percentFor", () => {
  it("rekent op de laatste pagina van de spread", () => {
    const spreads = buildSpreads(10, true, { aspects: {} });
    expect(percentFor(spreads, 1, 10)).toBe(30);
  });

  it("is 100 aan het einde", () => {
    const spreads = buildSpreads(4, false, { aspects: {} });
    expect(percentFor(spreads, 3, 4)).toBe(100);
  });

  it("is 0 bij een leeg boek", () => {
    expect(percentFor([], 0, 0)).toBe(0);
  });
});
