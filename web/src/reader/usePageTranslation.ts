import { useQuery } from "@tanstack/react-query";

import { ApiError, api } from "../api/client";
import type { PageTranslation } from "../api/types";

/**
 * Wat er voor deze pagina klaarligt (M8).
 *
 * Eén query, gedeeld door de overlay en de afbeelding zelf: in de tekststand
 * legt de lezer tekstvlakken over het origineel, in de beeldstanden vervangt
 * hij de hele afbeelding. Zonder deze gedeelde query zou de lezer twee keer
 * hetzelfde moeten opvragen om te weten welke van de twee het wordt.
 */
export function usePageTranslation(bookId: number, pageIndex: number, enabled: boolean) {
  return useQuery<PageTranslation>({
    queryKey: ["translation", bookId, pageIndex],
    queryFn: () => api.pageTranslation(bookId, pageIndex),
    enabled,
    // 404 = nog niet vertaald. Dat is een normale toestand, geen storing, dus
    // niet opnieuw proberen: de wachtrij komt er vanzelf aan toe.
    retry: (_count, error) => !(error instanceof ApiError && error.status === 404),
    staleTime: Infinity,
  });
}
