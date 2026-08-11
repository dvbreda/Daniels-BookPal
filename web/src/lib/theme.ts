import { useCallback, useEffect, useState } from "react";

/**
 * Licht of donker, met "systeem" als standaard.
 *
 * "systeem" is de standaard omdat een leesapp meestal moet doen wat de rest
 * van het apparaat doet: 's avonds donker, overdag licht, zonder dat je er
 * iets voor hoeft aan te zetten. Wie dat niet wil kiest zelf.
 */

export type ThemeChoice = "system" | "light" | "dark";

const STORAGE_KEY = "bookpal.theme";

export const THEME_LABELS: Record<ThemeChoice, string> = {
  system: "Systeem",
  light: "Licht",
  dark: "Donker",
};

function prefersLight(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-color-scheme: light)").matches;
}

/** Zet het gekozen thema op <html>, waar de CSS-variabelen op reageren. */
export function applyTheme(choice: ThemeChoice): void {
  if (typeof document === "undefined") return;
  const light = choice === "light" || (choice === "system" && prefersLight());
  const root = document.documentElement;
  if (light) root.setAttribute("data-theme", "light");
  else root.removeAttribute("data-theme");
}

export function readStoredTheme(): ThemeChoice {
  if (typeof window === "undefined") return "system";
  const stored = window.localStorage.getItem(STORAGE_KEY);
  return stored === "light" || stored === "dark" ? stored : "system";
}

export function useTheme(): [ThemeChoice, (choice: ThemeChoice) => void] {
  const [choice, setChoice] = useState<ThemeChoice>(readStoredTheme);

  useEffect(() => {
    applyTheme(choice);
    try {
      window.localStorage.setItem(STORAGE_KEY, choice);
    } catch {
      /* private mode: het thema geldt dan alleen deze sessie */
    }
  }, [choice]);

  // Meebewegen als het systeem overdag omslaat, maar alleen als je het aan het
  // systeem hebt overgelaten.
  useEffect(() => {
    if (choice !== "system" || !window.matchMedia) return;
    const query = window.matchMedia("(prefers-color-scheme: light)");
    const onChange = () => applyTheme("system");
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, [choice]);

  const update = useCallback((next: ThemeChoice) => setChoice(next), []);
  return [choice, update];
}
