import type { Config } from "tailwindcss";
const config: Config = {
  darkMode: "class",
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: {
          primary:   "#060912",
          secondary: "#0a0f1e",
          card:      "#0d1426",
          elevated:  "#111d35",
          hover:     "#162040",
        },
        border: {
          DEFAULT: "#1a2540",
          bright:  "#253660",
          accent:  "rgba(99,102,241,0.4)",
        },
        accent: {
          DEFAULT:    "#162040", // Shadcn hover compatibility
          foreground: "#f0f4ff", // Shadcn hover text compatibility
          indigo:  "#6366f1",
          cyan:    "#06b6d4",
          green:   "#22c55e",
          amber:   "#f59e0b",
          red:     "#ef4444",
          purple:  "#a855f7",
          blue:    "#3b82f6",
        },
        text: {
          primary:   "#f0f4ff",
          secondary: "#8b9cc8",
          muted:     "#4a5880",
          dim:       "#2d3a5c",
        },
        // Shadcn compatibility
        background:  "#060912",
        foreground:  "#f0f4ff",
        card: {
          DEFAULT:     "#0d1426",
          foreground:  "#f0f4ff",
        },
        popover: {
          DEFAULT:    "#111d35",
          foreground: "#f0f4ff",
        },
        primary: {
          DEFAULT:    "#6366f1",
          foreground: "#ffffff",
        },
        secondary: {
          DEFAULT:    "#111d35",
          foreground: "#8b9cc8",
        },
        muted: {
          DEFAULT:    "#111d35",
          foreground: "#4a5880",
        },
        destructive: {
          DEFAULT:    "#ef4444",
          foreground: "#ffffff",
        },
        input:  "#111d35",
        ring:   "#6366f1",
      },
      fontFamily: {
        sans: ["Inter", "-apple-system", "BlinkMacSystemFont", "Segoe UI", "sans-serif"],
        mono: ["JetBrains Mono", "Fira Code", "Consolas", "monospace"],
      },
      fontSize: {
        "2xs": ["0.625rem", { lineHeight: "1rem" }],
        xs:    ["0.75rem",  { lineHeight: "1.125rem" }],
        sm:    ["0.8125rem",{ lineHeight: "1.25rem" }],
        base:  ["0.875rem", { lineHeight: "1.5rem" }],
        lg:    ["1rem",     { lineHeight: "1.5rem" }],
        xl:    ["1.125rem", { lineHeight: "1.625rem" }],
        "2xl": ["1.25rem",  { lineHeight: "1.75rem" }],
        "3xl": ["1.5rem",   { lineHeight: "2rem" }],
        "4xl": ["1.875rem", { lineHeight: "2.25rem" }],
        "5xl": ["2.25rem",  { lineHeight: "2.5rem" }],
      },
      spacing: {
        sidebar: "240px",
        topbar:  "80px",
      },
      borderRadius: {
        sm:   "4px",
        DEFAULT: "6px",
        md:   "8px",
        lg:   "10px",
        xl:   "12px",
        "2xl":"16px",
        "3xl":"20px",
      },
      backgroundImage: {
        "gradient-ae":       "linear-gradient(135deg, #6366f1 0%, #06b6d4 50%, #22c55e 100%)",
        "gradient-ae-blue":  "linear-gradient(135deg, #6366f1, #06b6d4)",
        "gradient-ae-warm":  "linear-gradient(135deg, #f59e0b, #ef4444)",
        "gradient-ae-green": "linear-gradient(135deg, #22c55e, #06b6d4)",
        "gradient-ae-purple":"linear-gradient(135deg, #a855f7, #6366f1)",
        "gradient-card":     "linear-gradient(135deg, rgba(13,20,38,0.9) 0%, rgba(10,15,30,0.95) 100%)",
        "gradient-sidebar":  "linear-gradient(180deg, #060912 0%, #0a0f1e 100%)",
        "gradient-radial":   "radial-gradient(var(--tw-gradient-stops))",
        "card-shine":        "linear-gradient(135deg, rgba(255,255,255,0.03) 0%, transparent 50%)",
        "hero-glow":         "radial-gradient(ellipse 80% 50% at 50% -20%, rgba(99,102,241,0.15), transparent)",
      },
      boxShadow: {
        glow:          "0 0 30px rgba(99,102,241,0.2), 0 0 60px rgba(99,102,241,0.08)",
        "glow-cyan":   "0 0 30px rgba(6,182,212,0.2), 0 0 60px rgba(6,182,212,0.08)",
        "glow-green":  "0 0 30px rgba(34,197,94,0.2), 0 0 60px rgba(34,197,94,0.08)",
        "glow-amber":  "0 0 30px rgba(245,158,11,0.2), 0 0 60px rgba(245,158,11,0.08)",
        "glow-red":    "0 0 30px rgba(239,68,68,0.2), 0 0 60px rgba(239,68,68,0.08)",
        "glow-purple": "0 0 30px rgba(168,85,247,0.2), 0 0 60px rgba(168,85,247,0.08)",
        card:          "0 4px 32px rgba(0,0,0,0.5), 0 1px 0 rgba(255,255,255,0.03) inset",
        "card-hover":  "0 8px 48px rgba(0,0,0,0.7)",
        elevated:      "0 8px 48px rgba(0,0,0,0.7), 0 0 0 1px rgba(255,255,255,0.04)",
        panel:         "0 0 0 1px #1a2540, 0 4px 32px rgba(0,0,0,0.5)",
        inner:         "inset 0 1px 0 rgba(255,255,255,0.04)",
      },
      animation: {
        "fade-in":      "fadeIn 0.3s ease-out forwards",
        "slide-up":     "slideUp 0.4s cubic-bezier(0.4,0,0.2,1) forwards",
        "slide-right":  "slideInRight 0.35s cubic-bezier(0.4,0,0.2,1) forwards",
        "scale-in":     "scaleIn 0.3s cubic-bezier(0.4,0,0.2,1) forwards",
        "spin-slow":    "spin 3s linear infinite",
        "pulse-slow":   "pulse 3s ease-in-out infinite",
        "live-pulse":   "livePulse 1.5s ease-in-out infinite",
        "glow-pulse":   "glowPulse 2s ease-in-out infinite",
        shimmer:        "shimmer 1.5s linear infinite",
        "border-glow":  "borderGlow 2s ease-in-out infinite",
        "float":        "float 3s ease-in-out infinite",
        "count-up":     "countUp 0.6s cubic-bezier(0.4,0,0.2,1) forwards",
      },
      keyframes: {
        fadeIn: {
          from: { opacity: "0" },
          to:   { opacity: "1" },
        },
        slideUp: {
          from: { opacity: "0", transform: "translateY(16px)" },
          to:   { opacity: "1", transform: "translateY(0)" },
        },
        slideInRight: {
          from: { opacity: "0", transform: "translateX(-16px)" },
          to:   { opacity: "1", transform: "translateX(0)" },
        },
        scaleIn: {
          from: { opacity: "0", transform: "scale(0.95)" },
          to:   { opacity: "1", transform: "scale(1)" },
        },
        livePulse: {
          "0%, 100%": { opacity: "1", transform: "scale(1)" },
          "50%":      { opacity: "0.4", transform: "scale(0.8)" },
        },
        glowPulse: {
          "0%, 100%": { boxShadow: "0 0 20px rgba(99,102,241,0.15)" },
          "50%":      { boxShadow: "0 0 50px rgba(99,102,241,0.4)" },
        },
        shimmer: {
          "0%":   { backgroundPosition: "-400px 0" },
          "100%": { backgroundPosition: "400px 0" },
        },
        borderGlow: {
          "0%, 100%": { borderColor: "#1a2540" },
          "50%":      { borderColor: "rgba(99,102,241,0.6)", boxShadow: "0 0 20px rgba(99,102,241,0.15)" },
        },
        float: {
          "0%, 100%": { transform: "translateY(0)" },
          "50%":      { transform: "translateY(-6px)" },
        },
        countUp: {
          from: { opacity: "0", transform: "translateY(8px)" },
          to:   { opacity: "1", transform: "translateY(0)" },
        },
      },
      backdropBlur: {
        xs: "2px",
        sm: "4px",
        DEFAULT: "8px",
        md: "12px",
        lg: "16px",
        xl: "24px",
      },
      transitionTimingFunction: {
        "ae-ease": "cubic-bezier(0.4, 0, 0.2, 1)",
        "ae-spring": "cubic-bezier(0.34, 1.56, 0.64, 1)",
      },
      zIndex: {
        sidebar:  "50",
        topbar:   "40",
        modal:    "100",
        tooltip:  "200",
        toast:    "300",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
export default config;