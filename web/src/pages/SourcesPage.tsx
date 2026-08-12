import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { SearchHit, SubscriptionPolicy, SubscriptionRow } from "../api/types";

/**
 * Talen waarin je een reeks kunt volgen.
 *
 * Meerdere naast elkaar is een geldige wens en geen vergissing: van sommige
 * series is maar een klein deel vertaald, en dan wil je het origineel eronder
 * om verder te kunnen lezen — met de vertaalknop erbij. Ze worden uitgaven van
 * één serie, geen aparte series.
 */
const TAALNAMEN: Record<string, string> = {
  en: "Engels",
  ja: "Japans",
  nl: "Nederlands",
  de: "Duits",
  fr: "Frans",
  es: "Spaans",
  ko: "Koreaans",
  zh: "Chinees",
};

const TALEN: [string, string][] = [
  ["en", "Engels"],
  ["ja", "Japans"],
  ["nl", "Nederlands"],
  ["de", "Duits"],
  ["fr", "Frans"],
  ["es", "Spaans"],
  ["ko", "Koreaans"],
  ["zh", "Chinees"],
];

/**
 * Bronnen: zoeken, volgen en zien wat er binnen is (M5).
 *
 * Een gevolgd hoofdstuk is eerst alleen een verwijzing; pas het ophalen zet er
 * een bestand bij. Daarom toont de abonnementenlijst "lokaal van totaal" — dat
 * is precies het verschil dat je wilt kunnen zien.
 */
/** ``embedded`` laat de eigen kop en terugknop weg: in de instellingen staat
 * die er al, en twee keer "← Bibliotheek" onder elkaar is verwarrend. */
export function SourcesPage({ embedded = false }: { embedded?: boolean } = {}) {
  const queryClient = useQueryClient();
  const { data: sources } = useQuery({ queryKey: ["sources"], queryFn: api.sources });
  const { data: types } = useQuery({ queryKey: ["source-types"], queryFn: api.sourceTypes });
  const { data: subscriptions } = useQuery({
    queryKey: ["subscriptions"],
    queryFn: api.subscriptions,
  });

  const [message, setMessage] = useState<string | null>(null);

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ["sources"] });
    void queryClient.invalidateQueries({ queryKey: ["subscriptions"] });
    void queryClient.invalidateQueries({ queryKey: ["series"] });
  }

  const runNow = useMutation({
    mutationFn: api.runSources,
    onSuccess: (report) => {
      setMessage(
        `Ronde klaar: ${report.chapters_added} nieuwe hoofdstukken, ` +
          `${report.downloaded} opgehaald, ${report.expired} verlopen.` +
          (report.errors.length ? ` Fouten: ${report.errors.join("; ")}` : ""),
      );
      refresh();
    },
    onError: () => setMessage("De ronde is mislukt."),
  });

  const activeSource = sources?.[0];

  return (
    <div className={embedded ? "" : "mx-auto max-w-3xl px-4 py-6"}>
      {!embedded && (
        <>
          <Link to="/" className="text-sm text-slate-400 hover:text-slate-200">
            ← Bibliotheek
          </Link>
          <h1 className="mt-4 text-2xl font-semibold text-slate-100">Bronnen</h1>
        </>
      )}
      <p className="mt-1 text-sm text-slate-500">
        Series volgen bij een externe bron. Hoofdstukken verschijnen eerst als
        verwijzing; wat je ophaalt komt in je bibliotheek te staan en leest verder
        als elk ander bestand.
      </p>

      <section className="mt-6 rounded border border-ink-600 p-4">
        <h2 className="font-medium text-slate-200">Ingestelde bronnen</h2>
        <div className="mt-3 space-y-2">
          {sources?.map((source) => (
            <div key={source.id} className="flex items-center gap-3 rounded bg-ink-800 p-3">
              <div className="min-w-0 flex-1">
                <p className="truncate text-slate-100">{source.name}</p>
                <p className="text-xs text-slate-500">{source.type}</p>
              </div>
              <button
                onClick={() => {
                  void api.deleteSource(source.id).then(refresh);
                }}
                className="rounded bg-ink-700 px-3 py-1.5 text-sm text-slate-300"
              >
                Verwijderen
              </button>
            </div>
          ))}
          <AddSource types={types ?? []} onAdded={refresh} setMessage={setMessage} />
        </div>
      </section>

      {activeSource && <SearchPanel sourceId={activeSource.id} onChanged={refresh} />}

      <section className="mt-6 rounded border border-ink-600 p-4">
        <div className="flex items-center justify-between">
          <h2 className="font-medium text-slate-200">Wat je volgt</h2>
          <button
            onClick={() => runNow.mutate()}
            disabled={runNow.isPending}
            className="rounded bg-ink-700 px-3 py-1.5 text-sm text-slate-200 disabled:opacity-50"
            title="Nieuwe hoofdstukken zoeken en vooruitlezen ophalen"
          >
            {runNow.isPending ? "Bezig…" : "Nu bijwerken"}
          </button>
        </div>
        <div className="mt-3 space-y-2">
          {subscriptions?.map((subscription) => (
            <SubscriptionRowView
              key={subscription.id}
              subscription={subscription}
              onChanged={refresh}
            />
          ))}
          {subscriptions?.length === 0 && (
            <p className="text-sm text-slate-500">Je volgt nog niets.</p>
          )}
        </div>
      </section>

      {message && (
        <p className="mt-4 rounded bg-ink-800 p-3 text-sm text-slate-300">{message}</p>
      )}
    </div>
  );
}

