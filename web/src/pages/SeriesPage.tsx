import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError, api, imageUrl } from "../api/client";
import type { Book, OriginRegion, SeriesDetail } from "../api/types";
import { CoverPicker } from "../components/CoverPicker";
import { EditionsPanel } from "../components/EditionsPanel";
import { SourceBadge } from "../components/SourceBadge";
import { TranslationPicker } from "../components/TranslationPicker";
import { useStoredState } from "../lib/useStoredState";

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

  // Onthouden over series heen: wie dit aanzet wil het meestal overal.
  const [hideRead, setHideRead] = useStoredState("series.hideRead", false);
  const visible = useMemo(
    () => (hideRead ? (data?.books ?? []).filter((b) => !b.progress?.finished) : data?.books ?? []),
    [data?.books, hideRead],
  );

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
          {data.authors.length > 0 && ` · ${data.authors.join(", ")}`}
          {data.publisher && ` · ${data.publisher}`}
        </p>
        {data.summary && <p className="mt-3 max-w-2xl text-sm text-slate-300">{data.summary}</p>}
      </header>

      <ContinueBar seriesId={seriesId} />

      <WikiLinks title={data.title} authors={data.authors} seriesId={seriesId} />

      <SeriesSettings series={data} seriesId={seriesId} setOrigin={setOrigin} />

      <div className="mt-6 flex items-center justify-between">
        <h2 className="text-sm font-medium text-slate-200">
          {visible.length === data.books.length
            ? `${data.books.length} delen`
            : `${visible.length} van ${data.books.length} delen`}
        </h2>
        <label className="flex items-center gap-2 text-xs text-slate-400">
          <input
            type="checkbox"
            checked={hideRead}
            onChange={(event) => setHideRead(event.target.checked)}
          />
          Gelezen verbergen
        </label>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4">
        {visible.map((book) => (
          <BookCard key={book.id} book={book} seriesId={seriesId} />
        ))}
      </div>
      {visible.length === 0 && (
        <p className="mt-4 text-sm text-slate-500">
          Alles gelezen. Haal het vinkje weg om ze weer te zien.
        </p>
      )}
    </div>
  );
}

/**
 * Achtergrond bij deze serie (en de auteur) op Wikipedia.
 *
 * Zoekt pas als je erop klikt: bij het openen van elke seriepagina meteen
 * Wikipedia bevragen is verkeer waar je meestal niets aan hebt, en het is niet
 * ons eigen adres om zomaar te belasten.
 */
