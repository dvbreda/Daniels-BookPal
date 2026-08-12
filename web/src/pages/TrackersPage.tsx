import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { ShelfRow, TrackerAccountRow } from "../api/types";

/**
 * Trackers: MyAnimeList koppelen en pushen, Goodreads als CSV-export (M7).
 *
 * Eenrichtingsverkeer — BookPal leest hier nooit iets terug, dus er is geen
 * conflict om op te lossen. Een nieuw account staat standaard op dry-run: de
 * gedebouncede trigger na elke voortgangsupdate is daardoor onschadelijk
 * totdat je bewust "dry-run uit" zet.
 */
const MAL_TERUG: Record<string, string> = {
  gekoppeld: "MyAnimeList is gekoppeld.",
  mislukt: "Koppelen met MyAnimeList is niet gelukt. Klopt de redirect-URL in je app-registratie?",
  onbekend: "De terugkeer van MyAnimeList hoorde bij geen enkele koppelpoging; probeer opnieuw.",
};

export function TrackersPage() {
  const queryClient = useQueryClient();
  const { data: trackers } = useQuery({ queryKey: ["trackers"], queryFn: api.trackers });
  const [params, setParams] = useSearchParams();
  // MyAnimeList stuurt je hierheen terug met de uitkomst in de URL.
  const [message, setMessage] = useState<string | null>(
    MAL_TERUG[params.get("mal") ?? ""] ?? null,
  );

  useEffect(() => {
    if (params.has("mal")) {
      params.delete("mal");
      setParams(params, { replace: true });
    }
  }, [params, setParams]);

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ["trackers"] });
  }

  const mal = trackers?.find((t) => t.provider === "mal");

  const addMal = useMutation({
    mutationFn: (body: { client_id: string; client_secret: string }) =>
      api.addTracker({ provider: "mal", ...body }),
    onSuccess: refresh,
    onError: (error: unknown) =>
      setMessage(error instanceof ApiError ? error.message : "Toevoegen mislukt."),
  });

  return (
    <div className="mx-auto max-w-3xl px-4 py-6">
      <Link to="/" className="text-sm text-slate-400 hover:text-slate-200">
        ← Bibliotheek
      </Link>
      <h1 className="mt-4 text-2xl font-semibold text-slate-100">Trackers</h1>
      <p className="mt-1 text-sm text-slate-500">
        Leesvoortgang eenrichtingsverkeer naar buiten sturen. BookPal leest hier
        nooit iets terug — bij twijfel push je gewoon opnieuw.
      </p>

      <section className="mt-6 rounded border border-ink-600 p-4">
        <h2 className="font-medium text-slate-200">MyAnimeList</h2>
        {mal ? (
          <MalAccount account={mal} onChanged={refresh} setMessage={setMessage} />
        ) : (
          <MalSetupForm
            onSubmit={(body) => addMal.mutate(body)}
            pending={addMal.isPending}
          />
        )}
      </section>

      <GoodreadsPanel setMessage={setMessage} />

      {mal?.connected && <MalListPanel accountId={mal.id} setMessage={setMessage} />}

      <ShelvesPanel />

      {message && (
        <p className="mt-4 rounded bg-ink-800 p-3 text-sm text-slate-300">{message}</p>
      )}
    </div>
  );
}

function MalSetupForm({
  onSubmit,
  pending,
}: {
  onSubmit: (body: { client_id: string; client_secret: string }) => void;
  pending: boolean;
}) {
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");

  return (
    <form
      className="mt-3 space-y-3"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit({ client_id: clientId.trim(), client_secret: clientSecret.trim() });
      }}
    >
      <p className="text-sm text-slate-500">
        Registreer eerst een eigen app op{" "}
        <span className="text-slate-400">myanimelist.net/apiconfig</span> en plak
        hier de client-gegevens.
      </p>
      <input
        value={clientId}
        onChange={(event) => setClientId(event.target.value)}
        placeholder="Client ID"
        className="w-full rounded bg-ink-700 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500"
      />
      <input
        value={clientSecret}
        onChange={(event) => setClientSecret(event.target.value)}
        placeholder="Client secret"
        type="password"
        className="w-full rounded bg-ink-700 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500"
      />
      <button
        type="submit"
        disabled={pending || !clientId.trim() || !clientSecret.trim()}
        className="rounded bg-accent px-4 py-2 text-sm text-ink-900 disabled:opacity-50"
      >
        Opslaan
      </button>
    </form>
  );
}

