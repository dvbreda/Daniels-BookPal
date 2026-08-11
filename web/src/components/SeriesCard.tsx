import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { api, imageUrl } from "../api/client";
import type { Series } from "../api/types";
import { REGION_LABELS } from "../lib/labels";
import { SubscriptionBadge } from "./SourceBadge";

export function SeriesCard({ series, coverProfile }: { series: Series; coverProfile: string }) {
  return (
    <Link
      to={`/serie/${series.id}`}
      className="group overflow-hidden rounded-lg bg-ink-800 transition hover:ring-2 hover:ring-accent"
    >
      <div className="relative aspect-[2/3] bg-ink-700">
        <CoverImage
          seriesId={series.id}
          hasCoverUrl={series.has_cover_url}
          profile={coverProfile}
        />
        <div className="absolute left-1 top-1">
          <SubscriptionBadge fromSource={series.from_source} />
        </div>
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

/**
 * De omslag van een serie. Een bron levert soms een betere dan "pagina 1 van
 * het eerste deel" — bij scanlaties staat daar vaak een credits-pagina van de
 * vertaalgroep over de echte omslag heen (zie TranslationPicker-achtige uitleg
 * bij "Omslag" op de seriepagina). Die officiële omslag krijgt voorrang.
 */
function CoverImage({
  seriesId,
  hasCoverUrl,
  profile,
}: {
  seriesId: number;
  hasCoverUrl: boolean;
  profile: string;
}) {
  if (hasCoverUrl) {
    return (
      <img
        src={imageUrl.seriesCover(seriesId, profile)}
        alt=""
        loading="lazy"
        className="h-full w-full object-cover"
        onError={(event) => {
          event.currentTarget.style.visibility = "hidden";
        }}
      />
    );
  }
  return <FirstPageCover seriesId={seriesId} profile={profile} />;
}

function FirstPageCover({ seriesId, profile }: { seriesId: number; profile: string }) {
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
