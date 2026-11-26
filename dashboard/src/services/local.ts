import { useEffect, useState } from "react";
import type { ZodType } from "zod";

export const localPreview = () => document.querySelector('meta[name="local-pilot-preview"]')?.getAttribute("content") === "enabled";

/** Refresh a loopback-only resource while the dashboard is visible. */
export function useLocalFeed<T>(filename: string, schema: ZodType<T>) {
  const [value, setValue] = useState<T | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!localPreview()) return;
    let active = true, pending = false;
    const refresh = async () => {
      if (pending || document.visibilityState !== "visible") return;
      pending = true;
      try {
        const response = await fetch(import.meta.env.BASE_URL + "local/" + filename, {
          cache: "no-store", signal: AbortSignal.timeout(30_000),
        });
        if (!response.ok) throw new Error();
        const next = schema.parse(await response.json());
        if (active) { setValue(next); setFailed(false); }
      } catch {
        if (active) setFailed(true);
      } finally { pending = false; }
    };
    void refresh();
    const timer = window.setInterval(refresh, 60_000);
    document.addEventListener("visibilitychange", refresh);
    window.addEventListener("focus", refresh);
    window.addEventListener("online", refresh);
    window.addEventListener("research-refresh", refresh);
    return () => {
      active = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", refresh);
      window.removeEventListener("focus", refresh);
      window.removeEventListener("online", refresh);
      window.removeEventListener("research-refresh", refresh);
    };
  }, [filename, schema]);
  return {value, failed};
}
