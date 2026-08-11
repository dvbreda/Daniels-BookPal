import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { api, imageUrl } from "../api/client";
import type { Book, OriginRegion } from "../api/types";

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
  if (!data) return <p className="p-6 text-red-400">Serie niet gevonden.</p>;

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

      <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4">
        {data.books.map((book) => (
          <BookCard key={book.id} book={book} />
        ))}
      </div>
    </div>
  );
}

function BookCard({ book }: { book: Book }) {
  const percent = book.progress?.percent ?? 0;
  // Een epub of pdf gaat niet naar de stripleer maar naar het bestand zelf;
  // die formaten rendert de client, niet de server.
  const isComic = book.kind === "comic" || book.kind === "pdf";
  const target = isComic ? `/lezen/${book.id}` : imageUrl.file(book.id);

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
      </div>
    </>
  );

  const className =
    "block overflow-hidden rounded-lg bg-ink-800 transition hover:ring-2 hover:ring-accent";

  return isComic ? (
    <Link to={target} className={className}>
      {inner}
    </Link>
  ) : (
    <a href={target} className={className} download>
      {inner}
    </a>
  );
}
