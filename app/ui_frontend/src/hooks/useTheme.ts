import { useState, useEffect, useCallback } from "react";

const STORAGE_KEY = "theme";
export type ThemePref = "system" | "light" | "dark";
const THEMES: ThemePref[] = ["system", "light", "dark"];

const readStored = (): ThemePref => {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return (THEMES as string[]).includes(v ?? "") ? (v as ThemePref) : "system";
  } catch {
    return "system";
  }
};

const systemQuery = () => window.matchMedia("(prefers-color-scheme: dark)");
const resolve = (t: ThemePref): "light" | "dark" =>
  t === "system" ? (systemQuery().matches ? "dark" : "light") : t;

/** Fires whenever the resolved theme changes — canvas charts re-read their colors on it. */
export const THEME_EVENT = "insidertrack:theme";

/**
 * Theme preference: 'system' | 'light' | 'dark'. Stored per browser in
 * localStorage and applied as `data-theme` on <html>, which index.css keys its
 * tokens off. index.html runs the same resolution inline before first paint so
 * there is no flash; this hook keeps it in sync afterwards.
 */
export default function useTheme() {
  const [theme, setThemeState] = useState<ThemePref>(readStored);

  useEffect(() => {
    const apply = () => {
      const next = resolve(theme);
      if (document.documentElement.dataset.theme !== next) {
        document.documentElement.dataset.theme = next;
        window.dispatchEvent(new CustomEvent(THEME_EVENT, { detail: next }));
      }
    };
    apply();
    if (theme !== "system") return;
    const q = systemQuery();
    q.addEventListener("change", apply);
    return () => q.removeEventListener("change", apply);
  }, [theme]);

  const setTheme = useCallback((next: ThemePref) => {
    if (!THEMES.includes(next)) return;
    setThemeState(next);
    try {
      if (next === "system") localStorage.removeItem(STORAGE_KEY);
      else localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* private mode: the choice still applies for this page load */
    }
  }, []);

  return { theme, setTheme, resolved: resolve(theme) };
}

/** Current resolved theme, re-rendering on change. For components that only need to react. */
export function useResolvedTheme(): "light" | "dark" {
  const read = () => (document.documentElement.dataset.theme === "light" ? "light" : "dark");
  const [t, setT] = useState<"light" | "dark">(read);
  useEffect(() => {
    const h = () => setT(read());
    window.addEventListener(THEME_EVENT, h);
    return () => window.removeEventListener(THEME_EVENT, h);
  }, []);
  return t;
}
