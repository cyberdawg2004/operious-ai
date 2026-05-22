"use client";

import { createContext, useContext, useEffect, useState } from "react";

type Theme = "dark" | "light";

interface ThemeContextType {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<Theme>("dark"); // Default to dark
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    // Check localStorage first, then system preference, default to dark
    const stored = localStorage.getItem("operious-theme") as Theme | null;
    if (stored) {
      setThemeState(stored);
    } else {
      // Default to dark for operational tools (Bloomberg/Linear convention)
      // Only use light if user explicitly prefers it AND we have no stored preference
      const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      // We default to dark regardless, but respect explicit light preference
      const prefersLight = window.matchMedia("(prefers-color-scheme: light)").matches;
      if (prefersLight && !prefersDark) {
        // User has explicitly set light mode in their system
        setThemeState("light");
      } else {
        setThemeState("dark");
      }
    }
  }, []);

  useEffect(() => {
    if (!mounted) return;
    
    const root = document.documentElement;
    if (theme === "dark") {
      root.classList.add("dark");
    } else {
      root.classList.remove("dark");
    }
    localStorage.setItem("operious-theme", theme);
  }, [theme, mounted]);

  const setTheme = (newTheme: Theme) => {
    setThemeState(newTheme);
  };

  const toggleTheme = () => {
    setThemeState((prev) => (prev === "dark" ? "light" : "dark"));
  };

  // Always provide context, even when not mounted (use default dark value)
  return (
    <ThemeContext.Provider value={{ theme, setTheme, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (context === undefined) {
    throw new Error("useTheme must be used within a ThemeProvider");
  }
  return context;
}
