import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError, api } from "../api/client";
import type { Edition } from "../api/types";

/**
 * De uitgaven van een serie, in de volgorde waarin je ze wilt lezen.
 *
 * Van dezelfde reeks heb je vaak meerdere versies: de gekleurde die achterloopt,
 * de zwart-witte die compleet is, je eigen bestanden. Wat hier bovenaan staat
 * wint waar beide hetzelfde deel hebben; de rest vult aan waar de eerste keus
 * niets heeft. Daarom staat er per uitgave hoeveel delen hij levert — dat maakt
 * meteen zichtbaar waar je voorkeur ophoudt.
 */
export function EditionsPanel({
  seriesId,
  editions,
}: {
  seriesId: number;
  editions: Edition[];
}) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [hernoemen, setHernoemen] = useState<number | null>(null);

  const opnieuw = () => {
    void queryClient.invalidateQueries({ queryKey: ["series-detail", seriesId] });
  };

  const order = useMutation({
    mutationFn: (editionIds: number[]) => api.orderEditions(seriesId, editionIds),
    onSuccess: opnieuw,
    onError: (fout: unknown) =>
      setError(fout instanceof ApiError ? fout.message : "Volgorde opslaan mislukt."),
  });

  const rename = useMutation({
    mutationFn: ({ id, name }: { id: number; name: string }) =>
      api.renameEdition(seriesId, id, { name }),
    onSuccess: () => {
      setHernoemen(null);
      opnieuw();
    },
    onError: (fout: unknown) =>
      setError(fout instanceof ApiError ? fout.message : "Hernoemen mislukt."),
  });

  const verplaats = (index: number, richting: -1 | 1) => {
    const volgorde = editions.map((edition) => edition.id);
    const doel = index + richting;
    const hier = volgorde[index];
    const daar = volgorde[doel];
    if (hier === undefined || daar === undefined) return;
    volgorde[index] = daar;
    volgorde[doel] = hier;
    order.mutate(volgorde);
  };

  if (editions.length === 0) return null;

  return (
    <section className="mt-3 rounded border border-ink-600 p-4">
      <h2 className="text-sm font-medium text-slate-200">Uitgaven</h2>
      <p className="mt-1 text-xs text-slate-500">
        {editions.length === 1
          ? "Eén uitgave. Zodra je er een tweede bij hebt — een bron in kleur, een andere druk — bepaal je hier welke voorgaat."
          : "De bovenste wint waar meerdere hetzelfde deel hebben; de rest vult de gaten."}
      </p>

      <ol className="mt-3 space-y-1">
        {editions.map((edition, index) => (
          <li
            key={edition.id}
            className="flex flex-wrap items-center gap-2 rounded bg-ink-800 px-3 py-2 text-sm"
          >
            <span className="w-5 shrink-0 tabular-nums text-xs text-slate-500">{index + 1}.</span>

            {hernoemen === edition.id ? (
              <form
                className="flex min-w-0 flex-1 gap-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  const veld = event.currentTarget.elements.namedItem("naam");
                  if (veld instanceof HTMLInputElement && veld.value.trim()) {
                    rename.mutate({ id: edition.id, name: veld.value.trim() });
                  }
                }}
              >
                <input
                  name="naam"
                  defaultValue={edition.name}
                  autoFocus
                  className="min-w-0 flex-1 rounded bg-ink-700 px-2 py-1 text-xs text-slate-100"
                />
                <button type="submit" className="rounded bg-accent px-2 py-1 text-xs text-ink-900">
                  Opslaan
                </button>
                <button
                  type="button"
                  onClick={() => setHernoemen(null)}
                  className="rounded bg-ink-700 px-2 py-1 text-xs text-slate-300"
                >
                  Terug
                </button>
              </form>
            ) : (
              <>
                <button
                  onClick={() => setHernoemen(edition.id)}
                  title="Naam aanpassen"
                  className="min-w-0 flex-1 truncate text-left text-slate-100 hover:text-accent"
                >
                  {edition.name}
                  {edition.note && (
                    <span className="ml-2 text-xs text-slate-500">{edition.note}</span>
                  )}
                </button>
                <span
                  className="shrink-0 tabular-nums text-xs text-slate-500"
                  title="Hoeveel delen je hiervan leest, van het totaal in deze uitgave"
                >
                  {edition.chosen_count}/{edition.book_count}
                </span>
                <span className="shrink-0">
                  <button
                    onClick={() => verplaats(index, -1)}
                    disabled={index === 0 || order.isPending}
                    aria-label="Hoger in de voorkeur"
                    className="rounded bg-ink-700 px-2 py-1 text-xs text-slate-300 disabled:opacity-30"
                  >
                    ▲
                  </button>
                  <button
                    onClick={() => verplaats(index, 1)}
                    disabled={index === editions.length - 1 || order.isPending}
                    aria-label="Lager in de voorkeur"
                    className="ml-1 rounded bg-ink-700 px-2 py-1 text-xs text-slate-300 disabled:opacity-30"
                  >
                    ▼
                  </button>
                </span>
              </>
            )}
          </li>
        ))}
      </ol>

      {error && <p className="mt-2 text-xs text-danger">{error}</p>}
    </section>
  );
}
