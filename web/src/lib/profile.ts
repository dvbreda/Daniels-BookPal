/**
 * Kiest het beeldprofiel op basis van het scherm.
 *
 * De server rendert per profiel en cachet het resultaat, dus hier alleen kiezen
 * — niet in de browser schalen. Dat scheelt bandbreedte over ZeroTier en
 * geheugen op een iPad met een lange webtoon.
 */

export type PageProfile = "web" | "web-hidpi";

export function pickPageProfile(
  width: number = typeof window === "undefined" ? 1280 : window.innerWidth,
  pixelRatio: number = typeof window === "undefined" ? 1 : window.devicePixelRatio,
): PageProfile {
  const effective = width * Math.min(pixelRatio, 3);
  return effective > 1600 ? "web-hidpi" : "web";
}

export function pickCoverProfile(): "thumb" | "cover" {
  if (typeof window === "undefined") return "cover";
  return window.innerWidth < 640 ? "thumb" : "cover";
}
