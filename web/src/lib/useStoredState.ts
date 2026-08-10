import { useCallback, useEffect, useState } from "react";

/**
 * Voorkeuren die een sessie overleven — leesrichting, fit-modus, dubbele
 * pagina's. Die wil je één keer instellen, niet bij elk boek opnieuw.
 */
export function useStoredState<T>(key: string, initial: T): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => {
    if (typeof window === "undefined") return initial;
    try {
      const stored = window.localStorage.getItem(`bookpal.${key}`);
      return stored === null ? initial : (JSON.parse(stored) as T);
    } catch {
      return initial;
    }
  });

  useEffect(() => {
    try {
      window.localStorage.setItem(`bookpal.${key}`, JSON.stringify(value));
    } catch {
      /* private mode of vol geheugen — geen reden om de lezer te laten vallen */
    }
  }, [key, value]);

  const update = useCallback((next: T) => setValue(next), []);
  return [value, update];
}
