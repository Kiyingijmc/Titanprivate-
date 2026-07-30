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
      // Motion tokens, bound the same way as borderRadius/boxShadow above.
      // Overriding DEFAULT is the point: without it every bare `transition-*`
      // silently falls back to Tailwind's own 150ms / cubic-bezier(.4,0,.2,1)
      // and the tokens govern nothing.
      transitionTimingFunction: {
        DEFAULT: "var(--ease)",
        out: "var(--ease-out)",
        "in-out": "var(--ease-in-out)",
      },
      transitionDuration: {
        DEFAULT: "var(--motion-fast)",
        fast: "var(--motion-fast)",
        base: "var(--motion-base)",
      },
    },
  },
  plugins: [],
} satisfies Config;
