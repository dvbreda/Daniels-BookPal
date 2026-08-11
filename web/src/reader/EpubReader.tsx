import { useCallback, useEffect, useRef, useState } from "react";

import { api, imageUrl } from "../api/client";
import type { BookDetail } from "../api/types";
import { useStoredState } from "../lib/useStoredState";

// Zelfde ritme als de stripleer: niet elke paginawissel meteen wegschrijven.
const PROGRESS_DEBOUNCE_MS = 1200;

/** Wat we van foliate's <foliate-view> gebruiken. */
interface FoliateView extends HTMLElement {
  open(book: Blob | File): Promise<void>;
  goTo(target: string | number): Promise<void>;
  goLeft(): Promise<void>;
  goRight(): Promise<void>;
  renderer: {
    setStyles?(css: string): void;
    setAttribute(name: string, value: string): void;
    next(): Promise<void>;
    prev(): Promise<void>;
  };
}

interface RelocateDetail {
  fraction: number;
  cfi: string;
  tocItem?: { label?: string } | null;
}

const THEMES = {
  donker: { bg: "#0f172a", fg: "#e2e8f0" },
  sepia: { bg: "#f5ecd9", fg: "#3b2f21" },
  licht: { bg: "#ffffff", fg: "#111827" },
} as const;

type ThemeName = keyof typeof THEMES;

/**
 * Epub lezen in de browser met foliate-js (M6).
 *
 * Herschikbare tekst laat zich niet server-side in pagina's knippen — waar een
 * lezer is, hangt af van lettergrootte en schermbreedte. Daarom rendert de
 * client, en slaan we de positie op als CFI: dat is een verwijzing in het
 * document zelf en blijft dus kloppen als je op een ander apparaat verder
 * leest met andere instellingen. Precies waar het datamodel op rekent.
 */
