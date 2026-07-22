"use client";

import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
} from "react";
import { CheckCircle2, Info, X, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";

interface Toast {
  id: number;
  kind: "success" | "error" | "info";
  title: string;
  detail?: string;
}

interface ToastContextValue {
  toast: (t: Omit<Toast, "id">) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}

const ICONS = {
  success: <CheckCircle2 className="size-4.5 text-emerald-300" aria-hidden />,
  error: <XCircle className="size-4.5 text-red-300" aria-hidden />,
  info: <Info className="size-4.5 text-ink-600" aria-hidden />,
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => {
    setToasts((list) => list.filter((t) => t.id !== id));
  }, []);

  const toast = useCallback(
    (t: Omit<Toast, "id">) => {
      const id = nextId.current++;
      setToasts((list) => [...list.slice(-3), { ...t, id }]);
      window.setTimeout(() => dismiss(id), t.kind === "error" ? 8000 : 5000);
    },
    [dismiss]
  );

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div
        aria-live="polite"
        aria-label="Notifications"
        className="pointer-events-none fixed right-4 bottom-4 z-[70] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            role="status"
            className={cn(
              "pointer-events-auto flex items-start gap-3 rounded-xl border bg-coal-800 p-3.5 shadow-(--shadow-float) animate-fade-up",
              t.kind === "error" ? "border-red-400/25" : "border-line"
            )}
          >
            {ICONS[t.kind]}
            <div className="min-w-0 flex-1">
              <p className="text-[13px] font-bold text-ink-900">{t.title}</p>
              {t.detail && (
                <p className="mt-0.5 text-[12px] leading-relaxed text-ink-500">
                  {t.detail}
                </p>
              )}
            </div>
            <button
              onClick={() => dismiss(t.id)}
              aria-label="Dismiss notification"
              className="rounded-md p-1 text-ink-500 hover:bg-white/8 hover:text-ink-800"
            >
              <X className="size-3.5" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
