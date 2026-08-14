import { Link } from "react-router-dom";

import { imageUrl } from "../api/client";
import type { HomeItem } from "../api/types";

/**
 * Waar je gebleven was, groot en als eerste.
 *
 * Het enige wat een lezer bij het openen bijna altijd wil is terug naar de
 * pagina waar hij zat. Dat hoort geen zoektocht door een alfabetisch raster te
 * zijn maar één tik, en groot genoeg om hem op een telefoon met een duim te
 * raken. Alles daaronder is voor de keren dat je iets anders wilt.
 */
export function ContinueHero({ item }: { item: HomeItem }) {
  const deel = [
    item.volume ? `Deel ${item.volume}` : null,
    item.number ? `Hoofdstuk ${item.number}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <section className="mb-8 overflow-hidden rounded-xl bg-ink-800">
      <div className="flex flex-col gap-4 sm:flex-row">
        <Link
          to={`/lezen/${item.book_id}`}
          className="relative w-full shrink-0 sm:w-40"
          aria-label={`Verder lezen in ${item.series_title}`}
        >
          {/* Op een telefoon een brede band, op een breed scherm een omslag
              naast de tekst: hetzelfde beeld, andere uitsnede. */}
          <img
            src={imageUrl.cover(item.book_id)}
            alt=""
            className="h-32 w-full object-cover sm:h-full"
            onError={(event) => {
              event.currentTarget.style.visibility = "hidden";
            }}
          />
        </Link>

        <div className="flex min-w-0 flex-1 flex-col justify-center gap-2 p-4 sm:pl-0">
          <p className="text-xs uppercase tracking-wide text-slate-500">Verder lezen</p>
          <Link
            to={`/serie/${item.series_id}`}
            className="truncate text-xl font-semibold text-slate-100 hover:text-accent"
          >
            {item.series_title}
          </Link>
          <p className="truncate text-sm text-slate-400">
            {[deel, item.title].filter(Boolean).join(" — ")}
          </p>

          <div className="mt-1 flex items-center gap-3">
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-ink-700">
              <div
                className="h-full rounded-full bg-accent"
                style={{ width: `${Math.max(2, Math.round(item.percent))}%` }}
              />
            </div>
            <span className="shrink-0 tabular-nums text-xs text-slate-500">
              {Math.round(item.percent)}%
            </span>
          </div>

          <Link
            to={`/lezen/${item.book_id}`}
            className="mt-2 inline-block self-start rounded-lg bg-accent px-5 py-2.5 text-sm font-medium text-ink-900"
          >
            Lees verder
            {item.kind !== "epub" && item.page > 0 ? ` · pagina ${item.page + 1}` : ""}
          </Link>
        </div>
      </div>
    </section>
  );
}
