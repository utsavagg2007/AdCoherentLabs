"use client";

import { useCallback, useEffect, useRef, useState } from "react";

interface AsyncState<T> {
  data: T | null;
  error: unknown;
  loading: boolean;
}

/** Small data-fetch hook: abortable, refreshable, stable across renders.
 * `fn` receives an AbortSignal; re-runs when `deps` change. The effect
 * captures the `fn` from the render that triggered it, which is always the
 * fresh one for that deps/tick combination. */
export function useAsyncData<T>(
  fn: (signal: AbortSignal) => Promise<T>,
  deps: React.DependencyList
): AsyncState<T> & { refresh: (opts?: { silent?: boolean }) => void } {
  const [state, setState] = useState<AsyncState<T>>({
    data: null,
    error: null,
    loading: true,
  });
  const [tick, setTick] = useState(0);
  const silentRef = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    const silent = silentRef.current;
    silentRef.current = false;
    if (!silent) {
      // queued as a microtask so the effect body itself stays side-effect-lean
      Promise.resolve().then(() => {
        if (!controller.signal.aborted)
          setState((s) =>
            s.loading && s.error === null ? s : { ...s, loading: true, error: null }
          );
      });
    }
    fn(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted)
          setState({ data, error: null, loading: false });
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        if (error instanceof DOMException && error.name === "AbortError") return;
        setState((s) => ({ data: s.data, error, loading: false }));
      });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  const refresh = useCallback((opts?: { silent?: boolean }) => {
    silentRef.current = Boolean(opts?.silent);
    setTick((t) => t + 1);
  }, []);

  return { ...state, refresh };
}

/** prefers-reduced-motion, SSR-safe (defaults to reduced until known). */
export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(true);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);
  return reduced;
}

/** Interval that pauses when the tab is hidden. `null` delay disables. */
export function usePolling(callback: () => void, delayMs: number | null) {
  // latest-callback ref, synced in its own effect (runs before the interval
  // effect on every commit) — never touched during render
  const savedRef = useRef(callback);
  useEffect(() => {
    savedRef.current = callback;
  }, [callback]);
  useEffect(() => {
    if (delayMs === null) return;
    let id: ReturnType<typeof setInterval> | null = null;
    const start = () => {
      if (id === null) id = setInterval(() => savedRef.current(), delayMs);
    };
    const stop = () => {
      if (id !== null) {
        clearInterval(id);
        id = null;
      }
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") {
        savedRef.current(); // catch up immediately on return
        start();
      } else {
        stop();
      }
    };
    start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [delayMs]);
}