function SearchPanel({ sourceId, onChanged }: { sourceId: number; onChanged: () => void }) {
  // Vanaf je MyAnimeList-lijst kom je hier binnen met een titel al ingevuld,
  // zodat "zoek bij bron" één klik is in plaats van overtypen.
  const [params] = useSearchParams();
  const vooraf = params.get("zoek") ?? "";
  const [query, setQuery] = useState(vooraf);
  const [submitted, setSubmitted] = useState(vooraf);
  const [policy, setPolicy] = useState<SubscriptionPolicy>("readahead");
  // In welke taal je de reeks volgt. Je kunt er meerdere naast elkaar hebben:
  // van sommige series is maar een klein deel vertaald, en dan wil je het
  // origineel eronder om verder te kunnen lezen (met de vertaalknop erbij).
  const [language, setLanguage] = useState("en");

  const { data, isFetching, error } = useQuery({
    queryKey: ["source-search", sourceId, submitted, language],
    // De taal filtert bij de bron: anders krijg je tien treffers terug waarvan
    // er twee in jouw taal bestaan, en dat zie je pas na het volgen.
    queryFn: () => api.searchSource(sourceId, submitted, language || undefined),
    enabled: submitted.length > 0,
  });

  const subscribe = useMutation({
    mutationFn: (hit: SearchHit) => api.subscribe(sourceId, { ref: hit.ref, policy, language }),
    onSuccess: onChanged,
  });

  return (
    <section className="mt-6 rounded border border-ink-600 p-4">
      <h2 className="font-medium text-slate-200">Zoeken</h2>
      <form
        className="mt-3 flex flex-wrap gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          setSubmitted(query.trim());
        }}
      >
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Titel van een serie…"
          className="min-w-0 flex-1 rounded bg-ink-700 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500"
        />
        <select
          value={language}
          onChange={(event) => setLanguage(event.target.value)}
          className="rounded bg-ink-700 px-3 py-2 text-sm text-slate-100"
          title="Je kunt dezelfde reeks in meerdere talen volgen; ze worden uitgaven van één serie"
        >
          {/* Leeg = alles: soms wil je gewoon zien wat er bestaat, en pas
              daarna kiezen in welke taal je het volgt. */}
          <option value="">Alle talen</option>
          {TALEN.map(([code, label]) => (
            <option key={code} value={code}>
              {label}
            </option>
          ))}
        </select>
        <select
          value={policy}
          onChange={(event) => setPolicy(event.target.value as SubscriptionPolicy)}
          className="rounded bg-ink-700 px-3 py-2 text-sm text-slate-100"
          title="Permanent bewaart wat je ophaalt; vooruitlezen ruimt het na de TTL weer op"
        >
          <option value="readahead">Vooruitlezen (tijdelijk)</option>
          <option value="permanent">Permanent bewaren</option>
        </select>
        <button type="submit" className="rounded bg-accent px-4 py-2 text-sm text-ink-900">
          Zoeken
        </button>
      </form>

      {isFetching && <p className="mt-3 text-sm text-slate-400">Zoeken…</p>}
      {error && (
        <p className="mt-3 text-sm text-danger">
          {error instanceof ApiError ? error.message : "Zoeken mislukt."}
        </p>
      )}

      <div className="mt-3 space-y-2">
        {data?.map((hit) => (
          <div key={hit.ref} className="flex items-start gap-3 rounded bg-ink-800 p-3">
            {/* Zonder omslag is een titel alleen niet genoeg om te beoordelen
                of dit de reeks is die je zoekt. */}
            {hit.cover_url && (
              <img
                src={hit.cover_url}
                alt=""
                loading="lazy"
                className="h-24 w-16 shrink-0 rounded object-cover"
                onError={(event) => {
                  event.currentTarget.style.display = "none";
                }}
              />
            )}
            <div className="min-w-0 flex-1">
              <p className="truncate text-slate-100">{hit.title}</p>
              <p className="text-xs text-slate-500">
                {[
                  hit.year,
                  hit.status,
                  hit.original_language,
                  hit.languages.length ? hit.languages.slice(0, 6).join(" ") : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
              <p className="text-xs text-slate-500">
                <ChapterCount sourceId={sourceId} refId={hit.ref} language={language || "en"} />
                {hit.url && (
                  <>
                    {" · "}
                    <a
                      href={hit.url}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="underline hover:text-slate-300"
                    >
                      bij de bron bekijken
                    </a>
                  </>
                )}
              </p>
              {/* Je hebt hier al iets van staan onder een net andere titel.
                  Dan voeg je een bron toe aan wat je hebt, en maak je geen
                  tweede serie — dat hoor je te zien vóór je op volgen drukt. */}
              {hit.existing_series_id && (
                <p className="mt-1 text-xs text-accent">
                  Wordt een uitgave van «{hit.existing_series_title}»
                </p>
              )}
            </div>
            {hit.subscribed_series_id ? (
              <>
                <Link
                  to={`/serie/${hit.subscribed_series_id}`}
                  className="rounded bg-ink-700 px-3 py-1.5 text-sm text-slate-300"
                >
                  Volg je al
                </Link>
                {/* Nog een taal erbij: die wordt een tweede uitgave van
                    dezelfde serie, niet een tweede serie. */}
                <button
                  onClick={() => subscribe.mutate(hit)}
                  disabled={subscribe.isPending}
                  className="rounded bg-ink-700 px-3 py-1.5 text-sm text-slate-300 disabled:opacity-50"
                  title="Volg deze reeks ook in de gekozen taal"
                >
                  + {language}
                </button>
              </>
            ) : (
              <button
                onClick={() => subscribe.mutate(hit)}
                disabled={subscribe.isPending}
                className="rounded bg-accent px-3 py-1.5 text-sm text-ink-900 disabled:opacity-50"
              >
                {hit.existing_series_id ? "Bron toevoegen" : "Volgen"}
              </button>
            )}
          </div>
        ))}
        {data?.length === 0 && submitted && (
          <p className="text-sm text-slate-500">Niets gevonden.</p>
        )}
      </div>
    </section>
  );
}

