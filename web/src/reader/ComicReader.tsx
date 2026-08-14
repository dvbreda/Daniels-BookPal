import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useNavigate } from "react-router-dom";

import { ApiError, api, imageUrl } from "../api/client";
import type {
  BatchKind,
  BatchPlan,
  BookDetail,
  TranslateMode,
} from "../api/types";
import { pickPageProfile } from "../lib/profile";
import { useStoredState } from "../lib/useStoredState";
import type { GridTransform } from "./grid";
import { cellOrder, cellTransform } from "./grid";
import { TranslationOverlay } from "./TranslationOverlay";
import { usePageColour } from "./usePageColour";
import { wheelSteps } from "./wheel";
import { usePageTranslation } from "./usePageTranslation";
import {
  buildSpreads,
  orderForDisplay,
  pagesToPreload,
  percentFor,
  spreadIndexOfPage,
} from "./spreads";

export type FitMode = "width" | "height" | "screen";
export type ViewMode = "paged" | "vertical";

const PRELOAD_SPREADS = 2;
const PROGRESS_DEBOUNCE_MS = 1200;
const ZOOM_STEP = 0.25;
const MAX_ZOOM = 4;

interface Props {
  book: BookDetail;
  /** De huidige stand geeft de aanroeper mee: die bepaalt of je nog moet
   * worden gevraagd of dit als ongelezen mag. */
  onClose: (percent: number) => void;
}

