"use client";

/** Light / dark / system theming.
 *
 * The stylesheet does the real work: every color is a role var redefined
 * under `[data-theme="dark"]`, and `system` resolves through a
 * `prefers-color-scheme` media query. So this module only has to own the
 * *choice* — write `data-theme` on <html>, persist it, and render a control.
 *
 * There is no `.dark` class and no duplicated Tailwind variants anywhere in
 * the app; switching a single attribute re-resolves the whole tree. */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useSyncExternalStore,
} from "react";
import { Monitor, Moon, Sun } from "lucide-react";
import { cn } from "@/lib/utils";

export const THEME_STORAGE_KEY = "adcoherent.theme";

export type ThemeChoice = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

/** Runs before first paint, inlined into <head>. Without it the document
 * renders in the default (dark) palette for one frame and then snaps —
 * the white flash every themed app is judged on. Kept dependency-free and
 * failure-tolerant: a blocked localStorage must not stop the page. */
export const themeInitScript = `(function(){try{
var c=localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)});
if(c!=="light"&&c!=="dark"&&c!=="system")c="system";
document.documentElement.setAttribute("data-theme",c);
}catch(e){document.documentElement.setAttribute("data-theme","system");}})();`;

interface ThemeContextValue {
  /** What the user picked — may be "system". */
  choice: ThemeChoice;
  /** What that currently renders as. Follows the OS while choice is "system". */
  resolved: ResolvedTheme;
  setChoice: (next: ThemeChoice) => void;
  /** Light ⇄ dark. From "system", flips away from whatever is on screen. */
  toggle: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used inside <ThemeProvider>");
  return ctx;
}

/* The <html data-theme> attribute is the source of truth, not React state.
 * The pre-paint script writes it, `setChoice` writes it, and the stylesheet
 * reads it — so subscribing to it keeps React a follower of the DOM rather
 * than a second, racing owner of the same value. */

const THEME_EVENT = "adcoherent:theme";

function subscribeChoice(onChange: () => void): () => void {
  // Same tab: setChoice dispatches. Other tabs: the storage event.
  window.addEventListener(THEME_EVENT, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(THEME_EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

function readChoice(): ThemeChoice {
  const v = document.documentElement.getAttribute("data-theme");
  return v === "light" || v === "dark" || v === "system" ? v : "system";
}

/* Server and first client render must agree. Both say "system", and the
 * subscription corrects it without a repaint — the attribute was already
 * right before React ever ran. */
const serverChoice = (): ThemeChoice => "system";

const DARK_QUERY = "(prefers-color-scheme: dark)";

function subscribeSystem(onChange: () => void): () => void {
  const mq = window.matchMedia(DARK_QUERY);
  mq.addEventListener("change", onChange);
  return () => mq.removeEventListener("change", onChange);
}

const readSystemDark = () => window.matchMedia(DARK_QUERY).matches;
const serverSystemDark = () => false;

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const choice = useSyncExternalStore(subscribeChoice, readChoice, serverChoice);
  const systemDark = useSyncExternalStore(
    subscribeSystem,
    readSystemDark,
    serverSystemDark
  );

  useEffect(() => {
    // Opting into the cross-theme transition only after mount keeps the
    // first paint instant instead of fading in from the wrong palette.
    const raf = requestAnimationFrame(() =>
      document.documentElement.setAttribute("data-theme-ready", "")
    );
    return () => cancelAnimationFrame(raf);
  }, []);

  // Another tab may have written a different preference while this one was
  // in the background; the storage event fires but only updates that tab's
  // localStorage, so the attribute has to be re-synced here.
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key !== THEME_STORAGE_KEY) return;
      const v = e.newValue;
      if (v === "light" || v === "dark" || v === "system") {
        document.documentElement.setAttribute("data-theme", v);
      }
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const setChoice = useCallback((next: ThemeChoice) => {
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      /* storage unavailable — the choice still applies for this session */
    }
    window.dispatchEvent(new Event(THEME_EVENT));
  }, []);

  const resolved: ResolvedTheme =
    choice === "system" ? (systemDark ? "dark" : "light") : choice;

  // Reads the live DOM/OS state rather than closing over `resolved`, so two
  // clicks inside one frame still flip twice instead of computing the same
  // answer from a render that has not happened yet.
  const toggle = useCallback(() => {
    const current = readChoice();
    const showing: ResolvedTheme =
      current === "system" ? (readSystemDark() ? "dark" : "light") : current;
    setChoice(showing === "dark" ? "light" : "dark");
  }, [setChoice]);

  return (
    <ThemeContext.Provider value={{ choice, resolved, setChoice, toggle }}>
      {children}
    </ThemeContext.Provider>
  );
}

// ─────────────────────────────────────────────────────────────── controls

/** False during SSR and the hydrating render, true afterwards. Used to hold
 * back output that legitimately cannot match the server — here, an icon that
 * depends on the OS color preference. */
const noopSubscribe = () => () => {};
function useHydrated(): boolean {
  return useSyncExternalStore(
    noopSubscribe,
    () => true,
    () => false
  );
}

const OPTIONS: { value: ThemeChoice; label: string; Icon: typeof Sun }[] = [
  { value: "light", label: "Light", Icon: Sun },
  { value: "dark", label: "Dark", Icon: Moon },
  { value: "system", label: "System", Icon: Monitor },
];

/** Three-way segmented control. All three states are visible at once, so
 * "system" is discoverable instead of hidden behind a third click. */
export function ThemeSwitch({ className }: { className?: string }) {
  const { choice, setChoice } = useTheme();
  return (
    <div
      role="radiogroup"
      aria-label="Color theme"
      className={cn(
        "inline-flex items-center gap-0.5 rounded-full border border-line bg-sunken p-0.5",
        className
      )}
    >
      {OPTIONS.map(({ value, label, Icon }) => {
        const active = choice === value;
        return (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={`${label} theme`}
            title={`${label} theme`}
            onClick={() => setChoice(value)}
            className={cn(
              "flex size-9 cursor-pointer items-center justify-center rounded-full transition-colors duration-200 [@media(pointer:fine)]:size-7",
              active
                ? "bg-brand text-brand-on shadow-(--shadow-brand)"
                : "text-subtle hover:bg-tint-2 hover:text-strong"
            )}
          >
            <Icon className="size-3.5" aria-hidden />
          </button>
        );
      })}
    </div>
  );
}

/** Single-button light⇄dark flip, for tight spots (nav bars, mobile header).
 * Meets the 44px touch target through padding while the icon stays 18px. */
export function ThemeToggle({ className }: { className?: string }) {
  const { resolved, toggle } = useTheme();
  const mounted = useHydrated();

  // Before mount the resolved theme is not knowable, so render the frame
  // without an icon rather than guessing and swapping it a frame later.
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={
        mounted ? `Switch to ${resolved === "dark" ? "light" : "dark"} theme` : "Switch theme"
      }
      title={mounted ? `Switch to ${resolved === "dark" ? "light" : "dark"} theme` : undefined}
      className={cn(
        // 44px by default, tightened only where a precise pointer is
        // actually present. Keying this off viewport width instead would
        // shrink the target on every large touchscreen.
        "inline-flex size-11 cursor-pointer items-center justify-center rounded-full text-muted transition-colors duration-200 hover:bg-tint-2 hover:text-strong [@media(pointer:fine)]:size-9",
        className
      )}
    >
      {mounted &&
        (resolved === "dark" ? (
          <Sun className="size-[18px]" aria-hidden />
        ) : (
          <Moon className="size-[18px]" aria-hidden />
        ))}
    </button>
  );
}
