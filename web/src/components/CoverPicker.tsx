import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError, api } from "../api/client";
import type { SearchHit } from "../api/types";

/**
 * Een schone omslag van een bron koppelen aan deze serie.
 *
 * Bestaat vooral voor scanlaties: "pagina 1 van het eerste deel" is daar vaak
 * een credits-pagina van de vertaalgroep over de echte omslag heen, niet de
 * omslag zelf. Werkt voor elke serie, ook een die je zelf hebt gescand — er
 * komt geen abonnement bij, alleen de omslag.
 */
export function CoverPicker({ seriesId }: { seriesId: number }) {
  const queryClient = useQueryClient();
  const { data: sources } = useQuery({ queryKey: ["sources"], queryFn: api.sources });
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const source = sources?.[0];

  const { data: hits, isFetching } = useQuery({
    queryKey: ["cover-search", source?.id, submitted],
    queryFn: () => api.searchSource(source!.id, submitted),
    enabled: open && !!source && submitted.length > 0,
  });

  const choose = useMutation({
    mutationFn: (hit: SearchHit) => api.attachCover(seriesId, { source_id: source!.id, ref: hit.ref }),
    onSuccess: () => {
      setOpen(false);
      setMessage(null);
      void queryClient.invalidateQueries({ queryKey: ["series-detail", seriesId] });
      void queryClient.invalidateQueries({ queryKey: ["series"] });
    },
    onError: (error: unknown) => {
      setMessage(error instanceof ApiError ? error.message : "Omslag koppelen mislukt.");
    },
  });

  if (!source) return null;

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="mt-2 text-xs text-slate-500 underline hover:text-slate-300"
      >
        Omslag niet goed? Kies een andere
      </button>
    );
  }

  return (
    <section className="mt-4 rounded border border-ink-600 p-4">
      <h2 className="text-sm font-medium text-slate-200">Omslag kiezen</h2>
      <p className="mt-1 text-xs text-slate-500">
        Bij scanlaties staat er op pagina 1 vaak een credits-pagina van de
        vertaalgroep over de echte omslag heen. Dit haalt de schone versie bij{" "}
        {source.name} op.
      </p>
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
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="rounded bg-ink-700 px-4 py-2 text-sm text-slate-300"
        >
          Annuleren
        </button>
      </form>

      {isFetching && <p className="mt-3 text-sm text-slate-400">Zoeken…</p>}
      {message && <p className="mt-3 text-sm text-danger">{message}</p>}

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
    </section>
  );
}
