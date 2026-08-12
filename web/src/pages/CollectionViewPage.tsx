import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import type { Series } from "../api/types";
import { SeriesCard } from "../components/SeriesCard";
import { pickCoverProfile } from "../lib/profile";

/**
 * Toont een slimme collectie. Groepering is client-side: de server levert de
 * platte serielijst, de sectie-indeling gebeurt hier op `group_by`. Voor
 * grotere collecties komt server-side groepering terug zodra "submappen als
 * collectie" er echt toe doet (ontwerp 2).
 */
export function CollectionViewPage() {
  const { id } = useParams<{ id: string }>();
  const collectionId = Number(id);
  const coverProfile = pickCoverProfile();

  const { data: collection } = useQuery({
    queryKey: ["collection", collectionId],
    queryFn: () => api.collection(collectionId),
  });
  const { data, isLoading, error } = useQuery({
    queryKey: ["collection-series", collectionId],
    queryFn: () => api.collectionSeries(collectionId, { limit: 500 }),
  });

  const groups = groupSeries(data?.items ?? [], collection?.group_by ?? null);

  return (
    <div className="mx-auto max-w-7xl px-4 py-6">
      <Link to="/collecties" className="text-sm text-slate-400 hover:text-slate-200">
        ← Collecties
      </Link>
      <h1 className="mt-4 text-2xl font-semibold text-slate-100">
        {collection?.name ?? "Collectie"}
      </h1>

      {isLoading && <p className="mt-4 text-slate-400">Laden…</p>}
      {error && <p className="mt-4 text-danger">Kon de collectie niet laden.</p>}
      {data && data.items.length === 0 && (
        <p className="mt-4 text-slate-400">Deze collectie is nog leeg.</p>
      )}

      {groups.map(([label, items]) => (
        <section key={label} className="mt-6">
          {label && <h2 className="mb-3 text-sm font-medium text-slate-400">{label}</h2>}
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
            {items.map((series) => (
              <SeriesCard key={series.id} series={series} coverProfile={coverProfile} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function groupSeries(items: Series[], groupBy: string | null): [string, Series[]][] {
  if (groupBy !== "publisher" && groupBy !== "folder") {
    return items.length ? [["", items]] : [];
  }
  const buckets = new Map<string, Series[]>();
  for (const series of items) {
    const key =
      (groupBy === "publisher" ? series.publisher : series.folder_path) || "Onbekend";
    const bucket = buckets.get(key);
    if (bucket) bucket.push(series);
    else buckets.set(key, [series]);
  }
  return [...buckets.entries()].sort(([a], [b]) => a.localeCompare(b));
}
