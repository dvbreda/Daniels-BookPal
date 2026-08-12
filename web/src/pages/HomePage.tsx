import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { BookKind, OriginRegion } from "../api/types";
import { ContinueHero } from "../components/ContinueHero";
import { Rail } from "../components/Rail";
import { SeriesCard } from "../components/SeriesCard";
import { ThemeToggle } from "../components/ThemeToggle";
import { KIND_LABELS, REGION_LABELS } from "../lib/labels";
import { pickCoverProfile } from "../lib/profile";

/**
 * De startpagina.
 *
 * De volgorde is het ontwerp. Bovenaan waar je gebleven was — dat is bij een
 * lezer bijna altijd wat je wilt, en het hoort één tik te zijn in plaats van een
 * zoektocht. Daaronder rails met wat er klaarligt. Pas onderaan de bibliotheek
 * zelf, want bladeren door alles is wat je zelden doet maar dan wel goed moet
 * kunnen.
 *
 * De filterrij is er één en geen twee. Een tab ís een opgeslagen filter, dus
 * "Manga" als tab en "Manga" als soort-knop naast elkaar zetten was hetzelfde
 * twee keer vragen. Nu staan jouw tabs vooraan en de ingebouwde snelfilters
 * erachter, in dezelfde rij.
 */
const SNELFILTERS: [BookKind, string][] = Object.entries(KIND_LABELS) as [BookKind, string][];

const REGIOS: OriginRegion[] = ["europe", "japan", "korea", "us"];

export function HomePage() {
  const [search, setSearch] = useState("");
  const [tabId, setTabId] = useState<number | null>(null);
  const [kind, setKind] = useState<BookKind | undefined>();
  const [region, setRegion] = useState<OriginRegion | undefined>();
  const [meer, setMeer] = useState(false);
  const coverProfile = pickCoverProfile();

  const { data: home } = useQuery({ queryKey: ["home"], queryFn: api.home });
  const { data: tabs } = useQuery({ queryKey: ["tabs"], queryFn: api.tabs });

  const bladeren = search.trim().length > 0 || tabId !== null || kind || region;

  const alles = useQuery({
    queryKey: ["series", kind, region, search],
    queryFn: () => api.series({ kind, region, search: search.trim() || undefined, limit: 200 }),
    enabled: tabId === null,
  });
  const vanTab = useQuery({
    queryKey: ["tab-series", tabId, search],
    queryFn: () => api.tabSeries(tabId!, { search: search.trim() || undefined, limit: 200 }),
    enabled: tabId !== null,
  });
  const { data, isLoading, error } = tabId === null ? alles : vanTab;

  const verder = home?.rails.find((rail) => rail.key === "verder");
  const held = verder?.items[0];
  // De held staat al groot bovenaan; hem daaronder herhalen is ruis.
  const rails = (home?.rails ?? []).map((rail) =>
    rail.key === "verder" ? { ...rail, items: rail.items.slice(1) } : rail,
  );

  const kies = (actie: () => void) => {
    setTabId(null);
    setKind(undefined);
    setRegion(undefined);
    actie();
  };

  return (
    <div className="mx-auto max-w-7xl px-4 py-6">
      <header className="mb-6 flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold text-slate-100">BookPal</h1>
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Zoek een serie…"
          className="ml-auto w-64 rounded bg-ink-700 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500"
        />
        <ThemeToggle />
        <Link to="/instellingen" className="rounded bg-ink-700 px-3 py-2 text-sm text-slate-200">
          Instellingen
        </Link>
      </header>

      {/* Alleen als je niets aan het filteren bent: zodra je zoekt is de
          bibliotheek waar je naar kijkt, en dan hoort die bovenaan te staan. */}
      {!bladeren && (
        <>
          {held && <ContinueHero item={held} />}
          {rails.map((rail) => (
            <Rail key={rail.key} rail={rail} />
          ))}
        </>
      )}

      <section>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <h2 className="mr-1 text-sm font-medium uppercase tracking-wide text-slate-400">
            Bibliotheek
          </h2>
          <Chip actief={!bladeren || (!tabId && !kind && !region)} onClick={() => kies(() => {})}>
            Alles
          </Chip>
          {tabs
            ?.filter((tab) => tab.enabled)
            .map((tab) => (
              <Chip
                key={tab.id}
                actief={tabId === tab.id}
                onClick={() => kies(() => setTabId(tab.id))}
              >
                {tab.icon ? `${tab.icon} ` : ""}
                {tab.name}
              </Chip>
            ))}

          <span className="mx-1 h-5 w-px bg-ink-600" aria-hidden />

          {SNELFILTERS.map(([waarde, label]) => (
            <Chip key={waarde} actief={kind === waarde} onClick={() => kies(() => setKind(waarde))}>
              {label}
            </Chip>
          ))}
          <button
            onClick={() => setMeer(!meer)}
            aria-expanded={meer}
            className="rounded px-2 py-1.5 text-sm text-slate-500 hover:text-slate-300"
            title="Filter op herkomst"
          >
            ⋯
          </button>
        </div>

        {meer && (
          <div className="mb-3 flex flex-wrap items-center gap-2">
            {REGIOS.map((waarde) => (
              <Chip
                key={waarde}
                actief={region === waarde}
                onClick={() => kies(() => setRegion(waarde))}
              >
                {REGION_LABELS[waarde]}
              </Chip>
            ))}
            <Link to="/instellingen?paneel=tabs" className="text-xs text-slate-500 underline">
              Hier een eigen tab van maken
            </Link>
          </div>
        )}

        {isLoading && <p className="text-slate-400">Laden…</p>}
        {error && <p className="text-danger">Kon de bibliotheek niet laden.</p>}
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
      </section>
    </div>
  );
}

function Chip({
  actief,
  onClick,
  children,
}: {
  actief: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded-full px-3 py-1.5 text-sm ${
        actief ? "bg-accent text-ink-900" : "bg-ink-700 text-slate-300 hover:bg-ink-600"
      }`}
    >
      {children}
    </button>
  );
}