function SubscriptionRowView({
  subscription,
  onChanged,
}: {
  subscription: SubscriptionRow;
  onChanged: () => void;
}) {
  const refresh = useMutation({
    mutationFn: () => api.refreshSubscription(subscription.id),
    onSuccess: onChanged,
  });
  const remove = useMutation({
    mutationFn: () => api.unsubscribe(subscription.id),
    onSuccess: onChanged,
  });

  return (
    <div className="flex flex-wrap items-center gap-3 rounded bg-ink-800 p-3">
      <div className="min-w-0 flex-1">
        <Link
          to={`/serie/${subscription.series_id}`}
          className="block truncate text-slate-100 hover:text-accent"
        >
          {subscription.series_title}
          {/* Welke reeks bij de bron, en in welke taal. Bij een serie met
              meerdere abonnementen is dát het verschil — de serietitel is voor
              alle drie dezelfde. */}
          {subscription.source_title && subscription.source_title !== subscription.series_title && (
            <span className="text-slate-400"> ({subscription.source_title})</span>
          )}
          <span className="ml-2 text-xs text-slate-500">
            {TAALNAMEN[subscription.language] ?? subscription.language}
          </span>
        </Link>
        <p className="text-xs text-slate-500">
          {subscription.chapters_local} van {subscription.chapters_total} lokaal ·{" "}
          {subscription.policy === "readahead"
            ? `${subscription.readahead_n} vooruit, ${subscription.ttl_days} dagen bewaren`
            : "permanent"}
        </p>
      </div>
      <button
        onClick={() => refresh.mutate()}
        disabled={refresh.isPending}
        className="rounded bg-ink-700 px-3 py-1.5 text-sm text-slate-200 disabled:opacity-50"
      >
        {refresh.isPending ? "…" : "Bijwerken"}
      </button>
      <button
        onClick={() => remove.mutate()}
        className="rounded bg-ink-700 px-3 py-1.5 text-sm text-slate-300"
        title="De al opgehaalde hoofdstukken blijven staan"
      >
        Ontvolgen
      </button>
    </div>
  );
}