export function ComicReader({ book, onClose }: Props) {
  const pageCount = book.page_count ?? 0;
  const profile = useMemo(() => pickPageProfile(), []);

  const [viewMode, setViewMode] = useStoredState<ViewMode>(
    "reader.viewMode",
    "paged",
  );
  const [doublePage, setDoublePage] = useStoredState("reader.doublePage", true);
  const [fit, setFit] = useStoredState<FitMode>("reader.fit", "height");
  // De leesrichting komt uit de metadata, maar blijft overschrijfbaar: niet elk
  // bestand heeft een correct ingevuld Manga-veld.
  const [rtlOverride, setRtlOverride] = useState<boolean | null>(null);
  const rightToLeft = rtlOverride ?? book.right_to_left;

  const [aspects, setAspects] = useState<Record<number, number>>({});
  // De pagina is de bron van waarheid, niet de spread-index.
  //
  // Andersom lijkt logischer, maar dan moet bij elke moduswissel de index
  // omgerekend worden, en dat gebeurt onvermijdelijk één render te laat: de
  // nieuwe weergave ziet dan nog de oude positie en springt naar de verkeerde
  // pagina. Met de pagina als basis is de index puur afgeleid en kan hij per
  // definitie niet uit de pas lopen.
  const [page, setPage] = useState(() => {
    const stored = book.progress?.position as { page?: number } | undefined;
    return typeof stored?.page === "number" ? stored.page : 0;
  });
  const [zoom, setZoom] = useState(1);
  const [showChrome, setShowChrome] = useState(true);
  const [translated, setTranslated] = useStoredState(
    "reader.translated",
    false,
  );
  // Leesinstellingen die het beeld zelf raken; de server snijdt en rekt op en
  // cachet het resultaat, dus dit kost niets bij het omslaan.
  const [crop, setCrop] = useStoredState("reader.crop", false);
  // Rasterzoom: de pagina in cellen, één voor één vullend. Op een telefoon is
  // een mangapagina anders leesbaar noch te overzien.
  const [grid, setGrid] = useStoredState("reader.grid", 0);
  const [cell, setCell] = useState(0);
  const [contrast, setContrast] = useStoredState("reader.contrast", 100);
  // Ingekleurde pagina's als basis. Onze eigen tekstvlakken komen er gewoon
  // overheen: dat is waarom kleur en de tekststand samen kunnen, zonder dat het
  // beeldmodel de ballonnen hoeft leeg te vegen — wat het niet betrouwbaar kan.
  const [coloured, setColoured] = useStoredState("reader.colour", false);
  // Hoe vaak een pagina opnieuw is gemaakt. Zonder dit blijft na "opnieuw"
  // dezelfde afbeelding staan: het adres verandert niet, dus de browser haalt
  // niets op. Per pagina en niet één teller voor alles, anders laadt een heel
  // hoofdstuk opnieuw omdat je één pagina overdeed.
  const [versies, setVersies] = useState<Record<number, number>>({});
  const opnieuwGemaakt = useCallback((index: number) => {
    setVersies((huidig) => ({ ...huidig, [index]: (huidig[index] ?? 0) + 1 }));
  }, []);
  const adjust = useMemo(() => ({ crop, contrast }), [crop, contrast]);
  const [dismissedNext, setDismissedNext] = useState(false);

  const spreads = useMemo(
    // Rasterzoom en dubbelpagina sluiten elkaar uit: een raster over twee
    // pagina's tegelijk zou per pagina apart schalen en uit elkaar lopen.
    () =>
      buildSpreads(
        pageCount,
        viewMode === "paged" && doublePage && grid === 0,
        { aspects },
      ),
    [pageCount, viewMode, doublePage, grid, aspects],
  );

  const spreadIndex = spreadIndexOfPage(spreads, page);
  const currentSpread = spreads[spreadIndex] ?? [];
  const currentPage = currentSpread[0] ?? 0;

  const noteAspect = useCallback(
    (index: number, width: number, height: number) => {
      if (height <= 0) return;
      setAspects((current) =>
        current[index] === undefined
          ? { ...current, [index]: width / height }
          : current,
      );
    },
    [],
  );

  // Vooruit laden zodat een paginawissel geen laadmoment is.
  useEffect(() => {
    if (viewMode !== "paged") return;
    for (const page of pagesToPreload(spreads, spreadIndex, PRELOAD_SPREADS)) {
      const image = new Image();
      image.src = imageUrl.page(book.id, page, profile, adjust);
    }
  }, [adjust, book.id, profile, spreadIndex, spreads, viewMode]);

  // Voortgang wegschrijven, ontdaan van ruis tijdens snel doorbladeren.
  const pendingPercent = useRef<number | null>(null);
  useEffect(() => {
    if (spreads.length === 0) return;
    const percent = percentFor(spreads, spreadIndex, pageCount);
    pendingPercent.current = percent;
    const timer = window.setTimeout(() => {
      void api
        .setProgress({
          book_id: book.id,
          position: { page: currentPage },
          percent,
          device: "web",
        })
        .catch(() => {
          /* offline: de lezer moet gewoon doorlopen */
        });
    }, PROGRESS_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [book.id, currentPage, pageCount, spreadIndex, spreads]);

  const goToSpread = useCallback(
    (index: number) => {
      const clamped = Math.min(Math.max(index, 0), spreads.length - 1);
      const target = spreads[clamped];
      if (target && target.length > 0) {
        setZoom(1);
        setPage(target[0] as number);
      }
    },
    [spreads],
  );

  // Bij een raster van 0 staat het uit; 2 betekent 2x2, 3 betekent 3x2.
  const gridRows = grid === 0 ? 1 : grid;
  const gridCols = grid === 0 ? 1 : 2;
  const cells = useMemo(
    () => (grid === 0 ? [] : cellOrder(gridRows, gridCols, rightToLeft)),
    [grid, gridRows, gridCols, rightToLeft],
  );

  // Bij een sprong met de schuifbalk (of een moduswissel) hoor je bovenaan de
  // nieuwe pagina te beginnen, niet halverwege het raster.
  useEffect(() => {
    setCell(0);
  }, [currentPage]);

  const goNext = useCallback(() => {
    // Eerst door de cellen van deze pagina, dan pas omslaan.
    if (cells.length > 0 && cell < cells.length - 1) {
      setCell(cell + 1);
      return;
    }
    setCell(0);
    goToSpread(spreadIndex + 1);
  }, [cell, cells.length, goToSpread, spreadIndex]);

  const goPrevious = useCallback(() => {
    if (cells.length > 0 && cell > 0) {
      setCell(cell - 1);
      return;
    }
    // Terugbladeren komt onderaan de vorige pagina uit, niet bovenaan.
    setCell(Math.max(0, cells.length - 1));
    goToSpread(spreadIndex - 1);
  }, [cell, cells.length, goToSpread, spreadIndex]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      switch (event.key) {
        case "ArrowRight":
          // Bij manga loopt de rechterpijl mee met de leesrichting.
          rightToLeft ? goPrevious() : goNext();
          break;
        case "ArrowLeft":
          rightToLeft ? goNext() : goPrevious();
          break;
        case " ":
        case "ArrowDown":
          event.preventDefault();
          goNext();
          break;
        case "ArrowUp":
          goPrevious();
          break;
        case "Home":
          goToSpread(0);
          break;
        case "End":
          goToSpread(spreads.length - 1);
          break;
        case "d":
          setDoublePage(!doublePage);
          break;
        case "v":
          setViewMode(viewMode === "paged" ? "vertical" : "paged");
          break;
        case "f":
          setFit(
            fit === "width" ? "height" : fit === "height" ? "screen" : "width",
          );
          break;
        case "Escape":
          onClose(pendingPercent.current ?? 0);
          break;
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [
    doublePage,
    fit,
    goNext,
    goPrevious,
    goToSpread,
    onClose,
    rightToLeft,
    setDoublePage,
    setFit,
    setViewMode,
    spreads.length,
    viewMode,
  ]);

  function onWheel(event: React.WheelEvent) {
    if (!event.ctrlKey) return;
    event.preventDefault();
    setZoom((current) =>
      Math.min(
        MAX_ZOOM,
        Math.max(1, current - Math.sign(event.deltaY) * ZOOM_STEP),
      ),
    );
  }

  function onClickArea(event: React.MouseEvent<HTMLDivElement>) {
    const bounds = event.currentTarget.getBoundingClientRect();
    const relative = (event.clientX - bounds.left) / bounds.width;
    // Middenderde schakelt de knoppenbalk; de zijkanten bladeren.
    if (relative > 0.35 && relative < 0.65) {
      setShowChrome((visible) => !visible);
      return;
    }
    const forward = relative >= 0.65;
    (rightToLeft ? !forward : forward) ? goNext() : goPrevious();
  }

  if (pageCount === 0) {
    return (
      <div className="flex h-viewport items-center justify-center bg-ink-900 text-slate-300">
        <div className="text-center">
          <p>Dit boek heeft geen leesbare pagina's.</p>
          <button
            className="mt-4 rounded bg-ink-700 px-4 py-2"
            onClick={() => onClose(0)}
          >
            Terug
          </button>
        </div>
      </div>
    );
  }

  // Op de laatste spread: aanbieden om door te gaan. Niet pas bij "uitgelezen",
  // want die vlag gaat pas om als de voortgang is weggeschreven — dan sta je al
  // een tel te wachten op iets wat je nu wilt.
  const atEnd = spreads.length > 0 && spreadIndex === spreads.length - 1;

  const fitClass =
    fit === "width"
      ? "w-full h-auto"
      : fit === "height"
        ? "h-full w-auto"
        : "max-h-full max-w-full";

  return (
    <div className="relative h-viewport select-none overflow-hidden bg-ink-900">
      {viewMode === "vertical" ? (
        <VerticalReader
          book={book}
          pageCount={pageCount}
          profile={profile}
          initialPage={currentPage}
          onVisiblePage={setPage}
          onAspect={noteAspect}
          translated={translated}
          coloured={coloured}
          adjust={adjust}
          versies={versies}
        />
      ) : (
        <div
          className="flex h-full items-center justify-center"
          onClick={onClickArea}
          onWheel={onWheel}
          style={{ cursor: zoom > 1 ? "grab" : "default" }}
        >
          <div
            className="flex h-full items-center justify-center gap-0.5 transition-transform"
            style={{ transform: `scale(${zoom})` }}
          >
            {orderForDisplay(currentSpread, rightToLeft).map((page) => (
              // De overlay staat absoluut binnen dit vlak, dus het moet net zo
              // groot zijn als de afbeelding zelf — vandaar w-fit en relative.
              <TranslatablePage
                key={page}
                book={book}
                page={page}
                profile={profile}
                fitClass={fitClass}
                translated={translated}
                coloured={coloured}
                versie={versies[page] ?? 0}
                adjust={adjust}
                grid={
                  grid === 0
                    ? null
                    : cellTransform(
                        cells[cell] ?? { row: 0, col: 0 },
                        gridRows,
                        gridCols,
                      )
                }
                onAspect={noteAspect}
              />
            ))}
          </div>
        </div>
      )}

      {atEnd && !dismissedNext && (
        <NextChapterPrompt
          bookId={book.id}
          onDismiss={() => setDismissedNext(true)}
        />
      )}

      {showChrome && (
        <Chrome
          book={book}
          fit={fit}
          setFit={setFit}
          viewMode={viewMode}
          setViewMode={setViewMode}
          doublePage={doublePage}
          setDoublePage={setDoublePage}
          rightToLeft={rightToLeft}
          setRightToLeft={setRtlOverride}
          zoom={zoom}
          setZoom={setZoom}
          spreadIndex={spreadIndex}
          spreadCount={spreads.length}
          currentPage={currentPage}
          pageCount={pageCount}
          crop={crop}
          setCrop={setCrop}
          grid={grid}
          setGrid={(value) => {
            setGrid(value);
            setCell(0);
          }}
          contrast={contrast}
          setContrast={setContrast}
          translated={translated}
          setTranslated={setTranslated}
          coloured={coloured}
          setColoured={setColoured}
          onRemade={opnieuwGemaakt}
          onSeek={setPage}
          onClose={() => onClose(pendingPercent.current ?? 0)}
        />
      )}
    </div>
  );
}

interface VerticalProps {
  book: BookDetail;
  pageCount: number;
  profile: string;
  initialPage: number;
  onVisiblePage: (page: number) => void;
  onAspect: (index: number, width: number, height: number) => void;
  translated: boolean;
  coloured: boolean;
  adjust: { crop: boolean; contrast: number };
  versies: Record<number, number>;
}

/** Doorlopende verticale weergave voor webtoons — daar zijn "pagina's" een
 * kunstmatige knip en wil je gewoon scrollen. */
function VerticalReader({
  book,
  pageCount,
  profile,
  initialPage,
  onVisiblePage,
  onAspect,
  translated,
  coloured,
  adjust,
  versies,
}: VerticalProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const jumped = useRef(false);
  // Waar je nu bent, buiten de render om: de observer schrijft hem en het
  // herschikken na een draai leest hem.
  const visible = useRef(initialPage);
  const [loaded, setLoaded] = useState<Set<number>>(() => new Set());

  // Naar de huidige pagina springen vóór de observer aan gaat. Zonder dit
  // begint de doorlopende modus altijd bovenaan en meldt de observer meteen
  // pagina 1 terug — je verliest dan je plek bij elke moduswissel.
  //
  // De sprong wordt een paar keer herhaald: de beelden laden lui, dus de
  // hoogte van alles erboven staat pas na een paar frames vast en één keer
  // scrollen landt dan te hoog.
  useEffect(() => {
    if (jumped.current) return;
    if (initialPage <= 0) {
      jumped.current = true;
      return;
    }
    const container = containerRef.current;
    if (!container) return;

    let attempts = 0;
    const timer = window.setInterval(() => {
      const target = container.querySelector<HTMLElement>(
        `[data-page="${initialPage}"]`,
      );
      if (target) target.scrollIntoView({ block: "start" });
      attempts += 1;
      if (attempts >= 8) {
        window.clearInterval(timer);
        jumped.current = true;
      }
    }, 150);
    return () => window.clearInterval(timer);
  }, [initialPage]);

  // Daarna is elke wijziging van buitenaf een sprong: de tijdlijn, of een tik
  // op een hoofdstukknop. Zonder dit deed de balk in deze weergave niets — hij
  // veranderde de teller wel, maar niemand scrolde.
  //
  // De vergelijking met wat de observer als laatste meldde is het verschil
  // tussen "jij vraagt om pagina 30" en "de observer zag zojuist pagina 30
  // langskomen"; op dat tweede reageren zou het scrollen bij elke pagina
  // onderbreken.
  useEffect(() => {
    if (!jumped.current || initialPage === visible.current) return;
    const doel = containerRef.current?.querySelector<HTMLElement>(
      `[data-page="${initialPage}"]`,
    );
    if (!doel) return;
    visible.current = initialPage;
    doel.scrollIntoView({ block: "start" });
  }, [initialPage]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // De observer wordt meteen aangemaakt en negeert meldingen zolang de
    // sprong nog loopt. Eerder stond hier `if (!jumped.current) return` vóór
    // het aanmaken — maar een ref laat een effect niet opnieuw draaien, dus de
    // observer kwam er nooit en het paginanummer bleef staan waar je begon.
    const observer = new IntersectionObserver(
      (entries) => {
        if (!jumped.current) return;
        for (const entry of entries) {
          if (entry.isIntersecting) {
            const index = Number((entry.target as HTMLElement).dataset.page);
            if (!Number.isNaN(index)) {
              visible.current = index;
              onVisiblePage(index);
            }
          }
        }
      },
      { root: container, threshold: 0.5 },
    );
    for (const child of container.querySelectorAll("[data-page]"))
      observer.observe(child);
    return () => observer.disconnect();
  }, [onVisiblePage, pageCount]);

  // Draaien van staand naar liggend verandert de hoogte van elke pagina, en
  // daarmee schuift alles onder je weg. De browser probeert je positie te
  // bewaren maar rekent met de oude hoogtes, dus je landt tientallen pagina's
  // verderop. Na een maatverandering zetten we je daarom terug op de pagina
  // waar je was.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let timer = 0;
    const observer = new ResizeObserver(() => {
      window.clearTimeout(timer);
      // Even wachten tot het herschikken klaar is; tijdens het draaien komen
      // er tientallen meldingen achter elkaar.
      timer = window.setTimeout(() => {
        const doel = container.querySelector<HTMLElement>(
          `[data-page="${visible.current}"]`,
        );
        if (doel) doel.scrollIntoView({ block: "start" });
      }, 200);
    });
    observer.observe(container);
    return () => {
      window.clearTimeout(timer);
      observer.disconnect();
    };
  }, []);

  return (
    <div ref={containerRef} className="h-full overflow-y-auto">
      <div className="mx-auto flex max-w-3xl flex-col">
        {Array.from({ length: pageCount }, (_, index) => (
          // Zolang een pagina nog niet geladen is houdt de wrapper 2:3 aan, de
          // verhouding van vrijwel elke stripbladzijde. Zonder die reservering
          // hebben ongeladen pagina's hoogte nul, schuift alles onder je weg
          // zodra ze binnenkomen, en landt geen enkele scrollpositie goed.
          <VerticalPage
            key={index}
            book={book}
            index={index}
            profile={profile}
            adjust={adjust}
            translated={translated}
            coloured={coloured}
            versie={versies[index] ?? 0}
            loaded={loaded.has(index)}
            onLoaded={(width, height) => {
              onAspect(index, width, height);
              setLoaded((current) =>
                current.has(index) ? current : new Set(current).add(index),
              );
            }}
          />
        ))}
      </div>
    </div>
  );
}

