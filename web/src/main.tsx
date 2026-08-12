import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "./index.css";
import { applyTheme, readStoredTheme } from "./lib/theme";

// Vóór de eerste render, anders zie je even de verkeerde achtergrond.
applyTheme(readStoredTheme());

const container = document.getElementById("root");
if (!container) throw new Error("root-element ontbreekt");

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