/**
 * Hoeveel hoofdstukken deze reeks in deze taal heeft.
 *
 * Apart opgehaald en niet in het zoekresultaat: het kost een verzoek per
 * treffer, en dat hoort het zoeken zelf niet trager te maken. Zo verschijnt het
 * getal na een tel terwijl de lijst er meteen staat.
 */
function ChapterCount({
  sourceId,
  refId,
  language,
}: {
  sourceId: number;
  refId: string;
  language: string;
}) {
  const { data, isLoading } = useQuery({
    queryKey: ["chapter-count", sourceId, refId, language],
    queryFn: () => api.chapterCount(sourceId, refId, language),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  if (isLoading) return <span className="text-slate-600">tellen…</span>;
  if (!data) return <span className="text-slate-600">aantal onbekend</span>;
  return (
    <span>
      {data.count} {data.count === 1 ? "hoofdstuk" : "hoofdstukken"} in {language}
    </span>
  );
}


/**
 * Een bron erbij.
 *
 * MangaDex en Internet Archive hebben niets nodig — die kennen hun eigen adres.
 * OPDS wel: dat is juist de bron waar jij een catalogus in zet. Kavita, Komga,
 * Calibre-web, Standard Ebooks en BookPal zelf spreken het allemaal, dus één
 * adres invullen is genoeg.
 */
function AddSource({
  types,
  onAdded,
  setMessage,
}: {
  types: string[];
  onAdded: () => void;
  setMessage: (bericht: string | null) => void;
}) {
  const [type, setType] = useState("opds");
  const [naam, setNaam] = useState("");
  const [url, setUrl] = useState("");
  const [gebruiker, setGebruiker] = useState("");
  const [wachtwoord, setWachtwoord] = useState("");

  const toevoegen = useMutation({
    mutationFn: () =>
      api.addSource({
        type,
        name: naam.trim() || type,
        config:
          type === "opds"
            ? {
                url: url.trim(),
                ...(gebruiker ? { username: gebruiker, password: wachtwoord } : {}),
              }
            : {},
      }),
    onSuccess: () => {
      setMessage(null);
      setNaam("");
      setUrl("");
      setGebruiker("");
      setWachtwoord("");
      onAdded();
    },
    onError: (fout: unknown) =>
      setMessage(fout instanceof ApiError ? fout.message : "Bron toevoegen mislukt."),
  });

  const heeftAdres = type !== "opds" || url.trim().length > 0;

  return (
    <form
      className="mt-3 border-t border-ink-700 pt-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (heeftAdres) toevoegen.mutate();
      }}
    >
      <p className="mb-2 text-sm text-slate-300">Bron toevoegen</p>
      <div className="flex flex-wrap gap-2">
        <select
          value={type}
          onChange={(event) => setType(event.target.value)}
          className="rounded bg-ink-700 px-3 py-2 text-sm text-slate-100"
        >
          {types.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>
        <input
          value={naam}
          onChange={(event) => setNaam(event.target.value)}
          placeholder="Naam (optioneel)"
          className="w-40 rounded bg-ink-700 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500"
        />
        {type === "opds" && (
          <input
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://… /opds"
            className="min-w-0 flex-1 rounded bg-ink-700 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500"
          />
        )}
        <button
          type="submit"
          disabled={toevoegen.isPending || !heeftAdres}
          className="rounded bg-accent px-4 py-2 text-sm text-ink-900 disabled:opacity-50"
        >
          {toevoegen.isPending ? "Proberen…" : "Toevoegen"}
        </button>
      </div>

      {type === "opds" && (
        <>
          <div className="mt-2 flex flex-wrap gap-2">
            <input
              value={gebruiker}
              onChange={(event) => setGebruiker(event.target.value)}
              placeholder="Gebruikersnaam (alleen als de catalogus erom vraagt)"
              className="min-w-0 flex-1 rounded bg-ink-700 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500"
            />
            <input
              value={wachtwoord}
              onChange={(event) => setWachtwoord(event.target.value)}
              type="password"
              placeholder="Wachtwoord"
              className="w-48 rounded bg-ink-700 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500"
            />
          </div>
          <p className="mt-1 text-xs text-slate-500">
            Het adres wordt meteen geprobeerd; klopt het niet, dan hoor je dat nu in plaats
            van pas als je gaat zoeken.
          </p>
        </>
      )}
    </form>
  );
}
