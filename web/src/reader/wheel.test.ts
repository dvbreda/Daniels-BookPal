import { describe, expect, it } from "vitest";

import { WHEEL_STEP, wheelSteps } from "./wheel";

describe("wheelSteps", () => {
  it("bladert één pagina bij een muisklik", () => {
    expect(wheelSteps(0, WHEEL_STEP).steps).toBe(1);
  });

  it("houdt kleine bewegingen vast tot ze samen genoeg zijn", () => {
    // Een trackpad geeft tientallen kleine meldingen; per stuk bladeren zou
    // een heel hoofdstuk voorbij laten vliegen.
    let rest = 0;
    let gebladerd = 0;
    for (let i = 0; i < 6; i += 1) {
      const uitkomst = wheelSteps(rest, 10);
      rest = uitkomst.rest;
      gebladerd += uitkomst.steps;
    }
    expect(gebladerd).toBe(1);
  });

  it("bladert terug bij omhoog scrollen", () => {
    expect(wheelSteps(0, -WHEEL_STEP).steps).toBe(-1);
  });

  it("laat niets weglekken", () => {
    const uitkomst = wheelSteps(0, WHEEL_STEP * 2.5);
    expect(uitkomst.steps).toBe(2);
    expect(uitkomst.rest).toBeCloseTo(WHEEL_STEP * 0.5);
  });
});
