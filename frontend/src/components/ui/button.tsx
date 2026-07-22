"use client";

import Link from "next/link";
import { forwardRef } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "dark";
type Size = "sm" | "md" | "lg";

const VARIANTS: Record<Variant, string> = {
  // polished platinum on dark metal — the brand CTA
  primary:
    "text-coal-950 bg-[linear-gradient(180deg,#ffffff_0%,#dfe4e9_55%,#c3cad2_100%)] shadow-[inset_0_1px_0_rgb(255_255_255/0.9),inset_0_-1px_0_rgb(0_0_0/0.12),0_8px_24px_-10px_rgb(0_0_0/0.6)] hover:brightness-110 active:scale-[0.98]",
  secondary:
    "border border-line bg-coal-800 text-ink-850 hover:bg-coal-700 hover:border-white/20",
  ghost: "text-ink-700 hover:bg-white/8",
  danger: "bg-red-600 text-white hover:bg-red-500 active:bg-red-700",
  dark: "border border-white/15 bg-white/5 text-ink-900 hover:bg-white/10",
};

const SIZES: Record<Size, string> = {
  sm: "h-8 px-3 text-[13px] gap-1.5",
  md: "h-10 px-4.5 text-sm gap-2",
  lg: "h-12 px-6 text-[15px] gap-2",
};

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  href?: string;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  function Button(
    { className, variant = "primary", size = "md", loading, href, children, disabled, ...props },
    ref
  ) {
    const classes = cn(
      "inline-flex cursor-pointer select-none items-center justify-center rounded-full font-semibold transition-[background-color,border-color,filter,transform] duration-200 disabled:cursor-not-allowed disabled:opacity-50",
      VARIANTS[variant],
      SIZES[size],
      className
    );
    if (href && !disabled) {
      return (
        <Link href={href} className={classes}>
          {children}
        </Link>
      );
    }
    return (
      <button
        ref={ref}
        className={classes}
        disabled={disabled || loading}
        {...props}
      >
        {loading && <Loader2 className="size-4 animate-spin" aria-hidden />}
        {children}
      </button>
    );
  }
);
