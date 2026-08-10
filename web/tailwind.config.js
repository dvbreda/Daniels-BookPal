/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { 900: "#0b0d12", 800: "#141821", 700: "#1e2430", 600: "#2b3342" },
        accent: "#e0a458",
      },
    },
  },
  plugins: [],
};