interface ChromeProps {
  book: BookDetail;
  fit: FitMode;
  setFit: (value: FitMode) => void;
  viewMode: ViewMode;
  setViewMode: (value: ViewMode) => void;
  doublePage: boolean;
  setDoublePage: (value: boolean) => void;
  rightToLeft: boolean;
  setRightToLeft: (value: boolean) => void;
  zoom: number;
  setZoom: (value: number) => void;
  spreadIndex: number;
  spreadCount: number;
  currentPage: number;
  pageCount: number;
  crop: boolean;
  setCrop: (value: boolean) => void;
  grid: number;
  setGrid: (value: number) => void;
  contrast: number;
  setContrast: (value: number) => void;
  translated: boolean;
  setTranslated: (value: boolean) => void;
  coloured: boolean;
  setColoured: (value: boolean) => void;
  /** Bijhouden dat een pagina opnieuw gemaakt is, zodat de afbeelding ververst. */
  onRemade: (page: number) => void;
  onSeek: (page: number) => void;
  onClose: () => void;
}

function Chrome(props: ChromeProps) {
  // Standaard dicht: een lezer hoort een strip te tonen, geen bedieningspaneel.
  const [showSettings, setShowSettings] = useState(false);
  const tijdlijn = useRef<HTMLInputElement>(null);
  const {
    book,
    fit,
    setFit,
    viewMode,
    setViewMode,
    doublePage,
    setDoublePage,
    rightToLeft,
    setRightToLeft,
    zoom,
    setZoom,
    spreadIndex,
    spreadCount,
    currentPage,
    pageCount,
    crop,
    setCrop,
    grid,
    setGrid,
    contrast,
    setContrast,
    translated,
    setTranslated,
    coloured,
    setColoured,
    onRemade,
    onSeek,
    onClose,
  } = props;

  // Scrollen over de balk bladert. Een eigen luisteraar en geen onWheel, omdat
  // React die passief aanhangt: dan kan preventDefault niet, en scrolt de
  // doorlopende weergave eronder mee terwijl je bladert.
  useEffect(() => {
    const element = tijdlijn.current;
    if (!element) return;
    let rest = 0;
    function onWheel(event: WheelEvent) {
      event.preventDefault();
      const uitkomst = wheelSteps(rest, event.deltaY + event.deltaX);
      rest = uitkomst.rest;
      if (uitkomst.steps === 0) return;
      onSeek(
        Math.min(
          Math.max(0, currentPage + uitkomst.steps),
          Math.max(0, pageCount - 1),
        ),
      );
    }
    element.addEventListener("wheel", onWheel, { passive: false });
    return () => element.removeEventListener("wheel", onWheel);
  }, [currentPage, onSeek, pageCount]);

  return (
    <>
      <div className="absolute inset-x-0 top-0 flex items-center gap-3 bg-ink-900/90 px-4 py-3 text-sm text-slate-200 backdrop-blur">
        <button
          className="rounded px-2 py-1 hover:bg-ink-700"
          onClick={onClose}
        >
          ← Terug
        </button>
        <span className="truncate font-medium">
          {book.series_title}
          {book.number ? ` ${book.number}` : ""}
        </span>
        <TranslationBadge
          bookId={book.id}
          page={currentPage}
          visible={translated}
          onToggle={() => setTranslated(!translated)}
        />
        <ColourBadge
          bookId={book.id}
          page={currentPage}
          visible={coloured}
          onToggle={() => setColoured(!coloured)}
        />
        <span className="ml-auto tabular-nums text-slate-400">
          {currentPage + 1} / {pageCount}
        </span>
      </div>

      <div className="pb-safe absolute inset-x-0 bottom-0 space-y-2 bg-ink-900/90 px-4 pt-3 backdrop-blur">
        {/* De balk loopt altijd van links naar rechts, ook bij manga. Hij
            spiegelen leek consequent met de leesrichting, maar een voortgangs-
            balk is geen pagina: links is begin en rechts is eind, net als in
            elke andere speler. Meespiegelen maakte het juist onvoorspelbaar.

            Hoog genoeg om met een duim te raken: een tik op de balk springt
            naar die pagina, en dat is op een telefoon de snelste manier om
            terug te bladeren. */}
        {/* Bij het begin van het hoofdstuk: de knoppen die het hele hoofdstuk
            klaarzetten. Daar maak je die keuze, niet halverwege — en het is
            precies waar je op de cover staat te kijken. */}
        {currentPage === 0 && (
          <BatchPanel bookId={book.id} currentPage={currentPage} />
        )}
        <input
          ref={tijdlijn}
          type="range"
          min={0}
          max={Math.max(0, pageCount - 1)}
          value={currentPage}
          onChange={(event) => onSeek(Number(event.target.value))}
          aria-label="Pagina kiezen"
          className="h-6 w-full cursor-pointer accent-accent [touch-action:none]"
        />
        {/* Één regel die altijd zichtbaar is: wat je tijdens het lezen echt
            omzet. De rest zit achter "Weergave" — die balk was uitgegroeid tot
            zestien knoppen, en dat is op een telefoon vier regels over je
            strip heen. */}
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-300">
          <Toggle
            active={viewMode === "vertical"}
            onClick={() =>
              setViewMode(viewMode === "paged" ? "vertical" : "paged")
            }
          >
            {viewMode === "vertical" ? "Doorlopend" : "Pagina's"}
          </Toggle>
          <Toggle
            active={translated}
            onClick={() => setTranslated(!translated)}
          >
            Vertaling
          </Toggle>
          {/* Kleur vervangt de pagina zelf; onze tekstvlakken komen er gewoon
              overheen. Daarom kunnen kleur en vertaling samen — en hoeft het
              beeldmodel de ballonnen niet leeg te vegen, wat het niet
              betrouwbaar kan. Pagina's zonder ingekleurde versie vallen
              vanzelf terug op het origineel. */}
          <Toggle
            active={coloured}
            onClick={() => setColoured(!coloured)}
            title="Toon ingekleurde pagina's waar die er zijn"
          >
            Kleur
          </Toggle>
          <Toggle
            active={showSettings}
            onClick={() => setShowSettings(!showSettings)}
          >
            ⚙ Weergave
          </Toggle>
          <span className="ml-auto tabular-nums text-slate-500">
            {spreadIndex + 1} / {spreadCount}
          </span>
        </div>

        {showSettings && (
          <div className="space-y-2 border-t border-ink-700 pt-2 text-xs text-slate-300">
            <div className="flex flex-wrap items-center gap-2">
              <Toggle
                active={doublePage}
                disabled={viewMode === "vertical" || grid > 0}
                onClick={() => setDoublePage(!doublePage)}
              >
                Dubbel
              </Toggle>
              <Toggle
                active={rightToLeft}
                onClick={() => setRightToLeft(!rightToLeft)}
              >
                {rightToLeft ? "Rechts → links" : "Links → rechts"}
              </Toggle>
              <div className="flex gap-1">
                {(["width", "height", "screen"] as FitMode[]).map((mode) => (
                  <Toggle
                    key={mode}
                    active={fit === mode}
                    onClick={() => setFit(mode)}
                  >
                    {mode === "width"
                      ? "Breedte"
                      : mode === "height"
                        ? "Hoogte"
                        : "Passend"}
                  </Toggle>
                ))}
              </div>
              <div className="ml-auto flex items-center gap-1">
                <Toggle
                  active={false}
                  onClick={() => setZoom(Math.max(1, zoom - ZOOM_STEP))}
                >
                  −
                </Toggle>
                <span className="w-12 text-center tabular-nums">
                  {Math.round(zoom * 100)}%
                </span>
                <Toggle
                  active={false}
                  onClick={() => setZoom(Math.min(MAX_ZOOM, zoom + ZOOM_STEP))}
                >
                  +
                </Toggle>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <div className="flex items-center gap-1">
                <span className="text-slate-500">Raster</span>
                {[0, 2, 3].map((value) => (
                  <Toggle
                    key={value}
                    active={grid === value}
                    disabled={viewMode === "vertical"}
                    onClick={() => setGrid(value)}
                    title={
                      value === 0
                        ? "Hele pagina"
                        : `Pagina in ${value}x2 cellen; bladeren gaat per cel`
                    }
                  >
                    {value === 0 ? "Uit" : `${value}×2`}
                  </Toggle>
                ))}
              </div>
              <Toggle
                active={crop}
                onClick={() => setCrop(!crop)}
                title="Egale rand rond de pagina wegsnijden — scheelt op een klein scherm zo een vijfde"
              >
                Bijsnijden
              </Toggle>
              <Toggle
                active={contrast > 100}
                onClick={() => setContrast(contrast > 100 ? 100 : 140)}
                title="Grijsbereik oprekken; helpt bij bleke scans"
              >
                Contrast
              </Toggle>
              <TranslateControl
                bookId={book.id}
                currentPage={currentPage}
                translated={translated}
                setActive={setTranslated}
                onRemade={onRemade}
              />
            </div>

            <RedoControl
              bookId={book.id}
              currentPage={currentPage}
              translated={translated}
              onRemade={onRemade}
            />

            <p className="text-slate-500">
              Pijltjes bladeren, D dubbel, V doorlopend, F passend, Esc sluit.
            </p>
          </div>
        )}
      </div>
    </>
  );
}

