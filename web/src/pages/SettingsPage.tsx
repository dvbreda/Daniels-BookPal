import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { ScanResult } from "../api/types";

export function SettingsPage() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [path, setPath] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [lastScan, setLastScan] = useState<ScanResult | null>(null);

  const { data: roots } = useQuery({ queryKey: ["libraries"], queryFn: api.libraries });
  const { data: health } = useQuery({ queryKey: ["health"], queryFn: api.health });

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ["libraries"] });
    void queryClient.invalidateQueries({ queryKey: ["health"] });
    void queryClient.invalidateQueries({ queryKey: ["series"] });
  }

  const addRoot = useMutation({
    mutationFn: () => api.addLibrary({ name, path }),
    onSuccess: () => {
      setName("");
      setPath("");
      setMessage(null);
      refresh();
    },
    onError: (error: unknown) => {
      setMessage(error instanceof ApiError ? error.message : "Toevoegen mislukt.");
    },
  });

  const scan = useMutation({
    mutationFn: (id: number) => api.scanLibrary(id),
    onSuccess: (result) => {
      setLastScan(result);
      setMessage(null);
      refresh();
    },
    onError: (error: unknown) => {
      // Een afgebroken scan wegens een niet-gemounte share is geen fout in de
      // app; die uitleg wil je letterlijk zien.
      setMessage(error instanceof ApiError ? error.message : "Scannen mislukt.");
    },
  });

  const removeRoot = useMutation({
    mutationFn: (id: number) => api.deleteLibrary(id),
    onSuccess: refresh,
  });

  return (
    <div className="mx-auto max-w-3xl px-4 py-6">
      <Link to="/" className="text-sm text-slate-400 hover:text-slate-200">
        ← Bibliotheek
      </Link>
      <h1 className="mt-4 text-2xl font-semibold text-slate-100">Instellingen</h1>

      {health && (
        <p className="mt-2 text-sm text-slate-400">
          {health.series} series · {health.books} boeken · {health.cache_mb} MB beeldcache
        </p>
      )}

      <section className="mt-6 rounded border border-ink-600 p-4">
        <h2 className="font-medium text-slate-200">Mappen op de NAS</h2>
        <p className="mt-1 text-xs text-slate-500">
          Paden zoals de server ze ziet — binnen Docker dus het pad in de container.
        </p>

        <div className="mt-4 space-y-4">
          {roots?.map((root) => (
            <div key={root.id} className="flex flex-wrap items-center gap-3 rounded bg-ink-800 p-3">
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium text-slate-100">{root.name}</p>
                <p className="truncate text-xs text-slate-500">{root.path}</p>
                <p className="text-xs text-slate-500">
                  {root.series_count} series · {root.book_count} boeken
                  {root.last_scan_at &&
                    ` · laatst gescand ${new Date(root.last_scan_at).toLocaleString("nl-NL")}`}
                </p>
              </div>
              <button
                onClick={() => scan.mutate(root.id)}
                disabled={scan.isPending}
                className="rounded bg-accent px-3 py-1.5 text-sm text-ink-900 disabled:opacity-50"
              >
                {scan.isPending ? "Bezig…" : "Scannen"}
              </button>
              <button
                onClick={() => removeRoot.mutate(root.id)}
                className="rounded bg-ink-700 px-3 py-1.5 text-sm text-slate-300"
              >
                Verwijderen
              </button>
            </div>
          ))}
          {roots?.length === 0 && (
            <p className="text-sm text-slate-500">Nog geen mappen toegevoegd.</p>
          )}
        </div>

        <form
          className="mt-6 flex flex-wrap gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            addRoot.mutate();
          }}
        >
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Naam, bv. Strips"
            required
            className="w-40 rounded bg-ink-700 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500"
          />
          <input
            value={path}
            onChange={(event) => setPath(event.target.value)}
            placeholder="/library/strips"
            required
            className="min-w-0 flex-1 rounded bg-ink-700 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500"
          />
          <button
            type="submit"
            disabled={addRoot.isPending}
            className="rounded bg-accent px-4 py-2 text-sm text-ink-900 disabled:opacity-50"
          >
            Toevoegen
          </button>
        </form>

        {message && <p className="mt-3 rounded bg-red-950 p-3 text-sm text-red-300">{message}</p>}
        {lastScan && (
          <div className="mt-3 rounded bg-ink-800 p-3 text-sm text-slate-300">
            <p>
              {lastScan.root}: {lastScan.added} nieuw, {lastScan.updated} bijgewerkt,{" "}
              {lastScan.unchanged} ongewijzigd, {lastScan.removed} verwijderd.
            </p>
            {lastScan.errors.length > 0 && (
              <ul className="mt-2 list-inside list-disc text-xs text-amber-400">
                {lastScan.errors.map((error) => (
                  <li key={error}>{error}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
