import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError, api, imageUrl } from "../api/client";
import type { SearchHit, SeriesDetail } from "../api/types";

type Mode = null | "search" | "page";

/**
 * De omslag van een serie bijstellen: zoeken bij een bron, of gewoon een
 * andere pagina van het eerste boek kiezen.
 *
 * Bestaat vooral voor scanlaties: "pagina 1 van het eerste deel" is daar vaak
 * een credits- of wervingspagina van de vertaalgroep over de echte omslag
 * heen, niet de omslag zelf. Een bron-zoekopdracht lost dat het netst op,
 * maar niet elke serie staat bij een bron — dan is een andere pagina kiezen
 * het enige alternatief. Werkt voor elke serie, ook een die je zelf hebt
 * gescand; er komt geen abonnement bij, alleen de omslag.
 */
export function CoverPicker({ series }: { series: SeriesDetail }) {
  const queryClient = useQueryClient();
  const { data: sources } = useQuery({ queryKey: ["sources"], queryFn: api.sources });
  const [mode, setMode] = useState<Mode>(null);
  const [message, setMessage] = useState<string | null>(null);

  const source = sources?.[0];
  const firstBook = series.books[0];
  // Alleen strips en pdf hebben vaste pagina's om als omslag te kiezen; een
  // epub rendert de client zelf en heeft geen paginanummers op de server.
  const canPickPage = firstBook && firstBook.kind !== "epub" && (firstBook.page_count ?? 0) > 0;

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ["series-detail", series.id] });
    void queryClient.invalidateQueries({ queryKey: ["series"] });
  }

  if (!source && !canPickPage) return null;

  if (mode === null) {
    return (
      <div className="mt-2 flex flex-wrap gap-3 text-xs text-slate-500">
        <span>Omslag niet goed?</span>
        {source && (
          <button onClick={() => setMode("search")} className="underline hover:text-slate-300">
            Zoek bij een bron
          </button>
        )}
        {canPickPage && (
          <button onClick={() => setMode("page")} className="underline hover:text-slate-300">
            Kies een andere pagina
          </button>
        )}
      </div>
    );
  }

  return (
    <section className="mt-4 rounded border border-ink-600 p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-slate-200">Omslag kiezen</h2>
        <button
          onClick={() => setMode(null)}
          className="text-xs text-slate-500 hover:text-slate-300"
        >
          Sluiten
        </button>
      </div>
      {message && <p className="mt-2 text-sm text-danger">{message}</p>}
      {mode === "search" && source && (
        <SourceSearch
          seriesId={series.id}
          sourceId={source.id}
          sourceName={source.name}
          onDone={(error) => {
            setMessage(error);
            if (!error) {
              setMode(null);
              refresh();
            }
          }}
        />
      )}
      {mode === "page" && firstBook && (
        <PagePicker
          seriesId={series.id}
          bookId={firstBook.id}
          pageCount={firstBook.page_count ?? 0}
          currentPageIndex={series.cover_page_index}
          onDone={(error) => {
            setMessage(error);
            if (!error) refresh();
          }}
        />
      )}
    </section>
  );
}

