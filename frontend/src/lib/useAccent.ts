import { useCallback, useEffect, useState } from "react";

export type Accent = "violet" | "blue";
const KEY = "titan.accent";

/** Reflect the accent onto <html> so the CSS token override in tokens.css applies. */
function applyAccent(a: Accent) {
  if (typeof document === "undefined") return;
  const el = document.documentElement;
  if (a === "blue") el.setAttribute("data-accent", "blue");
  else el.removeAttribute("data-accent");
}

function initialAccent(): Accent {
  try {
    return localStorage.getItem(KEY) === "blue" ? "blue" : "violet";
  } catch {
    return "violet";
  }
}

/**
 * Signature-accent switcher (violet ↔ electric blue). The <html data-accent>
 * attribute is the single source of truth for styling (see tokens.css); this
 * hook persists the choice and keeps the attribute in sync. main.tsx pre-applies
 * the saved value before first paint to avoid a flash; the mount effect here is
 * a belt-and-braces sync for that path.
 */
export function useAccent() {
  const [accent, setAccent] = useState<Accent>(initialAccent);

  useEffect(() => {
    applyAccent(accent);
  }, [accent]);

  const toggle = useCallback(() => {
    setAccent((prev) => {
      const next: Accent = prev === "violet" ? "blue" : "violet";
      try {
        localStorage.setItem(KEY, next);
      } catch {
        /* ignore persistence failures (private mode etc.) */
      }
      return next;
    });
  }, []);

  return { accent, toggle };
}
