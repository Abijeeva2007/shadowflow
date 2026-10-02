"use client";

import { useCallback, useEffect, useRef, useState } from "react";

// How often to re-attempt a request that failed because the API is booting
// (Render free instances sleep; the detection engine runs at backend startup).
const RETRY_MS = 3000;
// Only show the "waking up" banner once a request has been pending/slow for
// this long, so a fast backend never flashes the banner.
const SLOW_MS = 1200;

/**
 * Treat a request as "backend still booting" when the fetch itself failed
 * (network error / connection refused -> no status) or the server answered
 * with a gateway/warming status. Everything else is a real error.
 */
export function isWakingErr(e: any): boolean {
  const s = e?.status;
  return (
    s === undefined ||
    s === null ||
    s === 429 ||
    s === 502 ||
    s === 503 ||
    s === 504
  );
}

/**
 * Fetch JSON with automatic retry while the backend is warming up.
 * Returns { data, error, waking, reload }. `key` identifies the request:
 * when it changes, data resets and the request re-runs.
 */
export function useApiData<T>(loader: () => Promise<T>, key: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [waking, setWaking] = useState(false);
  const [slow, setSlow] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;
  const prevKey = useRef(key);
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const slowTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (prevKey.current !== key) {
      prevKey.current = key;
      setData(null);
      setError(null);
      setSlow(false);
    }
    if (slowTimer.current) clearTimeout(slowTimer.current);
    slowTimer.current = setTimeout(() => {
      if (!cancelled) setSlow(true);
    }, SLOW_MS);

    (async () => {
      try {
        const d = await loaderRef.current();
        if (cancelled) return;
        if (slowTimer.current) clearTimeout(slowTimer.current);
        setData(d);
        setError(null);
        setWaking(false);
      } catch (e: any) {
        if (cancelled) return;
        if (isWakingErr(e)) {
          // Backend is booting: keep the "waking" state and retry shortly.
          setWaking(true);
          setError(null);
          retryTimer.current = setTimeout(
            () => setAttempt((a) => a + 1),
            RETRY_MS,
          );
        } else {
          if (slowTimer.current) clearTimeout(slowTimer.current);
          setError(String(e?.message ?? e));
          setWaking(false);
        }
      }
    })();

    return () => {
      cancelled = true;
      if (retryTimer.current) clearTimeout(retryTimer.current);
      if (slowTimer.current) clearTimeout(slowTimer.current);
    };
  }, [key, attempt]);

  const reload = useCallback(() => setAttempt((a) => a + 1), []);
  return { data, error, waking: waking && slow, reload };
}

/** Clear "Backend is waking up, please wait" panel with auto-retry running. */
export function WakingState({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="panel p-8 text-center">
      <div className="text-sm font-medium text-ink-text">
        Backend is waking up, please wait
      </div>
      <div className="text-xxs text-ink-muted mt-1.5">
        The detection engine runs once at startup. This page retries every few
        seconds automatically.
      </div>
      <div className="mt-4 flex justify-center">
        <div className="skeleton h-1 w-48 rounded" />
      </div>
      <button className="btn-ghost mt-5" onClick={onRetry}>
        Retry now
      </button>
    </div>
  );
}

/** Terminal API error with a manual retry. */
export function ErrorState({
  error,
  onRetry,
}: {
  error: string;
  onRetry: () => void;
}) {
  return (
    <div className="err-banner">
      <div>{error}</div>
      <button className="btn-ghost mt-2" onClick={onRetry}>
        Retry
      </button>
    </div>
  );
}
