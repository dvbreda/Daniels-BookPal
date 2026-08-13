/**
 * Wielgebeurtenissen omrekenen naar hele pagina's.
 *
 * Losgetrokken omdat de maat per apparaat verschilt: een muiswiel geeft één
 * melding van rond de 100, een trackpad tientallen van een paar pixels. Per
 * melding bladeren zou met een trackpad een heel hoofdstuk voorbij laten
 * vliegen, dus tellen we op tot een drempel en houden we de rest vast.
 */

/** Hoeveel er op moet tellen voor één pagina. Ongeveer één muisklik. */
export const WHEEL_STEP = 60;

export interface WheelResult {
  steps: number;
  rest: number;
}

export function wheelSteps(
  carried: number,
  delta: number,
  step = WHEEL_STEP,
): WheelResult {
  const total = carried + delta;
  const steps = Math.trunc(total / step);
  return { steps, rest: total - steps * step };
}
