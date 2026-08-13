import { useQuery } from "@tanstack/react-query";

import { ApiError, api } from "../api/client";
import type { PageColourInfo } from "../api/types";

/**
 * Wat er qua kleur voor deze pagina klaarligt.
 *
 * Gedeeld door de afbeelding en het merkje, zodat het bij één verzoek per
 * pagina blijft. Alleen opgevraagd als kleur aanstaat: staat hij uit, dan
 * verandert het antwoord toch niets aan wat je ziet.
 */
export function usePageColour(bookId: number, pageIndex: number, lang: string | undefined, enabled: boolean) {
  return useQuery<PageColourInfo>({
    queryKey: ["colour-info", bookId, pageIndex, lang ?? null],
    queryFn: () => api.pageColourInfo(bookId, pageIndex, lang),
    enabled,
    retry: (_count, error) => !(error instanceof ApiError && error.status === 404),
    staleTime: Infinity,
  });
}
