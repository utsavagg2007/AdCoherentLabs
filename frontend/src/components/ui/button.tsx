"use client";

import Link from "next/link";
import { forwardRef } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "dark";
type Size = "sm" | "md" | "lg";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-violet-600 text-white hover:bg-violet-500 active:bg-violet-700 shadow-[0_1px_2px_rgb(76_29_149/0.3)]",
  secondary:
    "border border-line bg-white text-ink-800 hover:bg-cream hover:border-zinc-300",
  ghost: "text-ink-700 hover:bg-zinc-100",
  danger: "bg-red-600 text-white hover:bg-red-500 active:bg-red-700",
  dark: "border border-white/15 bg-white/5 text-white hover:bg-white/10",
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
      "inline-flex select-none items-center justify-center rounded-full font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50",
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
