import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "#0a0a0f",
        surface: "#12121a",
        "surface-2": "#1a1a26",
        "surface-3": "#22223a",
        border: "#2a2a40",
        primary: "#6366f1",
        "primary-hover": "#4f46e5",
        success: "#10b981",
        warning: "#f59e0b",
        danger: "#ef4444",
        muted: "#6b7280",
        "text-primary": "#f1f5f9",
        "text-secondary": "#94a3b8",
      },
    },
  },
  plugins: [],
};
export default config;
