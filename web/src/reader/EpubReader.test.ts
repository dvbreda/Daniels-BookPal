import { describe, expect, it } from "vitest";

import { loadingLabel } from "./EpubReader";

describe("loadingLabel", () => {
  it("toont een generiek label voordat er iets binnenkomt", () => {
    expect(loadingLabel(null)).toBe("Laden…");
    expect(loadingLabel({ loaded: 0, total: 1000 })).toBe("Laden…");
  });

  it("toont een percentage met de grootte in MB als de totale omvang bekend is", () => {
    expect(loadingLabel({ loaded: 50_000_000, total: 173_749_193 })).toBe(
      "29% (50 MB van 174 MB)",
    );
  });

  it("toont alleen wat al binnen is als de omvang onbekend is", () => {
    expect(loadingLabel({ loaded: 12_000_000, total: null })).toBe("12 MB opgehaald…");
  });

  it("gaat nooit boven de 100%, ook niet bij een afwijkende Content-Length", () => {
    expect(loadingLabel({ loaded: 200, total: 100 })).toBe("100% (0 MB van 0 MB)");
  });
});
