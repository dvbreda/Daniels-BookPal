import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError, api } from "../api/client";
import type { KoboSyncResult } from "../api/types";

/**
 * De Nickel-integratie: lezen in Kobo's eigen lezer, met alles wat erbij hoort.
 *
 * Drie onderdelen die los aan kunnen, omdat ze los van elkaar nut hebben en los
 * van elkaar kunnen breken. Alleen de laatste twee raken `KoboReader.sqlite`
 * aan — de enige plek in BookPal die op reverse-engineering leunt, en dus de
 * enige die een firmware-update kan overleven of niet.
 *
 * De proefstand staat standaard aan: dit schrijft bestanden naar je lezer en
 * regels in zijn database, en dan hoor je eerst te zien wat er zou gebeuren.
 */
export function KoboPanel() {
  const queryClient = useQueryClient();
  const [melding, setMelding] = useState<string | null>(null);
  const [mount, setMount] = useState<string | null>(null);

  const { data } = useQuery({ queryKey: ["kobo"], queryFn: api.koboStatus });
  const { data: reeksen } = useQuery({
    queryKey: ["series", "kobo"],
    queryFn: () => api.series({ limit: 200 }),
  });
  const { data: plan } = useQuery({ queryKey: ["kobo-plan"], queryFn: api.koboPlan });

  const opslaan = useMutation({
    mutationFn: (body: Parameters<typeof api.koboSettings>[0]) => api.koboSettings(body),
    onSuccess: () => {
      setMelding(null);
      void queryClient.invalidateQueries({ queryKey: ["kobo"] });
      void queryClient.invalidateQueries({ queryKey: ["kobo-plan"] });
    },
    onError: (fout: unknown) =>
      setMelding(fout instanceof ApiError ? fout.message : "Opslaan mislukt."),
  });

  const sync = useMutation({
    mutationFn: () => api.koboSync(),
    onSuccess: (result) => {
      setMelding(samenvatting(result));
      void queryClient.invalidateQueries({ queryKey: ["kobo"] });
      void queryClient.invalidateQueries({ queryKey: ["series"] });
    },
    onError: (fout: unknown) =>
      setMelding(fout instanceof ApiError ? fout.message : "Synchroniseren mislukt."),
  });

  if (!data) return null;

  const gekozen = new Set(data.series_ids);

  return (
    <section className="mt-6 rounded border border-ink-600 p-4">
      <h2 className="font-medium text-slate-200">Kobo</h2>
      <p className="mt-1 text-xs text-slate-500">
        Voor lezen in Kobo's eigen lezer. Sluit hem via USB aan op de NAS en wijs hier de map
        aan. Wat je op de Kobo leest telt hier daarna gewoon mee.
      </p>

      <form
        className="mt-3 flex flex-wrap gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          opslaan.mutate({ mount: (mount ?? data.mount ?? "").trim() || null });
        }}
      >
        <input
          value={mount ?? data.mount ?? ""}
          onChange={(event) => setMount(event.target.value)}
          placeholder="/mnt/kobo"
          className="min-w-0 flex-1 rounded bg-ink-700 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500"
        />
        <button
          type="submit"
          disabled={opslaan.isPending}
          className="rounded bg-ink-700 px-3 py-2 text-sm text-slate-200 disabled:opacity-50"
        >
          Opslaan
        </button>
      </form>

      <p className="mt-2 text-xs">
        {data.connected ? (
          <span className="text-slate-400">
            Kobo gevonden{data.writable ? "" : " — maar de map is niet beschrijfbaar"}.
          </span>
        ) : (
          <span className="text-warning">{data.error ?? "Nog geen Kobo aangewezen."}</span>
        )}
      </p>

      <div className="mt-3 space-y-2">
        <Schakelaar
          aan={data.export_books}
          label="Boeken wegzetten"
          uitleg="Waar je gebleven bent plus een paar vooruit, per serie."
          onChange={(waarde) => opslaan.mutate({ export_books: waarde })}
        />
        <Schakelaar
          aan={data.write_shelves}
          label="Series als planken"
          uitleg="Schrijft in KoboReader.sqlite; er gaat altijd eerst een kopie naast."
          onChange={(waarde) => opslaan.mutate({ write_shelves: waarde })}
        />
        <Schakelaar
          aan={data.read_progress}
          label="Voortgang teruglezen"
          uitleg="Wat je in Nickel las telt hier ook mee."
          onChange={(waarde) => opslaan.mutate({ read_progress: waarde })}
        />
        <Schakelaar
          aan={data.dry_run}
          label="Proefronde"
          uitleg="Laat zien wat er zou gebeuren, zonder iets te schrijven."
          onChange={(waarde) => opslaan.mutate({ dry_run: waarde })}
        />
      </div>

      <label className="mt-3 flex flex-wrap items-center gap-2 text-sm text-slate-300">
        Hoofdstukken vooruit
        <input
          type="number"
          min={1}
          max={50}
          defaultValue={data.ahead}
          onBlur={(event) => {
            const waarde = Number(event.target.value);
            if (waarde >= 1 && waarde !== data.ahead) opslaan.mutate({ ahead: waarde });
          }}
          className="w-20 rounded bg-ink-700 px-2 py-1 text-sm text-slate-100"
        />
        <span className="text-xs text-slate-500">Een Kobo heeft een paar GB, geen 700 delen.</span>
      </label>

      <div className="mt-3">
        <p className="text-sm text-slate-300">Welke series gaan mee?</p>
        <ul className="mt-1 max-h-48 space-y-1 overflow-y-auto">
          {(reeksen?.items ?? []).map((serie) => (
            <li key={serie.id}>
              <label className="flex cursor-pointer items-center gap-2 rounded bg-ink-800 px-3 py-2 text-sm">
                <input
                  type="checkbox"
                  checked={gekozen.has(serie.id)}
                  onChange={(event) => {
                    const volgende = new Set(gekozen);
                    if (event.target.checked) volgende.add(serie.id);
                    else volgende.delete(serie.id);
                    opslaan.mutate({ series_ids: [...volgende] });
                  }}
                />
                <span className="min-w-0 flex-1 truncate text-slate-100">{serie.title}</span>
              </label>
            </li>
          ))}
        </ul>
      </div>

      {plan && plan.length > 0 && (
        <p className="mt-3 text-xs text-slate-500">
          Klaar om mee te gaan: {plan.length}{" "}
          {plan.length === 1 ? "hoofdstuk" : "hoofdstukken"} —{" "}
          {plan
            .slice(0, 3)
            .map((item) => item.title)
            .join(", ")}
          {plan.length > 3 ? "…" : ""}
        </p>
      )}

      <button
        onClick={() => sync.mutate()}
        disabled={sync.isPending || !data.connected}
        className="mt-3 rounded bg-accent px-4 py-2 text-sm text-ink-900 disabled:opacity-50"
      >
        {sync.isPending ? "Bezig…" : data.dry_run ? "Proefronde draaien" : "Synchroniseren"}
      </button>

      {melding && (
        <p className="mt-3 whitespace-pre-line rounded bg-ink-800 p-3 text-sm text-slate-300">
          {melding}
        </p>
      )}
    </section>
  );
}

