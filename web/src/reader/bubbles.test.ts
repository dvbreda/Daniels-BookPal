import { describe, expect, it } from "vitest";

import { type Box, expandBox, fontScale } from "./bubbles";

describe("expandBox", () => {
  it("maakt het vlak ruimer dan de gedetecteerde tekst", () => {
    const [x0, y0, x1, y1] = expandBox([0.2, 0.2, 0.4, 0.3]);
    expect(x0).toBeLessThan(0.2);
    expect(y0).toBeLessThan(0.2);
    expect(x1).toBeGreaterThan(0.4);
    expect(y1).toBeGreaterThan(0.3);
  });

  it("groeit naar verhouding, niet met een vast aantal pixels", () => {
    const smal = expandBox([0.4, 0.4, 0.5, 0.5]);
    const breed = expandBox([0.0, 0.4, 0.8, 0.5]);
    expect(breed[0]).toBe(0);
    expect(0.5 - smal[0]).toBeLessThan(breed[2] - 0.8 + 0.8);
  });

  it("loopt niet buiten de pagina", () => {
    const [x0, y0, x1, y1] = expandBox([0, 0, 1, 1]);
    expect(x0).toBe(0);
    expect(y0).toBe(0);
    expect(x1).toBe(1);
    expect(y1).toBe(1);
  });
});

describe("fontScale", () => {
  const ruim: Box = [0.1, 0.1, 0.5, 0.4];

  it("laat korte tekst op ware grootte staan", () => {
    expect(fontScale(ruim, 10)).toBe(1);
  });

  it("krimpt naarmate er meer tekst in moet", () => {
    const kort = fontScale(ruim, 50);
    const lang = fontScale(ruim, 400);
    expect(lang).toBeLessThan(kort);
  });

  it("wordt nooit groter dan de basismaat", () => {
    // Anders zou één woord in een grote ballon beeldvullend worden.
    expect(fontScale([0, 0, 1, 1], 1)).toBe(1);
  });

  it("krimpt sterker in een klein vlak dan in een groot", () => {
    const klein = fontScale([0.1, 0.1, 0.2, 0.15], 60);
    const groot = fontScale([0.1, 0.1, 0.6, 0.5], 60);
    expect(klein).toBeLessThan(groot);
  });

  it("gaat niet stuk op een leeg vlak of lege tekst", () => {
    expect(fontScale([0.3, 0.3, 0.3, 0.3], 20)).toBe(1);
    expect(fontScale(ruim, 0)).toBe(1);
  });
});
