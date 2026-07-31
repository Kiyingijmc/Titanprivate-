import type { Config } from "tailwindcss";

export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // surfaces
        background: "hsl(var(--bg))",
        surface: { 1: "hsl(var(--surface-1))", 2: "hsl(var(--surface-2))" },
        elevated: "hsl(var(--elevated))",
        // lines + text
        border: "hsl(var(--border))",
        "border-strong": "hsl(var(--border-strong))",
        foreground: "hsl(var(--text-primary))",
        "secondary-foreground": "hsl(var(--text-secondary))",
        "muted-foreground": "hsl(var(--text-muted))",
        // accent + states
        accent: {
          DEFAULT: "hsl(var(--accent))",
          hover: "hsl(var(--accent-hover))",
          active: "hsl(var(--accent-active))",
          subtle: "hsl(var(--accent-subtle))",
          foreground: "hsl(var(--on-accent))",
        },
        ring: "hsl(var(--focus-ring))",
        // semantic (design-system §2) — always paired with an icon+label in UI
        profit: "hsl(var(--profit))",
        loss: "hsl(var(--loss))",
        warning: "hsl(var(--warning))",
        info: "hsl(var(--info))",
        blocked: "hsl(var(--blocked))",
        destructive: { DEFAULT: "hsl(var(--loss))", foreground: "hsl(var(--on-accent))" },
        // back-compat aliases — existing components still reference these v1 names
        card: { DEFAULT: "hsl(var(--surface-1))", foreground: "hsl(var(--text-primary))" },
        muted: { DEFAULT: "hsl(var(--surface-2))", foreground: "hsl(var(--text-muted))" },
        input: "hsl(var(--border))",
        primary: { DEFAULT: "hsl(var(--accent))", foreground: "hsl(var(--on-accent))" },
      },
      borderRadius: {
        lg: "var(--radius-lg)",
        md: "var(--radius-md)",
        sm: "var(--radius-sm)",
      },
      fontFamily: {
        sans: ["'Instrument Sans'", "system-ui", "-apple-system", "sans-serif"],
        mono: ["'JetBrains Mono'", "ui-monospace", "monospace"],
      },
      boxShadow: {
        1: "var(--shadow-1)",
        2: "var(--shadow-2)",
      },
      // Motion tokens, bound the same way as borderRadius/boxShadow above —
      // without this a bare `duration-fast`/`ease-out` class has nothing to
      // resolve to and the token in tokens.css is dead CSS.
      //
      // DELIBERATE: `out` is Tailwind's stock key for the `ease-out` utility
      // (built-in value `cubic-bezier(0, 0, 0.2, 1)`). This entry REPLACES
      // that stock curve app-wide with Titan's `--ease-out`
      // (`cubic-bezier(0.23, 1, 0.32, 1)`) so the design system has one
      // easing vocabulary — Tailwind's built-in easings are too weak/linear
      // for UI motion, and the point of a token layer is that the system's
      // curve is what you get by default, not something every call site has
      // to opt into by hand. A component that genuinely wants Tailwind's
      // original stock curve must reach for the arbitrary-value form
      // (`ease-[cubic-bezier(0,0,0.2,1)]`) rather than assume `ease-out`
      // still means Tailwind's default — it doesn't, anywhere in this app.
      // Pinned by frontend/src/design/motion-tokens.test.ts.
      transitionTimingFunction: {
        out: "var(--ease-out)",
      },
      transitionDuration: {
        fast: "var(--motion-fast)",
      },
    },
  },
  plugins: [],
} satisfies Config;
