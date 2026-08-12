/** @type {import('tailwindcss').Config} */

// De waarden zelf staan als CSS-variabelen in src/index.css, zodat lichte en
// donkere modus dezelfde klassen delen. `<alpha-value>` houdt opacity werkend
// (`bg-ink-900/70`).
const themed = (name) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Vlakken: 900 is de pagina, 600 het meest naar voren.
        ink: {
          900: themed("ink-900"),
          800: themed("ink-800"),
          700: themed("ink-700"),
          600: themed("ink-600"),
        },
        // Tekst: 100 leest het best, 600 is het zwakst. Deze schaal overschrijft
        // Tailwinds eigen slate bewust — de app gebruikt hem alleen voor tekst,
        // en zo hoeft geen enkele bestaande klasse te veranderen.
        slate: {
          100: themed("slate-100"),
          200: themed("slate-200"),
          300: themed("slate-300"),
          400: themed("slate-400"),
          500: themed("slate-500"),
          600: themed("slate-600"),
        },
        accent: themed("accent"),
        // Meldingen; ook thema-afhankelijk, zie index.css.
        danger: { DEFAULT: themed("danger"), bg: themed("danger-bg") },
        warning: themed("warning"),
      },
    },
  },
  plugins: [],
};
