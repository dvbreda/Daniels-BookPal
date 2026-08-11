import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { ApiError, api, imageUrl } from "../api/client";
import type { Book, OriginRegion } from "../api/types";
import { SourceBadge } from "../components/SourceBadge";
import { TranslationPicker } from "../components/TranslationPicker";

const REGIONS: [OriginRegion, string][] = [
  ["europe", "Europa"],
  ["japan", "Japan"],
  ["korea", "Korea"],
  ["china", "China"],
  ["us", "VS"],
  ["other", "Overig"],
  ["unknown", "Onbekend"],
];

const ORIGIN_EXPLANATION: Record<string, string> = {
  manual: "handmatig gezet",
  online: "van een online bron",
  embedded: "uit het bestand zelf",
  root_default: "standaard van de map",
  none: "niet vastgesteld",
};

export function SeriesPage() {
  const { id } = useParams<{ id: string }>();
  const seriesId = Number(id);
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["series-detail", seriesId],
    queryFn: () => api.seriesDetail(seriesId),
  });

  const setOrigin = useMutation({
    mutationFn: (region: OriginRegion) =>
      api.setOrigin(seriesId, { origin_region: region }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["series-detail", seriesId] });
      void queryClient.invalidateQueries({ queryKey: ["series"] });
    },
  });

  if (isLoading) return <p className="p-6 text-slate-400">Laden…</p>;
  if (!data) return <p className="p-6 text-danger">Serie niet gevonden.</p>;

  return (
    <div className="mx-auto max-w-5xl px-4 py-6">
      <Link to="/" className="text-sm text-slate-400 hover:text-slate-200">
        ← Bibliotheek
      </Link>

      <header className="mt-4">
        <h1 className="text-2xl font-semibold text-slate-100">{data.title}</h1>
        <p className="mt-1 text-sm text-slate-400">
          {data.book_count} {data.book_count === 1 ? "deel" : "delen"}
          {data.publisher && ` · ${data.publisher}`}
        </p>
        {data.summary && <p className="mt-3 max-w-2xl text-sm text-slate-300">{data.summary}</p>}
      </header>

      <section className="mt-6 rounded border border-ink-600 p-4">
        <h2 className="text-sm font-medium text-slate-200">Herkomst</h2>
        <p className="mt-1 text-xs text-slate-500">
          Nu: {REGIONS.find(([key]) => key === data.origin_region)?.[1]} (
          {ORIGIN_EXPLANATION[data.origin_source]}). Wat je hier kiest blijft staan, ook na een
          nieuwe scan.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          {REGIONS.map(([value, label]) => (
            <button
              key={value}
              onClick={() => setOrigin.mutate(value)}
              disabled={setOrigin.isPending}
              className={`rounded px-2 py-1 text-sm ${
                data.origin_region === value
                  ? "bg-accent text-ink-900"
                  : "bg-ink-700 text-slate-300 hover:bg-ink-600"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </section>

      <TranslationPicker seriesId={seriesId} books={data.books} />

      <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4">
        {data.books.map((book) => (
          <BookCard key={book.id} book={book} seriesId={seriesId} />
        ))}
      </div>
    </div>
  );
}

function BookCard({ book, seriesId }: { book: Book; seriesId: number }) {
  const queryClient = useQueryClient();
  const percent = book.progress?.percent ?? 0;
  // Alles leest nu in de app: strips en pdf als beeld van de server, epub met
  // foliate-js in de browser (M6).
  const target = `/lezen/${book.id}`;

  const download = useMutation({
    mutationFn: () => api.downloadChapter(book.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["series-detail", seriesId] });
    },
  });

  const inner = (
    <>
      <div className="relative aspect-[2/3] bg-ink-700">
        <img
          src={imageUrl.cover(book.id)}
          alt=""
          loading="lazy"
          className="h-full w-full object-cover"
          onError={(event) => {
            event.currentTarget.style.visibility = "hidden";
          }}
        />
        <div className="absolute left-1 top-1">
          <SourceBadge
            fromSource={book.from_source}
            hasFile={book.has_file}
            expiresAt={book.expires_at}
          />
        </div>
        {percent > 0 && (
          <div className="absolute inset-x-0 bottom-0 h-1 bg-ink-900/70">
            <div className="h-full bg-accent" style={{ width: `${percent}%` }} />
          </div>
        )}
      </div>
      <div className="p-2">
        <p className="truncate text-sm text-slate-100">
          {book.number ? `${book.number}. ` : ""}
          {book.title}
        </p>
        <p className="text-xs text-slate-500">
          {book.page_count ?? "?"} {book.kind === "epub" ? "hoofdstukken" : "pagina's"}
          {percent > 0 && ` · ${Math.round(percent)}%`}
        </p>
        {book.source_group_name && (
          <p className="truncate text-xs text-slate-600" title="Vertaald door">
            {book.source_group_name}
          </p>
        )}
      </div>
    </>
  );

  const className =
    "block overflow-hidden rounded-lg bg-ink-800 transition hover:ring-2 hover:ring-accent";

  // Een hoofdstuk van een bron dat nog niet is opgehaald heeft niets om naartoe
  // te linken; daar hoort een knop, geen dode link.
  if (!book.has_file) {
    return (
      <div className={className}>
        {inner}
        <div className="px-2 pb-2">
          <button
            onClick={() => download.mutate()}
            disabled={download.isPending}
            className="w-full rounded bg-accent px-2 py-1.5 text-xs text-ink-900 disabled:opacity-50"
          >
            {download.isPending ? "Ophalen…" : "Ophalen"}
          </button>
          {download.isError && (
            <p className="mt-1 text-xs text-danger">
              {download.error instanceof ApiError ? download.error.message : "Ophalen mislukt."}
            </p>
          )}
        </div>
      </div>
    );
  }

  return (
    <Link to={target} className={className}>
      {inner}
    </Link>
  );
}
