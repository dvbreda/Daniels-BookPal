import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useNavigate } from "react-router-dom";

import { ApiError, api, imageUrl } from "../api/client";
import type { BookDetail, TranslateMode } from "../api/types";
import { pickPageProfile } from "../lib/profile";
import { useStoredState } from "../lib/useStoredState";
import type { GridTransform } from "./grid";
import { cellOrder, cellTransform } from "./grid";
import { TranslationOverlay } from "./TranslationOverlay";
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
  onClose: () => void;
}

export function ComicReader({ book, onClose }: Props) {
  const pageCount = book.page_count ?? 0;
  const profile = useMemo(() => pickPageProfile(), []);

  const [viewMode, setViewMode] = useStoredState<ViewMode>("reader.viewMode", "paged");
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
  const [translated, setTranslated] = useStoredState("reader.translated", false);
  // Leesinstellingen die het beeld zelf raken; de server snijdt en rekt op en
  // cachet het resultaat, dus dit kost niets bij het omslaan.
  const [crop, setCrop] = useStoredState("reader.crop", false);
  // Rasterzoom: de pagina in cellen, één voor één vullend. Op een telefoon is
  // een mangapagina anders leesbaar noch te overzien.
  const [grid, setGrid] = useStoredState("reader.grid", 0);
  const [cell, setCell] = useState(0);
  const [contrast, setContrast] = useStoredState("reader.contrast", 100);
  const adjust = useMemo(() => ({ crop, contrast }), [crop, contrast]);
  const [dismissedNext, setDismissedNext] = useState(false);

  const spreads = useMemo(
    // Rasterzoom en dubbelpagina sluiten elkaar uit: een raster over twee
    // pagina's tegelijk zou per pagina apart schalen en uit elkaar lopen.
    () => buildSpreads(pageCount, viewMode === "paged" && doublePage && grid === 0, { aspects }),
    [pageCount, viewMode, doublePage, grid, aspects],
  );

  const spreadIndex = spreadIndexOfPage(spreads, page);
  const currentSpread = spreads[spreadIndex] ?? [];
  const currentPage = currentSpread[0] ?? 0;

  const noteAspect = useCallback((index: number, width: number, height: number) => {
    if (height <= 0) return;
    setAspects((current) =>
      current[index] === undefined ? { ...current, [index]: width / height } : current,
    );
  }, []);

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
          setFit(fit === "width" ? "height" : fit === "height" ? "screen" : "width");
          break;
        case "Escape":
          onClose();
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
      Math.min(MAX_ZOOM, Math.max(1, current - Math.sign(event.deltaY) * ZOOM_STEP)),
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
      <div className="flex h-screen items-center justify-center bg-ink-900 text-slate-300">
        <div className="text-center">
          <p>Dit boek heeft geen leesbare pagina's.</p>
          <button className="mt-4 rounded bg-ink-700 px-4 py-2" onClick={onClose}>
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
    <div className="relative h-screen select-none overflow-hidden bg-ink-900">
      {viewMode === "vertical" ? (
        <VerticalReader
          book={book}
          pageCount={pageCount}
          profile={profile}
          initialPage={currentPage}
          onVisiblePage={setPage}
          onAspect={noteAspect}
          translated={translated}
          adjust={adjust}
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
                adjust={adjust}
                grid={
                  grid === 0
                    ? null
                    : cellTransform(cells[cell] ?? { row: 0, col: 0 }, gridRows, gridCols)
                }
                onAspect={noteAspect}
              />
            ))}
          </div>
        </div>
      )}

      {atEnd && !dismissedNext && (
        <NextChapterPrompt bookId={book.id} onDismiss={() => setDismissedNext(true)} />
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
          onSeek={setPage}
          onClose={onClose}
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
  adjust: { crop: boolean; contrast: number };
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
  adjust,
}: VerticalProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const jumped = useRef(false);
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
      const target = container.querySelector<HTMLElement>(`[data-page="${initialPage}"]`);
      if (target) target.scrollIntoView({ block: "start" });
      attempts += 1;
      if (attempts >= 8) {
        window.clearInterval(timer);
        jumped.current = true;
      }
    }, 150);
    return () => window.clearInterval(timer);
  }, [initialPage]);

  useEffect(() => {
    // Pas observeren nadat de sprong gedaan is.
    if (!jumped.current) return;
    const container = containerRef.current;
    if (!container) return;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            const index = Number((entry.target as HTMLElement).dataset.page);
            if (!Number.isNaN(index)) onVisiblePage(index);
          }
        }
      },
      { root: container, threshold: 0.5 },
    );
    for (const child of container.querySelectorAll("[data-page]")) observer.observe(child);
    return () => observer.disconnect();
  }, [onVisiblePage, pageCount]);

  return (
    <div ref={containerRef} className="h-full overflow-y-auto">
      <div className="mx-auto flex max-w-3xl flex-col">
        {Array.from({ length: pageCount }, (_, index) => (
          // Zolang een pagina nog niet geladen is houdt de wrapper 2:3 aan, de
          // verhouding van vrijwel elke stripbladzijde. Zonder die reservering
          // hebben ongeladen pagina's hoogte nul, schuift alles onder je weg
          // zodra ze binnenkomen, en landt geen enkele scrollpositie goed.
          <div
            key={index}
            data-page={index}
            className="relative w-full [container-type:inline-size]"
            style={loaded.has(index) ? undefined : { aspectRatio: "2 / 3" }}
          >
            <img
              src={imageUrl.page(book.id, index, profile, adjust)}
              alt={`Pagina ${index + 1}`}
              className="w-full"
              loading="lazy"
              draggable={false}
              onLoad={(event) => {
                onAspect(
                  index,
                  event.currentTarget.naturalWidth,
                  event.currentTarget.naturalHeight,
                );
                setLoaded((current) =>
                  current.has(index) ? current : new Set(current).add(index),
                );
              }}
            />
            {loaded.has(index) && (
              <TranslationOverlay bookId={book.id} pageIndex={index} enabled={translated} />
            )}
          </div>
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
  onSeek: (page: number) => void;
  onClose: () => void;
}

function Chrome(props: ChromeProps) {
  // Standaard dicht: een lezer hoort een strip te tonen, geen bedieningspaneel.
  const [showSettings, setShowSettings] = useState(false);
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
    onSeek,
    onClose,
  } = props;

  return (
    <>
      <div className="absolute inset-x-0 top-0 flex items-center gap-3 bg-ink-900/90 px-4 py-3 text-sm text-slate-200 backdrop-blur">
        <button className="rounded px-2 py-1 hover:bg-ink-700" onClick={onClose}>
          ← Terug
        </button>
        <span className="truncate font-medium">
          {book.series_title}
          {book.number ? ` ${book.number}` : ""}
        </span>
        <span className="ml-auto tabular-nums text-slate-400">
          {currentPage + 1} / {pageCount}
        </span>
      </div>

      <div className="absolute inset-x-0 bottom-0 space-y-2 bg-ink-900/90 px-4 py-3 backdrop-blur">
        <input
          type="range"
          min={0}
          max={Math.max(0, pageCount - 1)}
          value={currentPage}
          onChange={(event) => onSeek(Number(event.target.value))}
          className="w-full accent-accent"
          // Bij manga loopt de balk mee met de leesrichting.
          style={{ direction: rightToLeft ? "rtl" : "ltr" }}
        />
        {/* Één regel die altijd zichtbaar is: wat je tijdens het lezen echt
            omzet. De rest zit achter "Weergave" — die balk was uitgegroeid tot
            zestien knoppen, en dat is op een telefoon vier regels over je
            strip heen. */}
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-300">
          <Toggle
            active={viewMode === "vertical"}
            onClick={() => setViewMode(viewMode === "paged" ? "vertical" : "paged")}
          >
            {viewMode === "vertical" ? "Doorlopend" : "Pagina's"}
          </Toggle>
          <Toggle active={translated} onClick={() => setTranslated(!translated)}>
            Vertaling
          </Toggle>
          <Toggle active={showSettings} onClick={() => setShowSettings(!showSettings)}>
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
              <Toggle active={rightToLeft} onClick={() => setRightToLeft(!rightToLeft)}>
                {rightToLeft ? "Rechts → links" : "Links → rechts"}
              </Toggle>
              <div className="flex gap-1">
                {(["width", "height", "screen"] as FitMode[]).map((mode) => (
                  <Toggle key={mode} active={fit === mode} onClick={() => setFit(mode)}>
                    {mode === "width" ? "Breedte" : mode === "height" ? "Hoogte" : "Passend"}
                  </Toggle>
                ))}
              </div>
              <div className="ml-auto flex items-center gap-1">
                <Toggle active={false} onClick={() => setZoom(Math.max(1, zoom - ZOOM_STEP))}>
                  −
                </Toggle>
                <span className="w-12 text-center tabular-nums">{Math.round(zoom * 100)}%</span>
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
                setActive={setTranslated}
              />
            </div>

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
function NextChapterPrompt({ bookId, onDismiss }: { bookId: number; onDismiss: () => void }) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const { data } = useQuery({
    queryKey: ["next-chapter", bookId],
    queryFn: () => api.nextChapter(bookId),
    retry: (_count, error) => !(error instanceof ApiError && error.status === 404),
    staleTime: Infinity,
  });

  if (!data) return null;

  const label = [data.volume ? `Deel ${data.volume}` : null, data.number ? `#${data.number}` : null]
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
        <button onClick={onDismiss} className="rounded bg-ink-700 px-3 py-1.5 text-slate-300">
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
  adjust,
  grid,
  onAspect,
}: {
  book: BookDetail;
  page: number;
  profile: string;
  fitClass: string;
  translated: boolean;
  adjust: { crop: boolean; contrast: number };
  grid: GridTransform | null;
  onAspect: (index: number, width: number, height: number) => void;
}) {
  const { data } = usePageTranslation(book.id, page, translated);
  const useFullPage = translated && data?.full_page === true;

  return (
    // De overlay staat absoluut binnen dit vlak, dus het moet net zo groot zijn
    // als de afbeelding zelf — vandaar w-fit en relative. Bij rasterzoom
    // schaalt en verschuift ditzelfde vlak, zodat de vertaling meebeweegt.
    <div
      className="relative w-fit overflow-hidden [container-type:inline-size]"
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
        src={
          useFullPage
            ? imageUrl.fullTranslation(book.id, page)
            : imageUrl.page(book.id, page, profile, adjust)
        }
        alt={`Pagina ${page + 1}`}
        className={`object-contain ${fitClass}`}
        draggable={false}
        onLoad={(event) =>
          onAspect(page, event.currentTarget.naturalWidth, event.currentTarget.naturalHeight)
        }
      />
      <TranslationOverlay bookId={book.id} pageIndex={page} enabled={translated} />
    </div>
  );
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
  setActive,
}: {
  bookId: number;
  currentPage: number;
  setActive: (value: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const { data: status } = useQuery({
    queryKey: ["translation-status", bookId],
    queryFn: () => api.translationStatus(bookId),
    // Terwijl de wachtrij loopt willen we de teller zien oplopen; daarna niet
    // meer pollen dan nodig.
    refetchInterval: (query) => ((query.state.data?.queued ?? 0) > 0 ? 4000 : false),
  });

  const [busy, setBusy] = useState<string | null>(null);

  if (!status?.configured) return null;

  const total = status.page_count ?? 0;
  const done = status.translated;

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ["translation", bookId, currentPage] });
    void queryClient.invalidateQueries({ queryKey: ["translation-status", bookId] });
  }

  async function translateThisPage() {
    setBusy("tekst");
    try {
      await api.makePageTranslation(bookId, currentPage);
      setActive(true);
      refresh();
    } catch {
      /* zacht falen: de lezer toont gewoon het origineel */
    } finally {
      setBusy(null);
    }
  }

  // De dure standen: altijd een bewuste keuze per pagina, ook als de
  // schakelaar in de instellingen op goedkoop staat. Ze kosten tientallen
  // centen per pagina, dus ze horen nooit vanzelf te lopen.
  async function translateFully(mode: TranslateMode) {
    setBusy(mode);
    try {
      await api.translatePageFully(bookId, currentPage, { mode });
      setActive(true);
      refresh();
    } catch {
      /* zacht falen */
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
      <Toggle
        active={false}
        disabled={busy !== null}
        onClick={() => void translateFully("image_fast")}
        title="Hele pagina hertekenen met het snelle beeldmodel (~$0,07 per pagina)"
      >
        {busy === "image_fast" ? "Bezig…" : "Volledig"}
      </Toggle>
      <Toggle
        active={false}
        disabled={busy !== null}
        onClick={() => void translateFully("image_pro")}
        title="Hele pagina hertekenen met het zware beeldmodel (~$0,13 per pagina)"
      >
        {busy === "image_pro" ? "Bezig…" : "Volledig+"}
      </Toggle>
      <Toggle
        active={false}
        disabled={status.queued > 0 || busy !== null}
        onClick={() => {
          void api
            .translateBook(bookId, { from_page: currentPage })
            .then(() =>
              queryClient.invalidateQueries({ queryKey: ["translation-status", bookId] }),
            )
            .catch(() => {
              /* zacht falen */
            });
        }}
      >
        {status.queued > 0 ? `In wachtrij: ${status.queued}` : "Rest vertalen"}
      </Toggle>
      <span className="tabular-nums text-slate-500">
        {done}/{total}
      </span>
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
        active ? "bg-accent text-ink-900" : "bg-ink-700 text-slate-200 hover:bg-ink-600"
      } ${disabled ? "cursor-not-allowed opacity-40" : ""}`}
    >
      {children}
    </button>
  );
}
