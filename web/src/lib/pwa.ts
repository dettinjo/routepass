import { useEffect, useState } from "react";

export type ThemeMode = "system" | "light" | "dark";
const THEME_KEY = "routepass.theme";

export function getTheme(): ThemeMode {
  try {
    const v = localStorage.getItem(THEME_KEY);
    if (v === "light" || v === "dark" || v === "system") return v;
  } catch {
    /* ignore */
  }
  return "system";
}

export function applyTheme(mode: ThemeMode): void {
  const root = document.documentElement;
  if (mode === "light" || mode === "dark") {
    root.dataset.theme = mode;
  } else {
    delete root.dataset.theme;
  }
  const isDark =
    mode === "dark" ||
    (mode === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  const color = isDark ? "#111110" : "#f4f4f2";
  document
    .querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]')
    .forEach((m) => m.setAttribute("content", color));
  window.dispatchEvent(new CustomEvent("routepass:theme", { detail: mode }));
}

export function setTheme(mode: ThemeMode): void {
  try {
    localStorage.setItem(THEME_KEY, mode);
  } catch {
    /* ignore */
  }
  applyTheme(mode);
}

export function useTheme(): [ThemeMode, (m: ThemeMode) => void] {
  const [mode, setMode] = useState<ThemeMode>(getTheme);
  useEffect(() => {
    const onTheme = () => setMode(getTheme());
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onMq = () => {
      if (getTheme() === "system") applyTheme("system");
    };
    window.addEventListener("routepass:theme", onTheme);
    mq.addEventListener("change", onMq);
    return () => {
      window.removeEventListener("routepass:theme", onTheme);
      mq.removeEventListener("change", onMq);
    };
  }, []);
  return [mode, setTheme];
}

export function useOnlineStatus(): boolean {
  const [online, setOnline] = useState<boolean>(() =>
    typeof navigator !== "undefined" ? navigator.onLine : true,
  );
  useEffect(() => {
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);
  return online;
}

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

let deferredPrompt: BeforeInstallPromptEvent | null = null;
const promptListeners = new Set<() => void>();

if (typeof window !== "undefined") {
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferredPrompt = e as BeforeInstallPromptEvent;
    promptListeners.forEach((fn) => fn());
  });
  window.addEventListener("appinstalled", () => {
    deferredPrompt = null;
    promptListeners.forEach((fn) => fn());
  });
}

export function useInstallPrompt() {
  const [, tick] = useState(0);
  const [installed, setInstalled] = useState<boolean>(() =>
    typeof window !== "undefined"
      ? window.matchMedia("(display-mode: standalone)").matches ||
        (navigator as any).standalone === true
      : false,
  );

  useEffect(() => {
    const notify = () => {
      setInstalled(
        window.matchMedia("(display-mode: standalone)").matches ||
          (navigator as any).standalone === true,
      );
      tick((n) => n + 1);
    };
    promptListeners.add(notify);
    return () => {
      promptListeners.delete(notify);
    };
  }, []);

  const install = async () => {
    if (!deferredPrompt) return false;
    await deferredPrompt.prompt();
    const { outcome } = await deferredPrompt.userChoice;
    if (outcome === "accepted") {
      deferredPrompt = null;
      promptListeners.forEach((fn) => fn());
      return true;
    }
    return false;
  };

  return { canInstall: !!deferredPrompt && !installed, installed, install };
}

export function registerServiceWorker(): void {
  if (typeof window === "undefined" || !("serviceWorker" in navigator)) return;
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {
      /* ignore registration error in unsupported contexts */
    });
  });
}

/** Forget offline copies of personal data (on sign-out). */
export async function clearOfflineData(): Promise<void> {
  try {
    navigator.serviceWorker?.controller?.postMessage({ type: "CLEAR_API_CACHE" });
    if ("caches" in window) await caches.delete("routepass-api-v3");
  } catch {
    /* ignore */
  }
}
