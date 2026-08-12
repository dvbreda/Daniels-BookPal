import { THEME_LABELS, type ThemeChoice, useTheme } from "../lib/theme";

const ORDER: ThemeChoice[] = ["system", "light", "dark"];
const ICONS: Record<ThemeChoice, string> = {
  system: "🖥",
  light: "☀",
  dark: "🌙",
};

/**
 * Doorklikken tussen systeem, licht en donker. Bewust één knop en geen
 * keuzelijst: het zijn drie standen die je zelden aanraakt, en zo kost het
 * geen ruimte in de kop.
 */
export function ThemeToggle({ className = "" }: { className?: string }) {
  const [choice, setChoice] = useTheme();
  const next = ORDER[(ORDER.indexOf(choice) + 1) % ORDER.length] ?? "system";

  return (
    <button
      onClick={() => setChoice(next)}
      title={`Weergave: ${THEME_LABELS[choice]} — klik voor ${THEME_LABELS[next].toLowerCase()}`}
      aria-label={`Weergave: ${THEME_LABELS[choice]}`}
      className={`rounded bg-ink-700 px-3 py-2 text-sm text-slate-200 ${className}`}
    >
      {ICONS[choice]}
    </button>
  );
}