export function EpubReader({ book, onClose }: { book: BookDetail; onClose: () => void }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<FoliateView | null>(null);

  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const [showChrome, setShowChrome] = useState(true);
  const [label, setLabel] = useState<string>("");
  const [percent, setPercent] = useState<number>(book.progress?.percent ?? 0);

  const [fontSize, setFontSize] = useStoredState("epub.fontSize", 100);
  const [theme, setTheme] = useStoredState<ThemeName>("epub.theme", "donker");

  const pending = useRef<{ cfi: string; percent: number } | null>(null);

  // Het boek inladen. foliate definieert een custom element, dus dit gebeurt
  // één keer per boek en niet bij elke render.
  useEffect(() => {
    let cancelled = false;
    const host = hostRef.current;
    if (!host) return;

    async function load() {
      try {
        await import("../vendor/foliate/view.js");
        if (cancelled || !host) return;

        const response = await fetch(imageUrl.file(book.id));
        if (!response.ok) throw new Error(`kon het bestand niet ophalen (${response.status})`);
        const blob = await response.blob();
        if (cancelled) return;

        const view = document.createElement("foliate-view") as FoliateView;
        host.replaceChildren(view);
        viewRef.current = view;

        view.addEventListener("relocate", (event) => {
          const detail = (event as CustomEvent<RelocateDetail>).detail;
          const nextPercent = Math.round((detail.fraction ?? 0) * 1000) / 10;
          setPercent(nextPercent);
          setLabel(detail.tocItem?.label ?? "");
          pending.current = { cfi: detail.cfi, percent: nextPercent };
        });

        await view.open(blob);
        if (cancelled) return;

        // Verder waar je gebleven was. Een CFI van een ander apparaat werkt
        // hier gewoon; dat is het hele punt van een CFI.
        const stored = book.progress?.position as { cfi?: string } | undefined;
        if (stored?.cfi) {
          try {
            await view.goTo(stored.cfi);
          } catch {
            /* verouderde CFI (bestand vervangen?): begin dan vooraan */
          }
        }
        setReady(true);
      } catch (error) {
        if (!cancelled) {
          setFailed(error instanceof Error ? error.message : "Onbekende fout");
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
      viewRef.current = null;
      host.replaceChildren();
    };
  }, [book.id, book.progress?.position]);

  // Opmaak toepassen. Apart van het inladen, want dit verandert terwijl je leest.
  useEffect(() => {
    const view = viewRef.current;
    if (!view || !ready) return;
    const { bg, fg } = THEMES[theme];
    view.renderer.setStyles?.(`
      @namespace epub "http://www.idpf.org/2007/ops";
      html { color-scheme: ${theme === "licht" ? "light" : "dark"}; }
      html, body { background: ${bg}; color: ${fg}; }
      body { font-size: ${fontSize}%; line-height: 1.6; }
      a:any-link { color: #7dd3fc; }
      p { text-align: justify; hyphens: auto; }
    `);
  }, [fontSize, theme, ready]);

  // Voortgang wegschrijven, ontdaan van ruis tijdens snel doorbladeren.
  useEffect(() => {
    if (!ready) return;
    const timer = window.setInterval(() => {
      const next = pending.current;
      if (!next) return;
      pending.current = null;
      void api
        .setProgress({
          book_id: book.id,
          position: { cfi: next.cfi },
          percent: next.percent,
          device: "web",
        })
        .catch(() => {
          /* offline: de lezer moet gewoon doorlopen */
        });
    }, PROGRESS_DEBOUNCE_MS);
    return () => window.clearInterval(timer);
  }, [book.id, ready]);

  const goLeft = useCallback(() => void viewRef.current?.goLeft(), []);
  const goRight = useCallback(() => void viewRef.current?.goRight(), []);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "ArrowLeft" || event.key === "PageUp") goLeft();
      else if (event.key === "ArrowRight" || event.key === "PageDown" || event.key === " ")
        goRight();
      else if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [goLeft, goRight, onClose]);

  if (failed) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-4 bg-ink-900 px-6 text-center text-slate-300">
        <p>Dit boek kon niet geopend worden.</p>
        <p className="text-sm text-slate-500">{failed}</p>
        <div className="flex gap-2">
          <a
            href={imageUrl.file(book.id)}
            download
            className="rounded bg-ink-700 px-4 py-2 text-sm"
          >
            Bestand downloaden
          </a>
          <button onClick={onClose} className="rounded bg-ink-700 px-4 py-2 text-sm">
            Terug
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="relative h-screen w-screen overflow-hidden" style={{ background: THEMES[theme].bg }}>
      <div ref={hostRef} className="h-full w-full" onClick={() => setShowChrome((v) => !v)} />

      {!ready && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-slate-400">
          Laden…
        </div>
      )}

      {/* Tikken op de randen bladert; dat is op een telefoon prettiger dan knoppen. */}
      <button
        aria-label="Vorige pagina"
        onClick={goLeft}
        className="absolute inset-y-0 left-0 w-1/4 cursor-w-resize opacity-0"
      />
      <button
        aria-label="Volgende pagina"
        onClick={goRight}
        className="absolute inset-y-0 right-0 w-1/4 cursor-e-resize opacity-0"
      />

      {showChrome && (
        <>
          <header className="absolute inset-x-0 top-0 flex items-center gap-3 bg-ink-900/90 px-4 py-2 text-sm text-slate-200">
            <button onClick={onClose} className="rounded bg-ink-700 px-3 py-1.5">
              ← Terug
            </button>
            <span className="min-w-0 flex-1 truncate">
              {book.series_title ? `${book.series_title} · ` : ""}
              {book.title}
            </span>
          </header>

          <footer className="absolute inset-x-0 bottom-0 flex flex-wrap items-center gap-3 bg-ink-900/90 px-4 py-2 text-sm text-slate-200">
            <div className="flex items-center gap-1">
              <button
                onClick={() => setFontSize(Math.max(60, fontSize - 10))}
                className="rounded bg-ink-700 px-2 py-1"
                aria-label="Kleiner"
              >
                A−
              </button>
              <span className="w-12 text-center text-xs text-slate-400">{fontSize}%</span>
              <button
                onClick={() => setFontSize(Math.min(220, fontSize + 10))}
                className="rounded bg-ink-700 px-2 py-1"
                aria-label="Groter"
              >
                A+
              </button>
            </div>

            <div className="flex items-center gap-1">
              {(Object.keys(THEMES) as ThemeName[]).map((name) => (
                <button
                  key={name}
                  onClick={() => setTheme(name)}
                  className={`rounded px-2 py-1 text-xs capitalize ${
                    theme === name ? "bg-accent text-ink-900" : "bg-ink-700 text-slate-300"
                  }`}
                >
                  {name}
                </button>
              ))}
            </div>

            <span className="ml-auto min-w-0 truncate text-xs text-slate-400">
              {label && `${label} · `}
              {percent.toFixed(0)}%
            </span>
          </footer>
        </>
      )}
    </div>
  );
}