function MalAccount({
  account,
  onChanged,
  setMessage,
}: {
  account: TrackerAccountRow;
  onChanged: () => void;
  setMessage: (message: string | null) => void;
}) {
  // Het terugkeeradres dat in je MAL-app-registratie moet staan. We tonen het
  // pas als je op koppelen drukt, want eerder weet je niet waarvoor het is.
  const [redirectUri, setRedirectUri] = useState<string | null>(null);

  const startAuth = useMutation({
    mutationFn: () => api.malAuthorizeUrl(account.id),
    onSuccess: (result) => {
      setRedirectUri(result.redirect_uri);
      // Zelfde tabblad: MyAnimeList stuurt je hierna vanzelf terug, dus een
      // tweede tabblad zou je alleen maar achterlaten op een lege pagina.
      window.location.href = result.url;
    },
    onError: (error: unknown) =>
      setMessage(error instanceof ApiError ? error.message : "Kon geen autorisatie-URL ophalen."),
  });

  const toggle = useMutation({
    mutationFn: (body: { enabled?: boolean; dry_run?: boolean }) =>
      api.updateTracker(account.id, body),
    onSuccess: onChanged,
  });

  const remove = useMutation({
    mutationFn: () => api.deleteTracker(account.id),
    onSuccess: onChanged,
  });

  const runNow = useMutation({
    mutationFn: () => api.runTracker(account.id),
    onSuccess: (report) => {
      setMessage(
        `${report.pushed} gepusht van ${report.results.length}.` +
          (report.errors.length ? ` Fouten: ${report.errors.join("; ")}` : ""),
      );
    },
    onError: (error: unknown) =>
      setMessage(error instanceof ApiError ? error.message : "Pushen mislukt."),
  });

  return (
    <div className="mt-3 space-y-3">
      <div className="flex flex-wrap items-center gap-3 rounded bg-ink-800 p-3">
        <div className="min-w-0 flex-1">
          <p className="text-slate-100">
            {account.connected ? "Gekoppeld" : "Nog niet gekoppeld"}
          </p>
          <p className="text-xs text-slate-500">
            {account.last_sync_at
              ? `Laatst gepusht: ${new Date(account.last_sync_at).toLocaleString("nl-NL")}`
              : "Nog niet gepusht"}
          </p>
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-300">
          <input
            type="checkbox"
            checked={account.enabled}
            onChange={(event) => toggle.mutate({ enabled: event.target.checked })}
          />
          Actief
        </label>
        <label
          className="flex items-center gap-2 text-sm text-slate-300"
          title="Dry-run rapporteert alleen wat er zou gebeuren, zonder echt te pushen"
        >
          <input
            type="checkbox"
            checked={account.dry_run}
            onChange={(event) => toggle.mutate({ dry_run: event.target.checked })}
          />
          Dry-run
        </label>
        <button
          onClick={() => remove.mutate()}
          className="rounded bg-ink-700 px-3 py-1.5 text-sm text-slate-300"
        >
          Verwijderen
        </button>
      </div>

      {!account.connected && (
        <div className="space-y-2 rounded bg-ink-800 p-3">
          <p className="text-sm text-slate-400">
            Je logt in op MyAnimeList zelf; BookPal ziet je wachtwoord nooit. Zet in je
            app-registratie op{" "}
            <span className="text-slate-300">myanimelist.net/apiconfig</span> dit adres als
            redirect-URL:
          </p>
          <code className="block break-all rounded bg-ink-900 p-2 text-xs text-slate-300">
            {redirectUri ?? `${window.location.origin}/api/trackers/mal/redirect`}
          </code>
          <button
            onClick={() => startAuth.mutate()}
            disabled={startAuth.isPending}
            className="rounded bg-accent px-3 py-1.5 text-sm text-ink-900 disabled:opacity-50"
          >
            {startAuth.isPending ? "Bezig…" : "Inloggen bij MyAnimeList"}
          </button>
        </div>
      )}

      {account.connected && (
        <button
          onClick={() => runNow.mutate()}
          disabled={runNow.isPending || !account.enabled}
          className="rounded bg-ink-700 px-3 py-1.5 text-sm text-slate-200 disabled:opacity-50"
          title={account.enabled ? "" : "Zet dit account eerst op actief"}
        >
          {runNow.isPending ? "Bezig…" : "Nu pushen"}
        </button>
      )}
    </div>
  );
}


