import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { ScanResult, TranslateMode } from "../api/types";

export function SettingsPage() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [path, setPath] = useState("");
  const [region, setRegion] = useState("");
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
    mutationFn: () =>
      api.addLibrary({ name, path, default_origin_region: region || null }),
    onSuccess: () => {
      setName("");
      setPath("");
      setRegion("");
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

      <TranslateModePanel />

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
          <select
            value={region}
            onChange={(event) => setRegion(event.target.value)}
            className="rounded bg-ink-700 px-3 py-2 text-sm text-slate-100"
            title="Herkomst voor bestanden in deze map die zelf niets prijsgeven"
          >
            <option value="">Herkomst afleiden</option>
            <option value="europe">Standaard Europa</option>
            <option value="japan">Standaard Japan</option>
            <option value="korea">Standaard Korea</option>
            <option value="china">Standaard China</option>
            <option value="us">Standaard VS</option>
          </select>
          <button
            type="submit"
            disabled={addRoot.isPending}
            className="rounded bg-accent px-4 py-2 text-sm text-ink-900 disabled:opacity-50"
          >
            Toevoegen
          </button>
        </form>
        <p className="mt-2 text-xs text-slate-500">
          De herkomst is het vangnet voor bestanden zonder ComicInfo.xml. Wat het
          bestand zelf zegt wint hier altijd van, en jouw handmatige keuze per serie
          wint van allebei.
        </p>

        {message && <p className="mt-3 rounded bg-danger-bg p-3 text-sm text-danger">{message}</p>}
        {lastScan && (
          <div className="mt-3 rounded bg-ink-800 p-3 text-sm text-slate-300">
            <p>
              {lastScan.root}: {lastScan.added} nieuw, {lastScan.updated} bijgewerkt,{" "}
              {lastScan.unchanged} ongewijzigd, {lastScan.removed} verwijderd.
            </p>
            {lastScan.errors.length > 0 && (
              <ul className="mt-2 list-inside list-disc text-xs text-warning">
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


const MODE_LABELS: Record<TranslateMode, { naam: string; uitleg: string }> = {
  text: {
    naam: "Tekst (goedkoop)",
    uitleg:
      "Het taalmodel leest de pagina, wij zetten de vertaling zelf in een vlakje. " +
      "Voorspelbaar correct, raakt de tekening nooit aan, en je kunt op een ballon " +
      "tikken voor het origineel.",
  },
  image_fast: {
    naam: "Beeldmodel (snel)",
    uitleg:
      "Het beeldmodel hertekent de hele pagina mét vertaling. Mooi ingepast, maar " +
      "liet in onze tests op 3 van de 4 pagina's iets liggen — waaronder één keer " +
      "een gewijzigd bedrag, en dat valt niet op.",
  },
  image_pro: {
    naam: "Beeldmodel (zwaar)",
    uitleg:
      "Hetzelfde met het zware model. Kwam in alle vier onze tests goed door, maar " +
      "is veruit het duurst.",
  },
};

const MODE_ORDER: TranslateMode[] = ["text", "image_fast", "image_pro"];

/**
 * De vertaalstand (M8).
 *
 * Bewust met de prijs erbij: het verschil tussen de goedkoopste en de duurste
 * stand is een factor zestig, en dat hoor je te zien vóór je kiest in plaats
 * van achteraf op een rekening.
 */
function TranslateModePanel() {
  const queryClient = useQueryClient();
  const { data } = useQuery({ queryKey: ["translate-mode"], queryFn: api.translateMode });
  const change = useMutation({
    mutationFn: (mode: TranslateMode) => api.setTranslateMode(mode),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["translate-mode"] }),
  });

  if (!data) return null;

  return (
    <section className="mt-6 rounded border border-ink-600 p-4">
      <h2 className="font-medium text-slate-200">Vertaling van tekstwolkjes</h2>
      {!data.configured ? (
        <p className="mt-1 text-sm text-slate-500">
          Er is geen Gemini-sleutel ingesteld (<code>BOOKPAL_GEMINI_API_KEY</code>), dus
          vertalen staat uit.
        </p>
      ) : (
        <>
          <p className="mt-1 text-xs text-slate-500">
            Geldt voor de vertaalknop en de wachtrij die vooruitleest. Los daarvan kun je in
            de lezer altijd één pagina met een duurder model doen — dat wordt bewaard, dus
            een tweede keer kost niets.
          </p>
          <div className="mt-3 space-y-2">
            {MODE_ORDER.map((mode) => (
              <label
                key={mode}
                className={`flex cursor-pointer gap-3 rounded p-3 ${
                  data.mode === mode ? "bg-ink-700" : "bg-ink-800"
                }`}
              >
                <input
                  type="radio"
                  name="vertaalstand"
                  className="mt-1"
                  checked={data.mode === mode}
                  onChange={() => change.mutate(mode)}
                />
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-baseline gap-2">
                    <span className="text-slate-100">{MODE_LABELS[mode].naam}</span>
                    <span className="tabular-nums text-xs text-slate-500">
                      ± ${(data.costs[mode] ?? 0).toFixed(3)} per pagina
                    </span>
                  </span>
                  <span className="mt-1 block text-xs text-slate-500">
                    {MODE_LABELS[mode].uitleg}
                  </span>
                </span>
              </label>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
