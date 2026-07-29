import React from "react";
import ReactDOM from "react-dom/client";
// Self-hosted brand fonts (Vite-bundled woff2 — CSP-safe, no CDN).
import "@fontsource/instrument-sans/400.css";
import "@fontsource/instrument-sans/500.css";
import "@fontsource/instrument-sans/600.css";
import "@fontsource/instrument-sans/700.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import "@fontsource/jetbrains-mono/600.css";
import App from "./App";
import "./index.css";

// Pre-apply the saved signature accent before first paint (avoids a violet→blue
// flash). tokens.css keys the electric-blue override off <html data-accent="blue">.
try {
  if (localStorage.getItem("titan.accent") === "blue") {
    document.documentElement.setAttribute("data-accent", "blue");
  }
} catch {
  /* ignore storage-unavailable */
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode><App /></React.StrictMode>
);
