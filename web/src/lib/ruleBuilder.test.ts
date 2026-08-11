import { describe, expect, it } from "vitest";

import { type ConditionRow, compileRows, decompileRule, fieldDefs } from "./ruleBuilder";

const defs = fieldDefs([
  { id: 1, name: "Strips" },
  { id: 2, name: "Manga" },
]);

describe("compileRows", () => {
  it("geeft een lege regel als er niets is ingevuld", () => {
    expect(compileRows([], defs)).toEqual({});
  });

  it("laat lege waarden weg", () => {
    const rows: ConditionRow[] = [
      { field: "kind", value: "" },
      { field: "extension", value: [] },
    ];
    expect(compileRows(rows, defs)).toEqual({});
  });

  it("levert één conditie zonder omhullende and", () => {
    const rows: ConditionRow[] = [{ field: "origin_region", value: "japan" }];
    expect(compileRows(rows, defs)).toEqual({ origin_region: { eq: "japan" } });
  });

  it("combineert meerdere condities met and", () => {
    const rows: ConditionRow[] = [
      { field: "extension", value: ["cbz", "cbr"] },
      { field: "origin_region", value: "europe" },
    ];
    expect(compileRows(rows, defs)).toEqual({
      and: [{ extension: { in: ["cbz", "cbr"] } }, { origin_region: { eq: "europe" } }],
    });
  });

  it("stuurt de map-id als getal, want de server vergelijkt met een int-kolom", () => {
    const rows: ConditionRow[] = [{ field: "root", value: "2" }];
    expect(compileRows(rows, defs)).toEqual({ root: { eq: 2 } });
  });

  it("gebruikt contains voor uitgever", () => {
    const rows: ConditionRow[] = [{ field: "publisher", value: "Dupuis" }];
    expect(compileRows(rows, defs)).toEqual({ publisher: { contains: "Dupuis" } });
  });
});

describe("decompileRule", () => {
  it("leest een lege regel als nul rijen", () => {
    expect(decompileRule({}, defs)).toEqual([]);
  });

  it("leest één conditie", () => {
    expect(decompileRule({ origin_region: { eq: "japan" } }, defs)).toEqual([
      { field: "origin_region", value: "japan" },
    ]);
  });

  it("leest een platte and terug naar rijen", () => {
    const rule = {
      and: [{ extension: { in: ["cbz"] } }, { origin_region: { eq: "europe" } }],
    };
    expect(decompileRule(rule, defs)).toEqual([
      { field: "extension", value: ["cbz"] },
      { field: "origin_region", value: "europe" },
    ]);
  });

  it("is een rondreis met compileRows", () => {
    const rows: ConditionRow[] = [
      { field: "kind", value: "epub" },
      { field: "reading_status", value: "finished" },
    ];
    expect(decompileRule(compileRows(rows, defs), defs)).toEqual(rows);
  });

  it("geeft null bij geneste or — die hoort in de JSON-modus", () => {
    const rule = { or: [{ kind: { eq: "epub" } }, { kind: { eq: "pdf" } }] };
    expect(decompileRule(rule, defs)).toBeNull();
  });

  it("geeft null bij not", () => {
    expect(decompileRule({ not: { kind: { eq: "epub" } } }, defs)).toBeNull();
  });

  it("geeft null bij een onbekend veld", () => {
    expect(decompileRule({ verzonnen: { eq: 1 } }, defs)).toBeNull();
  });

  it("geeft null bij een operator die de bouwer niet gebruikt", () => {
    // De bouwer zet origin_region altijd met eq; in staat alleen in de JSON-modus.
    expect(decompileRule({ origin_region: { in: ["japan"] } }, defs)).toBeNull();
  });

  it("geeft null als een and een onbekende conditie bevat", () => {
    const rule = { and: [{ kind: { eq: "epub" } }, { verzonnen: { eq: 1 } }] };
    expect(decompileRule(rule, defs)).toBeNull();
  });
});
