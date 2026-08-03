import type { Config } from "tailwindcss";

export default {
  darkMode: ["class"],
  // Wraps every `hover:` utility in @media (hover: hover) and (pointer: fine).
  // BottomTabs proves phones are a real target, and on touch a tap fires :hover
  // and leaves the element stuck in its hover state until the next tap.
  future: { hoverOnlyWhenSupported: true },
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
        // Semantic vocabulary — see src/design/tokens.css. Bound here in the
        // SAME change as the token definitions: a token bound to nothing is
        // valid CSS referenced by no utility, which is how the motion tokens
        // silently shipped dead.
        "domain-risk": "hsl(var(--domain-risk))",
        "domain-market": "hsl(var(--domain-market))",
        "domain-execution": "hsl(var(--domain-execution))",
        "domain-analytics": "hsl(var(--domain-analytics))",
        "impact-high": "hsl(var(--impact-high))",
        "impact-medium": "hsl(var(--impact-medium))",
        "impact-low": "hsl(var(--impact-low))",
        "dd-shallow": "hsl(var(--dd-shallow))",
        "dd-moderate": "hsl(var(--dd-moderate))",
        "dd-severe": "hsl(var(--dd-severe))",
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