function Schakelaar({
  aan,
  label,
  uitleg,
  onChange,
}: {
  aan: boolean;
  label: string;
  uitleg: string;
  onChange: (waarde: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-2 text-sm text-slate-300">
      <input
        type="checkbox"
        checked={aan}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-1"
      />
      <span>
        {label}
        <span className="block text-xs text-slate-500">{uitleg}</span>
      </span>
    </label>
  );
}

function samenvatting(result: KoboSyncResult): string {
  const regels: string[] = [];
  if (result.dry_run) {
    regels.push(`Proefronde: ${result.planned} hoofdstukken zouden meegaan.`);
  } else {
    regels.push(
      `${result.copied} gekopieerd, ${result.skipped} stond er al, ${result.removed} opgeruimd.`,
    );
    if (result.shelf_entries || result.shelves_created.length) {
      regels.push(
        `Planken: ${result.shelves_created.length} nieuw, ${result.shelf_entries} boeken erin.`,
      );
    }
    if (result.progress_updated) {
      regels.push(`${result.progress_updated} keer voortgang overgenomen van de Kobo.`);
    }
    if (result.backup) regels.push(`Kopie van de database: ${result.backup}`);
  }
  regels.push(...result.notes);
  if (result.errors.length) regels.push(`Fouten: ${result.errors.slice(0, 3).join("; ")}`);
  return regels.join("\n");
}
