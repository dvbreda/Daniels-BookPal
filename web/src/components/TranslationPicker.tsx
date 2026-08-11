import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError, api } from "../api/client";

/**
 * Welke vertaling wil je lezen?
 *
 * Een bron kan dezelfde aflevering meerdere keren hebben, vertaald door
 * verschillende groepen. BookPal kiest automatisch de groep die het grootste
 * deel van de reeks heeft gedaan — dat geeft één consistente vertaling — maar
 * de meeste hoofdstukken is niet hetzelfde als de mooiste vertaling. Vandaar
 * deze keuze.
 *
 * Toont niets als deze serie geen abonnement heeft of er maar één groep is.
 */
export function TranslationPicker({ seriesId }: { seriesId: number }) {
  const queryClient = useQueryClient();
  const [message, setMessage] = useState<string | null>(null);

  const { data: subscription } = useQuery({
    queryKey: ["subscription-for-series", seriesId],
    queryFn: () => api.subscriptionForSeries(seriesId),
    // 404 betekent gewoon "geen abonnement"; niet opnieuw proberen.
    retry: false,
  });

  const choose = useMutation({
    mutationFn: (groupId: string | null) =>
      api.updateSubscription(subscription!.id, { preferred_group_id: groupId }),
    onSuccess: (result) => {
      setMessage(
        result.chapters_added > 0
          ? `${result.chapters_added} hoofdstukken van deze vertaling opgehaald.`
          : "Vertaling bijgewerkt.",
      );
      void queryClient.invalidateQueries({ queryKey: ["series-detail", seriesId] });
      void queryClient.invalidateQueries({ queryKey: ["subscription-for-series", seriesId] });
    },
    onError: (error: unknown) => {
      setMessage(error instanceof ApiError ? error.message : "Wisselen mislukt.");
    },
  });

  if (!subscription || subscription.available_groups.length < 2) return null;

  return (
    <section className="mt-6 rounded border border-ink-600 p-4">
      <h2 className="text-sm font-medium text-slate-200">Vertaling</h2>
      <p className="mt-1 text-xs text-slate-500">
        Meerdere groepen hebben deze reeks vertaald. Automatisch betekent: de groep
        met de meeste hoofdstukken, zodat je één stijl leest.
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <select
          value={subscription.preferred_group_id ?? ""}
          onChange={(event) => choose.mutate(event.target.value || null)}
          disabled={choose.isPending}
          className="rounded bg-ink-700 px-3 py-2 text-sm text-slate-100 disabled:opacity-50"
        >
          <option value="">Automatisch kiezen</option>
          {subscription.available_groups.map((group) => (
            <option key={group.id} value={group.id}>
              {group.name} ({group.chapters} hoofdstukken)
            </option>
          ))}
        </select>
        {choose.isPending && <span className="text-xs text-slate-400">Ophalen…</span>}
      </div>
      {message && <p className="mt-2 text-xs text-slate-400">{message}</p>}
      <p className="mt-2 text-xs text-slate-500">
        Al opgehaalde afleveringen blijven staan, ook die van de andere vertaling.
      </p>
    </section>
  );
}
