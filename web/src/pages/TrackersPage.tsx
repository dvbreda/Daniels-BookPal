import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { TrackerAccountRow } from "../api/types";

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
