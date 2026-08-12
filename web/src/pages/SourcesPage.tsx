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
export function SourcesPage() {
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

  const addSource = useMutation({
    mutationFn: (type: string) => api.addSource({ type, name: type }),
    onSuccess: refresh,
    onError: (error: unknown) =>
      setMessage(error instanceof ApiError ? error.message : "Toevoegen mislukt."),
  });

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
    <div className="mx-auto max-w-3xl px-4 py-6">
      <Link to="/" className="text-sm text-slate-400 hover:text-slate-200">
        ← Bibliotheek
      </Link>
      <h1 className="mt-4 text-2xl font-semibold text-slate-100">Bronnen</h1>
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
          {sources?.length === 0 && (
            <div className="flex flex-wrap gap-2">
              {types?.map((type) => (
                <button
                  key={type}
                  onClick={() => addSource.mutate(type)}
                  className="rounded bg-accent px-3 py-1.5 text-sm text-ink-900"
                >
                  {type} toevoegen
                </button>
              ))}
            </div>
          )}
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
    queryKey: ["source-search", sourceId, submitted],
    queryFn: () => api.searchSource(sourceId, submitted),
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
            <div className="min-w-0 flex-1">
              <p className="truncate text-slate-100">{hit.title}</p>
              <p className="text-xs text-slate-500">
                {[hit.year, hit.status, hit.original_language].filter(Boolean).join(" · ")}
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
