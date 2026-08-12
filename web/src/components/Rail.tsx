import { Link } from "react-router-dom";

import { imageUrl } from "../api/client";
import type { HomeItem, HomeRail } from "../api/types";

/**
 * Eén rij van de startpagina, horizontaal doorschuifbaar.
 *
 * Bewust geen raster: een raster nodigt uit tot zoeken en dat is precies wat een
 * startpagina je uit handen hoort te nemen. Een rij zegt "dit zijn er een paar,
 * kijk verder als je wilt" — en op een telefoon veeg je er met één duim
 * doorheen.
 */
export function Rail({ rail }: { rail: HomeRail }) {
  if (rail.items.length === 0) return null;

  return (
    <section className="mb-8">
      <h2 className="mb-2 text-sm font-medium uppercase tracking-wide text-slate-400">
        {rail.title}
      </h2>
      {/* De negatieve marges laten de rij tot aan de schermrand doorlopen, zodat
          zichtbaar is dat er meer staat dan er past. */}
      <ul className="-mx-4 flex snap-x snap-mandatory gap-3 overflow-x-auto px-4 pb-2">
        {rail.items.map((item) => (
          <li key={item.book_id} className="w-32 shrink-0 snap-start sm:w-36">
            <RailCard item={item} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function RailCard({ item }: { item: HomeItem }) {
  const label = [item.volume ? `D${item.volume}` : null, item.number].filter(Boolean).join(".");

  return (
    <Link
      to={`/lezen/${item.book_id}`}
      className="group block overflow-hidden rounded-lg bg-ink-800 transition hover:ring-2 hover:ring-accent"
    >
      <div className="relative aspect-[2/3] bg-ink-700">
        <img
          src={imageUrl.cover(item.book_id)}
          alt=""
          loading="lazy"
          className="h-full w-full object-cover"
          onError={(event) => {
            event.currentTarget.style.visibility = "hidden";
          }}
        />
        {item.percent > 0 && (
          <div className="absolute inset-x-0 bottom-0 h-1 bg-ink-900/70">
            <div className="h-full bg-accent" style={{ width: `${item.percent}%` }} />
          </div>
        )}
      </div>
      <div className="p-2">
        <p className="truncate text-xs font-medium text-slate-100">{item.series_title}</p>
        <p className="truncate text-xs text-slate-500">
          {label ? `${label} · ` : ""}
          {item.title}
        </p>
      </div>
    </Link>
  );
}
