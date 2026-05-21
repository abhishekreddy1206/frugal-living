import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        display: ["var(--font-display)", "Georgia", "serif"],
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
      },
      colors: {
        // Warm "kitchen almanac" palette.
        paper: "#f4eede",
        crust: "#ece3ce", // sidebar / recessed surfaces
        raised: "#fffdf7", // cards
        ink: {
          DEFAULT: "#2a2018",
          soft: "#6f6353",
          faint: "#a99c84",
        },
        line: "#e4d9bf",
        clay: {
          DEFAULT: "#bb5a36",
          deep: "#974025",
        },
        ember: "#cf8a3c",
        moss: "#5c6a48",
      },
      boxShadow: {
        warm: "0 1px 2px rgba(70,45,20,0.05), 0 10px 26px -14px rgba(70,45,20,0.22)",
        "warm-lg": "0 2px 6px rgba(70,45,20,0.06), 0 28px 50px -22px rgba(70,45,20,0.30)",
      },
      keyframes: {
        "rise-in": {
          "0%": { opacity: "0", transform: "translateY(10px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "rise-in": "rise-in 0.5s cubic-bezier(0.2, 0.7, 0.2, 1) both",
      },
    },
  },
  plugins: [],
};
export default config;
