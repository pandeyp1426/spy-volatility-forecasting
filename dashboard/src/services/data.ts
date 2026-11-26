import { useEffect, useState, useSyncExternalStore } from "react";
import {
  schemas,
  envelope,
  manifestSchema,
  type Data,
  type Dataset,
} from "../types/public";
export const dataUrl = (file: string, base = import.meta.env.BASE_URL) =>
  base + "data/" + file;
async function fetchFile(name: string) {
  const response = await fetch(dataUrl(name), {
    cache: "no-store",
    signal: AbortSignal.timeout(15_000),
  });
  if (!response.ok) throw new Error("The approved data file is unavailable.");
  return response;
}
async function readManifest() {
  return manifestSchema.parse(await (await fetchFile("manifest.json")).json());
}
type Manifest = Awaited<ReturnType<typeof readManifest>>;
interface Release {
  manifest: Manifest;
  cache: Map<Dataset, Promise<unknown>>;
}

async function loadDataset<K extends Dataset>(key: K, manifest: Manifest): Promise<Data<K>> {
  const entry = manifest.datasets[key];
  if (entry.file !== key + ".json")
    throw new Error("Unrecognized dataset file.");
  const bytes = await (await fetchFile(entry.file)).arrayBuffer();
  const digest = Array.from(
    new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
    (v) => v.toString(16).padStart(2, "0"),
  ).join("");
  if (digest !== entry.sha256)
    throw new Error("The dataset does not match its published digest.");
  const parsed = envelope.parse(JSON.parse(new TextDecoder().decode(bytes)));
  if (
    parsed.dataset !== key ||
    parsed.generated_at !== manifest.generated_at ||
    parsed.status !== entry.status
  )
    throw new Error("The release metadata does not match.");
  return schemas[key].parse(parsed.data) as Data<K>;
}
function dataset<K extends Dataset>(release: Release, key: K): Promise<Data<K>> {
  if (!release.cache.has(key)) {
    release.cache.set(key, loadDataset(key, release.manifest).catch((error) => {
      release.cache.delete(key);
      throw error;
    }));
  }
  return release.cache.get(key)! as Promise<Data<K>>;
}

interface Publication {
  release: Release | null;
  checkedAt: string | null;
  checking: boolean;
  failed: boolean;
}
let publication: Publication = {release: null, checkedAt: null, checking: false, failed: false};
const listeners = new Set<() => void>();
function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
const snapshot = () => publication;
function update(changes: Partial<Publication>) {
  publication = {...publication, ...changes};
  listeners.forEach((listener) => listener());
}

export async function checkPublication() {
  if (publication.checking) return;
  update({checking: true});
  try {
    const manifest = await readManifest();
    let release = publication.release;
    if (!release || JSON.stringify(manifest) !== JSON.stringify(release.manifest)) {
      const candidate: Release = {manifest, cache: new Map()};
      // Keep the displayed release intact while already used files are verified.
      // A partial upload must not advance the timestamp or mix research vintages.
      await Promise.all(Array.from(release?.cache.keys() ?? [], (key) => dataset(candidate, key)));
      release = candidate;
    }
    update({release, checkedAt: new Date().toISOString(), failed: false, checking: false});
  } catch {
    update({failed: true, checking: false});
  }
}

export function usePublicationMonitor() {
  const state = useSyncExternalStore(subscribe, snapshot);
  useEffect(() => {
    const checkVisible = () => {
      if (document.visibilityState === "visible") void checkPublication();
    };
    checkVisible();
    const timer = window.setInterval(checkVisible, 60_000);
    window.addEventListener("focus", checkVisible);
    window.addEventListener("online", checkVisible);
    document.addEventListener("visibilitychange", checkVisible);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", checkVisible);
      window.removeEventListener("online", checkVisible);
      document.removeEventListener("visibilitychange", checkVisible);
    };
  }, []);
  return state;
}

export function useDataset<K extends Dataset>(key: K) {
  const {release, checkedAt, failed} = useSyncExternalStore(subscribe, snapshot);
  const [result, setResult] = useState<{release: Release; key: K; data: Data<K> | null}>();
  useEffect(() => {
    if (!release) return;
    let active = true;
    dataset(release, key).then(
      (data) => { if (active) setResult({release, key, data}); },
      () => { if (active) setResult({release, key, data: null}); },
    );
    return () => { active = false; };
  }, [key, release, checkedAt]);
  const current = result?.release === release && result?.key === key ? result : undefined;
  const error = ((!release && failed) || current?.data === null)
    ? "The approved dataset could not be loaded or verified." : null;
  return {data: current?.data ?? null, error, loading: !current && !error, retry: checkPublication};
}