/**
 * Goodreads koppelen via een echte browser.
 *
 * Hun API is dood sinds eind 2020 en de inlog loopt via Amazon; er bestaat ook
 * geen derde-partij-API die kán schrijven. Dit is dus de enige weg, en meteen
 * de breekbaarste koppeling in de app — vandaar dat er eerlijk bij staat wat
 * de risico's zijn in plaats van dat het als "gewoon inloggen" wordt gebracht.
 */
function GoodreadsPanel({ setMessage }: { setMessage: (message: string | null) => void }) {
  const queryClient = useQueryClient();
  const { data: status } = useQuery({
    queryKey: ["goodreads-status"],
    queryFn: api.goodreadsStatus,
  });
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ["goodreads-status"] });
  }

  const installBrowser = useMutation({
    mutationFn: api.goodreadsInstallBrowser,
    onSuccess: refresh,
    onError: (error: unknown) =>
      setMessage(error instanceof ApiError ? error.message : "Browser downloaden mislukt."),
  });

  const login = useMutation({
    mutationFn: () => api.goodreadsLogin(email.trim(), password),
    onSuccess: () => {
      setPassword("");
      setMessage("Ingelogd bij Goodreads.");
      refresh();
    },
    onError: (error: unknown) =>
      setMessage(error instanceof ApiError ? error.message : "Inloggen mislukt."),
  });

  const logout = useMutation({
    mutationFn: api.goodreadsLogout,
    onSuccess: refresh,
  });

  const sync = useMutation({
    mutationFn: api.goodreadsSync,
    onSuccess: (result) => {
      setMessage(
        `${result.updated.length} boeken bijgewerkt op Goodreads.` +
          (result.errors.length ? ` Niet gelukt: ${result.errors.slice(0, 3).join("; ")}` : ""),
      );
      refresh();
    },
    onError: (error: unknown) =>
      setMessage(error instanceof ApiError ? error.message : "Synchroniseren mislukt."),
  });

  return (
    <section className="mt-6 rounded border border-ink-600 p-4">
      <h2 className="font-medium text-slate-200">Goodreads</h2>

      {!status?.browser_ready ? (
        <div className="mt-2 space-y-2">
          <p className="text-sm text-slate-500">
            Goodreads heeft geen API meer en logt in via Amazon, dus hiervoor stuurt BookPal een
            echte browser aan. Die wordt pas gedownload als je hem nodig hebt (~170 MB, één keer).
          </p>
          <button
            onClick={() => installBrowser.mutate()}
            disabled={installBrowser.isPending}
            className="rounded bg-ink-700 px-3 py-1.5 text-sm text-slate-200 disabled:opacity-50"
          >
            {installBrowser.isPending ? "Downloaden… (kan een minuut duren)" : "Browser ophalen"}
          </button>
        </div>
      ) : status.connected ? (
        <div className="mt-2 space-y-2">
          <p className="text-sm text-slate-300">
            Ingelogd.
            {status.last_sync_at
              ? ` Laatst bijgewerkt: ${new Date(status.last_sync_at).toLocaleString("nl-NL")}`
              : " Nog niet bijgewerkt."}
          </p>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => sync.mutate()}
              disabled={sync.isPending}
              className="rounded bg-accent px-3 py-1.5 text-sm text-ink-900 disabled:opacity-50"
            >
              {sync.isPending ? "Bezig… (dit duurt even)" : "Planken bijwerken"}
            </button>
            <button
              onClick={() => logout.mutate()}
              className="rounded bg-ink-700 px-3 py-1.5 text-sm text-slate-300"
            >
              Uitloggen
            </button>
          </div>
        </div>
      ) : (
        <form
          className="mt-2 space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            login.mutate();
          }}
        >
          <p className="text-sm text-slate-500">
            BookPal logt namens jou in op Goodreads. Twee dingen om te weten: je wachtwoord wordt
            gebruikt om in te loggen en daarna <strong>niet</strong> bewaard (alleen de sessie),
            en Amazon kan geautomatiseerd inloggen als verdacht aanmerken. Vraagt Amazon om een
            CAPTCHA of code, dan stopt BookPal en krijg jij die vraag te zien.
          </p>
          <input
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="E-mailadres"
            type="email"
            autoComplete="username"
            className="w-full rounded bg-ink-700 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500"
          />
          <input
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="Wachtwoord"
            type="password"
            autoComplete="current-password"
            className="w-full rounded bg-ink-700 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500"
          />
          <button
            type="submit"
            disabled={login.isPending || !email.trim() || !password}
            className="rounded bg-accent px-4 py-2 text-sm text-ink-900 disabled:opacity-50"
          >
            {login.isPending ? "Inloggen… (dit duurt even)" : "Inloggen bij Goodreads"}
          </button>
        </form>
      )}

      <p className="mt-3 border-t border-ink-700 pt-3 text-xs text-slate-500">
        Werkt het inloggen niet? De CSV blijft de betrouwbare weg — die laad je in bij My Books →
        Import and Export.{" "}
        <a href={api.goodreadsExportUrl()} download className="text-accent underline">
          CSV downloaden
        </a>
      </p>
    </section>
  );
}