/**
 * "Volgende hoofdstuk?" als je aan het eind bent.
 *
 * Staat het nog niet op schijf, dan haalt de knop het eerst op — bij een
 * abonnement is het volgende hoofdstuk vaak nog een verwijzing, en dan is
 * "bestaat niet" het verkeerde antwoord.
 */
function NextChapterPrompt({
  bookId,
  onDismiss,
}: {
  bookId: number;
  onDismiss: () => void;
}) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const { data } = useQuery({
    queryKey: ["next-chapter", bookId],
    queryFn: () => api.nextChapter(bookId),
    retry: (_count, error) =>
      !(error instanceof ApiError && error.status === 404),
    staleTime: Infinity,
  });

  if (!data) return null;

  const label = [
    data.volume ? `Deel ${data.volume}` : null,
    data.number ? `#${data.number}` : null,
  ]
    .filter(Boolean)
    .join(" ");

  async function go() {
    if (data!.has_file) {
      navigate(`/lezen/${data!.book_id}`);
      return;
    }
    setBusy(true);
    try {
      await api.downloadChapter(data!.book_id);
      navigate(`/lezen/${data!.book_id}`);
    } catch {
      setBusy(false);
    }
  }

  return (
    <div className="absolute inset-x-0 bottom-24 z-10 mx-auto w-fit max-w-[90%] rounded-lg bg-ink-800/95 p-3 text-sm shadow-lg backdrop-blur">
      <p className="text-slate-300">
        Volgende: <span className="text-slate-100">{label || data.title}</span>
      </p>
      <div className="mt-2 flex gap-2">
        <button
          onClick={() => void go()}
          disabled={busy}
          className="rounded bg-accent px-3 py-1.5 text-ink-900 disabled:opacity-50"
        >
          {busy ? "Ophalen…" : data.has_file ? "Lezen" : "Ophalen en lezen"}
        </button>
        <button
          onClick={onDismiss}
          className="rounded bg-ink-700 px-3 py-1.5 text-slate-300"
        >
          Later
        </button>
      </div>
    </div>
  );
}

