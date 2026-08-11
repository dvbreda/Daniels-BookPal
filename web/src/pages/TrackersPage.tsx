import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

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
export function TrackersPage() {
  const queryClient = useQueryClient();
  const { data: trackers } = useQuery({ queryKey: ["trackers"], queryFn: api.trackers });
  const [message, setMessage] = useState<string | null>(null);

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

      <section className="mt-6 rounded border border-ink-600 p-4">
        <h2 className="font-medium text-slate-200">Goodreads</h2>
        <p className="mt-1 text-sm text-slate-500">
          De publieke API is dood sinds eind 2020, dus geen live koppeling — wel
          een CSV die je bij My Books → Import and Export kunt inladen.
        </p>
        <a
          href={api.goodreadsExportUrl()}
          download
          className="mt-3 inline-block rounded bg-accent px-4 py-2 text-sm text-ink-900"
        >
          CSV downloaden
        </a>
      </section>

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
  const [authorizeUrl, setAuthorizeUrl] = useState<string | null>(null);
  const [code, setCode] = useState("");

  const startAuth = useMutation({
    mutationFn: () => api.malAuthorizeUrl(account.id),
    onSuccess: (result) => {
      setAuthorizeUrl(result.url);
      window.open(result.url, "_blank", "noopener,noreferrer");
    },
    onError: (error: unknown) =>
      setMessage(error instanceof ApiError ? error.message : "Kon geen autorisatie-URL ophalen."),
  });

  const confirmCode = useMutation({
    mutationFn: () => api.malCallback(account.id, code.trim()),
    onSuccess: () => {
      setAuthorizeUrl(null);
      setCode("");
      setMessage("MyAnimeList gekoppeld.");
      onChanged();
    },
    onError: (error: unknown) =>
      setMessage(error instanceof ApiError ? error.message : "Koppelen mislukt."),
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
        <div className="rounded bg-ink-800 p-3">
          <button
            onClick={() => startAuth.mutate()}
            disabled={startAuth.isPending}
            className="rounded bg-accent px-3 py-1.5 text-sm text-ink-900 disabled:opacity-50"
          >
            Account koppelen
          </button>
          {authorizeUrl && (
            <form
              className="mt-3 flex flex-wrap gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                confirmCode.mutate();
              }}
            >
              <p className="w-full text-sm text-slate-500">
                Log in via het geopende tabblad en plak de <code>code</code> uit de
                terugkeer-URL hieronder.
              </p>
              <input
                value={code}
                onChange={(event) => setCode(event.target.value)}
                placeholder="code"
                className="min-w-0 flex-1 rounded bg-ink-700 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500"
              />
              <button
                type="submit"
                disabled={confirmCode.isPending || !code.trim()}
                className="rounded bg-accent px-4 py-2 text-sm text-ink-900 disabled:opacity-50"
              >
                Bevestigen
              </button>
            </form>
          )}
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