function SourceSearch({
  seriesId,
  sourceId,
  sourceName,
  onDone,
}: {
  seriesId: number;
  sourceId: number;
  sourceName: string;
  onDone: (error: string | null) => void;
}) {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");

  const { data: hits, isFetching } = useQuery({
    queryKey: ["cover-search", sourceId, submitted],
    queryFn: () => api.searchSource(sourceId, submitted),
    enabled: submitted.length > 0,
  });

  const choose = useMutation({
    mutationFn: (hit: SearchHit) => api.attachCover(seriesId, { source_id: sourceId, ref: hit.ref }),
    onSuccess: () => onDone(null),
    onError: (error: unknown) => {
      onDone(error instanceof ApiError ? error.message : "Omslag koppelen mislukt.");
    },
  });

  return (
    <div className="mt-3">
      <p className="text-xs text-slate-500">Haalt de schone versie bij {sourceName} op.</p>
      <form
        className="mt-3 flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          setSubmitted(query.trim());
        }}
      >
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Titel…"
          className="min-w-0 flex-1 rounded bg-ink-700 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500"
        />
        <button type="submit" className="rounded bg-accent px-4 py-2 text-sm text-ink-900">
          Zoeken
        </button>
      </form>

      {isFetching && <p className="mt-3 text-sm text-slate-400">Zoeken…</p>}

      <div className="mt-3 grid grid-cols-3 gap-3 sm:grid-cols-5">
        {hits?.map((hit) => (
          <button
            key={hit.ref}
            onClick={() => choose.mutate(hit)}
            disabled={choose.isPending}
            className="group text-left disabled:opacity-50"
            title={hit.title}
          >
            <div className="aspect-[2/3] overflow-hidden rounded bg-ink-700">
              {/* Rechtstreeks van de bron: dit is een eenmalige blik in een
                  zoekresultaat, geen herhaalde paginaweergave — daar is onze
                  eigen cache (na het koppelen) voor bedoeld, niet dit lijstje. */}
              {hit.cover_url ? (
                <img
                  src={hit.cover_url}
                  alt=""
                  loading="lazy"
                  className="h-full w-full object-cover"
                  onError={(event) => {
                    event.currentTarget.style.visibility = "hidden";
                  }}
                />
              ) : (
                <div className="flex h-full w-full items-center justify-center text-2xl text-slate-600">
                  📖
                </div>
              )}
            </div>
            <p className="mt-1 truncate text-xs text-slate-300 group-hover:text-accent">
              {hit.title}
            </p>
          </button>
        ))}
      </div>
      {hits?.length === 0 && submitted && (
        <p className="mt-3 text-sm text-slate-500">Niets gevonden.</p>
      )}
    </div>
  );
}

/** Hoeveel pagina's er te kiezen worden aangeboden — de omslag zit vrijwel
 * altijd binnen de eerste handvol, en meer wordt een lange, trage rij. */
const MAX_PAGE_CHOICES = 12;

function PagePicker({
  seriesId,
  bookId,
  pageCount,
  currentPageIndex,
  onDone,
}: {
  seriesId: number;
  bookId: number;
  pageCount: number;
  currentPageIndex: number | null;
  onDone: (error: string | null) => void;
}) {
  const choose = useMutation({
    mutationFn: (pageIndex: number | null) => api.setCoverPage(seriesId, pageIndex),
    onSuccess: () => onDone(null),
    onError: (error: unknown) => {
      onDone(error instanceof ApiError ? error.message : "Omslag instellen mislukt.");
    },
  });

  const choices = Array.from({ length: Math.min(pageCount, MAX_PAGE_CHOICES) }, (_, i) => i);

  return (
    <div className="mt-3">
      <p className="text-xs text-slate-500">
        Kies welke pagina van het eerste deel als omslag dient.
      </p>
      <div className="mt-3 grid grid-cols-4 gap-2 sm:grid-cols-6">
        {choices.map((index) => (
          <button
            key={index}
            onClick={() => choose.mutate(index)}
            disabled={choose.isPending}
            className={`overflow-hidden rounded ring-2 transition disabled:opacity-50 ${
              currentPageIndex === index ? "ring-accent" : "ring-transparent hover:ring-ink-600"
            }`}
            title={`Pagina ${index + 1}`}
          >
            <img
              src={imageUrl.page(bookId, index, "thumb")}
              alt={`Pagina ${index + 1}`}
              loading="lazy"
              className="aspect-[2/3] w-full object-cover"
            />
          </button>
        ))}
      </div>
      {currentPageIndex !== null && (
        <button
          onClick={() => choose.mutate(null)}
          disabled={choose.isPending}
          className="mt-3 text-xs text-slate-500 underline hover:text-slate-300 disabled:opacity-50"
        >
          Terug naar de standaardkeuze
        </button>
      )}
    </div>
  );
}