/**
 * Eén pagina met wat er aan vertaling voor klaarligt (M8).
 *
 * In de tekststand komt er een overlay overheen; in de beeldstanden is de hele
 * pagina hertekend en wordt de afbeelding zelf vervangen. Welke van de twee het
 * wordt, weet alleen de server — vandaar dat de vertaalquery hier bepaalt welke
 * bron de img krijgt.
 */
function TranslatablePage({
  book,
  page,
  profile,
  fitClass,
  translated,
  coloured,
  versie,
  adjust,
  grid,
  onAspect,
}: {
  book: BookDetail;
  page: number;
  profile: string;
  fitClass: string;
  translated: boolean;
  coloured: boolean;
  /** Telt op als deze pagina opnieuw gemaakt is; hoort in de URL thuis. */
  versie: number;
  adjust: { crop: boolean; contrast: number };
  grid: GridTransform | null;
  onAspect: (index: number, width: number, height: number) => void;
}) {
  const { data } = usePageTranslation(book.id, page, translated);
  const { data: kleur } = usePageColour(
    book.id,
    page,
    translated ? data?.target_lang : undefined,
    coloured,
  );
  const [geenKleur, setGeenKleur] = useState(false);
  // Maar na het inkleuren ís hij er wel. Zonder dit blijft de eerdere 404
  // gelden en kijk je naar het origineel terwijl je net betaald hebt.
  useEffect(() => {
    setGeenKleur(false);
  }, [versie]);

  return (
    // De overlay staat absoluut binnen dit vlak, dus het moet net zo groot zijn
    // als de afbeelding zelf — vandaar w-fit en relative. Bij rasterzoom
    // schaalt en verschuift ditzelfde vlak, zodat de vertaling meebeweegt.
    //
    // Géén container-type hier: dat legt inline-size-containment op, en dan mag
    // de afbeelding de breedte niet meer bepalen. `w-fit` valt daardoor terug
    // op nul en de pagina verdwijnt volledig. De containercontext hoort op de
    // overlay zelf, die wél een vaste maat heeft.
    <div
      className="relative w-fit"
      style={
        grid
          ? {
              transform: `scale(${grid.scale}) translate(${grid.translateX}%, ${grid.translateY}%)`,
              transformOrigin: "center",
            }
          : undefined
      }
    >
      <img
        src={pageSource(book.id, page, profile, adjust, versie, {
          translated,
          coloured: coloured && !geenKleur,
          fullPage: data?.full_page === true,
          lang: data?.target_lang,
          colour: kleur,
        })}
        alt={`Pagina ${page + 1}`}
        className={`object-contain ${fitClass}`}
        draggable={false}
        onError={() => setGeenKleur(true)}
        onLoad={(event) =>
          onAspect(
            page,
            event.currentTarget.naturalWidth,
            event.currentTarget.naturalHeight,
          )
        }
      />
      <TranslationOverlay
        bookId={book.id}
        pageIndex={page}
        enabled={translated}
      />
    </div>
  );
}

const BATCH_LABELS: Record<BatchKind, { knop: string; wat: string }> = {
  tekst: { knop: "Tekst", wat: "tekstvlakken over het origineel" },
  hertekend: {
    knop: "Ingetekend",
    wat: "de hele pagina hertekend mét vertaling",
  },
  kleuren: { knop: "Inkleuren", wat: "ingekleurd" },
};

/**
 * Het hele hoofdstuk in één keer, via de batch van Gemini.
 *
 * Staat bij het begin van een hoofdstuk, want dat is waar je die keuze maakt:
 * je zet het klaar en komt later terug. Gemeten duurt een batch minuten
 * ongeacht het aantal pagina's — voor de pagina waar je nú op staat is de
 * gewone knop sneller.
 *
 * Nooit starten zonder het bedrag te tonen. Dit is de enige knop in de app die
 * met één druk een heel hoofdstuk afrekent.
 */
function BatchPanel({
  bookId,
  currentPage,
}: {
  bookId: number;
  currentPage: number;
}) {
  const queryClient = useQueryClient();
  const { data: status } = useQuery({
    queryKey: ["translation-status", bookId],
    queryFn: () => api.translationStatus(bookId),
  });
  const { data: klus } = useQuery({
    queryKey: ["batch", bookId],
    queryFn: () => api.batchStatus(bookId),
    // Tijdens het werk meekijken; daarna niet meer pollen dan nodig.
    refetchInterval: (query) =>
      query.state.data?.state === "bezig" ? 15000 : false,
  });
  const [vraag, setVraag] = useState<BatchPlan | null>(null);
  const [bezig, setBezig] = useState(false);
  const [fout, setFout] = useState<string | null>(null);

  if (!status?.configured) return null;

  async function vraagPrijs(kind: BatchKind) {
    setFout(null);
    setBezig(true);
    try {
      setVraag(await api.batchPlan(bookId, kind));
    } catch (exc) {
      setFout(
        exc instanceof ApiError ? exc.message : "Kon de klus niet inschatten.",
      );
    } finally {
      setBezig(false);
    }
  }

  async function starten(kind: BatchKind) {
    setVraag(null);
    setBezig(true);
    setFout(null);
    try {
      await api.startBatch(bookId, kind);
      await queryClient.invalidateQueries({ queryKey: ["batch", bookId] });
    } catch (exc) {
      setFout(exc instanceof ApiError ? exc.message : "Starten mislukt.");
    } finally {
      setBezig(false);
    }
  }

  const loopt = klus?.state === "bezig";

  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-slate-300">
      <span className="text-slate-500">Hele hoofdstuk</span>
      {(Object.keys(BATCH_LABELS) as BatchKind[]).map((kind) => (
        <Toggle
          key={kind}
          active={false}
          disabled={bezig || loopt}
          onClick={() => void vraagPrijs(kind)}
          title={`Het hele hoofdstuk ${BATCH_LABELS[kind].wat}, op de achtergrond`}
        >
          {BATCH_LABELS[kind].knop}
        </Toggle>
      ))}

      {/* De bevestiging met het bedrag erin. Zonder dit zou één tik een
          hoofdstuk van tweehonderd pagina's afrekenen. */}
      {vraag && (
        <span className="flex flex-wrap items-center gap-1 text-amber-300">
          {vraag.pages === 0 ? (
            <>
              Er is niets meer te doen.
              <Toggle active={false} onClick={() => setVraag(null)}>
                Sluiten
              </Toggle>
            </>
          ) : (
            <>
              {vraag.pages} pagina&apos;s × ${vraag.price_per_page.toFixed(3)} ={" "}
              <strong className="tabular-nums">
                ${vraag.total.toFixed(2)}
              </strong>
              <span className="text-slate-500">
                (batch, {Math.round(vraag.batch_factor * 100)}% van het gewone
                tarief)
              </span>
              <Toggle active={false} onClick={() => void starten(vraag.kind)}>
                Starten
              </Toggle>
              <Toggle active={false} onClick={() => setVraag(null)}>
                Annuleren
              </Toggle>
            </>
          )}
        </span>
      )}

      {klus && !vraag && (
        <span
          className={
            klus.state === "mislukt" ? "text-danger" : "text-slate-400"
          }
        >
          {klus.state === "bezig"
            ? `Bezig: ${BATCH_LABELS[klus.kind].knop.toLowerCase()}, ${klus.done}/${klus.total}`
            : klus.state === "klaar"
              ? `Klaar: ${klus.done} pagina's${klus.failed ? `, ${klus.failed} mislukt` : ""}`
              : (klus.error ?? "Mislukt.")}
        </span>
      )}
      {fout && <span className="text-danger">{fout}</span>}
      {currentPage > 0 && !loopt && !klus && (
        <span className="text-slate-500">
          vanaf het begin van dit hoofdstuk
        </span>
      )}
    </div>
  );
}