const PLANK_TITELS: Record<string, string> = {
  reading: "Aan het lezen",
  to_read: "Wil ik lezen",
  read: "Uitgelezen",
};

/**
 * Wat er op je leeslijsten zou staan.
 *
 * Dezelfde afleiding als de export gebruikt, dus dit is precies wat er de deur
 * uit gaat — je kunt hier controleren of de leesstatus klopt vóór je iets
 * pusht, in plaats van het bij de tracker te ontdekken.
 */
function ShelvesPanel() {
  const [provider, setProvider] = useState<"goodreads" | "mal">("goodreads");
  const { data } = useQuery({
    queryKey: ["shelves", provider],
    queryFn: () => api.shelves(provider),
  });
  const [open, setOpen] = useState<string>("reading");

  if (!data) return null;

  const planken: [string, ShelfRow[]][] = [
    ["reading", data.reading],
    ["to_read", data.to_read],
    ["read", data.read],
  ];

  return (
    <section className="mt-6 rounded border border-ink-600 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="font-medium text-slate-200">Je leeslijsten</h2>
        <div className="ml-auto flex gap-1">
          {(["goodreads", "mal"] as const).map((key) => (
            <button
              key={key}
              onClick={() => setProvider(key)}
              className={`rounded px-2 py-1 text-xs ${
                provider === key ? "bg-accent text-ink-900" : "bg-ink-700 text-slate-300"
              }`}
            >
              {key === "mal" ? "MyAnimeList" : "Goodreads"}
            </button>
          ))}
        </div>
      </div>
      <p className="mt-1 text-xs text-slate-500">
        Afgeleid uit je voortgang, precies zoals het naar deze tracker gaat.
        {data.without_id > 0 &&
          ` ${data.without_id} ${data.without_id === 1 ? "serie heeft" : "series hebben"} ` +
            "geen MyAnimeList-id en wordt overgeslagen; koppel er een omslag van een bron aan " +
            "om die op te halen."}
      </p>

      <div className="mt-3 flex flex-wrap gap-2">
        {planken.map(([key, rows]) => (
          <button
            key={key}
            onClick={() => setOpen(key)}
            className={`rounded px-3 py-1.5 text-sm ${
              open === key ? "bg-accent text-ink-900" : "bg-ink-700 text-slate-300"
            }`}
          >
            {PLANK_TITELS[key]} ({rows.length})
          </button>
        ))}
      </div>

      <ul className="mt-3 space-y-1">
        {(planken.find(([key]) => key === open)?.[1] ?? []).map((row) => (
          <li key={row.series_id}>
            <Link
              to={`/serie/${row.series_id}`}
              className="flex flex-wrap items-baseline gap-2 rounded bg-ink-800 px-3 py-2 hover:bg-ink-700"
            >
              <span className="min-w-0 flex-1 truncate text-sm text-slate-100">
                {row.title}
                {!row.pushable && (
                  <span className="ml-2 text-xs text-warning" title="Geen id bij deze tracker">
                    geen id
                  </span>
                )}
              </span>
              {row.author && (
                <span className="truncate text-xs text-slate-500">{row.author}</span>
              )}
              {row.chapters_total > 0 && (
                <span className="tabular-nums text-xs text-slate-400">
                  {row.chapters_read}/{row.chapters_total}
                  {row.percent > 0 && ` · ${Math.round(row.percent)}%`}
                </span>
              )}
            </Link>
          </li>
        ))}
        {(planken.find(([key]) => key === open)?.[1] ?? []).length === 0 && (
          <li className="px-3 py-2 text-sm text-slate-500">Niets op deze plank.</li>
        )}
      </ul>
    </section>
  );
}


