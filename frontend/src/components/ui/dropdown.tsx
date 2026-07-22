"use client";

import * as DropdownPrimitive from "@radix-ui/react-dropdown-menu";
import { cn } from "@/lib/utils";

export const Dropdown = DropdownPrimitive.Root;
export const DropdownTrigger = DropdownPrimitive.Trigger;

export function DropdownContent({
  className,
  children,
  align = "start",
  sideOffset = 6,
}: {
  className?: string;
  children: React.ReactNode;
  align?: "start" | "center" | "end";
  sideOffset?: number;
}) {
  return (
    <DropdownPrimitive.Portal>
      <DropdownPrimitive.Content
        align={align}
        sideOffset={sideOffset}
        className={cn(
          "z-50 min-w-[220px] rounded-xl border border-line bg-coal-800 p-1.5 shadow-(--shadow-float) data-[state=open]:animate-fade-in",
          className
        )}
      >
        {children}
      </DropdownPrimitive.Content>
    </DropdownPrimitive.Portal>
  );
}

export function DropdownItem({
  className,
  children,
  onSelect,
  disabled,
}: {
  className?: string;
  children: React.ReactNode;
  onSelect?: () => void;
  disabled?: boolean;
}) {
  return (
    <DropdownPrimitive.Item
      disabled={disabled}
      onSelect={onSelect}
      className={cn(
        "flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-sm text-ink-800 outline-none select-none data-[disabled]:cursor-not-allowed data-[disabled]:opacity-50 data-[highlighted]:bg-white/6 data-[highlighted]:text-ink-950",
        className
      )}
    >
      {children}
    </DropdownPrimitive.Item>
  );
}

export function DropdownSeparator() {
  return <DropdownPrimitive.Separator className="my-1 h-px bg-line" />;
}

export function DropdownLabel({ children }: { children: React.ReactNode }) {
  return (
    <DropdownPrimitive.Label className="px-2.5 pt-1.5 pb-1 text-[11px] font-bold tracking-wider text-ink-500 uppercase">
      {children}
    </DropdownPrimitive.Label>
  );
}
