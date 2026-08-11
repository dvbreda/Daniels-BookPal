import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api, imageUrl } from "../api/client";
import type { BookKind, OriginRegion, Series } from "../api/types";
import { KIND_LABELS, REGION_LABELS } from "../lib/labels";
import { pickCoverProfile } from "../lib/profile";

/**
 * "Alles" filtert nog los op soort/regio/zoekterm — precies de condities
 * waar een tab-regel naar compileert (ontwerp 2). Een echte tab vervangt die
 * twee knoppenrijen door zijn regel; de zoekbalk blijft erbovenop werken.
 */
export function LibraryPage() {
  const [kind, setKind] = useState<BookKind | undefined>();
  const [region, setRegion] = useState<OriginRegion | undefined>();
  const [search, setSearch] = useState("");
  const [activeTabId, setActiveTabId] = useState<number | null>(null);
  const coverProfile = pickCoverProfile();

  const { data: tabs } = useQuery({ queryKey: ["tabs"], queryFn: api.tabs });

  const allSeries = useQuery({
    queryKey: ["series", kind, region, search],
    queryFn: () => api.series({ kind, region, search: search || undefined, limit: 200 }),
    enabled: activeTabId === null,
  });
  const tabSeries = useQuery({
    queryKey: ["tab-series", activeTabId, search],
    queryFn: () => api.tabSeries(activeTabId!, { search: search || undefined, limit: 200 }),
    enabled: activeTabId !== null,
  });
  const { data, isLoading, error } = activeTabId === null ? allSeries : tabSeries;

  return (
    <div className="mx-auto max-w-7xl px-4 py-6">
      <header className="mb-6 flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold text-slate-100">Bibliotheek</h1>
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Zoek een serie…"
          className="ml-auto w-64 rounded bg-ink-700 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500"
        />
        <Link to="/instellingen" className="rounded bg-ink-700 px-3 py-2 text-sm text-slate-200">
          Instellingen
        </Link>
      </header>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <button
          onClick={() => setActiveTabId(null)}
          className={`rounded px-3 py-1.5 text-sm ${
            activeTabId === null ? "bg-accent text-ink-900" : "bg-ink-700 text-slate-300"
          }`}
        >
          Alles
        </button>
        {tabs
          ?.filter((tab) => tab.enabled)
          .map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTabId(tab.id)}
              className={`rounded px-3 py-1.5 text-sm ${
                activeTabId === tab.id ? "bg-accent text-ink-900" : "bg-ink-700 text-slate-300"
              }`}
            >
              {tab.icon ? `${tab.icon} ` : ""}
              {tab.name}
            </button>
          ))}
        <Link to="/tabs" className="ml-auto text-xs text-slate-500 hover:text-slate-300">
          Tabs beheren
        </Link>
      </div>

      {activeTabId === null && (
        <div className="mb-6 flex flex-wrap gap-2">
          <FilterGroup
            label="Soort"
            value={kind}
            options={Object.entries(KIND_LABELS) as [BookKind, string][]}
            onChange={setKind}
          />
          <FilterGroup
            label="Herkomst"
            value={region}
            options={
              (["europe", "japan", "korea", "us", "unknown"] as OriginRegion[]).map(
                (value) => [value, REGION_LABELS[value]] as [OriginRegion, string],
              )
            }
            onChange={setRegion}
          />
        </div>
      )}

      {isLoading && <p className="text-slate-400">Laden…</p>}
      {error && <p className="text-red-400">Kon de bibliotheek niet laden.</p>}
      {data && data.items.length === 0 && (
        <div className="rounded border border-ink-600 p-8 text-center text-slate-400">
          <p>Niets gevonden.</p>
          <Link to="/instellingen" className="mt-2 inline-block text-accent underline">
            Voeg een map toe en scan
          </Link>
        </div>
      )}

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
        {data?.items.map((series) => (
          <SeriesCard key={series.id} series={series} coverProfile={coverProfile} />
        ))}
      </div>
    </div>
  );
}

function FilterGroup<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T | undefined;
  options: [T, string][];
  onChange: (value: T | undefined) => void;
}) {
  return (
    <div className="flex items-center gap-1">
      <span className="mr-1 text-xs uppercase tracking-wide text-slate-500">{label}</span>
      <button
        onClick={() => onChange(undefined)}
        className={`rounded px-2 py-1 text-sm ${
          value === undefined ? "bg-accent text-ink-900" : "bg-ink-700 text-slate-300"
        }`}
      >
        Alles
      </button>
      {options.map(([key, text]) => (
        <button
          key={key}
          onClick={() => onChange(value === key ? undefined : key)}
          className={`rounded px-2 py-1 text-sm ${
            value === key ? "bg-accent text-ink-900" : "bg-ink-700 text-slate-300"
          }`}
        >
          {text}
        </button>
      ))}
    </div>
  );
}

function SeriesCard({ series, coverProfile }: { series: Series; coverProfile: string }) {
  return (
    <Link
      to={`/serie/${series.id}`}
      className="group overflow-hidden rounded-lg bg-ink-800 transition hover:ring-2 hover:ring-accent"
    >
      <div className="aspect-[2/3] bg-ink-700">
        <CoverImage seriesId={series.id} profile={coverProfile} />
      </div>
      <div className="p-2">
        <p className="truncate text-sm font-medium text-slate-100">{series.title}</p>
        <p className="text-xs text-slate-400">
          {series.book_count} {series.book_count === 1 ? "deel" : "delen"}
          {series.origin_region !== "unknown" && ` · ${REGION_LABELS[series.origin_region]}`}
        </p>
      </div>
    </Link>
  );
}

/** De omslag van een serie is die van het eerste deel. */
function CoverImage({ seriesId, profile }: { seriesId: number; profile: string }) {
  const { data } = useQuery({
    queryKey: ["series-detail", seriesId],
    queryFn: () => api.seriesDetail(seriesId),
    staleTime: 5 * 60 * 1000,
  });
  const first = data?.books[0];
  if (!first) return <div className="h-full w-full bg-ink-700" />;
  return (
    <img
      src={imageUrl.cover(first.id, profile)}
      alt=""
      loading="lazy"
      className="h-full w-full object-cover"
      onError={(event) => {
        event.currentTarget.style.visibility = "hidden";
      }}
    />
  );
}