const MAL_STATUS: Record<string, string> = {
  plan_to_read: "Wil ik lezen",
  reading: "Aan het lezen",
  completed: "Uitgelezen",
  on_hold: "Gepauzeerd",
  dropped: "Gestopt",
};

/**
 * Je eigen MyAnimeList-lijst, om er abonnementen bij te zoeken.
 *
 * De enige plek waar BookPal van een tracker leest. Dat botst niet met het
 * eenrichtingsverkeer: dat gaat over voortgang, en die blijft hier de waarheid.
 * Dit haalt alleen op wát je wilt gaan lezen.
 */
function MalListPanel({
  accountId,
  setMessage,
}: {
  accountId: number;
  setMessage: (message: string | null) => void;
}) {
  const [status, setStatus] = useState("plan_to_read");
  const { data, isFetching, error } = useQuery({
    queryKey: ["mal-list", accountId, status],
    queryFn: () => api.malList(accountId, status),
  });
  const { data: sources } = useQuery({ queryKey: ["sources"], queryFn: api.sources });
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const bron = sources?.[0];

  // Welke regel zijn eigen koppelpaneel open heeft staan.
  const [kiezen, setKiezen] = useState<string | null>(null);

  const overnemen = useMutation({
    mutationFn: (seriesId: number) => api.malImportProgress(accountId, seriesId),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ["series"] });
      setMessage(
        result.marked > 0
          ? `${result.marked} hoofdstukken als gelezen gezet: ${result.series.join(", ")}.`
          : "Je stond hier al even ver of verder.",
      );
    },
    onError: (error: unknown) =>
      setMessage(error instanceof ApiError ? error.message : "Overnemen mislukt."),
  });

  const link = useMutation({
    mutationFn: ({ seriesId, malId }: { seriesId: number; malId: string }) =>
      api.malLink(accountId, seriesId, malId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["mal-list"] });
      void queryClient.invalidateQueries({ queryKey: ["shelves"] });
      setKiezen(null);
      setMessage("Gekoppeld; je voortgang loopt nu mee.");
    },
  });

  return (
    <section className="mt-6 rounded border border-ink-600 p-4">
      <h2 className="font-medium text-slate-200">Je MyAnimeList-lijst</h2>
      <p className="mt-1 text-xs text-slate-500">
        Wat er op je lijst staat, om er een abonnement bij te zoeken.
      </p>

      <div className="mt-3 flex flex-wrap gap-1">
        {Object.entries(MAL_STATUS).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setStatus(key)}
            className={`rounded px-2 py-1 text-xs ${
              status === key ? "bg-accent text-ink-900" : "bg-ink-700 text-slate-300"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {isFetching && <p className="mt-2 text-xs text-slate-500">Ophalen…</p>}
      {error && (
        <p className="mt-2 text-xs text-danger">
          {error instanceof ApiError ? error.message : "Ophalen mislukt."}
        </p>
      )}

      <ul className="mt-3 space-y-1">
        {(data ?? []).map((item) => (
          <li
            key={item.mal_id}
            className="flex flex-wrap items-center gap-2 rounded bg-ink-800 px-3 py-2 text-sm"
          >
            <span className="min-w-0 flex-1 truncate text-slate-100">{item.title}</span>
            {/* MyAnimeList geeft 0 als totaal voor reeksen die nog lopen; het
                aantal staat dan simpelweg niet vast. Dat is geen reden om ook
                te verzwijgen hoe ver jij bent. */}
            {(item.chapters > 0 || item.chapters_read > 0) && (
              <span
                className="tabular-nums text-xs text-slate-500"
                title={item.chapters > 0 ? undefined : "Loopt nog; totaal onbekend"}
              >
                {item.chapters_read}/{item.chapters > 0 ? item.chapters : "?"}
              </span>
            )}
            {item.series_id ? (
              <>
                {item.chapters_read > 0 && (
                  <button
                    onClick={() => overnemen.mutate(item.series_id!)}
                    disabled={overnemen.isPending}
                    className="rounded bg-ink-700 px-2 py-1 text-xs text-slate-300 disabled:opacity-50"
                    title="Zet hier de eerste hoofdstukken als gelezen, tot waar je bij MyAnimeList stond"
                  >
                    Neem {item.chapters_read} over
                  </button>
                )}
                <button
                  onClick={() => navigate(`/serie/${item.series_id}`)}
                  className="rounded bg-ink-700 px-2 py-1 text-xs text-slate-300"
                >
                  In je bibliotheek
                </button>
              </>
            ) : item.match_series_id ? (
              <button
                onClick={() =>
                  link.mutate({ seriesId: item.match_series_id!, malId: item.mal_id })
                }
                disabled={link.isPending}
                className="rounded bg-accent px-2 py-1 text-xs text-ink-900 disabled:opacity-50"
                title={`Koppelen aan "${item.match_title}" in je bibliotheek`}
              >
                Koppelen aan {item.match_title}
              </button>
            ) : (
              <>
                {/* Een titel als "One Piece (Official Colored)" haalt de
                    automatische vergelijking nooit; dan wijs je hem zelf aan. */}
                <button
                  onClick={() => setKiezen(kiezen === item.mal_id ? null : item.mal_id)}
                  className="rounded bg-ink-700 px-2 py-1 text-xs text-slate-300"
                >
                  Zelf koppelen
                </button>
                <button
                  onClick={() => {
                    if (!bron) {
                      setMessage("Voeg eerst een bron toe onder Bronnen.");
                      return;
                    }
                    navigate(`/bronnen?zoek=${encodeURIComponent(item.title)}`);
                  }}
                  className="rounded bg-accent px-2 py-1 text-xs text-ink-900"
                >
                  Zoek bij bron
                </button>
              </>
            )}
            {kiezen === item.mal_id && (
              <SeriesKiezer
                zoek={item.title}
                pending={link.isPending}
                onKies={(seriesId) => link.mutate({ seriesId, malId: item.mal_id })}
              />
            )}
          </li>
        ))}
        {data && data.length === 0 && (
          <li className="px-3 py-2 text-sm text-slate-500">Niets op deze lijst.</li>
        )}
      </ul>
    </section>
  );
}

/**
 * Zelf een serie in je bibliotheek aanwijzen.
 *
 * De automatische vergelijking kijkt naar de titel, en die loopt stuk zodra
 * jouw map een editie noemt: "One Piece (Official Colored)" is voor een
 * computer iets anders dan "One Piece". Beginnen doen we met de titel van de
 * tracker als zoekterm, want daar zit het gemeenschappelijke deel in.
 */
function SeriesKiezer({
  zoek,
  pending,
  onKies,
}: {
  zoek: string;
  pending: boolean;
  onKies: (seriesId: number) => void;
}) {
  const [term, setTerm] = useState(zoek);
  const { data } = useQuery({
    queryKey: ["series", "kiezer", term],
    queryFn: () => api.series({ search: term, limit: 8 }),
  });

  return (
    <div className="mt-2 w-full rounded bg-ink-900 p-2">
      <input
        value={term}
        onChange={(event) => setTerm(event.target.value)}
        placeholder="Zoek in je bibliotheek"
        className="w-full rounded bg-ink-700 px-2 py-1 text-xs text-slate-100 placeholder:text-slate-500"
      />
      <ul className="mt-1 space-y-1">
        {(data?.items ?? []).map((series) => (
          <li key={series.id}>
            <button
              onClick={() => onKies(series.id)}
              disabled={pending}
              className="w-full truncate rounded px-2 py-1 text-left text-xs text-slate-300 hover:bg-ink-700 disabled:opacity-50"
            >
              {series.title}
            </button>
          </li>
        ))}
        {data && data.items.length === 0 && (
          <li className="px-2 py-1 text-xs text-slate-500">Niets gevonden.</li>
        )}
      </ul>
    </div>
  );
}
