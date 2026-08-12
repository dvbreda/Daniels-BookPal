import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import type { BookDetail } from "../api/types";
import { EpubReader } from "../reader/EpubReader";

/**
 * Een Wikipedia-artikel lezen met dezelfde lezer als je boeken.
 *
 * Waarom een epub en geen webpagina: zo krijg je je eigen lettergrootte, je
 * eigen thema en dezelfde manier van bladeren — en op de Kobo hoef je er geen
 * browser voor open te trekken.
 *
 * Er zit geen boek in de bibliotheek achter, dus de lezer krijgt een
 * kunstmatig BookDetail en schrijft geen voortgang weg.
 */
export function WikiReaderPage() {
  const { lang = "nl", key = "" } = useParams<{ lang: string; key: string }>();
  const [params] = useSearchParams();
  const navigate = useNavigate();

  const title = params.get("titel") || key.replace(/_/g, " ");
  const back = params.get("terug");

  // Alleen om te weten of het artikel er is; de lezer haalt het bestand zelf.
  const { data: hits } = useQuery({
    queryKey: ["wiki-search", lang, key],
    queryFn: () => api.wikiSearch(title, lang),
    staleTime: Infinity,
  });

  const book = {
    id: -1,
    series_id: -1,
    kind: "epub",
    title,
    number: null,
    volume: null,
    page_count: null,
    right_to_left: false,
    has_file: true,
    from_source: false,
    source_group_name: null,
    expires_at: null,
    extension: ".epub",
    added_at: new Date().toISOString(),
    progress: null,
    series_title: hits?.[0]?.description ?? "Wikipedia",
    toc: [],
  } as unknown as BookDetail;

  return (
    <EpubReader
      book={book}
      fileUrl={api.wikiArticleUrl(key, lang)}
      saveProgress={false}
      onClose={() => (back ? navigate(back) : navigate(-1))}
    />
  );
}
