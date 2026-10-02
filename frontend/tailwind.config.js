/** Colours mirror frontend/src/theme.ts (keep both in sync). */
/** @type {import('tailwindcss').Config} */
const config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./src/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        ink: {
          DEFAULT: "#0F1115",
          panel: "#161A21",
          panel2: "#1B2029",
          border: "#232934",
          text: "#E7E9EE",
          muted: "#8B93A3",
          faint: "#5A6272",
        },
        risk: {
          amber: "#D29922",
          red: "#C74E4E",
          green: "#63965D",
        },
      },
      fontFamily: {
        sans: ["IBM Plex Sans", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      fontSize: {
        xxs: ["10px", "14px"],
      },
    },
  },
  plugins: [],
};
module.exports = config;