/** Wat inkleuren nu kost, in de stand die je hebt ingesteld. */
function useColourPrice(): string {
  const { data } = useQuery({
    queryKey: ["translate-mode"],
    queryFn: api.translateMode,
    staleTime: 5 * 60 * 1000,
  });
  const stand = data?.colour_mode ?? "image_fast";
  const prijs = data?.costs?.[stand];
  return prijs === undefined ? "" : ` (~$${prijs.toFixed(2)})`;
}

/**
 * Inkleuren, met een vraag als de pagina al kleur heeft.
 *
 * Gedeeld door de gewone knop en het opnieuw-paneel, want de vraag hoort bij
 * het inkleuren zelf en niet bij één van de twee knoppen. De server antwoordt
 * met 412 als de tekenaar de pagina al kleurde; dat is geen storing maar een
 * bevestiging die je nog kunt geven.
 */
function useColourise(
  bookId: number,
  page: number,
  lang: string | undefined,
  onRemade: (page: number) => void,
) {
  const [busy, setBusy] = useState(false);
  const [fout, setFout] = useState<string | null>(null);
  const [vraag, setVraag] = useState(false);
  const [klaar, setKlaar] = useState(false);

  const start = useCallback(
    async (force: boolean) => {
      setBusy(true);
      setFout(null);
      setVraag(false);
      setKlaar(false);
      try {
        await api.colourisePage(bookId, page, lang, force || undefined);
        // De afbeelding staat op hetzelfde adres, dus zonder dit blijft de
        // vorige versie in beeld.
        onRemade(page);
        setKlaar(true);
      } catch (exc) {
        if (exc instanceof ApiError && exc.status === 412) setVraag(true);
        else
          setFout(exc instanceof ApiError ? exc.message : "Inkleuren mislukt.");
      } finally {
        setBusy(false);
      }
    },
    [bookId, page, lang, onRemade],
  );

  return { busy, fout, vraag, klaar, start, annuleer: () => setVraag(false) };
}

/**
 * Iets nog een keer laten maken.
 *
 * Een vertaling of inkleuring die er eenmaal ligt wordt nooit vanzelf
 * vervangen — dat zou geld kosten bij elke pagina die je terugbladert. Maar
 * soms is de opdracht beter geworden of viel het antwoord tegen, en dan is dit
 * de enige manier om eroverheen te gaan. Bewust achter de instellingen: het
 * kost per klik ongeveer evenveel als de eerste keer.
 */