function WikiLinks({
  title,
  authors,
  seriesId,
}: {
  title: string;
  authors: string[];
  seriesId: number;
}) {
  const [term, setTerm] = useState<string | null>(null);
  const navigate = useNavigate();

  const { data, isFetching, error } = useQuery({
    queryKey: ["wiki-search", term],
    queryFn: () => api.wikiSearch(term!),
    enabled: term !== null,
    staleTime: Infinity,
  });

  const onderwerpen = [title, ...authors.slice(0, 2)];

  return (
    <section className="mt-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-slate-500">Achtergrond:</span>
        {onderwerpen.map((onderwerp) => (
          <button
            key={onderwerp}
            onClick={() => setTerm(onderwerp)}
            className={`rounded px-2 py-1 text-xs ${
              term === onderwerp
                ? "bg-accent text-ink-900"
                : "bg-ink-700 text-slate-300 hover:bg-ink-600"
            }`}
          >
            {onderwerp}
          </button>
        ))}
      </div>

      {isFetching && <p className="mt-2 text-xs text-slate-500">Zoeken op Wikipedia…</p>}
      {error && (
        <p className="mt-2 text-xs text-danger">
          {error instanceof ApiError ? error.message : "Wikipedia niet bereikbaar."}
        </p>
      )}
      {data && data.length === 0 && (
        <p className="mt-2 text-xs text-slate-500">Niets gevonden op Wikipedia.</p>
      )}
      {data && data.length > 0 && (
        <ul className="mt-2 space-y-1">
          {data.map((hit) => (
            <li key={`${hit.lang}:${hit.key}`}>
              <button
                onClick={() =>
                  navigate(
                    `/wiki/${hit.lang}/${encodeURIComponent(hit.key)}` +
                      `?titel=${encodeURIComponent(hit.title)}&terug=/serie/${seriesId}`,
                  )
                }
                className="w-full rounded bg-ink-800 px-3 py-2 text-left text-sm hover:bg-ink-700"
              >
                <span className="text-slate-100">{hit.title}</span>
                <span className="ml-2 text-xs uppercase text-slate-500">{hit.lang}</span>
                {hit.description && (
                  <span className="block truncate text-xs text-slate-500">{hit.description}</span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/**
 * Serie-instellingen achter een tandwiel.
 *
 * Herkomst, omslag en vertaalgroep zijn dingen die je één keer goedzet en
 * daarna nooit meer aanraakt. Ze stonden alle drie permanent open boven de
 * hoofdstukkenlijst, waardoor je op een telefoon eerst langs drie panelen
 * moest scrollen voor je bij je strips was. Nu dicht, en de lijst staat weer
 * bovenaan.
 */
function SeriesSettings({
  series,
  seriesId,
  setOrigin,
}: {
  series: SeriesDetail;
  seriesId: number;
  setOrigin: { mutate: (region: OriginRegion) => void; isPending: boolean };
}) {
  const [open, setOpen] = useState(false);

  return (
    <section className="mt-4">
      <button
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="flex items-center gap-2 rounded px-2 py-1 text-sm text-slate-400 hover:bg-ink-800 hover:text-slate-200"
      >
        <span aria-hidden>⚙</span>
        Instellingen
        <span aria-hidden className="text-xs">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="mt-2">
          <section className="rounded border border-ink-600 p-4">
            <h2 className="text-sm font-medium text-slate-200">Herkomst</h2>
            <p className="mt-1 text-xs text-slate-500">
              Nu: {REGIONS.find(([key]) => key === series.origin_region)?.[1]} (
              {ORIGIN_EXPLANATION[series.origin_source]}). Wat je hier kiest blijft staan, ook
              na een nieuwe scan.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {REGIONS.map(([value, label]) => (
                <button
                  key={value}
                  onClick={() => setOrigin.mutate(value)}
                  disabled={setOrigin.isPending}
                  className={`rounded px-2 py-1 text-sm ${
                    series.origin_region === value
                      ? "bg-accent text-ink-900"
                      : "bg-ink-700 text-slate-300 hover:bg-ink-600"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </section>

          <EditionsPanel seriesId={seriesId} editions={series.editions} />
          <CoverPicker series={series} />
          <TranslationPicker seriesId={seriesId} books={series.books} />
          {series.from_source && <ImportPanel series={series} seriesId={seriesId} />}
        </div>
      )}
    </section>
  );
}

function BookCard({ book, seriesId }: { book: Book; seriesId: number }) {
  const queryClient = useQueryClient();
  const [toonVersies, setVersies] = useState(false);
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

  const leesstatus = useMutation({
    mutationFn: (finished: boolean) => api.setReadState(book.id, finished),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["series-detail", seriesId] });
      void queryClient.invalidateQueries({ queryKey: ["continue", seriesId] });
    },
  });

  const uit = book.progress?.finished ?? false;

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
          {/* Zonder het deel is de volgorde niet te volgen zodra hoofdstukken
              per deel opnieuw beginnen te tellen (elk deel heeft een "1"). */}
          {book.volume ? `Deel ${book.volume} · ` : ""}
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
        {/* Alleen tonen als er iets te kiezen viel: bij één uitgave zegt de
            naam niets, en dan is het ruis onder elk deel. */}
        {book.edition_name && book.alternatives.length > 0 && (
          <p className="truncate text-xs text-slate-600">{book.edition_name}</p>
        )}
      </div>
    </>
  );

  const className =
    "block overflow-hidden rounded-lg bg-ink-800 transition hover:ring-2 hover:ring-accent";

  // Zelf de leesstatus zetten. De automatiek is soms te gretig — een kort
  // hoofdstuk staat na één blik op 100% — en dan wil je een weg terug.
  const statusknop = (
    <button
      onClick={() => leesstatus.mutate(!uit)}
      disabled={leesstatus.isPending}
      title={uit ? "Markeer als ongelezen" : "Markeer als gelezen"}
      aria-label={uit ? "Markeer als ongelezen" : "Markeer als gelezen"}
      className={`absolute right-1 top-1 rounded px-1.5 py-0.5 text-xs disabled:opacity-50 ${
        uit ? "bg-accent text-ink-900" : "bg-ink-900/70 text-slate-400 hover:text-slate-100"
      }`}
    >
      ✓
    </button>
  );

  // Andere versies van precies dit deel. Buiten de kaartlink gehouden: een link
  // in een link is geen geldige HTML, en een klik zou naar de verkeerde versie
  // gaan.
  const versies = book.alternatives.length > 0 && (
    <div className="px-2 pb-2">
      <button
        onClick={() => setVersies(!toonVersies)}
        aria-expanded={toonVersies}
        className="w-full rounded bg-ink-700 px-2 py-1 text-xs text-slate-400 hover:text-slate-200"
      >
        {book.alternatives.length + 1} versies
      </button>
      {toonVersies && (
        <ul className="mt-1 space-y-1">
          {book.alternatives.map((andere) => (
            <li key={andere.id}>
              {andere.has_file ? (
                <Link
                  to={`/lezen/${andere.id}`}
                  className="block truncate rounded px-2 py-1 text-xs text-slate-300 hover:bg-ink-700"
                >
                  {andere.edition_name ?? andere.title}
                </Link>
              ) : (
                <span
                  className="block truncate px-2 py-1 text-xs text-slate-600"
                  title="Nog niet opgehaald"
                >
                  {andere.edition_name ?? andere.title}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );

  // Een hoofdstuk van een bron dat nog niet is opgehaald heeft niets om naartoe
  // te linken; daar hoort een knop, geen dode link.
  if (!book.has_file) {
    return (
      <div className={`relative ${className}`}>
        {inner}
        {statusknop}
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
        {versies}
      </div>
    );
  }

  return (
    <div className={`relative ${className}`}>
      <Link to={target} className="block">
        {inner}
      </Link>
      {statusknop}
      {versies}
    </div>
  );
}


/**
 * "Lees verder" (M8-bijwerk).
 *
 * De server bepaalt wáár je verder leest — op leesvolgorde, niet op "laatst
 * geopend", want bij manga lees je vooruit en een teruggekeken oud hoofdstuk
 * hoort je niet terug te trekken. De knop ernaast ruimt op wat je daarvóór
 * blijkbaar al elders gelezen had.
 */
function ContinueBar({ seriesId }: { seriesId: number }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { data } = useQuery({
    queryKey: ["continue", seriesId],
    queryFn: () => api.continueReading(seriesId),
    // 404 = niets leesbaars in deze serie; dat is geen storing.
    retry: (_count, error) => !(error instanceof ApiError && error.status === 404),
  });

  const ophalen = useMutation({
    mutationFn: (bookId: number) => api.downloadChapter(bookId),
    onSuccess: (_result, bookId) => {
      void queryClient.invalidateQueries({ queryKey: ["series-detail", seriesId] });
      navigate(`/lezen/${bookId}`);
    },
  });

  const markRead = useMutation({
    mutationFn: () => api.markReadBefore(seriesId, data!.book_id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["continue", seriesId] });
      void queryClient.invalidateQueries({ queryKey: ["series-detail", seriesId] });
    },
  });

  if (!data) return null;

  // Nog niet op de NAS: dan hoort de knop hem eerst op te halen en daarna te
  // openen. Bij een serie die je online volgt is dat de normale gang van zaken.
  const label = !data.has_file
    ? ophalen.isPending
      ? "Ophalen…"
      : "Ophalen en lezen"
    : data.resuming
      ? "Lees verder"
      : "Beginnen";
  const waar = [data.number ? `#${data.number}` : null, data.title].filter(Boolean).join(" ");

  return (
    <section className="mt-6 flex flex-wrap items-center gap-3 rounded border border-ink-600 p-4">
      <button
        onClick={() =>
          data.has_file ? navigate(`/lezen/${data.book_id}`) : ophalen.mutate(data.book_id)
        }
        disabled={ophalen.isPending}
        className="rounded bg-accent px-4 py-2 text-sm font-medium text-ink-900 disabled:opacity-50"
      >
        {label}
      </button>
      <span className="min-w-0 flex-1 truncate text-sm text-slate-400">
        {waar}
        {data.resuming && data.page > 0 ? ` · pagina ${data.page + 1}` : ""}
        {ophalen.isError && (
          <span className="ml-2 text-danger">
            {ophalen.error instanceof ApiError ? ophalen.error.message : "Ophalen mislukt."}
          </span>
        )}
      </span>
      {data.unread_before > 0 && (
        <button
          onClick={() => markRead.mutate()}
          disabled={markRead.isPending}
          className="rounded bg-ink-700 px-3 py-2 text-sm text-slate-200 disabled:opacity-50"
          title="Zet alles vóór dit hoofdstuk op gelezen"
        >
          {markRead.isPending
            ? "Bezig…"
            : `Markeer ${data.unread_before} eerdere als gelezen`}
        </button>
      )}
    </section>
  );
}


/**
 * Een gevolgde serie als gewone bestanden in je eigen mappen zetten.
 *
 * Een abonnement houdt hoofdstukken als verwijzing en haalt ze tijdelijk op;
 * na de TTL gaat het bestand weer weg. Prima om bij te blijven, niet wat je
 * wilt voor een serie die je houdt.
 */
function ImportPanel({ series, seriesId }: { series: SeriesDetail; seriesId: number }) {
  const queryClient = useQueryClient();
  const { data: roots } = useQuery({ queryKey: ["libraries"], queryFn: api.libraries });
  const [rootId, setRootId] = useState<number | null>(null);
  const [result, setResult] = useState<string | null>(null);

  const doImport = useMutation({
    mutationFn: () => api.importSeries(seriesId, { root_id: rootId! }),
    onSuccess: (report) => {
      setResult(
        `${report.moved} verplaatst, ${report.downloaded} opgehaald, ` +
          `${report.skipped} overgeslagen.` +
          (report.errors.length ? ` Fouten: ${report.errors.slice(0, 3).join("; ")}` : ""),
      );
      void queryClient.invalidateQueries({ queryKey: ["series-detail", seriesId] });
    },
    onError: (error: unknown) =>
      setResult(error instanceof ApiError ? error.message : "Importeren mislukt."),
  });

  // De downloadmap is waar gevolgde hoofdstukken nu al staan; die aanbieden als
  // doel zou niets verplaatsen.
  const doelen = (roots ?? []).filter((root) => root.id !== series.library_root_id);

  return (
    <section className="mt-4 rounded border border-ink-600 p-4">
      <h2 className="text-sm font-medium text-slate-200">Importeren naar je bibliotheek</h2>
      <p className="mt-1 text-xs text-slate-500">
        Zet alle hoofdstukken als gewone bestanden in een van je eigen mappen, in een submap op
        serienaam. Daarna verdwijnen ze niet meer door de TTL en lees je ze ook als de bron
        onbereikbaar is. Wat er al staat wordt nooit overschreven.
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <select
          value={rootId ?? ""}
          onChange={(event) => setRootId(Number(event.target.value) || null)}
          className="rounded bg-ink-700 px-3 py-2 text-sm text-slate-100"
        >
          <option value="">Kies een map…</option>
          {doelen.map((root) => (
            <option key={root.id} value={root.id}>
              {root.name} ({root.path})
            </option>
          ))}
        </select>
        <button
          onClick={() => doImport.mutate()}
          disabled={!rootId || doImport.isPending}
          className="rounded bg-accent px-4 py-2 text-sm text-ink-900 disabled:opacity-50"
        >
          {doImport.isPending ? "Bezig… (dit kan lang duren)" : "Importeren"}
        </button>
      </div>

      {result && <p className="mt-2 text-xs text-slate-400">{result}</p>}
    </section>
  );
}
