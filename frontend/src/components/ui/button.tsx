"use client";

import Link from "next/link";
import { forwardRef } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "dark";
type Size = "sm" | "md" | "lg";

const VARIANTS: Record<Variant, string> = {
  // The brand CTA. A violet→indigo gradient reads as one confident object in
  // both themes, unlike the old platinum fill which vanished on light.
  primary:
    "text-brand-on bg-[linear-gradient(135deg,var(--cta-1)_0%,var(--cta-2)_52%,var(--cta-3)_100%)] shadow-(--shadow-brand) hover:brightness-110 active:scale-[0.98]",
  secondary:
    "border border-line bg-surface text-body shadow-(--shadow-soft) hover:bg-hover hover:border-line-strong",
  ghost: "text-muted hover:bg-tint-2 hover:text-strong",
  // Destructive stays outside the brand spectrum on purpose.
  danger:
    "bg-danger text-danger-on hover:bg-danger-hover active:brightness-95",
  dark: "border border-line-strong bg-tint text-strong hover:bg-tint-2",
};

const SIZES: Record<Size, string> = {
  // md/lg clear the 44px touch target on coarse pointers; sm is reserved for
  // dense desktop rows (tables, cards) where a pointer is already assumed.
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