function RedoControl({
  bookId,
  currentPage,
  translated,
  onRemade,
}: {
  bookId: number;
  currentPage: number;
  translated: boolean;
  onRemade: (page: number) => void;
}) {
  const queryClient = useQueryClient();
  // Dezelfde sleutels als de vertaalknop, dus dit kost geen extra verzoek.
  const { data: vertaling } = usePageTranslation(bookId, currentPage, true);
  const { data: status } = useQuery({
    queryKey: ["translation-status", bookId],
    queryFn: () => api.translationStatus(bookId),
  });
  const [busy, setBusy] = useState(false);
  const [fout, setFout] = useState<string | null>(null);
  const [klaar, setKlaar] = useState<string | null>(null);
  const prijs = useColourPrice();
  const kleur = useColourise(
    bookId,
    currentPage,
    translated ? vertaling?.target_lang : undefined,
    onRemade,
  );

  if (!status?.configured) return null;

  // Opnieuw vertalen doet het in dezelfde stand als wat er ligt: heb je deze
  // pagina laten hertekenen, dan wil je geen tekstvlakken terugkrijgen.
  async function opnieuwVertalen() {
    if (!vertaling) return;
    setBusy(true);
    setFout(null);
    setKlaar(null);
    try {
      if (vertaling.full_page) {
        await api.translatePageFully(bookId, currentPage, {
          mode: vertaling.mode,
          force: true,
        });
      } else {
        await api.makePageTranslation(bookId, currentPage, undefined, true);
      }
      await queryClient.invalidateQueries({
        queryKey: ["translation", bookId, currentPage],
      });
      onRemade(currentPage);
      setKlaar("Opnieuw vertaald.");
    } catch (exc) {
      setFout(exc instanceof ApiError ? exc.message : "Vertalen mislukt.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-ink-700 pt-2">
      <span className="text-slate-500">Opnieuw</span>
      <Toggle
        active={false}
        disabled={busy || kleur.busy || !vertaling}
        onClick={() => void opnieuwVertalen()}
        title={
          vertaling
            ? "Deze pagina opnieuw laten vertalen, in dezelfde stand als wat er ligt"
            : "Deze pagina is nog niet vertaald"
        }
      >
        {busy ? "Bezig…" : "Vertalen"}
      </Toggle>
      <Toggle
        active={false}
        disabled={busy || kleur.busy}
        onClick={() => void kleur.start(true)}
        title={`Deze pagina opnieuw laten inkleuren${prijs}, ook als hij al kleur heeft`}
      >
        {kleur.busy ? "Bezig…" : "Inkleuren"}
      </Toggle>
      {(fout ??
        kleur.fout ??
        klaar ??
        (kleur.klaar ? "Opnieuw ingekleurd." : null)) && (
        <span
          className={`max-w-[16rem] truncate ${(fout ?? kleur.fout) ? "text-danger" : "text-slate-400"}`}
        >
          {fout ?? kleur.fout ?? klaar ?? "Opnieuw ingekleurd."}
        </span>
      )}
    </div>
  );
}

/**
 * Welke van de drie versies van deze pagina je te zien krijgt.
 *
 * De volgorde deed er eerder niet toe omdat kleur en hertekend elkaar niet
 * raakten. Nu wel: is de ingekleurde pagina gemaakt ván de hertekende
 * vertaling, dan zit de Nederlandse tekst er al in gebakken en is dát het
 * beeld dat je wilt zien. Zonder deze voorrang won de hertekende pagina altijd
 * en kreeg je de kleur nooit te zien, terwijl er wel voor betaald was.
 */
function pageSource(
  bookId: number,
  index: number,
  profile: string,
  adjust: { crop: boolean; contrast: number },
  versie: number,
  opties: {
    translated: boolean;
    coloured: boolean;
    fullPage: boolean;
    lang: string | undefined;
    colour: { available: boolean; translated: boolean } | undefined;
  },
): string {
  const { translated, coloured, fullPage, lang, colour } = opties;
  if (coloured && colour?.available) {
    // Alleen om de taal vragen als die versie er ook is; anders krijg je het
    // ingekleurde origineel met de oorspronkelijke tekst erin.
    return imageUrl.colour(
      bookId,
      index,
      colour.translated ? lang : undefined,
      versie,
    );
  }
  if (translated && fullPage) {
    return imageUrl.fullTranslation(bookId, index, undefined, versie);
  }
  return imageUrl.page(bookId, index, profile, adjust);
}

/**
 * Vertaalknop met voortgang (M8).
 *
 * Verschijnt alleen als er een Gemini-sleutel is: zonder sleutel zou hij je op
 * een 409 laten lopen, en dat is geen keuze die je in een lezer wilt maken.
 * "Vertaal de rest" zet het boek in de wachtrij vanaf waar je bent — wat je al
 * gelezen hebt hoeft niet meer.
 */
function TranslateControl({
  bookId,
  currentPage,
  translated,
  setActive,
  onRemade,
}: {
  bookId: number;
  currentPage: number;
  translated: boolean;
  setActive: (value: boolean) => void;
  onRemade: (page: number) => void;
}) {
  const queryClient = useQueryClient();
  const { data: vertaling } = usePageTranslation(bookId, currentPage, true);
  const { data: status } = useQuery({
    queryKey: ["translation-status", bookId],
    queryFn: () => api.translationStatus(bookId),
    // Terwijl de wachtrij loopt willen we de teller zien oplopen; daarna niet
    // meer pollen dan nodig.
    refetchInterval: (query) =>
      (query.state.data?.queued ?? 0) > 0 ? 4000 : false,
  });

  // Wat de knop doet staat in de instellingen, los van wat er vanzelf gebeurt:
  // vanzelf mag goedkoop zijn, en als jij zelf op een pagina drukt is dat juist
  // omdat díé pagina het waard is.
  const { data: standen } = useQuery({
    queryKey: ["translate-mode"],
    queryFn: api.translateMode,
    staleTime: 5 * 60 * 1000,
  });

  const [busy, setBusy] = useState<string | null>(null);
  const [fout, setFout] = useState<string | null>(null);
  const prijs = useColourPrice();
  // De taal alleen meesturen als je de vertaling aan hebt staan: anders maak je
  // een ingekleurde Nederlandse pagina die je vervolgens niet te zien krijgt.
  const kleur = useColourise(
    bookId,
    currentPage,
    translated ? vertaling?.target_lang : undefined,
    onRemade,
  );

  if (!status?.configured) return null;

  const knopStand = standen?.button_mode ?? "image_fast";

  const total = status.page_count ?? 0;
  const done = status.translated;

  function refresh() {
    void queryClient.invalidateQueries({
      queryKey: ["translation", bookId, currentPage],
    });
    void queryClient.invalidateQueries({
      queryKey: ["translation-status", bookId],
    });
  }

  async function translateThisPage() {
    setBusy("tekst");
    setFout(null);
    try {
      await api.makePageTranslation(bookId, currentPage);
      setActive(true);
      refresh();
    } catch (exc) {
      // Niet stil laten mislukken. Een rate limit of een lege sleutel zag je
      // hiervoor niet: de knop ging terug naar rust en er gebeurde niets, wat
      // niet te onderscheiden is van "deze pagina heeft geen tekst".
      setFout(exc instanceof ApiError ? exc.message : "Vertalen mislukt.");
    } finally {
      setBusy(null);
    }
  }

  async function translateFully(mode: TranslateMode) {
    setBusy(mode);
    setFout(null);
    try {
      await api.translatePageFully(bookId, currentPage, { mode });
      setActive(true);
      refresh();
    } catch (exc) {
      setFout(exc instanceof ApiError ? exc.message : "Vertalen mislukt.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex items-center gap-1">
      <Toggle
        active={false}
        disabled={busy !== null}
        onClick={() => void translateThisPage()}
      >
        {busy === "tekst" ? "Bezig…" : "Deze pagina"}
      </Toggle>
      {/* Inkleuren is geen vertaling: het verandert niets aan de tekst en komt
          nooit in de plaats van een vertaalde pagina. Het staat hier omdat het
          hetzelfde beeldmodel gebruikt en per pagina evenveel kost. */}
      <Toggle
        active={false}
        disabled={busy !== null || kleur.busy}
        onClick={() => void kleur.start(false)}
        title={`Deze pagina laten inkleuren${prijs}. Zet daarna 'Kleur' aan.`}
      >
        {kleur.busy ? "Bezig…" : "Inkleuren"}
      </Toggle>
      {/* Eén knop, met de stand die jij hebt gekozen. Eerder stonden hier
          "Volledig" en "Volledig+" naast elkaar, en dat zei niet wat het deed
          of wat het kostte. */}
      {knopStand !== "text" && (
        <Toggle
          active={false}
          disabled={busy !== null}
          onClick={() => void translateFully(knopStand)}
          title={`${BUTTON_LABELS[knopStand]} — te wijzigen bij Instellingen → Vertaling`}
        >
          {busy === knopStand ? "Bezig…" : BUTTON_SHORT[knopStand]}
        </Toggle>
      )}
      <Toggle
        active={false}
        disabled={status.queued > 0 || busy !== null}
        onClick={() => {
          void api
            .translateBook(bookId, { from_page: currentPage })
            .then(() =>
              queryClient.invalidateQueries({
                queryKey: ["translation-status", bookId],
              }),
            )
            .catch(() => {
              /* zacht falen */
            });
        }}
      >
        {status.queued > 0 ? `In wachtrij: ${status.queued}` : "Rest vertalen"}
      </Toggle>
      {/* Hoever de wachtrij is, als balkje. Vertalen duurt tientallen seconden
          per pagina; een teller alleen laat je raden of er iets gebeurt. */}
      <span className="flex items-center gap-2">
        {total > 0 && (
          <span
            className="h-1.5 w-16 overflow-hidden rounded-full bg-ink-700"
            aria-hidden
          >
            <span
              className="block h-full rounded-full bg-accent transition-[width]"
              style={{ width: `${Math.round((done / total) * 100)}%` }}
            />
          </span>
        )}
        <span className="tabular-nums text-slate-500">
          {done}/{total}
        </span>
      </span>

      {/* Al kleur op de pagina? Dan is inkleuren overschilderen: het model
          vervangt het palet van de tekenaar door zijn eigen aquarel. Vragen
          dus, in plaats van het geld uitgeven en het daarna uitleggen. */}
      {kleur.vraag && (
        <span className="flex items-center gap-1 text-amber-300">
          Al in kleur — toch overschilderen?
          <Toggle active={false} onClick={() => void kleur.start(true)}>
            Ja
          </Toggle>
          <Toggle active={false} onClick={kleur.annuleer}>
            Nee
          </Toggle>
        </span>
      )}

      {(busy !== null ||
        fout !== null ||
        kleur.busy ||
        kleur.fout ||
        kleur.klaar) && (
        <span
          className={`max-w-[16rem] truncate ${(fout ?? kleur.fout) ? "text-danger" : "text-slate-400"}`}
        >
          {fout ??
            kleur.fout ??
            (kleur.busy
              ? "Bezig met inkleuren…"
              : busy !== null
                ? "Bezig met vertalen…"
                : "Ingekleurd — zet 'Kleur' aan om het te zien.")}
        </span>
      )}
    </div>
  );
}

function Toggle({
  active,
  disabled,
  onClick,
  title,
  children,
}: {
  active: boolean;
  disabled?: boolean;
  onClick: () => void;
  title?: string;
  children: React.ReactNode;
}) {
  return (
    <button
      disabled={disabled}
      onClick={onClick}
      title={title}
      className={`rounded px-2 py-1 transition ${
        active
          ? "bg-accent text-ink-900"
          : "bg-ink-700 text-slate-200 hover:bg-ink-600"
      } ${disabled ? "cursor-not-allowed opacity-40" : ""}`}
    >
      {children}
    </button>
  );
}

/**
 * Wat de knop in de lezer doet, kort en in het lang.
 *
 * De richtprijs staat erbij omdat dit de enige plek in de app is waar één tik
 * meteen geld kost. "Volledig+" zei dat niet — dit wel.
 */
const BUTTON_SHORT: Record<TranslateMode, string> = {
  text: "Tekstvlakken",
  image_fast: "Hertekenen",
  image_pro: "Hertekenen (zwaar)",
};

const BUTTON_LABELS: Record<TranslateMode, string> = {
  text: "Tekstvlakken over de pagina (~$0,002 per pagina)",
  image_fast:
    "Hele pagina hertekenen met het snelle beeldmodel (~$0,07 per pagina)",
  image_pro:
    "Hele pagina hertekenen met het zware beeldmodel (~$0,13 per pagina)",
};

/**
 * Wat er voor deze pagina klaarligt, klein en in de hoek.
 *
 * Zonder dit is er geen verschil te zien tussen "niet vertaald", "vertaald maar
 * uitgezet" en "je kijkt nu naar een hertekende pagina" — terwijl dat laatste
 * betekent dat je niet op een ballon kunt tikken voor het origineel. Een tik
 * op het merkje zet de vertaling aan of uit.
 */
function TranslationBadge({
  bookId,
  page,
  visible,
  onToggle,
}: {
  bookId: number;
  page: number;
  visible: boolean;
  onToggle: () => void;
}) {
  // Ook opvragen als de vertaling uitstaat: anders weet je niet dát er iets
  // ligt. Dezelfde query als de overlay, dus samen één verzoek per pagina.
  const { data } = usePageTranslation(bookId, page, true);
  if (!data) return null;

  const hertekend = data.full_page;
  const label = hertekend ? "Hertekend" : "Tekstvlakken";

  return (
    <button
      onClick={onToggle}
      title={
        `${label} — ${MODE_NAMES[data.mode] ?? data.mode}. ` +
        (visible
          ? "Tik om het origineel te zien."
          : "Tik om de vertaling te tonen.") +
        (hertekend
          ? " Bij een hertekende pagina kun je niet op losse ballonnen tikken."
          : "")
      }
      aria-pressed={visible}
      className={`rounded-full px-2 py-0.5 text-xs ${
        visible ? "bg-accent text-ink-900" : "bg-ink-700 text-slate-400"
      }`}
    >
      <span aria-hidden>{hertekend ? "▣" : "💬"}</span>
      <span className="ml-1 hidden sm:inline">{label}</span>
    </button>
  );
}

/**
 * Of er kleur is voor deze pagina, en van wie.
 *
 * Naast het vertaalmerkje, met dezelfde werking: het zegt wat er ligt en één
 * tik zet het aan of uit. Een pagina die de tekenaar zelf al kleurde krijgt
 * een eigen tekst — daar valt niets in te kleuren, en dat is iets anders dan
 * "nog niet gedaan".
 */
function ColourBadge({
  bookId,
  page,
  visible,
  onToggle,
}: {
  bookId: number;
  page: number;
  lang?: string;
  visible: boolean;
  onToggle: () => void;
}) {
  // Ook als kleur uitstaat: anders weet je niet dát er iets ligt.
  const { data } = usePageColour(bookId, page, undefined, true);
  if (!data || (!data.available && !data.native)) return null;

  const eigen = data.native;
  const label = eigen ? "Al in kleur" : "Kleur";

  return (
    <button
      onClick={eigen ? undefined : onToggle}
      disabled={eigen}
      title={
        eigen
          ? "Deze pagina is van zichzelf in kleur; inkleuren zou het palet van de tekenaar vervangen."
          : visible
            ? "Ingekleurd — tik om het origineel te zien."
            : "Er ligt een ingekleurde versie. Tik om die te tonen."
      }
      aria-pressed={eigen ? undefined : visible}
      className={`rounded-full px-2 py-0.5 text-xs ${
        eigen
          ? "bg-ink-800 text-slate-500"
          : visible
            ? "bg-accent text-ink-900"
            : "bg-ink-700 text-slate-400"
      }`}
    >
      <span aria-hidden>{eigen ? "🖌" : "🎨"}</span>
      <span className="ml-1 hidden sm:inline">{label}</span>
    </button>
  );
}

/** Voor in de uitleg bij het merkje; korter dan de volle omschrijving. */
const MODE_NAMES: Record<string, string> = {
  text: "taalmodel met tekstvlakken",
  image_fast: "beeldmodel (snel)",
  image_pro: "beeldmodel (zwaar)",
};

/**
 * Eén pagina in de doorlopende weergave.
 *
 * Het verschil met de paginaweergave zat hier: die koos al tussen het origineel
 * en een hertekende pagina, deze toonde altijd het origineel. Een pagina die je
 * met het beeldmodel had laten hertekenen leek daardoor gewoon onvertaald — de
 * overlay houdt zich bij een hertekende pagina namelijk stil, want dan zou de
 * tekst dubbel staan.
 *
 * De vertaling wordt pas opgevraagd als de afbeelding er is. Een doorlopende
 * weergave zet alle pagina's tegelijk in de dom; zonder die grens zou het
 * openen van een hoofdstuk honderden verzoeken tegelijk opleveren.
 */
function VerticalPage({
  book,
  index,
  profile,
  adjust,
  translated,
  coloured,
  versie,
  loaded,
  onLoaded,
}: {
  book: BookDetail;
  index: number;
  profile: string;
  adjust: { crop: boolean; contrast: number };
  translated: boolean;
  coloured: boolean;
  /** Telt op als deze pagina opnieuw gemaakt is; hoort in de URL thuis. */
  versie: number;
  loaded: boolean;
  onLoaded: (width: number, height: number) => void;
}) {
  const { data } = usePageTranslation(book.id, index, translated && loaded);
  const { data: kleur } = usePageColour(
    book.id,
    index,
    translated ? data?.target_lang : undefined,
    coloured && loaded,
  );
  // Niet elke pagina is ingekleurd; dat merken we aan de afbeelding zelf in
  // plaats van er vooraf naar te vragen — dat scheelt een verzoek per pagina.
  const [geenKleur, setGeenKleur] = useState(false);
  // Maar na het inkleuren ís hij er wel. Zonder dit blijft de eerdere 404
  // gelden en kijk je naar het origineel terwijl je net betaald hebt.
  useEffect(() => {
    setGeenKleur(false);
  }, [versie]);

  return (
    <div
      data-page={index}
      className="relative w-full [container-type:inline-size]"
      style={loaded ? undefined : { aspectRatio: "2 / 3" }}
    >
      <img
        src={pageSource(book.id, index, profile, adjust, versie, {
          translated,
          coloured: coloured && !geenKleur,
          fullPage: data?.full_page === true,
          lang: data?.target_lang,
          colour: kleur,
        })}
        alt={`Pagina ${index + 1}`}
        className="w-full"
        loading="lazy"
        draggable={false}
        onError={() => setGeenKleur(true)}
        onLoad={(event) =>
          onLoaded(
            event.currentTarget.naturalWidth,
            event.currentTarget.naturalHeight,
          )
        }
      />
      {loaded && (
        <TranslationOverlay
          bookId={book.id}
          pageIndex={index}
          enabled={translated}
        />
      )}
    </div>
  );
}
